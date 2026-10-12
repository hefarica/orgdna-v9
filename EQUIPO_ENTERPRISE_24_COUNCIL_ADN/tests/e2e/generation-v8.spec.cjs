'use strict';
// Authored UI-only snapshots. Browser execution remains NOT_RUN until an authorized run.
const { test, expect } = require('./fixtures.cjs');

async function showSnapshot(app, modify) {
  const snapshot = await app.state();
  modify(snapshot);
  await app.page.route('**/api/state', route => route.fulfill({ json: snapshot }));
  await app.page.reload();
  await expect(app.page.locator('#notice')).not.toContainText('Conectando');
  return snapshot;
}

function receiptJob(status) {
  return { job_id:'v8-render-only', status, stage:status, provider:'deepseek-official', model:'deepseek-flash', sent_requests:1, completed_requests:0, max_requests:2, potentially_billed:true,
    usage_summary:{prompt_tokens:73,completion_tokens:19,total_tokens:92,known_requests:1,unknown_requests:0},
    request_receipts:[{index:1,status:'response_received_not_yet_validated',usage:{prompt_tokens:73,completion_tokens:19,total_tokens:92},latency_ms:412,http_status:200,error_code:'invalid_json',payload_sha256:'a'.repeat(64),response_id_sha256:'b'.repeat(64),max_output_tokens:15424,raw_response:'UNSAFE_V8_SENTINEL'}] };
}

test('v8 generation: choose an exact API ID while display name and preserved DSH alias remain distinct', async ({ app }) => {
  const snapshot = await showSnapshot(app, state => {
    state.config.provider='deepseek-official';state.config.model='DeepSeek-V41-Flash';
    state.organization.agents.forEach(a => { a.provider='deepseek-official';a.model='DeepSeek-V41-Flash'; });
    state.models=[{provider:'deepseek-official',model:'deepseek-flash',name:'DeepSeek-V4.1-Flash',available:true,source:'live_api',catalog_scope:'provider_api'}];
  });
  const oldRoutes = snapshot.organization.agents.map(a => [a.provider,a.model]);
  await expect(app.page.locator('#generation-model-status')).toContainText('aún no está verificado');
  await expect(app.page.locator('#generation-model-select')).toContainText('DeepSeek-V4.1-Flash');
  await app.page.locator('#generation-model-select').selectOption('deepseek-flash');
  await expect(app.page.locator('#config-form [name="model"]')).toHaveValue('deepseek-flash');
  await expect(app.page.locator('#config-form [name="provider"]')).toHaveValue('deepseek-official');
  await expect(app.page.locator('#generation-model-identity')).toContainText('DeepSeek-V41-Flash');
  expect(snapshot.organization.agents.map(a => [a.provider,a.model])).toEqual(oldRoutes);
  expect(app.requests.filter(p => p === '/api/generation-plan' || p === '/api/generation-confirm' || p === '/api/discover-models')).toHaveLength(0);
});

test('v8 generation: preview separates requested nominal and per-batch limits, estimated input, unknown cost and evidence', async ({ app }) => {
  await showSnapshot(app, state => {
    state.config.llm_budget_usd=0;
    state.generation_job={job_id:'v8-plan',status:'awaiting_consent',stage:'review',sent_requests:0,max_requests:2};
    state.pending_consent={job_id:'v8-plan',approval_id:'v8-approval',payload_sha256:'c'.repeat(64),coverage_sha256:'d'.repeat(64),config_version:7,partial_inventory_required:true,requested_max_output_tokens:16384,max_output_tokens:16384,max_total_output_tokens:18848,estimated_input_tokens:1020,coverage_review:{inventory_complete:false,coverage:{whole_repository_content_complete:false,inventory:{pending_subtrees:2,pending_subtree_paths:['pending/module']}}},preview:{files:[{path:'src/main.py',family:'implementation',module:'src',bytes:512,content_sha256:'e'.repeat(64)}]},evidence_distribution:{strategy:'common_plus_targeted',unique_read_paths:2,sent_file_occurrences:2,full_repeat_file_occurrences:4,omitted_from_all_batches:['not-sent.txt'],heuristic_only:true},requests:[{index:1,slots:[1,2,3,4,5,6],max_output_tokens:15424,estimated_input_tokens:700,evidence_paths:['src/main.py'],evidence_package:{common_paths:[],targeted_paths:['src/main.py'],omitted_read_paths:['not-sent.txt']}},{index:2,slots:[7],max_output_tokens:3424,estimated_input_tokens:320}]};
  });
  const summary=app.page.locator('#generation-preview-summary');
  for (const text of ['16384','15424','18848','1020','No calculado','Sin referencia definida']) await expect(summary).toContainText(text);
  await expect(summary).not.toContainText('0 USD');
  await expect(app.page.locator('#generation-partial-notice')).toBeVisible();
  await app.page.locator('#generation-batch-details > summary').click();
  await expect(app.page.locator('#generation-batch-list')).toContainText('src/main.py');
  await expect(app.page.locator('#generation-evidence-summary')).toContainText('pending/module');
  await expect(app.page.locator('#generation-preview input[type="checkbox"]')).toHaveCount(1);
  await expect(app.page.locator('#confirm-generation')).toBeDisabled();
});

