# 策略引擎重构：指标库 + 策略基类 + 多因子模型

> **设计文档** — 对应 ROADMAP「新策略类型」功能开发

## 1. 背景与目标

### 1.1 现状

当前策略引擎（`backend/strategy_engines.py`）包含 4 个平级独立策略函数（`ma_cross`、`dca`、`macd` + 网格 `grid`），共享 `_ma`/`_ema` 辅助函数和 `_compute_metrics` 指标计算。策略间无复用，无基类，无指标库。

### 1.2 目标

1. 建立三层架构：**指标库 → 策略基类 → 组合策略（多因子模型）**
2. 所有现有策略透明迁移到基类体系，API 输出结构不变
3. 新增 4 个策略类型：布林带反转、唐奇安突破、动量、多因子
4. 多因子模型作为核心组合策略：ADX 市场状态过滤器 + 动态模块切换

### 1.3 非目标

- 全账户组合视角（多策略同时运行时的资金动态协调）— 后续方向
- 多品种横截面动量 — 后续方向
- 网格策略迁移到基类（网格是区间逻辑，不同范式，保持独立）

## 2. 三层架构

### 2.1 第 1 层：指标库 `backend/indicators.py`

纯函数，输入日线序列/K 线序列，输出对齐序列（预热区返回 `None`）。

| 指标 | 函数签名 | 说明 |
|------|----------|------|
| 简单均线 | `ma(values, period) → list[float\|None]` | 从 strategy_engines 提取 |
| 指数均线 | `ema(values, period) → list[float]` | 从 strategy_engines 提取 |
| 滚动标准差 | `rolling_std(values, period) → list[float\|None]` | 预热期返回 None |
| 布林带 | `bollinger(values, period, num_std) → tuple[list, list, list]` | 返回 `(mid, upper, lower)` |
| ATR | `atr(bars, period) → list[float\|None]` | 真实波幅，输入 bar 需含 high/low/close |
| ADX | `adx(bars, period) → list[float\|None]` | 趋势强度 0–100 |
| 唐奇安通道 | `donchian(bars, period) → tuple[list, list]` | 返回 `(upper, lower)` |
| 动量 | `momentum(values, period) → list[float\|None]` | N 日涨跌幅 % |
| 偏离度 | `deviation(values, period) → list[float\|None]` | (close/MA−1)×100 |
| RSI | `rsi(values, period) → list[float\|None]` | 可选，供后续使用 |

### 2.2 第 2 层：策略基类 `backend/strategy_base.py`

```python
class BaseStrategy(ABC):
    id: str                           # 策略标识，如 "bollinger"
    label: str                        # 中文显示名，如 "布林带反转"
    config_schema: list[dict]         # 前端配置表单 schema

    @abstractmethod
    def generate_signals(self, bars: list[dict], config: dict) -> list[Signal]:
        """子类只实现信号生成，返回 Signal 列表。"""
        ...

    def backtest(self, bars: list[dict], config: dict) -> dict:
        """基类统一执行：资金、整手、手续费、T+1、权益曲线、指标、基准。
        返回结构与现有 backtest_* 函数完全一致。"""
        ...
```

**基类统一处理**：
- 资金管理（`capital × allocationRatio`）
- 100 股整手（`floor(cash / close / 100) * 100`）
- 手续费（`transaction_fee`，双向佣金最低 5 元 + 卖出印花税 0.05% + 过户费）
- T+1 交收（卖出时前一日买入的仓位才可卖）
- 权益曲线（`equity_curve`，归一化）
- 买入持有基准（`buy_and_hold_benchmark`）
- 指标计算（`_compute_metrics`：收益/回撤/夏普/胜率/换手/费用等）
- 假设披露生成（中文，含「结果仅用于研究，不代表未来收益」）

**Signal 定义**：
```python
@dataclass
class Signal:
    date: str
    side: Literal["buy", "sell"]
    price: float
    reason: str = ""  # 如 "price < lower_band, 均值回归买入"
    confidence: float | None = None  # 可选，供后续使用
```

### 2.3 第 3 层：多因子模型 `backend/multi_factor.py`

#### 2.3.1 架构

```
每根 K 线 i:
  1. 计算 ADX[i]
  2. ADX >= 阈值(25) → 趋势市 → 激活「唐奇安突破」模块
  3. ADX < 阈值(25)  → 震荡市 → 激活「布林带反转」模块
  4. 僵局保护检查 → 若暂停，持有现金
  5. 生成信号 → 基类统一执行
```

