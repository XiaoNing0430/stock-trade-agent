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

  it('409 返回 { ok:false, conflict:true }（不透传 message，策略处理在调用方）且绝不自动重试', async () => {
    const workspace = useWorkspaceStore();
    workspace.workspaceSynced = true;
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
      jsonResponse({ detail: { error: '冲突' } }, false, 409)
    );
    vi.stubGlobal('fetch', fetchMock);
    const result = await workspace.syncNow();
    expect(result).toEqual({ ok: false, conflict: true });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('非 409 失败返回 { ok:false, message }（Task 9：透传后端中文 detail 供调用方 toast）', async () => {
    const workspace = useWorkspaceStore();
    workspace.workspaceSynced = true;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
        jsonResponse({ detail: { error: '服务不可用' } }, false, 503)
      )
    );
    const result = await workspace.syncNow();
    expect(result).toEqual({ ok: false, message: '服务不可用' });
  });

  it('workspaceSynced=false 时直接返回 { ok:true }（未初始化不发 PUT）', async () => {
    const workspace = useWorkspaceStore();
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ revision: 1 }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await workspace.syncNow();
    expect(result).toEqual({ ok: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('定时同步回调触发时复查同步锁：syncNow 持锁期间不重复 PUT', async () => {
    vi.useFakeTimers();
    try {
      const workspace = useWorkspaceStore();
      workspace.workspaceSynced = true;
      let releaseFirst!: () => void;
      const firstGate = new Promise<void>((resolve) => {
        releaseFirst = resolve;
      });
      let call = 0;
      const fetchMock = vi.fn((_url: RequestInfo | URL, _init?: RequestInit) => {
        call += 1;
        // 第 1 个 PUT（syncNow 持锁挂起）永不返回；第 2 个（若回归为双 PUT）正常返回
        return call === 1
          ? firstGate.then(() => jsonResponse({ revision: 2 }))
          : Promise.resolve(jsonResponse({ revision: 3 }));
      });
      vi.stubGlobal('fetch', fetchMock);
      // 先布防 350ms 定时同步，再让 syncNow 同步段持锁挂起 → 定时回调到期时锁仍被持有
      workspace.scheduleWorkspaceSync();
      const pending = workspace.syncNow();
      await vi.advanceTimersByTimeAsync(400);
      expect(fetchMock).toHaveBeenCalledTimes(1); // 回调复查锁跳过，无第二次 PUT
      releaseFirst();
      await expect(pending).resolves.toEqual({ ok: true });
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });

  it('syncNow 等待上限 3s：锁始终被持有时返回 { ok:false, message }（不可让 UI 假死；收尾硬化 L2 补文案）', async () => {
    // shouldAdvanceTime 让 3s 等待循环按真实时间推进 → 本用例本身约 3s，默认 5s 超时过窄（曾 flake 一次）；
    // 显式放宽而不是改生产逻辑（③a 遗留：时序脆弱项）。
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const workspace = useWorkspaceStore();
      workspace.workspaceSynced = true;
      // 从不 resolve 的 fetch → 定时同步进入 PUT 后锁永不释放
      vi.stubGlobal(
        'fetch',
        vi.fn((_url: RequestInfo | URL, _init?: RequestInit) => new Promise(() => {}))
      );
      workspace.scheduleWorkspaceSync();
      await vi.advanceTimersByTimeAsync(360); // 350ms 防抖到期 → 定时同步持有锁
      expect(workspace.workspaceSyncTimer).toBeTruthy();
      const result = await workspace.syncNow(); // 3s 等待循环在假计时器下瞬时推进
      expect(result).toEqual({ ok: false, message: '同步超时（定时同步长时间占用），请稍后重试' });
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  }, 15000);
});

/** 后端每次保存都 +1（storage._bump_workspace_revision）；本地基线不跟进的话，
 *  下一次 PUT 必带落后的 baseRevision → 立刻 409 → 默认 server 策略又会用服务器快照
 *  覆盖本地（丢未保存改动）。既有缺陷 F1。 */
describe('useWorkspaceStore 修订号跟进（F1）', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('syncNow 成功 PUT 后采用响应里的新 revision', async () => {
    const workspace = useWorkspaceStore();
    workspace.workspaceSynced = true;
    workspace.workspaceRevision = 5;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ revision: 6 }))
    );
    await workspace.syncNow();
    expect(workspace.workspaceRevision).toBe(6);
  });

  it('定时同步成功后基线跟进：第二次 PUT 携带服务器返回的新 baseRevision', async () => {
    vi.useFakeTimers();
    try {
      const workspace = useWorkspaceStore();
      workspace.workspaceSynced = true;
      workspace.workspaceRevision = 5;
      let call = 0;
      const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => {
        call += 1;
        return jsonResponse({ revision: 5 + call });
      });
      vi.stubGlobal('fetch', fetchMock);
      workspace.scheduleWorkspaceSync();
      await vi.advanceTimersByTimeAsync(400);
      expect(String(fetchMock.mock.calls[0][0])).toContain('baseRevision=5');
      workspace.scheduleWorkspaceSync();
      await vi.advanceTimersByTimeAsync(400);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(String(fetchMock.mock.calls[1][0])).toContain('baseRevision=6');
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });

  it('响应缺 revision 时不把基线清零（防御异常响应体）', async () => {
    const workspace = useWorkspaceStore();
    workspace.workspaceSynced = true;
    workspace.workspaceRevision = 9;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({}))
    );
    await workspace.syncNow();
    expect(workspace.workspaceRevision).toBe(9);
  });
});
