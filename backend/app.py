from __future__ import annotations

import logging
import math
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from importlib.util import find_spec
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from backend import bars_etl, minute_path, plan_review, portfolio_risk, redis_cache, snapshot_archive, snapshot_query
from backend.assist.limiter import SlidingWindowLimiter
from backend.assist.service import UpstreamError, build_plan_draft
from backend.data_source import (
    apply_runtime_config,
    classify_code,
    current_cache_ttl,
    facade_state,
    price_limit_ratio,
    recent_stale,
    set_facade,
)
from backend.grid_scheduler import (
    schedule_strategy,
    scheduler,
    start_scheduler,
    stop_scheduler,
    unschedule_strategy,
)
from backend.grid_strategy import backtest_grid, optimize_grid, suggest_grid
from backend.industry_map import get_industry_map, industry_health, last_refresh_complete, refresh_industry_map
from backend.schemas import (
    CustomStrategyIn,
    DeleteOut,
    GridBacktestIn,
    GridBacktestOut,
    GridOptimizeIn,
    GridOptimizeOut,
    GridPreviewIn,
    GridPreviewOut,
    GridStatusPut,
    GridStrategiesOut,
    HealthOut,
    HistoryOut,
    MarketOut,
    MinuteOut,
    PlanDraftIn,
    PlanDraftOut,
    PlanDraftResponse,
    ScreenerOut,
    ScreenerStrategyOut,
    ScreenerStrategyRunIn,
    SettingsOut,
    SettingsPut,
    SettingsPutOut,
    StrategiesOut,
    StrategyBacktestIn,
    StrategyBacktestOut,
    StrategyPreviewIn,
    StrategyPreviewOut,
    StrategyStatusPut,
    WorkspaceOut,
    WorkspacePut,
    WorkspacePutOut,
)
from backend.settings import get_settings
from backend.sources import build_router, get_all_sources_info
from backend.storage import (
    DEFAULT_WORKSPACE_SETTINGS,
    CustomStrategyConflict,
    cleanup_legacy_index_qfq,
    delete_custom_strategy,
    delete_grid_strategy,
    get_custom_strategy,
    get_grid_strategy,
    get_scan_config,
    get_strategy,
    get_workspace,
    get_workspace_revision,
    get_workspace_settings,
    initialize_storage,
    list_custom_strategies,
    list_enabled_scan_configs,
    list_grid_strategies,
    list_scan_configs,
    list_scan_history,
    list_scan_references,
    list_strategies,
    load_market_bars,
    save_grid_backtest,
    save_grid_strategy,
    save_market_bars,
    save_strategy,
    save_strategy_backtest,
    save_workspace,
    save_workspace_settings,
    storage_status,
    upsert_custom_strategy,
    upsert_scan_config,
    validate_plan_links,
)
from backend.storage import (
    delete_strategy as delete_generic_strategy,
)
from backend.strategy_engines import STRATEGY_ENGINES

# 结构化错误码（统一 API 错误契约）
ERR_STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"  # 503 持久化不可用
ERR_WORKSPACE_CONFLICT = "WORKSPACE_CONFLICT"  # 409 工作区版本冲突
ERR_UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"  # 502 行情/排名上游失败
ERR_VALIDATION_ERROR = "VALIDATION_ERROR"  # 422 参数/设置/策略类型
ERR_NOT_FOUND = "NOT_FOUND"  # 404 资源不存在
ERR_RATE_LIMITED = "RATE_LIMITED"  # 429 草案限频
ERR_SCREENER_STRATEGY_CONFLICT = "SCREENER_STRATEGY_CONFLICT"  # 409 自定义策略乐观锁冲突

logger = logging.getLogger("atlas.assist")
review_logger = logging.getLogger("atlas.review")  # 计划复盘独立通道：上游失败 codes 落日志（r3.1）
industry_logger = logging.getLogger("atlas.industry")  # 行业映射后台预热独立通道（Task 2）
screener_logger = logging.getLogger("atlas.screener")  # 自定义选股策略写路径与删除快照通道


def api_error(status_code: int, code: str, message: str, **extras) -> HTTPException:
    """统一错误构造：detail = {"error": message, "code": code, **extras}。"""
    return HTTPException(status_code=status_code, detail={"error": message, "code": code, **extras})


# 请求模型校验失败的中文短句（FastAPI 默认回 detail 列表 + pydantic 英文样板，破坏统一契约）
_VALIDATION_TYPE_LABELS = {
    "missing": "必填项缺失",
    "string_type": "必须是字符串",
    "int_parsing": "必须是整数",
    "int_type": "必须是整数",
    "float_parsing": "必须是数字",
    "float_type": "必须是数字",
    "bool_parsing": "必须是布尔值",
    "bool_type": "必须是布尔值",
    "list_type": "必须是数组",
    "dict_type": "必须是对象",
    "string_too_long": "长度超出上限",
    "literal_error": "取值不在允许范围内",
    "enum": "取值不在允许范围内",
    "extra_forbidden": "不支持的字段",
}


def _validation_error_message(exc: RequestValidationError) -> str:
    """首个校验错误 → 中文短句（带字段路径，不外泄 pydantic 英文样板与文档链接）。"""
    errors = exc.errors()
    if not errors:
        return "请求参数不合法"
    first = errors[0]
    loc = [str(part) for part in first.get("loc", ()) if part != "body"]
    field = ".".join(loc) or "请求体"
    label = _VALIDATION_TYPE_LABELS.get(str(first.get("type") or ""))
    if label is None:
        label = str(first.get("msg") or "").removeprefix("Value error, ") or "参数不合法"
    return f"{field}：{label}"


ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"


def _load_history_with_fallback(
    code: str,
    limit: int,
    is_index: bool = False,
    adjustment: str = "qfq",
    source: Any = None,
    bucket: str | None = None,
) -> tuple[list, str, str | None, str]:
    """优先所选历史源；上游失败时降级读取本地 market_bars 持久化历史。返回 (history, dataSource, dataAsOf, provider)。

    source 可由调用方预解析注入（复盘按请求解析一次，免逐码重建 settings+router）；缺省按当前 settings 现场路由。
    bucket 仅覆盖落库/兜底读取的键空间（A1 指数隔离用 qfq:idx）；上游请求参数恒为 adjustment，不受隔离影响。
    """
    store_bucket = bucket or adjustment
    if source is None:
        from backend.sources import build_router

        settings = get_workspace_settings("default")
        router = build_router()
    try:
        if source is None:
            source = router.route_with_fallback(
                settings.get("historySource", "tencent"), "history", settings.get("fallbackEnabled", True)
            )
        history = source.load_history(code, limit=limit, is_index=is_index, adjustment=adjustment)
        data_as_of = save_market_bars(code, history, adjustment=store_bucket)
        return history, "live", data_as_of, source.provider_label
    except Exception:
        bars = load_market_bars(code, limit=limit, adjustment=store_bucket)
        if not bars:
            raise
        return bars, "local", bars[-1]["date"], "local"


def _resolve_history_loader() -> tuple[Any, dict[str, int], list[str]]:
    """按请求解析一次历史源，返回 (loader, stats, degraded)——复盘/组合端点共用（Task 6 提取）。

    loader(codes)：经 fetch_all_bars 做 bfq 口径（adjustment=""）预取，上限 _BARS_LIMIT=300 根；
    stats["upstream"] 累计上游调用次数；命中本地 market_bars 兜底的 code 收进 degraded 并落
    review_degraded 告警（红线：降级不得静默）。构造失败 → source=None 逐码现场路由（旧行为）。
    """
    stats = {"upstream": 0}
    degraded: list[str] = []
    history_source: Any = None
    try:
        from backend.sources import build_router

        settings = get_workspace_settings("default")
        history_source = build_router().route_with_fallback(
            settings.get("historySource", "tencent"), "history", settings.get("fallbackEnabled", True)
        )
    except Exception:  # 构造失败 → helper 逐码现场路由（与旧行为一致）
        history_source = None

    def _counting(code: str, limit: int, is_index: bool = False, adjustment: str = "") -> list:
        stats["upstream"] += 1
        history, flag, as_of, _ = _load_history_with_fallback(code, limit, is_index, adjustment, source=history_source)
        if flag == "local":
            degraded.append(code)
            review_logger.warning("review_degraded code=%s as_of=%s", code, as_of)
        return history

    def _loader(codes: list[str]) -> dict[str, list[dict[str, Any]]]:
        return plan_review.fetch_all_bars(codes, SimpleNamespace(load_history=_counting))

    return _loader, stats, degraded


