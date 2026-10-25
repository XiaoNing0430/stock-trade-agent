import { describe, expect, it, vi, afterEach } from 'vitest';
import { requestJson } from '@/api/client';

function response(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('requestJson', () => {
  it('returns parsed json on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(response({ items: [1] })))
    );
    await expect(requestJson<{ items: number[] }>('/api/x')).resolves.toEqual({ items: [1] });
  });

  it('unwraps nested detail to chinese message and machine code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          response(
            { detail: { error: '沪深主板买入须满足：最小 100 股，且为 100 股整数倍', code: 'QTY_NOT_LOT' } },
            422
          )
        )
      )
    );
    await expect(requestJson('/api/fills', { method: 'POST' })).rejects.toMatchObject({
      message: '沪深主板买入须满足：最小 100 股，且为 100 股整数倍',
      code: 'QTY_NOT_LOT',
      status: 422,
    });
  });

  it('keeps legacy top-level error shape working', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(response({ error: '旧式错误', code: 'LEGACY' }, 409)))
    );
    await expect(requestJson('/api/x')).rejects.toMatchObject({ message: '旧式错误', code: 'LEGACY', status: 409 });
  });

  it('falls back to HTTP status when body is not json', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 502,
          json: async () => {
            throw new Error('not json');
          },
        } as unknown as Response)
      )
    );
    await expect(requestJson('/api/x')).rejects.toMatchObject({ message: 'HTTP 502', status: 502 });
  });
});
