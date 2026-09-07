# SPEC — 策略定时扫描 + 指令推送（P1）

> 日期：2026-09-07 ｜ 状态：评审稿 ｜ 分支：（评审通过后从 develop 拉 feature/strategy-scan-alerts）
> 前置：交易辅助闭环已交付（`POST /api/assist/plan-draft` + PlanDraftDialog，见 2026-09-04-trade-assist-loop-spec.md）。本 spec 在其上增加「无人值守命中发现」一环。

## 1. 背景与目标

当前策略选股管道需要用户手动打开策略实验室运行；收盘后可能出现的信号（新命中代码）无人发现。

**目标**：已启用的策略在收盘后自动扫描，命中通过提醒中心推送给用户；用户点击代码 → 用**当时最新行情**重算草案 → 人工确认落计划。闭环变为：

```
定时扫描（服务端） → 提醒中心（前端合成） → 点击代码片 → 草案对话框（看时重算） → 人工确认 → 计划
```

**产品红线不变**：扫描绝不自动写计划、绝不连券商；草案永远经用户确认（同 trade-assist spec §非目标）。

## 2. 用户故事

1. 我在策略实验室把「趋势突破」打开定时扫描（quick 模式）→ 收盘后 15:40 系统自动扫描 → 提醒中心出现「扫描命中」提醒，列出新增代码 → 我点击代码片 → 草案对话框弹出（最新价、最新 ATR/MA20 止损）→ 确认落入计划。
2. 连续多日命中同一只票 → 只在它**首次进入**命中列表那天提醒；跌出榜单后再命中才重新提醒（不刷屏）。
3. 上游数据源故障导致某次扫描失败 → 其他策略照常扫描；策略实验室里该策略显示「上次扫描失败」；不产生失败提醒刷屏。
4. 周五停机错过扫描 → 周六 10:00 补扫仍用周五收盘数据补上信号。

## 3. 功能需求

