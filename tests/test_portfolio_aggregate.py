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
    ], "signalDate=看板锚点（窗内 stop/target 首触日）；本例 bars_map 为空 → 无锚点 → None（不造数）"
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
    assert "truncatedAt" not in out["meta"], (
        "控制器裁定：truncatedAt 归还 spec 原义（ALL 窗 300-bar 起点截断日，T6 端点填）；"
        "列表截断披露 = 各 *Total 与 len 对比（前端显「共 N 条已截断」）"
    )


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
    assert out["concentration"] == {
        "top3": 0.0,
        "hhi": 0.0,
        "industries": [],
        "unknownPct": 0.0,
        "watchPool": None,
        "hypothetical": None,
    }, "无持仓成分 → 空分布（对象恒在，前端免判空）"
    assert out["signals"]["items"] == [] and "口径" in out["signals"]["note"]
    assert out["signalsTotal"] == 0
    assert out["nav"] == {"dates": [], "gross": [], "net": []}, "feeCum/feeSum 由 T6 端点拼入"
    assert out["watchIndex"] is None, "with_watch=False → null（键恒在）"
    assert out["kpis"]["navNow"] is None and out["kpis"]["cashPct"] is None, "空序列不造数"
    assert out["meta"]["layer"] == "core" and out["meta"]["windowStart"] == WINDOW_START
    assert out["meta"]["equity"] == pytest.approx(100_000.0) and out["meta"]["feeRate"] == FEE
    assert out["meta"]["industryCoverage"] == {"known": 0, "total": 0, "staleCount": 0}
    assert "truncatedAt" not in out["meta"], "无截断省略键（§6 truncatedAt? 可选）"

    on = agg(with_watch=True, dates=["2026-01-05", "2026-01-06"])
    assert set(on["watchIndex"]) == {"dates", "values", "equityStart", "note"}
    assert on["watchIndex"]["values"] == [None, None], "空白自选/无数据 → 全 null（不造数）"
    assert on["watchIndex"]["equityStart"] == 1


# —— T5b：集中度（窗尾市值权重 / HHI / Top3 / 未知桶 / coverage）——


