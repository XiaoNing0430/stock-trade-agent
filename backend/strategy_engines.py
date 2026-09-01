"""策略注册表：集中登记策略类，供 API 与调度器按 id 调用。

策略实现在 backend.strategies 包中，本文件不再承载回测逻辑。
"""

from typing import Any

from backend.multi_factor import MultiFactorStrategy
from backend.strategies.bollinger import BollingerStrategy
from backend.strategies.dca import DcaStrategy
from backend.strategies.donchian import DonchianStrategy
from backend.strategies.ma_cross import MaCrossStrategy
from backend.strategies.macd import MacdStrategy
from backend.strategies.momentum import MomentumStrategy

STRATEGY_ENGINES: dict[str, dict[str, Any]] = {
    "ma_cross": {
        "label": "双均线",
        "backtest": MaCrossStrategy().backtest,
        "suggest": None,
        "configSchema": MaCrossStrategy.config_schema,
    },
    "dca": {
        "label": "定投",
        "backtest": DcaStrategy().backtest,
        "suggest": None,
        "configSchema": DcaStrategy.config_schema,
    },
    "macd": {
        "label": "MACD",
        "backtest": MacdStrategy().backtest,
        "suggest": None,
        "configSchema": MacdStrategy.config_schema,
    },
    "bollinger": {
        "label": "布林带反转",
        "backtest": BollingerStrategy().backtest,
        "suggest": None,
        "configSchema": BollingerStrategy.config_schema,
    },
    "donchian": {
        "label": "唐奇安突破",
        "backtest": DonchianStrategy().backtest,
        "suggest": None,
        "configSchema": DonchianStrategy.config_schema,
    },
    "momentum": {
        "label": "动量",
        "backtest": MomentumStrategy().backtest,
        "suggest": None,
        "configSchema": MomentumStrategy.config_schema,
    },
    "multi_factor": {
        "label": "多因子",
        "backtest": MultiFactorStrategy().backtest,
        "suggest": None,
        "configSchema": MultiFactorStrategy.config_schema,
    },
}
