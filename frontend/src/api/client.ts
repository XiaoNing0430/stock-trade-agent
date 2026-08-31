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
    const error = new Error(
      detail && typeof detail === 'object' && 'error' in detail
        ? String((detail as { error: unknown }).error)
        : `HTTP ${res.status}`
    ) as Error & { code?: string; status: number; detail?: unknown };
    error.status = res.status;
    error.detail = detail;
    if (detail && typeof detail === 'object' && 'code' in detail)
      error.code = String((detail as { code: unknown }).code);
    throw error;
  }
  return res.json() as Promise<T>;
}
