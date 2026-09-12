"""组合风险视图 Task 3：回放引擎核心（入场微结构 / 名义额静态分配 / 主层离场 / 毛净双序列）。

表驱动助手沿用 tests/test_plan_review.py 的 make_bars / make_plan 风格。
钉死事实：CREATED_MS = 1_767_312_000_000 = 2026-01-02（周五）08:00 Asia/Shanghai。
bar 元组顺序与 test_plan_review 一致：(date, open, close, high, low, volume)。

oracle 说明（评审低1 修正）：`replay_plan` 只在本文件里作为对照 oracle 导入——引擎本体
backend/portfolio_risk.py 不 import replay_plan，微结构等价性由 test_equiv_vs_plan_review 锁住。

分歧口径（评审 I-2 钉桩）：「同日双触且 open>target（高开跳空）」一角，复盘 gap_exit 按
stop/target 双侧检查（plan_review.py:143）→ 记 gapFill；组合只在**实际成交价≠触发价**时记
→ 该角不记（双触成交价恒=stop 侧）。成交价与离场日仍逐项等价，equiv 断言经 `equiv_skip`
仅豁免该角的 gapFill 比较（场景 double_touch_gap_up，组合侧行为另由 expect 钉死）。
"""

from __future__ import annotations

from typing import Any

import pytest
from backend.plan_review import replay_plan
from backend.portfolio_risk import compose_nav, nav_dates, replay_positions

CREATED_MS = 1_767_312_000_000  # 2026-01-02（周五）
CREATED_MS_DEC = 1_764_547_200_000  # 2025-12-01（本月内 → 过期 2025-12-31）
WINDOW_START = "2026-01-05"  # 创建日次一交易日（窗起点日 bar 参与回放）
TODAY = "2026-01-14"  # 全部测试 bar 均 < TODAY（未收盘 bar 已由 fetch 层排除）
EQUIV_TODAY = "2026-02-05"  # > 本月内过期日 01-31 → oracle 窗口已闭合（flat 分支可达）
FEE = 0.0015


def make_bars(rows: list[tuple[str, float, float, float, float, float]]) -> list[dict[str, Any]]:
    """(date, open, close, high, low, volume) → bar dicts，amount/change 补默认。"""
    return [
        {"date": d, "open": o, "close": c, "high": h, "low": lo, "volume": v, "amount": 1_000_000.0, "change": 1.0}
        for d, o, c, h, lo, v in rows
    ]


def make_plan(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "P1",
        "code": "600519",
        "direction": "buy",
        "entry": 10.0,
        "stop": 9.5,
        "target": 11.0,
        "capital": 10000,
        "position": 30,
        "validity": "长期",
        "status": "执行中",
        "triggered": {},
        "createdAtMs": CREATED_MS,
        "note": "",
        "createdAt": "08:00",
        "source": None,
        "relatedPlan": None,
        "exitMode": None,
    }
    base.update(over)
    return base


def replay_one(
    plan: dict[str, Any],
    bars: list[dict[str, Any]],
    window_start: str = WINDOW_START,
    today: str = TODAY,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """单计划回放便捷口：返回 (position | None, events)。"""
    positions, events = replay_positions([plan], {str(plan["code"]): bars}, window_start, today, "core", {})
    return (positions[0] if positions else None), events


# —— brief 用例 1：跳空入场成交价 + 名义额静态分配（基准=NAV₀=1）——


def test_entry_gap_and_notional() -> None:
    # 窗 [01-05..01-13]，plan position=30 → notional=0.30×NAV₀=0.30；
    # 01-06 open=9.6 < entry=10 → 成交价 9.6、入场日 01-06；入场日起 marks=close（事件日 mark=close）
    bars = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),  # 创建当日：窗口外，仅供 prevClose 起锚
            ("2026-01-05", 10.6, 10.5, 10.7, 10.4, 1000.0),  # low 10.4 > entry 10 → 未触及
            ("2026-01-06", 9.6, 9.8, 9.9, 9.6, 1000.0),  # 跳空低开：open 9.6 < entry → 成交 9.6
            ("2026-01-07", 9.9, 10.2, 10.3, 9.8, 1000.0),
            ("2026-01-08", 10.2, 10.4, 10.5, 10.0, 1000.0),
        ]
    )
    pos, events = replay_one(make_plan(), bars)
    assert pos is not None and events == []
    assert pos["planId"] == "P1" and pos["code"] == "600519"
    assert pos["entryDate"] == "2026-01-06" and pos["entryPrice"] == pytest.approx(9.6)
    assert pos["positionPct"] == pytest.approx(30.0)
    assert pos["baseNav"] == pytest.approx(1.0)  # 01-06 之前唯一已知收盘 NAV = 01-05 收盘 = 1.0
    assert pos["requestedNotional"] == pytest.approx(0.30) and pos["scaled"] is False
    assert pos["notional"] == pytest.approx(0.30)
    assert pos["shares"] == pytest.approx(0.30 / 9.6)
    assert pos["marks"] == {"2026-01-06": 9.8, "2026-01-07": 10.2, "2026-01-08": 10.4}
    assert pos["status"] == "holding" and pos["exit"] is None
    assert pos["preWindow"] is False

    dates = nav_dates({str(pos["code"]): bars}, WINDOW_START, TODAY)
    assert dates == ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    r = compose_nav([pos], dates, 0.0)
    # 现金 0.70 + 0.03125 股 × close
    assert r["gross"] == pytest.approx([1.0, 1.00625, 1.01875, 1.025])
    assert r["net"] == pytest.approx(r["gross"]) and r["feeCum"] == pytest.approx([0.0, 0.0, 0.0, 0.0])
    assert r["feeSum"] == pytest.approx(0.0)
    assert r["cashEnd"] == pytest.approx(0.70) and r["exposureEnd"] == pytest.approx(0.325)
    assert r["mddGross"] == pytest.approx(0.0)


