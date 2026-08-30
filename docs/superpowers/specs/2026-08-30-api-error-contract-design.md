# 统一 API 错误契约 — 设计

## 目标

为后端所有 `HTTPException` 补充结构化错误码 `detail.code`，使前端可按错误码编程分支，而非匹配中文文案；保持现有字段名（`error` / `revision` / `workspace` / `provider`）完全不变。

## 非目标

- 不引入 requestId / traceId（本地单用户应用无必要）。
- 不重命名任何现有字段、不改 UI 文案、不重写前端错误处理框架。
- 不改变任何 HTTP 状态码语义。

## 后端设计（backend/app.py）

新增错误码常量与统一助手：

```python
# 结构化错误码（P3-3 统一错误契约）
ERR_STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"   # 503 持久化不可用
ERR_WORKSPACE_CONFLICT  = "WORKSPACE_CONFLICT"    # 409 工作区版本冲突
ERR_UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE" # 502 行情/排名上游失败
ERR_VALIDATION_ERROR    = "VALIDATION_ERROR"      # 422 参数/设置/策略类型
ERR_NOT_FOUND           = "NOT_FOUND"             # 404 资源不存在

def api_error(status_code: int, code: str, message: str, **extras) -> HTTPException:
    """统一错误构造：detail = {"error": message, "code": code, **extras}。"""
    return HTTPException(status_code=status_code, detail={"error": message, "code": code, **extras})
```

逐处替换（约 30 处 raise 站点，保持状态码与文案一致）：

| 现状 | 替换 |
|------|------|
| `HTTPException(503, detail={"error": f"持久化存储不可用: {exc}"})` | `api_error(503, ERR_STORAGE_UNAVAILABLE, f"持久化存储不可用: {exc}")` |
| `HTTPException(409, detail={"error": ..., "revision": ..., "workspace": ...})` | `api_error(409, ERR_WORKSPACE_CONFLICT, ..., revision=..., workspace=...)` |
| `HTTPException(502, detail={"error": str(exc), "provider": ...})` | `api_error(502, ERR_UPSTREAM_UNAVAILABLE, str(exc), provider=...)` |
| `HTTPException(422, detail={"error": ...})` | `api_error(422, ERR_VALIDATION_ERROR, ...)` |
| `HTTPException(404, detail={"error": "策略不存在"})` | `api_error(404, ERR_NOT_FOUND, "策略不存在")` |

`except HTTPException: raise` 原样保留（不吞错、不改写）。

## 前端设计（frontend/app.js）

`requestJson` 错误对象补 code 字段（`error.message` 中文文案不变）：

```js
const error = new Error(payload.detail?.error || payload.error || `接口返回 ${response.status}`);
error.status = response.status;
error.code = payload.detail?.code || payload.code || 'UNKNOWN';
error.payload = payload;
throw error;
```

409 工作区冲突分支：现以 `error.status === 409` 判断，保持不变（错误码为新增信息，不破坏现有逻辑）。

## 测试（tests/test_backend_api.py）

新增/扩展断言 `detail.code`：

- 409 工作区冲突 → `detail.code == "WORKSPACE_CONFLICT"`（现有测试 `test_workspace_put_rejects_stale_revision_with_409` 追加断言）
- 422 未知策略类型 → `detail.code == "VALIDATION_ERROR"`
- 404 策略不存在 → `detail.code == "NOT_FOUND"`
- 502 上游失败 → `detail.code == "UPSTREAM_UNAVAILABLE"`
- 503 持久化不可用 → `detail.code == "STORAGE_UNAVAILABLE"`

## 验证命令

```powershell
python -m pytest tests/ -q   # 全量回归（68 + 新增断言）
node --check frontend/app.js # 前端语法
```

## 交付物

- `backend/app.py`：错误码常量 + `api_error` 助手 + 逐处替换
- `frontend/app.js`：`requestJson` 补 `error.code`
- `tests/test_backend_api.py`：错误码断言