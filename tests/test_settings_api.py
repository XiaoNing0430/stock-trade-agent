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
