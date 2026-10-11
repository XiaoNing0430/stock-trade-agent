"""多策略回测对比端点：同 bars 重放 / 白名单上界 / 部分失败隔离 / trades 不截断 / 一次取数。"""

from backend import app as app_module
from backend.strategy_engines import STRATEGY_ENGINES
from fastapi.testclient import TestClient


def _bars(count=120, start=100.0):
    """确定性日线序列（先跌后涨再回落），保证多数策略可产生成交。"""
    bars = []
    for i in range(count):
        progress = i / max(1, count - 1)
        if progress < 0.4:
            factor = 1 - (progress / 0.4) * 0.3
        elif progress < 0.7:
            factor = 0.7 + ((progress - 0.4) / 0.3) * 0.6
        else:
            factor = 1.3 - ((progress - 0.7) / 0.3) * 0.6
        close = round(start * factor, 2)
        bars.append(
            {
                "date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 10000,
            }
        )
    return bars


ALL_TYPES = ["grid", *STRATEGY_ENGINES.keys()]


def _patch_history(monkeypatch, bars):
    calls = {"count": 0, "limit": None}

    def fake_load(code, limit, is_index=False):
        calls["count"] += 1
        calls["limit"] = limit
        return bars, "tencent", bars[-1]["date"], "tencent"

    monkeypatch.setattr(app_module, "_load_history_with_fallback", fake_load)
    return calls


def test_compare_runs_all_types_on_shared_bars(monkeypatch):
    bars = _bars()
    calls = _patch_history(monkeypatch, bars)
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare",
            json={"code": "600519", "lookback": 120, "capital": 100000, "feeBps": 3, "strategyTypes": ALL_TYPES},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dataSource"] == "tencent"
    assert data["barCount"] == len(bars)
    assert data["benchmarkCurve"][0]["date"] == bars[0]["date"]
    assert len(data["results"]) == len(ALL_TYPES)
    by_type = {item["strategyType"]: item for item in data["results"]}
    assert set(by_type) == set(ALL_TYPES)
    # grid：自动建议区间 + 默认 8 格 classic
    grid = by_type["grid"]
    assert grid["error"] is None
    assert grid["config"]["gridCount"] == 8
    assert grid["config"]["mode"] == "classic"
    assert 0 < grid["config"]["lower"] < grid["config"]["upper"]
    # 引擎：schema 默认参数补齐
    assert by_type["ma_cross"]["config"]["fastPeriod"] == 5
    assert by_type["ma_cross"]["config"]["slowPeriod"] == 20
    for item in data["results"]:
        assert set(item) == {
            "strategyType",
            "label",
            "config",
            "metrics",
            "equityCurve",
            "trades",
            "assumptions",
            "error",
        }
        assert "benchmarkCurve" not in item  # 顶层仅一份
    # 一次上游取数
    assert calls["count"] == 1
    assert calls["limit"] == 120


def test_compare_whitelist_and_bounds(monkeypatch):
    bars = _bars()
    calls = _patch_history(monkeypatch, bars)
    with TestClient(app_module.create_app()) as client:
        resp_unknown = client.post(
            "/api/strategy/compare",
            json={"code": "600519", "strategyTypes": ["grid", "nope"]},
        )
        resp_empty = client.post("/api/strategy/compare", json={"code": "600519", "strategyTypes": []})
        resp_dup = client.post(
            "/api/strategy/compare",
            json={"code": "600519", "strategyTypes": ["grid", "grid", "grid"]},
        )
        resp_capital = client.post(
            "/api/strategy/compare", json={"code": "600519", "capital": 0, "strategyTypes": ["grid"]}
        )
        resp_lookback = client.post(
            "/api/strategy/compare", json={"code": "600519", "lookback": 500, "strategyTypes": ["grid"]}
        )
    assert resp_unknown.status_code == 422
    body = resp_unknown.json()["detail"]
    assert body["code"] == "VALIDATION_ERROR"
    assert "nope" in body["error"]
    assert resp_empty.status_code == 422
    assert resp_dup.status_code == 200  # 去重保序，不报错
    assert len(resp_dup.json()["results"]) == 1
    assert resp_capital.status_code == 422
    # lookback clamp 20..240
    assert resp_lookback.status_code == 200
    assert resp_lookback.json()["barCount"] <= 240
    assert calls["limit"] == 240


