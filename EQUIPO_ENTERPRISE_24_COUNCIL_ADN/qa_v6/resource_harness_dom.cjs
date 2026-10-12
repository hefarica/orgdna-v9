/* Minimal DOM contracts for resource prerequisites and DSH boundary lights. */
'use strict';
const fs0=require('fs'),path0=require('path');
const harnessPath=path0.resolve(__dirname,'../qa_v3/frontend_generation_dom.cjs');
let prefix=fs0.readFileSync(harnessPath,'utf8').split('(async()=>{for(let i=0;i<8;i++)await Promise.resolve();')[0];
prefix=prefix.replace('vm.createContext(context);','context.crypto=require("crypto").webcrypto;context.clearTimeout=()=>{};vm.createContext(context);');
const checks=String.raw`
(async()=>{
 for(let i=0;i<8;i++)await Promise.resolve();
 const exec=s=>vm.runInContext(s,context),el=id=>document.querySelector(id),body=()=>JSON.parse(requests.filter(r=>r.opts?.method==='POST').at(-1).opts.body);
 mockState=structuredClone(fixture);mockState.generation_job=null;mockState.pending_consent=null;mockState.resource_workflows={job:null,preview:null};
 exec('generationOperation=false;generationCancelPending=false;generationReviewStale=false;configDirty=false;busy=false;');await exec('readGenerationState()');
 assert.equal(el('#resource-baseline').disabled,true,'No source means no resource plan');
 mockState.capability_library.reference={source_url:'https://example.org/reference',source_hash:'a'.repeat(64),item_proposals:[],coverage:{complete:false},evidence:[]};
 mockState.resource_workflows.job={job_id:'qa-resource-ai',status:'awaiting_consent',stale:false,consent:{approval_id:'qa-approval',payload_sha256:'qa-payload'},result:null};await exec('readGenerationState()');
 assert.equal(el('#resource-confirm').disabled,true);const before=requests.length;await el('#resource-confirm').onclick();assert.equal(requests.length,before);
 el('#resource-data-consent').checked=true;exec('updateResourceControls()');assert.equal(el('#resource-confirm').disabled,true);
 el('#resource-cost-consent').checked=true;exec('updateResourceControls()');assert.equal(el('#resource-confirm').disabled,false);
 mockState.resource_workflows.job.status='running';mockState.resource_workflows.job.consent=null;await el('#resource-confirm').onclick();assert.equal(body().approval_id,'qa-approval');assert.equal(body().payload_sha256,'qa-payload');
 let release;mockControls.deferGet=new Promise(resolve=>release=resolve);const poll=exec('pollResourceWorkflows()'),old=structuredClone(mockState);
 mockState.resource_workflows.job.status='cancelled';await el('#resource-cancel').onclick();release({ok:true,json:async()=>old});await poll;assert.equal(exec('resourceState().job.status'),'cancelled');
 const aid=fixture.organization.agents[0].id;
 mockState.resource_workflows={job:{job_id:'qa-role-plan',status:'completed',stale:false,result:{mode_notice:'Propuesta local sin ejecución',agents:[{agent_id:aid,workflow:{role:'QA role',objective:'Review before running',prerequisites:['Verify backend and obtain separate approval'],steps:['Prepare a contract'],deliverables:['manifest.json'],acceptance_tests:['Independent review'],source_ids:['qa-source']}}]}},preview:null};await exec('readGenerationState()');
 assert.equal(el('#resource-results').querySelectorAll('.resource-workflow').length,1);assert(el('#resource-results').textContent.includes('Verify backend'));
 mockState.resource_workflows.preview={preview_hash:'qa-role-preview',changed_count:1};await el('#resource-preview').onclick();assert.deepEqual(body().workflow_agent_ids,[aid]);assert.equal(body().action,'assign');assert.equal(el('#resource-apply').disabled,false);
 el('#resource-assignment-action').value='activate';el('#resource-assignment-action').onchange();assert.equal(el('#resource-apply').disabled,true,'Assignment changes invalidate exact preview');
 // TCP/exit-zero must remain visually independent of authentication and roster.
 mockState.dsh_harness={status:'EXISTING_LISTENER_PAIRING_REQUIRED',plan:{plan_sha256:'qa-harness'},live_connection:false,connection:{identity_verified:false},launcher:{health:[{tcp_listening:true}],run:{status:'EXITED',exit_code:0}},readback:null};await exec('readGenerationState()');
 const lights=el('#harness-lights').children;assert.equal(lights.find(x=>x.textContent.includes('Listener TCP')).dataset.status,'pending');assert.equal(lights.find(x=>x.textContent.includes('Bridge DSH')).dataset.status,'pending');assert.equal(lights.find(x=>x.textContent.includes('Roster')).dataset.status,'pending');
 mockState.dsh_harness={...mockState.dsh_harness,status:'AWAITING_START_APPROVAL'};await exec('readGenerationState()');exec('harnessPreparedInput=harnessInput();renderHarness()');assert.equal(el('#harness-start').disabled,true);
 el('#harness-start-consent').checked=true;exec('updateHarnessControls()');assert.equal(el('#harness-start').disabled,false);
 el('#dsh-launch-exe').value='/changed/launcher.exe';el('#dsh-launch-form').oninput();assert.equal(el('#harness-start').disabled,true,'Changed launcher path invalidates reviewed harness');
 exec('harnessPreparedInput=harnessInput();renderHarness()');el('#harness-port').value='19001';exec('harnessPreparedInput=harnessInput();updateHarnessControls()');el('#harness-code').value='QA_PAIRING_SECRET';el('#harness-pair-consent').checked=true;
 await el('#harness-pair-form').onsubmit({preventDefault(){}});assert.equal(el('#harness-code').value,'');assert.equal(el('#harness-pair-consent').checked,false);assert.equal(body().pairing_code,'QA_PAIRING_SECRET');assert.equal(body().pair_confirmed,true);
 console.log('PASS independent resource/harness DOM: prerequisite source, separate AI approval, stale cancel, role-bound preview, changed action/path invalidation, TCP vs identity/roster lights, pairing secret clearing. No browser/DSH execution.');
})().catch(e=>{console.error(e);process.exitCode=1;});
`;
new Function('require','__dirname',prefix+checks)(require,path0.dirname(harnessPath));