def test_concentration_weights_and_hhi() -> None:
    positions = [
        a_position(
            planId="B1",
            code="600519",
            notional=0.6,
            shares=60.0,
            entryDate="2026-01-06",
            entryPrice=10.0,
            marks={"2026-01-06": 9.8, "2026-01-07": 10.0},  # 窗尾 60×10 = 600
        ),
        a_position(
            planId="B2",
            code="000001",
            notional=0.4,
            shares=40.0,
            entryDate="2026-01-06",
            entryPrice=10.0,
            marks={"2026-01-07": 10.0},  # 窗尾 40×10 = 400
        ),
        a_position(  # 窗尾前已离场 → 现金，不参与归一
            planId="B3",
            code="600519",
            status="closed",
            notional=0.5,
            shares=50.0,
            entryDate="2026-01-06",
            entryPrice=10.0,
            marks={"2026-01-06": 9.8},
            exit={"date": "2026-01-07", "price": 9.8, "reason": "stop"},
        ),
        a_position(planId="B4", code="600000", status="notEntered"),  # 未入场 → 不参与
    ]
    industry = {"600519": "白酒", "000001": "银行"}
    out = agg(
        positions=positions,
        industry=industry,
        dates=["2026-01-05", "2026-01-06", "2026-01-07"],
    )
    con = out["concentration"]
    assert set(con) == {"top3", "hhi", "industries", "unknownPct", "watchPool", "hypothetical"}
    assert con["industries"] == [
        {"key": "白酒", "label": "白酒", "pct": pytest.approx(60.0)},
        {"key": "银行", "label": "银行", "pct": pytest.approx(40.0)},
    ], "pct 降序；60/40 两行业"
    assert con["top3"] == pytest.approx(100.0), "不足三只 = 全部（合并展示前三语义）"
    assert con["hhi"] == pytest.approx(0.52), "0.6² + 0.4²"
    assert con["unknownPct"] == pytest.approx(0.0)
    assert con["watchPool"] is None and con["hypothetical"] is None, "with_watch=False → 双 null"
    assert out["meta"]["industryCoverage"] == {"known": 2, "total": 2, "staleCount": 0}

    # 未知桶计入并披露 + 同 code 多计划合并归一（coverage.total 按去重 code 数计）
    unknown = agg(
        positions=positions
        + [
            a_position(
                planId="B5",
                code="600519",
                notional=0.1,
                shares=10.0,  # 同 code 加仓 → 白酒 600+100
                entryDate="2026-01-06",
                entryPrice=10.0,
                marks={"2026-01-07": 10.0},
            ),
            a_position(
                planId="B6",
                code="300750",
                notional=0.1,
                shares=10.0,  # 行业 miss → 未知桶
                entryDate="2026-01-06",
                entryPrice=10.0,
                marks={"2026-01-07": 10.0},
            ),
        ],
        industry=industry,
        industry_status="stale",
        dates=["2026-01-05", "2026-01-06", "2026-01-07"],
    )
    con2 = unknown["concentration"]
    assert con2["industries"] == [
        {"key": "白酒", "label": "白酒", "pct": pytest.approx(700 / 12)},
        {"key": "银行", "label": "银行", "pct": pytest.approx(400 / 12)},
        {"key": "未知", "label": "未知", "pct": pytest.approx(100 / 12)},
    ]
    assert con2["unknownPct"] == pytest.approx(100 / 12), "未命中映射 → 未知桶（参与 HHI/Top3）"
    assert con2["hhi"] == pytest.approx((7 / 12) ** 2 + (4 / 12) ** 2 + (1 / 12) ** 2)
    assert con2["top3"] == pytest.approx(100.0)
    assert unknown["meta"]["industryCoverage"] == {
        "known": 2,
        "total": 3,
        "staleCount": 3,
    }, "total=去重 code 数；status≠fresh 时整表视为可陈旧（保守语义，见实现注释）"

    # 无 mark 的持仓回落 entryPrice（与 compose_nav 同填充口径）：不丢弃，按成本基参与归一
    fallback = agg(
        positions=[
            positions[0],
            a_position(
                planId="B7",
                code="600000",
                notional=0.2,
                shares=20.0,
                entryDate="2026-01-06",
                entryPrice=10.0,
            ),
        ],
        industry=industry,
        dates=["2026-01-05", "2026-01-06", "2026-01-07"],
    )
    assert fallback["concentration"]["industries"] == [
        {"key": "白酒", "label": "白酒", "pct": pytest.approx(75.0)},
        {"key": "未知", "label": "未知", "pct": pytest.approx(25.0)},
    ], "600 vs 20×10=200——marks 缺失走 entryPrice 回落，静默丢弃会只剩白酒 100%"


def test_concentration_920_always_unknown_bucket() -> None:
    """T2-M4 已知限制：920xxx 北交所不在东财 fs universe → 行业恒 miss → 常态「未知」桶，如实披露。"""
    positions = [
        a_position(
            planId="B9",
            code="920001",
            notional=0.3,
            shares=30.0,
            entryDate="2026-01-06",
            entryPrice=10.0,
            marks={"2026-01-07": 10.0},
        )
    ]
    out = agg(
        positions=positions,
        industry={"600519": "白酒", "000001": "银行"},  # 全市场映射也拿不到 920xxx
        dates=["2026-01-05", "2026-01-06", "2026-01-07"],
    )
    con = out["concentration"]
    assert con["industries"] == [{"key": "未知", "label": "未知", "pct": pytest.approx(100.0)}]
    assert con["unknownPct"] == pytest.approx(100.0)
    assert con["top3"] == pytest.approx(100.0) and con["hhi"] == pytest.approx(1.0)
    assert out["meta"]["industryCoverage"] == {"known": 0, "total": 1, "staleCount": 0}


# —— T5b：信号看板（§5.4 锚点 / 尾窗不足 null / 费用估算列 / orphans.signalDate 回填）——


def _board_bars() -> list[dict[str, Any]]:
    return make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.0, 10.1, 10.3, 9.95, 1000.0),  # S2 双触日 → 保守取 stop 9.95
            ("2026-01-06", 9.4, 8.95, 9.6, 8.9, 1000.0),  # S1 stop 首触 → 基准价 9.0
            ("2026-01-07", 8.95, 9.2, 9.4, 8.8, 1000.0),
            ("2026-01-08", 9.2, 9.6, 9.7, 9.1, 1000.0),
            ("2026-01-09", 9.6, 9.4, 9.8, 9.3, 1000.0),
            ("2026-01-12", 9.4, 9.8, 9.9, 9.35, 1000.0),
            ("2026-01-13", 9.8, 11.0, 11.1, 9.7, 1000.0),
        ]
    )


