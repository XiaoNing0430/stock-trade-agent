"""计划绩效复盘：source 归因存储 + bfq 链路 + 回放引擎 + 聚合 API。

沿用 test_storage_coverage.py 的既有模式：真实 PostgreSQL（initialize_storage）+
专用工作区避免污染默认数据；不臆造 fixture。
"""

from __future__ import annotations

import pytest
from backend import storage
from backend import storage as storage_module
from backend.plan_review import replay_plan, shanghai_date_str, slice_window, validity_expiry_date

# 专用测试工作区，避免覆盖默认工作区真实数据
WS = "pr-ws"


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables():
    storage_module.initialize_storage()


@pytest.fixture(autouse=True)
def _cleanup_test_data():
    yield
    from sqlalchemy import delete

    models = [
        storage_module.WatchlistItem,
        storage_module.TradePlan,
        storage_module.Alert,
        storage_module.WorkspaceState,
    ]
    with storage_module.engine.begin() as connection:
        for model in models:
            connection.execute(delete(model).where(model.workspace_id == WS))


def test_plan_dict_carries_source():
    with storage_module.SessionLocal() as session:
        plan = storage_module.TradePlan(
            id="pr-p1",
            workspace_id=WS,
            code="300750",
            direction="buy",
            entry=10.0,
            stop=9.5,
            target=11.0,
            capital=10000,
            position=50,
            validity="本周内",
            source="scan:trend_breakout",
        )
        session.add(plan)
        session.commit()
        loaded = session.get(storage_module.TradePlan, "pr-p1")
        assert loaded.source == "scan:trend_breakout"
        d = storage_module._plan_dict(loaded)
        assert d["source"] == "scan:trend_breakout"


def test_plan_source_null_is_legacy_ready():
    with storage_module.SessionLocal() as session:
        plan = storage_module.TradePlan(
            id="pr-p2",
            workspace_id=WS,
            code="600519",
            direction="buy",
            entry=10.0,
            stop=9.5,
            target=11.0,
            capital=10000,
            position=50,
            validity="本周内",
        )
        session.add(plan)
        session.commit()
        loaded = session.get(storage_module.TradePlan, "pr-p2")
        assert loaded.source is None
        assert storage_module._plan_dict(loaded)["source"] is None  # 归一为 legacy 在 plan_review 层做


def test_save_workspace_roundtrips_source():
    payload = {
        "plans": [
            {
                "id": "pr-p3",
                "code": "000001",
                "direction": "buy",
                "entry": 10.0,
                "stop": 9.5,
                "target": 11.0,
                "capital": 10000,
                "position": 50,
                "validity": "本月内",
                "status": "执行中",
                "triggered": {},
                "createdAtMs": 1700000000000,
                "source": "manual",
            }
        ],
        "watchlist": [],
        "alerts": [],
    }
    storage_module.save_workspace(payload, WS)
    ws = storage_module.get_workspace(WS)
    plan = next(p for p in ws["plans"] if p["id"] == "pr-p3")
    assert plan["source"] == "manual"
    payload["plans"][0]["source"] = ""  # 空串 → None（存量/清空语义）
    storage_module.save_workspace(payload, WS)
    plan = next(p for p in storage_module.get_workspace(WS)["plans"] if p["id"] == "pr-p3")
    assert plan["source"] is None


# —— Task 2: bfq 原始价链路（brief 测试块原样转录）——
# session_db：brief 第三例的参数名；tests/ 下无同名 fixture，这里给出最小实现，
# 并在前后清理 300750 的 market_bars，避免与其他用例互相污染。

@pytest.fixture()
def session_db():
    from sqlalchemy import delete as _delete

    with storage_module.engine.begin() as connection:
        connection.execute(_delete(storage_module.MarketBar).where(storage_module.MarketBar.code == "300750"))
    yield
    with storage_module.engine.begin() as connection:
        connection.execute(_delete(storage_module.MarketBar).where(storage_module.MarketBar.code == "300750"))


