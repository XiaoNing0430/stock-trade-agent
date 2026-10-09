"""组合风险视图 Task 2：行业映射双层缓存（进程 TTL + DB 持久化）。

离线：注入 fake fetch_page，全市场拉取路径绝不触达真东财；DB 走真实 PostgreSQL
（与 tests/test_portfolio_api.py 最接近的存储测试样板一致），tmp_db 前后清空
industry_map 表 + 重置进程缓存，保证用例互不污染。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from backend import industry_map as im
from backend import storage as storage_module
from backend.industry_map import get_industry_map, refresh_industry_map
from backend.storage import IndustryMap


class TmpDb:
    """industry_map 表测试夹具：读快照 / 清空 / 批量回填 updated_at。"""

    def clear(self) -> None:
        from sqlalchemy import delete

        with storage_module.SessionLocal.begin() as session:
            session.execute(delete(IndustryMap))

    def snapshot(self) -> dict[str, str]:
        from sqlalchemy import select

        with storage_module.SessionLocal() as session:
            rows = session.scalars(select(IndustryMap)).all()
            return {row.code: row.name for row in rows}

    def age_back(self, hours: int) -> None:
        """把全表 updated_at 挪到 hours 小时前（模拟陈旧数据）。"""
        from sqlalchemy import update

        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        with storage_module.SessionLocal.begin() as session:
            session.execute(update(IndustryMap).values(updated_at=cutoff))

    def age_code(self, code: str, hours: int) -> None:
        """把单个 code 的 updated_at 挪到 hours 小时前（模拟该行未被最近一轮刷新）。

        评审 I-1：混合时间戳是暴露 max/min 语义差异的关键——上游自第 N 页起失败时，
        只有前段行被刷新、后段行无限变陈，全表并非同旧。
        """
        from sqlalchemy import update

        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        with storage_module.SessionLocal.begin() as session:
            session.execute(update(IndustryMap).values(updated_at=cutoff).where(IndustryMap.code == code))


@pytest.fixture()
def tmp_db() -> Any:
    storage_module.initialize_storage()
    im.reset_process_cache()
    TmpDb().clear()
    yield TmpDb()
    im.reset_process_cache()
    TmpDb().clear()


def test_get_industry_map_three_states(tmp_db: TmpDb) -> None:
    # fresh：刷新写穿进程缓存；清库后仍能读到 → 证明来自进程缓存而非 DB
    calls = {"n": 0}

    def fake_page(page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        calls["n"] += 1
        return ([{"code": "600519", "industry": "白酒"}, {"code": "000001", "industry": "银行"}], 2)

    assert refresh_industry_map(fetch_page=fake_page) == 2
    assert calls["n"] == 1

    tmp_db.clear()  # 掏空 DB，若读路径走 DB 会得 empty；仍返回两行 = 进程缓存命中
    m, st = get_industry_map()
    assert m["600519"] == "白酒" and st == "fresh"
    assert calls["n"] == 1  # get_industry_map 未触发任何 upstream 拉取


def test_stale_tolerance(tmp_db: TmpDb) -> None:
    # DB 有行、进程缓存空（模拟重启/过期）→ updated_at 超 24h → status=stale
    def ok_page(page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        return ([{"code": "600519", "industry": "白酒"}], 1)

    assert refresh_industry_map(fetch_page=ok_page) == 1
    tmp_db.age_back(hours=30)  # 挪到 30h 前
    im.reset_process_cache()  # 进程缓存清零，强制走 DB 读

    m, st = get_industry_map()
    assert st == "stale"
    assert m == {"600519": "白酒"}


def test_mixed_timestamps_status_stale(tmp_db: TmpDb) -> None:
    # 评审 I-1：混合时间戳——上游自第 N 页起失败时前段行被刷新、后段行无限变陈。
    # 语义为"仅当整表都在最近一轮完整刷新内才算 fresh"，故任意一行 >24h 即整表 stale，
    # 绝不允许"有任一行新"冒充全表新鲜（穿透"过期数据必须展现为过期"红线）。
    def page1(page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        if page == 1:
            return ([{"code": "600519", "industry": "白酒"}, {"code": "000001", "industry": "银行"}], 2)
        return ([], 2)  # 第二页空即终止

    assert refresh_industry_map(fetch_page=page1) == 2
    im.reset_process_cache()  # 掏空进程缓存，强制走 DB 判定

    # 先证 min 语义不会把"全表都在窗口内"误判为 stale
    tmp_db.age_code("600519", hours=1)
    tmp_db.age_code("000001", hours=2)
    m, st = get_industry_map()
    assert st == "fresh" and m == {"600519": "白酒", "000001": "银行"}
    im.reset_process_cache()  # fresh 读会回写进程缓存，需清掉再验混合态

    # 一行仍新（1h）、一行落后期（30h）→ 整表 stale，但 map 仍返回全行（部分陈旧不丢数据）
    tmp_db.age_code("000001", hours=30)
    m, st = get_industry_map()
    assert st == "stale"
    assert m == {"600519": "白酒", "000001": "银行"}


def test_empty(tmp_db: TmpDb, monkeypatch: pytest.MonkeyPatch) -> None:
    # 表空且进程无缓存 → ({}, 'empty')，绝不内联全市场拉取
    tmp_db.clear()
    im.reset_process_cache()

    def boom(page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        raise AssertionError("get_industry_map 读路径不得触发全市场拉取")

    monkeypatch.setattr(im, "_default_fetch_page", boom)
    m, st = get_industry_map()
    assert m == {} and st == "empty"


def test_refresh_partial_page_keeps_rows(tmp_db: TmpDb) -> None:
    # 拉取中途失败 → 已 upsert 行保留（每页独立提交），返回已累计计数，不整体回滚
    def flaky(page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        if page == 1:
            return ([{"code": "600519", "industry": "白酒"}, {"code": "000001", "industry": "银行"}], 4)
        raise ConnectionError("网络中断")

    assert refresh_industry_map(fetch_page=flaky) == 2
    assert tmp_db.snapshot() == {"600519": "白酒", "000001": "银行"}

    # 部分失败不污染进程缓存：清缓存后从 DB 读到前两行
    im.reset_process_cache()
    m, st = get_industry_map()
    assert st == "fresh" and m == {"600519": "白酒", "000001": "银行"}


def test_clist_page_falls_back_to_delay_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    """主站网络重置/502 → 行业分页走 push2delay 镜像（f100 同源，行业无价格鲜度要求）。"""
    import requests as req
    from backend.sources.eastmoney import EastMoneySource

    src = EastMoneySource()
    calls: list[str] = []

    def fake(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(url)
        if url == src.CLIST_URL:
            raise req.exceptions.ConnectionError("push2 reset by peer")
        return {"data": {"total": 1, "diff": [{"f12": "600519", "f14": "贵州茅台", "f100": "白酒"}]}}

    monkeypatch.setattr(src, "_http_get", fake)
    rows, total = src._clist_page(1, 200)
    assert calls == [src.CLIST_URL, src.CLIST_MIRROR_URL]
    assert total == 1 and rows[0]["industry"] == "白酒"


def test_clist_page_primary_success_never_touches_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.sources.eastmoney import EastMoneySource

    src = EastMoneySource()
    calls: list[str] = []

    def fake(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(url)
        return {"data": {"total": 1, "diff": [{"f12": "600519", "f14": "贵州茅台", "f100": "白酒"}]}}

    monkeypatch.setattr(src, "_http_get", fake)
    src._clist_page(1, 200)
    assert calls == [src.CLIST_URL]


def test_screener_paged_does_not_silently_degrade_to_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    """选股器路径（load_screener_paged）保持主站失败如实上抛——绝不静默返回延时价格。"""
    import requests as req
    from backend.sources.eastmoney import EastMoneySource

    src = EastMoneySource()

    def fake(url: str, params: dict[str, Any]) -> dict[str, Any]:
        raise req.exceptions.HTTPError("502 Bad Gateway")

    monkeypatch.setattr(src, "_http_get", fake)
    with pytest.raises(req.exceptions.HTTPError):
        src.load_screener_paged(page=1, page_size=5, sort_by="changePct", sort_dir="desc")


# ---------- 韧性硬化（2026-10-03）：连接级有界重试 / 日志降噪 / 完成标记 / health 观测面 ----------


def _clist_ok(_url: str, _params: dict[str, Any]) -> dict[str, Any]:
    return {"data": {"total": 1, "diff": [{"f12": "600519", "f14": "贵州茅台", "f100": "白酒"}]}}


def test_clist_page_retries_connection_error_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """行业路径连接被重置 → 同 URL 退避重试（默认 0 次重试保持 API 行为不变）。"""
    import requests as req
    from backend.sources import eastmoney as em
    from backend.sources.eastmoney import EastMoneySource

    src = EastMoneySource()
    calls: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr(em.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(url)
        if len(calls) == 1:
            raise req.exceptions.ConnectionError("Remote end closed connection")
        return _clist_ok(url, params)

    monkeypatch.setattr(src, "_http_get", fake)
    rows, total = src._clist_page(1, 200, retries=2)

    assert calls == [src.CLIST_URL, src.CLIST_URL]  # 主站第二次即成功，未触达镜像
    assert sleeps == [0.5]  # 只退避一次
    assert rows and total == 1


def test_clist_page_retries_exhausted_falls_back_to_mirror_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主站+镜像各重试到上限后仍失败 → 如实上抛（调用方记日志并保留已写入行）。"""
    import requests as req
    from backend.sources import eastmoney as em
    from backend.sources.eastmoney import EastMoneySource

    src = EastMoneySource()
    calls: list[str] = []
    monkeypatch.setattr(em.time, "sleep", lambda _seconds: None)

    def fake(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(url)
        raise req.exceptions.ConnectionError("reset")

    monkeypatch.setattr(src, "_http_get", fake)
    with pytest.raises(req.exceptions.ConnectionError):
        src._clist_page(1, 200, retries=2)

    assert calls.count(src.CLIST_URL) == 3  # 1 次 + 2 次重试
    assert calls.count(src.CLIST_MIRROR_URL) == 3
    assert calls[0] == src.CLIST_URL and calls[-1] == src.CLIST_MIRROR_URL


def test_clist_page_zero_retries_keeps_api_latency(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认 retries=0：主站连接失败立刻换镜像、绝不 sleep（选股器 API 路径延迟不变）。"""
    import requests as req
    from backend.sources import eastmoney as em
    from backend.sources.eastmoney import EastMoneySource

    src = EastMoneySource()
    calls: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr(em.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(url)
        if url == src.CLIST_URL:
            raise req.exceptions.ConnectionError("reset")
        return _clist_ok(url, params)

    monkeypatch.setattr(src, "_http_get", fake)
    rows, _total = src._clist_page(1, 200)

    assert calls == [src.CLIST_URL, src.CLIST_MIRROR_URL]
    assert sleeps == []
    assert rows


def test_clist_page_http_error_skips_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 错误（4xx/5xx）不是瞬时故障：不重试、不 sleep，直接换镜像。"""
    import requests as req
    from backend.sources import eastmoney as em
    from backend.sources.eastmoney import EastMoneySource

    src = EastMoneySource()
    calls: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr(em.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake(url: str, params: dict[str, Any]) -> dict[str, Any]:
        calls.append(url)
        if url == src.CLIST_URL:
            raise req.exceptions.HTTPError("403 Forbidden")
        return _clist_ok(url, params)

    monkeypatch.setattr(src, "_http_get", fake)
    src._clist_page(1, 200, retries=2)

    assert calls == [src.CLIST_URL, src.CLIST_MIRROR_URL]
    assert sleeps == []


def test_refresh_marks_completion_flag(tmp_db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """完成标记：整轮跑完=True；中途失败=False（供后台 job 决定是否提前重排）。"""
    monkeypatch.setattr(im, "_last_refresh_complete", None)  # 进程级状态：显式归零，免用例顺序依赖
    assert im.last_refresh_complete() is None

    def ok(page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        return ([{"code": "600519", "industry": "白酒"}], 1)

    refresh_industry_map(fetch_page=ok)
    assert im.last_refresh_complete() is True

    def flaky(page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        raise ConnectionError("reset")

    refresh_industry_map(fetch_page=flaky)
    assert im.last_refresh_complete() is False


def test_refresh_connection_error_logs_without_traceback(tmp_db: Any, caplog: Any) -> None:
    """连接级失败是可降级的已知故障：一行 warning，不刷 urllib3 内部栈。"""
    import logging

    def flaky(page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        raise ConnectionError("Remote end closed connection without response")

    with caplog.at_level(logging.WARNING, logger="atlas.industry"):
        refresh_industry_map(fetch_page=flaky)

    records = [r for r in caplog.records if r.name == "atlas.industry"]
    assert len(records) == 1
    assert records[0].exc_info is None  # 降噪：不打 traceback
    assert "连接" in records[0].getMessage()


def test_refresh_unexpected_error_keeps_traceback(tmp_db: Any, caplog: Any) -> None:
    """非连接级异常（解析/契约错）保留完整栈，便于排查。"""
    import logging

    def broken(page: int, size: int) -> tuple[list[dict[str, Any]], int]:
        raise ValueError("payload 结构不符")

    with caplog.at_level(logging.WARNING, logger="atlas.industry"):
        refresh_industry_map(fetch_page=broken)

    records = [r for r in caplog.records if r.name == "atlas.industry"]
    assert len(records) == 1
    assert records[0].exc_info is not None


def test_industry_health_reports_rows_and_age(tmp_db: Any) -> None:
    """health 观测面：只做聚合（不拉全表、不触网），空表/新鲜/陈旧三态如实。"""
    assert im.industry_health()["status"] == "empty"

    refresh_industry_map(fetch_page=lambda page, size: ([{"code": "600519", "industry": "白酒"}], 1))
    fresh = im.industry_health()
    assert fresh["status"] == "fresh" and fresh["rows"] == 1
    assert isinstance(fresh["oldestAgeSeconds"], int) and fresh["oldestAgeSeconds"] >= 0

    tmp_db.age_back(hours=30)
    stale = im.industry_health()
    assert stale["status"] == "stale" and stale["rows"] == 1
