'use strict';
const { test, expect, SENTINEL, prepare, approve, waitJob, acceptNextDialog } = require('./fixtures.cjs');

test('generation: exact plan needs one fresh approval and publishes exactly N profiles', async ({ app }) => {
  await prepare(app);
  const before = await app.state();
  expect(before.e2e_fixture.synthetic_design_calls).toBe(0);
  await expect(app.page.locator('#generation-preview input[type="checkbox"]')).toHaveCount(1);
  await expect(app.page.locator('#generation-preview-summary')).toContainText('fixture-model');
  await approve(app); await waitJob(app, 'completed');
  const after = await app.state();
  expect(after.organization.agents).toHaveLength(4);
  expect(after.e2e_fixture.synthetic_design_calls).toBe(1);
  expect(after.generation_stale).toBe(false);
  await expect(app.page.locator('#generation-result')).toContainText('4 / 4');
});

test('generation: rapid double prepare and confirm send one of each request', async ({ app }) => {
  await app.control('mode', { mode: 'blocked_design' });
  await app.page.locator('#prepare-generation').dblclick();
  await expect(app.page.locator('#generation-preview')).toBeVisible();
  expect(app.requests.filter(x => x === '/api/generation-plan')).toHaveLength(1);
  await app.page.locator('#generation-consent').check();
  await app.page.locator('#confirm-generation').dblclick();
  expect(app.requests.filter(x => x === '/api/generation-confirm')).toHaveLength(1);
  await app.control('release'); await waitJob(app, 'completed');
  expect((await app.state()).e2e_fixture.synthetic_design_calls).toBe(1);
});

test('generation: partial coverage warning belongs to the single authorization', async ({ app }) => {
  await prepare(app, 'partial');
  await expect(app.page.locator('#generation-partial-notice')).toBeVisible();
  expect((await app.state()).pending_consent.partial_inventory_required).toBe(true);
  await approve(app); await waitJob(app, 'completed');
});

for (const [selector, value] of [['#generation-tokens','8192'], ['#generation-batch','2'], ['#generation-response-mode','text']]) {
  test(`generation: ${selector} is locked during review and a replacement plan needs fresh approval`, async ({ app }) => {
    await prepare(app);
    const previousId = (await app.state()).generation_job.job_id;
    await app.page.locator('#generation-consent').check();
    const control = app.page.locator(selector);
    await expect(control).toBeDisabled();
    await app.page.locator('#cancel-generation').click();
    await waitJob(app, 'cancelled');
    await expect(control).toBeEnabled();
    if (selector.endsWith('mode')) await control.selectOption(value);
    else { await control.fill(value); await control.press('Tab'); }
    await app.page.locator('#prepare-generation').click();
    await expect(app.page.locator('#generation-preview')).toBeVisible();
    await expect(app.page.locator('#generation-consent')).not.toBeChecked();
    await expect(app.page.locator('#confirm-generation')).toBeDisabled();
    expect((await app.state()).generation_job.job_id).not.toBe(previousId);
    expect((await app.state()).e2e_fixture.synthetic_design_calls).toBe(0);
    await app.page.locator('#cancel-generation').click();
    await waitJob(app, 'cancelled');
  });
}

for (const [selector, value] of [['#generation-tokens','4095'], ['#generation-tokens','8192.5'], ['#generation-batch','0'], ['#generation-batch','33']]) {
  test(`generation: invalid ${selector}=${value} cannot prepare`, async ({ app }) => {
    await app.page.locator(selector).fill(value);
    await app.page.locator('#prepare-generation').click();
    expect((await app.state()).generation_job).toBeNull();
    expect(app.requests.filter(x => x === '/api/generation-plan')).toHaveLength(0);
  });
}

test('generation: failed request downloads bounded diagnostic and retry only prepares', async ({ app }) => {
  await prepare(app, 'fail_design'); await approve(app); await waitJob(app, 'failed');
  const failed = await app.state();
  await expect(app.page.locator('#generation-retry')).toBeVisible();
  const report = await app.download(app.page.locator('#generation-diagnostic-download'));
  expect(report.filename).toBe(`orgdna-generation-diagnostic-${failed.generation_job.job_id}.json`);
  expect(report.json().format).toBe('orgdna-generation-diagnostic');
  expect(report.json().privacy.credentials_included).toBe(false);
  expect(report.bytes.toString()).not.toContain(SENTINEL);
  await app.control('mode', { mode: 'success' });
  await app.page.locator('#generation-retry').dblclick();
  await expect(app.page.locator('#generation-preview')).toBeVisible();
  const retry = await app.state();
  expect(retry.generation_job.job_id).not.toBe(failed.generation_job.job_id);
  expect(retry.e2e_fixture.synthetic_design_calls).toBe(1);
  expect(app.requests.filter(x => x === '/api/generation-plan')).toHaveLength(2);
  await expect(app.page.locator('#generation-consent')).not.toBeChecked();
  await expect(app.page.locator('#confirm-generation')).toBeDisabled();
  await approve(app); await waitJob(app, 'completed');
  expect((await app.state()).e2e_fixture.synthetic_design_calls).toBe(2);
});

