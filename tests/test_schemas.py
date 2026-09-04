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


def test_strategy_backtest_in_accepts_capital_allocation():
    from backend.schemas import StrategyBacktestIn

    payload = StrategyBacktestIn(strategyType="momentum", code="600519", capital=100000, capitalAllocation=0.6)
    assert payload.capitalAllocation == 0.6


def test_plan_draft_in_defaults() -> None:
    from backend.schemas import PlanDraftIn

    m = PlanDraftIn.model_validate({"code": "600519"})
    assert m.code == "600519" and m.entryPrice is None and m.stopMode is None


def test_plan_draft_in_rejects_out_of_range() -> None:
    import pytest
    from pydantic import ValidationError
    from backend.schemas import PlanDraftIn

    with pytest.raises(ValidationError):
        PlanDraftIn.model_validate({"code": "600519", "rrRatio": 99})
    with pytest.raises(ValidationError):
        PlanDraftIn.model_validate({"code": "600519", "entryPrice": -1})


def test_plan_draft_out_shape() -> None:
    from backend.schemas import PlanDraftOut

    m = PlanDraftOut.model_validate(
        {
            "code": "600519",
            "name": "贵州茅台",
            "entry": 10.0,
            "referenceDate": "2026-09-03",
            "disclaimer": "x",
        }
    )
    assert m.direction == "buy" and m.suggestedShares == 0 and m.stale is False and m.fallbackUsed is False
    assert m.warnings == []
