# 行情缓存 TTL 下限与外部接口限频 — 设计

## 目标

- 防止 `cacheSeconds` 设为 0 时每次轮询直打上游行情接口。
- 为外部 HTTP 请求增加统一节流，避免个股详情页并发拉取、选股器翻页等场景突发请求。
- 全市场选股器（Screener v2）接入缓存，减少重复请求。

## 非目标

- 不改前端设置 UI（`cacheSeconds` 最小值仍显示 0，后端 floor 透明生效）。
- 不引入外部依赖（`time.sleep` + `threading.Lock` 即可）。
- 不改变缓存新鲜窗口、降级兜底、stale header 语义。

## 1. TTL 硬下限

`backend/data_source.py` 的 `apply_runtime_config`：

```python
if cache_seconds is not None:
    _cache_ttl = max(2, int(cache_seconds))  # 硬下限 2 秒
```

`backend/storage.py` 的 `_normalize_workspace_settings` 同步：

```python
data["cacheSeconds"] = max(2, min(int(data["cacheSeconds"]), 300))
```

## 2. 外部接口限频（token bucket）

`backend/data_source.py` 新增模块级限频状态与助手：

```python
RATE_LIMIT_RPS = 5               # 默认每秒请求上限
_min_request_interval: float = 1.0 / RATE_LIMIT_RPS
_last_request_at: float = 0.0
rate_lock = threading.Lock()

def _throttle() -> None:
    """阻塞直到满足最小请求间隔（全局节流）。"""
    global _last_request_at
    while True:
        with rate_lock:
            now = time.time()
            wait = _last_request_at + _min_request_interval - now
            if wait <= 0:
                _last_request_at = now
                return
        time.sleep(wait)
```

- 在 `_http_get` 入口处调用 `_throttle()`（所有外部请求统一经过 `_http_get`）。
- `apply_runtime_config` 可选参数 `rate_limit_rps`（默认 5，下限 1），更新 `_min_request_interval`。

## 3. Screener v2 接入缓存

`backend/data_source.py` 的 `load_screener_v2`：

```python
def load_screener_v2(page=1, page_size=50, sort_by="changePct", sort_dir="desc"):
    key = f"screener_v2:{sort_by}:{sort_dir}:{page}"
    return cached(key, lambda: _fetch_screener_v2(page, page_size, sort_by, sort_dir))
```

`_fetch_screener_v2` 为原请求逻辑（`requests.get` → 归一化 → 返回 payload）。复用 `cached()` 的 TTL / 降级兜底。

## 4. 配置接线

`backend/app.py` lifespan 与 `update_settings` 中的 `apply_runtime_config(...)` 调用补 `rate_limit_rps=applied.get("rateLimitRps")`（默认 None → 不覆盖默认 5）。不新增工作区设置字段，前端无感知。

## 测试（tests/test_backend_api.py 或 test_data_source 相关）

- `apply_runtime_config(cache_seconds=0)` 后 `_cache_ttl >= 2`。
- `apply_runtime_config(rate_limit_rps=20)` 后 `_min_request_interval == 0.05`。
- `load_screener_v2` 同参数第二次调用命中缓存（用 monkeypatch 计数 `_http_get` 调用次数）。

## 验证命令

```powershell
python -m pytest tests/ -q   # 全量回归（72 + 新增）
```

## 交付物

- `backend/data_source.py`：TTL 下限、限频器、Screener v2 缓存
- `backend/storage.py`：cacheSeconds 下限 2
- `backend/app.py`：`apply_runtime_config` 补 `rate_limit_rps`
- `tests/`：新增断言