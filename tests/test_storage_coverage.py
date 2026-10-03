"""Task 5.2 覆盖率门禁：storage.py 持久化函数补全覆盖。

沿用现有 monkeypatch 离线模式 + 真实 PostgreSQL（与 test_backend_api.py 中
initialize_storage / save_market_bars 用法一致）；使用专用工作区 cov-ws，不污染默认数据。
"""

from datetime import UTC, datetime

import pytest
from backend import storage as storage_module

# 专用测试工作区，避免覆盖默认工作区真实数据
WS = "cov-ws"


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables():
    storage_module.initialize_storage()


@pytest.fixture(autouse=True)
def _cleanup_test_data():
    yield
    from sqlalchemy import delete

    models = [
        storage_module.WatchlistItem,
        storage_module.TradePlan,
        storage_module.Alert,
        storage_module.GridStrategy,
        storage_module.GridBacktest,
        storage_module.Strategy,
        storage_module.StrategyBacktest,
        storage_module.WorkspaceState,
        storage_module.WorkspaceSettings,
    ]
    with storage_module.engine.begin() as connection:
        for model in models:
            connection.execute(delete(model).where(model.workspace_id == WS))
        connection.execute(delete(storage_module.MarketBar).where(storage_module.MarketBar.code.like("cov-%")))


