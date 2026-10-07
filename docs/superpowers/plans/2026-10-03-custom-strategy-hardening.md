# 自定义策略编辑器硬化（审计修复）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development。步骤用 checkbox（`- [ ]`）跟踪。

**背景：** 2026-10-03 对已合入 `develop` 的自定义策略编辑器做逐条 spec 审计，发现 1 个可复现缺陷 + 1 处 spec 违背 + 2 处契约缺口。本计划只做硬化，不加新功能。

**审计证据（复现记录）：**
- 清空数字输入框（Vue `.number` → `''`）→ 提交 `{"quickFilters":{"pe":["",null]}}` → 服务端 422 `float_parsing` 英文报错。
- 409 分支 `applyRow(server)` 覆盖用户本地输入，且同段注释写「不覆盖本地输入」；spec 两处要求「不自动覆盖本地编辑」。
- name 100 字符 / description 400 字符在 SQLite 下 200；模型列为 `String(64)`/`String(256)`，真库 PG 会 DataError → 被兜成 502 而非 422。
- 422 `detail.error` 为 pydantic 英文原文（含 errors.pydantic.dev 链接）。

## 冻结决策

1. **空数值语义**：`''` 一律「视为未填」，绝不猜数。
   - `quick_filters` 边界：`''` → `None`；两侧皆空 → 整键不发（UI 语义「留空 = 不设限」）。
   - `topN` / `deepCap`：`''` → 省略键，服务端既有默认（10 / 200）生效。
   - 因子 `period` / `weight`：`''` → 省略键，服务端既有默认（14 / 1.0）生效。
   - 因子 `threshold`：无默认值（必填）→ 前端内联中文校验「第 N 条因子的阈值不能为空」，**不提交**；后端 `''` → 中文 422。
2. **中文 422**：loader 校验器消息改中文；storage 捕获 `ValidationError` 后映射首条错误为中文，`detail.error` 不再含 pydantic 英文与链接；`detail.code` 保持 `VALIDATION_ERROR`。
3. **长度上界**：`ScreenerStrategyConfig.name` ≤ 64、`description` ≤ 256（对齐 DB 列），越界 → 422（而非真库 502）。
4. **409 语义**：保留用户本地编辑，只用服务器行刷新 `form.version`；横幅展示服务器最新版本与名称供对照。绝不整体覆盖表单。
5. **范围**：不动管道核心、不动删除事务语义、不动扫描联动；P3 观察项（`sort_by` 白名单、`custom` 角标、`customStrategies` 冗余状态、`sourceBuiltin` 恒空、合并列表静默吞异常）只记 backlog，不在本批改。

## Tasks

### Task 1: 后端测试先行（RED）
- Modify: `tests/test_custom_strategies.py`
- 用例：
  - `test_custom_strategy_api_put_delete_invalidate_cache`——假 pipeline 进 `app._strategy_pipeline["p"]`，断言 PUT/DELETE 各调用一次 `invalidate_strategy(id)`。
  - `test_custom_strategy_delete_logs_config_snapshot`——caplog 断言 `atlas.screener` 记录含 `screener.custom_strategy_deleted` 与完整 config 快照。
  - `test_pipeline_custom_strategy_equals_builtin`——复用 `test_screener_pipeline.py` 的 FakeRouter 夹具：把 `oversold_bounce` 配置存为自定义策略，断言 `deep` 模式结果与内置逐行等价，且两 id 缓存互不串（各自 cached 行为独立）。
  - `test_custom_strategy_api_normalizes_empty_numeric_strings`——`{"pe":["",null]}` / `topN:""` / 因子 `period:""`、`weight:""` → 200 且落库为未填语义。
  - `test_custom_strategy_api_rejects_empty_threshold_with_chinese_detail`——因子 `threshold:""` → 422 中文。
  - `test_custom_strategy_api_rejects_overlong_name_and_description`——name 100 / description 400 → 422。
  - `test_custom_strategy_api_422_detail_has_no_pydantic_english`——未知因子名 422 文案为中文且不含 `errors.pydantic.dev`。

