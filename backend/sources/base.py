from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, time
from typing import Any, Literal

Capability = Literal["realtime", "history", "screener", "paged_screener", "fundamental"]


class DataSource(ABC):
    id: str
    name: str
    capabilities: frozenset[Capability]
    available: bool  # token/依赖是否满足
    provider_label: str  # 前端展示的 provider 文案（如"东方财富实时行情"）

    @abstractmethod
    def load_quotes(self, codes: list[str]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def load_history(self, code: str, limit: int, is_index: bool) -> list[dict[str, Any]]: ...

    @abstractmethod
    def load_market(self, codes: list[str]) -> dict[str, Any]: ...

    @abstractmethod
    def load_screener(self, market: str, page_size: int) -> dict[str, Any]: ...

    def load_screener_paged(
        self, page: int = 1, page_size: int = 50, sort_by: str = "changePct", sort_dir: str = "desc"
    ) -> dict[str, Any]:
        """全市场分页排序选股；仅声明 paged_screener 能力位的源实现此方法。"""
        raise NotImplementedError(f"{self.id} does not support paged_screener")

    @property
    @abstractmethod
    def calendar(self) -> MarketCalendar: ...

    @property
    @abstractmethod
    def normalizer(self) -> DataNormalizer: ...

    @property
    @abstractmethod
    def metadata(self) -> AssetMetadata: ...


class MarketCalendar(ABC):
    market: str  # "CN" / "US"

    @abstractmethod
    def is_trading_day(self, day: date) -> bool: ...

    @abstractmethod
    def next_trading_day(self, day: date) -> date: ...

    @abstractmethod
    def previous_trading_day(self, day: date) -> date: ...

    @abstractmethod
    def trading_session(self, day: date) -> tuple[time, time] | None: ...

    @abstractmethod
    def local_tz(self) -> str: ...


class DataNormalizer(ABC):
    @abstractmethod
    def normalize_ohlc(self, raw_row: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    def adjust_for_split(self, row: dict[str, Any], ratio: float) -> dict[str, Any]: ...

    @abstractmethod
    def convert_currency(self, value: float, from_currency: str, to_currency: str) -> float: ...


class AssetMetadata(ABC):
    @abstractmethod
    def currency(self, code: str) -> str: ...  # 返回 "CNY" / "USD"

    @abstractmethod
    def market_cap(self, code: str) -> float | None: ...

    @abstractmethod
    def sector(self, code: str) -> str | None: ...
