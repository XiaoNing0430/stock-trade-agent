# 全栈完整标准工程化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Atlas Trading Desk 从前端无打包器/无类型/无组件测试、后端无 lint/无类型检查/裸 dict API/原生 ALTER TABLE 迁移的状态，改造为前后端完整标准的工程化项目（Vite + TS + SFC + Pinia + vitest + ruff + mypy + Pydantic + Alembic + CI + 一键启动）。

**Architecture:** 6 个 Git Flow feature 分支依次从 develop 开出并 merge 回 develop，每个分支独立可验证：① 规范工具链 → ② 前端 Vite+TS+SFC 迁移（含 FastAPI dist 适配与一键启动）→ ③ 前端 Pinia stores 拆分 + 纯逻辑抽取 → ④ 后端 Pydantic + Alembic → ⑤ 前端 vitest + 后端覆盖率 → ⑥ CI + 文档收口。前端目录从 `frontend/` 迁移到 `frontend/src/`，dev 走 Vite HMR（:5173），prod 走 FastAPI 托管 `dist/`（:4173）。

**Tech Stack:** Vue 3 + TypeScript(strict) + Vite + @vitejs/plugin-vue + vue-tsc + Pinia + vitest + @vue/test-utils + ESLint 9 flat config + Prettier 3 + lucide（核心包）；Python 3.13 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic + ruff + mypy + pytest + pytest-cov + pre-commit；GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-08-30-fullstack-engineering-design.md`

## Global Constraints

- UI 文案保持中文；新增用户可见字符串用中文。
- **前端 API 字段名逐字节不变**（前端依赖现有字段名，Pydantic 模型化时不得改名/删除）。
- 时间戳规范：机器时间戳 `createdAtMs`（epoch 毫秒）；展示用 `formatTime(ms)`。
- 计划 `status` 值：`执行中` / `已触发` / `已过期` / `已归档`。
- XSS 纪律：`showToast` 用 `textContent`；`chartSvg` 插值必须 `escapeHtml`。
- 不引入 mock 数据；缺数据显示 `--` / 空状态。
- 网格回测假设保守且披露（T+1、100 股整手、最低佣金、印花税、过户费、滑点、涨跌停、停牌；70/30 训练/验证）。不要声称回测收益代表未来表现。
- Git Flow 强制：所有分支从 develop 开出，`git flow feature start <name>` 开始、`git flow feature finish <name>` 结束；commit subject 用中文，Conventional Commits 前缀（feat/fix/refactor/perf/test/docs/chore）。
- 提交信息示例：`feat: xxx` / `refactor: xxx` / `docs: xxx`。
- 前端运行约束：dev 模式 `npm run dev`（concurrently 聚合 :4173 后端 + :5173 Vite）；prod `npm run build` → `python server.py`（:4173 服务 dist）；兼容 `python server.py` 无 dist 时回退源码服务。
- `package-lock.json` 必须提交（CI 用 `npm ci`）。
- 每个分支合并前验证总纲：后端 `ruff check .` / `ruff format --check .` / `mypy backend` / `python -m pytest tests/ -q` 全绿；前端 `npx vue-tsc --noEmit` / `npx eslint .` / `npx vitest run` 全绿；`npm run dev` 与 `npm run build` 双形态均可运行。

---

# Phase 1 — feature/eng-toolchain：前后端规范工具链

**分支**：`git flow feature start eng-toolchain`
**目标**：立规范——ESLint + Prettier + ruff + mypy + pyproject.toml + pre-commit + npm scripts 收口（修复 node --test 尾斜杠 bug）。**本分支不改动任何业务逻辑，代码结构维持现状（JS + 源码静态服务）。**

### Task 1.1: 前端工具链依赖与配置文件

**Files:**
- Modify: `package.json`
- Create: `eslint.config.js`
- Create: `.prettierrc.json`
- Create: `.prettierignore`
- Create: `.editorconfig`

**Interfaces:**
- Produces: ESLint flat config 入口 `eslint.config.js`、Prettier 配置，供 Task 1.2 / Task 1.3 使用。

- [ ] **Step 1: 安装 devDependencies**

Run: `npm install --save-dev eslint@9 eslint-plugin-import prettier@3 globals`
Expected: 安装成功，`package.json` 新增 devDependencies；生成 `package-lock.json`（**提交**）。

- [ ] **Step 2: 创建 `eslint.config.js`**

```js
// eslint.config.js — ESLint 9 flat config（项目无打包器、无 TS，JS + 全局 Vue）
import js from '@eslint/js';
import globals from 'globals';

export default [
  { ignores: ['node_modules/**', 'frontend/vendor/**', 'frontend/dist/**', 'tests/frontend/**'] },
  js.configs.recommended,
  {
    files: ['frontend/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser, Vue: 'readonly' },
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      'no-console': 'off',
    },
  },
  {
    files: ['server.js'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'commonjs', globals: globals.node },
  },
];
```

- [ ] **Step 3: 创建 `.prettierrc.json`**

```json
{
  "printWidth": 120,
  "semi": true,
  "singleQuote": true,
  "trailingComma": "es5",
  "tabWidth": 2
}
```

- [ ] **Step 4: 创建 `.prettierignore`**

```
node_modules/
frontend/vendor/
frontend/dist/
package-lock.json
```

- [ ] **Step 5: 创建 `.editorconfig`**

```
root = true

[*]
charset = utf-8
end_of_line = lf
indent_style = space
indent_size = 2
insert_final_newline = true
trim_trailing_whitespace = true

[*.py]
indent_size = 4

