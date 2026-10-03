# 自定义策略编辑器（选股管道策略存 DB）

日期：2026-10-03 ｜ 状态：待用户审核（审核通过前不开发）

## 目标

前端表单创建/编辑自定义选股策略（quick_filters 区间、因子条件与权重、排序截断参数），存 PostgreSQL；可立即在策略页手动运行，并可被 P1 定时扫描引用。内置 JSON 策略保持只读不动。

## 冻结决策（用户已裁定 + 实现约定）

- **创建方式**：空白新建 + 「从内置复制」预填，两者都提供。
- **扫描联动**：自定义策略 id 可被定时扫描引用；扫描开关列表自动包含（来自合并后的策略列表）。
- **删除语义**：提示后可删——删除前展示引用该策略的扫描配置，确认后删除；不级联改扫描配置，残留引用的扫描按未知策略失败隔离（FR-13④ 既有容错，日志+history 如实 failed）。
- **命名空间**：自定义 id 由服务端生成 `custom_<12hex>`（uuid4），与内置 id 无冲突可能；解析顺序 = 内置文件优先（防碰撞安全网）→ 自定义 DB。
- **校验**：存储前后均经既有 `ScreenerStrategyConfig` pydantic 校验；本次新增两条白名单校验（内置配置天然合法，不受影响）：
  - 因子 `name` ∈ `FactorLibrary.available_factors()`（7 因子：rsi/ma_slope/ma_arrange/bollinger_pos/momentum/deviation/volume_surge）；
  - `quick_filters` 字段 ∈ {pe, pb, turnoverRate, changePct, amount}（管道行数值字段；未知字段会因行值缺失静默全滤，必须挡在保存前）。
- **红线不变**：无未来函数（reference_date 截断）、缓存键含策略 id、限频/降级/可观测全部沿用管道既有机制，零改管道核心。

## 数据模型

新表 `screener_custom_strategies`（Alembic 前向迁移）：
- `id` String(32) PK（`custom_<12hex>`）
- `name` String(64)、`description` String(256)
- `config` JSON（完整 ScreenerStrategyConfig 形状，与 configs/*.json 同构：quick_filters/advanced_factors/sort_by/top_n/deep_cap）
- `source_builtin` String(64) nullable（fork 来源内置 id）
- `created_at` / `updated_at` timestamptz

## API（camelCase 面向前端；保留既有字段名）

- `GET /api/screener/custom-strategies` → 列表（含每项 `scanReferences`：引用它的扫描配置 id 列表，供删除确认）
- `POST /api/screener/custom-strategies` → 创建（服务端生成 id，校验失败 422 中文 detail）
- `PUT /api/screener/custom-strategies/{id}` → 更新
- `DELETE /api/screener/custom-strategies/{id}` → 删除（响应含已删 id；引用提示由 GET 列表的 scanReferences 承担，前端确认）
- `GET /api/screener/strategies` → **合并**自定义策略（行内加 `custom: true`），内置行为零变化——扫描开关与策略下拉自动覆盖自定义
- `POST /api/screener/strategy` → 零改动：`load_strategy(id)` 扩展为内置优先、自定义兜底，管道/扫描自动可跑自定义 id

## 前端（ViewScreener 策略标签页）

- 策略列表出现自定义条目（`custom` 角标 + 编辑/删除按钮）；运行入口与内置一致。
- 新增 `CustomStrategyDialog.vue` 编辑器对话框：
  - 名称/描述；quick_filters 固定 5 字段行（每行 min/max，可空=不设限）；
  - 因子动态行：因子下拉（7 选）+ period(2-250) + operator(>/</≥/≤) + threshold + weight(>0)，可增删；
  - sort_by 下拉 + top_n(1-100) + deep_cap(1-1000)；
  - 「从内置复制」下拉预填；校验失败 422 中文 detail 原样展示。
- `useScreenerStore` 增加 customStrategies 状态与 CRUD 方法；api/client.ts 增对应请求。

## 非目标（防蔓延）

- 不做自定义新因子/表达式语言（只能组合既有 7 因子）；不做策略版本历史/审计链；不做导入导出与多工作区共享；`history_deadline_s` 不进表单（保持默认 45s）；回测域 `strategies` 表不动。

## 验收

- 存储 CRUD + 规范化 round-trip；两条白名单校验拒收矩阵（未知因子/未知 quick_filter 字段 → 422）；
- `load_strategy` 解析顺序（内置优先、custom_ 前缀走 DB、未知 id ValueError）；管道跑自定义 id 与内置行为等价（离线 monkeypatch）；
- 扫描引用：scan config 可指向 custom id 并跑通（离线）；删除后残留引用按 FR-13④ 失败隔离；
- API 回归：合并列表形状（内置行零变化）、创建/更新/删除/引用提示；
- 前端：对话框表单提交 payload 正确、fork 预填、422 错误展示、列表合并渲染。
