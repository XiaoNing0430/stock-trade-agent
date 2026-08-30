# 网站设置布局优化设计（方案 A：分层收拢）

日期：2026-08-30
状态：已确认
分支：feature/componentization-b1（P3-1 B1 子项目内）

## 背景

B1 组件化后，个人中心（ViewSettings 组件）的「网站设置」子视图存在布局问题：

- **双标题堆叠**：外层 `PERSONAL HUB 个人中心` 与内层 `WORKSPACE SETTINGS 网站设置` 重复。
- **双 tab 栏同一样式**：外层（提醒中心|网站设置）与内层（工作区|数据|连接）视觉无区分，层级混淆。
- **设置行留白大**：`settings-row` 为 `flex space-between`，1116px 宽时标签与控件之间留白巨大，行高 77px 偏松。
- **控件未对齐**：input/select/toggle 高度与右缘不统一。
- **页面微抛光不足**：缺少 hover 态、分隔线，toggle 尺寸与盯盘页不一致。

## 目标

在不动后端、不动提醒中心（alerts）的前提下，优化网站设置子视图的布局与视觉效果，拉开双层 tab 层级，实现控件对齐与页面抛光。

## 具体改动

### 1. 标题层去重（ViewSettings.js 模板）

- 移除设置内部的大标题块（`WORKSPACE SETTINGS 网站设置` + heading-note）。
- 页面仅保留顶部 `PERSONAL HUB 个人中心` 一个标题。
- 「保存设置」按钮移入内层 tab 行右侧，右对齐。

### 2. 双层 tab 视觉区分（ViewSettings.js 模板 + styles.css）

- 外层 tab（提醒中心|网站设置）→ `settings-tabs-primary`：分段胶囊容器（背景底 + 圆角），激活项主题色文字/浅底。
- 内层 tab（工作区|数据|连接）→ `settings-tabs-sub`：下划线式（底部细线，激活项主题色下划线）。
- 内层 tab 行与保存按钮同排（`settings-subbar`：flex space-between 布局）。

### 3. 设置行两栏对齐（styles.css）

- `.settings-row` 改为 `grid-template-columns: minmax(0, 1fr) auto`；左栏标签+描述，右栏控件。
- 控件（input/select/toggle/number-input）统一高度 36px、右缘对齐。
- 行高收紧：padding `18px 20px` → `14px 20px`。

### 4. 页面微抛光（styles.css）

- `.settings-row:hover` 背景微亮 + 边框色加深。
- 设置行底部 1px 半透明分隔线（替代大间距留白）。
- toggle 尺寸统一：轨道 40×22、圆点 16px。
- 控件统一高度 36px。

## 范围

- 只改 `frontend/modules/views/ViewSettings.js`（模板结构）+ `frontend/styles.css`（新增/调整样式）。
- 提醒中心（alerts）布局不动。
- 后端零改动。
- `?v=` bump styles.css（ViewSettings.js 为模块内嵌模板，随 app.js 版本链加载）。

## 验收

1. 网站设置子视图只有一个标题「个人中心」。
2. 外层胶囊 tab / 内层下划线 tab 层级清晰，切换正常。
3. 「保存设置」按钮位于内层 tab 行右侧，悬停/点击正常。
4. 设置行标签左对齐、控件右对齐且高度统一（36px），行内 hover 有反馈。
5. toggle 尺寸与盯盘页一致。
6. 提醒中心（alerts）布局与交互无回归。
7. `node --check` 通过；浏览器 CDP 冒烟验证布局几何（行高 ~64px、控件右缘对齐）。

## 非目标

- 不改提醒中心布局。
- 不改后端。
- 不做响应式重构（仅保持现状不恶化）。
