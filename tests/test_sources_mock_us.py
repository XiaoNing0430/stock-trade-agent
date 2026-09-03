from __future__ import annotations

from datetime import date, time
from typing import Any

import pytest
from backend.sources.mock_us import (
    MockUSAssetMetadata,
    MockUSCalendar,
    MockUSNormalizer,
    MockUSSource,
)


def test_mock_us_source_basic() -> None:
    source = MockUSSource()
    assert source.id == "mock_us"
    assert source.name == "美股模拟行情"
    assert source.available is True
    assert source.provider_label == "Mock US Market (simulated)"
    assert source.capabilities == frozenset({"realtime", "history", "screener"})
    assert "realtime" in source.capabilities
    assert "fundamental" not in source.capabilities
    quotes = source.load_quotes(["AAPL", "MSFT"])
    assert len(quotes) == 2
    assert quotes[0]["code"] == "AAPL"
    assert quotes[0]["price"] == 100.0
    assert quotes[0]["exchange"] == "NYSE"
    assert quotes[0]["market"] == "美股"


def test_mock_us_constructor_warns() -> None:
    # 构造函数必须发出 UserWarning（开发验证用途提示）
    with pytest.warns(UserWarning, match="MockUSSource is active"):
        MockUSSource()


def test_mock_us_components() -> None:
    source = MockUSSource()
    assert isinstance(source.calendar, MockUSCalendar)
    assert isinstance(source.normalizer, MockUSNormalizer)
    assert isinstance(source.metadata, MockUSAssetMetadata)


def test_mock_us_load_history() -> None:
    source = MockUSSource()
    rows = source.load_history("AAPL", limit=3)
    assert len(rows) == 3
    required = {"date", "open", "close", "high", "low", "volume", "amount"}
    assert required.issubset(rows[0].keys())
    assert 500000 <= rows[0]["volume"] <= 2000000


def test_mock_us_load_market() -> None:
    source = MockUSSource()
    market = source.load_market(["AAPL"])
    assert market["provider"] == "Mock US Market (simulated)"
    assert len(market["quotes"]) == 1
    assert market["indices"] == []
    assert market["errors"] == []


def test_mock_us_load_screener() -> None:
    source = MockUSSource()
    assert source.load_screener("US") == {"total": 0, "rows": [], "universeSize": 0}


def test_mock_us_metadata() -> None:
    source = MockUSSource()
    assert source.metadata.currency("AAPL") == "USD"
    assert source.metadata.sector("AAPL") == "Technology"
    assert source.metadata.market_cap("AAPL") == 3500000000000
    assert source.metadata.market_cap("MSFT") == 3100000000000
    assert source.metadata.sector("TSLA") == "Consumer Cyclical"


def test_mock_us_metadata_unknown() -> None:
    metadata = MockUSAssetMetadata()
    # 未知代码 → 货币默认 USD，市值/行业为 None
    assert metadata.currency("UNKNOWN") == "USD"
    assert metadata.market_cap("UNKNOWN") is None
    assert metadata.sector("UNKNOWN") is None


def test_mock_us_calendar() -> None:
    source = MockUSSource()
    assert source.calendar.market == "US"
    # 周六不是交易日
    sat = date(2026, 9, 5)  # Saturday
    assert not source.calendar.is_trading_day(sat)
    # 周日也不是交易日
    assert not source.calendar.is_trading_day(date(2026, 9, 6))  # Sunday
    # 周一至周五是交易日
    mon = date(2026, 9, 7)  # Monday
    assert source.calendar.is_trading_day(mon)
    assert source.calendar.is_trading_day(date(2026, 9, 4)) is True  # Friday


def test_mock_us_calendar_next_trading_day() -> None:
    cal = MockUSCalendar()
    # 2026-09-04 周五 → 下一交易日 2026-09-07 周一
    assert cal.next_trading_day(date(2026, 9, 4)) == date(2026, 9, 7)
    # 周六/周日 → 同样落到周一
    assert cal.next_trading_day(date(2026, 9, 5)) == date(2026, 9, 7)
    assert cal.next_trading_day(date(2026, 9, 6)) == date(2026, 9, 7)


def test_mock_us_calendar_previous_trading_day() -> None:
    cal = MockUSCalendar()
    # 2026-09-07 周一 → 上一交易日 2026-09-04 周五
    assert cal.previous_trading_day(date(2026, 9, 7)) == date(2026, 9, 4)
    assert cal.previous_trading_day(date(2026, 9, 5)) == date(2026, 9, 4)


def test_mock_us_calendar_session() -> None:
    cal = MockUSCalendar()
    # 交易日 → (9:30, 16:00) ET
    assert cal.trading_session(date(2026, 9, 7)) == (time(9, 30), time(16, 0))
    # 非交易日 → None
    assert cal.trading_session(date(2026, 9, 5)) is None
    assert cal.local_tz() == "America/New_York"


def test_mock_us_normalizer() -> None:
    normalizer = MockUSNormalizer()
    row = {"open": 100.0, "close": 101.0}
    assert normalizer.normalize_ohlc(row) is row
    assert normalizer.adjust_for_split(row, 2.0) is row
    # 固定汇率：1 USD ≈ 7.2 CNY
    assert normalizer.convert_currency(10, "USD", "CNY") == 72.0
    assert normalizer.convert_currency(720, "CNY", "USD") == pytest.approx(100.0, abs=0.001)
    assert normalizer.convert_currency(100, "USD", "USD") == 100.0


def test_mock_us_expiry_warning(monkeypatch: Any, recwarn: Any) -> None:
    from datetime import date as _date

    from backend.sources import mock_us

    class _FutureDate(_date):
        @classmethod
        def today(cls) -> _FutureDate:
            return _FutureDate(2028, 1, 1)

    # patch mock_us 模块内的 date 到 2028 年，触发过期 DeprecationWarning
    monkeypatch.setattr(mock_us, "date", _FutureDate)
    MockUSSource._check_expiry()
    deprecations = [w for w in recwarn if issubclass(w.category, DeprecationWarning)]
    assert len(deprecations) >= 1
    assert "expired" in str(deprecations[0].message)
