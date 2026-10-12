'use strict';
// Authored browser assertions only: Chromium NOT_RUN until a permitted run.
// All writes below are initiated through real forms/buttons in the isolated fixture.
const { test, expect, openDetailsFor } = require('./fixtures.cjs');

async function postFromUI(app, action, click) {
  const pending = app.page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/' + action && response.request().method() === 'POST');
  await click();
  const response = await pending;
  expect(response.ok(), await response.text()).toBeTruthy();
  const state = await response.json();
  await expect(app.page.locator('body')).toHaveAttribute('aria-busy', 'false');
  return { body: response.request().postDataJSON(), state };
}

async function showEvidence(app) {
  await app.navigate('habilidades');
  await app.page.locator('[data-cap-tab="evidence"]').click();
  await expect(app.page.locator('#cap-evidence')).toBeVisible();
}

async function registerSkill(app, name, ownerId) {
  await showEvidence(app);
  await openDetailsFor(app.page, '#skill-register-form');
  const form = app.page.locator('#skill-register-form');
  await form.locator('[name="name"]').fill(name);
  await form.locator('[name="description"]').fill('Synthetic manual proposal; effectiveness remains unverified.');
  await form.locator('[name="owner_agent_id"]').selectOption(ownerId);
  await form.locator('[name="evidence"]').fill('fixture://skill/registration\nfixture://skill/source');
  const result = await postFromUI(app, 'skill-register', () => form.locator('button[type="submit"]').click());
  await expect(form.locator('[name="name"]')).toHaveValue('');
  const skill = result.state.skill_registry.find(row => row.name === name);
  expect(skill).toMatchObject({ name, owner_agent_id: ownerId, status: 'proposed', version: 1,
    installed: false, verified: false, origin: 'manual_entry', history: [],
    evidence: ['fixture://skill/registration', 'fixture://skill/source'] });
  await expect(app.page.locator('#skill-proposals > article').filter({ hasText: name }))
    .toContainText('Propuesta · no instalada');
  return skill;
}

async function fillFeedback(app, skillId, agentId, suffix) {
  await showEvidence(app);
  await openDetailsFor(app.page, '#skill-feedback-form');
  const form = app.page.locator('#skill-feedback-form');
  await form.locator('[name="skill_id"]').selectOption(skillId);
  await form.locator('[name="agent_id"]').selectOption(agentId);
  await form.locator('[name="failure"]').fill('Synthetic failure ' + suffix);
  await form.locator('[name="proposed_change"]').fill('Manual checklist revision ' + suffix);
  await form.locator('[name="retest_result"]').fill('Manual retest declaration ' + suffix + '; no test executed by this app.');
  return form;
}

async function saveProject(app, name) {
  await app.navigate('inicio');
  await app.page.locator('#project-name').fill(name);
  const { state } = await postFromUI(app, 'project-save', () =>
    app.page.locator('#project-save-form button[type="submit"]').click());
  await expect(app.page.locator('#project-status')).toContainText('guardado');
  await expect(app.page.locator('#project-list option[value="' + state.project.id + '"]')).toBeAttached();
  await expect(app.page.locator('#project-version option[value="' + state.project.version_id + '"]')).toBeAttached();
  return state.project;
}

async function loadProjectVersion(app, project) {
  await app.navigate('inicio');
  await app.page.locator('#project-list').selectOption(project.id);
  await app.page.locator('#project-version').selectOption(project.version_id);
  const { state } = await postFromUI(app, 'project-load', () => app.page.locator('#project-load').click());
  expect(state.project.id).toBe(project.id);
  expect(state.project.version_id).toBe(project.version_id);
  return state;
}

function profileEvidence(agents) {
  // Project reload deliberately refreshes catalog availability and derived prompts.
  // Preserve the actual assertions about hierarchy, permissions and skill evidence.
  return agents.map(agent => ({ id: agent.id, display_name: agent.display_name,
    reports_to: agent.reports_to, tool_policy: agent.tool_policy,
    skills: agent.skills.map(skill => ({ id: skill.id, verified_level: skill.verified_level, evidence: skill.evidence })) }));
}

