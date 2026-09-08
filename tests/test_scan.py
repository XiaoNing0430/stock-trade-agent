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
