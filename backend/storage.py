from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from redis import Redis
from sqlalchemy import JSON, DateTime, Float, Integer, String, UniqueConstraint, create_engine, delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from backend.settings import get_settings


class Base(DeclarativeBase):
    pass


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("workspace_id", "code", name="uq_watchlist_workspace_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    code: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


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
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 交易对关联：仅 sell 使用，指向同 workspace 内 buy 计划 id；与 trade_plans.id 主键同宽 String(96)
    related_plan: Mapped[str | None] = mapped_column(
        String(96), nullable=True, comment="交易对关联：sell→buy 计划 id（仅 sell 使用）"
    )
    # 离场模式枚举 race|sell_priority|sell_stop_only|sell_only；NULL≡race（先到先平）
    exit_mode: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="交易对离场模式 race|sell_priority|sell_stop_only|sell_only；NULL≡race"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(256))
    message: Mapped[str] = mapped_column(String(2000))
    read: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


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
    mode: Mapped[str] = mapped_column(String(16), default="classic")
    lookback: Mapped[int] = mapped_column(Integer, default=120)
    settlement_days: Mapped[int] = mapped_column(Integer, default=1)
    slippage_bps: Mapped[float] = mapped_column(Float, default=5)
    schedule: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="草稿")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_backtest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class Strategy(Base):
    """通用策略（双均线/DCA/MACD 等非网格类型）。网格继续使用 GridStrategy。"""

    __tablename__ = "strategies"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    strategy_type: Mapped[str] = mapped_column(String(24), index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    capital: Mapped[float] = mapped_column(Float)
    fee_bps: Mapped[float] = mapped_column(Float, default=3)
    schedule: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="启用")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_backtest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class StrategyBacktest(Base):
    """通用策略回测记录。"""

    __tablename__ = "strategy_backtests"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(96), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    code: Mapped[str] = mapped_column(String(32), index=True)
    strategy_type: Mapped[str] = mapped_column(String(24), index=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    trade_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)


class MarketBar(Base):
    __tablename__ = "market_bars"
    __table_args__ = (UniqueConstraint("code", "trade_date", "adjustment", name="uq_market_bars_code_date_adjustment"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    trade_date: Mapped[str] = mapped_column(String(16), index=True)
    adjustment: Mapped[str] = mapped_column(String(16), default="qfq")
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="Tencent public quote API")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ScreenerScanConfig(Base):
    """策略定时扫描配置（策略本体是包内 JSON，用户状态落库）。"""

    __tablename__ = "screener_scan_configs"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    enabled: Mapped[bool] = mapped_column(default=False)
    mode: Mapped[str] = mapped_column(String(8), default="quick")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_hits: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    last_new_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class ScreenerScanHistory(Base):
    """扫描运行摘要（FR-12）：仅计数不存明细，全表滚动 500 行。"""

    __tablename__ = "screener_scan_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(96), index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    status: Mapped[str] = mapped_column(String(16))
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[str] = mapped_column(String(16), default="")


class WorkspaceSettings(Base):
    __tablename__ = "workspace_settings"

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class WorkspaceState(Base):
    __tablename__ = "workspace_state"

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class IndustryMap(Base):
    """行业映射持久层（组合风险视图 Task 2）：全市场 code→行业（东财 f100），后台每日刷新。

    name 存原始 f100 字符串；行业缺失（空/缺）的行不落库——消费侧对未命中统一走"未知"桶。
    """

    __tablename__ = "industry_map"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def initialize_storage() -> None:
    # 注意：正式迁移走 Alembic（backend/migrations/），此处仅兼容历史部署。
    # 新部署通过 python -m alembic upgrade head 建表，此兜底逻辑对已迁移库无副作用。
    Base.metadata.create_all(engine)
    # Lightweight forward migration for instances created before grid scheduling existed.
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE grid_strategies ADD COLUMN IF NOT EXISTS mode VARCHAR(16) NOT NULL DEFAULT 'classic'")
        )
        connection.execute(
            text("ALTER TABLE grid_strategies ADD COLUMN IF NOT EXISTS lookback INTEGER NOT NULL DEFAULT 120")
        )
        connection.execute(
            text("ALTER TABLE grid_strategies ADD COLUMN IF NOT EXISTS settlement_days INTEGER NOT NULL DEFAULT 1")
        )
        connection.execute(
            text(
                "ALTER TABLE grid_strategies ADD COLUMN IF NOT EXISTS slippage_bps DOUBLE PRECISION NOT NULL DEFAULT 5"
            )
        )
        connection.execute(text("ALTER TABLE grid_strategies ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMPTZ"))
        connection.execute(text("ALTER TABLE grid_strategies ADD COLUMN IF NOT EXISTS last_backtest_at TIMESTAMPTZ"))
        connection.execute(text("ALTER TABLE grid_strategies ADD COLUMN IF NOT EXISTS latest_metrics JSONB"))


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
        "source": plan.source,
        "relatedPlan": plan.related_plan,
        "exitMode": plan.exit_mode,
        "createdAt": plan.created_at.astimezone().strftime("%H:%M"),
        "createdAtMs": int(plan.created_at.timestamp() * 1000),
    }


