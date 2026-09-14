"""P2-M2 cached()×CacheFacade 接线测试（I8）：L2 回填/写穿/降级真实 age/白名单零触达。

既有 cached 测试（test_backend_api）零修改通过=同文件回归；本文件只加新面。
"""

import pytest
from backend import data_source, redis_cache


class SpyFacade:
    """记录型 facade：store 值以 (age_seconds, value) 存放，get 一律视为新鲜。"""

    def __init__(self):
        self.store: dict[str, tuple[float, object]] = {}
        self.sets: list[tuple] = []
        self.state_value = "connected"

    def get(self, key):
        if not key.startswith(redis_cache.WHITELIST_PREFIXES):
            return None
        hit = self.store.get(key)
        if hit and hit[0] <= data_source.current_cache_ttl() + 5:  # 真实门面同款新鲜窗
            return hit[1]
        return None

    def stale_read(self, key, max_age):
        if not key.startswith(redis_cache.WHITELIST_PREFIXES):
            return None
        hit = self.store.get(key)
        if hit and hit[0] <= max_age:
            return hit[1], hit[0]
        return None

    def set(self, key, value, ttl):
        self.sets.append((key, value, ttl))
        if key.startswith(redis_cache.WHITELIST_PREFIXES):
            self.store[key] = (0, value)

    def state(self):
        return self.state_value


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(data_source, "cache", {})
    monkeypatch.setattr(data_source, "_facade", None)
    monkeypatch.setattr(data_source, "stale_marker", {"at": 0.0, "age": 0.0})
    yield


def test_l2_hit_backfills_l1_without_loader():
    f = SpyFacade()
    f.store["quotes:a"] = (0, {"px": 1})
    data_source.set_facade(f)
    calls = []
    value = data_source.cached("quotes:a", lambda: calls.append(1) or {"px": 99})
    assert value == {"px": 1} and calls == []
    assert data_source.cache["quotes:a"][1] == {"px": 1}  # L1 回填


def test_write_through_after_loader():
    f = SpyFacade()
    data_source.set_facade(f)
    value = data_source.cached("history:x:40:", lambda: [1, 2])
    assert value == [1, 2]
    assert f.sets == [("history:x:40:", [1, 2], data_source.current_cache_ttl())]


def test_degraded_prefers_l2_stale_with_honest_age():
    f = SpyFacade()
    f.store["quotes:a"] = (45.0, {"px": 7})
    data_source.set_facade(f)

    def boom():
        raise ConnectionError("upstream down")

    value = data_source.cached("quotes:a", boom)
    assert value == {"px": 7}
    marker = data_source.recent_stale(window=5.0)
    assert marker is not None and marker["age"] == 45.0  # L2 真实 age 进降级标记


def test_degraded_beyond_stale_window_raises():
    f = SpyFacade()
    f.store["quotes:a"] = (99_999.0, {"px": 7})  # 超 1800s 语义过期
    data_source.set_facade(f)
    with pytest.raises(ConnectionError):
        data_source.cached("quotes:a", lambda: (_ for _ in ()).throw(ConnectionError("upstream down")))


def test_none_facade_legacy_path_intact():
    value = data_source.cached("quotes:a", lambda: "v1")
    assert value == "v1" and data_source.cache["quotes:a"][1] == "v1"


def test_screener_key_never_reaches_facade():
    f = SpyFacade()
    data_source.set_facade(f)
    value = data_source.cached("screener_v2:p1:asc", lambda: {"rows": [1]})
    assert value == {"rows": [1]}
    assert f.store == {}  # 永不入 L2（D6；门面调用记账非本面职责，facade 内部白名单另有专测）


def test_load_quote_symbols_uses_sorted_key_end_to_end(monkeypatch):
    fetched = []

    def fake_text(url, params):
        fetched.append(params["q"])
        return ""  # 解析空不干扰本测试面：只验缓存键归一

    monkeypatch.setattr(data_source, "fetch_text", fake_text)
    data_source.load_quote_symbols(["sz000001", "sh600000"])
    r2 = data_source.load_quote_symbols(["sh600000", "sz000001"])
    assert fetched == ["sh600000,sz000001"]  # 乱序入参命中同一缓存条目（sorted 键归一，上游串亦归一）
    assert r2 == []


def test_facade_state_helpers():
    assert data_source.facade_state() == "down"  # 未接线=down（无配置语义）
    f = SpyFacade()
    data_source.set_facade(f)
    assert data_source.facade_state() == "connected"