def test_compare_partial_failure_isolated(monkeypatch):
    bars = _bars()

    def _boom(bars_, config):
        raise ValueError("引擎炸了")

    monkeypatch.setitem(STRATEGY_ENGINES, "macd", {**STRATEGY_ENGINES["macd"], "backtest": _boom})
    _patch_history(monkeypatch, bars)
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare",
            json={"code": "600519", "strategyTypes": ALL_TYPES},
        )
    assert resp.status_code == 200
    by_type = {item["strategyType"]: item for item in resp.json()["results"]}
    assert "回测失败" in by_type["macd"]["error"]
    assert by_type["ma_cross"]["error"] is None


def test_compare_trades_not_truncated(monkeypatch):
    bars = _bars()
    fake_result = {
        "trades": [
            {
                "date": f"2026-01-{i % 28 + 1:02d}",
                "side": "buy",
                "triggerPrice": None,
                "price": 100.0,
                "shares": 100,
                "fee": 5.0,
                "module": None,
            }
            for i in range(150)
        ],
        "equityCurve": [{"date": b["date"], "equity": 1.0} for b in bars],
        "benchmarkCurve": [{"date": b["date"], "equity": 1.0} for b in bars],
        "metrics": {"tradeCount": 150},
        "assumptions": "测试",
    }
    monkeypatch.setitem(
        STRATEGY_ENGINES,
        "momentum",
        {**STRATEGY_ENGINES["momentum"], "backtest": lambda bars_, config: fake_result},
    )
    _patch_history(monkeypatch, bars)
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare",
            json={"code": "600519", "strategyTypes": ["momentum"]},
        )
    assert resp.status_code == 200
    assert len(resp.json()["results"][0]["trades"]) == 150


# ===== compare-saved：快照读库 + 现跑零写库 =====


def _grid_row(**overrides):
    row = {
        "id": "grid-1",
        "workspaceId": "default",
        "code": "600519",
        "name": "网格A",
        "lower": 85.0,
        "upper": 115.0,
        "gridCount": 8,
        "capital": 100000.0,
        "feeBps": 3.0,
        "mode": "classic",
        "lookback": 120,
        "settlementDays": 1,
        "slippageBps": 5,
        "schedule": "manual",
        "status": "启用",
        "nextRunAt": None,
        "lastBacktestAt": "2026-10-10T15:20:00+00:00",
        "latestMetrics": {"returnPct": 5.0, "maxDrawdownPct": 3.0},
        "updatedAt": "2026-10-10T15:20:00+00:00",
    }
    row.update(overrides)
    return row


def _strategy_row(**overrides):
    row = {
        "id": "strategy-1",
        "workspaceId": "default",
        "code": "600519",
        "name": "双均线A",
        "strategyType": "ma_cross",
        "config": {
            "fastPeriod": 5,
            "slowPeriod": 20,
            "capital": 100000,
            "feeBps": 3,
            "lookback": 120,
            "capitalAllocation": 1.0,
            "securityType": "股票",
            "exchange": "上交所",
        },
        "capital": 100000.0,
        "feeBps": 3.0,
        "schedule": "manual",
        "status": "启用",
        "nextRunAt": None,
        "lastBacktestAt": None,
        "latestMetrics": None,
        "updatedAt": "2026-10-10T15:20:00+00:00",
    }
    row.update(overrides)
    return row


def _patch_saved(monkeypatch, grid_rows, strategy_rows):
    def fake_get_grid(strategy_id):
        return next((r for r in grid_rows if r["id"] == strategy_id), None)

    def fake_get_strategy(strategy_id):
        return next((r for r in strategy_rows if r["id"] == strategy_id), None)

    monkeypatch.setattr(app_module, "get_grid_strategy", fake_get_grid)
    monkeypatch.setattr(app_module, "get_strategy", fake_get_strategy)
    # 零写库断言：所有写路径录制器
    calls: list[str] = []

    def _recorder(name):
        def _fn(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"对比端点不得写库：{name}")

        return _fn

    for name in (
        "save_grid_strategy",
        "save_strategy",
        "save_grid_backtest",
        "save_strategy_backtest",
        "schedule_strategy",
    ):
        monkeypatch.setattr(app_module, name, _recorder(name))
    return calls


