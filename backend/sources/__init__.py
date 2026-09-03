"""数据源注册表：构建 Router + 源元信息（Task 6 后端基础集成）。

build_router() / get_all_sources_info() 共用同一注册逻辑（_registered_sources()），
保证 /api/settings sources 列表与实际路由注册一致。
"""

from __future__ import annotations

import os

from backend.sources.base import DataSource
from backend.sources.eastmoney import EastMoneySource
from backend.sources.mock_us import MockUSSource
from backend.sources.router import DataSourceRouter
from backend.sources.tencent import TencentSource


def _registered_sources() -> list[DataSource]:
    """当前注册的源列表：tencent + eastmoney；MOCK_US_ENABLED 开启时追加 mock_us。"""
    sources: list[DataSource] = [TencentSource(), EastMoneySource()]
    if os.environ.get("MOCK_US_ENABLED", "").lower() in ("1", "true", "yes"):
        sources.append(MockUSSource())
    return sources


def build_router() -> DataSourceRouter:
    """构建含全部已注册源的 Router（mock_us 仅当 MOCK_US_ENABLED 开启时注册）。"""
    return DataSourceRouter({source.id: source for source in _registered_sources()})


def get_source_info(source: DataSource) -> dict[str, bool | str]:
    """单个源的元信息 dict（/api/settings sources 条目用）。"""
    return {
        "id": source.id,
        "name": source.name,
        "realtime": "realtime" in source.capabilities,
        "history": "history" in source.capabilities,
        "screener": "screener" in source.capabilities,
        "fundamental": "fundamental" in source.capabilities,
        "available": source.available,
        "providerLabel": source.provider_label,
    }


def get_all_sources_info() -> list[dict[str, bool | str]]:
    """所有已注册源元信息（/api/settings sources 列表用）。"""
    return [get_source_info(source) for source in _registered_sources()]
