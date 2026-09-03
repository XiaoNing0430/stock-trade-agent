"""Pydantic 请求/响应模型（Task 4.1 / 4.2）。

字段名与 backend/app.py 各路由读取/返回的 key 逐字节一致：
- 请求模型替换 `payload: dict = Body(...)`，extra="ignore" 容忍前端多发字段；
- 响应模型作为路由返回注解，字段名与各路由现返回 dict 顶层 key 一致。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkspacePut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    watchlist: list[str] = Field(default_factory=list)
    plans: list[dict[str, Any]] = Field(default_factory=list)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    monitorEnabled: bool = True
    presetName: str = ""
    revision: int = 0


class SettingsPut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    workspaceName: str = "个人工作区"
    defaultCapital: float = 100000
    monitorEnabled: bool = True
    realtimeSource: str = "tencent"
    historySource: str = "tencent"
    screenerSource: str = "tencent"
    fundamentalSource: str = "eastmoney"
    fallbackEnabled: bool = True
    refreshInterval: int = 15
    cacheSeconds: int = 8
    timeoutSeconds: int = 10
    retryCount: int = 1
    conflictPolicy: str = "server"
    notifyDesktopAlert: bool = True
    notifyDesktopSystem: bool = False


class GridPreviewIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    lookback: int = 120
    gridCount: int = 8
    capital: float = 100000
    mode: str = "classic"


class GridBacktestIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    lower: float
    upper: float
    gridCount: int
    capital: float
    feeBps: float = 3
    mode: str = "classic"
    lookback: int = 120
    settlementDays: int = 1
    slippageBps: float = 5
    name: str | None = None
    schedule: str = "manual"
    save: bool = False
    id: str | None = None


class GridOptimizeIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    lookback: int = 120
    capital: float = 100000
    feeBps: float = 3
    mode: str = "classic"
    settlementDays: int = 1
    slippageBps: float = 5


class GridStatusPut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    schedule: str | None = None


class StrategyPreviewIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategyType: str
    config: dict[str, Any] = Field(default_factory=dict)


class StrategyBacktestIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategyType: str
    code: str
    lookback: int = 120
    config: dict[str, Any] = Field(default_factory=dict)
    capital: float = 100000
    feeBps: float = 3
    capitalAllocation: float = Field(default=1.0, ge=0.1, le=1.0)
    name: str | None = None
    schedule: str = "manual"
    save: bool = False
    id: str | None = None


class StrategyStatusPut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    schedule: str | None = None


# ===== 响应模型（字段名与各路由现返回 dict 顶层 key 逐字节一致） =====


class HealthOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool
    provider: str
    serverTime: int
    mode: str
    universeSize: int
    storage: dict[str, bool]


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    watchlist: list[str] = Field(default_factory=list)
    plans: list[dict[str, Any]] = Field(default_factory=list)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    revision: int = 0


# save_workspace 返回与 get_workspace 相同结构
WorkspacePutOut = WorkspaceOut


class SettingsOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)


class SettingsPutOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: dict[str, Any] = Field(default_factory=dict)


class MarketOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    quotes: list[dict[str, Any]] = Field(default_factory=list)
    indices: list[dict[str, Any]] = Field(default_factory=list)
    fetchedAt: int = 0
    provider: str = ""
    errors: list[dict[str, Any]] = Field(default_factory=list)


class HistoryOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    provider: str
    fetchedAt: int
    history: list[dict[str, Any]] = Field(default_factory=list)
    dataSource: str
    dataAsOf: str | None = None


class ScreenerOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rows: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    universeSize: int = 0
    provider: str = ""
    fetchedAt: int = 0


class GridPreviewOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    profile: dict[str, Any] = Field(default_factory=dict)
    dataAsOf: str | None = None
    dataSource: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    suggestion: dict[str, Any] = Field(default_factory=dict)


class GridBacktestOut(BaseModel):
    # extra="allow" 保留 **result 展开的 metrics/equityCurve/assumptions/trades 等字段
    model_config = ConfigDict(extra="allow")

    code: str
    profile: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    # strategy（可选）经 extra="allow" 透传，仅 save=True 时出现


class GridOptimizeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    profile: dict[str, Any] = Field(default_factory=dict)
    dataAsOf: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class GridStrategiesOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategies: list[dict[str, Any]] = Field(default_factory=list)


class DeleteOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deleted: bool
    id: str


class StrategyPreviewOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategyType: str
    suggestion: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class StrategyBacktestOut(BaseModel):
    # extra="allow" 保留 **result 展开的 metrics/equityCurve/assumptions/trades 等字段
    model_config = ConfigDict(extra="allow")

    code: str
    profile: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, Any]] = Field(default_factory=list)
    strategyType: str
    config: dict[str, Any] = Field(default_factory=dict)
    dataSource: str
    dataAsOf: str | None = None
    # strategy（可选）经 extra="allow" 透传，仅 save=True 时出现


class StrategiesOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    strategies: list[dict[str, Any]] = Field(default_factory=list)


class ScreenerStrategyRunIn(BaseModel):
    """POST /api/screener/strategy 请求体。"""

    strategy: str
    mode: str = "quick"  # quick（纯粗筛）/ deep（API 粗筛 + 本地因子精筛）
    refresh: bool = False  # 强制重算（绕过缓存）
    referenceDate: str | None = None  # YYYY-MM-DD；默认上一交易日


class ScreenerStrategyOut(BaseModel):
    """POST /api/screener/strategy 响应；rows 内含 score/factors/roe 等透传字段。"""

    model_config = ConfigDict(extra="allow")

    strategy: str
    name: str
    mode: str
    referenceDate: str
    provider: str
    rows: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    cached: bool = False
    stale: bool = False
    elapsedMs: int = 0