### Task 2: 后端实现（GREEN）
- Modify: `backend/screener/loader.py`——校验器中文消息；`name`/`description` 长度上界；`_normalize` 前处理把 `''` 视为缺省。
- Modify: `backend/storage.py`——新增 `_chinese_validation_error`；`_custom_strategy_config` 捕获 `ValidationError` 转中文 `ValueError`。
- Modify: `backend/schemas.py`——`CustomStrategyIn.topN/deepCap/version` 前处理把 `''` 视为 None（否则 FastAPI 请求模型层会先抛英文 422，路由与 api_error 契约都走不到）。

### Task 3: 前端测试先行（RED）
- Modify: `tests/frontend/ViewScreener.test.ts`
- 用例：
  - 清空 `市盈率最小值` → payload `quickFilters` 不含 `pe`、`topN` 省略键（不再是 `""`）。
  - 因子 `阈值` 清空 → 内联中文错误、不发 POST。
  - 409 → 本地输入保留 + `version` 刷为服务器值（第二次保存携带新 version）。
  - 422 → 展示后端中文 detail。
  - 自定义策略名含 HTML → option 文本为原文、页面无 `img` 元素（无 `v-html`）。

### Task 4: 前端实现（GREEN）
- Modify: `frontend/src/components/CustomStrategyDialog.vue`——`normalizeNumber()`；payload 组装归一；409 只刷 version；因子阈值内联校验。

### Task 5: 门禁 + 文档 + finish
- 全量：`ruff check` / `ruff format --check` / `mypy backend` / `npx vue-tsc --noEmit` / `npx vitest run` / `python -m pytest tests/`（覆盖率 ≥80）。
- 文档：spec 同步（列表接口 `scanReferences` 改按需、409 语义澄清）；ROADMAP/AGENTS 记录；P3 观察项进 ROADMAP backlog。
- `git flow feature finish custom-strategy-hardening`。

## 验收清单

- [x] 后端 7 个新用例先 RED 后 GREEN，且原有 15 个用例不回归。
  - RED 证据：4 个新行为用例按预期失败（`''` → `int_parsing`/`float_parsing` 英文 422；name 65 字符 200；未知因子英文 422）；
    3 个 characterization 用例（失效接线/删除日志/管道等价）当时即通过（补的是覆盖缺口，非行为驱动）。
  - GREEN 证据：`tests/test_custom_strategies.py` + `tests/test_screener_loader.py` + `tests/test_screener_pipeline.py` 43 passed。
- [x] 前端 5 个新用例先 RED 后 GREEN，且原 227 项不回归。
  - RED 证据：3 个新行为用例失败（`expected { pe: ['', null] } to deeply equal {}`；阈值留空竟发出 3 次请求；`expected '服务器名2' to be '本地输入'`）；
    2 个 characterization 用例（422 展示/文本插值）当时即通过。
  - GREEN 证据：`ViewScreener.test.ts` 22 passed；全量 `npx vitest run` 232 passed / 21 文件。
- [x] 空数字输入不再产生 `""`；阈值留空有中文提示且不提交。
- [x] 409 保留本地编辑且可重试成功（version 已刷新：第二次 PUT 携带 v8）。
- [x] 越界 name/description → 422；422 `detail.error` 全中文、无 pydantic 链接。
- [x] 自查：`git diff --stat` 仅触及 `backend/{schemas.py,screener/loader.py,storage.py}`、
  `frontend/src/components/CustomStrategyDialog.vue`、两个测试文件、三份文档 + 本计划，无其它模块行为变更。

## 门禁证据（2026-10-03）

- `python -m ruff check backend tests server.py` → All checks passed
- `python -m ruff format --check backend tests server.py` → 89 files already formatted
- `python -m mypy backend` → Success: no issues found in 53 source files
- `npx eslint .` → 0 errors（1629 warnings 为仓库既有基线）
- `npx vue-tsc --noEmit` → exit 0
- `npx prettier --check`（改动文件）→ All matched files use Prettier code style
- `npx vitest run` → 21 files / 232 tests passed
- `python -m pytest tests/` → 634 passed，覆盖率 92.95%（≥80 门槛）

