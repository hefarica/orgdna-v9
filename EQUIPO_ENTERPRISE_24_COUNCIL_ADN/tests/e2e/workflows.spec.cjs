'use strict';
const { test, expect, SENTINEL, acceptNextDialog } = require('./fixtures.cjs');
const matrix = require('./control-matrix.json');

test('inicio: source selection, readonly Council count and offline alternative', async ({ app }) => {
  const { page } = app;
  await page.locator('[name="source_kind"]').selectOption('website');
  await expect(page.locator('#source-url-label')).toContainText(/sitio|web/i);
  await page.locator('[name="source_kind"]').selectOption('github_repository');
  await page.locator('[name="agent_count"]').fill('5');
  await page.locator('[name="agent_count"]').press('Tab');
  await expect(page.locator('[name="council_concurrency"]')).toHaveValue('5');
  await expect(page.locator('[name="council_concurrency"]')).toHaveAttribute('readonly','');
  await page.locator('#config-form button[type="submit"]').click();
  await page.locator('details').filter({ has: page.locator('#generate-offline') }).locator('summary').click();
  await page.locator('#generate-offline').click();
  await expect(page.locator('#stat-agents')).toHaveText('5');
  expect((await app.state()).e2e_fixture.synthetic_design_calls).toBe(0);
});

test('inicio: synthetic credential field clears, does not persist and can be forgotten', async ({ app }) => {
  const { page } = app;
  await acceptNextDialog(page, () => page.locator('#forget-key').click());
  await expect(page.locator('#key-status')).toContainText(/Sin clave/i);
  await page.locator('[name="api_key"]').fill(SENTINEL);
  await expect(page.locator('#persist-key')).not.toBeChecked();
  await page.locator('#key-form button[type="submit"]').click();
  await expect(page.locator('[name="api_key"]')).toHaveValue('');
  expect((await app.state()).credentials_persisted).toBe(false);
  await app.navigate('registro');
  await expect(page.locator('#receipt-list')).not.toContainText(SENTINEL);
});

test('perfiles: search/filter and save a real dialog edit; dirty close needs a decision', async ({ app }) => {
  const { page } = app;
  const original = (await app.state()).organization.agents[0];
  await app.navigate('perfiles');
  await expect(page.locator('.profile-card')).toHaveCount(4);
  await page.locator('#profile-search').fill('Missing E2E profile');
  await expect(page.locator('#profile-empty')).toBeVisible();
  await page.locator('#profile-search').fill(original.display_name);
  await expect(page.locator('.profile-card')).toHaveCount(1);
  await page.locator('.profile-card').first().click();
  for (const row of matrix.controls.filter(row => row.page === 'profile-dialog' && row.source === 'html')) {
    await expect(page.locator(row.locator).nth(row.nth || 0)).toBeAttached();
  }
  await page.locator('#agent-name').fill('E2E revised synthetic profile');
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('#close-inspector').click();
  await expect(page.locator('#profile-dialog')).toBeVisible();
  await page.locator('#save-profile').click();
  await expect(page.locator('#profile-dialog')).toBeHidden();
  await page.locator('#profile-search').fill('E2E revised');
  await expect(page.locator('.profile-card')).toHaveCount(1);
  expect((await app.state()).organization.agents[0].display_name).toBe('E2E revised synthetic profile');
  await page.locator('#profile-search').fill('');
  await page.locator('#department-filter').selectOption(original.department);
  expect(await page.locator('.profile-card').count()).toBeGreaterThan(0);
  await page.locator('#department-filter').selectOption('');
  await page.locator('#skill-status-filter').selectOption('verified');
  await expect(page.locator('#profile-empty')).toBeVisible();
});

test('perfiles: tool policy draft rejects overlap and resets without runtime changes', async ({ app }) => {
  const { page } = app;
  await app.navigate('perfiles'); await page.locator('.profile-card').first().click();
  await page.locator('#permission-section > summary').click();
  await page.locator('#tools-allow').fill('e2e_read');
  await page.locator('#tools-deny').fill('e2e_read');
  await expect(page.locator('#save-tool-policy')).toBeDisabled();
  await expect(page.locator('#permission-validation')).not.toBeEmpty();
  await acceptNextDialog(page, () => page.locator('#reset-tool-policy').click());
  await page.locator('#cancel-inspector').click();
  expect((await app.state()).e2e_fixture.actions).not.toContain('dsh-connect');
});

