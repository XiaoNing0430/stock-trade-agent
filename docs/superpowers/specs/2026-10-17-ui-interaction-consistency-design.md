# UI 优化第③b批：交互一致性 — 设计 Spec

- **日期：** 2026-10-17
- **状态：** 待用户复审（复审通过前禁止开发）
- **计划分支：** `feature/ui-interaction-consistency`（Git Flow，基线 `develop`，含已合入的 ③a `d756d2a`）
- **路线图定位：** 「整体界面优化」三批的第③批拆分项。③a 布局 IA 已于 2026-10-16 完成、2026-10-17 合入 `develop`（`d756d2a`）；本批是其配对的交互层，③b 之后该批收口。
- **行号口径：** 本文所有行号为 2026-10-17 在 `feature/ui-layout-ia`（`f8b6d1b`）上核对所得；实现时以符号/文本定位为准。

## 1. 背景与目标

③a 解决了**信息架构**（同一事实只写一遍、导航分组桌面手机同构、下钻可达）。但**交互层**从未统一：浮层没有键盘出口、加载与空态共用一个类、Toast 不可关闭也不去重、快捷键有一半没提示且会被浮层抢走。经逐文件核对，问题可精确归为**五类**：

| # | 问题 | 规模 | 核对结论 |
|---|---|---|---|
| 1 | 浮层无 Esc / 无焦点陷阱 / 无滚动锁 / 不归还焦点 | 4 个浮层 | 前端**零** `Escape` 处理；唯一全局键盘监听在 `app.ts:88` |
| 2 | 加载态与空态语义混用 | 5 处加载用 `.empty-state`；4 处该有指示却什么都不显示 | `.loading-state` 类在全仓库**不存在** |
| 3 | Toast 无规则 | 1 个 `showToast`、~75 处调用 | 固定 3200ms、可无限堆叠、不可关闭、无去重 |
| 4 | 快捷键不完整且被浮层抢 | 1 个全局监听 | `1`–`6` 无提示、`7` 缺失、抑制条件只查 INPUT/TEXTAREA、浮层打开时照切视图 |
| 5 | ③a 新代码的遗留一致性缺口 | 4 项 | ≤1060 图标条主题开关竖排；5 处下钻控件无逐行可访问名；通知面板缺 `aria-modal`；4 处空态只有文字建议 |

本批目标：**让浮层有统一的键盘行为，让「加载中 / 没有数据 / 字段缺失 / 请求失败」四态各有明确画法，让瞬时反馈可信可控，让快捷键可发现且不误触**。

## 2. 已裁定决策（2026-10-17 用户确认）

1. **范围**：四项核心（浮层行为、加载/空态规范、Toast 规则、快捷键增补）**＋** §1 表第 5 行的四项遗留缺口全部纳入本批。
2. **浮层架构 = 共享组合式函数**：新增一个 `useOverlayA11y`（Esc + 焦点陷阱 + 滚动锁 + 焦点归还），各浮层接一行；**不**抽统一浮层组件、**不**重写 4 处模板 DOM/类名。
3. **加载/空态 = 补齐缺口 + 立规范**：给缺失处加真加载态，立 `.loading-state` / `.empty-state` 两套语义，措辞收敛；**不**引入骨架屏。
4. **Toast = 去重 + 上限 + 可关闭 + 分时长**：同文案去重（重置计时 + 高亮，不叠条）、堆叠上限 3、整条可点击关闭、悬停/聚焦暂停计时、error 6s 其余 3.2s，保留 `aria-live="polite"`。
5. **快捷键 = `1`–`7` + `/` + Esc + `?` 帮助浮层**：帮助浮层是全部键位的唯一集中说明，自身复用本批浮层行为；抑制条件扩到 SELECT / contenteditable / 输入法组合中 / 浮层打开时（Esc 除外）；导航项补 `aria-keyshortcuts`，顶栏加 `?` 入口。
6. **空态动作 = 就地动能优先，否则跳转**：只在有**真实去处**时加按钮（复用该面板已有动作，或跳到能动手的视图），绝不做假按钮。