[*.md]
trim_trailing_whitespace = false
```

- [ ] **Step 6: 验证 lint 可运行**

Run: `npx eslint frontend/app.js`
Expected: 无报错或仅有风格告警（尚未全量修复，Task 1.2 处理）。

- [ ] **Step 7: Commit**

```bash
git add package.json package-lock.json eslint.config.js .prettierrc.json .prettierignore .editorconfig
git commit -m "chore: 引入 ESLint 9 + Prettier + EditorConfig 前端工具链"
```

### Task 1.2: 前端全量格式化

**Files:**
- Modify: `frontend/app.js`、`frontend/index.html`、`frontend/styles.css`、`frontend/modules/*.js`、`frontend/modules/views/*.js`、`tests/frontend/*.js`

**Interfaces:**
- Consumes: Task 1.1 的 Prettier 配置。
- Produces: 全量格式化后的前端源码（行为零变化）。

- [ ] **Step 1: 全量格式化**

Run: `npx prettier --write "frontend/**/*.{js,html,css}" "tests/frontend/*.js"`
Expected: 所有文件被格式化。

- [ ] **Step 2: 验证无行为变化**

Run: `node --check frontend/app.js && node --test "tests/frontend/*.test.js"`
Expected: 语法通过，26 项测试全绿。

- [ ] **Step 3: Commit**

```bash
git add -A frontend tests/frontend
git commit -m "chore: 前端全量 Prettier 格式化"
```

### Task 1.3: 后端工具链（pyproject.toml + requirements-dev.txt）

**Files:**
- Create: `pyproject.toml`
- Create: `requirements-dev.txt`

**Interfaces:**
- Produces: ruff / mypy / pytest / coverage 的统一配置入口，供 Task 1.4 / Phase 5 / Phase 6 复用。

- [ ] **Step 1: 创建 `pyproject.toml`**

```toml
[tool.ruff]
line-length = 120
target-version = "py313"
src = ["backend", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.mypy]
python_version = "3.13"
warn_unused_configs = true
check_untyped_defs = true
no_implicit_optional = true
ignore_missing_imports = true
files = ["backend", "tests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: 创建 `requirements-dev.txt`**

```
-r requirements.txt
ruff==0.9.10
mypy==1.15.0
pytest-cov==6.0.0
pre-commit==4.1.0
alembic==1.14.1
```

- [ ] **Step 3: 安装开发依赖**

Run: `python -m pip install -r requirements-dev.txt`
Expected: 安装成功。

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml requirements-dev.txt
git commit -m "chore: 新增 pyproject.toml 统一 ruff/mypy/pytest 配置与开发依赖"
```

### Task 1.4: 后端全量 ruff 修复 + mypy 标注修复

**Files:**
- Modify: `backend/*.py`、`tests/*.py`、`server.py`

**Interfaces:**
- Consumes: Task 1.3 的 pyproject.toml。
- Produces: 通过 `ruff check` / `ruff format --check` / `mypy backend` 的后端代码。

- [ ] **Step 1: ruff check 自动修复**

Run: `python -m ruff check backend tests server.py --fix`
Expected: 自动修复可修项；剩余问题人工处理至 `ruff check` 通过。

- [ ] **Step 2: ruff format**

Run: `python -m ruff format backend tests server.py`
Expected: 全部格式化。

- [ ] **Step 3: mypy 检查并修复标注**

Run: `python -m mypy backend`
Expected: 无错误。若因严格规则报错，按错误逐条补充类型标注（如 `dict[str, Any]`、`list[X]`、Optional），不改变运行时行为。

- [ ] **Step 4: 后端测试回归**

Run: `python -m pytest tests/ -q`
Expected: 75 项全绿。

- [ ] **Step 5: 验证格式**

Run: `python -m ruff format --check backend tests server.py && python -m ruff check backend tests server.py`
Expected: 无输出（通过）。

- [ ] **Step 6: Commit（分两个 commit：lint 修复 + 格式化）**

```bash
git add backend tests server.py pyproject.toml
git commit -m "refactor: 后端 ruff 全量修复与 mypy 类型标注补齐"
```

### Task 1.5: npm scripts 收口 + 修复 node --test 尾斜杠 bug

**Files:**
- Modify: `package.json`

**Interfaces:**
- Produces: `npm run verify` 一条命令完整回归；修复 Windows 下 `node --test tests/frontend/` 尾斜杠报错。

- [ ] **Step 1: 更新 `package.json` scripts**

```json
{
  "scripts": {
    "dev:frontend": "vite --port 5173",
    "dev:backend": "python server.py",
    "dev": "concurrently -k -n backend,frontend -c blue,green \"npm:dev:backend\" \"npm:dev:frontend\"",
    "test:frontend": "node --test \"tests/frontend/*.test.js\"",
    "check:frontend": "node --check frontend/app.js",
    "test:backend": "python -m pytest tests/",
    "lint": "eslint . && ruff check .",
    "format": "prettier --write \"frontend/**/*.{js,html,css}\" \"tests/frontend/*.js\" && ruff format backend tests server.py",
    "verify": "npm run test:frontend && npm run check:frontend && npm run test:backend"
  }
}
```

> 注：`dev` / `dev:frontend` 依赖 concurrently 与 vite，将在 Phase 2 安装；本任务先写入 scripts，Phase 2 装依赖后生效。**此时 `node --test` 尾斜杠 bug 已通过 glob 写法修复。**

- [ ] **Step 2: 验证 scripts 语法**

Run: `npm run test:frontend`
Expected: 26 项测试通过（glob 写法，Windows 不再报 MODULE_NOT_FOUND）。

- [ ] **Step 3: 验证 verify**

Run: `npm run verify`
Expected: 前端 26 项 + 语法检查 + 后端 75 项全绿。

- [ ] **Step 4: Commit**

```bash
git add package.json
git commit -m "chore: 收口 npm scripts 并修复 node --test 尾斜杠在 Windows 的报错"
```

### Task 1.6: pre-commit 钩子

**Files:**
- Create: `.pre-commit-config.yaml`

**Interfaces:**
- Produces: 提交前自动跑 ruff / mypy / eslint / prettier / node --check 的钩子。

- [ ] **Step 1: 创建 `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.10
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: python -m mypy backend
        language: system
        pass_filenames: false
      - id: eslint
        name: eslint
        entry: npx eslint .
        language: system
        pass_filenames: false
      - id: prettier
        name: prettier
        entry: npx prettier --write "frontend/**/*.{js,html,css}" "tests/frontend/*.js"
        language: system
        pass_filenames: false
      - id: node-check
        name: node-check
        entry: node --check frontend/app.js
        language: system
        pass_filenames: false
```

- [ ] **Step 2: 安装钩子**

Run: `python -m pre_commit install`
Expected: 输出 `pre-commit installed at .git/hooks/pre-commit`。

- [ ] **Step 3: 验证钩子配置**

Run: `python -m pre_commit run --all-files`
Expected: 全部通过（或仅文件级格式化差异被自动修复）。

- [ ] **Step 4: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore: 引入 pre-commit 钩子统一前后端检查"
```

### Task 1.7: 文档与 CHANGELOG 更新（Phase 1 部分）

**Files:**
- Modify: `OPERATIONS.md`、`AGENTS.md`、`CHANGELOG.md`

**Interfaces:**
- Produces: 与本分支改动一致的文档。AGENTS.md 的完整双轨改写留待 Phase 6 收口；本任务只补工具链命令。

- [ ] **Step 1: OPERATIONS.md 本地验证章节补充**

在"本地验证"小节加入：

```markdown
## 本地验证

```powershell
npm run verify        # 前端 26 项 node:test + node --check + 后端 75 项 pytest
python -m ruff check backend tests server.py
python -m ruff format --check backend tests server.py
python -m mypy backend
```
```

- [ ] **Step 2: AGENTS.md 测试章节补充**

在"## Testing"章节补充 ruff/mypy/pre-commit 命令，并注明 `node --test` 必须使用 glob 写法。

- [ ] **Step 3: CHANGELOG.md 新增版本条目**

```markdown
## [v0.4.0] - 2026-08-30

### 工程化
- 工具链：ESLint 9 + Prettier 3（前端）、ruff + mypy（后端）、pre-commit 钩子、pyproject.toml 统一配置。
- 命令收口：`npm run verify` 一键完整回归；修复 node --test 尾斜杠在 Windows 的报错。
- 后端 75 项 / 前端 26 项测试全量通过。
```

- [ ] **Step 4: Commit**

```bash
git add OPERATIONS.md AGENTS.md CHANGELOG.md
git commit -m "docs: 记录工具链命令与 Phase 1 变更"
```

### Task 1.8: Phase 1 收口验证 + git flow finish

- [ ] **Step 1: 全量验证**

Run: `npm run verify && python -m ruff check backend tests server.py && python -m ruff format --check backend tests server.py && python -m mypy backend`
Expected: 全部通过。

- [ ] **Step 2: 手工冒烟**

Run: `python server.py` → 打开 http://127.0.0.1:4173，确认全视图正常（格式化不应改变行为）。
Expected: 页面正常。

- [ ] **Step 3: git flow finish**

```bash
git flow feature finish eng-toolchain
git push origin develop
```

---

# Phase 2 — feature/eng-vite：前端 Vite+TS+SFC 迁移 + FastAPI dist 适配（最大分支）

**分支**：`git flow feature start eng-vite`
**目标**：前端从"源码静态服务"迁移为 Vite 构建体系——TS(strict) + SFC 组件 + Pinia 依赖就绪 + 一键启动；FastAPI 优先服务 dist、缺省回退源码。**逻辑原样搬移，行为零变化；状态管理仍用 APP_CTX（Pinia 迁移在 Phase 3）。**

### Task 2.1: Vite + TS 脚手架

**Files:**
- Modify: `package.json`
- Create: `vite.config.ts`
- Create: `tsconfig.json`
- Create: `frontend/index.html`（重写为最小入口）
- Create: `frontend/src/main.ts`

**Interfaces:**
- Produces: Vite 入口（`frontend/index.html` → `frontend/src/main.ts` → `App.vue`）；别名 `@` → `frontend/src`；dev proxy `/api` → :4173。

- [ ] **Step 1: 安装依赖**

Run: `npm install vue lucide pinia && npm install -D vite @vitejs/plugin-vue typescript vue-tsc concurrently @types/node`
Expected: 安装成功，lockfile 更新（提交）。

- [ ] **Step 2: 创建 `vite.config.ts`**

```ts
import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  base: '/',
  resolve: {
    alias: { '@': fileURLToPath(new URL('./frontend/src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:4173' },
  },
  build: {
    outDir: 'frontend/dist',
    emptyOutDir: true,
  },
});
```