async function createRemediation(app, name = 'E2E synthetic reproducible failure') {
  const agent = (await app.state()).organization.agents[1];
  await showEvidence(app);
  await openDetailsFor(app.page, '#remediation-form');
  const form = app.page.locator('#remediation-form');
  await form.locator('[name="agent_id"]').selectOption(agent.id);
  await form.locator('[name="failure"]').fill(name);
  await form.locator('[name="expected"]').fill('Synthetic expected result A');
  await form.locator('[name="actual"]').fill('Synthetic observed result B');
  await form.locator('[name="evidence"]').fill('fixture://remediation/observed');
  const { state } = await postFromUI(app, 'remediation-create', () => form.locator('button[type="submit"]').click());
  await expect(form.locator('[name="failure"]')).toHaveValue('');
  const record = state.remediation_records.find(row => row.failure === name);
  expect(record).toMatchObject({ agent_id: agent.id, status: 'observed', events: [],
    origin: 'manual_entry', tests_executed_by_app: false, effectiveness_verified: false });
  return record;
}

function remediationButton(page, failure) {
  return page.locator('#remediation-list > article').filter({ hasText: failure })
    .getByRole('button', { name: 'Registrar siguiente paso', exact: true });
}

async function answerPrompts(page, answers, click) {
  const seen = [];
  let complete, fail;
  const finished = new Promise((resolve, reject) => { complete = resolve; fail = reject; });
  const handler = async dialog => {
    try {
      expect(dialog.type()).toBe('prompt');
      const answer = answers[seen.length];
      expect(answer, 'Unexpected extra prompt').toBeDefined();
      seen.push({ message: dialog.message(), defaultValue: dialog.defaultValue() });
      if (answer === null) await dialog.dismiss();
      else await dialog.accept(answer);
      if (seen.length === answers.length) complete();
    } catch (error) {
      await dialog.dismiss().catch(() => {});
      fail(error);
    }
  };
  page.on('dialog', handler);
  try {
    await Promise.all([click(), finished]);
    expect(seen).toHaveLength(answers.length);
    expect(seen[0].message).toContain('El motor valida el orden y la independencia');
    if (seen.length > 1) expect(seen[1].message).toContain('Describe el cambio');
    if (seen.length > 2) expect(seen[2].message).toContain('Referencias de evidencia');
    return seen;
  } finally {
    page.off('dialog', handler);
  }
}

async function createCapability(app, name, content = 'Review only the synthetic fixture evidence.') {
  await app.navigate('habilidades');
  await app.page.locator('[data-cap-tab="library"]').click();
  await openDetailsFor(app.page, '#cap-manual-form');
  await app.page.locator('#cap-manual-name').fill(name);
  await app.page.locator('#cap-manual-type').selectOption('skill_instructions');
  await app.page.locator('#cap-manual-description').fill('Locally authored capability for isolated acceptance checks.');
  await app.page.locator('#cap-manual-instructions').fill(content);
  const { state } = await postFromUI(app, 'capability-save', () => app.page.locator('#cap-manual-save').click());
  await expect(app.page.locator('#cap-manual-name')).toHaveValue('');
  const item = state.capability_library.page.items.find(row => row.name === name && row.content === content);
  expect(item).toMatchObject({ name, content, kind: 'skill_instructions', installed: false,
    runtime_verified: false, permission_grant: false, provenance: { type: 'user_authored' } });
  return item;
}

function capabilityCard(page, itemId) {
  return page.locator('#cap-library-results > article').filter({
    has: page.locator('[data-cap-key="library:' + itemId + '"]')
  });
}

async function checkProfileTargets(app, ids) {
  await app.page.locator('#cap-target-mode').selectOption('selected');
  const agents = (await app.state()).organization.agents;
  for (const id of ids) {
    const index = agents.findIndex(agent => agent.id === id);
    expect(index).toBeGreaterThanOrEqual(0);
    await app.page.locator('#cap-target-options [data-cap-target]').nth(index).check();
  }
}

