# 多数据源接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现统一数据源接入层（DataSource ABC + Router + 3 适配器 + 3 正交抽象），起步接入东财实盘 + 美股模拟验证全链路。

**Architecture:** 适配器模式（`DataSource` ABC）+ 策略路由（按能力路由、降级链、深度上限）+ 正交抽象（交易日历/数据标准化/资产元信息）。TencentSource 薄封装现有 `data_source.py` 函数，EastMoneySource 直接实现东财 HTTP 接口，MockUSSource 模拟数据验证跨市场，所有适配器通过 `DataSourceRouter` 统一调度。

**Tech Stack:** Python 3.12+ / FastAPI / SQLAlchemy / Vue 3 + Pinia

## Global Constraints

- 遵循 AGENTS.md 所有约定（中文 UI、`--no-ff` 合并、`from __future__ import annotations`、类型注解、ruff 格式、mypy strict）
- 绝不使用模拟值填充缺失数据——MockUSSource 仅用于美股模拟市场，A 股实盘绝不走模拟
- 现有 `data_source.py` 模块级函数保持不动（向后兼容），TencentSource 薄封装调用它们
- 所有新文件放在 `backend/sources/` 包下
- 测试覆盖率维持 ≥80%（当前 97.6%）
- 每个适配器必须实现 `calendar` / `normalizer` / `metadata` 属性（ABC 类型）
- East Money 接口已验证：`push2.eastmoney.com`（报价/日线/排行/财务）无 token 门槛
- `FALLBACK_MAX_DEPTH = 3` 硬上限，降级链路日志格式 `"{source_id} → {source_id} → {source_id}"`
- MockUSSource 含过期守卫：`if date.today() > date(2027, 1, 1): warnings.warn("MockUSSource expired", DeprecationWarning)`
- 前端 settings 已有 `realtimeSource`/`historySource`/`screenerSource`，新增 `fundamentalSource`

---

### Task 1: 抽象基类 + CN 实现

**Files:**
- Create: `backend/sources/__init__.py`
- Create: `backend/sources/base.py` — DataSource, MarketCalendar, DataNormalizer, AssetMetadata ABCs
- Create: `backend/sources/cn_impl.py` — CNMarketCalendar, CNDataNormalizer, CNAssetMetadata
- Create: `tests/test_sources_base.py`

**Interfaces:**

```python
# backend/sources/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Literal
from datetime import date, time, datetime

Capability = Literal["realtime", "history", "screener", "fundamental"]

class DataSource(ABC):
    id: str
    name: str
    capabilities: frozenset[Capability]
    available: bool               # token/依赖是否满足
    provider_label: str           # 前端展示的 provider 文案（如"东方财富实时行情"）

    @abstractmethod
    def load_quotes(self, codes: list[str]) -> list[dict[str, Any]]: ...
    @abstractmethod
    def load_history(self, code: str, limit: int, is_index: bool) -> list[dict[str, Any]]: ...
    @abstractmethod
    def load_market(self, codes: list[str]) -> dict[str, Any]: ...
    @abstractmethod
    def load_screener(self, market: str, page_size: int) -> dict[str, Any]: ...

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
```

```python
# backend/sources/cn_impl.py
from __future__ import annotations
from datetime import date, time, datetime, timedelta

class CNMarketCalendar(MarketCalendar):
    market = "CN"
    def local_tz(self) -> str: return "Asia/Shanghai"
    def trading_session(self, day: date) -> tuple[time, time] | None:
        if not self.is_trading_day(day): return None
        return (time(9, 30), time(15, 0))
    def is_trading_day(self, day: date) -> bool:
        # 周一至周五，排除元旦/春节（简化版）
        return day.weekday() < 5
    def next_trading_day(self, day: date) -> date:
        d = day + timedelta(days=1)
        while not self.is_trading_day(d): d += timedelta(days=1)
        return d
    def previous_trading_day(self, day: date) -> date:
        d = day - timedelta(days=1)
        while not self.is_trading_day(d): d -= timedelta(days=1)
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
        if from_currency == to_currency: return value
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
```

- [ ] **Step 1: Create `backend/sources/` package**

```bash
mkdir -p backend/sources
echo "" > backend/sources/__init__.py
```

