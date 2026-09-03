"""观测性验收：跑一次 deep 策略，输出结构化日志（trace_id + stage_timings）。

用法：python scripts/observe_screener.py
"""

from __future__ import annotations

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)


def main() -> int:
    from fastapi.testclient import TestClient

    from backend import app as app_module

    with TestClient(app_module.create_app()) as client:
        strategies = client.get("/api/screener/strategies").json()["strategies"]
        print(f"\n=== 内置策略: {[s['id'] for s in strategies]} ===\n")
        resp = client.post("/api/screener/strategy", json={"strategy": "oversold_bounce", "mode": "deep"})
        print(f"\n=== POST /api/screener/strategy (deep) → {resp.status_code} ===")
        data = resp.json()
        print(f"traceId: {data.get('traceId')}")
        print(f"referenceDate: {data.get('referenceDate')}")
        print(f"provider: {data.get('provider')}  cached: {data.get('cached')}  stale: {data.get('stale')}")
        print(f"elapsedMs: {data.get('elapsedMs')}  total: {data.get('total')}")
        print(f"debug: {data.get('debug')}")
        for row in data.get("rows", [])[:3]:
            print(f"  - {row['code']} {row['name']} score={row.get('score')} factors={ {k: v['value'] for k, v in (row.get('factors') or {}).items()} }")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
