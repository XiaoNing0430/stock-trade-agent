"""Pydantic 请求模型（Task 4.1）。

字段名与 backend/app.py 中路由读取的 key 逐字节一致，
用于 Task 4.2 替换 `payload: dict = Body(...)`。extra="ignore" 容忍前端多发字段。
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
    name: str | None = None
    schedule: str = "manual"
    save: bool = False
    id: str | None = None


class StrategyStatusPut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    schedule: str | None = None
