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
