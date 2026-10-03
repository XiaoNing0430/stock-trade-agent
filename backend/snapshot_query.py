"""Point-in-time snapshot reads shared by review and portfolio consumers.

The module deliberately contains no network or write path.  Market prices are
strictly same-day; only industry mappings may fall back to an older snapshot.
The storage models are resolved lazily so this module remains importable while
older installations are being migrated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from sqlalchemy import and_, select

CoverageStatus = Literal["exact", "recent_fallback", "historical_fallback", "current_fallback", "unknown"]


@dataclass
class SnapshotCoverage:
    requested_date: str
    resolved_date: str | None = None
    status: CoverageStatus = "unknown"
    degraded: bool = True
    run_status: str | None = None
    coverage_pct: float | None = None
    error_count: int = 0
    missing_codes: list[str] = field(default_factory=list)
    missing_breakdown: dict[str, list[str]] = field(
        default_factory=lambda: {"missing_in_snapshot": [], "missing_degraded": [], "missing_no_snapshot": []}
    )
    suspended_codes: list[str] = field(default_factory=list)
    suspended_no_prev_close: list[str] = field(default_factory=list)
    industry_fallback_days: int | None = None
    provider: str | None = None
    acquisition: str | None = None
    pit_quality: str | None = None

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        aliases = {
            "requested_date": "requestedDate",
            "resolved_date": "resolvedDate",
            "run_status": "runStatus",
            "coverage_pct": "coveragePct",
            "error_count": "errorCount",
            "missing_codes": "missingCodes",
            "missing_breakdown": "missingBreakdown",
            "suspended_codes": "suspendedCodes",
            "suspended_no_prev_close": "suspendedNoPrevClose",
            "industry_fallback_days": "industryFallbackDays",
            "pit_quality": "pitQuality",
        }
        return {aliases.get(key, key): value for key, value in raw.items()}


def _model(storage: Any, *names: str) -> Any:
    for name in names:
        value = getattr(storage, name, None)
        if value is not None:
            return value
    return None


def _field(row: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(row, dict) and name in row:
            return row[name]
        value = getattr(row, name, None)
        if value is not None:
            return value
    return default


def _trading_day_distance(requested: str, resolved: str, trading_dates: list[str] | None = None) -> int:
    """Count observed CN market sessions, falling back to weekdays when unavailable."""
    if requested == resolved:
        return 0
    observed = sorted({item for item in (trading_dates or []) if resolved < item <= requested})
    if observed:
        return len(observed)
    current = date.fromisoformat(resolved)
    end = date.fromisoformat(requested)
    distance = 0
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:
            distance += 1
    return distance


def _industry_status(pit_quality: str | None, distance: int) -> CoverageStatus:
    if pit_quality == "inferred":
        return "historical_fallback"
    if distance == 0:
        return "exact"
    if distance <= 5:
        return "recent_fallback"
    if distance <= 20:
        return "historical_fallback"
    return "current_fallback"


def query_market_snapshots(
    session: Any,
    codes: list[str],
    requested_date: str,
    *,
    storage: Any | None = None,
) -> tuple[dict[str, dict[str, Any]], SnapshotCoverage]:
    """Read raw close snapshots for exactly ``requested_date``.

    Missing rows are never filled from an older date.  Suspended rows retain a
    ``None`` value when no previous close exists and are reported separately.
    """
    if storage is None:
        from backend import storage as storage_module

        storage = storage_module
    model = _model(storage, "MarketCloseSnapshot", "MarketCloseSnapshots", "SnapshotClose")
    run_model = _model(storage, "DataSnapshotRun", "SnapshotRun", "DataSnapshotRuns")
    coverage = SnapshotCoverage(requested_date=requested_date)
    result: dict[str, dict[str, Any]] = {}
    wanted = list(dict.fromkeys(str(code) for code in codes))
    if model is None:
        coverage.missing_codes = wanted
        coverage.missing_breakdown["missing_no_snapshot"] = wanted
        return result, coverage

    rows = session.query(model).filter(model.as_of_date == requested_date, model.code.in_(wanted)).all()
    row_by_code = {str(_field(row, "code")): row for row in rows}
    run = session.query(run_model).filter(run_model.as_of_date == requested_date).first() if run_model else None
    coverage.run_status = str(_field(run, "status") or "no-run")
    coverage.coverage_pct = _field(run, "coverage_pct")
    coverage.error_count = int(_field(run, "error_count", default=0) or 0)
    if not wanted:
        has_usable_run = coverage.run_status in ("complete", "degraded")
        coverage.resolved_date = requested_date if has_usable_run else None
        coverage.status = "exact" if has_usable_run else "unknown"
        coverage.degraded = coverage.run_status != "complete"
        return result, coverage
    for code in wanted:
        row = row_by_code.get(code)
        if row is None:
            coverage.missing_codes.append(code)
            if coverage.run_status == "complete":
                bucket = "missing_in_snapshot"
            elif coverage.run_status == "degraded":
                bucket = "missing_degraded"
            else:
                bucket = "missing_no_snapshot"
            coverage.missing_breakdown[bucket].append(code)
            continue
        trade_status = _field(row, "trade_status", default="trading")
        prev_close = _field(row, "prev_close")
        value = _field(row, "close") if trade_status != "suspended" else prev_close
        result[code] = {
            "code": code,
            "date": requested_date,
            "value": value,
            "close": _field(row, "close"),
            "volume": _field(row, "volume"),
            "amount": _field(row, "amount"),
            "tradeStatus": trade_status,
            "prevClose": prev_close,
            "provider": _field(row, "provider", "source"),
            "acquisition": _field(row, "acquisition"),
        }
        if trade_status == "suspended":
            coverage.suspended_codes.append(code)
            if prev_close is None:
                coverage.suspended_no_prev_close.append(code)
    coverage.resolved_date = requested_date if rows else None
    coverage.status = "exact" if rows else "unknown"
    coverage.degraded = bool(
        coverage.missing_codes or coverage.suspended_no_prev_close or coverage.run_status != "complete"
    )
    coverage.provider = next(
        (str(_field(row, "provider", "source")) for row in rows if _field(row, "provider", "source")), None
    )
    coverage.acquisition = next((str(_field(row, "acquisition")) for row in rows if _field(row, "acquisition")), None)
    return result, coverage


def query_industry_map(
    session: Any,
    codes: list[str],
    requested_date: str,
    *,
    storage: Any | None = None,
    max_trading_days: int = 20,
) -> tuple[dict[str, str], SnapshotCoverage]:
    """Resolve industry mappings using PIT snapshots, then current mapping."""
    if storage is None:
        from backend import storage as storage_module

        storage = storage_module
    model = _model(storage, "IndustryMapSnapshot", "IndustryMapSnapshots", "SnapshotIndustry")
    current_model = _model(storage, "IndustryMap")
    wanted = list(dict.fromkeys(str(code) for code in codes))
    coverage = SnapshotCoverage(requested_date=requested_date)
    mappings: dict[str, str] = {}
    statuses: list[CoverageStatus] = []
    resolved_dates: list[str] = []
    distances: list[int] = []
    qualities: list[str] = []
    market_model = _model(storage, "MarketBar")
    trading_dates: list[str] = []
    if market_model is not None:
        date_rows = (
            session.query(market_model.trade_date)
            .filter(market_model.adjustment == "", market_model.trade_date <= requested_date)
            .distinct()
            .all()
        )
        trading_dates = [str(item[0]) for item in date_rows]
    if model is not None:
        rows = session.query(model).filter(model.as_of_date <= requested_date, model.code.in_(wanted)).all()
        by_code: dict[str, list[Any]] = {}
        for row in rows:
            by_code.setdefault(str(_field(row, "code")), []).append(row)
        for code in wanted:
            candidates = by_code.get(code, [])
            if not candidates:
                continue
            eligible: list[tuple[Any, int]] = []
            for candidate in candidates:
                candidate_date = str(_field(candidate, "as_of_date"))
                candidate_distance = _trading_day_distance(requested_date, candidate_date, trading_dates)
                if candidate_distance <= max_trading_days:
                    eligible.append((candidate, candidate_distance))
            trusted = [
                item
                for item in eligible
                if str(_field(item[0], "pit_quality", default="exact")) in ("exact", "rebuilt")
            ]
            pool = trusted or eligible
            if not pool:
                continue
            row, distance = max(pool, key=lambda item: str(_field(item[0], "as_of_date")))
            resolved = str(_field(row, "as_of_date"))
            name = _field(row, "name", "industry_name")
            if not name:
                continue
            quality = str(_field(row, "pit_quality", default="exact"))
            mappings[code] = str(name)
            status = _industry_status(quality, distance)
            statuses.append(status)
            resolved_dates.append(resolved)
            distances.append(distance)
            qualities.append(quality)
            coverage.provider = coverage.provider or _field(row, "provider", "source")
            coverage.acquisition = coverage.acquisition or _field(row, "acquisition")
    if current_model is not None:
        remaining = [code for code in wanted if code not in mappings]
        if remaining:
            current = session.query(current_model).filter(current_model.code.in_(remaining)).all()
            for row in current:
                name = _field(row, "name", "industry_name")
                if name:
                    mappings[str(_field(row, "code"))] = str(name)
            if current:
                statuses.append("current_fallback")
    coverage.missing_codes = [code for code in wanted if code not in mappings]
    coverage.missing_breakdown["missing_no_snapshot"] = coverage.missing_codes.copy()
    rank = {"exact": 0, "recent_fallback": 1, "historical_fallback": 2, "current_fallback": 3, "unknown": 4}
    if coverage.missing_codes:
        statuses.append("unknown")
    coverage.status = max(statuses, key=rank.__getitem__) if statuses else "unknown"
    coverage.degraded = coverage.status != "exact"
    if "inferred" in qualities:
        coverage.pit_quality = "inferred"
    elif "rebuilt" in qualities:
        coverage.pit_quality = "rebuilt"
    elif qualities:
        coverage.pit_quality = "exact"
    if coverage.status in ("exact", "recent_fallback", "historical_fallback") and resolved_dates:
        coverage.resolved_date = min(resolved_dates)
        coverage.industry_fallback_days = max(distances)
    else:
        coverage.resolved_date = None
        coverage.industry_fallback_days = None
    return mappings, coverage


def load_archived_bars(
    session: Any, codes: list[str], as_of_date: str, *, storage: Any | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Load OHLC rows only for dates proven present in the immutable close archive."""
    if storage is None:
        from backend import storage as storage_module

        storage = storage_module
    wanted = list(dict.fromkeys(str(code) for code in codes))
    if not wanted:
        return {}
    rows = session.execute(
        select(storage.MarketBar, storage.SnapshotClose)
        .join(
            storage.SnapshotClose,
            and_(
                storage.SnapshotClose.code == storage.MarketBar.code,
                storage.SnapshotClose.as_of_date == storage.MarketBar.trade_date,
            ),
        )
        .where(
            storage.MarketBar.adjustment == "",
            storage.MarketBar.code.in_(wanted),
            storage.MarketBar.trade_date <= as_of_date,
        )
        .order_by(storage.MarketBar.code, storage.MarketBar.trade_date)
    ).all()
    out: dict[str, list[dict[str, Any]]] = {code: [] for code in wanted}
    for bar, snap in rows:
        out[str(bar.code)].append(
            {
                "date": bar.trade_date,
                "open": snap.open,
                "high": snap.high,
                "low": snap.low,
                "close": snap.close,
                "volume": snap.volume,
                "amount": snap.amount,
            }
        )
    return out


# Descriptive aliases used by callers that prefer "resolve" terminology.
resolve_market_snapshots = query_market_snapshots
resolve_industry_map = query_industry_map
