# UI 第①批：设计令牌收敛 + 暗色主题基建 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 styles.css 与组件层的 ~120 处裸色值收敛为语义令牌（浅色像素级零变化），并交付浅/深/跟随系统三态主题。

**Architecture:** 方案 A——`:root` 现有 28 个变量名值不动，新增 ~69 个语义令牌（浅色值 = 现字面量），`html[data-theme='dark']` 覆盖同一套变量名；`modules/theme.ts` 内聚状态与 localStorage/matchMedia；图表经内联 `style` 传 `var(--chart-N)`。

**Tech Stack:** 原生 CSS 变量 + Vue 3 `ref`（无新依赖）；vitest 单测；零后端改动。

**Spec:** `docs/superpowers/specs/2026-10-11-ui-tokens-dark-theme-design.md`（已评审通过）

## Global Constraints

- 分支 `feature/ui-tokens-dark-theme`（已建好，spec 已在其上提交），直接提交。
- **浅色像素级零变化**：`:root` 现有 28 变量名值逐字不动；新增令牌浅色值 = 被替换字面量的**精确值**（本计划唯一例外为无——Task 1 采用 `--sidebar-hover`/`--sidebar-hover-soft` 分立令牌保住 0.045 与 0.05 两个原值，全计划**无任何渲染偏差**）。
- 收敛后裸色值断言为 0：styles.css 仅 `:root` 与 `[data-theme='dark']` 两个令牌块内允许字面量；`frontend/src` 的 `.vue`/`.ts`（不含 tests/）grep hex 为 0。
- 暗色覆盖块**只允许出现在文件末尾**的 `html[data-theme='dark'] { … }` 单一块内。
- 安全纪律不变：`showToast` 用 `textContent`；SVG 文本插值过 `escapeHtml`；不新增 `v-html` 面。
- 提交信息中文 Conventional Commits；ruff/eslint/prettier/mypy/vue-tsc pre-commit 门禁先本地跑绿。
- 零后端改动（无 API/schema/迁移）。

---

### Task 1: styles.css 令牌基建（:root 新增 + dark 覆盖块，渲染零变化）

**Files:**
- Modify: `frontend/src/styles.css`（`:root` 块末尾追加新令牌；文件末尾追加 dark 覆盖块）

**Interfaces:**
- Produces: Task 2 依赖的 69 个新令牌名（浅色值如下）；Task 3-5 依赖的 `--chart-1..8`、`--chart-benchmark`、`--chart-baseline`、`--chart-watch`、`--coral`、`--blue`、`--muted`、`--ink`。

- [ ] **Step 1: 在 `:root` 块末尾（`--radius-small: 8px;` 之后、块内）追加新令牌浅色值**

```css
  /* ===== 语义令牌扩充（2026-10-11 令牌收敛；浅色值=原字面量，渲染零变化） ===== */
  /* 侧栏/深色面板文字与结构 */
  --sidebar-text: #ffffff;
  --sidebar-text-bright: #eef3fb;
  --sidebar-text-soft: #f7faff;
  --sidebar-text-dim: #dce5f2;
  --sidebar-kbd: #7e8aa1;
  --sidebar-label: #65728a;
  --sidebar-line: rgba(255, 255, 255, 0.08);
  --sidebar-line-strong: rgba(255, 255, 255, 0.1);
  --sidebar-hover: rgba(255, 255, 255, 0.05);
  --sidebar-hover-soft: rgba(255, 255, 255, 0.045);
  --sidebar-coral-bg: rgba(239, 109, 83, 0.14);
  --sidebar-active-line: rgba(239, 109, 83, 0.22);
  --sidebar-coral-text: #ff9a83;
  --sidebar-green: #a8e4d0;
  --dot-idle: #aeb8c6;
  /* 状态点与光晕 */
  --status-green: #66d4ac;
  --status-gold: #d6a54a;
  --status-coral: #ef7b68;
  --glow-green: rgba(37, 143, 118, 0.14);
  --glow-green-soft: rgba(102, 212, 172, 0.1);
  --glow-gold: rgba(214, 165, 74, 0.1);
  --glow-coral: rgba(239, 123, 104, 0.1);
  /* 强调色上的文字 / 珊瑚系浅底 */
  --on-accent: #ffffff;
  --on-ink: #ffffff;
  --coral-wash: #fff8f6;
  --coral-tint: rgba(239, 109, 83, 0.12);
  --coral-line: #f3d0c7;
  --coral-line-strong: #f0c6bb;
  --chart-coral-fill: rgba(239, 109, 83, 0.09);
  /* 蓝系 / 焦点 */
  --blue-line: #b5cce8;
  --chip-blue-bg: #d8e4f1;
  --chip-blue-ink: #30547a;
  --focus-ring: rgba(59, 111, 182, 0.28);
  --focus-blue-soft: rgba(59, 111, 182, 0.09);
  --chart-blue-fill: rgba(59, 111, 182, 0.08);
  /* 金色系 / 警示横幅 */
  --gold-line-soft: #eadfbe;
  --gold-line: #e8e0c7;
  --gold-wash: #fffdf6;
  --gold-wash-deep: #eee9d7;
  --warning-ink: #8a5a00;
  --warning-bg: #fff3cd;
  --warning-bg-soft: #fff8e6;
  --warning-line: #f0d488;
  /* 中性填充 / 滚动条 / 顶栏 */
  --row-hover: #fbfcfd;
  --chip-neutral-bg: #f0f2f5;
  --chip-line: rgba(148, 163, 184, 0.25);
  --chip-hover: rgba(148, 163, 184, 0.08);
  --input-placeholder: #a6afbd;
  --kbd-text: #9ba4b2;
  --track-idle: #bac3cf;
  --track-idle-soft: #c5ccd6;
  --grid-line: #e8edf1;
  --scroll-thumb: rgba(0, 0, 0, 0.18);
  --scroll-thumb-soft: rgba(0, 0, 0, 0.1);
  --topbar-bg: rgba(255, 255, 255, 0.84);
  --demo-line: #d8ece4;
  --footer-line: rgba(148, 163, 184, 0.18);
  --knob: #ffffff;
  --knob-shadow: 0 1px 3px rgba(21, 32, 51, 0.24);
  --shadow-hairline: 0 1px 3px rgba(21, 32, 51, 0.14);
  --scrim: rgba(15, 23, 42, 0.45);
  --scrim-strong: rgba(8, 12, 22, 0.35);
  --inset-surface: #16223a;
  --inset-text: #eef2f8;
  --surface-raised: rgba(59, 130, 246, 0.12);
  --danger: #dc2626;
  /* 图表系列与中性线（浅色=COMPARE_COLORS 原值） */
  --chart-1: #2563eb;
  --chart-2: #059669;
  --chart-3: #d97706;
  --chart-4: #dc2626;
  --chart-5: #7c3aed;
  --chart-6: #0891b2;
  --chart-7: #ca8a04;
  --chart-8: #e11d48;
  --chart-benchmark: #9aa7bd;
  --chart-baseline: #6b7280;
  --chart-watch: #9aa6b8;
```

