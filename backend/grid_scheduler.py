from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.data_source import classify_code, load_history, price_limit_ratio
from backend.grid_strategy import backtest_grid
from backend.storage import (
    list_scheduled_grid_strategies,
    list_scheduled_strategies,
    save_grid_backtest,
    save_strategy_backtest,
    set_grid_next_run,
    set_strategy_next_run,
)
from backend.strategy_engines import STRATEGY_ENGINES

TIMEZONE = ZoneInfo("Asia/Shanghai")
scheduler = BackgroundScheduler(timezone=TIMEZONE)


def run_scheduled_backtest(strategy: dict) -> None:
    history = load_history(strategy["code"], limit=max(20, min(int(strategy.get("lookback", 120)), 240)))
    profile = classify_code(strategy["code"])
    result = backtest_grid(
        history,
        float(strategy["lower"]),
        float(strategy["upper"]),
        int(strategy["gridCount"]),
        float(strategy["capital"]),
        float(strategy["feeBps"]),
        str(strategy.get("mode", "classic")),
        profile["securityType"],
        profile["exchange"],
        settlement_days=int(strategy.get("settlementDays", 1)),
        slippage_bps=float(strategy.get("slippageBps", 5)),
        price_limit_pct=price_limit_ratio(strategy["code"]),
    )
    save_grid_backtest(strategy["id"], strategy["code"], strategy, result, strategy.get("workspaceId", "default"))


def run_scheduled_strategy(strategy: dict) -> None:
    """通用策略（双均线/DCA/MACD）的每日调度回测。"""
    strategy_type = str(strategy.get("strategyType", ""))
    engine = STRATEGY_ENGINES.get(strategy_type)
    if not engine:
        return
    config = dict(strategy.get("config") or {})
    lookback = int(config.get("lookback", 120))
    history = load_history(strategy["code"], limit=max(20, min(lookback, 240)))
    profile = classify_code(strategy["code"])
    config.update({
        "capital": float(strategy.get("capital", 100000)),
        "feeBps": float(strategy.get("feeBps", 3)),
        "securityType": profile["securityType"],
        "exchange": profile["exchange"],
        "lookback": lookback,
    })
    result = engine["backtest"](history, config)
    save_strategy_backtest(strategy["id"], strategy["code"], strategy_type, strategy, result, strategy.get("workspaceId", "default"))


def schedule_strategy(strategy: dict) -> datetime | None:
    """调度一个策略：网格用 grid-backtest 前缀，通用策略用 strategy-backtest 前缀。"""
    prefix = "grid-backtest" if "lower" in strategy else "strategy-backtest"
    job_id = f"{prefix}:{strategy['id']}"
    scheduler.remove_job(job_id) if scheduler.get_job(job_id) else None
    if strategy.get("status") != "启用" or strategy.get("schedule") != "daily":
        if "lower" in strategy:
            set_grid_next_run(strategy["id"], None)
        else:
            set_strategy_next_run(strategy["id"], None)
        return None
    target = run_scheduled_backtest if "lower" in strategy else run_scheduled_strategy
    job = scheduler.add_job(
        target,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=20, timezone=TIMEZONE),
        args=[strategy],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    if "lower" in strategy:
        set_grid_next_run(strategy["id"], job.next_run_time)
    else:
        set_strategy_next_run(strategy["id"], job.next_run_time)
    return job.next_run_time


def unschedule_strategy(strategy_id: str) -> None:
    for prefix in ("grid-backtest", "strategy-backtest"):
        job_id = f"{prefix}:{strategy_id}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
    for strategy in list_scheduled_grid_strategies():
        schedule_strategy(strategy)
    for strategy in list_scheduled_strategies():
        schedule_strategy(strategy)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