# —— brief 用例 2：当日各新分配等比缩放至剩余现金 + scaling 事件快照 ——


def test_scaling_event() -> None:
    # 两 plan 30%+80% 同日触发 → 当日请求合计 1.10 > 可用现金 1.00
    # → 当日各新分配等比缩放（系数 1/1.1）：A 0.272727 / B 0.727273，比例 3:8 保持、存量永不动
    plan_a = make_plan(id="A", code="600519", entry=10.0, stop=9.5, target=11.0, position=30)
    plan_b = make_plan(id="B", code="000001", entry=20.0, stop=19.0, target=22.0, position=80)
    bars_a = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.2, 10.3, 10.4, 9.9, 1000.0),  # low 9.9 ≤ entry 10，open 10.2 ≥ entry → 成交 10
            ("2026-01-06", 10.3, 10.4, 10.6, 10.1, 1000.0),
        ]
    )
    bars_b = make_bars(
        [
            ("2026-01-02", 20.6, 20.5, 20.7, 20.4, 1000.0),
            ("2026-01-05", 20.2, 20.4, 20.6, 19.8, 1000.0),  # low 19.8 ≤ entry 20，open 20.2 ≥ entry → 成交 20
            ("2026-01-06", 20.4, 20.6, 20.8, 20.2, 1000.0),
        ]
    )
    bars_map = {"600519": bars_a, "000001": bars_b}
    positions, events = replay_positions([plan_a, plan_b], bars_map, WINDOW_START, TODAY, "core", {})
    by_id = {p["planId"]: p for p in positions}
    assert set(by_id) == {"A", "B"}
    factor = 1.0 / 1.10
    assert by_id["A"]["requestedNotional"] == pytest.approx(0.30)
    assert by_id["A"]["notional"] == pytest.approx(0.30 * factor), "等比缩放含当日首笔新分配（spec §5.2）"
    assert by_id["B"]["requestedNotional"] == pytest.approx(0.80)
    assert by_id["B"]["notional"] == pytest.approx(0.80 * factor)
    assert by_id["A"]["notional"] + by_id["B"]["notional"] == pytest.approx(1.0), "分配恰好用尽可用现金"
    assert by_id["A"]["notional"] / by_id["B"]["notional"] == pytest.approx(3.0 / 8.0), "等比：相对权重不变"
    assert by_id["A"]["scaled"] is True and by_id["B"]["scaled"] is True
    # 存量不动：01-06 无任何新分配/缩放事件
    assert [e for e in events if e["date"] != "2026-01-05"] == []

    scaling = [e for e in events if e["type"] == "scaling"]
    assert len(scaling) == 2 and all(e["date"] == "2026-01-05" for e in scaling)
    assert all(set(e) == {"type", "date", "code", "detail"} for e in scaling)
    ev_b = next(e for e in scaling if e["code"] == "000001")
    assert set(ev_b["detail"]) == {"positionPct", "baseNav", "requestedNotional", "allocatedNotional"}
    assert ev_b["detail"]["positionPct"] == pytest.approx(80.0)
    assert ev_b["detail"]["baseNav"] == pytest.approx(1.0)
    assert ev_b["detail"]["requestedNotional"] == pytest.approx(0.80)
    assert ev_b["detail"]["allocatedNotional"] == pytest.approx(0.80 * factor)

    r = compose_nav(positions, ["2026-01-05", "2026-01-06"], 0.0)
    assert r["cashEnd"] == pytest.approx(0.0), "缩放后现金被完全分配"
    assert r["exposureEnd"] == pytest.approx(r["gross"][-1])


# —— brief 用例 3：同日双触保守取 stop（跳空则取 open）——


