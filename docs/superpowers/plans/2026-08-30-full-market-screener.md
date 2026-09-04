# 全市场选股器实施计划

> **⚠️ 已完成并归档。** 本计划基于旧架构（frontend/app.js + index.html），已在 Pinia/Vite 重构前实施完毕。多数据源 Router 版本的后续改进见 `2026-09-02-full-market-screener-v2.md`。

> **For agentic workers:** Use superpowers:executing-plans (inline) to implement this plan task-by-task.

**Goal:** 基于腾讯全市场排名接口（`getBoardRankList`），将选股器从 50 只精选扩容为全市场分页排序选股器。

**Architecture:** 后端 `data_source.py` 新增 `load_screener_v2()` + `/api/screener/v2` 端点（保留 v1 兼容）；前端选股器视图升级为分页表格 + 排序 + "精选/全市场"切换。

**Tech Stack:** Python / FastAPI, Vue 3 全局构建。验证：pytest（TDD）+ `node --check` + 浏览器手动。

---

### Task 1: 分支准备

- [x] `git flow feature start full-market-screener`

---

### Task 2: 后端（TDD）

**Files:** `backend/data_source.py`, `backend/app.py`, `tests/test_backend_api.py`

- [x] **Step 1: 失败测试**

`tests/test_backend_api.py` 追加：

```python
def test_screener_v2_returns_paginated_results(monkeypatch):
    fake_data = {"data": {"rank_list": [{"code": "sh600519", "name": "贵州茅台", "zxj": "1297.4", "zdf": "0.39", "hsl": "0.13",
        "ltsz": "16218.56", "pe_ttm": "19.92", "pn": "6.46", "turnover": "208601", "zf": "0.77", "lb": "0.54",
        "zdf_d5": "1.93", "zdf_d10": "-3.32", "zdf_d20": "-3.94", "zdf_d60": "4.63", "zdf_w52": "-6.94", "zdf_y": "-3.84",
        "volume": "16126.00", "speed": "0.02", "zd": "5.10", "zsz": "16218.56", "zljlr": "-7495.96",
        "state": "", "stock_type": "GP-A"}], "offset": 0, "total": 4596}}
    import json
    class FakeResponse:
        def json(self): return fake_data
    monkeypatch.setattr("backend.data_source.requests.get", lambda url, params=None, timeout=10: FakeResponse())
    from backend.data_source import load_screener_v2
    result = load_screener_v2(page=1, page_size=10, sort_by="changePct", sort_dir="desc")
    assert result["total"] == 4596
    assert result["page"] == 1
    assert result["pageSize"] == 10
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["code"] == "sh600519"
    assert row["name"] == "贵州茅台"
    assert row["price"] == 1297.4
    assert row["changePct"] == 0.39
    assert row["change"] == 5.10
    assert row["turnoverRate"] == 0.13
    assert row["volumeRatio"] == 0.54
    assert row["peTtm"] is not None
    assert row["amount"] is not None
    assert row["totalMarketCap"] is not None

def test_screener_v2_when_upstream_fails(monkeypatch):
    monkeypatch.setattr("backend.data_source.requests.get", lambda url, params=None, timeout=10: (_ for _ in ()).throw(ConnectionError("timeout")))
    from backend.data_source import load_screener_v2
    import pytest
    with pytest.raises(RuntimeError, match="全市场选股器请求失败"):
        load_screener_v2()

def test_screener_v2_endpoint_returns_proper_shape(monkeypatch):
    fake_data = {"data": {"rank_list": [{"code": "sh600519", "name": "贵州茅台", "zxj": "1297.4", "zdf": "0.39", "hsl": "0.13",
        "ltsz": "16218.56", "pe_ttm": "19.92", "pn": "6.46", "turnover": "208601", "zf": "0.77", "lb": "0.54",
        "zdf_d5": "1.93", "zdf_d10": "-3.32", "zdf_d20": "-3.94", "zdf_d60": "4.63", "zdf_w52": "-6.94", "zdf_y": "-3.84",
        "volume": "16126.00", "speed": "0.02", "zd": "5.10", "zsz": "16218.56", "zljlr": "-7495.96",
        "state": "", "stock_type": "GP-A"}], "offset": 0, "total": 4596}}
    class FakeResponse:
        def json(self): return fake_data
    monkeypatch.setattr("backend.data_source.requests.get", lambda url, params=None, timeout=10: FakeResponse())
    from backend import app as app_module
    from fastapi.testclient import TestClient
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/screener/v2?page=1&pageSize=10&sortBy=changePct&sortDir=desc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4596
    assert data["page"] == 1
    assert len(data["rows"]) == 1
```

- [x] **Step 2: 跑测试确认红**

`python -m pytest tests/test_backend_api.py -q`

- [x] **Step 3: 实现**

`backend/data_source.py` 末尾追加：