def _alert_dict(alert: Alert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "kind": alert.kind,
        "title": alert.title,
        "message": alert.message,
        "time": alert.created_at.astimezone().strftime("%H:%M"),
        "read": alert.read,
        "createdAtMs": int(alert.created_at.timestamp() * 1000),
    }


def get_workspace_revision(workspace_id: str = "default") -> int:
    with SessionLocal() as session:
        row = session.get(WorkspaceState, workspace_id)
        return int(row.revision) if row else 0


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
        return {
            "watchlist": watchlist,
            "plans": [_plan_dict(plan) for plan in plans],
            "alerts": [_alert_dict(alert) for alert in alerts],
            "revision": get_workspace_revision(workspace_id),
        }


DEFAULT_WORKSPACE_SETTINGS = {
    "workspaceName": "个人工作区",
    "defaultCapital": 100000,
    "monitorEnabled": True,
    "realtimeSource": "tencent",
    "historySource": "tencent",
    "screenerSource": "tencent",
    "fundamentalSource": "eastmoney",
    "fallbackEnabled": True,
    "refreshInterval": 15,
    "cacheSeconds": 8,
    "timeoutSeconds": 10,
    "retryCount": 1,
    "conflictPolicy": "server",
    "notifyDesktopAlert": True,
    "notifyDesktopSystem": False,
    # 交易辅助 4 键：风险%/盈亏比/止损模式/单票仓位上限
    "riskPerTradePct": 1.0,
    "rrRatio": 2.0,
    "stopMode": "atr",
    "positionCapPct": 25,
    # 组合风险视图：总仓位上限（敞口卡"上限对比"分母与 >100% 提示锚，范围 20..300）
    "totalPositionCapPct": 100,
}


def _normalize_workspace_settings(payload: dict[str, Any]) -> dict[str, Any]:
    allowed_sources = {"tencent", "eastmoney", "akshare", "tushare", "mock_us"}
    data = {
        **DEFAULT_WORKSPACE_SETTINGS,
        **{key: value for key, value in payload.items() if key in DEFAULT_WORKSPACE_SETTINGS},
    }
    for key in ("realtimeSource", "historySource", "screenerSource", "fundamentalSource"):
        if data[key] not in allowed_sources:
            data[key] = "tencent"
    data["workspaceName"] = str(data["workspaceName"]).strip()[:64] or DEFAULT_WORKSPACE_SETTINGS["workspaceName"]
    data["defaultCapital"] = max(1000, min(float(data["defaultCapital"]), 100000000))
    data["refreshInterval"] = max(5, min(int(data["refreshInterval"]), 300))
    data["cacheSeconds"] = max(2, min(int(data["cacheSeconds"]), 300))
    data["timeoutSeconds"] = max(2, min(int(data["timeoutSeconds"]), 60))
    data["retryCount"] = max(0, min(int(data["retryCount"]), 5))
    data["conflictPolicy"] = (
        data["conflictPolicy"] if data["conflictPolicy"] in {"server", "local", "ask"} else "server"
    )
    data["fallbackEnabled"] = bool(data["fallbackEnabled"])
    data["monitorEnabled"] = bool(data["monitorEnabled"])
    data["notifyDesktopAlert"] = bool(data["notifyDesktopAlert"])
    data["notifyDesktopSystem"] = bool(data["notifyDesktopSystem"])
    # 交易辅助 4 键越界回退默认值（同现有 source 校验模式）
    data["riskPerTradePct"] = max(0.1, min(float(data["riskPerTradePct"]), 5.0))
    data["rrRatio"] = max(1.0, min(float(data["rrRatio"]), 10.0))
    data["stopMode"] = data["stopMode"] if data["stopMode"] in {"atr", "ma20"} else "atr"
    data["positionCapPct"] = max(5.0, min(float(data["positionCapPct"]), 100.0))
    # 组合风险视图：总仓位上限 int 化 + clamp（照 defaultCapital 行式）
    data["totalPositionCapPct"] = max(20, min(int(data["totalPositionCapPct"]), 300))
    return data