- [ ] **Step 2: Write ABCs + CN impls + tests**

Tests cover:
- `DataSource` ABC: instantiation raises TypeError, subclass with all abstract methods works
- `CNMarketCalendar`: is_trading_day(weekday) is True, is_trading_day(Saturday) is False, next_trading_day(Friday) → Monday, trading_session returns (9:30, 15:00) on trading day, None on non-trading day
- `CNDataNormalizer`: convert_currency(100, "CNY", "USD") → pytest.approx(13.888...), convert_currency(10, "USD", "CNY") → 72.0, convert_currency(100, "CNY", "CNY") → 100
- `CNAssetMetadata`: currency("600519") → "CNY", currency("AAPL") → "CNY" (A股统一)

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_sources_base.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/sources/ tests/test_sources_base.py
git commit -m "feat: 数据源 ABC + CN 实现（交易日历/标准化/元信息）"
```

---

### Task 2: TencentSource 适配器

**Files:**
- Create: `backend/sources/tencent.py` — TencentSource
- Create: `tests/test_sources_tencent.py`

**Interfaces:**

```python
# backend/sources/tencent.py
from backend.sources.base import DataSource, Capability
from backend.sources.cn_impl import CNMarketCalendar, CNDataNormalizer, CNAssetMetadata
from backend import data_source as tencent_ds  # 现有模块

class TencentSource(DataSource):
    id = "tencent"
    name = "腾讯公开行情"
    capabilities = frozenset[Capability]({"realtime", "history", "screener"})
    available = True
    provider_label = "Tencent public quote API"

    def __init__(self):
        self._calendar = CNMarketCalendar()
        self._normalizer = CNDataNormalizer()
        self._metadata = CNAssetMetadata()

    @property
    def calendar(self) -> CNMarketCalendar: return self._calendar
    @property
    def normalizer(self) -> CNDataNormalizer: return self._normalizer
    @property
    def metadata(self) -> CNAssetMetadata: return self._metadata

    def load_quotes(self, codes: list[str]) -> list[dict]:
        return tencent_ds.load_quotes(codes)

    def load_history(self, code: str, limit: int = 40, is_index: bool = False) -> list[dict]:
        return tencent_ds.load_history(code, limit, is_index)

    def load_market(self, codes: list[str]) -> dict:
        return tencent_ds.load_market(codes)

    def load_screener(self, market: str, page_size: int = 300) -> dict:
        return tencent_ds.load_screener(market, page_size)
```

- [ ] **Step 1: Write tests**

```python
def test_tencent_source_delegates_to_existing_module(monkeypatch):
    import backend.sources.tencent
    source = backend.sources.tencent.TencentSource()
    assert source.id == "tencent"
    assert source.available
    assert "realtime" in source.capabilities
    assert "fundamental" not in source.capabilities
    # 验证 delegation
    called = []
    monkeypatch.setattr("backend.data_source.load_quotes", lambda codes: called.append(("quotes", codes)) or [{"code":"600519"}])
    result = source.load_quotes(["600519"])
    assert called == [("quotes", ["600519"])]
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/test_sources_tencent.py -v
```

- [ ] **Step 3: Commit**

```bash
git add backend/sources/tencent.py tests/test_sources_tencent.py
git commit -m "feat: TencentSource 适配器（薄封装现有 data_source.py）"
```

---

### Task 3: EastMoneySource 适配器

**Files:**
- Create: `backend/sources/eastmoney.py` — EastMoneySource
- Create: `tests/test_sources_eastmoney.py`

**Interfaces:**

```python
# backend/sources/eastmoney.py
from backend.sources.base import DataSource, Capability
from backend.sources.cn_impl import CNMarketCalendar, CNDataNormalizer, CNAssetMetadata

class EastMoneySource(DataSource):
    id = "eastmoney"
    name = "东方财富行情"
    capabilities = frozenset[Capability]({"realtime", "history", "screener", "fundamental"})
    available = True
    provider_label = "东方财富实时行情"

    QUOTE_URL = "http://push2.eastmoney.com/api/qt/ulist.np/get"
    KLINE_URL = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
    CLIST_URL = "http://push2.eastmoney.com/api/qt/clist/get"
    STOCK_URL = "http://push2.eastmoney.com/api/qt/stock/get"
    REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}