## 3. 非目标

- 浮层组件化重构（<AppOverlay>）、`inert` 背景隔离、背景元素 `aria-hidden` 以外的高级 a11y。
- 骨架屏 / 内容占位动画。
- Toast 撤销、通知队列管理 UI、声音提示、`assertive` 播报。
- 快捷键可配置化（ROADMAP 已列为 P2）、命令面板、组合键（`g` 系列）。
- 主题/配色/字号/布局再动（①②③a 已交付）。
- 后端与数据结构改动（**零 API / 零 schema / 零迁移**）。
- `.vue` 组件结构重构、`styles.css` 拆分（维持单文件 CSS）。

## 4. 红线与约束

- **绝不使用模拟值填充缺失数据**：加载中显示「正在…」，加载完成但字段缺失仍是 `--`，绝不用占位数字顶替。
- **警示强度不得变弱**：降级/错误路径（`.connection-banner`、`role="alert"`、分钟线状态条、`fallbackUsed` 徽标）文案与强度本批不动；Toast 升级不得吞掉任何 error。
- **免责声明**（页脚「研究工具，不构成投资建议」）本批不动。
- 用户可见文案全中文；不新增英文装饰标签。
- **`showToast(message, tone)` 签名与调用点不变**（~75 处调用与既有 spy 断言 `toHaveBeenCalledWith(msg, 'error')` 必须继续通过）。
- **`NAV_ITEMS` 顺序与数量不变**（`aria-keyshortcuts` 只加属性，不改结构）。

## 5. 现状证据

### 5.1 浮层（4 个，无一例外）

| 浮层 | 文件 | 开关 | Esc | 焦点陷阱 | 滚动锁 | 焦点归还 | 遮罩 | ARIA |
|---|---|---|---|---|---|---|---|---|
| 交易计划草案 | `components/PlanDraftDialog.vue:111-112` | `assist.visible` | ❌ | ❌ | ❌ | ❌ | `@click.self` | `role=dialog` `aria-modal=true` |
| 自定义策略编辑器 | `components/CustomStrategyDialog.vue:2-3` | `screener.strategyEditorOpen` | ❌ | ❌ | ❌ | ❌ | `@click.self` | `role=dialog` `aria-modal=true` |
| 通知面板 | `App.vue:92-93` | `alerts.notifOpen` | ❌ | ❌ | ❌ | ❌ | 兄弟节点 `@click`（无子元素，功能等价 `.self`） | `role=dialog`，**缺 `aria-modal`** |
| 手机「更多」抽屉 | `App.vue:259-260` | `moreSheetOpen` | ❌ | ❌ | ❌ | ❌ | `@click.self` | `role=dialog` `aria-modal=true` |

滚动容器事实：`html, body { height:100%; overflow:hidden }`（`styles.css:140-157`）、`.app-shell` 同为 `overflow:hidden`，**真正滚动的是 `.view-panel.is-active { overflow:auto }`（`styles.css:577`）**。因此滚动锁不会引起滚动条宽度跳变（无 100vw 补偿需求）。

### 5.2 加载 / 空态

**共用同一个类**（都写 `class="empty-state"`，仅图标不同）：

| 位置 | 语义 | 文案 |
|---|---|---|
| `ViewOverview.vue:144-145` | 加载 | （loader-circle） |
| `ViewScreener.vue:235-236` | 加载 | 正在运行策略 |
| `ViewScreener.vue:410-411` | 加载 | 正在读取真实行情 / 行情列表返回后会显示筛选结果。 |
| `ViewScreener.vue:505-506` | 加载 | 正在读取全市场行情 |

