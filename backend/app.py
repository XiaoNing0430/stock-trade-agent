from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.util import find_spec
import time
from pathlib import Path
from uuid import uuid4

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from backend.data_source import apply_runtime_config, classify_code, load_history, load_market, load_screener, price_limit_ratio, recent_stale
from backend.grid_strategy import backtest_grid, optimize_grid, suggest_grid
from backend.grid_scheduler import schedule_strategy, start_scheduler, stop_scheduler, unschedule_strategy
from backend.storage import (
    delete_grid_strategy,
    delete_strategy as delete_generic_strategy,
    DEFAULT_WORKSPACE_SETTINGS,
    get_workspace,
    get_workspace_revision,
    get_workspace_settings,
    get_grid_strategy,
    get_strategy,
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
from backend.strategy_engines import STRATEGY_ENGINES

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"


def _load_history_with_fallback(code: str, limit: int, is_index: bool = False) -> tuple[list, str, str | None]:
    """优先实时行情；上游失败时降级读取本地 market_bars 持久化历史。返回 (history, dataSource, dataAsOf)。"""
    try:
        history = load_history(code, limit=limit, is_index=is_index)
        data_as_of = save_market_bars(code, history)
        return history, "live", data_as_of
    except Exception:
        bars = load_market_bars(code, limit=limit)
        if not bars:
            raise
        return bars, "local", bars[-1]["date"]


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
                )
            except Exception:
                pass
        yield
        stop_scheduler()

    app = FastAPI(title="Atlas Stock Trade Agent", lifespan=lifespan)
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.middleware("http")
    async def stale_header_middleware(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            marker = recent_stale(window=2.0)
            if marker:
                response.headers["X-Atlas-Stale"] = f"{int(marker['age'])}"
        return response

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "provider": "Tencent public quote API",
            "serverTime": int(time.time() * 1000),
            "mode": "separated",
            "universeSize": 50,
            "storage": storage_status(),
        }

    @app.get("/api/workspace")
    def workspace(workspace_id: str = Query(default="default", alias="workspace")):
        try:
            return get_workspace(workspace_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": f"持久化存储不可用: {exc}"}) from exc

    @app.put("/api/workspace")
    def update_workspace(
        payload: dict = Body(...),
        workspace_id: str = Query(default="default", alias="workspace"),
        base_revision: int | None = Query(default=None, alias="baseRevision"),
        force: bool = Query(default=False),
    ):
        try:
            current = get_workspace_revision(workspace_id)
            if base_revision is not None and base_revision != current and not force:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "其他页面已更新工作区数据", "revision": current, "workspace": get_workspace(workspace_id)},
                )
            return save_workspace(payload, workspace_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": f"持久化存储不可用: {exc}"}) from exc

    @app.get("/api/settings")
    def settings(workspace_id: str = Query(default="default", alias="workspace")):
        try:
            data = get_workspace_settings(workspace_id)
        except Exception:
            data = dict(DEFAULT_WORKSPACE_SETTINGS)
        akshare_installed = find_spec("akshare") is not None
        tushare_installed = find_spec("tushare") is not None
        tushare_configured = bool(getattr(__import__("backend.settings", fromlist=["get_settings"]).get_settings(), "tushare_token", ""))
        return {"data": data, "sources": [
                {"id": "tencent", "name": "腾讯公开行情", "realtime": True, "history": True, "screener": True, "available": True},
                {"id": "akshare", "name": "AkShare", "realtime": False, "history": True, "screener": True, "available": False, "installed": akshare_installed, "reason": "暂未支持切换，适配器开发中" if akshare_installed else "未安装 AkShare"},
                {"id": "tushare", "name": "Tushare", "realtime": False, "history": True, "screener": True, "available": False, "installed": tushare_installed, "tushareConfigured": tushare_configured, "reason": "暂未支持切换，适配器开发中" if tushare_configured else "未配置 TUSHARE_TOKEN"},
            ]}

    @app.put("/api/settings")
    def update_settings(payload: dict = Body(...), workspace_id: str = Query(default="default", alias="workspace")):
        try:
            saved = save_workspace_settings(payload, workspace_id)
            apply_runtime_config(
                timeout_seconds=saved.get("timeoutSeconds"),
                retry_count=saved.get("retryCount"),
                cache_seconds=saved.get("cacheSeconds"),
            )
            return {"data": saved}
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": f"设置保存失败: {exc}"}) from exc

    @app.get("/api/market")
    def market(codes: str = Query(default="")):
        try:
            return load_market(codes.split(",") if codes else [])
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc), "provider": "Tencent public quote API"})

    @app.get("/api/history")
    def history(code: str = Query(default="600519"), index: bool = Query(default=False)):
        try:
            history, data_source_flag, data_as_of = _load_history_with_fallback(code, 120, is_index=index)
            return {
                "code": code,
                "provider": "Tencent public quote API",
                "fetchedAt": int(time.time() * 1000),
                "history": history,
                "dataSource": data_source_flag,
                "dataAsOf": data_as_of,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc), "provider": "Tencent public quote API"})

    @app.get("/api/screener")
    def screener(market: str = Query(default="全部"), pageSize: int = Query(default=300, alias="pageSize")):
        try:
            payload = load_screener(market, pageSize)
            payload["provider"] = "Tencent public quote API"
            payload["fetchedAt"] = int(time.time() * 1000)
            return payload
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc), "provider": "Tencent public quote API"})

    @app.get("/api/screener/v2")
    def screener_v2(page: int = Query(default=1, ge=1), pageSize: int = Query(default=50, alias="pageSize", ge=1, le=200),
                    sortBy: str = Query(default="changePct", alias="sortBy"), sortDir: str = Query(default="desc", alias="sortDir")):
        try:
            from backend.data_source import load_screener_v2
            return load_screener_v2(page=page, page_size=pageSize, sort_by=sortBy, sort_dir=sortDir)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc), "provider": "Tencent rank API"})

    @app.post("/api/grid/preview")
    def grid_preview(payload: dict = Body(...)):
        try:
            code = str(payload["code"])
            profile = classify_code(code)
            grid_count = max(2, min(int(payload.get("gridCount", 8)), 30))
            history, data_source_flag, data_as_of = _load_history_with_fallback(code, max(20, min(int(payload.get("lookback", 120)), 240)))
            return {"code": code, "profile": profile, "dataAsOf": data_as_of, "dataSource": data_source_flag, "history": history, "suggestion": suggest_grid(history, grid_count, float(payload.get("capital", 100000)), str(payload.get("mode", "classic")))}
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc

    @app.post("/api/grid/backtest")
    def grid_backtest(payload: dict = Body(...), workspace_id: str = Query(default="default", alias="workspace")):
        try:
            code = str(payload["code"])
            profile = classify_code(code)
            lookback = max(20, min(int(payload.get("lookback", 120)), 240))
            history, data_source_flag, data_as_of = _load_history_with_fallback(code, lookback)
            capital = float(payload.get("capital", 100000))
            fee_bps = float(payload.get("feeBps", 3))
            grid_count = max(2, min(int(payload.get("gridCount", 8)), 30))
            mode = str(payload.get("mode", "classic"))
            settlement_days = max(0, min(int(payload.get("settlementDays", 1)), 5))
            slippage_bps = max(0, min(float(payload.get("slippageBps", 5)), 100))
            suggestion = suggest_grid(history, grid_count, capital, mode)
            lower = float(payload.get("lower") or suggestion["lower"])
            upper = float(payload.get("upper") or suggestion["upper"])
            limit_pct = price_limit_ratio(code)
            result = backtest_grid(history, lower, upper, grid_count, capital, fee_bps, mode, profile["securityType"], profile["exchange"], settlement_days, slippage_bps, limit_pct)
            response = {"code": code, "profile": profile, "history": history, "config": {"lower": lower, "upper": upper, "gridCount": grid_count, "capital": capital, "feeBps": fee_bps, "lookback": lookback, "mode": mode, "settlementDays": settlement_days, "slippageBps": slippage_bps, "priceLimitPct": limit_pct * 100, "dataAsOf": data_as_of}, **result}
            if payload.get("save"):
                strategy = save_grid_strategy({"id": payload.get("id") or f"grid-{uuid4().hex}", "code": code, "name": payload.get("name"), "lower": lower, "upper": upper, "gridCount": grid_count, "capital": capital, "feeBps": fee_bps, "mode": mode, "lookback": lookback, "settlementDays": settlement_days, "slippageBps": slippage_bps, "schedule": payload.get("schedule", "manual"), "status": "启用"}, workspace_id)
                save_grid_backtest(strategy["id"], code, response["config"], result, workspace_id)
                schedule_strategy(strategy)
                response["strategy"] = get_grid_strategy(strategy["id"])
            return response
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc

    @app.post("/api/grid/optimize")
    def grid_optimize(payload: dict = Body(...)):
        try:
            code = str(payload["code"])
            profile = classify_code(code)
            lookback = max(20, min(int(payload.get("lookback", 120)), 240))
            history = load_history(code, limit=lookback)
            data_as_of = save_market_bars(code, history)
            return {"code": code, "profile": profile, "dataAsOf": data_as_of, "history": history, "candidates": optimize_grid(history, float(payload.get("capital", 100000)), float(payload.get("feeBps", 3)), str(payload.get("mode", "classic")), profile["securityType"], profile["exchange"], max(0, min(int(payload.get("settlementDays", 1)), 5)), max(0, min(float(payload.get("slippageBps", 5)), 100)), price_limit_ratio(code))}
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc

    @app.get("/api/grid/strategies")
    def grid_strategies(workspace_id: str = Query(default="default", alias="workspace")):
        try:
            return {"strategies": list_grid_strategies(workspace_id)}
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc

    @app.patch("/api/grid/strategies/{strategy_id}")
    def update_grid_strategy_status(strategy_id: str, payload: dict = Body(...), workspace_id: str = Query(default="default", alias="workspace")):
        try:
            strategy = get_grid_strategy(strategy_id)
            if not strategy or strategy["workspaceId"] != workspace_id:
                raise HTTPException(status_code=404, detail={"error": "策略不存在"})
            strategy.update({key: value for key, value in payload.items() if key in {"status", "schedule"}})
            saved = save_grid_strategy(strategy, workspace_id)
            schedule_strategy(saved)
            return saved
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc

    @app.delete("/api/grid/strategies/{strategy_id}")
    def delete_strategy(strategy_id: str, workspace_id: str = Query(default="default", alias="workspace")):
        try:
            if not delete_grid_strategy(strategy_id, workspace_id):
                raise HTTPException(status_code=404, detail={"error": "策略不存在"})
            unschedule_strategy(strategy_id)
            return {"deleted": True, "id": strategy_id}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc

    @app.post("/api/strategy/preview")
    def strategy_preview(payload: dict = Body(...)):
        try:
            strategy_type = str(payload.get("strategyType", ""))
            engine = STRATEGY_ENGINES.get(strategy_type)
            if not engine:
                raise HTTPException(status_code=422, detail={"error": f"未知策略类型：{strategy_type}"})
            config = dict(payload.get("config") or {})
            suggestion = {}
            for field in engine["configSchema"]:
                key = field["key"]
                if key not in config:
                    suggestion[key] = field.get("default")
            return {
                "strategyType": strategy_type,
                "suggestion": suggestion,
                "note": "已应用该策略类型的默认参数，可手动调整后回测。",
            }
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc

    @app.post("/api/strategy/backtest")
    def strategy_backtest(payload: dict = Body(...), workspace_id: str = Query(default="default", alias="workspace")):
        try:
            strategy_type = str(payload.get("strategyType", ""))
            engine = STRATEGY_ENGINES.get(strategy_type)
            if not engine:
                raise HTTPException(status_code=422, detail={"error": f"未知策略类型：{strategy_type}"})
            code = str(payload["code"])
            profile = classify_code(code)
            lookback = max(20, min(int(payload.get("lookback", 120)), 240))
            history, data_source_flag, data_as_of = _load_history_with_fallback(code, lookback)
            config = dict(payload.get("config") or {})
            config.update({
                "capital": float(payload.get("capital", 100000)),
                "feeBps": float(payload.get("feeBps", 3)),
                "securityType": profile["securityType"],
                "exchange": profile["exchange"],
                "lookback": lookback,
            })
            result = engine["backtest"](history, config)
            response = {"code": code, "profile": profile, "history": history, "strategyType": strategy_type, "config": {**config, "dataAsOf": data_as_of}, "dataSource": data_source_flag, "dataAsOf": data_as_of, **result}
            if payload.get("save"):
                strategy = save_strategy({"id": payload.get("id") or f"strategy-{uuid4().hex}", "code": code, "name": payload.get("name"), "strategyType": strategy_type, "config": config, "capital": config["capital"], "feeBps": config["feeBps"], "schedule": payload.get("schedule", "manual"), "status": "启用", "lookback": lookback}, workspace_id)
                save_strategy_backtest(strategy["id"], code, strategy_type, response["config"], result, workspace_id)
                schedule_strategy(strategy)
                response["strategy"] = get_strategy(strategy["id"])
            return response
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc

    @app.get("/api/strategy/strategies")
    def strategy_strategies(workspace_id: str = Query(default="default", alias="workspace")):
        try:
            return {"strategies": list_strategies(workspace_id)}
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc

    @app.patch("/api/strategy/strategies/{strategy_id}")
    def update_strategy_status(strategy_id: str, payload: dict = Body(...), workspace_id: str = Query(default="default", alias="workspace")):
        try:
            strategy = get_strategy(strategy_id)
            if not strategy or strategy["workspaceId"] != workspace_id:
                raise HTTPException(status_code=404, detail={"error": "策略不存在"})
            strategy.update({key: value for key, value in payload.items() if key in {"status", "schedule"}})
            saved = save_strategy(strategy, workspace_id)
            schedule_strategy(saved)
            return saved
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc

    @app.delete("/api/strategy/strategies/{strategy_id}")
    def remove_strategy(strategy_id: str, workspace_id: str = Query(default="default", alias="workspace")):
        try:
            if not delete_generic_strategy(strategy_id, workspace_id):
                raise HTTPException(status_code=404, detail={"error": "策略不存在"})
            unschedule_strategy(strategy_id)
            return {"deleted": True, "id": strategy_id}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()