def test_signal_board_truncation() -> None:
    buy = a_plan(id="B1", status="已触发")
    s1 = a_plan(id="S1", direction="sell", code="600519", stop=9.0, target=999.0, position=30)  # 孤儿
    s2 = a_plan(
        id="S2",
        direction="sell",
        code="600519",
        stop=9.95,
        target=10.3,
        position=20,
        relatedPlan="B1",  # 已配对，但因 redundant 事件进看板
    )
    s3 = a_plan(id="S3", direction="sell", code="600519", stop=1.0, target=999.0, position=10)  # 永不触发
    bars = {"600519": _board_bars()}
    events = [
        {
            "type": "redundant",
            "date": "2026-01-08",
            "code": "600519",
            "detail": {
                "sellPlanId": "S2",
                "sellTriggerPrice": 10.3,
                "positionExit": {"date": "2026-01-07", "price": 9.2},
            },
        }
    ]
    out = agg(
        plans=[buy, s1, s2, s3],
        bars_map=bars,
        events=events,
        links={"B1": {"sell": s2, "exitMode": "race"}},
        dates=["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13"],
    )
    items = out["signals"]["items"]
    assert out["signalsTotal"] == 2 and len(items) == 2, "无信号的 S3 不进 items"
    assert set(items[0]) == {
        "planId",
        "code",
        "signalDate",
        "basePrice",
        "chg5",
        "chg10",
        "chg20",
        "maxRebound",
        "maxDrawdown",
        "feeEstPct",
        "paired",
    }
    first, second = items
    assert (first["planId"], first["signalDate"]) == ("S2", "2026-01-05")
    assert first["paired"] is True and first["basePrice"] == pytest.approx(9.95), "同日双触保守取 stop"
    assert first["chg5"] == pytest.approx(9.8 / 9.95 - 1)
    assert first["chg10"] is None and first["chg20"] is None, "尾窗不足 N 日 → null（不造数）"
    assert first["maxRebound"] == pytest.approx(11.1 / 9.95 - 1)
    assert first["maxDrawdown"] == pytest.approx(8.8 / 9.95 - 1)
    assert (second["planId"], second["signalDate"]) == ("S1", "2026-01-06")
    assert second["paired"] is False and second["basePrice"] == pytest.approx(9.0)
    assert second["chg5"] == pytest.approx(11.0 / 9.0 - 1)
    assert second["chg10"] is None and second["chg20"] is None
    assert second["maxRebound"] == pytest.approx(11.1 / 9.0 - 1)
    assert second["maxDrawdown"] == pytest.approx(8.8 / 9.0 - 1)
    assert second["feeEstPct"] == pytest.approx(0.0015 * 2), "名义额×feeRate×2 / 名义额 = feeRate×2"
    assert "口径" in out["signals"]["note"] or "估算" in out["signals"]["note"]
    # orphans.signalDate 同锚点回填（S1/S3 未配对；S2 已配对不进 orphans）
    by_id = {o["planId"]: o["signalDate"] for o in out["orphans"]}
    assert by_id == {"S1": "2026-01-06", "S3": None}


def test_signal_board_gap_and_suspension() -> None:
    """跳空低开按 open 成交（复盘同款）；停牌日（volume≤0）不判触发、不更新前收。"""
    sell = a_plan(id="S1", direction="sell", code="600519", stop=8.0, target=999.0, position=25)
    bars = {
        "600519": make_bars(
            [
                ("2026-01-05", 10.0, 10.0, 10.1, 9.9, 1000.0),
                ("2026-01-06", 10.0, 10.0, 10.1, 7.0, 0.0),  # 停牌：low 7.0 视而不见，prev_close 不更新
                ("2026-01-07", 7.5, 7.4, 7.6, 7.3, 1000.0),  # 跳空低开穿越 8.0 → 基准价 = open 7.5
            ]
        )
    }
    out = agg(plans=[sell], bars_map=bars, dates=["2026-01-05", "2026-01-06", "2026-01-07"])
    item = out["signals"]["items"][0]
    assert item["signalDate"] == "2026-01-07" and item["basePrice"] == pytest.approx(7.5)
    assert item["chg5"] is None and item["maxRebound"] is None and item["maxDrawdown"] is None
    assert item["feeEstPct"] == pytest.approx(0.003)


