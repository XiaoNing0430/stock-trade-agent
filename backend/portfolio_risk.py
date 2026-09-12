"""组合风险视图——回放引擎核心（Task 3：主层入场 / 名义额静态分配 / 主层离场 / 毛净双序列）。

契约：docs/superpowers/specs/2026-09-12-portfolio-risk-view-spec.md r3.2 §5.1/§5.2/§5.4/§5.5；
冻结接口 I7 `replay_positions` / I9 `compose_nav`（I6 `plan_review.FEE_RATE_MAX` 同任务落地）。

纯函数、只读、零写计划。微结构复用 `plan_review` 的同一批纯函数（`slice_window` /
`validity_expiry_date` / `_limit_prices` / `_board_pct`）；本模块**不 import `replay_plan`**——
与复盘引擎的语义等价由 `tests/test_portfolio_engine.py::test_equiv_vs_plan_review`
以 `replay_plan` 作 oracle 逐项锁住（oracle import 只出现在测试文件）。

单位：NAV 无量纲、起点 = 1（名义额 0.30 即"起始净值的 30%"）；金额换算在聚合层（meta.equity）。
数组不做 round：毛净恒等式逐日精确成立，显示位数由前端 format 层负责。

微结构口径（与复盘 engine 的对照，逐条；详见 task-3-report.md）：
1. 触及判定 entry `low<=entry` / 止损 `low<=stop` / 止盈 `high>=target`；同日双触保守取 stop —— 同复盘（决议 3）。
2. 停牌（volume<=0）跳过判定且**不更新 prev_close** —— 同复盘；组合侧另按裁定"沿用前收 mark"。
3. 一字板可成交性：涨停一字不可买（顺延）、跌停一字不可卖（顺延）、跌停一字可买 —— 同复盘（决议 20）。
4. 跳空成交价：开盘越过触发价 → 以 open 成交（复盘同款，gapFill 只落在真实成交当日）。
   **有意分歧**：入场跳空（open<entry）组合以 open 建仓，复盘 R 基准恒记计划 entry
   （计划 §Task3 + brief 用例 1；复盘只需 R 归一，组合需真实成本基算浮动盈亏）。
5. 窗口：计划自身窗 = (创建日, min(过期日, today)]（复用 slice_window，未收盘 bar 由取数层排除）；
   组合 `window_start` 只切断**计账**，不切断**判定**——窗前生命周期用于"是否存续到窗内"的归属。
6. 分配（§5.2 r3 统一规则）：`notional = 分配日之前最近一个已知收盘 NAV × positionPct/100`，
   窗起点日触发视同窗前触发（基准 = NAV_起点 = 1，无特判）；当日累计请求 > 当日开始现金
   → 当日各**新**分配等比缩放至剩余现金（存量永不动、不再平衡），每次缩放记 `scaling` 事件（含 §5.5 快照）。
7. 窗尾未离场 = holding，按最后可得收盘进 NAV 浮动，**不算结束**（持有到"今天"）。
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Any

from backend.plan_review import _board_pct, _limit_prices, slice_window, validity_expiry_date

NAV_START = 1.0
_EPS = 1e-12

# 离场原因（I7 position.exit.reason）；T4 闭环层扩展 "relatedSell" 不改既有值
REASON_STOP = "stop"
REASON_TARGET = "target"


def nav_dates(bars_map: dict[str, list[dict[str, Any]]], window_start: str, today: str) -> list[str]:
    """组合 NAV 日频轴 = 各标的 bar 日并集 ∩ [window_start, today)（升序，YYYY-MM-DD 字符串）。"""
    days = {str(bar["date"]) for bars in bars_map.values() for bar in bars if window_start <= str(bar["date"]) < today}
    return sorted(days)


def _exec_price(bar: dict[str, Any], trigger: float, side: str, prev_close: float | None, code: str) -> float | None:
    """复盘同款成交价（跳空 + 一字板可成交性）；返回 None = 当日该方向一字板封死，不可成交。

    `side` 表明被触发的信号种类（决定跳空方向与可成交性），T4 复用不重构（计划观察 1）：
      - `entry`  建仓买单：跳空穿越（open < trigger）按 open 成交，否则按 trigger；涨停一字不可买。
      - `stop`   止损卖单：低开跳空（open < trigger）按 open 成交（更劣），否则按 trigger；跌停一字不可卖。
      - `target` 止盈卖单：高开跳空（open > trigger）按 open 成交（更优），否则按 trigger；跌停一字不可卖。
    `prev_close` 必须是**当日收盘更新之前**的前收（与复盘同序），涨跌停带按板块涨跌幅计算。
    """
    limits = _limit_prices(prev_close, _board_pct(str(code or "")))
    close = float(bar["close"])
    if limits and float(bar["high"]) == float(bar["low"]):
        if side == "entry" and close >= limits[0]:  # 涨停一字：买单排不进
            return None
        if side in (REASON_STOP, REASON_TARGET) and close <= limits[1]:  # 跌停一字：卖单出不去
            return None
    open_ = float(bar["open"])
    if side == REASON_TARGET:
        return open_ if open_ > trigger else trigger
    return open_ if open_ < trigger else trigger  # entry / stop：下行穿越取 open


@dataclass
class _PositionState:
    """单计划（buy）在回放中的可变状态；窗内计账，窗前只判定。"""

    plan_id: str
    code: str
    entry: float
    stop: float
    target: float
    validity: str
    created_ms: int
    pct: float
    bars_by_date: dict[str, dict[str, Any]]
    prev_close: float | None
    entered: bool = False
    accounted: bool = False  # 是否已进入组合账（窗内开仓）
    pre_window: bool = False  # 窗前已触发、窗起点补记开仓
    aborted: bool = False  # 窗前已结束 → 整计划不纳入（§5.2 跨界规则）
    pending: bool = False  # 当日有待结算的分配意图（金额见 pending_requested/pending_price）
    pending_requested: float = 0.0  # 当日待分配意图：requestedNotional
    pending_price: float = 0.0  # 当日待分配意图：成交价（shares = allocated/price）
    settled: bool = False  # 离场回笼已入账（日期轴继续前进时防止重复计现金）
    base_nav: float = NAV_START
    requested: float = 0.0
    notional: float = 0.0
    shares: float = 0.0
    entry_date: str | None = None
    entry_price: float | None = None
    exit: dict[str, Any] | None = None
    marks: dict[str, float] = field(default_factory=dict)
    last_mark: float | None = None
    scaled: bool = False
    ambiguous: bool = False
    gap_fill: bool = False
    limit_deferred: bool = False

    @property
    def proceeds(self) -> float | None:
        if self.exit is None or not self.accounted:
            return None
        return self.shares * float(self.exit["price"])

    def open(self, date: str, price: float, close: float, base_nav: float) -> None:
        """窗内开仓计账：mark=收盘、登记当日分配意图（pending 由 replay_positions 结算为股数）。

        正常入场 `price`=触发/跳空成交价；窗前触发存续到窗内的补记开仓 `price`=close（收盘开仓）。
        """
        self.accounted = True
        self.entry_date = date
        self.entry_price = price
        self.base_nav = base_nav
        self.requested = base_nav * self.pct / 100.0
        self.pending = True
        self.pending_requested = self.requested
        self.pending_price = price
        self.last_mark = close
        self.marks[date] = close

    def to_position(self) -> dict[str, Any]:
        status = "notEntered" if not self.accounted else ("closed" if self.exit is not None else "holding")
        return {
            "planId": self.plan_id,
            "code": self.code,
            "direction": "buy",
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "validity": self.validity,
            "createdAtMs": self.created_ms,
            "positionPct": self.pct,
            "status": status,
            "baseNav": self.base_nav,
            "requestedNotional": self.requested,
            "notional": self.notional,
            "scaled": self.scaled,
            "preWindow": self.pre_window,
            "entryDate": self.entry_date,
            "entryPrice": self.entry_price,
            "shares": self.shares,
            "exit": self.exit,
            "proceeds": self.proceeds,
            "marks": dict(self.marks),
            "ambiguous": self.ambiguous,
            "gapFill": self.gap_fill,
            "limitDeferred": self.limit_deferred,
        }


def _build_state(
    plan: dict[str, Any], bars_map: dict[str, list[dict[str, Any]]], window_start: str, today: str
) -> _PositionState | None:
    """纳入判定 + 回放窗切片。返回 None = 不纳入主层（非 buy / 参数无效 / 窗前已结束 / 窗内无 bar）。"""
    if str(plan.get("direction") or "buy") != "buy":
        return None  # D2：主层不含 sell（闭环层由 T4 以关联信号参与）
    entry = float(plan.get("entry") or 0)
    stop = float(plan.get("stop") or 0)
    target = float(plan.get("target") or 0)
    if entry <= 0 or stop <= 0 or target <= 0 or entry - stop <= 0:
        return None  # 参数无效（复盘 invalid 同口径）——不造仓、不分配
    pct = float(plan.get("position") or 0)
    if pct <= 0:
        return None  # 无仓位比例即无名义额可分配
    created_ms = int(plan.get("createdAtMs") or 0)
    validity = str(plan.get("validity") or "")
    if validity_expiry_date(created_ms, validity) < window_start:
        return None  # 计划自身回放窗整体早于组合窗起点 → 窗前已结束（静态不追溯）
    bars = bars_map.get(str(plan.get("code") or "")) or []
    window, prev_bar, _closed = slice_window(list(bars), created_ms, validity, today)
    if not any(str(bar["date"]) >= window_start for bar in window):
        return None  # 窗内无可观测 bar：既不开仓也不记 notEntered（无数据不下结论）
    return _PositionState(
        plan_id=str(plan.get("id") or ""),
        code=str(plan.get("code") or ""),
        entry=entry,
        stop=stop,
        target=target,
        validity=validity,
        created_ms=created_ms,
        pct=pct,
        bars_by_date={str(bar["date"]): bar for bar in window},
        prev_close=float(prev_bar["close"]) if prev_bar else None,
    )


def _step(state: _PositionState, date: str, window_start: str, base_nav: float) -> None:
    """单计划处理一个 bar 日：停牌 → 入场/补记开仓 → 离场判定 → mark（顺序与复盘逐字对齐）。

    窗前（date < window_start）只做判定不记账：入场触发/离场触发照常评估（离场判定与复盘
    同序、含入场当日同 bar），但不开仓、不 mark、不产生分配；窗前已离场 → aborted 整计划不纳入。
    """
    if state.aborted or state.exit is not None:
        return  # 终态：窗前已结束 / 已离场，后续日期不再有任何动作
    bar = state.bars_by_date.get(date)
    if bar is None:
        return  # 该标的当日无 bar（日历错位）→ mark 由 compose_nav 前向填充
    close = float(bar["close"])
    volume = float(bar.get("volume") or 0)
    if volume <= 0:  # 停牌：不判触发、prev_close 不更新；持仓沿用前收 mark（不造现价）
        if state.accounted and state.exit is None:
            state.marks[date] = state.last_mark if state.last_mark is not None else close
        return
    prev_close = state.prev_close
    state.prev_close = close  # 与复盘同序：一字板判定用更新前的前收，随后立即滚动
    low = float(bar["low"])
    high = float(bar["high"])

    if not state.entered:
        buy_price = _exec_price(bar, state.entry, "entry", prev_close, state.code)
        if buy_price is None:  # 涨停一字：买单排不进 → 顺延（复盘同款：未入场时先于触及判定）
            state.limit_deferred = True
            return
        if low > state.entry:
            return  # 未触及 entry
        state.entered = True
        if date < window_start:
            state.pre_window = True  # 窗前触发：继续落入下方离场判定（是否存续到窗内的归属），但不计账
        else:
            state.open(date, buy_price, close, base_nav)
            # 入场当日即可触发 stop/target（复盘同款：同一次迭代内继续判定）
    elif not state.accounted:
        if date < window_start:
            pass  # 窗前已触发且存续：只判离场，不开仓不 mark
        else:
            # 窗起点后第一根可交易 bar 以**收盘**补记开仓（不编造历史成交价；开仓即在收盘，本 bar 不再判离场）
            state.open(date, close, close, base_nav)
            return

    if state.exit is not None:
        return
    stop_hit = low <= state.stop
    target_hit = high >= state.target
    if stop_hit and target_hit:
        # 同日双触保守记败（决议 3）：复盘该分支不查一字板——良构计划（target>stop）下跌停一字
        # 不可能同时上穿 target 与下穿 stop，故此处不检查可成交性即与复盘逐字等价。
        state.ambiguous = True
        open_ = float(bar["open"])
        price = open_ if open_ < state.stop else state.stop
        if price != state.stop:
            state.gap_fill = True
        state.exit = {"date": date, "price": price, "reason": REASON_STOP}
        if not state.accounted:
            state.aborted = True  # 窗前已触发且已离场 → 窗前已结束，整计划不纳入
        return
    exit_price: float
    if target_hit:
        resolved = _exec_price(bar, state.target, REASON_TARGET, prev_close, state.code)
        if resolved is None:
            state.limit_deferred = True
            return
        exit_price = resolved
        if exit_price != state.target:
            state.gap_fill = True
        state.exit = {"date": date, "price": exit_price, "reason": REASON_TARGET}
    elif stop_hit:
        resolved = _exec_price(bar, state.stop, REASON_STOP, prev_close, state.code)
        if resolved is None:
            state.limit_deferred = True
            return
        exit_price = resolved
        if exit_price != state.stop:
            state.gap_fill = True
        state.exit = {"date": date, "price": exit_price, "reason": REASON_STOP}
    else:
        if state.accounted:  # 持仓日 mark=close；窗前持仓（未计账）不留 mark
            state.last_mark = close
            state.marks[date] = close
        return
    if not state.accounted:
        state.aborted = True  # 窗前已触发且已离场 → 窗前已结束，整计划不纳入


def replay_positions(
    plans: list[dict[str, Any]],
    bars_map: dict[str, list[dict[str, Any]]],
    window_start: str,
    today: str,
    layer: str = "core",
    links: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """I7：主层组合回放。返回 (positions, events)；position/事件结构见模块 docstring 与 spec §5.5。

    - `window_start` / `today`：YYYY-MM-DD 字符串；`bars_map` 每 code 的 bars 按 date 升序、
      未收盘 bar 已由取数层排除（日期纪律，引擎不再判收盘）。
    - `layer` 本任务只实现 `core`（`closed` 由 Task 4 扩展，签名冻结不变）。
    - `links`（I8 产出 buyPlanId→{sell, exitMode}）在闭环层才参与判定；主层按 D2 零参与，显式忽略。
    - 单趟按日期轴推进：判定 → 当日新分配等比缩放 → 离场结算 → 当日收盘 NAV（供次日分配基准）。
      缩放基准 = **当日开始时的现金**（不含当日离场回笼），与遍历顺序无关（确定性）。
    """
    if layer != "core":
        raise NotImplementedError(
            "组合闭环层（layer='closed'：交易对信号源 / exitMode 四档 / 冲突与冗余事件）由 Task 4 实现"
        )
    if links is None:
        links = {}

    states = [s for s in (_build_state(p, bars_map, window_start, today) for p in plans) if s is not None]
    events: list[dict[str, Any]] = []
    axis = sorted({date for state in states for date in state.bars_by_date})
    cash = NAV_START  # gross 现金（费用只在 compose_nav 的 net 线上体现）
    base_nav = NAV_START  # 最近一个已知收盘 NAV：窗起点之前恒为 1（裁定"窗起点=1"）

    for date in axis:
        day_start_cash = cash
        for state in states:  # 1) 判定 + 登记当日待分配意图
            _step(state, date, window_start, base_nav)
        intents = [s for s in states if s.pending]
        if intents:  # 2) 当日各新分配等比缩放至剩余现金（存量不动）
            requested_total = sum(s.pending_requested for s in intents)
            factor = 1.0 if requested_total <= day_start_cash + _EPS else day_start_cash / requested_total
            for state in intents:
                allocated = state.pending_requested * factor
                state.notional = allocated
                state.scaled = allocated < state.pending_requested - _EPS
                if state.scaled and state.pending_price > 0:
                    events.append(
                        {
                            "type": "scaling",
                            "date": date,
                            "code": state.code,
                            "detail": {
                                "positionPct": state.pct,
                                "baseNav": state.base_nav,
                                "requestedNotional": state.pending_requested,
                                "allocatedNotional": allocated,
                            },
                        }
                    )
                state.shares = allocated / state.pending_price if state.pending_price > 0 else 0.0
                if state.shares <= 0:  # 成交价缺失（异常数据）→ 不记账，绝不造数
                    state.accounted = False
                    state.notional = 0.0
                    state.exit = None
                cash -= state.notional
                state.pending = False
        for state in states:  # 3) 离场结算：回笼本金一次（含入场当日即离场的同日本金回笼）
            if state.exit is not None and state.accounted and not state.settled:
                state.settled = True
                proceeds = state.proceeds
                if proceeds is not None:
                    cash += proceeds
        if date >= window_start:  # 4) 当日收盘 NAV（毛线）→ 次日分配基准
            value = 0.0
            for state in states:
                if not state.accounted or state.entry_date is None or state.entry_date > date:
                    continue
                if state.exit is not None and str(state.exit["date"]) <= date:
                    continue
                # 日期轴升序推进：last_mark 即"截至当日"的最近 mark（当日无 bar 者天然前向沿用）
                if state.last_mark is not None:
                    value += state.shares * state.last_mark
            base_nav = cash + value

    positions = [
        s.to_position() for s in states if not s.aborted and s.code in bars_map and (not s.entered or s.accounted)
    ]
    return positions, events


def compose_nav(positions: list[dict[str, Any]], dates: list[str], fee_rate: float) -> dict[str, Any]:
    """I9：由 positions 组装毛/净双序列 NAV（两序列持仓市值逐日全等，差异严格等于现金差异）。

    费用模型（D7 / 终审 R2）：gross 不计费；net 入场日 `cash −= notional×feeRate`、
    离场日 `cash −= proceeds×feeRate`（proceeds = 离场市值），费用只扣现金端、绝不改市值。
    **基准日费用并入次日**：净线以 gross₀==net₀（feeCum₀≡0）为基准，故若入场/离场费的事件日
    恰为轴首日，其费用顺延到轴第 2 日进入 feeCum 曲线；本金 cash_delta 仍在真实事件日。
    恒等式 `gross_t − net_t == feeCum_t`（且 `feeCum[-1] == feeSum`）由构造逐日成立。
    返回 `{dates, gross, net, feeCum, feeSum, cashEnd, exposureEnd, mddGross, mddNet}`；
    cashEnd/exposureEnd 以 NAV 单位计（起点 = 1），两者之和 = gross 末值。
    """
    axis = list(dates)
    n = len(axis)
    cash_delta = [0.0] * n
    fees_delta = [0.0] * n
    value_sum = [0.0] * n

    for pos in positions:
        notional = float(pos.get("notional") or 0.0)
        entry_date = pos.get("entryDate")
        shares = float(pos.get("shares") or 0.0)
        if notional <= 0.0 or entry_date is None or shares <= 0.0:
            continue  # notEntered / 零名义 → 纯现金贡献
        start = min(bisect_left(axis, str(entry_date)), n - 1)
        if n == 0:
            break
        cash_delta[start] -= notional
        fees_delta[_fee_slot(start, n)] += notional * fee_rate
        marks = pos.get("marks") or {}
        mark_dates = sorted(str(k) for k in marks)
        last = float(marks[mark_dates[0]]) if mark_dates else float(pos.get("entryPrice") or 0.0)
        exit_ = pos.get("exit")
        m_idx = 0
        for j in range(start, n):  # 市值前向填充：停牌/日历缺口沿用前收（绝不填充造数）
            day = axis[j]
            if exit_ is not None and str(exit_["date"]) <= day:
                break
            while m_idx < len(mark_dates) and mark_dates[m_idx] <= day:
                last = float(marks[mark_dates[m_idx]])
                m_idx += 1
            value_sum[j] += shares * last
        if exit_ is not None:
            proceeds = float(pos.get("proceeds") or 0.0)
            end = min(bisect_left(axis, str(exit_["date"])), n - 1)
            if end >= start:
                cash_delta[end] += proceeds
                fees_delta[_fee_slot(end, n)] += proceeds * fee_rate

    gross: list[float] = []
    net: list[float] = []
    fee_cum: list[float] = []
    cash, fee_acc, value = NAV_START, 0.0, 0.0
    for j in range(n):
        cash += cash_delta[j]
        value = value_sum[j]
        fee_acc += fees_delta[j]
        nav = cash + value
        gross.append(nav)
        fee_cum.append(fee_acc)
        net.append(nav - fee_acc)
    return {
        "dates": axis,
        "gross": gross,
        "net": net,
        "feeCum": fee_cum,
        "feeSum": fee_acc,
        "cashEnd": cash if n else NAV_START,
        "exposureEnd": value if n else 0.0,
        "mddGross": _max_drawdown(gross),
        "mddNet": _max_drawdown(net),
    }


def _fee_slot(index: int, n: int) -> int:
    """费用在 feeCum 曲线中的落点：事件日本身，但轴首日（基准日）顺延至第 2 日。

    净线以 feeCum₀≡0（net₀==gross₀）为基准，故落在首日的入场/离场费用并入次日累计；
    n<2 时无处顺延，费用仍留在首日（feeSum 与恒等式不受影响，测试不覆盖该退化形）。
    """
    return index if index > 0 or n < 2 else 1


def _max_drawdown(series: list[float]) -> float:
    """MDD = max(1 − NAV_t / max_{{s≤t}} NAV_s)，峰值起锚 = NAV₀ = 1（spec §5.4）。"""
    peak = NAV_START
    trough = 0.0
    for nav in series:
        peak = max(peak, nav)
        if peak > 0:
            trough = max(trough, 1.0 - nav / peak)
    return trough


# —— 闭环层 I8：交易对配对 ——
# 本函数只管"谁跟谁是一对"；exitMode 矩阵与 conflict/redundant 由仓位状态机（Task 4 第二段）消费。


def _plan_kind(plan: dict) -> str:
    """计划类型：兼容 brief 的 type 键与 storage 的 direction 键，缺省视为 buy（同 _build_state 口径）。"""
    return str(plan.get("type") or plan.get("direction") or "buy").strip().lower()


def _plan_id(plan: dict) -> str:
    pid = plan.get("id")
    return pid if isinstance(pid, str) else ""


def _plan_code(plan: dict) -> str:
    code = plan.get("code")
    return code if isinstance(code, str) else ""


def _plan_date(plan: dict) -> str | None:
    date = plan.get("date")
    return date if isinstance(date, str) and date else None


def _is_archived(plan: dict) -> bool:
    status = plan.get("status")
    return isinstance(status, str) and "归档" in status


def _exit_mode(plan: dict) -> str:
    """离场档位：空/缺省 → race（spec §5.3 默认档）；枚举合法性由 API 层 422 把关，引擎不篡改。"""
    mode = plan.get("exitMode")
    if not isinstance(mode, str):
        return "race"
    return mode.strip() or "race"


def build_links(plans: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    """I8：把 buy+sell 混合计划配成交易对。纯函数、零 IO。

    返回 ``(links, events)``：

    - ``links``：``buyId → {"sell": sell计划dict, "exitMode": str}``。仅 sell 型且其
      ``relatedPlan`` 指向"存在、为 buy、未归档"的计划才配对；一 buy 至多配一 sell，
      按 plans 顺序先到先得；``exitMode`` 空/缺省 → ``"race"``。
    - ``events``：§5.5 结构 ``{type, date, code, detail}``。配不上的 sell →
      ``danglingRelatedPlan``，``detail.reason`` ∈ ``missing``（目标不存在）/ ``not_buy``
      （目标非 buy，含自引用）/ ``archived``（目标已归档）/ ``already_paired``
      （双配：后来者不配对，``detail.pairedWith`` 记在位 sell）。事件 date/code 取自该
      sell 计划，取不到为 ``None`` / ``""``。
    - 无 ``relatedPlan`` 的孤儿 sell 静默跳过（平仓信号看板消费）；buy 自带
      ``relatedPlan`` 一律忽略、不产事件（决策 D2）。
    """
    index: dict[str, dict] = {}
    for plan in plans:
        if not isinstance(plan, dict):
            continue
        pid = _plan_id(plan)
        if pid and pid not in index:
            index[pid] = plan

    links: dict[str, dict] = {}
    events: list[dict] = []
    for plan in plans:
        if not isinstance(plan, dict) or _plan_kind(plan) != "sell":
            continue
        target = plan.get("relatedPlan")
        if not isinstance(target, str) or not target:
            continue
        detail: dict[str, Any] = {"sellPlanId": _plan_id(plan), "relatedPlan": target}
        linked = index.get(target)
        if linked is None:
            detail["reason"] = "missing"
        elif _plan_kind(linked) != "buy":
            detail["reason"] = "not_buy"
        elif _is_archived(linked):
            detail["reason"] = "archived"
        elif target in links:
            detail["reason"] = "already_paired"
            detail["pairedWith"] = _plan_id(links[target]["sell"])
        else:
            links[target] = {"sell": plan, "exitMode": _exit_mode(plan)}
            continue
        events.append(
            {
                "type": "danglingRelatedPlan",
                "date": _plan_date(plan),
                "code": _plan_code(plan),
                "detail": detail,
            }
        )
    return links, events
