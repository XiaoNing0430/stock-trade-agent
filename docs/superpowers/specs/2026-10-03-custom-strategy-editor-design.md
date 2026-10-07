# 自定义策略编辑器（选股管道策略存 DB）— spec r2

日期：2026-10-03 ｜ 状态：r2 待用户复审（复审通过前不开发）

## 定位与验收标准

本设计验收标准 = **单用户本地量化工具**（与 ROADMAP 非目标红线一致：明确排除多租户/RBAC/TLS/生产级编排）。
评审指出的生产级基线缺失（认证/授权/多租户/审计链/监控告警/备份恢复/API 治理等）属**定位选择而非遗漏**；若未来目标升级为生产级网站，需另立生产级 spec（评审第四节清单已记录在案作为起点），本设计不承载。

## 评审装载记录

2026-10-03 用户评审：按单用户本地标准"设计合理，可进入开发"，P1×3 + P2×5 工程细节要求计划期明确——全部装载如下（P1 进冻结决策，P2 见对应小节）。

## 冻结决策（r1 已有 + 本轮新增标 ★）

- 创建方式：空白新建 + 「从内置复制」预填，两者都提供。
- 扫描联动：自定义策略 id 可被定时扫描引用；扫描开关列表自动包含（来自合并后的策略列表）。
- 删除语义：提示后可删；★删除在**同一事务内**执行（引用复查 + DELETE 原子完成），响应携带删除时点的引用快照，不级联改扫描配置；残留引用的扫描按未知策略失败隔离（FR-13④ 既有容错）。引用完整性不加外键（scan_configs.strategyId 同时指向内置/自定义，多态引用），以事务复查 + 响应快照保证。
- ★乐观锁：config 行带 `version`（自增整数）。PUT 必须携带读取时的 `version`，不匹配 → 409（detail 含服务器最新行，复用工作区修订锁约定），前端提示冲突且**不自动覆盖**。
- ★执行资源上界（叠加既有机制）：
  - 因子条数 ≤ 20（新增校验）；
  - weight ∈ [0.01, 100]（校验收紧）；threshold 必须有限值且 |threshold| ≤ 1e6（拒绝 NaN/±inf）；
  - 既有机制引用：deep_cap ≤ 1000、top_n ≤ 100、精筛阶段 deadline（默认 45s / 上限 300s，既有）——单次运行计算量 = 1000 码 × ≤20 因子，有界；扫描侧单策略异常失败隔离（既有 FR-13④）。不新增第二套超时机制。
- 命名空间：自定义 id 服务端生成 `custom_<12hex>`；解析顺序 = 内置文件优先（防碰撞安全网）→ 自定义 DB。
- 校验：存储前后均经既有 `ScreenerStrategyConfig` pydantic 校验；新增白名单——因子 `name` ∈ `FactorLibrary.available_factors()`（7 因子）；`quick_filters` 字段 ∈ {pe, pb, turnoverRate, changePct, amount}（未知字段会因行值缺失静默全滤，挡在保存前）。
- 红线不变：无未来函数（reference_date 截断）、缓存键含策略 id、限频/降级/可观测沿用管道既有机制，零改管道核心。

## 数据模型

