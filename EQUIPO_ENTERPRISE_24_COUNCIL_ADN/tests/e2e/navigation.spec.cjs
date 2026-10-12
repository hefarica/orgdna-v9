'use strict';
const { test, expect, PAGES, acceptNextDialog } = require('./fixtures.cjs');
const matrix = require('./control-matrix.json');

for (const section of PAGES) {
  test(`navigation: ${section} page and static control inventory`, async ({ app }) => {
    const { page } = app;
    await app.navigate(section);
    await expect(page.locator(`#${section} h1`)).toBeVisible();
    await expect(page.locator(`nav a[data-page="${section}"]`)).toHaveAttribute('aria-current', 'page');
    for (const row of matrix.controls.filter(row => row.page === section && row.source === 'html')) {
      await expect(page.locator(row.locator).nth(row.nth || 0), row.feature).toBeAttached();
    }
    await page.reload();
    await expect(page.locator('#' + section)).toBeVisible();
  });
}
for (const width of [390, 768, 1440]) {
  for (const section of PAGES) {
    test(`responsive: ${section} at ${width}px`, async ({ app }, testInfo) => {
      const { page } = app;
      await page.setViewportSize({ width, height: 900 });
      await app.navigate(section);
      await expect(page.locator(`#${section} h1`)).toBeInViewport();
      const metrics = await page.evaluate(() => ({ client: document.documentElement.clientWidth,
        scroll: document.documentElement.scrollWidth }));
      expect(metrics.scroll, 'Document must not overflow horizontally; graph/table may scroll internally').toBeLessThanOrEqual(metrics.client + 2);
      await page.screenshot({ path: testInfo.outputPath(`${section}-${width}.png`), fullPage: true });
    });
  }
}

test('navigation: aliases and browser history preserve the active page', async ({ app }) => {
  await app.navigate('perfiles');
  await app.navigate('council');
  await app.page.goBack();
  await expect(app.page.locator('#perfiles')).toBeVisible();
  await app.page.goForward();
  await expect(app.page.locator('#council')).toBeVisible();
  await app.page.goto(app.origin + '/#design-recovery');
  await expect(app.page.locator('#inicio')).toBeVisible();
  await app.page.goto(app.origin + '/#dsh-connection');
  await expect(app.page.locator('#exportaciones')).toBeVisible();
});

test('a11y: Spanish document, labelled visible controls and keyboard profile dialog', async ({ app }) => {
  const { page } = app;
  await expect(page.locator('html')).toHaveAttribute('lang', 'es');
  await expect(page.locator('#notice')).toHaveAttribute('aria-live', 'polite');
  await app.navigate('organigrama');
  const first = page.locator('#org-tree [role="button"]').first();
  await first.focus(); await page.keyboard.press('Enter');
  await expect(page.locator('#profile-dialog')).toBeVisible();
  await expect(page.locator('#agent-name')).toHaveAccessibleName('Nombre ficticio');
  await page.keyboard.press('Escape');
  await expect(page.locator('#profile-dialog')).toBeHidden();
  await expect(first).toBeFocused();
});

test('a11y: capabilities tabs use arrow, home, end and selected state', async ({ app }) => {
  const { page } = app;
  await app.navigate('habilidades');
  const first = page.locator('[data-cap-tab="search"]');
  await first.focus(); await page.keyboard.press('ArrowRight');
  await expect(page.locator('[data-cap-tab="suggested"]')).toHaveAttribute('aria-selected', 'true');
  await page.keyboard.press('End');
  await expect(page.locator('[data-cap-tab="evidence"]')).toHaveAttribute('aria-selected', 'true');
  await page.keyboard.press('Home');
  await expect(first).toHaveAttribute('aria-selected', 'true');
});

test('organigrama: zoom, filter, inspector cancel and hierarchy restore', async ({ app }) => {
  const { page } = app;
  await app.navigate('organigrama');
  const before = await page.locator('#zoom-label').textContent();
  await page.locator('#zoom-in').click();
  await expect(page.locator('#zoom-label')).not.toHaveText(before);
  await page.locator('#zoom-out').click();
  await page.locator('#zoom-fit').click();
  await page.locator('#org-search').fill('ZZZ nonexistent profile');
  await expect(page.locator('.graph-node.dimmed')).toHaveCount(4);
  await page.locator('#org-search').fill('');
  await expect(page.locator('.graph-node.dimmed')).toHaveCount(0);
  await page.locator('.graph-node').first().click();
  await page.locator('#cancel-inspector').click();
  await expect(page.locator('#profile-dialog')).toBeHidden();
  await acceptNextDialog(page, () => page.locator('#hierarchy-reset').click());
  expect((await app.state()).organization.agents).toHaveLength(4);
});
