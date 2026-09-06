import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import type { Plan } from '@/types/models';

const basePlan: Plan = {
  id: 'plan-600519-1',
  code: '600519',
  direction: 'buy',
  entry: 10,
  stop: 9,
  target: 12,
  capital: 100000,
  position: 10,
  validity: '本周内',
  note: '',
  status: '执行中',
  triggered: {},
  createdAtMs: Date.now(),
};

/** requestJson 内部调用 fetch；store 内部闭包调用无法用 store 属性 spy 拦截，需在 fetch 层打桩。 */
function jsonResponse(payload: unknown, ok = true, status = 200) {
  return { ok, status, headers: { get: () => null }, json: async () => payload };
}

describe('useWorkspaceStore syncNow', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('立即 PUT 工作区（带 baseRevision）并在成功时返回 { ok: true }', async () => {
    const workspace = useWorkspaceStore();
    workspace.workspaceSynced = true;
    workspace.plans = [basePlan];
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ revision: 3 }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await workspace.syncNow();
    expect(result).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toContain('/api/workspace?baseRevision=');
    expect((options as RequestInit).method).toBe('PUT');
    const body = JSON.parse(String((options as RequestInit).body));
    expect(body.plans).toHaveLength(1);
    expect(body.plans[0].code).toBe('600519');
  });

  it('409 返回 { ok:false, conflict:true } 且绝不自动重试', async () => {
    const workspace = useWorkspaceStore();
    workspace.workspaceSynced = true;
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ detail: { error: '冲突' } }, false, 409));
    vi.stubGlobal('fetch', fetchMock);
    const result = await workspace.syncNow();
    expect(result).toEqual({ ok: false, conflict: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('非 409 失败返回 { ok:false }', async () => {
    const workspace = useWorkspaceStore();
    workspace.workspaceSynced = true;
    vi.stubGlobal('fetch', vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ detail: { error: '服务不可用' } }, false, 503)));
    const result = await workspace.syncNow();
    expect(result).toEqual({ ok: false });
  });

  it('workspaceSynced=false 时直接返回 { ok:true }（未初始化不发 PUT）', async () => {
    const workspace = useWorkspaceStore();
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ revision: 1 }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await workspace.syncNow();
    expect(result).toEqual({ ok: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
