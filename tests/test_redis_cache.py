"""P2-M2 CacheFacade 测试（全离线：fake redis + 假时钟）。I7 契约 + P1 系列回归锚。"""

import json

from backend import redis_cache


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.fail = False
        self.last_px = None
        self.set_calls = 0
        self.get_calls = 0

    def set(self, key, value, px=None):
        self.set_calls += 1
        if self.fail:
            raise ConnectionError("redis down")
        self.last_px = px
        self.store[key] = value
        return True

    def get(self, key):
        self.get_calls += 1
        if self.fail:
            raise ConnectionError("redis down")
        return self.store.get(key)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(ttl=8, client=None, **kw):
    clock = Clock()
    facade = redis_cache.CacheFacade(
        client=client if client is not None else FakeRedis(),
        ttl_getter=lambda: ttl,
        clock=clock,
        **kw,
    )
    facade._clock = clock  # 测试便利：推进假时钟
    return facade


# ── 白名单（I8 断言面） ──────────────────────────────────────────────────────


def test_whitelist_only_quotes_and_history_touch_l2():
    f = make()
    f.set("quotes:sh600000", {"px": 1}, ttl=8)
    f.set("history:sh600000:300:", [1, 2], ttl=8)
    f.set("screener_v2:p1:asc", {"rows": []}, ttl=8)
    f.set("whatever:else", "x", ttl=8)
    assert set(f.client.store) == {
        redis_cache.L2_PREFIX + "quotes:sh600000",
        redis_cache.L2_PREFIX + "history:sh600000:300:",
    }
    assert f.get("screener_v2:p1:asc") is None
    assert f.get("whatever:else") is None
    assert f.client.get_calls == 0  # 非白名单 get 零触达客户端


# ── 新鲜/陈旧语义（P1-1/P1-5 回归锚） ───────────────────────────────────────


def test_fresh_read_then_grace_expiry_rejects():
    f = make(ttl=8)
    f.set("quotes:a", {"px": 9.9}, ttl=8)
    f._clock.t += 8
    assert f.get("quotes:a") == {"px": 9.9}  # ttl+5 宽限内
    f._clock.t += 10
    assert f.get("quotes:a") is None  # 超新鲜窗：get 弃用


def test_take_stale_reaches_within_1800_and_expires_after():
    f = make(ttl=8)
    f.set("history:x", [1, 2], ttl=8)
    f._clock.t += 2000  # 远超新鲜窗
    assert f.take_stale("history:x", 1800) is None  # ts 超 1800s：语义过期
    f2 = make(ttl=8)
    f2.set("history:x", [1, 2], ttl=8)
    f2._clock.t += 100
    assert f2.take_stale("history:x", 1800) == [1, 2]  # 降级窗物理+语义均可达
    assert f2.client.last_px == (1800 + 60) * 1000  # 物理 TTL ≥ STALE+60（P1-1 核心断言）


def test_physical_px_grows_with_large_cache_ttl():
    f = make(ttl=3600)
    f.set("quotes:a", 1, ttl=3600)
    assert f.client.last_px == (3600 + 60) * 1000  # P1-5：随动不被 1860 截短


# ── 严格序列化（P1-3 + 类型不转换红线） ─────────────────────────────────────


def test_unserializable_skips_without_breaker_or_type_conversion():
    f = make()
    for _ in range(5):
        f.set("quotes:a", {"obj": object()}, ttl=8)
    assert f.client.store == {}
    assert f.state() == "connected"  # 跳写绝不推熔断
    assert f.counters["skip_unserializable"] == 5


def test_oversized_value_skipped_without_breaker():
    f = make()
    f.set("quotes:big", "x" * (redis_cache.MAX_L2_BYTES + 1), ttl=8)
    assert f.client.store == {} and f.counters["skip_oversize"] == 1 and f.state() == "connected"


def test_corrupt_l2_payload_decodes_to_none():
    f = make()
    f.client.store[redis_cache.L2_PREFIX + "quotes:a"] = "{not json"
    assert f.get("quotes:a") is None
    assert f.take_stale("quotes:a", 1800) is None


# ── 熔断（D7：仅客户端异常计入） ─────────────────────────────────────────────


def test_breaker_opens_after_three_client_failures_and_recovers():
    f = make()
    f.set("quotes:a", 1, ttl=8)
    f.client.fail = True
    for _ in range(2):  # 已 1 次成功；再来 3 次失败开熔断
        f.get("quotes:a")
    f.get("quotes:b")
    f.get("quotes:c")
    assert f.state() == "bypassed"
    f.client.get_calls = 0
    f.set("quotes:a", 2, ttl=8)  # 熔断期内完全旁路
    assert f.client.get_calls == 0 and f.client.set_calls == 1  # set 也旁路（不计 set_calls 增）
    f.client.fail = False  # 模拟 Redis 恢复
    f._clock.t += redis_cache.BREAKER_SECONDS + 1
    f.set("quotes:a", 1, ttl=8)  # 恢复后重写（旧封装 ts 早已超新鲜窗）
    assert f.get("quotes:a") == 1
    assert f.state() == "connected"


def test_no_client_means_down_facade_is_total_passthrough():
    f = redis_cache.CacheFacade(None, ttl_getter=lambda: 8)
    assert f.state() == "down"
    f.set("quotes:a", 1, ttl=8)
    assert f.get("quotes:a") is None
    assert f.take_stale("quotes:a", 1800) is None


def test_envelope_shape_is_ts_v():
    f = make()
    f.set("quotes:a", {"px": 1}, ttl=8)
    env = json.loads(f.client.store[redis_cache.L2_PREFIX + "quotes:a"])
    assert set(env) == {"ts", "v"} and env["v"] == {"px": 1}


# ── I6 build_facade ──────────────────────────────────────────────────────────


def test_build_facade_without_redis_config_is_down():
    settings = type("S", (), {"redis_host": "", "redis_port": 6379, "redis_password": "", "redis_db": 0})()
    f = redis_cache.build_facade(settings, ttl_getter=lambda: 8)
    assert f.state() == "down"


def test_build_facade_probe_failure_is_down_not_raise():
    settings = type("S", (), {"redis_host": "192.0.2.1", "redis_port": 6399, "redis_password": None, "redis_db": 0})()
    f = redis_cache.build_facade(settings, ttl_getter=lambda: 8)  # 不可达 IP：探测失败吞
    assert f.state() == "down"


def test_build_facade_injected_client_connected():
    f = redis_cache.build_facade(None, client=FakeRedis(), ttl_getter=lambda: 8)
    assert f.state() == "connected"


def test_default_clock_uses_time_module():
    f = redis_cache.CacheFacade(client=FakeRedis(), ttl_getter=lambda: 8)
    f.set("quotes:a", 1, ttl=8)
    assert f.get("quotes:a") == 1  # 真时钟下写入即读必新鲜