**完全无加载指示的缺口**：`ViewGrid` 三处结果区（策略回测 `:503-506`、多策略对比 `:663-666`、网格建议 `:319-322` 已有按钮但无加载分支）——回测运行期间结果区仍显示空态，观感是「点了没反应」；`ViewPlans` 复盘面板（`review.loading` 存在，`:211` 起无指示）；`ViewStockDetail` 报价区（`:23-58`）与分钟线（`:87-99`，`fetchMinute` 在途无任何提示）；`ViewPortfolio` KPI 行（`:70-118`）加载期间是一排**裸 `--`**（与「字段缺失」无法区分）。

### 5.3 Toast

`useWorkspaceStore.ts:73-91` 命令式建 DOM，追加 `#toast-region`（`App.vue:279`，`aria-live="polite"` + `aria-atomic="true"`），`setTimeout(3200)` 移除。无去重、无上限、不可关闭、不可暂停、时长不分 tone。

### 5.4 快捷键

| 键 | 现状 | 提示 | 被浮层抢 | SELECT 内触发 |
|---|---|---|---|---|
| `/` | `app.ts:90-96` 聚焦搜索 | `<kbd>/</kbd>`（`App.vue:77`） | 是 | 否（仅查 INPUT/TEXTAREA） |
| `1`–`6` | `app.ts:97-101` 切视图 | **无** | 是 | **是** |
| `7` | **缺失**（`settings` 到不了） | — | — | — |
| `Esc` | **无任何处理** | — | — | — |
| `?` | **无** | — | — | — |

### 5.5 下钻控件可访问名（5 处，文案全同）

`App.vue:157-165`（`alert-detail-chip`「查看详情」）、`ViewSettings.vue:75-83`（`alert-detail-link`「查看详情」）、`ViewPlans.vue:138-145`（`plan-code-link` 文本即代码）、`ViewPlans.vue:304-312`（`review-code-link` 文本即代码）、`ViewPortfolio.vue:249-257`（`pair-code-link` 文本即代码）。前两处逐行同名；后三处可访问名只有 6 位代码、不含股票名，读屏逐行听是「查看详情」×N。

## 6. 浮层行为设计

### 6.1 新模块 `frontend/src/modules/overlayA11y.ts`

```ts
export interface OverlayA11yOptions {
  id: string;                         // 浮层标识，用于栈与调试
  isOpen: Ref<boolean>;
  panelRef: Ref<HTMLElement | null>;
  onClose: () => void;
  closeOnEsc?: boolean;               // 默认 true
}
export function useOverlayA11y(options: OverlayA11yOptions): void;
// 供 app.ts 与测试使用
export function isAnyOverlayOpen(): boolean;
export function isOverlayOpen(id: string): boolean;
export function topOverlayId(): string | null;
// 纯函数（单测直接打）
export function focusableWithin(root: HTMLElement): HTMLElement[];
export function nextFocusTarget(elements: HTMLElement[], active: Element | null, shift: boolean): HTMLElement | null;
```

**模块级浮层栈**（`id` 数组）+ **模块级锁计数**，两个浮层同时打开时只有栈顶响应 Esc。

### 6.2 行为细则

