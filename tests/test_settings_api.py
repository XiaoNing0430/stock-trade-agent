from backend import app as app_module
from fastapi.testclient import TestClient


def test_settings_api_returns_default_data_sources_without_secrets(monkeypatch):
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["historySource"] == "tencent"
    assert payload["data"]["realtimeSource"] == "tencent"
    assert "tushareToken" not in str(payload)


def test_conflict_policy_normalization_defaults_and_whitelist():
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    assert DEFAULT_WORKSPACE_SETTINGS["conflictPolicy"] == "server"
    assert _normalize_workspace_settings({})["conflictPolicy"] == "server"
    assert _normalize_workspace_settings({"conflictPolicy": "local"})["conflictPolicy"] == "local"
    assert _normalize_workspace_settings({"conflictPolicy": "ask"})["conflictPolicy"] == "ask"
    assert _normalize_workspace_settings({"conflictPolicy": "bogus"})["conflictPolicy"] == "server"


def test_notification_desktop_settings_defaults_and_normalization():
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    assert DEFAULT_WORKSPACE_SETTINGS["notifyDesktopAlert"] is True
    assert DEFAULT_WORKSPACE_SETTINGS["notifyDesktopSystem"] is False
    assert _normalize_workspace_settings({})["notifyDesktopAlert"] is True
    assert _normalize_workspace_settings({})["notifyDesktopSystem"] is False
    normalized = _normalize_workspace_settings({"notifyDesktopSystem": "yes", "notifyDesktopAlert": 0})
    assert normalized["notifyDesktopSystem"] is True
    assert normalized["notifyDesktopAlert"] is False


def test_settings_assist_defaults(monkeypatch):
    # 交易辅助 4 键默认值：风险%/盈亏比/止损模式/单票上限
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["riskPerTradePct"] == 1.0
    assert data["rrRatio"] == 2.0
    assert data["stopMode"] == "atr"
    assert data["positionCapPct"] == 25.0


def test_settings_assist_clamps(monkeypatch):
    # 交易辅助 4 键越界回退：走真实 normalize 校验，不落库
    from backend.storage import _normalize_workspace_settings

    monkeypatch.setattr(
        app_module,
        "save_workspace_settings",
        lambda payload, workspace_id="default": _normalize_workspace_settings(payload),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.put(
            "/api/settings",
            json={"riskPerTradePct": 99, "rrRatio": 0, "stopMode": "bogus", "positionCapPct": 1},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["riskPerTradePct"] == 5.0
    assert data["rrRatio"] == 1.0
    assert data["stopMode"] == "atr"
    assert data["positionCapPct"] == 5.0