- [ ] **Step 2: 文件末尾追加 dark 覆盖块（完整逐字）**

```css
/* ===== 暗色主题（B · 中性炭灰，spec §4；html[data-theme='dark'] 覆盖同一套变量名） ===== */
html[data-theme='dark'] {
  --canvas: #101113;
  --surface: #191b1e;
  --surface-soft: #222528;
  --surface-tint: #1e2125;
  --ink: #e9ebee;
  --ink-soft: #c9cdd3;
  --muted: #9aa1ab;
  --muted-strong: #b3bac2;
  --line: #2e3237;
  --line-strong: #3c4148;
  --sidebar: #16171a;
  --sidebar-soft: #1f2125;
  --sidebar-muted: #9aa1ab;
  --coral: #ef6d53;
  --coral-dark: #ff8a70;
  --coral-soft: #3a221c;
  --red: #e06c6c;
  --red-soft: #3a2222;
  --green: #35a583;
  --green-soft: #1d332c;
  --blue: #5e8fd6;
  --blue-soft: #1f2c40;
  --gold: #d1a54a;
  --gold-soft: #383018;
  --shadow: 0 14px 34px rgba(0, 0, 0, 0.45);
  --shadow-small: 0 5px 16px rgba(0, 0, 0, 0.4);
  --sidebar-text: #ffffff;
  --sidebar-text-bright: #eef3fb;
  --sidebar-text-soft: #f7faff;
  --sidebar-text-dim: #dce5f2;
  --sidebar-kbd: #8b96a6;
  --sidebar-label: #7c8798;
  --sidebar-line: rgba(255, 255, 255, 0.1);
  --sidebar-line-strong: rgba(255, 255, 255, 0.14);
  --sidebar-hover: rgba(255, 255, 255, 0.08);
  --sidebar-hover-soft: rgba(255, 255, 255, 0.07);
  --sidebar-coral-bg: rgba(239, 109, 83, 0.2);
  --sidebar-active-line: rgba(239, 109, 83, 0.45);
  --sidebar-coral-text: #ff9a83;
  --sidebar-green: #a8e4d0;
  --dot-idle: #77828f;
  --status-green: #66d4ac;
  --status-gold: #d6a54a;
  --status-coral: #ef7b68;
  --glow-green: rgba(53, 165, 131, 0.25);
  --glow-green-soft: rgba(102, 212, 172, 0.16);
  --glow-gold: rgba(209, 165, 74, 0.18);
  --glow-coral: rgba(239, 123, 104, 0.18);
  --on-accent: #ffffff;
  --on-ink: #101113;
  --coral-wash: #2e1d18;
  --coral-tint: rgba(239, 109, 83, 0.18);
  --coral-line: #4a2b23;
  --coral-line-strong: #57332a;
  --chart-coral-fill: rgba(239, 109, 83, 0.16);
  --blue-line: #2c3d55;
  --chip-blue-bg: #22303f;
  --chip-blue-ink: #a9c4e4;
  --focus-ring: rgba(94, 143, 214, 0.45);
  --focus-blue-soft: rgba(94, 143, 214, 0.16);
  --chart-blue-fill: rgba(94, 143, 214, 0.14);
  --gold-line-soft: #453c22;
  --gold-line: #4a4128;
  --gold-wash: #2a2618;
  --gold-wash-deep: #33301f;
  --warning-ink: #e8c268;
  --warning-bg: #3a3116;
  --warning-bg-soft: #332c15;
  --warning-line: #5a4c26;
  --row-hover: #1f2125;
  --chip-neutral-bg: #222528;
  --chip-line: #33383e;
  --chip-hover: #24272b;
  --input-placeholder: #6f7a88;
  --kbd-text: #77828f;
  --track-idle: #3a3f46;
  --track-idle-soft: #454b52;
  --grid-line: #26282c;
  --scroll-thumb: rgba(255, 255, 255, 0.16);
  --scroll-thumb-soft: rgba(255, 255, 255, 0.08);
  --topbar-bg: rgba(16, 17, 19, 0.85);
  --demo-line: #2a3a34;
  --footer-line: #2c3138;
  --knob: #f2f4f7;
  --knob-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
  --shadow-hairline: 0 1px 3px rgba(0, 0, 0, 0.4);
  --scrim: rgba(0, 0, 0, 0.6);
  --scrim-strong: rgba(0, 0, 0, 0.55);
  --inset-surface: #1c2534;
  --inset-text: #e9eef7;
  --surface-raised: rgba(94, 143, 214, 0.14);
  --danger: #ef6b6b;
  --chart-1: #6b9bf5;
  --chart-2: #3dd6a3;
  --chart-3: #f0a54a;
  --chart-4: #ef7b7b;
  --chart-5: #a78bfa;
  --chart-6: #22c3d6;
  --chart-7: #d4b34a;
  --chart-8: #f472a0;
  --chart-benchmark: #8b96a6;
  --chart-baseline: #9aa1ab;
  --chart-watch: #93a0b6;
}
```