def validate_plan_links(plans_payload: list[dict[str, Any]]) -> str | None:
    """交易对关联写路径校验（spec §3 规则）。None=通过；返回中文错误串即 422 detail。

    规则：exitMode 若设置须落四值白名单（整表校验，不限 sell；留空≡race）；
    仅 sell 可携带 relatedPlan；目标须存在、为 buy、workspace 内、非归档；
    禁自引用；同 code；一 buy 至多被一 sell 关联。悬空（目标已删）消息含"请先解除关联"
    指引；悬空数据的引擎侧容错（孤儿 + degraded 标注）由回放任务负责，不在此处。
    """
    # 评审 I-1（fix round 1）：exitMode 白名单先跑，杜绝任意串落库与超长 500 兜底
    exit_modes = {"race", "sell_priority", "sell_stop_only", "sell_only"}
    for item in plans_payload:
        mode = item.get("exitMode")
        if mode and str(mode) not in exit_modes:
            sid = str(item.get("id") or "")
            return (
                f"计划「{sid}」的离场模式「{mode}」无效；"
                f"合法值：race / sell_priority / sell_stop_only / sell_only（留空≡race）"
            )
    by_id = {str(item.get("id")): item for item in plans_payload if item.get("id")}
    linked_buy: dict[str, str] = {}  # buy id → 首个关联它的 sell id（一 buy 一 sell）
    for item in plans_payload:
        related = item.get("relatedPlan")
        if not related:
            continue
        sid = str(item.get("id") or "")
        tid = str(related)
        if item.get("direction", "buy") != "sell":
            return f"计划「{sid}」为建仓方向，不能携带关联建仓计划；仅卖出计划可设置 relatedPlan"
        if sid and sid == tid:
            return f"计划「{sid}」不能关联自身"
        target = by_id.get(tid)
        if target is None:
            return f"卖出计划「{sid}」关联的建仓计划「{tid}」不存在；如需删除该建仓计划，请先解除关联"
        if target.get("direction", "buy") != "buy":
            return f"卖出计划「{sid}」只能关联建仓（buy）计划，「{tid}」方向为 {target.get('direction')}"
        if target.get("status") == "已归档":
            return f"卖出计划「{sid}」关联的建仓计划「{tid}」已归档；请先解除关联或改关联未归档的建仓计划"
        if str(target.get("code") or "") != str(item.get("code") or ""):
            return f"卖出计划「{sid}」与关联建仓计划「{tid}」的证券代码不一致，不能跨代码关联"
        owner = linked_buy.get(tid)
        if owner is not None:
            return f"建仓计划「{tid}」已被卖出计划「{owner}」关联，不能被「{sid}」重复关联；如需换绑请先解除原关联"
        linked_buy[tid] = sid
    return None


def get_workspace_settings(workspace_id: str = "default") -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(WorkspaceSettings, workspace_id)
        return _normalize_workspace_settings(row.data if row else {})


def save_workspace_settings(payload: dict[str, Any], workspace_id: str = "default") -> dict[str, Any]:
    data = _normalize_workspace_settings(payload)
    with SessionLocal.begin() as session:
        row = session.get(WorkspaceSettings, workspace_id)
        if row is None:
            row = WorkspaceSettings(workspace_id=workspace_id, data=data)
            session.add(row)
        else:
            row.data = data
    return data


def _bump_workspace_revision(session, workspace_id: str) -> None:
    row = session.get(WorkspaceState, workspace_id)
    if row is None:
        session.add(WorkspaceState(workspace_id=workspace_id, revision=1))
    else:
        row.revision = int(row.revision) + 1