def test_stop_target_race_conservative() -> None:
    # 同日 high>=target 且 low<=stop → 按 stop 价离场（跳空取 open）
    gap_bars = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.2, 10.3, 10.4, 9.8, 1000.0),  # 入场：low 9.8 ≤ entry，open ≥ entry → 成交 10
            ("2026-01-06", 9.45, 9.5, 11.15, 9.37, 1000.0),  # 双触 + open 9.45 < stop → 执行 9.45
        ]
    )
    pos, events = replay_one(make_plan(), gap_bars)
    assert pos is not None and events == []
    assert pos["status"] == "closed" and pos["exit"] is not None
    assert pos["exit"]["date"] == "2026-01-06" and pos["exit"]["reason"] == "stop"
    assert pos["exit"]["price"] == pytest.approx(9.45)
    assert pos["gapFill"] is True and pos["ambiguous"] is True
    assert pos["marks"] == {"2026-01-05": 10.3}, "离场日不再计 mark（转现金）"
    assert pos["proceeds"] == pytest.approx(0.30 / 10.0 * 9.45)

    # 无跳空的双触 → 执行价 = stop 本身，gapFill 不留幻影
    plain_bars = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.2, 10.3, 10.4, 9.8, 1000.0),
            ("2026-01-06", 9.8, 9.6, 11.2, 9.4, 1000.0),  # 双触，open 9.8 > stop → 执行 stop 9.5
        ]
    )
    pos2, _ = replay_one(make_plan(id="P2"), plain_bars)
    assert pos2 is not None and pos2["exit"] is not None
    assert pos2["exit"]["price"] == pytest.approx(9.5) and pos2["gapFill"] is False
    assert pos2["ambiguous"] is True and pos2["exit"]["reason"] == "stop"


# —— brief 用例 4：毛/净双序列恒等式（feeCum 数组 + feeSum 标量）——


def test_nav_identity_gross_net() -> None:
    bars = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.6, 10.5, 10.7, 10.4, 1000.0),  # 未触及
            ("2026-01-06", 10.0, 9.9, 10.1, 9.8, 1000.0),  # 入场 10（open=entry）→ 市值 0.297
            ("2026-01-07", 9.9, 9.7, 10.0, 9.6, 1000.0),  # mark 9.7 → 0.291
            ("2026-01-08", 9.4, 9.5, 9.6, 9.3, 1000.0),  # 跳空止损：执行 9.4 → 变现 0.282
        ]
    )
    pos, _ = replay_one(make_plan(), bars)
    assert pos is not None
    dates = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    r = compose_nav([pos], dates, fee_rate=0.0015)
    for t in range(len(r["dates"])):
        assert r["gross"][t] - r["net"][t] == pytest.approx(r["feeCum"][t])  # P0 修正：feeCum 数组
    assert r["feeCum"][-1] == pytest.approx(r["feeSum"])  # 标量=末位数组值
    assert r["dates"] == dates
    # 手推：入场费 0.30×0.0015=0.00045（01-06）；离场费 0.282×0.0015=0.000423（01-08）
    assert r["feeCum"] == pytest.approx([0.0, 0.00045, 0.00045, 0.000873])
    assert r["gross"] == pytest.approx([1.0, 0.997, 0.991, 0.982])
    assert r["net"] == pytest.approx([1.0, 0.99655, 0.99055, 0.981127])
    assert all(r["net"][t] <= r["gross"][t] for t in range(len(dates))), "net ≤ gross"
    assert all(r["feeCum"][t + 1] >= r["feeCum"][t] for t in range(len(dates) - 1)), "费用单调累计"
    assert r["mddGross"] == pytest.approx(0.018) and r["mddNet"] == pytest.approx(1 - 0.981127)
    assert r["cashEnd"] == pytest.approx(0.982) and r["exposureEnd"] == pytest.approx(0.0)
    assert r["mddNet"] >= r["mddGross"]


# —— brief 用例 5：与 plan_review.replay_plan 逐项等价（oracle 对照）——

SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "win_target",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.4, 10.3, 10.6, 10.2, 1000.0),  # low 10.2 > entry → 未触及
            ("2026-01-06", 10.2, 10.4, 10.6, 9.9, 1000.0),  # 入场成交 10
            ("2026-01-07", 10.5, 11.1, 11.3, 10.4, 1000.0),  # 止盈 11（limitUp 11.44 内）
        ],
        "expect": {"entryDate": "2026-01-06", "outcome": "win", "exitDate": "2026-01-07"},
    },
    {
        "name": "loss_stop",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.4, 10.3, 10.6, 10.2, 1000.0),
            ("2026-01-06", 10.2, 10.4, 10.6, 9.9, 1000.0),
            ("2026-01-07", 10.0, 9.4, 10.1, 9.4, 1000.0),  # low 9.4 ≤ stop，open > stop → 执行 9.5
        ],
        "expect": {"entryDate": "2026-01-06", "outcome": "loss", "exitDate": "2026-01-07"},
    },
    {
        "name": "gap_win_open_above_target",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-06", 10.2, 10.4, 10.6, 9.9, 1000.0),
            ("2026-01-07", 11.2, 11.3, 11.4, 11.1, 1000.0),  # 高开跳空 → 执行 open 11.2
        ],
        "expect": {"gapFill": True, "outcome": "win", "exitDate": "2026-01-07"},
    },
    {
        "name": "gap_loss_open_below_stop",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-06", 10.2, 10.4, 10.6, 9.9, 1000.0),
            ("2026-01-07", 9.4, 9.3, 9.5, 9.2, 1000.0),  # 低开跳空 → 执行 open 9.4
        ],
        "expect": {"gapFill": True, "outcome": "loss"},
    },
    {
        "name": "double_touch_conservative",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-06", 10.2, 10.4, 10.6, 9.9, 1000.0),
            ("2026-01-07", 10.0, 10.0, 11.2, 9.4, 1000.0),  # 双触无跳空 → stop 9.5
        ],
        "expect": {"ambiguous": True, "gapFill": False, "outcome": "loss"},
    },
    {
        "name": "double_touch_gap_down",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-06", 10.2, 10.4, 10.6, 9.9, 1000.0),
            ("2026-01-07", 9.45, 9.5, 11.15, 9.37, 1000.0),  # 双触 + 低开 → 9.45
        ],
        "expect": {"ambiguous": True, "gapFill": True, "outcome": "loss"},
    },
    {
        # 评审 I-2 分歧角：双触 + open 11.2 > target 11 → 复盘 gap_exit 双侧检查记 gapFill=True，
        # 成交价仍=stop 9.5；组合按"成交价≠触发价"不记（expect 钉组合侧）。
        # equiv 断言本角只比成交价/离场日（equiv_skip 豁免 gapFill），口径见模块 docstring。
        "name": "double_touch_gap_up",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.2, 10.3, 10.4, 9.9, 1000.0),  # 入场 @10
            ("2026-01-06", 11.2, 10.8, 11.3, 9.4, 1000.0),  # 双触（low 9.4≤stop，high 11.3≥target）+ 高开
        ],
        "equiv_skip": ["gapFill"],
        "expect": {"ambiguous": True, "gapFill": False, "outcome": "loss", "exitDate": "2026-01-06"},
    },
    {
        "name": "suspended_day_skipped",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-06", 10.2, 10.4, 10.6, 9.9, 1000.0),
            ("2026-01-07", 9.4, 9.4, 9.4, 9.4, 0.0),  # 停牌：9.4 若被误判会假止损
            ("2026-01-08", 10.5, 11.2, 11.3, 10.4, 1000.0),
        ],
        "expect": {"outcome": "win", "exitDate": "2026-01-08"},
    },
    {
        "name": "limit_up_one_price_defers_entry",
        "plan_over": {"entry": 12.0, "stop": 9.0, "target": 13.0},
        "bars": [
            ("2026-01-02", 9.0, 9.0, 9.0, 9.0, 1000.0),  # prevClose 9.0 → 主板 limitUp 9.9
            ("2026-01-05", 9.9, 9.9, 9.9, 9.9, 1000.0),  # 一字涨停：low 9.9 < entry 12 亦不可买 → 顺延
            ("2026-01-06", 10.0, 10.2, 10.4, 9.7, 1000.0),  # 次日入场：open 10.0 < entry → 成交 10.0
            ("2026-01-07", 10.6, 11.0, 11.1, 10.5, 1000.0),
        ],
        "expect": {"limitDeferred": True, "entryDate": "2026-01-06"},
    },
    {
        "name": "limit_down_one_price_defers_exit",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-06", 10.2, 10.4, 10.6, 9.9, 1000.0),  # 入场 10
            ("2026-01-07", 9.36, 9.36, 9.36, 9.36, 1000.0),  # 一字跌停（10.4×0.9）→ 卖不出，顺延
            ("2026-01-08", 9.2, 9.2, 9.3, 9.1, 1000.0),  # 次日低开止损 → 执行 9.2
        ],
        "expect": {"limitDeferred": True, "gapFill": True, "outcome": "loss", "exitDate": "2026-01-08"},
    },
    {
        "name": "not_entered",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-06", 10.6, 10.8, 11.0, 10.5, 1000.0),  # high ≥ target 但从未入场 → 无离场判定
        ],
        "expect": {"entryDate": None, "status": "notEntered", "outcome": "notEntered"},
    },
    {
        "name": "flat_at_window_end",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-06", 10.2, 10.4, 10.6, 9.9, 1000.0),
            ("2026-01-07", 10.4, 10.6, 10.8, 10.3, 1000.0),
        ],
        "expect": {"status": "holding", "outcome": "flat", "exitDate": "2026-01-07"},
    },
    {
        "name": "gap_through_entry",
        "bars": [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 9.8, 9.9, 10.0, 9.6, 1000.0),  # 跳空穿越 entry：组合成交 open 9.8（复盘 R 基准恒记 10）
            ("2026-01-06", 9.9, 10.1, 10.3, 9.7, 1000.0),
            ("2026-01-07", 10.4, 11.0, 11.1, 10.3, 1000.0),
        ],
        "expect": {"entryDate": "2026-01-05", "entryPrice": 9.8, "outcome": "win", "exitDate": "2026-01-07"},
    },
    {
        "name": "star_20pct_one_price_not_limit_up",
        "plan_over": {"code": "300750"},
        "bars": [
            ("2026-01-02", 9.0, 9.0, 9.0, 9.0, 1000.0),  # 创业板 20% → limitUp 10.8
            ("2026-01-05", 9.9, 9.9, 9.9, 9.9, 1000.0),  # 一字 9.9 < 10.8 → 非涨停一字，照常入场
            ("2026-01-06", 10.0, 10.4, 10.6, 9.8, 1000.0),
        ],
        "expect": {"limitDeferred": False, "entryDate": "2026-01-05", "entryPrice": 9.9, "outcome": "flat"},
    },
]


