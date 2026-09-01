# tests/test_indicators.py
from backend.indicators import (
    adx,
    atr,
    bollinger,
    deviation,
    donchian,
    ema,
    ma,
    momentum,
    rolling_std,
    rsi,
)


def test_ma_basic():
    values = [1.0, 2.0, 3.0, 4.0]
    out = ma(values, 3)
    assert out[:2] == [None, None]
    assert out[2] == 2.0
    assert out[3] == 3.0


def test_ma_handles_empty():
    assert ma([], 3) == []


def test_ema_seed_and_tail():
    values = [1.0, 2.0, 3.0, 4.0]
    out = ema(values, 3)
    assert len(out) == 4
    assert out[0] == 1.0
    # multiplier = 2/(3+1) = 0.5
    assert abs(out[1] - 1.5) < 1e-9
    assert abs(out[2] - 2.25) < 1e-9


def test_rolling_std_known():
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    out = rolling_std(values, 8)
    assert out[:7] == [None] * 7
    # population std of the 8 values = 2.0
    assert abs(out[7] - 2.0) < 1e-9


def test_bollinger_bands():
    values = [float(i) for i in range(1, 25)]
    mid, upper, lower = bollinger(values, 20, 2.0)
    assert mid[:19] == [None] * 19  # 前 19 个为预热
    # 首个有效值位于 index 19：mean(1..20)=10.5, std(1..20)=sqrt(665/20)≈5.7663
    assert abs(mid[19] - 10.5) < 1e-9
    assert abs(upper[19] - (10.5 + 2 * 5.766281297335398)) < 1e-9
    assert abs(lower[19] - (10.5 - 2 * 5.766281297335398)) < 1e-9


def test_atr_known():
    bars = [
        {"date": "d", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
        {"date": "d", "open": 1, "high": 3, "low": 1, "close": 2.5},
        {"date": "d", "open": 1, "high": 4, "low": 1.5, "close": 3.5},
        {"date": "d", "open": 1, "high": 5, "low": 2, "close": 4.5},
    ]
    out = atr(bars, 3)
    assert out[:3] == [None, None, None]
    # TR: 2.0, 2.5, 3.0 → 首值(位于 index 3) = (2.0+2.5+3.0)/3 = 2.5
    assert abs(out[3] - 2.5) < 1e-9


def test_donchian_known():
    bars = [
        {"date": "d", "high": 10, "low": 8, "close": 9},
        {"date": "d", "high": 12, "low": 9, "close": 11},
        {"date": "d", "high": 11, "low": 7, "close": 10},
        {"date": "d", "high": 13, "low": 10, "close": 12},
    ]
    upper, lower = donchian(bars, 3)
    assert upper[:2] == [None, None]
    # index 2 窗口 = bars[0:3]，highs=[10,12,11], lows=[8,9,7]
    assert upper[2] == 12.0 and lower[2] == 7.0
    assert upper[3] == 13.0 and lower[3] == 7.0


def test_momentum_known():
    out = momentum([100.0, 110.0, 99.0], 2)
    assert out[:2] == [None, None]
    assert abs(out[2] - (-1.0)) < 1e-9


def test_deviation_known():
    out = deviation([100.0, 100.0, 110.0], 3)
    assert out[:2] == [None, None]
    # ma=103.333, dev=(110/103.333-1)*100 ≈ 6.45
    assert abs(out[2] - 6.4516) < 0.01


def test_rsi_known_all_gains():
    out = rsi([1.0, 2.0, 3.0, 4.0, 5.0], 3)
    assert out[:3] == [None, None, None]
    assert out[4] == 100.0


def test_rsi_flat_series_neutral():
    out = rsi([100.0, 100.0, 100.0, 100.0, 100.0], 3)
    assert out[:3] == [None, None, None]
    assert out[4] == 50.0


def test_adx_known_trend_strength():
    # 持续单边上涨 → ADX 应显著高于震荡序列
    up_bars = [{"date": f"d{i}", "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100 + i} for i in range(30)]
    flat_bars = [{"date": f"d{i}", "open": 100, "high": 101, "low": 99, "close": 100} for i in range(30)]
    up_adx = [v for v in adx(up_bars, 14) if v is not None]
    flat_adx = [v for v in adx(flat_bars, 14) if v is not None]
    assert up_adx and flat_adx
    assert max(up_adx) > max(flat_adx) + 20
