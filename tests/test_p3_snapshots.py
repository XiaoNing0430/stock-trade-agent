from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

import pytest
from backend import bars_etl, plan_review, snapshot_archive, snapshot_query, storage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    storage.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_industry_resolution_is_per_code_and_inferred_never_exact() -> None:
    factory = _session_factory()
    with factory.begin() as session:
        session.add_all(
            [
                storage.SnapshotIndustry(
                    as_of_date="2026-09-18",
                    code="600000",
                    name="银行",
                    provider="eastmoney",
                    acquisition="realtime",
                    pit_quality="exact",
                ),
                storage.SnapshotIndustry(
                    as_of_date="2026-09-18",
                    code="000001",
                    name="金融",
                    provider="eastmoney",
                    acquisition="backfill",
                    pit_quality="inferred",
                ),
                storage.SnapshotIndustry(
                    as_of_date="2026-08-14",
                    code="300001",
                    name="软件",
                    provider="eastmoney",
                    acquisition="realtime",
                    pit_quality="exact",
                ),
                storage.IndustryMap(code="300001", name="计算机"),
            ]
        )
    with factory() as session:
        mapping, coverage = snapshot_query.query_industry_map(
            session, ["600000", "000001", "300001"], "2026-09-18", storage=storage
        )
    assert mapping == {"600000": "银行", "000001": "金融", "300001": "计算机"}
    assert coverage.status == "current_fallback"
    assert coverage.degraded is True


def test_market_snapshot_classifies_missing_and_suspended_without_prev_close() -> None:
    factory = _session_factory()
    with factory.begin() as session:
        session.add(storage.SnapshotRun(as_of_date="2026-09-18", status="degraded", coverage_pct=0.8, error_count=1))
        session.add(
            storage.SnapshotClose(
                as_of_date="2026-09-18", code="600000", close=10, volume=0, trade_status="suspended", prev_close=None
            )
        )
    with factory() as session:
        rows, coverage = snapshot_query.query_market_snapshots(
            session, ["600000", "000001"], "2026-09-18", storage=storage
        )
    assert rows["600000"]["value"] is None
    assert coverage.suspended_no_prev_close == ["600000"]
    assert coverage.missing_breakdown["missing_degraded"] == ["000001"]
    assert coverage.error_count == 1


def test_historical_archive_does_not_label_current_industry_exact(monkeypatch) -> None:
    captured: list[list[dict]] = []

    def capture(**kwargs) -> dict:
        captured.append(kwargs["industry_rows"])
        return {}

    monkeypatch.setattr(snapshot_archive, "_target_codes", lambda: [])
    monkeypatch.setattr(snapshot_archive, "_load_archive_inputs", lambda *_: ([], [], {}))
    monkeypatch.setattr(storage, "save_snapshot_batch", capture)
    snapshot_archive.archive_daily_snapshot("2026-09-18", captured_on=date(2026, 9, 20))
    assert captured == [[]]


def test_review_as_of_date_includes_plans_created_later_that_day() -> None:
    created_ms = int(datetime(2026, 9, 18, 15, 0, tzinfo=plan_review.SHANGHAI).timestamp() * 1000)
    plan = {
        "id": "p1",
        "code": "600000",
        "createdAtMs": created_ms,
        "direction": "buy",
        "entry": 10,
        "stop": 9,
        "target": 12,
        "validity": "长期",
    }
    result = plan_review.review_plans(
        [plan], days=0, fee_rate=0.0015, load_bars=lambda _codes: {"600000": []}, as_of_date="2026-09-18"
    )
    assert result["kpis"]["total"] == 1


