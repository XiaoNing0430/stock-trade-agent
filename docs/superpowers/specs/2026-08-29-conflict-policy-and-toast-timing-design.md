# 冲突处理策略与 toast 计时修复设计

## 背景

P0 乐观锁上线后的用户反馈两点：其一，双标签页冲突时每次都要手动点横幅，希望默认自动采用服务器版本、可通过配置切换；其二，冲突流程连发两条 toast 时提示停留远超 3.2 秒。

## 根因

`showToast` 中所有 toast 共享一个 `lastToastTimer`：新 toast 会清除上一条的移除定时器并重设，导致冲突流程（错误提示 → 成功提示连发）中第一条 toast 实际停留约 6.4 秒。这是计时 bug，而非单条时长设置问题。

## 目标

1. 新增工作区设置 `conflictPolicy`，冲突（409）时按策略自动处理，默认无需人工干预。
2. 修复 toast 逐条独立计时，消除连发时的超长停留。

## 非目标

- 不改 409 API 契约（`baseRevision`/`force`/`detail.workspace` 不变）。
- 不改单条 toast 的 3.2 秒时长（如需调整属后续调参）。
- 不做 toast 关闭按钮或队列 UI。

## 设计

### 冲突处理策略（`conflictPolicy`）

- 取值：`server`（默认）｜`local`｜`ask`。
- `server`：收到 409 → 自动套用服务器快照、更新本地 `revision`、toast "检测到其他页面更新，已自动采用服务器版本"。横幅不出现。
- `local`：收到 409 → 自动带 `force=true` 重发本地快照、更新 `revision`、toast "检测到冲突，已自动用本地版本覆盖服务器"。横幅不出现。此档会覆盖另一页面刚保存的数据，由用户显式配置承担。
- `ask`：保持现有横幅与"采用服务器版本"/"用本地覆盖"两动作。
- 配置入口：系统设置页新增"冲突处理策略"下拉行（三个选项），存于服务端 workspace settings，两个标签页读到同一策略。
- 后端：`DEFAULT_WORKSPACE_SETTINGS` 增加 `"conflictPolicy": "server"`；`_normalize_workspace_settings` 白名单校验，非法值回退 `server`。
- 兜底：409 响应异常缺失 `detail.workspace` 时，`server`/`local` 策略静默降级为 `ask` 行为；任何策略下都不自动重试写入。

### toast 计时修复

- 移除共享 `lastToastTimer`，每条 toast 持有自己的移除定时器；活跃定时器收集进 `Set`，应用卸载时统一 `clearTimeout`。
- 单条 3.2 秒时长不变。

## 数据与接口变化

- `GET/PUT /api/settings` 的 `data` 新增 `conflictPolicy` 字段（纯新增）。
- 其余 API 无变化。

## 验证

- pytest：`DEFAULT_WORKSPACE_SETTINGS["conflictPolicy"] == "server"`；归一化接受 `local`/`ask`、非法值与缺省回退 `server`；既有 37 项回归。
- `node --check frontend/app.js`。
- 浏览器：三种策略下双标签页冲突各验证一次；连发 toast（加入自选后立即再触发一条）观察各自 3.2 秒消失。

## Git 流程

`git flow feature start conflict-policy-toast-fix` → 按逻辑分提交（策略后端+测试；前端策略分派；toast 修复）→ `git flow feature finish`。