def test_signal_board_cap_50_with_total() -> None:
    bars = {"600519": _board_bars()}
    plans = [
        a_plan(id=f"S{i:02d}", direction="sell", code="600519", stop=9.0, target=999.0, position=1) for i in range(51)
    ]
    out = agg(plans=plans, bars_map=bars, dates=["2026-01-06"])
    assert len(out["signals"]["items"]) == 50 and out["signalsTotal"] == 51
    assert out["meta"].get("truncatedAt") is None, "truncatedAt 归还 spec 原义：聚合层不产该键"


# —— T5b：自选观察指数（等权 / 缺 bar null 不填充）+ watchPool / hypothetical ——


def test_watch_index_equal_weight_and_missing() -> None:
    watchlist = ["600519", "000001", "688111"]
    bars_map = {
        "600519": make_bars(
            [
                ("2026-01-02", 10.0, 10.0, 10.1, 9.9, 1000.0),
                ("2026-01-05", 10.0, 11.0, 11.1, 10.0, 1000.0),  # +10%
                ("2026-01-06", 11.0, 11.0, 11.2, 10.9, 1000.0),  # 0%
                ("2026-01-08", 11.0, 12.1, 12.2, 11.0, 1000.0),  # +10%（自身轴前收=01-06）
            ]
        ),
        "000001": make_bars(
            [
                ("2026-01-02", 20.0, 20.0, 20.2, 19.8, 1000.0),
                ("2026-01-05", 20.0, 20.0, 20.4, 19.9, 1000.0),  # 0%
                ("2026-01-06", 20.0, 22.0, 22.1, 20.0, 1000.0),  # +10%
            ]
        ),
        "688111": make_bars([("2026-01-05", 5.0, 5.0, 5.1, 4.9, 1000.0)]),  # 无前收 → 永不贡献
    }
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    out = agg(with_watch=True, watchlist=watchlist, bars_map=bars_map, dates=dates)
    wi = out["watchIndex"]
    assert wi["dates"] == dates and wi["equityStart"] == 1
    assert "非持仓" in wi["note"]
    assert wi["values"][0] == pytest.approx(1.05), "等权 avg(+10%, 0%) = +5%"
    assert wi["values"][1] == pytest.approx(1.05 * 1.05)
    assert wi["values"][2] is None, "01-07 全员缺 bar → 该日 null（不填充）"
    assert wi["values"][3] == pytest.approx(1.1025 * 1.1), "null 日之后的日收益仍以前一个可见值续乘"


def test_hypothetical_null_without_flag() -> None:
    watchlist = ["600519", "000001", "920001"]
    industry = {"600519": "白酒", "000001": "银行"}
    settings = {"defaultCapital": 100000, "totalPositionCapPct": 60}
    off = agg(with_watch=False, watchlist=watchlist, industry=industry, settings=settings)
    assert off["watchIndex"] is None
    assert off["concentration"]["watchPool"] is None
    assert off["concentration"]["hypothetical"] is None

    on = agg(with_watch=True, watchlist=watchlist, industry=industry, settings=settings)
    pool = on["concentration"]["watchPool"]
    assert pool["industries"] == [
        {"key": "白酒", "label": "白酒", "pct": pytest.approx(100 / 3)},
        {"key": "银行", "label": "银行", "pct": pytest.approx(100 / 3)},
        {"key": "未知", "label": "未知", "pct": pytest.approx(100 / 3)},
    ], "观察池等权行业分布（不参竞主指标）"
    assert pool["unknownPct"] == pytest.approx(100 / 3)
    hypo = on["concentration"]["hypothetical"]
    assert hypo["industries"][0]["pct"] == pytest.approx(20.0), "capPct 60 / 3 只 = 每只 20（占权益百分比）"
    assert hypo["unknownPct"] == pytest.approx(20.0)
    assert sum(i["pct"] for i in hypo["industries"]) == pytest.approx(60.0)
    assert "假想" in hypo["note"]


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