test('organigrama: subteam uses existing members and saves locally', async ({ app }) => {
  const { page } = app;
  await app.navigate('organigrama');
  await page.locator('#subteam-editor > summary').click();
  await page.locator('#subteam-name').fill('E2E Review');
  await page.locator('#subteam-type').selectOption('consulting');
  await page.locator('#subteam-members input[type="checkbox"]').first().check();
  await page.locator('#subteam-scope').fill('Review synthetic fixture evidence only.');
  await page.locator('#save-subteam').click();
  await expect(page.locator('#subteam-list')).toContainText('E2E Review');
  expect((await app.state()).organization.agents).toHaveLength(4);
  await page.locator('#new-subteam').click();
  await expect(page.locator('#subteam-name')).toHaveValue('');
});

test('council: save manual entry and close it without starting agents', async ({ app }) => {
  const { page } = app;
  await app.navigate('council');
  await page.locator('#council-topic').fill('E2E synthetic review');
  await page.locator('#council-objection').fill('Fixture observation, not an agent response.');
  await page.locator('#council-evidence').fill('fixture://evidence/one');
  await page.locator('#council-save').click();
  await expect(page.locator('#council-records')).toContainText('Fixture observation');
  page.once('dialog', dialog => dialog.accept('Closed synthetic record; no agents executed.'));
  await page.locator('#council-close').click();
  await expect(page.locator('#council-save')).toBeDisabled();
  expect((await app.state()).council_sessions).toHaveLength(1);
  expect((await app.state()).e2e_fixture.synthetic_design_calls).toBe(0);
});

test('habilidades: manual library item, local search and assignment preview', async ({ app }) => {
  const { page } = app;
  await app.navigate('habilidades');
  await page.locator('[data-cap-tab="library"]').click();
  await page.locator('details').filter({ has: page.locator('#cap-manual-form') }).locator('summary').first().click();
  await page.locator('#cap-manual-name').fill('E2E evidence review');
  await page.locator('#cap-manual-description').fill('Synthetic local testing instruction');
  await page.locator('#cap-manual-instructions').fill('Check fixture evidence. Never call providers or DSH.');
  await page.locator('#cap-manual-save').click();
  await page.locator('#cap-library-query').fill('E2E evidence review');
  await page.locator('#cap-library-search button[type="submit"]').click();
  await expect(page.locator('#cap-library')).toContainText('E2E evidence review');
  const selected = page.locator('#cap-library [data-cap-selection]').first();
  await selected.check();
  await expect(page.locator('#cap-preview')).toBeEnabled();
  await page.locator('#cap-preview').click();
  await expect(page.locator('#cap-plan-review')).toBeVisible();
  await page.locator('#cap-plan-discard').click();
  await expect(page.locator('#cap-plan-review')).toBeHidden();
  await page.locator('#cap-clear').click();
  await expect(page.locator('#cap-preview')).toBeDisabled();
});

test('modelos: synthetic catalog, exact-ID selection and per-profile assignment', async ({ app }) => {
  const { page } = app;
  await app.navigate('modelos');
  await acceptNextDialog(page, () => page.locator('#discover-models').click());
  await expect(page.locator('#model-table')).toContainText('fixture-model');
  await page.locator('#model-table button').first().click();
  await expect(page.locator('[name="model"]')).toHaveValue('fixture-model');
  await page.locator('#config-form button[type="submit"]').click();
  await app.navigate('modelos');
  await page.locator('#model-agent-model').fill('fixture-model-override');
  await page.locator('#save-model-assignment').click();
  const state = await app.state();
  expect(Object.values(state.model_overrides)[0].model).toBe('fixture-model-override');
  expect(state.e2e_fixture.synthetic_design_calls).toBe(0);
});

