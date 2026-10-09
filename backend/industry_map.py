"""行业映射双层缓存（组合风险视图 Task 2）。

I4 `get_industry_map()` / I5 `refresh_industry_map()`。

读序（spec r3.2 观察 4）：进程缓存（TTL 86400s）→ DB 全量（**最旧行** updated_at 距今 ≤24h
→fresh，即整表都在最近一轮完整刷新内；任一行超窗即 stale）→ 表空→({}, 'empty')。读路径
**绝不内联全市场拉取**：全市场拉取只发生在后台 APScheduler job 与显式 `refresh_industry_map()`；
首启由启动后延迟预热填充，前端见 empty 出"预热中"文案（Task 8）。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from backend import storage
from backend.storage import IndustryMap

logger = logging.getLogger("atlas.industry")

# 进程缓存 TTL（秒）与"DB 数据新鲜"窗口：均 24h。DB 新鲜以**最旧行** updated_at 计（见 get_industry_map）
_PROCESS_TTL = 86400.0
_FRESH_WINDOW = 86400.0
# 分页拉取：每页 size、页间最小间隔（≤3 req/s）、最大页数护栏。
# 2026-10-03 降速：原先 0.11s（≈9 req/s）× 最多 100 页是把本机 IP 打进东财 push2 惩罚窗的
# 主要嫌疑（惩罚窗内所有 push2 调用 RemoteDisconnected）。后台预热不赶时间——宁慢勿封。
_PAGE_SIZE = 200
_MIN_INTERVAL = 0.4
_MAX_PAGES = 100
# 单页连接级错误的有界重试次数（主站/镜像各自）：抵御偶发 RemoteDisconnected，
# 避免一次抖动让整轮刷新作废、行业映射陈旧到下一个 24h 周期
_PAGE_RETRIES = 2

# 进程缓存：(填充时刻 time.monotonic, code→行业 映射)；None 表示无缓存
_cache: tuple[float, dict[str, str]] | None = None

# 最近一轮 refresh 是否完整跑完（None=本进程内尚未跑过）：后台 job 据此决定是否提前重排
_last_refresh_complete: bool | None = None

# 连接级故障的异常类名（按 MRO 判定；避免为此 import requests）：
# requests.ConnectionError / requests.Timeout / urllib3 ProtocolError / http.client.RemoteDisconnected
_CONNECTION_ERROR_NAMES = frozenset({"ConnectionError", "Timeout", "RemoteDisconnected", "ProtocolError"})


def _is_connection_error(exc: BaseException) -> bool:
    return any(cls.__name__ in _CONNECTION_ERROR_NAMES for cls in type(exc).__mro__)


def last_refresh_complete() -> bool | None:
    """最近一轮 refresh 是否完整跑完（None=进程内尚未跑过）。"""
    return _last_refresh_complete


# 真东财适配器惰性单例（避免每页重复构造日历/归一器）
_source: Any | None = None


def reset_process_cache() -> None:
    """清空进程缓存（预热/刷新失败回退、测试隔离）。"""
    global _cache
    _cache = None


def _get_source() -> Any:
    global _source
    if _source is None:
        from backend.sources.eastmoney import EastMoneySource  # 惰性导入，避免模块加载期网络

        _source = EastMoneySource()
    return _source


def _default_fetch_page(page: int, size: int) -> tuple[list[dict[str, Any]], int]:
    """默认取页：真东财 clist 全市场分页，复用既有请求构造（连接级错误退避重试）。"""
    return _get_source()._clist_page(page, size, retries=_PAGE_RETRIES)


def industry_health() -> dict[str, Any]:
    """health 观测面：行业映射行数/最旧行时龄/三态。

    只做聚合查询（不拉全表映射、绝不触发网络）；查询失败如实返回 unavailable（不造假）。
    """
    try:
        with storage.SessionLocal() as session:
            rows, oldest = session.execute(select(func.count(), func.min(IndustryMap.updated_at))).one()
    except Exception:
        logger.warning("行业映射 health 查询失败", exc_info=True)
        return {"status": "unavailable", "rows": 0, "oldestAgeSeconds": None}
    if not rows:
        return {"status": "empty", "rows": 0, "oldestAgeSeconds": None}
    age_seconds = (datetime.now(UTC) - oldest).total_seconds()
    return {
        "status": "fresh" if age_seconds <= _FRESH_WINDOW else "stale",
        "rows": int(rows),
        "oldestAgeSeconds": int(max(age_seconds, 0)),
    }


def get_industry_map() -> tuple[dict[str, str], str]:
    """返回 (code→行业 映射, status)，status ∈ 'fresh'|'stale'|'empty'。绝不触发全市场拉取。

    fresh 判定以**整表最旧行**的 updated_at 为基准（min）：仅当全表都在最近一轮完整刷新内
    （最旧一行距今 ≤24h）才算 fresh；任意一行超窗即整表标 stale，使部分页刷新失败如实显为
    过期（评审 I-1）。stale/empty 仍返回当前 DB 全量映射（部分陈旧不丢数据）。空表 → ({}, 'empty')。
    """
    global _cache
    cached = _cache
    if cached is not None and (time.monotonic() - cached[0]) <= _PROCESS_TTL:
        return dict(cached[1]), "fresh"

    with storage.SessionLocal() as session:
        rows = session.scalars(select(IndustryMap)).all()
    if not rows:
        return {}, "empty"

    mapping = {row.code: row.name for row in rows}
    oldest = min(row.updated_at for row in rows)
    age_seconds = (datetime.now(UTC) - oldest).total_seconds()
    if age_seconds <= _FRESH_WINDOW:
        # 仅当整表**最旧**一行仍在 24h 窗口内（= 全表都在最近一轮完整刷新内）才算 fresh。
        # 仅 fresh 回写进程缓存；stale 不回写，避免下一读被误判为 fresh
        _cache = (time.monotonic(), dict(mapping))
        return mapping, "fresh"
    # 任意一行超出 TTL → 整表 stale。评审 I-1：不能用 max(updated_at)，否则上游从第 N 页起
    # 持续失败时（反爬/解析错），每轮只有前段行被刷新、后段行无限变陈，而"最新行仍新"会把
    # 全表冒充 fresh，穿透"过期数据必须展现为过期"红线。改用 min 使部分刷新失败如实显为过期。
    # 注：退市/上游不再返回的 code 形成"幽灵行"，其 updated_at 永久停滞会长期拖住 min → 整表
    # 长期 stale，属**有意的保守过度披露**——宁可多报过期，也绝不让陈旧子集冒充新鲜数据。
    return mapping, "stale"


def _upsert_page(items: dict[str, str]) -> int:
    """单页 upsert（存在则更新 name/updated_at），独立事务提交→部分失败保留已写行。"""
    if not items:
        return 0
    now = datetime.now(UTC)
    with storage.SessionLocal.begin() as session:
        existing = session.scalars(select(IndustryMap).where(IndustryMap.code.in_(list(items)))).all()
        by_code = {row.code: row for row in existing}
        for code, name in items.items():
            obj = by_code.get(code)
            if obj is None:
                session.add(IndustryMap(code=code, name=name, updated_at=now))
            else:
                obj.name = name
                obj.updated_at = now
    return len(items)


def refresh_industry_map(
    fetch_page: Callable[[int, int], tuple[list[dict[str, Any]], int]] | None = None,
) -> int:
    """分页拉全市场→逐页 upsert→成功完成后写穿进程缓存；返回累计 upsert 行数。

    fetch_page(page, size) → (归一 rows, total)；None 用真东财。任一页抛错即中断，保留
    已 upsert 行（每页独立提交）并返回已累计计数；不完整结果不写进程缓存。
    """
    global _cache, _last_refresh_complete
    page_fn = fetch_page or _default_fetch_page
    upserted = 0
    seen = 0  # 已消费的上游行数（含被跳过的空行业行），用于按 total 判终止
    collected: dict[str, str] = {}
    page = 1
    completed = False
    while page <= _MAX_PAGES:
        try:
            rows, total = page_fn(page, _PAGE_SIZE)
        except Exception as exc:
            if _is_connection_error(exc):
                # 连接级抖动是可降级的已知故障：一行说清（页码/已保留行数/上游异常），
                # 不打 urllib3 内部长栈；非预期异常才保留完整 traceback。
                logger.warning("行业映射刷新第 %d 页上游连接失败（已保留 %d 行）: %s", page, upserted, exc)
            else:
                logger.warning("行业映射刷新第 %d 页失败，保留已写入 %d 行", page, upserted, exc_info=True)
            break
        fetched = len(rows)
        seen += fetched
        page_map: dict[str, str] = {}
        for row in rows:
            code = str(row.get("code") or "").strip()
            industry = str(row.get("industry") or "").strip()
            if not code or not industry or industry == "-":
                continue  # 空/缺/占位'-' 行业不落库；消费侧统一走"未知"桶
            page_map[code] = industry
        upserted += _upsert_page(page_map)
        collected.update(page_map)

        if fetched == 0:
            completed = True  # 拉到空页：已无更多数据
            break
        if total and seen >= total:
            completed = True
            break
        if not total and fetched < _PAGE_SIZE:
            completed = True  # 无 total 时的短页兜底：视为末页
            break
        page += 1
        time.sleep(_MIN_INTERVAL)  # ≤10 req/s

    if completed and collected:
        _cache = (time.monotonic(), dict(collected))
    _last_refresh_complete = completed
    return upserted
