import pytest
from backend.sources.base import DataSource
from backend.sources.router import FALLBACK_MAX_DEPTH, DataSourceRouter


def make_mock_source(source_id: str, capabilities: set[str], available: bool = True):
    _capabilities = capabilities  # capture to avoid class-scope name collision
    _available = available

    class MockSource(DataSource):
        id = source_id
        name = source_id
        capabilities = frozenset(_capabilities)  # type: ignore
        available = _available
        provider_label = source_id
        _calendar = None
        _normalizer = None
        _metadata = None

        @property
        def calendar(self):
            return self._calendar

        @property
        def normalizer(self):
            return self._normalizer

        @property
        def metadata(self):
            return self._metadata

        def load_quotes(self, codes):
            return []

        def load_history(self, code, limit=40, is_index=False):
            return []

        def load_market(self, codes):
            return {}

        def load_screener(self, market, page_size=300):
            return {}

    return MockSource()


def test_router_route_success():
    s1 = make_mock_source("tencent", {"realtime", "history"})
    router = DataSourceRouter({"tencent": s1})
    assert router.route("tencent", "realtime").id == "tencent"


def test_router_route_missing_capability():
    s1 = make_mock_source("tencent", {"history"})
    router = DataSourceRouter({"tencent": s1})
    with pytest.raises(ValueError, match="does not support"):
        router.route("tencent", "realtime")


def test_router_route_unavailable():
    s1 = make_mock_source("tencent", {"realtime"}, available=False)
    router = DataSourceRouter({"tencent": s1})
    with pytest.raises(ValueError, match="not available"):
        router.route("tencent", "realtime")


def test_router_fallback_chain():
    s1 = make_mock_source("tencent", {"realtime"})
    s2 = make_mock_source("eastmoney", {"realtime", "history"})
    s3 = make_mock_source("mock_us", {"realtime", "history"})
    router = DataSourceRouter({"tencent": s1, "eastmoney": s2, "mock_us": s3})
    chain = list(router.fallback_chain("realtime", ["eastmoney", "tencent"]))
    assert len(chain) <= FALLBACK_MAX_DEPTH
    assert chain[0].id == "eastmoney"  # 首选


def test_router_fallback_unavailable():
    s1 = make_mock_source("tencent", {"realtime"}, available=False)
    s2 = make_mock_source("eastmoney", {"realtime"})
    router = DataSourceRouter({"tencent": s1, "eastmoney": s2})
    chain = list(router.fallback_chain("realtime", ["tencent"]))
    assert len(chain) == 1
    assert chain[0].id == "eastmoney"  # 跳过不可用的 tencent


def test_router_fallback_chain_max_depth():
    # 超过 FALLBACK_MAX_DEPTH 个可用源时，链最多 FALLBACK_MAX_DEPTH 个
    sources = {f"src{i}": make_mock_source(f"src{i}", {"realtime"}) for i in range(5)}
    router = DataSourceRouter(sources)
    chain = list(router.fallback_chain("realtime", []))
    assert len(chain) == FALLBACK_MAX_DEPTH


def test_router_route_with_fallback():
    s1 = make_mock_source("tencent", {"realtime"}, available=False)
    s2 = make_mock_source("eastmoney", {"realtime"})
    router = DataSourceRouter({"tencent": s1, "eastmoney": s2})
    result = router.route_with_fallback("tencent", "realtime", fallback_enabled=True)
    assert result.id == "eastmoney"


def test_router_route_with_fallback_disabled():
    s1 = make_mock_source("tencent", {"realtime"}, available=False)
    s2 = make_mock_source("eastmoney", {"realtime"})
    router = DataSourceRouter({"tencent": s1, "eastmoney": s2})
    with pytest.raises(ValueError, match="fallback disabled"):
        router.route_with_fallback("tencent", "realtime", fallback_enabled=False)


def test_router_get_source_unknown():
    router = DataSourceRouter({})
    with pytest.raises(ValueError, match="Unknown data source"):
        router.get_source("nonexistent")


def test_router_get_capability_sources():
    s1 = make_mock_source("tencent", {"realtime", "history"})
    s2 = make_mock_source("eastmoney", {"realtime"})
    s3 = make_mock_source("mock_us", {"history"}, available=False)
    router = DataSourceRouter({"tencent": s1, "eastmoney": s2, "mock_us": s3})
    realtime = router.get_capability_sources("realtime")
    assert [s.id for s in realtime] == ["tencent", "eastmoney"]
    history = router.get_capability_sources("history")
    assert [s.id for s in history] == ["tencent"]


def test_router_route_with_fallback_success():
    # 首选源可用 → 直接返回，不降级
    s1 = make_mock_source("tencent", {"realtime"}, available=True)
    s2 = make_mock_source("eastmoney", {"realtime"})
    router = DataSourceRouter({"tencent": s1, "eastmoney": s2})
    result = router.route_with_fallback("tencent", "realtime", fallback_enabled=True)
    assert result.id == "tencent"


def test_router_fallback_chain_duplicate_preferred():
    # 重复 preferred_id 被跳过
    s1 = make_mock_source("tencent", {"realtime"})
    s2 = make_mock_source("eastmoney", {"realtime"})
    router = DataSourceRouter({"tencent": s1, "eastmoney": s2})
    chain = list(router.fallback_chain("realtime", ["tencent", "tencent", "eastmoney"]))
    assert len(chain) == 2
    assert chain[0].id == "tencent"
    assert chain[1].id == "eastmoney"


def test_router_fallback_chain_preferred_fills_max_depth():
    # preferred_ids 足够填满 FALLBACK_MAX_DEPTH，不再追加其他源
    s1 = make_mock_source("a", {"realtime"})
    s2 = make_mock_source("b", {"realtime"})
    s3 = make_mock_source("c", {"realtime"})
    s4 = make_mock_source("d", {"realtime"})  # 不应出现在链中
    router = DataSourceRouter({"a": s1, "b": s2, "c": s3, "d": s4})
    chain = list(router.fallback_chain("realtime", ["a", "b", "c"]))
    assert len(chain) == FALLBACK_MAX_DEPTH
    assert [s.id for s in chain] == ["a", "b", "c"]


def test_router_no_available_source():
    s1 = make_mock_source("tencent", {"realtime"}, available=False)
    router = DataSourceRouter({"tencent": s1})
    with pytest.raises(ValueError, match="No available source"):
        router.route_with_fallback("tencent", "realtime", fallback_enabled=True)
