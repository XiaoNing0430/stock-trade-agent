"""策略定时扫描：去重引擎 + 编排 + 调度注册（spec 2026-09-07，方案 A）。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("screener.scan")


def merge_hits(
    prev_hits: list[dict[str, Any]], rows: list[dict[str, Any]], today: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """跌出再报去重（FR-4）：返回 (新进入命中, 新滞留状态)。

    - 新进入：当前 rows 中存在、prev 中不存在的代码，firstSeen=today
    - 滞留：两轮都在，保留原 firstSeen、更新 name/score
    - 跌出：prev 有、rows 无 → 从状态中移除（下次再进算新）
    """
    prev_by_code = {str(p.get("code")): p for p in prev_hits if p.get("code")}
    new_state: list[dict[str, Any]] = []
    newly: list[dict[str, Any]] = []
    for row in rows:
        code = row.get("code")
        if not code:
            continue
        code = str(code)
        entry = {"code": code, "name": str(row.get("name") or ""), "score": row.get("score")}
        prev_entry = prev_by_code.pop(code, None)
        if prev_entry is None:
            entry["firstSeen"] = today
            newly.append(entry)
        else:
            entry["firstSeen"] = str(prev_entry.get("firstSeen") or today)
        new_state.append(entry)
    return newly, new_state
