# 统一数据源接入层设计

日期：2026-09-02
分支：`feature/multi-data-source`

## 背景与目标

当前 `backend/data_source.py` 全部为腾讯公开行情专用实现（报价/日线/选股器/限频/缓存）。ROADMAP「多数据源接入」要求支持多个行情数据源。

用户给出了分阶段演进路线：起步阶段用免费源（东方财富、AkShare、Yahoo Finance 等）快速验证；策略研发阶段接入 Tushare Pro（A 股）或 Polygon.io（美股）等专业 API；机构级考虑 Wind / Bloomberg / 交易所直连。

本设计的目标是**架构按全球多市场设计、数据只做实盘 A 股 + 模拟美股全链路验证**，使未来接真实美股源时只新增适配器、不改调度引擎。

## 架构总览

```
┌─────────────────────────────────────────────────────┐
│                    DataSourceRouter                  │
│  按能力路由: realtimeSource / historySource /        │
│  screenerSource / fundamentalSource + fallback 链    │
├─────────────────────────────────────────────────────┤
│  DataSource (ABC)          MarketCalendar (ABC)      │
│  ├─ load_quotes()          ├─ is_trading_day()       │
│  ├─ load_history()         ├─ next_trading_day()     │
│  ├─ load_market()          ├─ previous_trading_day() │
│  ├─ load_screener()        └─ local_tz()             │
│  └─ capabilities /         DataNormalizer (ABC)      │
│     available /             ├─ adjust_for_split()    │
│     provider_label          ├─ convert_currency()    │
│                              └─ normalize_ohlc()     │
│                            AssetMetadata (ABC)       │
│                             ├─ currency(code)->str   │
│                             ├─ market_cap()          │
│                             └─ sector()              │
├─────────────────────────────────────────────────────┤
│  Adapters: TencentSource | EastMoneySource |         │
│  MockUSSource            [Future: Polygon/Yahoo]     │
└─────────────────────────────────────────────────────┘
```

## 核心接口

### DataSource（数据源适配器基类）

```python
class DataSource(ABC):
    id: str                # "tencent" / "eastmoney" / "mock_us"
    name: str              # 显示名
    capabilities: frozenset[str]
        # 取值: "realtime" | "history" | "screener" | "fundamental"
    available: bool        # 依赖/配置是否满足（如 token、库安装）
    provider_label: str    # 前端展示的 provider 文案

    @abstractmethod
    def load_quotes(self, codes: list[str]) -> list[dict]: ...
    @abstractmethod
    def load_history(self, code: str, limit: int, is_index: bool) -> list[dict]: ...
    @abstractmethod
    def load_market(self, codes: list[str]) -> dict: ...
    @abstractmethod
    def load_screener(self, market: str, page_size: int) -> dict: ...
```

说明：
- `fundamental` 能力表示可拉取财务/估值指标（PE/PB/ROE 等），与 K 线（`history`）降级路径独立。
- 每个适配器自带其请求方式、限频、解析逻辑；通用缓存/节流/降级逻辑由 Router 或基类提供。
- 当前 `data_source.py` 的模块级全局缓存/限频保持，但需要改造为适配器实例级或共享基础设施。

### MarketCalendar（交易日历抽象）

```python
class MarketCalendar(ABC):
    market: str            # "CN" / "US"
    @abstractmethod
    def is_trading_day(self, day) -> bool: ...
    @abstractmethod
    def next_trading_day(self, day): ...
    @abstractmethod
    def previous_trading_day(self, day): ...
    @abstractmethod
    def trading_session(self, day) -> tuple[time, time] | None: ...
    @abstractmethod
    def local_tz(self): ...
```

解决时区与交易日差异。A 股实现基于交易所日历（简单法：周一至周五 + 固定假日表）；美股实现为模拟。

### DataNormalizer（数据标准化抽象）

