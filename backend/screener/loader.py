"""声明式选股策略配置加载：backend/screener/configs/*.json → Pydantic 校验。"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ScreenerFactorSpec(BaseModel):
    """单因子条件：name + period + operator + threshold + weight。"""

    name: str
    period: int = Field(default=14, ge=2, le=250)
    operator: str
    threshold: float
    weight: float = Field(default=1.0, gt=0)

    @field_validator("operator")
    @classmethod
    def _check_operator(cls, v: str) -> str:
        if v not in (">", "<", ">=", "<="):
            raise ValueError(f"operator must be one of > < >= <=, got {v!r}")
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
            if not isinstance(bounds, list | tuple) or len(bounds) != 2:
                raise ValueError(f"quick_filters[{key!r}] must be [min, max]")
            lo, hi = bounds
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"quick_filters[{key!r}] min > max")
            out[key] = (lo, hi)
        return out


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
    """加载单个策略；未知 id 抛 ValueError。"""
    path = resources.files(__package__).joinpath(_CONFIGS_DIR).joinpath(f"{strategy_id}.json")
    if not path.is_file():
        raise ValueError(f"unknown strategy: {strategy_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return ScreenerStrategyConfig.model_validate(data)
