"""组合风险视图 Task 1：交易对关联存储（relatedPlan/exitMode）+ 写路径校验 + 总仓位上限设置。

沿用 test_plan_review.py 端点段既有模式：真实 PostgreSQL + 专用工作区（initialize_storage +
module-level TestClient + workspace 读写助手）；独立文件零共享 fixture。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

import pytest
from backend import app as app_module
from backend import storage as storage_module
from backend.assist.limiter import SlidingWindowLimiter
from backend.plan_review import SHANGHAI, ReviewUpstreamError
from backend.storage import validate_plan_links
from fastapi.testclient import TestClient

# 专用测试工作区，避免覆盖默认工作区真实数据
WS = "pf-ws"


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables():
    storage_module.initialize_storage()


@pytest.fixture(autouse=True)
def _cleanup_test_data():
    yield
    from sqlalchemy import delete

    models = [
        storage_module.WatchlistItem,
        storage_module.TradePlan,
        storage_module.Alert,
        storage_module.WorkspaceState,
    ]
    with storage_module.engine.begin() as connection:
        for model in models:
            connection.execute(delete(model).where(model.workspace_id == WS))


@pytest.fixture()
def workspace_client() -> TestClient:
    # 模块级 app（create_app 产物）；直连真实 PostgreSQL，按 ?workspace= 隔离
    return TestClient(app_module.app)


def put_ws(client: TestClient, plans: list[dict[str, Any]]) -> dict[str, Any]:
    """plans 整表同步保存（workspace PUT 是计划编辑唯一通路）。"""
    response = client.put(
        "/api/workspace",
        params={"workspace": WS},
        json={"watchlist": [], "plans": plans, "alerts": []},
    )
    assert response.status_code == 200, response.text
    return response.json()


def get_ws(client: TestClient) -> dict[str, Any]:
    response = client.get("/api/workspace", params={"workspace": WS})
    assert response.status_code == 200, response.text
    return response.json()


def test_plan_link_roundtrip(workspace_client):
    plans = [
        {
            "id": "b1",
            "code": "600519",
            "direction": "buy",
            "entry": 10,
            "stop": 9.5,
            "target": 11,
            "position": 10,
            "status": "执行中",
            "validity": "30天",
        },
        {
            "id": "s1",
            "code": "600519",
            "direction": "sell",
            "entry": 12,
            "stop": 11.5,
            "target": 13,
            "position": 10,
            "status": "执行中",
            "validity": "30天",
            "relatedPlan": "b1",
            "exitMode": "sell_priority",
        },
    ]
    put_ws(workspace_client, plans)  # 既有 workspace PUT 助手风格
    got = {p["id"]: p for p in get_ws(workspace_client)["plans"]}
    assert got["s1"]["relatedPlan"] == "b1" and got["s1"]["exitMode"] == "sell_priority"
    assert got["b1"]["relatedPlan"] is None  # 键恒在
    assert got["b1"]["exitMode"] is None
    # 解除关联语义：空串 → None（同 source 既有模式）
    plans[1]["relatedPlan"] = ""
    plans[1]["exitMode"] = ""
    put_ws(workspace_client, plans)
    got = {p["id"]: p for p in get_ws(workspace_client)["plans"]}
    assert got["s1"]["relatedPlan"] is None and got["s1"]["exitMode"] is None


def test_link_validation_rejects():
    bad = [{"id": "s1", "direction": "sell", "relatedPlan": "ghost"}]
    assert validate_plan_links(bad)  # 目标不存在 → 返回中文错误串
    assert validate_plan_links([{"id": "s1", "direction": "buy", "relatedPlan": "b2"}])
    # 一 buy 双 sell 关联、自引用、跨 code、目标非 buy → 均非 None；合法链 → None
    assert validate_plan_links(
        [
            {"id": "b1", "code": "600519", "direction": "buy"},
            {"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "b1"},
            {"id": "s2", "code": "600519", "direction": "sell", "relatedPlan": "b1"},
        ]
    )
    assert validate_plan_links([{"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "s1"}])
    assert validate_plan_links(
        [
            {"id": "b1", "code": "000001", "direction": "buy"},
            {"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "b1"},
        ]
    )
    assert validate_plan_links(
        [
            {"id": "x1", "code": "600519", "direction": "sell"},
            {"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "x1"},
        ]
    )
    # 目标已归档 → 非 None（spec §3：目标须非归档）
    assert validate_plan_links(
        [
            {"id": "b1", "code": "600519", "direction": "buy", "status": "已归档"},
            {"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "b1"},
        ]
    )
    # 合法链 → None
    assert (
        validate_plan_links(
            [
                {"id": "b1", "code": "600519", "direction": "buy"},
                {"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "b1", "exitMode": "race"},
            ]
        )
        is None
    )
    # 无任何关联 → None
    assert validate_plan_links([{"id": "b1", "code": "600519", "direction": "buy"}]) is None


def test_dangling_link_error_is_actionable():
    # 裁决补强：删除被关联的 buy（悬空）时错误消息必须指导用户
    msg = validate_plan_links([{"id": "s1", "code": "600519", "direction": "sell", "relatedPlan": "b1"}])
    assert msg is not None
    assert "请先解除关联" in msg


def test_workspace_put_rejects_bad_link_422(workspace_client):
    response = workspace_client.put(
        "/api/workspace",
        params={"workspace": WS},
        json={
            "watchlist": [],
            "plans": [
                {
                    "id": "s1",
                    "code": "600519",
                    "direction": "sell",
                    "entry": 12,
                    "stop": 11.5,
                    "target": 13,
                    "position": 10,
                    "status": "执行中",
                    "validity": "30天",
                    "relatedPlan": "ghost",
                }
            ],
            "alerts": [],
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert "请先解除关联" in detail["error"]
    # 校验在 save 前：被拒写盘不落任何计划
    assert get_ws(workspace_client)["plans"] == []


def test_exit_mode_whitelist(workspace_client):
    # Fix round 1（评审 I-1）：exitMode 四值白名单，写路径整表校验（不限 sell）
    msg = validate_plan_links([{"id": "b1", "code": "600519", "direction": "buy", "exitMode": "banana"}])
    assert msg is not None
    assert "banana" in msg
    assert all(v in msg for v in ("race", "sell_priority", "sell_stop_only", "sell_only"))  # 消息列合法四值
    assert validate_plan_links([{"id": "b1", "code": "600519", "direction": "buy", "exitMode": "x" * 40}])
    # 超长旧路径会走 PG 列宽 500 兜底，现须白名单先行拒绝
    for legal in ("race", "sell_priority", "sell_stop_only", "sell_only"):
        assert validate_plan_links([{"id": "s1", "code": "600519", "direction": "sell", "exitMode": legal}]) is None
    # 空串/缺省=留空≡race（save_workspace or None 映射），恒通过
    assert validate_plan_links([{"id": "s1", "code": "600519", "direction": "sell", "exitMode": ""}]) is None
    assert validate_plan_links([{"id": "s1", "code": "600519", "direction": "sell"}]) is None
    # HTTP：banana PUT → 422 VALIDATION_ERROR 且不落盘
    response = workspace_client.put(
        "/api/workspace",
        params={"workspace": WS},
        json={
            "watchlist": [],
            "plans": [
                {
                    "id": "b1",
                    "code": "600519",
                    "direction": "buy",
                    "entry": 10,
                    "stop": 9.5,
                    "target": 11,
                    "position": 10,
                    "status": "执行中",
                    "validity": "30天",
                    "exitMode": "banana",
                }
            ],
            "alerts": [],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert "离场模式" in response.json()["detail"]["error"]
    assert get_ws(workspace_client)["plans"] == []


def test_total_position_cap_default_and_clamp():
    # I3：设置 +1 键 totalPositionCapPct（int 默认 100，clamp 20..300）
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    assert DEFAULT_WORKSPACE_SETTINGS["totalPositionCapPct"] == 100
    assert _normalize_workspace_settings({})["totalPositionCapPct"] == 100
    assert _normalize_workspace_settings({"totalPositionCapPct": 5})["totalPositionCapPct"] == 20
    assert _normalize_workspace_settings({"totalPositionCapPct": 999})["totalPositionCapPct"] == 300
    assert _normalize_workspace_settings({"totalPositionCapPct": 150.7})["totalPositionCapPct"] == 150


# ---------------------------------------------------------------------------
# Task 6 提交 1：review 端点「per-request source 解析 + _counting + degraded 收集」提取为
# 模块级 _resolve_history_loader()（组合端点复用，行为零变化）。
# 打桩边界与 test_plan_review.py 端点段同款：app_module._load_history_with_fallback +
# storage 缓存读写（fetch_all_bars 函数内 from backend import storage，按属性调用可 patch）。
# ---------------------------------------------------------------------------

client = TestClient(app_module.app)  # 模块级共享；各用例自 monkeypatch，互不残留


def test_resolve_history_loader_counts_and_degrades(monkeypatch):
    """提取物单测：(loader, stats, degraded) 三元组语义——stats 计上游命中，degraded 收 local 兜底码。"""
    seen: list[tuple[str, int, str]] = []

    def fake(code, limit, is_index=False, adjustment="qfq", source=None):
        assert is_index is False
        seen.append((code, limit, adjustment))
        flag = "local" if code == "000001" else "live"
        bar = {"date": "2026-01-05", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 100}
        return [dict(bar)], flag, "2026-01-05", "tencent"

    monkeypatch.setattr(app_module, "_load_history_with_fallback", fake)
    monkeypatch.setattr(storage_module, "load_market_bars", lambda *a, **k: [])
    monkeypatch.setattr(storage_module, "save_market_bars", lambda *a, **k: None)

    loader, stats, degraded = app_module._resolve_history_loader()
    bars_map = loader(["600519", "000001"])
    assert set(bars_map) == {"600519", "000001"}
    assert bars_map["600519"][0]["close"] == 10.2
    assert stats["upstream"] == 2
    assert degraded == ["000001"]  # 仅 local 兜底码入 degraded（顺序=拉取序）
    # bfq 口径 + 300 上限透传（fetch_all_bars 冻结契约）
    assert seen == [("600519", 300, ""), ("000001", 300, "")]


def _review_like_plan() -> dict[str, Any]:
    now_ms = int(datetime.now(SHANGHAI).timestamp() * 1000)
    return {
        "id": "reg-1",
        "code": "600519",
        "direction": "buy",
        "entry": 10.0,
        "stop": 9.5,
        "target": 11.0,
        "validity": "长期",
        "status": "执行中",
        "createdAtMs": now_ms - 10 * 86_400_000,
    }


def _recent_bars(n_from: int = 9, n_to: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "date": (datetime.now(SHANGHAI) - timedelta(days=d)).strftime("%Y-%m-%d"),
            "open": 10.4,
            "high": 11.5,
            "low": 9.9,
            "close": 11.0,
            "volume": 1000,
        }
        for d in range(n_from, n_to, -1)
    ]


def test_review_refactor_regression(monkeypatch, caplog):
    """提取回归钉：复盘端点走真实 review_plans/fetch_all_bars 链路，行为与提取前逐字一致
    （degraded 收集并包 + review_degraded 告警 + feeRate 上限常量收口到 plan_review.FEE_RATE_MAX）。"""
    bars = _recent_bars()

    def fake_local(code, limit, is_index=False, adjustment="qfq", source=None):
        return list(bars), "local", "2026-01-05", "local"

    monkeypatch.setattr(app_module, "get_workspace", lambda *a, **k: {"plans": [_review_like_plan()]})
    monkeypatch.setattr(app_module, "_load_history_with_fallback", fake_local)
    monkeypatch.setattr(storage_module, "load_market_bars", lambda *a, **k: [])
    monkeypatch.setattr(storage_module, "save_market_bars", lambda *a, **k: None)
    caplog.set_level(logging.WARNING)
    r = client.get("/api/plans/review", params={"days": 90})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] == ["600519"] and body["items"][0]["outcome"] == "win"  # 降级不阻断回算
    assert "review_degraded code=600519" in caplog.text
    # 上限常量同源（0.05 字面量 → plan_review.FEE_RATE_MAX）：边界值放行、越界 422（行为零变化）
    assert client.get("/api/plans/review", params={"days": 90, "feeRate": 0.05}).status_code == 200
    assert client.get("/api/plans/review", params={"days": 90, "feeRate": 0.0501}).status_code == 422


# ---------------------------------------------------------------------------
# Task 6 段 2：GET /api/portfolio/risk 端点（校验 / 20 次分护栏 / 取数复用 / 降级与日志）
# 离线取数沿用文件既有手法：monkeypatch app_module.get_workspace / _load_history_with_fallback
# + storage load/save_market_bars（真实链路：_resolve_history_loader → fetch_all_bars → _counting）。
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _portfolio_limiter_headroom(monkeypatch: pytest.MonkeyPatch) -> None:
    """评审 F4：默认 20/60 limiter 是全模块共享实例，真实请求已耗大半——每例先换高容量实例斩断顺序耦合。

    429 例（test_risk_429_after_limit）在体内自换 max=2 小实例，monkeypatch 后写覆盖前写，不受影响。
    """
    monkeypatch.setattr(
        app_module.app.state,
        "portfolio_limiter",
        SlidingWindowLimiter(max_events=1000, window_seconds=60.0),
    )


def _risk_plan(**over: Any) -> dict[str, Any]:
    """可入场/可离线的 buy 计划（position 必填——引擎名义额分配的前提）。"""
    now_ms = int(datetime.now(SHANGHAI).timestamp() * 1000)
    base: dict[str, Any] = {
        "id": "R1",
        "code": "600519",
        "direction": "buy",
        "entry": 10.0,
        "stop": 9.0,
        "target": 11.0,
        "position": 30,
        "validity": "长期",
        "status": "执行中",
        "createdAtMs": now_ms - 12 * 86_400_000,
        "relatedPlan": None,
        "exitMode": None,
    }
    base.update(over)
    return base


def _risk_sell(**over: Any) -> dict[str, Any]:
    now_ms = int(datetime.now(SHANGHAI).timestamp() * 1000)
    base: dict[str, Any] = {
        "id": "S1",
        "code": "600519",
        "direction": "sell",
        "entry": 10.8,
        "stop": 9.0,
        "target": 11.5,
        "position": 30,
        "validity": "长期",
        "status": "执行中",
        "createdAtMs": now_ms - 11 * 86_400_000,
        "relatedPlan": "R1",
        "exitMode": "race",
    }
    base.update(over)
    return base


def _stub_risk_env(
    monkeypatch: pytest.MonkeyPatch,
    plans: list[dict[str, Any]],
    *,
    watchlist: list[str] | None = None,
    bars: list[dict[str, Any]] | None = None,
    flag: str = "live",
    settings: dict[str, Any] | None = None,
) -> None:
    """端点离线桩：工作区 + 历史 loader + 行业缓存（读缓存路径不触网、不触 DB）。"""
    rows = bars if bars is not None else _recent_bars()
    monkeypatch.setattr(app_module, "get_workspace", lambda *a, **k: {"plans": plans, "watchlist": watchlist or []})
    monkeypatch.setattr(
        app_module,
        "get_workspace_settings",
        lambda *a, **k: settings or {"defaultCapital": 100000, "totalPositionCapPct": 100},
    )
    monkeypatch.setattr(app_module, "get_industry_map", lambda: ({}, "empty"))

    def fake(code: str, limit: int, is_index: bool = False, adjustment: str = "qfq", source: Any = None) -> tuple:
        return [dict(b) for b in rows], flag, str(rows[-1]["date"]), "tencent"

    monkeypatch.setattr(app_module, "_load_history_with_fallback", fake)
    monkeypatch.setattr(storage_module, "load_market_bars", lambda *a, **k: [])
    monkeypatch.setattr(storage_module, "save_market_bars", lambda *a, **k: None)


def _spy_bars_loader(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_codes: set[str] | None = None,
    bars: list[dict[str, Any]] | None = None,
) -> list[list[str]]:
    """fetch_all_bars 替身（576c84d 两趟实现的注入点）：逐趟记录 loader 收到的 codes——列表长度即趟数。

    fail_codes 与该趟 codes 有交即抛 ReviewUpstreamError（只抛该趟命中的失败码），其余趟回全 bar。
    """
    rows = bars if bars is not None else _recent_bars()
    boom = fail_codes or set()
    calls: list[list[str]] = []

    def spy(codes: list[str], router: Any) -> dict[str, list[dict[str, Any]]]:
        calls.append(list(codes))
        if boom & set(codes):
            failed = [c for c in codes if c in boom]
            # 与生产 fetch_all_bars 同步的行为（收尾硬化 L1）：失败前已成功的码以 partial 携带。
            partial = {c: [dict(b) for b in rows] for c in codes if c not in boom}
            raise ReviewUpstreamError(failed, partial=partial)
        return {code: [dict(b) for b in rows] for code in codes}

    monkeypatch.setattr("backend.plan_review.fetch_all_bars", spy)
    return calls


def test_risk_happy_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 顶层键（brief 名单）+ nav 五键同源并包 + 默认 days=90/layer=core 档跑通全链。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])
    r = client.get("/api/portfolio/risk")
    assert r.status_code == 200, r.text
    body = r.json()
    assert {
        "kpis",
        "nav",
        "exposure",
        "concentration",
        "pairs",
        "orphans",
        "signals",
        "events",
        "eventsTotal",
        "degraded",
        "meta",
    } <= set(body)
    assert set(body["nav"]) == {"dates", "gross", "net", "feeCum", "feeSum"}  # feeCum/feeSum 端点并包
    assert body["meta"]["layer"] == "core" and body["meta"]["feeRate"] == 0.0015
    assert len(body["kpis"]) == 10 and body["kpis"]["planCount"]["active"] == 1
    assert body["degraded"] == []


def test_risk_empty_plans_zero_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """空计划 → 200 全键零态（键恒在，前端免判空）；空仓 nav 全空数组、navNow null（不造数）。"""
    _stub_risk_env(monkeypatch, [])
    r = client.get("/api/portfolio/risk", params={"days": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"kpis", "nav", "exposure", "concentration", "pairs", "orphans", "signals", "events", "meta"} <= set(body)
    assert body["nav"] == {"dates": [], "gross": [], "net": [], "feeCum": [], "feeSum": 0.0}
    assert body["kpis"]["navNow"] is None and body["kpis"]["pairCount"] == 0
    assert body["pairs"] == [] and body["orphans"] == [] and body["events"] == [] and body["eventsTotal"] == 0
    assert body["degraded"] == []
    assert body["watchIndex"] is None  # withWatch 默认 false → 键恒在 null


def test_risk_start_overrides_days(monkeypatch: pytest.MonkeyPatch) -> None:
    """start 优先：days=30 完全忽略（终审 R4），meta.windowStart 逐字回显 start（评审钉）。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])
    far = (datetime.now(SHANGHAI) - timedelta(days=400)).strftime("%Y-%m-%d")
    r = client.get("/api/portfolio/risk", params={"days": 30, "start": far})
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["windowStart"] == far
    # 窗口 = [start, today) → 全部近期 bar 入轴（400 天窗 vs 30 天窗的判别）
    assert len(r.json()["nav"]["dates"]) == 8


