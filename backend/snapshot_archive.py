"""Daily point-in-time snapshot archiving from the completed bars ETL batch."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from backend import storage

DEFAULT_COVERAGE_THRESHOLD = 0.95


def archive_daily_snapshot(as_of_date: str, *, codes: list[str] | None = None) -> dict[str, Any]:
    """Archive same-day raw closes and the currently known industry map.

    The function is deliberately idempotent and never backfills an older date
    automatically; historical industry backfill is an explicit API operation.
    """
    target_codes = list(dict.fromkeys(str(c) for c in (codes or _target_codes())))
    bars: dict[str, Any] = {}
    errors = 0
    with storage.SessionLocal() as session:
        stmt = select(storage.MarketBar).where(
            storage.MarketBar.trade_date == as_of_date, storage.MarketBar.adjustment == ""
        )
        if target_codes:
            stmt = stmt.where(storage.MarketBar.code.in_(target_codes))
        rows = session.scalars(stmt).all()
        for row in rows:
            bars[str(row.code)] = row
        previous_rows = session.scalars(
            select(storage.MarketBar)
            .where(storage.MarketBar.adjustment == "", storage.MarketBar.trade_date < as_of_date)
            .order_by(storage.MarketBar.trade_date.desc())
        ).all()
        previous_close: dict[str, float] = {}
        for previous in previous_rows:
            if previous.code not in previous_close and previous.close is not None and (previous.volume or 0) > 0:
                previous_close[str(previous.code)] = float(previous.close)
        industry_rows = session.scalars(select(storage.IndustryMap)).all()

    close_rows: list[dict[str, Any]] = []
    suspended = 0
    for code, row in bars.items():
        volume = float(row.volume) if row.volume is not None else None
        is_suspended = volume is not None and volume <= 0
        suspended += int(is_suspended)
        close_rows.append(
            {
                "code": code,
                "close": row.close,
                "volume": row.volume,
                "amount": row.amount,
                "date": as_of_date,
                "tradeStatus": "suspended" if is_suspended else "trading",
                "prevClose": previous_close.get(code) if is_suspended else None,
                "provider": "eastmoney",
                "acquisition": "realtime",
            }
        )
    industry = [
        {
            "code": row.code,
            "name": row.name,
            "provider": "eastmoney",
            "acquisition": "realtime",
            "pitQuality": "exact",
            "observedDate": as_of_date,
        }
        for row in industry_rows
        if row.name
    ]
    universe = len(target_codes)
    coverage = (len(close_rows) / universe) if universe else 0.0
    status = "complete" if coverage >= DEFAULT_COVERAGE_THRESHOLD and errors == 0 else "degraded"
    storage.save_snapshot_run(as_of_date, status=status, source="eastmoney", completed=True, universe_count=universe, bar_count=len(close_rows), industry_count=len(industry), suspended_count=suspended, error_count=errors, coverage_pct=coverage)
    storage.upsert_snapshot_closes(as_of_date, close_rows)
    storage.upsert_snapshot_industries(as_of_date, industry)
    return {
        "asOfDate": as_of_date,
        "status": status,
        "universeCount": universe,
        "barCount": len(close_rows),
        "industryCount": len(industry),
        "suspendedCount": suspended,
        "errorCount": errors,
        "coveragePct": coverage,
        "capturedAt": datetime.now(UTC).isoformat(),
    }


def _target_codes() -> list[str]:
    with storage.SessionLocal() as session:
        rows = session.scalars(select(storage.MarketBar.code).distinct()).all()
    return [str(code) for code in rows]


def backfill_industry(as_of_date: str, *, reason: str = "", mode: str = "backfill") -> dict[str, Any]:
    if mode == "rebuild":
        raise NotImplementedError("真实历史源未接入，rebuild 暂不可用")
    with storage.SessionLocal() as session:
        rows = session.scalars(select(storage.IndustryMap)).all()
    payload = [{"code": r.code, "name": r.name, "provider": "eastmoney", "acquisition": "backfill", "pitQuality": "inferred", "observedDate": as_of_date} for r in rows if r.name]
    count = storage.upsert_snapshot_industries(as_of_date, payload)
    audit = storage.record_snapshot_audit(as_of_date, payload, mode=mode)
    return {"asOfDate": as_of_date, "mode": mode, "affectedCount": count, "audit": audit, "reason": reason}
