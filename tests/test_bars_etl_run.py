"""P2-M1 run_full 测试：空判失败熔断 / DQ 拒收 / SAVEPOINT 隔离 / no_new_bar / 自愈队列 / 护栏 / 互斥。"""

import pytest
from backend import bars_etl, storage

WM = "2099-10-09"  # 固定水位（周五）


def _bar(**kw):
    b = {"date": "2099-10-09", "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100.0, "amount": 1000.0}
    b.update(kw)
    return b


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    bars_etl._recheck.clear()
    monkeypatch.setattr(bars_etl, "authoritative_watermark", lambda now=None: WM)
    monkeypatch.setattr(bars_etl, "UNIVERSE_MIN", 1)  # 小样本测试面降护栏；护栏行为另有专测
    monkeypatch.setattr(bars_etl, "market_code_count", lambda: 10**6)  # 默认关护栏（不依赖本机 industry 表状态）
    yield
    bars_etl._recheck.clear()
    with storage.SessionLocal.begin() as s:
        s.query(storage.MarketBar).filter(storage.MarketBar.code.like("cov%")).delete(synchronize_session=False)


# ── validate_bars：DQ 坏根矩阵（P1-3） ──────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [
        {"high": 8.0},  # OHLC 颠倒（high < close）
        {"low": -1.0},  # 负价
        {"volume": -5.0},  # 负量
        {"open": None},  # 缺价
        {"date": "2099-12-31"},  # 未来日（> 水位）
        {"date": ""},  # 无日
    ],
)
def test_validate_bars_rejects(bad):
    payload = {"date": "2099-10-09"}
    payload.update(bad)
    clean, rejected = bars_etl.validate_bars([_bar(**payload)], WM)
    assert clean == [] and rejected == 1


def test_validate_bars_accepts_normal_and_suspended_zero_volume():
    bars = [_bar(date="2099-10-08"), _bar(date="2099-10-09", volume=0.0, amount=0.0)]  # 停牌零量合法
    clean, rejected = bars_etl.validate_bars(bars, WM)
    assert len(clean) == 2 and rejected == 0


# ── P0-2：空响应=失败（并计熔断，含最小样本） ───────────────────────────────


def _stub(monkeypatch, codes, gaps=None):
    monkeypatch.setattr(bars_etl, "resolve_universe", lambda: list(codes))
    monkeypatch.setattr(
        bars_etl,
        "detect_gaps",
        lambda: gaps or {"missing": list(codes), "stale_deep": [], "stale_light": [], "up_to_date": 0},
    )


def test_all_empty_responses_abort_breaker(monkeypatch):
    codes = [f"covf-{i:03d}" for i in range(60)]  # 60≥最小样本50：100% 失败必熔断
    _stub(monkeypatch, codes)
    upserts = []
    monkeypatch.setattr(storage, "upsert_market_bars_batch", lambda *a, **k: upserts.append(a))
    stats = bars_etl.run_full(fetch=lambda code, limit: [])
    assert stats.aborted is True and stats.reason == "fail_rate"
    # 熔断=达样本阈值即中途切断，剩余码留待下轮（failed∈[50,60] 而非必然 60）
    assert 50 <= len(stats.failed) <= 60 and stats.fetched == 0
    assert upserts == []  # 静默空洞封堵：空响应零写库


def test_small_sample_does_not_trip_breaker(monkeypatch):
    codes = [f"covg-{i:03d}" for i in range(10)]  # 10<50：全失败也不早切（P2-1）
    _stub(monkeypatch, codes)
    stats = bars_etl.run_full(fetch=lambda code, limit: [])
    assert stats.aborted is False and len(stats.failed) == 10


# ── I10 码级 SAVEPOINT：单码异常不连坐同组他码 ─────────────────────────────


def test_savepoint_isolates_failing_code(monkeypatch):
    codes = [f"covs-{i}" for i in range(1, 6)]
    _stub(monkeypatch, codes)

    def fetch(code, limit):
        if code == "covs-3":
            raise ConnectionError("upstream down")
        return [_bar(date="2099-10-09")]

    stats = bars_etl.run_full(fetch=fetch)
    assert stats.failed == ["covs-3", "covs-3"] or stats.failed == ["covs-3"]  # 重试 1 次→计一次失败
    assert stats.fetched == 4
    assert {r.code for r in _rows(codes)} == {"covs-1", "covs-2", "covs-4", "covs-5"}


def _rows(codes):
    from sqlalchemy import select

    with storage.SessionLocal() as s:
        return s.scalars(select(storage.MarketBar).where(storage.MarketBar.code.in_(codes))).all()


# ── no_new_bar / DQ 拒收计数 / _recheck 自愈队列 ────────────────────────────


