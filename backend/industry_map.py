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

from sqlalchemy import select

from backend import storage
from backend.storage import IndustryMap

logger = logging.getLogger("atlas.industry")

# 进程缓存 TTL（秒）与"DB 数据新鲜"窗口：均 24h。DB 新鲜以**最旧行** updated_at 计（见 get_industry_map）
_PROCESS_TTL = 86400.0
_FRESH_WINDOW = 86400.0
# 分页拉取：每页 size、页间最小间隔（≤10 req/s）、最大页数护栏
_PAGE_SIZE = 200
_MIN_INTERVAL = 0.11
_MAX_PAGES = 100

# 进程缓存：(填充时刻 time.monotonic, code→行业 映射)；None 表示无缓存
_cache: tuple[float, dict[str, str]] | None = None

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
    """默认取页：真东财 clist 全市场分页，复用既有请求构造。"""
    return _get_source()._clist_page(page, size)


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
    global _cache
    page_fn = fetch_page or _default_fetch_page
    upserted = 0
    seen = 0  # 已消费的上游行数（含被跳过的空行业行），用于按 total 判终止
    collected: dict[str, str] = {}
    page = 1
    completed = False
    while page <= _MAX_PAGES:
        try:
            rows, total = page_fn(page, _PAGE_SIZE)
        except Exception:
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
    return upserted