def test_risk_fee_rate_bounds_422(monkeypatch: pytest.MonkeyPatch) -> None:
    """feeRate 域 (0, FEE_RATE_MAX]：0 与负数与上限外一律 422；上限内放行（校验取 I6 同源常量）。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])
    assert client.get("/api/portfolio/risk", params={"feeRate": 0}).status_code == 422
    assert client.get("/api/portfolio/risk", params={"feeRate": -0.1}).status_code == 422
    assert client.get("/api/portfolio/risk", params={"feeRate": 0.0501}).status_code == 422
    ok = client.get("/api/portfolio/risk", params={"feeRate": 0.05})
    assert ok.status_code == 200 and ok.json()["meta"]["feeRate"] == 0.05
    assert ok.json()["nav"]["feeSum"] > 0


def test_risk_429_after_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """20 次/分护栏：换 max=2 小 limiter 实例直发 3 请求（不 monkeypatch 时钟、不真发 20 次，观察 5）。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])
    monkeypatch.setattr(
        app_module.app.state, "portfolio_limiter", SlidingWindowLimiter(max_events=2, window_seconds=60.0)
    )
    assert client.get("/api/portfolio/risk").status_code == 200
    assert client.get("/api/portfolio/risk").status_code == 200
    r = client.get("/api/portfolio/risk")
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "RATE_LIMITED"
    assert int(r.headers["Retry-After"]) >= 1


