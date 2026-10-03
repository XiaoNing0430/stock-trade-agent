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
