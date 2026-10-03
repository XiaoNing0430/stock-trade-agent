"""声明式选股策略配置加载：backend/screener/configs/*.json → Pydantic 校验。"""

from __future__ import annotations

import json
import math
from importlib import resources
from typing import Any

from pydantic import BaseModel, Field, field_validator

# quick_filters 字段白名单：管道行数值字段——未知字段会因行值缺失静默全滤，挡在保存前
ALLOWED_QUICK_FILTER_FIELDS = {"pe", "pb", "turnoverRate", "changePct", "amount"}
# 因子条数上限（执行资源上界，spec r2：1000 码 × ≤20 因子有界）
MAX_ADVANCED_FACTORS = 20


class ScreenerFactorSpec(BaseModel):
    """单因子条件：name + period + operator + threshold + weight。"""

    name: str
    period: int = Field(default=14, ge=2, le=250)
    operator: str
    threshold: float
    weight: float = Field(default=1.0, ge=0.01, le=100)

    @field_validator("operator")
    @classmethod
    def _check_operator(cls, v: str) -> str:
        if v not in (">", "<", ">=", "<="):
            raise ValueError(f"operator must be one of > < >= <=, got {v!r}")
        return v

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        from backend.screener.factors import FactorLibrary

        if v not in FactorLibrary.available_factors():
            raise ValueError(f"factor name must be one of {FactorLibrary.available_factors()}, got {v!r}")
        return v

    @field_validator("threshold")
    @classmethod
    def _check_threshold(cls, v: float) -> float:
        if not math.isfinite(v) or abs(v) > 1_000_000:
            raise ValueError("threshold must be a finite value with |threshold| <= 1e6")
        return v


class ScreenerStrategyConfig(BaseModel):
    """选股策略：粗筛 quick_filters + 精筛 advanced_factors + 排序/截断。"""

    id: str
    name: str
    description: str = ""
    # quick_filters: 字段 → [min, max]，None 表示该侧不设限
    quick_filters: dict[str, tuple[float | None, float | None]] = Field(default_factory=dict)
    advanced_factors: list[ScreenerFactorSpec] = Field(default_factory=list)
    sort_by: str = "changePct"
    top_n: int = Field(default=10, ge=1, le=100)
    deep_cap: int = Field(default=200, ge=1, le=1000)
    # 深度精筛阶段 deadline（秒）；默认 45s，可按策略覆盖
    history_deadline_s: float = Field(default=45.0, gt=0, le=300)

    @field_validator("quick_filters")
    @classmethod
    def _check_quick_filters(cls, v: dict[str, Any]) -> dict[str, tuple[float | None, float | None]]:  # noqa: ARG001
        out: dict[str, tuple[float | None, float | None]] = {}
        for key, bounds in v.items():
            if key not in ALLOWED_QUICK_FILTER_FIELDS:
                raise ValueError(f"quick_filters[{key!r}] not allowed; allowed: {sorted(ALLOWED_QUICK_FILTER_FIELDS)}")
            if not isinstance(bounds, list | tuple) or len(bounds) != 2:
                raise ValueError(f"quick_filters[{key!r}] must be [min, max]")
            lo, hi = bounds
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"quick_filters[{key!r}] min > max")
            out[key] = (lo, hi)
        return out

    @field_validator("advanced_factors")
    @classmethod
    def _check_factor_count(cls, v: list[ScreenerFactorSpec]) -> list[ScreenerFactorSpec]:
        if len(v) > MAX_ADVANCED_FACTORS:
            raise ValueError(f"advanced_factors supports at most {MAX_ADVANCED_FACTORS} factors, got {len(v)}")
        return v


_CONFIGS_DIR = "configs"


def list_strategies() -> list[ScreenerStrategyConfig]:
    """列出全部内置策略（按 id 排序，稳定顺序）。"""
    entries = [e for e in resources.files(__package__).joinpath(_CONFIGS_DIR).iterdir() if e.name.endswith(".json")]
    configs: list[ScreenerStrategyConfig] = []
    for entry in sorted(entries, key=lambda e: e.name):
        data = json.loads(entry.read_text(encoding="utf-8"))
        configs.append(ScreenerStrategyConfig.model_validate(data))
    return configs


def load_strategy(strategy_id: str) -> ScreenerStrategyConfig:
    """加载策略：内置文件优先（防碰撞安全网）→ 自定义 DB；未知 id 抛 ValueError。"""
    path = resources.files(__package__).joinpath(_CONFIGS_DIR).joinpath(f"{strategy_id}.json")
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        return ScreenerStrategyConfig.model_validate(data)
    from backend import storage

    row = storage.get_custom_strategy(strategy_id)
    if row is not None:
        return ScreenerStrategyConfig.model_validate(row["config"])
    raise ValueError(f"unknown strategy: {strategy_id}")