@pytest.mark.parametrize("case", SCENARIOS, ids=[str(c["name"]) for c in SCENARIOS])
def test_equiv_vs_plan_review(case: dict[str, Any]) -> None:
    plan_over: dict[str, Any] = case.get("plan_over") or {}
    plan = make_plan(validity="本月内", **plan_over)
    bars = make_bars(list(case["bars"]))
    oracle = replay_plan(plan, bars, FEE, today=EQUIV_TODAY)
    pos, events = replay_one(plan, bars, WINDOW_START, EQUIV_TODAY)
    assert pos is not None and events == [], "主层单计划不应产生缩放事件"

    outcome = oracle["outcome"]
    risk = float(plan["entry"]) - float(plan["stop"])
    implied = None if oracle["rValue"] is None else float(plan["entry"]) + float(oracle["rValue"]) * risk

    # 入场/离场日期与价格逐项 == replay_plan rec 字段
    assert pos["entryDate"] == oracle["entryDate"], outcome
    if outcome in ("win", "loss"):
        assert pos["status"] == "closed" and pos["exit"] is not None
        assert pos["exit"]["date"] == oracle["exitDate"], outcome
        assert pos["exit"]["reason"] == ("target" if outcome == "win" else "stop")
        assert pos["exit"]["price"] == pytest.approx(implied, abs=1e-3), outcome
    elif outcome == "flat":
        # 复盘在窗口闭合日"平出"（价=末收盘）；组合按"持有到今天"记浮动——同价、不同标签（不算结束）
        assert pos["status"] == "holding" and pos["exit"] is None
        assert oracle["exitDate"] is not None and max(pos["marks"]) == oracle["exitDate"]
        assert pos["marks"][max(pos["marks"])] == pytest.approx(implied, abs=1e-3), outcome
    elif outcome == "open":
        assert pos["status"] == "holding" and pos["exit"] is None
    else:
        assert outcome == "notEntered"
        assert pos["status"] == "notEntered" and pos["notional"] == 0.0 and pos["marks"] == {}
        assert pos["exit"] is None

    for key in ("ambiguous", "gapFill", "limitDeferred"):
        if key in (case.get("equiv_skip") or []):
            # 评审 I-2：双触+高开跳空一角成交价/离场日等价但 gapFill 标记有意分歧
            # （复盘 gap_exit 双侧检查→True；组合按成交价≠触发价→False）。分歧由 expect 单独钉。
            assert pos[key] is False and oracle[key] is True, (key, outcome)
            continue
        assert pos[key] == oracle[key], (key, outcome)
    if oracle["entryDate"] is not None:
        entry_bar = next(b for b in bars if b["date"] == pos["entryDate"])
        # 组合口径成交价 = 跳空穿越取 open，否则取触发价（计划 entry）
        assert pos["entryPrice"] == pytest.approx(min(float(entry_bar["open"]), float(plan["entry"])))
        if float(entry_bar["open"]) >= float(plan["entry"]):
            assert pos["entryPrice"] == pytest.approx(float(oracle["entry"])), "无跳空时与复盘成本基准同价"

    expect: dict[str, Any] = case["expect"]
    for key, want in expect.items():
        if key in ("outcome", "exitDate"):
            assert oracle[key] == want, (key, "oracle 分支未按预期覆盖")
        elif key == "entryPrice":
            assert pos["entryPrice"] == pytest.approx(want)  # 有意分歧处（跳空入场）单独钉死
        else:
            assert pos[key] == want, (key, outcome)


# —— 补充边界（控制器裁定项 + I7/I9 契约面）——


def test_pre_window_exit_not_included() -> None:
    # 窗前已触发且已在窗前离场 → 窗前已结束 → 不纳入（零 position、零事件、NAV 全现金）
    bars = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.2, 10.4, 10.6, 9.9, 1000.0),  # 窗前入场
            ("2026-01-06", 9.6, 9.4, 9.7, 9.4, 1000.0),  # 窗前止损（low 9.4 ≤ stop）
            ("2026-01-07", 10.0, 10.6, 10.7, 9.9, 1000.0),  # 若被误纳入会虚增收益
            ("2026-01-08", 10.6, 11.0, 11.1, 10.5, 1000.0),
        ]
    )
    positions, events = replay_positions([make_plan()], bars_map={"600519": bars}, window_start="2026-01-08", today=TODAY)  # fmt: skip
    assert positions == [] and events == []
    r = compose_nav(positions, ["2026-01-08"], FEE)
    assert r["gross"] == [1.0] and r["net"] == [1.0] and r["feeCum"] == [0.0] and r["feeSum"] == 0.0


