from __future__ import annotations

from datetime import date, time
from typing import Any

import pytest
from backend.sources.base import (
    AssetMetadata,
    Capability,
    DataNormalizer,
    DataSource,
    MarketCalendar,
)
from backend.sources.cn_impl import (
    CNAssetMetadata,
    CNDataNormalizer,
    CNMarketCalendar,
)


def test_data_source_abc_cannot_instantiate() -> None:
    with pytest.raises(TypeError):
        DataSource()  # type: ignore[abstract]


def test_market_calendar_abc_cannot_instantiate() -> None:
    with pytest.raises(TypeError):
        MarketCalendar()  # type: ignore[abstract]


def test_data_normalizer_abc_cannot_instantiate() -> None:
    with pytest.raises(TypeError):
        DataNormalizer()  # type: ignore[abstract]


def test_asset_metadata_abc_cannot_instantiate() -> None:
    with pytest.raises(TypeError):
        AssetMetadata()  # type: ignore[abstract]


class _CompleteSource(DataSource):
    id = "stub"
    name = "Stub Source"
    capabilities: frozenset[Capability] = frozenset({"realtime", "history"})
    available = True
    provider_label = "Stub 数据源"

    def load_quotes(self, codes: list[str]) -> list[dict[str, Any]]:
        return []

    def load_history(self, code: str, limit: int, is_index: bool) -> list[dict[str, Any]]:
        return []

    def load_market(self, codes: list[str]) -> dict[str, Any]:
        return {}

    def load_screener(self, market: str, page_size: int) -> dict[str, Any]:
        return {}

    @property
    def calendar(self) -> MarketCalendar:
        return CNMarketCalendar()

    @property
    def normalizer(self) -> DataNormalizer:
        return CNDataNormalizer()

    @property
    def metadata(self) -> AssetMetadata:
        return CNAssetMetadata()


def test_complete_data_source_subclass_instantiates() -> None:
    source = _CompleteSource()
    assert source.id == "stub"
    assert source.name == "Stub Source"
    assert source.available is True
    assert source.provider_label == "Stub 数据源"
    assert source.capabilities == frozenset({"realtime", "history"})
    assert source.load_quotes(["600519"]) == []
    assert source.load_history("600519", 10, is_index=False) == []
    assert source.load_market(["600519"]) == {}
    assert source.load_screener("sh", 20) == {}
    assert isinstance(source.calendar, CNMarketCalendar)
    assert isinstance(source.normalizer, CNDataNormalizer)
    assert isinstance(source.metadata, CNAssetMetadata)


def test_cn_calendar_market_and_tz() -> None:
    cal = CNMarketCalendar()
    assert cal.market == "CN"
    assert cal.local_tz() == "Asia/Shanghai"


def test_cn_calendar_is_trading_day() -> None:
    cal = CNMarketCalendar()
    # 2026-09-02 是周三，2026-09-04 是周五
    assert cal.is_trading_day(date(2026, 9, 2)) is True
    assert cal.is_trading_day(date(2026, 9, 4)) is True
    # 2026-09-05 是周六，2026-09-06 是周日
    assert cal.is_trading_day(date(2026, 9, 5)) is False
    assert cal.is_trading_day(date(2026, 9, 6)) is False


def test_cn_calendar_next_trading_day_friday_to_monday() -> None:
    cal = CNMarketCalendar()
    # 2026-09-04 是周五 → 下一交易日是 2026-09-07 周一
    assert cal.next_trading_day(date(2026, 9, 4)) == date(2026, 9, 7)
    # 周六/周日 → 同样落到周一
    assert cal.next_trading_day(date(2026, 9, 5)) == date(2026, 9, 7)
    assert cal.next_trading_day(date(2026, 9, 6)) == date(2026, 9, 7)


def test_cn_calendar_previous_trading_day() -> None:
    cal = CNMarketCalendar()
    # 2026-09-07 周一 → 上一交易日是 2026-09-04 周五
    assert cal.previous_trading_day(date(2026, 9, 7)) == date(2026, 9, 4)
    assert cal.previous_trading_day(date(2026, 9, 5)) == date(2026, 9, 4)


def test_cn_calendar_trading_session() -> None:
    cal = CNMarketCalendar()
    # 交易日 → (9:30, 15:00)
    assert cal.trading_session(date(2026, 9, 2)) == (time(9, 30), time(15, 0))
    # 非交易日 → None
    assert cal.trading_session(date(2026, 9, 5)) is None


def test_cn_normalizer_convert_currency() -> None:
    normalizer = CNDataNormalizer()
    assert normalizer.convert_currency(100, "CNY", "USD") == pytest.approx(13.8889, abs=0.001)
    assert normalizer.convert_currency(10, "USD", "CNY") == 72.0
    assert normalizer.convert_currency(100, "CNY", "CNY") == 100


def test_cn_normalizer_passthrough() -> None:
    normalizer = CNDataNormalizer()
    row = {"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5}
    assert normalizer.normalize_ohlc(row) is row
    assert normalizer.adjust_for_split(row, 1.5) is row


def test_cn_asset_metadata() -> None:
    metadata = CNAssetMetadata()
    assert metadata.currency("600519") == "CNY"
    assert metadata.currency("AAPL") == "CNY"
    assert metadata.market_cap("600519") is None
    assert metadata.sector("600519") is None
