"""计划绩效复盘：source 归因存储 + bfq 链路 + 回放引擎 + 聚合 API。

沿用 test_storage_coverage.py 的既有模式：真实 PostgreSQL（initialize_storage）+
专用工作区避免污染默认数据；不臆造 fixture。
"""

from __future__ import annotations

import pytest
from backend import storage as storage_module

# 专用测试工作区，避免覆盖默认工作区真实数据
WS = "pr-ws"


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables():
    storage_module.initialize_storage()


@pytest.fixture(autouse=True)
def _cleanup_test_data():
    yield
    from sqlalchemy import delete

    models = [
        storage_module.WatchlistItem,
        storage_module.TradePlan,
        storage_module.Alert,
        storage_module.WorkspaceState,
    ]
    with storage_module.engine.begin() as connection:
        for model in models:
            connection.execute(delete(model).where(model.workspace_id == WS))


def test_plan_dict_carries_source():
    with storage_module.SessionLocal() as session:
        plan = storage_module.TradePlan(
            id="pr-p1",
            workspace_id=WS,
            code="300750",
            direction="buy",
            entry=10.0,
            stop=9.5,
            target=11.0,
            capital=10000,
            position=50,
            validity="本周内",
            source="scan:trend_breakout",
        )
        session.add(plan)
        session.commit()
        loaded = session.get(storage_module.TradePlan, "pr-p1")
        assert loaded.source == "scan:trend_breakout"
        d = storage_module._plan_dict(loaded)
        assert d["source"] == "scan:trend_breakout"


def test_plan_source_null_is_legacy_ready():
    with storage_module.SessionLocal() as session:
        plan = storage_module.TradePlan(
            id="pr-p2",
            workspace_id=WS,
            code="600519",
            direction="buy",
            entry=10.0,
            stop=9.5,
            target=11.0,
            capital=10000,
            position=50,
            validity="本周内",
        )
        session.add(plan)
        session.commit()
        loaded = session.get(storage_module.TradePlan, "pr-p2")
        assert loaded.source is None
        assert storage_module._plan_dict(loaded)["source"] is None  # 归一为 legacy 在 plan_review 层做


def test_save_workspace_roundtrips_source():
    payload = {
        "plans": [
            {
                "id": "pr-p3",
                "code": "000001",
                "direction": "buy",
                "entry": 10.0,
                "stop": 9.5,
                "target": 11.0,
                "capital": 10000,
                "position": 50,
                "validity": "本月内",
                "status": "执行中",
                "triggered": {},
                "createdAtMs": 1700000000000,
                "source": "manual",
            }
        ],
        "watchlist": [],
        "alerts": [],
    }
    storage_module.save_workspace(payload, WS)
    ws = storage_module.get_workspace(WS)
    plan = next(p for p in ws["plans"] if p["id"] == "pr-p3")
    assert plan["source"] == "manual"
    payload["plans"][0]["source"] = ""  # 空串 → None（存量/清空语义）
    storage_module.save_workspace(payload, WS)
    plan = next(p for p in storage_module.get_workspace(WS)["plans"] if p["id"] == "pr-p3")
    assert plan["source"] is None
