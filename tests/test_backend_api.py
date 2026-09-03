from datetime import UTC

from backend import app as app_module
from backend import data_source
from backend.data_source import index_symbol, parse_quote_body, tencent_symbol
from fastapi.testclient import TestClient


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
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )

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

    monkeypatch.setattr("backend.data_source.load_market", fake_market)
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
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )

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

    monkeypatch.setattr("backend.data_source.load_screener", fake_screener)
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
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )

    def fake_history(code, limit=40, is_index=False):
        return [{"date": "2026-08-06", "open": 10, "close": 11, "high": 12, "low": 9, "volume": 1000}]

    monkeypatch.setattr("backend.data_source.load_history", fake_history)
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
    # 双轨托管：dist 存在时服务 Vite 产物（引用 /assets/...），否则源码入口（引用 /src/main.ts）；
    # 两种模式都包含 Vue 挂载点 <div id="app">。
    assert '<div id="app">' in response.text


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


def test_cache_ttl_floor_enforced():
    """cacheSeconds=0 时 _cache_ttl 不低于 2 秒。"""
    data_source.apply_runtime_config(cache_seconds=0)
    assert data_source._cache_ttl >= 2
    data_source.apply_runtime_config(cache_seconds=8)


def test_rate_limit_config_applied():
    """rate_limit_rps 配置更新 _min_request_interval。"""
    data_source.apply_runtime_config(rate_limit_rps=10)
    assert data_source._min_request_interval == 0.1
    data_source.apply_runtime_config(rate_limit_rps=1)
    assert data_source._min_request_interval == 1.0
    # 恢复
    data_source.apply_runtime_config(rate_limit_rps=5)
    assert data_source._min_request_interval == 0.2


def test_screener_v2_cached_uses_cache(monkeypatch):
    """同参数第二次调用 load_screener_v2 命中缓存，不触发 _http_get。"""
    calls = {"n": 0}

    class FakeResponse:
        def json(self):
            return {"data": {"total": 1, "rank_list": []}}

    def fake_http_get(url, params):
        calls["n"] += 1
        return FakeResponse()

    data_source.cache.clear()
    monkeypatch.setattr(data_source, "_http_get", fake_http_get)
    # 第一次调用：缓存未命中，调用 _http_get
    data_source.load_screener_v2(page=1, page_size=5, sort_by="changePct", sort_dir="desc")
    n1 = calls["n"]
    # 第二次调用同参数：应命中缓存
    data_source.load_screener_v2(page=1, page_size=5, sort_by="changePct", sort_dir="desc")
    assert calls["n"] == n1, "同参数第二次调用应命中缓存，不触发 _http_get"


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
    from datetime import datetime

    from backend.storage import _alert_dict

    class FakeAlert:
        id = "alert-x"
        kind = "system"
        title = "事件"
        message = "详情"
        read = False
        created_at = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)

    data = _alert_dict(FakeAlert())
    assert data["createdAtMs"] == int(FakeAlert.created_at.timestamp() * 1000)


def test_workspace_get_includes_revision(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "get_workspace",
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
        app_module,
        "get_workspace",
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
    assert body["detail"]["code"] == "WORKSPACE_CONFLICT"
    assert "payload" not in saved


def test_workspace_put_with_matching_revision_saves(monkeypatch):
    monkeypatch.setattr(app_module, "get_workspace_revision", lambda workspace_id="default": 7, raising=False)
    monkeypatch.setattr(
        app_module,
        "get_workspace",
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
        app_module,
        "get_workspace",
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
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, initialize_storage, save_market_bars

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )
    initialize_storage()
    save_market_bars(
        "600888",
        [{"date": "2026-08-28", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10000}],
    )
    monkeypatch.setattr(
        "backend.data_source.load_history",
        lambda code, limit=120, is_index=False: (_ for _ in ()).throw(ConnectionError("upstream down")),
    )
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/history?code=600888")
    assert response.status_code == 200
    data = response.json()
    assert data["dataSource"] == "local"
    # 验证保存的 bar 在结果中（数据库可能跨测试累积其他 bar）
    saved_dates = [h["date"] for h in data["history"]]
    assert "2026-08-28" in saved_dates


def test_fallback_raises_when_no_local_data(monkeypatch):
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )
    monkeypatch.setattr(
        "backend.data_source.load_history",
        lambda code, limit=120, is_index=False: (_ for _ in ()).throw(ConnectionError("upstream down")),
    )
    monkeypatch.setattr(app_module, "load_market_bars", lambda code, adjustment="qfq", limit=240: [])
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/history?code=absent")
    assert response.status_code == 502


