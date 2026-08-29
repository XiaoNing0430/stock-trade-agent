from fastapi.testclient import TestClient

from backend import app as app_module
from backend import data_source
from backend.data_source import index_symbol, parse_quote_body, tencent_symbol


def test_tencent_symbol_000001_maps_to_stock_not_index():
    # 000001 is both 平安银行 (sz000001) and the SH index (sh000001). Treat it as a stock.
    assert tencent_symbol("000001") == "sz000001"
    assert data_source.classify_code("000001")["exchange"] == "深交所"
    assert data_source.classify_code("000001")["securityType"] == "股票"


def test_index_symbol_maps_to_dedicated_index_codes():
    assert index_symbol("000001") == "sh000001"
    assert index_symbol("399001") == "sz399001"
    assert index_symbol("399006") == "sz399006"


def test_load_history_index_flag_uses_index_symbol(monkeypatch):
    captured = {}

    def fake_fetch_json(url, params):
        captured["params"] = params
        return {"data": {"sh000001": {"qfqday": [["2026-08-06", 10, 11, 12, 9, 1000]]}}}

    monkeypatch.setattr(data_source, "fetch_json", fake_fetch_json)
    history = data_source.load_history("000001", limit=40, is_index=True)

    assert captured["params"]["param"].startswith("sh000001,day")
    assert history[-1]["close"] == 11


def test_load_history_stock_000001_uses_stock_symbol(monkeypatch):
    captured = {}

    def fake_fetch_json(url, params):
        captured["params"] = params
        return {"data": {"sz000001": {"qfqday": [["2026-08-06", 10, 11, 12, 9, 1000]]}}}

    monkeypatch.setattr(data_source, "fetch_json", fake_fetch_json)
    data_source.load_history("000001", limit=40, is_index=False)

    assert captured["params"]["param"].startswith("sz000001,day")


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
    classification = data_source.classify_code("588000")
    assert classification == {
        "exchange": "上交所",
        "board": "科创板ETF",
        "securityType": "ETF",
        "market": "科创板ETF",
    }


def test_stock_codes_are_classified_by_exchange_and_board():
    assert data_source.classify_code("600519") == {
        "exchange": "上交所",
        "board": "沪深主板",
        "securityType": "股票",
        "market": "沪深主板",
    }
    assert data_source.classify_code("300750") == {
        "exchange": "深交所",
        "board": "创业板",
        "securityType": "股票",
        "market": "创业板",
    }
    assert data_source.classify_code("688981") == {
        "exchange": "上交所",
        "board": "科创板",
        "securityType": "股票",
        "market": "科创板",
    }
    assert data_source.classify_code("830799") == {
        "exchange": "北交所",
        "board": "北交所",
        "securityType": "股票",
        "market": "北交所",
    }


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
    assert quote["exchange"] == "上交所"
    assert quote["board"] == "沪深主板"
    assert quote["securityType"] == "股票"
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
    def fake_history(code, limit=40, is_index=False):
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