新表 `screener_custom_strategies`（Alembic 前向迁移）：
- `id` String(32) PK（`custom_<12hex>`）
- `name` String(64)、`description` String(256)
- `config` JSON（与 configs/*.json 同构：quick_filters/advanced_factors/sort_by/top_n/deep_cap）
- `version` Integer NOT NULL default 1（每次 PUT 成功 +1）
- `source_builtin` String(64) nullable（fork 来源内置 id）
- `created_at` / `updated_at` timestamptz

## API（camelCase；保留既有字段名；错误走既有 api_error 契约 detail.error + detail.code）

- `GET /api/screener/custom-strategies?search=&limit=&offset=` → 名称子串搜索 + 分页（默认 limit 200，updated_at desc；本地单用户量级上限足够）；每项含 `version`；**不含** `scanReferences`（列表瘦身，2026-10-03 计划钉子 #5）
- `GET /api/screener/custom-strategies/{id}` → 单条含完整 `config` 与 `scanReferences`（编辑/删除对话框打开时按需取）
- `POST /api/screener/custom-strategies` → 创建（服务端生成 id 与 version=1；校验失败 422 中文 detail + 机器可读 code）
- `PUT /api/screener/custom-strategies/{id}` → 携带 `version`；成功返回新 version；不匹配 409（新增错误码 `SCREENER_STRATEGY_CONFLICT`，detail 含服务器最新行）
- `DELETE /api/screener/custom-strategies/{id}` → 事务内复查引用并删除；响应含删除时点 `scanReferences` 快照；★删除写结构化日志（含完整 config 快照，硬删除后可凭日志手工重建）
- `GET /api/screener/strategies` → 合并自定义条目（行内加 `custom: true` + `version`），内置行零变化
- `POST /api/screener/strategy` → 零改动（load_strategy 内置优先 → 自定义兜底）
- ★缓存失效：PUT/DELETE 成功后主动失效该策略的进程内管道缓存（quick/deep 及 stale 副本，实现期对齐 `_stale_by_prefix` 机制）；失效失败不阻断写路径，仅日志（下次运行按 TTL 自然过期）

## 前端（ViewScreener 策略标签页）

- 自定义条目（`custom` 角标 + 编辑/删除）；运行入口与内置一致。
- `CustomStrategyDialog.vue`：名称/描述；quick_filters 固定 5 字段行（min/max 可空）；因子动态行（7 因子下拉 + period 2-250 + operator 4 选 + threshold + weight 0.01-100，≤20 行，可增删）；sort_by + top_n(1-100) + deep_cap(1-1000)；「从内置复制」预填；422 中文 detail + code 原样展示；409 冲突提示"策略已被其他页面更新"，**保留本地编辑**，仅以服务器行刷新 `version`（否则重试必然再 409）并在横幅展示服务器最新版本与名称——绝不整体覆盖表单（2026-10-03 硬化）。
- ★XSS 纪律：名称/描述一律 Vue 文本插值（框架自动转义），**禁止 v-html**；与既有 showToast textContent / chartSvg escapeHtml 纪律并列执行。
- `useScreenerStore` 增加 customStrategies 状态与 CRUD 方法；api/client.ts 增对应请求。

## 非目标（防蔓延）

不做自定义新因子/表达式语言；不做策略版本历史/审计链（删除日志单条快照除外）；不做导入导出与多工作区共享；`history_deadline_s` 不进表单；不做软删除（硬删除 + 日志快照）；回测域 `strategies` 表不动；生产级基线（见定位节）全部不在本设计范围。

## 验收

- 存储 CRUD + 规范化 round-trip；白名单/资源上界拒收矩阵（未知因子、未知 quick_filter 字段、>20 因子行、weight 越界、threshold 非有限值 → 422）；
- 乐观锁：version 不匹配 409 + 服务器行回显；匹配则更新且 version+1；
- 删除：事务内引用复查 + 响应快照；删除日志含 config 快照；残留引用扫描按 FR-13④ 失败隔离；
- 缓存失效：PUT/DELETE 后同策略再跑不走旧缓存（离线 monkeypatch 断言失效调用）；
- 列表：search/limit/offset 生效；合并列表形状内置行零变化；
- `load_strategy` 解析顺序（内置优先、custom_ 走 DB、未知 ValueError）；管道跑自定义 id 与内置等价（离线）；
- 前端：表单提交 payload、fork 预填、422/409 展示、名称描述文本插值（无 v-html）。

## 审计硬化记录（2026-10-03，feature/custom-strategy-hardening）

对已合入 `develop` 的实现逐条复核本 spec 后发现并修复（计划：`docs/superpowers/plans/2026-10-03-custom-strategy-hardening.md`）：

1. **空数值输入**：Vue `v-model.number` 清空数字框会写回 `''`（不是 `null`），此前原样提交 → `float_parsing` 英文 422，quick_filters / topN / deepCap / 因子全中。现规定 `''` = 未填：前端归一为 `null`（区间）或省略键（有服务端默认值的字段回落默认）；因子 `threshold` 无默认值 → 前端中文内联拦截（不提交）+ 后端中文 422。后端 `ScreenerStrategyConfig` 亦做同样归一，挡住直接 API 调用。
2. **409 语义**：原实现 `applyRow(server)` 整体覆盖用户本地编辑，且代码注释与行为相反。现只刷新 `form.version` 并保留本地输入。
3. **文本上界**：`name ≤ 64` / `description ≤ 256`（对齐 DB 列宽）。此前越界在真库 PG 会 DataError → 被兜成 502，现为 422。
4. **422 文案**：loader 校验器消息改中文 + storage 把 pydantic 首条错误映射为中文（形如 `因子 #1 阈值：…`），`detail.code` 保持 `VALIDATION_ERROR`，不再回显 pydantic 英文样板与 errors.pydantic.dev 链接。
5. **补齐测试**：PUT/DELETE 缓存失效接线、删除日志含 config 快照、管道跑自定义 id 与内置策略等价（含缓存键隔离）、前端 422 展示与文本插值（无 v-html）。

**未纳入本批**（记入 ROADMAP backlog）：`sort_by` 白名单、列表 `custom` 角标、`customStrategies` 冗余状态、`sourceBuiltin` 由 UI 提交、合并列表静默吞 DB 故障时缺日志、FastAPI 请求模型校验错误的响应契约形状。