test('generation: cancellation before consent never calls the inert provider', async ({ app }) => {
  const old = (await app.state()).organization;
  await prepare(app);
  await app.page.locator('#cancel-generation').click();
  await waitJob(app, 'cancelled');
  const current = await app.state();
  expect(current.organization).toEqual(old);
  expect(current.e2e_fixture.synthetic_design_calls).toBe(0);
  await expect(app.page.locator('#confirm-generation')).toBeDisabled();
});

test('generation: cancel while request waits prevents a late result from publishing', async ({ app }) => {
  const old = (await app.state()).organization;
  await prepare(app, 'blocked_design'); await approve(app);
  await expect.poll(async () => (await app.state()).e2e_fixture.synthetic_design_calls).toBe(1);
  await app.page.locator('#cancel-generation').click();
  await waitJob(app, 'cancelled');
  await app.control('release');
  await app.page.reload();
  await expect(app.page.locator('#generation-result')).toBeVisible();
  expect((await app.state()).organization).toEqual(old);
  expect((await app.state()).generation_job.status).toBe('cancelled');
});

test('generation: reload resumes awaiting consent without remembering checked approval', async ({ app }) => {
  await prepare(app); const id = (await app.state()).generation_job.job_id;
  await app.page.locator('#generation-consent').check();
  await app.page.reload();
  await expect(app.page.locator('#generation-preview')).toBeVisible();
  await expect(app.page.locator('#generation-consent')).not.toBeChecked();
  expect((await app.state()).generation_job.job_id).toBe(id);
  expect((await app.state()).e2e_fixture.synthetic_design_calls).toBe(0);
  await app.page.locator('#cancel-generation').click();
});

test('recovery: saved config blocks exports then restores original bytes and keeps draft', async ({ app }) => {
  await app.navigate('exportaciones');
  const original = await app.download(app.page.locator('#export-definitions'));
  await app.navigate('inicio');
  await app.page.locator('[name="repo_name"]').fill('Pending synthetic revision');
  await app.page.locator('#config-form button[type="submit"]').click();
  await expect(app.page.locator('#restore-design')).toBeVisible();
  await app.navigate('exportaciones');
  await expect(app.page.locator('#export-definitions')).toHaveAttribute('aria-disabled', 'true');
  await app.navigate('inicio');
  await acceptNextDialog(app.page, () => app.page.locator('#restore-design').click());
  await expect(app.page.locator('#recovery-exports')).toBeVisible();
  await app.page.locator('#recovery-exports').click();
  const restored = await app.download(app.page.locator('#export-definitions'));
  expect(restored.bytes.equals(original.bytes)).toBe(true);
  expect(restored.filename).toBe(original.filename);
  await app.navigate('inicio');
  await acceptNextDialog(app.page, () => app.page.locator('#resume-design-draft').click());
  await expect(app.page.locator('[name="repo_name"]')).toHaveValue('Pending synthetic revision');
  expect((await app.state()).generation_stale).toBe(true);
  expect((await app.state()).e2e_fixture.synthetic_design_calls).toBe(0);
});

test('recovery: failed redesign preserves identity and restore remains valid after saved-project reload', async ({ app }) => {
  const old = (await app.state()).organization.organization_id;
  await app.page.locator('[name="repo_name"]').fill('Failure draft');
  await prepare(app, 'fail_design'); await approve(app); await waitJob(app, 'failed');
  await app.page.locator('#project-name').fill('E2E failed-state version');
  await app.page.locator('#project-save-form button[type="submit"]').click();
  await expect(app.page.locator('#project-status')).toContainText('E2E failed-state version');
  const stored = await app.state();
  await app.page.locator('#project-list').selectOption(stored.project.id);
  await app.page.locator('#project-load').click();
  await expect(app.page.locator('#restore-design')).toBeEnabled();
  await acceptNextDialog(app.page, () => app.page.locator('#restore-design').click());
  await expect(app.page.locator('#recovery-exports')).toBeVisible();
  const current = await app.state();
  expect(current.generation_stale).toBe(false);
  expect(current.organization.organization_id).toBe(old);
});

test('recovery: late polling response cannot replace a successful restore', async ({ app }) => {
  await app.page.locator('[name="repo_name"]').fill('Draft with delayed polling');
  await prepare(app, 'blocked_design'); await approve(app);
  let releaseRead, readStarted;
  const started = new Promise(resolve => { readStarted = resolve; });
  const release = new Promise(resolve => { releaseRead = resolve; });
  await app.page.route('**/api/state', async route => {
    const response = await route.fetch(); const body = await response.body();
    readStarted(); await release; await route.fulfill({ response, body });
  }, { times: 1 });
  await started;
  await app.page.locator('#cancel-generation').click();
  await expect(app.page.locator('#restore-design')).toBeEnabled();
  await acceptNextDialog(app.page, () => app.page.locator('#restore-design').click());
  await expect(app.page.locator('#recovery-exports')).toBeVisible();
  const delivered = app.page.waitForResponse('**/api/state');
  releaseRead(); await delivered; await app.control('release');
  await app.page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(app.page.locator('#restore-design')).toBeHidden();
  await expect(app.page.locator('#recovery-exports')).toBeVisible();
  expect((await app.state()).generation_stale).toBe(false);
});