def test_snapshot_batch_is_atomic_and_complete_snapshot_is_immutable(monkeypatch) -> None:
    factory = _session_factory()
    monkeypatch.setattr(storage, "SessionLocal", factory)

    with pytest.raises(ValueError):
        storage.save_snapshot_batch(
            as_of_date="2026-09-18",
            close_rows=[
                {"code": "600000", "close": 10, "volume": 100, "date": "2026-09-18"},
                {"code": "000001", "close": "invalid", "volume": 100, "date": "2026-09-18"},
            ],
            industry_rows=[],
            status="complete",
            universe_count=2,
            suspended_count=0,
            error_count=0,
            coverage_pct=1.0,
        )
    with factory() as session:
        assert session.scalar(select(storage.SnapshotRun)) is None
        assert session.scalars(select(storage.SnapshotClose)).all() == []

    storage.save_snapshot_batch(
        as_of_date="2026-09-18",
        close_rows=[{"code": "600000", "close": 10, "volume": 100, "date": "2026-09-18"}],
        industry_rows=[
            {
                "code": "600000",
                "name": "银行",
                "provider": "eastmoney",
                "acquisition": "realtime",
                "pitQuality": "exact",
            }
        ],
        status="complete",
        universe_count=1,
        suspended_count=0,
        error_count=0,
        coverage_pct=1.0,
    )
    repeated = storage.save_snapshot_batch(
        as_of_date="2026-09-18",
        close_rows=[{"code": "600000", "close": 99, "volume": 100, "date": "2026-09-18"}],
        industry_rows=[
            {
                "code": "600000",
                "name": "未来行业",
                "provider": "eastmoney",
                "acquisition": "realtime",
                "pitQuality": "exact",
            }
        ],
        status="complete",
        universe_count=1,
        suspended_count=0,
        error_count=0,
        coverage_pct=1.0,
    )
    assert repeated["idempotent"] is True
    with factory() as session:
        assert session.scalar(select(storage.SnapshotClose.close)) == 10
        assert session.scalar(select(storage.SnapshotIndustry.name)) == "银行"


def test_backfill_a_b_a_appends_audits_and_identical_retry_is_idempotent(monkeypatch) -> None:
    factory = _session_factory()
    monkeypatch.setattr(storage, "SessionLocal", factory)

    def rows(name: str) -> list[dict]:
        return [{"code": "600000", "name": name, "provider": "eastmoney", "acquisition": "backfill"}]

    first = storage.backfill_industry_snapshot("2026-09-18", rows("银行"), reason="first")
    second = storage.backfill_industry_snapshot("2026-09-18", rows("金融"), reason="second")
    third = storage.backfill_industry_snapshot("2026-09-18", rows("银行"), reason="third")
    duplicate = storage.backfill_industry_snapshot("2026-09-18", rows("银行"), reason="duplicate")

    assert [first["idempotent"], second["idempotent"], third["idempotent"]] == [False, False, False]
    assert duplicate["idempotent"] is True
    with factory() as session:
        audits = session.scalars(select(storage.SnapshotAudit).order_by(storage.SnapshotAudit.id)).all()
        assert [row.reason for row in audits] == ["first", "second", "third"]
        assert audits[0].canonical_hash == audits[2].canonical_hash
        assert session.scalar(select(storage.SnapshotIndustry.name)) == "银行"


def test_backfill_affected_count_only_counts_changed_codes(monkeypatch) -> None:
    factory = _session_factory()
    monkeypatch.setattr(storage, "SessionLocal", factory)
    original = [
        {"code": "600000", "name": "银行", "provider": "eastmoney", "acquisition": "backfill"},
        {"code": "000001", "name": "金融", "provider": "eastmoney", "acquisition": "backfill"},
    ]
    changed = [dict(original[0], name="证券"), original[1]]
    storage.backfill_industry_snapshot("2026-09-18", original)
    result = storage.backfill_industry_snapshot("2026-09-18", changed)
    assert result["affectedCount"] == 1


def test_backfill_cannot_overwrite_exact_snapshot(monkeypatch) -> None:
    factory = _session_factory()
    monkeypatch.setattr(storage, "SessionLocal", factory)
    with factory.begin() as session:
        session.add(
            storage.SnapshotIndustry(
                as_of_date="2026-09-18",
                code="600000",
                name="银行",
                provider="eastmoney",
                acquisition="realtime",
                pit_quality="exact",
            )
        )
    with pytest.raises(storage.SnapshotConflictError):
        storage.backfill_industry_snapshot(
            "2026-09-18",
            [{"code": "600000", "name": "未来行业", "provider": "eastmoney", "acquisition": "backfill"}],
        )


def test_snapshot_coverage_api_shape_uses_camel_case() -> None:
    body = snapshot_query.SnapshotCoverage(
        requested_date="2026-09-18",
        resolved_date="2026-09-18",
        run_status="complete",
        coverage_pct=1.0,
        missing_codes=["000001"],
        suspended_no_prev_close=["600000"],
        industry_fallback_days=0,
    ).to_dict()
    assert body["requestedDate"] == "2026-09-18"
    assert body["resolvedDate"] == "2026-09-18"
    assert body["runStatus"] == "complete"
    assert body["coveragePct"] == 1.0
    assert body["missingCodes"] == ["000001"]
    assert body["suspendedNoPrevClose"] == ["600000"]
    assert body["industryFallbackDays"] == 0
    assert "requested_date" not in body