- [ ] **Step 3: 验证渲染零变化**

Run: `npx vitest run`（应全绿，本步无 JS 改动）+ 手动打开 dev 页面浅色目视无变化（纯添加，理论上零风险）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles.css
git commit -m "feat: styles.css 新增语义令牌浅色值与暗色覆盖块（渲染零变化）"
```

---

### Task 2: 103 处裸值逐行替换（映射表）+ fallback 清理

**Files:**
- Modify: `frontend/src/styles.css`（Task 1 追加令牌后行号整体下移；**下表行号为当前 HEAD 的行号，替换以「值 + 选择器上下文」定位，不依赖行号**）

**Interfaces:**
- Consumes: Task 1 的全部新令牌。
- Produces: styles.css 令牌块之外 0 裸值（机械验收）；Task 5 依赖 `--chart-benchmark` 已在 CSS 中被消费。

- [ ] **Step 1: 按映射表逐处替换**

同一原值映射到不同令牌的（`#ffffff`、`#fff`），先 `grep -n` 定位全部出现处，再按「选择器/行号」列对号入座；其余值全局唯一或全局同令牌，可直接全局替换。

| 行号(当前) | 选择器（上下文） | 原值 | 目标令牌 |
|---|---|---|---|
| 81 | textarea:focus-visible outline | rgba(59, 111, 182, 0.28) | `var(--focus-ring)` |
| 101 | .brand 区亮文字 | #eef3fb | `var(--sidebar-text-bright)` |
| 118 | .brand-mark color | #ffffff | `var(--sidebar-text)` |
| 146 | .market-switcher border | rgba(255, 255, 255, 0.08) | `var(--sidebar-line)` |
| 148 | .market-switcher bg | rgba(255, 255, 255, 0.045) | `var(--sidebar-hover-soft)` |
| 174 | .market-state 绿字 | #a8e4d0 | `var(--sidebar-green)` |
| 186 | .live-dot box-shadow | rgba(37, 143, 118, 0.14) | `0 0 0 3px var(--glow-green)` |
| 190 | .live-dot bg | #66d4ac | `var(--status-green)` |
| 191 | .live-dot box-shadow | rgba(102, 212, 172, 0.1) | `0 0 0 3px var(--glow-green-soft)` |
| 219 | .nav-item:hover bg | rgba(255, 255, 255, 0.05) | `var(--sidebar-hover)` |
| 220 | .nav-item.is-active color | #f7faff | `var(--sidebar-text-soft)` |
| 224 | .nav-item.is-active border-color | rgba(239, 109, 83, 0.22) | `var(--sidebar-active-line)` |
| 225 | .nav-item.is-active bg | rgba(239, 109, 83, 0.14) | `var(--sidebar-coral-bg)` |
| 226 | .nav-item.is-active color | #ffffff | `var(--sidebar-text)` |
| 245 | .nav-item kbd border | rgba(255, 255, 255, 0.1) | `var(--sidebar-line-strong)` |
| 247 | .nav-item kbd color | #7e8aa1 | `var(--sidebar-kbd)` |
| 260 | .nav-count color | #ffffff | `var(--sidebar-text)` |
| 267 | .sidebar-section-label color | #65728a | `var(--sidebar-label)` |
| 286 | .sidebar-data-note color | #dce5f2 | `var(--sidebar-text-dim)` |
| 301 | .status-dot bg | #aeb8c6 | `var(--dot-idle)` |
| 305 | .status-dot.live bg | #66d4ac | `var(--status-green)` |
| 306 | .status-dot.live shadow | rgba(102, 212, 172, 0.1) | `0 0 0 3px var(--glow-green-soft)` |
| 310 | .status-dot.stale bg | #d6a54a | `var(--status-gold)` |
| 311 | .status-dot.stale shadow | rgba(214, 165, 74, 0.1) | `0 0 0 3px var(--glow-gold)` |
| 315 | .status-dot.error bg | #ef7b68 | `var(--status-coral)` |
| 316 | .status-dot.error shadow | rgba(239, 123, 104, 0.1) | `0 0 0 3px var(--glow-coral)` |
| 329 | .sidebar-note border | rgba(255, 255, 255, 0.08) | `var(--sidebar-line)` |
| 341 | .sidebar-note bg | rgba(239, 109, 83, 0.14) | `var(--sidebar-coral-bg)` |
| 342 | .sidebar-note color | #ff9a83 | `var(--sidebar-coral-text)` |
| 371 | .user-profile border-top | rgba(255, 255, 255, 0.08) | `var(--sidebar-line)` |
| 381 | .avatar bg | #d8e4f1 | `var(--chip-blue-bg)` |
| 382 | .avatar color | #30547a | `var(--chip-blue-ink)` |
| 421 | .topbar bg | rgba(255, 255, 255, 0.84) | `var(--topbar-bg)` |
| 463 | .demo-badge border | #d8ece4 | `var(--demo-line)` |
| 472 | .demo-badge-stale border-color | #eadfbe | `var(--gold-line-soft)` |
| 523 | .global-search input::placeholder | #a6afbd | `var(--input-placeholder)` |
| 534 | .global-search kbd color | #9ba4b2 | `var(--kbd-text)` |
| 578 | .icon-button-dark border-color | rgba(255, 255, 255, 0.08) | `var(--sidebar-line)` |
| 579 | .icon-button-dark bg | rgba(255, 255, 255, 0.05) | `var(--sidebar-hover)` |
| 580 | .icon-button-dark color | #ffffff | `var(--sidebar-text)` |
| 625 | 滚动条 hover bg | rgba(0, 0, 0, 0.1) | `var(--scroll-thumb-soft)` |
| 630 | 滚动条 thumb bg | rgba(0, 0, 0, 0.18) | `var(--scroll-thumb)` |
| 635 | scrollbar-color | rgba(0, 0, 0, 0.1) transparent | `var(--scroll-thumb-soft) transparent` |
| 771 | .connection-banner border | #eadfbe | `var(--gold-line-soft)` |
| 773 | .connection-banner bg | #fffdf6 | `var(--gold-wash)` |
| 848 | .button-primary color | #ffffff | `var(--on-accent)` |
| 1038 | .chart-grid-line stroke | #e8edf1 | `var(--grid-line)` |
| 1043 | .chart-area fill | rgba(239, 109, 83, 0.09) | `var(--chart-coral-fill)` |
| 1109 | 禁用轨道 bg | #bac3cf | `var(--track-idle)` |
| 1144 | 禁用轨道 bg | #bac3cf | `var(--track-idle)` |
| 1198 | .data-table tr:hover bg | #fbfcfd | `var(--row-hover)` |
| 1282 | .signal-chip-neutral bg | #f0f2f5 | `var(--chip-neutral-bg)` |
| 1299 | 边框色（珊瑚强） | #f0c6bb | `var(--coral-line-strong)` |
| 1463 | 边框色（珊瑚） | #f3d0c7 | `var(--coral-line)` |
| 1464 | 珊瑚浅底 bg | #fff8f6 | `var(--coral-wash)` |
| 1591 | 边框色（蓝） | #b5cce8 | `var(--blue-line)` |
| 1592 | focus shadow | rgba(59, 111, 182, 0.09) | `0 0 0 3px var(--focus-blue-soft)` |
| 1646 | 珊瑚浅底 bg | #fff8f6 | `var(--coral-wash)` |
| 1804 | 图表蓝 fill | rgba(59, 111, 182, 0.08) | `var(--chart-blue-fill)` |
| 1884 | 金系边框 | #e8e0c7 | `var(--gold-line)` |
| 1886 | 金系浅底 bg | #fffdf6 | `var(--gold-wash)` |
| 1936 | 金系深浅底 bg | #eee9d7 | `var(--gold-wash-deep)` |
| 2118 | 轨道浅 bg | #c5ccd6 | `var(--track-idle-soft)` |
| 2127 | .toggle-track span bg | #ffffff | `var(--knob)` |
| 2128 | .toggle-track span shadow | rgba(21, 32, 51, 0.24) | `var(--knob-shadow)`（替换整个 `0 1px 3px rgba(21, 32, 51, 0.24)` 值） |
| 2346 | 边框珊瑚 | #ef6d53 | `var(--coral)` |
| 2350 | 边框中性灰 | #9aa7bd | `var(--chart-benchmark)` |
| 2659 | 边框色（蓝） | #b5cce8 | `var(--blue-line)` |
| 2660 | focus shadow | rgba(59, 111, 182, 0.09) | `0 0 0 3px var(--focus-blue-soft)` |
| 2697 | 中性 chip bg | #f0f2f5 | `var(--chip-neutral-bg)` |
| 2767 | .dark-chip color（bg 为 var(--ink)） | #ffffff | `var(--on-ink)` |
| 3212 | 暗色浮层 bg | #16223a | `var(--inset-surface)` |
| 3213 | 暗色浮层 border | #ef6d53 | `var(--coral)` |
| 3214 | 暗色浮层 color | #eef2f8 | `var(--inset-text)` |
| 3215 | 暗色浮层 shadow | rgba(8, 12, 22, 0.35) | `var(--scrim-strong)` |
| 3219 | 暗色浮层强调 color | #ef6d53 | `var(--coral)` |
| 3232 | chip 边框 | rgba(148, 163, 184, 0.25) | `var(--chip-line)` |
| 3295 | 遮罩 bg | rgba(15, 23, 42, 0.45) | `var(--scrim)` |
| 3342 | 警示 ink | #8a5a00 | `var(--warning-ink)` |
| 3343 | 警示 bg | #fff3cd | `var(--warning-bg)` |
| 3344 | 警示 border | #f0d488 | `var(--warning-line)` |
| 3363 | 警示 ink | #8a5a00 | `var(--warning-ink)` |
| 3369 | 警示 soft bg | #fff8e6 | `var(--warning-bg-soft)` |
| 3370 | 警示 border | #f0d488 | `var(--warning-line)` |
| 3451 | 主按钮 bg | #ef6d53 | `var(--coral)` |
| 3452 | 主按钮 color | #fff | `var(--on-accent)` |
| 3515 | chip 边框 | rgba(148, 163, 184, 0.25) | `var(--chip-line)` |
| 3522 | 边框珊瑚 | #ef6d53 | `var(--coral)` |
| 3545 | chip hover bg | rgba(148, 163, 184, 0.08) | `var(--chip-hover)` |
| 3550 | 强调 color | #ef6d53 | `var(--coral)` |
| 3557 | chip hover bg | rgba(148, 163, 184, 0.08) | `var(--chip-hover)` |
| 3596 | .app-footer bg | #101a2b | `var(--sidebar)` |
| 3597 | .app-footer border-top | rgba(148, 163, 184, 0.18) | `var(--footer-line)` |
| 3618 | 强调 color | #ef6d53 | `var(--coral)` |
| 3628 | 主按钮 color | #fff | `var(--on-accent)` |
| 3629 | 主按钮 bg | #ef6d53 | `var(--coral)` |
| 3644 | chip 边框 | rgba(148, 163, 184, 0.25) | `var(--chip-line)` |
| 3653 | 边框珊瑚 | #ef6d53 | `var(--coral)` |
| 3654 | 暗底浮层 color | #eef2f8 | `var(--inset-text)` |
| 3655 | 珊瑚 tint bg | rgba(239, 109, 83, 0.12) | `var(--coral-tint)` |
| 3697 | 细阴影 | rgba(21, 32, 51, 0.14) | `var(--shadow-hairline)`（替换整个 `0 1px 3px rgba(21, 32, 51, 0.14)` 值） |
| 3966 | var 带兜底 | var(--surface-raised, rgba(59, 130, 246, 0.12)) | `var(--surface-raised)`（令牌已在 Task 1 定义） |
| 4397 | var 带兜底 | var(--danger, #dc2626) | `var(--danger)` |

- [ ] **Step 2: 机械验收——裸值归零**

Run:
```bash
awk '/:root \{|data-theme=.{1,4}dark.\{/{skip=1} skip{if (/\}/) skip=0; next} /#[0-9a-fA-F]{3,8}\b|rgba?\(/ {print NR": "$0}' frontend/src/styles.css
grep -rnE "#[0-9a-fA-F]{6}\b" frontend/src --include="*.vue" --include="*.ts" | grep -v node_modules
```
Expected: 两条命令均**无输出**（styles.css 令牌块外 0 裸值；vue/ts 无 hex——注意此刻 useCompareStore/chart.ts/视图的 hex 还在，**它们归 Task 5**，故本步 vue/ts 检查预期仍有 17 处命中——只验收 styles.css 归零，vue/ts 断言留到 Task 5 收口）。

修正后的本步验收：第一条命令无输出；第二条记录命中清单（应为 Task 5 清单的那 17 处 + `#fff` 三位缩进变体 0 处）。

- [ ] **Step 3: 浅色等价验证**

Run: `npx vitest run && npx vue-tsc --noEmit`
Expected: 全绿（CSS 改动不影响测试，vue-tsc 校验 .vue 内联样式无语法破坏）。浏览器浅色目视抽查：侧栏/顶栏/表格/警示横幅/滚动条无变化。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/styles.css
git commit -m "refactor: styles.css 103 处裸色值收敛为语义令牌（浅色渲染零变化）"
```

---

### Task 3: `modules/theme.ts` + 单测 + main.ts 接线（TDD）

**Files:**
- Create: `frontend/src/modules/theme.ts`
- Create: `tests/frontend/theme.test.ts`
- Modify: `frontend/src/main.ts`（import + `initTheme()`）

**Interfaces:**
- Consumes: 无。
- Produces（Task 4 消费）: `themePreference: ComputedRef<'light'|'dark'|null>`、`effectiveTheme: ComputedRef<'light'|'dark'>`、`setTheme(next: 'light'|'dark'|null): void`、`toggleTheme(): void`、`initTheme(): void`。

- [ ] **Step 1: 写失败测试 `tests/frontend/theme.test.ts`**

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type FakeMedia = { matches: boolean; addEventListener: ReturnType<typeof vi.fn>; removeEventListener: ReturnType<typeof vi.fn> };
let media: FakeMedia;
let store: Record<string, string>;

async function fresh() {
  vi.resetModules();
  return import('@/modules/theme');
}

beforeEach(() => {
  store = {};
  media = { matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => { store[k] = v; },
    removeItem: (k: string) => { delete store[k]; },
  });
  vi.stubGlobal('matchMedia', vi.fn(() => media));
  document.documentElement.removeAttribute('data-theme');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('theme 模块', () => {
  it('未设偏好 + 系统浅色 → effective light，initTheme 写入 data-theme=light', async () => {
    const theme = await fresh();
    theme.initTheme();
    expect(theme.effectiveTheme.value).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(media.addEventListener).toHaveBeenCalled();
  });

  it('未设偏好 + 系统深色 → 跟随系统为 dark', async () => {
    media.matches = true;
    const theme = await fresh();
    theme.initTheme();
    expect(theme.effectiveTheme.value).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('显式 light/dark 覆盖系统偏好', async () => {
    media.matches = true;
    store['atlas-theme'] = 'light';
    let theme = await fresh();
    theme.initTheme();
    expect(theme.effectiveTheme.value).toBe('light');
    store['atlas-theme'] = 'dark';
    theme = await fresh();
    theme.initTheme();
    expect(theme.effectiveTheme.value).toBe('dark');
  });

  it('非法存储值视同未设（跟随系统）', async () => {
    media.matches = true;
    store['atlas-theme'] = 'blue';
    const theme = await fresh();
    theme.initTheme();
    expect(theme.themePreference.value).toBeNull();
    expect(theme.effectiveTheme.value).toBe('dark');
  });

  it('setTheme 写入存储并即时生效；setTheme(null) 删键回跟随系统', async () => {
    const theme = await fresh();
    theme.initTheme();
    theme.setTheme('dark');
    expect(store['atlas-theme']).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    theme.setTheme(null);
    expect('atlas-theme' in store).toBe(false);
    expect(theme.themePreference.value).toBeNull();
  });

  it('系统偏好变化仅在未显式选择时联动', async () => {
    const theme = await fresh();
    theme.initTheme();
    const handler = media.addEventListener.mock.calls[0][1] as (e: { matches: boolean }) => void;
    handler({ matches: true });
    expect(document.documentElement.dataset.theme).toBe('dark');
    theme.setTheme('light');
    handler({ matches: false });
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('localStorage 抛异常时静默降级（内存态仍生效，不崩溃）', async () => {
    vi.stubGlobal('localStorage', {
      getItem: () => { throw new Error('blocked'); },
      setItem: () => { throw new Error('blocked'); },
      removeItem: () => { throw new Error('blocked'); },
    });
    const theme = await fresh();
    theme.initTheme();
    expect(() => theme.setTheme('dark')).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('toggleTheme 在浅深间翻转（显式写入）', async () => {
    const theme = await fresh();
    theme.initTheme();
    theme.toggleTheme();
    expect(theme.themePreference.value).toBe('dark');
    theme.toggleTheme();
    expect(theme.themePreference.value).toBe('light');
  });
});
```

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run tests/frontend/theme.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `frontend/src/modules/theme.ts`**

```ts
// 主题偏好（spec §5）：localStorage 键 atlas-theme 存 'light'|'dark'；键不存在 = 跟随系统。
// 状态内聚在本模块（单值不值得一个 Pinia store）；localStorage 异常静默降级为跟随系统。
import { computed, ref } from 'vue';

export type ThemePreference = 'light' | 'dark' | null;
export type EffectiveTheme = 'light' | 'dark';

const STORAGE_KEY = 'atlas-theme';
const preference = ref<ThemePreference>(readStored());
const systemDark = ref(false);

function readStored(): ThemePreference {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw === 'light' || raw === 'dark' ? raw : null;
  } catch {
    return null;
  }
}

export const themePreference = computed(() => preference.value);
export const effectiveTheme = computed<EffectiveTheme>(() =>
  preference.value ?? (systemDark.value ? 'dark' : 'light')
);

function apply(): void {
  document.documentElement.dataset.theme = effectiveTheme.value;
}

function onSystemChange(event: MediaQueryListEvent): void {
  systemDark.value = event.matches;
  if (preference.value === null) apply();
}

export function setTheme(next: ThemePreference): void {
  preference.value = next;
  try {
    if (next === null) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* 隐私模式/存储被禁：仅内存生效 */
  }
  apply();
}

export function toggleTheme(): void {
  setTheme(effectiveTheme.value === 'dark' ? 'light' : 'dark');
}

export function initTheme(): void {
  try {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    systemDark.value = media.matches;
    media.addEventListener('change', onSystemChange);
  } catch {
    /* matchMedia 不可用：保持浅色兜底 */
  }
  apply();
}
```

- [ ] **Step 4: main.ts 接线（防 FOUC——必须在 createApp 之前）**

在 `import './styles.css';` 之后加 `import { initTheme } from './modules/theme';`，在 `const app = createApp(App);` 之前加：

```ts
initTheme();
```

- [ ] **Step 5: 运行确认通过**

Run: `npx vitest run tests/frontend/theme.test.ts && npx vue-tsc --noEmit`
Expected: 8 passed；类型无错误

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/theme.ts tests/frontend/theme.test.ts frontend/src/main.ts
git commit -m "feat: 新增 theme 模块——三态主题解析/持久化/跟随系统与首帧防闪"
```

---

### Task 4: 侧栏快捷开关 + 设置页外观卡片

**Files:**
- Modify: `frontend/src/App.vue`（`.sidebar-spacer` 之后插入开关按钮）
- Modify: `frontend/src/views/ViewSettings.vue`（workspace tab 内新增「外观」settings-row）
- Modify: `frontend/src/styles.css`（两个小组件样式追加文件末尾 dark 块之前？——追加到文件末尾 dark 块**之后**亦可，类名独立不涉主题）
- Test: `tests/frontend/ViewSettings.test.ts`（追加冒烟）

**Interfaces:**
- Consumes: Task 3 的 `effectiveTheme` / `themePreference` / `setTheme` / `toggleTheme`。
- Produces: 用户可见入口两处。

- [ ] **Step 1: 写失败冒烟（ViewSettings.test.ts 末尾追加）**

```ts
test('外观卡片：三态单选渲染，点击深色写 localStorage 并切 data-theme', async () => {
  const wrapper = mount(ViewSettings, { global: { plugins: [createPinia()] } });
  const radios = wrapper.findAll('input[name="atlas-theme-option"]');
  expect(radios.length).toBe(3);
  await radios[1].setValue();
  expect(window.localStorage.getItem('atlas-theme')).toBe('dark');
  expect(document.documentElement.dataset.theme).toBe('dark');
});
```

（若该文件已有全局 localStorage/mock 惯例，跟随其 beforeEach 模式；`mount` 已导入则复用。）

- [ ] **Step 2: 运行确认失败**

Run: `npx vitest run tests/frontend/ViewSettings.test.ts`
Expected: 新用例 FAIL（无外观卡片）

- [ ] **Step 3: App.vue 侧栏开关**

(a) `<script setup>` 追加：

```ts
import { nextTick } from 'vue';
import { effectiveTheme, toggleTheme } from '@/modules/theme';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
// 若 App.vue 已导入 useWorkspaceStore 则复用既有实例
const workspaceStore = useWorkspaceStore();
const currentTheme = effectiveTheme;
function onToggleTheme() {
  toggleTheme();
  nextTick(() => workspaceStore.renderIcons());
}
```

(b) 模板 `<div class="sidebar-spacer"></div>` 之后插入：

```vue
      <button
        class="sidebar-theme-toggle"
        type="button"
        :aria-label="currentTheme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
        @click="onToggleTheme"
      >
        <i :data-lucide="currentTheme === 'dark' ? 'sun' : 'moon'" aria-hidden="true"></i>
        <span>{{ currentTheme === 'dark' ? '浅色模式' : '深色模式' }}</span>
      </button>
```

(c) `styles.css` 文件末尾追加（dark 块之后）：

```css
.sidebar-theme-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 14px 10px;
  padding: 9px 10px;
  border: 1px solid var(--sidebar-line);
  border-radius: var(--radius-small);
  background: transparent;
  color: var(--sidebar-muted);
  font-size: 12.5px;
  cursor: pointer;
  transition: color 140ms ease, border-color 140ms ease;
}

