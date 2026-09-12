# 组合风险视图（P1）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付「组合风险视图」：计划驱动的建仓/闭环双层虚拟组合 NAV（名义额静态分配、毛/费后双序列）+ 敞口/行业集中度 + 平仓信号质量看板 + ViewPortfolio 第 8 视图。

**Architecture:** 新引擎 `backend/portfolio_risk.py` 复用 `plan_review` 纯函数与微结构语义（零触碰引擎本体）；行业映射双层缓存（进程+DB 表）+ 后台预热；`GET /api/portfolio/risk` 只读端点带轻量限流；前端 store+ViewPortfolio+ViewPlans 关联操作。契约 = spec `2026-09-12-portfolio-risk-view-spec.md` r3（含 r3.1 修正）。

**Tech Stack:** FastAPI + SQLAlchemy/Alembic + APScheduler（既有实例）；Vue3+TS strict + Pinia + vitest；pytest（离线 fake）+ ruff + mypy。

## Global Constraints（每任务隐含遵守）

- 分支：执行开始 `git flow feature start portfolio-risk`（基于 develop）。
- 红线：无券商/无自动执行；**绝不造数**——缺数据 null/"未知"/degraded，永不填充；面板双句红线文案逐字来自 spec D6。
- UI 中文；API 字段 camelCase 且**只增不改名**（`Plan` 现有字段零触碰）。
- 测试纪律：新逻辑一律先写失败测试（TDD）；任务级 pytest 用 `python -m pytest tests/<file> -q --no-cov`；全量门禁只在 T10。
- 提交：中文主题 Conventional Commits，`--no-verify`（门禁手工跑）；每任务末提交。
- 冻结接口（下表）不可擅改；需改 → 停下报告控制器。
- Windows/pwsh：短命令；`$env:PYTHONPATH='.'` 跑仓库根脚本；pytest 绿跑可能出现 stderr 假 [exit code 1]——以点行/汇总行为准。

**冻结接口总表**

| # | 接口 | 定义方 |
|---|---|---|
| I1 | `validate_plan_links(plans_payload: list[dict]) -> str \| None`（None=通过；返回中文错误即 422 detail） | T1 |
| I2 | `TradePlan.related_plan/exit_mode` 列 + `_plan_dict` 键 `relatedPlan/exitMode`（恒在，可 None） | T1 |
| I3 | 设置键 `totalPositionCapPct`（int 默认 100，clamp 20..300） | T1 |
| I4 | `industry_map.get_industry_map() -> tuple[dict[str,str], str]`（status ∈ fresh\|stale\|empty） | T2 |
| I5 | `industry_map.refresh_industry_map(fetch_page: Callable[[int,int], tuple[list[dict],int]] \| None = None) -> int`（page→(rows,total)；None=真东财；返回 upsert 行数） | T2 |
| I6 | `FEE_RATE_MAX = 0.05` 入 `plan_review.py`（与既有 `DEFAULT_FEE_RATE` 并排；两端点共用） | T3 |
| I7 | `replay_positions(plans, bars_map, window_start: str, today: str, layer: str, links: dict[str,dict]) -> tuple[list[dict], list[dict]]`（positions, events；position 含 `marks: dict[date,float]`、`status: holding\|closed\|notEntered`、`exit: {date,price,reason}\|None`） | T3 |
| I8 | `build_links(plans) -> tuple[dict[str,dict], list[dict]]`（buyPlanId→{sell,exitMode}，events：dangling/双配冲突） | T4 |
| I9 | `compose_nav(positions, dates: list[str], fee_rate: float) -> dict`（`{dates, gross, net, cashEnd, exposureEnd, mddGross, mddNet, feeSum}`；恒等式 gross_t−net_t=Σfee_{≤t}） | T3 |
| I10 | `aggregate_portfolio(...) -> dict`（payload 除 degraded 的全部区块，签名见 T5） | T5 |
| I11 | `GET /api/portfolio/risk` 参数与顶层键（spec §6 逐字） | T6 |
| I12 | `usePortfolioStore`：`{days,start,layer,withWatch,feeRate,payload,error,loading,fetchedOnce, fetch(), setParam()}` | T7 |
| I13 | payload TS 接口名 `PortfolioPayload` 等（models/store 内联 interface，风格同 ReviewPayload） | T7 |

