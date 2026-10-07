# 自定义策略编辑器 实现计划（spec r2 已评审通过）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 选股管道自定义策略存 DB：CRUD API + 乐观锁 + 白名单/资源上界校验 + 管道/扫描零改动联动 + 前端编辑器对话框。

**Architecture:** 新表 `screener_custom_strategies`（version 乐观锁）；`load_strategy` 内置优先→自定义兜底（管道/扫描零改动）；进程内管道缓存按 `screener:{id}:{mode}:{market}` 前缀主动失效；扫描配置 id 即 strategyId，引用查询与 DELETE 同事务。

**评审六条实现细节的落地钉子：**
1. 乐观锁原子性 = 单条 `UPDATE ... WHERE id=:id AND version=:expected`，rowcount==0 → 409（SQLite/PG 通用，不用 RETURNING）。
2. 删除事务 = `SessionLocal.begin()` 单事务内 `SELECT`（PG 加 `with_for_update()`，SQLite 方言自动忽略）复查引用 + DELETE；引用表 `screener_scan_configs.id == strategy_id`。
3. 缓存键清单 = `screener:{id}:quick:{market}` 与 `screener:{id}:deep:{market}`（进程内 dict，TTL `_cache_ttl_s`）；失效 = `ScreenerPipeline.invalidate_strategy(id)` 按前缀 pop；不涉 L2（D6：screener 不进 Redis）。
4. 合并列表形状：内置行字段集断言不变（id/name/description/sortBy/topN/deepCap/factorCount）；自定义行 = 同字段 + `custom: true` + `version`；合并列表不分页（内置 2 行 + 自定义 ≤200 由 custom 列表分页兜底）。
5. scanReferences 按需：列表接口**不含**引用；`GET /{id}` 单条含 `scanReferences`（编辑/删除对话框打开时按需取）；DELETE 响应永远带事务内快照。
6. 删除日志 = logger `screener.custom_strategy`，INFO 级，`extra={"action": "deleted", "strategyId": ..., "snapshot": {完整 config JSON}}`；保留随本地日志轮转。

## Tasks

### Task 1: 存储层——模型/迁移/CRUD（原子乐观锁 + 事务删除）
- Modify: `backend/storage.py`（模型 + `upsert_custom_strategy` / `get_custom_strategy` / `list_custom_strategies` / `delete_custom_strategy` / `CustomStrategyConflict`）
- Create: `backend/migrations/versions/` 新迁移（down_revision=p3pit20260918）
- Test: `tests/test_custom_strategies.py`（sqlite 内存库 pattern 同 test_p3_snapshots）
- 接口：`upsert_custom_strategy(data: dict, expected_version: int | None) -> dict`（None=创建，id 服务端生成；冲突抛 `CustomStrategyConflict(current_row_dict)`）；`delete_custom_strategy(id) -> dict | None`（含 scanReferences 快照）；`list_custom_strategies(search="", limit=200, offset=0) -> (rows, total)`。

### Task 2: 校验加严——loader/factors
- Modify: `backend/screener/loader.py`（ScreenerFactorSpec：name 白名单、weight ge=0.01 le=100、threshold 有限值 |≤1e6；ScreenerStrategyConfig：quick_filters 键白名单、advanced_factors ≤20）
- Test: `tests/test_custom_strategies.py`（拒收矩阵 + 内置 configs 回归）

### Task 3: 解析顺序 + 管道失效
- Modify: `backend/screener/loader.py::load_strategy`（内置优先 → `storage.get_custom_strategy` 兜底）；`backend/screener/pipeline.py::invalidate_strategy(id)`
- Test: 解析顺序 / 未知 id / 失效前缀 pop

### Task 4: API——CRUD 四端点 + 合并列表 + 409/422
- Modify: `backend/schemas.py`（CustomStrategyIn/Out）、`backend/app.py`（端点 + 合并 + 失效接线）
- Test: `tests/test_custom_strategies.py`（round-trip/409/422/分页搜索/合并形状断言）

### Task 5: 扫描联动
- Test: upsert_scan_config 接受 custom id、`_scan_config_out` 名称解析走自定义、删除后隔离
- Modify: 仅在扫描保存存在内置白名单时放开（预计零改动）

### Task 6: 前端 store + client
- Modify: `frontend/src/api/client.ts`、`frontend/src/stores/useScreenerStore.ts`
- Test: `tests/frontend/ViewScreener.test.ts` 或新增 store 测试

### Task 7: 前端 UI——CustomStrategyDialog.vue + 列表合并渲染
- Create: `frontend/src/components/CustomStrategyDialog.vue`
- Modify: `frontend/src/views/ViewScreener.vue`
- Test: 表单 payload、fork 预填、422/409 展示、文本插值

### Task 8: 门禁 + 文档 + finish
- AGENTS/ROADMAP 收口；npm run verify + ruff/mypy；feature finish + push
