from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from redis import Redis
from sqlalchemy import DateTime, Float, Integer, JSON, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from backend.settings import get_settings


class Base(DeclarativeBase):
    pass


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("workspace_id", "code", name="uq_watchlist_workspace_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    code: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TradePlan(Base):
    __tablename__ = "trade_plans"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    code: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(16))
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    capital: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)
    validity: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[str] = mapped_column(String(32), default="执行中", index=True)
    triggered: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256))
    message: Mapped[str] = mapped_column(String(2000))
    read: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


class GridStrategy(Base):
    __tablename__ = "grid_strategies"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    lower: Mapped[float] = mapped_column(Float)
    upper: Mapped[float] = mapped_column(Float)
    grid_count: Mapped[int] = mapped_column(Integer)
    capital: Mapped[float] = mapped_column(Float)
    fee_bps: Mapped[float] = mapped_column(Float, default=3)
    schedule: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="草稿")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )


class GridBacktest(Base):
    __tablename__ = "grid_backtests"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(96), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    code: Mapped[str] = mapped_column(String(32), index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    trade_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def initialize_storage() -> None:
    Base.metadata.create_all(engine)


def redis_client() -> Redis:
    return Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        db=settings.redis_db,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def storage_status() -> dict[str, bool]:
    database_ok = False
    redis_ok = False
    try:
        with SessionLocal() as session:
            session.execute(select(WatchlistItem.id).limit(1))
            database_ok = True
    except Exception:
        pass
    try:
        redis_client().ping()
        redis_ok = True
    except Exception:
        pass
    return {"database": database_ok, "redis": redis_ok}


def _plan_dict(plan: TradePlan) -> dict[str, Any]:
    return {
        "id": plan.id,
        "code": plan.code,
        "direction": plan.direction,
        "entry": plan.entry,
        "stop": plan.stop,
        "target": plan.target,
        "capital": plan.capital,
        "position": plan.position,
        "validity": plan.validity,
        "note": plan.note,
        "status": plan.status,
        "triggered": plan.triggered or {},
        "createdAt": plan.created_at.astimezone().strftime("%H:%M"),
    }


def _alert_dict(alert: Alert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "kind": alert.kind,
        "title": alert.title,
        "message": alert.message,
        "time": alert.created_at.astimezone().strftime("%H:%M"),
        "read": alert.read,
    }


def get_workspace(workspace_id: str = "default") -> dict[str, Any]:
    with SessionLocal() as session:
        watchlist = session.scalars(
            select(WatchlistItem.code).where(WatchlistItem.workspace_id == workspace_id).order_by(WatchlistItem.id)
        ).all()
        plans = session.scalars(
            select(TradePlan).where(TradePlan.workspace_id == workspace_id).order_by(TradePlan.created_at.desc())
        ).all()
        alerts = session.scalars(
            select(Alert).where(Alert.workspace_id == workspace_id).order_by(Alert.created_at.desc()).limit(100)
        ).all()
        return {"watchlist": watchlist, "plans": [_plan_dict(plan) for plan in plans], "alerts": [_alert_dict(alert) for alert in alerts]}


def save_workspace(payload: dict[str, Any], workspace_id: str = "default") -> dict[str, Any]:
    watchlist = list(dict.fromkeys(str(code) for code in payload.get("watchlist", []) if code))
    with SessionLocal.begin() as session:
        existing_watchlist = session.scalars(select(WatchlistItem).where(WatchlistItem.workspace_id == workspace_id)).all()
        for item in existing_watchlist:
            session.delete(item)
        session.add_all([WatchlistItem(workspace_id=workspace_id, code=code) for code in watchlist])

        plans_payload = [item for item in payload.get("plans", []) if item.get("id") and item.get("code")]
        plan_ids = {item["id"] for item in plans_payload}
        for plan in session.scalars(select(TradePlan).where(TradePlan.workspace_id == workspace_id)).all():
            if plan.id not in plan_ids:
                session.delete(plan)
        for item in plans_payload:
            if not item.get("id") or not item.get("code"):
                continue
            plan = session.get(TradePlan, item["id"])
            if plan is None:
                plan = TradePlan(id=item["id"], workspace_id=workspace_id, code=item["code"], direction=item.get("direction", "buy"), entry=0, stop=0, target=0, capital=0, position=0, validity="本周内")
                session.add(plan)
            plan.workspace_id = workspace_id
            plan.code = item["code"]
            plan.direction = item.get("direction", "buy")
            plan.entry = float(item.get("entry", 0))
            plan.stop = float(item.get("stop", 0))
            plan.target = float(item.get("target", 0))
            plan.capital = float(item.get("capital", 0))
            plan.position = float(item.get("position", 0))
            plan.validity = item.get("validity", "本周内")
            plan.note = item.get("note", "")
            plan.status = item.get("status", "执行中")
            plan.triggered = item.get("triggered") or {}

        alerts_payload = [item for item in payload.get("alerts", []) if item.get("id")]
        alert_ids = {item["id"] for item in alerts_payload}
        for alert in session.scalars(select(Alert).where(Alert.workspace_id == workspace_id)).all():
            if alert.id not in alert_ids:
                session.delete(alert)
        for item in alerts_payload:
            alert = session.get(Alert, item["id"])
            if alert is None:
                alert = Alert(id=item["id"], workspace_id=workspace_id, kind=item.get("kind", "info"), title=item.get("title", "提醒"), message=item.get("message", ""))
                session.add(alert)
            alert.workspace_id = workspace_id
            alert.kind = item.get("kind", "info")
            alert.title = item.get("title", "提醒")
            alert.message = item.get("message", "")
            alert.read = bool(item.get("read", False))
    return get_workspace(workspace_id)


def _grid_strategy_dict(strategy: GridStrategy) -> dict[str, Any]:
    return {
        "id": strategy.id,
        "code": strategy.code,
        "name": strategy.name,
        "lower": strategy.lower,
        "upper": strategy.upper,
        "gridCount": strategy.grid_count,
        "capital": strategy.capital,
        "feeBps": strategy.fee_bps,
        "schedule": strategy.schedule,
        "status": strategy.status,
        "updatedAt": strategy.updated_at.astimezone().isoformat(),
    }


def save_grid_strategy(payload: dict[str, Any], workspace_id: str = "default") -> dict[str, Any]:
    strategy_id = str(payload["id"])
    with SessionLocal.begin() as session:
        strategy = session.get(GridStrategy, strategy_id)
        if strategy is None:
            strategy = GridStrategy(
                id=strategy_id,
                workspace_id=workspace_id,
                code=str(payload["code"]),
                name=str(payload.get("name") or f"{payload['code']} 网格策略"),
                lower=0,
                upper=0,
                grid_count=0,
                capital=0,
            )
            session.add(strategy)
        strategy.workspace_id = workspace_id
        strategy.code = str(payload["code"])
        strategy.name = str(payload.get("name") or f"{payload['code']} 网格策略")
        strategy.lower = float(payload["lower"])
        strategy.upper = float(payload["upper"])
        strategy.grid_count = int(payload["gridCount"])
        strategy.capital = float(payload["capital"])
        strategy.fee_bps = float(payload.get("feeBps", 3))
        strategy.schedule = str(payload.get("schedule", "manual"))
        strategy.status = str(payload.get("status", "启用"))
    with SessionLocal() as session:
        return _grid_strategy_dict(session.get(GridStrategy, strategy_id))


def list_grid_strategies(workspace_id: str = "default") -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(GridStrategy).where(GridStrategy.workspace_id == workspace_id).order_by(GridStrategy.updated_at.desc())
        ).all()
        return [_grid_strategy_dict(row) for row in rows]


def save_grid_backtest(strategy_id: str, code: str, config: dict[str, Any], result: dict[str, Any], workspace_id: str = "default") -> None:
    with SessionLocal.begin() as session:
        session.add(
            GridBacktest(
                strategy_id=strategy_id,
                workspace_id=workspace_id,
                code=code,
                config=config,
                metrics=result["metrics"],
                trade_count=int(result["metrics"]["tradeCount"]),
            )
        )
