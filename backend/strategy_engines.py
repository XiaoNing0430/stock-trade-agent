"""策略注册表：集中登记策略类，供 API 与调度器按 id 调用。

策略实现在 backend.strategies 包中，本文件不再承载回测逻辑。
"""

from typing import Any

from backend.strategies.dca import DcaStrategy
from backend.strategies.ma_cross import MaCrossStrategy
from backend.strategies.macd import MacdStrategy

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
}