```python
SCREENER_V2_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"

_SCREENER_SORT_MAP = {
    "changePct": "price",  # 腾讯按 price 时也返回 zdf
    "amount": "turnover",
    "turnoverRate": "turnover",
    "price": "price",
    "totalMarketCap": "price",
    "peTtm": "price",
}


def _normalize_rank_item(item: dict) -> dict:
    def n(v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return {
        "code": str(item.get("code", "") or str(item.get("_", "")),
        "name": str(item.get("name", "")),
        "price": n(item.get("zxj")),
        "change": n(item.get("zd")),
        "changePct": n(item.get("zdf")),
        "turnoverRate": n(item.get("hsl")),
        "amt": n(item.get("turnover")),
        "volume": n(item.get("volume")),
        "totalMarketCap": n(item.get("zsz")),
        "circulatingMarketCap": n(item.get("ltsz")),
        "peTtm": n(item.get("pe_ttm")),
        "pb": n(item.get("pn")),
        "amplitude": n(item.get("zf")),
        "volumeRatio": n(item.get("lb")),
        "speed": n(item.get("speed")),
        "netMoneyFlow": n(item.get("zljlr")),
    }


def _map_sort_field(sort_by: str) -> str:
    return _SCREENER_SORT_MAP.get(sort_by, "price")


def load_screener_v2(page: int = 1, page_size: int = 50, sort_by: str = "changePct", sort_dir: str = "desc") -> dict:
    params = {
        "board_code": "aStock",
        "sort_type": _map_sort_field(sort_by),
        "direct": "down" if sort_dir == "desc" else "up",
        "offset": str((page - 1) * page_size),
        "count": str(page_size),
    }
    try:
        resp = requests.get(SCREENER_V2_URL, params=params, timeout=10)
        data = resp.json()["data"]
        rows = [_normalize_rank_item(item) for item in data.get("rank_list", [])]
        return {
            "total": data.get("total", 0),
            "page": page,
            "pageSize": page_size,
            "rows": rows,
            "provider": "Tencent rank API",
        }
    except Exception as exc:
        raise RuntimeError(f"全市场选股器请求失败: {exc}") from exc
```

`backend/app.py` 追加端点（`screener` 端点之后）：

```python
    @app.get("/api/screener/v2")
    def screener_v2(page: int = Query(default=1, ge=1), pageSize: int = Query(default=50, alias="pageSize", ge=1, le=200),
                    sortBy: str = Query(default="changePct", alias="sortBy"), sortDir: str = Query(default="desc", alias="sortDir")):
        try:
            from backend.data_source import load_screener_v2
            return load_screener_v2(page=page, page_size=pageSize, sort_by=sortBy, sort_dir=sortDir)
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc), "provider": "Tencent rank API"})
```

- [x] **Step 4: 跑测试确认绿 + 提交**

`python -m pytest tests/ -q` → 全绿。

```bash
git add backend/data_source.py backend/app.py tests/
git commit -m "feat: 全市场选股器腾讯排名接口与分页端点"
```

---

### Task 3: 前端选股器升级

**Files:** `frontend/app.js`, `frontend/index.html`, `frontend/styles.css`, `frontend/index.html`（app.js version bump）

- [x] **Step 1: app.js 新增状态与函数**

- `screenerViewMode` ref: `'featured'`（精选 50） | `'all'`（全市场）
- `screenerPage` ref, `screenerTotal` ref, `screenerSortBy` ref, `screenerSortDir` ref
- `screenerRows` ref（全市场数据）
- `fetchScreenerV2(page, sortBy, sortDir)` 函数
- `toggleScreenerMode()` / `screenerPageUp()` / `screenerPageDown()` / `screenerSort(column)` 函数
- return 导出所有新 ref 与函数

- [x] **Step 2: index.html 升级选股器视图**

- 顶部加切换标签：「精选 50」/「全市场」
- 全市场模式下：
  - 表格表头加排序箭头（代码/名称/最新价/涨跌幅/成交额/换手率/市值/PE/量比/振幅/主力资金）
  - 底部加分页器（上一页/下一页/页码指示/总条数）
  - 表头点击触发排序（正序/倒序切换）
- 精选模式下保持现有内容不变

- [x] **Step 3: styles.css 追加样式**

- `.screener-tabs` / `.screener-tab` 切换标签样式
- `.screener-sort` 排序箭头
- `.pagination` 分页器样式
- `.screener-search` 搜索框

- [x] **Step 4: 验证 + 提交**

`node --check frontend/app.js` + 模板闭包检查。

```bash
git add frontend/app.js frontend/index.html frontend/styles.css
git commit -m "feat: 选股器升级为全市场分页排序与精选切换"
```

---

### Task 4: 回归、验证与收尾

- [x] **Step 1: 全量回归**

`python -m pytest tests/ -q` + `node --check frontend/app.js` → 全绿。

- [x] **Step 2: 浏览器手动验证**

- 选股器出现「精选 50」/「全市场」切换标签
- 全市场标签下：默认按涨跌幅排序第一页 50 只，分页器可用
- 点击表头列可切换排序（涨跌幅/成交额/换手率/市值等）
- 精选标签下保持原有 50 只不变

- [x] **Step 3: 完成分支**

```bash
git flow feature finish full-market-screener
```