def test_pre_window_expiry_not_included() -> None:
    # 静态规则：计划自身回放窗（created..expiry）整体早于组合窗起点 → 不纳入
    bars = make_bars(
        [
            ("2025-12-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2025-12-03", 10.2, 10.4, 10.6, 9.9, 1000.0),  # 12 月入场且持有到过期
            ("2026-01-05", 10.6, 11.0, 11.1, 10.5, 1000.0),  # 组合窗内的涨价不得追溯
        ]
    )
    plan = make_plan(createdAtMs=CREATED_MS_DEC, validity="本月内")  # 过期 2025-12-31 < 01-05
    positions, events = replay_positions([plan], {"600519": bars}, WINDOW_START, TODAY, "core", {})
    assert positions == [] and events == []


def test_pre_window_trigger_allocated_at_window_start() -> None:
    # 窗前已触发且存续 → 窗起点按 positionPct 分配（基准=NAV_起点=1），收益自窗起点起算、窗前不追溯
    bars = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-06", 10.2, 10.4, 10.6, 9.9, 1000.0),  # 窗前触发（不计账）
            ("2026-01-07", 10.4, 10.6, 10.7, 10.2, 1000.0),
            ("2026-01-08", 10.6, 10.8, 10.9, 10.5, 1000.0),  # 窗起点：以该日收盘开仓
            ("2026-01-09", 10.8, 11.2, 11.3, 10.7, 1000.0),  # target=11.5 → 仍持有
        ]
    )
    pos, events = replay_one(make_plan(target=11.5), bars, "2026-01-08", TODAY)
    assert pos is not None and events == []
    assert pos["preWindow"] is True and pos["entryDate"] == "2026-01-08"
    assert pos["baseNav"] == pytest.approx(1.0) and pos["notional"] == pytest.approx(0.30)
    assert pos["entryPrice"] == pytest.approx(10.8), "窗前触发以窗起点收盘开仓（不编造历史成交价）"
    assert pos["marks"] == {"2026-01-08": 10.8, "2026-01-09": 11.2}
    assert pos["status"] == "holding" and pos["exit"] is None
    dates = nav_dates({"600519": bars}, "2026-01-08", TODAY)
    assert dates == ["2026-01-08", "2026-01-09"]
    r = compose_nav([pos], dates, 0.0)
    assert r["gross"] == pytest.approx([1.0, 0.70 + (0.30 / 10.8) * 11.2])  # 开仓当日 NAV 不变


def test_allocation_base_uses_last_known_nav() -> None:
    # 分配基准=分配日之前最近一个已知收盘 NAV；离场现金可再分配（存量不动，不做再平衡）
    bars_a = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.2, 10.4, 10.6, 9.9, 1000.0),  # 入场 10 → 市值 0.312
            ("2026-01-06", 10.6, 11.0, 11.2, 10.5, 1000.0),  # 止盈 11 → 变现 0.33，NAV=1.03
        ]
    )
    bars_b = make_bars(
        [
            ("2026-01-02", 20.6, 20.5, 20.7, 20.4, 1000.0),
            ("2026-01-07", 20.2, 20.4, 20.6, 19.8, 1000.0),  # 入场 20
        ]
    )
    plan_a = make_plan(id="A", code="600519", position=30)
    plan_b = make_plan(id="B", code="000001", entry=20.0, stop=19.0, target=22.0, position=50)
    positions, events = replay_positions([plan_a, plan_b], {"600519": bars_a, "000001": bars_b}, WINDOW_START, TODAY)
    assert events == []
    by_id = {p["planId"]: p for p in positions}
    assert by_id["A"]["baseNav"] == pytest.approx(1.0) and by_id["A"]["notional"] == pytest.approx(0.30)
    assert by_id["A"]["exit"] == {"date": "2026-01-06", "price": pytest.approx(11.0), "reason": "target"}
    assert by_id["B"]["entryDate"] == "2026-01-07"
    assert by_id["B"]["baseNav"] == pytest.approx(1.03), "基准=01-06 收盘 NAV，不是 1"
    assert by_id["B"]["requestedNotional"] == pytest.approx(0.515) and by_id["B"]["scaled"] is False
    assert by_id["B"]["notional"] == pytest.approx(0.515)
    dates = nav_dates({"600519": bars_a, "000001": bars_b}, WINDOW_START, TODAY)
    r = compose_nav(positions, dates, 0.0)
    assert dates == ["2026-01-05", "2026-01-06", "2026-01-07"]
    assert r["gross"] == pytest.approx([1.012, 1.03, 1.0403])
    assert r["mddGross"] == pytest.approx(0.0)


