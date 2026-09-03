from __future__ import annotations

import warnings
from datetime import date, datetime, time, timedelta
from typing import Any

from backend.sources.base import AssetMetadata, Capability, DataNormalizer, DataSource, MarketCalendar


class MockUSCalendar(MarketCalendar):
    market = "US"
    # NYSE: Mon-Fri, 9:30-16:00 ET

    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5

    def next_trading_day(self, day: date) -> date:
        d = day + timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d

    def previous_trading_day(self, day: date) -> date:
        d = day - timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def trading_session(self, day: date) -> tuple[time, time] | None:
        if not self.is_trading_day(day):
            return None
        return (time(9, 30), time(16, 0))

    def local_tz(self) -> str:
        return "America/New_York"


class MockUSNormalizer(DataNormalizer):
    def normalize_ohlc(self, raw_row: dict[str, Any]) -> dict[str, Any]:
        return raw_row

    def adjust_for_split(self, row: dict[str, Any], ratio: float) -> dict[str, Any]:
        return row

    def convert_currency(self, value: float, from_currency: str, to_currency: str) -> float:
        RATES = {"CNY": 1, "USD": 7.2}
        return value * RATES[from_currency] / RATES[to_currency]


class MockUSAssetMetadata(AssetMetadata):
    _MOCK_CODES: dict[str, tuple[str | None, int | None, str | None]] = {
        "AAPL": ("USD", 3500000000000, "Technology"),
        "MSFT": ("USD", 3100000000000, "Technology"),
        "TSLA": ("USD", 800000000000, "Consumer Cyclical"),
    }

    def currency(self, code: str) -> str:
        # 未知代码默认按美元处理（美股模拟源）
        return self._MOCK_CODES.get(code, (None, None, None))[0] or "USD"

    def market_cap(self, code: str) -> float | None:
        return self._MOCK_CODES.get(code, (None, None, None))[1]

    def sector(self, code: str) -> str | None:
        return self._MOCK_CODES.get(code, (None, None, None))[2]


class MockUSSource(DataSource):
    id = "mock_us"
    name = "美股模拟行情"
    capabilities = frozenset[Capability]({"realtime", "history", "screener"})
    available = True
    provider_label = "Mock US Market (simulated)"
    # 仅用于 feature/multi-data-source 分支验证
    # 预计移除版本：v2.3.0（真实美股接入后）
    # 若当前日期 > 2027-01-01，启动时抛出 DeprecationWarning

    def __init__(self) -> None:
        warnings.warn("MockUSSource is active — for development verification only", UserWarning, stacklevel=2)
        self._check_expiry()
        self._calendar = MockUSCalendar()
        self._normalizer = MockUSNormalizer()
        self._metadata = MockUSAssetMetadata()

    @staticmethod
    def _check_expiry() -> None:
        if date.today() > date(2027, 1, 1):
            warnings.warn(
                "MockUSSource has expired (past 2027-01-01). "
                "Replace with a real US data source adapter before using in production.",
                DeprecationWarning,
                stacklevel=2,
            )

    @property
    def calendar(self) -> MockUSCalendar:
        return self._calendar

    @property
    def normalizer(self) -> MockUSNormalizer:
        return self._normalizer

    @property
    def metadata(self) -> MockUSAssetMetadata:
        return self._metadata

    # 模拟数据方法
    def load_quotes(self, codes: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "code": c,
                "name": c,
                "price": 100.0,
                "change": 0.5,
                "changeAmount": 0.5,
                "prevClose": 99.5,
                "open": 99.8,
                "high": 101.0,
                "low": 99.0,
                "volume": 1000000,
                "amount": 100000000,
                "exchange": "NYSE",
                "board": "美股",
                "securityType": "股票",
                "market": "美股",
                "updatedAt": int(datetime.now().timestamp() * 1000),
            }
            for c in codes
        ]

    def load_history(self, code: str, limit: int = 40, is_index: bool = False) -> list[dict[str, Any]]:
        import random

        random.seed(hash(code))
        base = random.uniform(80, 120)
        return [
            {
                "date": (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": base + random.uniform(-2, 2),
                "close": base + random.uniform(-2, 2),
                "high": base + random.uniform(0, 3),
                "low": base + random.uniform(-3, 0),
                "volume": int(random.uniform(500000, 2000000)),
                "amount": int(random.uniform(50000000, 500000000)),
            }
            for i in range(limit)
        ]

    def load_market(self, codes: list[str]) -> dict[str, Any]:
        return {
            "provider": "Mock US Market (simulated)",
            "fetchedAt": int(datetime.now().timestamp() * 1000),
            "quotes": self.load_quotes(codes),
            "indices": [],
            "errors": [],
        }

    def load_screener(self, market: str, page_size: int = 300) -> dict[str, Any]:
        return {"total": 0, "rows": [], "universeSize": 0}