def test_etl_archive_receives_actual_universe_and_failed_code_count(monkeypatch) -> None:
    captured: list[dict] = []

    def fake_run(stats, _force, _fetch) -> None:
        stats.watermark = "2026-09-18"
        stats.target_codes = ["600000", "000001", "300001"]
        stats.failed = ["000001", "000001"]
        stats.rejected = 3
        stats.rejected_codes = ["300001", "300001", "300001"]

    monkeypatch.setattr(bars_etl, "_do_run", fake_run)
    monkeypatch.setattr(snapshot_archive, "archive_daily_snapshot", lambda *args, **kwargs: captured.append(kwargs))
    bars_etl.run_full(fetch=lambda *_: [])
    assert captured == [
        {
            "codes": ["600000", "000001", "300001"],
            "error_count": 2,
        }
    ]


def test_backfill_audit_summary_keeps_counts_hashes_and_bounded_samples(monkeypatch) -> None:
    factory = _session_factory()
    monkeypatch.setattr(storage, "SessionLocal", factory)
    original = [
        {"code": f"{index:06d}", "name": f"行业{index}", "provider": "eastmoney", "acquisition": "backfill"}
        for index in range(150)
    ]
    changed = [dict(row, name=f"新行业{index}") for index, row in enumerate(original)]
    storage.backfill_industry_snapshot("2026-09-18", original, reason="initial")
    storage.backfill_industry_snapshot("2026-09-18", changed, reason="changed")

    with factory() as session:
        audit = session.scalars(select(storage.SnapshotAudit).order_by(storage.SnapshotAudit.id.desc())).first()
        assert audit is not None
        assert audit.before_summary is not None
        summary = audit.after_summary
        assert summary is not None
        assert summary["affectedCount"] == 150
        assert summary["affectedCodesHash"].startswith("sha256:")
        assert len(summary["affectedCodesSample"]) == 100
        assert summary["nameChangesCount"] == 150
        assert summary["nameChangesHash"].startswith("sha256:")
        assert len(summary["nameChangesSample"]) == 50
        assert summary["truncated"] is True
        assert len(json.dumps(summary, ensure_ascii=False).encode("utf-8")) <= 64 * 1024


def test_review_as_of_date_uses_snapshot_path_and_returns_snapshot_meta(monkeypatch) -> None:
    from backend import app as app_module
    from fastapi.testclient import TestClient

    coverage = snapshot_query.SnapshotCoverage(
        requested_date="2026-09-18",
        resolved_date="2026-09-18",
        status="exact",
        degraded=False,
        run_status="complete",
        coverage_pct=1.0,
    )
    seen: list[str] = []

    def snapshot_loader(as_of_date: str):
        seen.append(as_of_date)
        return (lambda _codes: {}), {"coverage": coverage}

    monkeypatch.setattr(app_module, "_snapshot_loader", snapshot_loader)
    monkeypatch.setattr(
        app_module,
        "_resolve_history_loader",
        lambda: (_ for _ in ()).throw(AssertionError("historical request must not use live history")),
    )
    monkeypatch.setattr(app_module, "get_workspace", lambda *args, **kwargs: {"plans": []})
    monkeypatch.setattr(
        plan_review,
        "review_plans",
        lambda *args, **kwargs: {"kpis": {"total": 0}, "groups": {}, "items": []},
    )
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/plans/review", params={"asOfDate": "2026-09-18"})
    assert response.status_code == 200, response.text
    assert seen == ["2026-09-18"]
    assert response.json()["snapshot"]["requestedDate"] == "2026-09-18"
    assert response.json()["snapshot"]["runStatus"] == "complete"


def test_snapshot_backfill_rebuild_is_501_without_writing_audit(monkeypatch) -> None:
    from backend import app as app_module
    from fastapi.testclient import TestClient

    called: list[bool] = []
    monkeypatch.setattr(
        snapshot_archive,
        "backfill_industry",
        lambda *args, **kwargs: called.append(True),
    )
    with TestClient(app_module.create_app()) as client:
        response = client.post(
            "/api/snapshots/industry",
            json={"asOfDate": "2026-09-18", "mode": "rebuild", "confirm": True},
        )
    assert response.status_code == 501
    assert called == []