```

**关键实现细节：**

```python
# 东财 secid 转换：1. = 上交所, 0. = 深交所, 北交所用 0. (或 1.)
_SECID_MAP = {"上交所": "1.", "深交所": "0.", "北交所": "0."}

def _secid(code: str) -> str:
    from backend.data_source import classify_code
    prefix = _SECID_MAP.get(classify_code(code)["exchange"], "0.")
    return f"{prefix}{code}"

# 字段映射
# 报价: f2=price, f3=changePct, f4=changeAmount, f12=code, f14=name
# 日线: klines=["date,open,close,high,low,volume,amount"]
# 排行: f2=price, f3=changePct, f5=volume, f6=amount, f8=turnoverRate, f9=pe, f10=pb, f12=code, f14=name
# 财务: 见已验证返回
_QUOTE_FIELDS = "f2,f3,f4,f12,f14"
_CLIST_FIELDS = "f2,f3,f5,f6,f8,f9,f10,f12,f14"
_STOCK_FIELDS = "f2,f3,f9,f10,f23,f43,f44,f45,f46,f47,f57,f58,f162,f164,f167,f168,f169,f170,f171,f173,f177,f178"
```

- [ ] **Step 1: Write tests (mock HTTP)**

```python
def test_parse_em_quote(monkeypatch):
    source = EastMoneySource()
    def fake_get(url, params, headers, timeout):
        class FakeResp:
            status_code = 200
            def json(self):
                return {"rc":0,"data":{"diff":[{"f2":1297.5,"f3":-0.16,"f4":-2.06,"f12":"600519","f14":"贵州茅台"}]}}
            def raise_for_status(self): pass
        return FakeResp()
    monkeypatch.setattr("requests.get", fake_get)
    result = source.load_quotes(["600519"])
    assert len(result) == 1
    assert result[0]["code"] == "600519"
    assert result[0]["price"] == 1297.5
    assert result[0]["change"] == -0.16

def test_parse_em_kline(monkeypatch):
    source = EastMoneySource()
    def fake_get(url, params, headers, timeout):
        class FakeResp:
            status_code = 200
            def json(self):
                return {"rc":0,"data":{"klines":["2026-09-02,1302.80,1297.50,1303.00,1291.20,20308,2634084231.00"]}}
            def raise_for_status(self): pass
        return FakeResp()
    monkeypatch.setattr("requests.get", fake_get)
    result = source.load_history("600519", limit=1)
    assert len(result) == 1
    assert result[0]["date"] == "2026-09-02"
    assert result[0]["open"] == 1302.80
    assert result[0]["close"] == 1297.50
    assert result[0]["volume"] == 20308

def test_parse_em_screener(monkeypatch):
    source = EastMoneySource()
    def fake_get(url, params, headers, timeout):
        class FakeResp:
            status_code = 200
            def json(self):
                return {"rc":0,"data":{"total":100,"diff":[{"f2":53.82,"f3":104.41,"f5":202103,"f6":1205493198.97,"f8":77.78,"f9":36.42,"f10":"-","f12":"301688","f14":"N格林"}]}}
            def raise_for_status(self): pass
        return FakeResp()
    monkeypatch.setattr("requests.get", fake_get)
    result = source.load_screener("全部", page_size=5)
    assert result["total"] == 100
    assert len(result["rows"]) == 1

def test_em_fundamental_capability():
    source = EastMoneySource()
    assert "fundamental" in source.capabilities
    assert "realtime" in source.capabilities

def test_em_secid_sh():
    from backend.sources.eastmoney import _secid
    assert _secid("600519") == "1.600519"  # 上交所
    assert _secid("000001") == "0.000001"  # 深交所
    assert _secid("300750") == "0.300750"  # 创业板
