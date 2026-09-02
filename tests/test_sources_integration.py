"""Task 6 后端基础集成：源注册表 + settings 路由集成测试。

沿用现有 monkeypatch 离线模式 + 真实 PostgreSQL 模式（与 test_settings_api.py 一致）。
"""

from __future__ import annotations

from typing import Any

import pytest
from backend import app as app_module
from backend.sources import build_router, get_all_sources_info, get_source_info
from backend.sources.eastmoney import EastMoneySource
from backend.sources.tencent import TencentSource
from backend.storage import save_workspace_settings
from fastapi.testclient import TestClient

_WS = "test-intg-ws"  # 专用工作区，避免污染默认数据


def test_settings_returns_sources():
    """GET /api/settings 返回 tencent/eastmoney 源列表，fundamental 位正确。"""
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/settings")
    assert resp.status_code == 200
    sources: list[dict[str, Any]] = resp.json()["sources"]
    ids = [s["id"] for s in sources]
    assert "tencent" in ids
    assert "eastmoney" in ids
    em = next(s for s in sources if s["id"] == "eastmoney")
    assert em["fundamental"] is True
    assert em["realtime"] is True
    tencent = next(s for s in sources if s["id"] == "tencent")
    assert tencent["fundamental"] is False
    # 每个 source 必须有 fundamental 字段
    for s in sources:
        assert "fundamental" in s


def test_settings_put_accepts_fundamental_source():
    """PUT /api/settings 保存 fundamentalSource 和 realtimeSource=eastmoney。"""
    save_workspace_settings({}, _WS)  # 确保工作区存在
    with TestClient(app_module.create_app()) as client:
        resp = client.put(
            "/api/settings",
            json={"fundamentalSource": "eastmoney", "realtimeSource": "eastmoney"},
            params={"workspace": _WS},
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["fundamentalSource"] == "eastmoney"
    assert data["realtimeSource"] == "eastmoney"


def test_build_router_registers_core_sources():
    """build_router() 包含 tencent/eastmoney；MOCK_US_ENABLED=1 时含 mock_us。"""
    router = build_router()
    # tencent 和 eastmoney 始终注册（get_source 不抛异常即注册）
    router.get_source("tencent")
    router.get_source("eastmoney")
    with pytest.raises(ValueError, match="Unknown data source: mock_us"):
        router.get_source("mock_us")


def test_build_router_registers_with_mock_us(monkeypatch):
    """monkeypatch 方式验证 MOCK_US_ENABLED=1 时 mock_us 注册。"""
    monkeypatch.setenv("MOCK_US_ENABLED", "1")
    router = build_router()
    router.get_source("mock_us")  # 不抛异常即注册成功


def test_get_all_sources_info():
    """get_all_sources_info() 返回 dict 列表，含 id/fundamental/providerLabel 字段。"""
    infos = get_all_sources_info()
    assert isinstance(infos, list)
    assert len(infos) >= 2
    ids = [info["id"] for info in infos]
    assert "tencent" in ids
    assert "eastmoney" in ids
    for info in infos:
        assert "id" in info
        assert "fundamental" in info
        assert "providerLabel" in info
        assert isinstance(info["fundamental"], bool)
        assert isinstance(info["providerLabel"], str)


def test_get_source_info_tencent():
    """get_source_info() 对 TencentSource 返回正确能力位。"""
    src = TencentSource()
    info = get_source_info(src)
    assert info["id"] == "tencent"
    assert info["realtime"] is True
    assert info["history"] is True
    assert info["screener"] is True
    assert info["fundamental"] is False
    assert info["available"] is True


def test_get_source_info_eastmoney():
    """get_source_info() 对 EastMoneySource 返回 fundamental=True。"""
    src = EastMoneySource()
    info = get_source_info(src)
    assert info["id"] == "eastmoney"
    assert info["realtime"] is True
    assert info["history"] is True
    assert info["screener"] is True
    assert info["fundamental"] is True
    assert info["available"] is True