def _row(date: str) -> list:
    return [date, "10.0", "10.2", "10.5", "9.9", "100000", "102000000", "1.5", "2.0", "0.1", "1.1"]


def test_load_history_default_qfq_unchanged(monkeypatch):
    from backend import data_source as ds
    keys: list[str] = []
    seen: dict[str, str] = {}

    def fake_cached(key, fn):
        keys.append(key)
        return fn()

    def fake_fetch_json(url, params):
        seen["param"] = params["param"]
        return {"data": {"sh600519": {"qfqday": [_row("2026-09-01")]}}}

    monkeypatch.setattr(ds, "tencent_symbol", lambda c: "sh600519")
    monkeypatch.setattr(ds, "cached", fake_cached)
    monkeypatch.setattr(ds, "fetch_json", fake_fetch_json)
    rows = ds.load_history("600519", limit=40)
    assert rows[0]["date"] == "2026-09-01"
    assert keys == ["history:sh600519:40:qfq"]          # 默认 qfq：缓存键含 :qfq
    assert seen["param"] == "sh600519,day,,,40,qfq"     # 上游 param 尾字段 qfq（现行为不变）


def test_load_history_bfq_uses_day_rows(monkeypatch):
    from backend import data_source as ds
    keys: list[str] = []
    seen: dict[str, str] = {}

    def fake_cached(key, fn):
        keys.append(key)
        return fn()

    def fake_fetch_json(url, params):
        seen["param"] = params["param"]
        return {"data": {"sh600519": {"day": [_row("2026-09-02")]}}}   # 不复权响应只有 day 键

    monkeypatch.setattr(ds, "tencent_symbol", lambda c: "sh600519")
    monkeypatch.setattr(ds, "cached", fake_cached)
    monkeypatch.setattr(ds, "fetch_json", fake_fetch_json)
    rows = ds.load_history("600519", limit=40, adjustment="")
    assert rows[0]["date"] == "2026-09-02"
    assert keys == ["history:sh600519:40:"]             # 空串 fq 的缓存键（与 qfq 键不冲突）
    assert seen["param"] == "sh600519,day,,,40,"        # 尾字段空串 → 上游返回原始价


def test_storage_market_bars_bfq_roundtrip(session_db):
    bars = [{"date": "2026-09-01", "open": 10.0, "close": 10.2, "high": 10.5,
             "low": 9.9, "volume": 100000, "amount": 102000000.0, "change": 1.5}]
    storage.save_market_bars("300750", bars, adjustment="")
    loaded = storage.load_market_bars("300750", adjustment="")
    assert loaded[0]["date"] == "2026-09-01"
    qfq = storage.load_market_bars("300750", adjustment="qfq")  # 互不污染
    assert qfq == []


# —— Task 3: 回放引擎核心（窗口切片 + 六态 + 双触保守 + sell 平仓语义 + R/净R）——
# brief 测试块原样转录；钉死事实（勿重推）：createdAtMs = 1_789_084_800_000
# = 2026-09-11（周五）08:00 Asia/Shanghai（已实算：1_767_225_600 = 2026-01-01 00:00 UTC，+253 整天）。

TODAY = "2026-10-05"  # 「本月内」（过期 09-30）窗口均闭合


def make_bars(dates_prices: list[tuple[str, float, float, float, float, float]]) -> list[dict]:
    """(date, open, close, high, low, volume) → bar dicts，amount/change 补默认。"""
    return [{"date": d, "open": o, "close": c, "high": h, "low": lo, "volume": v,
             "amount": 1_000_000.0, "change": 1.0} for d, o, c, h, lo, v in dates_prices]


def make_plan(**over) -> dict:
    base = {"id": "p1", "code": "300750", "direction": "buy", "entry": 10.0, "stop": 9.5,
            "target": 11.0, "capital": 10000, "position": 50, "validity": "本月内",
            "status": "执行中", "triggered": {}, "createdAtMs": 1_789_084_800_000,
            "note": "", "createdAt": "00:00", "source": None}
    base.update(over)
    return base