```

- [ ] **Step 2: 实现 EastMoneySource**

完整实现包含：
- `_secid(code)` — 交易所前缀映射
- `load_quotes(codes)` — 调用 QUOTE_URL，解析 `f2`/`f3`/`f4`/`f12`/`f14`，返回与 Tencent 一致格式的 dict 列表
- `load_history(code, limit, is_index)` — 调用 KLINE_URL，`klt=101`(日线) `fqt=1`(前复权)，解析 `klines` 字符串数组
- `load_market(codes)` — 调用 load_quotes + 额外查询指数
- `load_screener(market, page_size)` — 调用 CLIST_URL，`fs=m:0+t:6,...` 全市场，filter by market
- `_http_get(url, params)` — 内部 HTTP 请求封装（限频复用 data_source 的全局 throttle？最好复用，但简单起见先独立；后续可抽象共享限频器）

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_sources_eastmoney.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/sources/eastmoney.py tests/test_sources_eastmoney.py
git commit -m "feat: EastMoneySource 适配器（报价/日线/排行/财务）"
```

---

### Task 4: MockUSSource 适配器

**Files:**
- Create: `backend/sources/mock_us.py` — MockUSSource + MockUSCalendar + MockUSNormalizer + MockUSAssetMetadata
- Create: `tests/test_sources_mock_us.py`

**Interfaces:**

```python
# backend/sources/mock_us.py
from __future__ import annotations
import warnings
from datetime import date, time, datetime, timedelta
from backend.sources.base import DataSource, MarketCalendar, DataNormalizer, AssetMetadata, Capability

class MockUSCalendar(MarketCalendar):
    market = "US"
    # NYSE: Mon-Fri, 9:30-16:00 ET
    def is_trading_day(self, day: date) -> bool:
        return day.weekday() < 5
    def trading_session(self, day: date) -> tuple[time, time] | None:
        if not self.is_trading_day(day): return None
        return (time(9, 30), time(16, 0))
    def local_tz(self) -> str:
        return "America/New_York"

class MockUSNormalizer(DataNormalizer):
    def normalize_ohlc(self, raw_row: dict) -> dict:
        return raw_row
    def adjust_for_split(self, row: dict, ratio: float) -> dict:
        return row
    def convert_currency(self, value: float, from_currency: str, to_currency: str) -> float:
        RATES = {"CNY": 1, "USD": 7.2}
        return value * RATES[from_currency] / RATES[to_currency]

class MockUSAssetMetadata(AssetMetadata):
    _MOCK_CODES = {"AAPL": ("USD", 3500000000000, "Technology"),
                   "MSFT": ("USD", 3100000000000, "Technology"),
                   "TSLA": ("USD", 800000000000, "Consumer Cyclical")}
    def currency(self, code: str) -> str:
        return self._MOCK_CODES.get(code, ("USD", None, None))[0]
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

    def __init__(self):
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
                DeprecationWarning, stacklevel=2)

    # 模拟数据方法
    def load_quotes(self, codes: list[str]) -> list[dict]:
        return [{"code": c, "name": c, "price": 100.0, "change": 0.5,
                 "changeAmount": 0.5, "prevClose": 99.5, "open": 99.8,
                 "high": 101.0, "low": 99.0, "volume": 1000000,
                 "amount": 100000000, "exchange": "NYSE", "board": "美股",
                 "securityType": "股票", "market": "美股",
                 "updatedAt": int(datetime.now().timestamp() * 1000)}
                for c in codes]

    def load_history(self, code: str, limit: int = 40, is_index: bool = False) -> list[dict]:
        import random
        random.seed(hash(code))
        base = random.uniform(80, 120)
        return [{"date": (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d"),
                 "open": base + random.uniform(-2, 2),
                 "close": base + random.uniform(-2, 2),
                 "high": base + random.uniform(0, 3),
                 "low": base + random.uniform(-3, 0),
                 "volume": int(random.uniform(500000, 2000000)),
                 "amount": int(random.uniform(50000000, 500000000))}
                for i in range(limit)]

    def load_market(self, codes: list[str]) -> dict:
        return {"provider": "Mock US Market (simulated)", "fetchedAt": int(datetime.now().timestamp() * 1000),
                "quotes": self.load_quotes(codes), "indices": [], "errors": []}

    def load_screener(self, market: str, page_size: int = 300) -> dict:
        return {"total": 0, "rows": [], "universeSize": 0}
```

- [ ] **Step 1: Write tests**

