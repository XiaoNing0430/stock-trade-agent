"""策略定时扫描：存储助手 + 去重引擎 + 编排 + 端点。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from backend import storage as storage_module


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables():
    storage_module.initialize_storage()


def _cleanup_scan_tables() -> None:
    from backend.storage import ScreenerScanConfig, ScreenerScanHistory, SessionLocal
    from sqlalchemy import delete

    with SessionLocal() as session:
        session.execute(delete(ScreenerScanHistory))
        session.execute(delete(ScreenerScanConfig))
        session.commit()


def test_upsert_and_get_scan_config() -> None:
    _cleanup_scan_tables()
    from backend.storage import get_scan_config, upsert_scan_config

    cfg = upsert_scan_config("trend_breakout", enabled=True, mode="quick")
    assert cfg["strategyId"] == "trend_breakout"
    assert cfg["enabled"] is True and cfg["mode"] == "quick"
    assert cfg["lastStatus"] is None and cfg["lastHits"] is None
    # 二次 upsert 覆盖（同主键更新不插入）
    cfg2 = upsert_scan_config("trend_breakout", enabled=False, mode="deep")
    assert cfg2["enabled"] is False and cfg2["mode"] == "deep"
    assert get_scan_config("trend_breakout")["mode"] == "deep"
    assert get_scan_config("no_such") is None


def test_update_scan_state_roundtrip_and_guard() -> None:
    _cleanup_scan_tables()
    from backend.storage import get_scan_config, update_scan_state, upsert_scan_config

    upsert_scan_config("trend_breakout", enabled=True, mode="quick")
    hits: list[dict[str, Any]] = [{"code": "600519", "name": "贵州茅台", "score": 82.5, "firstSeen": "2026-09-07"}]
    now = datetime.now(UTC)
    assert update_scan_state("trend_breakout", "ok", hits, now, new_count=1) is True
    cfg = get_scan_config("trend_breakout")
    assert cfg is not None
    assert cfg["lastStatus"] == "ok" and cfg["lastHits"] == hits and cfg["lastNewCount"] == 1
    # require_enabled 守卫：关闭后写入被拒
    upsert_scan_config("trend_breakout", enabled=False, mode="quick")
    assert update_scan_state("trend_breakout", "ok", hits, now, require_enabled=True) is False
    assert update_scan_state("trend_breakout", "ok", hits, now, require_enabled=False) is True


def test_update_scan_state_bad_json_tolerance() -> None:
    _cleanup_scan_tables()
    from backend.storage import ScreenerScanConfig, SessionLocal, get_scan_config, update_scan_state, upsert_scan_config
    from sqlalchemy import update as sa_update

    upsert_scan_config("oversold_bounce", enabled=True, mode="quick")
    # 直接把 last_hits 破坏成坏 JSON（模拟外部污染）
    with SessionLocal() as session:
        session.execute(
            sa_update(ScreenerScanConfig)
            .values(last_hits="{not-json")
            .where(ScreenerScanConfig.id == "oversold_bounce")
        )
        session.commit()
    # 读路径容错：坏 JSON → None（不抛异常）
    cfg = get_scan_config("oversold_bounce")
    assert cfg is not None
    assert cfg["lastHits"] is None
    # 写路径可正常覆盖恢复
    update_scan_state("oversold_bounce", "ok", [], datetime.now(UTC))
    assert get_scan_config("oversold_bounce")["lastHits"] == []


def test_insert_scan_history_rolling_cleanup() -> None:
    _cleanup_scan_tables()
    from backend.storage import insert_scan_history, list_scan_history

    for i in range(7):
        insert_scan_history("trend_breakout", "ok", hit_count=10 + i, new_count=i, elapsed_ms=100 * i, trace_id=f"t{i}")
    rows = list_scan_history("trend_breakout")
    assert len(rows) == 7 and rows[0]["newCount"] == 6  # 按 run_at 降序，最新在前


def test_merge_hits_three_states() -> None:
    from backend.screener.scan import merge_hits

    prev = [
        {"code": "600519", "name": "贵州茅台", "score": 82.5, "firstSeen": "2026-09-04"},
        {"code": "300750", "name": "宁德时代", "score": 77.0, "firstSeen": "2026-09-04"},
    ]
    rows = [
        {"code": "600519", "name": "贵州茅台", "score": 83.0},
        {"code": "510300", "name": "沪深300ETF", "score": 71.2},
    ]
    newly, state = merge_hits(prev, rows, today="2026-09-07")
    # 新进入：510300（600519 滞留保持 firstSeen，300750 跌出）
    assert newly == [{"code": "510300", "name": "沪深300ETF", "score": 71.2, "firstSeen": "2026-09-07"}]
    assert state == [
        {"code": "600519", "name": "贵州茅台", "score": 83.0, "firstSeen": "2026-09-04"},
        {"code": "510300", "name": "沪深300ETF", "score": 71.2, "firstSeen": "2026-09-07"},
    ]


def test_merge_hits_empty_prev_and_empty_rows() -> None:
    from backend.screener.scan import merge_hits

    # 首扫：全部为新
    newly, state = merge_hits([], [{"code": "600519", "name": "贵州茅台"}], today="2026-09-07")
    assert newly == [{"code": "600519", "name": "贵州茅台", "score": None, "firstSeen": "2026-09-07"}]
    # 全部跌出：newly 空，state 空
    prev = [{"code": "600519", "name": "贵州茅台", "score": 82.5, "firstSeen": "2026-09-04"}]
    newly2, state2 = merge_hits(prev, [], today="2026-09-07")
    assert newly2 == [] and state2 == []


def test_merge_hits_ignores_malformed_rows() -> None:
    from backend.screener.scan import merge_hits

    newly, state = merge_hits([], [{"name": "无代码行"}, {"code": "600519", "name": "贵州茅台"}], today="2026-09-07")
    assert len(newly) == 1 and newly[0]["code"] == "600519"


# ---- 编排（Task 3）：FakeRedis / FakePipeline，不起真调度器 ----


class _FakeRedis:
    """SET NX PX / GET / 评估释放的最小替身（同进程语义即可）。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, nx: bool = False, px: int = 0) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:  # 释放脚本原样执行语义
        key, token = keys_and_args[0], keys_and_args[1]
        return 1 if self.store.get(key) == token else 0