test('repositorio: synthetic inventory reads display scope without an LLM call', async ({ app }) => {
  await app.navigate('repositorio');
  await app.page.locator('#inventory').click();
  await expect.poll(async () => (await app.state()).e2e_fixture.synthetic_inventory_calls).toBe(1);
  await expect(app.page.locator('#repositorio')).toContainText('README.md');
  expect((await app.state()).e2e_fixture.synthetic_design_calls).toBe(0);
});

test('exportaciones: actual downloaded native JSON agrees on format, IDs, bytes and hashes', async ({ app }) => {
  await app.navigate('exportaciones');
  const state = await app.state();
  const backup = await app.download(app.page.locator('#export-definitions'));
  const recipe = await app.download(app.page.locator('#export-implementation'));
  const org = await app.download(app.page.locator('a[href="/download/organization.json"]'));
  expect(backup.json().format).toBe('agent-team-gui/definitions');
  expect(backup.json().version).toBe(2);
  expect(recipe.json().format).toBe('agent-team-gui/recipe');
  expect(recipe.json().version).toBe(1);
  expect(backup.json().agents).toEqual(recipe.json().agents);
  expect(recipe.json().agents.map(a => a.id).sort()).toEqual(org.json().agents.map(a => a.id).sort());
  expect(recipe.json().agents).toHaveLength(4);
  for (const [file, type] of [[backup, 'definitions'], [recipe, 'implementation']]) {
    expect(file.filename).toBe(state.export_artifacts[type].filename);
    expect(file.sha256).toBe(state.export_artifacts[type].sha256);
    expect(file.bytes.length).toBe(state.export_artifacts[type].bytes);
    expect(file.bytes.toString()).not.toContain(SENTINEL);
  }
});

test('exportaciones: DSH guards and mocked readonly refresh never connect or launch', async ({ app }) => {
  await app.navigate('exportaciones');
  for (const id of ['dsh-connect','dsh-disconnect','dsh-read-profiles','dsh-read-team','dsh-preview-import','dsh-launch-execute','harness-start']) {
    await expect(app.page.locator('#' + id)).toBeDisabled();
  }
  await app.page.locator('#dsh-refresh-status').click();
  const state = await app.state();
  expect(state.e2e_fixture.actions).toContain('dsh-status');
  expect(state.e2e_fixture.actions.filter(a => a.startsWith('dsh-'))).toEqual(['dsh-status']);
  expect(state.dsh_connection.runtime_write_supported).toBe(false);
});

test('registro: actual receipt download identifies fixture provenance without secrets', async ({ app }) => {
  await app.navigate('registro');
  await expect(app.page.locator('#receipt-list')).toContainText('E2E FIXTURE ONLY');
  const file = await app.download(app.page.locator('#registro a[download]'));
  expect(file.json().receipts.length).toBeGreaterThan(0);
  expect(file.json().verification.provider_live_calls).toBe('NOT_RUN_E2E_FIXTURE_ONLY');
  expect(file.bytes.toString()).not.toContain(SENTINEL);
});

test('inicio: save two project versions, reload old version, and save independent copy', async ({ app }) => {
  const { page } = app;
  const original = (await app.state()).organization.agents[0].display_name;
  await page.locator('#project-name').fill('E2E versioned organization');
  await page.locator('#project-save-form button[type="submit"]').click();
  await expect(page.locator('#project-status')).toContainText('guardado');
  const first = (await app.state()).project;
  await app.navigate('perfiles'); await page.locator('.profile-card').first().click();
  await page.locator('#agent-name').fill('Second version name');
  await page.locator('#save-profile').click();
  await app.navigate('inicio');
  await page.locator('#project-save-form button[type="submit"]').click();
  await expect.poll(async () => (await app.state()).project.version_id).not.toBe(first.version_id);
  await page.locator('#project-refresh').click();
  await page.locator('#project-list').selectOption(first.id);
  await page.locator('#project-version').selectOption(first.version_id);
  await page.locator('#project-load').click();
  await expect.poll(async () => (await app.state()).organization.agents[0].display_name).toBe(original);
  await page.locator('#project-name').fill('E2E independent copy');
  await page.locator('#project-save-new').click();
  await expect.poll(async () => (await app.state()).project.id).not.toBe(first.id);
  expect((await app.state()).e2e_fixture.synthetic_design_calls).toBe(0);
});

