'use strict';
const { test, expect, openDetailsFor, acceptNextDialog } = require('./fixtures.cjs');
async function fillLease(app, owner, task, paths = 'src') {
  const { page } = app;
  await app.navigate('council');
  await openDetailsFor(page, '#lease-form');
  await page.locator('#lease-owner').selectOption(owner);
  await page.locator('#lease-form [name="task_id"]').fill(task);
  await page.locator('#lease-form [name="workspace"]').fill((await app.state()).e2e_fixture.synthetic_workspace);
  await page.locator('#lease-form [name="paths"]').fill(paths);
  await page.locator('#lease-form [name="base_sha"]').fill('b'.repeat(40));
  await page.locator('#lease-ttl').fill('60');
}
async function acquire(app, owner, task, paths = 'src') {
  await fillLease(app, owner, task, paths);
  await app.page.locator('#acquire-lease').click();
  await expect(app.page.locator('#lease-list .lease-record').filter({ hasText: task })).toBeVisible();
  await expect(app.page.locator('#notice')).toContainText('Rutas reservadas en el coordinador local.');
  await expect(app.page.locator('body')).toHaveAttribute('aria-busy', 'false');
  await expect.poll(async () => (await app.state()).coordination.leases.some(item => item.task_id === task)).toBe(true);
}

test('coordination: acquire renew release and reload preserve exact local lease identity', async ({ app }) => {
  const { page } = app, owner = (await app.state()).organization.agents[0].id;
  await acquire(app, owner, 'e2e-lease', 'src\nsrc/nested/file.js');
  let state = await app.state();
  const lease = state.coordination.leases[0];
  expect(lease.paths).toEqual(['src']);
  expect(lease.owner_agent_id).toBe(owner);
  expect(state.coordination.active_writer_count).toBe(1);
  await expect(page.locator('#lease-count')).toHaveText('1 / 3 escritores');
  for (const flag of ['filesystem_lock_enforced', 'dsh_enforced', 'runtime_identity_verified', 'base_sha_verified']) expect(lease[flag]).toBe(false);
  const version = state.coordination.version;
  await page.locator('#lease-ttl').fill('120');
  await page.locator('#lease-list button').filter({ hasText: 'Renovar' }).click();
  await expect.poll(async () => (await app.state()).coordination.version).toBe(version + 1);
  state = await app.state();
  expect(state.coordination.leases[0].id).toBe(lease.id);
  expect(state.coordination.leases[0].expires_at_epoch).toBeGreaterThan(lease.expires_at_epoch);
  await page.locator('#lease-list button').filter({ hasText: 'Liberar' }).click();
  await expect(page.locator('#lease-count')).toHaveText('0 / 3 escritores');
  expect((await app.state()).coordination.leases[0].status).toBe('released');
  await expect(page.locator('#lease-list button')).toHaveCount(0);
  await page.reload(); await openDetailsFor(page, '#lease-list');
  await page.locator('#refresh-coordination').click();
  await expect(page.locator('#lease-count')).toHaveText('0 / 3 escritores');
  expect((await app.state()).coordination.leases[0].status).toBe('released');
});

test('coordination: overlapping path rejects atomically and third-writer limit survives refresh', async ({ app }) => {
  const { page } = app, ids = (await app.state()).organization.agents.map(item => item.id);
  await acquire(app, ids[0], 'writer-a', 'src');
  const first = (await app.state()).coordination;
  await fillLease(app, ids[1], 'writer-conflict', 'src/nested/file.py');
  await app.expectActionError('/api/lease-acquire', () => page.locator('#acquire-lease').click(), /Conflicto/);
  expect((await app.state()).coordination.leases).toEqual(first.leases);
  await expect(page.locator('#coordination-error')).toContainText('Conflicto');
  await acquire(app, ids[1], 'writer-b', 'docs');
  await acquire(app, ids[2], 'writer-c', 'tests');
  await expect(page.locator('#coordination-error')).toBeHidden();
  const full = (await app.state()).coordination;
  await fillLease(app, ids[3], 'writer-four', 'unused');
  await app.expectActionError('/api/lease-acquire', () => page.locator('#acquire-lease').click(), /tres/);
  expect((await app.state()).coordination.leases).toEqual(full.leases);
  await page.locator('#refresh-coordination').click();
  await expect(page.locator('#lease-count')).toHaveText('3 / 3 escritores');
  expect((await app.state()).coordination.active_writer_count).toBe(3);
});

test('coordination: native SHA and TTL validity prevent requests; traversal cannot reserve outside fixture', async ({ app }) => {
  const { page } = app, owner = (await app.state()).organization.agents[0].id;
  await fillLease(app, owner, 'invalid-lease');
  await page.locator('#lease-form [name="base_sha"]').fill('bad');
  await page.locator('#lease-ttl').fill('59');
  await page.locator('#acquire-lease').click();
  expect(app.requests.filter(path => path === '/api/lease-acquire')).toHaveLength(0);
  expect(await page.locator('#lease-form [name="base_sha"]').evaluate(el => el.validity.patternMismatch)).toBe(true);
  expect(await page.locator('#lease-ttl').evaluate(el => el.validity.rangeUnderflow)).toBe(true);
  await page.locator('#lease-form [name="base_sha"]').fill('c'.repeat(64));
  await page.locator('#lease-ttl').fill('3601');
  await page.locator('#acquire-lease').click();
  expect(await page.locator('#lease-ttl').evaluate(el => el.validity.rangeOverflow)).toBe(true);
  expect(app.requests.filter(path => path === '/api/lease-acquire')).toHaveLength(0);
  await page.locator('#lease-ttl').fill('60');
  await page.locator('#lease-form [name="paths"]').fill('../outside');
  await app.expectActionError('/api/lease-acquire', () => page.locator('#acquire-lease').click(), /traversal/);
  expect((await app.state()).coordination.leases).toEqual([]);
});

test('modelos: invalid priorities never post; exact rank persists across reload without inference', async ({ app }) => {
  const { page } = app;
  await app.navigate('modelos');
  await acceptNextDialog(page, () => page.locator('#discover-models').click());
  await expect(page.locator('.model-rank')).toHaveCount(1);
  for (const value of ['0', '1.5', '100001']) {
    await page.locator('.model-rank').fill(value);
    await page.locator('#save-model-preferences').click();
    await expect(page.locator('#notice')).toContainText('enteros entre 1 y 100.000');
  }
  expect(app.requests.filter(path => path === '/api/model-preferences')).toHaveLength(0);
  await page.locator('.model-rank').fill('7');
  await page.locator('#save-model-preferences').click();
  await expect.poll(async () => (await app.state()).models[0].user_rank).toBe(7);
  await page.reload();
  await expect(page.locator('.model-rank')).toHaveValue('7');
  expect((await app.state()).e2e_fixture.synthetic_design_calls).toBe(0);
});