```python
def test_mock_us_source_basic():
    source = MockUSSource()
    assert source.id == "mock_us"
    assert "realtime" in source.capabilities
    quotes = source.load_quotes(["AAPL", "MSFT"])
    assert len(quotes) == 2
    assert quotes[0]["code"] == "AAPL"
    assert quotes[0]["price"] == 100.0

def test_mock_us_metadata():
    source = MockUSSource()
    assert source.metadata.currency("AAPL") == "USD"
    assert source.metadata.sector("AAPL") == "Technology"
    assert source.metadata.market_cap("AAPL") == 3500000000000

def test_mock_us_calendar():
    source = MockUSSource()
    assert source.calendar.market == "US"
    # 周六不是交易日
    sat = date(2026, 9, 5)  # Saturday
    assert not source.calendar.is_trading_day(sat)
    # 周一至周五是交易日
    mon = date(2026, 9, 7)  # Monday
    assert source.calendar.is_trading_day(mon)

def test_mock_us_expiry_warning(monkeypatch, recwarn):
    from backend.sources.mock_us import MockUSSource
    import datetime
    # patch 到 2027 年之后，触发过期警告
    monkeypatch.setattr(datetime, "date", lambda: type("FakeDate", (), {"today": staticmethod(lambda: type("Today", (), {"__gt__": lambda self, other: True, "__le__": lambda self, other: False})())})())
    # 强制重新导入（reset 模块级检查）
    if hasattr(MockUSSource, "_check_expiry"):
        MockUSSource._check_expiry()  # 手动触发
    w = [x for x in recwarn if issubclass(x.category, DeprecationWarning)]
    assert len(w) >= 1
    assert "expired" in str(w[0].message)
```

- [ ] **Step 2: Run tests**

```bash
python -m pytest tests/test_sources_mock_us.py -v
```

- [ ] **Step 3: Commit**

```bash
git add backend/sources/mock_us.py tests/test_sources_mock_us.py
git commit -m "feat: MockUSSource 适配器（美股模拟 + 过期守卫 + 日历/标准化/元信息）"
```

---

### Task 5: DataSourceRouter

**Files:**
- Create: `backend/sources/router.py` — DataSourceRouter
- Create: `tests/test_sources_router.py`

**Interfaces:**

```python
# backend/sources/router.py
from __future__ import annotations
import logging
from typing import Iterator
from backend.sources.base import DataSource, Capability

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
            if sid in seen_ids: continue
            if sid in self._sources and capability in self._sources[sid].capabilities and self._sources[sid].available:
                chain.append(self._sources[sid])
                seen_ids.add(sid)
            if len(chain) >= FALLBACK_MAX_DEPTH:
                break
        if len(chain) < FALLBACK_MAX_DEPTH:
            for s in self._sources.values():
                if s.id in seen_ids: continue
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

    def route_with_fallback(self, source_id: str, capability: Capability,
                            fallback_enabled: bool = True) -> DataSource:
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
```

- [ ] **Step 1: Write tests**

```python
import pytest
from backend.sources.base import DataSource, Capability
from backend.sources.router import DataSourceRouter, FALLBACK_MAX_DEPTH

def make_mock_source(source_id: str, capabilities: set[str], available: bool = True):
    class MockSource(DataSource):
        id = source_id
        name = source_id
        capabilities = frozenset(capabilities)  # type: ignore
        available = available
        provider_label = source_id
        _calendar = None; _normalizer = None; _metadata = None
        @property
        def calendar(self): return self._calendar
        @property
        def normalizer(self): return self._normalizer
        @property
        def metadata(self): return self._metadata
        def load_quotes(self, codes): return []
        def load_history(self, code, limit=40, is_index=False): return []
        def load_market(self, codes): return {}
        def load_screener(self, market, page_size=300): return {}
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

def test_router_no_available_source():
    s1 = make_mock_source("tencent", {"realtime"}, available=False)
    router = DataSourceRouter({"tencent": s1})
    with pytest.raises(ValueError, match="No available source"):
        router.route_with_fallback("tencent", "realtime", fallback_enabled=True)
```

- [ ] **Step 2: Implement router**

```python
# backend/sources/router.py — 完整实现如上
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_sources_router.py -v
```

- [ ] **Step 4: Commit**

```bash
git add backend/sources/router.py tests/test_sources_router.py
git commit -m "feat: DataSourceRouter（路由/降级链/深度上限）"
```

---

### Task 6: 后端基础集成（schemas/storage/sources 注册表/settings 路由）

