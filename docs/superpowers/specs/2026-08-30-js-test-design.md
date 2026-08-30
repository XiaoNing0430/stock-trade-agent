# JS 纯函数模块测试 — 设计

## 目标

为 `frontend/modules/` 下的纯函数模块（format.js / chart.js / constants.js）补充 `node:test` 单测，建立前端模块的测试基线，防止回归。

## 非目标

- 不测 Vue 组件（`app.js` 与 `index.html` 无 DOM 测试运行器）。
- 不新增 npm 依赖。
- 不改动现有模块代码（零侵入）。

## 技术选型

- **测试框架**：Node.js 内置 `node:test`（`import test from 'node:test'`），Node 22 提供增量测试运行器。
- **断言库**：`node:assert/strict`（`import assert from 'node:assert/strict'`）。
- **运行命令**：`node --test tests/frontend/`（ESM 支持，`package.json` 已有 `"type": "module"`）。
- 不依赖 `package.json` 中的 `test` script（但可加）。

## 测试文件

### `tests/frontend/format.test.js`

覆盖 format.js 全部 10 个导出函数：

| 函数 | 测试场景 |
|------|----------|
| `formatNumber` | 正常值（1234.567 → "1,234.57"）、整数、零、null/undefined/NaN → "--" |
| `formatPct` | 正数 "+10.00%"，负数 "-5.12%"，零 "+0.00%"，null/undefined/NaN → "--" |
| `formatTime` | 有效时间戳 → "HH:MM:SS"，零/undefined → "--:--:--" |
| `formatDateLabel` | 有效 → "更新于 HH:MM:SS"，无效 → "尚未更新" |
| `formatAmount` | 亿级（1e9 → "10.00 亿"）、万级（5e7 → "5,000.00 万"）、元级（1234 → "1,234 元"）、null → "--" |
| `formatMoney` | 1e6 → "¥1,000,000"，零 → "¥0"，null → "¥0" |
| `formatNullable` | 委托给 `formatNumber`，测试边缘值 |
| `formatPctNullable` | 委托给 `formatPct`，测试边缘值 |
| `trendClass` | 正数 → "trend-up"，负数 → "trend-down"，零 → "trend-up"，null → "trend-flat" |
| `escapeHtml` | `&<>"'` 全部转义、普通文本不变、空字符串/undefined |
| `validityExpiry` | "今日"→ 当日末、"本周内"→ 周日末、"本月内"→ 月末、"未知值"→ 当日末、null→null |

### `tests/frontend/chart.test.js`

| 函数 | 测试场景 |
|------|----------|
| `chartSvg` | 空数组→空状态、单元素→空状态、2 个点→正常 SVG、多个点→含 path/circle/text |
| `compareChartSvg` | 空结果→空状态、正常 equityCurve+benchmarkCurve→含两条 path 的 SVG、曲线长度不足 2→空状态 |

### `tests/frontend/constants.test.js`

- PRESETS 长度与结构（name/icon/iconClass/description/filters）
- NAV_ITEMS 长度与 id 唯一性
- VIEW_META 所有视图 key 存在
- SETTINGS_TABS 长度与 id
- STRATEGY_TYPES 长度与 id（grid/ma_cross/dca/macd）
- STRATEGY_SCHEMAS 结构（各类型 configSchema 的 key/label/type/default）

## 验证命令

```powershell
node --test tests/frontend/
```

与 `node --check frontend/app.js` 并列在回归命令中。

## 测试

无需后端测试；`node --test` 输出类似 pytest 的增量结果。

## 交付物

- `tests/frontend/format.test.js`
- `tests/frontend/chart.test.js`
- `tests/frontend/constants.test.js`
- 回归命令文档更新（可选）