def test_no_new_bar_normal_bucket(monkeypatch):
    _stub(
        monkeypatch,
        ["covn-1"],
        gaps={"missing": [], "stale_deep": [], "stale_light": ["covn-1"], "up_to_date": 0},
    )
    storage.upsert_market_bars_batch("covn-1", [_bar(date="2099-10-08")], adjustment="")
    stats = bars_etl.run_full(fetch=lambda code, limit: [_bar(date="2099-10-08")])  # 拉回无新根（假日形态）
    assert stats.no_new_bar == 1 and stats.fetched == 1 and stats.failed == []


def test_rejected_routes_code_to_recheck_next_round(monkeypatch):
    _stub(
        monkeypatch,
        ["covr-1"],
        gaps={"missing": [], "stale_deep": [], "stale_light": ["covr-1"], "up_to_date": 0},
    )
    stats = bars_etl.run_full(fetch=lambda code, limit: [_bar(date="2099-10-08"), _bar(date="2099-10-09", low=-1)])
    assert stats.rejected == 1 and "covr-1" in bars_etl._recheck
    # 第二轮：缺口检测已视其 up_to_date，自愈队列仍强制复核
    calls = []

    def fetch(code, limit):
        calls.append(code)
        return [_bar(date="2099-10-09", low=9.0)]

    _stub(
        monkeypatch,
        ["covr-1"],
        gaps={"missing": [], "stale_deep": [], "stale_light": [], "up_to_date": 1},
    )
    stats2 = bars_etl.run_full(fetch=fetch)
    assert calls == ["covr-1"] and stats2.daily == 1
    assert "covr-1" not in bars_etl._recheck  # 本轮无 rejected，出队


def test_all_bars_rejected_counts_code_as_failed(monkeypatch):
    _stub(monkeypatch, ["covx-1"])
    stats = bars_etl.run_full(fetch=lambda code, limit: [_bar(date="2099-10-09", low=-2)])
    assert stats.failed == ["covx-1"] and stats.fetched == 0 and stats.rejected == 1


# ── 护栏：小分母 / 互斥锁 / force ───────────────────────────────────────────


def test_universe_guard_aborts_before_fetch(monkeypatch):
    """⟹ spec D4 语义变更：market 小且全为未入库新码 → 不再整轮中止；
    新码全 deferred、零 fetch，abort_reason 如实（旧"universe_too_small 整轮 aborted"废除）。
    本测试文件属"语义变更修测试"白名单——依据 spec §3 D4/评审 P0-1。"""
    _stub(monkeypatch, [f"covh-{i}" for i in range(5)])
    monkeypatch.setattr(bars_etl, "UNIVERSE_MIN", 10)  # _stub 默认放行 market 后本例锁护栏
    monkeypatch.setattr(bars_etl, "market_code_count", lambda: 0)
    calls = []
    stats = bars_etl.run_full(fetch=lambda code, limit: calls.append(code) or [])
    assert stats.aborted is False and stats.abort_reason == "market_universe_small"
    assert stats.deferred == 5 and stats.backfill == 0
    assert calls == [] and stats.failed == []


def test_run_lock_gives_overlap_abort(monkeypatch):
    _stub(monkeypatch, [f"covo-{i}" for i in range(60)])
    assert bars_etl._RUN_LOCK.acquire()
    try:
        stats = bars_etl.run_full(fetch=lambda code, limit: [])
    finally:
        bars_etl._RUN_LOCK.release()
    assert stats.aborted is True and stats.reason == "overlap"


def test_force_requeues_up_to_date_codes(monkeypatch):
    codes = ["covt-1", "covt-2"]
    _stub(monkeypatch, codes, gaps={"missing": [], "stale_deep": [], "stale_light": [], "up_to_date": 2})
    calls = []

    def fetch(code, limit):
        calls.append((code, limit))
        return [_bar(date="2099-10-09")]

    stats = bars_etl.run_full(force=True, fetch=fetch)
    assert sorted(c for c, _ in calls) == codes
    assert stats.daily == 2 and all(limit >= 20 for _, limit in calls)


def test_plain_run_skips_up_to_date(monkeypatch):
    _stub(monkeypatch, ["covt-1"], gaps={"missing": [], "stale_deep": [], "stale_light": [], "up_to_date": 1})
    calls = []
    stats = bars_etl.run_full(fetch=lambda code, limit: calls.append(code) or [])
    assert calls == [] and stats.up_to_date == 1 and stats.backfill == 0 and stats.daily == 0


# ── L8 三连修：公平随机序 / 回补预算 / ETL 专属限速 ────────────────────────


def test_fair_order_stable_rotating_and_not_head_sorted():
    q = [f"c{i:02d}" for i in range(24)]
    a = bars_etl._fair_order(q, "bf:2099-10-09")
    assert sorted(a) == q
    assert a == bars_etl._fair_order(q, "bf:2099-10-09")  # 同日盐同序（组重放稳定）
    assert a != bars_etl._fair_order(q, "bf:2099-10-10")  # 跨日轮换头部
    assert a != list(q)  # 非恒等（salt 定值下的存在性断言，失败即换 salt）