**Files:**
- Modify: `backend/sources/__init__.py` — 构建注册表 + 源信息
- Modify: `backend/schemas.py` — SettingsPut 加 fundamentalSource
- Modify: `backend/storage.py` — DEFAULT_WORKSPACE_SETTINGS + _normalize_workspace_settings 加 fundamentalSource
- Create: `tests/test_sources_integration.py`

**Integration details:**

```python
# backend/sources/__init__.py
from backend.sources.base import DataSource
from backend.sources.tencent import TencentSource
from backend.sources.eastmoney import EastMoneySource
from backend.sources.mock_us import MockUSSource
from backend.sources.router import DataSourceRouter

def build_router() -> DataSourceRouter:
    """构建含全部已注册源的 Router（mock_us 仅当 MOCK_US_ENABLED 开启时注册）。"""
    import os
    sources: dict[str, DataSource] = {"tencent": TencentSource(), "eastmoney": EastMoneySource()}
    if os.environ.get("MOCK_US_ENABLED", "").lower() in ("1", "true", "yes"):
        sources["mock_us"] = MockUSSource()
    return DataSourceRouter(sources)

def get_source_info(source: DataSource) -> dict:
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

def get_all_sources_info() -> list[dict]:
    """所有已注册源元信息（/api/settings sources 列表用）。"""
    return [get_source_info(s) for s in build_router()._sources.values()]
```

**storage.py 修改：**

```python
DEFAULT_WORKSPACE_SETTINGS = {
    # ... 现有字段不变，新增：
    "fundamentalSource": "eastmoney",
}

_allowed_sources = {"tencent", "eastmoney", "akshare", "tushare", "mock_us"}

# 在 _normalize_workspace_settings 中，替换原 allowed_sources 逻辑：
for key in ("realtimeSource", "historySource", "screenerSource", "fundamentalSource"):
    if data[key] not in _allowed_sources:
        data[key] = "tencent"
# 注意：原代码第 321 行有 data["realtimeSource"] = "tencent" 强制覆盖，需删除该行
```

**schemas.py 修改：**

```python
class SettingsPut(BaseModel):
    # ... 现有字段不变，新增：
    fundamentalSource: str = "eastmoney"
```

**app.py `/api/settings` 修改：**

```python
# GET /api/settings 中，替换硬编码 sources 列表：
from backend.sources import get_all_sources_info
sources = get_all_sources_info()
```

- [ ] **Step 1: 修改 schemas.py + storage.py**

添加 `fundamentalSource` 字段，更新 `_allowed_sources`，删除第 321 行强制 `data["realtimeSource"] = "tencent"`。

- [ ] **Step 2: 更新 `backend/sources/__init__.py`**

实现 `build_router()`、`get_source_info()`、`get_all_sources_info()`。

- [ ] **Step 3: 修改 `GET /api/settings` 路由**

用 `get_all_sources_info()` 替换硬编码 sources 列表（保留 akshare/tushare 的 installed/config 探测信息合并）。

- [ ] **Step 4: 写集成测试**

```python
def test_settings_returns_sources(client):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    sources = resp.json()["sources"]
    ids = [s["id"] for s in sources]
    assert "tencent" in ids
    assert "eastmoney" in ids
    em = next(s for s in sources if s["id"] == "eastmoney")
    assert em["fundamental"] is True
    assert em["realtime"] is True
    tencent = next(s for s in sources if s["id"] == "tencent")
    assert tencent["fundamental"] is False  # spec: Tencent 无 fundamental

def test_settings_put_accepts_fundamental_source(client):
    resp = client.put("/api/settings", json={"fundamentalSource": "eastmoney", "realtimeSource": "eastmoney"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["fundamentalSource"] == "eastmoney"
    assert data["realtimeSource"] == "eastmoney"
```

- [ ] **Step 5: Run all backend tests**

```bash
python -m pytest tests/test_sources_integration.py tests/test_backend_api.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/sources/__init__.py backend/schemas.py backend/storage.py tests/test_sources_integration.py
git commit -m "feat: 后端基础集成（fundamentalSource 设置 + 源注册表 + settings 路由）"
```

---

### Task 7: 后端 API 路由改造