#### 2.3.2 模块定义

| 模块 | 策略 | 开仓条件 | 平仓条件 |
|------|------|----------|----------|
| 震荡市 | 布林带反转 | `price < lower_band`（超卖） | `price > upper_band`（超买） |
| 趋势市 | 唐奇安突破 | `price > upper_channel AND ADX > 25` | `price < lower_channel`（反向突破，不依赖 ADX） |

#### 2.3.3 僵局保护

```
模块跟踪 consecutiveLosses（连续亏损交易数）
若 consecutiveLosses >= 10（可配置）：
  → 暂停该模块
  → 资金转为现金，不移交给另一模块
  → 下一笔盈利交易后复位计数器
  → 回测输出同时记录 theoreticalIfUnfrozen 盈亏
```

#### 2.3.4 输出

除了标准 `trades/equityCurve/benchmarkCurve/metrics/assumptions`，多因子回测额外输出：

```python
{
    "moduleUsage": {
        "range": {"trades": 12, "grossPnl": 3500, "frozenPeriods": [...]},
        "trend": {"trades": 8, "grossPnl": 8200, "frozenPeriods": [...]},
    },
    "theoreticalIfUnfrozen": [...],  # 暂停期间模块的理论收益
}
```

## 3. 策略清单

### 3.1 独立策略（可单独使用）

| 策略类型 | 基类 | 文件 | 说明 |
|----------|------|------|------|
| 双均线 | 迁移 | `ma_cross.py` | 从现有函数迁移，输出不变 |
| 定投DCA | 迁移 | `dca.py` | 从现有函数迁移，输出不变 |
| MACD | 迁移 | `macd.py` | 从现有函数迁移，输出不变 |
| 布林带反转 | 新增 | `bollinger.py` | 可独立使用，也是多因子震荡模块 |
| 唐奇安突破 | 新增 | `donchian.py` | 可独立使用，也是多因子趋势模块 |
| 动量 | 新增 | `momentum.py` | 独立策略，不纳入多因子，需资金隔离 |

### 3.2 组合策略

| 策略类型 | 文件 | 说明 |
|----------|------|------|
| 多因子 | `multi_factor.py` | ADX 状态过滤器 + 布林带/唐奇安切换 + 僵局保护 |

### 3.3 网格策略

保持独立（`backend/grid_strategy.py` + `backend/grid_scheduler.py`），不迁移。

## 4. 资金隔离（坑 1）

- 策略配置增加 `capitalAllocation: float` 字段（默认 1.0，范围 0.1–1.0）
- 回测时：`effective_capital = total_capital × capitalAllocation`
- **按比例切分**：每个策略实例使用自己的资金池，头寸独立计算
- 多因子内部：震荡/趋势模块共享 100% 的多因子资金（不会同时开仓）
- 动量独立策略：用户配置占用比例（如 0.6），剩余为现金缓冲
- 全账户组合视角（资金动态再分配）留待后续

## 5. 僵局保护（坑 2）

- 阈值：`maxConsecutiveLosses: int = 10`（可配置）
- 暂停期：资金保持现金，不转移给其他模块
- 恢复：下一笔盈利交易后复位
- 记录：`frozenPeriods` 含 `{startIndex, endIndex, theoreticalReturnPct}`

## 6. ADX 延迟处理（坑 3）

- 采用方案 B（被动接受）：多品种分散平滑，接受 ADX 滞后
- 入口/出口分离：唐奇安突破用 ADX>25 确认**开仓**，但**平仓**用唐奇安通道反向突破，不依赖 ADX
- 文档中明确披露 ADX 滞后假设作为已知局限
- 回测结果不因此过度优化参数

## 7. 注册表改造 `backend/strategy_engines.py`

保持 `STRATEGY_ENGINES` 字典结构不变（`label/backtest/suggest/configSchema`），API 契约零破坏。

```python
STRATEGY_ENGINES = {
    "grid": {"label": "网格", "backtest": backtest_grid, ...},  # 不变
    "ma_cross": {"label": "双均线", "backtest": ..., "configSchema": [...]},  # 重新实现
    "dca": ...,   # 重新实现
    "macd": ...,  # 重新实现
    "bollinger": {"label": "布林带反转", "backtest": ..., "configSchema": [...]},
    "donchian": {"label": "唐奇安突破", "backtest": ..., "configSchema": [...]},
    "momentum": {"label": "动量", "backtest": ..., "configSchema": [...]},
    "multi_factor": {"label": "多因子", "backtest": ..., "configSchema": [...]},
}
```