def save_workspace(payload: dict[str, Any], workspace_id: str = "default") -> dict[str, Any]:
    watchlist = list(dict.fromkeys(str(code) for code in payload.get("watchlist", []) if code))
    with SessionLocal.begin() as session:
        existing_watchlist = session.scalars(
            select(WatchlistItem).where(WatchlistItem.workspace_id == workspace_id)
        ).all()
        for watch_item in existing_watchlist:
            session.delete(watch_item)
        session.flush()  # 确保 DELETE 先执行，避免 INSERT 撞唯一约束
        session.add_all([WatchlistItem(workspace_id=workspace_id, code=code) for code in watchlist])

        plans_payload = [item for item in payload.get("plans", []) if item.get("id") and item.get("code")]
        plan_ids = {item["id"] for item in plans_payload}
        for existing_plan in session.scalars(select(TradePlan).where(TradePlan.workspace_id == workspace_id)).all():
            if existing_plan.id not in plan_ids:
                session.delete(existing_plan)
        for item in plans_payload:
            if not item.get("id") or not item.get("code"):
                continue
            plan = session.get(TradePlan, item["id"])
            if plan is None:
                plan = TradePlan(
                    id=item["id"],
                    workspace_id=workspace_id,
                    code=item["code"],
                    direction=item.get("direction", "buy"),
                    entry=0,
                    stop=0,
                    target=0,
                    capital=0,
                    position=0,
                    validity="本周内",
                )
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
            plan.source = item.get("source") or None
            plan.related_plan = item.get("relatedPlan") or None
            plan.exit_mode = item.get("exitMode") or None

        alerts_payload = [item for item in payload.get("alerts", []) if item.get("id")]
        alert_ids = {item["id"] for item in alerts_payload}
        for existing_alert in session.scalars(select(Alert).where(Alert.workspace_id == workspace_id)).all():
            if existing_alert.id not in alert_ids:
                session.delete(existing_alert)
        for item in alerts_payload:
            alert = session.get(Alert, item["id"])
            if alert is None:
                alert = Alert(
                    id=item["id"],
                    workspace_id=workspace_id,
                    kind=item.get("kind", "info"),
                    title=item.get("title", "提醒"),
                    message=item.get("message", ""),
                )
                session.add(alert)
            alert.workspace_id = workspace_id
            alert.kind = item.get("kind", "info")
            alert.title = item.get("title", "提醒")
            alert.message = item.get("message", "")
            alert.read = bool(item.get("read", False))
        _bump_workspace_revision(session, workspace_id)
    return get_workspace(workspace_id)


def _grid_strategy_dict(strategy: GridStrategy) -> dict[str, Any]:
    return {
        "id": strategy.id,
        "workspaceId": strategy.workspace_id,
        "code": strategy.code,
        "name": strategy.name,
        "lower": strategy.lower,
        "upper": strategy.upper,
        "gridCount": strategy.grid_count,
        "capital": strategy.capital,
        "feeBps": strategy.fee_bps,
        "mode": strategy.mode,
        "lookback": strategy.lookback,
        "settlementDays": strategy.settlement_days,
        "slippageBps": strategy.slippage_bps,
        "schedule": strategy.schedule,
        "status": strategy.status,
        "nextRunAt": strategy.next_run_at.isoformat() if strategy.next_run_at else None,
        "lastBacktestAt": strategy.last_backtest_at.isoformat() if strategy.last_backtest_at else None,
        "latestMetrics": strategy.latest_metrics,
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
        strategy.mode = str(payload.get("mode", "classic"))
        strategy.lookback = int(payload.get("lookback", 120))
        strategy.settlement_days = int(payload.get("settlementDays", 1))
        strategy.slippage_bps = float(payload.get("slippageBps", 5))
        strategy.schedule = str(payload.get("schedule", "manual"))
        strategy.status = str(payload.get("status", "启用"))
    with SessionLocal() as session:
        saved_strategy = session.get(GridStrategy, strategy_id)
        if saved_strategy is None:
            raise RuntimeError(f"网格策略不存在: {strategy_id}")
        return _grid_strategy_dict(saved_strategy)


def list_grid_strategies(workspace_id: str = "default") -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(GridStrategy)
            .where(GridStrategy.workspace_id == workspace_id)
            .order_by(GridStrategy.updated_at.desc())
        ).all()
        return [_grid_strategy_dict(row) for row in rows]


