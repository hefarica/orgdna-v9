/* Independent minimal-DOM lifecycle checks; no browser or runtime execution. */
'use strict';
const fs0=require('fs'),path0=require('path');
const harnessPath=path0.resolve(__dirname,'../qa_v3/frontend_generation_dom.cjs');
let prefix=fs0.readFileSync(harnessPath,'utf8').split('(async()=>{for(let i=0;i<8;i++)await Promise.resolve();')[0];
prefix=prefix.replace('vm.createContext(context);','context.crypto=require("crypto").webcrypto;context.clearTimeout=()=>{};vm.createContext(context);');
const checks=String.raw`
(async()=>{
 for(let i=0;i<8;i++)await Promise.resolve();
 const exec=s=>vm.runInContext(s,context),el=id=>document.querySelector(id);
 const first={id:'cat-a',name:'First',category:'tools',description:'Read only'},second={id:'cat-b',name:'Second',category:'tools',description:'Read only'};
 mockState=structuredClone(fixture);mockState.generation_job=null;mockState.pending_consent=null;
 mockState.plugin_shop={catalog:{catalog_sha256:'qa-cat',candidate_count:2},search:{results:[first],total:2,offset:0,next_offset:1}};
 mockState.capability_library={status:{revision:0,item_count:0},page:{items:[],total:0},assignment_page:{items:[],total:0},reference:null};
 exec('generationOperation=false;generationCancelPending=false;generationReviewStale=false;configDirty=false;busy=false;');
 await exec('readGenerationState()');
 exec('capShowTab("library");capChoose('+JSON.stringify(first)+',true,"catalog")');
 mockState.plugin_shop.search={results:[second],total:2,offset:1,next_offset:null};await exec('readGenerationState()');
 exec('capChoose('+JSON.stringify(second)+',true,"catalog")');
 assert.equal(exec('capSelected.size'),2);assert.equal(exec('capTab'),'library');
 assert.deepEqual(Array.from(exec('[...capSelected.values()].map(v=>v.item.id)')),['cat-a','cat-b']);
 const plan={id:'qa-plan',preview:{preview_hash:'qa-plan-hash',assignment_preview:{agent_ids:fixture.organization.agents.map(a=>a.id),changed_count:48,unchanged_count:0,action:'assign'}}};
 mockState.capability_library.plan=plan;const before=requests.length;await el('#cap-preview').onclick();
 const sent=requests.filter(r=>r.opts?.method==='POST').at(-1);assert.equal(sent.url,'/api/capability-preview');assert.deepEqual(JSON.parse(sent.opts.body).candidate_ids,['cat-a','cat-b']);assert.equal(exec('capPlan.id'),'qa-plan');
 assert.equal(mockState.capability_library.status.item_count,0);assert.equal(el('#cap-plan-review').hidden,false);
 await el('#cap-plan-discard').onclick();assert.equal(exec('capPlan'),null);assert.equal(mockState.capability_library.status.item_count,0);
 mockState.plugin_shop.catalog.catalog_sha256='qa-cat-new';await exec('readGenerationState()');assert.equal(exec('capSelected.size'),0);
 // An old read must not resurrect a cancelled AI job after cancellation returns.
 const job={job_id:'qa-ai',status:'running',mode:'ai',stale:false,consent:null,result:null};mockState.capability_recommendations={job};await exec('readGenerationState()');
 let release;mockControls.deferGet=new Promise(resolve=>release=resolve);const pending=exec('pollCapabilityRecommendations()');
 const old=structuredClone(mockState);mockState.capability_recommendations.job={...job,status:'cancelled'};
 await el('#cap-ai-cancel').onclick();assert.equal(exec('state.capability_recommendations.job.status'),'cancelled');
 release({ok:true,json:async()=>old});await pending;
 assert.equal(exec('state.capability_recommendations.job.status'),'cancelled','Late AI poll must not revive cancelled work');
 console.log('PASS independent SkillHub DOM: multi-page selection, tab persistence, inert preview/discard, catalog invalidation, stale AI polling cancellation. No browser rendering.');
})().catch(e=>{console.error(e);process.exitCode=1;});
`;
new Function('require','__dirname',prefix+checks)(require,path0.dirname(harnessPath));