def test_risk_502_failed_codes(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """上游取数失败 → 502 + detail.failedCodes + atlas.review 留痕（同复盘式，红线：失败可见化）。"""

    def boom(codes: list[str], router: Any) -> dict[str, Any]:
        raise ReviewUpstreamError(list(codes))

    _stub_risk_env(monkeypatch, [_risk_plan()])
    monkeypatch.setattr("backend.plan_review.fetch_all_bars", boom)
    caplog.set_level(logging.ERROR)
    r = client.get("/api/portfolio/risk")
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert detail["code"] == "UPSTREAM_UNAVAILABLE" and detail["failedCodes"] == ["600519"]
    assert "review_upstream_failed" in caplog.text and "600519" in caplog.text


def test_risk_watch_failure_degrades_not_502(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """评审 F1 反例：withWatch 自选码上游硬失败 = 外围失败 → 200 不 502，只并 degraded + review_degraded。

    注入点即两趟实现的接缝：自选码那趟（codes 含外围码）抛 ReviewUpstreamError，计划码趟照常回 bar。
    """
    _stub_risk_env(monkeypatch, [_risk_plan()], watchlist=["300750"])
    passes = _spy_bars_loader(monkeypatch, fail_codes={"300750"})
    caplog.set_level(logging.WARNING)
    r = client.get("/api/portfolio/risk", params={"withWatch": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] == ["300750"] and "600519" not in body["degraded"]  # 只披露外围码，计划码不受染
    assert "review_degraded code=300750" in caplog.text  # 降级不得静默（同复盘留痕）
    assert "review_upstream_failed" not in caplog.text  # 502 路径未被误走
    assert passes == [["600519"], ["300750"]]  # 两趟隔离：自选码绝不混进计划码趟
    assert len(body["nav"]["dates"]) == 8 and body["kpis"]["planCount"]["active"] == 1  # NAV 不被外围拖空
    assert body["watchIndex"] is not None and set(body["watchIndex"]["values"]) == {None}  # 缺 bar 全 null 不造数


def test_risk_watch_partial_absorbed(monkeypatch: pytest.MonkeyPatch) -> None:
    """收尾硬化 L1：同趟部分成功不再整批丢弃——partial 码进 watchIndex，degraded 仅失败码。"""
    _stub_risk_env(monkeypatch, [_risk_plan()], watchlist=["300750", "301234"])
    _spy_bars_loader(monkeypatch, fail_codes={"301234"})
    r = client.get("/api/portfolio/risk", params={"withWatch": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["degraded"] == ["301234"]  # 只披露真失败的码
    wi = body["watchIndex"]
    assert wi is not None and any(v is not None for v in wi["values"])  # 300750 的 bar 未被连坐丢弃


def test_risk_codes_layer_closed_and_watch_spy(monkeypatch: pytest.MonkeyPatch) -> None:
    """评审 F3：codes 集合三规则 + withWatch 生效——spy 记每趟 loader 入参断形状（配对 sell 排除/孤儿纳入/closed 全收）。"""
    plans = [
        _risk_plan(),  # R1 buy 600519
        _risk_sell(id="S2", code="000002", relatedPlan="R1"),  # 已配对 sell（跨码只为让两档集合可判别）
        _risk_sell(id="S3", code="000003", relatedPlan=None, exitMode=None),  # 孤儿 sell：看板信号也要 bar
    ]
    _stub_risk_env(monkeypatch, plans, watchlist=["600036"])
    passes = _spy_bars_loader(monkeypatch)

    core = client.get("/api/portfolio/risk", params={"withWatch": True})
    assert core.status_code == 200, core.text
    # core：配对 sell 码（000002）排除、孤儿 sell 码（000003）恒在；自选码独立第二趟
    assert passes == [["600519", "000003"], ["600036"]]
    assert core.json()["meta"]["layer"] == "core"

    passes.clear()
    closed = client.get("/api/portfolio/risk", params={"layer": "closed", "withWatch": True})
    assert closed.status_code == 200, closed.text
    assert passes == [["600519", "000002", "000003"], ["600036"]]  # closed：全部 sell 码入第一趟，自选仍隔离


def test_risk_422_days_whitelist(monkeypatch: pytest.MonkeyPatch) -> None:
    """days 白名单 0/30/90/180/365：45 不在档 → 422 中文 detail；180/365 组合端点新增档放行。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])
    r = client.get("/api/portfolio/risk", params={"days": 45})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR" and "days" in detail["error"]
    assert client.get("/api/portfolio/risk", params={"days": 180}).status_code == 200
    assert client.get("/api/portfolio/risk", params={"days": 365}).status_code == 200


def test_risk_422_start_window_and_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """评审 F3 校验矩阵补洞：start 上界（today+1）／下界（today−1826）双向越界与非法月日一律 422；闭区间下界放行。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])
    now = datetime.now(SHANGHAI)
    too_late = (now + timedelta(days=1)).strftime("%Y-%m-%d")  # 当日/未来不可作起点（ceiling=today−1）
    too_early = (now - timedelta(days=1826)).strftime("%Y-%m-%d")  # 下界 floor=today−1825（5 年）
    for bad in (too_late, too_early, "2026/13/01"):
        r = client.get("/api/portfolio/risk", params={"start": bad})
        assert r.status_code == 422, bad
        detail = r.json()["detail"]
        assert detail["code"] == "VALIDATION_ERROR" and "start" in detail["error"]
    floor_in = (now - timedelta(days=1825)).strftime("%Y-%m-%d")
    assert client.get("/api/portfolio/risk", params={"start": floor_in}).status_code == 200  # 边界闭区间放行


def test_risk_422_layer_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    """layer 域 core/closed：复盘合法的 "both" 之类一律 422（组合端点新增档不外溢），detail 文案点出合法域。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])
    for bad in ("both", "CORE", ""):
        r = client.get("/api/portfolio/risk", params={"layer": bad})
        assert r.status_code == 422, bad
        detail = r.json()["detail"]
        assert detail["code"] == "VALIDATION_ERROR" and "layer 仅支持 core/closed" in detail["error"]


def test_risk_truncated_at_gate_decoupled(monkeypatch: pytest.MonkeyPatch) -> None:
    """评审 F2：截断门与 days/start 解耦——反例正常窗不产键；正例降 plan_review.BARS_LIMIT 造截断，值=并集轴首日。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])  # 默认 8 根 bar << 300
    ok = client.get("/api/portfolio/risk", params={"days": 90})
    assert ok.status_code == 200, ok.text
    assert "truncatedAt" not in ok.json()["meta"]  # 反例：未被拉满 → 键缺席（与 T5 聚合层缺席钉同源）

    monkeypatch.setattr("backend.plan_review.BARS_LIMIT", 2)  # 公开别名（576c84d F7）：门从 300 降到 2
    far = (datetime.now(SHANGHAI) - timedelta(days=1000)).strftime("%Y-%m-%d")
    long_window = client.get("/api/portfolio/risk", params={"start": far})  # start 长窗：旧 days==0 门在此漏报
    assert long_window.status_code == 200, long_window.text
    body = long_window.json()
    assert body["meta"]["truncatedAt"] == body["nav"]["dates"][0]  # 值=多码并集轴首日（文档化语义）
    assert client.get("/api/portfolio/risk", params={"days": 0}).json()["meta"]["truncatedAt"]  # ALL 档同门在位


def test_risk_degraded_and_log(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """local 兜底一例码 → payload.degraded 含该码（降级不得静默）+ review_degraded 告警留痕（复盘同源）。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])  # 先铺全链桩，再换 per-code flag 的 loader
    rows = _recent_bars()

    def fake(code: str, limit: int, is_index: bool = False, adjustment: str = "qfq", source: Any = None) -> tuple:
        flag = "local" if code == "600519" else "live"
        return [dict(b) for b in rows], flag, str(rows[-1]["date"]), "tencent"

    monkeypatch.setattr(app_module, "_load_history_with_fallback", fake)
    caplog.set_level(logging.WARNING)
    r = client.get("/api/portfolio/risk")
    assert r.status_code == 200, r.text
    assert "600519" in r.json()["degraded"]
    assert "review_degraded code=600519" in caplog.text


def test_risk_nav_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """nav 恒等式三钉（评审要求，同一次 compose_nav 并包才成立）：逐日 gross[i]−net[i]==feeCum[i]、尾==feeSum、首==0。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])
    r = client.get("/api/portfolio/risk")
    assert r.status_code == 200, r.text
    nav = r.json()["nav"]
    gross, net, fee_cum, fee_sum = nav["gross"], nav["net"], nav["feeCum"], nav["feeSum"]
    assert len(gross) == len(net) == len(fee_cum) >= 2
    for i in range(len(gross)):
        assert gross[i] - net[i] == pytest.approx(fee_cum[i], abs=1e-12)
    assert fee_cum[-1] == pytest.approx(fee_sum, abs=1e-12)
    assert fee_cum[0] == 0


