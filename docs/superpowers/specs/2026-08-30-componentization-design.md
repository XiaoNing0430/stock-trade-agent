# 组件化拆分 — 设计

## 目标

将当前单一大 setup + 单文件模板的架构，重构为 Vue 3 组件化架构：7 个视图（overview / screener / stock-detail / grid / plans / monitor / settings）独立为 `Vue.component` 注册的组件，模板从 index.html 迁移到 JS 模块字符串模板，共享状态通过 `provide / inject` 传递。index.html 最终瘦身为仅有骨架与布局的薄壳。

## 约束

- **无 bundler，无构建步骤**：Vue 全局构建（`vue.global.prod.js`，含运行时编译器），ES modules 浏览器加载。
- **模板字符串作为组件模板**：每个视图组件在 JS 模块中定义 `template: \`...\``，Vue 运行时编译。
- **闭包+白屏纪律**：每个视图组件的模板插值必须在对应 setup 的 return 中暴露。每步迁移后浏览器验收。
- **lucide icons**：`renderIcons()` 在组件 mounted 后调用（`onMounted`）。
- **版本号缓存**：`?v=20260830-5` 每步 bump。

## 非目标

- 不改后端、不引入 npm 依赖、不替换 `vue.global.prod.js`。
- 不改变现有功能、UI 文案、字段名、行为。
- 不一次性迁移全部 7 个视图——按子项目分步进行。

## 架构设计

### 组件树

```
App.vue（根组件，index.html 中内联）
├── app-header（标题、搜索、状态指示器）
├── nav-bar（底部导航按钮，view 切换）
├── <component :is="currentView" />  （动态当前视图）
├── stock-detail  (独立视图，非 nav 路由)
├── toast-container
├── conflict-banner
├── notification-hub
└── notif-toggle
```

### 共享状态上下文（provide）

根组件（App.setup）通过 `provide(key, value)` 提供以下共享上下文，各视图组件 `inject` 所需部分：

```js
// 共享状态键
const APP_CTX = Symbol('app.context')
provide(APP_CTX, {
  // 响应式状态
  view, selectedCode, quotes, market, watchlistCodes, plans, alerts,
  screenRows, gridResult, strategies, settingsDraft, ...,
  // 全局函数
  requestJson, showToast, addAlert, renderIcons, switchView,
  selectStock, backFromDetail, refreshAll, ensureQuote, ...,
  // 工具函数
  isWatched, toggleWatch, formatNumber, formatPct, trendClass, escapeHtml,
})
```

### 视图组件定义

每个视图组件独立文件，格式：

```js
// frontend/modules/views/settings.js
import { inject, ref, onMounted, nextTick } from 'vue';
import { APP_CTX } from './context.js';

export default {
  name: 'ViewSettings',
  template: `...`,  // 迁移自 index.html 中 settings 的 section 内容
  setup() {
    // inject 需要的共享状态
    const ctx = inject(APP_CTX);
    const { settingsDraft, settingsTab, ... } = ctx;
    // 视图私有状态
    const localState = ref(...);
    // 视图私有函数
    function save() { ... }
    onMounted(() => ctx.renderIcons());
    return { settingsDraft, settingsTab, ..., save, renderIcons: ctx.renderIcons };
    // 注意：模板中引用的所有标识符必须 return
  }
};
```

### 模板迁移规则

1. 视图的 `<section class="view-panel is-active">` 内容原样迁移到 `template: \`...\`` 中。
2. 去掉 `<section>` 外层的 `v-if` / `v-else-if`（由 `:is="currentView"` 处理）。
3. `v-if="view === 'xxx'"` 不需要了，但内部的 `v-if` 条件保留。
4. 所有 `{{ }}` 插值与指令引用的变量必须在 setup return 中。
5. `.strategy-tabs` 等仅在当前视图中的样式可保留在组件中（通过 `scoped` 模拟），但推荐保持全局样式文件。

### 组件注册

在 `app.js` 中：

```js
import ViewSettings from './modules/views/settings.js';
app.component('ViewSettings', ViewSettings);
```

### 动态视图切换

在 index.html 中：

```html
<section class="view-panel is-active" style="flex:1">
  <component :is="currentViewComponent" />
</section>
```

在 app.js 中：

```js
const currentViewComponent = computed(() => {
  const map = { overview: 'ViewOverview', screener: 'ViewScreener', grid: 'ViewGrid', ... };
  return map[view.value];
});
```

## 子项目分解

| 子项目 | 内容 | 风险 | 依赖 |
|--------|------|------|------|
| B1 | 基础设施：提供上下文键 APP_CTX、provide 骨架、`<component :is>` 切换、迁移第一个轻量视图 **settings**（最小复杂度，验证管道） | 中 | |
| B2 | 迁移 **overview** + **monitor**（中复杂度，大量共享状态） | 中 | B1 |
| B3 | 迁移 **screener** + **stock-detail**（中等复杂度，选股器状态多） | 中 | B1 |
| B4 | 迁移 **grid（策略实验室，最复杂）** + **plans**（高复杂度，大量内联函数） | 高 | B1 |
| B5 | 收尾：index.html 瘦身、清理死模板、死样式、全量回归、浏览器验收 | 低 | B1-B4 |

## 关键风险

1. **模板字符串转义**：index.html 中的 `\`、` 反引号、`${` 需要在模板字符串中正确转义。`${` 必须写为 `\${`。反引号写为 `\``。
2. **闭包引用**：setup 中未 return 的变量在模板中引用会白屏。每个组件文件需独立闭包检查。
3. **renderIcons**：lucide 图标在模板字符串中通过 `data-lucide` 属性标记，`onMounted` 调用 `renderIcons()` 解析。
4. **provide/inject 丢失**：都通过 Symbol key 注入，子组件 inject 失败会静默返回 undefined，导致白屏。需在 setup 中检查关键值。

## 测试

- `node --check frontend/modules/views/*.js`（语法检查）
- `python -m pytest tests/ -q`（后端回归）
- 每个子项目浏览器验收（对应视图可见、交互正常、其他视图零回归）

## 交付物（最终）

- `frontend/modules/views/`：7 个视图组件文件
- `frontend/modules/views/context.js`：共享上下文键与注入辅助
- `frontend/app.js`：瘦身版（provide 骨架 + 组件注册 + 只保留全局状态与跨视图函数）
- `frontend/index.html`：瘦身版（骨架 + 布局 + `<component :is>`）
- `frontend/styles.css`：清理死样式（视图专有样式移到各组件文件？不，保持全局样式文件，仅清理死类）