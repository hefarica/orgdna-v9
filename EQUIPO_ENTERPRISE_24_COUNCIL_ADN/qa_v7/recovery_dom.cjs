/* Independent V7 DOM lifecycle checks. Minimal DOM; no browser/layout claim. */
'use strict';
const fs0=require('fs'),path0=require('path');
const harnessPath=path0.resolve(__dirname,'../qa_v3/frontend_generation_dom.cjs');
let prefix=fs0.readFileSync(harnessPath,'utf8').split('(async()=>{for(let i=0;i<8;i++)await Promise.resolve();')[0];
prefix=prefix.replace('vm.createContext(context);','context.crypto=require("crypto").webcrypto;context.clearTimeout=()=>{};vm.createContext(context);');
const checks=String.raw`
(async()=>{
 for(let i=0;i<8;i++)await Promise.resolve();
 const exec=s=>vm.runInContext(s,context),el=id=>document.querySelector(id),posts=()=>requests.filter(r=>r.opts?.method==='POST');
 assert(requests.every(r=>!r.opts||r.opts.method!=='POST'),'Startup cannot prepare, confirm, retry, or restore');
 const failed=structuredClone(fixture);failed.generation_stale=true;failed.config.repo_name='Pending new draft';failed.pending_consent=null;
 failed.design_recovery={available:true,can_restore:true,requires_restore:true,snapshot_id:'independent-snapshot',expected_config_version:17,config:fixture.config,agent_count:fixture.organization.agents.length};
 failed.generation_job={job_id:'independent-failed-job',status:'failed',stage:'failed',failed_stage:'api_design',progress:30,sent_requests:1,completed_requests:0,max_requests:3,potentially_billed:true,error:{code:'invalid_json',category:'invalid_response',message:'Invalid JSON <img src=x onerror=alert(1)>',next_action:'Prepare a new reviewed plan'}};
 failed.generation_diagnostic_available=true;mockState=structuredClone(failed);
 exec('generationOperation=false;generationCancelPending=false;generationReviewStale=false;configDirty=false;busy=false;');await exec('readGenerationState()');
 assert.equal(document.querySelectorAll('img').length,0,'Adversarial diagnostic text must stay inert');
 const failedPosts=posts().length;exec('render();render();');assert.equal(posts().length,failedPosts,'Repeated error rendering cannot trigger requests');
 assert.equal(el('#generation-percent').textContent,'30%');assert.equal(el('#restore-design').disabled,false);
 // An old GET begun before restore must not re-block exports after restore wins.
 let releaseOld;mockControls.deferGet=new Promise(resolve=>releaseOld=resolve);const oldPoll=exec('readGenerationState()');
 const restored=structuredClone(failed);restored.config=structuredClone(fixture.config);restored.generation_stale=false;restored.design_recovery={...failed.design_recovery,can_restore:false,requires_restore:false,draft_config:failed.config};mockState=restored;
 await Promise.all([exec('restoreDesign()'),exec('restoreDesign()')]);assert.equal(posts().length,failedPosts+1);assert.equal(posts().at(-1).url,'/api/design-restore');
 releaseOld({ok:true,json:async()=>structuredClone(failed)});await oldPoll;
 assert.equal(exec('state.generation_stale'),false,'A stale poll must not undo successful recovery');
 assert.equal(el('#recovery-exports').hidden,false);assert.equal(el('#restore-design').hidden,true);
 // A dismissed restore confirmation does no POST and leaves the pending state.
 mockState=structuredClone(failed);await exec('readGenerationState()');context.confirm=()=>false;const beforeDismiss=posts().length;await exec('restoreDesign()');assert.equal(posts().length,beforeDismiss);assert.equal(exec('state.generation_stale'),true);context.confirm=()=>true;
 // Double retry prepares once, keeps exact model/N and starts with empty approval.
 exec("state.credentials_configured=['deepseek-official'];$('#config-form').elements.repo_url.value='https://github.com/example/v7';$('#generation-tokens').value='32768';$('#generation-batch').value='1';$('#generation-response-mode').value='text';");
 const reviewed=structuredClone(failed);reviewed.credentials_configured=['deepseek-official'];reviewed.generation_job={job_id:'independent-new-job',status:'awaiting_consent',stage:'review',progress:25,config_version:18};reviewed.pending_consent={job_id:'independent-new-job',approval_id:'independent-approval',payload_sha256:'payload-A',coverage_sha256:'coverage-A',config_version:18,partial_inventory_required:true,agent_count:fixture.organization.agents.length,max_requests:4,max_output_tokens:32768,max_total_output_tokens:131072,provider:'deepseek',model:fixture.config.model};mockState=reviewed;
 const beforeRetry=posts().length;await Promise.all([exec('prepareGeneration()'),exec('prepareGeneration()')]);assert.equal(posts().length,beforeRetry+1);assert.equal(posts().at(-1).url,'/api/generation-plan');
 assert.equal(el('#generation-consent').checked,false);assert.equal(el('#confirm-generation').disabled,true);
 el('#generation-consent').checked=true;exec('updateGenerationControls()');assert.equal(el('#confirm-generation').disabled,false);
 mockState.pending_consent.coverage_sha256='coverage-B';await exec('readGenerationState()');assert.equal(el('#generation-consent').checked,false);assert.equal(el('#confirm-generation').disabled,true,'Coverage replacement resets the single exact-plan approval');
 assert(posts().every(r=>!r.url.includes('dsh')&&!r.url.includes('harness')&&!r.url.includes('cordis')),'Recovery flow cannot touch DSH routes');
 console.log('PASS independent V7 DOM: no requests from startup/error rendering; inert diagnostics; repeat restore/retry; stale GET after recovery; dismissed recovery; new coverage resets single consent; no DSH routes. Minimal DOM only.');
})().catch(e=>{console.error(e);process.exitCode=1;});
`;
new Function('require','__dirname',prefix+checks)(require,path0.dirname(harnessPath));
