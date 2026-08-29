# 行情降级缓存兜底（stale-on-error cache fallback）设计 — 2026-08-29

## 目标

上游行情接口失败时，`cached()` 回退使用服务器内存缓存中**上一次成功获取的真实数据**（而非直接报错），并通过响应头向前端诚实披露陈旧程度；前端以 `dataState=stale` 披露并入收件箱。

## 非目标

- 不做跨进程持久化缓存（服务器重启即失；归 P3）。
- 不改变现有 TTL 语义（新鲜窗口仍由 `cacheSeconds` 设置驱动）。
- 不伪造任何数据——降级返回的永远是真实获取过的历史数据，且必须披露。

## 数据层（backend/data_source.py）

- 新常量 `STALE_MAX_AGE = 1800`（30 分钟硬顶，用户选定）。
- `cached(key, loader)`：TTL 过期时尝试 `loader()`；**异常时**若缓存存在且 `now - fetch_time <= STALE_MAX_AGE` → 返回旧值并记录降级标记；否则原样抛出。无缓存时原样抛出。
- 降级标记：模块级 `stale_marker = {"at": 0.0, "age": 0.0}`（锁保护）；`mark_stale(age)` 记录；`recent_stale(window=2.0) -> dict | None` 供 API 层查询 2 秒窗口内的降级（全局近似窗口，多 key 并发下宁多标不漏标）。

## API 层（backend/app.py）

- HTTP middleware（仅 `/api/` 路径）：响应前查 `recent_stale(2.0)`，命中则加响应头 `X-Atlas-Stale: <数据年龄秒>`（整数）。零响应体结构变更。

## 前端（frontend/app.js）

- `requestJson`：读取 `x-atlas-stale` 响应头 → `serverStaleAge` ref（秒）；正常响应无头即清除。
- `refreshAll` dataState 计算：现有 failures 判定之外并入 `serverStaleAge`——本轮任一响应带头 → `dataState='stale'`，`errorMessage='行情源暂时不可用，展示服务器缓存的真实行情（约 X 分钟前）'`；头消失且无失败 → 恢复 `live`（现有状态机不变）。
- 收件箱联动：`lastRecordedDataState` 状态机自动记录降级/恢复系统事件（通知中心已建，零新增）。

## 测试（TDD）

- `cached`：缓存存在且 ≤30min + loader 抛异常 → 返回旧值并置标记；>30min → 重新抛出；无缓存 → 抛出。
- `recent_stale`：窗口内/外行为。
- middleware：降级后 `/api/*` 响应含 `X-Atlas-Stale` 头（TestClient + monkeypatch）。

## 验证

- pytest 全量（40+ 新增）；`node --check`。
- 手动：DevTools Offline 触发上游失败 → 页面「缓存行情」+ 收件箱系统事件（约 X 分钟前）；恢复联网 → 「真实行情」+ 恢复事件。