async function previewCapability(app, item, agentIds, selection) {
  const before = await app.state();
  const { body, state } = await postFromUI(app, 'capability-preview', () => app.page.locator('#cap-preview').click());
  expect(body.item_ids).toEqual([item.id]);
  expect(body.selection).toEqual(selection);
  expect(body.assignment_action).toBe('assign');
  expect(body.expected_state_version).toBe(before.organization.state_version);
  expect(body.expected_revision).toBe(before.capability_library.status.revision);
  const plan = state.capability_library.plan;
  const preview = plan.preview.assignment_preview;
  expect(preview.agent_ids).toEqual(agentIds);
  expect(preview.item_ids).toEqual([item.id]);
  expect(preview.effects).toEqual(agentIds.map(agent_id => ({ agent_id, item_id: item.id, before: null, after: false })));
  expect(preview.changed_count).toBe(agentIds.length);
  expect(preview.unchanged_count).toBe(0);
  expect(preview.installs).toEqual([]);
  expect(preview.permission_changes).toEqual([]);
  expect(preview.tool_availability).toBe('unverified');
  expect(state.capability_library.status.revision).toBe(before.capability_library.status.revision);
  expect(state.capability_library.assignment_page.items).toEqual(before.capability_library.assignment_page.items);
  await expect(app.page.locator('#cap-plan-review')).toBeVisible();
  await expect(app.page.locator('#cap-plan-impact li')).toHaveCount(agentIds.length);
  await openDetailsFor(app.page, '#cap-plan-json');
  expect(JSON.parse(await app.page.locator('#cap-plan-json').innerText())).toEqual(plan);
  return plan;
}

async function applyCapability(app, plan, item, agentIds) {
  const { body, state } = await postFromUI(app, 'capability-apply', () => app.page.locator('#cap-apply').click());
  expect(body).toMatchObject({ plan_id: plan.id, preview_hash: plan.preview.preview_hash, confirmed: true });
  expect(typeof body.idempotency_key).toBe('string');
  expect(body.idempotency_key.length).toBeGreaterThan(0);
  expect(state.capability_library.plan).toBeNull();
  expect(state.capability_library.assignment_page.items.map(row => row.agent_id).sort()).toEqual([...agentIds].sort());
  for (const row of state.capability_library.assignment_page.items) {
    expect(row).toMatchObject({ item_id: item.id, active: false, assigned: true, installed: false, runtime_verified: false });
  }
  expect(state.capability_library.assignment_page.permission_grants).toEqual([]);
  await expect(app.page.locator('#cap-plan-review')).toBeHidden();
  await expect(app.page.locator('#cap-apply')).toBeDisabled();
  await app.page.locator('[data-cap-tab="assignments"]').click();
  await expect(app.page.locator('#cap-assignment-results > article')).toHaveCount(agentIds.length);
  await expect(app.page.locator('#cap-assignment-results')).toContainText('Referencia asignada · instrucciones inactivas');
  return state;
}

test('habilidades: skill registration and feedback required fields block empty evidence without a POST', async ({ app }) => {
  const { page } = app;
  await showEvidence(app);
  await openDetailsFor(page, '#skill-feedback-form');
  await expect(page.locator('#save-skill-feedback')).toBeDisabled();
  await openDetailsFor(page, '#skill-register-form');
  await page.locator('#skill-register-form [name="name"]').fill('E2E required fields');
  await page.locator('#skill-register-form button[type="submit"]').click();
  expect(await page.locator('#skill-register-form [name="description"]').evaluate(el => el.validity.valueMissing)).toBe(true);
  expect(app.requests.filter(path => path === '/api/skill-register')).toHaveLength(0);
  expect((await app.state()).skill_registry).toEqual([]);
  const agents = (await app.state()).organization.agents;
  const skill = await registerSkill(app, 'E2E required fields', agents[1].id);
  const form = await fillFeedback(app, skill.id, agents[2].id, 'required-evidence');
  const before = await app.state();
  await page.locator('#save-skill-feedback').click();
  expect(await form.locator('[name="evidence"]').evaluate(el => el.validity.valueMissing)).toBe(true);
  expect(app.requests.filter(path => path === '/api/skill-feedback')).toHaveLength(0);
  expect((await app.state()).skill_registry).toEqual(before.skill_registry);
  await form.locator('[name="evidence"]').fill('fixture://feedback/required');
  const { body, state } = await postFromUI(app, 'skill-feedback', () => page.locator('#save-skill-feedback').click());
  expect(body.expected_state_version).toBe(before.organization.state_version);
  expect(state.skill_registry[0].version).toBe(2);
  await expect(form.locator('[name="failure"]')).toHaveValue('');
  await expect(form).not.toHaveAttribute('data-base-version', /.+/);
});