# days=0（ALL）的窗口起点哨兵：早于任何可得 bar 日期，回放/轴切按「全部可得数据」处理（spec §4 D4 回看档）。
# bars 取数天然受 plan_review._BARS_LIMIT=300 根上限约束，真实起点由 meta.truncatedAt 如实披露（spec §11）。
_ALL_WINDOW_START = "0001-01-01"

_RISK_DAYS = (0, 30, 90, 180, 365)  # 组合风险回看白名单（0=ALL，默认 90=前端 3M）
_RISK_LAYERS = ("core", "closed")  # 主层 / 闭环层（I7 layer 域）
_RISK_START_MAX_DAYS = 1825  # start 下界：今天−5 年（spec §6）


def _parse_iso_day(value: str, label: str) -> datetime:
    """严格 YYYY-MM-DD 解析（多余时间部分/错格式一律 422 中文 detail，同复盘纪律）。"""
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise api_error(422, ERR_VALIDATION_ERROR, f"{label} 须为合法日期 YYYY-MM-DD") from exc


def _shift_date_str(day: str, delta_days: int) -> str:
    """日历日位移（复盘 `now_ms − days*86400_000` 同款 slice 语义的字符串形式）。"""
    return (_parse_iso_day(day, "date") + timedelta(days=delta_days)).strftime("%Y-%m-%d")