.sidebar-theme-toggle:hover {
  color: var(--sidebar-text);
  border-color: var(--sidebar-line-strong);
}
```

- [ ] **Step 4: ViewSettings 外观卡片（镜像相邻 settings-row 结构）**

`workspace` tab 的最后一个 `settings-row` 之后插入：

```vue
        <section v-if="settingsTab === 'workspace'" class="settings-row">
          <div>
            <strong>外观</strong>
            <span>界面主题即时生效，仅保存在本浏览器</span>
          </div>
          <div class="theme-options">
            <label v-for="option in THEME_OPTIONS" :key="option.value" class="theme-option">
              <input
                type="radio"
                name="atlas-theme-option"
                :checked="(themePreference ?? 'system') === option.value"
                @change="onThemeChange(option.value)"
              /><span>{{ option.label }}</span>
            </label>
          </div>
        </section>
```

`<script setup>` 追加：

```ts
import { themePreference, setTheme } from '@/modules/theme';
const THEME_OPTIONS = [
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
  { value: 'system', label: '跟随系统' },
] as const;
function onThemeChange(value: 'light' | 'dark' | 'system') {
  setTheme(value === 'system' ? null : value);
}
```

样式追加 styles.css 末尾：

```css
.theme-options {
  display: flex;
  gap: 14px;
}