def test_holding_to_window_end_marks_float_and_suspension_carries_prev_close() -> None:
    # 窗尾未离场 = holding 按最后 close 进 NAV（不算结束）；停牌日 mark 沿用前收且 prevClose 不更新
    bars = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.2, 10.4, 10.6, 9.9, 1000.0),  # 入场 10
            ("2026-01-06", 9.4, 9.4, 9.4, 9.4, 0.0),  # 停牌：9.4 不得进 mark、不得触止损
            ("2026-01-07", 10.5, 10.7, 10.9, 10.3, 1000.0),  # 仍持有（high 10.9 < target 11）
        ]
    )
    pos, _ = replay_one(make_plan(), bars)
    assert pos is not None
    assert pos["status"] == "holding" and pos["exit"] is None
    assert pos["marks"] == {"2026-01-05": 10.4, "2026-01-06": 10.4, "2026-01-07": 10.7}
    dates = nav_dates({"600519": bars}, WINDOW_START, TODAY)
    assert dates == ["2026-01-05", "2026-01-06", "2026-01-07"]
    r = compose_nav([pos], dates, FEE)
    for t in range(len(dates)):
        assert r["gross"][t] - r["net"][t] == pytest.approx(r["feeCum"][t])
    assert r["gross"] == pytest.approx([1.012, 1.012, 1.021])
    assert r["feeCum"] == pytest.approx([0.0, 0.00045, 0.00045])
    assert r["mddGross"] == pytest.approx(0.0)
    assert r["cashEnd"] == pytest.approx(0.70) and r["exposureEnd"] == pytest.approx(0.321)


def test_compose_nav_empty_positions_is_flat_one() -> None:
    r = compose_nav([], ["2026-01-05", "2026-01-06"], FEE)
    assert r["gross"] == [1.0, 1.0] and r["net"] == [1.0, 1.0] and r["feeCum"] == [0.0, 0.0]
    assert r["feeSum"] == 0.0 and r["mddGross"] == 0.0 and r["mddNet"] == 0.0
    assert r["cashEnd"] == 1.0 and r["exposureEnd"] == 0.0
    assert compose_nav([], [], FEE)["dates"] == []


def test_core_layer_ignores_sell_plans_and_links() -> None:
    # 主层（layer='core'）：sell 计划零参与，links 入参不参与判定（T4 才消费）
    buy = make_plan(id="B1", code="600519")
    sell = make_plan(id="S1", code="600519", direction="sell", relatedPlan="B1", exitMode="race")
    bars = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.2, 10.3, 10.4, 9.8, 1000.0),
            ("2026-01-06", 10.4, 11.2, 11.3, 10.3, 1000.0),
        ]
    )
    positions, events = replay_positions(
        [buy, sell], {"600519": bars}, WINDOW_START, TODAY, "core", {"B1": {"sell": sell, "exitMode": "race"}}
    )
    assert [p["planId"] for p in positions] == ["B1"] and events == []
    assert positions[0]["status"] == "closed" and positions[0]["exit"] is not None
    assert positions[0]["exit"]["reason"] == "target", "主层离场只由 stop/target 决定，与关联 sell 无关"


def test_closed_layer_deferred_to_task4() -> None:
    with pytest.raises(NotImplementedError):
        replay_positions(
            [make_plan()],
            {"600519": make_bars([("2026-01-05", 10, 10, 10, 10, 1.0)])},
            WINDOW_START,
            TODAY,
            "closed",
            {},
        )


