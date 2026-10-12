/* Executable minimal-DOM tests only. No browser rendering, provider calls or DSH execution. */
'use strict';
const fs0=require('fs'),path0=require('path');
const harnessPath=path0.resolve(__dirname,'../qa_v3/frontend_generation_dom.cjs');
let prefix=fs0.readFileSync(harnessPath,'utf8').split('(async()=>{for(let i=0;i<8;i++)await Promise.resolve();')[0];
prefix=prefix.replace('vm.createContext(context);','context.crypto=require("crypto").webcrypto;context.clearTimeout=()=>{};vm.createContext(context);');
const checks=String.raw`
(async()=>{
 for(let i=0;i<8;i++)await Promise.resolve();
 const exec=s=>vm.runInContext(s,context),el=id=>document.querySelector(id),posts=()=>requests.filter(r=>r.opts?.method==='POST'),body=()=>JSON.parse(posts().at(-1).opts.body);
 let confirmations=0;context.confirm=()=>{confirmations++;return true;};
 mockState=structuredClone(fixture);mockState.generation_stale=true;mockState.config.model='pending-model';
 mockState.design_recovery={available:true,can_restore:true,requires_restore:true,snapshot_id:'snapshot-original',expected_config_version:11,config:fixture.config,agent_count:fixture.organization.agents.length,organization_id:fixture.organization.organization_id,dna_revision:fixture.organization.dna_revision};
 mockState.generation_job={job_id:'failed-job',status:'failed',stage:'failed',failed_stage:'api_design',progress:30,sent_requests:1,completed_requests:0,max_requests:3,completed_profiles:0,potentially_billed:true,provider:'deepseek-official',model:'pending-model',error:{category:'compatibility',code:'unsupported_response_format',message:'El modelo no admite el formato JSON solicitado.',next_action:'Prepara otro plan con formato de texto.',stage:'api_design',field:'response_format',http_status:400,provider_body:'DO_NOT_EXPORT_PROVIDER_BODY',api_key:'DO_NOT_EXPORT_KEY'},request:{payload:'DO_NOT_EXPORT_PAYLOAD'}};
 mockState.pending_consent=null;mockState.generation_diagnostic_available=true;
 exec('generationOperation=false;generationCancelPending=false;generationReviewStale=false;configDirty=false;busy=false;');
 const beforeFailure=posts().length;await exec('readGenerationState()');
 assert.equal(posts().length,beforeFailure,'Rendering a failure cannot retry');
 assert.equal(el('#generation-percent').textContent,'30%');assert(el('#generation-result').textContent.includes('Compatibilidad del modelo'));assert(el('#generation-result').textContent.includes('Solicitudes iniciadas'));assert(el('#generation-result').textContent.includes('formato de texto'));
 assert.equal(el('#design-recovery').hidden,false);assert.equal(el('#restore-design').disabled,false);assert.equal(el('#export-recovery-note').hidden,false);
 const diagnostic=exec('JSON.stringify(generationDiagnostic(state.generation_job))');assert(!diagnostic.includes('DO_NOT_EXPORT'));assert(diagnostic.includes('response_format'));
 assert(!el('#generation-result').textContent.includes('DO_NOT_EXPORT'));assert.equal(el('#generation-diagnostic-download').disabled,false);
 // Report downloads bind to the viewed job and do not trigger inference or restore.
 const originalFetch=context.fetch;let downloaded=[];
 context.URL=class extends URL{static createObjectURL(blob){downloaded.push(blob);return 'blob:fixture';}static revokeObjectURL(){}};
 context.fetch=async(url,opts)=>{if(url.startsWith('/download/generation-diagnostic.json')){requests.push({url,opts});return {ok:true,headers:{get:()=> 'attachment; filename="orgdna-generation-diagnostic-failed-job.json"'},blob:async()=>new Blob(['{"job_id":"failed-job"}'],{type:'application/json'})};}return originalFetch(url,opts);};
 await el('#generation-diagnostic-download').onclick();assert.equal(requests.at(-1).url,'/download/generation-diagnostic.json?job_id=failed-job');assert.equal(posts().length,beforeFailure);assert.equal(downloaded.length,1);
 // Unknown adapter accounting stays explicitly unknown, not zero or free.
 mockState.generation_job.sent_requests=null;await exec('readGenerationState()');assert(el('#generation-result').textContent.includes('No confirmado'));
 // Exact recovery is versioned, double clicks are inert, and DSH endpoints are untouched.
 const savedPending=structuredClone(mockState.config),restored=structuredClone(mockState);restored.config=structuredClone(fixture.config);restored.generation_stale=false;restored.design_recovery={...mockState.design_recovery,can_restore:false,requires_restore:false,draft_config:savedPending};mockState=restored;
 const beforeRestore=posts().length;await Promise.all([exec('restoreDesign()'),exec('restoreDesign()')]);assert.equal(posts().length,beforeRestore+1);assert.equal(posts().at(-1).url,'/api/design-restore');assert.equal(body().snapshot_id,'snapshot-original');assert.equal(body().expected_config_version,11);assert.equal(body().confirmed,true);assert.equal(el('#recovery-exports').hidden,false);assert.equal(el('#resume-design-draft').hidden,false);assert.equal(el('#export-recovery-note').hidden,true);
 // Resuming the saved draft is an explicit config-only operation.
 mockState=structuredClone(restored);mockState.config=savedPending;mockState.generation_stale=true;mockState.design_recovery.requires_restore=true;mockState.design_recovery.can_restore=true;
 await exec('resumeDesignDraft()');assert.equal(posts().at(-1).url,'/api/config');assert.equal(body().config.model,'pending-model');assert.equal(exec('configDirty'),false);
 // A retry prepares a fresh plan with exact options; it never confirms by itself.
 const pending={job_id:'new-job',approval_id:'new-approval',payload_sha256:'fresh-hash',coverage_sha256:'new-coverage',config_version:12,partial_inventory_required:true,provider:'deepseek-official',model:'pending-model',max_requests:30,max_output_tokens:65536,max_total_output_tokens:1966080,profiles_per_request:1,response_mode:'text'};
 exec("state.credentials_configured=['deepseek-official'];$('#config-form').elements.provider.value='deepseek-official';$('#config-form').elements.model.value='pending-model';$('#config-form').elements.repo_url.value='https://github.com/example/repo';$('#generation-tokens').value='65536';$('#generation-batch').value='1';$('#generation-response-mode').value='text';");
 mockState.credentials_configured=['deepseek-official'];mockState.config.provider='deepseek-official';mockState.config.model='pending-model';mockState.config.repo_url='https://github.com/example/repo';mockState.pending_consent=pending;mockState.generation_job={job_id:'new-job',status:'awaiting_consent',stage:'review',progress:25,config_version:12,max_requests:30};
 const beforeRetry=posts().length,consentDialogs=confirmations;await el('#generation-retry').onclick();assert.equal(posts().length,beforeRetry+1);assert.equal(posts().at(-1).url,'/api/generation-plan');assert.equal(body().max_output_tokens,65536);assert.equal(body().profiles_per_request,1);assert.equal(body().response_mode,'text');assert.equal(body().config.model,'pending-model');assert.equal(el('#generation-consent').checked,false);assert.equal(el('#confirm-generation').disabled,true);assert.equal(el('#generation-partial-notice').hidden,false);assert(el('#generation-preview-summary').textContent.includes('1966080'));
 const unapproved=posts().length;await exec('confirmGeneration()');assert.equal(posts().length,unapproved);
 el('#generation-consent').checked=true;exec('updateGenerationControls()');assert.equal(el('#confirm-generation').disabled,false);
 // Changing requested options invalidates approval even with synthetic edits to locked fields.
 el('#generation-batch').value='2';el('#generation-batch').onchange();assert.equal(el('#generation-consent').checked,false);assert.equal(el('#confirm-generation').disabled,true);await exec('confirmGeneration()');assert.equal(posts().length,unapproved);
 exec("generationReviewStale=false;$('#generation-consent').checked=true;");mockState.pending_consent=null;mockState.generation_job.status='running';await exec('confirmGeneration()');assert.equal(body().consent_id,'new-approval');assert.equal(body().coverage_sha256,'new-coverage');assert.equal(body().partial_inventory_acknowledged,true);assert.equal(body().data_reviewed,true);assert.equal(body().budget_acknowledged,true);assert.equal(confirmations,consentDialogs,'One exact-plan checkbox does not add a duplicate modal');
 assert(posts().every(r=>!r.url.includes('dsh')&&!r.url.includes('harness')&&!r.url.includes('cordis')),'Generation recovery must never call DSH integration routes');
 // Invalid limits are rejected locally before preparation; no silent coercion to unlimited.
 mockState.generation_job.status='failed';await exec('readGenerationState()');el('#generation-tokens').value='0';const beforeInvalid=posts().length;await exec('prepareGeneration()');assert.equal(posts().length,beforeInvalid);el('#generation-tokens').value='131073';assert.equal(exec('readGenerationOptions()'),null);el('#generation-tokens').value='4096';el('#generation-batch').value='33';assert.equal(exec('readGenerationOptions()'),null);el('#generation-batch').value='';assert.equal(exec('readGenerationOptions().max_output_tokens'),4096);
 console.log('PASS V7 recovery DOM: safe diagnostics, job-bound download, honest attempt counts, exact versioned restore, saved draft resume, fresh-plan retry, bounded options, one consent, coverage/option invalidation, duplicate clicks, no DSH routes. Minimal DOM only; no browser visual QA.');
})().catch(e=>{console.error(e);process.exitCode=1;});
`;
new Function('require','__dirname',prefix+checks)(require,path0.dirname(harnessPath));
