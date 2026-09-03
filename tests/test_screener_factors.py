"""策略选股因子库测试：编排 backend/indicators.py 既有指标。"""

from typing import Any

import pytest
from backend.screener.factors import FactorLibrary, evaluate_condition


def _bars(closes: list[float], volumes: list[float] | None = None) -> list[dict[str, Any]]:
    """构造 bars（旧→新）：date/open/high/low/close/volume。"""
    vols = volumes or [10000.0] * len(closes)
    return [
        {
            "date": f"2026-08-{i + 1:02d}",
            "open": c,
            "high": c * 1.02,
            "low": c * 0.98,
            "close": c,
            "volume": vols[i],
        }
        for i, c in enumerate(closes)
    ]


def test_factor_library_lists_factors() -> None:
    names = FactorLibrary.available_factors()
    for expected in ("rsi", "ma_slope", "ma_arrange", "bollinger_pos", "momentum", "deviation", "volume_surge"):
        assert expected in names


def test_compute_factor_rsi() -> None:
    """单调下跌 30 根 → rsi(14) 接近 0，< 30 判定超卖成立。"""
    closes = [100.0 - i for i in range(30)]
    lib = FactorLibrary()
    value = lib.compute_factor(_bars(closes), {"name": "rsi", "period": 14})
    assert value is not None
    assert value < 30.0


def test_compute_factor_unknown_raises() -> None:
    lib = FactorLibrary()
    with pytest.raises(ValueError, match="unknown factor"):
        lib.compute_factor(_bars([10.0] * 30), {"name": "nope"})


def test_compute_factor_insufficient_bars_returns_none() -> None:
    """bars 不足（无法预热指标）→ None，评分时按未达标处理。"""
    lib = FactorLibrary()
    value = lib.compute_factor(_bars([10.0, 11.0]), {"name": "rsi", "period": 14})
    assert value is None


def test_evaluate_condition_operators() -> None:
    assert evaluate_condition(29.0, "<", 30.0) is True
    assert evaluate_condition(31.0, "<", 30.0) is False
    assert evaluate_condition(31.0, ">", 30.0) is True
    assert evaluate_condition(30.0, ">=", 30.0) is True
    assert evaluate_condition(29.9, "<=", 30.0) is True
    assert evaluate_condition(None, "<", 30.0) is False  # 缺数据 → 未达标
    with pytest.raises(ValueError, match="operator"):
        evaluate_condition(1.0, "~", 30.0)


def test_score_breakdown() -> None:
    """多因子加权：rsi 超卖达标（weight 2）+ ma_slope 上升未达标（weight 1）→ score=2。"""
    closes = [100.0 - i for i in range(30)]
    factors = [
        {"name": "rsi", "period": 14, "operator": "<", "threshold": 30, "weight": 2},
        {"name": "ma_slope", "period": 20, "operator": ">", "threshold": 0, "weight": 1},
    ]
    result = FactorLibrary().score_candidate(_bars(closes), factors)
    assert result["score"] == 2.0
    assert set(result["factors"].keys()) == {"rsi", "ma_slope"}
    rsi_entry = result["factors"]["rsi"]
    assert rsi_entry["met"] is True
    assert rsi_entry["weight"] == 2
    assert rsi_entry["value"] is not None
    assert result["factors"]["ma_slope"]["met"] is False


def test_volume_surge_factor() -> None:
    """放量：最新量为均值 3 倍 → volume_surge ≈ 3。"""
    closes = [10.0] * 25
    vols = [1000.0] * 24 + [3000.0]
    lib = FactorLibrary()
    value = lib.compute_factor(_bars(closes, vols), {"name": "volume_surge", "period": 20})
    assert value is not None
    assert value > 2.5


def test_bollinger_pos_oversold() -> None:
    """跌破布林下轨 → bollinger_pos < 0。"""
    closes = [20.0] * 25 + [15.0]
    lib = FactorLibrary()
    value = lib.compute_factor(_bars(closes), {"name": "bollinger_pos", "period": 20})
    assert value is not None
    assert value < 0.0


def test_ma_arrange_bullish() -> None:
    """上升趋势：close > ma5 > ma20 → ma_arrange = 1。"""
    closes = [10.0 + i * 0.2 for i in range(25)]
    lib = FactorLibrary()
    value = lib.compute_factor(_bars(closes), {"name": "ma_arrange", "period": 20})
    assert value == 1.0
