"""自定义选股策略存储层：CRUD / 原子乐观锁 / 事务删除引用快照 / 搜索分页。"""

from __future__ import annotations

import pytest
from backend import storage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    storage.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def factory(monkeypatch):
    factory = _session_factory()
    monkeypatch.setattr(storage, "SessionLocal", factory)
    return factory


VALID_CONFIG = {
    "quick_filters": {"pe": [0, 25]},
    "advanced_factors": [{"name": "rsi", "period": 14, "operator": "<", "threshold": 30, "weight": 2}],
    "sort_by": "changePct",
    "top_n": 10,
    "deep_cap": 200,
}


def test_upsert_creates_with_server_id_and_version(factory):
    row = storage.upsert_custom_strategy(
        {"name": "我的策略", "description": "d", **VALID_CONFIG}, strategy_id=None, expected_version=None
    )
    assert row["id"].startswith("custom_") and len(row["id"]) == len("custom_") + 12
    assert row["version"] == 1
    assert row["config"]["quick_filters"] == {"pe": (0.0, 25.0)}  # 校验器规范化为 (lo, hi) 元组
    assert row["config"]["advanced_factors"][0]["weight"] == 2


def test_update_atomic_version_bump_and_conflict(factory):
    row = storage.upsert_custom_strategy({"name": "A", **VALID_CONFIG}, strategy_id=None, expected_version=None)
    updated = storage.upsert_custom_strategy({"name": "B", **VALID_CONFIG}, strategy_id=row["id"], expected_version=1)
    assert updated["version"] == 2 and updated["name"] == "B"
    with pytest.raises(storage.CustomStrategyConflict) as exc:
        storage.upsert_custom_strategy({"name": "C", **VALID_CONFIG}, strategy_id=row["id"], expected_version=1)
    assert exc.value.server_row["version"] == 2  # 服务器最新行回显


def test_update_unknown_id_raises_value_error(factory):
    with pytest.raises(ValueError, match="unknown custom strategy"):
        storage.upsert_custom_strategy(
            {"name": "X", **VALID_CONFIG}, strategy_id="custom_deadbeefdead", expected_version=1
        )


def test_upsert_rejects_invalid_config(factory):
    with pytest.raises(ValueError):
        storage.upsert_custom_strategy(
            {"name": "坏", **VALID_CONFIG, "top_n": 0}, strategy_id=None, expected_version=None
        )
    with pytest.raises(ValueError):
        storage.upsert_custom_strategy({"name": "", **VALID_CONFIG}, strategy_id=None, expected_version=None)


def test_delete_returns_transactional_scan_references(factory):
    row = storage.upsert_custom_strategy({"name": "A", **VALID_CONFIG}, strategy_id=None, expected_version=None)
    with factory.begin() as session:
        session.add(storage.ScreenerScanConfig(id=row["id"], enabled=True))
    result = storage.delete_custom_strategy(row["id"])
    assert result["scanReferences"] == [row["id"]]
    assert result["deleted"]["config"]["top_n"] == 10  # 快照含完整 config，可凭日志重建
    with factory() as session:
        assert session.get(storage.ScreenerCustomStrategy, row["id"]) is None


def test_delete_missing_returns_none(factory):
    assert storage.delete_custom_strategy("custom_deadbeefdead") is None


def test_list_search_and_pagination(factory):
    for i in range(3):
        storage.upsert_custom_strategy({"name": f"策略{i}", **VALID_CONFIG}, strategy_id=None, expected_version=None)
    rows, total = storage.list_custom_strategies(search="策略1")
    assert total == 1 and rows[0]["name"] == "策略1"
    rows, total = storage.list_custom_strategies(limit=2)
    assert total == 3 and len(rows) == 2
    rows, total = storage.list_custom_strategies()
    assert total == 3 and len(rows) == 3


def test_get_custom_strategy_roundtrip(factory):
    created = storage.upsert_custom_strategy(
        {"name": "A", "description": "desc", **VALID_CONFIG}, strategy_id=None, expected_version=None
    )
    loaded = storage.get_custom_strategy(created["id"])
    assert loaded is not None and loaded["description"] == "desc" and loaded["version"] == 1
    assert storage.get_custom_strategy("custom_deadbeefdead") is None


def test_factor_and_quick_filter_whitelists_and_bounds():
    from backend.screener.loader import ScreenerStrategyConfig, list_strategies

    def build(factors, filters=None):
        return ScreenerStrategyConfig.model_validate(
            {"id": "t", "name": "t", "quick_filters": filters or {}, "advanced_factors": factors}
        )

    with pytest.raises(ValueError, match="factor name must be one of"):
        build([{"name": "made_up", "operator": ">", "threshold": 1}])
    with pytest.raises(ValueError):
        build([{"name": "rsi", "operator": ">", "threshold": 1, "weight": 101}])  # weight 上界
    with pytest.raises(ValueError):
        build([{"name": "rsi", "operator": ">", "threshold": 1, "weight": 0.001}])  # weight 下界
    with pytest.raises(ValueError):
        build([{"name": "rsi", "operator": ">", "threshold": float("inf")}])  # 非有限值
    with pytest.raises(ValueError):
        build([{"name": "rsi", "operator": ">", "threshold": 1} for _ in range(21)])  # 因子条数上限
    with pytest.raises(ValueError, match="not allowed"):
        build([], filters={"marketCap": [0, 1]})  # 未知 quick_filter 字段
    assert len(list_strategies()) >= 2  # 内置配置在加严后仍全部合法


