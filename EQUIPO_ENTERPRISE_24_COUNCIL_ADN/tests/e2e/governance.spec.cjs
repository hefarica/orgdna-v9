'use strict';
const { test, expect, openDetailsFor, acceptNextDialog } = require('./fixtures.cjs');

async function submitPerformance(app, task = 'e2e-delivery', coauthor = false) {
  const { page } = app;
  await app.navigate('perfiles');
  await openDetailsFor(page, '#performance-form');
  const current = await app.state(), aid = current.organization.agents.at(-1).id;
  await page.locator('#performance-agent').selectOption(aid);
  const values = { task_id: task, title: 'E2E recorded ' + task, comparison_group: 'e2e-comparable',
    budget: '10', budget_unit: 'minutes', candidate_sha: 'a'.repeat(40),
    acceptance_criteria: 'Criterion one\nCriterion two', evidence: 'fixture://delivery/' + task };
  for (const [name, value] of Object.entries(values)) await page.locator(`#performance-form [name="${name}"]`).fill(value);
  if (coauthor) await page.locator('#performance-authors input').first().check();
  await page.locator('#performance-form button[type="submit"]').click();
  await expect(page.locator('#performance-form [name="task_id"]')).toHaveValue('');
  await expect(page.locator('#performance-form')).not.toHaveAttribute('data-base-version', /.+/);
  await expect(page.locator('#notice')).toContainText('Entregable registrado.');
  await expect.poll(async () => (await app.state()).performance_records.some(row => row.task_id === task)).toBe(true);
  const row = (await app.state()).performance_records.find(row => row.task_id === task);
  expect(row.acceptance_criteria).toEqual(['Criterion one', 'Criterion two']);
  expect(row).toMatchObject({ agent_id: aid, task_id: task, title: values.title,
    comparison_group: values.comparison_group, budget: 10, budget_unit: values.budget_unit,
    candidate_sha: values.candidate_sha, evidence: [values.evidence] });
  expect(row.tests_executed_by_app).toBe(false);
  expect(row.evidence_verified_by_app).toBe(false);
  expect(row.status).toBe('awaiting_independent_review');
  expect(row.reviews).toEqual([]);
  return row;
}

async function fillReview(app, row, quality = 2) {
  const { page } = app;
  await openDetailsFor(page, '#performance-review-form');
  await page.locator('#review-performance').selectOption(row.id);
  await page.locator('#reviewer-id').selectOption('EXTERNAL');
  await expect(page.locator('#external-reviewer-fields')).toBeVisible();
  await page.locator('#external-reviewer-id').fill('e2e.synthetic-reviewer');
  await page.locator('#external-reviewer-name').fill('Synthetic fixture reviewer');
  await page.locator('#external-reviewer-evidence').fill('fixture://appointment/manual-only');
  const values = { quality_numerator: String(quality), compliance_numerator: '2', compliance_denominator: '2',
    efficiency_actual: '10', collaboration_numerator: '2', collaboration_denominator: '2',
    evidence_numerator: '2', evidence_denominator: '2', rationale: 'Synthetic manual review; no tests executed.',
    evidence: 'fixture://review/including-negative-results' };
  for (const [name, value] of Object.entries(values)) await page.locator(`#performance-review-form [name="${name}"]`).fill(value);
  await expect(page.locator('#performance-review-form [name="quality_denominator"]')).toHaveValue('2');
  await expect(page.locator('#performance-review-form [name="quality_denominator"]')).toHaveAttribute('readonly', '');
  await expect(page.locator('#performance-review-form [name="efficiency_budget"]')).toHaveValue('10');
  await expect(page.locator('#performance-review-form [name="efficiency_budget"]')).toHaveAttribute('readonly', '');
}
async function saveReview(app, row, quality = 2) {
  await fillReview(app, row, quality);
  await app.page.locator('#review-no-conflict').check();
  await app.page.locator('#review-includes-failures').check();
  const count = (await app.state()).performance_records.find(item => item.id === row.id).reviews.length;
  await app.page.locator('#performance-review-form button[type="submit"]').click();
  await expect(app.page.locator('#performance-review-form [name="rationale"]')).toHaveValue('');
  await expect(app.page.locator('#performance-review-form')).not.toHaveAttribute('data-base-version', /.+/);
  await expect(app.page.locator('#notice')).toContainText('Revisión manual registrada.');
  await expect.poll(async () => (await app.state()).performance_records.find(item => item.id === row.id).reviews.length).toBe(count + 1);
  return (await app.state()).performance_records.find(item => item.id === row.id);
}
async function fillPromotion(app, row, kind) {
  const { page } = app;
  await openDetailsFor(page, '#promotion-form');
  await page.locator('#promotion-score').selectOption(JSON.stringify([row.agent_id, row.comparison_group]));
  await page.locator('#promotion-form [name="kind"]').selectOption(kind);
  await page.locator('#promotion-target').selectOption('OWNER_EXTERNAL');
  await page.locator('#promotion-form [name="recommendation"]').fill('Synthetic proposed ' + kind + '; no runtime authority.');
  await page.locator('#promotion-form [name="evidence"]').fill('fixture://proposal/reviewed-data');
}
async function decide(app, row, status) {
  const { page } = app;
  await openDetailsFor(page, '#promotion-review-form');
  await page.locator('#promotion-record').selectOption(row.id);
  await page.locator('#promotion-status').selectOption(status);
  await page.locator('#promotion-review-form [name="note"]').fill('Synthetic declared ' + status);
  await page.locator('#promotion-review-form [name="evidence"]').fill('fixture://decision/manual-only');
  await page.locator('#promotion-no-conflict').check();
  await page.locator('#promotion-review-form button[type="submit"]').click();
  await expect(page.locator('#promotion-review-form [name="note"]')).toHaveValue('');
  await expect(page.locator('#promotion-review-form')).not.toHaveAttribute('data-base-version', /.+/);
  await expect(page.locator('#notice')).toContainText('Decisión manual registrada.');
  await expect.poll(async () => (await app.state()).promotion_records.find(item => item.id === row.id).status).toBe(status);
}

