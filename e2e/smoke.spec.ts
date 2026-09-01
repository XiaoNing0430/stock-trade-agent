import { test, expect } from '@playwright/test';

test.describe('应用冒烟测试', () => {
  test('首页加载成功', async ({ page }) => {
    await page.goto('/');
    // 等待 Vue 应用挂载
    await page.waitForSelector('.app-shell', { timeout: 10000 });
    await expect(page.locator('.brand')).toContainText('Atlas');
  });

  test('导航菜单存在且可点击', async ({ page }) => {
    await page.goto('/');
    await page.waitForSelector('.app-shell', { timeout: 10000 });
    const nav = page.locator('.primary-nav');
    await expect(nav).toBeVisible();
    // 至少包含 4 个导航项（总览/选股/网格/设置）
    const items = nav.locator('button');
    await expect(items.first()).toBeVisible();
    expect(await items.count()).toBeGreaterThanOrEqual(4);
  });

  test('API 健康检查端点正常', async ({ request }) => {
    const resp = await request.get('/api/health');
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body.ok).toBe(true);
  });
});
