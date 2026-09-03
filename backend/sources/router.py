from __future__ import annotations

import logging
from collections.abc import Iterator

from backend.sources.base import Capability, DataSource

logger = logging.getLogger(__name__)

FALLBACK_MAX_DEPTH = 3


class DataSourceRouter:
    """数据源路由：按能力路由 + 降级链 + 深度上限"""

    def __init__(self, sources: dict[str, DataSource]):
        self._sources = sources

    def get_source(self, source_id: str) -> DataSource:
        if source_id not in self._sources:
            raise ValueError(f"Unknown data source: {source_id}")
        return self._sources[source_id]

    def get_capability_sources(self, capability: Capability) -> list[DataSource]:
        return [s for s in self._sources.values() if capability in s.capabilities and s.available]

    def fallback_chain(self, capability: Capability, preferred_ids: list[str]) -> Iterator[DataSource]:
        """按 preferred_ids 顺序 + 其他可用源，降级链不超过 FALLBACK_MAX_DEPTH。"""
        chain: list[DataSource] = []
        seen_ids: set[str] = set()
        for sid in preferred_ids:
            if sid in seen_ids:
                continue
            if sid in self._sources and capability in self._sources[sid].capabilities and self._sources[sid].available:
                chain.append(self._sources[sid])
                seen_ids.add(sid)
            if len(chain) >= FALLBACK_MAX_DEPTH:
                break
        if len(chain) < FALLBACK_MAX_DEPTH:
            for s in self._sources.values():
                if s.id in seen_ids:
                    continue
                if capability in s.capabilities and s.available:
                    chain.append(s)
                    seen_ids.add(s.id)
                if len(chain) >= FALLBACK_MAX_DEPTH:
                    break
        yield from chain

    def route(self, source_id: str, capability: Capability) -> DataSource:
        source = self.get_source(source_id)
        if capability not in source.capabilities:
            raise ValueError(f"Source {source_id} does not support capability {capability}")
        if not source.available:
            raise ValueError(f"Source {source_id} is not available")
        return source

    def route_with_fallback(self, source_id: str, capability: Capability, fallback_enabled: bool = True) -> DataSource:
        """路由 + 降级链。返回 DataSource，失败时抛 ValueError。"""
        source = self.get_source(source_id) if source_id in self._sources else None
        if source and capability in source.capabilities and source.available:
            return source
        if not fallback_enabled:
            raise ValueError(f"Source {source_id} unavailable for {capability} and fallback disabled")
        # 构建降级链
        preferred = [source_id] if source_id else []
        chain = list(self.fallback_chain(capability, preferred))
        if not chain:
            raise ValueError(f"No available source for capability {capability}")
        chain_log = " → ".join(s.id for s in chain)
        logger.warning("Fallback chain for %s: %s", capability, chain_log)
        return chain[0]  # 返回第一个可用源
