from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.data_source import classify_code, load_history
from backend.grid_strategy import backtest_grid
from backend.storage import list_scheduled_grid_strategies, save_grid_backtest, set_grid_next_run

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
    )
    save_grid_backtest(strategy["id"], strategy["code"], strategy, result, strategy.get("workspaceId", "default"))


def schedule_strategy(strategy: dict) -> datetime | None:
    job_id = f"grid-backtest:{strategy['id']}"
    scheduler.remove_job(job_id) if scheduler.get_job(job_id) else None
    if strategy.get("status") != "启用" or strategy.get("schedule") != "daily":
        set_grid_next_run(strategy["id"], None)
        return None
    job = scheduler.add_job(
        run_scheduled_backtest,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=20, timezone=TIMEZONE),
        args=[strategy],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    set_grid_next_run(strategy["id"], job.next_run_time)
    return job.next_run_time


def unschedule_strategy(strategy_id: str) -> None:
    job_id = f"grid-backtest:{strategy_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
    for strategy in list_scheduled_grid_strategies():
        schedule_strategy(strategy)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