- **FR-1 每策略扫描开关（新表）**：扫描配置存 DB 新表 `screener_scan_configs`（策略选股的策略是包内不可变 JSON，不可加用户状态），字段见 §4.1。默认关闭。
- **FR-2 调度**：APScheduler 两个 cron 任务（Asia/Shanghai）：工作日 `mon-fri 15:40`（避网格回测 15:20 高峰）+ 周末 `sat,sun 10:00` 补扫；`misfire_grace_time=3600`；随 `start_scheduler()` 注册，与现有回测任务同生命周期。
- **FR-3 扫描执行**：顺序遍历已启用配置，逐策略调用 `ScreenerPipeline.run(strategy_id, mode=配置模式, refresh=False)`（复用管道缓存击穿防护/限频/降级，**不自建数据获取路径**）。单策略失败 → 记 `last_status="failed"` + trace 日志，继续下一个（失败隔离）。
- **FR-4 跌出再报去重**：每次扫描成功后，把当前命中代码集写入 `last_hits`（含每码 `first_seen` 日期）。`first_seen` 在代码首次进入命中时设置、滞留期间保持、跌出即清除。提醒内容只含 `first_seen == 本次扫描日` 的新进入代码；无新进入代码则不产生提醒（但仍更新状态）。
- **FR-5 扫描结果端点**：`GET /api/screener/scan/hits` 返回各启用配置的最近一次扫描状态（命中列表含 `firstSeen`、lastRunAt、lastStatus）。**只读服务端状态，零计算**。
- **FR-6 扫描配置端点**：`GET /api/screener/scan/configs`（列表，含策略名）+ `PUT /api/screener/scan/configs`（设置 `{strategyId, enabled, mode}`；校验策略存在于 configs 目录、mode ∈ {quick, deep}，否则 422）。
- **FR-7 手动立即扫描**：`POST /api/screener/scan/now {strategyId}` 同步执行单策略扫描（与请求内运行策略管道同一超时包络；命中更新状态并反映到 /hits），供用户不等到 15:40 试跑。
- **FR-8 前端提醒合成**：提醒中心把 `GET /scan/hits` 的结果合成为提醒项（**不写入 workspace.alerts、不进 workspace 同步**——服务端插入 alerts 表会被客户端下次 PUT 的全量替换语义清除，故走独立端点）。id = `scan:{strategyId}:{code}:{firstSeen}` 天然去重；已读/看过状态存 localStorage（键 `atlas.scan.seen.{strategyId}` = 毫秒时间戳，本地单用户够用）。未读计数并入提醒中心徽标。
- **FR-9 点击流**：提醒中的代码片点击 → `useAssistStore.openFor({ code, name })` → PlanDraftDialog 弹出 → 走既有 plan-draft 端点**看时重算**（entry 空 → 实时行情路径）→ 用户确认 → 既有 confirmDraft 落计划。
- **FR-10 策略实验室 UI**：策略行加「定时扫描」开关（data-testid=`scan-toggle`）+ 模式选择 quick/deep（data-testid=`scan-mode`），随开关持久化到 PUT configs；行内显示上次扫描时间/状态（成功时间或「上次扫描失败」）。
- **FR-11 观测**：每次扫描记录结构化日志（logger `screener.scan`，extra 含 trace_id/strategy_id/mode/命中数/新增数/elapsed_ms/stale）；GET /hits 与策略实验室展示 lastStatus。
- **FR-12 扫描历史摘要**：每次扫描结束追加一行到 `screener_scan_history`（仅摘要：策略/时间/状态/命中数/新增数/耗时，**不存命中明细**），全表滚动保留最近 500 行（插入时清理）。此表直接服务 ROADMAP 下一 P1「计划绩效复盘」的轻量运行留痕需求。
- **FR-13 可靠性护栏**：① Redis 分布式锁（`scan:lock` SET NX PX，TTL 15 分钟，value 为进程唯一 token）保证多进程部署下同一时刻只有一个 worker 执行扫描；**扫描结束 finally 中主动释放**（Lua 比对 value 防误删他人锁），不干等 TTL 到期；Redis 不可用时降级为无锁 + 日志告警；② 单策略扫描失败 → 为**每个**失败策略独立创建 10 分钟后单次重试（APScheduler date-trigger one-shot，job id `scan:retry:{strategyId}`，replace_existing；重试触发时先校验该策略仍 enabled，已关闭则直接跳过不跑管道；重试本身不再武装重试）；③ `EVENT_JOB_MISSED` 监听 → 结构化日志（错过事件可见，不自动补偿，`POST /scan/now` 为人工补偿路径）；④ 状态/历史写入包 try/except → 日志，DB 故障不炸调度线程；⑤ `update_scan_state` 前置校验 `enabled` 仍为 True，扫描中途被关闭则跳过写入并记日志（重试路径天然复用此校验）。

## 4. 契约

### 4.1 数据模型 `screener_scan_configs`（Alembic 迁移，一张新表）

| 列 | 类型 | 说明 |
|---|---|---|
| id | String(96) PK | = strategy_id |
| workspace_id | String(64) index | 默认 "default" |
| enabled | bool | 默认 False |
| mode | String(8) | "quick" \| "deep"，默认 "quick" |
| last_run_at | DateTime(timezone=True) nullable | 最近一次**成功**扫描时间 |
| last_status | String(16) nullable | "ok" \| "failed"（nullable = 从未扫描） |
| last_hits | JSON nullable | `[{"code","name","score","firstSeen"}]`，firstSeen 为 `YYYY-MM-DD` |
| created_at / updated_at | DateTime | |

Storage 助手：`list_scan_configs()` / `get_scan_config(strategy_id)` / `upsert_scan_config(strategy_id, enabled, mode)` / `update_scan_state(strategy_id, status, hits, run_at)`。JSON 读写容错（坏 JSON 视为空）；`last_hits` 结构演进只增不改（新字段可选，旧读取方忽略未知键）。

**`screener_scan_history`**（摘要，FR-12）：

| 列 | 类型 | 说明 |
|---|---|---|
| id | Integer PK autoincrement | |
| strategy_id | String(96) index | |
| run_at | DateTime(timezone=True) index | 扫描结束时间 |
| status | String(16) | "ok" \| "failed" |
| hit_count / new_count | Integer | 滞留命中数 / 新进入数 |
| elapsed_ms | Integer | |
| trace_id | String(16) | 关联日志 |

助手：`insert_scan_history(...)` + 插入后 `DELETE WHERE id NOT IN (取最近 500)` 滚动清理。