| 行为 | 规则 |
|---|---|
| **Esc 关闭** | 仅在 `isOpen` 期间监听 `window` keydown；`event.key === 'Escape'` 且**本浮层是栈顶**才动作（否则忽略，不 stopPropagation）。关闭即调 `onClose()`。**不做 `<select>` 特判**：Windows 上原生下拉会先吃掉 Esc（见 §6.4）。 |
| **焦点陷阱** | 打开后 `await nextTick()`（浮层根节点为 `v-if`，元素此时才存在）：面板内有 `[data-autofocus]` 则优先，否则取 `focusableWithin(panel)[0]`，都没有则给面板 `tabindex="-1"` 并聚焦面板。`Tab`/`Shift+Tab` 只在**栈顶**浮层内循环（`focusableWithin` 为空时 `preventDefault` 并留在面板）。可聚焦选择器：`a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])`，过滤 `display:none`/`visibility:hidden`/`inert`。 |
| **滚动锁** | 打开时计数 +1，`0 → 1` 时 `document.body.classList.add('overlay-open')`；关闭时计数 −1，`1 → 0` 时移除。CSS 一条：`body.overlay-open .view-panel.is-active { overflow: hidden; }`。**幂等**（嵌套浮层只加一次）、**不动 scrollTop**（`overflow:hidden` 保留滚动位置）、**无布局位移**（滚动条不在 body 上）。 |
| **焦点归还** | 打开时记录 `document.activeElement`；关闭时若该元素 `isConnected` 且未被 `disabled` 则 `focus()` 回去，否则不动。5 个浮层的触发者都是常驻 DOM（侧栏项 / 顶栏按钮 / 视图内按钮），实测路径均能归还。 |
| **ARIA** | 面板一律 `role="dialog"` + `aria-modal="true"` + `aria-label`（沿用既有 4 处的 `aria-label` 风格，帮助浮层同）；遮罩统一 `@click.self`。**不给背景加 `aria-hidden`/`inert`**（§3 非目标；`aria-modal` 已表达模态语义）。 |

### 6.3 接线（5 处，各一行 + 小改）

| 浮层 | 改动 |
|---|---|
| `PlanDraftDialog.vue` | 加 `panelRef`（`:112` 的 `<section>`）+ `useOverlayA11y({ id:'plan-draft', isOpen:()=>assist.visible, onClose:assist.close })` |
| `CustomStrategyDialog.vue` | 同上，`onClose: screener.closeStrategyEditor` |
| 通知面板 `App.vue:93` | 同上（`id:'notif'`）+ **补 `aria-modal="true"`**；`:92` 遮罩 `@click` → `@click.self`（功能等价，字面统一） |
| 「更多」抽屉 `App.vue:260` | 同上（`id:'more-sheet'`）。**不加媒体门控**：桌面端它由 `display:none` 隐藏，`display:none` 元素不可聚焦，无键盘风险（记入报告） |
| 帮助浮层（新增 `components/ShortcutHelpDialog.vue`） | 同上（`id:'shortcut-help'`），见 §9 |

### 6.4 已知行为（记录，不修）

- Esc 与原生 `<select>` 下拉：Windows 上原生下拉先消费 Esc，浮层不会同时关闭；其他平台可能同时关闭——可接受，不写特判。
- 浮层面板内 `Esc` 不做「输入框先清空再关闭」的两段式（本批不做，避免与 `?`/`/` 的输入语义纠缠）。

## 7. 加载 / 空态规范

### 7.1 四态语义（本批立规）

| 状态 | 画法 | 判据 |
|---|---|---|
| **加载中** | `.loading-state` + 转圈图标 + `role="status"` | 请求在途、字段尚未到达 |
| **没有数据** | `.empty-state`：结论 + 下一步 +（有真实去处时）动作按钮 | 请求成功、结果集为空 |
| **字段缺失** | `--`（现有格式化函数） | 请求成功、该字段确实为空 |
| **请求失败 / 降级** | 沿用现有 `.connection-banner` / `role="alert"` / 分钟线状态条 | 请求失败 |

**加载中绝不用 `--` 顶替**，**缺失绝不用「正在…」掩盖**。

### 7.2 类与视觉

- 新增 `.loading-state`：与 `.empty-state` 共用版式（CSS 以共享选择器 `:is(.empty-state, .loading-state)` 一次性给两者同样的容器/文字规则），差异只有 `svg { animation: spin 1s linear infinite }`（`@media (prefers-reduced-motion: reduce)` 下不转）。
- 语义分开后可机械核对：**加载分支不再写 `empty-state`**。
- 现有 `.empty-state` 文案与结构保持（`styles.css:2606-2633`）；**不新增视觉令牌**。

