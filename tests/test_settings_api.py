from fastapi.testclient import TestClient

from backend import app as app_module


def test_settings_api_returns_default_data_sources_without_secrets():
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