---

### Task 1: 存储层——计划关联两列 + 总仓位上限设置 + 校验

**Files:**
- Modify: `backend/storage.py`（TradePlan 模型、`_plan_dict` ~L275、`save_workspace` plans 映射 ~L444、`DEFAULT_WORKSPACE_SETTINGS`、clamp 区）
- Modify: `backend/app.py`（workspace PUT 处理器：调 I1 校验 → `api_error(422, ERR_VALIDATION_ERROR, msg)`）
- Create: `backend/migrations/versions/xxxx_plan_related_exit.py`（`alembic revision -m "计划关联与离场模式列"`，手写 upgrade/downgrade）
- Modify: `frontend/src/types/models.ts`（Plan +`relatedPlan?: string; exitMode?: 'race'|'sell_priority'|'sell_stop_only'|'sell_only'`）
- Test: `tests/test_portfolio_api.py`（新文件，本任务起建存储段）+ 检查 `tests/test_settings_api.py` 默认键断言是否需 +1

- [ ] **Step 1: 写失败测试**

```python
# tests/test_portfolio_api.py
def test_plan_link_roundtrip(workspace_client):
    plans = [
        {"id": "b1", "code": "600519", "direction": "buy", "entry": 10, "stop": 9.5,
         "target": 11, "position": 10, "status": "执行中", "validity": "30天"},
        {"id": "s1", "code": "600519", "direction": "sell", "entry": 12, "stop": 11.5,
         "target": 13, "position": 10, "status": "执行中", "validity": "30天",
         "relatedPlan": "b1", "exitMode": "sell_priority"},
    ]
    put_ws(workspace_client, plans)                      # 既有 workspace PUT 助手风格
    got = {p["id"]: p for p in get_ws(workspace_client)["plans"]}
    assert got["s1"]["relatedPlan"] == "b1" and got["s1"]["exitMode"] == "sell_priority"
    assert got["b1"]["relatedPlan"] is None              # 键恒在

def test_link_validation_rejects():
    bad = [{"id": "s1", "direction": "sell", "relatedPlan": "ghost"}]
    assert validate_plan_links(bad)                      # 目标不存在 → 返回中文错误串
    assert validate_plan_links([{"id": "s1", "direction": "buy", "relatedPlan": "b2"}])
    # 一 buy 双 sell 关联、自引用、跨 code、目标非 buy → 均非 None；合法链 → None
```

（`workspace_client`/`put_ws`/`get_ws`：仿 `tests/test_plan_review.py` 端点段既有 module-level client + workspace 存取风格建最小 fixture。）

- [ ] **Step 2: 跑红** — `python -m pytest tests/test_portfolio_api.py -q --no-cov` → ImportError/AttributeError。
- [ ] **Step 3: 实现** — 模型两列（String(96)/String(16)，nullable，注释含枚举与 NULL≡race）；`_plan_dict` 透传（恒出键）；`save_workspace` `plan.related_plan = item.get("relatedPlan") or None; plan.exit_mode = item.get("exitMode") or None`；`validate_plan_links`（规则=spec §3：仅 sell 可带、目标存在且 buy、禁自引用、同 code、一 buy 一 sell）；app.py workspace PUT 在 save 前调用；迁移手写（`op.add_column`×2 / downgrade drop）；settings 默认键 + clamp（照 `defaultCapital` 行式 `max(20, min(..., 300))`，int 化）；models.ts 两字段。**跑 test_settings_api / test_storage_coverage 若因默认键集合失败→同步该断言（一次提交内）**。
- [ ] **Step 4: 跑绿** — 目标文件 + `tests/test_backend_api.py tests/test_storage_coverage.py tests/test_settings_api.py -q --no-cov`；`alembic upgrade head`（本地 PG）验证迁移。
- [ ] **Step 5: Commit** — `feat: 计划交易对关联存储（related_plan/exit_mode 列+迁移+写路径校验+总仓位上限设置）`

