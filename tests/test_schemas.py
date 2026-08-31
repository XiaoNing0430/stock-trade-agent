from backend.schemas import GridBacktestIn, SettingsPut, StrategyBacktestIn, WorkspacePut


def test_settings_defaults():
    s = SettingsPut()
    assert s.refreshInterval == 15
    assert s.conflictPolicy == "server"


def test_workspace_put_extra_ignored():
    w = WorkspacePut.model_validate({"watchlist": ["600519"], "unknown": 1})
    assert w.watchlist == ["600519"]


def test_grid_backtest_required_fields():
    g = GridBacktestIn(code="588000", lower=1.0, upper=2.0, gridCount=8, capital=100000)
    assert g.mode == "classic"


def test_strategy_backtest_defaults():
    s = StrategyBacktestIn(strategyType="ma_cross", code="600519", config={"fast": 5})
    assert s.feeBps == 3
    assert s.schedule == "manual"
    assert s.lookback == 120
