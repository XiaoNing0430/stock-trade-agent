from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.data_source import load_history, load_market, load_screener

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"


def create_app() -> FastAPI:
    app = FastAPI(title="Atlas Stock Trade Agent")
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "provider": "Tencent public quote API",
            "serverTime": int(time.time() * 1000),
            "mode": "separated",
            "universeSize": 50,
        }

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

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()