test('governance: evidence has no score until independent review; correction preserves history', async ({ app }) => {
  const { page } = app;
  const row = await submitPerformance(app, 'e2e-with-coauthor', true);
  expect(row.author_ids).toContain((await app.state()).organization.agents[0].id);
  expect((await app.state()).scoreboard.rows.find(item => item.agent_id === row.agent_id && item.comparison_group === row.comparison_group).score).toBeNull();
  await fillReview(app, row);
  const choices = await page.locator('#reviewer-id option').evaluateAll(items => items.map(item => item.value));
  for (const author of row.author_ids) expect(choices).not.toContain(author);
  expect(choices).not.toContain('OWNER_EXTERNAL');
  await page.locator('#performance-review-form button[type="submit"]').click();
  expect((await app.state()).performance_records[0].reviews).toEqual([]);
  expect(app.requests.filter(path => path === '/api/performance-review')).toHaveLength(0);
  const first = await saveReview(app, row);
  expect(first.reviews[0]).toMatchObject({ score: 100, reviewer_id: 'EXTERNAL:e2e.synthetic-reviewer',
    external_reviewer_name: 'Synthetic fixture reviewer', appointed_by: 'OWNER_EXTERNAL',
    appointment_evidence: ['fixture://appointment/manual-only'], conflict_of_interest: false, includes_failures: true,
    dimensions: { quality: 100, compliance: 100, efficiency: 100, collaboration: 100, evidence: 100 },
    evidence_verified_by_app: false });
  const corrected = await saveReview(app, row, 1);
  expect(corrected.reviews).toHaveLength(2);
  expect(corrected.reviews[0]).toEqual(first.reviews[0]);
  expect(corrected.reviews[1].supersedes_review_id).toBe(first.reviews[0].id);
  expect(corrected.reviews[1].score).toBe(85);
  const score = (await app.state()).scoreboard.rows.find(item => item.agent_id === row.agent_id && item.comparison_group === row.comparison_group);
  expect(score.score).toBe(85); expect(score.sample_count).toBe(1); expect(score.promotion_eligible).toBe(false);
  await page.reload();
  await openDetailsFor(page, '#governance-records');
  await expect(page.locator('#governance-records')).toContainText('score 85');
  await page.locator('#merit-ranking button').filter({ hasText: (await app.state()).organization.agents.at(-1).display_name }).click();
  await expect(page.locator('#profile-dialog')).toBeVisible();
  await page.locator('#close-inspector').click();
});

