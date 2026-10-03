"""Daily point-in-time snapshot archiving from the completed bars ETL batch."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select

from backend import storage

DEFAULT_COVERAGE_THRESHOLD = 0.95


def _load_archive_inputs(as_of_date: str, target_codes: list[str]) -> tuple[list[Any], list[Any], dict[str, float]]:
    with storage.SessionLocal() as session:
        stmt = select(storage.MarketBar).where(
            storage.MarketBar.trade_date == as_of_date, storage.MarketBar.adjustment == ""
        )
        if target_codes:
            stmt = stmt.where(storage.MarketBar.code.in_(target_codes))
        rows = list(session.scalars(stmt).all())
        previous_rows = session.scalars(
            select(storage.MarketBar)
            .where(storage.MarketBar.adjustment == "", storage.MarketBar.trade_date < as_of_date)
            .order_by(storage.MarketBar.trade_date.desc())
        ).all()
        previous_close: dict[str, float] = {}
        for previous in previous_rows:
            if previous.code not in previous_close and previous.close is not None and (previous.volume or 0) > 0:
                previous_close[str(previous.code)] = float(previous.close)
        industries = list(session.scalars(select(storage.IndustryMap)).all())
    return rows, industries, previous_close


def archive_daily_snapshot(
    as_of_date: str,
    *,
    codes: list[str] | None = None,
    error_count: int = 0,
    captured_on: date | None = None,
) -> dict[str, Any]:
    try:
        return _archive_daily_snapshot(
            as_of_date,
            codes=codes,
            error_count=error_count,
            captured_on=captured_on,
        )
    except Exception as exc:
        try:
            storage.save_snapshot_failure(as_of_date, str(exc))
        except Exception:
            pass
        raise


def _archive_daily_snapshot(
    as_of_date: str,
    *,
    codes: list[str] | None = None,
    error_count: int = 0,
    captured_on: date | None = None,
) -> dict[str, Any]:
    """Archive same-day raw closes and the currently known industry map.

    The function is deliberately idempotent and never backfills an older date
    automatically; historical industry backfill is an explicit API operation.
    """
    target_codes = list(dict.fromkeys(str(c) for c in (codes or _target_codes())))
    rows, industry_rows, previous_close = _load_archive_inputs(as_of_date, target_codes)
    bars = {str(row.code): row for row in rows}

    close_rows: list[dict[str, Any]] = []
    suspended = 0
    for code, row in bars.items():
        volume = float(row.volume) if row.volume is not None else None
        is_suspended = volume is not None and volume <= 0
        suspended += int(is_suspended)
        close_rows.append(
            {
                "code": code,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "amount": row.amount,
                "date": as_of_date,
                "tradeStatus": "suspended" if is_suspended else "trading",
                "prevClose": previous_close.get(code) if is_suspended else None,
                "provider": str(row.source or "unknown"),
                "acquisition": "realtime",
            }
        )
    captured_on = captured_on or datetime.now().astimezone().date()
    industry = (
        [
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
        if captured_on.isoformat() == as_of_date
        else []
    )
    universe = len(target_codes)
    coverage = (len(close_rows) / universe) if universe else 0.0
    status = "complete" if coverage >= DEFAULT_COVERAGE_THRESHOLD and error_count == 0 else "degraded"
    storage.save_snapshot_batch(
        as_of_date=as_of_date,
        close_rows=close_rows,
        industry_rows=industry,
        status=status,
        universe_count=universe,
        suspended_count=suspended,
        error_count=error_count,
        coverage_pct=coverage,
        degraded_reason="etl_errors" if error_count else None,
    )
    return {
        "asOfDate": as_of_date,
        "status": status,
        "universeCount": universe,
        "barCount": len(close_rows),
        "industryCount": len(industry),
        "suspendedCount": suspended,
        "errorCount": error_count,
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
    payload = [
        {
            "code": r.code,
            "name": r.name,
            "provider": "eastmoney",
            "acquisition": "backfill",
            "pitQuality": "inferred",
            "observedDate": as_of_date,
        }
        for r in rows
        if r.name
    ]
    if not payload:
        raise ValueError("当前行业映射为空，请先刷新行业数据")
    result = storage.backfill_industry_snapshot(as_of_date, payload, reason=reason)
    return {"asOfDate": as_of_date, "mode": mode, **result}