### 4.2 API 契约

**GET /api/screener/scan/configs** → `{"configs": [{"strategyId","strategyName","enabled","mode","lastRunAt"(ISO 串或 null),"lastStatus"(null|"ok"|"failed"),"hitCount","newCount"}]}`；`strategyName` 由 `load_strategy` 读取，策略配置不存在 → "（策略已不存在）" 且不参与扫描。

**PUT /api/screener/scan/configs** ← `{strategyId, enabled, mode}` → 200 返回更新后单条（同上形状）。错误：422 `ERR_VALIDATION_ERROR`（未知策略 / 非法 mode / enabled 非 bool）。

**POST /api/screener/scan/now** ← `{strategyId}` → 200 `{"config": <单条同上>, "alerted": <新增命中数>}`；立即扫描**同步执行**（管道 quick 模式与既有 `/api/screener/strategy` 同包络）。错误：422 未知策略；502 `ERR_UPSTREAM_UNAVAILABLE`（管道抛错，last_status 记 failed）。

**GET /api/screener/scan/hits** → `{"hits": [{"strategyId","strategyName","scannedAt"(ISO 或 null),"status","codes": [{"code","name","score","firstSeen"}]}]}`；只含 enabled 配置；`codes` 为**当前滞留命中全集**（含 firstSeen，前端据 firstSeen 与本地 seen 时间戳判定新提示）。只读状态，无 IO 重活。

响应包裹沿用 `/api/strategy/strategies` 风格：顶层键名分组（`configs` / `hits`），不加 `{data}` 层。

### 4.3 扫描提醒项（前端合成，非后端结构）

```ts
{
  id: `scan:${strategyId}:${code}:${firstSeen}`,   // 天然去重键
  kind: 'alert',                                    // 计入「交易」过滤与未读徽标
  title: `扫描命中 · ${strategyName}`,
  message: `${code} ${name}（评分 ${score ?? '--'}）`,
  code, strategyId, firstSeen,                      // firstSeen: 'YYYY-MM-DD'
  createdAtMs: firstSeen 当日 15:40（Asia/Shanghai，纯展示排序用）,
}
```

每个新进入代码一条提醒（跌出再报保证量小）；同一策略一次扫描多个新码 → 多条，共享 title。**不落 alerts 表、不进 workspace PUT 载荷**（反向同步会清除服务端未知行）。

## 5. 调度设计

- 注册点：`grid_scheduler.start_scheduler()` 末尾调用 `register_scan_jobs()`（backend/screener/scan.py），两个 job id：`scan:weekday`（mon-fri 15:40）、`scan:weekend`（sat,sun 10:00），均 `run_all_scans` + `replace_existing=True` + `misfire_grace_time=3600`。
- `run_all_scans()` 顺序执行（BackgroundScheduler 线程池内单线程循环），逐策略 try/except；全程复用管道自身限频（≤10 req/s 池化）与缓存，多策略不叠加爆发。
- 已知限制（与现有回测调度一致）：多进程部署下调度为近似（每 worker 各自注册）——本地单用户单进程精确；写入 ROADMAP 交付说明。
- 测试环境不 start_scheduler（现有模式），注册逻辑单独单测（断言 job 数/触发器参数）。

## 6. 边界情况