**Interfaces:** Produces I1/I2/I3。

---

### Task 2: 行业映射——f100 + 双层缓存 + DB 表 + 预热任务

**Files:**
- Modify: `backend/sources/eastmoney.py`（`_CLIST_FIELDS = "f2,f3,f5,f6,f8,f9,f10,f12,f14,f100"`；行映射带出 industry）
- Create: `backend/industry_map.py`
- Create: 迁移（`industry_map` 表：`code String(32) PK, name String(64), updated_at`）
- Modify: `backend/app.py`（startup：`start_scheduler()` 之后 `add_job(refresh_industry_map, "interval", hours=24, first_run_delay=30, id="industry-warmup", replace_existing=True)`，job 函数 try/except 记 `logger("atlas.industry").warning` 不抛）
- Test: `tests/test_industry_map.py`

- [ ] **Step 1: 失败测试**

```python
def test_get_industry_map_three_states(tmp_db):        # fresh：进程缓存命中 upstream 零调用
    def fake_page(page, size):  # (rows, total)
        return ([{"code": "600519", "industry": "白酒"}, {"code": "000001", "industry": "银行"}], 2)
    assert refresh_industry_map(fetch_page=fake_page) == 2
    m, st = get_industry_map()
    assert m["600519"] == "白酒" and st == "fresh"
def test_stale_tolerance(tmp_db):                       # DB 有行、刷新失败 → status="stale"，map=DB 行
def test_empty(tmp_db):                                 # 表空且拉取失败 → ({}, "empty")
def test_refresh_partial_page_keeps_rows(tmp_db):       # 拉取中途失败 → 已 upsert 行保留，返回计数
```

- [ ] **Step 2: 红**；**Step 3: 实现**：进程 `_cache: tuple[float, dict]` TTL 86400；读序=进程→DB(updated_at 距今≤24h→fresh)→DB 全量(stale)→触发拉取（仅表空）；`refresh_industry_map` 分页循环（size=200，≤10req/s 用既有 sleep 纪律）、upsert、写穿进程缓存；真 fetch_page 用 eastmoney 既有 clist 请求构造（新增薄函数 `_clist_page(page, size)` 返回归一 rows）。
- [ ] **Step 4: 绿 + ruff/mypy 该两文件**；**Step 5: Commit** — `feat: 行业映射双层缓存（东财 f100+DB 持久化+每日预热）`

**Interfaces:** Consumes 既有 scheduler；Produces I4/I5。

---

### Task 3: 回放引擎核心——入场/名义额/主层离场/双序列 NAV

**Files:**
- Create: `backend/portfolio_risk.py`
- Modify: `backend/plan_review.py`（仅加 `FEE_RATE_MAX = 0.05` 常量一行，I6）
- Test: `tests/test_portfolio_engine.py`（新）

**引擎语义（照 spec §5.2/§5.4，逐条断言化）：**
- 成分：buy；窗交集；status 不参与判定。入场=entry 触及（`low<=entry`；跳空 `open<entry`→成交 open），一字板纪律：跌停一字可买、涨停一字顺延、停牌（volume≤0）跳过且不更新 prevClose。
- 分配：`notional = 前一已知收盘 NAV × positionPct/100`；NAV₀=1；窗起点日触发视同窗前触发（基准=1）。超可用现金→当日各新分配等比缩放（事件 `scaling`，detail 快照 I11 之 §5.5）。
- 主层离场：stop/target（buy：`high>=target` 止盈 / `low<=stop` 止损；同日双触保守取 stop；跳空开盘劣于触发价→open 成交）→ 转现金；窗尾仍持仓→最后 close 记浮动（holding 进 NAV）。
- 事件日 mark=close（停牌沿用前收）。

- [ ] **Step 1: 失败测试（表驱动，仿 test_plan_review 的 bars() 助手风格）**

