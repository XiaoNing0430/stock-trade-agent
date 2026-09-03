"""策略选股因子库：编排 backend/indicators.py 既有指标，纯函数无状态。

因子值约定：float 或 None（数据不足/无法计算时 None，评分按未达标处理，绝不造数）。
"""

from __future__ import annotations

from typing import Any

from backend import indicators as ind

# ma_slope 的回看窗口（MA 相对 5 根前的变化百分比）
_SLOPE_LOOKBACK = 5


class FactorLibrary:
    """本地因子库：bars（旧→新）→ 因子取值 → 条件判定 → 加权评分。"""

    @staticmethod
    def available_factors() -> list[str]:
        return [
            "rsi",
            "ma_slope",
            "ma_arrange",
            "bollinger_pos",
            "momentum",
            "deviation",
            "volume_surge",
        ]

    def compute_factor(self, bars: list[dict[str, Any]], spec: dict[str, Any]) -> float | None:
        """按 spec{name, period, ...} 计算因子最新值；数据不足返回 None。"""
        name = str(spec.get("name", ""))
        period = int(spec.get("period", 14))
        handler = self._handlers().get(name)
        if handler is None:
            raise ValueError(f"unknown factor: {name}")
        return handler(bars, period)

    def score_candidate(self, bars: list[dict[str, Any]], advanced_factors: list[dict[str, Any]]) -> dict[str, Any]:
        """加权评分：score = Σ(达标因子 weight)；返回逐因子明细供前端展示。"""
        factors: dict[str, dict[str, Any]] = {}
        score = 0.0
        for spec in advanced_factors:
            name = str(spec.get("name"))
            weight = float(spec.get("weight", 1))
            try:
                value = self.compute_factor(bars, spec)
            except ValueError:
                raise
            except Exception:
                value = None
            met = evaluate_condition(value, spec.get("operator", "<"), spec.get("threshold"))
            factors[name] = {"value": value, "met": met, "weight": weight}
            if met:
                score += weight
        return {"score": score, "factors": factors}

    # ---- 因子实现（取最新有效值） ----

    def _handlers(self) -> dict[str, Any]:
        return {
            "rsi": self._rsi,
            "ma_slope": self._ma_slope,
            "ma_arrange": self._ma_arrange,
            "bollinger_pos": self._bollinger_pos,
            "momentum": self._momentum,
            "deviation": self._deviation,
            "volume_surge": self._volume_surge,
        }

    @staticmethod
    def _last(values: list[float | None]) -> float | None:
        """取最后一个非 None 值。"""
        for v in reversed(values):
            if v is not None:
                return v
        return None

    def _rsi(self, bars: list[dict[str, Any]], period: int) -> float | None:
        closes = [float(b["close"]) for b in bars]
        return self._last(ind.rsi(closes, period))

    def _ma_slope(self, bars: list[dict[str, Any]], period: int) -> float | None:
        """MA 相对 _SLOPE_LOOKBACK 根前的变化百分比；正数 = 均线向上。"""
        closes = [float(b["close"]) for b in bars]
        mas = ind.ma(closes, period)
        valid = [v for v in mas if v is not None]
        if len(valid) <= _SLOPE_LOOKBACK:
            return None
        prev = valid[-(_SLOPE_LOOKBACK + 1)]
        last = valid[-1]
        if not prev:
            return None
        return (last / prev - 1) * 100

    def _ma_arrange(self, bars: list[dict[str, Any]], period: int) -> float | None:
        """多头排列：close > MA5 > MA(period) → 1.0，否则 0.0；MA 不足 → None。"""
        closes = [float(b["close"]) for b in bars]
        mas = ind.ma(closes, period)
        mas5 = ind.ma(closes, 5)
        long_ma, ma5, close = mas[-1], mas5[-1], closes[-1]
        if long_ma is None or ma5 is None:
            return None
        return 1.0 if close > ma5 > long_ma else 0.0

    def _bollinger_pos(self, bars: list[dict[str, Any]], period: int) -> float | None:
        """收盘价在布林带中的位置：(close-lower)/(upper-lower)；<0 跌破下轨。"""
        closes = [float(b["close"]) for b in bars]
        _, upper, lower = ind.bollinger(closes, period)
        up, low = upper[-1], lower[-1]
        if up is None or low is None or up == low:
            return None
        return (closes[-1] - low) / (up - low)

    def _momentum(self, bars: list[dict[str, Any]], period: int) -> float | None:
        closes = [float(b["close"]) for b in bars]
        return self._last(ind.momentum(closes, period))

    def _deviation(self, bars: list[dict[str, Any]], period: int) -> float | None:
        closes = [float(b["close"]) for b in bars]
        return self._last(ind.deviation(closes, period))

    def _volume_surge(self, bars: list[dict[str, Any]], period: int) -> float | None:
        """最新量 / 近 period 均量；均值 0 → None。"""
        if len(bars) <= period:
            return None
        vols = [float(b["volume"]) for b in bars]
        avg = sum(vols[-period:]) / period
        if not avg:
            return None
        return vols[-1] / avg


_OPERATORS = {
    ">": lambda v, t: v > t,
    "<": lambda v, t: v < t,
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
}


def evaluate_condition(value: float | None, operator: str, threshold: Any) -> bool:
    """条件判定：value 为 None（缺数据）一律未达标，绝不猜测。"""
    if value is None:
        return False
    op = _OPERATORS.get(operator)
    if op is None:
        raise ValueError(f"unsupported operator: {operator}")
    return bool(op(value, threshold))
