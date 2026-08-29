# MarketBar 本地日线历史读取路径设计 — 2026-08-30

## 目标

上游行情 API 失败时，走势图（`/api/history`）与网格回测/预览回退读取 PostgreSQL `market_bars` 表持久化的历史日线，实现离线可用 + 诚实披露。

## 非目标

- 不做"本地有数据就不调上游"的优先策略（上游始终优先，实时优先于本地）。
- 不改变现有 TTL/TIMEOUT 语义。
- 不涉及 MarketBar 之外的数据；走势图/回测/预览的数据源统一为此链路。

## 数据层（backend/storage.py）

- 新增 `load_market_bars(code, adjustment='qfq', limit=240) -> list[dict]`：
  - 查询 `market_bars` 表，按 `trade_date DESC` 取最近 `limit` 条，升序排序返回
  - 每条 dict 含 `date`/`open`/`high`/`low`/`close`/`volume`/`amount`（同 `load_history` 结构，无缝替换）
  - 额外含 `fetchedAt`（datetime → ISO 字符串，披露缓存时间）
  - 无数据返回空列表 `[]`

## API 层（backend/app.py）

- 抽 helper `_load_history_with_fallback(code, limit, is_index=False) -> (history, data_source, data_as_of)`：
  ```
  try:
      history = load_history(code, limit=limit, is_index=is_index)
      data_as_of = save_market_bars(code, history)  # 实时成功即写库（扩大覆盖率）
      return history, 'live', data_as_of
  except Exception:
      bars = load_market_bars(code, limit=limit)
      if not bars:
          raise
      data_as_of = bars[-1]['date']
      return bars, 'local', data_as_of
  ```
  降级链路：内存 stale → 本地库（用户选定）。内存 stale 已由 `cached()` 降级 + `X-Atlas-Stale` 头处理，此处不重复。

- 三个端点使用此 helper：
  - `/api/history`：返回加 `dataSource`（`'live'`/`'local'`）、`dataAsOf`（最新交易日）、`fetchedAt`（本地数据时间）
  - `/api/grid/preview`、`/api/grid/backtest`：响应加 `dataSource`（`'live'`/`'local'`）

## 前端（frontend/app.js）

- `fetchHistory`：读取 `payload.dataSource` → `chartDataSource` ref（`'live'`/`'local'`）
- `gridProvenance` computed：读取 `result.dataSource`，若 `'local'` 则来源显示"本地缓存"替代 `providerLabel`
- 走势图列表旁加来源标签（"实时·腾讯" / "本地缓存"）
- 回测来源行（grid-provenance）：`来源 ${result.dataSource === 'local' ? '本地缓存' : providerLabel.value}`
- dataState 保持不变（本地降级时请求成功，不触发 error/stale 状态）

## 测试（TDD）

- `load_market_bars`：插入测试数据后查询结果条数、顺序、字段完整性
- `_load_history_with_fallback`：monkeypatch `load_history` 抛异常 + `save_market_bars` 返回空 chain → 验证本地数据返回
- `_load_history_with_fallback`：无本地数据 → 抛出
- middleware 头不变（本地降级是正常请求成功，不加 X-Atlas-Stale）

## 验证

- pytest 全量（43+3 新增）；`node --check`。
- 手动：断网 + 刷新某只走势图（本地面板有回测记录）→ 走势图显示"本地缓存"；回测再跑一次 → provenance 行显示"来源 本地缓存（截至 X）"。
- 联网正常路径 → 显示"实时·腾讯"。