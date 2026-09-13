"""组合风险视图 Task 1：交易对关联存储（relatedPlan/exitMode）+ 写路径校验 + 总仓位上限设置。

沿用 test_plan_review.py 端点段既有模式：真实 PostgreSQL + 专用工作区（initialize_storage +
module-level TestClient + workspace 读写助手）；独立文件零共享 fixture。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pytest
from backend import app as app_module
from backend import storage as storage_module
from backend.plan_review import SHANGHAI
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


def test_exit_mode_whitelist(workspace_client):
    # Fix round 1（评审 I-1）：exitMode 四值白名单，写路径整表校验（不限 sell）
    msg = validate_plan_links([{"id": "b1", "code": "600519", "direction": "buy", "exitMode": "banana"}])
    assert msg is not None
    assert "banana" in msg
    assert all(v in msg for v in ("race", "sell_priority", "sell_stop_only", "sell_only"))  # 消息列合法四值
    assert validate_plan_links([{"id": "b1", "code": "600519", "direction": "buy", "exitMode": "x" * 40}])
    # 超长旧路径会走 PG 列宽 500 兜底，现须白名单先行拒绝
    for legal in ("race", "sell_priority", "sell_stop_only", "sell_only"):
        assert validate_plan_links([{"id": "s1", "code": "600519", "direction": "sell", "exitMode": legal}]) is None
    # 空串/缺省=留空≡race（save_workspace or None 映射），恒通过
    assert validate_plan_links([{"id": "s1", "code": "600519", "direction": "sell", "exitMode": ""}]) is None
    assert validate_plan_links([{"id": "s1", "code": "600519", "direction": "sell"}]) is None
    # HTTP：banana PUT → 422 VALIDATION_ERROR 且不落盘
    response = workspace_client.put(
        "/api/workspace",
        params={"workspace": WS},
        json={
            "watchlist": [],
            "plans": [
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
                    "exitMode": "banana",
                }
            ],
            "alerts": [],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert "离场模式" in response.json()["detail"]["error"]
    assert get_ws(workspace_client)["plans"] == []


def test_total_position_cap_default_and_clamp():
    # I3：设置 +1 键 totalPositionCapPct（int 默认 100，clamp 20..300）
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    assert DEFAULT_WORKSPACE_SETTINGS["totalPositionCapPct"] == 100
    assert _normalize_workspace_settings({})["totalPositionCapPct"] == 100
    assert _normalize_workspace_settings({"totalPositionCapPct": 5})["totalPositionCapPct"] == 20
    assert _normalize_workspace_settings({"totalPositionCapPct": 999})["totalPositionCapPct"] == 300
    assert _normalize_workspace_settings({"totalPositionCapPct": 150.7})["totalPositionCapPct"] == 150


# ---------------------------------------------------------------------------
# Task 6 提交 1：review 端点「per-request source 解析 + _counting + degraded 收集」提取为
# 模块级 _resolve_history_loader()（组合端点复用，行为零变化）。
# 打桩边界与 test_plan_review.py 端点段同款：app_module._load_history_with_fallback +
# storage 缓存读写（fetch_all_bars 函数内 from backend import storage，按属性调用可 patch）。
# ---------------------------------------------------------------------------

client = TestClient(app_module.app)  # 模块级共享；各用例自 monkeypatch，互不残留


def test_resolve_history_loader_counts_and_degrades(monkeypatch):
    """提取物单测：(loader, stats, degraded) 三元组语义——stats 计上游命中，degraded 收 local 兜底码。"""
    seen: list[tuple[str, int, str]] = []

    def fake(code, limit, is_index=False, adjustment="qfq", source=None):
        assert is_index is False
        seen.append((code, limit, adjustment))
        flag = "local" if code == "000001" else "live"
        bar = {"date": "2026-01-05", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 100}
        return [dict(bar)], flag, "2026-01-05", "tencent"

    monkeypatch.setattr(app_module, "_load_history_with_fallback", fake)
    monkeypatch.setattr(storage_module, "load_market_bars", lambda *a, **k: [])
    monkeypatch.setattr(storage_module, "save_market_bars", lambda *a, **k: None)

    loader, stats, degraded = app_module._resolve_history_loader()
    bars_map = loader(["600519", "000001"])
    assert set(bars_map) == {"600519", "000001"}
    assert bars_map["600519"][0]["close"] == 10.2
    assert stats["upstream"] == 2
    assert degraded == ["000001"]  # 仅 local 兜底码入 degraded（顺序=拉取序）
    # bfq 口径 + 300 上限透传（fetch_all_bars 冻结契约）
    assert seen == [("600519", 300, ""), ("000001", 300, "")]


def _review_like_plan() -> dict[str, Any]:
    now_ms = int(datetime.now(SHANGHAI).timestamp() * 1000)
    return {
        "id": "reg-1",
        "code": "600519",
        "direction": "buy",
        "entry": 10.0,
        "stop": 9.5,
        "target": 11.0,
        "validity": "长期",
        "status": "执行中",
        "createdAtMs": now_ms - 10 * 86_400_000,
    }


def _recent_bars(n_from: int = 9, n_to: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "date": (datetime.now(SHANGHAI) - timedelta(days=d)).strftime("%Y-%m-%d"),
            "open": 10.4,
            "high": 11.5,
            "low": 9.9,
            "close": 11.0,
            "volume": 1000,
        }
        for d in range(n_from, n_to, -1)
    ]


def test_review_refactor_regression(monkeypatch, caplog):
    """提取回归钉：复盘端点走真实 review_plans/fetch_all_bars 链路，行为与提取前逐字一致
    （degraded 收集并包 + review_degraded 告警 + feeRate 上限常量收口到 plan_review.FEE_RATE_MAX）。"""
    bars = _recent_bars()

    def fake_local(code, limit, is_index=False, adjustment="qfq", source=None):
        return list(bars), "local", "2026-01-05", "local"

    monkeypatch.setattr(app_module, "get_workspace", lambda *a, **k: {"plans": [_review_like_plan()]})
    monkeypatch.setattr(app_module, "_load_history_with_fallback", fake_local)
    monkeypatch.setattr(storage_module, "load_market_bars", lambda *a, **k: [])
    monkeypatch.setattr(storage_module, "save_market_bars", lambda *a, **k: None)
    caplog.set_level(logging.WARNING)
    r = client.get("/api/plans/review", params={"days": 90})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] == ["600519"] and body["items"][0]["outcome"] == "win"  # 降级不阻断回算
    assert "review_degraded code=600519" in caplog.text
    # 上限常量同源（0.05 字面量 → plan_review.FEE_RATE_MAX）：边界值放行、越界 422（行为零变化）
    assert client.get("/api/plans/review", params={"days": 90, "feeRate": 0.05}).status_code == 200
    assert client.get("/api/plans/review", params={"days": 90, "feeRate": 0.0501}).status_code == 422