test('habilidades: two manual feedback versions persist and historical project reload restores the original proposal', async ({ app }) => {
  const { page } = app;
  const agents = (await app.state()).organization.agents;
  const skill = await registerSkill(app, 'E2E versioned manual learning', agents[1].id);
  const first = await saveProject(app, 'E2E manual learning versions');
  const feedback = [];
  for (const [index, agent] of [agents[2], agents[3]].entries()) {
    const suffix = String(index + 1);
    const form = await fillFeedback(app, skill.id, agent.id, suffix);
    await form.locator('[name="evidence"]').fill('fixture://feedback/' + suffix + '/failure\nfixture://feedback/' + suffix + '/retest');
    const before = await app.state();
    const { body, state } = await postFromUI(app, 'skill-feedback', () => page.locator('#save-skill-feedback').click());
    expect(body).toMatchObject({ skill_id: skill.id, agent_id: agent.id,
      expected_state_version: before.organization.state_version,
      evidence: ['fixture://feedback/' + suffix + '/failure', 'fixture://feedback/' + suffix + '/retest'] });
    const saved = state.skill_registry.find(row => row.id === skill.id);
    expect(saved).toMatchObject({ version: index + 2, installed: false, verified: false, status: 'proposed' });
    expect(saved.feedback).toHaveLength(index + 1);
    expect(saved.feedback.at(-1)).toMatchObject({ agent_id: agent.id, failure: 'Synthetic failure ' + suffix,
      proposed_change: 'Manual checklist revision ' + suffix,
      retest_result: 'Manual retest declaration ' + suffix + '; no test executed by this app.',
      origin: 'manual_entry', runtime_identity_verified: false, verified: false, evidence: body.evidence });
    feedback.push(saved.feedback.at(-1));
    expect(state.organization.agents).toEqual(agents);
    await expect(page.locator('#skill-feedback-records > article')).toHaveCount(index + 1);
    await expect(page.locator('#skill-feedback-records')).toContainText('Retest declarado:');
    await expect(page.locator('#skill-feedback-records > article .tag')).toHaveText(
      Array(index + 1).fill('No instalada · eficacia sin verificar'));
  }
  const latest = await saveProject(app, 'E2E manual learning versions');
  expect(latest.id).toBe(first.id);
  expect(latest.version_id).not.toBe(first.version_id);
  const original = await loadProjectVersion(app, first);
  expect(original.skill_registry).toEqual([skill]);
  await showEvidence(app);
  await expect(page.locator('#skill-feedback-records > article')).toHaveCount(0);
  await expect(page.locator('#feedback-skill option').filter({ hasText: skill.name })).toHaveText(skill.name + ' · v1');
  const restored = await loadProjectVersion(app, latest);
  expect(restored.skill_registry[0]).toMatchObject({ id: skill.id, version: 3, feedback,
    installed: false, verified: false });
  await page.reload();
  await showEvidence(app);
  await expect(page.locator('#skill-feedback-records > article')).toHaveCount(2);
  await expect(page.locator('#feedback-skill option').filter({ hasText: skill.name })).toHaveText(skill.name + ' · v3');
  expect(profileEvidence((await app.state()).organization.agents)).toEqual(profileEvidence(agents));
});

test('habilidades: remediation prompt cancellations and invalid status leave the observation unchanged', async ({ app }) => {
  const { page } = app;
  const record = await createRemediation(app);
  const initial = await app.state();
  for (const answers of [[null], ['proposed', null], ['proposed', 'Draft change cancelled before evidence', null]]) {
    const dialogs = await answerPrompts(page, answers, () => remediationButton(page, record.failure).click());
    expect(dialogs[0].defaultValue).toBe('proposed');
    expect((await app.state()).remediation_records).toEqual(initial.remediation_records);
    expect(app.requests.filter(path => path === '/api/remediation-update')).toHaveLength(0);
  }
  await answerPrompts(page, ['invented-status'], () => remediationButton(page, record.failure).click());
  await expect(page.locator('#notice')).toContainText('Estado de remediación no admitido.');
  expect(app.requests.filter(path => path === '/api/remediation-update')).toHaveLength(0);
  const current = await app.state();
  expect(current.remediation_records).toEqual(initial.remediation_records);
  expect(current.organization.state_version).toBe(initial.organization.state_version);
  await expect(page.locator('#remediation-list')).toContainText('Observado');
});