- [ ] **Step 3: 创建 `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "jsx": "preserve",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "esModuleInterop": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "noEmit": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./frontend/src/*"] },
    "types": ["vite/client"]
  },
  "include": ["frontend/src/**/*.ts", "frontend/src/**/*.vue", "vite.config.ts", "tests/frontend/**/*.ts"],
  "exclude": ["node_modules", "frontend/dist"]
}
```

- [ ] **Step 4: 重写 `frontend/index.html` 为最小入口**

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#101a2b">
  <meta name="description" content="连接真实 A 股行情的选股、交易计划和盯盘工作台">
  <title>Atlas 交易工作台</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.ts"></script>
</body>
</html>
```

- [ ] **Step 5: 创建 `frontend/src/main.ts`（临时最小化，Task 2.3 补全）**

```ts
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import './styles.css';

createApp(App).use(createPinia()).mount('#app');
```

- [ ] **Step 6: 创建占位 `frontend/src/App.vue`（Task 2.3 填充壳）**

```vue
<template><div>Atlas</div></template>
<script setup lang="ts"></script>
```

- [ ] **Step 7: 迁移 `styles.css`**

Run: `git mv frontend/styles.css frontend/src/styles.css`
Expected: 文件移动成功，被 main.ts 引用。

- [ ] **Step 8: Commit**

```bash
git add package.json package-lock.json vite.config.ts tsconfig.json frontend/index.html frontend/src
git commit -m "feat: 引入 Vite + TypeScript 脚手架与最小入口"
```

### Task 2.2: modules 迁移 TS + node:test 迁移 vitest

**Files:**
- Create: `frontend/src/modules/constants.ts`、`format.ts`、`chart.ts`
- Modify: `tests/frontend/constants.test.ts`、`format.test.ts`、`chart.test.ts`（迁移自 .js）
- Create: `vitest.config.ts`
- Delete: `frontend/modules/constants.js`、`format.js`、`chart.js`

**Interfaces:**
- Produces: `@/modules/format.ts` 导出 `formatNumber/formatPct/formatTime/formatDateLabel/formatAmount/formatMoney/formatNullable/formatPctNullable/trendClass/escapeHtml/validityExpiry`；`@/modules/chart.ts` 导出 `chartSvg/compareChartSvg`；`@/modules/constants.ts` 导出 `STORAGE_KEY/DEFAULT_WATCHLIST/DEFAULT_FILTERS/DEFAULT_ALERTS/PRESETS/NAV_ITEMS/VIEW_META/SETTINGS_TABS/STRATEGY_TYPES/STRATEGY_SCHEMAS`。

- [ ] **Step 1: 创建 `vitest.config.ts`**

```ts
import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./frontend/src', import.meta.url)) } },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/frontend/**/*.test.ts'],
  },
});
```

- [ ] **Step 2: 安装 vitest 依赖**

Run: `npm install -D vitest jsdom @vue/test-utils`
Expected: 安装成功。

- [ ] **Step 3: 迁移三个 modules 文件**

Run: 将 `frontend/modules/constants.js` / `format.js` / `chart.js` 内容原样复制为 `.ts`（函数体零改动，仅文件扩展名与 import 路径改为 `@/modules/...`）。若严格模式报隐式 any，为参数补最小类型标注（如 `(value: number | null | undefined)`），**不改行为**。
Expected: `frontend/src/modules/*.ts` 存在且内容等价。

- [ ] **Step 4: 迁移三个测试文件**

将 `tests/frontend/constants.test.js` / `format.test.js` / `chart.test.js` 复制为 `.ts`，import 路径改为 `@/modules/...`。**断言内容逐条保留**。

- [ ] **Step 5: 运行 vitest 验证**

Run: `npx vitest run`
Expected: 26 项测试全绿。

- [ ] **Step 6: 删除旧 JS 文件**

Run: `git rm frontend/modules/constants.js frontend/modules/format.js frontend/modules/chart.js tests/frontend/*.test.js`
Expected: 删除成功（旧测试已被 .ts 版替代）。

- [ ] **Step 7: 更新 package.json 脚本**

将 `"test:frontend": "node --test \"tests/frontend/*.test.js\""` 改为 `"test:frontend": "vitest run"`。
将 `"check:frontend": "node --check frontend/app.js"` 改为 `"check:frontend": "vue-tsc --noEmit"`（app.js 迁移为 src/app.ts 后语法检查改由 vue-tsc 承担）。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/modules tests/frontend vitest.config.ts package.json package-lock.json
git commit -m "refactor: modules 迁移 TypeScript 并切换 vitest 测试框架"
```

### Task 2.3: types + api client + App.vue 壳 + 视图迁移

**Files:**
- Create: `frontend/src/types/models.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/App.vue`（完整壳，自现 index.html 搬移）
- Create: `frontend/src/views/ViewOverview.vue`、`ViewMonitor.vue`、`ViewScreener.vue`、`ViewStockDetail.vue`、`ViewGrid.vue`、`ViewPlans.vue`、`ViewSettings.vue`
- Create: `frontend/src/modules/views/context.ts`
- Modify: `frontend/src/app.ts`（自 `frontend/app.js` 迁移；setup 主体保持）
- Delete: `frontend/app.js`、`frontend/modules/views/*.js`

**Interfaces:**
- Produces: `@/types/models.ts` 的类型定义；`@/api/client.ts` 的 `requestJson<T>(url, options)`；`@/modules/views/context.ts` 的 `APP_CTX`（Symbol）；视图组件注册名 `ViewOverview` 等与 Phase 3 store 对接。

- [ ] **Step 1: 创建 `frontend/src/types/models.ts`**

```ts
// 与后端 Pydantic 契约一致的字段（字段名逐字节保持现状，不得改名）
export interface Quote {
  code: string;
  name: string;
  price: number | null;
  change: number | null;
  changePct: number | null;
  volumeRatio?: number | null;
  [key: string]: unknown;
}

export interface StockRow extends Quote {
  pe?: number | null;
  turnover?: number | null;
}

export interface Plan {
  id: string;
  code: string;
  direction: 'buy' | 'sell';
  entry: number;
  stop: number;
  target: number;
  capital: number;
  position: number;
  validity: string;
  note: string;
  status: string;
  triggered: Record<string, boolean>;
  createdAtMs: number;
}

export interface Alert {
  id: string;
  kind: 'alert' | 'success' | 'info' | 'system';
  title: string;
  message: string;
  read: boolean;
  createdAtMs: number;
  count?: number;
}

export interface HistoryBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
```

- [ ] **Step 2: 创建 `frontend/src/api/client.ts`**

```ts
// 自 app.js 的 requestJson 迁移，返回类型泛型化；行为等价
export async function requestJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = await res.json();
    } catch {
      /* 非 JSON 错误体 */
    }
    const error = new Error(detail && typeof detail === 'object' && 'error' in detail ? String((detail as { error: unknown }).error) : `HTTP ${res.status}`) as Error & { code?: string; status: number; detail?: unknown };
    error.status = res.status;
    error.detail = detail;
    if (detail && typeof detail === 'object' && 'code' in detail) error.code = String((detail as { code: unknown }).code);
    throw error;
  }
  return res.json() as Promise<T>;
}
```

- [ ] **Step 3: 创建 `frontend/src/modules/views/context.ts`**

```ts
export const APP_CTX = Symbol('atlas.app.context');
```

- [ ] **Step 4: 创建 `frontend/src/app.ts`**

将 `frontend/app.js` 内容复制为 `.ts`，改三处 import：
- `import { ... } from './modules/constants.js'` → `from '@/modules/constants'`
- `import { ... } from './modules/format.js'` → `from '@/modules/format'`
- `import { chartSvg, compareChartSvg } from './modules/chart.js'` → `from '@/modules/chart'`
- `import { APP_CTX } from './modules/views/context.js'` → `from '@/modules/views/context'`
- 视图 import 改为 `@/views/ViewXxx.vue`
- 删除末尾 `createApp(appOptions)` 与组件注册（改由 main.ts + App.vue 完成）
- 顶部 `const { createApp, ref, ... } = Vue` 改为 `import { ref, reactive, computed, watch, onMounted, onBeforeUnmount, nextTick, provide } from 'vue'`（createApp 移到 main.ts）
- `export const appOptions` 导出（供 App.vue 使用）

**若 strict 报隐式 any**：为 setup 参数/返回补最小类型（如 `(stock: StockRow | undefined)`），**不改行为**。

- [ ] **Step 5: 创建 `frontend/src/App.vue`**

将现 `frontend/index.html` 中 `<div id="app">` 内的壳（sidebar/topbar/notif/footer/bottom-nav 全部模板）搬入 `<template>`；`<script setup lang="ts">` 中：

```ts
import { computed, provide, ref } from 'vue';
import { appOptions } from '@/app';
// 视图按 view 值切换（v-if），逻辑来自 appOptions.setup 返回值
```

> 实现说明：App.vue 的 setup 调用 `appOptions.setup()` 拿到全部状态与函数，`provide(APP_CTX, {...})` 供视图 inject；模板与现 index.html 的插值表达式逐字保留。

- [ ] **Step 6: 迁移 7 个视图组件**

对每个 `frontend/modules/views/ViewXxx.js`：
1. 复制为 `frontend/src/views/ViewXxx.vue`。
2. 模板字符串内容 → `<template>`；`setup()` → `<script setup lang="ts">`（`const ctx = inject(APP_CTX)` 保留；从 ctx 解构所需字段原样保留；`onMounted(() => renderIcons())` 保留）。
3. import 改为 `import { inject, onMounted } from 'vue'; import { APP_CTX } from '@/modules/views/context';`。
4. 删除 JS 原文件。

示例（ViewPlans）：

```vue
<template>
  <section class="view-panel is-active">
    <!-- 原 template 字符串内容逐字搬入 -->
  </section>
