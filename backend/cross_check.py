"""日线最新收盘跨源校验（只读、默认关闭）。"""
from __future__ import annotations

import hashlib
import random
import threading
from dataclasses import dataclass
from datetime import date
from typing import Any

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
    result = CrossStats(None, 0, [], [], 0, "disabled") if not provider else CrossStats(provider, 0, [], [], 0, "degraded")
    with _lock:
        _last = result.as_dict()
    return result
