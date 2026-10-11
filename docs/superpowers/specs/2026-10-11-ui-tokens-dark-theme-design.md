# UI 优化第①批：设计令牌收敛 + 暗色主题基建 — 设计 Spec

- **日期：** 2026-10-11
- **状态：** 待用户复审（复审通过前禁止开发）
- **计划分支：** `feature/ui-tokens-dark-theme`（Git Flow，spec 与实现同分支）
- **路线图定位：** 「整体界面优化」三批推进的第①批（地基）；②视觉观感打磨、③布局 IA + 交互一致性随后独立成批

## 1. 背景与目标

用户提出整体界面优化，四个方向全选：视觉观感、布局与信息架构、交互与反馈、暗色主题。经拆解裁定**按依赖分三批**，本批为第①批——把 `frontend/src/styles.css`（4410 行，`:root` 外 103 处裸色值）与组件层 17 处 hex 收敛为语义化设计令牌，并在其上交付**暗色主题**（浅色/深色/跟随系统三态）。这一批是地基：后续视觉打磨只改令牌值，浅暗两套主题同时受益。

**已裁定决策（2026-10-11 用户确认）：**

1. 三批推进，本批先做令牌 + 暗色基建。
2. **浅色主题像素级零变化**——本批只做等价收敛，观感变化全部留给第②批。
3. 暗色基调：**B · 中性炭灰**（VS Code / Linear 式纯中性灰阶，视觉伴侣小样对比后选定）。
4. 令牌架构：**方案 A**——复用现有变量名 + `html[data-theme='dark']` 覆盖层；否决双层令牌体系（原语层+语义层，对单用户工具过度工程）。
5. 持久化走 **localStorage**（前端自闭环、零后端改动）；跨浏览器同步需求出现时再迁 workspace settings，本批不预设。

## 2. 非目标

- 任何浅色主题下的视觉变化（字号/间距/阴影/圆角/配色均不动——第②批内容）。
- 布局与信息架构调整、侧栏导航分组（第③批内容）。
- 加载态/空态/toast 的交互行为改造（第③批内容；本批只保证暗色下呈现正确）。
- 自定义配色（用户自定义主题色）与多语言——ROADMAP 另一项，本批不触碰。
- `styles.css` 拆分为多文件、CSS-in-JS 化——无关重构，不做。
- 后端改动（零 API/schema 变更，零迁移）。

## 3. 令牌收敛与映射原则

现状：`:root` 28 个变量名值不动；`:root` 之外 103 处裸 hex/rgba + 组件/TS 层 17 处 hex（`useCompareStore` 8 处、`ViewPortfolio` 3 处、`ViewStockDetail` 2 处、`chart.ts` 2 处、`ViewOverview` 1 处、样式表其余）需收敛。

**映射三规则（实现计划产出逐行映射表，spec 定原则）：**

1. 字面量值与现有令牌相同 → 直接替换为 `var(--existing)`。
2. 同一值出现 ≥2 次且无对应现有令牌 → 新增语义令牌，全部裸值引用之。
3. 仅出现一次的装饰色 → 归入语义最近的现有令牌，或新增专用令牌；**不留裸值**。

**新增语义令牌（预计 12-15 个，计划期定稿）：**

- `--up` / `--up-soft` / `--down` / `--down-soft`：A 股红涨绿跌语义别名（浅色初值分别等于 `--red/--red-soft/--green/--green-soft` 的现值，二者保持独立定义以便主题分别取值）。
- `--chart-1` … `--chart-8`：图表系列色（浅色初值 = 现 `useCompareStore.COMPARE_COLORS` 八色，色相不变）。
- `--scrim`：对话框/浮层遮罩色。
- `--hover-fill`：列表/按钮悬停填充色（现为若干 rgba 字面量）。
- 收敛过程中发现的其他必要语义（计划申报）。

**验收即机械可查：** `grep -rnoE "#[0-9a-fA-F]{3,8}\b|rgba?\(" frontend/src`（排除 `styles.css` 的 `:root` 与 `[data-theme='dark']` 令牌块）结果为 **0**；`tests/` 目录不受此约束（测试断言字符串允许）。

## 4. 暗色值表（data-theme='dark' 覆盖同一套变量名）

核心值（浏览器小样 B 基调目视确认）：