def test_screener_v2_returns_paginated_results(monkeypatch):
    fake_data = {
        "data": {
            "rank_list": [
                {
                    "code": "sh600519",
                    "name": "贵州茅台",
                    "zxj": "1297.4",
                    "zdf": "0.39",
                    "hsl": "0.13",
                    "ltsz": "16218.56",
                    "pe_ttm": "19.92",
                    "pn": "6.46",
                    "turnover": "208601",
                    "zf": "0.77",
                    "lb": "0.54",
                    "zdf_d5": "1.93",
                    "zdf_d10": "-3.32",
                    "zdf_d20": "-3.94",
                    "zdf_d60": "4.63",
                    "zdf_w52": "-6.94",
                    "zdf_y": "-3.84",
                    "volume": "16126.00",
                    "speed": "0.02",
                    "zd": "5.10",
                    "zsz": "16218.56",
                    "zljlr": "-7495.96",
                    "state": "",
                    "stock_type": "GP-A",
                }
            ],
            "offset": 0,
            "total": 4596,
        }
    }

    class FakeResponse:
        def json(self):
            return fake_data

    data_source.cache.clear()
    monkeypatch.setattr(data_source, "_http_get", lambda url, params: FakeResponse())
    from backend.data_source import load_screener_v2

    result = load_screener_v2(page=1, page_size=10, sort_by="changePct", sort_dir="desc")
    assert result["total"] == 4596
    assert result["page"] == 1
    assert result["pageSize"] == 10
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["code"] == "600519"
    assert row["symbol"] == "sh600519"
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
    data_source.cache.clear()
    monkeypatch.setattr(data_source, "_http_get", lambda url, params: (_ for _ in ()).throw(ConnectionError("timeout")))
    import pytest
    from backend.data_source import load_screener_v2

    with pytest.raises(RuntimeError, match="全市场选股器请求失败"):
        load_screener_v2()


def test_screener_v2_endpoint_returns_proper_shape(monkeypatch):
    fake_data = {
        "data": {
            "rank_list": [
                {
                    "code": "sh600519",
                    "name": "贵州茅台",
                    "zxj": "1297.4",
                    "zdf": "0.39",
                    "hsl": "0.13",
                    "ltsz": "16218.56",
                    "pe_ttm": "19.92",
                    "pn": "6.46",
                    "turnover": "208601",
                    "zf": "0.77",
                    "lb": "0.54",
                    "zdf_d5": "1.93",
                    "zdf_d10": "-3.32",
                    "zdf_d20": "-3.94",
                    "zdf_d60": "4.63",
                    "zdf_w52": "-6.94",
                    "zdf_y": "-3.84",
                    "volume": "16126.00",
                    "speed": "0.02",
                    "zd": "5.10",
                    "zsz": "16218.56",
                    "zljlr": "-7495.96",
                    "state": "",
                    "stock_type": "GP-A",
                }
            ],
            "offset": 0,
            "total": 4596,
        }
    }

    class FakeResponse:
        def json(self):
            return fake_data

    data_source.cache.clear()
    monkeypatch.setattr(data_source, "_http_get", lambda url, params: FakeResponse())
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/screener/v2?page=1&pageSize=10&sortBy=changePct&sortDir=desc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4596
    assert data["page"] == 1
    assert len(data["rows"]) == 1


def _strategy_bars(count=60, start=100.0):
    """构造用于策略回测测试的确定性日线序列。"""
    bars = []
    for i in range(count):
        progress = i / max(1, count - 1)
        if progress < 0.4:
            factor = 1 - (progress / 0.4) * 0.3
        elif progress < 0.7:
            factor = 0.7 + ((progress - 0.4) / 0.3) * 0.6
        else:
            factor = 1.3 - ((progress - 0.7) / 0.3) * 0.6
        close = round(start * factor, 2)
        bars.append(
            {
                "date": f"2026-{1 + i // 22:02d}-{1 + i % 28:02d}",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 10000,
            }
        )
    return bars


