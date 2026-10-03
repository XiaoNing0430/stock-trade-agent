"""计划绩效复盘：source 归因存储 + bfq 链路 + 回放引擎 + 聚合 API。

沿用 test_storage_coverage.py 的既有模式：真实 PostgreSQL（initialize_storage）+
专用工作区避免污染默认数据；不臆造 fixture。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest
from backend import app as app_module
from backend import storage
from backend import storage as storage_module
from backend.plan_review import (
    SHANGHAI,
    ReviewUpstreamError,
    aggregate,
    fetch_all_bars,
    replay_plan,
    review_plans,
    shanghai_date_str,
    slice_window,
    validity_expiry_date,
)
from fastapi.testclient import TestClient

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

    def fake_fetch_json(url, params, **kw):
        seen["param"] = params["param"]
        return {"data": {"sh600519": {"qfqday": [_row("2026-09-01")]}}}

    monkeypatch.setattr(ds, "tencent_symbol", lambda c: "sh600519")
    monkeypatch.setattr(ds, "cached", fake_cached)
    monkeypatch.setattr(ds, "fetch_json", fake_fetch_json)
    rows = ds.load_history("600519", limit=40)
    assert rows[0]["date"] == "2026-09-01"
    assert keys == ["history:sh600519:40:qfq"]  # 默认 qfq：缓存键含 :qfq
    assert seen["param"] == "sh600519,day,,,40,qfq"  # 上游 param 尾字段 qfq（现行为不变）


def test_load_history_bfq_uses_day_rows(monkeypatch):
    from backend import data_source as ds

    keys: list[str] = []
    seen: dict[str, str] = {}

    def fake_cached(key, fn):
        keys.append(key)
        return fn()

    def fake_fetch_json(url, params, **kw):
        seen["param"] = params["param"]
        return {"data": {"sh600519": {"day": [_row("2026-09-02")]}}}  # 不复权响应只有 day 键

    monkeypatch.setattr(ds, "tencent_symbol", lambda c: "sh600519")
    monkeypatch.setattr(ds, "cached", fake_cached)
    monkeypatch.setattr(ds, "fetch_json", fake_fetch_json)
    rows = ds.load_history("600519", limit=40, adjustment="")
    assert rows[0]["date"] == "2026-09-02"
    assert keys == ["history:sh600519:40:"]  # 空串 fq 的缓存键（与 qfq 键不冲突）
    assert seen["param"] == "sh600519,day,,,40,"  # 尾字段空串 → 上游返回原始价


def test_storage_market_bars_bfq_roundtrip(session_db):
    bars = [
        {
            "date": "2026-09-01",
            "open": 10.0,
            "close": 10.2,
            "high": 10.5,
            "low": 9.9,
            "volume": 100000,
            "amount": 102000000.0,
            "change": 1.5,
        }
    ]
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
    return [
        {"date": d, "open": o, "close": c, "high": h, "low": lo, "volume": v, "amount": 1_000_000.0, "change": 1.0}
        for d, o, c, h, lo, v in dates_prices
    ]


def make_plan(**over) -> dict:
    base = {
        "id": "p1",
        "code": "300750",
        "direction": "buy",
        "entry": 10.0,
        "stop": 9.5,
        "target": 11.0,
        "capital": 10000,
        "position": 50,
        "validity": "本月内",
        "status": "执行中",
        "triggered": {},
        "createdAtMs": 1_789_084_800_000,
        "note": "",
        "createdAt": "00:00",
        "source": None,
    }
    base.update(over)
    return base


def test_buy_win_hits_target_first():
    # 创建 09-11；窗口从 09-14 起。entry=10 stop=9.5 target=11 → risk=0.5
    # 09-14 low=9.8>未触? low 9.8 > entry 10? 9.8<10 → 触及 entry（low≤entry）
    # 09-15 high=11.3 ≥ target 11 → win, R=(11-10)/0.5=2.0；costR=0.0015*10/0.5=0.03 → netR=1.97
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0), ("2026-09-15", 10.5, 11.2, 11.3, 10.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "win" and rec["rValue"] == 2.0 and rec["netR"] == 1.97
    assert rec["entryDate"] == "2026-09-14" and rec["exitDate"] == "2026-09-15"
    assert rec["costR"] == 0.03 and rec["ambiguous"] is False


def test_buy_loss_hits_stop():
    bars = make_bars(
        [("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0), ("2026-09-15", 10.0, 9.4, 10.1, 9.4, 1000.0)]
    )  # low 9.4 ≤ stop 9.5
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
    bars = make_bars([("2026-09-14", 9.7, 9.6, 9.8, 9.5, 1000.0), ("2026-09-15", 9.5, 9.4, 9.6, 9.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["entryDate"] == "2026-09-14" and rec["outcome"] == "loss"


def test_flat_exits_at_window_end_close():
    # 窗口内触及 entry 后 target/stop 均未触 → 平出，exit=末收盘 10.1，R=(10.1-10)/0.5=0.2
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.3, 9.9, 1000.0), ("2026-09-15", 10.1, 10.1, 10.4, 10.0, 1000.0)])
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
    bars = make_bars(
        [
            (
                "2026-09-11",
                9.0,
                9.0,
                9.0,
                9.0,
                1000.0,
            ),  # 创建当日：若被误用会立刻 win（low≤entry≤target）→ 该用例防前视
            ("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
        ]
    )
    rec = replay_plan(make_plan(validity="本月内"), bars, 0.0015, today=TODAY)
    assert rec["entryDate"] == "2026-09-14"  # 创建当日 bar 未参与


def test_unclosed_today_bar_excluded():
    # today=09-15：09-15 的 bar 是"今天"，未收盘不参与 → 09-14 触及 entry 后窗口无后续 → open
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0), ("2026-09-15", 11.5, 11.6, 11.7, 11.0, 1000.0)])
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
    assert rec["outcome"] == "open"  # 窗口未闭合 → 进行中（非 notEntered）


# —— slice_window 窗口终点语义直测（数值按 createdAt=09-11 钉死）——


def test_slice_window_expiry_day_bar_included():
    # validity=本周内 → 过期日 09-13；today=09-16 → end_date=min(09-13, 09-16)=09-13，已闭合
    # 窗口 = (09-11, 09-13] → 09-12、09-13；prevClose 用 09-11（创建当日 bar 可作 prev）
    bars = make_bars(
        [
            ("2026-09-11", 10, 10, 10, 10, 1000.0),
            ("2026-09-12", 10, 10, 10, 10, 1000.0),
            ("2026-09-13", 10, 10, 10, 10, 1000.0),
            ("2026-09-14", 10, 10, 10, 10, 1000.0),
        ]
    )  # 09-14 > 过期日 → 不在窗口
    window, prev, closed = slice_window(bars, 1_789_084_800_000, "本周内", today="2026-09-16")
    assert [b["date"] for b in window] == ["2026-09-12", "2026-09-13"]  # 过期日当日 bar 参与（r3.1 消歧）
    assert closed is True and prev is not None and prev["date"] == "2026-09-11"


def test_slice_window_excludes_unclosed_today_bar():
    # today=09-15：09-15 的 bar 未收盘，即使 ≤ end_date 也排除（B2）
    bars = make_bars(
        [
            ("2026-09-11", 10, 10, 10, 10, 1000.0),
            ("2026-09-14", 10, 10, 10, 10, 1000.0),
            ("2026-09-15", 10, 10, 10, 10, 1000.0),
        ]
    )
    window, _, closed = slice_window(bars, 1_789_084_800_000, "本月内", today="2026-09-15")
    assert [b["date"] for b in window] == ["2026-09-14"]  # 09-15（今天）被 < today 排除
    assert closed is False  # end_date=min(09-30,09-15)=09-15 不早于今天


def test_shanghai_date_str_pins_creation_ms():
    # 补充钉死用例（brief 用例集未含）：钉死时区换算事实，并使 shanghai_date_str 导入被使用（避免 F401）
    assert shanghai_date_str(1_789_084_800_000) == "2026-09-11"


# —— Task 4: 市场微结构（跳空成交价 + 停牌跳过 + 前收盘涨跌停一字板顺延 + B2 双触跳空修正）——
# brief Step 1/Step 3 测试块转录。转录调整（语义中立，详见 task-4-report.md）：
# 1. 两个一字板用例的 brief 注释均为「主板 10%」口径，而 make_plan 默认 code=300750（创业板 → 20%），
#    故按注释意图改用 make_plan(code="600519")（沪深主板 → 10%）。
# 2. test_limit_down 按 brief 自带的构造修正落定：prevClose=10.1 → limitDown=round(10.1*0.9,2)=9.09，
#    09-15 取 9.05（≤9.09 且 high==low）方为一字跌停。
# 3. test_suspended_day_skipped 的停牌 bar 报价 9.4（brief 原值 10.1 触不到 stop/target，在 T3 循环下
#    不具判别力；9.4 若被误作交易日，low 9.4 ≤ stop 9.5 会误判 09-15 loss——正是本用例要抓的行为）。
# 一字板用例一律先手算 limitUp/limitDown 再造 bar（brief 示范纪律）。


def test_gap_fill_stop_executes_at_open():
    # 跳空低开：open 9.2 < stop 9.5 → exit=open（更劣），R=(9.2-10)/0.5=-1.6，gapFill=True
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0), ("2026-09-15", 9.2, 9.1, 9.6, 9.0, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "loss" and rec["gapFill"] is True
    assert rec["rValue"] == -1.6 and rec["netR"] == -1.63


def test_gap_fill_target_executes_at_open():
    # 跳空高开：open 11.5 > target 11 → exit=open（更优），R=(11.5-10)/0.5=3.0，gapFill=True
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0), ("2026-09-15", 11.5, 11.6, 11.7, 11.2, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "win" and rec["gapFill"] is True and rec["rValue"] == 3.0


def test_suspended_day_skipped():
    # 09-14 触及 entry；09-15 停牌（volume 0）跳过；09-16 到 target → win
    # （停牌报价 9.4：若误作交易日，low 9.4 ≤ stop 9.5 会误判 09-15 loss）
    bars = make_bars(
        [
            ("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
            ("2026-09-15", 9.4, 9.4, 9.4, 9.4, 0.0),
            ("2026-09-16", 10.5, 11.2, 11.3, 10.4, 1000.0),
        ]
    )
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "win" and rec["exitDate"] == "2026-09-16"


def test_limit_up_one_price_defers_buy_entry():
    # 主板 10%：prevClose=10.0 → limitUp=11.0；09-14 一字涨停（high==low==11.0, vol>0）→ 买入入场顺延
    # 09-15 正常触及 entry → entryDate=09-15，limitDeferred=True
    bars = make_bars(
        [
            ("2026-09-11", 10.0, 10.0, 10.0, 10.0, 1000.0),  # prev bar（窗口前一根）
            ("2026-09-14", 11.0, 11.0, 11.0, 11.0, 1000.0),  # 一字涨停
            ("2026-09-15", 10.5, 10.6, 10.8, 9.8, 1000.0),
        ]
    )
    rec = replay_plan(make_plan(code="600519"), bars, 0.0015, today=TODAY)
    assert rec["entryDate"] == "2026-09-15" and rec["limitDeferred"] is True and rec["outcome"] == "flat"


def test_limit_down_one_price_defers_sell_exit():
    # buy 已入场后 09-15 一字跌停（prevClose=10.1 → limitDown=round(10.1*0.9,2)=9.09）
    # → 卖出离场顺延；09-16 low 9.0 ≤ stop 9.5 → loss；limitDeferred=True
    # （brief 构造修正保留：09-15 取 9.05 ≤ 9.09 且 high==low 方为一字跌停）
    bars = make_bars(
        [
            ("2026-09-11", 10.0, 10.0, 10.0, 10.0, 1000.0),
            ("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),  # 入场
            ("2026-09-15", 9.05, 9.05, 9.05, 9.05, 1000.0),  # 一字跌停（9.05 ≤ 9.09）
            ("2026-09-16", 9.0, 9.0, 9.2, 9.0, 1000.0),
        ]
    )
    rec = replay_plan(make_plan(code="600519"), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "loss" and rec["limitDeferred"] is True


def test_deferred_limit_down_day_leaves_no_phantom_gap_fill():
    # 回归：跌停一字 09-15 open 9.05 < stop 9.5 属跳空离场价，但当日离场顺延（不可成交）
    # → gapFill 不得留幻影标记（旧代码在顺延分支前置赋值）；次日真实跳空止损离场才记位。
    deferred_only = make_bars(
        [
            ("2026-09-11", 10.0, 10.0, 10.0, 10.0, 1000.0),  # 窗口前一根（prevClose 起锚）
            ("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),  # 入场日
            ("2026-09-15", 9.05, 9.05, 9.05, 9.05, 1000.0),  # 一字跌停（prevClose 10.1 → limitDown 9.09）
        ]
    )
    rec = replay_plan(make_plan(code="600519"), deferred_only, 0.0015, today=TODAY)
    # 当日未决出止损离场：outcome 非该 bar 的跳空 loss，窗口走完 → 期末平出（flat）
    assert rec["outcome"] == "flat" and rec["limitDeferred"] is True and rec["gapFill"] is False
    # 次日普通跳空低开（open 9.0 < stop）→ 真实离场日 gapFill=True、loss
    bars = deferred_only + make_bars([("2026-09-16", 9.0, 9.0, 9.2, 9.0, 1000.0)])
    rec2 = replay_plan(make_plan(code="600519"), bars, 0.0015, today=TODAY)
    assert rec2["outcome"] == "loss" and rec2["exitDate"] == "2026-09-16"
    assert rec2["gapFill"] is True and rec2["limitDeferred"] is True and rec2["rValue"] == -2.0


def test_double_touch_with_gap_down_uses_open_exit():
    # 双触 + 跳空低开：open 9.2 < stop 9.5 → exit=9.2，R=(9.2-10)/0.5=-1.6（非 -1），ambiguous+gapFill
    bars = make_bars(
        [
            ("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),  # 入场日
            ("2026-09-15", 9.2, 9.3, 11.2, 9.0, 1000.0),
        ]
    )  # open<stop 且 low≤stop、high≥target
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "loss" and rec["ambiguous"] is True and rec["gapFill"] is True
    assert rec["rValue"] == -1.6


# —— Task 5: bars 批量获取 + 聚合编排（fetch_all_bars 双层缓存 / aggregate kpis+四维分组 / review_plans）——
# brief 测试块转录。转录修正（非语义中立，详见 task-5-report.md）：
# test_aggregate_excludes_null_netr_defensively 的计数断言由 brief 原稿 decided == 2 / winRate == 1.0
# （注释"2 胜 0 败"）修正为 decided == 3 / winRate == 0.667（注释"2 胜 1 败"）：输入含 2 胜 1 败三条
# 记录，spec r3 B3（spec.md:43「decided = 胜 + 败」，None 净R 只剔均值不剔计数——正是本用例注释
# 「计数仍按 outcome」的本意）与 brief 自带实现、上方 kpis 主用例一致地给出 3/0.667；
# 均值剔除断言（avgWinR 1.97 / expectancyR 0.47，B3 的核心）原样保留。


def test_aggregate_kpis_and_null_placeholders():
    recs = [
        {**_rec("win", 2.0, 0.03)},
        {**_rec("win", 1.5, 0.03)},
        {**_rec("loss", -1.0, 0.03)},
        {**_rec("flat", 0.2, 0.03)},
        {**_rec("notEntered", None, None)},
        {**_rec("open", None, None)},
        {**_rec("invalid", None, None)},
    ]
    out = aggregate(recs)
    k = out["kpis"]
    # netR：win 1.97 / win 1.47 / loss -1.03 / flat 0.17（cost=0.03）
    assert k["total"] == 7 and k["decided"] == 3 and k["flatCount"] == 1
    assert k["winRate"] == 0.667  # 2 胜 / 3 decided
    assert k["expectancyR"] == 0.645  # (1.97+1.47-1.03+0.17)/4
    assert k["avgWinR"] == 1.72 and k["avgLossR"] == -1.03
    assert k["payoffRatio"] == 1.67  # 1.72 / 1.03
    assert k["notEnteredRate"] == 0.2  # 1 / (3+1+1)
    assert k["openCount"] == 1 and k["invalidCount"] == 1


def test_aggregate_null_when_no_losses():
    recs = [{**_rec("win", 2.0, 0.0)}, {**_rec("win", 1.0, 0.0)}]
    k = aggregate(recs)["kpis"]
    assert k["payoffRatio"] is None and k["avgLossR"] is None  # 败样本空 → null（绝不造数）


def test_groups_small_sample_flag():
    recs = [{**_rec("win", 2.0, 0.03), "source": "manual"}] * 3
    out = aggregate(recs)
    g = next(row for row in out["groups"]["source"] if row["key"] == "manual")
    assert g["smallSample"] is True and g["decided"] + g["flatCount"] < 5


def test_aggregate_excludes_null_netr_defensively():
    # 评审 B3：settled 记录 netR 为 None（回放异常）→ 显式剔除均值，绝不静默归零；计数仍按 outcome
    recs = [{**_rec("win", 2.0, 0.03)}, {**_rec("win", None, None)}, {**_rec("loss", -1.0, 0.03)}]
    k = aggregate(recs)["kpis"]
    assert k["decided"] == 3 and k["winRate"] == 0.667  # 计数按结局：2 胜 1 败（spec r3 B3，转录修正）
    assert k["avgWinR"] == 1.97  # netR None 的 win 剔除后均值（非 (2.0+0)/2）
    assert k["expectancyR"] == round((1.97 - 1.03) / 2, 3)  # 0.47


def test_review_plans_days_filter_and_flow():
    # 相对时钟（fix round 1）：不再钉死 createdAtMs——400 天前恒在 90 天窗口外，昨天恒在窗口内
    old = int((datetime.now() - timedelta(days=400)).timestamp() * 1000)
    new = int((datetime.now() - timedelta(days=1)).timestamp() * 1000)
    plans = [make_plan(id="old", createdAtMs=old), make_plan(id="new", createdAtMs=new)]

    def fake_load_bars(codes):
        return {
            c: make_bars(
                [("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0), ("2026-09-15", 10.5, 11.2, 11.3, 10.4, 1000.0)]
            )
            for c in codes
        }

    out = review_plans(plans, days=90, fee_rate=0.0015, load_bars=fake_load_bars)
    ids = {i["planId"] for i in out["items"]}
    assert "new" in ids and "old" not in ids  # days=90 只留 createdAt 近 90 天
    out_all = review_plans(plans, days=0, fee_rate=0.0015, load_bars=fake_load_bars)
    assert {"old", "new"} <= {i["planId"] for i in out_all["items"]}


def test_fetch_all_bars_uses_db_cache_and_raises_on_failure(session_db, monkeypatch):
    # DB 命中：save 一份 bfq bars（昨日 bar——恒新于 7 天 stale 阈值，fix round 1 相对时钟）后 fetch 不打上游
    fresh_date = (datetime.now(SHANGHAI) - timedelta(days=1)).strftime("%Y-%m-%d")
    bars = make_bars([(fresh_date, 10, 10, 10, 10, 1000.0)])
    storage.save_market_bars("300750", bars, adjustment="")
    calls: list[str] = []

    class FakeRouter:
        def load_history(self, code, limit, is_index=False, adjustment="qfq"):
            calls.append(code)
            return []

    out = fetch_all_bars(["300750"], FakeRouter())
    assert out["300750"][0]["date"] == fresh_date and calls == []
    # 上游失败：无缓存 code 抛 ReviewUpstreamError 且 codes 齐全

    class BadRouter:
        def load_history(self, code, limit, is_index=False, adjustment="qfq"):
            raise RuntimeError("upstream down")

    # 封闭性：本段不得依赖共享 DB 里 market_bars 恰为空（冒烟/真实使用会留新鲜 bfq 缓存，
    # 命中即绕过 BadRouter → 不抛错）。强制缓存未命中，验证的是上游失败聚合路径本身。
    monkeypatch.setattr(storage, "load_market_bars", lambda *a, **k: [])
    with pytest.raises(ReviewUpstreamError) as ei:
        fetch_all_bars(["600519", "000001"], BadRouter())
    assert sorted(ei.value.codes) == ["000001", "600519"]


def _rec(outcome, r, cost):
    return {
        "planId": "x",
        "code": "300750",
        "source": "manual",
        "direction": "buy",
        "entry": 10.0,
        "stop": 9.5,
        "target": 11.0,
        "validity": "本月内",
        "status": "执行中",
        "outcome": outcome,
        "rValue": r,
        "netR": None if r is None else round(r - (cost or 0), 3),
        "costR": cost,
        "entryDate": None,
        "exitDate": None,
        "ambiguous": False,
        "gapFill": False,
        "limitDeferred": False,
    }


# ---------------------------------------------------------------------------
# API 端点（Task 6）：GET /api/plans/review + GET /api/screener/scan/history
# patch 目标：review_plans 走 "backend.plan_review.review_plans" 属性访问（app.py 同款）；
# get_workspace / list_scan_history 走 app 模块名（与 test_backend_api.py 的
# monkeypatch.setattr(app_module, ...) 惯例一致——app.py 顶层 from-import 直引名称）。
# ---------------------------------------------------------------------------

client = TestClient(app_module.app)  # 模块级共享；各用例自 monkeypatch，互不残留


def test_review_endpoint_happy_path(monkeypatch):
    plans = [make_plan(id="p1"), make_plan(id="p2", source="scan:trend_breakout")]
    monkeypatch.setattr(app_module, "get_workspace", lambda *a, **k: {"plans": plans})
    monkeypatch.setattr(
        "backend.plan_review.review_plans",
        lambda ps, days, fee_rate, **k: {"kpis": {"total": len(ps)}, "groups": {}, "items": []},
    )
    r = client.get("/api/plans/review", params={"days": 90})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"kpis", "groups", "items", "degraded"} and body["kpis"]["total"] == 2
    # feeRate 以字符串数值传入 → FastAPI float 解析兼容（评审遗留观察）
    ok = client.get("/api/plans/review", params={"days": 0, "feeRate": "0.002"})
    assert ok.status_code == 200


def test_review_endpoint_422_days_and_feerate(monkeypatch):
    monkeypatch.setattr("backend.plan_review.review_plans", lambda *a, **k: {})  # 422 在调用前返回，不触达
    assert client.get("/api/plans/review", params={"days": 45}).status_code == 422
    assert client.get("/api/plans/review", params={"days": 90, "feeRate": 0.9}).status_code == 422
    assert client.get("/api/plans/review", params={"days": 90, "feeRate": -0.1}).status_code == 422


def test_review_endpoint_502_logs_failed_codes(monkeypatch, caplog):
    def boom(plans, days, fee_rate, **k):
        raise ReviewUpstreamError(["600519", "000001"])

    caplog.set_level(logging.ERROR)
    monkeypatch.setattr(app_module, "get_workspace", lambda *a, **k: {"plans": []})
    monkeypatch.setattr("backend.plan_review.review_plans", boom)
    r = client.get("/api/plans/review")
    assert r.status_code == 502
    assert r.json()["detail"]["failedCodes"] == ["600519", "000001"]  # codes 进 detail（冻结契约）
    assert "600519" in caplog.text and "000001" in caplog.text  # 失败 code 落日志（r3.1）


def test_scan_history_endpoint(monkeypatch):
    run_at = datetime.now(SHANGHAI)
    rows = [
        {
            "id": 7,
            "strategyId": "trend_breakout",
            "runAt": run_at,
            "status": "ok",
            "hitCount": 3,
            "newCount": 1,
            "elapsedMs": 1200,
            "traceId": "t1",
        }
    ]  # list_scan_history 实际行键（storage.py:875）：已 camelCase，runAt 为 datetime，无 mode 列
    seen: dict = {}

    def fake_list(strategy_id=None, limit=50):
        seen["strategy_id"] = strategy_id
        seen["limit"] = limit
        return rows

    monkeypatch.setattr(app_module, "list_scan_history", fake_list)
    r = client.get("/api/screener/scan/history", params={"strategyId": "trend_breakout"})
    assert r.status_code == 200
    body = r.json()["history"][0]
    assert body["hitCount"] == 3 and body["strategyId"] == "trend_breakout"  # camelCase 出参
    assert body["runAtMs"] == int(run_at.timestamp() * 1000)  # 机器时间戳口径（ms，同 storage.py:288 惯例）
    assert seen["strategy_id"] == "trend_breakout" and seen["limit"] == 30  # 默认 limit=30
    assert client.get("/api/screener/scan/history", params={"limit": 999}).status_code == 200
    assert seen["limit"] == 200  # 1..200 夹取


def test_review_endpoint_real_chain_with_load_history_facade(monkeypatch):
    """冒烟缺陷回归：bars 预取必须走路由历史路径 _load_history_with_fallback（旧接线 assist_router
    无 load_history → fetch_all_bars 对每个 code 抛 AttributeError → ReviewUpstreamError → 502）。

    真实 review_plans/fetch_all_bars/slice_window/replay_plan 链路，只在历史路径
    （app 模块名）与 storage 缓存读写两个边界打桩；bfq 口径 adjustment="" 须全程透传。
    """
    now_ms = int(datetime.now(SHANGHAI).timestamp() * 1000)
    plan = {
        "id": "chain-1",
        "code": "600519",
        "name": "链路冒烟",
        "direction": "buy",
        "entry": 10.0,
        "stop": 9.5,
        "target": 11.0,
        "position": 10,
        "validity": "长期",
        "status": "执行中",
        "triggered": False,
        "source": "manual",
        "createdAtMs": now_ms - 10 * 86_400_000,
    }
    bars = [
        {
            "date": (datetime.now(SHANGHAI) - timedelta(days=d)).strftime("%Y-%m-%d"),
            "open": 10.4,
            "high": 11.5,
            "low": 9.9,
            "close": 11.0,
            "volume": 1000,
        }
        for d in range(9, 1, -1)  # 8 根：创建日(now-10d)之后、今天之前的连续日期
    ]
    saved: list = []
    calls: list[dict] = []

    def fake_with_fallback(code, limit, is_index=False, adjustment="qfq", source=None):
        calls.append({"code": code, "limit": limit, "is_index": is_index, "adjustment": adjustment})
        return list(bars), "live", None, "tencent"

    monkeypatch.setattr(app_module, "get_workspace", lambda *a, **k: {"plans": [plan]})
    monkeypatch.setattr(app_module, "_load_history_with_fallback", fake_with_fallback)
    monkeypatch.setattr(storage, "load_market_bars", lambda *a, **k: [])
    monkeypatch.setattr(storage, "save_market_bars", lambda code, rows, adjustment="": saved.append((code, adjustment)))
    r = client.get("/api/plans/review", params={"days": 90})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kpis"]["total"] == 1 and body["kpis"]["winRate"] == 1.0
    assert body["items"][0]["outcome"] == "win" and body["items"][0]["netR"] == 1.97
    assert body["degraded"] == []  # live 路径无降级
    assert saved and saved[0] == ("600519", "")  # bfq 落缓存，adjustment 恒空串
    # 复盘走路由历史路径且 bfq 口径透传：adjustment=""、limit=300、非指数
    assert len(calls) == 1 and calls[0]["adjustment"] == ""
    assert calls[0]["code"] == "600519" and calls[0]["limit"] == 300 and calls[0]["is_index"] is False


def test_review_endpoint_local_fallback_disclosed_in_degraded(monkeypatch, caplog):
    """红线（round-3 N1）：本地 market_bars 兜底命中不得静默——响应 degraded 列表 + review_degraded 告警如实披露。"""
    now_ms = int(datetime.now(SHANGHAI).timestamp() * 1000)
    plan = {
        "id": "deg-1",
        "code": "600519",
        "direction": "buy",
        "entry": 10.0,
        "stop": 9.5,
        "target": 11.0,
        "validity": "长期",
        "status": "执行中",
        "createdAtMs": now_ms - 10 * 86_400_000,
    }
    bars = [
        {
            "date": (datetime.now(SHANGHAI) - timedelta(days=d)).strftime("%Y-%m-%d"),
            "open": 10.4,
            "high": 11.5,
            "low": 9.9,
            "close": 11.0,
            "volume": 1000,
        }
        for d in range(9, 1, -1)
    ]

    def fake_local(code, limit, is_index=False, adjustment="qfq", source=None):
        return list(bars), "local", "2026-01-05", "local"  # 兜底命中：陈旧 as_of 如实带出

    monkeypatch.setattr(app_module, "get_workspace", lambda *a, **k: {"plans": [plan]})
    monkeypatch.setattr(app_module, "_load_history_with_fallback", fake_local)
    monkeypatch.setattr(storage, "load_market_bars", lambda *a, **k: [])
    monkeypatch.setattr(storage, "save_market_bars", lambda *a, **k: None)
    caplog.set_level(logging.WARNING)
    r = client.get("/api/plans/review", params={"days": 90})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] == ["600519"] and body["items"][0]["outcome"] == "win"  # 降级不阻断回算
    assert "review_degraded code=600519 as_of=2026-01-05" in caplog.text