| 令牌 | 浅色（保持不变） | 暗色 |
|---|---|---|
| `--canvas` / `--surface` | `#eef1f4` / `#ffffff` | `#101113` / `#191b1e` |
| `--surface-soft` / `--surface-tint` | `#f7f8fa` / `#f1f5f6` | `#222528` / `#1e2125` |
| `--ink` / `--ink-soft` | `#152033` / `#334057` | `#e9ebee` / `#c9cdd3` |
| `--muted` / `--muted-strong` | `#7d8798` / `#5e6a7d` | `#9aa1ab` / `#b3bac2` |
| `--line` / `--line-strong` | `#e2e6eb` / `#d2d9e1` | `#2e3237` / `#3c4148` |
| `--sidebar` / `--sidebar-soft` / `--sidebar-muted` | `#101a2b` / `#17243a` / `#93a0b6` | `#16171a` / `#1f2125` / `#9aa1ab` |
| `--coral` / `--coral-dark` / `--coral-soft` | `#ef6d53` / `#d95b42` / `#fff0eb` | `#ef6d53` / `#ff8a70` / `#3a221c` |
| `--red` / `--red-soft` | `#d75450` / `#fff0ef` | `#e06c6c` / `#3a2222` |
| `--green` / `--green-soft` | `#258f76` / `#eaf7f3` | `#35a583` / `#1d332c` |
| `--blue` / `--blue-soft` | `#3b6fb6` / `#edf3fb` | `#5e8fd6` / `#1f2c40` |
| `--gold` / `--gold-soft` | `#aa7d22` / `#fff7df` | `#d1a54a` / `#383018` |
| `--shadow` / `--shadow-small` | 现值 | 加深黑阴影（如 `0 14px 34px rgba(0,0,0,0.45)`） |

**派生规则（计划期产出全表）：**

- `*-soft` 类：浅色是「主色的浅底」，暗色反转为「主色的深底」（主色同色相提亮）。
- `coral-dark/muted-strong` 等「强度词」令牌：暗色下强度方向反转（hover 态主色变亮、强调灰变亮）。
- `--chart-1..8`：浅色 = 现 `COMPARE_COLORS` 八色原值；暗色 = 同色相提升亮度，对 `--surface` 对比度 ≥3:1（图形件目标）。
- `--scrim`：浅色沿用现遮罩 rgba；暗色加深（如 `rgba(0,0,0,0.65)`）。
- 上表未覆盖的令牌（`radius` 等非颜色令牌）不随主题变化。

## 5. 切换机制与持久化

- **状态模型：** `localStorage` 键 `atlas-theme`，值 `'light' | 'dark'`；**键不存在 = 跟随系统**（`matchMedia('(prefers-color-scheme: dark)')`）。无第三种存储值——「跟随系统」是缺省态而非存储态。
- **应用方式：** `document.documentElement.dataset.theme = 'light' | 'dark'`；CSS 侧 `:root { …浅色值… }` + `html[data-theme='dark'] { …暗色值… }`。
- **FOUC 防护：** `main.ts` 在 `createApp` **之前**同步调用 `initTheme()`（读 localStorage → 解析有效主题 → 设 `data-theme` → 注册 matchMedia 监听），首帧即正确主题。
- **跟随系统：** matchMedia `change` 监听仅在**未显式选择**（键不存在）时联动；一旦用户显式选择，系统变化不再影响，直至在设置页选回「跟随系统」（即删除存储键）。
- **新模块 `frontend/src/modules/theme.ts`**（不新建 Pinia store——单值状态不值得一个 store）：
  - `getStoredTheme(): 'light' | 'dark' | null`
  - `getEffectiveTheme(): 'light' | 'dark'`（stored ?? matchMedia 结果）
  - `applyTheme(): void`（按 effective 设 `data-theme`）
  - `setTheme(theme: 'light' | 'dark' | null): void`（null = 回到跟随系统：删键 + apply）
  - `initTheme(): void`（apply + 注册 matchMedia 监听；模块内聚一个 Vue `ref` 供组件响应式读当前主题）
  - **健壮性：** localStorage 读写 try/catch（隐私模式/禁用 → 静默降级为跟随系统，不崩溃）；存储值非法（非 `light/dark`）→ 视同未设。
- **入口两处：**
  - 侧栏底部快捷开关（`App.vue`，lucide `sun`/`moon` 图标）：点击在浅/深间切换并**显式写入** localStorage；按钮呈现当前 effective 主题的对侧图标。
  - 设置页新增「外观」卡片（`ViewSettings.vue`）：三态单选「浅色 / 深色 / 跟随系统」，选择即生效；「跟随系统」= `setTheme(null)`。纯前端偏好，不入 workspace settings、不走 revision 同步。