</template>

<script setup lang="ts">
import { inject, onMounted } from 'vue';
import { APP_CTX } from '@/modules/views/context';

const ctx = inject(APP_CTX)!;
const { activePlans, draft, draftDirty, planOptions, planMetrics, savePlan, formatMoney, formatNumber, quoteFor, calculateRr, calculateShares, monitorPlan, archivePlan, switchView, refreshAll, renderIcons } = ctx;
onMounted(() => renderIcons());
</script>
```

- [ ] **Step 7: 删除 vendor 并接入 lucide**

Run: `git rm -r frontend/vendor`
在 `app.ts` 顶部（或 main.ts）加入：

```ts
import { createIcons } from 'lucide';
// 原 renderIcons 的实现从 window.lucide.createIcons() 改为 createIcons()
```

`renderIcons()` 内 `lucide.createIcons()` → `createIcons()`（`lucide` 命名空间改为 import 的 `createIcons`）。

- [ ] **Step 8: 类型检查**

Run: `npx vue-tsc --noEmit`
Expected: 无错误（如 strict 报错，按错误最小修复，不改行为）。

- [ ] **Step 9: 构建验证**

Run: `npm run build`
Expected: 产出 `frontend/dist/`。

- [ ] **Step 10: 同步更新 pre-commit 的 node-check 钩子**

`.pre-commit-config.yaml` 中 `node-check` 钩子的 entry 改为 `npx vue-tsc --noEmit`（app.js 已迁移为 app.ts），`pass_filenames: false` 不变。若 `node --check frontend/app.js` 不再适用，直接删除该本地钩子（类型检查由 vue-tsc 兜底）。

- [ ] **Step 11: Commit**

```bash
git add frontend/src frontend/index.html frontend/app.js frontend/modules package.json package-lock.json .pre-commit-config.yaml
git commit -m "feat: 前端迁移 SFC 组件与 TypeScript，接入 lucide 核心包"
```

### Task 2.4: FastAPI dist 适配 + 一键启动

**Files:**
- Modify: `backend/app.py`（FRONTEND_DIR/DIST_DIR 逻辑与 index 路由）
- Modify: `package.json`（dev 脚本确认）

**Interfaces:**
- Produces: FastAPI 优先服务 `frontend/dist`、无 dist 回退源码；`npm run dev` 一键启动。

- [ ] **Step 1: 修改 `backend/app.py`**

```python
FRONTEND_DIR = ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
STATIC_DIR = DIST_DIR if DIST_DIR.exists() else FRONTEND_DIR
```

- [ ] **Step 2: 修改挂载与 index 路由**

```python
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")
```

```python
    @app.get("/")
    def index():
        index_file = DIST_DIR / "index.html" if DIST_DIR.exists() else FRONTEND_DIR / "index.html"
        return FileResponse(index_file)
