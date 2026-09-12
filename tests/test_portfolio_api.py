"""组合风险视图 Task 1：交易对关联存储（relatedPlan/exitMode）+ 写路径校验 + 总仓位上限设置。

沿用 test_plan_review.py 端点段既有模式：真实 PostgreSQL + 专用工作区（initialize_storage +
module-level TestClient + workspace 读写助手）；独立文件零共享 fixture。
"""

from __future__ import annotations

from typing import Any

import pytest
from backend import app as app_module
from backend import storage as storage_module
from backend.storage import validate_plan_links
from fastapi.testclient import TestClient

# 专用测试工作区，避免覆盖默认工作区真实数据
WS = "pf-ws"


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


@pytest.fixture()
def workspace_client() -> TestClient:
    # 模块级 app（create_app 产物）；直连真实 PostgreSQL，按 ?workspace= 隔离
    return TestClient(app_module.app)


def put_ws(client: TestClient, plans: list[dict[str, Any]]) -> dict[str, Any]:
    """plans 整表同步保存（workspace PUT 是计划编辑唯一通路）。"""
    response = client.put(
        "/api/workspace",
        params={"workspace": WS},
        json={"watchlist": [], "plans": plans, "alerts": []},
    )
    assert response.status_code == 200, response.text
    return response.json()


def get_ws(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/workspace", params={"workspace": WS})
    assert response.status_code == 200, response.text
    return response.json()


def test_plan_link_roundtrip(workspace_client):
    plans = [
        {
            "id": "b1",
            "code": "600519",
            "direction": "buy",
            "entry": 10,
            "stop": 9.5,
            "target": 11,
            "position": 10,
            "status": "执行中",
            "validity": "30天",
        },
        {
            "id": "s1",
            "code": "600519",
            "direction": "sell",
            "entry": 12,
            "stop": 11.5,
            "target": 13,
            "position": 10,
            "status": "执行中",
            "validity": "30天",
            "relatedPlan": "b1",
            "exitMode": "sell_priority",
        },
    ]
    put_ws(workspace_client, plans)  # 既有 workspace PUT 助手风格
    got = {p["id"]: p for p in get_ws(workspace_client)["plans"]}
    assert got["s1"]["relatedPlan"] == "b1" and got["s1"]["exitMode"] == "sell_priority"
    assert got["b1"]["relatedPlan"] is None  # 键恒在
    assert got["b1"]["exitMode"] is None
    # 解除关联语义：空串 → None（同 source 既有模式）
    plans[1]["relatedPlan"] = ""
    plans[1]["exitMode"] = ""
    put_ws(workspace_client, plans)
    got = {p["id"]: p for p in get_ws(workspace_client)["plans"]}
    assert got["s1"]["relatedPlan"] is None and got["s1"]["exitMode"] is None


def test_link_validation_rejects():
    bad = [{"id": "s1", "direction": "sell", "relatedPlan": "ghost"}]
    assert validate_plan_links(bad)  # 目标不存在 → 返回中文错误串
    assert validate_plan_links([{"id": "s1", "direction": "buy", "relatedPlan": "b2"}])
    # 一 buy 双 sell 关联、自引用、跨 code、目标非 buy → 均非 None；合法链 → None
    assert validate_plan_links(
        [
            {"id": "b1", "code": "600519", "direction": "buy"},
            {"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "b1"},
            {"id": "s2", "code": "600519", "direction": "sell", "relatedPlan": "b1"},
        ]
    )
    assert validate_plan_links([{"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "s1"}])
    assert validate_plan_links(
        [
            {"id": "b1", "code": "000001", "direction": "buy"},
            {"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "b1"},
        ]
    )
    assert validate_plan_links(
        [
            {"id": "x1", "code": "600519", "direction": "sell"},
            {"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "x1"},
        ]
    )
    # 目标已归档 → 非 None（spec §3：目标须非归档）
    assert validate_plan_links(
        [
            {"id": "b1", "code": "600519", "direction": "buy", "status": "已归档"},
            {"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "b1"},
        ]
    )
    # 合法链 → None
    assert (
        validate_plan_links(
            [
                {"id": "b1", "code": "600519", "direction": "buy"},
                {"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "b1", "exitMode": "race"},
            ]
        )
        is None
    )
    # 无任何关联 → None
    assert validate_plan_links([{"id": "b1", "code": "600519", "direction": "buy"}]) is None


def test_dangling_link_error_is_actionable():
    # 裁决补强：删除被关联的 buy（悬空）时错误消息必须指导用户
    msg = validate_plan_links([{"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "b1"}])
    assert msg is not None
    assert "请先解除关联" in msg


def test_workspace_put_rejects_bad_link_422(workspace_client):
    response = workspace_client.put(
        "/api/workspace",
        params={"workspace": WS},
        json={
            "watchlist": [],
            "plans": [
                {
                    "id": "s1",
                    "code": "600519",
                    "direction": "sell",
                    "entry": 12,
                    "stop": 11.5,
                    "target": 13,
                    "position": 10,
                    "status": "执行中",
                    "validity": "30天",
                    "relatedPlan": "ghost",
                }
            ],
            "alerts": [],
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert "请先解除关联" in detail["error"]
    # 校验在 save 前：被拒写盘不落任何计划
    assert get_ws(workspace_client)["plans"] == []


def test_total_position_cap_default_and_clamp():
    # I3：设置 +1 键 totalPositionCapPct（int 默认 100，clamp 20..300）
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    assert DEFAULT_WORKSPACE_SETTINGS["totalPositionCapPct"] == 100
    assert _normalize_workspace_settings({})["totalPositionCapPct"] == 100
    assert _normalize_workspace_settings({"totalPositionCapPct": 5})["totalPositionCapPct"] == 20
    assert _normalize_workspace_settings({"totalPositionCapPct": 999})["totalPositionCapPct"] == 300
    assert _normalize_workspace_settings({"totalPositionCapPct": 150.7})["totalPositionCapPct"] == 150
