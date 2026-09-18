"""Point-in-time snapshot reads shared by review and portfolio consumers.

The module deliberately contains no network or write path.  Market prices are
strictly same-day; only industry mappings may fall back to an older snapshot.
The storage models are resolved lazily so this module remains importable while
older installations are being migrated.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

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
        return asdict(self)


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


def _date_distance(requested: str, resolved: str, dates: list[str]) -> int:
    """Return distance in available trading snapshots, not calendar days."""
    ordered = sorted({str(item) for item in dates if str(item) <= requested})
    try:
        return len(ordered) - 1 - ordered.index(resolved)
    except ValueError:
        return 0


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
    coverage.run_status = _field(run, "status")
    coverage.coverage_pct = _field(run, "coverage_pct")
    coverage.error_count = int(_field(run, "error_count", default=0) or 0)
    for code in wanted:
        row = row_by_code.get(code)
        if row is None:
            coverage.missing_codes.append(code)
            bucket = "missing_no_snapshot" if run is None else (
                "missing_in_snapshot" if coverage.run_status == "complete" else "missing_degraded"
            )
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
    coverage.status = "exact" if rows and not coverage.missing_codes else "historical_fallback"
    coverage.degraded = bool(coverage.missing_codes or coverage.suspended_no_prev_close or coverage.run_status != "complete")
    coverage.provider = next((str(_field(row, "provider", "source")) for row in rows if _field(row, "provider", "source")), None)
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
    if model is not None:
        rows = session.query(model).filter(model.as_of_date <= requested_date, model.code.in_(wanted)).all()
        dates = [str(_field(row, "as_of_date")) for row in rows]
        resolved = max(dates, default=None)
        if resolved is not None:
            distance = _date_distance(requested_date, resolved, dates)
            selected = [row for row in rows if str(_field(row, "as_of_date")) == resolved]
            quality = str(_field(selected[0], "pit_quality", default="exact")) if selected else "exact"
            if distance <= max_trading_days:
                for row in selected:
                    name = _field(row, "name", "industry_name")
                    if name:
                        mappings[str(_field(row, "code"))] = str(name)
                coverage.resolved_date = resolved
                coverage.industry_fallback_days = distance
                coverage.status = _industry_status(quality, distance)
                coverage.degraded = coverage.status != "exact"
                coverage.pit_quality = quality
                coverage.provider = _field(selected[0], "provider", "source")
                coverage.acquisition = _field(selected[0], "acquisition")
    if current_model is not None:
        remaining = [code for code in wanted if code not in mappings]
        if remaining:
            current = session.query(current_model).filter(current_model.code.in_(remaining)).all()
            for row in current:
                name = _field(row, "name", "industry_name")
                if name:
                    mappings[str(_field(row, "code"))] = str(name)
            if current and coverage.status in ("unknown", "current_fallback"):
                coverage.status = "current_fallback"
                coverage.degraded = True
    coverage.missing_codes = [code for code in wanted if code not in mappings]
    coverage.missing_breakdown["missing_no_snapshot"] = coverage.missing_codes.copy()
    if not mappings:
        coverage.status = "unknown"
    elif coverage.status == "unknown":
        coverage.status = "current_fallback"
    return mappings, coverage


# Descriptive aliases used by callers that prefer "resolve" terminology.
resolve_market_snapshots = query_market_snapshots
resolve_industry_map = query_industry_map