def test_strategy_preview_returns_default_config(monkeypatch):
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()) as client:
        resp = client.post("/api/strategy/preview", json={"strategyType": "ma_cross", "config": {}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategyType"] == "ma_cross"
    assert data["suggestion"]["fastPeriod"] == 5
    assert data["suggestion"]["slowPeriod"] == 20


def test_strategy_preview_rejects_unknown_type():
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()) as client:
        resp = client.post("/api/strategy/preview", json={"strategyType": "nope", "config": {}})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_strategy_not_found_returns_code(monkeypatch):
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()) as client:
        resp = client.patch("/api/strategy/strategies/absent", json={"status": "暂停"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"


def test_grid_strategy_not_found_returns_code():
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()) as client:
        resp = client.delete("/api/grid/strategies/absent")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"


def test_upstream_failure_returns_code(monkeypatch):
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )
    monkeypatch.setattr(
        "backend.data_source.load_market", lambda codes: (_ for _ in ()).throw(ConnectionError("upstream down"))
    )
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/market?codes=600519")
    assert resp.status_code == 502
    body = resp.json()
    assert body["detail"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert body["detail"]["provider"] == "upstream"


def test_storage_unavailable_returns_code(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "get_workspace",
        lambda workspace_id="default": (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/workspace")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "STORAGE_UNAVAILABLE"


def test_strategy_backtest_returns_unified_shape(monkeypatch):
    bars = _strategy_bars()
    monkeypatch.setattr(
        app_module,
        "_load_history_with_fallback",
        lambda code, limit, is_index=False: (bars, "tencent", "2026-08-30", "tencent"),
    )
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/backtest",
            json={
                "strategyType": "ma_cross",
                "code": "600519",
                "config": {"fastPeriod": 5, "slowPeriod": 20},
                "capital": 100000,
                "feeBps": 3,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["strategyType"] == "ma_cross"
    assert data["metrics"]["tradeCount"] >= 0
    assert "equityCurve" in data
    assert "assumptions" in data
    assert data["history"][0]["date"] == bars[0]["date"]


def test_strategy_backtest_save_persists_strategy(monkeypatch):
    bars = _strategy_bars()
    monkeypatch.setattr(
        app_module,
        "_load_history_with_fallback",
        lambda code, limit, is_index=False: (bars, "tencent", "2026-08-30", "tencent"),
    )
    saved = {}

    def fake_save_strategy(payload, workspace_id="default"):
        saved["id"] = payload["id"]
        saved["code"] = payload["code"]
        saved["strategyType"] = payload["strategyType"]
        return {**payload, "id": payload["id"]}

    def fake_save_backtest(strategy_id, code, strategy_type, config, result, workspace_id="default"):
        saved["metrics"] = result["metrics"]

    def fake_get_strategy(strategy_id):
        return {"id": strategy_id, "code": "600519", "strategyType": "ma_cross", "status": "启用"}

    monkeypatch.setattr(app_module, "save_strategy", fake_save_strategy)
    monkeypatch.setattr(app_module, "save_strategy_backtest", fake_save_backtest)
    monkeypatch.setattr(app_module, "get_strategy", fake_get_strategy)
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/backtest",
            json={
                "strategyType": "dca",
                "code": "600519",
                "name": "茅台定投",
                "config": {"amountPerPeriod": 5000, "intervalDays": 5, "stopProfitPct": 20, "stopLossPct": 15},
                "capital": 100000,
                "schedule": "manual",
                "save": True,
            },
        )
    assert resp.status_code == 200
    assert saved["code"] == "600519"
    assert saved["strategyType"] == "dca"
    assert "metrics" in saved


def test_strategy_backtest_falls_back_to_local_cache(monkeypatch):
    bars = _strategy_bars()
    monkeypatch.setattr(
        app_module,
        "_load_history_with_fallback",
        lambda code, limit, is_index=False: (bars, "local", "2026-08-29", "local"),
    )
    from fastapi.testclient import TestClient

    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/backtest",
            json={
                "strategyType": "macd",
                "code": "600519",
                "config": {"fastPeriod": 12, "slowPeriod": 26, "signalPeriod": 9},
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dataSource"] == "local"


# ===== data_source 边缘分支（numeric / classify_code / price_limit / _http_get / parse / load 等） =====


def test_numeric_handles_empty_and_invalid():
    from backend.data_source import numeric

    assert numeric(None) is None
    assert numeric("") is None
    assert numeric("-") is None
    assert numeric("—") is None
    assert numeric("abc") is None
    assert numeric("12.5") == 12.5


def test_classify_code_deep_etf_and_unknown():
    assert data_source.classify_code("159915")["securityType"] == "ETF"
    assert data_source.classify_code("159915")["board"] == "深市ETF"
    assert data_source.classify_code("181888")["board"] == "深市ETF"
    assert data_source.classify_code("900001")["exchange"] == "未知"


def test_market_for_code_maps_market():
    assert data_source.market_for_code("600519") == "沪深主板"
    assert data_source.market_for_code("900001") == "未知"


def test_price_limit_ratio_by_board():
    assert data_source.price_limit_ratio("830799") == 0.30  # 北交所
    assert data_source.price_limit_ratio("300750") == 0.20  # 创业板
    assert data_source.price_limit_ratio("688981") == 0.20  # 科创板
    assert data_source.price_limit_ratio("600519") == 0.10


def test_http_get_raises_after_retries_exhausted(monkeypatch):
    def always_fail(url, params=None, headers=None, timeout=None):
        raise data_source.requests.ConnectionError("boom")

    monkeypatch.setattr(data_source.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(data_source.requests, "get", always_fail)
    data_source.apply_runtime_config(retry_count=2)
    try:
        try:
            data_source._http_get("https://example.test", {})
            raise AssertionError("should raise")
        except data_source.requests.ConnectionError:
            pass
    finally:
        data_source.apply_runtime_config(retry_count=1)


def test_parse_quote_body_short_or_invalid_returns_none():
    assert data_source.parse_quote_body("sh600519", "v_sh600519=") is None  # 长度 < 35
    values = [""] * 54
    values[1] = "贵州茅台"
    values[2] = "600519"
    values[3] = "abc"  # 价格非数值 → prev_close 也不为 None？need prev_close set
    values[4] = "2033.00"
    assert data_source.parse_quote_body("sh600519", "~".join(values)) is None  # price=None → None


def test_load_quote_symbols_parses_multiple_quotes(monkeypatch):
    def quote_body(name, code, price):
        values = [""] * 54
        values[1] = name
        values[2] = code
        values[3] = price
        values[4] = "10.0"
        return "~".join(values)

    body = (
        f'v_sh600519="{quote_body("贵州茅台", "600519", "2060.9")}";'
        f'v_sz000001="{quote_body("平安银行", "000001", "11.2")}";'
    )
    monkeypatch.setattr(data_source, "fetch_text", lambda url, params: body)
    data_source.cache.clear()
    quotes = data_source.load_quote_symbols(["sh600519", "sz000001", "sz666666"])
    assert [q["code"] for q in quotes] == ["600519", "000001"]


def test_load_queries_uses_tencent_symbols(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        data_source, "load_quote_symbols", lambda symbols: seen.update(symbols=symbols) or [{"code": "600519"}]
    )
    data_source.cache.clear()
    quotes = data_source.load_quotes(["600519", " 600519 "])
    assert quotes == [{"code": "600519"}]
    assert seen["symbols"] == ["sh600519"]


def test_load_history_skips_short_rows(monkeypatch):
    def fake_fetch_json(url, params):
        return {
            "data": {
                "sh600519": {
                    "qfqday": [
                        ["2026-08-06", 10, 11, 12, 9],  # 只有 5 个元素 → 跳过
                        ["2026-08-07", 10, 11, 12, 9, 1000, 11000],
                    ]
                }
            }
        }

    monkeypatch.setattr(data_source, "fetch_json", fake_fetch_json)
    data_source.cache.clear()
    history = data_source.load_history("600519", limit=40)
    assert len(history) == 1
    assert history[0]["date"] == "2026-08-07"
    assert history[0]["amount"] == 11000


def test_load_market_builds_quotes_and_indices(monkeypatch):
    stock = {"code": "600519", "name": "贵州茅台", "price": 2060.9}
    idx = {"code": "000001", "name": "上证指数", "price": 3100.1}

    monkeypatch.setattr(data_source, "load_quotes", lambda codes: [stock] if "600519" in codes else [])
    monkeypatch.setattr(
        data_source, "load_quote_symbols", lambda symbols: [idx] if any("000001" in s for s in symbols) else []
    )
    data_source.cache.clear()
    payload = data_source.load_market(["600519"])
    assert payload["quotes"][0]["code"] == "600519"
    assert payload["indices"][0]["name"] == "上证指数"
    assert payload["indices"][0]["securityType"] == "指数"


def test_load_screener_filters_by_market(monkeypatch):
    rows = [
        {"code": "600001", "market": "沪深主板", "change": 1.0},
        {"code": "300001", "market": "创业板", "change": 2.0},
    ]
    monkeypatch.setattr(data_source, "load_quotes", lambda codes: rows)
    payload = data_source.load_screener("创业板", page_size=20)
    assert [r["code"] for r in payload["rows"]] == ["300001"]


def test_normalize_rank_item_handles_empty_values():
    from backend.data_source import _normalize_rank_item

    item = _normalize_rank_item({"code": "sh600519", "zxj": "", "zdf": "bad", "name": "贵州茅台"})
    assert item["price"] is None
    assert item["changePct"] is None


# ===== app.py 路由覆盖率补全 =====


def test_workspace_put_storage_failure_returns_503(monkeypatch):
    monkeypatch.setattr(app_module, "get_workspace_revision", lambda workspace_id="default": 0, raising=False)
    monkeypatch.setattr(
        app_module,
        "save_workspace",
        lambda payload, workspace_id="default": (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.put("/api/workspace", json={"watchlist": [], "plans": [], "alerts": []})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "STORAGE_UNAVAILABLE"


def test_settings_get_falls_back_to_defaults_on_storage_error(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "get_workspace_settings",
        lambda workspace_id="default": (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/settings")
    assert resp.status_code == 200
    assert resp.json()["data"]["refreshInterval"] == 15


def test_settings_put_saves_and_applies(monkeypatch):
    saved_payload = {}

    def fake_save(payload, workspace_id="default"):
        saved_payload["payload"] = dict(payload)
        return {
            **payload,
            "timeoutSeconds": 7,
            "retryCount": 2,
            "cacheSeconds": 5,
            "rateLimitRps": 10,
        }

    monkeypatch.setattr(app_module, "save_workspace_settings", fake_save, raising=False)
    with TestClient(app_module.create_app()) as client:
        resp = client.put("/api/settings", json={"timeoutSeconds": 7, "refreshInterval": 30})
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["timeoutSeconds"] == 7
    assert "timeoutSeconds" in saved_payload["payload"]


def test_settings_put_validation_failure(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "save_workspace_settings",
        lambda payload, workspace_id="default": (_ for _ in ()).throw(RuntimeError("boom")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.put("/api/settings", json={"refreshInterval": 30})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_lifespan_survives_settings_failure(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "get_workspace_settings",
        lambda workspace_id="default": (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200


def test_grid_preview_returns_suggestion(monkeypatch):
    bars = _strategy_bars()
    monkeypatch.setattr(
        app_module,
        "_load_history_with_fallback",
        lambda code, limit, is_index=False: (bars, "tencent", "2026-08-30", "tencent"),
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.post("/api/grid/preview", json={"code": "600519", "gridCount": 6, "capital": 100000})
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "600519"
    assert data["dataSource"] == "tencent"
    assert "lower" in data["suggestion"]


def test_grid_preview_history_failure_returns_422(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_load_history_with_fallback",
        lambda code, limit, is_index=False: (_ for _ in ()).throw(RuntimeError("no data")),
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.post("/api/grid/preview", json={"code": "600519"})
    assert resp.status_code == 422


def test_grid_backtest_returns_unified_shape(monkeypatch):
    bars = _strategy_bars()
    monkeypatch.setattr(
        app_module,
        "_load_history_with_fallback",
        lambda code, limit, is_index=False: (bars, "tencent", "2026-08-30", "tencent"),
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/grid/backtest",
            json={
                "code": "600519",
                "lower": 80,
                "upper": 130,
                "gridCount": 6,
                "capital": 100000,
                "feeBps": 3,
                "mode": "classic",
                "lookback": 120,
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "600519"
    assert data["config"]["gridCount"] == 6
    assert "metrics" in data
    assert data["history"][0]["date"] == bars[0]["date"]


def test_grid_backtest_with_save_persists_strategy(monkeypatch):
    bars = _strategy_bars()
    monkeypatch.setattr(
        app_module,
        "_load_history_with_fallback",
        lambda code, limit, is_index=False: (bars, "tencent", "2026-08-30", "tencent"),
    )
    calls = {}

    def fake_save_grid_strategy(payload, workspace_id="default"):
        calls["payload"] = payload
        return {**payload, "id": payload["id"], "workspaceId": workspace_id}

    monkeypatch.setattr(app_module, "save_grid_strategy", fake_save_grid_strategy)
    monkeypatch.setattr(app_module, "save_grid_backtest", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "schedule_strategy", lambda strategy: None)
    monkeypatch.setattr(
        app_module, "get_grid_strategy", lambda sid: {"id": sid, "code": "600519", "workspaceId": "default"}
    )

    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/grid/backtest",
            json={
                "code": "600519",
                "lower": 80,
                "upper": 130,
                "gridCount": 6,
                "capital": 100000,
                "feeBps": 3,
                "mode": "classic",
                "name": "茅台网格",
                "schedule": "daily",
                "save": True,
                "id": "g-cov-save",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert calls["payload"]["schedule"] == "daily"
    assert data["strategy"]["id"] == "g-cov-save"


def test_grid_backtest_history_failure_returns_422(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_load_history_with_fallback",
        lambda code, limit, is_index=False: (_ for _ in ()).throw(RuntimeError("no data")),
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/grid/backtest",
            json={"code": "600519", "lower": 80, "upper": 130, "gridCount": 6, "capital": 100000},
        )
    assert resp.status_code == 422


def test_grid_optimize_returns_candidates(monkeypatch):
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )
    bars = _strategy_bars(60)
    monkeypatch.setattr("backend.data_source.load_history", lambda code, limit=40, is_index=False: bars)
    monkeypatch.setattr(app_module, "save_market_bars", lambda code, history: "2026-08-30")
    with TestClient(app_module.create_app()) as client:
        resp = client.post("/api/grid/optimize", json={"code": "600519", "capital": 100000, "feeBps": 3})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["candidates"]) >= 1


def test_grid_optimize_history_failure_returns_422(monkeypatch):
    monkeypatch.setattr(
        "backend.data_source.load_history",
        lambda code, limit=40, is_index=False: (_ for _ in ()).throw(RuntimeError("no data")),
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.post("/api/grid/optimize", json={"code": "600519"})
    assert resp.status_code == 422


def test_grid_strategies_lists_strategies(monkeypatch):
    monkeypatch.setattr(app_module, "list_grid_strategies", lambda workspace_id="default": [], raising=False)
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/grid/strategies")
    assert resp.status_code == 200
    assert resp.json()["strategies"] == []


def test_grid_strategies_storage_failure_returns_503(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "list_grid_strategies",
        lambda workspace_id="default": (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/grid/strategies")
    assert resp.status_code == 503


def test_grid_strategy_status_update_success(monkeypatch):
    strategy = {"id": "g1", "workspaceId": "default", "status": "启用", "schedule": "manual"}
    monkeypatch.setattr(app_module, "get_grid_strategy", lambda sid: dict(strategy), raising=False)
    monkeypatch.setattr(
        app_module, "save_grid_strategy", lambda payload, workspace_id="default": payload, raising=False
    )
    monkeypatch.setattr(app_module, "schedule_strategy", lambda strategy: None, raising=False)
    with TestClient(app_module.create_app()) as client:
        resp = client.patch("/api/grid/strategies/g1", json={"status": "暂停"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "暂停"


def test_grid_strategy_status_not_found(monkeypatch):
    monkeypatch.setattr(app_module, "get_grid_strategy", lambda sid: None, raising=False)
    with TestClient(app_module.create_app()) as client:
        resp = client.patch("/api/grid/strategies/absent", json={"status": "暂停"})
    assert resp.status_code == 404


def test_grid_strategy_delete_success(monkeypatch):
    monkeypatch.setattr(app_module, "delete_grid_strategy", lambda sid, workspace_id="default": True, raising=False)
    monkeypatch.setattr(app_module, "unschedule_strategy", lambda sid: None, raising=False)
    with TestClient(app_module.create_app()) as client:
        resp = client.delete("/api/grid/strategies/g1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_strategy_list_storage_failure_returns_503(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "list_strategies",
        lambda workspace_id="default": (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/strategy/strategies")
    assert resp.status_code == 503


def test_strategy_status_update_success(monkeypatch):
    strategy = {"id": "s1", "workspaceId": "default", "status": "启用", "schedule": "manual"}
    monkeypatch.setattr(app_module, "get_strategy", lambda sid: dict(strategy), raising=False)
    monkeypatch.setattr(app_module, "save_strategy", lambda payload, workspace_id="default": payload, raising=False)
    monkeypatch.setattr(app_module, "schedule_strategy", lambda strategy: None, raising=False)
    with TestClient(app_module.create_app()) as client:
        resp = client.patch("/api/strategy/strategies/s1", json={"status": "暂停"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "暂停"


def test_strategy_delete_success(monkeypatch):
    monkeypatch.setattr(app_module, "delete_generic_strategy", lambda sid, workspace_id="default": True, raising=False)
    monkeypatch.setattr(app_module, "unschedule_strategy", lambda sid: None, raising=False)
    with TestClient(app_module.create_app()) as client:
        resp = client.delete("/api/strategy/strategies/s1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_strategy_backtest_unknown_type_returns_422():
    with TestClient(app_module.create_app()) as client:
        resp = client.post("/api/strategy/backtest", json={"strategyType": "nope", "code": "600519", "config": {}})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_strategy_backtest_history_failure_returns_422(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "_load_history_with_fallback",
        lambda code, limit, is_index=False: (_ for _ in ()).throw(RuntimeError("no data")),
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/backtest",
            json={
                "strategyType": "ma_cross",
                "code": "600519",
                "config": {"fastPeriod": 5, "slowPeriod": 20},
            },
        )
    assert resp.status_code == 422


def test_screener_upstream_failure_returns_502(monkeypatch):
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS)
    )
    monkeypatch.setattr(
        "backend.data_source.load_screener",
        lambda market, page_size: (_ for _ in ()).throw(ConnectionError("upstream down")),
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/screener")
    assert resp.status_code == 502


def test_screener_v2_upstream_failure_returns_502(monkeypatch):
    def boom(page=1, page_size=50, sort_by="changePct", sort_dir="desc"):
        raise ConnectionError("rank down")

    monkeypatch.setattr(data_source, "load_screener_v2", boom)
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/screener/v2")
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_lifespan_survives_storage_init_failure(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "initialize_storage",
        lambda: (_ for _ in ()).throw(RuntimeError("db init down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200


def test_lifespan_survives_scheduler_failure(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "start_scheduler",
        lambda: (_ for _ in ()).throw(RuntimeError("scheduler down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200


def test_grid_strategy_status_update_storage_failure_returns_503(monkeypatch):
    strategy = {"id": "g1", "workspaceId": "default", "status": "启用", "schedule": "manual"}
    monkeypatch.setattr(app_module, "get_grid_strategy", lambda sid: dict(strategy), raising=False)
    monkeypatch.setattr(
        app_module,
        "save_grid_strategy",
        lambda payload, workspace_id="default": (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.patch("/api/grid/strategies/g1", json={"status": "暂停"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "STORAGE_UNAVAILABLE"


def test_grid_strategy_delete_storage_failure_returns_503(monkeypatch):
    monkeypatch.setattr(app_module, "delete_grid_strategy", lambda sid, workspace_id="default": True, raising=False)
    monkeypatch.setattr(
        app_module,
        "unschedule_strategy",
        lambda sid: (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.delete("/api/grid/strategies/g1")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "STORAGE_UNAVAILABLE"


def test_strategy_status_update_storage_failure_returns_503(monkeypatch):
    strategy = {"id": "s1", "workspaceId": "default", "status": "启用", "schedule": "manual"}
    monkeypatch.setattr(app_module, "get_strategy", lambda sid: dict(strategy), raising=False)
    monkeypatch.setattr(
        app_module,
        "save_strategy",
        lambda payload, workspace_id="default": (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.patch("/api/strategy/strategies/s1", json={"status": "暂停"})
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "STORAGE_UNAVAILABLE"


def test_strategy_delete_storage_failure_returns_503(monkeypatch):
    monkeypatch.setattr(app_module, "delete_generic_strategy", lambda sid, workspace_id="default": True, raising=False)
    monkeypatch.setattr(
        app_module,
        "unschedule_strategy",
        lambda sid: (_ for _ in ()).throw(RuntimeError("db down")),
        raising=False,
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.delete("/api/strategy/strategies/s1")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "STORAGE_UNAVAILABLE"


def test_strategy_delete_not_found_returns_404(monkeypatch):
    monkeypatch.setattr(app_module, "delete_generic_strategy", lambda sid, workspace_id="default": False, raising=False)
    with TestClient(app_module.create_app()) as client:
        resp = client.delete("/api/strategy/strategies/absent")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"
