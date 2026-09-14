"""P2-M1 bars_etl 核心测试：水位（时刻粒度）/ universe（并集护栏面）/ 缺口四档。"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from backend import bars_etl, storage

SH = ZoneInfo("Asia/Shanghai")


# ── I2 水位：Asia/Shanghai 时刻粒度（P0-3 回归锚） ──────────────────────────


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 11, 15, 4, tzinfo=SH), "2026-09-10"),  # 周四 15:04 未到收盘点→昨交易日
        (datetime(2026, 9, 11, 15, 5, tzinfo=SH), "2026-09-11"),  # 恰 15:05→当日
        (datetime(2026, 9, 11, 15, 6, tzinfo=SH), "2026-09-11"),  # 15:06→当日
        (datetime(2026, 9, 12, 9, 0, tzinfo=SH), "2026-09-11"),  # 周六→上周五
        (datetime(2026, 9, 13, 12, 0, tzinfo=SH), "2026-09-11"),  # 周日中午→上周五
        (datetime(2026, 9, 14, 16, 0, tzinfo=SH), "2026-09-14"),  # 周一收盘后→当日
        (
            datetime(2026, 9, 14, 16, 0, tzinfo=ZoneInfo("America/New_York")),
            "2026-09-14",
        ),  # 纽约输入归一上海（彼时 04:00 周二盘前→周一）
    ],
)
def test_watermark_moment_granularity(now, expected):
    assert bars_etl.authoritative_watermark(now=now) == expected


# ── I1 universe：三源并集 + 去重升序 + 北交所工作区码在内 + 无指数特判面 ──────


def test_resolve_universe_union_dedup_sorted():
    day_seed = [
        storage.IndustryMap(code="810001", name="测试行业A"),
        storage.IndustryMap(code="810002", name="测试行业B"),
        storage.WatchlistItem(workspace_id="default", code="810001"),  # 与 industry 重复→去重
        storage.WatchlistItem(workspace_id="default", code="920001"),  # 北交所样式码：工作区即入
        storage.TradePlan(
            id="cov-plan-1",
            code="920002",
            direction="buy",
            entry=1,
            stop=0.9,
            target=1.2,
            capital=100,
            position=10,
            validity="本周内",
        ),
    ]
    try:
        with storage.SessionLocal.begin() as s:
            s.add_all(day_seed)
        universe = bars_etl.resolve_universe()
        assert universe == sorted(universe)
        assert len(universe) == len(set(universe))
        for code in ("810001", "810002", "920001", "920002"):
            assert code in universe
        # 不断言生产规模（开发库 industry_map 可能为空——run_full 的 UNIVERSE_MIN 护栏正是为此存在）
    finally:
        with storage.SessionLocal.begin() as s:
            s.query(storage.IndustryMap).filter(storage.IndustryMap.code.in_(["810001", "810002"])).delete(
                synchronize_session=False
            )
            s.query(storage.WatchlistItem).filter(storage.WatchlistItem.code.in_(["810001", "920001"])).delete(
                synchronize_session=False
            )
            s.query(storage.TradePlan).filter(storage.TradePlan.id == "cov-plan-1").delete(synchronize_session=False)


# ── I3 缺口四档：真 PG 预置，集合相等断言 ──────────────────────────────────


def test_detect_gaps_four_buckets(monkeypatch):
    wm = "2099-10-09"  # 周五
    monkeypatch.setattr(bars_etl, "authoritative_watermark", lambda now=None: wm)
    codes = ["cove-a", "cove-b", "cove-c", "cove-d", "cove-e"]
    monkeypatch.setattr(bars_etl, "resolve_universe", lambda: codes)
    bar = lambda d: {"date": d, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10, "amount": 100}  # noqa: E731
    try:
        # A 无行=missing；B 落后>10 交易日=stale_deep；C 落后 1=stale_light；D 恰水位=up_to_date；
        # E 水位之后（周末异常行）lag=0 → up_to_date
        storage.upsert_market_bars_batch("cove-b", [bar("2099-09-01")], adjustment="")
        storage.upsert_market_bars_batch("cove-c", [bar("2099-10-08")], adjustment="")
        storage.upsert_market_bars_batch("cove-d", [bar(wm)], adjustment="")
        storage.upsert_market_bars_batch("cove-e", [bar("2099-10-11")], adjustment="")
        gaps = bars_etl.detect_gaps()
        assert gaps["missing"] == ["cove-a"]
        assert gaps["stale_deep"] == ["cove-b"]
        assert gaps["stale_light"] == ["cove-c"]
        assert gaps["up_to_date"] == 2
    finally:
        with storage.SessionLocal.begin() as s:
            s.query(storage.MarketBar).filter(storage.MarketBar.code.in_(codes)).delete(synchronize_session=False)


# ── lag 计数辅助（weekday 近似，与 §9-L3 同源） ─────────────────────────────


@pytest.mark.parametrize(
    ("last", "watermark", "expected"),
    [
        (None, "2026-09-11", 10_000),
        ("2026-09-11", "2026-09-11", 0),
        ("2026-09-12", "2026-09-11", 0),  # 超前（周末异常）不产生负 lag
        ("2026-09-10", "2026-09-11", 1),
        ("2026-09-04", "2026-09-11", 5),  # 跨周末只数 weekday
    ],
)
def test_lag_days(last, watermark, expected):
    assert bars_etl._lag_days(last, watermark) == expected