def get_grid_strategy(strategy_id: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        strategy = session.get(GridStrategy, strategy_id)
        return _grid_strategy_dict(strategy) if strategy else None


def delete_grid_strategy(strategy_id: str, workspace_id: str = "default") -> bool:
    with SessionLocal.begin() as session:
        strategy = session.get(GridStrategy, strategy_id)
        if not strategy or strategy.workspace_id != workspace_id:
            return False
        for backtest in session.scalars(select(GridBacktest).where(GridBacktest.strategy_id == strategy_id)).all():
            session.delete(backtest)
        session.delete(strategy)
    return True


def list_scheduled_grid_strategies() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(GridStrategy).where(GridStrategy.status == "启用", GridStrategy.schedule == "daily")
        ).all()
        return [_grid_strategy_dict(row) for row in rows]


def set_grid_next_run(strategy_id: str, next_run_at: datetime | None) -> None:
    with SessionLocal.begin() as session:
        strategy = session.get(GridStrategy, strategy_id)
        if strategy:
            strategy.next_run_at = next_run_at


def load_market_bars(code: str, adjustment: str = "qfq", limit: int = 240) -> list[dict[str, Any]]:
    """从本地 market_bars 表读取历史日线，按交易日升序返回最近 limit 条。"""
    with SessionLocal() as session:
        rows = session.scalars(
            select(MarketBar)
            .where(MarketBar.code == code, MarketBar.adjustment == adjustment)
            .order_by(MarketBar.trade_date.desc())
            .limit(limit)
        ).all()
        if not rows:
            return []
        return sorted(
            [
                {
                    "date": row.trade_date,
                    "open": row.open,
                    "high": row.high,
                    "low": row.low,
                    "close": row.close,
                    "volume": row.volume,
                    "amount": row.amount,
                    "fetchedAt": row.fetched_at.isoformat() if row.fetched_at else None,
                }
                for row in rows
            ],
            key=lambda r: r["date"],
        )


def save_market_bars(code: str, bars: list[dict[str, Any]], adjustment: str = "qfq") -> str | None:
    latest_date = None
    with SessionLocal.begin() as session:
        for bar in bars:
            trade_date = str(bar.get("date") or "")
            if not trade_date:
                continue
            latest_date = trade_date
            row = session.scalars(
                select(MarketBar).where(
                    MarketBar.code == code, MarketBar.trade_date == trade_date, MarketBar.adjustment == adjustment
                )
            ).first()
            if row is None:
                row = MarketBar(code=code, trade_date=trade_date, adjustment=adjustment)
                session.add(row)
            for field in ("open", "high", "low", "close", "volume", "amount"):
                value = bar.get(field)
                setattr(row, field, float(value) if value is not None else None)
            row.fetched_at = datetime.now(UTC)
    return latest_date


def upsert_market_bars_batch(code: str, bars: list[dict[str, Any]], adjustment: str, session: Any = None) -> int:
    """I10 批量幂等写（ETL 性能预算）：单语句 ON CONFLICT 覆盖；批内同日去重保后者。

    空 bars 拒写——上游空响应不是数据（P0-2 防线）。session 传入则加入调用方事务
    （外层按码 begin_nested 拿 SAVEPOINT 隔离单码失败）；缺省自开自提。返回影响行数。
    """
    if not bars:
        raise ValueError("bars 不能为空——空响应不是数据")
    dedup: dict[str, dict[str, Any]] = {}
    for bar in bars:
        date = str(bar.get("date") or "")
        if date:
            dedup[date] = bar
    if not dedup:
        raise ValueError("bars 无有效交易日——空响应不是数据")
    now = datetime.now(UTC)
    values = [
        {
            "code": code,
            "trade_date": date,
            "adjustment": adjustment,
            "open": bar.get("open"),
            "high": bar.get("high"),
            "low": bar.get("low"),
            "close": bar.get("close"),
            "volume": bar.get("volume"),
            "amount": bar.get("amount"),
            "fetched_at": now,
        }
        for date, bar in dedup.items()
    ]
    stmt = pg_insert(MarketBar).values(values)
    # 影响行数走 RETURNING 计数而非 cursor.rowcount——psycopg3 对 ON CONFLICT 语句报 -1（方言怪癖）
    upsert = stmt.on_conflict_do_update(
        constraint="uq_market_bars_code_date_adjustment",
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
            "amount": stmt.excluded.amount,
            "fetched_at": stmt.excluded.fetched_at,
        },
    ).returning(MarketBar.trade_date)
    if session is not None:
        return len(session.execute(upsert).all())
    with SessionLocal.begin() as own:
        return len(own.execute(upsert).all())