test('perfiles: save exact proposed tool allow/deny and reopen without runtime grants', async ({ app }) => {
  const { page } = app;
  await app.navigate('perfiles'); await page.locator('.profile-card').first().click();
  await page.locator('#permission-section > summary').click();
  await page.locator('#tools-allow').fill('e2e_read_only_tool');
  await page.locator('#tools-deny').fill('e2e_destructive_tool');
  await expect(page.locator('#save-tool-policy')).toBeEnabled();
  await page.locator('#save-tool-policy').click();
  await expect(page.locator('#permission-badge')).toContainText('1 allow');
  await page.locator('#close-inspector').click();
  await page.locator('.profile-card').first().click();
  await expect(page.locator('#tools-allow')).toHaveValue('e2e_read_only_tool');
  await expect(page.locator('#tools-deny')).toHaveValue('e2e_destructive_tool');
  expect((await app.state()).dsh_connection.runtime_write_supported).toBe(false);
});

test('habilidades: assign, activate, deactivate and unassign require separate local previews', async ({ app }) => {
  const { page } = app;
  await app.navigate('habilidades'); await page.locator('[data-cap-tab="library"]').click();
  await page.locator('details').filter({ has: page.locator('#cap-manual-form') }).locator('summary').first().click();
  await page.locator('#cap-manual-name').fill('E2E reversible instruction');
  await page.locator('#cap-manual-description').fill('Local assignment lifecycle fixture');
  await page.locator('#cap-manual-instructions').fill('Only inspect synthetic fixture data.');
  await page.locator('#cap-manual-save').click();
  await expect(page.locator('#cap-library')).toContainText('E2E reversible instruction');
  for (const action of ['assign','activate','deactivate','unassign']) {
    await page.locator('#cap-library [data-cap-selection]').first().check();
    await page.locator('#cap-assignment-action').selectOption(action);
    await expect(page.locator('#cap-apply')).toBeDisabled();
    await page.locator('#cap-preview').click();
    await expect(page.locator('#cap-plan-review')).toBeVisible();
    await expect(page.locator('#cap-plan-summary')).toContainText(action);
    const pending = (await app.state()).capability_library.plan;
    expect(pending).toBeTruthy();
    await page.locator('#cap-apply').click();
    await expect(page.locator('#cap-plan-review')).toBeHidden();
    const current = await app.state();
    const assignments = current.capability_library.assignment_page.items;
    if (action === 'unassign') expect(assignments).toHaveLength(0);
    else expect(assignments).toHaveLength(4);
    expect(current.dsh_connection.runtime_write_supported).toBe(false);
  }
});

test('habilidades: evaluation controls expose limits and require a reviewed plan', async ({ app }) => {
  const { page } = app;
  await app.navigate('habilidades'); await page.locator('[data-cap-tab="evidence"]').click();
  const details = page.locator('details').filter({ has: page.locator('#evaluation-form') });
  // Open only collapsed ancestors, using each real summary control.
  for (const ancestor of await details.all()) {
    if (await ancestor.getAttribute('open') === null) await ancestor.locator(':scope > summary').click();
  }
  await expect(page.locator('#evaluation-start')).toBeDisabled();
  await page.locator('#evaluation-task').fill('Synthetic evaluation plan only');
  await page.locator('#evaluation-timeout').fill('121');
  expect(await page.locator('#evaluation-timeout').evaluate(el => el.validity.rangeOverflow)).toBe(true);
  await page.locator('#evaluation-prepare').click();
  expect(app.requests.filter(path => path === '/api/evaluation-prepare')).toHaveLength(0);
  await expect(page.locator('#evaluation-start')).toBeDisabled();
  expect((await app.state()).evaluations.runs).toHaveLength(0);
});
