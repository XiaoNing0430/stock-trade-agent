# P3 数据能力：分层 Point-in-time 日快照

日期：2026-09-18 ｜ 状态：用户确认，进入实现

## 冻结决策

- 系统首次成功归档日之后每日生成严格 PIT `exact` 行业快照；历史缺口默认不伪造，显式回填生成 `inferred`。
- `asOfDate` 是“历史今天”，同时约束行情、行业、窗口、计划可见性和有效期。
- 行情严格不跨日回退；`volume <= 0` 判定停牌，缺失按 complete/degraded/no-run 三类披露。
- 行业最多回溯 20 个交易日，`pit_quality` 优先于距离；`inferred` 永远是 `historical_fallback`。
- 回填内容按 `(code,name,provider,acquisition)` 集合计算 canonical SHA-256，内容变化写新审计。

## 实现范围

新增快照运行、原始收盘、行业快照及审计表；新增统一 `snapshot_query.py`；ETL 完成后幂等归档；复盘和组合风险接入可选 `asOfDate`；新增行业回填接口。`rebuild` 模式首版返回 501，不写审计。

## 验收

覆盖状态映射、停牌无前收、三类缺失、审计截断/哈希、窗口语义、计划创建日过滤、迁移、ETL 失败重试和 API 回归测试。数据库不可达时明确标记环境限制，不宣称全量通过。