```python
def test_entry_gap_and_notional():
    # 窗 [01-02..01-08]，plan position=30 → notional=0.30×NAV₀=0.30；
    # 01-03 open=9.6 < entry=10 → 成交价 9.6、入场日 01-03；01-04 起 marks=close
def test_scaling_event():
    # 两 plan 30%+80% 同日触发 → 第二个分配 0.70×(1-0.30)=0.49，事件 requested=0.80 allocated=0.49
def test_stop_target_race_conservative():
    # 同日 high>=target 且 low<=stop → 按 stop 价离场（跳空取 open）
def test_nav_identity_gross_net():
    r = compose_nav(positions, dates, fee_rate=0.0015)
    for t in range(len(r["dates"])):
        assert r["gross"][t] - r["net"][t] == pytest.approx(r["feeCum"][t])
def test_equiv_vs_plan_review():
    # 单 plan、窗=其 created..expiry：portfolio 入场/离场/价格与 plan_review.replay_plan 逐项相等
```

- [ ] **Step 2: 红**；**Step 3: 实现** `replay_positions` + `compose_nav`（两函数；position dict 结构照 I7；`from backend.plan_review import slice_window, _limit_prices, _board_pct` 复用微结构；不 import replay_plan——语义等价由 test_equiv 锁住）。
- [ ] **Step 4: 绿**；**Step 5: Commit** — `feat: 组合回放引擎核心（名义额静态分配/毛净双序列/缩放事件）`

**Produces I7/I9/I6。**

---

### Task 4: 闭环层——交易对、exitMode 矩阵、冲突/冗余事件

**Files:**
- Modify: `backend/portfolio_risk.py`
- Test: `tests/test_portfolio_engine.py`（追加闭环段）

- [ ] **Step 1: 失败测试**

```python
def test_sell_signal_closes_position():      # race：sell.target 触及日按 sell 执行价平仓转现金
def test_same_day_priority_matrix():
    # stop+sell 同日：race→stop 执行 sell→suppressed（conflict 事件）；
    # sell_priority→sell 赢（执行价=sell 触发价含跳空）；sell_stop_only→stop 赢；sell_only→仅 sell 信号生效
def test_redundant_after_exit():             # stop 先离场，sell 后触发 → redundant 事件 + position 不受影响
def test_dangling_link():                    # relatedPlan 目标不在 plans → danglingRelatedPlan 事件，sell 按孤儿
def test_exit_mode_suppresses_target():      # sell_priority 下 target 永不触发离场
def test_build_links_rules():                # 双配→后者视为未配对 sell；buy 带 relatedPlan→忽略
```

- [ ] **Step 2: 红**；**Step 3: 实现** `build_links`（I8）+ 信号集日扫描扩展（position 状态机加 sell 信号源；`layer=='closed'` 才启用；exitMode 默认 race；执行价统一函数 `_exec_price(bar, trigger, side, prev_close, code)`）；conflict `detail.suppressed[]`。
- [ ] **Step 4: 绿**；**Step 5: Commit** — `feat: 闭环层交易对与四档离场模式（冲突抑制/冗余平仓事件）`

**Produces I8。**

---

### Task 5: 聚合——KPI/敞口/集中度/信号看板/观察指数/假想线

**Files:**
- Modify: `backend/portfolio_risk.py`
- Test: `tests/test_portfolio_aggregate.py`

- [ ] **Step 1: 失败测试**

```python
def test_exposure_snapshot():   # 执行中+已触发 ΣpositionPct；overCap vs totalPositionCapPct；amount=equity×pct/100
def test_concentration_weights_and_hhi():
    # 两行业市值 60/40 → Top3=100（合并展示前三语义：不足三只=全部）、HHI=0.52、未知桶计入并披露
def test_signal_board_truncation():  # 尾窗不足 10 日 → chg10=None、chg5 有值；费用估算列存在
def test_watch_index_equal_weight_and_missing():  # 缺 bar 标的该日 null 拖尾（不填充）；等权=Σret/n
def test_hypothetical_null_without_flag()
def test_kpis_and_plan_count()
```

- [ ] **Step 2: 红**；**Step 3: 实现**：