def test_buy_win_hits_target_first():
    # 创建 09-11；窗口从 09-14 起。entry=10 stop=9.5 target=11 → risk=0.5
    # 09-14 low=9.8>未触? low 9.8 > entry 10? 9.8<10 → 触及 entry（low≤entry）
    # 09-15 high=11.3 ≥ target 11 → win, R=(11-10)/0.5=2.0；costR=0.0015*10/0.5=0.03 → netR=1.97
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
                      ("2026-09-15", 10.5, 11.2, 11.3, 10.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "win" and rec["rValue"] == 2.0 and rec["netR"] == 1.97
    assert rec["entryDate"] == "2026-09-14" and rec["exitDate"] == "2026-09-15"
    assert rec["costR"] == 0.03 and rec["ambiguous"] is False


def test_buy_loss_hits_stop():
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
                      ("2026-09-15", 10.0, 9.4, 10.1, 9.4, 1000.0)])  # low 9.4 ≤ stop 9.5
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "loss" and rec["rValue"] == -1.0 and rec["netR"] == -1.03


def test_same_day_double_touch_conservative_loss():
    # 09-14 当日 low 9.4≤stop 且 high 11.2≥target → 保守记败 R=-1
    bars = make_bars([("2026-09-14", 10.2, 10.0, 11.2, 9.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "loss" and rec["ambiguous"] is True and rec["rValue"] == -1.0


def test_gap_down_whole_day_below_entry_still_enters():
    # 整日低于 entry（high 9.8 < entry 10）→ low ≤ entry 触及成立（r3.1），成交价记 entry=10
    # 09-15 收 9.4≤stop? low 9.4 ≤ stop 9.5 → loss -1
    bars = make_bars([("2026-09-14", 9.7, 9.6, 9.8, 9.5, 1000.0),
                      ("2026-09-15", 9.5, 9.4, 9.6, 9.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["entryDate"] == "2026-09-14" and rec["outcome"] == "loss"


def test_flat_exits_at_window_end_close():
    # 窗口内触及 entry 后 target/stop 均未触 → 平出，exit=末收盘 10.1，R=(10.1-10)/0.5=0.2
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.3, 9.9, 1000.0),
                      ("2026-09-15", 10.1, 10.1, 10.4, 10.0, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "flat" and abs(rec["rValue"] - 0.2) < 1e-9


def test_not_entered_when_entry_never_touched():
    bars = make_bars([("2026-09-14", 10.5, 10.6, 10.8, 10.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "notEntered" and rec["rValue"] is None


def test_open_when_window_not_closed():
    # validity=本月内（09-11 创建 → 09-30 过期）但 today=09-16：窗口未闭合 → 进行中
    bars = make_bars([("2026-09-14", 10.5, 10.6, 10.8, 10.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today="2026-09-16")
    assert rec["outcome"] == "open"


def test_sell_direction_flat_order_semantics():
    # sell：无未入场判定；先 target 记胜。R=(11-10)/0.5=2.0（不翻向）
    bars = make_bars([("2026-09-14", 10.5, 11.1, 11.2, 10.4, 1000.0)])
    rec = replay_plan(make_plan(direction="sell"), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "win" and rec["rValue"] == 2.0


def test_invalid_plan_params():
    rec = replay_plan(make_plan(entry=0), [], 0.0015, today=TODAY)
    assert rec["outcome"] == "invalid"
    rec2 = replay_plan(make_plan(stop=10.5), [], 0.0015, today=TODAY)  # entry-stop ≤ 0
    assert rec2["outcome"] == "invalid"


def test_no_bars_at_all_is_invalid():
    rec = replay_plan(make_plan(), [], 0.0015, today=TODAY)
    assert rec["outcome"] == "invalid"


def test_creation_day_bar_excluded_and_expiry_day_included():
    # 创建 2026-09-11（周五）：09-11 的 bar 不参与（决议 9）；窗口从 09-14 起
    # validity=本周内 → 过期日=09-13（ISO 周日，已实算）
    assert validity_expiry_date(1_789_084_800_000, "本周内") == "2026-09-13"
    assert validity_expiry_date(1_789_084_800_000, "本月内") == "2026-09-30"
    bars = make_bars([("2026-09-11", 9.0, 9.0, 9.0, 9.0, 1000.0),   # 创建当日：若被误用会立刻 win（low≤entry≤target）→ 该用例防前视
                      ("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0)])
    rec = replay_plan(make_plan(validity="本月内"), bars, 0.0015, today=TODAY)
    assert rec["entryDate"] == "2026-09-14"  # 创建当日 bar 未参与


def test_unclosed_today_bar_excluded():
    # today=09-15：09-15 的 bar 是"今天"，未收盘不参与 → 09-14 触及 entry 后窗口无后续 → open
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
                      ("2026-09-15", 11.5, 11.6, 11.7, 11.0, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today="2026-09-15")
    assert rec["outcome"] == "open"


def test_sell_empty_closed_window_is_invalid():
    # sell 已持仓平仓单：窗口空（bars 全在创建日前）且已闭合 → invalid（评审 B1；无末收盘价可平出，绝不算 notEntered）
    bars = make_bars([("2026-09-01", 10, 10, 10, 10, 1000.0)])
    rec = replay_plan(make_plan(direction="sell"), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "invalid"


def test_validity_long_term_and_empty_sentinel():
    # 长期/空 → 哨兵 9999-12-31，slice_window 收口为"终点=今天"（spec 边界表；评审非 Blocker ①）
    assert validity_expiry_date(1_789_084_800_000, "长期") == "9999-12-31"
    assert validity_expiry_date(1_789_084_800_000, "") == "9999-12-31"
    bars = make_bars([("2026-09-14", 10.5, 10.6, 10.8, 10.4, 1000.0)])
    rec = replay_plan(make_plan(validity="长期"), bars, 0.0015, today="2026-09-16")
    assert rec["outcome"] == "open"   # 窗口未闭合 → 进行中（非 notEntered）


# —— slice_window 窗口终点语义直测（数值按 createdAt=09-11 钉死）——


def test_slice_window_expiry_day_bar_included():
    # validity=本周内 → 过期日 09-13；today=09-16 → end_date=min(09-13, 09-16)=09-13，已闭合
    # 窗口 = (09-11, 09-13] → 09-12、09-13；prevClose 用 09-11（创建当日 bar 可作 prev）
    bars = make_bars([("2026-09-11", 10, 10, 10, 10, 1000.0),
                      ("2026-09-12", 10, 10, 10, 10, 1000.0),
                      ("2026-09-13", 10, 10, 10, 10, 1000.0),
                      ("2026-09-14", 10, 10, 10, 10, 1000.0)])   # 09-14 > 过期日 → 不在窗口
    window, prev, closed = slice_window(bars, 1_789_084_800_000, "本周内", today="2026-09-16")
    assert [b["date"] for b in window] == ["2026-09-12", "2026-09-13"]  # 过期日当日 bar 参与（r3.1 消歧）
    assert closed is True and prev is not None and prev["date"] == "2026-09-11"


def test_slice_window_excludes_unclosed_today_bar():
    # today=09-15：09-15 的 bar 未收盘，即使 ≤ end_date 也排除（B2）
    bars = make_bars([("2026-09-11", 10, 10, 10, 10, 1000.0),
                      ("2026-09-14", 10, 10, 10, 10, 1000.0),
                      ("2026-09-15", 10, 10, 10, 10, 1000.0)])
    window, _, closed = slice_window(bars, 1_789_084_800_000, "本月内", today="2026-09-15")
    assert [b["date"] for b in window] == ["2026-09-14"]    # 09-15（今天）被 < today 排除
    assert closed is False                                   # end_date=min(09-30,09-15)=09-15 不早于今天


def test_shanghai_date_str_pins_creation_ms():
    # 补充钉死用例（brief 用例集未含）：钉死时区换算事实，并使 shanghai_date_str 导入被使用（避免 F401）
    assert shanghai_date_str(1_789_084_800_000) == "2026-09-11"
