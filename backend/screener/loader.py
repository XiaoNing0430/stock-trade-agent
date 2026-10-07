"""声明式选股策略配置加载：backend/screener/configs/*.json → Pydantic 校验。"""

from __future__ import annotations

import json
import math
from importlib import resources
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# quick_filters 字段白名单：管道行数值字段——未知字段会因行值缺失静默全滤，挡在保存前
ALLOWED_QUICK_FILTER_FIELDS = {"pe", "pb", "turnoverRate", "changePct", "amount"}
# 因子条数上限（执行资源上界，spec r2：1000 码 × ≤20 因子有界）
MAX_ADVANCED_FACTORS = 20
# 文本上界：对齐 DB 列宽（screener_custom_strategies.name String(64) / description String(256)），
# 否则真库 PG 会 DataError → 被兜成 502，而非契约要求的 422
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 256


class ScreenerFactorSpec(BaseModel):
    """单因子条件：name + period + operator + threshold + weight。"""

    name: str
    period: int = Field(default=14, ge=2, le=250)
    operator: str
    threshold: float
    weight: float = Field(default=1.0, ge=0.01, le=100)

    @model_validator(mode="before")
    @classmethod
    def _normalize_blank_inputs(cls, data: Any) -> Any:
        """空数值输入视为未填：有默认值的字段省略键（用默认），阈值必填 → 中文报错。

        Vue `v-model.number` 清空输入框会送 `''`（不是 null），此前会直落 pydantic 英文 422。
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for key in ("period", "weight"):
            if data.get(key) == "":
                data.pop(key, None)
        if "threshold" in data and data["threshold"] in ("", None):
            raise ValueError("因子阈值不能为空（必填，无默认值）")
        return data

    @field_validator("operator")
    @classmethod
    def _check_operator(cls, v: str) -> str:
        if v not in (">", "<", ">=", "<="):
            raise ValueError(f"算子必须是 > < >= <= 之一，收到 {v!r}")
        return v

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        from backend.screener.factors import FactorLibrary

        available = FactorLibrary.available_factors()
        if v not in available:
            raise ValueError(f"未知因子 {v!r}；可用因子：{'、'.join(available)}")
        return v

    @field_validator("threshold")
    @classmethod
    def _check_threshold(cls, v: float) -> float:
        if not math.isfinite(v) or abs(v) > 1_000_000:
            raise ValueError("阈值必须为有限值且 |阈值| ≤ 1e6")
        return v


class ScreenerStrategyConfig(BaseModel):
    """选股策略：粗筛 quick_filters + 精筛 advanced_factors + 排序/截断。"""

    id: str
    name: str = Field(max_length=MAX_NAME_LENGTH)
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LENGTH)
    # quick_filters: 字段 → [min, max]，None 表示该侧不设限
    quick_filters: dict[str, tuple[float | None, float | None]] = Field(default_factory=dict)
    advanced_factors: list[ScreenerFactorSpec] = Field(default_factory=list)
    sort_by: str = "changePct"
    top_n: int = Field(default=10, ge=1, le=100)
    deep_cap: int = Field(default=200, ge=1, le=1000)
    # 深度精筛阶段 deadline（秒）；默认 45s，可按策略覆盖
    history_deadline_s: float = Field(default=45.0, gt=0, le=300)

    @model_validator(mode="before")
    @classmethod
    def _normalize_blank_inputs(cls, data: Any) -> Any:
        """空数值输入视为未填：清空数字框（`''`）回落既有默认值，两侧皆空的区间整键丢弃。"""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for key in ("top_n", "deep_cap", "history_deadline_s"):
            if data.get(key) == "":
                data.pop(key, None)
        filters = data.get("quick_filters")
        if isinstance(filters, dict):
            normalized: dict[str, Any] = {}
            for key, bounds in filters.items():
                if isinstance(bounds, list | tuple) and len(bounds) == 2:
                    lo = None if bounds[0] in ("", None) else bounds[0]
                    hi = None if bounds[1] in ("", None) else bounds[1]
                    if lo is None and hi is None:
                        continue  # 「留空 = 不设限」：两侧皆空等价于不声明该键
                    normalized[key] = [lo, hi]
                else:
                    normalized[key] = bounds  # 形状不对：交给下方校验器/类型检查报错
            data["quick_filters"] = normalized
        return data

    @field_validator("quick_filters")
    @classmethod
    def _check_quick_filters(cls, v: dict[str, Any]) -> dict[str, tuple[float | None, float | None]]:  # noqa: ARG001
        out: dict[str, tuple[float | None, float | None]] = {}
        for key, bounds in v.items():
            if key not in ALLOWED_QUICK_FILTER_FIELDS:
                allowed = "、".join(sorted(ALLOWED_QUICK_FILTER_FIELDS))
                raise ValueError(f"不支持的粗筛字段 {key!r}；允许的字段：{allowed}")
            if not isinstance(bounds, list | tuple) or len(bounds) != 2:
                raise ValueError(f"粗筛字段 {key!r} 的区间必须为 [最小值, 最大值]")
            lo, hi = bounds
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"粗筛字段 {key!r} 的最小值不能大于最大值")
            out[key] = (lo, hi)
        return out

    @field_validator("advanced_factors")
    @classmethod
    def _check_factor_count(cls, v: list[ScreenerFactorSpec]) -> list[ScreenerFactorSpec]:
        if len(v) > MAX_ADVANCED_FACTORS:
            raise ValueError(f"因子最多 {MAX_ADVANCED_FACTORS} 条，当前 {len(v)} 条")
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
