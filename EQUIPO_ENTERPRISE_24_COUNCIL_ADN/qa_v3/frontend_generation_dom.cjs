/* Minimal DOM fixture smoke test. No browser, layout engine, network or visual QA. */
'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert'),cp=require('child_process'),path=require('path');
const root=path.resolve(__dirname,'..');
class Element {
 constructor(tag){this.tagName=tag.toLowerCase();this.attrs={};this.children=[];this.parent=null;this.dataset={};this._value=undefined;this._text='';this.events={};this.disabled=false;this.checked=false;this.hidden=false;this.open=false;this.scrollTop=0;this.scrollLeft=0;this.clientWidth=1000;this.clientHeight=610;this.className='';this.style={};this.classList={toggle:(name,on)=>{const s=new Set(this.className.split(' ').filter(Boolean));if(on===undefined)on=!s.has(name);on?s.add(name):s.delete(name);this.className=[...s].join(' ');}};}
 set textContent(x){this._text=String(x);this.children=[];}get textContent(){return this._text+this.children.map(x=>x.textContent||'').join('');}
 set value(x){this._value=String(x);}get value(){if(this.tagName==='select'){const options=this.options;if(this._value!==undefined)return options.some(o=>o.value===this._value)?this._value:'';return options.find(o=>o.attrs.selected!==undefined)?.value||options[0]?.value||'';}return this._value??this.attrs.value??'';}
 setAttribute(k,v){this.attrs[k]=String(v);if(k==='content')this.content=String(v);if(k==='class')this.className=String(v);if(k==='value')this._value=String(v);if(k.startsWith('data-'))this.dataset[k.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=String(v);}
 getAttribute(k){return k==='class'?this.className:this.attrs[k]??null;}removeAttribute(k){delete this.attrs[k];}
 append(...els){for(const el of els){el.parent=this;this.children.push(el);}}replaceChildren(...els){this.children=[];this._text='';this.append(...els);if(this.tagName==='select')this._value=undefined;}
 addEventListener(k,f){this.events[k]=f;}scrollIntoView(){}showModal(){this.open=true;}close(){this.open=false;}click(){if(this.onclick)this.onclick();}remove(){if(this.parent)this.parent.children=this.parent.children.filter(x=>x!==this);}reportValidity(){return true;}reset(){for(const el of this.querySelectorAll('input').concat(this.querySelectorAll('textarea'))){el.value='';el.checked=false;}}
 get options(){return this.querySelectorAll('option');}get elements(){const rows=all(this).filter(el=>el.attrs.name);return new Proxy({namedItem:n=>rows.find(el=>el.attrs.name===n)}, {get:(o,k)=>k in o?o[k]:rows.find(el=>el.attrs.name===k)});}
 querySelector(s){return this.querySelectorAll(s)[0]||null;}querySelectorAll(s){const parts=s.split(/\s+/);return all(this).filter(el=>match(el,parts.at(-1))&&(!parts[0]||parts.length===1||ancestor(el,parts.slice(0,-1).join(' '))));}
}
function all(el){return el.children.flatMap(child=>[child,...all(child)]);}
function ancestor(el,s){return el.parent&&(match(el.parent,s)||ancestor(el.parent,s));}
function match(el,s){if(s.endsWith(':checked'))return el.checked&&match(el,s.slice(0,-8));if(s[0]==='#')return el.attrs.id===s.slice(1);if(s[0]==='.')return el.className.split(' ').includes(s.slice(1));const m=s.match(/^([\w-]*)\[([^=\]]+)(?:=['"]?([^'"\]]+)['"]?)?\]$/);if(m)return (!m[1]||el.tagName===m[1])&&el.attrs[m[2]]!==undefined&&(m[3]===undefined||el.attrs[m[2]]===m[3]);return el.tagName===s;}
const document=new Element('document');document.createElement=t=>new Element(t);document.createElementNS=(_,t)=>new Element(t);const stack=[document],voids=new Set(['meta','link','input','hr','br']);
const html=fs.readFileSync(path.join(root,'web/index.html'),'utf8');for(const token of html.matchAll(/<\/?[\w-]+\b[^>]*>/g)){const raw=token[0],closing=raw.startsWith('</'),tag=raw.match(/^<\/?([\w-]+)/)[1].toLowerCase();if(closing){while(stack.length>1){if(stack.pop().tagName===tag)break;}continue;}const el=new Element(tag);for(const a of raw.slice(tag.length+1,-1).matchAll(/([\w:-]+)(?:="([^"]*)"|='([^']*)'|=([^\s>]+))?/g))el.setAttribute(a[1],a[2]??a[3]??a[4]??'');stack.at(-1).append(el);if(!voids.has(tag))stack.push(el);}
document.body=document.querySelector('body');document.activeElement=null;
const fixture=JSON.parse(cp.execFileSync('python',['-c',"import json,tempfile;from engine.bridge import BridgeState;from engine.project_store import ProjectStore;s=BridgeState(project_store=ProjectStore(tempfile.mkdtemp()));s.execute('generate',{});print(json.dumps(s.public()))"],{cwd:root,maxBuffer:10*1024*1024}));
const clipboard=[];const requests=[],mockControls={failure:null,deferGet:null,deferConfirm:null};let mockState=structuredClone(fixture);const context={fixtureJSON:JSON.stringify(fixture),document,console,navigator:{clipboard:{writeText:async value=>clipboard.push(value)}},Map,Set,JSON,Date,String,Number,Math,Array,Object,Promise,URL,location:{hash:''},window:{addEventListener(){}},requestAnimationFrame:f=>f(),setTimeout:()=>0,confirm:()=>true,prompt:()=>null,fetch:async(url,opts)=>{requests.push({url,opts});if(url==='/api/generation-confirm'&&mockControls.deferConfirm){const pending=mockControls.deferConfirm;mockControls.deferConfirm=null;return await pending;}if(url==='/api/state'&&mockControls.deferGet){const pending=mockControls.deferGet;mockControls.deferGet=null;return await pending;}if(opts?.method==='POST'&&mockControls.failure){const error=mockControls.failure;mockControls.failure=null;return {ok:false,json:async()=>({error})};}return {ok:true,json:async()=>url==='/api/projects'?{projects:[]}:structuredClone(mockState)};},FormData:class{constructor(form){return all(form).filter(el=>el.attrs.name).map(el=>[el.attrs.name,el.value]);}}};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(root,'web/app.js'),'utf8'),context);
(async()=>{for(let i=0;i<8;i++)await Promise.resolve();
assert.equal(document.querySelectorAll('.profile-card').length,24);assert.equal(document.querySelectorAll('.graph-node').length,24);assert.equal(document.querySelectorAll('.member').length,24);assert.equal(document.querySelectorAll('.graph-edge').length,24);
assert(requests.every(r=>!r.opts||!r.opts.method),'Startup must only read local state/projects');
vm.runInContext("openInspector(agents()[0].id)",context);assert(document.querySelector('#profile-dialog').open);assert.equal(document.querySelector('#agent-supervisor').value,'OWNER_EXTERNAL');assert.equal(document.querySelector('#agent-supervisor').disabled,true);
vm.runInContext("$('#profile-dialog').close();state.organization.agents[0].display_name='<img src=x onerror=alert(1)>';render();",context);assert.equal(document.querySelectorAll('img').length,0);assert(document.querySelector('#profile-grid').textContent.includes('<img src=x onerror=alert(1)>'));
vm.runInContext("$('#profile-search').value='no-match-value-172';renderProfiles();",context);assert.equal(document.querySelectorAll('.profile-card').length,0);assert.equal(document.querySelector('#profile-empty').hidden,false);
vm.runInContext("state.organization=null;render();setBusy(false)",context);assert.equal(document.querySelector('#save-model-assignment').disabled,true);assert.equal(document.querySelector('#save-subteam').disabled,true);assert.equal(document.querySelector('#council-save').disabled,true);assert.equal(document.querySelector('#org-empty').hidden,false);
await vm.runInContext("action('generate')",context);const post=requests.at(-1);assert.equal(post.url,'/api/generate');assert.equal(post.opts.method,'POST');assert.equal(post.opts.headers['X-CSRF-Token'],'__CSRF_TOKEN__');
// New local UI contracts. Transport is a fixture; these are not browser/runtime tests.
vm.runInContext("state=JSON.parse(fixtureJSON);render();setBusy(false);openInspector(agents()[0].id)",context);
assert.equal(document.querySelector('#tool-catalog-list').children.length,40);
assert(document.querySelector('#tool-catalog-count').textContent.includes('271'));
assert(document.querySelector('#inspector-command').textContent.includes('Disenso razonado'));
assert(document.querySelector('#inspector-command').textContent.includes('candidate_sha'));
assert.equal(document.querySelector('#merit-ranking').children.length,24);
assert(document.querySelector('#merit-ranking').textContent.includes('Sin evaluar'));
assert(!document.querySelector('#merit-ranking').textContent.includes('0 / 100'));
const exec=source=>vm.runInContext(source,context),el=id=>document.querySelector(id),submit=async id=>{const form=el(id);await form.onsubmit({preventDefault(){},target:form});},body=()=>JSON.parse(requests.filter(r=>r.opts?.method==='POST').at(-1).opts.body);
exec("$('#tools-allow').value=Array.from({length:256},(_,i)=>'external.tool.'+i).join('\\n');$('#tools-deny').value='';refreshToolCounters();");assert.equal(exec('toolPolicyIssue()'),'');assert(el('#allow-counter').textContent.includes('256 / 256'));
exec("$('#tools-allow').value+='\\nexternal.tool.256';refreshToolCounters();");assert(exec('toolPolicyIssue()').includes('256'));assert.equal(el('#save-tool-policy').disabled,true);
exec("$('#tools-allow').value='x'.repeat(201);refreshToolCounters();");assert(exec('toolPolicyIssue()').includes('200'));
exec("$('#tools-allow').value='😀'.repeat(101);refreshToolCounters();");assert(exec('toolPolicyIssue()').includes('200'),'Names count UTF-16 units like the schema');
exec("$('#tools-allow').value='ops_status\\nops_status';refreshToolCounters();");assert(exec('toolPolicyIssue()').includes('duplicados'));
exec("$('#tools-allow').value='ops_status';$('#tools-deny').value='ops_status';refreshToolCounters();");assert(exec('toolPolicyIssue()').includes('tanto en allow'));
exec("$('#tools-allow').value='manual.custom.tool';$('#tools-deny').value='';refreshToolCounters();");assert.equal(exec('toolPolicyIssue()'),'');assert(el('#permission-validation').textContent.includes('UNVERIFIED_EXTERNAL / UNKNOWN'));
exec("$('#tools-allow').value='';$('#tools-deny').value='ops_status';$('#inherit-parent-tools').checked=false;refreshToolCounters();");assert(exec('toolPolicyIssue()').includes('herencia'));assert.equal(el('#inherit-tools-label').hidden,false);
exec("$('#inherit-parent-tools').checked=true;refreshToolCounters();");assert.equal(exec('toolPolicyIssue()'),'');
await submit('#tool-policy-form');assert.equal(body().inherit_parent_tools,true);assert.equal(body().expected_state_version,fixture.organization.state_version);assert.deepEqual(body().deny,['ops_status']);
// A failed versioned save preserves the user's draft and the version it began with.
exec("$('#tools-allow').value='manual.draft';$('#tools-deny').value='';permissionsDirty=true;refreshToolCounters();");mockControls.failure='Versión obsoleta: recarga antes de editar herramientas.';
await submit('#tool-policy-form');assert.equal(el('#tools-allow').value,'manual.draft');assert(el('#inspector-notice').textContent.includes('Versión obsoleta'));assert.equal(exec('permissionsDirty'),true);
exec("permissionsDirty=false;profileDirty=false;$('#profile-dialog').close();");
// Lease forms send the declared identity, task, SHA and current coordination version.
const leaseForm=el('#lease-form');leaseForm.elements.task_id.value='task-ui';leaseForm.elements.workspace.value='/workspace/project';leaseForm.elements.paths.value='web/app.js\ntests/test_ui.py';leaseForm.elements.base_sha.value='a'.repeat(40);leaseForm.elements.ttl_seconds.value='900';
await submit('#lease-form');assert.equal(body().expected_version,fixture.coordination.version);assert.deepEqual(body().paths,['web/app.js','tests/test_ui.py']);assert.equal(body().owner_agent_id,fixture.organization.agents[0].id);
mockControls.failure='Conflicto de rutas: web/app.js ya está reservada.';await submit('#lease-form');assert.equal(el('#coordination-error').hidden,false);assert(el('#coordination-error').textContent.includes('Conflicto de rutas'));assert.equal(leaseForm.elements.task_id.value,'task-ui');
exec("state.coordination={...state.coordination,version:7,active_writer_count:1,leases:[{id:'lease-fixture',owner_agent_id:agents()[0].id,task_id:'task-ui',workspace:'/workspace/project',paths:['web/app.js'],base_sha:'a'.repeat(40),status:'active',expires_at:'2026-10-08T00:00:00Z'}]};renderCoordination();");
assert(el('#lease-count').textContent.includes('1 / 3'));assert.equal(el('#lease-list').querySelectorAll('button').length,2);await exec("changeLease('lease-renew',state.coordination.leases[0])");assert.equal(body().lease_id,'lease-fixture');assert.equal(body().expected_version,7);assert.equal(body().ttl_seconds,900);
exec("state.coordination.leases=[{id:'lease-fixture',owner_agent_id:agents()[0].id,task_id:'task-ui',status:'active'}];state.coordination.version=8;");await exec("changeLease('lease-release',state.coordination.leases[0])");assert.equal(body().expected_version,8);assert(!('ttl_seconds' in body()));
// Draft version is captured on editing, not silently advanced by a state refresh.
const performance=el('#performance-form');performance.events.input();const draftVersion=Number(performance.dataset.baseVersion);performance.elements.task_id.value='performance-ui';performance.elements.title.value='Fixture deliverable';performance.elements.comparison_group.value='comparable-ui';performance.elements.budget.value='10';performance.elements.budget_unit.value='minutes';performance.elements.candidate_sha.value='abcdef0';performance.elements.acceptance_criteria.value='Criterion one\nCriterion two';performance.elements.evidence.value='fixture://evidence';exec('state.organization.state_version+=1;');
await submit('#performance-form');assert.equal(body().expected_state_version,draftVersion);assert.deepEqual(body().acceptance_criteria,['Criterion one','Criterion two']);assert.deepEqual(body().author_ids,[fixture.organization.agents[0].id]);
// Review form includes all criteria and exact preset budget, needs both declarations.
exec("state.performance_records=[{id:'perf-fixture',agent_id:agents()[4].id,author_ids:[agents()[4].id],title:'Delivery fixture',task_id:'performance-ui',comparison_group:'comparable-ui',budget:10,budget_unit:'minutes',candidate_sha:'abcdef0',acceptance_criteria:['One','Two'],evidence:['fixture://evidence'],reviews:[],status:'awaiting_independent_review'}];renderGovernance();$('#review-performance').value='perf-fixture';renderReviewForm();");
const review=el('#performance-review-form');assert.equal(review.elements.quality_denominator.value,'2');assert.equal(review.elements.efficiency_budget.value,'10');assert(!el('#reviewer-id').options.some(o=>o.value===fixture.organization.agents[4].id));
const beforeNoApproval=requests.length;await submit('#performance-review-form');assert.equal(requests.length,beforeNoApproval);assert(el('#notice').textContent.includes('Faltan las declaraciones'));
for(const key of ['quality','compliance','collaboration','evidence']){review.elements[key+'_numerator'].value='1';if(key!=='quality')review.elements[key+'_denominator'].value='1';}review.elements.efficiency_actual.value='12';review.elements.rationale.value='Manual review fixture';review.elements.evidence.value='fixture://review';el('#reviewer-id').value='EXTERNAL';el('#external-reviewer-id').value='independent.fixture';el('#external-reviewer-name').value='Fixture reviewer';el('#external-reviewer-evidence').value='fixture://appointment';el('#review-no-conflict').checked=true;el('#review-includes-failures').checked=true;
await submit('#performance-review-form');assert.equal(body().reviewer_id,'EXTERNAL:independent.fixture');assert.equal(body().includes_failures,true);assert.equal(body().conflict_of_interest,false);assert.deepEqual(body().measurements.quality,{numerator:1,denominator:2});assert.equal(body().measurements.efficiency.budget,10);
// Compare only backend-provided groups, without deriving rank or adding activity points.
exec("state.scoreboard.rows=[{agent_id:agents()[0].id,comparison_group:'same-work',rank:1,score:89,sample_count:5,pending_count:0,reviewer_count:2,confidence:'medium',promotion_eligible:true,dimensions:{quality:90,compliance:95,efficiency:80,collaboration:85,evidence:95}}];renderGovernance();");assert(el('#merit-ranking').textContent.includes('#1'));assert(el('#merit-ranking').textContent.includes('89 / 100'));assert.equal(el('#promotion-score').options.length,2);
exec("state.organization=null;state.scoreboard.rows=[];render();setBusy(false);");assert.equal(el('#acquire-lease').disabled,true);assert.equal(el('#save-tool-policy').disabled,true);assert.equal(el('#save-skill-feedback').disabled,true);assert(document.querySelectorAll('.governance-submit').every(b=>b.disabled));
// All new mutation requests retain the CSRF token and same-origin credentials.
assert(requests.filter(r=>r.opts?.method==='POST').every(r=>r.opts.headers['X-CSRF-Token']==='__CSRF_TOKEN__'&&r.opts.credentials==='same-origin'));
// Catalog selection carries the API ID, never its display name or a DSH alias.
exec("state=JSON.parse(fixtureJSON);state.models=[{provider:'deepseek-official',id:'deepseek-flash',model:'deepseek-flash',name:'DeepSeek-V4.1-Flash',available:true}];state.generation_job=null;configDirty=false;render();setBusy(false);");
const originalRoutes=exec("JSON.stringify(state.organization.agents.map(a=>[a.id,a.provider,a.model]))");
const catalogRequestCount=requests.length;
el('#model-table').querySelectorAll('button')[0].click();
assert.equal(el('#config-form').elements.model.value,'deepseek-flash');
assert.equal(el('#config-form').elements.provider.value,'deepseek-official');
assert.equal(el('#generation-model-confirm'),null);
assert.equal(exec('configDirty'),true);
assert.equal(requests.length,catalogRequestCount);
assert.equal(exec("JSON.stringify(state.organization.agents.map(a=>[a.id,a.provider,a.model]))"),originalRoutes);
assert.equal(exec('readGenerationConfig().model'),'deepseek-flash');
// V3 guided generation UI: real app JavaScript executed against this minimal DOM.
exec("state=JSON.parse(fixtureJSON);state.credentials_configured=['deepseek-official'];state.config.repo_url='https://github.com/example/fixture';configDirty=false;render();setBusy(false);$('#config-form').elements.repo_url.value=state.config.repo_url;$('#generation-tokens').value='8192';$('#generation-new-project').checked=true;");
let previous=requests.length;
assert.equal(el('#generation-model-confirm'),null,'Unpaid preparation needs no redundant model confirmation');
exec("state.credentials_configured=[];");await exec('prepareGeneration()');assert.equal(requests.length,previous,'Missing key must not send request');
exec("state.credentials_configured=['deepseek-official'];");
const ready=structuredClone(fixture);ready.config.repo_url='https://github.com/example/fixture';ready.credentials_configured=['deepseek-official'];ready.generation_job={job_id:'qa-job-one',status:'awaiting_consent',stage:'review',progress:25,config_version:9,agent_count:24,max_requests:4,potentially_billed:false};
ready.pending_consent={job_id:'qa-job-one',approval_id:'qa-approval-one',payload_sha256:'a'.repeat(64),config_version:9,agent_count:24,provider:'deepseek',model:'fixture-model',endpoint:'https://api.deepseek.com/chat/completions',files:['README.md','src/service.py'],documents:[],max_requests:4,max_output_tokens:8192,max_total_output_tokens:32768,payload_bytes:5000,requests:[{index:1,payload:{messages:[{role:'user',content:'UNTRUSTED fixture <script>unsafe</script>'}]},payload_sha256:'b'.repeat(64)}]};
mockState=structuredClone(ready);previous=requests.filter(r=>r.opts?.method==='POST').length;
await Promise.all([exec('prepareGeneration()'),exec('prepareGeneration()')]);
assert.equal(requests.filter(r=>r.opts?.method==='POST').length,previous+1,'Double preparation clicks must send exactly one plan');
assert.equal(body().new_project,true);assert(body().idempotency_key.length>=8);assert.equal(body().max_output_tokens,8192);assert.equal(requests.at(-1).url,'/api/generation-plan');
assert.equal(el('#generation-preview').hidden,false);assert.equal(el('#generation-consent').checked,false);assert.equal(el('#confirm-generation').disabled,true);
assert(el('#generation-preview-summary').textContent.includes('32768'));assert(el('#generation-preview-payload').textContent.includes('UNTRUSTED fixture <script>unsafe</script>'));assert.equal(document.querySelectorAll('script').length,1,'Untrusted preview must stay text');
exec("$('#generation-consent').checked=true;renderGeneration();");assert.equal(el('#confirm-generation').disabled,false);
// A synthetic config edit invalidates reviewed consent even though controls are locked.
exec("$('#config-form').events.input({target:{name:'model'}});");assert.equal(el('#confirm-generation').disabled,true);previous=requests.length;await exec('confirmGeneration()');assert.equal(requests.length,previous);
exec("configDirty=false;generationReviewStale=false;$('#generation-consent').checked=true;renderGeneration();");
mockState=structuredClone(ready);mockState.pending_consent=null;mockState.generation_job.status='running';mockState.generation_job.stage='api_design';mockState.generation_job.progress=30;mockState.generation_job.potentially_billed=true;
previous=requests.filter(r=>r.opts?.method==='POST').length;await Promise.all([exec('confirmGeneration()'),exec('confirmGeneration()')]);
assert.equal(requests.filter(r=>r.opts?.method==='POST').length,previous+1,'Double approval clicks must send exactly one confirm');
assert.equal(body().job_id,'qa-job-one');assert.equal(body().consent_id,'qa-approval-one');assert.equal(body().config_version,9);assert.equal(body().payload_sha256,'a'.repeat(64));assert.equal(body().confirmed,true);assert.equal(body().data_reviewed,true);assert.equal(body().budget_acknowledged,true);
assert.equal(el('#generation-percent').textContent,'30%');assert.equal(el('#generation-preview').hidden,true);assert.equal(el('#cancel-generation').disabled,false);
// In-flight stale polling cannot resurrect the job after cancel wins.
let release;mockControls.deferGet=new Promise(resolve=>{release=resolve;});const stalePoll=exec('readGenerationState()');
const staleRunning=structuredClone(mockState);mockState.generation_job.status='cancelled';mockState.generation_job.stage='cancelled';
previous=requests.filter(r=>r.opts?.method==='POST').length;await Promise.all([exec('cancelGeneration()'),exec('cancelGeneration()')]);
assert.equal(requests.filter(r=>r.opts?.method==='POST').length,previous+1);assert.equal(requests.at(-1).url,'/api/generation-cancel');
release({ok:true,json:async()=>staleRunning});await stalePoll;assert.equal(exec('state.generation_job.status'),'cancelled');assert.equal(el('#generation-preview').hidden,true);assert.equal(el('#generation-result').hidden,false);assert(el('#generation-result').textContent.includes('cargos'));
// Cancelling while the confirmation POST is unresolved must win over its late reply.
mockState=structuredClone(ready);await exec('readGenerationState()');
exec("configDirty=false;generationReviewStale=false;$('#generation-consent').checked=true;renderGeneration();");
let releaseConfirm;mockControls.deferConfirm=new Promise(resolve=>{releaseConfirm=resolve;});const lateConfirmation=exec('confirmGeneration()');
assert.equal(el('#cancel-generation').disabled,false,'Cancel must remain usable while confirmation POST is pending');
mockState=structuredClone(staleRunning);mockState.generation_job.status='cancelled';mockState.generation_job.stage='cancelled';await exec('cancelGeneration()');
releaseConfirm({ok:true,json:async()=>staleRunning});await lateConfirmation;
assert.equal(exec('state.generation_job.status'),'cancelled','A late confirm response must not resurrect a cancelled job');
// Failed generations never claim 100 percent or an import/execution in DSH.
mockState.generation_job.status='failed';mockState.generation_job.progress=30;await exec('readGenerationState()');assert.equal(el('#generation-percent').textContent,'30%');assert(el('#generation-result').textContent.includes('No se publicó un ADN nuevo'));
assert(requests.filter(r=>r.opts?.method==='POST').every(r=>r.opts.headers['X-CSRF-Token']==='__CSRF_TOKEN__'&&r.opts.credentials==='same-origin'));
// V5: async failure updates only a generation-owned banner, including immediate POST failure.
mockState.generation_job.error={message:'No se pudo resolver el endpoint.',stage:'inventory',code:'repository_read_failed'};
mockState.generation_job.potentially_billed=false;
exec("generationMessage('Leyendo el repositorio','busy');");await exec('readGenerationState()');
assert(el('#notice').textContent.includes('No se pudo resolver el endpoint.'));
assert(el('#notice').textContent.includes('inventory'));
assert(el('#notice').className.includes('error'));
assert(el('#generation-result').textContent.includes('inventory'));
exec("generationMessage('Leyendo el repositorio','busy');message('Mensaje posterior de otra acción');");await exec('readGenerationState()');
assert.equal(el('#notice').textContent,'Mensaje posterior de otra acción');
exec("generationMessage('Otra generación','busy','another-job');");await exec('readGenerationState()');
assert.equal(el('#notice').textContent,'Otra generación');
exec("generationMessage('Leyendo el repositorio','busy');state=JSON.parse(fixtureJSON);state.generation_job=null;configDirty=false;render();setBusy(false);state.credentials_configured=['deepseek-official'];$('#config-form').elements.repo_url.value='https://github.com/example/fixture';");
await exec('prepareGeneration()');
assert(el('#notice').textContent.includes('No se pudo resolver el endpoint.'));
assert.equal(exec('generationOperation'),false);
// Autonomous presentation uses saved/current context, never stale organization goals.
exec("state=JSON.parse(fixtureJSON);state.organization.autonomy.mission='Prior organization mission';state.autonomy_preview={...state.organization.autonomy,mission:'New repository mission <img src=x onerror=alert(1)>',plan_preview:'New repository Plan Preview, no transactions authorized'};state.generation_stale=true;state.generation_job=null;configDirty=false;render();setBusy(false);");
assert(el('#autonomy-mission').textContent.includes('New repository mission'));assert(!el('#autonomy-mission').textContent.includes('Prior organization mission'));assert.equal(document.querySelectorAll('img').length,0);assert.equal(el('#autonomy-plan-preview').value,'New repository Plan Preview, no transactions authorized');
previous=requests.length;await exec('copyPlanPreview()');assert.equal(clipboard.at(-1),'New repository Plan Preview, no transactions authorized');assert.equal(requests.length,previous,'Copy preview is local and cannot dispatch a job');
const copied=clipboard.length;exec('configDirty=true;renderAutonomy();setBusy(false);');assert.equal(el('#copy-plan-preview').disabled,true);assert(el('#autonomy-preview-state').textContent.includes('sin guardar'));await exec('copyPlanPreview()');assert.equal(clipboard.length,copied);
exec("configDirty=false;$('#config-form').elements.autonomy_preset.value='autonomous';$('#config-form').elements.planning_context.value='full';$('#config-form').elements.objective.value='Buscar beneficio neto realizado con mandato separado';$('#config-form').elements.planner_max_tokens.value='8192';$('#config-form').elements.member_timeout_ms.value='900000';$('#config-form').elements.handoff_summary_max_chars.value='16000';$('#config-form').elements.runtime_token_budget.value='288000';$('#config-form').elements.quality_gate_rounds.value='0';");
const configPayload=exec('readGenerationConfig()');assert.equal(configPayload.autonomy_preset,'autonomous');assert.equal(configPayload.planning_context,'full');assert.equal(configPayload.quality_gate_rounds,0);assert.equal(configPayload.runtime_token_budget,288000);assert.equal(configPayload.planner_max_tokens,8192);assert(!('previewTask' in configPayload));
// Cordis, Plugin Shop and the read-only connection are explicit independent steps.
exec("state=JSON.parse(fixtureJSON);state.generation_job=null;state.generation_stale=false;configDirty=false;render();setBusy(false);");
mockState=structuredClone(fixture);previous=requests.filter(r=>r.opts?.method==='POST').length;el('#prepare-cordis').onclick();for(let i=0;i<12;i++)await Promise.resolve();
assert.equal(requests.filter(r=>r.opts?.method==='POST').length,previous+1);assert.equal(requests.at(-1).url,'/api/cordis-prepare');assert.equal(body().expected_state_version,fixture.organization.state_version);
exec("state.cordis_addon={status:'stale',artifact:null,runtime_verified:false};renderCordis();");assert.equal(el('#download-cordis').getAttribute('aria-disabled'),'true');assert(el('#cordis-status').textContent.includes('Desactualizado'));
const candidates=Array.from({length:4},(_,i)=>({id:'qa-plugin-'+i,name:'qa-plugin-'+i,version:'1.2.3',description:'Untrusted <img src=x onerror=alert(1)>',category:'tool',status:'proposal',capabilities:['search'],compatibility:{status:'UNVERIFIED'},trust:{status:'UNVERIFIED'},provenance:{entry_sha256:'d'.repeat(64),catalog_url:'https://example.com/catalog'},installed:false,active:false}));
context.shopFixture=JSON.stringify({catalog:{catalog_sha256:'a'.repeat(64),count:13950},search:{results:candidates,total:4},inspected:{},reported_candidates:{},plans:[]});exec('state.plugin_shop=JSON.parse(shopFixture);renderPluginShop();setBusy(false);');
assert.equal(el('#plugin-shop-results').querySelectorAll('.plugin-result').length,4);assert.equal(document.querySelectorAll('img').length,0);assert(el('#plugin-shop-status').textContent.includes('sin verificar'));
for(const card of el('#plugin-shop-results').querySelectorAll('.plugin-result')){const compareLabel=card.querySelectorAll('label').find(label=>label.textContent==='Comparar');assert(compareLabel,'Comparison control must exist');const check=compareLabel.querySelector('input');check.checked=true;check.events.change();}assert.equal(exec('pluginCompared.size'),3,'Compare selection must stay bounded at three');
exec("state.plugin_shop.catalog.catalog_sha256='b'.repeat(64);renderPluginShop();");assert.equal(exec('pluginCompared.size'),0,'Catalog replacement must clear stale comparison entries');
exec("state.dsh_connection={status:{status:'CONNECTED',live_connection:true,identity_verified:true,scopes:['teams.profiles.read'],capabilities:{profiles_read:{available:true},import_preview:{available:false},agentteams_state_read:{available:false}}}};renderDshConnection();setBusy(false);");
assert.equal(el('#dsh-read-profiles').disabled,false);assert.equal(el('#dsh-read-team').disabled,true);assert.equal(el('#dsh-preview-import').disabled,true);
const pairing=el('#dsh-connect-form');pairing.elements.port.value='12345';pairing.elements.pairing_code.value='C'.repeat(43);exec("$('#dsh-pairing-consent').checked=false;");previous=requests.length;await submit('#dsh-connect-form');assert.equal(requests.length,previous);
exec("$('#dsh-pairing-consent').checked=true;");mockState=structuredClone(fixture);await submit('#dsh-connect-form');assert.equal(pairing.elements.pairing_code.value,'');assert.equal(requests.at(-1).url,'/api/dsh-connect');assert.equal(body().confirmed,true);assert.equal(body().port,12345);assert.equal(body().pairing_code,'C'.repeat(43));assert.equal(el('#dsh-pairing-consent').checked,false);
exec("state.dsh_connection={status:{status:'CONNECTED',live_connection:true,identity_verified:true,scopes:['teams.profiles.read'],capabilities:{profiles_read:{available:true}}}};renderDshConnection();setBusy(false);");
let releaseDshPoll;mockControls.deferGet=new Promise(resolve=>{releaseDshPoll=resolve;});const oldConnectionPoll=exec('readGenerationState()');const oldConnectionState=exec('JSON.parse(JSON.stringify(state))');
mockState=structuredClone(fixture);mockState.dsh_connection={status:{status:'DISCONNECTED',live_connection:false,identity_verified:false}};await exec('disconnectDsh()');releaseDshPoll({ok:true,json:async()=>oldConnectionState});await oldConnectionPoll;
assert.equal(exec('dshConnectionStatus().status'),'DISCONNECTED','Late full-state poll must not revive disconnected pairing');assert.equal(el('#dsh-read-profiles').disabled,true);assert.equal(el('#dsh-connection-status').textContent,'Desconectado');
// V7 partial coverage is explicit in the same exact-plan approval, reset by its hash.
mockState=structuredClone(ready);mockState.pending_consent.partial_inventory_required=true;mockState.pending_consent.coverage_sha256='coverage-one';mockState.pending_consent.coverage_review={source_kind:'github_repository',inventory_complete:false,known_safe_files:4100,total_repository_files:null,read_files:20,coverage:{inventory:{method:'bounded_subtrees'},gaps:['Subtree not observed']}};
exec("generationOperation=false;generationCancelPending=false;generationReviewStale=false;configDirty=false;");await exec('readGenerationState()');
assert.equal(el('#generation-partial-notice').hidden,false);assert(el('#generation-preview-summary').textContent.includes('4100'));assert(el('#generation-preview-summary').textContent.includes('Desconocido'));
const callsBeforePartial=requests.length;await exec('confirmGeneration()');assert.equal(requests.length,callsBeforePartial,'No checkbox means no confirmation');
exec("$('#generation-consent').checked=true;renderGeneration();");assert.equal(el('#confirm-generation').disabled,false);
mockState.pending_consent.coverage_sha256='coverage-two';await exec('readGenerationState()');assert.equal(el('#generation-consent').checked,false);assert.equal(el('#confirm-generation').disabled,true);
// Web source selection changes the scope copy without silently choosing a model.
exec("state.generation_job=null;state.pending_consent=null;configDirty=false;render();$('#config-form').elements.source_kind.value='website';renderSourceChoice();");
assert(el('#source-url-label').textContent.includes('sitio web'));assert.equal(el('#source-git-ref').hidden,true);assert(el('#source-read-note').textContent.includes('No ejecuta JavaScript'));
// V6 local evaluations use current IDs, a reviewed hash, and a separate execution approval.
mockState=structuredClone(fixture);mockState.generation_job=null;mockState.pending_consent=null;mockState.evaluations={profiles:[{id:'python_unittest_v1',name:'Python unittest'}],plans:[],runs:[]};
exec("generationOperation=false;generationCancelPending=false;generationReviewStale=false;configDirty=false;busy=false;");await exec('readGenerationState()');
assert.equal(el('#evaluation-profile').value,'python_unittest_v1');assert(!el('#evaluation-evaluator').options.some(item=>item.value===el('#evaluation-agent').value));
el('#evaluation-cwd').value='/synthetic/reviewed';el('#evaluation-tests').value='tests';el('#evaluation-task').value='test-ui';el('#evaluation-timeout').value='30';
const localPlan={id:'evaluation-plan-ui',plan_hash:'exact-plan-hash',argv:['python','-I','-m','unittest'],cwd:'/synthetic/reviewed',agent_id:el('#evaluation-agent').value};mockState.evaluations.plans=[localPlan];await submit('#evaluation-form');
assert.equal(body().profile_id,'python_unittest_v1');assert.equal(body().cwd,'/synthetic/reviewed');assert.equal(el('#evaluation-review').hidden,false);assert.equal(el('#evaluation-start').disabled,true);
const beforeLocalApproval=requests.length;await el('#evaluation-start').onclick();assert.equal(requests.length,beforeLocalApproval);
el('#evaluation-consent').checked=true;mockState.evaluations.runs=[{id:'evaluation-run-ui',plan_id:localPlan.id,status:'pass',evidence_ref:'evaluation://test/hash'}];await el('#evaluation-start').onclick();assert.equal(body().plan_id,localPlan.id);assert.equal(body().plan_hash,'exact-plan-hash');assert.equal(body().confirmed,true);
exec("state.credentials_configured=[];");const beforeImprovement=requests.length;await exec("prepareImprovement(['evaluation-run-ui'])");assert.equal(requests.length,beforeImprovement);assert.equal(exec('generationImprovementRunIds.length'),1);assert.equal(el('#improvement-selection').hidden,false);assert.equal(el('#generation-new-project').checked,false);
await el('#improvement-clear').onclick();assert.equal(exec('generationImprovementRunIds.length'),0);
console.log('PASS: legacy DOM fixture plus v3 model/key preflight, exact consent preview, inert injection text, one exact-plan approval including data, cost and partial coverage, double-click preparation and confirmation guards, stale configuration, real status percentages, double cancel and stale polling protection, repo-specific autonomy preview, local-only copying, stale goal protection and typed native budget fields, inert Cordis preparation, bounded Plugin Shop comparison, explicit pairing with cleared code, scoped read controls and stale-poll disconnect protection. Minimal DOM fixture only; no browser rendering or DSH executed.');

})().catch(e=>{console.error(e);process.exitCode=1;});