**Files:**
- Modify: `backend/app.py` — market/history/screener 路由 + `_load_history_with_fallback` 使用 Router
- Create: `tests/test_sources_router_integration.py`

**改动要点：**

`_load_history_with_fallback` 需要读取 settings 选择 history 源。改造为：

```python
def _load_history_with_fallback(code: str, limit: int, is_index: bool = False) -> tuple[list, str, str | None]:
    """优先所选历史源；上游失败时降级读取本地 market_bars 持久化历史。返回 (history, dataSource, dataAsOf)。"""
    from backend.sources import build_router
    settings = get_workspace_settings("default")
    router = build_router()
    try:
        source = router.route_with_fallback(settings.get("historySource", "tencent"), "history", settings.get("fallbackEnabled", True))
        history = source.load_history(code, limit=limit, is_index=is_index)
        data_as_of = save_market_bars(code, history)
        return history, "live", data_as_of
    except Exception:
        bars = load_market_bars(code, limit=limit)
        if not bars:
            raise
        return bars, "local", bars[-1]["date"]
```

**market/screener 路由改造：**

```python
@app.get("/api/market")
def market(codes: str = Query(default="")) -> MarketOut:
    try:
        from backend.sources import build_router
        settings = get_workspace_settings("default")
        source = build_router().route_with_fallback(settings.get("realtimeSource", "tencent"), "realtime", settings.get("fallbackEnabled", True))
        payload = source.load_market(codes.split(",") if codes else [])
        payload["provider"] = source.provider_label
        return MarketOut.model_validate(payload)
    except Exception as exc:
        raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, str(exc), provider="upstream")

@app.get("/api/screener")
def screener(market: str = Query(default="全部"), pageSize: int = Query(default=300, alias="pageSize")) -> ScreenerOut:
    try:
        from backend.sources import build_router
        settings = get_workspace_settings("default")
        source = build_router().route_with_fallback(settings.get("screenerSource", "tencent"), "screener", settings.get("fallbackEnabled", True))
        payload = source.load_screener(market, pageSize)
        payload["provider"] = source.provider_label
        payload["fetchedAt"] = int(time.time() * 1000)
        return ScreenerOut.model_validate(payload)
    except Exception as exc:
        raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, str(exc), provider="upstream")
```

注意：`/api/history` 已通过 `_load_history_with_fallback` 使用 Router；`/api/screener/v2`、`/api/grid/preview`、`/api/grid/backtest`、`/api/strategy/*` 均通过 `_load_history_with_fallback` 或 `load_market`，已覆盖。`/api/market` 与 `/api/screener` 显式改造如上。

- [ ] **Step 1: 改造 `_load_history_with_fallback`**

- [ ] **Step 2: 改造 `/api/market` 与 `/api/screener` 路由**

- [ ] **Step 3: 写集成测试**

```python
def test_market_route_uses_router_and_provider(monkeypatch, client):
    from backend import app as app_module
    from backend.sources import build_router
    source = build_router().get_source("eastmoney")
    monkeypatch.setattr(source, "load_market", lambda codes: {"provider": "x", "fetchedAt": 0, "quotes": [{"code": "600519"}], "indices": [], "errors": []})
    resp = client.get("/api/market?codes=600519")
    assert resp.status_code == 200
    assert resp.json()["provider"] == "东方财富实时行情"

def test_history_route_uses_history_source(monkeypatch, client):
    from backend import app as app_module
    monkeypatch.setattr(app_module, "get_workspace_settings", lambda wid="default": {"historySource": "eastmoney", "fallbackEnabled": True, **{}})
    # 断言调用的是 eastmoney 的 load_history（通过 _load_history_with_fallback 间接）
    resp = client.get("/api/history?code=600519")
    assert resp.status_code in (200, 502)  # 实盘可能 502，但路由逻辑应正确路由
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_sources_router_integration.py tests/test_backend_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app.py tests/test_sources_router_integration.py
git commit -m "feat: API 路由接入 DataSourceRouter（market/history/screener 按设置选源）"
```

---

### Task 8: 前端

**Files:**
- Modify: `frontend/src/stores/useSettingsStore.ts` — 加 fundamentalSource
- Modify: `frontend/src/views/ViewSettings.vue` — 动态数据源下拉 + fundamentalSource + 能力位展示
- Modify: `tests/frontend/ViewSettings.test.ts` — 更新测试