def test_load_strategy_resolves_custom_and_builtin(factory):
    from backend.screener.loader import load_strategy

    assert load_strategy("oversold_bounce").name == "超跌反弹"  # 内置优先不受自定义影响
    created = storage.upsert_custom_strategy(
        {"name": "自定策略", **VALID_CONFIG}, strategy_id=None, expected_version=None
    )
    cfg = load_strategy(created["id"])
    assert cfg.id == created["id"] and cfg.name == "自定策略"
    with pytest.raises(ValueError, match="unknown strategy"):
        load_strategy("custom_doesnotexist")


def test_pipeline_invalidate_strategy_drops_cache_keys():
    import threading

    from backend.screener.pipeline import ScreenerPipeline

    pipeline = ScreenerPipeline.__new__(ScreenerPipeline)  # 仅验证 _cache 前缀失效，不构造依赖
    pipeline._cache = {
        "screener:custom_x:quick:CN": ({"rows": []}, 1.0),
        "screener:custom_x:deep:CN": ({"rows": []}, 1.0),
        "screener:other:quick:CN": ({"rows": []}, 1.0),
    }
    pipeline._locks = {}
    pipeline._rate_lock = threading.Lock()

    assert pipeline.invalidate_strategy("custom_x") == 2
    assert set(pipeline._cache) == {"screener:other:quick:CN"}
    assert pipeline.invalidate_strategy("custom_x") == 0  # 幂等


def test_custom_strategy_api_crud_roundtrip(monkeypatch):
    from backend import app as app_module
    from fastapi.testclient import TestClient

    monkeypatch.setattr(storage, "SessionLocal", _session_factory())
    with TestClient(app_module.create_app()) as client:
        created = client.post(
            "/api/screener/custom-strategies",
            json={
                "name": "测试策略",
                "description": "d",
                "quickFilters": {"pe": [0, 25]},
                "advancedFactors": [{"name": "rsi", "period": 14, "operator": "<", "threshold": 30, "weight": 2}],
            },
        )
        assert created.status_code == 200, created.text
        row = created.json()
        assert row["id"].startswith("custom_") and row["version"] == 1

        merged = client.get("/api/screener/strategies").json()["strategies"]
        mine = next(s for s in merged if s["id"] == row["id"])
        assert mine["custom"] is True and mine["version"] == 1 and mine["topN"] == 10
        assert all(s.get("custom") is not True for s in merged if s["id"] != row["id"])  # 内置行零变化

        single = client.get(f"/api/screener/custom-strategies/{row['id']}").json()
        assert single["scanReferences"] == [] and single["config"]["top_n"] == 10

        updated = client.put(
            f"/api/screener/custom-strategies/{row['id']}",
            json={"name": "测试策略2", "version": 1, "quickFilters": {}, "advancedFactors": [], "topN": 5},
        )
        assert updated.status_code == 200 and updated.json()["version"] == 2

        conflict = client.put(
            f"/api/screener/custom-strategies/{row['id']}",
            json={"name": "x", "version": 1, "quickFilters": {}, "advancedFactors": []},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "SCREENER_STRATEGY_CONFLICT"
        assert conflict.json()["detail"]["server"]["version"] == 2

        gone = client.delete(f"/api/screener/custom-strategies/{row['id']}")
        assert gone.status_code == 200 and gone.json()["scanReferences"] == []
        assert client.delete(f"/api/screener/custom-strategies/{row['id']}").status_code == 404


def test_custom_strategy_api_validation_and_missing_version(monkeypatch):
    from backend import app as app_module
    from fastapi.testclient import TestClient

    monkeypatch.setattr(storage, "SessionLocal", _session_factory())
    with TestClient(app_module.create_app()) as client:
        bad = client.post("/api/screener/custom-strategies", json={"name": "坏", "quickFilters": {"marketCap": [0, 1]}})
        assert bad.status_code == 422
        no_version = client.put("/api/screener/custom-strategies/custom_x", json={"name": "n"})
        assert no_version.status_code == 422
        assert client.get("/api/screener/custom-strategies/custom_nope").status_code == 404


def test_custom_strategy_api_list_search(monkeypatch):
    from backend import app as app_module
    from fastapi.testclient import TestClient

    monkeypatch.setattr(storage, "SessionLocal", _session_factory())
    with TestClient(app_module.create_app()) as client:
        for i in range(3):
            resp = client.post(
                "/api/screener/custom-strategies",
                json={"name": f"动量{i}", "advancedFactors": [{"name": "momentum", "operator": ">", "threshold": 0}]},
            )
            assert resp.status_code == 200, resp.text
        listed = client.get("/api/screener/custom-strategies", params={"search": "动量1"}).json()
        assert listed["total"] == 1 and listed["strategies"][0]["name"] == "动量1"
