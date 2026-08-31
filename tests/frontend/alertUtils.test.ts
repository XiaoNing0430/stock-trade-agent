import { describe, expect, it } from 'vitest';
import { dedupeSystemAlert } from '@/modules/alertUtils';
import type { Alert } from '@/types/models';

const alert = (overrides: Partial<Alert> = {}): Alert => ({
  id: 'alert-1',
  kind: 'system',
  title: '行情数据降级',
  message: '第一次',
  read: false,
  createdAtMs: 0,
  ...overrides,
});

describe('alertUtils', () => {
  it('dedupeSystemAlert 10 分钟内同标题 system 去重并累加', () => {
    const now = 1_000_000;
    const base = [alert({ createdAtMs: now - 5 * 60 * 1000, count: 1 })];
    const result = dedupeSystemAlert(base, 'system', '行情数据降级', '再次发生', now);
    expect(result.count).toBe(2);
    expect(result.alerts).toHaveLength(1);
    expect(result.alerts[0].count).toBe(2);
    expect(result.alerts[0].message).toBe('再次发生（10 分钟内第 2 次）');
    expect(result.alerts[0].createdAtMs).toBe(now);
    expect(base[0].count).toBe(1); // 入参不修改
  });
  it('dedupeSystemAlert 超出 10 分钟不合并，追加新提醒', () => {
    const now = 1_000_000;
    const base = [alert({ createdAtMs: now - 11 * 60 * 1000 })];
    const result = dedupeSystemAlert(base, 'system', '行情数据降级', '再次发生', now);
    expect(result.count).toBe(1);
    expect(result.alerts).toHaveLength(2);
    expect(result.alerts[0].id).toMatch(/^alert-/);
    expect(result.alerts[0].message).toBe('再次发生');
    expect(result.alerts[0].read).toBe(false);
    expect(result.alerts[0].createdAtMs).toBe(now);
  });
  it('dedupeSystemAlert 恰好 10 分钟边界不合并', () => {
    const now = 1_000_000;
    const base = [alert({ createdAtMs: now - 10 * 60 * 1000 })];
    const result = dedupeSystemAlert(base, 'system', '行情数据降级', '再次发生', now);
    expect(result.count).toBe(1);
    expect(result.alerts).toHaveLength(2);
  });
  it('dedupeSystemAlert 不同标题不合并', () => {
    const now = 1_000_000;
    const base = [alert({ createdAtMs: now - 1000, title: '行情数据降级' })];
    const result = dedupeSystemAlert(base, 'system', '连接中断', '消息', now);
    expect(result.count).toBe(1);
    expect(result.alerts).toHaveLength(2);
  });
  it('dedupeSystemAlert 非 system 类型走普通追加', () => {
    const now = 1_000_000;
    const base = [alert({ kind: 'info', title: '标题A', createdAtMs: now - 1000 })];
    const result = dedupeSystemAlert(base, 'info', '标题A', '消息', now);
    expect(result.count).toBe(1);
    expect(result.alerts).toHaveLength(2);
    expect(result.alerts[0].kind).toBe('info');
  });
  it('dedupeSystemAlert 超过 24 条裁剪保留最新 24 条', () => {
    const now = 1_000_000;
    const base = Array.from({ length: 24 }, (_, i) => alert({ id: `alert-${i}`, title: `标题${i}` }));
    const result = dedupeSystemAlert(base, 'system', '新标题', '消息', now);
    expect(result.alerts).toHaveLength(24);
    expect(result.alerts[0].title).toBe('新标题');
  });
  it('dedupeSystemAlert 纯函数不修改入参数组', () => {
    const now = 1_000_000;
    const base = [alert({ kind: 'system', title: '标题A', createdAtMs: now - 1000 })];
    const before = JSON.stringify(base);
    dedupeSystemAlert(base, 'system', '标题A', '消息', now);
    expect(JSON.stringify(base)).toBe(before);
  });
});
