"""日线最新收盘跨源校验（只读、默认关闭）。"""
from __future__ import annotations

import hashlib
import random
import threading
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests
from sqlalchemy import select

from backend import storage
from backend.data_source import classify_code

_lock = threading.Lock()
_last: dict[str, Any] | None = None


@dataclass
class CrossStats:
    provider: str | None
    sampled: int
    mismatched: list[str]
    missing: list[str]
    skipped_suspended: int
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "sampled": self.sampled, "mismatched": len(self.mismatched), "missing": len(self.missing), "skippedSuspended": self.skipped_suspended, "status": self.status}


def last_result() -> dict[str, Any] | None:
    with _lock:
        return dict(_last) if _last else None


def compare_rows(local: dict[str, tuple[float | None, float | None]], provider: dict[str, tuple[float | None, float | None]]) -> CrossStats:
    mismatched: list[str] = []
    missing: list[str] = []
    skipped = 0
    for code, (close, volume) in local.items():
        row = provider.get(code)
        if row is None:
            missing.append(code)
            continue
        pclose, pvol = row
        if pclose is None:
            skipped += 1
            continue
        if close is None or abs(float(close) - float(pclose)) > max(abs(float(close or 0)) * 0.001, 0.011):
            mismatched.append(code)
            continue
        if volume and pvol and abs(float(volume) - float(pvol)) / abs(float(volume)) > 0.01:
            mismatched.append(code)
    return CrossStats(None, len(local), mismatched, missing, skipped, "ok")


def sample_codes(codes: list[str], anchors: list[str] | None = None, day: str | None = None, limit: int = 30) -> list[str]:
    anchors = anchors or []
    seed = int(hashlib.sha256((day or date.today().isoformat()).encode()).hexdigest()[:12], 16)
    rest = [c for c in dict.fromkeys(codes) if c not in anchors]
    random.Random(seed).shuffle(rest)
    return list(dict.fromkeys(anchors + rest))[:limit]


def run(provider: str | None = None, *, date: str | None = None, sleep: Any = None) -> CrossStats:
    global _last
    if not provider:
        result = CrossStats(None, 0, [], [], 0, "disabled")
    else:
        try:
            with storage.SessionLocal() as session:
                rows = session.execute(select(storage.MarketBar.code, storage.MarketBar.close, storage.MarketBar.volume).where(storage.MarketBar.adjustment == "")).all()
            local = {str(code): (close, volume) for code, close, volume in rows}
            selected = sample_codes(list(local), day=date, limit=30)
            provider_rows = fetch_eastmoney(selected) if provider == "eastmoney" else fetch_tushare(selected)
            result = compare_rows({code: local[code] for code in selected}, provider_rows)
            result.provider = provider
        except Exception:
            result = CrossStats(provider, 0, [], [], 0, "degraded")
    with _lock:
        _last = result.as_dict()
    return result


def fetch_eastmoney(codes: list[str]) -> dict[str, tuple[float | None, float | None]]:
    secids = ",".join(("1." if classify_code(code)["exchange"] == "上交所" else "0.") + code for code in codes)
    response = requests.get("http://push2.eastmoney.com/api/qt/ulist.np/get", params={"fltt": 2, "invt": 2, "fields": "f2,f5,f12", "secids": secids}, timeout=10)
    response.raise_for_status()
    diff = ((response.json().get("data") or {}).get("diff") or [])
    return {str(row.get("f12")): (row.get("f2"), row.get("f5")) for row in diff if row.get("f12")}


def fetch_tushare(codes: list[str]) -> dict[str, tuple[float | None, float | None]]:
    import tushare as ts

    from backend.settings import get_settings
    token = get_settings().tushare_token
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    frame = ts.pro_api(token).daily(trade_date=date.today().strftime("%Y%m%d"))
    wanted = set(codes)
    return {str(row.ts_code).split(".")[0]: (float(row.close), float(row.vol) * 100) for row in frame.itertuples() if str(row.ts_code).split(".")[0] in wanted}
