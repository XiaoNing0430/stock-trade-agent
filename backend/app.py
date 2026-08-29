from __future__ import annotations

from contextlib import asynccontextmanager
from importlib.util import find_spec
import time
from pathlib import Path
from uuid import uuid4

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.data_source import apply_runtime_config, classify_code, load_history, load_market, load_screener, price_limit_ratio
from backend.grid_strategy import backtest_grid, optimize_grid, suggest_grid
from backend.grid_scheduler import schedule_strategy, start_scheduler, stop_scheduler, unschedule_strategy
from backend.storage import (
    delete_grid_strategy,
    DEFAULT_WORKSPACE_SETTINGS,
    get_workspace,
    get_workspace_settings,
    get_grid_strategy,
    initialize_storage,
    list_grid_strategies,
    save_grid_backtest,
    save_grid_strategy,
    save_market_bars,
    save_workspace,
    save_workspace_settings,
    storage_status,
)

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"


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
    def update_workspace(payload: dict = Body(...), workspace_id: str = Query(default="default", alias="workspace")):
        try:
            return save_workspace(payload, workspace_id)
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
            return {
                "code": code,
                "provider": "Tencent public quote API",
                "fetchedAt": int(time.time() * 1000),
                "history": load_history(code, is_index=index),
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

    @app.post("/api/grid/preview")
    def grid_preview(payload: dict = Body(...)):
        try:
            code = str(payload["code"])
            profile = classify_code(code)
            grid_count = max(2, min(int(payload.get("gridCount", 8)), 30))
            history = load_history(code, limit=max(20, min(int(payload.get("lookback", 120)), 240)))
            data_as_of = save_market_bars(code, history)
            return {"code": code, "profile": profile, "dataAsOf": data_as_of, "history": history, "suggestion": suggest_grid(history, grid_count, float(payload.get("capital", 100000)), str(payload.get("mode", "classic")))}
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc

    @app.post("/api/grid/backtest")
    def grid_backtest(payload: dict = Body(...), workspace_id: str = Query(default="default", alias="workspace")):
        try:
            code = str(payload["code"])
            profile = classify_code(code)
            lookback = max(20, min(int(payload.get("lookback", 120)), 240))
            history = load_history(code, limit=lookback)
            data_as_of = save_market_bars(code, history)
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

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()
