"""声明式选股策略配置与加载器测试。"""

import pytest
from backend.screener.loader import list_strategies, load_strategy
from pydantic import ValidationError


def test_list_strategies_returns_builtin_two() -> None:
    strategies = list_strategies()
    ids = {s.id for s in strategies}
    assert {"oversold_bounce", "trend_breakout"}.issubset(ids)
    assert all(s.name for s in strategies)


def test_load_strategy_oversold_bounce() -> None:
    cfg = load_strategy("oversold_bounce")
    assert cfg.name == "超跌反弹"
    assert "pe" in cfg.quick_filters
    assert cfg.quick_filters["pe"][0] == 0
    assert cfg.advanced_factors, "必须至少声明一个因子"
    names = {f.name for f in cfg.advanced_factors}
    assert "rsi" in names
    assert cfg.top_n >= 1
    assert cfg.deep_cap >= 1


def test_load_strategy_trend_breakout() -> None:
    cfg = load_strategy("trend_breakout")
    names = {f.name for f in cfg.advanced_factors}
    assert "ma_arrange" in names


def test_load_strategy_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown strategy"):
        load_strategy("no_such_strategy")


def test_config_rejects_bad_operator() -> None:
    from backend.screener.loader import ScreenerStrategyConfig

    base = load_strategy("oversold_bounce").model_dump()
    base["advanced_factors"] = [{"name": "rsi", "period": 14, "operator": "~", "threshold": 30}]
    with pytest.raises(ValidationError):
        ScreenerStrategyConfig.model_validate(base)


def test_factor_spec_rejects_bad_operator_directly() -> None:
    from backend.screener.loader import ScreenerFactorSpec

    with pytest.raises(ValidationError):
        ScreenerFactorSpec(name="rsi", period=14, operator="~", threshold=30)


def test_config_rejects_zero_top_n() -> None:
    from backend.screener.loader import ScreenerStrategyConfig

    with pytest.raises(ValidationError):
        ScreenerStrategyConfig(id="x", name="X", top_n=0)