def test_backfill_budget_defers_tail(monkeypatch):
    monkeypatch.setattr(bars_etl, "BACKFILL_CODES_PER_RUN", 5)
    codes = [f"covb-{i:03d}" for i in range(60)]
    _stub(monkeypatch, codes)
    calls = []
    stats = bars_etl.run_full(fetch=lambda code, limit: calls.append(code) or [_bar(date="2099-10-09")])
    assert stats.backfill == 5 and stats.deferred == 55 and len(calls) == 5


def test_default_fetch_paces_upstream(monkeypatch):
    slept = []
    from backend import data_source

    monkeypatch.setattr(bars_etl.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(data_source, "load_history", lambda code, **kw: [])
    bars_etl._default_fetch("600000", 5)
    assert slept == [bars_etl.ETL_MIN_FETCH_INTERVAL]


# ── G3 护栏三面拆分 + L9 5xx 零重试（Task 1 / spec §3 D4） ──────────────────


def test_guard_freezes_new_but_runs_existing(monkeypatch):
    """industry 表空→market 面小→新码(missing)全 deferred，存量码(stale_deep)深补照跑。"""
    monkeypatch.setattr(bars_etl, "market_code_count", lambda: 0)  # market 面塌
    monkeypatch.setattr(bars_etl, "UNIVERSE_MIN", 2000)
    monkeypatch.setattr(bars_etl, "resolve_universe", lambda: ["covn-1", "covn-2", "covo-1"])
    monkeypatch.setattr(
        bars_etl,
        "detect_gaps",
        lambda: {"missing": ["covn-1", "covn-2"], "stale_deep": ["covo-1"], "stale_light": [], "up_to_date": 0},
    )
    up = []
    monkeypatch.setattr(storage, "upsert_market_bars_batch", lambda code, bars, **k: up.append(code) or 1)
    monkeypatch.setattr(bars_etl, "_max_map", lambda: {"covo-1": "2099-09-01"})  # covo-1 在库=存量
    stats = bars_etl.run_full(fetch=lambda code, limit: [_bar()])
    assert stats.backfill == 1 and up == ["covo-1"]  # 仅存量码深补
    assert stats.deferred == 2  # 两新码 deferred
    assert stats.aborted is False  # 护栏不再整轮冻结
    assert stats.abort_reason == "market_universe_small"


def test_guard_closed_backfills_all(monkeypatch):
    monkeypatch.setattr(bars_etl, "market_code_count", lambda: 9999)
    monkeypatch.setattr(bars_etl, "UNIVERSE_MIN", 2000)
    monkeypatch.setattr(bars_etl, "resolve_universe", lambda: ["covz-1"])
    monkeypatch.setattr(
        bars_etl, "detect_gaps", lambda: {"missing": ["covz-1"], "stale_deep": [], "stale_light": [], "up_to_date": 0}
    )
    up = []
    monkeypatch.setattr(storage, "upsert_market_bars_batch", lambda code, bars, **k: up.append(code) or 1)
    stats = bars_etl.run_full(fetch=lambda code, limit: [_bar()])
    assert up == ["covz-1"] and stats.deferred == 0 and stats.abort_reason == ""


def test_existing_backfill_priority_under_budget(monkeypatch):
    """预算紧时存量码占先，新码让位 deferred。"""
    monkeypatch.setattr(bars_etl, "market_code_count", lambda: 9999)
    monkeypatch.setattr(bars_etl, "BACKFILL_CODES_PER_RUN", 1)
    monkeypatch.setattr(bars_etl, "resolve_universe", lambda: ["covn-9", "covo-8"])
    monkeypatch.setattr(
        bars_etl,
        "detect_gaps",
        lambda: {"missing": ["covn-9"], "stale_deep": ["covo-8"], "stale_light": [], "up_to_date": 0},
    )
    monkeypatch.setattr(bars_etl, "_max_map", lambda: {"covo-8": "2099-09-01"})
    up = []
    monkeypatch.setattr(storage, "upsert_market_bars_batch", lambda code, bars, **k: up.append(code) or 1)
    stats = bars_etl.run_full(fetch=lambda code, limit: [_bar()])
    assert up == ["covo-8"] and stats.deferred == 1


def test_attempt_http_error_single_hit(monkeypatch):
    """L9: 5xx 在 bars 层零重试（区别于空响应/网络类）。"""
    import requests

    codes = [f"covr-{i}" for i in range(3)]
    _stub(monkeypatch, codes)
    calls = []

    def boom(code, limit):
        calls.append(code)
        raise requests.HTTPError("501")

    stats = bars_etl.run_full(fetch=boom)
    assert sorted(calls) == sorted(codes)  # 每码恰 1 次，非 2
    assert len(stats.failed) == 3