### 7.3 改造清单

| # | 位置 | 现状 | 改为 |
|---|---|---|---|
| 1 | `ViewScreener.vue:410-413` | `.empty-state` 表示加载 | `.loading-state`「正在读取真实行情」+「行情列表返回后会显示筛选结果。」（文案逐字不变，类与 role 变） |
| 2 | `ViewScreener.vue:235-238` / `:505-508` | 同上 | `.loading-state`（文案逐字不变） |
| 3 | `ViewOverview.vue:144-147` | 同上 | `.loading-state`（文案逐字不变） |
| 4 | `ViewGrid.vue` 策略回测结果（`:503` 前） | 无加载分支 | `v-if="strategyLoading"` → `.loading-state`「正在回放回测…」+「日线逐笔重放完成后显示权益曲线与指标。」；`v-else-if` 空态保留 |
| 5 | `ViewGrid.vue` 多策略对比结果（`:663` 前） | 无加载分支 | `v-if="compare.runLoading"` → `.loading-state`「正在对比…」+「勾选策略将在同一份日线上依次重放。」 |
| 6 | `ViewGrid.vue` 网格建议（`:319` 前） | 无加载分支（有按钮） | `v-if="gridLoading"` → `.loading-state`「正在计算网格参数…」 |
| 7 | `ViewPlans.vue` 复盘面板（`:211` 起） | `review.loading` 无指示 | `v-if="review.loading"` → `.loading-state`「正在回放复盘…」+「按设计口径逐日回放交易计划。」；明细 `review.traceLoading` 同（明细区一个小号 `.loading-state`） |
| 8 | `ViewStockDetail.vue` 报价（`:23-58`） | 刷新期间裸 `--` / 「选择一只股票」 | `quotes.loading && !selectedStock` → 面板内 `.loading-state`「正在读取行情…」；已加载无该码数据 → 保留 `--` 与现有空文案 |
| 9 | `ViewStockDetail.vue` 分钟线（`:87-99`） | 请求在途无提示 | 新增 `minuteLoading` ref：`v-if="minuteLoading"` → `.loading-state`「正在读取分钟线…」；**降级/429 文案与状态条一律不动** |
| 10 | `ViewPortfolio.vue` KPI 行（`:70-118`） | 加载期间裸 `--` | KPI 值槽加载期间显示「计算中」（新增 `kpiText()` 包装：`store.loading ? '计算中' : 现有 null→'--'`）；**缺失仍 `--`** |

### 7.4 空态动作（就地动能优先，否则跳转）

| 空态 | 现状文案 | 动作 | 处理器（已核实存在） |
|---|---|---|---|
| `ViewScreener.vue:414-417` 精选无结果 | 没有找到符合条件的股票 / 可以放宽 PE、PB 或涨幅条件再试一次。 | **就地**「重新读取行情」 | `fetchScreener()`（store 导出，`:107`） |
| `ViewPlans.vue:199-202` 无计划 | 还没有交易计划 / 先写下一个你愿意执行的交易剧本。 | **跳转**「去选股器挑一只」 | `quotes.switchView('screener')` |
| `ViewGrid.vue:503-506` 策略结果 | 运行{策略}回测 / 系统会基于历史日线… | **就地**「运行回测」 | `backtestStrategy()`（配置面板 `:411` 同一动作） |
| `ViewGrid.vue:663-666` 对比结果 | 运行多策略对比 / 同一份历史日线… | **就地**「开始对比」 | `compare.runCompare()`（`:569` 同一动作） |
| `ViewPortfolio.vue:128-132` 无净值 | 暂无计划持仓 / 窗口内还没有可回放的买入计划… | **跳转**「去交易计划」 | `quotes.switchView('plans')` |