| 场景 | 行为 |
|---|---|
| 上游不可达，pipeline.run 抛错 | 该策略 last_status="failed"、日志 trace，继续其余策略；不产生提醒 |
| 策略配置文件在升级中消失 | 跳过 + 日志；configs 列表 strategyName="（策略已不存在）"；PUT 422 |
| 周末补扫无新数据 | 管道缓存/最新收盘命中不变 → diff 空 → 只更新 last_run_at，无提醒 |
| 命中列表为空 | last_hits=[]；原滞留码全部自然"跌出"；无提醒 |
| 命中为 stale 缓存 | 透传 stale（管道返回），日志记录；提醒不标注 stale（看时重算保证新数据） |
| 深夜/节假日 misfire | grace 3600s 内补跑；超出则跳过等下个触发点（APScheduler 默认）；EVENT_JOB_MISSED 记日志（FR-13③） |
| 上游偶发故障 | 失败 10 分钟后单次重试（FR-13②）；仍失败等下个触发点 |
| 多 worker 部署重复扫描 | Redis 分布式锁互斥（FR-13①）；锁不可用降级无锁 + 告警日志 |
| 扫描中途用户关闭开关 | update_scan_state 前置校验 enabled，跳过写入 + 日志（FR-13⑤） |
| DB 不可达 | 状态/历史写入失败仅日志（FR-13④）；调度器存活；下次扫描重试写入 |
| PUT 与扫描并发 | 状态更新行级原子（upsert）+ enabled 复核（FR-13⑤） |
| 单策略扫描耗时 | 管道内部已有界：history_deadline_s=45s（配置上限 300s）+ 阶段 deadline + HTTP 10s×2 重试；扫描不叠加额外硬超时（避免比管道自身 deadline 更紧造成误杀） |
| 扫描 while 用户在跑同一策略 | 管道缓存击穿互斥锁 + 限频已处理（复用） |

## 7. 前端交互

- **提醒中心**：`scanAlerts` 计算属性（alerts store）从 `GET /scan/hits` 合成；与 workspace.alerts 合并渲染，kind='alert' 计入「交易」过滤与未读徽标。轮询挂进现有 `refreshAll()`。
- **已读**：localStorage `atlas.scan.seen.{strategyId}` 记用户最近一次查看该策略提醒的时间戳；`createdAtMs > seen` 计未读；打开提醒面板即刷新 seen。**只本地**，不回传。
- **代码片**：提醒项渲染可点代码片（data-testid=`alert-code-chip`），点击 → `assist.openFor({ code, name })`（不传 entryPrice → 实时行情路径）→ 草案对话框；XSS 纪律同现有 showToast（textContent）。
- **策略实验室**：策略行「定时扫描」开关 + quick/deep 下拉（开关关闭时下拉置灰）；切换即 PUT /scan/configs（失败回滚 + toast）；行内上次扫描状态显示；「立即扫描」按钮（data-testid=`scan-now`）带 submitting 态。

## 8. 测试与验收

单测（pytest，沿用离线 monkeypatch 模式）：
1. 去重引擎：新进入/滞留/跌出三态、first_seen 维护、多新码、空命中。
2. run_all_scans：顺序执行、单策略失败隔离、状态更新、trace 日志字段。
3. 端点：configs 列表/PUT 校验（422 分支）/scan-now（mock pipeline）/hits 形状；last_hits 坏 JSON 容错。
4. 调度注册：两个 job、cron 表达式正确、幂等重注册。
5. 迁移：两张新表 upgrade/downgrade 往返。
6. FR-13 护栏：锁获取/降级（Redis 不可用继续扫描 + 告警日志）；失败重试 job 创建且 one-shot；misfire 监听日志；enabled 复核跳过；DB 写失败仅日志不炸线程；history 滚动清理（>500 行）。

前端（vitest）：开关切换 PUT spy + 失败回滚；scanAlerts 合成 + 未读计数 + seen 打点；代码片点击 openFor spy；scan-now 按钮态。

验收：
1. 启用某策略 → 立即扫描 → 提醒中心出现该策略新码提醒，点击代码片弹出草案（数据为当前实时路径）。
2. 再次扫描（命中不变）→ 无新提醒；手工把 last_hits 清空后重扫 → 同码重新提醒（跌出再报语义）。
3. 断网扫描 → 策略实验室显示「上次扫描失败」，其他策略不受影响，无失败提醒。
4. 全量门禁：pytest ≥80% 覆盖、ruff/mypy 0 错、vitest/vue-tsc/build/eslint 绿。
5. 红线复核：扫描路径零 plans 写入、零券商依赖。

## 9. 非目标

- Webhook / 邮件推送（ROADMAP「提醒方式扩展」独立落点）
- 扫描时间可配置（固定 15:40 / 周末 10:00，要改是 P3 一行 cron 参数）
- 命中明细归档（摘要表 FR-12 只存计数；逐码明细留给绩效复盘 spec 设计）
- 自动把命中写入 plans（红线）
- 分钟级/盘中扫描；多策略回测对比
- 调度独立为 celery beat / k8s cronjob（本地单用户工具，非目标含 K8s 编排；P3 再议）
- Prometheus 指标与告警（本地无监控基础设施；结构化日志已含耗时/计数字段）
- 失败指数退避多级重试（单次 10 分钟重试足够，避免上游过载放大）
- 多用户/权限隔离（非目标红线：多租户 SaaS；全仓库统一 workspace_id="default" 惯例）