def test_compare_saved_snapshot_reads_library(monkeypatch):
    _patch_history(monkeypatch, _bars())
    _patch_saved(
        monkeypatch,
        [
            _grid_row(),
            _grid_row(id="grid-ws", workspaceId="other"),
            _grid_row(id="grid-never", latestMetrics=None, lastBacktestAt=None),
        ],
        [_strategy_row()],
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare-saved?workspace=default",
            json={"mode": "snapshot", "ids": ["grid-1", "strategy-1", "grid-never", "grid-ws", "nope"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rerun"] is False
    items = {item["id"]: item for item in data["results"]}
    assert items["grid-1"]["found"] is True
    assert items["grid-1"]["source"] == "grid"
    assert items["grid-1"]["latestMetrics"]["returnPct"] == 5.0
    assert items["strategy-1"]["source"] == "strategy"
    assert items["strategy-1"]["strategyType"] == "ma_cross"
    assert items["grid-never"]["latestMetrics"] is None
    assert items["grid-never"]["missingReason"] == "从未回测"
    assert items["grid-ws"]["found"] is False
    assert items["grid-ws"]["missingReason"] == "不存在或不属于当前工作区"
    assert items["nope"]["found"] is False


def test_compare_saved_rerun_runs_without_side_effects(monkeypatch):
    bars = _bars()
    _patch_history(monkeypatch, bars)
    _patch_saved(monkeypatch, [_grid_row()], [_strategy_row()])
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare-saved",
            json={"mode": "rerun", "ids": ["grid-1", "strategy-1"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rerun"] is True
    by_id = {item["id"]: item for item in data["results"]}
    grid_item = by_id["grid-1"]
    assert grid_item["metrics"]["tradeCount"] >= 0
    assert grid_item["config"]["lower"] == 85.0
    assert grid_item["config"]["gridCount"] == 8
    assert grid_item["dataSource"] == "tencent"
    assert "equityCurve" not in grid_item  # rerun 不含曲线
    assert "benchmarkCurve" not in grid_item
    engine_item = by_id["strategy-1"]
    assert engine_item["metrics"]["tradeCount"] >= 0
    assert engine_item["strategyType"] == "ma_cross"
    assert "equityCurve" not in engine_item


def test_compare_saved_rerun_partial_failure(monkeypatch):
    bars = _bars()

    def _boom(bars_, config):
        raise ValueError("引擎炸了")

    monkeypatch.setitem(STRATEGY_ENGINES, "ma_cross", {**STRATEGY_ENGINES["ma_cross"], "backtest": _boom})
    _patch_history(monkeypatch, bars)
    _patch_saved(monkeypatch, [_grid_row()], [_strategy_row()])
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare-saved",
            json={"mode": "rerun", "ids": ["grid-1", "strategy-1"]},
        )
    assert resp.status_code == 200
    by_id = {item["id"]: item for item in resp.json()["results"]}
    assert by_id["grid-1"]["error"] is None
    assert "回测失败" in by_id["strategy-1"]["error"]
    assert by_id["strategy-1"]["metrics"] is None


def test_compare_saved_bounds(monkeypatch):
    _patch_history(monkeypatch, _bars())
    _patch_saved(monkeypatch, [], [])
    with TestClient(app_module.create_app()) as client:
        resp_empty = client.post("/api/strategy/compare-saved", json={"mode": "snapshot", "ids": []})
        resp_too_many = client.post(
            "/api/strategy/compare-saved",
            json={"mode": "snapshot", "ids": [f"x{i}" for i in range(11)]},
        )
        resp_mode = client.post("/api/strategy/compare-saved", json={"mode": "weird", "ids": ["a"]})
    assert resp_empty.status_code == 422
    assert resp_too_many.status_code == 422
    assert resp_mode.status_code == 422