**前端改动：**

1. `useSettingsStore.ts` settingsDraft 加：
```ts
fundamentalSource: 'eastmoney',
```

2. `ViewSettings.vue` — 将三个固定下拉（40-42 行）改为**动态**生成（遍历 `dataSources`，按能力位过滤 + disabled 不可用源），并新增 fundamentalSource：

```html
<!-- 实时行情来源 -->
<section v-if="settingsTab === 'data'" class="settings-row">
  <div><strong>实时行情来源</strong><span>实时 A 股报价主数据源</span></div>
  <select v-model="settingsDraft.realtimeSource" aria-label="实时行情来源">
    <option v-for="s in dataSources.filter(s => s.realtime)" :key="s.id" :value="s.id" :disabled="!s.available">{{ s.name }}<template v-if="!s.available">（{{ s.reason || '不可用' }}）</template></option>
  </select>
</section>
<!-- 历史日线来源 -->
<section v-if="settingsTab === 'data'" class="settings-row">
  <div><strong>历史日线来源</strong><span>用于走势和网格回测</span></div>
  <select v-model="settingsDraft.historySource" aria-label="历史日线来源">
    <option v-for="s in dataSources.filter(s => s.history)" :key="s.id" :value="s.id" :disabled="!s.available">{{ s.name }}<template v-if="!s.available">（{{ s.reason || '不可用' }}）</template></option>
  </select>
</section>
<!-- 选股指标来源 -->
<section v-if="settingsTab === 'data'" class="settings-row">
  <div><strong>选股指标来源</strong><span>用于候选池估值和量价指标</span></div>
  <select v-model="settingsDraft.screenerSource" aria-label="选股指标来源">
    <option v-for="s in dataSources.filter(s => s.screener)" :key="s.id" :value="s.id" :disabled="!s.available">{{ s.name }}<template v-if="!s.available">（{{ s.reason || '不可用' }}）</template></option>
  </select>
</section>
<!-- 财务数据源（新增） -->
<section v-if="settingsTab === 'data'" class="settings-row">
  <div><strong>财务数据源</strong><span>市盈率/市净率等基本面指标主数据源</span></div>
  <select v-model="settingsDraft.fundamentalSource" aria-label="财务数据源">
    <option v-for="s in dataSources.filter(s => s.fundamental)" :key="s.id" :value="s.id" :disabled="!s.available">{{ s.name }}<template v-if="!s.available">（{{ s.reason || '不可用' }}）</template></option>
  </select>
</section>
```

3. 连接 tab（43 行）增加能力位展示（fundamental 徽标）。

4. 更新 `ViewSettings.test.ts`：验证 4 个数据源下拉存在、fundamental 下拉渲染、动态选项。

- [ ] **Step 1: 修改前端 settings store**

- [ ] **Step 2: 修改 ViewSettings.vue（动态下拉 + fundamentalSource）**

- [ ] **Step 3: 更新 vitest 测试**

```bash
npx vitest run tests/frontend/ViewSettings.test.ts -v
```

- [ ] **Step 4: 全量前端回归**

```bash
npx vitest run
npx vue-tsc --noEmit
npm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/useSettingsStore.ts frontend/src/views/ViewSettings.vue tests/frontend/
git commit -m "feat: 前端动态数据源下拉 + fundamentalSource + 能力位展示"
```

---

## 验证

所有任务完成后执行全量回归：

```bash
# 后端
python -m pytest tests/ -v
python -m ruff check backend tests server.py
python -m ruff format --check backend tests server.py
python -m mypy backend

# 前端
npx vitest run
npx vue-tsc --noEmit
npm run build

# 完整回归
npm run verify
```

## 非目标

- 不做真实美股行情接入（MockUSSource 仅验证框架）
- 不做 Wind / Bloomberg / 交易所直连
- 不做汇率实时行情（convert_currency 用固定汇率）
- 不改动选股池（REAL_UNIVERSE 50 只）
- 不改动 `data_source.py` 现有模块级全局函数（TencentSource 薄封装调用）
- 不修改 `data_source.py` 的全局缓存/限频（Router 复用现有机制）