def test_market_degraded_run_is_same_day_exact_without_price_fallback() -> None:
    factory = _session_factory()
    with factory.begin() as session:
        session.add(storage.SnapshotRun(as_of_date="2026-09-18", status="degraded", coverage_pct=0.5))
        session.add(
            storage.SnapshotClose(
                as_of_date="2026-09-18",
                code="600000",
                close=10,
                volume=100,
                trade_status="trading",
            )
        )
    with factory() as session:
        rows, coverage = snapshot_query.query_market_snapshots(
            session,
            ["600000", "000001"],
            "2026-09-18",
            storage=storage,
        )
    assert rows["600000"]["value"] == 10
    assert "000001" not in rows
    assert coverage.status == "exact"
    assert coverage.resolved_date == "2026-09-18"
    assert coverage.degraded is True


def test_industry_resolution_uses_newer_inferred_over_expired_exact() -> None:
    factory = _session_factory()
    with factory.begin() as session:
        session.add_all(
            [
                storage.SnapshotIndustry(
                    as_of_date="2026-07-01",
                    code="600000",
                    name="旧行业",
                    provider="eastmoney",
                    acquisition="realtime",
                    pit_quality="exact",
                ),
                storage.SnapshotIndustry(
                    as_of_date="2026-09-18",
                    code="600000",
                    name="回填行业",
                    provider="eastmoney",
                    acquisition="backfill",
                    pit_quality="inferred",
                ),
            ]
        )
    with factory() as session:
        mapping, coverage = snapshot_query.query_industry_map(
            session,
            ["600000"],
            "2026-09-18",
            storage=storage,
        )
    assert mapping == {"600000": "回填行业"}
    assert coverage.status == "historical_fallback"
    assert coverage.resolved_date == "2026-09-18"
    assert coverage.industry_fallback_days == 0


def test_review_days_window_includes_entire_boundary_date() -> None:
    boundary = int(datetime(2026, 8, 19, 0, 0, tzinfo=plan_review.SHANGHAI).timestamp() * 1000)
    plan = {
        "id": "boundary",
        "code": "600000",
        "createdAtMs": boundary,
        "direction": "buy",
        "entry": 10,
        "stop": 9,
        "target": 12,
        "validity": "长期",
    }
    result = plan_review.review_plans(
        [plan],
        days=30,
        fee_rate=0.0015,
        load_bars=lambda _codes: {"600000": []},
        as_of_date="2026-09-18",
    )
    assert result["kpis"]["total"] == 1


def test_concurrent_identical_backfill_writes_one_audit(monkeypatch, tmp_path) -> None:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'snapshots.db'}",
        connect_args={"check_same_thread": False},
    )
    storage.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(storage, "SessionLocal", factory)
    rows = [{"code": "600000", "name": "银行", "provider": "eastmoney", "acquisition": "backfill"}]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda reason: storage.backfill_industry_snapshot("2026-09-18", rows, reason=reason),
                ["first", "second"],
            )
        )

    assert sorted(result["idempotent"] for result in results) == [False, True]
    with factory() as session:
        assert len(session.scalars(select(storage.SnapshotAudit)).all()) == 1


def test_archive_failure_records_failed_run_and_retry_can_complete(monkeypatch) -> None:
    factory = _session_factory()
    monkeypatch.setattr(storage, "SessionLocal", factory)
    monkeypatch.setattr(snapshot_archive, "_target_codes", lambda: ["600000"])
    attempts = {"count": 0}

    class Bar:
        code = "600000"
        open = 9.5
        high = 10.5
        low = 9.0
        close = 10.0
        volume = 100.0
        amount = 1000.0
        source = "eastmoney"

    def load_inputs(*_args):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("archive input failed")
        return [Bar()], [], {}

    monkeypatch.setattr(snapshot_archive, "_load_archive_inputs", load_inputs)
    with pytest.raises(RuntimeError, match="archive input failed"):
        snapshot_archive.archive_daily_snapshot("2026-09-18", captured_on=date(2026, 9, 18))
    with factory() as session:
        failed = session.get(storage.SnapshotRun, "2026-09-18")
        assert failed is not None
        assert failed.status == "failed"
        assert failed.coverage_pct is None

    result = snapshot_archive.archive_daily_snapshot("2026-09-18", captured_on=date(2026, 9, 18))
    assert result["status"] == "complete"
    with factory() as session:
        completed = session.get(storage.SnapshotRun, "2026-09-18")
        assert completed is not None
        assert completed.status == "complete"
        assert completed.coverage_pct == 1.0


