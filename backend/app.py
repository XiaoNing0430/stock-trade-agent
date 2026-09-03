from __future__ import annotations

import time
from contextlib import asynccontextmanager
from importlib.util import find_spec
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from backend.data_source import (
    apply_runtime_config,
    classify_code,
    price_limit_ratio,
    recent_stale,
)
from backend.grid_scheduler import schedule_strategy, start_scheduler, stop_scheduler, unschedule_strategy
from backend.grid_strategy import backtest_grid, optimize_grid, suggest_grid
from backend.schemas import (
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
    ScreenerOut,
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
from backend.sources import get_all_sources_info
from backend.storage import (
    DEFAULT_WORKSPACE_SETTINGS,
    delete_grid_strategy,
    get_grid_strategy,
    get_strategy,
    get_workspace,
    get_workspace_revision,
    get_workspace_settings,
    initialize_storage,
    list_grid_strategies,
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


def api_error(status_code: int, code: str, message: str, **extras) -> HTTPException:
    """统一错误构造：detail = {"error": message, "code": code, **extras}。"""
    return HTTPException(status_code=status_code, detail={"error": message, "code": code, **extras})


ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"


def _load_history_with_fallback(code: str, limit: int, is_index: bool = False) -> tuple[list, str, str | None, str]:
    """优先所选历史源；上游失败时降级读取本地 market_bars 持久化历史。返回 (history, dataSource, dataAsOf, provider)。"""
    from backend.sources import build_router

    settings = get_workspace_settings("default")
    router = build_router()
    try:
        source = router.route_with_fallback(
            settings.get("historySource", "tencent"), "history", settings.get("fallbackEnabled", True)
        )
        history = source.load_history(code, limit=limit, is_index=is_index)
        data_as_of = save_market_bars(code, history)
        return history, "live", data_as_of, source.provider_label
    except Exception:
        bars = load_market_bars(code, limit=limit)
        if not bars:
            raise
        return bars, "local", bars[-1]["date"], "local"


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            initialize_storage()
            start_scheduler()
            app.state.storage_ready = True
        except Exception as exc:
            app.state.storage_ready = False
            app.state.storage_error = str(exc)
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
        yield
        stop_scheduler()

    app = FastAPI(title="Atlas Stock Trade Agent", lifespan=lifespan)
    # 双轨托管：优先服务构建产物 frontend/dist（Vite），无 dist 时回退源码目录。
    # Vite 产物把静态资源放在 dist/assets/ 下，挂载目录按实际布局选择。
    assets_dir = DIST_DIR / "assets" if DIST_DIR.exists() else FRONTEND_DIR
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

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
            return WorkspaceOut.model_validate(save_workspace(payload.model_dump(exclude_unset=True), workspace_id))
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
        tushare_configured = bool(
            getattr(__import__("backend.settings", fromlist=["get_settings"]).get_settings(), "tushare_token", "")
        )
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
            return SettingsPutOut(data=saved)
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
            history, data_source_flag, data_as_of, provider = _load_history_with_fallback(code, 120, is_index=index)
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