```

- [ ] **Step 3: 确认 `package.json` dev 脚本完整**

确认 scripts 含：

```json
"dev": "concurrently -k -n backend,frontend -c blue,green \"npm:dev:backend\" \"npm:dev:frontend\"",
"dev:backend": "python server.py",
"dev:frontend": "vite --port 5173"
```

- [ ] **Step 4: 一键启动验证**

Run: `npm run dev`
Expected: 两个进程启动；打开 http://127.0.0.1:5173 全视图正常、HMR 生效、`/api/health` 代理成功。Ctrl+C 同时终止两进程。

- [ ] **Step 5: 单进程形态验证**

Run: `npm run build && python server.py` → 打开 http://127.0.0.1:4173
Expected: 服务 dist，全视图正常。

- [ ] **Step 6: 无 dist 回退验证**

Run: `git stash` 掉 dist（或临时改 DIST_DIR 判断）后 `python server.py` → :4173
Expected: 回退源码服务，页面正常。

- [ ] **Step 7: Commit**

```bash
git add backend/app.py package.json package-lock.json
git commit -m "feat: FastAPI 双轨托管 dist/源码 + npm run dev 一键启动"
```

### Task 2.5: Phase 2 收口验证 + git flow finish

- [ ] **Step 1: 全量验证**

Run: `npx vue-tsc --noEmit && npx eslint . && npx vitest run && npm run verify`
Expected: 全部通过（注意：eslint 需兼容 .ts/.vue——若报解析错误，在 eslint.config.js 增加 `files: ['frontend/src/**/*.{ts,vue}']` 的 TS 解析，最小配置即可，Phase 6 完善）。

- [ ] **Step 2: 后端回归**

Run: `python -m pytest tests/ -q && python -m ruff check backend tests server.py && python -m mypy backend`
Expected: 全绿。

- [ ] **Step 3: 双形态手工冒烟**

Run: `npm run dev`（:5173）与 `npm run build && python server.py`（:4173）各打开一遍，全视图 + 行情 + 计划 + 网格功能正常。
Expected: 正常。

- [ ] **Step 4: git flow finish**

```bash
git flow feature finish eng-vite
git push origin develop
```

---

# Phase 3 — feature/eng-refactor：前端 Pinia stores + 纯逻辑抽取

**分支**：`git flow feature start eng-refactor`
**目标**：抽纯逻辑到 `@/modules/*Utils.ts`（配 vitest 测试）；引入 Pinia 8 个 store 替代 `APP_CTX`，`APP_CTX`/`context.ts` 退役；视图改 `useXxxStore()`。**行为零变化。**

### Task 3.1: 抽取 planUtils + marketUtils + signalUtils + alertUtils

**Files:**
- Create: `frontend/src/modules/planUtils.ts`
- Create: `frontend/src/modules/marketUtils.ts`
- Create: `frontend/src/modules/signalUtils.ts`
- Create: `frontend/src/modules/alertUtils.ts`
- Create: `tests/frontend/planUtils.test.ts`、`marketUtils.test.ts`、`signalUtils.test.ts`、`alertUtils.test.ts`

**Interfaces:**
- Produces:
  - `planUtils.ts`: `calculateShares(plan: Plan): number`、`calculateRr(plan: Plan): number`、`expiredPlans(plans: Plan[], now: number): Plan[]`（返回应标记已过期的计划，含 `status: '已过期'` 副本，不就地修改）
  - `marketUtils.ts`: `mergeMarketQuotes(existing: Quote[], incoming: Quote[]): Quote[]`（按 code 合并，incoming 覆盖同名；抽取自 app.js `mergeMarket(payload)` 内 quotes 合并核心逻辑）
  - `signalUtils.ts`: `signalText(stock: Quote | undefined | null, plan: Plan | null): string`、`signalClass(text: string): string`
  - `alertUtils.ts`: `dedupeSystemAlert(alerts: Alert[], kind: string, title: string, message: string, now: number): { alerts: Alert[]; count: number }`（返回去重/追加后的数组与计数值，纯函数不修改入参）

- [ ] **Step 1: 为每个工具模块写失败测试**

`tests/frontend/planUtils.test.ts`（节选，完整覆盖正常/边缘/null）：

```ts
import { describe, expect, it } from 'vitest';
import { calculateShares, calculateRr, expiredPlans } from '@/modules/planUtils';
import type { Plan } from '@/types/models';

const basePlan: Plan = {
  id: 'p1', code: '600519', direction: 'buy', entry: 1700, stop: 1600, target: 1900,
  capital: 100000, position: 50, validity: '今日', note: '', status: '执行中',
  triggered: {}, createdAtMs: 0,
};

describe('planUtils', () => {
  it('calculateShares 按资金与仓位计算整手股数', () => {
    expect(calculateShares(basePlan)).toBe(2900); // 50000 / 1700 = 29.41 手 → 2900 股
    expect(calculateShares({ ...basePlan, entry: 0 })).toBe(0);
  });
  it('calculateRr 计算盈亏比', () => {
    expect(calculateRr(basePlan)).toBe(2); // (1900-1700)/(1700-1600)
    expect(calculateRr({ ...basePlan, stop: 1700 })).toBe(0);
  });
  it('expiredPlans 标记过期且不改原数组', () => {
    const now = Date.now();
    const plans = [{ ...basePlan, createdAtMs: now - 2 * 86400000 }];
    const result = expiredPlans(plans, now);
    expect(result[0].status).toBe('已过期');
    expect(plans[0].status).toBe('执行中');
    expect(expiredPlans([], now)).toEqual([]);
  });
});
```

（marketUtils / signalUtils / alertUtils 测试按同样模式编写：mergeMarketQuotes 覆盖同名合并与新增；signalText 覆盖触及止损/目标/计划价/等待报价/放量突破/弱势观察/量能放大/跟踪中；signalClass 覆盖四类 chip；dedupeSystemAlert 覆盖 10 分钟去重与普通追加。）

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/planUtils.test.ts`
Expected: FAIL（模块不存在）。

- [ ] **Step 3: 实现四个工具模块（最小实现）**

`planUtils.ts`：

```ts
import type { Plan } from '@/types/models';

export function calculateShares(plan: Plan): number {
  const budget = Number(plan.capital || 0) * (Number(plan.position || 0) / 100);
  return plan.entry > 0 ? Math.max(0, Math.floor(budget / plan.entry / 100) * 100) : 0;
}

export function calculateRr(plan: Plan): number {
  const risk = Math.max(0.01, Number(plan.entry) - Number(plan.stop));
  const reward = Math.max(0, Number(plan.target) - Number(plan.entry));
  return reward / risk;
}

export function expiredPlans(plans: Plan[], now: number): Plan[] {
  const result: Plan[] = [];
  for (const plan of plans) {
    if (plan.status !== '执行中') continue;
    const expiresAt = validityExpiry(plan.createdAtMs, plan.validity);
    if (expiresAt && now > expiresAt) result.push({ ...plan, status: '已过期' });
  }
  return result;
}
```

> 注：`expiredPlans` 需要 `validityExpiry`——从 `@/modules/format` 导入。

`marketUtils.ts`：

```ts
import type { Quote } from '@/types/models';

export function mergeMarketQuotes(existing: Quote[], incoming: Quote[]): Quote[] {
  const map = new Map(existing.map((q) => [q.code, q]));
  for (const q of incoming) map.set(q.code, q);
  return [...map.values()];
}
```

`signalUtils.ts`（从 app.js `signalText`/`signalClass` 原样移植，`planFor` 改为入参）：

```ts
import type { Plan, Quote } from '@/types/models';

export function signalText(stock: Quote | undefined | null, plan: Plan | null): string {
  if (plan && stock?.price != null) {
    if (stock.price <= plan.stop) return '触及止损';
    if (stock.price >= plan.target) return '触及目标';
    if (stock.price <= plan.entry) return '触及计划价';
  }
  if (stock?.change == null) return '等待报价';
  if (stock.change >= 3 && Number(stock.volumeRatio || 0) >= 1.5) return '放量突破';
  if (stock.change <= -3) return '弱势观察';
  if (Number(stock.volumeRatio || 0) >= 1.5) return '量能放大';
  return '跟踪中';
}

export function signalClass(text: string): string {
  if (text === '触及止损') return 'signal-chip-risk';
  if (text === '触及目标' || text === '触及计划价' || text === '放量突破') return 'signal-chip-buy';
  if (text === '等待报价') return 'signal-chip-neutral';
  return 'signal-chip-watch';
}
```

`alertUtils.ts`：

```ts
import type { Alert } from '@/types/models';

export function dedupeSystemAlert(
  alerts: Alert[], kind: string, title: string, message: string, now: number,
): { alerts: Alert[]; count: number } {
  const list = [...alerts];
  if (kind === 'system') {
    const existing = list.find((item) => item.kind === 'system' && item.title === title);
    if (existing && now - (existing.createdAtMs || 0) < 10 * 60 * 1000) {
      const count = (existing.count || 1) + 1;
      list.splice(list.indexOf(existing), 1, { ...existing, count, message: count > 1 ? `${message}（10 分钟内第 ${count} 次）` : message, createdAtMs: now });
      return { alerts: list, count };
    }
  }
  list.unshift({ id: `alert-${now}-${Math.random().toString(16).slice(2)}`, kind: kind as Alert['kind'], title, message, read: false, createdAtMs: now });
  return { alerts: list.slice(0, 24), count: 1 };
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run tests/frontend/planUtils.test.ts tests/frontend/marketUtils.test.ts tests/frontend/signalUtils.test.ts tests/frontend/alertUtils.test.ts`
Expected: 全部 PASS。

- [ ] **Step 5: 接入 app.ts**

- `calculateShares`/`calculateRr`：`app.ts` 中改 import 使用（删除内部定义）。
- `expirePlans()`：改为 `const expired = expiredPlans(plans.value, Date.now()); if (expired.length) { plans.value = plans.value.map((p) => expired.find((e) => e.id === p.id) ? { ...p, status: '已过期' } : p); ... }`——**保持与旧逻辑等价的副作用**（旧逻辑就地改 status 并 alert/persist）。
- `signalText(stock)` 内部改为 `signalText(stock, planFor(stock?.code))`；`signalClass(stock)` 改为 `signalClass(signalText(stock, planFor(stock?.code)))`（新纯函数接收 text）。
- `addAlert` 内部数组操作改用 `dedupeSystemAlert`（保留 Notification 副作用与 persist 逻辑在外层）。
- `mergeMarket(payload)` 内 quotes 合并行改为 `market.quotes = mergeMarketQuotes(market.quotes, payload.quotes || [])`（其余 indices/provider/fetchedAt/errors 赋值保持原位）。

- [ ] **Step 6: 全量测试 + 类型检查**

Run: `npx vitest run && npx vue-tsc --noEmit`
Expected: 全绿。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules tests/frontend frontend/src/app.ts
git commit -m "refactor: 抽取计划/行情/信号/提醒纯逻辑模块并补测试"
```

### Task 3.2: 引入 Pinia 8 个 store

**Files:**
- Create: `frontend/src/stores/useWorkspaceStore.ts`、`useQuotesStore.ts`、`useScreenerStore.ts`、`usePlansStore.ts`、`useAlertsStore.ts`、`useSettingsStore.ts`、`useGridStore.ts`、`useStrategyStore.ts`

**Interfaces:**
- Produces: 8 个 `defineStore('xxx', ...)` store，导出 `useXxxStore()`。每个 store 持有 app.ts setup 中对应域的 `ref`/`reactive` 状态与函数（state/actions/getters 对应），字段名与现 `APP_CTX` 暴露一致。

- [ ] **Step 1: 创建 `useWorkspaceStore.ts`（示例，其余 7 个同模式）**

```ts
import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { Alert, Plan } from '@/types/models';

export const useWorkspaceStore = defineStore('workspace', () => {
  const watchlistCodes = ref<string[]>([]);
  const plans = ref<Plan[]>([]);
  const alerts = ref<Alert[]>([]);
  const workspaceRevision = ref(0);
  const conflictVisible = ref(false);
  const conflictSnapshot = ref<unknown>(null);

  // actions：loadWorkspace / adoptServerWorkspace / pushLocalWorkspace / forceSaveWorkspace /
  // persistLocal / persist / scheduleWorkspaceSync 等，从 app.ts setup 原样搬入（状态改 this.xxx / storeToRefs 用法）

  return { watchlistCodes, plans, alerts, workspaceRevision, conflictVisible, conflictSnapshot };
});
```

> 实现说明：8 个 store 的拆分边界按 spec 表（workspace/quotes/screener/plans/alerts/settings/grid/strategy）。**把 app.ts setup 中对应域的状态声明与函数原样搬入**，`ref`/`reactive`/`computed` 保留，跨 store 依赖用 `useXxxStore()` 互相调用。函数体内 `planOptions`/`presetHits` 等 computed 归属对应 store。

- [ ] **Step 2: 创建其余 7 个 store**（按 spec 表逐域搬移，边界见设计文档 `docs/superpowers/specs/2026-08-30-fullstack-engineering-design.md` 的 8 行表格）

- [ ] **Step 3: 类型检查**

Run: `npx vue-tsc --noEmit`
Expected: 通过（若跨 store 类型报错，按错误修正 store 返回类型）。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores
git commit -m "feat: 引入 Pinia 八个领域 store"
```

### Task 3.3: 视图切换 store + APP_CTX 退役

**Files:**
- Modify: `frontend/src/app.ts`、`frontend/src/App.vue`、`frontend/src/views/*.vue`（7 个）
- Delete: `frontend/src/modules/views/context.ts`

**Interfaces:**
- Consumes: Task 3.2 的 8 个 store。
- Produces: 视图通过 `useXxxStore()` 取状态；`APP_CTX` 删除。

- [ ] **Step 1: App.vue 移除 provide，改为组合 store**

`App.vue` 的 setup 改为：调用各 `useXxxStore()`（store 已在 main.ts 注册），把视图需要的状态/函数放进返回对象（模板插值逐字保留）。删除 `provide(APP_CTX, ...)`。

- [ ] **Step 2: 逐个视图改 inject → store**

每个 `views/ViewXxx.vue`：

```ts
// 改前
const ctx = inject(APP_CTX)!;
const { activePlans, ... } = ctx;
// 改后
const store = usePlansStore(); // 视所需域选择 1 或多个 store
const { activePlans, ... } = storeToRefs(store); // ref 用 storeToRefs；函数直接从 store 取
```

- [ ] **Step 3: 删除 context.ts 与 app.ts 中 APP_CTX 残留**

Run: `git rm frontend/src/modules/views/context.ts`
在 app.ts/App.vue 中删除 APP_CTX 相关 import 与 provide 调用。

- [ ] **Step 4: 全量验证**

Run: `npx vue-tsc --noEmit && npx vitest run && npx eslint . && npm run build`
Expected: 全绿，dist 产出。

- [ ] **Step 5: 双形态手工冒烟**

Run: `npm run dev`（:5173）与 `npm run build && python server.py`（:4173），全视图 + 计划创建/触发/过期 + 提醒 + 网格 + 设置冲突全流程。
Expected: 正常。

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "refactor: 视图迁移 Pinia store，退役 APP_CTX"
```

### Task 3.4: Phase 3 收口 + git flow finish

- [ ] **Step 1: 全量验证**

Run: `npm run verify && npx vue-tsc --noEmit && npx eslint . && npm run build`
Expected: 全部通过。

- [ ] **Step 2: 后端回归**

Run: `python -m pytest tests/ -q`
Expected: 75 项全绿（后端未改动，仅确认无意外影响）。

- [ ] **Step 3: git flow finish**

```bash
git flow feature finish eng-refactor
git push origin develop
```

---

# Phase 4 — feature/eng-backend：后端 Pydantic 模型化 + Alembic

**分支**：`git flow feature start eng-backend`
**目标**：全部 17 个路由改 Pydantic 请求/响应模型（字段名不变）；引入 Alembic baseline 迁移，未来 schema 变更走迁移；`initialize_storage` 保持幂等。

### Task 4.1: backend/schemas.py 请求模型

**Files:**
- Create: `backend/schemas.py`

**Interfaces:**
- Produces: 请求模型类（字段与现 `Body(...)` 接收的 dict key 完全一致）：
  - `WorkspacePut`（workspace 结构：watchlist: list[str], plans: list[dict], alerts: list[dict], monitorEnabled: bool, presetName: str, revision: int）
  - `SettingsPut`（workspaceName, defaultCapital, monitorEnabled, realtimeSource, historySource, screenerSource, fallbackEnabled, refreshInterval, cacheSeconds, timeoutSeconds, retryCount, conflictPolicy, notifyDesktopAlert, notifyDesktopSystem）
  - `GridPreviewIn`（code, lookback, gridCount）
  - `GridBacktestIn`（code, lower, upper, gridCount, capital, feeBps, mode, lookback, settlementDays, slippageBps, name?, schedule?）
  - `GridOptimizeIn`（code, lookback, minCount, maxCount, ...按现路由接收的 key）
  - `StrategyPreviewIn` / `StrategyBacktestIn` / `StrategyStatusPut`（按现路由 key）

- [ ] **Step 1: 阅读现 app.py 对应路由的 Body 参数与 storage 使用**

Run: 查看 `backend/app.py` 中 `update_workspace` / `update_settings` / `grid_preview` / `grid_backtest` / `grid_optimize` / `strategy_preview` / `strategy_backtest` / `update_strategy_status` / `update_grid_strategy_status` 的 payload 使用处，收集全部字段名。
Expected: 字段清单齐备。

- [ ] **Step 2: 编写 `backend/schemas.py` 请求模型**

```python
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class WorkspacePut(BaseModel):
    watchlist: list[str] = Field(default_factory=list)
    plans: list[dict[str, Any]] = Field(default_factory=list)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    monitorEnabled: bool = True
    presetName: str = ""
    revision: int = 0
    # 其它字段：按现 workspace 结构补充（额外 key 用 model_config = ConfigDict(extra="ignore") 容忍）


class SettingsPut(BaseModel):
    workspaceName: str = "个人工作区"
    defaultCapital: float = 100000
    monitorEnabled: bool = True
    realtimeSource: str = "tencent"
    historySource: str = "tencent"
    screenerSource: str = "tencent"
    fallbackEnabled: bool = True
    refreshInterval: int = 15
    cacheSeconds: int = 8
    timeoutSeconds: int = 10
    retryCount: int = 1
    conflictPolicy: str = "server"
    notifyDesktopAlert: bool = True
    notifyDesktopSystem: bool = False
    model_config = {"extra": "ignore"}


class GridBacktestIn(BaseModel):
    code: str
    lower: float
    upper: float
    gridCount: int
    capital: float
    feeBps: float = 3
    mode: str = "classic"
    lookback: int = 120
    settlementDays: int = 1
    slippageBps: float = 5
    name: str | None = None
    schedule: str = "manual"
    model_config = {"extra": "ignore"}
```

（GridPreviewIn / GridOptimizeIn / StrategyPreviewIn / StrategyBacktestIn / StrategyStatusPut 同模式，字段按 Step 1 清单补全。）

- [ ] **Step 3: 编写模型测试**

`tests/test_schemas.py`：

```python
from backend.schemas import GridBacktestIn, SettingsPut, WorkspacePut


def test_settings_defaults():
    s = SettingsPut()
    assert s.refreshInterval == 15
    assert s.conflictPolicy == "server"


def test_workspace_put_extra_ignored():
    w = WorkspacePut.model_validate({"watchlist": ["600519"], "unknown": 1})
    assert w.watchlist == ["600519"]


def test_grid_backtest_required_fields():
    g = GridBacktestIn(code="588000", lower=1.0, upper=2.0, gridCount=8, capital=100000)
    assert g.mode == "classic"
```

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_schemas.py -v`
Expected: 3 项 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/schemas.py tests/test_schemas.py
git commit -m "feat: 新增后端 Pydantic 请求模型与测试"
```

### Task 4.2: 响应模型 + 路由改造

**Files:**
- Modify: `backend/schemas.py`（追加响应模型）
- Modify: `backend/app.py`（17 个路由改签名）

**Interfaces:**
- Produces: 响应模型（HealthOut / WorkspaceOut / SettingsOut / MarketOut / HistoryOut / ScreenerOut / GridStrategiesOut / StrategiesOut 等，字段与现返回 dict 一致）；路由 `payload: dict = Body(...)` → 具体模型类型。

- [ ] **Step 1: schemas.py 追加响应模型**

```python
class HealthOut(BaseModel):
    status: str
    storage: str
    quoteSource: str
    # 按现 /api/health 返回字段补齐


class MarketOut(BaseModel):
    quotes: list[dict[str, Any]] = Field(default_factory=list)
    indices: list[dict[str, Any]] = Field(default_factory=list)
    fetchedAt: int = 0
    provider: str = "tencent"
    stale: bool = False
    model_config = {"extra": "ignore"}
```

（其余响应模型按各路由现返回 dict 的顶层 key 定义；`list[dict[str, Any]]` 内层结构不展开——保持字段名与前端消费一致。）

- [ ] **Step 2: 逐路由改造签名**

`backend/app.py` 中：

```python
@app.put("/api/workspace")
def update_workspace(payload: WorkspacePut, workspace_id: str = Query(default="default", alias="workspace")):
    # 函数体不变，payload.xxx 访问替代 payload["xxx"]（dict → 模型属性）
```

`@app.get("/api/health")` → `def health() -> HealthOut:`
其余 GET 路由加返回注解；POST/PUT 路由 Body 参数换具体模型。

- [ ] **Step 3: 回归既有测试**

Run: `python -m pytest tests/ -q`
Expected: 75 项全绿（+ 新增 schema 测试）。

- [ ] **Step 4: ruff + mypy**

Run: `python -m ruff check backend tests && python -m mypy backend`
Expected: 通过（mypy 对 Pydantic 模型属性访问需确认字段名拼写正确）。

- [ ] **Step 5: 手工冒烟 API**

Run: `python server.py` → 打开 http://127.0.0.1:4173/docs，逐个端点试调用（workspace GET/PUT、settings GET/PUT、market、history、screener、grid preview/backtest/optimize、strategy preview/backtest）。
Expected: 全部 200，返回结构与改造前一致。

- [ ] **Step 6: Commit（可拆多个 commit，按路由组）**

```bash
git add backend/schemas.py backend/app.py tests
git commit -m "refactor: 全部路由切换 Pydantic 请求/响应模型（字段名不变）"
```

### Task 4.3: Alembic 引入 + baseline 迁移

**Files:**
- Create: `alembic.ini`
- Create: `backend/migrations/env.py`、`script.py.mako`、`versions/0001_baseline.py`
- Modify: `backend/storage.py`（initialize_storage 幂等收敛）

**Interfaces:**
- Produces: `python -m alembic upgrade head` 在空库建全部表；`initialize_storage()` 在迁移后仍幂等。

- [ ] **Step 1: alembic 初始化**

Run: `python -m alembic init backend/migrations`
Expected: 生成 `alembic.ini` + `backend/migrations/`。

- [ ] **Step 2: 配置 alembic.ini 与 env.py**

`alembic.ini`：
```ini
[alembic]
script_location = backend/migrations
sqlalchemy.url = postgresql+psycopg://postgres:POSTGRES_PASSWORD@127.0.0.1:5432/stock_trade_agent
```

`backend/migrations/env.py` 改为从 `backend.settings.get_settings()` 取 URL：

```python
from backend.settings import get_settings
config.set_main_option("sqlalchemy.url", get_settings().database_url.render_as_string(hide_password=False))
```

- [ ] **Step 3: 生成 baseline 迁移**

Run: `python -m alembic revision --autogenerate -m "baseline schema" -o`（若 autogenerate 需 DB 连接，则手写迁移；**本步在已初始化过表的开发库上执行，用于对照**）
预期产物：`backend/migrations/versions/0001_baseline.py` 包含全部表（watchlist_items / trade_plans / alerts / grid_strategies / grid_backtests / strategies / strategy_backtests / market_bars / workspace_settings 等，以 storage.py Base.metadata 为准）。

> 若环境无可用 DB：手写 baseline 迁移，`op.create_table(...)` 逐一对应 storage.py 的 `Base.metadata` 表结构（列名/类型/约束照抄模型定义）。

- [ ] **Step 4: 空库验证 upgrade**

Run: `python -m alembic upgrade head`
Expected: 空库建表成功；`alembic_version` 表记录版本。

- [ ] **Step 5: initialize_storage 幂等收敛**

`storage.py` 的 `initialize_storage()` 中，原生 `ALTER TABLE ... IF NOT EXISTS` 逻辑保留为**兜底**（对已迁移库无副作用），并新增注释说明"正式迁移走 Alembic，此处仅兼容历史库"。**不删除现有逻辑**（避免破坏既有部署）。

- [ ] **Step 6: 验证既有库无破坏**

Run: `python -m alembic current`
Expected: 输出 baseline 版本号；业务查询正常。

- [ ] **Step 7: Commit**

```bash
git add alembic.ini backend/migrations backend/storage.py
git commit -m "feat: 引入 Alembic 迁移框架与 baseline 初始迁移"
```

### Task 4.4: Phase 4 收口 + git flow finish

- [ ] **Step 1: 全量验证**

Run: `python -m pytest tests/ -q && python -m ruff check backend tests server.py && python -m ruff format --check backend tests server.py && python -m mypy backend`
Expected: 全绿。

- [ ] **Step 2: API 冒烟**

Run: `python server.py` → :4173/docs 各端点 200。
Expected: 正常。

- [ ] **Step 3: git flow finish**

```bash
git flow feature finish eng-backend
git push origin develop
```

---

# Phase 5 — feature/eng-test：前端 vitest 组件测试 + 后端覆盖率

**分支**：`git flow feature start eng-test`
**目标**：前端组件测试（mount View + mock store）；后端 pytest-cov ≥80% 门禁。

### Task 5.1: 前端组件测试

**Files:**
- Create: `tests/frontend/ViewPlans.test.ts`、`ViewScreener.test.ts`、`ViewSettings.test.ts`（每视图一个，覆盖关键交互；其余视图可后续补）

**Interfaces:**
- Consumes: Phase 3 的 stores；`@vue/test-utils`。

- [ ] **Step 1: 编写 ViewPlans 组件测试**

`tests/frontend/ViewPlans.test.ts`：

```ts
import { describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ViewPlans from '@/views/ViewPlans.vue';
import { usePlansStore } from '@/stores/usePlansStore';

describe('ViewPlans', () => {
  it('渲染执行中计划列表', () => {
    setActivePinia(createPinia());
    const store = usePlansStore();
    store.plans = [{ id: 'p1', code: '600519', direction: 'buy', entry: 1700, stop: 1600, target: 1900, capital: 100000, position: 50, validity: '今日', note: '', status: '执行中', triggered: {}, createdAtMs: Date.now() }];
    const wrapper = mount(ViewPlans);
    expect(wrapper.text()).toContain('600519');
    expect(wrapper.text()).toContain('执行中');
  });
});
```

- [ ] **Step 2: 编写 ViewScreener / ViewSettings 测试**（按同模式，注入对应 store 状态，断言关键渲染：筛选行数、设置字段回显）

- [ ] **Step 3: 运行测试**

Run: `npx vitest run`
Expected: 新增组件测试 + 既有测试全绿。若组件测试因依赖注入缺失报错，检查 store 需在 `setActivePinia` 后实例化。

- [ ] **Step 4: Commit**

```bash
git add tests/frontend
git commit -m "test: 新增视图组件测试（mock Pinia store）"
```

### Task 5.2: 后端覆盖率门禁

**Files:**
- Modify: `pyproject.toml`（pytest addopts 加 --cov）
- Modify: `package.json`（可选，test:backend 脚本同步）

**Interfaces:**
- Produces: `python -m pytest --cov=backend --cov-fail-under=80` 门禁。

- [ ] **Step 1: 跑覆盖率基线**

Run: `python -m pytest tests/ -q --cov=backend --cov-report=term-missing`
Expected: 输出覆盖率百分比。若 <80%，补测试至达标（优先补 api 路由与 storage 层）。

- [ ] **Step 2: 补齐测试至 ≥80%**

针对未覆盖分支新增测试（如 `/api/health` 存储异常分支、grid optimize 参数边界、strategy backtest 空信号等），沿用现有 monkeypatch 离线模式。

- [ ] **Step 3: 写入门禁**

`pyproject.toml`：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q --cov=backend --cov-fail-under=80 --cov-report=term-missing"
```

- [ ] **Step 4: 验证门禁**

Run: `python -m pytest tests/ -q`
Expected: 通过，覆盖率 ≥80%。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests
git commit -m "test: 后端 pytest-cov 覆盖率门禁 ≥80%"
```

### Task 5.3: Phase 5 收口 + git flow finish

- [ ] **Step 1: 全量验证**

Run: `npm run verify && npx vue-tsc --noEmit && npx eslint . && python -m pytest tests/ -q && python -m ruff check backend tests server.py && python -m mypy backend`
Expected: 全绿。

- [ ] **Step 2: git flow finish**

```bash
git flow feature finish eng-test
git push origin develop
```

---

# Phase 6 — feature/eng-ci：CI 全栈门禁 + 文档收口

**分支**：`git flow feature start eng-ci`
**目标**：GitHub Actions 3-job 全栈 CI；AGENTS.md 双轨改写；OPERATIONS.md / README.md 全面更新；CHANGELOG 汇总。

### Task 6.1: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: push/PR 触发；backend / frontend / build 三个 job。

- [ ] **Step 1: 创建 `.github/workflows/ci.yml`**

```yaml
name: CI

on: [push, pull_request]

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -r requirements-dev.txt
      - run: ruff check backend tests server.py
      - run: ruff format --check backend tests server.py
      - run: mypy backend
      - run: python -m pytest tests/ -q

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - run: npm ci
      - run: npx vue-tsc --noEmit
      - run: npx eslint .
      - run: npx vitest run

  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: npm ci
      - run: npm run build
      - run: pip install -r requirements.txt
      - run: python server.py & sleep 5
      - run: curl -f http://127.0.0.1:4173/api/health
      - run: curl -f http://127.0.0.1:4173/
```

- [ ] **Step 2: 本地验证 workflow 语法**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: 无异常（或改用 npx actionlint 若已安装）。

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: 新增全栈 GitHub Actions 门禁（后端/前端/构建）"
```

### Task 6.2: ESLint TS/Vue 配置完善

**Files:**
- Modify: `eslint.config.js`

**Interfaces:**
- Produces: eslint 覆盖 `.ts` / `.vue`（Phase 2 起就有此需求，此处正式完善）。

- [ ] **Step 1: 扩展 `eslint.config.js`**

```js
import tseslint from 'typescript-eslint';
import vue from 'eslint-plugin-vue';

export default [
  { ignores: ['node_modules/**', 'frontend/dist/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs['flat/recommended'],
  {
    files: ['frontend/src/**/*.{ts,vue}'],
    languageOptions: {
      parserOptions: { parser: tseslint.parser, extraFileExtensions: ['.vue'] },
      globals: { ...globals.browser },
    },
    rules: { '@typescript-eslint/no-explicit-any': 'off' },
  },
  // ...其余（JS 全局 Vue、node）
];
```

Run: `npm install -D typescript-eslint eslint-plugin-vue`
Expected: 安装成功。

- [ ] **Step 2: 全量 lint**

Run: `npx eslint .`
Expected: 通过（若有存量告警，逐个修复至无 error）。

- [ ] **Step 3: Commit**

```bash
git add eslint.config.js package.json package-lock.json
git commit -m "chore: ESLint 覆盖 TypeScript 与 Vue SFC"
```

### Task 6.3: 文档收口

**Files:**
- Modify: `AGENTS.md`、`OPERATIONS.md`、`README.md`、`CHANGELOG.md`

**Interfaces:**
- Produces: 与最终工程状态一致的文档。

- [ ] **Step 1: AGENTS.md 重写相关章节**

- Tech Stack 段：前端改为 Vue 3 + TypeScript + Vite + Pinia + vitest；后端补 Pydantic v2 + Alembic + ruff + mypy。
- "Running the App" 段：改双轨说明（dev `npm run dev` → :5173；prod `npm run build` + `python server.py` → :4173）。
- 删除"no bundler, no npm build step"表述；删除"prefer 原生 ALTER TABLE"表述，改 Alembic。
- Project Layout 更新为 `frontend/src/` 结构。
- Testing 段：`npm run verify` / `npx vitest run` / `python -m pytest tests/` / `ruff` / `mypy`。

- [ ] **Step 2: OPERATIONS.md 全面重写**

- 运行章节：dev 一键（`npm run dev`）、prod（`npm run build` + `python server.py`）、兼容（无 dist 回退）。
- 验证章节：`npm run verify` + ruff/mypy + vitest。
- 新增"工程化工具链"小节（pre-commit、CI、覆盖率门禁）。

- [ ] **Step 3: README.md 工程化总览**

- 新增：项目结构（含 src/）、双轨快速开始、工具链说明、CI 徽章占位。

- [ ] **Step 4: CHANGELOG.md 汇总 v0.4.0**

将 Phase 1-6 的所有变更合并为完整 v0.4.0 条目（工程化大类下分：工具链 / 前端迁移 / 状态管理 / 后端契约与迁移 / 测试 / CI）。

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md OPERATIONS.md README.md CHANGELOG.md
git commit -m "docs: 全栈工程化改造文档收口（双轨运行/Alembic/CI/工具链）"
```