```python
def aggregate_portfolio(*, plans, watchlist, settings, bars_map, positions, dates,
                        gross, net, events, links, layer, window_start, today,
                        fee_rate, industry: dict[str, str], industry_status: str,
                        with_watch: bool) -> dict: ...   # I10：返回 spec §6 顶层区块（不含 degraded）
```

信号源=孤儿 sell + redundant 事件；市值权重取窗尾日 marks 归一（现金不参与）；行业 miss→"未知"；payload `meta.industryCoverage={known,total,stale}`。
- [ ] **Step 4: 绿**；**Step 5: Commit** — `feat: 组合聚合层（敞口/行业集中度/信号看板/自选观察指数/假想线）`

---

### Task 6: API 端点——参数校验/限流/取数复用/错误与日志

**Files:**
- Modify: `backend/app.py`（新 `GET /api/portfolio/risk`；把 review 端点内"per-request source 解析 + _counting + degraded 收集"提取为模块级 `_resolve_history_loader()` 复用于两端点，行为零变化）
- Test: `tests/test_portfolio_api.py`（追加端点段）

- [ ] **Step 1: 失败测试**（client 用既有 app 导入模式）

```python
def test_risk_422_days_whitelist(); def test_risk_start_overrides_days()  # days=30&start=远日 → 响应 meta.windowStart==start
def test_risk_fee_rate_bounds_422(); def test_risk_429_after_20_calls()    # 注入小 limiter 或 monkeypatch 时钟
def test_risk_502_failed_codes(); def test_risk_empty_plans_zero_state()   # 200 全零结构 + keys 恒在
def test_risk_happy_keys():  # {kpis,nav,exposure,concentration,pairs,orphans,signals,events,eventsTotal,degraded,meta}
def test_risk_degraded_and_log(caplog):  # local flag → degraded + review_degraded 复用告警
def test_review_refactor_regression():   # 既有复盘端点全测试保持绿（提取辅助不改行为）
```

- [ ] **Step 2: 红**；**Step 3: 实现**：参数解析（start 校验 `[today−1825d, today−1d]`）→ `fetch_all_bars(codes|watchlist, loader)`（layer=closed 并入 sell codes）→ `replay_positions/build_links` → `compose_nav` → `aggregate_portfolio` → `result["degraded"]=sorted(set(...))` → `review_logger.info("portfolio_ok layer=%s window=%d plans=%d codes=%d upstream=%d gross_mdd=%.4f net_mdd=%.4f scaling=%d conflicts=%d degraded=%s elapsed_ms=%d", ...)`；`ReviewUpstreamError`→502 同式；`SlidingWindowLimiter(20, 60)` 模块级实例（照 plan-draft 用法），超限 429 `api_error`。feeRate 校验用 I6 常量（review 端点内联 0.05 同步替换）。
- [ ] **Step 4: 绿（含复盘端点回归全量）**；**Step 5: Commit** — `feat: 组合风险端点（参数校验/20 次每分钟护栏/降级披露/结构化日志）`

---

### Task 7: 前端 store——usePortfolioStore

**Files:**
- Create: `frontend/src/stores/usePortfolioStore.ts`
- Test: `tests/frontend/usePortfolioStore.test.ts`

- [ ] **Step 1: 失败测试**：拼参（默认 days=90 单层请求；start 有值才带且不带 days；withWatch==='true'；feeRate 非空才带）；成功清 error；失败 `error='组合风险计算失败…'` + payload=null + fetchedOnce 复位；偏好 `{days,layer,withWatch}` localStorage `portfolio_prefs_v1` 读写（setParam 即持久化，初始化恢复）。类型 I13（`degraded: string[]`、`nav.net: (number|null)[]` 等照 payload 契约，字段名逐字）。
- [ ] **Step 2: 红**；**Step 3: 实现**（风格对齐 useReviewStore：refs + `api.get` + try/catch）；**Step 4: 绿** `npx vitest run tests/frontend/usePortfolioStore.test.ts`；**Step 5: Commit** — `feat: 组合风险 store（拼参/错误态/偏好持久化）`

---

