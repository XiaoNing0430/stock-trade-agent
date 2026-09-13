"""组合风险视图 Task 5（段1）：aggregate_portfolio 主区块（kpis/nav/exposure/pairs/orphans/events cap 族）。

brief 五例先行（exposure / kpis+planCount / pairs / orphans / cap50+*Total）+ 最小全键形状例
（占位键在位：concentration=None、signals={items,note} 空、watchIndex 占位、meta.industryCoverage 占位）
+ T4 顺带钉（closed 层 sell.entry 脏值 0/None → relatedSell 只按 target 触发，`0 < price` 守卫承重，
直调 replay_positions closed 层）。

I10 逐字签名 / §6 顶层键：见 .superpowers/sdd/2026-09-12-portfolio-risk-view/task-5-context.md。
集中度主体 / 信号看板 / 假想线 / 自选指数计算全部留 T5b（段2）。
bar 元组顺序与引擎测试一致：(date, open, close, high, low, volume)。
钉死事实：CREATED_MS = 1_767_312_000_000 = 2026-01-02（周五）08:00 Asia/Shanghai。
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.portfolio_risk import aggregate_portfolio, replay_positions

CREATED_MS = 1_767_312_000_000  # 2026-01-02（周五）
WINDOW_START = "2026-01-05"
TODAY = "2026-01-14"
FEE = 0.0015


def make_bars(rows: list[tuple[str, float, float, float, float, float]]) -> list[dict[str, Any]]:
    """(date, open, close, high, low, volume) → bar dicts，amount/change 补默认。"""
    return [
        {"date": d, "open": o, "close": c, "high": h, "low": lo, "volume": v, "amount": 1_000_000.0, "change": 1.0}
        for d, o, c, h, lo, v in rows
    ]


def a_plan(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "B1",
        "code": "600519",
        "direction": "buy",
        "entry": 10.0,
        "stop": 9.0,
        "target": 11.0,
        "position": 30,
        "validity": "长期",
        "status": "执行中",
        "createdAtMs": CREATED_MS,
        "relatedPlan": None,
        "exitMode": None,
    }
    base.update(over)
    return base


def a_position(**over: Any) -> dict[str, Any]:
    """to_position() 形状的聚合入参（只带聚合消费的键）。"""
    base: dict[str, Any] = {
        "planId": "B1",
        "code": "600519",
        "status": "holding",
        "positionPct": 30.0,
        "notional": 0.0,
        "shares": 0.0,
        "entryDate": None,
        "entryPrice": None,
        "marks": {},
        "exit": None,
    }
    base.update(over)
    return base


def agg(**over: Any) -> dict[str, Any]:
    """I10 全 keyword 便捷口：缺省全空态，各用例只覆盖相关入参。"""
    kwargs: dict[str, Any] = {
        "plans": [],
        "watchlist": [],
        "settings": {"defaultCapital": 100000, "totalPositionCapPct": 100},
        "bars_map": {},
        "positions": [],
        "dates": [],
        "gross": [],
        "net": [],
        "events": [],
        "links": {},
        "layer": "core",
        "window_start": WINDOW_START,
        "today": TODAY,
        "fee_rate": FEE,
        "industry": {},
        "industry_status": "fresh",
        "with_watch": False,
    }
    kwargs.update(over)
    return aggregate_portfolio(**kwargs)


# —— brief 用例：exposure 快照（执行中+已触发 ΣpositionPct；overCap vs totalPositionCapPct；金额换算）——


def test_exposure_snapshot() -> None:
    plans = [
        a_plan(id="B1", position=30, status="执行中"),
        a_plan(id="B2", position=20, status="已触发"),
        a_plan(id="B3", position=50, status="已过期"),  # 不计：只算执行中+已触发
        a_plan(id="S1", direction="sell", position=40, status="执行中"),  # 不计：sell 不占敞口
    ]
    out = agg(plans=plans, settings={"defaultCapital": 100000, "totalPositionCapPct": 45})
    exp = out["exposure"]
    assert set(exp) == {"plannedPct", "capPct", "overCap", "cashPct", "amountByEquity"}
    assert exp["plannedPct"] == pytest.approx(50.0)
    assert exp["capPct"] == pytest.approx(45.0)
    assert exp["overCap"] is True
    assert exp["amountByEquity"] == pytest.approx(50_000.0)  # equity × plannedPct/100
    assert exp["cashPct"] is None, "无 NAV 数据 → null，不造数"

    ok = agg(plans=plans)  # 默认 cap=100 → 未超限
    assert ok["exposure"]["overCap"] is False and ok["exposure"]["capPct"] == pytest.approx(100.0)

    empty = agg(plans=plans, settings={})  # 键缺失 → capPct 回落 100；equity 缺失 → 0（不造数）
    assert empty["exposure"]["capPct"] == pytest.approx(100.0)
    assert empty["exposure"]["amountByEquity"] == pytest.approx(0.0)


# —— brief 用例：kpis 十字段（含 planCount 嵌套）+ pairCount/orphanSellCount/scalingCount ——


def test_kpis_and_plan_count() -> None:
    positions = [
        a_position(
            planId="B1",
            notional=0.3,
            shares=0.05,
            entryDate="2026-01-06",
            entryPrice=10.0,
            marks={"2026-01-06": 9.8, "2026-01-07": 10.0},
        ),
        a_position(  # 窗内离场：期末不再占市值
            planId="B2",
            status="closed",
            notional=0.2,
            shares=0.02,
            entryDate="2026-01-06",
            entryPrice=10.0,
            marks={"2026-01-06": 9.8},
            exit={"date": "2026-01-07", "price": 9.0, "reason": "stop"},
        ),
        a_position(planId="B3", status="notEntered"),
    ]
    paired_sell = a_plan(id="S1", direction="sell", status="执行中", relatedPlan="B1")
    orphan_sell = a_plan(id="S2", direction="sell", status="已触发")
    plans = [
        a_plan(id="B1", status="执行中"),
        a_plan(id="B2", status="已触发"),
        a_plan(id="B3", status="执行中"),
        a_plan(id="B4", status="已过期"),
        paired_sell,
        orphan_sell,
    ]
    events = [{"type": "scaling"}, {"type": "scaling"}, {"type": "conflict"}]
    out = agg(
        plans=plans,
        positions=positions,
        dates=["2026-01-05", "2026-01-06", "2026-01-07"],
        gross=[1.0, 0.9, 0.95],
        net=[0.99, 0.89, 0.94],
        events=events,
        links={"B1": {"sell": paired_sell, "exitMode": "race"}},
    )
    k = out["kpis"]
    assert set(k) == {
        "navNow",
        "navNowNet",
        "mdd",
        "mddNet",
        "exposurePct",
        "cashPct",
        "planCount",
        "orphanSellCount",
        "pairCount",
        "scalingCount",
    }
    assert k["navNow"] == pytest.approx(0.95) and k["navNowNet"] == pytest.approx(0.94)
    assert k["mdd"] == pytest.approx(0.1), "峰值起锚 NAV₀=1：1−0.9/1.0"
    assert k["mddNet"] == pytest.approx(0.11), "1−0.89/1.0"
    # 期末持仓市值 = B1 0.05 股 × 10.0 = 0.5（B2 期末日前已离场、B3 未入场）
    assert k["exposurePct"] == pytest.approx(0.5 / 0.95), "NAV 占比口径（0..1，§6 cashPct 同款公式字面）"
    assert k["cashPct"] == pytest.approx((0.95 - 0.5) / 0.95)
    assert pytest.approx(k["exposurePct"] + k["cashPct"]) == 1.0
    assert k["planCount"] == {"active": 3, "triggered": 2, "closedInWindow": 1, "notEntered": 1}
    assert k["orphanSellCount"] == 1 and k["pairCount"] == 1 and k["scalingCount"] == 2


# —— brief 用例：pairs（links 已配对）——


def test_pairs_list_built() -> None:
    buy = a_plan(id="B1", entry=10.0, stop=9.0, target=11.0, position=30, status="已触发")
    sell = a_plan(
        id="S1",
        direction="sell",
        code="600519",
        entry=12.0,
        stop=11.5,
        target=13.0,
        status="执行中",
        relatedPlan="B1",
        exitMode="sell_priority",
    )
    out = agg(plans=[buy, sell], links={"B1": {"sell": sell, "exitMode": "sell_priority"}})
    assert out["pairsTotal"] == 1 and len(out["pairs"]) == 1
    p = out["pairs"][0]
    assert p["buyPlanId"] == "B1" and p["sellPlanId"] == "S1" and p["exitMode"] == "sell_priority"
    assert set(p["buy"]) == {"code", "entry", "stop", "target", "positionPct", "status"}
    assert set(p["sell"]) == {"code", "entry", "stop", "target", "status", "exitMode"}
    assert p["buy"]["code"] == "600519" and p["buy"]["positionPct"] == pytest.approx(30.0)
    assert p["buy"]["entry"] == 10.0 and p["buy"]["stop"] == 9.0 and p["buy"]["target"] == 11.0
    assert p["buy"]["status"] == "已触发"
    assert p["sell"]["entry"] == 12.0 and p["sell"]["stop"] == 11.5 and p["sell"]["target"] == 13.0
    assert p["sell"]["status"] == "执行中" and p["sell"]["exitMode"] == "sell_priority"
    assert out["orphans"] == [], "已配对 sell 不进 orphans"


# —— brief 用例：orphans（未配对 sell；signalDate 段1恒 None + T5b TODO）——


def test_orphans_list_built() -> None:
    buy = a_plan(id="B1")
    paired_sell = a_plan(id="S3", direction="sell", relatedPlan="B1")
    no_link_sell = a_plan(id="S1", direction="sell", code="920001")  # 无 relatedPlan → 孤儿
    dangling_sell = a_plan(id="S2", direction="sell", code="600519", relatedPlan="ghost")  # 目标缺失 → 未配对
    plans = [buy, no_link_sell, dangling_sell, paired_sell]
    out = agg(plans=plans, links={"B1": {"sell": paired_sell, "exitMode": "race"}})
    assert out["orphans"] == [
        {"planId": "S1", "code": "920001", "signalDate": None},
        {"planId": "S2", "code": "600519", "signalDate": None},
    ], "signalDate=看板锚点（stop/target 首触日），段2 T5b 补算；段1 恒 None 不造数"
    assert out["orphansTotal"] == 2 and out["kpis"]["orphanSellCount"] == 2


# —— brief 用例：pairs/orphans/signals/events 四族 cap 50 + *Total ——


def test_lists_cap_50_with_total() -> None:
    buys = [a_plan(id=f"B{i:02d}") for i in range(51)]
    paired = [a_plan(id=f"S{i:02d}", direction="sell", relatedPlan=f"B{i:02d}") for i in range(51)]
    orphans = [a_plan(id=f"O{i:02d}", direction="sell") for i in range(51)]
    links = {f"B{i:02d}": {"sell": paired[i], "exitMode": "race"} for i in range(51)}
    events = [{"type": "danglingRelatedPlan", "date": None}] + [
        {"type": "scaling", "date": f"2026-01-{d:02d}", "code": "", "detail": {}} for d in range(51, 1, -1)
    ]
    out = agg(plans=buys + paired + orphans, links=links, events=events)
    assert len(out["pairs"]) == 50 and out["pairsTotal"] == 51
    assert len(out["orphans"]) == 50 and out["orphansTotal"] == 51
    assert out["signals"]["items"] == [] and out["signalsTotal"] == 0  # 看板主体在 T5b
    assert len(out["events"]) == 50 and out["eventsTotal"] == 51
    assert out["events"][0]["date"] is None, "date=None 视同最早（排序选择，报告注明）"
    assert out["events"][1]["date"] == "2026-01-02", "date 字符串升序"
    assert out["kpis"]["pairCount"] == 51, "kpis 用未截断总数"
    assert out["kpis"]["orphanSellCount"] == 51 and out["kpis"]["scalingCount"] == 50
    assert out["meta"]["truncatedAt"] == ["pairs", "orphans", "events"], "meta 记录被截断族名列表"


# —— 最小全键形状例：占位键在位、degraded 缺席（T6 端点并）——


def test_aggregate_shape_placeholders() -> None:
    out = agg()
    assert set(out) == {
        "kpis",
        "nav",
        "exposure",
        "concentration",
        "pairs",
        "pairsTotal",
        "orphans",
        "orphansTotal",
        "signals",
        "signalsTotal",
        "events",
        "eventsTotal",
        "watchIndex",
        "meta",
    }, "degraded 由 T6 端点并入，不在 I10 payload"
    assert out["concentration"] is None, "集中度主体（含 watchPool/hypothetical）在 T5b 替换"
    assert out["signals"] == {"items": [], "note": ""}, "信号看板主体在 T5b 替换"
    assert out["signalsTotal"] == 0
    assert out["nav"] == {"dates": [], "gross": [], "net": []}, "feeCum/feeSum 由 T6 端点拼入"
    assert out["watchIndex"] is None, "with_watch=False → null（键恒在）"
    assert out["kpis"]["navNow"] is None and out["kpis"]["cashPct"] is None, "空序列不造数"
    assert out["meta"]["layer"] == "core" and out["meta"]["windowStart"] == WINDOW_START
    assert out["meta"]["equity"] == pytest.approx(100_000.0) and out["meta"]["feeRate"] == FEE
    assert out["meta"]["industryCoverage"] == {"known": 0, "total": 0, "staleCount": 0}, "T5b 占位"
    assert "truncatedAt" not in out["meta"], "无截断省略键（§6 truncatedAt? 可选）"

    on = agg(with_watch=True, dates=["2026-01-05", "2026-01-06"])
    assert on["watchIndex"] == {
        "dates": ["2026-01-05", "2026-01-06"],
        "values": [None, None],
        "note": "",
    }, "段1仅占位形状；等权指数主体在 T5b"


# —— T4 顺带钉：closed 层 sell.entry 脏值 → relatedSell 只按 target 触发（`0 < price` 守卫承重）——


@pytest.mark.parametrize("dirty", [0, None, "bad"])
def test_closed_dirty_sell_entry_only_triggers_on_target(dirty: Any) -> None:
    buy = a_plan(id="B1", entry=10.0, stop=9.0, target=13.0)
    sell = a_plan(id="S1", direction="sell", entry=dirty, stop=9.6, target=12.0, relatedPlan="B1")
    bars = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),  # 窗前锚（prevClose 起锚）
            ("2026-01-05", 10.2, 10.3, 10.4, 9.9, 1000.0),  # 入场 @10
            ("2026-01-06", 11.0, 11.5, 11.9, 10.9, 1000.0),  # high 11.9 > 脏 entry：无守卫则此日误平 @open
            ("2026-01-07", 11.9, 12.3, 12.5, 11.8, 1000.0),  # high 12.5 ≥ sell.target 12 → 唯一合法触发日
        ]
    )
    positions, events = replay_positions(
        [buy, sell],
        {"600519": bars},
        WINDOW_START,
        TODAY,
        "closed",
        {"B1": {"sell": sell, "exitMode": "race"}},
    )
    assert len(positions) == 1
    pos = positions[0]
    assert pos["exit"] == {"date": "2026-01-07", "price": 12.0, "reason": "relatedSell"}, (
        "脏 entry 经 _as_float 归 0，必须被 _sell_leg 的 `0 < price` 滤除——否则每根 bar 都误触"
    )
    assert pos["status"] == "closed" and events == []