def test_risk_portfolio_ok_log(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """成功留痕逐字钉（spec §8）：atlas.review INFO 级 portfolio_ok 行，恰 11 个 k=v 字段且顺序在位。"""
    _stub_risk_env(monkeypatch, [_risk_plan()])
    caplog.set_level(logging.INFO)
    assert client.get("/api/portfolio/risk").status_code == 200
    recs = [rec for rec in caplog.records if "portfolio_ok layer=" in rec.getMessage()]
    assert len(recs) == 1 and recs[0].levelno == logging.INFO and recs[0].name == "atlas.review"
    msg = recs[0].getMessage()
    fields = [tok for tok in msg.split() if "=" in tok]
    assert len(fields) == 11
    assert [f.split("=")[0] for f in fields] == [
        "layer",
        "window",
        "plans",
        "codes",
        "upstream",
        "gross_mdd",
        "net_mdd",
        "scaling",
        "conflicts",
        "degraded",
        "elapsed_ms",
    ]
    # 评审 F5 补强：键序钉之外再钉格式串本身——前缀逐字、空降级哨兵、%.4f 精度（旧计数法对含 = 的值不免疫）
    assert msg.startswith("portfolio_ok layer=core window=90 ")
    assert " degraded=- elapsed_ms=" in msg  # degraded 空 → "-" 哨兵（绝不留空破坏切分）
    assert re.search(r"gross_mdd=-?\d+\.\d{4} net_mdd=-?\d+\.\d{4} scaling=\d+ ", msg) is not None
