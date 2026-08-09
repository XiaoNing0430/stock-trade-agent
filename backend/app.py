from __future__ import annotations

from contextlib import asynccontextmanager
import time
from pathlib import Path
from uuid import uuid4

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.data_source import load_history, load_market, load_screener
from backend.grid_strategy import backtest_grid, optimize_grid, suggest_grid
from backend.grid_scheduler import schedule_strategy, start_scheduler, stop_scheduler
from backend.storage import (
    get_workspace,
    initialize_storage,
    list_grid_strategies,
    save_grid_backtest,
    save_grid_strategy,
    save_workspace,
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

    @app.get("/api/market")
    def market(codes: str = Query(default="")):
        try:
            return load_market(codes.split(",") if codes else [])
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc), "provider": "Tencent public quote API"})

    @app.get("/api/history")
    def history(code: str = Query(default="600519")):
        try:
            return {
                "code": code,
                "provider": "Tencent public quote API",
                "fetchedAt": int(time.time() * 1000),
                "history": load_history(code),
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
            grid_count = max(2, min(int(payload.get("gridCount", 8)), 30))
            history = load_history(code, limit=max(20, min(int(payload.get("lookback", 120)), 240)))
            return {"code": code, "history": history, "suggestion": suggest_grid(history, grid_count, float(payload.get("capital", 100000)), str(payload.get("mode", "classic")))}
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc

    @app.post("/api/grid/backtest")
    def grid_backtest(payload: dict = Body(...), workspace_id: str = Query(default="default", alias="workspace")):
        try:
            code = str(payload["code"])
            lookback = max(20, min(int(payload.get("lookback", 120)), 240))
            history = load_history(code, limit=lookback)
            capital = float(payload.get("capital", 100000))
            fee_bps = float(payload.get("feeBps", 3))
            grid_count = max(2, min(int(payload.get("gridCount", 8)), 30))
            mode = str(payload.get("mode", "classic"))
            suggestion = suggest_grid(history, grid_count, capital, mode)
            lower = float(payload.get("lower") or suggestion["lower"])
            upper = float(payload.get("upper") or suggestion["upper"])
            result = backtest_grid(history, lower, upper, grid_count, capital, fee_bps, mode)
            response = {"code": code, "history": history, "config": {"lower": lower, "upper": upper, "gridCount": grid_count, "capital": capital, "feeBps": fee_bps, "lookback": lookback, "mode": mode}, **result}
            if payload.get("save"):
                strategy = save_grid_strategy({"id": payload.get("id") or f"grid-{uuid4().hex}", "code": code, "name": payload.get("name"), "lower": lower, "upper": upper, "gridCount": grid_count, "capital": capital, "feeBps": fee_bps, "mode": mode, "lookback": lookback, "schedule": payload.get("schedule", "manual"), "status": "启用"}, workspace_id)
                save_grid_backtest(strategy["id"], code, response["config"], result, workspace_id)
                schedule_strategy(strategy)
                response["strategy"] = strategy
            return response
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc

    @app.post("/api/grid/optimize")
    def grid_optimize(payload: dict = Body(...)):
        try:
            code = str(payload["code"])
            lookback = max(20, min(int(payload.get("lookback", 120)), 240))
            history = load_history(code, limit=lookback)
            return {"code": code, "history": history, "candidates": optimize_grid(history, float(payload.get("capital", 100000)), float(payload.get("feeBps", 3)), str(payload.get("mode", "classic")))}
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"error": str(exc)}) from exc

    @app.get("/api/grid/strategies")
    def grid_strategies(workspace_id: str = Query(default="default", alias="workspace")):
        try:
            return {"strategies": list_grid_strategies(workspace_id)}
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": str(exc)}) from exc

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()