```python
class DataNormalizer(ABC):
    @abstractmethod
    def normalize_ohlc(self, raw_row: dict) -> dict: ...
    @abstractmethod
    def adjust_for_split(self, row: dict, ratio: float) -> dict: ...
    @abstractmethod
    def convert_currency(self, value: float, from_currency: str, to_currency: str) -> float: ...
```

解决复权/拆股/单位差异。A 股实盘：上游已前复权（腾讯/东财原生 qfq），normalize 做字段归一；美股模拟：无复权模拟。

### AssetMetadata（资产元信息服务）

```python
class AssetMetadata(ABC):
    @abstractmethod
    def currency(self, code: str) -> str: ...   # 显式返回 "CNY" / "USD"
    @abstractmethod
    def market_cap(self, code: str) -> float | None: ...
    @abstractmethod
    def sector(self, code: str) -> str | None: ...
```

- `currency()` **必须显式实现**：跨市场回测时汇率换算发生在因子计算之前，接口层强制暴露，避免后续遗漏。
- A 股实现：复用 `classify_code` + 行情字段；美股模拟：硬编码表。

## 调度与降级

- **按能力路由**：设置中的 `realtimeSource` / `historySource` / `screenerSource` / `fundamentalSource`（新增）各自选定源；同一能力缺省 `tencent`。
- **降级链**：首选源失败 → 若 `fallbackEnabled=true` → 遍历其余 `capabilities` 含该能力的源 → 均失败则报错。
- 降级发生时更新 provider 标记（前端已按 `provider` 展示数据来源）。
- 保留现有 `apply_runtime_config`（超时/重试/缓存/限频）与 `cached`/`mark_stale` 降级缓存机制。

## 适配器矩阵（本次交付）

| 适配器 | 市场 | 类型 | capabilities | 依赖 | 备注 |
|--------|------|------|--------------|------|------|
| TencentSource | A 股 | 实盘 | realtime/history/screener/fundamental | 无 | 现有代码重构进新接口 |
| EastMoneySource | A 股 | 实盘 | realtime/history/screener/fundamental | 无 | 免费公开接口，无 token |
| MockUSSource | 美股 | 模拟 | realtime/history/screener | 无 | 随机/固定数据，全链路验证 |

## 前端改动

- `/api/settings` 的 `sources` 列表已存在（tencent/akshare/tushare）；更新为动态来自适配器注册表，并增加 `fundamental` 能力位与 `currency` 相关展示。
- 设置页已有 `realtimeSource` / `historySource` / `screenerSource` 下拉，增加 `fundamentalSource`。
- 数据源选择下拉禁用不可用源（`available=false` 显示 reason）。
- 行情数据展示时按 `provider` 显示来源；美股模拟数据以明显「模拟」标记（绝不用模拟值冒充真实行情——遵守 AGENTS.md「绝不使用模拟值填充缺失数据」：MockUSSource 仅用于美股模拟市场，A 股实盘绝不走模拟）。

## 错误处理与安全

- 上游失败 → 降级链 → 兜底报错（502），与现有 `api_error(502, ERR_UPSTREAM_UNAVAILABLE)` 一致。
- 时区/交易日按 `MarketCalendar` 本地化。
- 不在本次范围：真实美股数据源（下个迭代只新增适配器）、Wind/Bloomberg/交易所直连、全 A 股扩池。

## 测试

- 单元：每个适配器解析函数（腾讯/东财/模拟美股）mock 上游响应。
- 接口契约：DataSource ABC 的每个实现满足 capabilities 声明的能力。
- Router：降级链、按能力路由、fallback 关闭时直抛。
- 交易日历：A 股周末/假日、美股模拟。
- 前端：设置页数据源下拉、sources 列表渲染。
- 回归：现有 pytest 全绿 + vitest 全绿 + coverage ≥80%。

## 非目标

- 不做真实美股行情接入。
- 不做 Wind / Bloomberg / 交易所直连。
- 不做汇率实时行情（currency 换算接口先实现占位/简单常数）。
- 不改动选股池（REAL_UNIVERSE 50 只）。