test('governance: duplicate task and stale form reject atomically; discard refreshes draft version', async ({ app }) => {
  const { page } = app;
  const row = await submitPerformance(app);
  await page.locator('#performance-form [name="task_id"]').fill(row.task_id);
  for (const [name, value] of Object.entries({ title: 'Duplicate', comparison_group: row.comparison_group, budget: '10', budget_unit: 'minutes', candidate_sha: row.candidate_sha, acceptance_criteria: 'One', evidence: 'fixture://duplicate' })) {
    await page.locator(`#performance-form [name="${name}"]`).fill(value);
  }
  const prior = (await app.state()).performance_records;
  await app.expectActionError('/api/performance-create', () => page.locator('#performance-form button').click(), /task_id ya registrado/);
  expect((await app.state()).performance_records).toEqual(prior);
  await page.locator('#performance-form [name="task_id"]').fill('new-stale-draft');
  const version = await page.locator('#performance-form').getAttribute('data-base-version');
  await page.locator('.profile-card').first().click();
  await page.locator('#agent-name').fill('Synthetic changed profile');
  await page.locator('#save-profile').click();
  await expect(page.locator('#profile-dialog')).toBeHidden();
  expect((await app.state()).organization.state_version).toBeGreaterThan(Number(version));
  await app.expectActionError('/api/performance-create', () => page.locator('#performance-form button').click(), /Versión/);
  expect((await app.state()).performance_records).toEqual(prior);
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('#reset-governance-drafts').click();
  await expect(page.locator('#performance-form [name="task_id"]')).toHaveValue('new-stale-draft');
  await acceptNextDialog(page, () => page.locator('#reset-governance-drafts').click());
  await expect(page.locator('#performance-form [name="task_id"]')).toHaveValue('');
  expect(await page.locator('#performance-form').getAttribute('data-base-version')).toBeNull();
  expect((await app.state()).performance_records).toEqual(prior);
});

for (const kind of ['promotion', 'succession']) {
  test(`governance: ${kind} refuses one perfect sample without changing authority`, async ({ app }) => {
    const row = await submitPerformance(app);
    await saveReview(app, row);
    const before = (await app.state()).organization.agents;
    await fillPromotion(app, row, kind);
    await app.expectActionError('/api/promotion-create', () => app.page.locator('#promotion-form button').click(), /umbrales\/muestras/);
    expect((await app.state()).promotion_records).toEqual([]);
    expect((await app.state()).organization.agents).toEqual(before);
  });
}

test('governance: recognition requires supervisor then Owner declaration and changes no hierarchy or permissions', async ({ app }) => {
  const row = await submitPerformance(app);
  await saveReview(app, row);
  const before = (await app.state()).organization.agents;
  await fillPromotion(app, row, 'recognition');
  await app.page.locator('#promotion-form button').click();
  await expect(app.page.locator('#promotion-form [name="recommendation"]')).toHaveValue('');
  await expect(app.page.locator('#notice')).toContainText('Propuesta de desarrollo registrada;');
  await expect.poll(async () => (await app.state()).promotion_records.length).toBe(1);
  const proposal = (await app.state()).promotion_records[0];
  await openDetailsFor(app.page, '#promotion-review-form');
  await app.page.locator('#promotion-record').selectOption(proposal.id);
  await expect(app.page.locator('#promotion-status option[value="owner_approved"]')).toHaveCount(0);
  await decide(app, proposal, 'supervisor_reviewed');
  await decide(app, proposal, 'owner_approved');
  const final = await app.state(), saved = final.promotion_records[0];
  expect(saved.events.map(event => event.status)).toEqual(['supervisor_reviewed', 'owner_approved']);
  expect(saved.events[1].reviewer_id).toBe('OWNER_EXTERNAL');
  for (const flag of ['runtime_changed', 'permissions_changed', 'hierarchy_applied']) expect(saved[flag]).toBe(false);
  expect(final.organization.agents).toEqual(before);
  await expect(app.page.locator('#promotion-record option').filter({ hasText: 'Reconocimiento' })).toHaveCount(0);
});

test('governance: five reviewed samples permit promotion proposal and Owner rejection closes it', async ({ app }) => {
  test.setTimeout(120000);
  let row;
  for (let i = 0; i < 5; i++) { row = await submitPerformance(app, 'sample-' + i); await saveReview(app, row); }
  const before = (await app.state()).organization.agents;
  const score = (await app.state()).scoreboard.rows.find(item => item.agent_id === row.agent_id && item.comparison_group === row.comparison_group);
  expect(score.sample_count).toBe(5); expect(score.promotion_eligible).toBe(true);
  await fillPromotion(app, row, 'promotion');
  await app.page.locator('#promotion-form button').click();
  await expect(app.page.locator('#promotion-form [name="recommendation"]')).toHaveValue('');
  await expect(app.page.locator('#notice')).toContainText('Propuesta de desarrollo registrada;');
  await expect.poll(async () => (await app.state()).promotion_records.length).toBe(1);
  const proposal = (await app.state()).promotion_records[0];
  await decide(app, proposal, 'rejected');
  const final = await app.state();
  expect(final.promotion_records[0].events[0].reviewer_id).toBe('OWNER_EXTERNAL');
  expect(final.organization.agents).toEqual(before);
  expect(final.e2e_fixture.synthetic_design_calls).toBe(0);
});