class _FakePipeline:
    """run() 返回预设 rows；可注入异常。"""

    def __init__(self, rows: list[dict[str, Any]] | None = None, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def run(
        self, strategy_id: str, mode: str = "quick", refresh: bool = False, reference_date: str | None = None
    ) -> dict[str, Any]:
        if self.error:
            raise self.error
        self.calls.append((strategy_id, mode))
        return {
            "strategy": strategy_id,
            "name": strategy_id,
            "mode": mode,
            "referenceDate": "2026-09-05",
            "provider": "腾讯",
            "rows": self.rows,
            "total": len(self.rows),
            "cached": False,
            "stale": False,
            "elapsedMs": 123,
        }


_ROWS_TWO = [
    {"code": "600519", "name": "贵州茅台", "score": 82.5},
    {"code": "300750", "name": "宁德时代", "score": 77.0},
]


def _setup_one_enabled(monkeypatch: Any, strategy_id: str = "trend_breakout") -> None:
    _cleanup_scan_tables()
    from backend.storage import upsert_scan_config

    upsert_scan_config(strategy_id, enabled=True, mode="quick")


def test_run_scan_first_scan_creates_state(monkeypatch: Any) -> None:
    _setup_one_enabled(monkeypatch)
    from backend.screener import scan as scan_module

    fake = _FakeRedis()
    monkeypatch.setattr(scan_module, "redis_client", lambda: fake)
    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: _FakePipeline(rows=_ROWS_TWO))
    result = scan_module.run_scan("trend_breakout", now=datetime(2026, 9, 7, 7, 40, tzinfo=UTC))
    assert result["status"] == "ok" and result["hitCount"] == 2 and result["newCount"] == 2
    from backend.storage import get_scan_config

    cfg = get_scan_config("trend_breakout")
    assert cfg["lastStatus"] == "ok" and len(cfg["lastHits"]) == 2
    assert all(h["firstSeen"] == "2026-09-07" for h in cfg["lastHits"])  # firstSeen = 扫描日（now 可控）
    # 历史摘要已插入
    from backend.storage import list_scan_history

    assert list_scan_history("trend_breakout")[0]["newCount"] == 2


