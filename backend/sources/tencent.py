from __future__ import annotations

from typing import Any

from backend import data_source as tencent_ds  # 现有模块
from backend.sources.base import Capability, DataSource
from backend.sources.cn_impl import CNAssetMetadata, CNDataNormalizer, CNMarketCalendar


class TencentSource(DataSource):
    id = "tencent"
    name = "腾讯公开行情"
    capabilities = frozenset[Capability]({"realtime", "history", "screener", "paged_screener"})
    available = True
    provider_label = "Tencent public quote API"

    def __init__(self) -> None:
        self._calendar = CNMarketCalendar()
        self._normalizer = CNDataNormalizer()
        self._metadata = CNAssetMetadata()

    @property
    def calendar(self) -> CNMarketCalendar:
        return self._calendar

    @property
    def normalizer(self) -> CNDataNormalizer:
        return self._normalizer

    @property
    def metadata(self) -> CNAssetMetadata:
        return self._metadata

    def load_quotes(self, codes: list[str]) -> list[dict[str, Any]]:
        return tencent_ds.load_quotes(codes)

    def load_history(self, code: str, limit: int = 40, is_index: bool = False) -> list[dict[str, Any]]:
        return tencent_ds.load_history(code, limit, is_index)

    def load_market(self, codes: list[str]) -> dict[str, Any]:
        return tencent_ds.load_market(codes)

    def load_screener(self, market: str, page_size: int = 300) -> dict[str, Any]:
        return tencent_ds.load_screener(market, page_size)

    def load_screener_paged(
        self, page: int = 1, page_size: int = 50, sort_by: str = "changePct", sort_dir: str = "desc"
    ) -> dict[str, Any]:
        """全市场分页排序选股：委托现有腾讯排名接口（含缓存）。"""
        return tencent_ds.load_screener_v2(page=page, page_size=page_size, sort_by=sort_by, sort_dir=sort_dir)
