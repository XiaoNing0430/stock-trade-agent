"""Task 5.2 覆盖率门禁：grid_scheduler.py 调度逻辑补全覆盖（真实 APScheduler，无网络依赖）。"""

from datetime import datetime

from backend import grid_scheduler

_FAKE_NEXT_RUN = datetime(2026, 9, 1, 15, 20, tzinfo=grid_scheduler.TIMEZONE)


class _FakeJob:
    next_run_time = _FAKE_NEXT_RUN


def _grid_strategy(**overrides):
    payload = {
        "id": "cov-g-1",
        "code": "600519",
        "name": "茅台网格",
        "lower": 80.0,
        "upper": 130.0,
        "gridCount": 6,
        "capital": 100000.0,
        "feeBps": 3.0,
        "mode": "classic",
        "lookback": 120,
        "settlementDays": 1,
        "slippageBps": 5.0,
        "schedule": "manual",
        "status": "启用",
        "workspaceId": "cov-ws",
    }
    payload.update(overrides)
    return payload


def test_run_scheduled_backtest(monkeypatch):
    captured = {}
    monkeypatch.setattr(grid_scheduler, "load_history", lambda code, limit=40: [{"close": 10.0}] * 60)
    monkeypatch.setattr(grid_scheduler, "backtest_grid", lambda *args, **kwargs: {"metrics": {"tradeCount": 1}})
    monkeypatch.setattr(grid_scheduler, "save_grid_backtest", lambda *args, **kwargs: captured.update(args=args))
    monkeypatch.setattr(grid_scheduler, "price_limit_ratio", lambda code: 0.1)

    grid_scheduler.run_scheduled_backtest(_grid_strategy(schedule="daily"))

    assert captured["args"][0] == "cov-g-1"


def test_run_scheduled_strategy(monkeypatch):
    captured = {}
    monkeypatch.setattr(grid_scheduler, "load_history", lambda code, limit=40: [{"close": 10.0}] * 60)
    monkeypatch.setattr(
        grid_scheduler,
        "STRATEGY_ENGINES",
        {"ma_cross": {"backtest": lambda history, config: {"metrics": {"tradeCount": 2}}}},
    )
    monkeypatch.setattr(grid_scheduler, "save_strategy_backtest", lambda *args, **kwargs: captured.update(args=args))

    grid_scheduler.run_scheduled_strategy(
        {
            "id": "cov-s-1",
            "code": "600519",
            "strategyType": "ma_cross",
            "config": {"lookback": 120},
            "capital": 100000.0,
            "feeBps": 3.0,
            "workspaceId": "cov-ws",
        }
    )

    assert captured["args"][0] == "cov-s-1"


def test_run_scheduled_strategy_unknown_type():
    # 未知策略类型直接返回，无副作用
    grid_scheduler.run_scheduled_strategy({"id": "x", "code": "600519", "strategyType": "nope"})


def test_schedule_strategy_manual_clears_grid_next_run(monkeypatch):
    cleared = {}
    monkeypatch.setattr(grid_scheduler, "set_grid_next_run", lambda sid, dt: cleared.update(sid=sid, dt=dt))

    assert grid_scheduler.schedule_strategy(_grid_strategy(schedule="manual")) is None
    assert cleared == {"sid": "cov-g-1", "dt": None}


def test_schedule_strategy_disabled_clears_strategy_next_run(monkeypatch):
    cleared = {}
    monkeypatch.setattr(grid_scheduler, "set_strategy_next_run", lambda sid, dt: cleared.update(sid=sid, dt=dt))

    strategy = {"id": "cov-s-1", "status": "暂停", "schedule": "daily"}
    assert grid_scheduler.schedule_strategy(strategy) is None
    assert cleared == {"sid": "cov-s-1", "dt": None}


def test_schedule_strategy_daily_adds_job(monkeypatch):
    captured = {}
    calls = {}

    def fake_add_job(*args, **kwargs):
        calls.update(args=args, kwargs=kwargs)
        return _FakeJob()

    # 注意：APScheduler 3.10 的 Job.next_run_time 仅在 scheduler 运行时才有值；
    # 这里用假 Job 验证 add_job 调用参数与 next_run_time 透传，避免依赖真实调度器运行状态。
    monkeypatch.setattr(grid_scheduler.scheduler, "add_job", fake_add_job)
    monkeypatch.setattr(grid_scheduler, "set_grid_next_run", lambda sid, dt: captured.update(sid=sid, dt=dt))

    next_run = grid_scheduler.schedule_strategy(_grid_strategy(schedule="daily"))

    assert next_run == _FAKE_NEXT_RUN
    assert calls["kwargs"]["id"] == "grid-backtest:cov-g-1"
    assert captured == {"sid": "cov-g-1", "dt": _FAKE_NEXT_RUN}


def test_unschedule_strategy_removes_existing_jobs(monkeypatch):
    # 直接注册一个真实 job（DateTrigger 远期），验证 unschedule 的 get_job/remove_job 路径
    scheduler = grid_scheduler.scheduler
    scheduler.add_job(
        lambda *args, **kwargs: None,
        "date",
        run_date=datetime(2099, 1, 1, 0, 0),
        id="grid-backtest:cov-g-1",
        replace_existing=True,
    )
    try:
        assert scheduler.get_job("grid-backtest:cov-g-1") is not None
        grid_scheduler.unschedule_strategy("cov-g-1")
        assert scheduler.get_job("grid-backtest:cov-g-1") is None
        grid_scheduler.unschedule_strategy("cov-g-1")  # 已删除：no-op
    finally:
        if scheduler.get_job("grid-backtest:cov-g-1"):
            scheduler.remove_job("grid-backtest:cov-g-1")


def test_start_scheduler_schedules_existing(monkeypatch):
    added = []

    def fake_add_job(*args, **kwargs):
        added.append(kwargs["id"])
        return _FakeJob()

    monkeypatch.setattr(grid_scheduler.scheduler, "add_job", fake_add_job)
    monkeypatch.setattr(
        grid_scheduler,
        "list_scheduled_grid_strategies",
        lambda: [_grid_strategy(id="cov-g-2", schedule="daily")],
    )
    monkeypatch.setattr(
        grid_scheduler,
        "list_scheduled_strategies",
        lambda: [
            {
                "id": "cov-s-2",
                "code": "600519",
                "strategyType": "ma_cross",
                "config": {},
                "status": "启用",
                "schedule": "daily",
                "capital": 100000.0,
                "feeBps": 3.0,
                "workspaceId": "cov-ws",
            }
        ],
    )

    was_running = grid_scheduler.scheduler.running
    try:
        grid_scheduler.start_scheduler()
    finally:
        if not was_running:
            grid_scheduler.stop_scheduler()

    assert "grid-backtest:cov-g-2" in added
    assert "strategy-backtest:cov-s-2" in added