def test_invalid_plans_and_missing_bars_are_skipped_without_fabrication() -> None:
    bars = make_bars([("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0), ("2026-01-05", 10.2, 10.3, 10.4, 9.8, 1000.0)])
    # entry<=0 / entry-stop<=0 / position 缺失 / 非 buy → 全部跳过，绝不造仓
    for over in ({"entry": 0.0}, {"stop": 10.5}, {"position": None}, {"direction": "sell"}):
        plan = make_plan(**over)
        positions, events = replay_positions([plan], {"600519": bars}, WINDOW_START, TODAY, "core", {})
        assert positions == [] and events == [], over
    # 无 bars 的可交易日历缺口：窗内无 bar 的已过期/存续计划 → 不出仓（有 bar 才计账）
    assert replay_positions([make_plan()], {}, WINDOW_START, TODAY, "core", {})[0] == []


# —— 评审补钉（Fix-round-1：I-1 / I-3 / M-1）——


def test_exit_proceeds_counted_once_into_later_allocation_base() -> None:
    # I-1 离场回笼单计：A 窗内止损回笼 0.94 后，隔 01-07/01-08 两个轴日 B 才分配——
    # base 必须仍是"单次回笼后"的 0.94；若每个后续轴日重复入账，01-09 会膨胀为 2.82。
    # （test_allocation_base_uses_last_known_nav 的下一日即分配，恰好躲不过该缺陷——评审指认。）
    bars_a = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.2, 10.3, 10.4, 9.9, 1000.0),  # A 入场 @10，notional=1.0（position=100）
            ("2026-01-06", 9.4, 9.5, 9.6, 9.3, 1000.0),  # A 跳空止损 @9.4 → 回笼 0.94，NAV=0.94
            ("2026-01-07", 9.6, 9.7, 9.8, 9.5, 1000.0),  # 离场后第 1 个轴日（重复入账在此暴露）
            ("2026-01-08", 9.7, 9.8, 9.9, 9.6, 1000.0),  # 第 2 个轴日
        ]
    )
    bars_b = make_bars(
        [
            ("2026-01-02", 20.6, 20.5, 20.7, 20.4, 1000.0),
            ("2026-01-09", 20.2, 20.4, 20.6, 19.8, 1000.0),  # B 入场 @20：基准必须=0.94（非 2.82）
        ]
    )
    plan_a = make_plan(id="A", code="600519", position=100)
    plan_b = make_plan(id="B", code="000001", entry=20.0, stop=19.0, target=22.0, position=50)
    positions, events = replay_positions([plan_a, plan_b], {"600519": bars_a, "000001": bars_b}, WINDOW_START, TODAY)
    assert events == []
    by_id = {p["planId"]: p for p in positions}
    a, b = by_id["A"], by_id["B"]
    assert a["status"] == "closed" and a["exit"] is not None
    assert a["exit"]["date"] == "2026-01-06" and a["exit"]["price"] == pytest.approx(9.4)
    assert a["proceeds"] == pytest.approx(0.94)
    assert b["entryDate"] == "2026-01-09" and b["entryPrice"] == pytest.approx(20.0)
    assert b["baseNav"] == pytest.approx(0.94), "回笼只计一次：01-07/01-08 不得再各 +0.94"
    assert b["requestedNotional"] == pytest.approx(0.47) and b["notional"] == pytest.approx(0.47)
    assert b["scaled"] is False and b["shares"] == pytest.approx(0.47 / 20.0)
    dates = nav_dates({"600519": bars_a, "000001": bars_b}, WINDOW_START, TODAY)
    r = compose_nav(positions, dates, 0.0)
    assert dates == ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
    # 01-06 起纯现金 0.94 平台两日（不膨胀）；01-09 = 0.47 现金 + 0.0235 股 × 20.4 = 0.9494
    assert r["gross"] == pytest.approx([1.03, 0.94, 0.94, 0.94, 0.9494])


def test_suspension_does_not_roll_prev_close_for_one_price_gate() -> None:
    # I-3 停牌+一字板连击：停牌日 close 9.9 恰为真前收 9.0 的涨停价（绊马索）；若停牌日被误滚动
    # prev_close，次日一字板带宽变 10.89 → 9.9 被误判"可正常买入"提前入场。
    # 正确口径：停牌日跳过且 prev_close 仍 9.0 → limitUp=9.9 → 涨停一字不可买 → 顺延至 01-07。
    bars = make_bars(
        [
            ("2026-01-02", 9.0, 9.0, 9.0, 9.0, 1000.0),  # 创建日锚：真 prev_close = 9.0
            ("2026-01-05", 9.9, 9.9, 9.9, 9.9, 0.0),  # 停牌：不得更新 prev_close
            ("2026-01-06", 9.9, 9.9, 9.9, 9.9, 1000.0),  # 一字板 = 正确带宽涨停位 → 买顺延
            ("2026-01-07", 10.0, 10.2, 10.4, 9.7, 1000.0),  # 次日正常：low 9.7 ≤ entry → 成交 10
        ]
    )
    pos, events = replay_one(make_plan(entry=10.0, stop=9.0, target=12.0), bars)
    assert pos is not None and events == []
    assert pos["limitDeferred"] is True, "一字板可成交性判定必须用跳过停牌后的前收（9.0→带宽 9.9）"
    assert pos["entryDate"] == "2026-01-07" and pos["entryPrice"] == pytest.approx(10.0)
    assert pos["marks"] == {"2026-01-07": 10.2}
    assert pos["status"] == "holding" and pos["exit"] is None


def test_compose_nav_key_set_matches_i9() -> None:
    # M-1：I9 九键键集钉桩（防增删/改名漂移），空仓与含仓返回同构。
    keys = {"dates", "gross", "net", "feeCum", "feeSum", "cashEnd", "exposureEnd", "mddGross", "mddNet"}
    assert set(compose_nav([], ["2026-01-05", "2026-01-06"], FEE)) == keys
    bars = make_bars(
        [
            ("2026-01-02", 10.6, 10.5, 10.7, 10.4, 1000.0),
            ("2026-01-05", 10.2, 10.3, 10.4, 9.9, 1000.0),
        ]
    )
    pos, _ = replay_one(make_plan(), bars)
    assert pos is not None
    assert set(compose_nav([pos], nav_dates({"600519": bars}, WINDOW_START, TODAY), FEE)) == keys
