# 全市场选股器实施计划（Phase 2 — 多数据源版）

> **For agentic workers:** Use superpowers:executing-plans (inline) to implement this plan task-by-task.
> 本文档取代 `2026-08-30-full-market-screener.md`（该版基于旧架构 frontend/app.js + index.html，已完成并合入 develop）。

**Goal:** 全市场选股器接入多数据源 Router：`/api/screener/v2` 按 `screenerSource` 设置选源（腾讯排名 / 东财 clist），EastMoneySource 补齐分页排序能力。

**前置状态（Phase 1 已合入 develop，537ddeb 之前）：**
- `load_screener_v2()`（腾讯排名接口 + 缓存）与 `/api/screener/v2` 端点已存在
- 前端 `useScreenerStore` 已有 `screenerMode`（featured/all）、分页、排序、切换
- `ViewScreener.vue` 已有「精选 50 / 全市场」双模式 UI
- 多数据源接入已完成（`backend/sources/` Router + 适配器，2026-09-02 合入）

**Phase 2 差距（本计划范围）：**
1. `/api/screener/v2` 固定调用 `backend.data_source.load_screener_v2`，不经过 Router，不跟随 `screenerSource` 设置
2. `EastMoneySource.load_screener` 只支持单页（`pn=1`），clist 接口原生的 `pn/pz/fid/po` 分页排序参数未暴露
3. 两源返回 shape 不同：腾讯 v2 返回 `{total, page, pageSize, rows, provider}`；东财返回 `{total, rows, universeSize}`

**Tech Stack:** Python / FastAPI, Vue 3 + Pinia + TS 5.9。验证：pytest（TDD）+ vitest + vue-tsc + npm run build。

---

### Task 1: EastMoneySource 分页排序能力（TDD）

**Files:** `backend/sources/eastmoney.py`, `tests/test_sources_eastmoney.py`

- **Step 1: 失败测试** — `test_load_screener_paged_maps_params`：mock `_http_get`，断言 clist 参数 `pn=页码`、`pz=页大小`、`fid` 按排序字段映射（f3 涨跌幅 / f6 成交额 / f8 换手率 / f20 总市值 / f9 PE）、`po` 按 sort_dir；断言返回 `{total, page, pageSize, rows, provider}` shape。
- **Step 2: 失败测试** — `test_load_screener_paged_normalizes_rows`：mock 返回 diff 列表，断言行字段与 `_parse_quote` 一致。
- **Step 3: 实现** — `EastMoneySource.load_screener_paged(page, page_size, sort_by, sort_dir) -> dict`：

```python
_EM_SORT_MAP = {"changePct": "f3", "amount": "f6", "turnoverRate": "f8", "totalMarketCap": "f20", "peTtm": "f9", "price": "f2"}

def load_screener_paged(self, page: int = 1, page_size: int = 50, sort_by: str = "changePct", sort_dir: str = "desc") -> dict[str, Any]:
    params = {"fltt": 2, "invt": 2, "fid": _EM_SORT_MAP.get(sort_by, "f3"),
              "po": 1 if sort_dir == "desc" else 0, "np": 1, "pn": page, "pz": page_size,
              "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "fields": _CLIST_FIELDS}
    data = self._http_get(self.CLIST_URL, params)
    payload = data.get("data") or {}
    rows = [q for raw in payload.get("diff", []) if (q := self._parse_quote(raw)) is not None]
    return {"total": int(payload.get("total", 0)), "page": page, "pageSize": page_size,
            "rows": rows, "provider": self.provider_label}
```

- **Step 4:** `python -m pytest tests/test_sources_eastmoney.py -q` 绿；ruff format；提交 `feat: EastMoneySource 分页排序选股（clist paged）`。

---

### Task 2: DataSourceRouter 扩展 paged screener 能力

**Files:** `backend/sources/base.py`, `backend/sources/tencent.py`, `backend/sources/router.py`, `tests/test_sources_router.py`

- **Step 1: 失败测试** — `Capability` 增加 `"paged_screener"`；TencentSource `load_screener_paged` 委托 `tencent_ds.load_screener_v2(page, page_size, sort_by, sort_dir)`；router 测试验证按能力位路由。
- **Step 2: 实现** — `TencentSource.capabilities` 加 `paged_screener`，新增方法；EastMoneySource 同步加能力位与 Task 1 方法。
- **Step 3:** pytest 绿；提交 `feat: paged_screener 能力位 + 腾讯委托`。

---

### Task 3: `/api/screener/v2` 接入 Router

**Files:** `backend/app.py`, `tests/test_backend_api.py`

- **Step 1: 失败测试** — mock `get_workspace_settings`（默认设置），mock `backend.data_source.load_screener_v2`，断言 `/api/screener/v2` 走腾讯；settings `screenerSource="eastmoney"` 时走东财（mock EastMoneySource.load_screener_paged）；上游失败返回 502。
- **Step 2: 实现** — 端点改为：

```python
settings = get_workspace_settings("default")
source = build_router().route_with_fallback(settings.get("screenerSource", "tencent"), "paged_screener", settings.get("fallbackEnabled", True))
payload = source.load_screener_paged(page=page, page_size=pageSize, sort_by=sortBy, sort_dir=sortDir)
payload["fetchedAt"] = int(time.time() * 1000)
```

- **Step 3:** 全量 pytest 绿；提交 `feat: /api/screener/v2 接入 DataSourceRouter`。

---

### Task 4: 前端兼容与回归

**Files:** `frontend/src/stores/useScreenerStore.ts`, `tests/frontend/ViewScreener.test.ts`

- **Step 1:** 检查 `fetchScreenerAll` 对 `payload.total / payload.rows / payload.fetchedAt` 的使用 — Task 3 已保证 shape 一致，无需改动则记录验证结论。
- **Step 2:** vitest + vue-tsc + `npm run build` 全绿。
- **Step 3:** 手动验证（可选）：切换设置里选股指标来源为东财 → 全市场分页仍工作。

---

### Task 5: 收尾

- 全量回归 `npm run verify`
- ROADMAP「全市场选股器」条目更新（分页/排序/缓存 → 已完成；标注多源）
- `git flow feature finish full-market-screener-v2` → push develop

---

## 非目标

- 不扩展 fs 板块过滤（创业板/科创板细分）
- 不做搜索联想与后端模糊查询（前端现有 search 过滤够用）
- 不做 WebSocket 实时推送
- MockUSSource 不支持 paged_screener（美股模拟源无全 A 股概念）