test('habilidades: remediation rejects a skipped step then persists proposed and testing as manual declarations', async ({ app }) => {
  const { page } = app;
  const record = await createRemediation(app, 'E2E ordered remediation');
  const initial = await app.state();
  await app.expectActionError('/api/remediation-update', () => answerPrompts(page,
    ['testing', 'Attempt to skip the proposal', 'fixture://remediation/skip'],
    () => remediationButton(page, record.failure).click()), /transición requiere avanzar/);
  expect((await app.state()).remediation_records).toEqual(initial.remediation_records);
  expect((await app.state()).organization.state_version).toBe(initial.organization.state_version);
  const steps = [
    ['proposed', 'Manual correction proposal', 'fixture://remediation/proposal', 'Corrección propuesta'],
    ['testing', 'Manual retest result; no command executed', 'fixture://remediation/retest', 'Pruebas declaradas']
  ];
  for (const [status, note, evidence, label] of steps) {
    const { body, state } = await postFromUI(app, 'remediation-update', () =>
      answerPrompts(page, [status, note, evidence], () => remediationButton(page, record.failure).click()));
    expect(body).toEqual({ remediation_id: record.id, status, note, evidence: [evidence] });
    expect(state.remediation_records[0]).toMatchObject({ status, tests_executed_by_app: false, effectiveness_verified: false });
    await expect(page.locator('#remediation-list')).toContainText(label);
  }
  const finalRecord = (await app.state()).remediation_records[0];
  expect(finalRecord.events.map(event => event.status)).toEqual(['proposed', 'testing']);
  expect(finalRecord.events.map(event => event.note)).toEqual(steps.map(step => step[1]));
  expect(finalRecord.events.every(event => event.origin === 'manual_entry' && event.reviewer_id === null)).toBe(true);
  expect(finalRecord.evidence).toEqual(['fixture://remediation/observed', ...steps.map(step => step[2])]);
  const saved = await saveProject(app, 'E2E remediation declarations');
  const restored = await loadProjectVersion(app, saved);
  expect(restored.remediation_records).toEqual([finalRecord]);
  expect(profileEvidence(restored.organization.agents)).toEqual(profileEvidence(initial.organization.agents));
  expect(restored.evaluations.runs).toEqual([]);
  expect(restored.e2e_fixture.synthetic_design_calls).toBe(0);
  await showEvidence(app);
  await expect(page.locator('#remediation-list')).toContainText('Pruebas declaradas');
});

test('habilidades: per-profile capability target changes invalidate review and discard keeps assignments empty', async ({ app }) => {
  const { page } = app;
  const item = await createCapability(app, 'E2E discard exact targets');
  const before = await app.state();
  const agents = before.organization.agents;
  await capabilityCard(page, item.id).locator('[data-cap-selection]').check();
  await page.locator('#cap-target-mode').selectOption('selected');
  await expect(page.locator('#cap-preview')).toBeDisabled();
  await expect(page.locator('#cap-target-summary')).toContainText('0 de 4 perfiles');
  await checkProfileTargets(app, [agents[0].id]);
  const firstPlan = await previewCapability(app, item, [agents[0].id],
    { mode: 'selected', agent_ids: [agents[0].id], subteam_ids: [] });
  await page.locator('#cap-target-options [data-cap-target]').nth(2).check();
  await expect(page.locator('#cap-plan-review')).toBeHidden();
  await expect(page.locator('#cap-apply')).toBeDisabled();
  await expect(page.locator('#cap-status')).toContainText('Destinatarios modificados');
  const ids = [agents[0].id, agents[2].id];
  const replacement = await previewCapability(app, item, ids, { mode: 'selected', agent_ids: ids, subteam_ids: [] });
  expect(replacement.id).not.toBe(firstPlan.id);
  await postFromUI(app, 'capability-discard', () => page.locator('#cap-plan-discard').click());
  await expect(page.locator('#cap-plan-review')).toBeHidden();
  await expect(page.locator('#cap-apply')).toBeDisabled();
  const discarded = await app.state();
  expect(discarded.capability_library.plan).toBeNull();
  expect(discarded.capability_library.assignment_page.items).toEqual([]);
  expect(discarded.capability_library.status.revision).toBe(before.capability_library.status.revision);
  expect(discarded.organization).toEqual(before.organization);
  expect(app.requests.filter(path => path === '/api/capability-apply')).toHaveLength(0);
  await page.locator('#cap-clear').click();
  await expect(capabilityCard(page, item.id).locator('[data-cap-selection]')).not.toBeChecked();
  await expect(page.locator('#cap-preview')).toBeDisabled();
});