.theme-option {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--ink-soft);
  cursor: pointer;
}
```

- [ ] **Step 5: 运行确认通过**

Run: `npx vitest run tests/frontend/ViewSettings.test.ts && npx vue-tsc --noEmit && npx eslint frontend/src --ext .ts,.vue`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.vue frontend/src/views/ViewSettings.vue frontend/src/styles.css tests/frontend/ViewSettings.test.ts
git commit -m "feat: 侧栏主题快捷开关与设置页外观三态卡片"
```

---

### Task 5: 图表与组件取色改造（hex → var 令牌）

**Files:**
- Modify: `frontend/src/modules/chart.ts:94-95`
- Modify: `frontend/src/views/ViewOverview.vue:236`、`frontend/src/views/ViewStockDetail.vue:78,156`、`frontend/src/views/ViewPortfolio.vue:480`
- Modify: `frontend/src/stores/useCompareStore.ts:20,79`
- Test: `tests/frontend/chart.test.ts`（compareChartSvg 用例补断言）

**Interfaces:**
- Consumes: Task 1 的 `--chart-1..8` / `--chart-benchmark` / `--chart-baseline` / `--chart-watch` / `--coral` / `--blue` / `--muted`。
- Produces: `frontend/src` 的 .vue/.ts 裸 hex 归零（§3 机械验收第二段此步收口）。

