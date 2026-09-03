from __future__ import annotations

from datetime import date, time, timedelta
from typing import Any

from backend.sources.base import AssetMetadata, DataNormalizer, MarketCalendar


class CNMarketCalendar(MarketCalendar):
    market = "CN"

    def local_tz(self) -> str:
        return "Asia/Shanghai"

    def trading_session(self, day: date) -> tuple[time, time] | None:
        if not self.is_trading_day(day):
            return None
        return (time(9, 30), time(15, 0))

    def is_trading_day(self, day: date) -> bool:
        # 周一至周五，排除元旦/春节（简化版）
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


class CNDataNormalizer(DataNormalizer):
    def normalize_ohlc(self, raw_row: dict[str, Any]) -> dict[str, Any]:
        # 腾讯/东财输出字段名不同，映射到统一格式
        # 适配器先归一化，normalizer 做最终校验
        return raw_row

    def adjust_for_split(self, row: dict[str, Any], ratio: float) -> dict[str, Any]:
        return row  # 上游已前复权(qfq)，无需调整

    def convert_currency(self, value: float, from_currency: str, to_currency: str) -> float:
        # 占位实现，实际汇率需要实时行情
        if from_currency == to_currency:
            return value
        # 固定汇率：1 USD ≈ 7.2 CNY（仅用于跨市场回测占位，非实时）
        RATES = {"CNY": 1, "USD": 7.2}
        return value * RATES[from_currency] / RATES[to_currency]


class CNAssetMetadata(AssetMetadata):
    def currency(self, code: str) -> str:
        return "CNY"

    def market_cap(self, code: str) -> float | None:
        return None  # 由行情数据提供

    def sector(self, code: str) -> str | None:
        return None  # 由 classify_code 提供