- 就地动作 = **同一动作复用同一处理器**，允许与配置面板按钮同名（同一动作同名是「同一事实只写一遍」，不是重复文案）。
- 已有动作按钮的空态（`ViewGrid.vue:319-322` 网格建议、`ViewMonitor.vue:105`）**不动**；纯说明性空态（`ViewOverview` 两处 compact-empty、`ViewGrid.vue:784` 已保存策略、通知面板 `App.vue:180`）**不加按钮**（无真实去处）。

## 8. Toast 规则

### 8.1 新模块 `frontend/src/modules/toastQueue.ts`

```ts
export const TOAST_CAP = 3;
export function durationFor(tone: string): number;          // error 6000，其余 3200
export function toastKey(tone: string, message: string): string;
export function showToast(message: string, tone: string, deps: { renderIcons?: () => void }): void;
export function resetToasts(): void;                        // 测试/卸载
```

`useWorkspaceStore.showToast(message, tone = 'success')` 变薄委托，**签名与返回值不变**。

### 8.2 行为契约

1. **去重**：key = `tone + '\x00' + message`。屏上已有同 key → **不新增节点**，重置计时器（按 `durationFor(tone)` 重计）并加 `.toast-pulse`（CSS 一次性高亮 200ms）提示「刚又发生了一次」。
2. **上限 3**：追加后若子节点数 > 3，从**最旧**（`firstElementChild`）开始移除（`.toast-leaving` 120ms 后摘除）。
3. **可关闭**：整条 toast `cursor:pointer` + `click` 关闭；并内置 `<button class="toast-close" type="button" aria-label="关闭提示">`（图标 `x`）供键盘用户关闭（浮层/Toast 不做焦点陷阱，焦点不被抢）。
4. **暂停**：`mouseenter`/`focusin` → 清计时器；`mouseleave`/`focusout` → 按 `durationFor(tone)` 重计（不做「剩余时长」精确续算，规则简单可预期）。
5. **分时长**：error 6000ms，其余 3200ms（现有 3200 不变）。
6. **播报**：保留 `#toast-region` 的 `aria-live="polite"`；**移除 `aria-atomic="true"`**（区域级 atomic 会在每次新增时把屏上 3 条一起重读）；error 仍靠「图标 + 颜色 + 文案」三重区分，**不用 `assertive`**。
7. **实现方式不变**：仍为命令式 DOM（~75 处调用点与既有 spy 断言零改动）；`renderIcons()` 仍在追加后调用。

## 9. 快捷键

### 9.1 新模块 `frontend/src/modules/shortcuts.ts`

```ts
export const VIEW_SHORTCUTS: Record<string, ViewId> = {
  '1': 'overview', '2': 'screener', '3': 'grid', '4': 'plans',
  '5': 'monitor', '6': 'portfolio', '7': 'settings',
};
export const helpOpen = ref(false);          // 模块级（先例：modules/theme.ts）
export type ShortcutAction = { type: 'view'; view: ViewId } | { type: 'search' } | { type: 'toggle-help' };
export function isTypingTarget(target: EventTarget | null): boolean;
export function shortcutFor(event: KeyboardEvent, ctx: { overlayOpen: boolean; helpOpen: boolean }): ShortcutAction | null;
```

### 9.2 派发规则

| 键 | 动作 | 抑制条件 |
|---|---|---|
| `/` | 聚焦 `.global-search input`（保留 `preventDefault`） | 输入中 / 浮层打开 |
| `1`–`7` | `switchView(view)` | 输入中 / 浮层打开 / 带修饰键 |
| `?`（含全角 `？`） | 开关帮助浮层 | 输入中 / **其它**浮层打开（帮助自身打开时 `?` 关闭它） |
| `Esc` | **不在此处理** | —（由 `overlayA11y` 浮层栈独占，避免双重处理） |

**统一抑制**（任一命中即忽略）：`ctrlKey/metaKey/altKey`、`event.isComposing`（中文输入法组合中）、target 为 `INPUT`/`TEXTAREA`/`SELECT`/`[contenteditable]` 或 `isContentEditable`、`ctx.overlayOpen`（Esc 与 `?` 例外见上）。