- [ ] **Step 1: chart.test.ts 先行断言（失败测试）**

在 `compareChartSvg 正常结果生成双曲线对比图` 用例的断言列表末尾追加：

```ts
  assert.match(svg, /stroke:var\(--chart-benchmark\)/);
  assert.match(svg, /stroke:var\(--coral\)/);
```

Run: `npx vitest run tests/frontend/chart.test.ts` → Expected: 该用例 FAIL（chart.ts 仍是 hex）

- [ ] **Step 2: 逐处替换**

| 文件:行 | 原值 | 替换为 |
|---|---|---|
| `chart.ts:94` | `stroke:#9aa7bd` | `stroke:var(--chart-benchmark)` |
| `chart.ts:95` | `stroke:#ef6d53` | `stroke:var(--coral)` |
| `ViewOverview.vue:236` | `'#ef6d53',` | `'var(--coral)',` |
| `ViewStockDetail.vue:78` | `'#3b6fb6',` | `'var(--blue)',` |
| `ViewStockDetail.vue:156` | `'#3b6fb6',` | `'var(--blue)',` |
| `ViewPortfolio.vue:480` | `const NAV_COLORS = { gross: '#ef6d53', net: '#7d8798', watch: '#9aa6b8' };` | `const NAV_COLORS = { gross: 'var(--coral)', net: 'var(--muted)', watch: 'var(--chart-watch)' };` |
| `useCompareStore.ts:20` | `const COMPARE_COLORS = ['#2563eb', … '#e11d48'];` | `const COMPARE_COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)', 'var(--chart-6)', 'var(--chart-7)', 'var(--chart-8)'];` |
| `useCompareStore.ts:79` | `color: '#6b7280',` | `color: 'var(--chart-baseline)',` |