## 6. 图表与特殊面取色

- `chart.ts` 的 `chartSvg` / `compareChartSvg` 已通过 CSS class 着色（styles.css 控制）→ 令牌化后自动适配，组件零改动。
- `multiLineSvg` 系列与图例色块经内联 `style="stroke:…"` / `style="fill:…"` 输出——调用方从硬编码 hex 改传 `var(--chart-N)`（内联 style 支持 CSS 变量，暗色自动跟随）。
- `useCompareStore.COMPARE_COLORS` → `['var(--chart-1)', …, 'var(--chart-8)']`；`ViewPortfolio` / `ViewStockDetail` / `ViewOverview` / `chart.ts` 的 hex 逐处映射至对应令牌。
- 安全纪律不变：`showToast` 保持 `textContent`，SVG 文本插值保持 `escapeHtml`，本批不新增 `v-html` 面。

## 7. 错误处理与边界

- localStorage 不可用（隐私模式/被禁用）：读写 try/catch，静默降级为跟随系统，功能不崩。
- 存储值被手工改坏：非 `light/dark` 一律视同未设（跟随系统）。
- matchMedia 不可用（极端环境）：`getEffectiveTheme` 兜底返回 `'light'`。
- 主题切换不触发任何网络请求、不影响轮询与 workspace revision 状态。

## 8. 测试计划

- **新增 `tests/frontend/theme.test.ts`：** 解析矩阵（未设+系统深/浅、显式 light/dark、非法值归一、setTheme(null) 删键回跟随、localStorage 抛异常降级、matchMedia 变化联动仅在未显式选择时生效）；`applyTheme` 写入 `data-theme` 断言。localStorage/matchMedia 全 mock。
- **既有测试同步（计划申报具体断言）：** `chart.test.ts` 中颜色字符串断言（hex → `var(--chart-N)`）；`useCompareStore.test.ts` 若断言 COMPARE_COLORS 值需同步；`ViewSettings.test.ts` 补外观卡片冒烟；`App.vue` 若有测试则补侧栏开关渲染断言。
- **`npm run verify` 全绿**（后端零改动，应无波动）。

## 9. 验收清单

- [ ] 浅色像素级不变：`:root` 值零改动 + 103/17 处映射等价（计划映射表逐行值相同）。
- [ ] 裸色值 grep 断言为 0（§3 命令）。
- [ ] 暗色走查：8 视图 + PlanDraftDialog/CustomStrategyDialog + toast + 空态 + 全部图表，无漏色、无可读性问题；正文对比度 ≥4.5:1、次要文字 ≥3:1（抽查实测记录）。
- [ ] 三态切换即时生效不刷新；刷新保持；跟随系统联动正确；显式选择后不受系统变化影响。
- [ ] `theme.test.ts` 全过；`npm run verify` 全绿。
- [ ] 文档收口：AGENTS.md modules 清单加 `theme.ts`；ROADMAP「多语言/自定义主题配色」项注记「主题基建（浅/深/跟随系统）已交付 2026-10-11，自定义配色与多语言仍待」；CHANGELOG v0.7.3（或随下一版本）条目。

## 10. 已知限制（如实披露）

- 本批不含任何观感提升——浅色用户升级后界面与之前完全一致（有意为之，观感归②批）。
- 主题偏好存 localStorage：换浏览器/清缓存回到跟随系统（单机单浏览器定位下可接受；跨端同步需求出现后再迁 DB）。
- 暗色下第三方内嵌内容（如有）不随主题；当前无此类内容。
- 裸值收敛以静态 grep 为准，动态拼接的颜色字符串（当前不存在）不在断言范围。

## 11. Self-Review 记录

- 占位符扫描：无 TBD/TODO；§3/§4 的「计划期定稿/产出全表」为数据依赖（映射表需逐行比对实际代码，属实现计划产物，非未实现内容）。
- 一致性：§4 表与 §5 状态模型、§3 验收命令互相引用一致；`setTheme(null)` 语义与「跟随系统是缺省态」一致。
- 范围：单一实现计划可承载（styles.css 收敛 + theme.ts + 两处入口 + 测试），无需再拆。
- 歧义修复：明确「跟随系统」不是存储值而是缺省态；明确 `tests/` 不在裸值 grep 断言范围。