## 8. 前端变更

### `frontend/src/modules/constants.ts`

`STRATEGY_TYPES` 追加：
```typescript
{ id: 'bollinger', label: '布林带反转', description: '超卖买入，超买卖出，均值回归' },
{ id: 'donchian', label: '唐奇安突破', description: '通道突破入场，反向突破离场（含ADX确认）' },
{ id: 'momentum', label: '动量', description: 'N日涨跌幅阈值进出，独立资金管理' },
{ id: 'multi_factor', label: '多因子', description: 'ADX状态过滤器 + 动态模块切换' },
```

`STRATEGY_SCHEMAS` 追加各配置 schema，多因子展示两级配置：
```
[ADX 过滤器]  周期 14  阈值 25
[震荡市] 布林带反转  MA周期 20  · 标准差 2.0
[趋势市] 唐奇安突破  通道周期 20  · ATR止损 2.0
[僵局保护] 最大连续亏损 10
```

### `ViewGrid.vue`

- 数据驱动，只需补新类型图标映射
- 多因子 tab 显示两级配置面板（ADX 参数 + 子模块参数 + 僵局保护）

## 9. 测试

### 9.1 后端测试

| 文件 | 内容 |
|------|------|
| `tests/test_indicators.py`（新增） | 每个指标 2–3 个用例：合成数据验证数值正确性、边界（预热区/零值） |
| `tests/test_strategy_base.py`（新增） | 信号→回测闭环、整手/费用/T+1 逻辑、空输入/边界 |
| `tests/test_multi_factor.py`（新增） | ADX 切换逻辑、僵局保护触发/恢复、模块统计输出 |
| `tests/test_strategy_engines.py`（更新） | 现有策略迁移后 shape 不变 + 新策略 shape + capitalAllocation |

### 9.2 验证命令

```bash
python -m pytest tests/ -q
npx vitest run
npm run build
```

## 10. 已知局限

- **ADX 滞后**：ADX 作为滞后指标，市场状态切换有延迟。已通过「入口 ADX 确认，出口唐奇安反向突破」缓解，但无法完全消除。
- **单品种时序**：当前多因子为单品种策略，不包含多品种分散或横截面动量。
- **全账户组合**：资金隔离为策略级分配，不包含跨策略动态再平衡或风险预算。
- **网格策略**：保持独立，不纳入基类体系。

## 11. 文件清单

### 新建

| 文件 | 约行数 | 说明 |
|------|--------|------|
| `backend/indicators.py` | ~200 | 指标库 |
| `backend/strategy_base.py` | ~250 | 基类 + 信号/回测/指标 |
| `backend/strategies/__init__.py` | 空 | 包初始化 |
| `backend/strategies/ma_cross.py` | ~80 | 迁移双均线 |
| `backend/strategies/dca.py` | ~80 | 迁移定投 |
| `backend/strategies/macd.py` | ~80 | 迁移 MACD |
| `backend/strategies/bollinger.py` | ~60 | 布林带反转 |
| `backend/strategies/donchian.py` | ~60 | 唐奇安突破 |
| `backend/strategies/momentum.py` | ~60 | 动量 |
| `backend/multi_factor.py` | ~150 | 多因子模型 |
| `tests/test_indicators.py` | ~150 | 指标测试 |
| `tests/test_strategy_base.py` | ~100 | 基类测试 |
| `tests/test_multi_factor.py` | ~100 | 多因子测试 |

### 修改

| 文件 | 说明 |
|------|------|
| `backend/strategy_engines.py` | 注册表指向新实现，保留网格 |
| `backend/schemas.py` | `StrategyBacktestIn` 增加 `capitalAllocation` |
| `frontend/src/modules/constants.ts` | `STRATEGY_TYPES` + `STRATEGY_SCHEMAS` 追加 |
| `tests/test_strategy_engines.py` | 更新 shape 断言 + 新增策略测试 |

## 12. 实施顺序

1. 指标库 `indicators.py`（TDD）
2. 策略基类 `strategy_base.py` + 迁移 3 个现有策略（TDD，全量回归）
3. 新增策略：布林带反转、唐奇安突破、动量（TDD）
4. 多因子模型 `multi_factor.py` + 僵局保护（TDD）
5. 注册表改造 + schema 更新
6. 前端 constants.ts 更新
7. 全量回归 + 浏览器手动验证