def test_empty_code_set_still_reports_same_day_run_coverage() -> None:
    factory = _session_factory()
    with factory.begin() as session:
        session.add(storage.SnapshotRun(as_of_date="2026-09-18", status="complete", coverage_pct=1.0))
    with factory() as session:
        rows, coverage = snapshot_query.query_market_snapshots(
            session,
            [],
            "2026-09-18",
            storage=storage,
        )
    assert rows == {}
    assert coverage.status == "exact"
    assert coverage.resolved_date == "2026-09-18"
    assert coverage.run_status == "complete"
    assert coverage.degraded is False


def test_portfolio_as_of_date_uses_snapshot_path_and_returns_both_coverages(monkeypatch) -> None:
    from backend import app as app_module
    from fastapi.testclient import TestClient

    factory = _session_factory()
    monkeypatch.setattr(storage, "SessionLocal", factory)
    market_coverage = snapshot_query.SnapshotCoverage(
        requested_date="2026-09-18",
        resolved_date="2026-09-18",
        status="exact",
        degraded=False,
        run_status="complete",
        coverage_pct=1.0,
    )
    seen: list[str] = []

    def snapshot_loader(as_of_date: str):
        seen.append(as_of_date)
        return (lambda _codes: {}), {"coverage": market_coverage}

    monkeypatch.setattr(app_module, "_snapshot_loader", snapshot_loader)
    monkeypatch.setattr(
        app_module,
        "_resolve_history_loader",
        lambda: (_ for _ in ()).throw(AssertionError("historical request must not use live history")),
    )
    monkeypatch.setattr(app_module, "get_workspace", lambda *args, **kwargs: {"plans": [], "watchlist": []})
    monkeypatch.setattr(app_module, "get_workspace_settings", lambda *_args, **_kwargs: {})
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/portfolio/risk", params={"asOfDate": "2026-09-18"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert seen == ["2026-09-18"]
    assert body["snapshot"]["market"]["requestedDate"] == "2026-09-18"
    assert body["snapshot"]["industry"]["requestedDate"] == "2026-09-18"


def test_as_of_date_rejects_non_trading_and_future_dates() -> None:
    from backend import app as app_module
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as weekend:
        app_module._validated_as_of("2026-09-20")
    assert weekend.value.status_code == 422
    with pytest.raises(HTTPException) as future:
        app_module._validated_as_of("9999-01-01")
    assert future.value.status_code == 422


def test_archived_bars_use_immutable_snapshot_ohlc(monkeypatch) -> None:
    factory = _session_factory()
    with factory.begin() as session:
        session.add(
            storage.MarketBar(
                code="600000",
                trade_date="2026-09-18",
                adjustment="",
                open=90,
                high=99,
                low=80,
                close=95,
                volume=999,
                amount=9999,
            )
        )
        session.add(
            storage.SnapshotClose(
                as_of_date="2026-09-18",
                code="600000",
                open=10,
                high=12,
                low=9,
                close=11,
                volume=100,
                amount=1000,
                trade_status="trading",
            )
        )
    with factory() as session:
        bars = snapshot_query.load_archived_bars(session, ["600000"], "2026-09-18", storage=storage)
    assert bars["600000"] == [
        {
            "date": "2026-09-18",
            "open": 10,
            "high": 12,
            "low": 9,
            "close": 11,
            "volume": 100,
            "amount": 1000,
        }
    ]


def test_snapshot_loader_does_not_fallback_when_requested_day_is_missing(monkeypatch) -> None:
    from backend import app as app_module

    factory = _session_factory()
    monkeypatch.setattr(storage, "SessionLocal", factory)
    with factory.begin() as session:
        session.add(storage.SnapshotRun(as_of_date="2026-09-18", status="degraded", coverage_pct=0.0))
        session.add(
            storage.MarketBar(
                code="600000",
                trade_date="2026-09-17",
                adjustment="",
                open=10,
                high=11,
                low=9,
                close=10,
                volume=100,
            )
        )
        session.add(
            storage.SnapshotClose(
                as_of_date="2026-09-17",
                code="600000",
                close=10,
                volume=100,
                trade_status="trading",
            )
        )
    load, state = app_module._snapshot_loader("2026-09-18")
    assert load(["600000"]) == {}
    assert state["coverage"].missing_codes == ["600000"]