def _date_delta_days(from_day: str, to_day: str) -> int:
    """含尾不含头的日差（to − from），供日志 window 字段（start 档无 days 可报）。"""
    return int((_parse_iso_day(to_day, "date") - _parse_iso_day(from_day, "date")).total_seconds() // 86400)


def _validated_start(start: str, today: str) -> str:
    """自定义起始日校验（spec §6）：合法 ISO 且 ∈ [today−1825d, today−1d]（今天不可作起点——当日 bar 未收盘）。

    归一返回 `YYYY-MM-DD`：`start` 优先且 days 完全忽略（终审 R4），meta.windowStart 回显该串（钉）。
    """
    parsed = _parse_iso_day(start, "start")
    floor = _parse_iso_day(today, "today") - timedelta(days=_RISK_START_MAX_DAYS)
    ceiling = _parse_iso_day(today, "today") - timedelta(days=1)
    if not (floor.date() <= parsed.date() <= ceiling.date()):
        raise api_error(
            422, ERR_VALIDATION_ERROR, f"start 须在 [{floor.strftime('%Y-%m-%d')}, {ceiling.strftime('%Y-%m-%d')}] 内"
        )
    return parsed.strftime("%Y-%m-%d")


def _validated_as_of(value: str | None) -> str | None:
    if value is None:
        return None
    from backend.sources.cn_impl import CNMarketCalendar

    parsed = _parse_iso_day(value, "asOfDate")
    current = datetime.now(plan_review.SHANGHAI).date()
    if parsed.date() > current:
        raise api_error(422, ERR_VALIDATION_ERROR, "asOfDate 不得晚于今天")
    if not CNMarketCalendar().is_trading_day(parsed.date()):
        raise api_error(422, ERR_VALIDATION_ERROR, "asOfDate 必须为交易日")
    return parsed.strftime("%Y-%m-%d")


def _snapshot_loader(as_of_date: str):
    from backend import storage

    with storage.SessionLocal() as session:
        _rows, initial_coverage = snapshot_query.query_market_snapshots(session, [], as_of_date, storage=storage)
    state: dict[str, Any] = {"coverage": initial_coverage}

    def load(codes: list[str]) -> dict[str, list[dict[str, Any]]]:
        with storage.SessionLocal() as session:
            rows, coverage = snapshot_query.query_market_snapshots(session, codes, as_of_date, storage=storage)
            eligible_codes = [code for code in codes if code in rows]
            bars = snapshot_query.load_archived_bars(session, eligible_codes, as_of_date, storage=storage)
        state["coverage"] = coverage
        return bars

    return load, state


# 行业映射整轮刷新不完整时的提前补跑间隔（分钟）：不完整 ≠ 无数据，但绝不该陈旧到 24h 后
_INDUSTRY_RETRY_MINUTES = 30


def _industry_warmup_job() -> None:
    """行业映射预热/每日刷新 job：吞异常并记 atlas.industry，job 崩溃绝不波及 API。

    整轮刷新不完整（如上游连接被重置、中途页失败）时**提前重排一次**，避免行业映射
    一直陈旧到下一个 24h 周期才被发现。
    """
    try:
        refresh_industry_map()
    except Exception:
        industry_logger.warning("行业映射全市场刷新失败（已跳过，不影响 API）", exc_info=True)
    _reschedule_industry_on_incomplete()


def _reschedule_industry_on_incomplete() -> None:
    """不完整 → `_INDUSTRY_RETRY_MINUTES` 分钟后补跑一次；完整 → 清掉可能残留的补跑 job。"""
    try:
        if last_refresh_complete() is False:
            scheduler.add_job(
                _industry_warmup_job,
                "date",
                run_date=datetime.now(scheduler.timezone) + timedelta(minutes=_INDUSTRY_RETRY_MINUTES),
                id="industry-warmup-retry",
                replace_existing=True,
            )
        elif scheduler.get_job("industry-warmup-retry") is not None:
            scheduler.remove_job("industry-warmup-retry")
    except Exception:
        industry_logger.warning("行业映射补跑任务调度失败（已跳过，不影响 API）", exc_info=True)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # P2-M2：L2 缓存门面接线（无配置/探测不可达 = down facade，行为与接管前一致）
        from backend.settings import get_settings

        set_facade(redis_cache.build_facade(get_settings(), ttl_getter=current_cache_ttl))
        try:
            initialize_storage()
            start_scheduler()
            app.state.storage_ready = True
        except Exception as exc:
            app.state.storage_ready = False
            app.state.storage_error = str(exc)
        if app.state.storage_ready:
            # A1 歧义桶一次性清理（spec §3.7 P2-3 时点纪律：重启窗口、幂等、留输出）。
            # 新代码生效后 qfq 桶仅个股写、qfq:idx 桶仅指数写——删除只损个股一次回源，绝不损正确性。
            try:
                removed = cleanup_legacy_index_qfq()
                if removed:
                    logger.info("a1_index_bucket_cleanup 删除历史歧义行=%d（幂等，0 行=已净）", removed)
            except Exception:
                logger.warning(
                    "a1_index_bucket_cleanup 失败（不阻塞启动；指数正确性不受影响——桶隔离已在读路径）", exc_info=True
                )
        if app.state.storage_ready:
            try:
                applied = get_workspace_settings("default")
                apply_runtime_config(
                    timeout_seconds=applied.get("timeoutSeconds"),
                    retry_count=applied.get("retryCount"),
                    cache_seconds=applied.get("cacheSeconds"),
                    rate_limit_rps=applied.get("rateLimitRps"),
                )
            except Exception:
                pass
            # 行业映射预热（Task 2）：启动后 30s 首刷，其后每 24h 刷新。
            # APScheduler 3.x 无 first_run_delay，用 next_run_time 等价实现延迟首刷；
            # 注册失败仅记日志，绝不影响 API 启动。
            try:
                scheduler.add_job(
                    _industry_warmup_job,
                    "interval",
                    hours=24,
                    id="industry-warmup",
                    replace_existing=True,
                    next_run_time=datetime.now(scheduler.timezone) + timedelta(seconds=30),
                )
            except Exception:
                industry_logger.warning("行业映射预热任务注册失败（已跳过，不影响 API）", exc_info=True)
            # 全市场日线 ETL（P2-M1）：启动 60s 自愈 + 交易日 15:20 + 周六审计；
            # 三 job 各自防重叠 kwargs，跨 job 互斥走 run_full 进程锁；注册异常内部已吞。
            bars_etl.register_jobs(scheduler)
        yield
        stop_scheduler()

    app = FastAPI(title="Atlas Stock Trade Agent", lifespan=lifespan)
    # 交易辅助：每实例新建限频器（测试隔离）与数据源路由（与数据源端点同一构建模式，离线安全）
    app.state.assist_limiter = SlidingWindowLimiter(max_events=30, window_seconds=60.0)
    app.state.assist_router = build_router()
    # 组合风险视图轻量护栏（spec §6：20 req/min，只防误循环/连点重算，非安全边界）：
    # 挂在 app.state 而非模块级，测试 fixture 直接换小实例验 429（不 monkeypatch 时钟、不真发 20 次）。
    app.state.portfolio_limiter = SlidingWindowLimiter(max_events=20, window_seconds=60.0)
    # 双轨托管：优先服务构建产物 frontend/dist（Vite），无 dist 时回退源码目录。
    # Vite 产物把静态资源放在 dist/assets/ 下，挂载目录按实际布局选择。
    # 判定必须落到 assets 子目录本身：dist 存在但 assets 缺失（构建中断、或 Vite emptyOutDir
    # 的建中窗口）时，挂载不存在的目录会让 StaticFiles 抛 RuntimeError 直接崩掉 create_app。
    assets_dir = DIST_DIR / "assets" if (DIST_DIR / "assets").is_dir() else FRONTEND_DIR
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.exception_handler(RequestValidationError)
    async def _request_validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """请求体/查询参数校验失败也返回统一 api_error 形状。

        FastAPI 默认回 `{"detail": [ ... pydantic 英文样板 ... ]}`：形状与既有契约不同，
        前端拿不到 `detail.code`。这里统一成 `{"detail": {"error": 中文, "code": VALIDATION_ERROR}}`。
        """
        return JSONResponse(
            status_code=422,
            content={"detail": {"error": _validation_error_message(exc), "code": ERR_VALIDATION_ERROR}},
        )

    @app.middleware("http")
    async def stale_header_middleware(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            marker = recent_stale(window=2.0)
            if marker:
                response.headers["X-Atlas-Stale"] = f"{int(marker['age'])}"
        return response

    @app.get("/api/health")
    def health() -> HealthOut:
        return HealthOut(
            ok=True,
            provider="Tencent public quote API",
            serverTime=int(time.time() * 1000),
            mode="separated",
            universeSize=50,
            storage=storage_status(),
            bars=bars_etl.bars_health(),
            redisCache=facade_state(),
            minuteCache=facade_state(),
            minuteCircuit=minute_path.breaker_state(),
            industry=industry_health(),
        )

    @app.get("/api/minute", response_model=MinuteOut)
    def minute(code: str, period: str = "5m", count: int = 320, index: bool = False) -> MinuteOut:
        try:
            result = minute_path.fetch_minute(code, period, count, index)
        except ValueError as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc
        if result.state == "rate_limited":
            raise HTTPException(
                status_code=429, detail={"error": "分钟线请求过于频繁，请稍后再试", "code": ERR_RATE_LIMITED}
            )
        return MinuteOut(
            bars=result.bars,
            source=result.source,
            state=result.state,
            degraded=result.degraded,
            updatedAtMs=result.updated_at_ms,
        )

    @app.get("/api/workspace")
    def workspace(workspace_id: str = Query(default="default", alias="workspace")) -> WorkspaceOut:
        try:
            return WorkspaceOut.model_validate(get_workspace(workspace_id))
        except Exception as exc:
            raise api_error(503, ERR_STORAGE_UNAVAILABLE, f"持久化存储不可用: {exc}") from exc

    @app.put("/api/workspace")
    def update_workspace(
        payload: WorkspacePut,
        workspace_id: str = Query(default="default", alias="workspace"),
        base_revision: int | None = Query(default=None, alias="baseRevision"),
        force: bool = Query(default=False),
    ) -> WorkspacePutOut:
        try:
            current = get_workspace_revision(workspace_id)
            if base_revision is not None and base_revision != current and not force:
                raise api_error(
                    409,
                    ERR_WORKSPACE_CONFLICT,
                    "其他页面已更新工作区数据",
                    revision=current,
                    workspace=get_workspace(workspace_id),
                )
            body = payload.model_dump(exclude_unset=True)
            # 交易对关联写路径校验（I1）：违规在落盘前拒绝，422 中文错误可直接指导用户
            link_error = validate_plan_links(body.get("plans") or [])
            if link_error:
                raise api_error(422, ERR_VALIDATION_ERROR, link_error)
            return WorkspaceOut.model_validate(save_workspace(body, workspace_id))
        except HTTPException:
            raise
        except Exception as exc:
            raise api_error(503, ERR_STORAGE_UNAVAILABLE, f"持久化存储不可用: {exc}") from exc

    @app.get("/api/settings")
    def settings(workspace_id: str = Query(default="default", alias="workspace")) -> SettingsOut:
        try:
            data = get_workspace_settings(workspace_id)
        except Exception:
            data = dict(DEFAULT_WORKSPACE_SETTINGS)
        akshare_installed = find_spec("akshare") is not None
        tushare_installed = find_spec("tushare") is not None
        # token 掩码纪律：GET 的 data 恒不含明文；配置状态与尾 4 位经 sources.tushare 行下发
        workspace_token = str(data.get("tushareToken") or "")
        env_token = str(get_settings().tushare_token or "")
        data = {**data, "tushareToken": ""}
        tushare_configured = bool(workspace_token or env_token)
        tushare_masked = f"****{(workspace_token or env_token)[-4:]}" if tushare_configured else ""
        sources: list[dict[str, Any]] = [dict(info) for info in get_all_sources_info()]
        # 已注册适配器之外的计划中源：保留 installed/config 探测信息（available=False）
        sources.extend(
            [
                {
                    "id": "akshare",
                    "name": "AkShare",
                    "realtime": False,
                    "history": True,
                    "screener": True,
                    "fundamental": False,
                    "available": False,
                    "installed": akshare_installed,
                    "reason": "暂未支持切换，适配器开发中" if akshare_installed else "未安装 AkShare",
                },
                {
                    "id": "tushare",
                    "name": "Tushare",
                    "realtime": False,
                    "history": True,
                    "screener": True,
                    "fundamental": False,
                    "available": False,
                    "installed": tushare_installed,
                    "tushareConfigured": tushare_configured,
                    "tushareTokenMasked": tushare_masked,
                    "reason": "暂未支持切换，适配器开发中" if tushare_configured else "未配置 TUSHARE_TOKEN",
                },
            ]
        )
        return SettingsOut(data=data, sources=sources)

    @app.put("/api/settings")
    def update_settings(
        payload: SettingsPut, workspace_id: str = Query(default="default", alias="workspace")
    ) -> SettingsPutOut:
        try:
            saved = save_workspace_settings(payload.model_dump(exclude_unset=True), workspace_id)
            apply_runtime_config(
                timeout_seconds=saved.get("timeoutSeconds"),
                retry_count=saved.get("retryCount"),
                cache_seconds=saved.get("cacheSeconds"),
                rate_limit_rps=saved.get("rateLimitRps"),
            )
            # PUT 响应同 GET 掩码纪律：不回显明文 token
            return SettingsPutOut(data={**saved, "tushareToken": ""})
        except Exception as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, f"设置保存失败: {exc}") from exc

    @app.get("/api/market")
    def market(codes: str = Query(default="")) -> MarketOut:
        try:
            from backend.sources import build_router

            settings = get_workspace_settings("default")
            source = build_router().route_with_fallback(
                settings.get("realtimeSource", "tencent"), "realtime", settings.get("fallbackEnabled", True)
            )
            payload = source.load_market(codes.split(",") if codes else [])
            payload["provider"] = source.provider_label
            return MarketOut.model_validate(payload)
        except Exception as exc:
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, str(exc), provider="upstream")

    @app.get("/api/history")
    def history(code: str = Query(default="600519"), index: bool = Query(default=False)) -> HistoryOut:
        try:
            history, data_source_flag, data_as_of, provider = _load_history_with_fallback(
                code, 120, is_index=index, adjustment="qfq", bucket="qfq:idx" if index else None
            )
            return HistoryOut(
                code=code,
                provider=provider,
                fetchedAt=int(time.time() * 1000),
                history=history,
                dataSource=data_source_flag,
                dataAsOf=data_as_of,
            )
        except Exception as exc:
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, str(exc), provider="upstream")

    @app.get("/api/screener")
    def screener(
        market: str = Query(default="全部"), pageSize: int = Query(default=300, alias="pageSize")
    ) -> ScreenerOut:
        try:
            from backend.sources import build_router

            settings = get_workspace_settings("default")
            source = build_router().route_with_fallback(
                settings.get("screenerSource", "tencent"), "screener", settings.get("fallbackEnabled", True)
            )
            payload = source.load_screener(market, pageSize)
            payload["provider"] = source.provider_label
            payload["fetchedAt"] = int(time.time() * 1000)
            return ScreenerOut.model_validate(payload)
        except Exception as exc:
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, str(exc), provider="upstream")

    @app.get("/api/screener/v2")
    def screener_v2(
        page: int = Query(default=1, ge=1),
        pageSize: int = Query(default=50, alias="pageSize", ge=1, le=200),
        sortBy: str = Query(default="changePct", alias="sortBy"),
        sortDir: str = Query(default="desc", alias="sortDir"),
    ):
        try:
            from backend.sources import build_router

            settings = get_workspace_settings("default")
            source = build_router().route_with_fallback(
                settings.get("screenerSource", "tencent"), "paged_screener", settings.get("fallbackEnabled", True)
            )
            payload = source.load_screener_paged(page=page, page_size=pageSize, sort_by=sortBy, sort_dir=sortDir)
            payload["fetchedAt"] = int(time.time() * 1000)
            return payload
        except Exception as exc:
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, str(exc), provider="upstream")

    # 模块级单例：策略管道跨请求复用缓存/锁（FastAPI 多 worker 间不共享，单实例部署足够）
    _strategy_pipeline: dict[str, Any] = {}

    @app.get("/api/screener/strategies")
    def screener_strategies():
        from backend.screener.loader import list_strategies as list_builtin_strategies

        strategies = [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "sortBy": c.sort_by,
                "topN": c.top_n,
                "deepCap": c.deep_cap,
                "factorCount": len(c.advanced_factors),
                # fork 预填所需完整配置（加性字段，兼容既有消费）
                "quickFilters": {k: list(v) for k, v in c.quick_filters.items()},
                "advancedFactors": [f.model_dump() for f in c.advanced_factors],
            }
            for c in list_builtin_strategies()
        ]
        # 自定义策略合并（custom 标志 + 乐观锁 version）；内置行字段零变化
        try:
            custom_rows, _total = list_custom_strategies(limit=500)
        except Exception:
            # 读库故障绝不拖垮合并列表（内置策略照常可用），但必须留日志——
            # 否则「读库失败」在 UI 上只表现为「没有自定义策略」，无从察觉
            screener_logger.warning("screener.custom_strategies_list_failed", exc_info=True)
            custom_rows = []
        strategies.extend(
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "sortBy": str(r["config"].get("sort_by") or "changePct"),
                "topN": int(r["config"].get("top_n") or 10),
                "deepCap": int(r["config"].get("deep_cap") or 200),
                "factorCount": len(r["config"].get("advanced_factors") or []),
                "quickFilters": {k: list(v) for k, v in (r["config"].get("quick_filters") or {}).items()},
                "advancedFactors": r["config"].get("advanced_factors") or [],
                "custom": True,
                "version": r["version"],
            }
            for r in custom_rows
        )
        return {"strategies": strategies}

    @app.post("/api/screener/strategy", response_model=ScreenerStrategyOut)
    def screener_strategy_run(payload: ScreenerStrategyRunIn) -> ScreenerStrategyOut:
        from backend.screener.pipeline import ScreenerPipeline

        pipeline = _strategy_pipeline.get("p")
        if pipeline is None:
            from backend.sources import build_router as _build_router

            # 显式经 app 模块的 get_workspace_settings（测试可 mock；运行时读真实设置）
            pipeline = ScreenerPipeline(_build_router(), settings_getter=lambda: get_workspace_settings("default"))
            _strategy_pipeline["p"] = pipeline
        try:
            result = pipeline.run(
                payload.strategy,
                mode=payload.mode,
                refresh=payload.refresh,
                reference_date=payload.referenceDate,
            )
        except ValueError as exc:
            # 未知策略 / 非法 mode / 非法 referenceDate → 422
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc))
        except Exception as exc:
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, str(exc), provider="upstream")
        return ScreenerStrategyOut(**result)

    def _invalidate_custom_strategy_cache(strategy_id: str) -> None:
        pipeline = _strategy_pipeline.get("p")
        if pipeline is None:
            return
        try:
            pipeline.invalidate_strategy(strategy_id)
        except Exception:
            logger.warning("screener.custom_cache_invalidate_failed", extra={"strategyId": strategy_id})

    @app.get("/api/screener/custom-strategies")
    def custom_strategies_list(
        search: str = Query(default=""),
        limit: int = Query(default=200, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        try:
            rows, total = list_custom_strategies(search=search, limit=limit, offset=offset)
        except Exception as exc:
            raise api_error(502, ERR_STORAGE_UNAVAILABLE, f"自定义策略读取失败: {exc}") from exc
        return {"strategies": rows, "total": total}

    def _write_custom_strategy(payload: CustomStrategyIn, strategy_id: str | None, expected_version: int | None):
        data = {
            "name": payload.name,
            "description": payload.description,
            "quick_filters": payload.quickFilters,
            "advanced_factors": payload.advancedFactors,
            "sort_by": payload.sortBy,
            "top_n": payload.topN,
            "deep_cap": payload.deepCap,
            "source_builtin": payload.sourceBuiltin,
        }
        try:
            row = upsert_custom_strategy(data, strategy_id=strategy_id, expected_version=expected_version)
        except CustomStrategyConflict as exc:
            raise api_error(
                409,
                ERR_SCREENER_STRATEGY_CONFLICT,
                "策略已被其他页面更新，请刷新后重试",
                server=exc.server_row,
            ) from exc
        except ValueError as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc
        except Exception as exc:
            raise api_error(502, ERR_STORAGE_UNAVAILABLE, f"保存自定义策略失败: {exc}") from exc
        _invalidate_custom_strategy_cache(row["id"])
        return row

    @app.post("/api/screener/custom-strategies")
    def custom_strategies_create(payload: CustomStrategyIn) -> dict[str, Any]:
        return _write_custom_strategy(payload, strategy_id=None, expected_version=None)

    @app.get("/api/screener/custom-strategies/{strategy_id}")
    def custom_strategies_get(strategy_id: str) -> dict[str, Any]:
        try:
            row = get_custom_strategy(strategy_id)
            refs = list_scan_references(strategy_id)
        except Exception as exc:
            raise api_error(502, ERR_STORAGE_UNAVAILABLE, f"自定义策略读取失败: {exc}") from exc
        if row is None:
            raise api_error(404, ERR_NOT_FOUND, "未知自定义策略")
        return {**row, "scanReferences": refs}

    @app.put("/api/screener/custom-strategies/{strategy_id}")
    def custom_strategies_update(strategy_id: str, payload: CustomStrategyIn) -> dict[str, Any]:
        if payload.version is None:
            raise api_error(422, ERR_VALIDATION_ERROR, "更新自定义策略必须携带 version（乐观锁）")
        return _write_custom_strategy(payload, strategy_id=strategy_id, expected_version=payload.version)

    @app.delete("/api/screener/custom-strategies/{strategy_id}")
    def custom_strategies_delete(strategy_id: str) -> dict[str, Any]:
        try:
            result = delete_custom_strategy(strategy_id)
        except Exception as exc:
            raise api_error(502, ERR_STORAGE_UNAVAILABLE, f"删除自定义策略失败: {exc}") from exc
        if result is None:
            raise api_error(404, ERR_NOT_FOUND, "未知自定义策略")
        screener_logger.info(
            "screener.custom_strategy_deleted",
            extra={"strategyId": strategy_id, "snapshot": result["deleted"]},
        )
        _invalidate_custom_strategy_cache(strategy_id)
        return {"deleted": result["deleted"], "scanReferences": result["scanReferences"]}

    def _scan_config_out(cfg: dict[str, Any]) -> dict[str, Any]:
        from backend.screener.loader import load_strategy

        try:
            name = str(load_strategy(cfg["strategyId"]).name)
        except ValueError:
            name = "（策略已不存在）"
        return {
            "strategyId": cfg["strategyId"],
            "strategyName": name,
            "enabled": cfg["enabled"],
            "mode": cfg["mode"],
            "lastRunAt": cfg["lastRunAt"].isoformat() if cfg["lastRunAt"] else None,
            "lastStatus": cfg["lastStatus"],
            "hitCount": len(cfg["lastHits"] or []),
            "newCount": int(cfg["lastNewCount"] or 0),
        }

    @app.get("/api/screener/scan/configs")
    def scan_configs_list() -> dict[str, Any]:
        return {"configs": [_scan_config_out(c) for c in list_scan_configs()]}

    @app.put("/api/screener/scan/configs")
    def scan_configs_put(payload: dict[str, Any]) -> dict[str, Any]:
        strategy_id = str(payload.get("strategyId") or "")
        mode = str(payload.get("mode") or "quick")
        if not isinstance(payload.get("enabled"), bool) or mode not in ("quick", "deep"):
            raise api_error(422, ERR_VALIDATION_ERROR, "enabled 必须为 bool，mode 须为 quick|deep")
        try:
            from backend.screener.loader import load_strategy

            load_strategy(strategy_id)
        except ValueError as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc))
        cfg = upsert_scan_config(strategy_id, bool(payload["enabled"]), mode)
        # 审计日志（二轮决议 14）：本地单用户，记录变更本身
        logger.info(
            "screener.scan_config_changed",
            extra={"strategy_id": strategy_id, "enabled": bool(payload["enabled"]), "mode": mode},
        )
        return {"config": _scan_config_out(cfg)}

    @app.post("/api/screener/scan/now")
    def scan_now(payload: dict[str, Any]) -> dict[str, Any]:
        strategy_id = str(payload.get("strategyId") or "")
        try:
            from backend.screener.loader import load_strategy

            load_strategy(strategy_id)
        except ValueError as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc))
        from backend.screener.scan import run_scan

        # 透传配置 mode（Finding 1）：立即扫描也须按用户配置的 quick/deep 执行；
        # cfg 为 None（无配置行）保持默认 quick——run 照跑，随后 skipped→422 分支如实映射
        cfg = get_scan_config(strategy_id)
        mode = str(cfg.get("mode") or "quick") if cfg is not None else "quick"
        result = run_scan(strategy_id, mode=mode)
        if result["status"] == "failed":
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, "扫描失败（上游不可用），稍后可重试")
        if result["status"] == "skipped":
            # 评审一轮 #1：skipped = 未落库（无配置行 / 配置已禁用），如实回 422 而非 500/谎报 200
            cfg = get_scan_config(strategy_id)
            if cfg is None:
                raise api_error(422, ERR_VALIDATION_ERROR, "该策略尚未配置定时扫描，请先在策略实验室开启开关")
            raise api_error(422, ERR_VALIDATION_ERROR, "该策略已禁用定时扫描，请先开启开关")
        cfg = get_scan_config(strategy_id)
        if cfg is None:  # status 为 ok/skipped 之外时配置行必然存在（run_scan 刚写过状态）；防御分支
            raise api_error(422, ERR_VALIDATION_ERROR, "该策略尚未配置定时扫描，请先在策略实验室开启开关")
        return {"config": _scan_config_out(cfg), "alerted": int(result["newCount"])}

    @app.get("/api/screener/scan/hits")
    def scan_hits() -> dict[str, Any]:
        from backend.screener.loader import load_strategy

        hits: list[dict[str, Any]] = []
        for cfg in list_enabled_scan_configs():
            try:
                name = str(load_strategy(cfg["strategyId"]).name)
            except ValueError:
                continue  # 策略已不存在 → 不进 hits
            codes = [
                {"code": h.get("code"), "name": h.get("name"), "score": h.get("score"), "firstSeen": h.get("firstSeen")}
                for h in (cfg["lastHits"] or [])
            ]
            hits.append(
                {
                    "strategyId": cfg["strategyId"],
                    "strategyName": name,
                    "scannedAt": cfg["lastRunAt"].isoformat() if cfg["lastRunAt"] else None,
                    "status": cfg["lastStatus"],
                    "codes": codes,
                }
            )
        return {"hits": hits}

    def _scan_history_out(row: dict[str, Any]) -> dict[str, Any]:
        """扫描历史行 → camelCase 出参。list_scan_history 行键已是 camelCase（storage.py:875），
        仅把 runAt（datetime）转为机器时间戳 runAtMs（毫秒，同 _plan_dict createdAtMs 惯例）。"""
        run_at = row.get("runAt")
        return {
            "strategyId": row.get("strategyId"),
            "runAtMs": int(run_at.timestamp() * 1000) if run_at is not None else None,
            "status": row.get("status"),
            "hitCount": row.get("hitCount"),
            "newCount": row.get("newCount"),
            "elapsedMs": row.get("elapsedMs"),
            "traceId": row.get("traceId"),
        }

    @app.get("/api/screener/scan/history")
    def scan_history(strategyId: str | None = None, limit: int = 30) -> dict[str, Any]:
        """扫描运行留痕（只读，最新在前）：limit 夹取 1..200。"""
        limit = max(1, min(int(limit), 200))
        rows = list_scan_history(strategy_id=strategyId or None, limit=limit)
        return {"history": [_scan_history_out(r) for r in rows]}

    @app.post("/api/snapshots/industry")
    def snapshots_industry(payload: dict[str, Any]) -> dict[str, Any]:
        as_of = str(payload.get("asOfDate") or "")
        mode = str(payload.get("mode") or "backfill")
        if not payload.get("confirm"):
            raise api_error(422, ERR_VALIDATION_ERROR, "confirm 必须为 true")
        as_of = _validated_as_of(as_of) or ""
        if mode not in ("backfill", "rebuild"):
            raise api_error(422, ERR_VALIDATION_ERROR, "mode 仅支持 backfill/rebuild")
        if mode == "rebuild":
            raise api_error(501, "NOT_IMPLEMENTED", "真实历史源未接入，rebuild 暂不可用")
        try:
            return snapshot_archive.backfill_industry(as_of, reason=str(payload.get("reason") or ""), mode=mode)
        except snapshot_archive.storage.SnapshotConflictError as exc:
            raise api_error(409, "SNAPSHOT_CONFLICT", str(exc)) from exc
        except ValueError as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc
        except Exception as exc:
            raise api_error(500, ERR_STORAGE_UNAVAILABLE, "行业快照回填失败") from exc

    @app.get("/api/plans/review")
    def plans_review(
        days: int = 90,
        feeRate: float = plan_review.DEFAULT_FEE_RATE,
        asOfDate: str | None = None,
    ) -> dict[str, Any]:
        """计划绩效复盘（只读，设计口径回算；红线：零写 plans）。"""
        if days not in (0, 30, 90):
            raise api_error(422, ERR_VALIDATION_ERROR, "days 仅支持 0/30/90")
        if not (0.0 <= feeRate <= plan_review.FEE_RATE_MAX):
            raise api_error(422, ERR_VALIDATION_ERROR, f"feeRate 须在 [0, {plan_review.FEE_RATE_MAX}]")
        asOfDate = _validated_as_of(asOfDate)
        plans = get_workspace().get("plans") or []
        # bars 预取走路由历史源（historySource/fallbackEnabled+本地 market_bars 兜底），bfq 口径 adjustment=""；
        # 命中本地兜底的 code 记入 degraded 如实披露（红线：降级不得静默），历史源按请求解析一次
        t0 = time.perf_counter()
        snapshot_state: dict[str, Any] = {}
        degraded: list[str]
        if asOfDate:
            load_bars, snapshot_state = _snapshot_loader(asOfDate)
            stats, degraded = {"upstream": 0}, []
        else:
            load_bars, stats, degraded = _resolve_history_loader()

        try:
            result = plan_review.review_plans(
                plans,
                days=days,
                fee_rate=float(feeRate),
                load_bars=load_bars,
                as_of_date=asOfDate,
            )
        except plan_review.ReviewUpstreamError as exc:
            review_logger.error("review_upstream_failed codes=%s", exc.codes)
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, "历史行情拉取失败", failedCodes=exc.codes) from exc
        result["degraded"] = sorted(set(degraded))
        if asOfDate:
            coverage = snapshot_state.get("coverage")
            result["snapshot"] = coverage.to_dict() if coverage else snapshot_query.SnapshotCoverage(asOfDate).to_dict()
        review_logger.info(
            "review_ok plans=%d window_days=%d codes=%d upstream=%d degraded=%s fee_rate=%.4f elapsed_ms=%d",
            len(plans),
            days,
            len({str(r.get("code")) for r in result.get("items", []) if r.get("code")}),
            stats["upstream"],
            ",".join(result["degraded"]) or "-",
            float(feeRate),
            int((time.perf_counter() - t0) * 1000),
        )
        return result

    @app.get("/api/portfolio/risk")
    def portfolio_risk_view(
        days: int = 90,
        start: str | None = None,
        layer: str = "core",
        withWatch: bool = False,
        feeRate: float = plan_review.DEFAULT_FEE_RATE,
        asOfDate: str | None = None,
        workspace_id: str = Query(default="default", alias="workspace"),
    ) -> dict[str, Any]:
        """组合风险视图（只读，设计口径回放；红线：零写 plans、永不连券商/自动下单）。spec §6 I11。"""
        # —— 1. 先限频后校验（429 样式照 assist_plan_draft：失败请求也计数）——
        limiter: SlidingWindowLimiter = app.state.portfolio_limiter
        allowed, retry_after = limiter.check()
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={"error": "组合风险请求过于频繁，请稍后再试", "code": ERR_RATE_LIMITED},
                headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
            )

        # —— 2. 参数校验（422 中文 detail，同复盘纪律）——
        today = datetime.now(plan_review.SHANGHAI).strftime("%Y-%m-%d")
        asOfDate = _validated_as_of(asOfDate)
        if asOfDate is not None:
            today = asOfDate
        replay_today = _shift_date_str(today, 1) if asOfDate else today
        window_start: str
        window_span: int  # 日志 window 字段：days 档给 days，start 档给起止日差
        if start is None:
            if days not in _RISK_DAYS:
                raise api_error(422, ERR_VALIDATION_ERROR, "days 仅支持 0/30/90/180/365")
            window_span = days
            window_start = _ALL_WINDOW_START if days == 0 else _shift_date_str(today, -days)
        else:
            # start 优先且 days 完全忽略、不参与交叉校验（spec §6 终审 R4）——窗口 = [start, today)
            window_start = _validated_start(start, today)
            window_span = _date_delta_days(window_start, today)
        if layer not in _RISK_LAYERS:
            raise api_error(422, ERR_VALIDATION_ERROR, "layer 仅支持 core/closed")
        if not (0.0 < float(feeRate) <= plan_review.FEE_RATE_MAX):
            raise api_error(422, ERR_VALIDATION_ERROR, f"feeRate 须在 (0, {plan_review.FEE_RATE_MAX}]")

        # —— 3. 取数（历史源按请求解析一次；stats/degraded 与复盘同源，Task 6 段 1 提取物）——
        t0 = time.perf_counter()
        workspace = get_workspace(workspace_id)
        end_ms = (
            int(
                (
                    datetime.strptime(today, "%Y-%m-%d").replace(tzinfo=plan_review.SHANGHAI) + timedelta(days=1)
                ).timestamp()
                * 1000
            )
            - 1
        )
        plans = [p for p in (workspace.get("plans") or []) if int(p.get("createdAtMs") or 0) <= end_ms]
        watchlist = workspace.get("watchlist") or []
        settings = get_workspace_settings(workspace_id)
        links, link_events = portfolio_risk.build_links(plans)
        # codes 集合：buy 成分码 ∪ (closed 层全部 sell 码 ∪ 未配对孤儿 sell 码——看板信号也要 bar) ∪ 自选码
        paired_sell_ids = {str((link.get("sell") or {}).get("id") or "") for link in links.values()}
        plan_codes: list[str] = []
        for plan in plans:
            if not isinstance(plan, dict):
                continue
            code = str(plan.get("code") or "").strip()
            if not code:
                continue
            kind = str(plan.get("type") or plan.get("direction") or "buy").strip().lower()
            if kind == "buy":
                plan_codes.append(code)
            elif layer == "closed" or str(plan.get("id") or "") not in paired_sell_ids:
                plan_codes.append(code)
        # 两趟取数（评审 F1）：计划码硬失败→502（保持现语义）；withWatch 自选码属外围，第二趟隔离——
        # 上游不可达只并 degraded + review_degraded 告警（不 502），缺 bar 由 watchIndex null 拖尾消化（引擎零改动）。
        plan_codes = list(dict.fromkeys(plan_codes))
        watch_codes: list[str] = []
        if withWatch:
            plan_set = set(plan_codes)
            watch_codes = [
                c
                for c in dict.fromkeys(str(item).strip() for item in watchlist if str(item or "").strip())
                if c not in plan_set
            ]
        codes = plan_codes + watch_codes  # 日志 codes 字段 = 两趟总取数码

        snapshot_state: dict[str, Any] = {}
        degraded: list[str]
        if asOfDate:
            load_bars, snapshot_state = _snapshot_loader(asOfDate)
            stats, degraded = {"upstream": 0}, []
        else:
            load_bars, stats, degraded = _resolve_history_loader()
        try:
            if asOfDate:
                from backend import storage

                with storage.SessionLocal() as session:
                    industry, industry_coverage = snapshot_query.query_industry_map(
                        session, codes, asOfDate, storage=storage
                    )
                industry_status = "fresh" if not industry_coverage.degraded else "stale"
            else:
                industry, industry_status = get_industry_map()  # 只读缓存：API 绝不内联拉全市场（spec §3）
            bars_map: dict[str, list[dict[str, Any]]] = load_bars(plan_codes) if plan_codes else {}
        except plan_review.ReviewUpstreamError as exc:
            review_logger.error("review_upstream_failed codes=%s", exc.codes)
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, "历史行情拉取失败", failedCodes=exc.codes) from exc
        if watch_codes:
            try:
                bars_map.update(load_bars(watch_codes))
            except plan_review.ReviewUpstreamError as exc:
                # 吸收部分成功（收尾硬化 L1）：失败前已真实拉到的自选码 bar 不整批丢弃，
                # degraded 仅记失败码——缺 bar 的码由引擎 watchIndex 对齐全 null 段如实拖尾。
                bars_map.update(exc.partial)
                for code in exc.codes:
                    degraded.append(code)
                    review_logger.warning("review_degraded code=%s as_of=%s", code, "-")

        # —— 4. 单趟回放 + NAV 组装（compose_nav 只调一次，nav 五键同源，评审三钉）——
        positions, replay_events = portfolio_risk.replay_positions(
            plans, bars_map, window_start, replay_today, layer, links
        )
        dates = portfolio_risk.nav_dates(bars_map, window_start, replay_today)
        nav = portfolio_risk.compose_nav(positions, dates, float(feeRate))
        payload = portfolio_risk.aggregate_portfolio(
            plans=plans,
            watchlist=watchlist,
            settings=settings,
            bars_map=bars_map,
            positions=positions,
            dates=nav["dates"],
            gross=nav["gross"],
            net=nav["net"],
            events=[*replay_events, *link_events],
            links=links,
            layer=layer,
            window_start=window_start,
            today=replay_today,
            fee_rate=float(feeRate),
            industry=industry,
            industry_status=industry_status,
            with_watch=withWatch,
        )
        # —— 5. 并包：nav 的 feeCum/feeSum 取自同一次 compose_nav（恒等式逐日成立）——
        payload["nav"]["feeCum"] = nav["feeCum"]
        payload["nav"]["feeSum"] = nav["feeSum"]
        payload["degraded"] = sorted(set(degraded))  # 降级不得静默（同复盘）
        if asOfDate:
            market_coverage = snapshot_state.get("coverage") or snapshot_query.SnapshotCoverage(asOfDate)
            payload["snapshot"] = {
                "degraded": bool(market_coverage.degraded or industry_coverage.degraded),
                "market": market_coverage.to_dict(),
                "industry": industry_coverage.to_dict(),
            }
        # bars 取数受 BARS_LIMIT 根上限：轴被拉满即窗起点存在截断，如实披露（评审 F2——判据与 days/start 解耦；
        # 值为多码并集轴首日；无截断不产该键，聚合层 T5 三处缺席钉语义不变）
        if len(dates) >= plan_review.BARS_LIMIT:
            payload["meta"]["truncatedAt"] = dates[0]
        all_events = [*replay_events, *link_events]
        review_logger.info(
            "portfolio_ok layer=%s window=%d plans=%d codes=%d upstream=%d gross_mdd=%.4f net_mdd=%.4f"
            " scaling=%d conflicts=%d degraded=%s elapsed_ms=%d",
            layer,
            window_span,
            len(plans),
            len(codes),
            stats["upstream"],
            float(payload["kpis"]["mdd"]),
            float(payload["kpis"]["mddNet"]),
            sum(1 for e in all_events if e.get("type") == "scaling"),
            sum(1 for e in all_events if e.get("type") == "conflict"),
            ",".join(payload["degraded"]) or "-",
            int((time.perf_counter() - t0) * 1000),
        )
        return payload

    @app.post("/api/assist/plan-draft", response_model=PlanDraftResponse)
    def assist_plan_draft(payload: PlanDraftIn) -> PlanDraftResponse:
        limiter: SlidingWindowLimiter = app.state.assist_limiter
        allowed, retry_after = limiter.check()  # 先限频计数（含失败请求），再做任何校验 / IO
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={"error": "草案请求过于频繁，请稍后再试", "code": ERR_RATE_LIMITED},
                headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
            )
        started = time.monotonic()
        trace_id = uuid4().hex[:8]
        try:
            draft = build_plan_draft(
                app.state.assist_router, payload.model_dump(), lambda: get_workspace_settings("default")
            )
        except ValueError as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc
        except UpstreamError as exc:
            logger.warning(
                "assist.upstream_error", extra={"trace_id": trace_id, "code": payload.code, "error": str(exc)}
            )
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, str(exc), provider="upstream") from exc
        logger.info(
            "assist.plan_draft",
            extra={
                "trace_id": trace_id,
                "code": payload.code,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
                "shares": draft["suggestedShares"],
                "stale": draft["stale"],
                "fallback_used": draft["fallbackUsed"],
                "provider": draft["provider"],
            },
        )
        return PlanDraftResponse(data=PlanDraftOut.model_validate(draft))

    @app.post("/api/grid/preview")
    def grid_preview(payload: GridPreviewIn) -> GridPreviewOut:
        try:
            code = payload.code
            profile = classify_code(code)
            grid_count = max(2, min(payload.gridCount, 30))
            history, data_source_flag, data_as_of, _ = _load_history_with_fallback(
                code, max(20, min(payload.lookback, 240))
            )
            return GridPreviewOut(
                code=code,
                profile=profile,
                dataAsOf=data_as_of,
                dataSource=data_source_flag,
                history=history,
                suggestion=suggest_grid(history, grid_count, payload.capital, payload.mode),
            )
        except Exception as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc

    @app.post("/api/grid/backtest")
    def grid_backtest(
        payload: GridBacktestIn, workspace_id: str = Query(default="default", alias="workspace")
    ) -> GridBacktestOut:
        try:
            code = payload.code
            profile = classify_code(code)
            lookback = max(20, min(payload.lookback, 240))
            history, data_source_flag, data_as_of, _ = _load_history_with_fallback(code, lookback)
            capital = payload.capital
            fee_bps = payload.feeBps
            grid_count = max(2, min(payload.gridCount, 30))
            mode = payload.mode
            settlement_days = max(0, min(payload.settlementDays, 5))
            slippage_bps = max(0, min(payload.slippageBps, 100))
            suggestion = suggest_grid(history, grid_count, capital, mode)
            lower = payload.lower or suggestion["lower"]
            upper = payload.upper or suggestion["upper"]
            limit_pct = price_limit_ratio(code)
            result = backtest_grid(
                history,
                lower,
                upper,
                grid_count,
                capital,
                fee_bps,
                mode,
                profile["securityType"],
                profile["exchange"],
                settlement_days,
                slippage_bps,
                limit_pct,
            )
            response = {
                "code": code,
                "profile": profile,
                "history": history,
                "config": {
                    "lower": lower,
                    "upper": upper,
                    "gridCount": grid_count,
                    "capital": capital,
                    "feeBps": fee_bps,
                    "lookback": lookback,
                    "mode": mode,
                    "settlementDays": settlement_days,
                    "slippageBps": slippage_bps,
                    "priceLimitPct": limit_pct * 100,
                    "dataAsOf": data_as_of,
                },
                **result,
            }
            if payload.save:
                strategy = save_grid_strategy(
                    {
                        "id": payload.id or f"grid-{uuid4().hex}",
                        "code": code,
                        "name": payload.name,
                        "lower": lower,
                        "upper": upper,
                        "gridCount": grid_count,
                        "capital": capital,
                        "feeBps": fee_bps,
                        "mode": mode,
                        "lookback": lookback,
                        "settlementDays": settlement_days,
                        "slippageBps": slippage_bps,
                        "schedule": payload.schedule,
                        "status": "启用",
                    },
                    workspace_id,
                )
                save_grid_backtest(strategy["id"], code, response["config"], result, workspace_id)
                schedule_strategy(strategy)
                response["strategy"] = get_grid_strategy(strategy["id"])
            return GridBacktestOut.model_validate(response)
        except Exception as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc

    @app.post("/api/grid/optimize")
    def grid_optimize(payload: GridOptimizeIn) -> GridOptimizeOut:
        try:
            code = payload.code
            profile = classify_code(code)
            lookback = max(20, min(payload.lookback, 240))
            from backend.sources import build_router

            settings = get_workspace_settings("default")
            source = build_router().route_with_fallback(
                settings.get("historySource", "tencent"), "history", settings.get("fallbackEnabled", True)
            )
            history = source.load_history(code, limit=lookback, is_index=False)
            data_as_of = save_market_bars(code, history)
            return GridOptimizeOut(
                code=code,
                profile=profile,
                dataAsOf=data_as_of,
                history=history,
                candidates=optimize_grid(
                    history,
                    payload.capital,
                    payload.feeBps,
                    payload.mode,
                    profile["securityType"],
                    profile["exchange"],
                    max(0, min(payload.settlementDays, 5)),
                    max(0, min(payload.slippageBps, 100)),
                    price_limit_ratio(code),
                ),
            )
        except Exception as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc

    @app.get("/api/grid/strategies")
    def grid_strategies(workspace_id: str = Query(default="default", alias="workspace")) -> GridStrategiesOut:
        try:
            return GridStrategiesOut(strategies=list_grid_strategies(workspace_id))
        except Exception as exc:
            raise api_error(503, ERR_STORAGE_UNAVAILABLE, str(exc)) from exc

    @app.patch("/api/grid/strategies/{strategy_id}")
    def update_grid_strategy_status(
        strategy_id: str, payload: GridStatusPut, workspace_id: str = Query(default="default", alias="workspace")
    ) -> dict:
        try:
            strategy = get_grid_strategy(strategy_id)
            if not strategy or strategy["workspaceId"] != workspace_id:
                raise api_error(404, ERR_NOT_FOUND, "策略不存在")
            strategy.update(
                {
                    key: value
                    for key, value in payload.model_dump(exclude_unset=True).items()
                    if key in {"status", "schedule"}
                }
            )
            saved = save_grid_strategy(strategy, workspace_id)
            schedule_strategy(saved)
            return saved
        except HTTPException:
            raise
        except Exception as exc:
            raise api_error(503, ERR_STORAGE_UNAVAILABLE, str(exc)) from exc

    @app.delete("/api/grid/strategies/{strategy_id}")
    def delete_strategy(strategy_id: str, workspace_id: str = Query(default="default", alias="workspace")) -> DeleteOut:
        try:
            if not delete_grid_strategy(strategy_id, workspace_id):
                raise api_error(404, ERR_NOT_FOUND, "策略不存在")
            unschedule_strategy(strategy_id)
            return DeleteOut(deleted=True, id=strategy_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise api_error(503, ERR_STORAGE_UNAVAILABLE, str(exc)) from exc

    @app.post("/api/strategy/preview")
    def strategy_preview(payload: StrategyPreviewIn) -> StrategyPreviewOut:
        try:
            strategy_type = payload.strategyType
            engine = STRATEGY_ENGINES.get(strategy_type)
            if not engine:
                raise api_error(422, ERR_VALIDATION_ERROR, f"未知策略类型：{strategy_type}")
            config = payload.config
            suggestion = {}
            for field in engine["configSchema"]:
                key = field["key"]
                if key not in config:
                    suggestion[key] = field.get("default")
            return StrategyPreviewOut(
                strategyType=strategy_type,
                suggestion=suggestion,
                note="已应用该策略类型的默认参数，可手动调整后回测。",
            )
        except Exception as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc

    @app.post("/api/strategy/backtest")
    def strategy_backtest(
        payload: StrategyBacktestIn, workspace_id: str = Query(default="default", alias="workspace")
    ) -> StrategyBacktestOut:
        try:
            strategy_type = payload.strategyType
            engine = STRATEGY_ENGINES.get(strategy_type)
            if not engine:
                raise api_error(422, ERR_VALIDATION_ERROR, f"未知策略类型：{strategy_type}")
            code = payload.code
            profile = classify_code(code)
            lookback = max(20, min(payload.lookback, 240))
            history, data_source_flag, data_as_of, _ = _load_history_with_fallback(code, lookback)
            config = payload.config
            config.update(
                {
                    "capital": payload.capital,
                    "feeBps": payload.feeBps,
                    "securityType": profile["securityType"],
                    "exchange": profile["exchange"],
                    "lookback": lookback,
                    "capitalAllocation": payload.capitalAllocation,
                }
            )
            result = engine["backtest"](history, config)
            response = {
                "code": code,
                "profile": profile,
                "history": history,
                "strategyType": strategy_type,
                "config": {**config, "dataAsOf": data_as_of},
                "dataSource": data_source_flag,
                "dataAsOf": data_as_of,
                **result,
            }
            if payload.save:
                strategy = save_strategy(
                    {
                        "id": payload.id or f"strategy-{uuid4().hex}",
                        "code": code,
                        "name": payload.name,
                        "strategyType": strategy_type,
                        "config": config,
                        "capital": config["capital"],
                        "feeBps": config["feeBps"],
                        "schedule": payload.schedule,
                        "status": "启用",
                        "lookback": lookback,
                    },
                    workspace_id,
                )
                save_strategy_backtest(strategy["id"], code, strategy_type, response["config"], result, workspace_id)
                schedule_strategy(strategy)
                response["strategy"] = get_strategy(strategy["id"])
            return StrategyBacktestOut.model_validate(response)
        except HTTPException:
            raise
        except Exception as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc

    @app.get("/api/strategy/strategies")
    def strategy_strategies(workspace_id: str = Query(default="default", alias="workspace")) -> StrategiesOut:
        try:
            return StrategiesOut(strategies=list_strategies(workspace_id))
        except Exception as exc:
            raise api_error(503, ERR_STORAGE_UNAVAILABLE, str(exc)) from exc

    @app.patch("/api/strategy/strategies/{strategy_id}")
    def update_strategy_status(
        strategy_id: str, payload: StrategyStatusPut, workspace_id: str = Query(default="default", alias="workspace")
    ) -> dict:
        try:
            strategy = get_strategy(strategy_id)
            if not strategy or strategy["workspaceId"] != workspace_id:
                raise api_error(404, ERR_NOT_FOUND, "策略不存在")
            strategy.update(
                {
                    key: value
                    for key, value in payload.model_dump(exclude_unset=True).items()
                    if key in {"status", "schedule"}
                }
            )
            saved = save_strategy(strategy, workspace_id)
            schedule_strategy(saved)
            return saved
        except HTTPException:
            raise
        except Exception as exc:
            raise api_error(503, ERR_STORAGE_UNAVAILABLE, str(exc)) from exc

    @app.delete("/api/strategy/strategies/{strategy_id}")
    def remove_strategy(strategy_id: str, workspace_id: str = Query(default="default", alias="workspace")) -> DeleteOut:
        try:
            if not delete_generic_strategy(strategy_id, workspace_id):
                raise api_error(404, ERR_NOT_FOUND, "策略不存在")
            unschedule_strategy(strategy_id)
            return DeleteOut(deleted=True, id=strategy_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise api_error(503, ERR_STORAGE_UNAVAILABLE, str(exc)) from exc

    @app.get("/")
    def index():
        index_file = DIST_DIR / "index.html" if DIST_DIR.exists() else FRONTEND_DIR / "index.html"
        return FileResponse(index_file)

    return app


app = create_app()
