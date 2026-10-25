// 自 app.js 的 requestJson 迁移，返回类型泛型化；行为等价
// 错误契约（AGENTS.md）：后端一律 {"detail": {"error": 中文, "code": 机器码}}。
// 2026-10-25 修复：早期实现只在 body 顶层找 error，导致所有 422 都退化成 "HTTP 422"，
// 中文规则提示传不到界面；现优先解包 detail，并兼容旧式顶层 {error, code}。
export async function requestJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* 非 JSON 错误体 */
    }
    const nested =
      body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : undefined;
    const detail = nested && typeof nested === 'object' ? nested : body;
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

export type MinuteResponse = {
  bars: any[];
  source: string | null;
  state: string;
  degraded: boolean;
  updatedAtMs?: number | null;
};

export function fetchMinute(code: string, period: string, count = 320) {
  return requestJson<MinuteResponse>(
    `/api/minute?code=${encodeURIComponent(code)}&period=${encodeURIComponent(period)}&count=${count}`
  );
}