### Task 8: ViewPortfolio 第 8 视图（含 chart 多线扩展）

**Files:**
- Create: `frontend/src/views/ViewPortfolio.vue`
- Modify: `frontend/src/main.ts`、`frontend/src/App.vue`（`view==='portfolio'` 分支）、`frontend/src/modules/constants.ts`（NAV 项 `{ id:'portfolio', label:'组合风险', icon:<lucide 现名，执行时验证存在> }`）、`frontend/src/app.ts:97`（`6:'portfolio'`）、`frontend/src/styles.css`（portfolio 块 + 复用 review/.muted 族）、`frontend/src/modules/chart.ts`（如需多线 svg 扩展；能力已够则不动）
- Test: `tests/frontend/ViewPortfolio.test.ts`

- [ ] **Step 1: 失败测试**：高级三区默认关（`queryByTestId('portfolio-adv-start')` null，点「高级」后在）；degraded 黄条 `portfolio-degraded` 文案含代码；预热文案 `industryCoverage.known===0 && stale==='empty'` → `portfolio-warming`「行业数据预热中」；红线双句逐字；层切换 chips 点击 → setParam+fetch；KPI '--'（null 渲染）；事件/信号折叠区 cap+`共 N 条已截断`。
- [ ] **Step 2: 红**；**Step 3: 实现**（区块顺序=spec §7；chart 线：gross 主 / net 灰虚 / 现金 0 基线 / watch 灰虚第二条）；`npx prettier --check` 触碰文件；**Step 4: 绿 + `npx vue-tsc --noEmit`**；**Step 5: Commit** — `feat: 组合风险视图（双层切换/毛净曲线/敞口集中度卡/事件与信号折叠区）`

---

### Task 9: ViewPlans 交易对关联操作

**Files:**
- Modify: `frontend/src/views/ViewPlans.vue`（sell 行关联 select + exitMode select + sell_only 二次确认；写路径=更新 plans store → 既有 workspace PUT；422/409 失败 toast 现模式）
- Test: `tests/frontend/ViewPlans.test.ts`（追加：下拉选项=同 code 未配对 buy；解除置 null；sell_only confirm 取消不写；confirm 通过写入并触发保存；保存失败 error toast）

- [ ] **Step 1-5:** TDD 同上节奏 → `feat: 交易计划关联平仓单（交易对下拉/exitMode 四档/仅 sell 二次确认）`

---

### Task 10: 文档 + 全量门禁 + 真实冒烟

**Files:** Modify `ROADMAP.md`（[x]+已知限制照 spec §11 浓缩）、`AGENTS.md`（布局 +portfolio_risk.py/industry_map.py/ViewPortfolio/usePortfolioStore；计数刷新：pytest/vitest 实际值）、Create `.superpowers/smoke_portfolio.py`（v2 模式：备份→播种 buy×2(1 配对 sell、1 孤儿 sell)→PUT→GET core/closed 手推 → net≤gross 恒等抽查 → 预热落库二次 upstream=0 → 恢复+零残留）
- [ ] 全量门禁：`python -m pytest tests/ -q`（含覆盖率）· `npx vitest run` · `npx vue-tsc --noEmit` · `npm run build` · ruff check/format · mypy · eslint/prettier 触碰面
- [ ] 冒烟跑通并归档报告 → `docs: ROADMAP/AGENTS 组合风险视图交付记录` + `chore: 组合风险真实冒烟脚本`

---

## Self-Review（计划↔spec）

- §3→T1；§4→T2；§5.2/5.4→T3；§5.3/5.5→T4（事件 detail 快照）；聚合→T5；§6→T6（限流/校验/start 优先）；§7→T8/T9（预热文案/偏好持久化/二次确认/截断提示全有测试位）；§8→T6/T8；§9→各任务测试步+T10；D7 net 恒等式=T3 硬断言；D9 拒绝项零实现。
- 无 TBD；跨任务类型一致：I7 position dict 键在 T4/T5/T6 引用同名；`links` 由 I8 产出、I7 消费（`links` 入参在 T3 定义 T4 传入，默认 `{}`=主层）。