## 10. 评审决议

### 第一轮（设计澄清）

| # | 决议点 | 结论 |
|---|---|---|
| 1 | 扫描启用粒度 | 每策略独立开关（新表，因策略为包内 JSON） |
| 2 | 推送形态 | 提醒中心 + 看时重算（不存草案快照） |
| 3 | 重复抑制 | 跌出再报（first_seen 机制） |
| 4 | 调度 | 工作日 15:40 + 周末 10:00 补扫 |
| 5 | 提醒通道 | 方案 A：独立端点 + 前端合成（不动 workspace 同步语义） |

### 第二轮（风险评审）

| # | 建议 | 裁定 | 依据 |
|---|---|---|---|
| 6 | Redis 分布式锁 | ✅ 采纳 | Redis 已直连，~10 行；不可用降级无锁 + 告警（FR-13①）；celery/k8s 长期方案进非目标 |
| 7 | 用户/workspace 隔离 | ❌ 驳回 | 多租户是非目标红线；全仓库统一 workspace_id="default"（plans/alerts/策略同惯例），扫描端点不特殊化 |
| 8 | scan_history 摘要表 | ✅ 采纳（缩小版） | 只存摘要不存明细（FR-12）；直接服务下一 P1 绩效复盘的"轻量运行留痕"；500 行滚动清理 |
| 9 | 每策略 30s 硬超时 | ❌ 驳回（数值） | 管道自有 history_deadline_s=45s（默认）+ HTTP 10s×2 有界，30s 比内部 deadline 更紧会截断合法扫描误记 failed；elapsed_ms 观测已在 FR-11 |
| 10 | 轮询实时性 | ❌ 驳回 | 评审自认可接受；/hits 挂现有 refreshAll 节奏；scan-now 后 UI 即时刷新 |
| 11 | enabled 并发复核 | ✅ 采纳 | update_scan_state 前置校验（FR-13⑤） |
| 12 | 失败自动重试 | ✅ 采纳（缩小版） | 单次 10 分钟 one-shot 重试；拒绝指数退避×3（上游过载放大，YAGNI） |
| 13 | misfire 错过标记 | ✅ 采纳（缩小版） | EVENT_JOB_MISSED 监听记日志；不自动补偿（scan-now 人工兜底） |
| 14 | 配置写审计 | ✅ 采纳（日志行） | PUT 变更记结构化日志（strategyId/enabled/mode）；本地单用户无"谁"维度，审计表 YAGNI |
| 15 | 评分脱敏 | ❌ 驳回 | 本地单用户、数据不出机器；多租户是非目标 |
| 16 | Prometheus 告警 | ❌ 驳回 | 无监控基础设施（K8s 编排在非目标）；日志已含指标字段，P3 再议 |
| 17 | DB 失败降级 | ✅ 采纳 | 状态/历史写入 try/except 仅日志（FR-13④） |
| 18 | last_hits JSON 演进 | ✅ 已覆盖 | 坏 JSON 容错已在 §4.1；字段只增注记已加 |

### 第三轮（细微修订）

| # | 建议 | 裁定 | 依据 |
|---|---|---|---|
| 19 | scan-now 区分 500/502 | ❌ 保持 502 | 既有姊妹端点 /api/screener/strategy 对非 ValueError 一律 502 ERR_UPSTREAM_UNAVAILABLE（app.py:378-379）；单独给 scan-now 引入区分会不一致，统一区分需全仓异常分类学（P3 一并做） |
| 20 | Redis 锁主动释放 | ✅ 采纳 | FR-13① 补"finally 主动释放（Lua 校验 value）"，实现者契约化而非口头提醒；测试补提前释放用例 |
| 21 | 重试范围与 enabled 前置校验 | ✅ 采纳 | FR-13② 明确逐策略独立 job（scan:retry:{strategyId}）+ 触发时先校验 enabled 再跑管道 |
