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
    # 明文 token 绝不出现在响应任何位置（掩码键 tushareTokenMasked 由专测覆盖）
    assert "abcd1234efgh" not in str(payload)


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


def test_workspace_settings_tushare_keys_normalize():
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    assert DEFAULT_WORKSPACE_SETTINGS["tushareToken"] == ""
    assert DEFAULT_WORKSPACE_SETTINGS["crossCheckEnabled"] is None
    normalized = _normalize_workspace_settings({"tushareToken": "  abc123  ", "crossCheckEnabled": True})
    assert normalized["tushareToken"] == "abc123"
    assert normalized["crossCheckEnabled"] is True
    bogus = _normalize_workspace_settings({"crossCheckEnabled": "yes"})
    assert bogus["crossCheckEnabled"] is None


def test_settings_api_masks_tushare_token_and_reports_configured(monkeypatch):
    from types import SimpleNamespace

    from backend.storage import _normalize_workspace_settings

    monkeypatch.setattr(
        app_module,
        "get_workspace_settings",
        lambda workspace_id="default": _normalize_workspace_settings({"tushareToken": "abcd1234efgh"}),
    )
    monkeypatch.setattr(app_module, "get_settings", lambda: SimpleNamespace(tushare_token=""))
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/settings")

    payload = response.json()
    assert payload["data"]["tushareToken"] == ""
    assert "abcd1234efgh" not in str(payload)
    tushare = next(s for s in payload["sources"] if s["id"] == "tushare")
    assert tushare["tushareConfigured"] is True
    assert tushare["tushareTokenMasked"] == "****efgh"


def test_settings_api_tushare_env_fallback_and_workspace_priority(monkeypatch):
    from types import SimpleNamespace

    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )
    monkeypatch.setattr(app_module, "get_settings", lambda: SimpleNamespace(tushare_token="envtoken9999"))
    with TestClient(app_module.create_app()) as client:
        env_only = client.get("/api/settings").json()
        assert next(s for s in env_only["sources"] if s["id"] == "tushare")["tushareTokenMasked"] == "****9999"
    monkeypatch.setattr(
        app_module,
        "get_workspace_settings",
        lambda workspace_id="default": _normalize_workspace_settings({"tushareToken": "abcd1234efgh"}),
    )
    with TestClient(app_module.create_app()) as client:
        both = client.get("/api/settings").json()
        assert next(s for s in both["sources"] if s["id"] == "tushare")["tushareTokenMasked"] == "****efgh"


def test_settings_put_tushare_roundtrip_and_clear(monkeypatch):
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    saved: dict[str, dict] = {}

    def fake_save(payload, workspace_id="default"):
        saved[workspace_id] = _normalize_workspace_settings({**saved.get(workspace_id, {}), **payload})
        return saved[workspace_id]

    monkeypatch.setattr(app_module, "save_workspace_settings", fake_save)
    monkeypatch.setattr(
        app_module,
        "get_workspace_settings",
        lambda workspace_id="default": saved.get(workspace_id, dict(DEFAULT_WORKSPACE_SETTINGS)),
    )
    with TestClient(app_module.create_app()) as client:
        put = client.put("/api/settings", json={"tushareToken": "tok12345", "crossCheckEnabled": True})
        assert put.status_code == 200
        assert put.json()["data"]["tushareToken"] == ""
        client.put("/api/settings", json={"refreshInterval": 30})
        assert saved["default"]["tushareToken"] == "tok12345"  # 缺省=不修改
        assert saved["default"]["crossCheckEnabled"] is True
        client.put("/api/settings", json={"tushareToken": ""})
        assert saved["default"]["tushareToken"] == ""  # ""=清除


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