- [ ] **Step 3: 机械验收（spec §3 断言全量收口）**

```bash
grep -rnE "#[0-9a-fA-F]{6}\b" frontend/src --include="*.vue" --include="*.ts" | grep -v node_modules
```
Expected: 无输出。

- [ ] **Step 4: 测试与类型**

Run: `npx vitest run && npx vue-tsc --noEmit`
Expected: 全绿（`useCompareStore.test.ts` 不断言色值，无需改动；`multiLineSvg` 用例传参 hex 是函数入参，保留）。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/modules/chart.ts frontend/src/views frontend/src/stores/useCompareStore.ts tests/frontend/chart.test.ts
git commit -m "feat: 图表与组件取色接入图表令牌（浅暗自适应）"
```

---

### Task 6: 暗色走查 + 全量验证 + 文档收口

**Files:**
- Modify: `AGENTS.md`、`ROADMAP.md`、`CHANGELOG.md`（走查发现的漏色修正落在对应源文件）

- [ ] **Step 1: 暗色全走查（人工 + 浏览器）**

`npm run dev` → 浏览器 devtools 执行 `document.documentElement.dataset.theme = 'dark'`（或点侧栏开关），逐视图走查并记录漏色：

1. 总览 / 盯盘 / 选股（含策略 tab）/ 股票详情（含图表）/ 策略实验室（含对比 tab）/ 计划 / 组合风险 / 设置
2. PlanDraftDialog、CustomStrategyDialog 两对话框
3. toast、确认横幅、警示横幅（金系）、空态、滚动条、focus 轮廓
4. 常见漏点重点检查：`linear-gradient(...)` 内嵌色、`box-shadow` 内嵌色、`::-webkit-scrollbar` 系列、SVG `fill=`/`stroke=` 属性、`border-color` 简写

发现漏色：按 Task 2 同规则归并令牌（新值需同时给浅色=原值与暗色值）并记入报告；预计 0-5 处。

- [ ] **Step 2: 全量验证**

Run: `npm run verify`
Expected: 后端 pytest 全绿（覆盖率 ≥80% 门禁）、前端 vitest 全绿、vue-tsc 绿。记录前端总数（267 → 267+theme 8+ViewSettings 1 = 预期 276）。

- [ ] **Step 3: 文档收口**

- `AGENTS.md`：modules 清单 `lucideIcons.ts（图标注册表）` 行后追加 ` / theme.ts（三态主题：浅/深/跟随系统，localStorage 持久化）`；`styles.css` 行描述改为 `全部样式（CSS 变量令牌体系，:root 浅色 + [data-theme='dark'] 暗色，单文件）`。
- `ROADMAP.md`：「多语言（英文 UI）/ 自定义主题配色」项下追加一行注记：`- 主题基建已交付（2026-10-11，第①批）：令牌收敛 + 浅/深/跟随系统三态；自定义配色与多语言仍待（第②③批后续）`。
- `CHANGELOG.md`：在既有 `[v0.7.2]` 段落内追加小节（不新开版本号，同属下次发布）：

```markdown
### UI 主题基建（第①批）

