from __future__ import annotations

from typing import Any

from backend.sources.cn_impl import CNAssetMetadata, CNDataNormalizer, CNMarketCalendar
from backend.sources.tencent import TencentSource


def test_tencent_source_basic_attributes() -> None:
    source = TencentSource()
    assert source.id == "tencent"
    assert source.name == "腾讯公开行情"
    assert source.available is True
    assert source.provider_label == "Tencent public quote API"


def test_tencent_source_capabilities_realtime_no_fundamental() -> None:
    source = TencentSource()
    assert "realtime" in source.capabilities
    assert "history" in source.capabilities
    assert "screener" in source.capabilities
    assert "paged_screener" in source.capabilities
    assert "fundamental" not in source.capabilities
    assert source.capabilities == frozenset({"realtime", "history", "screener", "paged_screener"})


def test_tencent_source_cn_components() -> None:
    source = TencentSource()
    assert isinstance(source.calendar, CNMarketCalendar)
    assert isinstance(source.normalizer, CNDataNormalizer)
    assert isinstance(source.metadata, CNAssetMetadata)


def test_tencent_source_load_quotes_delegates(monkeypatch) -> None:
    called: list[tuple[str, list[str]]] = []

    def fake_load_quotes(codes: list[str]) -> list[dict[str, Any]]:
        called.append(("quotes", codes))
        return [{"code": "600519"}]

    monkeypatch.setattr("backend.data_source.load_quotes", fake_load_quotes)
    result = TencentSource().load_quotes(["600519"])
    assert called == [("quotes", ["600519"])]
    assert result == [{"code": "600519"}]


def test_tencent_source_load_history_delegates(monkeypatch) -> None:
    called: list[tuple[str, int, bool]] = []

    def fake_load_history(code: str, limit: int, is_index: bool) -> list[dict[str, Any]]:
        called.append((code, limit, is_index))
        return [{"date": "2026-09-02", "close": 1500.0}]

    monkeypatch.setattr("backend.data_source.load_history", fake_load_history)
    result = TencentSource().load_history("600519", limit=10, is_index=True)
    assert called == [("600519", 10, True)]
    assert result == [{"date": "2026-09-02", "close": 1500.0}]


def test_tencent_source_load_history_defaults(monkeypatch) -> None:
    called: list[tuple[str, int, bool]] = []

    def fake_load_history(code: str, limit: int, is_index: bool) -> list[dict[str, Any]]:
        called.append((code, limit, is_index))
        return []

    monkeypatch.setattr("backend.data_source.load_history", fake_load_history)
    TencentSource().load_history("600519")
    assert called == [("600519", 40, False)]


def test_tencent_source_load_market_delegates(monkeypatch) -> None:
    called: list[list[str]] = []

    def fake_load_market(codes: list[str]) -> dict[str, Any]:
        called.append(codes)
        return {"provider": "Tencent public quote API", "quotes": [], "indices": [], "errors": []}

    monkeypatch.setattr("backend.data_source.load_market", fake_load_market)
    result = TencentSource().load_market(["600519", "000001"])
    assert called == [["600519", "000001"]]
    assert result["provider"] == "Tencent public quote API"


def test_tencent_source_load_screener_delegates(monkeypatch) -> None:
    called: list[tuple[str, int]] = []

    def fake_load_screener(market: str, page_size: int) -> dict[str, Any]:
        called.append((market, page_size))
        return {"total": 1, "rows": [], "universeSize": 50}

    monkeypatch.setattr("backend.data_source.load_screener", fake_load_screener)
    result = TencentSource().load_screener("全部", page_size=100)
    assert called == [("全部", 100)]
    assert result == {"total": 1, "rows": [], "universeSize": 50}


def test_tencent_source_load_screener_defaults(monkeypatch) -> None:
    called: list[tuple[str, int]] = []

    def fake_load_screener(market: str, page_size: int) -> dict[str, Any]:
        called.append((market, page_size))
        return {"total": 0, "rows": [], "universeSize": 50}

    monkeypatch.setattr("backend.data_source.load_screener", fake_load_screener)
    TencentSource().load_screener("全部")
    assert called == [("全部", 300)]
