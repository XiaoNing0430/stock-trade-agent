from backend import minute_path


def test_period_count_and_parse(monkeypatch):
    minute_path.reset_for_test()
    calls = []

    def fake(url, params, **kwargs):
        calls.append(params)
        return {"data": {"sh600000": {"m5": [["202609150935", "10", "11", "12", "9", "100"]]}}}

    monkeypatch.setattr(minute_path.data_source, "fetch_json", fake)
    result = minute_path.fetch_minute("600000", "5m", 999, now=lambda: 1)
    assert result.state == "ok" and result.source == "upstream"
    assert result.bars[0]["date"] == "2026-09-15 09:35"
    assert calls[0]["param"].endswith(",5,,,320")


def test_rate_limit_and_cache_only(monkeypatch):
    minute_path.reset_for_test()
    monkeypatch.setattr(minute_path.data_source, "fetch_json", lambda *a, **k: {"data": {}})
    assert minute_path.fetch_minute("600000", "1m", 10, now=lambda: 10).state == "ok"
    assert minute_path.fetch_minute("600001", "1m", 10, now=lambda: 10).state == "ok"
    assert minute_path.fetch_minute("600002", "1m", 10, now=lambda: 10).state == "ok"
    assert minute_path.fetch_minute("600003", "1m", 10, now=lambda: 10).state == "rate_limited"
    assert minute_path._cache_only("minute:sh600000:1m:10", "etl_busy", 10).state == "etl_busy"


def test_breaker_opens_after_three_failures(monkeypatch):
    minute_path.reset_for_test()
    monkeypatch.setattr(minute_path.data_source, "fetch_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    for i in range(3):
        minute_path.fetch_minute(f"600{i:03}", "1m", 10, now=lambda i=i: 100 + i * 2)
    assert minute_path.breaker_state(200) == "open"