def cleanup_legacy_index_qfq() -> int:
    """A1 一次性清理：指数与个股共享 (code,'qfq') 桶的历史混写行整删（幂等）。

    000001 与平安银行同码歧义不可分，qfq 缓存按需重取，删除代价≈首访一次回源。
    """
    with SessionLocal.begin() as session:
        n = session.execute(
            delete(MarketBar).where(MarketBar.adjustment == "qfq", MarketBar.code.in_(["000001", "399001", "399006"]))
        ).rowcount
    return int(n)


def save_grid_backtest(
    strategy_id: str, code: str, config: dict[str, Any], result: dict[str, Any], workspace_id: str = "default"
) -> None:
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
        strategy = session.get(GridStrategy, strategy_id)
        if strategy:
            strategy.last_backtest_at = datetime.now(UTC)
            strategy.latest_metrics = result["metrics"]


def _strategy_dict(strategy: Strategy) -> dict[str, Any]:
    return {
        "id": strategy.id,
        "workspaceId": strategy.workspace_id,
        "code": strategy.code,
        "name": strategy.name,
        "strategyType": strategy.strategy_type,
        "config": strategy.config,
        "capital": strategy.capital,
        "feeBps": strategy.fee_bps,
        "schedule": strategy.schedule,
        "status": strategy.status,
        "nextRunAt": strategy.next_run_at.isoformat() if strategy.next_run_at else None,
        "lastBacktestAt": strategy.last_backtest_at.isoformat() if strategy.last_backtest_at else None,
        "latestMetrics": strategy.latest_metrics,
        "updatedAt": strategy.updated_at.astimezone().isoformat(),
    }


def save_strategy(payload: dict[str, Any], workspace_id: str = "default") -> dict[str, Any]:
    strategy_id = str(payload["id"])
    with SessionLocal.begin() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy is None:
            strategy = Strategy(
                id=strategy_id,
                workspace_id=workspace_id,
                code=str(payload["code"]),
                name=str(payload.get("name") or f"{payload['code']} 策略"),
                strategy_type=str(payload.get("strategyType", "ma_cross")),
                capital=0,
            )
            session.add(strategy)
        strategy.workspace_id = workspace_id
        strategy.code = str(payload["code"])
        strategy.name = str(payload.get("name") or f"{payload['code']} 策略")
        strategy.strategy_type = str(payload.get("strategyType", "ma_cross"))
        strategy.config = payload.get("config") or {}
        strategy.capital = float(payload.get("capital", 100000))
        strategy.fee_bps = float(payload.get("feeBps", 3))
        strategy.schedule = str(payload.get("schedule", "manual"))
        strategy.status = str(payload.get("status", "启用"))
    with SessionLocal() as session:
        saved_strategy = session.get(Strategy, strategy_id)
        if saved_strategy is None:
            raise RuntimeError(f"策略不存在: {strategy_id}")
        return _strategy_dict(saved_strategy)


def list_strategies(workspace_id: str = "default") -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(Strategy).where(Strategy.workspace_id == workspace_id).order_by(Strategy.updated_at.desc())
        ).all()
        return [_strategy_dict(row) for row in rows]


def get_strategy(strategy_id: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        strategy = session.get(Strategy, strategy_id)
        return _strategy_dict(strategy) if strategy else None


def delete_strategy(strategy_id: str, workspace_id: str = "default") -> bool:
    with SessionLocal.begin() as session:
        strategy = session.get(Strategy, strategy_id)
        if not strategy or strategy.workspace_id != workspace_id:
            return False
        for backtest in session.scalars(
            select(StrategyBacktest).where(StrategyBacktest.strategy_id == strategy_id)
        ).all():
            session.delete(backtest)
        session.delete(strategy)
    return True


def list_scheduled_strategies() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(select(Strategy).where(Strategy.status == "启用", Strategy.schedule == "daily")).all()
        return [_strategy_dict(row) for row in rows]


def set_strategy_next_run(strategy_id: str, next_run_at: datetime | None) -> None:
    with SessionLocal.begin() as session:
        strategy = session.get(Strategy, strategy_id)
        if strategy:
            strategy.next_run_at = next_run_at


def save_strategy_backtest(
    strategy_id: str,
    code: str,
    strategy_type: str,
    config: dict[str, Any],
    result: dict[str, Any],
    workspace_id: str = "default",
) -> None:
    with SessionLocal.begin() as session:
        session.add(
            StrategyBacktest(
                strategy_id=strategy_id,
                workspace_id=workspace_id,
                code=code,
                strategy_type=strategy_type,
                config=config,
                metrics=result["metrics"],
                trade_count=int(result["metrics"]["tradeCount"]),
            )
        )
        strategy = session.get(Strategy, strategy_id)
        if strategy:
            strategy.last_backtest_at = datetime.now(UTC)
            strategy.latest_metrics = result["metrics"]


def _scan_config_dict(cfg: ScreenerScanConfig) -> dict[str, Any]:
    return {
        "strategyId": cfg.id,
        "workspaceId": cfg.workspace_id,
        "enabled": bool(cfg.enabled),
        "mode": cfg.mode,
        "lastRunAt": cfg.last_run_at,
        "lastStatus": cfg.last_status,
        "lastHits": cfg.last_hits,
        "lastNewCount": int(cfg.last_new_count or 0),
    }


def _parse_scan_hits(raw: Any) -> list[dict[str, Any]] | None:
    """last_hits JSON 容错：坏 JSON / 异形结构 → None（视为从未扫描）。"""
    if raw is None:
        return None
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict) and item.get("code")]
    return None