test('habilidades: per-profile capability apply sends the reviewed hash and persists only exact inactive recipients', async ({ app }) => {
  const { page } = app;
  const item = await createCapability(app, 'E2E exact selected assignment');
  const agents = (await app.state()).organization.agents;
  const ids = [agents[1].id, agents[3].id];
  await capabilityCard(page, item.id).locator('[data-cap-selection]').check();
  await checkProfileTargets(app, ids);
  const plan = await previewCapability(app, item, ids, { mode: 'selected', agent_ids: ids, subteam_ids: [] });
  const applied = await applyCapability(app, plan, item, ids);
  for (const agent of agents.filter(agent => !ids.includes(agent.id))) {
    await expect(page.locator('#cap-assignment-results')).not.toContainText(agent.display_name);
  }
  expect(applied.organization.agents).toEqual(agents);
  const project = await saveProject(app, 'E2E selected assignments');
  const restored = await loadProjectVersion(app, project);
  expect(restored.capability_library.assignment_page.items).toEqual(applied.capability_library.assignment_page.items);
  await page.reload();
  await app.navigate('habilidades');
  await page.locator('[data-cap-tab="assignments"]').click();
  await expect(page.locator('#cap-assignment-results > article')).toHaveCount(2);
  await expect(page.locator('#cap-selection-count')).toContainText('0 capacidades seleccionadas');
  expect((await app.state()).capability_library.status.active_count).toBe(0);
});

test('habilidades: overlapping subteam selections preview and apply the exact deduplicated member union', async ({ app }) => {
  const { page } = app;
  const agents = (await app.state()).organization.agents;
  const teams = [];
  await app.navigate('organigrama');
  await openDetailsFor(page, '#subteam-form');
  for (const [name, members] of [
    ['E2E overlapping team A', [agents[0].id, agents[1].id]],
    ['E2E overlapping team B', [agents[1].id, agents[2].id]]
  ]) {
    await page.locator('#new-subteam').click();
    await page.locator('#subteam-name').fill(name);
    await page.locator('#subteam-type').selectOption('consulting');
    await page.locator('#subteam-scope').fill('Synthetic overlapping-member target checks only.');
    for (const id of members) await page.locator('#subteam-members input[value="' + id + '"]').check();
    await page.locator('#subteam-facilitator').selectOption(members[0]);
    const { state } = await postFromUI(app, 'subteam-save', () => page.locator('#save-subteam').click());
    const team = state.subteams.find(row => row.name === name);
    expect(team.member_ids).toEqual(members);
    teams.push(team);
    await expect(page.locator('#subteam-name')).toHaveValue('');
  }
  const item = await createCapability(app, 'E2E subteam union instruction');
  const teamProfiles = (await app.state()).organization.agents;
  await capabilityCard(page, item.id).locator('[data-cap-selection]').check();
  await page.locator('#cap-target-mode').selectOption('subteams');
  await expect(page.locator('#cap-preview')).toBeDisabled();
  for (const team of teams) {
    await page.locator('#cap-target-options label').filter({ hasText: team.name })
      .locator('[data-cap-target]').check();
  }
  const ids = agents.slice(0, 3).map(agent => agent.id);
  await expect(page.locator('#cap-target-summary')).toContainText('3 de 4 perfiles');
  const plan = await previewCapability(app, item, ids,
    { mode: 'subteams', agent_ids: [], subteam_ids: teams.map(team => team.id) });
  expect(plan.preview.assignment_preview.selection).toEqual({ mode: 'selected', agent_ids: ids });
  const applied = await applyCapability(app, plan, item, ids);
  expect(applied.capability_library.status.assigned_count).toBe(3);
  expect(applied.capability_library.status.assigned_agent_count).toBe(3);
  await expect(page.locator('#cap-assignment-results')).not.toContainText(agents[3].display_name);
  expect(applied.organization.agents).toEqual(teamProfiles);
});