def test_apply_runtime_config_feeds_timeout_into_fetch(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(data_source.requests, "get", fake_get)
    data_source.apply_runtime_config(timeout_seconds=7)
    try:
        data_source.fetch_json("https://example.test", {})
    finally:
        data_source.apply_runtime_config(timeout_seconds=10)
    assert captured["timeout"] == 7


def test_fetch_retries_and_backs_off(monkeypatch):
    calls = {"n": 0}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise data_source.requests.ConnectionError("boom")
        return FakeResponse()

    monkeypatch.setattr(data_source.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(data_source.requests, "get", fake_get)
    data_source.apply_runtime_config(retry_count=1)
    try:
        result = data_source.fetch_json("https://example.test", {})
    finally:
        data_source.apply_runtime_config(retry_count=1)
    assert result == {"ok": True}
    assert calls["n"] == 2


def test_screener_sorts_zero_change_above_negative(monkeypatch):
    rows = [
        {"code": "600001", "name": "甲", "market": "沪深主板", "change": 0.0},
        {"code": "600002", "name": "乙", "market": "沪深主板", "change": 2.0},
        {"code": "600003", "name": "丙", "market": "沪深主板", "change": -1.0},
        {"code": "600004", "name": "丁", "market": "沪深主板", "change": None},
    ]
    monkeypatch.setattr(data_source, "load_quotes", lambda codes: rows)

    payload = data_source.load_screener("全部", page_size=20)

    assert [row["change"] for row in payload["rows"]] == [2.0, 0.0, -1.0, None]


def test_alert_dict_includes_created_at_ms():
    from datetime import datetime, timezone

    from backend.storage import _alert_dict

    class FakeAlert:
        id = "alert-x"
        kind = "system"
        title = "事件"
        message = "详情"
        read = False
        created_at = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)

    data = _alert_dict(FakeAlert())
    assert data["createdAtMs"] == int(FakeAlert.created_at.timestamp() * 1000)


def test_workspace_get_includes_revision(monkeypatch):
    monkeypatch.setattr(
        app_module, "get_workspace",
        lambda workspace_id="default": {"watchlist": ["600519"], "plans": [], "alerts": [], "revision": 3},
        raising=False,
    )

    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/workspace")

    assert response.status_code == 200
    assert response.json()["revision"] == 3


def test_workspace_put_rejects_stale_revision_with_409(monkeypatch):
    monkeypatch.setattr(app_module, "get_workspace_revision", lambda workspace_id="default": 7, raising=False)
    monkeypatch.setattr(
        app_module, "get_workspace",
        lambda workspace_id="default": {"watchlist": [], "plans": [], "alerts": [], "revision": 7},
        raising=False,
    )
    saved = {}

    def fake_save(payload, workspace_id="default"):
        saved["payload"] = payload
        return {"watchlist": payload.get("watchlist", []), "plans": [], "alerts": [], "revision": 8}

    monkeypatch.setattr(app_module, "save_workspace", fake_save, raising=False)

    with TestClient(app_module.create_app()) as client:
        response = client.put(
            "/api/workspace?baseRevision=6",
            json={"watchlist": ["600519"], "plans": [], "alerts": []},
        )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["revision"] == 7
    assert body["detail"]["workspace"]["revision"] == 7
    assert "payload" not in saved


def test_workspace_put_with_matching_revision_saves(monkeypatch):
    monkeypatch.setattr(app_module, "get_workspace_revision", lambda workspace_id="default": 7, raising=False)
    monkeypatch.setattr(
        app_module, "get_workspace",
        lambda workspace_id="default": {"watchlist": [], "plans": [], "alerts": [], "revision": 7},
        raising=False,
    )

    def fake_save(payload, workspace_id="default"):
        return {"watchlist": payload.get("watchlist", []), "plans": [], "alerts": [], "revision": 8}

    monkeypatch.setattr(app_module, "save_workspace", fake_save, raising=False)

    with TestClient(app_module.create_app()) as client:
        response = client.put(
            "/api/workspace?baseRevision=7",
            json={"watchlist": ["600519"], "plans": [], "alerts": []},
        )

    assert response.status_code == 200
    assert response.json()["revision"] == 8


def test_workspace_put_with_force_overrides_stale_revision(monkeypatch):
    monkeypatch.setattr(app_module, "get_workspace_revision", lambda workspace_id="default": 7, raising=False)
    monkeypatch.setattr(
        app_module, "get_workspace",
        lambda workspace_id="default": {"watchlist": [], "plans": [], "alerts": [], "revision": 7},
        raising=False,
    )

    def fake_save(payload, workspace_id="default"):
        return {"watchlist": payload.get("watchlist", []), "plans": [], "alerts": [], "revision": 8}

    monkeypatch.setattr(app_module, "save_workspace", fake_save, raising=False)

    with TestClient(app_module.create_app()) as client:
        response = client.put(
            "/api/workspace?baseRevision=6&force=true",
            json={"watchlist": ["600519"], "plans": [], "alerts": []},
        )

    assert response.status_code == 200
    assert response.json()["revision"] == 8


def test_cached_serves_stale_on_loader_failure(monkeypatch):
    from backend.data_source import cached

    # 先灌入一次成功缓存；TTL 强制为 0 使后续都走 fetch 路径
    monkeypatch.setattr(data_source, "_cache_ttl", 0)
    cached("k", lambda: "ok")
    assert data_source.cache["k"][1] == "ok"

    def boom():
        raise ConnectionError("upstream down")

    monkeypatch.setattr(data_source, "cache", dict(data_source.cache))
    assert cached("k", boom) == "ok"  # 降级返回旧值
    marker = data_source.recent_stale(window=60)
    assert marker is not None
    assert marker["age"] >= 0


def test_cached_raises_when_stale_too_old_or_absent(monkeypatch):
    from backend.data_source import cached

    monkeypatch.setattr(data_source, "_cache_ttl", 0)
    data_source.cache.clear()

    # 无缓存 → 抛出
    try:
        cached("absent", lambda: (_ for _ in ()).throw(ConnectionError("x")))
        raise AssertionError("should raise")
    except ConnectionError:
        pass

    # 超龄缓存（1970 年）→ 抛出
    data_source.cache["old"] = (0.0, "oldval")
    try:
        cached("old", lambda: (_ for _ in ()).throw(ConnectionError("x")))
        raise AssertionError("should raise")
    except ConnectionError:
        pass


def test_stale_header_present_when_recent_stale(monkeypatch):
    # app.py 以 from ... import recent_stale 直接绑定到自身命名空间，需 patch app_module
    monkeypatch.setattr(app_module, "recent_stale", lambda window=2.0: {"age": 300}, raising=False)
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/health")
    assert response.headers.get("x-atlas-stale") == "300"


def test_load_market_bars_returns_bars_ordered():
    from backend.storage import initialize_storage, load_market_bars, save_market_bars

    initialize_storage()
    bars = [
        {"date": "2026-08-28", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10000},
        {"date": "2026-08-29", "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 2000, "amount": 22000},
    ]
    save_market_bars("600999", bars)
    loaded = load_market_bars("600999", limit=10)
    assert len(loaded) == 2
    assert loaded[0]["date"] == "2026-08-28"
    assert loaded[1]["date"] == "2026-08-29"
    assert "fetchedAt" in loaded[0]


def test_load_market_bars_returns_empty_when_none():
    from backend.storage import initialize_storage, load_market_bars

    initialize_storage()
    assert load_market_bars("nonexistent") == []


def test_fallback_serves_local_when_upstream_fails(monkeypatch):
    from backend.storage import initialize_storage, save_market_bars

    initialize_storage()
    save_market_bars("600888", [{"date": "2026-08-28", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10000}])
    monkeypatch.setattr(app_module, "load_history", lambda code, limit=120, is_index=False: (_ for _ in ()).throw(ConnectionError("upstream down")))
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/history?code=600888")
    assert response.status_code == 200
    data = response.json()
    assert data["dataSource"] == "local"
    assert len(data["history"]) == 1
    assert data["history"][0]["date"] == "2026-08-28"


def test_fallback_raises_when_no_local_data(monkeypatch):
    monkeypatch.setattr(app_module, "load_history", lambda code, limit=120, is_index=False: (_ for _ in ()).throw(ConnectionError("upstream down")))
    monkeypatch.setattr(app_module, "load_market_bars", lambda code, adjustment="qfq", limit=240: [])
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/history?code=absent")
    assert response.status_code == 502


def test_screener_v2_returns_paginated_results(monkeypatch):
    fake_data = {"data": {"rank_list": [{"code": "sh600519", "name": "贵州茅台", "zxj": "1297.4", "zdf": "0.39", "hsl": "0.13",
        "ltsz": "16218.56", "pe_ttm": "19.92", "pn": "6.46", "turnover": "208601", "zf": "0.77", "lb": "0.54",
        "zdf_d5": "1.93", "zdf_d10": "-3.32", "zdf_d20": "-3.94", "zdf_d60": "4.63", "zdf_w52": "-6.94", "zdf_y": "-3.84",
        "volume": "16126.00", "speed": "0.02", "zd": "5.10", "zsz": "16218.56", "zljlr": "-7495.96",
        "state": "", "stock_type": "GP-A"}], "offset": 0, "total": 4596}}
    class FakeResponse:
        def json(self): return fake_data
    monkeypatch.setattr("backend.data_source.requests.get", lambda url, params=None, timeout=10: FakeResponse())
    from backend.data_source import load_screener_v2
    result = load_screener_v2(page=1, page_size=10, sort_by="changePct", sort_dir="desc")
    assert result["total"] == 4596
    assert result["page"] == 1
    assert result["pageSize"] == 10
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["code"] == "sh600519"
    assert row["name"] == "贵州茅台"
    assert row["price"] == 1297.4
    assert row["changePct"] == 0.39
    assert row["change"] == 5.10
    assert row["turnoverRate"] == 0.13
    assert row["volumeRatio"] == 0.54
    assert row["peTtm"] is not None
    assert row["amount"] is not None
    assert row["totalMarketCap"] is not None


def test_screener_v2_when_upstream_fails(monkeypatch):
    monkeypatch.setattr("backend.data_source.requests.get", lambda url, params=None, timeout=10: (_ for _ in ()).throw(ConnectionError("timeout")))
    from backend.data_source import load_screener_v2
    import pytest
    with pytest.raises(RuntimeError, match="全市场选股器请求失败"):
        load_screener_v2()


def test_screener_v2_endpoint_returns_proper_shape(monkeypatch):
    fake_data = {"data": {"rank_list": [{"code": "sh600519", "name": "贵州茅台", "zxj": "1297.4", "zdf": "0.39", "hsl": "0.13",
        "ltsz": "16218.56", "pe_ttm": "19.92", "pn": "6.46", "turnover": "208601", "zf": "0.77", "lb": "0.54",
        "zdf_d5": "1.93", "zdf_d10": "-3.32", "zdf_d20": "-3.94", "zdf_d60": "4.63", "zdf_w52": "-6.94", "zdf_y": "-3.84",
        "volume": "16126.00", "speed": "0.02", "zd": "5.10", "zsz": "16218.56", "zljlr": "-7495.96",
        "state": "", "stock_type": "GP-A"}], "offset": 0, "total": 4596}}
    class FakeResponse:
        def json(self): return fake_data
    monkeypatch.setattr("backend.data_source.requests.get", lambda url, params=None, timeout=10: FakeResponse())
    from fastapi.testclient import TestClient
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/screener/v2?page=1&pageSize=10&sortBy=changePct&sortDir=desc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4596
    assert data["page"] == 1
    assert len(data["rows"]) == 1