for (const status of ['failed','cancelled','completed']) {
  test(`v8 generation: ${status} keeps safe observed usage and distinguishes it from billing`, async ({ app }) => {
    await showSnapshot(app, state => { state.pending_consent=null;state.generation_job=receiptJob(status);state.generation_diagnostic_available=true; });
    await expect(app.page.locator('#generation-usage')).toBeVisible();
    await expect(app.page.locator('#generation-request-receipts')).toContainText('73 / 19 / 92');
    await expect(app.page.locator('#generation-usage')).not.toContainText('UNSAFE_V8_SENTINEL');
    await expect(app.page.locator('#generation-usage-summary')).toContainText('No calculado');
    await expect(app.page.locator('#generation-diagnostic-download')).toBeEnabled();
    expect(app.requests.filter(p => p === '/api/generation-confirm')).toHaveLength(0);
  });
}

test('v8 generation: a cancelled pending receipt continues local polling and unknown usage is not zero', async ({ app }) => {
  let reads=0;
  const snapshot=await app.state();snapshot.pending_consent=null;snapshot.generation_job=receiptJob('cancelled');snapshot.generation_job.receipts_pending=true;
  snapshot.generation_job.usage_summary={prompt_tokens:null,completion_tokens:null,total_tokens:null,known_requests:0,unknown_requests:1};snapshot.generation_job.request_receipts[0].usage={};
  await app.page.route('**/api/state', route => { reads++;return route.fulfill({json:snapshot}); });
  await app.page.reload();
  await expect(app.page.locator('#generation-usage-note')).toContainText('Recibo pendiente');
  await expect(app.page.locator('#generation-request-receipts')).toContainText('No informado / No informado / No informado');
  await expect.poll(() => reads).toBeGreaterThan(1);
  snapshot.generation_job.receipts_pending=false;snapshot.generation_job.usage_summary={prompt_tokens:73,completion_tokens:19,total_tokens:92,known_requests:1,unknown_requests:0};
  await expect(app.page.locator('#generation-usage-summary')).toContainText('Tokens reales totales92');
  expect(app.requests.filter(p => p === '/api/generation-confirm')).toHaveLength(0);
});

test('v8 generation: documented Z.AI selection requires its own acknowledgement and changing ID clears it', async ({ app }) => {
  await showSnapshot(app, state => {
    state.config.provider='zai';state.config.model='glm-5.3';state.credentials_configured=['zai'];state.generation_job=null;state.pending_consent=null;
    state.models=['glm-5.3','glm-5.3-flash'].map(model => ({provider:'zai',model,source:'official_docs_snapshot',available:null,catalog_scope:'provider_api'}));
  });
  await expect(app.page.locator('#generation-manual-model-label')).toBeVisible();
  await app.page.locator('#prepare-generation').click();
  expect(app.requests.filter(p => p === '/api/generation-plan')).toHaveLength(0);
  await app.page.locator('#generation-manual-model').check();
  await app.page.locator('#generation-model-select').selectOption('glm-5.3-flash');
  await expect(app.page.locator('#generation-manual-model')).not.toBeChecked();
  await expect(app.page.locator('#generation-model-status')).toContainText('sin verificar');
});