### Task 6.4: Phase 6 收口 + git flow finish

- [ ] **Step 1: 全量验证**

Run: `npm run verify && npx vue-tsc --noEmit && npx eslint . && python -m pytest tests/ -q && python -m ruff check backend tests server.py && python -m ruff format --check backend tests server.py && python -m mypy backend`
Expected: 全绿。

- [ ] **Step 2: 双形态冒烟**

Run: `npm run dev`（:5173）与 `npm run build && python server.py`（:4173）。
Expected: 正常。

- [ ] **Step 3: git flow finish**

```bash
git flow feature finish eng-ci
git push origin develop
```

- [ ] **Step 4: 发布说明（可选）**

```bash
git flow release start v0.4.0 && git flow release finish v0.4.0
```

---

## 全工程完成后的验收清单

- [ ] `git log --oneline develop` 含 6 个 feature merge（eng-toolchain / eng-vite / eng-refactor / eng-backend / eng-test / eng-ci）。
- [ ] `npm run verify` 一条命令全绿（前端 vitest + node --check 已并入 + 后端 pytest）。
- [ ] `npx vue-tsc --noEmit` 通过（strict）。
- [ ] `npx eslint .` 通过（覆盖 js/ts/vue）。
- [ ] `python -m ruff check .` / `ruff format --check .` / `mypy backend` 通过。
- [ ] `python -m pytest tests/ -q --cov-fail-under=80` 通过。
- [ ] `npm run dev` 一键启动 :5173 HMR 正常；`npm run build && python server.py` :4173 正常。
- [ ] 后端 17 个路由全部 Pydantic 模型化，`/docs` 展示 schema，字段名与 v0.3.4 完全一致。
- [ ] Alembic baseline 迁移空库建表成功，`initialize_storage` 幂等。
- [ ] 前端 8 个 Pinia store 替代 APP_CTX，视图全部 `useXxxStore()`。
- [ ] 前端组件测试（ViewPlans / ViewScreener / ViewSettings）+ 纯逻辑模块测试全绿。
- [ ] GitHub Actions ci.yml 在远端仓库首次运行全绿。
- [ ] AGENTS.md / OPERATIONS.md / README.md / CHANGELOG.md 与工程现状一致。