- `styles.css` 全量令牌化：103 处裸色值收敛为语义令牌（浅色渲染零变化），新增 `html[data-theme='dark']` 覆盖块（B · 中性炭灰基调）。
- 新模块 `modules/theme.ts`：浅/深/跟随系统三态，localStorage 持久化（键 `atlas-theme`，异常静默降级），`main.ts` 首帧前应用防闪白，系统偏好变化仅在未显式选择时联动。
- 入口：侧栏底部快捷开关 + 设置页「外观」三态卡片；图表/组件取色接入 `--chart-N` 令牌，暗色自适应。
```

- [ ] **Step 4: 提交并核验**

```bash
git add -A
git commit -m "docs: 收口 UI 第①批（暗色走查修正/AGENTS 令牌体系描述/ROADMAP 注记/CHANGELOG）"
git log --oneline -7
```

Expected: 工作树干净；分支 6-7 个提交（spec 1 + Task 1-6）。

---

## Self-Review 记录

1. **Spec 覆盖**：§3 映射规则与 grep 断言 → Task 2（+Task 5 收口 vue/ts）；§4 值表 → Task 1 dark 块；§5 切换机制 → Task 3+4（FOUC/联动/两入口/降级）；§6 图表取色 → Task 5；§7 边界 → Task 3 实现+测试（异常/非法值/matchMedia 兜底）；§8 测试 → 各任务 + Task 6 verify；§9 验收 → Task 6 走查清单 + 文档收口。无缺口。
2. **占位符**：无 TBD；映射表 103 行全量给出；唯一动态项是 Task 6 走查发现的漏色数（0-5 处，属人工走查数据）。
3. **类型一致性**：`theme.ts` 导出名（`themePreference/effectiveTheme/setTheme/toggleTheme/initTheme`）在 Task 3/4 各消费点逐字一致；令牌名在 Task 1（定义）与 Task 2（消费）逐字一致；`--chart-N` 在 Task 1/Task 5 一致。
4. **行号漂移声明**：Task 2 表格行号基于当前 HEAD；Task 1 插入后行号下移，替换以「值 + 选择器」定位（表格已含选择器列）。