def test_industry_quality_priority_prefers_recent_exact_over_same_day_inferred() -> None:
    factory = _session_factory()
    with factory.begin() as session:
        session.add_all(
            [
                storage.SnapshotIndustry(
                    as_of_date="2026-09-14",
                    code="600000",
                    name="可信行业",
                    provider="eastmoney",
                    acquisition="realtime",
                    pit_quality="exact",
                ),
                storage.SnapshotIndustry(
                    as_of_date="2026-09-18",
                    code="600000",
                    name="回填行业",
                    provider="eastmoney",
                    acquisition="backfill",
                    pit_quality="inferred",
                ),
            ]
        )
    with factory() as session:
        mapping, coverage = snapshot_query.query_industry_map(
            session,
            ["600000"],
            "2026-09-18",
            storage=storage,
        )
    assert mapping == {"600000": "可信行业"}
    assert coverage.status == "recent_fallback"
    assert coverage.pit_quality == "exact"


def test_industry_distance_uses_observed_market_sessions_not_weekdays() -> None:
    factory = _session_factory()
    with factory.begin() as session:
        session.add(
            storage.SnapshotIndustry(
                as_of_date="2026-09-30",
                code="600000",
                name="银行",
                provider="eastmoney",
                acquisition="realtime",
                pit_quality="exact",
            )
        )
        for trade_date in ("2026-09-30", "2026-10-09"):
            session.add(
                storage.MarketBar(
                    code="600000",
                    trade_date=trade_date,
                    adjustment="",
                    close=10,
                    volume=100,
                )
            )
    with factory() as session:
        _mapping, coverage = snapshot_query.query_industry_map(
            session,
            ["600000"],
            "2026-10-09",
            storage=storage,
        )
    assert coverage.industry_fallback_days == 1
    assert coverage.status == "recent_fallback"


def test_failed_and_no_run_missing_codes_are_not_classified_as_degraded() -> None:
    factory = _session_factory()
    with factory.begin() as session:
        session.add(storage.SnapshotRun(as_of_date="2026-09-18", status="failed", coverage_pct=None))
    with factory() as session:
        _rows, failed = snapshot_query.query_market_snapshots(
            session,
            ["600000"],
            "2026-09-18",
            storage=storage,
        )
        _rows, no_run = snapshot_query.query_market_snapshots(
            session,
            ["600000"],
            "2026-09-17",
            storage=storage,
        )
    assert failed.run_status == "failed"
    assert failed.missing_breakdown["missing_no_snapshot"] == ["600000"]
    assert failed.missing_breakdown["missing_degraded"] == []
    assert no_run.run_status == "no-run"
    assert no_run.missing_breakdown["missing_no_snapshot"] == ["600000"]


def test_exact_archive_replaces_inferred_same_day_and_clears_previous_error(monkeypatch) -> None:
    factory = _session_factory()
    monkeypatch.setattr(storage, "SessionLocal", factory)
    with factory.begin() as session:
        session.add(
            storage.SnapshotRun(
                as_of_date="2026-09-18",
                status="failed",
                coverage_pct=None,
                error="previous failure",
            )
        )
        session.add(
            storage.SnapshotIndustry(
                as_of_date="2026-09-18",
                code="600000",
                name="回填行业",
                provider="eastmoney",
                acquisition="backfill",
                pit_quality="inferred",
            )
        )
    storage.save_snapshot_batch(
        as_of_date="2026-09-18",
        close_rows=[{"code": "600000", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100}],
        industry_rows=[
            {
                "code": "600000",
                "name": "可信行业",
                "provider": "eastmoney",
                "acquisition": "realtime",
                "pitQuality": "exact",
            }
        ],
        status="complete",
        universe_count=1,
        suspended_count=0,
        error_count=0,
        coverage_pct=1.0,
    )
    with factory() as session:
        run = session.get(storage.SnapshotRun, "2026-09-18")
        industry = session.scalar(select(storage.SnapshotIndustry))
        assert run is not None and run.error is None
        assert industry is not None
        assert industry.name == "可信行业"
        assert industry.pit_quality == "exact"