### 9.3 接线

- `app.ts:88-102` 重构为「单监听 + 派发器 + 执行器」；监听注册返回值改为 disposer（`onBeforeUnmount` 清理），当前监听从不移除。
- 导航项（`App.vue:30-38`）与抽屉项（`:263-274`）加 `:aria-keyshortcuts="按 id 反查的数字"`；搜索框加 `aria-keyshortcuts="/"`。
- 新增帮助入口：顶栏 `.topbar-actions` 内、搜索框之后加一个 `?` 图标按钮（`aria-label="键盘快捷键"` + `data-tooltip="键盘快捷键"` + `aria-keyshortcuts="?"`），点击 `toggleHelp()`；**所有断点都显示**（≤680 也保留，保证无物理键盘时帮助仍可达）。
- `components/ShortcutHelpDialog.vue`（挂 `App.vue`）：`v-if="helpOpen"` 的 `.dialog-backdrop` + `.dialog-panel`，`role="dialog" aria-modal="true" aria-label="键盘快捷键"`，复用 `useOverlayA11y`；内容为键位表（`/`、`1`–`7`、`?`、`Esc` + `Enter` 在搜索框/回测参数框的提交语义），并注明数字键为**桌面快捷键**。关闭：Esc / `?` / 关闭按钮 / 遮罩。
- 手机端：底栏与抽屉结构不变，帮助浮层可打开（内容注明数字键需物理键盘）。

## 10. ③a 遗留缺口（前三项）

1. **≤1060 图标条主题开关文案竖排**：`styles.css:2841` 的 `@media (max-width: 1060px)` 块内，把 `.sidebar-theme-toggle span` 并入既有的 `display:none` 列表（`:2857-2862`），并给 `.sidebar-theme-toggle` 加 `justify-content: center; padding: var(--space-2) 0`，让 82px 图标条里只剩居中图标（与 `.nav-item` 同）。
2. **下钻控件逐行可访问名**：5 处（§5.5）统一加 `:aria-label="`查看 ${名称} ${代码} 的详情`"`——**名称取自该行模板中已渲染的字段**（如 `quoteFor(plan.code)?.name`），无名称时省略名称段、**代码必须存在**（保证逐行唯一）；**禁止为可访问名新增任何请求或字段**。
3. **通知面板 ARIA/遮罩一致**：见 §6.3。

## 11. 测试策略

**单测（新增）**

| 文件 | 覆盖 |
|---|---|
| `tests/frontend/overlayA11y.test.ts` | 栈顺序（嵌套时只有栈顶响应 Esc）、`focusableWithin` 过滤（disabled / display:none / tabindex=-1）、`nextFocusTarget` 循环（含空集）、锁计数幂等、焦点归还（元素已移除时不报错）、`isOpen` 为假时不挂监听 |
| `tests/frontend/toastQueue.test.ts` | 假时钟：去重（不新增节点 + 重置计时）、上限 3（淘最旧）、点击/按钮关闭、悬停暂停、error 6s vs 普通 3.2s、`resetToasts` |
| `tests/frontend/shortcuts.test.ts` | 抑制矩阵（INPUT/TEXTAREA/SELECT/contenteditable/isComposing/修饰键/浮层打开）、`1`–`7` 映射、`?` 的开与关、`/` 聚焦、Esc 不在表内 |
| `tests/frontend/ShortcutHelpDialog.test.ts` | 渲染键位表、Esc/`?`/关闭按钮/遮罩四种关闭、`aria-modal` + `aria-label` |

**单测（扩展现有）**：`AppShell.test.ts`（顶栏 `?` 按钮 + `aria-keyshortcuts`、通知面板 `aria-modal`、导航项 `aria-keyshortcuts`）、`ViewScreener/ViewGrid/ViewPlans/ViewPortfolio/ViewStockDetail.test.ts`（加载态出现时机、空态按钮与处理器、KPI「计算中」、分钟线加载中、5 处 `aria-label`）。

