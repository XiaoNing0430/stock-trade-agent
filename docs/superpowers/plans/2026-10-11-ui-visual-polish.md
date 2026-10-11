# UI 第②批：视觉观感打磨 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立字阶/间距/圆角/阴影四类版式令牌并全站归并（A 密度 + B 字阶），四族组件精修，playwright 前后截图对比验收。

**Architecture:** 全部走 CSS 令牌（`:root` 追加，主题无关不进 dark 块）；styles.css 全量替换分四步（字号 → 间距 → 圆角阴影 → 四族精修），每步机械验收；旧 `--radius/--radius-small/--shadow/--shadow-small` 迁移后删除。

**Tech Stack:** 原生 CSS 变量；playwright（node_modules 自带）截图对比；vitest；零后端改动。

**Spec:** `docs/superpowers/specs/2026-10-11-ui-visual-polish-design.md`（已评审通过，含两处修订：平局向上、阶梯至 space-8）

## Global Constraints

- 分支 `feature/ui-visual-polish`（已建好，spec 已在其上提交）。
- **版式令牌主题无关**：`--fs-*/--space-*/--radius-*/--shadow-sm/md` 定义在 `:root`，**不进 dark 块**（dark 块行数不变）。
- 字阶 5 档：`--fs-xs 11 / --fs-sm 12 / --fs-md 14 / --fs-lg 18 / --fs-xl 24`（px）。
- 间距 8 档：`--space-1..8` = 4/8/12/16/20/24/28/32（px）；取整规则**最近取整、平局向上**。
- 圆角三档：`--radius-sm 6 / --radius-md 8 / --radius-lg 12`；`999px/50%` 保留。
- 阴影：`--shadow-sm`（=现 `--shadow-small` 值）、`--shadow-md`（=现 `--shadow` 值）；`--shadow-hairline`/`--knob-shadow`/`--glow-*` 保留不动。
- 迁移完成后旧令牌删除：`var(--radius)`/`var(--radius-small)`/`var(--shadow)`/`var(--shadow-small)` 残留为 0（styles.css 与 .vue/.ts 全仓）。
- 替换范围仅 styles.css（.vue/.ts 无硬编码字号/间距——Task 2 grep 预核验，如有则申报处理）。
- 提交信息中文 Conventional Commits；pre-commit 门禁先本地跑绿。
- 零后端改动。

---

### Task 1: before 截图 + 版式令牌定义

**Files:**
- Create: `E:\Data\Code\AI\stock-trade-agent\.superpowers\sdd\2026-10-11-ui-visual-polish\screens\before\*.png`（git-ignored，走查产物）
- Modify: `frontend/src/styles.css`（`:root` 追加令牌）

**Interfaces:**
- Produces: Task 2-5 消费的全部版式令牌；before 截图（Task 6 对比基准）。

- [ ] **Step 1: 采集 before 截图**

启动 `npm run dev`（后台；若 5173 已有遗留 dev server 直接复用）。用 node + playwright（从仓库根 `require('playwright')` 或 `require('playwright-core')`，chromium 已随依赖安装）写脚本：访问 `http://127.0.0.1:5173`，依次点击侧栏导航（总览/盯盘/选股/股票详情——详情需先在选股或自选点开一只票，无票则截选股详情空态并记录/策略实验室/计划/组合风险/设置），每视图截浅色一张；执行 `localStorage.setItem('atlas-theme','dark'); location.reload()` 后再截深色一套。存 `.superpowers/sdd/2026-10-11-ui-visual-polish/screens/before/<view>-<light|dark>.png`。视图片名清单：`overview monitor screener stock-detail grid plans portfolio settings`。某视图无法到达（如详情无票）时截其空态并在报告注明。

- [ ] **Step 2: `:root` 追加版式令牌（`--radius-small: 8px;` 行之后）**

```css
  /* ===== 版式令牌（第②批：字阶/间距/圆角/阴影，主题无关） ===== */
  --fs-xs: 11px;
  --fs-sm: 12px;
  --fs-md: 14px;
  --fs-lg: 18px;
  --fs-xl: 24px;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-7: 28px;
  --space-8: 32px;
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --shadow-sm: 0 5px 16px rgba(21, 32, 51, 0.07);
  --shadow-md: 0 14px 34px rgba(21, 32, 51, 0.06);
```