def list_scan_configs() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(select(ScreenerScanConfig).order_by(ScreenerScanConfig.id)).all()
        return [_scan_config_dict(c) for c in rows]


def get_scan_config(strategy_id: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        cfg = session.get(ScreenerScanConfig, strategy_id)
        if cfg is None:
            return None
        d = _scan_config_dict(cfg)
        d["lastHits"] = _parse_scan_hits(cfg.last_hits)
        return d


def list_enabled_scan_configs() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(ScreenerScanConfig).where(ScreenerScanConfig.enabled.is_(True)).order_by(ScreenerScanConfig.id)
        ).all()
        return [_scan_config_dict(c) for c in rows]


def upsert_scan_config(strategy_id: str, enabled: bool, mode: str, workspace_id: str = "default") -> dict[str, Any]:
    with SessionLocal.begin() as session:
        cfg = session.get(ScreenerScanConfig, strategy_id)
        if cfg is None:
            cfg = ScreenerScanConfig(id=strategy_id, workspace_id=workspace_id)
            session.add(cfg)
        cfg.enabled = bool(enabled)
        cfg.mode = mode
        cfg.workspace_id = workspace_id
    return get_scan_config(strategy_id)  # type: ignore[return-value]


def update_scan_state(
    strategy_id: str,
    status: str,
    hits: list[dict[str, Any]],
    run_at: datetime,
    new_count: int = 0,
    require_enabled: bool = True,
) -> bool:
    with SessionLocal.begin() as session:
        cfg = session.get(ScreenerScanConfig, strategy_id)
        if cfg is None:
            return False
        if require_enabled and not cfg.enabled:
            return False
        cfg.last_status = status
        cfg.last_hits = hits
        cfg.last_run_at = run_at
        cfg.last_new_count = int(new_count)
        return True


def insert_scan_history(
    strategy_id: str, status: str, hit_count: int, new_count: int, elapsed_ms: int, trace_id: str
) -> None:
    with SessionLocal.begin() as session:
        session.add(
            ScreenerScanHistory(
                strategy_id=strategy_id,
                status=status,
                hit_count=hit_count,
                new_count=new_count,
                elapsed_ms=elapsed_ms,
                trace_id=trace_id,
            )
        )
        # FR-12 全表滚动 500 行：裁剪历史，仅保留最新 500 条。
        session.execute(
            text(
                "DELETE FROM screener_scan_history WHERE id NOT IN "
                "(SELECT id FROM screener_scan_history ORDER BY id DESC LIMIT 500)"
            )
        )


def list_scan_history(strategy_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        stmt = select(ScreenerScanHistory).order_by(ScreenerScanHistory.id.desc()).limit(limit)
        if strategy_id is not None:
            stmt = stmt.where(ScreenerScanHistory.strategy_id == strategy_id)
        return [
            {
                "id": r.id,
                "strategyId": r.strategy_id,
                "runAt": r.run_at,
                "status": r.status,
                "hitCount": r.hit_count,
                "newCount": r.new_count,
                "elapsedMs": r.elapsed_ms,
                "traceId": r.trace_id,
            }
            for r in session.scalars(stmt).all()
        ]