**真实浏览器验收（复用 ③a 的 playwright 方法，真实 chromium + `npm run dev` + 真后端）**：Esc 关 4 个浮层；Tab/Shift+Tab 在面板内循环且不逃出；浮层打开时 `.view-panel.is-active` 不可滚动且关闭后滚动位置不变；同文案连点 3 次只留 1 条、第 4 条淘最旧、点击可关、error 存活 ≥6s；`1`–`7` 切视图、SELECT 内按 `2` 不切、浮层打开时按 `2` 不切；`?` 开关帮助浮层；≤1060 图标条开关只剩图标（1440/1060/900/680 四宽度截图 + DOM 探针）。

**回归门禁**：`npm run verify`（vitest + vue-tsc + pytest 679）全绿；后端零改动（`git diff --stat <基线>...HEAD -- backend/ tests/` 为空）。

## 12. 机械验收断言

1. `rg -n 'class="empty-state"' frontend/src` 的命中中**不含** `loader-circle`（加载态已改用 `.loading-state`）。
2. `rg -c 'useOverlayA11y\(' frontend/src` = 5。
3. `rg -n 'aria-modal="true"' frontend/src` = 5（4 既有 + 通知面板 + 帮助浮层，含通知面板）。
4. `rg -n "'Escape'" frontend/src` = 1（仅 `modules/overlayA11y.ts`）。
5. `rg -n 'aria-keyshortcuts' frontend/src` ≥ 10（7 导航项 + 2 抽屉同项复用 + 搜索框 + `?` 按钮）。
6. `rg -n 'sidebar-theme-toggle span' frontend/src/styles.css` 命中于 ≤1060 媒体块。
7. `rg -n 'class="empty-state"' frontend/src/views/ViewGrid.vue` = 4（`:319/:503/:663/:784`，`784` 为本批不动的已保存策略）。
8. Toast 与快捷键的键表/上限常量只出现在 `modules/toastQueue.ts` / `modules/shortcuts.ts`（不在视图里散写）。
9. ⛔ 非目标守卫：`rg -n 'skeleton' frontend/src` = 0；`rg -n 'inert' frontend/src` = 0。

## 13. 待用户裁定 / 风险

### 13.1 基线分支（已裁定 2026-10-17）

**裁定 = A，已执行**：③a `feature/ui-layout-ia` 先以 `git flow feature finish --no-ff ui-layout-ia` 合入 `develop`（合并提交 `d756d2a`，本批规格提交在其上 rebase），本批从 `develop` 拉出，为干净独立批次。

被否选项 B（栈式：③b 从 `feature/ui-layout-ia` 拉出、两批有合并先后依赖）仅作记录。

### 13.2 风险与回退

| 风险 | 缓解 |
|---|---|
| 焦点陷阱/滚动锁引入全局副作用（监听泄漏、双重锁） | 栈与计数全在模块内，`resetToasts`/栈为空可自查；单测覆盖嵌套与幂等；真实浏览器复验 |
| Toast 命令式 DOM 与 Vue 生命周期脱节 | 保持现状实现（仅加策略），`resetToasts` 供卸载清理 |
| 空态按钮文案与配置面板同名引起疑惑 | §7.4 已披露为有意为之（同一动作同名）；真实浏览器截图复核 |
| `?`/全角 `？` 与中文输入法冲突 | `isComposing` 抑制 + 同匹配全角；`?` 属可关闭的轻量浮层 |
| `aria-atomic` 移除影响既有播报预期 | 区域保留 `aria-live="polite"`；单层播报是本批明确的规则（§8.2-6） |
| 扩展现有测试文件时误伤既有断言 | 只新增断言，不改既有断言语义；`npm run verify` 门禁 |