def test_storage_status_database_failure(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(storage_module, "SessionLocal", boom)

    # 同时 mock Redis ping，确保与 Redis 可用性无关（CI 无 Redis 时也确定通过）
    class _FakeRedis:
        def ping(self) -> bool:
            return True

    monkeypatch.setattr(storage_module, "redis_client", lambda: _FakeRedis())
    status = storage_module.storage_status()
    assert status["database"] is False
    assert status["redis"] is True


def test_storage_status_redis_failure(monkeypatch):
    def boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(storage_module, "redis_client", boom)
    status = storage_module.storage_status()
    assert status["database"] is True
    assert status["redis"] is False


def test_save_workspace_roundtrip_dedup_and_cleanup():
    payload = {
        "watchlist": ["600519", "600519", "300750"],
        "plans": [
            {
                "id": "plan-1",
                "code": "600519",
                "direction": "buy",
                "entry": 100,
                "stop": 90,
                "target": 120,
                "capital": 50000,
                "position": 100,
                "validity": "本周内",
                "note": "n",
                "status": "执行中",
                "triggered": {"x": 1},
            },
            {"code": "300750"},  # 无 id → 过滤
        ],
        "alerts": [{"id": "alert-1", "kind": "info", "title": "t", "message": "m", "read": False}],
    }
    saved = storage_module.save_workspace(payload, WS)
    assert saved["watchlist"] == ["600519", "300750"]  # 重复 code 去重
    assert saved["revision"] == 1
    assert [p["id"] for p in saved["plans"]] == ["plan-1"]
    assert "createdAtMs" in saved["plans"][0]
    assert saved["alerts"][0]["id"] == "alert-1"

    # 更新：删除 plan-1、新增 plan-2，alerts 置为已读
    updated = storage_module.save_workspace(
        {
            "watchlist": ["000001"],
            "plans": [{"id": "plan-2", "code": "000001"}],
            "alerts": [{"id": "alert-1", "kind": "info", "title": "t2", "message": "m2", "read": True}],
        },
        WS,
    )
    assert updated["watchlist"] == ["000001"]
    assert [p["id"] for p in updated["plans"]] == ["plan-2"]
    assert updated["alerts"][0]["read"] is True
    assert updated["revision"] == 2


def test_save_workspace_removes_orphaned_alerts():
    """删除分支：第二次保存时移除 alert → 触发 session.delete(existing_alert)"""
    payload = {
        "watchlist": [],
        "plans": [],
        "alerts": [{"id": "alert-1", "kind": "info", "title": "t", "message": "m", "read": False}],
    }
    storage_module.save_workspace(payload, WS)
    # 第二次保存：移除 alert-1
    cleaned = storage_module.save_workspace({"watchlist": [], "plans": [], "alerts": []}, WS)
    assert len(cleaned["alerts"]) == 0
    # 重新读取确认持久化
    reloaded = storage_module.get_workspace(WS)
    assert len(reloaded["alerts"]) == 0
    assert reloaded["revision"] == 2


def test_save_workspace_settings_roundtrip_and_clamping():
    saved = storage_module.save_workspace_settings(
        {
            "workspaceName": "  我的工作区  ",
            "defaultCapital": 50,
            "refreshInterval": 1,
            "cacheSeconds": 0,
            "timeoutSeconds": 999,
            "retryCount": -3,
            "conflictPolicy": "bogus",
            "realtimeSource": "bogus",
        },
        WS,
    )
    assert saved["workspaceName"] == "我的工作区"
    assert saved["defaultCapital"] == 1000
    assert saved["refreshInterval"] == 5
    assert saved["cacheSeconds"] == 2
    assert saved["timeoutSeconds"] == 60
    assert saved["retryCount"] == 0
    assert saved["conflictPolicy"] == "server"
    assert saved["realtimeSource"] == "tencent"

    # update 分支 + workspaceName 截断
    again = storage_module.save_workspace_settings({"workspaceName": "A" * 100}, WS)
    assert len(again["workspaceName"]) == 64
    assert storage_module.get_workspace_settings(WS) == again
    # 不存在的工作区 → 默认设置
    assert storage_module.get_workspace_settings("cov-nonexistent") == storage_module.DEFAULT_WORKSPACE_SETTINGS


_GRID_PAYLOAD = {
    "id": "g-cov-1",
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
}


def test_grid_strategy_roundtrip_and_delete():
    saved = storage_module.save_grid_strategy(_GRID_PAYLOAD, WS)
    assert saved["id"] == "g-cov-1"
    assert saved["workspaceId"] == WS
    assert storage_module.get_grid_strategy("g-cov-1")["upper"] == 130
    assert [s["id"] for s in storage_module.list_grid_strategies(WS)] == ["g-cov-1"]
    assert storage_module.get_grid_strategy("absent") is None
    assert storage_module.delete_grid_strategy("absent", WS) is False
    # update 分支
    updated = storage_module.save_grid_strategy({**_GRID_PAYLOAD, "upper": 140.0}, WS)
    assert updated["upper"] == 140
    assert storage_module.delete_grid_strategy("g-cov-1", WS) is True
    assert storage_module.get_grid_strategy("g-cov-1") is None


def test_grid_backtest_persists_metrics_and_next_run():
    storage_module.save_grid_strategy(_GRID_PAYLOAD, WS)
    result = {"metrics": {"tradeCount": 3, "returnPct": 1.2}}
    storage_module.save_grid_backtest("g-cov-1", "600519", {"lower": 80}, result, WS)
    strategy = storage_module.get_grid_strategy("g-cov-1")
    assert strategy["lastBacktestAt"] is not None
    assert strategy["latestMetrics"]["tradeCount"] == 3
    storage_module.set_grid_next_run("g-cov-1", datetime(2026, 9, 1, 15, 20, tzinfo=UTC))
    assert storage_module.get_grid_strategy("g-cov-1")["nextRunAt"] is not None
    storage_module.set_grid_next_run("absent", datetime.now(UTC))  # 不存在的策略：no-op
    # 删除带回测记录的网格策略
    assert storage_module.delete_grid_strategy("g-cov-1", WS) is True


_STRATEGY_PAYLOAD = {
    "id": "s-cov-1",
    "code": "600519",
    "name": "茅台策略",
    "strategyType": "ma_cross",
    "config": {"fastPeriod": 5, "slowPeriod": 20},
    "capital": 100000.0,
    "feeBps": 3.0,
    "schedule": "manual",
    "status": "启用",
}


def test_strategy_roundtrip_backtest_and_delete():
    saved = storage_module.save_strategy(_STRATEGY_PAYLOAD, WS)
    assert saved["id"] == "s-cov-1"
    assert storage_module.get_strategy("s-cov-1")["strategyType"] == "ma_cross"
    assert [s["id"] for s in storage_module.list_strategies(WS)] == ["s-cov-1"]
    assert storage_module.get_strategy("absent") is None
    assert storage_module.list_scheduled_strategies() == []  # manual → 不进入每日调度

    result = {"metrics": {"tradeCount": 4, "returnPct": 2.0}}
    storage_module.save_strategy_backtest("s-cov-1", "600519", "ma_cross", {"fastPeriod": 5}, result, WS)
    strategy = storage_module.get_strategy("s-cov-1")
    assert strategy["latestMetrics"]["tradeCount"] == 4
    storage_module.set_strategy_next_run("s-cov-1", datetime(2026, 9, 1, 15, 20, tzinfo=UTC))
    assert storage_module.get_strategy("s-cov-1")["nextRunAt"] is not None

    # update 分支
    storage_module.save_strategy({**_STRATEGY_PAYLOAD, "status": "暂停"}, WS)
    assert storage_module.get_strategy("s-cov-1")["status"] == "暂停"
    assert storage_module.delete_strategy("absent", WS) is False
    assert storage_module.delete_strategy("s-cov-1", WS) is True
    assert storage_module.get_strategy("s-cov-1") is None


def test_save_market_bars_skips_blank_date():
    latest = storage_module.save_market_bars(
        "cov-code",
        [
            {"date": "", "open": 10, "close": 11},
            {"date": "2026-09-01", "open": 11, "close": 12},
            {},
        ],
    )
    assert latest == "2026-09-01"
    loaded = storage_module.load_market_bars("cov-code")
    assert [bar["date"] for bar in loaded] == ["2026-09-01"]


def test_cleanup_legacy_index_qfq_is_idempotent():
    """A1 一次性清理：歧义桶 (指数共用码,'qfq') 整删且幂等；隔离桶 qfq:idx 与无关 code 不误伤。"""
    from sqlalchemy import delete, select

    day = "2099-12-31"  # 生僻交易日，避免与真实缓存行相撞

    def _bar(code: str, adjustment: str) -> storage_module.MarketBar:
        return storage_module.MarketBar(
            code=code, trade_date=day, adjustment=adjustment, open=1, high=2, low=0.5, close=1.5
        )

    with storage_module.SessionLocal.begin() as session:
        session.add_all([_bar("000001", "qfq"), _bar("000001", "qfq:idx"), _bar("cov-keep", "qfq")])
    try:
        assert storage_module.cleanup_legacy_index_qfq() >= 1
        assert storage_module.cleanup_legacy_index_qfq() == 0  # 幂等：二次调用无行可删
        with storage_module.SessionLocal() as session:
            buckets = set(
                session.scalars(
                    select(storage_module.MarketBar.adjustment).where(
                        storage_module.MarketBar.code == "000001", storage_module.MarketBar.trade_date == day
                    )
                ).all()
            )
            survivor = session.scalars(
                select(storage_module.MarketBar).where(
                    storage_module.MarketBar.code == "cov-keep", storage_module.MarketBar.trade_date == day
                )
            ).first()
        assert buckets == {"qfq:idx"}  # 歧义桶已清空，隔离桶保留
        assert survivor is not None  # 非歧义 code 的 qfq 行不动（cov-keep 由模块夹具收尾）
    finally:
        with storage_module.SessionLocal.begin() as session:
            session.execute(
                delete(storage_module.MarketBar).where(
                    storage_module.MarketBar.code == "000001", storage_module.MarketBar.trade_date == day
                )
            )


def test_upsert_market_bars_batch_idempotent_dedup_and_guards():
    """I10：ETL 批量 upsert——ON CONFLICT 幂等、批内同日去重保后者、空 bars 拒写、外部 session 加入组事务。"""
    from backend.storage import MarketBar, SessionLocal, upsert_market_bars_batch
    from sqlalchemy import delete, func, select

    d1, d2 = "2099-11-01", "2099-11-02"
    bars = [
        {"date": d1, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10, "amount": 15},
        {"date": d1, "open": 1, "high": 3, "low": 0.5, "close": 2.5, "volume": 20, "amount": 50},  # 同日后者胜
        {"date": d2, "open": 2, "high": 3, "low": 1, "close": 2.8, "volume": None, "amount": None},
    ]
    try:
        n1 = upsert_market_bars_batch("cov-batch", bars, adjustment="")
        n2 = upsert_market_bars_batch("cov-batch", bars, adjustment="")  # 重放幂等
        assert n1 == 2 and n2 == 2  # 每语句 2 行（插入或冲突覆盖），非累加
        with SessionLocal() as s:
            cnt = s.scalar(
                select(func.count())
                .select_from(MarketBar)
                .where(MarketBar.code == "cov-batch", MarketBar.adjustment == "")
            )
        assert cnt == 2
        loaded = storage_module.load_market_bars("cov-batch", adjustment="", limit=10)
        assert [b["date"] for b in loaded] == [d1, d2]
        assert loaded[0]["close"] == 2.5 and loaded[0]["high"] == 3.0  # 去重保后者
        with pytest.raises(ValueError):
            upsert_market_bars_batch("cov-batch", [], adjustment="")
        # 外部 session（组事务内）：回滚则本码不留痕
        with pytest.raises(RuntimeError):
            with SessionLocal.begin() as outer:
                upsert_market_bars_batch("cov-outer", bars, adjustment="", session=outer)
                raise RuntimeError("group abort")
        with SessionLocal() as s:
            assert s.scalar(select(func.count()).select_from(MarketBar).where(MarketBar.code == "cov-outer")) == 0
    finally:
        with SessionLocal.begin() as s:
            s.execute(delete(MarketBar).where(MarketBar.code.in_(["cov-batch", "cov-outer"])))
