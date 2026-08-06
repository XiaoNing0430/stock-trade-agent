from fastapi.testclient import TestClient

from backend import app as app_module
from backend import data_source
from backend.data_source import parse_quote_body


def test_fetch_text_decodes_tencent_gbk_response(monkeypatch):
    class FakeResponse:
        content = 'v_sh600519="1~贵州茅台~600519~1308.55";'.encode("gbk")

        def raise_for_status(self):
            return None

    monkeypatch.setattr(data_source.requests, "get", lambda *args, **kwargs: FakeResponse())

    text = data_source.fetch_text("https://example.test", {"q": "sh600519"})

    assert "~贵州茅台~" in text


def test_shanghai_etf_code_maps_to_shanghai_quote_symbol():
    assert data_source.tencent_symbol("588000") == "sh588000"
    assert data_source.market_for_code("588000") == "沪A"


def test_parse_quote_body_keeps_fields_used_by_screener():
    values = [""] * 54
    values[1] = "贵州茅台"
    values[2] = "600519"
    values[3] = "2060.90"
    values[4] = "2033.00"
    values[5] = "2000.00"
    values[6] = "42537"
    values[31] = "27.90"
    values[32] = "1.37"
    values[33] = "2088.00"
    values[34] = "1988.00"
    values[35] = "2060.90/42537/8695978565"
    values[38] = "0.34"
    values[46] = "17.44"
    values[49] = "1.42"
    values[52] = "57.40"

    quote = parse_quote_body("sh600519", "~".join(values))

    assert quote["code"] == "600519"
    assert quote["name"] == "贵州茅台"
    assert quote["price"] == 2060.90
    assert quote["volumeRatio"] == 1.42
    assert quote["turnoverRate"] == 0.34
    assert quote["pb"] == 17.44
    assert quote["pe"] == 57.40


def test_health_reports_tencent_provider():
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider"] == "Tencent public quote API"
    assert payload["mode"] == "separated"


def test_market_returns_real_quotes_and_indices(monkeypatch):
    def fake_market(codes):
        return {
            "provider": "Tencent public quote API",
            "fetchedAt": 1710000000000,
            "quotes": [
                {"code": "600519", "name": "贵州茅台", "price": 2060.90, "change": 1.37},
                {"code": "300750", "name": "宁德时代", "price": 210.18, "change": -0.5},
            ],
            "indices": [{"code": "000001", "name": "上证指数", "price": 3100.10, "change": 0.22}],
            "errors": [],
        }

    monkeypatch.setattr(app_module, "load_market", fake_market)
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/market?codes=600519,300750")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "Tencent public quote API"
    assert payload["quotes"][0]["code"] == "600519"
    assert payload["quotes"][0]["name"] == "贵州茅台"
    assert payload["quotes"][0]["price"] > 0
    assert payload["indices"][0]["code"] == "000001"
    assert payload["indices"][0]["name"] == "上证指数"


def test_screener_returns_real_market_rows(monkeypatch):
    def fake_screener(market, page_size):
        return {
            "total": 8,
            "universeSize": 8,
            "rows": [
                {
                    "code": f"6005{index:02d}",
                    "name": f"样本{index}",
                    "market": "沪A",
                    "price": 10 + index,
                    "change": 1.0,
                    "volumeRatio": 1.5,
                    "turnoverRate": 0.8,
                    "pe": 20,
                    "pb": 2,
                }
                for index in range(8)
            ],
        }

    monkeypatch.setattr(app_module, "load_screener", fake_screener)
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/screener?market=全部&pageSize=8")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "Tencent public quote API"
    assert payload["universeSize"] >= 8
    assert len(payload["rows"]) == 8
    assert payload["rows"][0]["code"]
    assert payload["rows"][0]["price"] > 0


def test_history_returns_daily_kline(monkeypatch):
    def fake_history(code):
        return [{"date": "2026-08-06", "open": 10, "close": 11, "high": 12, "low": 9, "volume": 1000}]

    monkeypatch.setattr(app_module, "load_history", fake_history)
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/history?code=600519")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "Tencent public quote API"
    assert payload["code"] == "600519"
    assert len(payload["history"]) > 0
    assert payload["history"][-1]["close"] > 0


def test_root_serves_vue_frontend():
    with TestClient(app_module.create_app()) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "/assets/app.js" in response.text
