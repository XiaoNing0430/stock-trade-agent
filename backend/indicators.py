"""技术指标库：纯函数、无状态、输入序列输出对齐序列（预热区 None）。"""

from __future__ import annotations

from typing import Any


def ma(values: list[float], period: int) -> list[float | None]:
    """简单移动平均，预热区 None。"""
    if not values or period < 1:
        return []
    cum = sum(values[:period])
    result: list[float | None] = [None] * (period - 1) + [cum / period]
    for i in range(period, len(values)):
        cum += values[i] - values[i - period]
        result.append(cum / period)
    return result


def ema(values: list[float], period: int) -> list[float]:
    """指数移动平均（无预热区，从首值起）。"""
    if not values or period < 1:
        return []
    multiplier = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append((v - result[-1]) * multiplier + result[-1])
    return result


def rolling_std(values: list[float], period: int) -> list[float | None]:
    """滚动总体标准差（除以 N），预热区 None。"""
    if not values or period < 1:
        return []
    result: list[float | None] = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        m = sum(window) / period
        result.append((sum((v - m) ** 2 for v in window) / period) ** 0.5)
    return result


def bollinger(values: list[float], period: int = 20, num_std: float = 2.0):
    """布林带：(mid, upper, lower)，预热区 None。"""
    mid = ma(values, period)
    std = rolling_std(values, period)
    n = len(values)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(n):
        m = mid[i]
        s = std[i]
        if m is not None and s is not None:
            upper[i] = m + num_std * s
            lower[i] = m - num_std * s
    return mid, upper, lower


def atr(bars: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    """平均真实波幅（Wilder 平滑）。"""
    n = len(bars)
    if n < 2:
        return [None] * n
    trs: list[float] = []
    for i in range(1, n):
        high, low = float(bars[i]["high"]), float(bars[i]["low"])
        prev_close = float(bars[i - 1]["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    result: list[float | None] = [None] * n
    if n - 1 < period:
        return result
    prev = sum(trs[:period]) / period
    result[period] = prev
    for i in range(period, len(trs)):
        prev = (prev * (period - 1) + trs[i]) / period
        result[i + 1] = prev
    return result


def donchian(bars: list[dict[str, Any]], period: int = 20):
    """唐奇安通道：(upper, lower)，预热区 None。"""
    n = len(bars)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(period - 1, n):
        highs = [float(b["high"]) for b in bars[i - period + 1 : i + 1]]
        lows = [float(b["low"]) for b in bars[i - period + 1 : i + 1]]
        upper[i] = max(highs)
        lower[i] = min(lows)
    return upper, lower


def momentum(values: list[float], period: int = 20) -> list[float | None]:
    """N 日涨跌幅百分比。"""
    n = len(values)
    result: list[float | None] = [None] * n
    for i in range(period, n):
        prev = values[i - period]
        if prev:
            result[i] = (values[i] / prev - 1) * 100
    return result


def deviation(values: list[float], period: int = 20) -> list[float | None]:
    """价格相对 MA 的偏离百分比 (close/MA−1)×100。"""
    mid = ma(values, period)
    n = len(values)
    result: list[float | None] = [None] * n
    for i in range(n):
        m = mid[i]
        if m:
            result[i] = (values[i] / m - 1) * 100
    return result


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """相对强弱指标（Wilder 平滑），全涨返回 100。"""
    n = len(values)
    if n <= period:
        return [None] * n
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    result: list[float | None] = [None] * n
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, n):
        avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
        avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        result[i] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return result


def adx(bars: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    """平均趋向指数（Wilder），0–100，预热区 None。"""
    n = len(bars)
    if n < period + 1:
        return [None] * n
    trs: list[float] = []
    pdm: list[float] = []
    ndm: list[float] = []
    for i in range(1, n):
        high, low = float(bars[i]["high"]), float(bars[i]["low"])
        prev_high = float(bars[i - 1]["high"])
        prev_low = float(bars[i - 1]["low"])
        prev_close = float(bars[i - 1]["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        up = high - prev_high
        dn = prev_low - low
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)

    def wilder(series: list[float]) -> list[float]:
        out = [0.0] * len(series)
        out[period - 1] = sum(series[:period]) / period
        for i in range(period, len(series)):
            out[i] = (out[i - 1] * (period - 1) + series[i]) / period
        return out

    atr_s = wilder(trs)
    pdm_s = wilder(pdm)
    ndm_s = wilder(ndm)
    dx: list[float | None] = [None] * n
    for i in range(period, n):
        if atr_s[i - 1] == 0:
            continue
        di_p = pdm_s[i - 1] / atr_s[i - 1] * 100
        di_m = ndm_s[i - 1] / atr_s[i - 1] * 100
        denom = di_p + di_m
        dx[i] = abs(di_p - di_m) / denom * 100 if denom else 0.0
    # Wilder 平滑 DX → ADX
    result: list[float | None] = [None] * n
    valid = [(i, v) for i, v in enumerate(dx) if v is not None]
    if len(valid) >= period:
        first_idx = valid[0][0]
        prev = sum(v for _, v in valid[:period]) / period
        result[first_idx + period - 1] = prev
        for j in range(period, len(valid)):
            idx, v = valid[j]
            prev = (prev * (period - 1) + v) / period
            result[idx] = prev
    return result