- [ ] **Step 3: 验证渲染零变化（纯添加）**

Run: `npx vitest run`（应 276 全绿）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles.css
git commit -m "feat: styles.css 新增版式令牌（字阶/间距/圆角/阴影，渲染零变化）"
```

---

### Task 2: 字号全量替换（134 处 → var(--fs-*)）

**Files:**
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: Task 1 的 `--fs-*`。
- Produces: styles.css 中 `font-size: \d` 像素字面量为 0（机械验收）。

- [ ] **Step 1: 预核验替换范围**

Run: `grep -rn "font-size" frontend/src --include="*.vue" --include="*.ts" | grep -v node_modules`
Expected: 无输出（若有命中：逐处按同规则令牌化并在报告申报）。

- [ ] **Step 2: 按值映射全局替换（值→令牌无歧义，可安全全局替换）**

| 现值 | 目标 | 处数（实测） |
|---|---|---|
| `font-size: 9px` | `font-size: var(--fs-xs)` | 2 |
| `font-size: 10px` | `font-size: var(--fs-xs)` | 48 |
| `font-size: 11px` | `font-size: var(--fs-xs)` | 41 |
| `font-size: 12px` | `font-size: var(--fs-sm)` | 43 |
| `font-size: 13px` | `font-size: var(--fs-sm)` | 20 |
| `font-size: 14px` | `font-size: var(--fs-md)` | 1 |
| `font-size: 15px` | `font-size: var(--fs-md)` | 2 |
| `font-size: 16px` | `font-size: var(--fs-md)` | 5 |
| `font-size: 18px` | `font-size: var(--fs-lg)` | 2 |
| `font-size: 19px` | `font-size: var(--fs-lg)` | 1 |
| `font-size: 20px` | `font-size: var(--fs-lg)` | 5 |
| `font-size: 22px` | `font-size: var(--fs-lg)` | 1 |
| `font-size: 25px` | `font-size: var(--fs-xl)` | 1 |
| `font-size: 26px` | `font-size: var(--fs-xl)` | 1 |

合计 134。替换后 `grep -c "font-size: [0-9]" frontend/src/styles.css` 必须为 **0**；`grep -oE "var\(--fs-[a-z]+\)" frontend/src/styles.css | sort -u` 恰 5 种。

- [ ] **Step 3: 验证与提交**

Run: `npx vitest run && npx vue-tsc --noEmit`
Expected: 全绿（纯 CSS）。

```bash
git add frontend/src/styles.css
git commit -m "refactor: 字号全量收敛为字阶令牌（14 种→5 档）"
```

---

### Task 3: 间距栅格化 + 令牌化（432 处声明）

**Files:**
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: Task 1 的 `--space-1..8`。
- Produces: 间距声明仅含 `var(--space-*)` 或允许字面量（0/1px/2px/auto/>32px 的 4 倍数/999px/50%）。

- [ ] **Step 1: 按单值映射表替换（完整覆盖实测全部 distinct 值）**

对每个 spacing 声明（padding/margin/gap/row-gap/column-gap 及四向子属性）的**每个 px 分量**独立按下表映射：

| 现值 | 目标 | 现值 | 目标 |
|---|---|---|---|
| 1px | `1px`（保留） | 13px | `var(--space-3)` |
| 2px | `2px`（保留） | 14px | `var(--space-4)` |
| 3px | `var(--space-1)` | 15px | `var(--space-4)` |
| 4px | `var(--space-1)` | 16px | `var(--space-4)` |
| 5px | `var(--space-1)` | 17px | `var(--space-4)` |
| 6px | `var(--space-2)` | 18px | `var(--space-5)` |
| 7px | `var(--space-2)` | 19px | `var(--space-5)` |
| 8px | `var(--space-2)` | 20px | `var(--space-5)` |
| 9px | `var(--space-2)` | 21px | `var(--space-5)` |
| 10px | `var(--space-3)` | 22px | `var(--space-6)` |
| 11px | `var(--space-3)` | 24px | `var(--space-6)` |
| 12px | `var(--space-3)` | 25px/26px | `var(--space-6)` |
| 27px/28px/29px | `var(--space-7)` | 32px | `var(--space-8)` |
| 38px | `40px` | 42px | `44px` |
| 96px | `96px` | 0/auto | 保留 |

组合值按分量独立映射（如 `10px 12px` → `var(--space-3) var(--space-3)`，可简写为 `var(--space-3)`；`8px 10px` → `var(--space-2) var(--space-3)`）。高频组合实测对照：`10px 12px`×9→`var(--space-3)`、`0 10px`×5→`0 var(--space-3)`、`8px 10px`×4→`var(--space-2) var(--space-3)`、`9px 10px`×2→`var(--space-2) var(--space-3)`、`6px 0`×3→`var(--space-2) 0`、`0 9px`×3→`0 var(--space-2)`、`5px 8px`×2→`var(--space-1) var(--space-2)`、`5px 14px`×2→`var(--space-1) var(--space-4)`、`10px 16px`×2→`var(--space-3) var(--space-4)`、`1px 7px`×2→`1px var(--space-2)`。

- [ ] **Step 2: 机械验收（命令已预验证）**

```bash
grep -oE "(padding|margin|gap|row-gap|column-gap)(-top|-right|-bottom|-left)?: [^;]+;" frontend/src/styles.css | grep -oE "[0-9]+px" | sort -n | uniq -c
```
Expected: 输出仅含 `1px`、`2px`、`40px`、`44px`、`96px` 五种（当前基线含 3-29px 共 29 种）。若出现其他值：按映射表补替换。

- [ ] **Step 3: 验证与提交**

Run: `npx vitest run && npx vue-tsc --noEmit`
Expected: 全绿。

```bash
git add frontend/src/styles.css
git commit -m "refactor: 间距全量落 4px 栅格并令牌化（最近取整平局向上）"
```

---

### Task 4: 圆角/阴影迁移 + 旧令牌删除

**Files:**
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: Task 1 的 `--radius-sm/md/lg`、`--shadow-sm/md`。
- Produces: `var(--radius)`/`var(--radius-small)`/`var(--shadow)`/`var(--shadow-small)` 全仓残留 0；:root 中这四个旧定义删除。

- [ ] **Step 1: 圆角替换**

| 现值 | 目标 | 处数（实测） |
|---|---|---|
| `border-radius: 5px` | `border-radius: var(--radius-sm)` | 7 |
| `border-radius: 7px` | `border-radius: var(--radius-md)` | 8 |
| `border-radius: 8px` | `border-radius: var(--radius-md)` | 17 |
| `border-radius: 10px` | `border-radius: var(--radius-md)` | 8（全部为条形/头像/小面板，md 档；选择器清单：.breadth-bar/.stock-avatar/.risk-bar/.draft-params/.preset-hit/.desk-stat-row/.grid-provenance/嵌套 1 处） |
| `border-radius: 12px` | `border-radius: var(--radius-lg)` | 4 |
| `border-radius: var(--radius-small)` | `border-radius: var(--radius-md)` | 11 |
| `border-radius: var(--radius)` | `border-radius: var(--radius-lg)` | 2 |
| 999px / 50% | 保留 | — |

- [ ] **Step 2: 阴影替换**

| 现值 | 目标 | 处数 |
|---|---|---|
| `box-shadow: var(--shadow)` | `box-shadow: var(--shadow-md)` | 3 |
| `box-shadow: var(--shadow-small)` | `box-shadow: var(--shadow-sm)` | 1 |
| `var(--shadow-hairline)` / `--knob-shadow` / `--glow-*` | 保留 | — |

- [ ] **Step 3: 删除旧令牌定义**

从 `:root` 删除 `--radius: 12px;`、`--radius-small: 8px;`、`--shadow: …;`、`--shadow-small: …;` 四行。

- [ ] **Step 4: 机械验收**

```bash
grep -n "var(--radius)\|var(--radius-small)\|var(--shadow)\|var(--shadow-small)" frontend/src/styles.css frontend/src -r --include="*.vue" --include="*.ts"
grep -oE "border-radius: [^;]+" frontend/src/styles.css | sort | uniq -c | sort -rn
```
Expected: 第一条无输出（注意 `var(--radius-sm` 是 `var(--radius)` 的前缀——用 `var(--radius)` 精确匹配时须带右括号或行尾判断，避免误报）；第二条仅含 `var(--radius-sm|md|lg)`、`999px`、`50%` 五种。

- [ ] **Step 5: 验证与提交**

Run: `npx vitest run && npx vue-tsc --noEmit`
Expected: 全绿。

```bash
git add frontend/src/styles.css
git commit -m "refactor: 圆角三档与阴影两档迁移，删除旧版式令牌"
```

---

### Task 5: 四族组件精修

**Files:**
- Modify: `frontend/src/styles.css`（仅以下选择器块的尺寸/间距/字阶行）

**Interfaces:**
- Consumes: Task 1-4 的全部版式令牌。
- Produces: 四族组件统一尺寸（截图对比验收）。

- [ ] **Step 1: 按逐规则表精修（selector | 属性 | 旧 | 新）**

**按钮体系**：

| 选择器 | 属性 | 旧 | 新 |
|---|---|---|---|
| `.button` | `gap` | 7px | `var(--space-2)` |
| `.button` | `min-height` | 35px | `34px` |
| `.button` | `padding` | 0 13px | `0 var(--space-3)` |
| `.button` | `border-radius` | 7px | `var(--radius-md)` |
| `.button` | `font-size` | 12px | `var(--fs-sm)` |
| `.text-button` | `gap` | 5px | `var(--space-1)` |
| `.text-button` | `font-size` | 11px | `var(--fs-xs)` |
| `.icon-button` | 高度/宽度 | （读现值） | `28px`（sm 档；若现值≥30 则下调并申报） |

**数据表格**：

| 选择器 | 属性 | 旧 | 新 |
|---|---|---|---|
| `.data-table th` | `padding` | 9px 9px | `var(--space-2) var(--space-3)` |
| `.data-table th` | `font-size` | 10px | `var(--fs-xs)` |
| `.data-table td` | `padding` | 12px 9px | `var(--space-2) var(--space-3)` |
| `.data-table td` | `font-size` | 11px | `var(--fs-sm)` |

（td 上下 12→8 与字号 11→12 相抵后行高 ≈ 12×1.45+16 ≈ 33px，密度略增；若 Task 3 已把此处替换为空间令牌，则只改与目标不同的分量。）

**表单控件**：

| 选择器 | 属性 | 旧 | 新 |
|---|---|---|---|
| `.field` | `gap` | 7px | `var(--space-2)` |
| `.field > span` | `gap` | 7px | `var(--space-2)` |
| `.field > span` | `font-size` | 11px | `var(--fs-xs)` |
| `.field select/input` 组 | `height` | 34px | `32px` |
| `.field select/input` 组 | `padding` | 0 9px | `0 var(--space-2)` |
| `.field select/input` 组 | `border-radius` | 7px | `var(--radius-md)` |
| `.field textarea` | `padding` | 9px | `var(--space-2)` |

（注：表单控件 focus 环已在第①批统一为 `--focus-ring` 的组若有遗漏——grep `:focus` 核对，未统一的补 `box-shadow: 0 0 0 3px var(--focus-ring)`。）

**卡片与标题层级**：

| 选择器 | 属性 | 旧 | 新 |
|---|---|---|---|
| `.surface-heading` | `gap` | 15px | `var(--space-4)` |
| `.surface-heading h3` | `font-size` | 16px | `var(--fs-md)` |
| `.surface-heading h3` | `margin` | 3px 0 0 | `var(--space-1) 0 0` |
| `.section-kicker`（读现值） | `font-size` | （现值） | `var(--fs-xs)` |
| `.heading-note`（读现值） | `font-size` | （现值） | `var(--fs-sm)` |

（「读现值」行：替换时读该选择器现行 font-size 按映射表落档；其余四族外选择器的字号已由 Task 2 全量覆盖，本任务只动上述结构性规则。）

- [ ] **Step 2: 验证与提交**

Run: `npx vitest run && npx vue-tsc --noEmit`
Expected: 全绿（若组件测试断言具体像素——如 ViewSettings 表单尺寸——同步断言并申报）。

```bash
git add frontend/src/styles.css
git commit -m "feat: 四族组件精修——表格/表单/按钮/卡片标题统一版式节奏"
```

---

### Task 6: after 截图对比 + verify + 文档收口

**Files:**
- Create: `.superpowers/sdd/2026-10-11-ui-visual-polish/screens/after/*.png`
- Modify: `AGENTS.md`、`CHANGELOG.md`

- [ ] **Step 1: after 截图（同 Task 1 脚本，存 `screens/after/`）**

同参数重跑 8 视图 × 浅/深 16 张。

- [ ] **Step 2: 前后对比走查**

逐视图成对核对（Read 图片）：版式更齐（字阶/间距/圆角一致）、无布局断裂、无文字截断/换行恶化（重点：侧栏宽标签、表格长代码列、按钮文字、中文换行）、深浅两套同构。发现断裂性换行/截断：定位规则修复（如补 `white-space: nowrap` 或微调该处 padding）并申报——这是精修清单内必须修复项。纯「更密/更松」的主观感受不算问题。

- [ ] **Step 3: 全量验证**

Run: `npm run verify`
Expected: 前端 276 全绿（纯 CSS 无波动；如有组件断言像素则同步）、后端 679 全绿、覆盖率 ≥80%。

- [ ] **Step 4: 文档收口**

- `AGENTS.md`：styles.css 行描述更新为「全部样式（CSS 变量令牌体系：颜色+版式[字阶/间距/圆角/阴影]，:root 浅色 + [data-theme='dark'] 暗色，单文件）」。
- `CHANGELOG.md`：[v0.7.2] 段落内「UI 主题基建（第①批）」之后追加小节：

```markdown
### UI 视觉打磨（第②批）

- 版式令牌阶梯：字阶 14 种收敛为 5 档（11/12/14/18/24，`--fs-*`）、间距全量落 4px 栅格（`--space-1..8`）、圆角 8 种收敛为三档（6/8/12，`--radius-sm|md|lg`）、阴影两档（`--shadow-sm|md`）；旧版式令牌删除。
- 四族组件精修：数据表格 33px 行高统一、表单控件 32px 高 + 焦点环统一、按钮三档高度（28/34/38）、卡片标题节奏统一。全站版面 ±1-2px 位移与字号 ±1px 变化属本批目的（A 密度 + B 字阶方向，用户选定）。
- playwright 8 视图 × 浅/深前后截图对比验收。
```

- [ ] **Step 5: 提交并核验**

```bash
git add AGENTS.md CHANGELOG.md
git commit -m "docs: 收口 UI 第②批（版式令牌体系描述/CHANGELOG 视觉打磨小节）"
git log --oneline -9
```

Expected: 分支 8-9 提交（spec 3 + Task 1-6），工作树干净。

---

## Self-Review 记录

1. **Spec 覆盖**：§3 字阶 → Task 2；§4 间距/圆角/阴影 → Task 3/4；§5 四族 → Task 5；§6 before 截图 → Task 1、after 对比 → Task 6；§7 机械验收 → Task 2/3/4；§8 verify+文档 → Task 6；§9 限制已披露。无缺口。
2. **占位符**：无 TBD；「读现值」的 4 行（icon-button/section-kicker/heading-note）为数据依赖——替换时按映射表落档，规则确定；Task 5 表格未覆盖的 selector 块由 Task 2/3 全量替换先行覆盖。
3. **类型一致性**：令牌名 `--fs-*`/`--space-*`/`--radius-*`/`--shadow-sm|md` 在 Task 1（定义）与 Task 2-5（消费）逐字一致；旧令牌删除仅在 Task 4 且验收断言兜底。
4. **验收命令**：间距 grep（已预验证当前基线含 3-29px 非栅格值，改后仅剩 1/2/40/44/96）；字号/圆角/旧令牌 grep 语义明确。
