# 设置页 Tushare Token 与跨源校验开关

日期：2026-10-03 ｜ 状态：用户确认，进入实现

## 冻结决策

- workspace settings 新增两键，走现有 `/api/settings` PUT 的 exclude_unset 白名单合并（缺省=不修改）：
  - `tushareToken`：DB 存储；GET 不回显明文（data 中恒为 `""`），`""` 表示清除；配置状态与尾 4 位掩码经 sources.tushare 行下发（`tushareConfigured`=DB 或 env 任一配置，新增 `tushareTokenMasked`）。
  - `crossCheckEnabled`：三态 `None`/`true`/`false`；`None`（默认）=跟随环境 `CROSS_CHECK_ENABLED`，DB 显式值优先。
- 跨源校验 job 常驻注册，`cross_check.run()` 运行时解析有效开关（DB 显式值 > env > 关）：页面开关即时生效、无需重启；disabled 时早退并向 `health.bars.crossCheck` 上报 `status: "disabled"`。
- `cross_check` 取 token 解析链：workspace settings → env `TUSHARE_TOKEN` → 空（空则 Tushare 面禁用，照旧东财辅源/降级）。cross_check 无请求上下文，读 default 工作区设置。
- 页面警告：Tushare 单位对拍（T0）未完成前启用可能出现对账偏差告警——只告警不改数。
- 纪律修订记录：P2.5 spec 原"校准完成前默认关（env 门）"由用户裁定放宽为页面开关（2026-10-03）；"不自动改数、不阻断 ETL"红线不变。

## 实现范围

storage 默认值与白名单两键；schemas 设置模型；app.py GET 掩码与 sources 掩码下发、PUT 透传；cross_check 有效开关/token 解析与 disabled 上报、bars_etl.register_jobs 常驻注册；前端 useSettingsStore 两字段、ViewSettings 连接标签 Tushare 行（password 输入 + 启用下拉 + 警告文案）。

## 验收

token PUT/GET 掩码与清除 round-trip；token 解析优先级（DB>env>空）；三态开关解析矩阵；常驻注册与 disabled 早退；前端 Tushare 行渲染与保存携带。既有"关→3 job"用例按新语义调整（理由入 commit message）。