def test_run_scan_failure_isolated_and_records_failed(monkeypatch: Any) -> None:
    _setup_one_enabled(monkeypatch)
    from backend.screener import scan as scan_module

    monkeypatch.setattr(scan_module, "redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: _FakePipeline(error=RuntimeError("upstream down")))
    result = scan_module.run_scan("trend_breakout")
    assert result["status"] == "failed"
    from backend.storage import get_scan_config

    assert get_scan_config("trend_breakout")["lastStatus"] == "failed"


def test_run_all_scans_sequential_and_failure_isolation(monkeypatch: Any) -> None:
    _cleanup_scan_tables()
    from backend.storage import upsert_scan_config

    upsert_scan_config("trend_breakout", enabled=True, mode="quick")
    upsert_scan_config("oversold_bounce", enabled=True, mode="quick")
    from backend.screener import scan as scan_module

    monkeypatch.setattr(scan_module, "redis_client", lambda: _FakeRedis())

    # 第一个策略炸、第二个正常：验证继续执行（失败隔离）
    def fake_run(strategy_id: str, mode: str = "quick", **kwargs: Any) -> dict[str, Any]:
        if strategy_id == "trend_breakout":
            raise RuntimeError("boom")
        return _FakePipeline(rows=_ROWS_TWO).run(strategy_id, mode)

    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: type("P", (), {"run": staticmethod(fake_run)})())
    monkeypatch.setattr(scan_module, "_schedule_retry", lambda strategy_id: None)  # 失败路径不触真调度器
    results = scan_module.run_all_scans()
    assert len(results) == 2
    assert {r["strategyId"]: r["status"] for r in results} == {
        "trend_breakout": "failed",
        "oversold_bounce": "ok",
    }


def test_run_all_scans_disabled_midway_skips_state_write(monkeypatch: Any) -> None:
    _setup_one_enabled(monkeypatch)
    from backend.screener import scan as scan_module

    monkeypatch.setattr(scan_module, "redis_client", lambda: _FakeRedis())
    calls: list[str] = []

    def fake_run(strategy_id: str, mode: str = "quick", **kwargs: Any) -> dict[str, Any]:
        calls.append(strategy_id)
        # 首次调用后关闭开关（模拟扫描中途用户关闭）
        from backend.storage import upsert_scan_config

        upsert_scan_config(strategy_id, enabled=False, mode="quick")
        return _FakePipeline(rows=_ROWS_TWO).run(strategy_id, mode)

    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: type("P", (), {"run": staticmethod(fake_run)})())
    result = scan_module.run_scan("trend_breakout")
    # FR-13⑤：require_enabled 拦截 → last_status 不被覆盖
    from backend.storage import get_scan_config

    assert get_scan_config("trend_breakout")["lastStatus"] is None
    assert result["status"] == "skipped"


def test_run_all_scans_lock_blocks_second_runner(monkeypatch: Any) -> None:
    _setup_one_enabled(monkeypatch)
    from backend.screener import scan as scan_module

    fake = _FakeRedis()
    fake.set("scan:lock", "other-worker", nx=True, px=900_000)  # 他人持锁
    monkeypatch.setattr(scan_module, "redis_client", lambda: fake)
    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: _FakePipeline(rows=_ROWS_TWO))
    results = scan_module.run_all_scans()
    assert results == []  # 未获锁直接返回空，不执行


def test_run_all_scans_degrades_without_redis(monkeypatch: Any) -> None:
    _setup_one_enabled(monkeypatch)
    from backend.screener import scan as scan_module

    def boom() -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(scan_module, "redis_client", boom)
    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: _FakePipeline(rows=_ROWS_TWO))
    results = scan_module.run_all_scans()
    assert len(results) == 1 and results[0]["status"] == "ok"  # 降级无锁继续


def test_register_scan_jobs_registers_two_crons_and_misfire_listener(monkeypatch: Any) -> None:
    from backend.screener import scan as scan_module

    added: list[tuple[str, str, str]] = []

    class _FakeScheduler:
        running = True

        def add_job(self, func: Any, trigger: Any, id: str, replace_existing: bool = True, **kwargs: Any) -> None:
            # APScheduler 3.11 的 CronTrigger.__str__ 不含 timezone，拼入 trigger.timezone 以便断言时区
            added.append(
                (id, f"{trigger} tz={getattr(trigger, 'timezone', None)}", str(kwargs.get("misfire_grace_time")))
            )

        def get_job(self, job_id: str) -> None:
            return None

        def remove_job(self, job_id: str) -> None:
            pass

        def add_listener(self, cb: Any, mask: int | None = None) -> None:
            added.append(("listener", str(mask), ""))

    fake_sched = _FakeScheduler()
    monkeypatch.setattr(scan_module, "_get_scheduler", lambda: fake_sched)
    scan_module.register_scan_jobs()
    ids = [a[0] for a in added]
    assert "scan:weekday" in ids and "scan:weekend" in ids and any(i == "listener" for i in ids)
    # cron 时刻正确（15:40 / 10:00）且时区为 Asia/Shanghai
    weekday = next(a for a in added if a[0] == "scan:weekday")
    assert "15" in weekday[1] and "40" in weekday[1] and "Asia/Shanghai" in weekday[1]
    weekend = next(a for a in added if a[0] == "scan:weekend")
    assert "10" in weekend[1] and "Asia/Shanghai" in weekend[1]