test('habilidades: editing a saved local capability creates an immutable new content version without reassigning the original', async ({ app }) => {
  const { page } = app;
  const original = await createCapability(app, 'E2E immutable local instruction', 'Original synthetic instructions.');
  const agents = (await app.state()).organization.agents;
  await capabilityCard(page, original.id).locator('[data-cap-selection]').check();
  await checkProfileTargets(app, [agents[1].id]);
  const plan = await previewCapability(app, original, [agents[1].id],
    { mode: 'selected', agent_ids: [agents[1].id], subteam_ids: [] });
  const applied = await applyCapability(app, plan, original, [agents[1].id]);
  await page.locator('[data-cap-tab="library"]').click();
  await capabilityCard(page, original.id).getByRole('button', { name: 'Editar copia local', exact: true }).click();
  await expect(page.locator('#cap-manual-id')).toHaveValue(original.id);
  await expect(page.locator('#cap-manual-name')).toHaveValue(original.name);
  await expect(page.locator('#cap-manual-instructions')).toHaveValue(original.content);
  await page.locator('#cap-manual-instructions').fill('Revised synthetic instructions with an explicit evidence checklist.');
  const { body, state } = await postFromUI(app, 'capability-save', () => page.locator('#cap-manual-save').click());
  expect(body.item.id).toBeUndefined();
  const copies = state.capability_library.page.items.filter(row => row.name === original.name);
  expect(copies).toHaveLength(2);
  expect(copies.find(row => row.id === original.id)).toEqual(original);
  const revised = copies.find(row => row.id !== original.id);
  expect(revised.content_hash).not.toBe(original.content_hash);
  expect(revised).toMatchObject({ content: body.item.content, installed: false, runtime_verified: false, permission_grant: false });
  expect(state.capability_library.assignment_page.items).toEqual(applied.capability_library.assignment_page.items);
  expect(state.capability_library.status.active_count).toBe(0);
  await expect(page.locator('#cap-manual-name')).toHaveValue('');
  await expect(page.locator('#cap-plan-review')).toBeHidden();
  await page.reload();
  await app.navigate('habilidades');
  await page.locator('[data-cap-tab="library"]').click();
  await expect(page.locator('#cap-library-results > article')).toHaveCount(2);
  expect((await app.state()).capability_library.page.items.filter(row => row.name === original.name)).toEqual(copies);
});

test('habilidades: manual capability references reject unsafe URL forms locally and editor reset has no write', async ({ app }) => {
  const { page } = app;
  await app.navigate('habilidades');
  await page.locator('[data-cap-tab="library"]').click();
  await openDetailsFor(page, '#cap-manual-form');
  await page.locator('#cap-manual-name').fill('E2E unvisited references');
  await page.locator('#cap-manual-description').fill('A locally recorded reference, never fetched.');
  await page.locator('#cap-manual-instructions').fill('Read only synthetic material during this acceptance suite.');
  for (const reference of ['http://example.invalid/reference', 'https://example.invalid/reference?query=synthetic',
    'https://example.invalid/reference#fragment']) {
    await page.locator('#cap-manual-references').fill(reference);
    await page.locator('#cap-manual-save').click();
    await expect(page.locator('#notice')).toContainText('Cada referencia debe ser una URL HTTPS sin credenciales, parámetros ni fragmentos.');
    expect(app.requests.filter(path => path === '/api/capability-save')).toHaveLength(0);
    expect((await app.state()).capability_library.status.item_count).toBe(0);
  }
  await page.locator('#cap-manual-references').fill('https://example.invalid/synthetic-reference');
  const { state } = await postFromUI(app, 'capability-save', () => page.locator('#cap-manual-save').click());
  expect(state.capability_library.page.items[0].provenance.evidence)
    .toContain('Referencias no consultadas: https://example.invalid/synthetic-reference');
  await page.locator('#cap-manual-name').fill('E2E discarded draft');
  await page.locator('#cap-manual-type').selectOption('memory_policy');
  await page.locator('#cap-manual-description').fill('Discard this draft.');
  await page.locator('#cap-manual-instructions').fill('Never saved.');
  await page.locator('#cap-manual-references').fill('https://example.invalid/discarded');
  await page.locator('#cap-manual-reset').click();
  for (const id of ['cap-manual-id', 'cap-manual-name', 'cap-manual-description', 'cap-manual-instructions', 'cap-manual-references']) {
    await expect(page.locator('#' + id)).toHaveValue('');
  }
  await expect(page.locator('#cap-manual-type')).toHaveValue('skill_instructions');
  expect(app.requests.filter(path => path === '/api/capability-save')).toHaveLength(1);
  expect((await app.state()).capability_library.page.items).toEqual(state.capability_library.page.items);
  expect((await app.state()).e2e_fixture.synthetic_inventory_calls).toBe(0);
});
