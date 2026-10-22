'use strict';
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const csrf = $('meta[name="csrf-token"]').content;
const SVG_NS = 'http://www.w3.org/2000/svg';
let state = null, busy = false, projects = [], selectedAgent = null, selectedCouncil = '';
let configDirty = false, profileDirty = false, consentId = null, zoom = 0.85;
let graphSize = {width:1200,height:700}, lastGraphVersion = '', graphFirstView = true;
let activePage = 'inicio';
let permissionsDirty = false, inspectorBaseVersion = null, permissionBaseVersion = null;
let generationOperation = false, generationOperationCounter = 0, generationPollTimer = null, generationEpoch = 0, generationPollInFlight = false;
let runtimeBudgetAutomatic = true;
let generationImprovementRunIds=[];
let evaluationPlanId=null,evaluationPlanFingerprint=null,evaluationPollTimer=null,evaluationPlanStale=false;
let generationNoticeOwned = false, generationNoticeJobId = null;
const pluginCompared = new Map();
let pluginReportFingerprint = null, pluginCatalogIdentity = null;
let dshDisconnectPending = false, dshEpoch = 0;
let dshLaunchDirty = false, dshLaunchRevision = 0;
let generationPlanKey = null, generationConsentId = null, generationCancelPending = false, generationReviewStale = false;
let generationModelFingerprint = null;
const generationTerminal = new Set(['completed','failed','cancelled','rejected','expired']);
const pageNames = {inicio:'Inicio',organigrama:'Organigrama',perfiles:'Perfiles',council:'Council',habilidades:'Habilidades',modelos:'Modelos',repositorio:'Repositorio',exportaciones:'Exportaciones',registro:'Registro'};
const aliases = {overview:'inicio',configuration:'inicio',providers:'modelos',analysis:'repositorio',excel:'exportaciones',evidence:'registro','plugin-shop':'habilidades','cordis-extension':'exportaciones','dsh-connection':'exportaciones','dsh-launcher':'exportaciones','autonomy-overview':'inicio','design-recovery':'inicio'};
const agents = () => state?.organization?.agents || [];
const textValue = value => value == null ? '' : typeof value === 'string' ? value : JSON.stringify(value, null, 2);
const lines = value => String(value || '').split('\n').map(s=>s.trim()).filter(Boolean);
const initials = value => String(value || '?').trim().split(/\s+/).slice(0,2).map(s=>s[0]).join('').toUpperCase();
const shorten = (s,n) => String(s || '').length > n ? String(s).slice(0,n-1)+'…' : String(s || '');
function node(tag,text,cls) { const el=document.createElement(tag); if(text!==undefined)el.textContent=textValue(text); if(cls)el.className=cls; return el; }
function svgNode(tag,attrs={},text) { const el=document.createElementNS(SVG_NS,tag); Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v))); if(text!==undefined)el.textContent=textValue(text); return el; }
function option(value,label) { const el=node('option',label); el.value=value; return el; }
function emptyRow(target,columns,text) { const tr=node('tr'),td=node('td',text); td.colSpan=columns;tr.append(td);target.append(tr); }
function message(text,kind='') { generationNoticeOwned=false; const n=$('#notice');n.textContent=text;n.className='notice '+kind;const inline=$('#inspector-notice');if(inline&&$('#profile-dialog').open){inline.textContent=text;inline.className='notice '+kind;inline.hidden=false;} }
function localDate(value) { if(!value)return ''; const date=new Date(value);return Number.isNaN(date.valueOf())?String(value):date.toLocaleString('es',{dateStyle:'short',timeStyle:'short'}); }
function setBusy(value) {
  busy=value; const locked=Boolean(value||generationOperation||generationActive());document.body.setAttribute('aria-busy',String(Boolean(value||generationOperation)));
  $$('button').forEach(b=>b.disabled=locked||!state);
  if(!locked && state) {
    $('#read-excel').disabled=!state.capabilities?.excel_com;
    $('#apply-excel').disabled=!state.capabilities?.excel_com||!state.organization||state.generation_stale===true;
    $('#persist-key').disabled=!state.capabilities?.dpapi;
    $('#confirm-analysis').disabled=Boolean(state.pending_consent?.partial_inventory_required&&!$('#analysis-partial-consent').checked)||!state.pending_consent||!$('#review-consent').checked||!$('#budget-consent').checked;
    $('#project-load').disabled=!$('#project-list').value;
    $('#council-close').disabled=!selectedCouncil||currentCouncil()?.status!=='open_manual_record';
    $('#save-profile').disabled=state.generation_stale===true;
    const noDesign=!state.organization||state.generation_stale===true;
    $('#council-save').disabled=noDesign;
    $('#acquire-lease').disabled=noDesign||!state.coordination;
    $('#save-skill-feedback').disabled=noDesign||!(state.skill_registry||[]).length;
    $('#refresh-coordination').disabled=false;
    ['#channel-publish-form','#channel-assign-form','#channel-evidence-form','#channel-task-form','#memory-append-form'].forEach(id=>{const button=$(id)?.querySelector('button[type="submit"]');if(button)button.disabled=noDesign;});
    $('#channel-inbox-drain').disabled=noDesign;
    $('#followups-tick').disabled=noDesign||!state.team_followups?.available;
    $('#followups-drain').disabled=noDesign||!state.team_followups?.available||!$('#followups-drain-member').value;
    if($('#sandbox-request')){const sandbox=state.sandbox||{},sandboxLocked=!state.organization||state.generation_stale===true||!sandbox.available;$('#sandbox-request').disabled=sandboxLocked;['#sandbox-code','#sandbox-agent','#sandbox-timeout','#sandbox-max-output','#sandbox-approver-role'].forEach(id=>{const el=$(id);if(el)el.disabled=sandboxLocked;});}
    $('#save-tool-policy').disabled=noDesign||!selectedAgent||Boolean(toolPolicyIssue());
    $('#apply-tool-recommendation').disabled=noDesign||!currentToolPreset();
    $$('.governance-submit').forEach(el=>el.disabled=noDesign);
    $('#save-model-assignment').disabled=noDesign;$('#save-model-preferences').disabled=noDesign||!(state.models||[]).length;$('#save-subteam').disabled=noDesign;$('#hierarchy-reset').disabled=noDesign;
    $('#remediation-form').querySelector('button[type="submit"]').disabled=noDesign;
    $('#inventory').disabled=!state.config.repo_url;
    $('#prepare-analysis').disabled=!state.repo_inventory;
    $('#discover-models').disabled=!(state.credentials_configured||[]).includes(state.config.provider)&&!['zai','zai-official'].includes(state.config.provider);
    ['#zoom-in','#zoom-out','#zoom-fit'].forEach(id=>$(id).disabled=!state.organization);
    $$('a[download]').forEach(a=>{const blocked=(noDesign||configDirty)&&!a.getAttribute('href').endsWith('evidence.json');a.setAttribute('aria-disabled',String(blocked));});
  }
  updateSkillHubControls();updateCapabilityRecommendationControls();updateCapabilityDeploymentControls();updateGenerationControls(value);updateExtensionControls(value);updateDshLauncherControls();updateEvaluationControls();updateHarnessControls();updateResourceControls();
}
// GenTeam P3: seguimiento de compromisos (panel "Compromisos" de #council). Todo el codigo
// de este bloque es NUEVO: no se modifica ninguna funcion ni ninguna linea de handler
// pineada por qa_v7/dsh_baseline.json (dsh/harness/cordis). El avance es un tick EXPLICITO:
// aqui no hay setInterval, setTimeout ni temporizadores de ningun tipo.
let followupsTick=null,followupsDrained=null;
function followupsView(){return (state&&state.team_followups)||{available:false,reason:'Genera un diseno para abrir el seguimiento del equipo.'};}
function followupsMemberLabel(id){const members=channelMembers(),member=members.find(m=>m.member_id===id);return member?member.name+' ('+member.member_id+')':String(id||'');}
function followupsStateLabel(value){return ({chasing:'en persecucion',escalated:'escalado a supervision',reported:'reportado y archivado'})[value]||String(value||'');}
function followupsRow(task,limits,archived){
  const row=node('article',undefined,'record'),max=Number(limits.max_reminders||0);
  row.dataset.followupTask=String(task.id||'');row.dataset.followupState=String(task.state||'');
  row.append(node('strong',String(task.id||'')+' | '+followupsStateLabel(task.state)+' | '+followupsMemberLabel(task.owner_member_id)+(archived?'':' | recordatorios '+String(task.reminders_sent||0)+'/'+String(max))));
  row.append(node('p','Compromiso del mensaje '+String(task.message_id||'')+': "'+String(task.snippet||'')+'"','helper'));
  if(!archived&&task.next_reminder_at)row.append(node('p','Proximo recordatorio: '+localDate(new Date(Number(task.next_reminder_at)*1000).toISOString()),'helper'));
  if(task.state==='escalated')row.append(node('span','escalado','tag amber'));
  row.append(node('p','Emite: '+(followupsView().authority?.role_label||'Coordinacion local (motor de seguimiento)')+' (no es un mensaje de un miembro)','helper'));
  row.append(node('p','Dirigido a: '+followupsMemberLabel(task.owner_member_id),'helper'));
  return row;
}
function renderFollowups(){
  if(!$('#followups-panel'))return;
  const view=followupsView(),stats=view.stats||{},authority=view.authority||{};
  const select=$('#followups-drain-member'),previous=select.value;select.replaceChildren();
  channelMembers().forEach(member=>select.append(option(member.member_id,member.name+(member.role?' | '+member.role:''))));
  if(channelMembers().some(member=>member.member_id===previous))select.value=previous;
  $('#followups-authority').textContent=String(authority.note||'Recordatorios y escalaciones los emite la coordinacion local (motor engine.followups); ningun miembro del roster es su autor.')+' Reloj: '+(view.clock_source==='injected'?'inyectado por el arnes (tiempo simulado).':'del sistema.')+' identity_verified=false.';
  const tasks=$('#followups-task-list'),archive=$('#followups-archive-list');
  tasks.replaceChildren();archive.replaceChildren();
  if(!view.available){
    $('#followups-count').textContent='Sin diseno';
    ['active','chasing','escalated','reported'].forEach(key=>{const cell=$('#followups-stat-'+key);if(cell)cell.textContent='0';});
    $('#followups-status').textContent=String(view.reason||'Genera un diseno para abrir el seguimiento del equipo.');
    $('#followups-empty-tasks').hidden=false;$('#followups-empty-archive').hidden=false;
    $('#followups-events').textContent='';$('#followups-engine-summary').textContent='';
    updateFollowupsControls();return;
  }
  $('#followups-count').textContent=String(stats.active||0)+' activos | '+String(stats.archived||0)+' archivados';
  ['active','chasing','escalated','reported'].forEach(key=>{const cell=$('#followups-stat-'+key);if(cell)cell.textContent=String(stats[key]||0);});
  (view.tasks||[]).forEach(task=>tasks.append(followupsRow(task,view,false)));
  (view.archive||[]).forEach(task=>archive.append(followupsRow(task,view,true)));
  $('#followups-empty-tasks').hidden=Boolean((view.tasks||[]).length);
  $('#followups-empty-archive').hidden=Boolean((view.archive||[]).length);
  const events=(view.events||[]).slice(-20);
  const summary=followupsTick?('Ultimo tick: '+String(followupsTick.events)+' evento(s), '+String(followupsTick.reminders)+' recordatorio(s), '+String(followupsTick.escalations)+' escalacion(es).'):'Sin tick en esta sesion del panel.';
  $('#followups-events').textContent=[summary].concat(events.map(row=>String(row.at||'')+' | '+String(row.event||'')+(row.task_id?' | '+String(row.task_id):'')+(row.owner_member_id?' | '+followupsMemberLabel(row.owner_member_id):''))).join('\n');
  $('#followups-status').textContent=followupsTick?('Tick ejecutado: '+String(followupsTick.events)+' evento(s), '+String(followupsTick.reminders)+' recordatorio(s), '+String(followupsTick.escalations)+' escalacion(es).'):'Seguimiento del equipo: tick explicito, sin temporizadores.';
  $('#followups-engine-summary').textContent='schema_version='+String(view.schema_version||'')+' | provenance='+String(view.provenance||'')+' | identidad de coordinacion='+String(view.agent_member_id||'')+' | supervision='+String(view.supervisor_member_id||'')+' | intervalo='+String(view.reminder_interval_secs)+' s | maximo='+String(view.max_reminders)+' recordatorio(s) | bucle='+(view.loop&&view.loop.available?'disponible':'no cableado');
  updateFollowupsControls();
}
function updateFollowupsControls(){
  const available=Boolean(state&&state.team_followups&&state.team_followups.available);
  const stale=Boolean(state&&(state.generation_stale===true||!state.organization));
  const drain=$('#followups-drain'),member=$('#followups-drain-member'),tick=$('#followups-tick');
  if(tick)tick.disabled=!available||stale;
  if(drain)drain.disabled=!available||stale||!(member&&member.value);
}
async function followupsRun(title,work,good){
  if(busy||generationOperation||generationActive())return false;
  setBusy(true);message(title,'busy');
  const box=$('#followups-error');if(box){box.hidden=true;box.textContent='';}
  try{await work();render();message(good);return true;}
  catch(error){
    if(box){box.textContent=String((error&&error.message)||'La accion de seguimiento no termino.');box.hidden=false;}
    try{const fresh=await fetch('/api/state',{credentials:'same-origin'});if(fresh.ok){state=await fresh.json();render();}}catch(_){}
    message((error&&error.message)||'La accion de seguimiento no termino.','error');return false;
  }finally{setBusy(false);}
}
async function tickFollowups(){
  const version=(state&&state.organization&&state.organization.state_version)||1;
  return followupsRun('Ejecutando un tick explicito de seguimiento...',async()=>{
    const payload=await request('followups-tick',{expected_state_version:version});
    followupsTick=(payload&&payload.followups_tick)||null;
  },'Tick de seguimiento ejecutado.');
}
async function drainFollowups(){
  const version=(state&&state.organization&&state.organization.state_version)||1;
  const member=$('#followups-drain-member').value,max=Number($('#followups-drain-max').value);
  return followupsRun('Drenando el inbox de seguimiento del miembro...',async()=>{
    const payload=await request('followups-drain',{expected_state_version:version,member:member,max_count:max});
    followupsDrained=(payload&&payload.followups_drained)||null;
    const counts=(followupsDrained&&followupsDrained.counts)||{delivered:0,reminders:0,other:0};
    $('#followups-drained-status').textContent='Drenados '+String(counts.delivered)+' mensaje(s): '+String(counts.reminders)+' recordatorio(s) de seguimiento y '+String(counts.other)+' de otros topicos.';
    const box=$('#followups-drained');box.replaceChildren();
    (followupsDrained&&followupsDrained.reminders||[]).forEach(row=>{const article=node('article',undefined,'record');
      article.append(node('strong','Recordatorio | dirigido a '+followupsMemberLabel(row.to)),node('p',String(row.text||''),'helper'),
        node('p','Emite: '+String((row.authority&&row.authority.role_label)||'Coordinacion local (motor de seguimiento)')+' (no es un mensaje de un miembro)','helper'));
      box.append(article);});
    (followupsDrained&&followupsDrained.other||[]).forEach(row=>{const article=node('article',undefined,'record');
      article.append(node('strong','Mensaje de otro topico | '+String(row.topic||'')+' | autor '+channelLabel(row.actor)),node('p',String(row.text||''),'helper'));
      box.append(article);});
    if(!counts.delivered)box.append(node('p','Drenados 0 mensaje(s): el buzon del miembro no tenia mensajes.','empty'));
  },'Inbox de seguimiento drenado (lectura destructiva).');
}
$('#followups-tick').onclick=()=>tickFollowups();
$('#followups-drain').onclick=()=>drainFollowups();
$('#followups-drain-member').onchange=()=>updateFollowupsControls();

async function request(name,data={}) {
  const dshRevision=dshEpoch;const response=await fetch('/api/'+name,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},credentials:'same-origin',body:JSON.stringify(data)});
  const payload=await response.json();if(!response.ok)throw new Error(payload.error||'No se pudo completar la acción.');
  if(dshRevision!==dshEpoch&&state)payload.dsh_connection=state.dsh_connection;state=payload;return payload;
}
async function run(title,fn,good) {
  if(busy||generationOperation||generationActive())return false;setBusy(true);message(title,'busy');
  try {await fn();render();message(good||state.receipts?.at(-1)?.message||'Cambio guardado en el motor local.');return true;}
  catch(error) {try{const fresh=await fetch('/api/state',{credentials:'same-origin'});if(fresh.ok){state=await fresh.json();render();}}catch(_){}message(error.message,'error');return false;}
  finally{setBusy(false);}
}
function action(name,data={},good) {return run('Procesando en el motor local…',()=>request(name,data),good);}
function navigate() {
  const hash=location.hash.slice(1), page=pageNames[hash]?hash:(aliases[hash]||'inicio');activePage=page;
  $$('.page').forEach(el=>el.hidden=el.id!==page);
  $$('[data-page]').forEach(el=>{const selected=el.dataset.page===page;el.classList.toggle('active',selected);if(selected)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  $('#page-breadcrumb').textContent=pageNames[page];document.title=pageNames[page]+' · OrgDNA Local Studio';
  if(['plugin-shop','cordis-extension','dsh-connection','dsh-launcher','autonomy-overview','design-recovery'].includes(hash))requestAnimationFrame(()=>$('#'+hash).scrollIntoView({block:'start'}));
  if(hash==='configuration')requestAnimationFrame(()=>$('#configuration').scrollIntoView({block:'start'}));
  else if(hash==='excel'){ $('#excel').open=true;requestAnimationFrame(()=>$('#excel').scrollIntoView({block:'start'})); }
  if(page==='organigrama')requestAnimationFrame(()=>{if(graphFirstView&&agents().length){zoom=Math.min(.85,Math.max(.3,($('#graph-viewport').clientWidth-40)/graphSize.width));applyZoom();centerOnRoot();graphFirstView=false;}});
}
function renderSourceChoice(){
  const form=$('#config-form'),web=form.elements.source_kind.value==='website';
  $('#source-url-label').textContent=web?'URL del sitio web público':'URL del repositorio público de GitHub';
  form.elements.repo_url.placeholder=web?'https://example.org/':'https://github.com/propietario/repositorio';
  $('#source-git-ref').hidden=web;
  $('#source-read-note').textContent=web?'Lectura acotada de HTML público. No ejecuta JavaScript, no inicia sesión ni envía formularios. Las páginas observadas no demuestran todas las capacidades del sitio.':'Inventario de rutas con commit fijado y selección limitada a 20 archivos / 250 KB por defecto. No se lee todo el contenido del repositorio.';
  $('#repo-scope').disabled=web;
}
function render() {
  if(!state)return;
  const c=state.config,org=state.organization, all=agents(),stale=state.generation_stale===true;
  if(!configDirty){runtimeBudgetAutomatic=c.runtime_token_budget==null||Number(c.runtime_token_budget)===Math.max(24000,Number(c.agent_count)*12000);const form=$('#config-form');const preset=state.autonomy_preview?.settings?.implementation||{},defaults={planning_context:preset.planningContext,response_mode:preset.responseMode,planner_max_tokens:preset.plannerMaxTokens,member_timeout_ms:preset.memberTimeoutMs,handoff_summary_max_chars:preset.handoffSummaryMaxChars,runtime_token_budget:preset.tokenBudget,quality_gate_rounds:2};Object.entries({...defaults,...c}).forEach(([k,v])=>{const el=form.elements.namedItem(k);if(el&&v!==undefined)el.value=v;});}
  renderSourceChoice();
  $('#workbook-path').value=state.workbook||'';
  $('#organization-name').textContent=c.repo_name||'Mi organización';
  $('#stat-agents').textContent=all.length||c.agent_count;
  $('#stat-span').textContent=c.max_direct_reports;
  $('#stat-models').textContent=(state.models||[]).length;
  $('#stat-ready').textContent=stale?'Diseño conservado':org?'Diseñada':'Por generar';
  $('#stat-source').textContent=stale?(state.design_recovery?.available?'Restaura el diseño o prepara una revisión':'Carga una versión o prepara una revisión'):generationSourceLabel();
  $('#key-status').textContent=(state.credentials_configured||[]).includes(c.provider)?'Clave preparada · '+c.provider:'Sin clave · '+c.provider;$('#model-key-status').textContent=$('#key-status').textContent;
  $('#provider-current').textContent=c.provider+' / '+(c.model||'Sin modelo seleccionado');
  $('#repo-current').textContent=c.repo_url?(c.repo_url+(c.source_kind==='website'?' · sitio web · HTML estático':' · ref: '+(c.repo_ref||'predeterminada'))):'Configura una fuente pública en Inicio.';
  $('#export-status').textContent=stale?'CONFIGURACIÓN PENDIENTE':org?'Estado generado disponible':'Genera primero';
  $('#export-status').classList.toggle('amber',stale);$('#export-recovery-note').hidden=!stale;
  const project=state.project||{};$('#project-status').textContent=project.name?(project.name+(project.dirty?' · sin guardar':' · guardado')):'Sin proyecto guardado';
  $('#project-dirty').textContent=project.dirty?'Cambios sin guardar':project.id?'Versión guardada':'Sin guardar';
  if(document.activeElement!==$('#project-name'))$('#project-name').value=project.name||c.repo_name||'';
  renderGraph();renderProfiles();renderCouncil();renderSkills();renderModels();renderAnalysis();renderReceipts();renderSubteams();renderGovernance();renderCoordination();renderTeamChannel();renderTeamMemory();renderFollowups();renderSandbox();renderGeneration();renderDesignRecovery();renderGenerationIntegrity();renderOrchestrationChoice();renderAutonomy();renderCordis();renderPluginShop();renderDshConnection();renderDshLauncher();renderEvaluations();renderSkillHub();renderCapabilityRecommendations();renderCapabilityDeployment();renderHarness();renderResourceWorkflows();setBusy(busy);
}
function matches(agent,query) {return !query||[agent.display_name,agent.title,agent.role,agent.department,agent.mission,...(agent.skills||[]).map(s=>s.name)].join(' ').toLocaleLowerCase('es').includes(query.toLocaleLowerCase('es'));}
function directCount(id) {return agents().filter(a=>a.reports_to===id).length;}
function renderGraph() {
  const all=agents(),svg=$('#org-tree');svg.replaceChildren(svgNode('title',{id:'svg-title'},'Organigrama de la organización'),svgNode('desc',{id:'svg-description'},'Líneas de supervisión directa. Perfiles seleccionables con teclado.'));
  $('#org-empty').hidden=all.length>0;$('#graph-viewport').hidden=!all.length;$('#org-count').textContent=all.length+' perfiles';
  const warnings=[...(state.organization?.warnings||[])];const maximum=state.config.max_direct_reports;const violations=all.filter(a=>directCount(a.id)>maximum);
  $('#hierarchy-status').textContent=!all.length?'Sin estructura':violations.length?'Límite excedido':`Máximo ${maximum} · ${all.length} perfiles`;
  $('#hierarchy-status').classList.toggle('amber',Boolean(violations.length));
  if(state.generation_stale)warnings.unshift('Diseño desactualizado: conserva tu trabajo en una versión y regenera antes de exportar.');
  if(violations.length)warnings.unshift('Hay perfiles que exceden el límite de reportes directos. La exportación requiere validación.');
  $('#org-warnings').hidden=!warnings.length;$('#org-warnings').textContent=warnings.map(textValue).join('\n');
  if(!all.length)return;
  const byId=new Map(all.map(a=>[a.id,a])),children=new Map(all.map(a=>[a.id,[]]));
  all.forEach(a=>{if(children.has(a.reports_to))children.get(a.reports_to).push(a);});
  const roots=all.filter(a=>!byId.has(a.reports_to)),placed=new Map(),visiting=new Set();let cursor=0,maxDepth=0;
  function layout(agent,depth) {
    if(placed.has(agent.id)||visiting.has(agent.id))return placed.get(agent.id)?.y||30;
    visiting.add(agent.id);maxDepth=Math.max(maxDepth,depth);const kids=children.get(agent.id)||[];
    const ys=kids.filter(k=>!visiting.has(k.id)).map(k=>layout(k,depth+1));
    const y=ys.length?(ys[0]+ys.at(-1))/2:30+(cursor++)*122;
    const pos={x:258+depth*280,y,depth};placed.set(agent.id,pos);visiting.delete(agent.id);return y;
  }
  roots.forEach(a=>layout(a,0));all.filter(a=>!placed.has(a.id)).forEach(a=>layout(a,0));
  graphSize={width:258+(maxDepth+1)*280+30,height:Math.max(400,cursor*122+65)};svg.setAttribute('viewBox',`0 0 ${graphSize.width} ${graphSize.height}`);
  const edges=svgNode('g',{'aria-hidden':'true'}),cards=svgNode('g');svg.append(edges,cards);
  const rootY=roots.length?placed.get(roots[0].id).y:30;
  const owner=svgNode('g',{class:'owner-node'});owner.append(svgNode('rect',{x:26,y:rootY+23,width:186,height:47,rx:10}),svgNode('text',{x:119,y:rootY+51,'text-anchor':'middle'},'OWNER EXTERNO'));cards.append(owner);
  all.forEach(a=>{const to=placed.get(a.id),parent=placed.get(a.reports_to);const from=parent?{x:parent.x+220,y:parent.y+48}:{x:212,y:rootY+47};const end={x:to.x,y:to.y+48};edges.append(svgNode('path',{class:'graph-edge',d:`M ${from.x} ${from.y} C ${from.x+28} ${from.y}, ${end.x-28} ${end.y}, ${end.x} ${end.y}`}));});
  const query=$('#org-search').value.trim();
  all.forEach((a,i)=>{const p=placed.get(a.id);const card=svgNode('g',{class:'graph-node'+(a.id===selectedAgent?' selected':'')+(!matches(a,query)?' dimmed':''),transform:`translate(${p.x} ${p.y})`,tabindex:'0',role:'button','aria-label':`${a.display_name}, ${a.title||a.role}. ${directCount(a.id)} reportes directos. Abrir perfil.`});
    card.append(svgNode('title',{},`${a.display_name}\n${a.title||a.role}\n${a.mission||''}`),svgNode('rect',{class:'node-box',width:220,height:96,rx:12}),svgNode('rect',{class:'node-avatar',x:14,y:15,width:30,height:30,rx:9}),svgNode('text',{class:'node-initial',x:29,y:35,'text-anchor':'middle'},initials(a.display_name)),svgNode('text',{class:'node-name',x:54,y:27},shorten(a.display_name,23)),svgNode('text',{class:'node-role',x:54,y:44},shorten(a.role||a.title,24)),svgNode('text',{class:'node-meta',x:15,y:65},shorten(a.title||a.department,37)),svgNode('text',{class:'node-meta',x:15,y:82},`${directCount(a.id)}/${maximum} directos · ${shorten(a.model||'Sin modelo',24)}`));
    card.addEventListener('click',()=>openInspector(a.id));card.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openInspector(a.id);}});cards.append(card);
  });
  applyZoom();const version=String(state.organization.state_version||1)+'-'+all.length;if(version!==lastGraphVersion){graphFirstView=true;lastGraphVersion=version;}
}
function applyZoom(){zoom=Math.min(1.8,Math.max(.02,zoom));$('#org-tree').setAttribute('width',Math.round(graphSize.width*zoom));$('#org-tree').setAttribute('height',Math.round(graphSize.height*zoom));$('#zoom-label').textContent=Math.round(zoom*100)+'%';}
function centerOnRoot(){const vp=$('#graph-viewport');vp.scrollTop=Math.max(0,(graphSize.height*zoom-vp.clientHeight)/2);vp.scrollLeft=0;}
function renderProfiles(){
  const filter=$('#department-filter'),selected=filter.value;filter.replaceChildren(option('','Todos los departamentos'));[...new Set(agents().map(a=>a.department))].sort().forEach(d=>filter.append(option(d,d)));filter.value=selected;
  const roleFilter=$('#profile-role-filter'),roleValue=roleFilter.value;roleFilter.replaceChildren(option('','Todos los roles'));[...new Set(agents().map(a=>a.role))].sort().forEach(role=>roleFilter.append(option(role,role)));roleFilter.value=roleValue;const query=$('#profile-search').value.trim(),status=$('#skill-status-filter').value;
  const found=agents().filter(a=>matches(a,query)&&(!roleFilter.value||a.role===roleFilter.value)&&(!filter.value||a.department===filter.value)&&(!status||(a.skills||[]).some(s=>status==='verified'?s.verified_level!=null:s.verified_level==null)));
  $('#profile-count').textContent=found.length+' / '+agents().length+' perfiles';$('#profile-empty').hidden=found.length>0;
  const grid=$('#profile-grid');grid.replaceChildren();found.forEach((a,i)=>{const card=node('button',undefined,'profile-card');card.type='button';card.setAttribute('aria-label','Abrir perfil de '+a.display_name);const top=node('div',undefined,'profile-card-top');top.append(node('span',initials(a.display_name),'avatar tone-'+i%4),node('span',a.department,'tag'));card.append(top,node('h3',a.display_name),node('p',a.title||a.role,'profile-title'),node('p',a.mission||'Misión pendiente de completar.','profile-mission'));const meta=node('div',undefined,'profile-meta');meta.append(node('span',(a.skills||[]).length+' habilidades'),node('span',directCount(a.id)+' directos'),node('span','Diseñado'));card.append(meta);card.onclick=()=>openInspector(a.id);grid.append(card);});
}
function openInspector(id){
  const a=agents().find(item=>item.id===id);if(!a)return;selectedAgent=id;profileDirty=false;permissionsDirty=false;inspectorBaseVersion=state.organization.state_version||1;permissionBaseVersion=inspectorBaseVersion;$('#inspector-notice').hidden=true;
  $('#agent-id').value=id;$('#inspector-title').textContent=a.display_name;$('#inspector-role').textContent=a.title||a.role;$('#inspector-avatar').textContent=initials(a.display_name);
  $('#agent-name').value=a.display_name||'';$('#agent-title').value=a.title||a.role||'';$('#agent-department').value=a.department||'';$('#agent-mission').value=a.mission||'';$('#agent-personality').value=a.personality||(a.cv?.working_style||[]).join('\n');
  const supervisor=$('#agent-supervisor');supervisor.replaceChildren();supervisor.append(option('OWNER_EXTERNAL','Owner externo'));
  const descendants=new Set([id]);let changed=true;while(changed){changed=false;agents().forEach(x=>{if(descendants.has(x.reports_to)&&!descendants.has(x.id)){descendants.add(x.id);changed=true;}});}
  agents().filter(x=>!descendants.has(x.id)).forEach(x=>{const count=directCount(x.id);const op=option(x.id,`${x.display_name} · ${count}/${state.config.max_direct_reports} directos`);op.disabled=count>=state.config.max_direct_reports&&x.id!==a.reports_to;supervisor.append(op);});supervisor.value=a.reports_to;
  const isRoot=a.reports_to==='OWNER_EXTERNAL';supervisor.disabled=isRoot;supervisor.options[0].disabled=!isRoot;
  $('#inspector-supervision').textContent=`${directCount(a.id)} de ${state.config.max_direct_reports} reportes directos. ${isRoot?'El CEO permanece bajo el Owner externo.':'Cambiar supervisor activa jerarquía manual y requiere validación de ciclos y límites.'}`;
  $('#inspector-model').textContent=`Modelo: ${a.provider} / ${a.model} · ${a.model_status==='unavailable'?'No disponible':a.model_status==='available'?'Disponibilidad observada; tarea no verificada':'Sin verificar'}. ID: ${a.id}`;const responsibilities=$('#inspector-responsibilities');responsibilities.replaceChildren(node('h4','Responsabilidades'),node('p',(a.responsibilities||[]).map(x=>'• '+x).join('\n')),node('h4','Entregables'),node('p',(a.deliverables||[]).map(x=>'• '+x).join('\n')));$('#profile-version').textContent='Versión de diseño '+(state.organization.state_version||1)+(state.generation_stale?' · desactualizado':'');
  const skills=$('#inspector-skills');skills.replaceChildren();(a.skills||[]).forEach(s=>{const chip=node('div',s.name,'skill-chip');chip.append(node('small',`Objetivo ${s.target_level??'—'} · ${s.verified_level==null?'Sin verificar':'Nivel verificado '+s.verified_level}`));skills.append(chip);});
  $('#agent-skills').value=(a.skills||[]).map(s=>s.name).join('\n');$('#agent-proposed-skills').value=(a.proposed_skills||[]).map(s=>typeof s==='string'?s:s.name).join('\n');
  const cv=$('#inspector-cv');cv.replaceChildren();const data=a.cv||{};cv.append(node('p',data.disclaimer||'Persona ficticia y CV aspiracional; sin credenciales verificadas.','helper'),node('p',data.summary||'No hay resumen de CV.'));['experience','education','certifications'].forEach((key,i)=>{cv.append(node('h4',['Experiencia objetivo','Formación aspiracional','Certificaciones objetivo'][i]));(data[key]||[]).forEach(row=>{const card=node('article',undefined,'cv-entry');if(typeof row==='string')card.append(node('p',row));else Object.entries(row).forEach(([k,v])=>{if(v!=null)card.append(node('p',(cvFieldLabels[k]||k)+': '+(Array.isArray(v)?v.map(textValue).join('\n• '):textValue(v))));});cv.append(card);});});['languages','working_style','research_interests','portfolio'].forEach(key=>{if(data[key]?.length)cv.append(node('h4',cvFieldLabels[key]||key),node('p',Array.isArray(data[key])?data[key].map(textValue).join('\n'):textValue(data[key])));});
  $('#inspector-provenance').textContent=(a.profile_source==='api_structured'?'Perfil diseñado mediante API':'Perfil sintético; procedencia: '+(a.profile_source||'plantilla local / no informada'))+'\n'+(a.evidence_paths?.length?'Rutas de evidencia: '+a.evidence_paths.join(' · '):'Sin rutas de evidencia específicas declaradas.')+(a.tool_mapping_status?'\nMapeo de herramientas: '+a.tool_mapping_status:'');
  $('#inspector-prompt').textContent=a.system_prompt||'Prompt todavía no generado.';
  renderCommandProfile(a);loadToolPolicy(a);renderToolRecommendations();renderToolCatalog();
  if(!$('#profile-dialog').open)$('#profile-dialog').showModal();setBusy(busy);
}
function closeInspector(){if((profileDirty||permissionsDirty)&&!confirm('¿Descartar las ediciones de perfil o permisos que aún no guardaste?'))return;profileDirty=false;permissionsDirty=false;$('#profile-dialog').close();}
function populateAgentSelect(el,allowEmpty=false){const previous=el.value;el.replaceChildren();if(allowEmpty)el.append(option('','Sin responsable asignado'));agents().forEach(a=>el.append(option(a.id,a.display_name+' · '+a.role)));if([...el.options].some(o=>o.value===previous))el.value=previous;}
function currentCouncil(){return (state?.council_sessions||[]).find(s=>s.id===selectedCouncil);}
function renderCouncil(){
  const all=agents(),ids=state.organization?.council?.members||all.map(a=>a.id);$('#nav-council-count').textContent=ids.length||state.config.agent_count;$('#council-count').textContent=ids.length+' miembros';
  const members=$('#council-members');members.replaceChildren();all.filter(a=>ids.includes(a.id)).forEach((a,i)=>{const row=node('button',undefined,'member');row.type='button';const text=node('span');text.append(node('strong',a.display_name),node('small',a.title||a.role));row.append(node('span',initials(a.display_name),'avatar tone-'+i%4),text,node('span',(currentCouncil()?.entries||[]).some(e=>e.agent_id===a.id)?'Aporte manual':'Sin aporte manual'));row.onclick=()=>openInspector(a.id);members.append(row);});
  if(!all.length)members.append(node('p','Genera la organización para ver a sus miembros.','helper'));
  populateAgentSelect($('#council-member'));
  const select=$('#council-session');select.replaceChildren(option('','Crear acta nueva'));(state.council_sessions||[]).forEach(s=>select.append(option(s.id,s.title+' · '+(s.status==='open_manual_record'?'abierta':'cerrada'))));select.value=selectedCouncil;if(!select.value)selectedCouncil='';
  const session=currentCouncil(),records=$('#council-records');records.replaceChildren();
  $('#council-session-status').textContent=session?`${new Set((session.entries||[]).map(e=>e.agent_id).filter(id=>(session.members||[]).includes(id))).size} / ${(session.members||[]).length} miembros con aporte manual · ${(session.entries||[]).length} entradas · ${session.status==='open_manual_record'?'abierta':'cerrada'} · ejecución de agentes no verificada`:'Crear una nueva acta no pone en marcha el Council.';
  const sessions=session?[session]:(state.council_sessions||[]).slice().reverse();sessions.forEach(s=>{const record=node('article',undefined,'record');record.append(node('h3',s.title),node('time',localDate(s.created_at)),node('p','Acta manual · '+(s.status==='open_manual_record'?'abierta':'cerrada')+' · sin ejecución DSH'));(s.entries||[]).forEach(entry=>{const a=all.find(x=>x.id===entry.agent_id);record.append(node('strong',(a?.display_name||entry.agent_id||'Entrada humana')+' · '+({fact:'Hecho',risk:'Riesgo',objection:'Objeción',proposal:'Propuesta',decision:'Decisión'}[entry.type]||entry.type)),node('p',entry.text));if(entry.evidence?.length)record.append(node('p','Referencias: '+entry.evidence.join('\n'),'helper'));});if(s.summary)record.append(node('p','Cierre: '+s.summary));const heard=new Set((s.entries||[]).map(e=>e.agent_id));const missing=(s.members||[]).filter(id=>!heard.has(id));record.append(node('p',`${missing.length} miembros sin aportes manuales asociados. Esto no mide participación real de agentes.`,'helper'));records.append(record);});
}
function renderSkills(){
  const body=$('#skills-table');body.replaceChildren();const query=$('#skills-search').value.toLowerCase().trim(),filter=$('#skills-filter').value;let count=0;
  agents().forEach(a=>(a.skills||[]).forEach(s=>{const verified=s.verified_level!=null;if(query&&!(s.name+' '+a.display_name).toLowerCase().includes(query))return;if(filter&&(filter==='verified')!==verified)return;count++;const row=node('tr'),profile=node('td'),link=node('button',a.display_name,'textbutton');link.type='button';link.onclick=()=>openInspector(a.id);profile.append(link);row.append(node('td',s.name),profile,node('td',s.target_level??'—'),node('td',verified?'Nivel '+s.verified_level+' registrado':'Sin verificar'),node('td',s.evidence||'Sin evidencia aportada'));body.append(row);}));
  $('#skills-count').textContent=count+' competencias';if(!count)emptyRow(body,5,'No hay competencias que coincidan con el filtro.');
  const proposals=$('#skill-proposals');proposals.replaceChildren();
  const builtins=[{name:'webapp-testing',description:'Propuesta: pruebas de flujos, estados interrumpidos y regresión de la app. Requiere revisión y evidencia antes de instalar.',status:'proposed'},{name:'systematic-debugging',description:'Propuesta: reproducción, diagnóstico de causa raíz y retest independiente. No instalada.',status:'proposed'}];
  const rows=[...(state.skill_registry||[]),...(state.organization?.competency_gaps||[]),...builtins];const seen=new Set();rows.forEach(s=>{if(seen.has(s.name))return;seen.add(s.name);const card=node('article',undefined,'proposal');card.append(node('h3',s.name),node('p',s.description||'Propuesta pendiente de revisión.'),node('span',skillStatus(s.status)+' · no instalada','tag amber'));if(s.evidence?.length)card.append(node('p','Evidencia: '+s.evidence.join('\n'),'helper'));if(s.id&&(state.skill_registry||[]).some(x=>x.id===s.id)){const btn=node('button','Actualizar revisión','textbutton');btn.type='button';btn.onclick=()=>updateSkill(s);card.append(btn);}proposals.append(card);});
  populateAgentSelect($('#skill-owner'),true);populateAgentSelect($('#remediation-agent'));renderSkillFeedback();
  const remediations=$('#remediation-list');remediations.replaceChildren();(state.remediation_records||[]).forEach(r=>{const a=agents().find(x=>x.id===r.agent_id),record=node('article',undefined,'record');record.append(node('h3',(a?.display_name||r.agent_id)+' · '+remediationStatus(r.status)),node('p',r.failure),node('p','Esperado: '+r.expected+'\nObservado: '+r.actual));if(r.evidence?.length)record.append(node('p',r.evidence.join('\n'),'helper'));const button=node('button','Registrar siguiente paso','textbutton');button.type='button';button.onclick=()=>updateRemediation(r);record.append(button);remediations.append(record);});if(!(state.remediation_records||[]).length)remediations.append(node('p','No se han registrado fallos. Ausencia de registros no equivale a pruebas superadas.','helper'));
}
function skillStatus(s){return ({proposed:'Propuesta',under_review:'En revisión',test_reported:'Prueba declarada',approved_manual:'Aprobación manual',rejected:'Rechazada'})[s]||'Propuesta';}
function remediationStatus(s){return ({observed:'Observado',proposed:'Corrección propuesta',testing:'Pruebas declaradas',supervisor_review:'Revisión supervisor',independent_review:'Revisión independiente',closed:'Cierre manual',rejected:'Rechazado'})[s]||s;}
async function updateSkill(skill){const status=prompt('Estado: proposed, under_review, test_reported, approved_manual o rejected. Aprobar manualmente no instala ni verifica la skill.',skill.status||'under_review');if(!status)return;if(!['proposed','under_review','test_reported','approved_manual','rejected'].includes(status)){message('Estado de revisión no admitido.','error');return;}const note=prompt('Nota de revisión (necesaria):');if(!note)return;const evidence=prompt('Referencias de evidencia, una por línea:','');if(evidence===null)return;await action('skill-update',{skill_id:skill.id,status,note,evidence:lines(evidence)});}
async function updateRemediation(record){const options=['observed','proposed','testing','supervisor_review','independent_review','closed','rejected'];const next={observed:'proposed',proposed:'testing',testing:'supervisor_review',supervisor_review:'independent_review',independent_review:'closed'}[record.status]||'proposed';const status=prompt('Siguiente estado: '+options.join(', ')+'. El motor valida el orden y la independencia.',next);if(!status)return;if(!options.includes(status)){message('Estado de remediación no admitido.','error');return;}const note=prompt('Describe el cambio y el resultado declarado:');if(!note)return;const evidence=prompt('Referencias de evidencia, una por línea:','');if(evidence===null)return;let reviewer_id;if(['supervisor_review','independent_review','closed'].includes(status)){reviewer_id=prompt('ID exacto del revisor. Puedes consultar los IDs en el ADN exportado. El motor verifica independencia:','');if(!reviewer_id)return;}await action('remediation-update',{remediation_id:record.id,status,note,evidence:lines(evidence),...(reviewer_id?{reviewer_id}:{})});}
function selectDesignModel(model){
  if(busy||generationOperation||generationActive()||model.available===false)return;
  const form=$('#config-form');form.elements.provider.value=model.provider;form.elements.model.value=model.model||model.id;
  configDirty=true;location.hash='configuration';renderGeneration();setBusy(busy);
  message('ID de API seleccionado: '+(model.model||model.id)+'. Confirma la selección antes de preparar. Las rutas del diseño existente no se han cambiado.');
}
function generationProviderRoute(provider){return ({'deepseek-official':'deepseek','zai-official':'zai'})[provider]||provider;}
function generationCatalogRows(provider){
  const route=generationProviderRoute(provider),rows=(state?.models||[]).filter(m=>generationProviderRoute(m.provider)===route&&m.catalog_scope!=='dsh_runtime'&&m.catalog_scope!=='dsh_runtime_reference');
  const unique=new Map();for(const row of rows){const id=row.model||row.id;if(!id)continue;const previous=unique.get(id);if(!previous||generationModelVerified(row))unique.set(id,row);}return [...unique.values()];
}
function generationModelVerified(row){return row?.available===true&&(row.source==='live_api'||row.status==='VERIFIED_INFERENCE'||(row.source==='live_inference'&&row.availability_verified===true));}
function generationDocumentedModel(row,provider){return generationProviderRoute(provider)==='zai'&&row?.source==='official_docs_snapshot'&&row.available!==false;}
function renderGenerationModelChoice(){
  const form=$('#config-form'),provider=form.elements.provider.value,selected=form.elements.model.value.trim(),rows=generationCatalogRows(provider),row=rows.find(m=>(m.model||m.id)===selected),select=$('#generation-model-select'),list=$('#model-list');
  const fingerprint=[provider,selected,row?.source,row?.status,row?.checked_at].join(':');if(generationModelFingerprint!==fingerprint){$('#generation-manual-model').checked=false;generationModelFingerprint=fingerprint;}
  select.replaceChildren(option('',rows.length?'Selecciona el ID de API exacto':'Consulta primero el catálogo'));list.replaceChildren();
  rows.sort((a,b)=>Number(generationModelVerified(b))-Number(generationModelVerified(a))).forEach(m=>{const id=m.model||m.id,verified=generationModelVerified(m),documented=generationDocumentedModel(m,provider),label=(m.name&&m.name!==id?m.name+' · ':'')+'ID API: '+id+' · '+(verified?'observado en cuenta':documented?'referencia manual':'sin verificar');const item=option(id,label);item.disabled=!verified&&!documented;select.append(item);if(verified||documented)list.append(option(id,label));});
  select.value=rows.some(m=>(m.model||m.id)===selected)?selected:'';
  const verified=generationModelVerified(row),documented=generationDocumentedModel(row,provider),status=$('#generation-model-status');
  status.textContent=row?.status==='ACCOUNT_RECHECK_REQUIRED'?'La clave o la cuenta cambió. Vuelve a consultar el catálogo para verificar este ID en la cuenta actual.':verified&&provider!==state?.config?.provider?'ID observado para el proveedor guardado. La cuenta del proveedor pendiente se comprobará al preparar; consulta su catálogo si cambiaste de clave.':verified?'ID exacto observado '+(row.status==='VERIFIED_INFERENCE'?'en una inferencia previa':'en el catálogo de esta cuenta')+'. Esto no verifica precio, calidad ni todas las capacidades.':documented?'Referencia documentada de Z.AI: disponibilidad de cuenta y capacidades sin verificar. Revisa y confirma la selección manual antes de preparar.':row?.available===false?'Este ID figura como no disponible. Elige otro ID del catálogo; no se sustituirá automáticamente.':'Este ID aún no está verificado para la API. Consulta el catálogo y elige un ID exacto. Un nombre visible o alias de DSH no verifica disponibilidad.';
  const facts=$('#generation-model-identity');facts.replaceChildren();appendFact(facts,'Nombre visible del catálogo',row?.name||'No informado');appendFact(facts,'ID exacto que recibirá la API',selected||'Sin seleccionar');
  const routes=[...new Set(agents().filter(a=>generationProviderRoute(a.provider)===generationProviderRoute(provider)).map(a=>a.provider+' / '+a.model))];appendFact(facts,'Rutas del diseño DSH conservado',routes.length?routes.slice(0,6).join(' · ')+(routes.length>6?' · otras '+(routes.length-6):''):'Sin rutas conservadas para este proveedor');appendFact(facts,'Alias y disponibilidad en DSH','No verificados por el catálogo API; no se modifica el runtime.');
  $('#generation-manual-model-label').hidden=!documented;
}
async function discoverGenerationModels(fromConfiguration=true){
  if(busy||generationOperation||generationActive()||!state)return;
  const provider=fromConfiguration?$('#config-form').elements.provider.value:state.config.provider,documented=generationProviderRoute(provider)==='zai';
  if(!documented&&!(state.credentials_configured||[]).includes(provider)){message('Prepara primero la clave del proveedor seleccionado para consultar su catálogo de cuenta.','error');return;}
  if(!confirm((documented?'¿Cargar las referencias documentadas de '+provider+'? No consulta la disponibilidad de tu cuenta.':'¿Consultar el catálogo de cuenta de '+provider+'? La clave preparada se enviará únicamente al endpoint autorizado; no hace una inferencia.')+(provider!==state.config.provider?' Se guardará el cambio de proveedor; los demás campos pendientes se conservan para revisar.':'')+' No cambia las rutas del diseño DSH conservado ni ejecuta DSH.'))return;
  await run('Consultando el catálogo, sin inferencia…',async()=>{if(provider!==state.config.provider){configDirty=true;await request('config',{config:{provider}});}await request('discover-models',Object.assign({confirmed:true},discoverConsent()));},documented?'Referencias documentadas cargadas. La disponibilidad de tu cuenta sigue sin verificar.':'Catálogo de cuenta consultado. Elige el ID exacto; no se inició una inferencia.');
}
$('#generation-discover-models').onclick=()=>discoverGenerationModels(true);
$('#generation-model-select').onchange=()=>{const form=$('#config-form'),id=$('#generation-model-select').value,row=generationCatalogRows(form.elements.provider.value).find(m=>(m.model||m.id)===id);if(!row||(!generationModelVerified(row)&&!generationDocumentedModel(row,form.elements.provider.value)))return;selectDesignModel({...row,provider:form.elements.provider.value});};
$('#generation-manual-model').onchange=()=>{if(generationActive()){generationReviewStale=true;$('#generation-consent').checked=false;}updateGenerationControls(busy);};
function renderModels(){populateAgentSelect($('#model-agent'));renderModelAssignment();const body=$('#model-table'),list=$('#model-list');body.replaceChildren();list.replaceChildren();(state.models||[]).forEach(m=>{const row=node('tr');[m.provider,m.model||m.id,m.available===true?'Disponible observado':m.available===false?'No disponible':'Sin verificar',[m.source||m.status||'Sin fuente',m.checked_at?localDate(m.checked_at):''].filter(Boolean).join(' · ')].forEach(v=>row.append(node('td',v)));const selection=node('td'),choose=node('button','Usar este ID para diseño','secondary');choose.type='button';choose.disabled=busy||generationActive()||m.available===false;choose.onclick=()=>selectDesignModel(m);selection.append(choose);row.append(selection);const cell=node('td'),rank=node('input');rank.type='number';rank.min='1';rank.max='100000';rank.value=m.user_rank||'';rank.className='model-rank';rank.dataset.provider=m.provider;rank.dataset.model=m.model||m.id;rank.setAttribute('aria-label','Prioridad de '+(m.model||m.id));cell.append(rank);row.append(cell);body.append(row);if(m.provider===state.config.provider)list.append(option(m.model||m.id,(m.model||m.id)+(m.name?' · '+m.name:'')));});if(!(state.models||[]).length)emptyRow(body,6,'Todavía no se ha consultado ningún catálogo real en esta sesión.');}
function renderModelAssignment(){const override=state.model_overrides?.[$('#model-agent').value]||{};$('#model-agent-provider').value=override.provider||'';$('#model-agent-model').value=override.model||'';}
$('#model-agent').onchange=renderModelAssignment;
$('#model-assignment-form').onsubmit=async e=>{e.preventDefault();if(!state.organization)return;const id=$('#model-agent').value,provider=$('#model-agent-provider').value,model=$('#model-agent-model').value.trim(),assignments=JSON.parse(JSON.stringify(state.model_overrides||{}));if(provider||model)assignments[id]={...(provider?{provider}:{}),...(model?{model}:{})};else delete assignments[id];await action('model-overrides',{assignments,expected_state_version:state.organization.state_version||1},'Asignación de modelo guardada. Se conserva el diseño; disponibilidad y calidad se verifican por separado.');};
$('#save-model-preferences').onclick=async()=>{const preferences=$$('.model-rank').map(input=>{const model=state.models.find(m=>m.provider===input.dataset.provider&&(m.model||m.id)===input.dataset.model),row={provider:input.dataset.provider,model:input.dataset.model};if(input.value)row.user_rank=Number(input.value);if(model?.capabilities)row.capabilities=model.capabilities;return row;});if(preferences.some(p=>p.user_rank!==undefined&&(!Number.isInteger(p.user_rank)||p.user_rank<1||p.user_rank>100000))){message('Las prioridades deben ser enteros entre 1 y 100.000.','error');return;}await action('model-preferences',{preferences,...(state.organization?{expected_state_version:state.organization.state_version||1}:{})});};
function renderAnalysis(){const analysis=state.analysis||state.repo_inventory,box=$('#analysis-summary');box.hidden=!analysis;box.textContent=analysis?[typeof analysis.summary==='string'?analysis.summary:'',JSON.stringify(analysis,null,2)].filter(Boolean).join('\n\n'):'';const pending=state.pending_consent?.job_id?null:state.pending_consent;$('#consent-box').hidden=!pending;$('#analysis-partial-label').hidden=!pending?.partial_inventory_required;$('#consent-details').textContent=pending?JSON.stringify(pending,null,2):'';if(consentId!==pending?.approval_id){$('#review-consent').checked=false;$('#budget-consent').checked=false;$('#analysis-partial-consent').checked=false;consentId=pending?.approval_id;}}
function renderReceipts(){const target=$('#receipt-list');target.replaceChildren();(state.receipts||[]).slice().reverse().forEach(r=>{const el=node('article',undefined,'receipt '+String(r.status).replace(/[^a-z_-]/gi,''));el.append(node('time',localDate(r.timestamp)),node('span',r.action+' · '+r.status,'status'),node('span',r.message,'message'));target.append(el);});if(!(state.receipts||[]).length)target.append(node('p','No hay acciones registradas en esta sesión.','empty'));}
async function refreshProjects(silent=false){try{const res=await fetch('/api/projects',{credentials:'same-origin'});const data=await res.json();if(!res.ok)throw new Error(data.error||'No se pudo leer la lista de proyectos.');projects=data.projects||[];const select=$('#project-list'),current=select.value;select.replaceChildren(option('','Selecciona un proyecto'));projects.forEach(p=>select.append(option(p.project_id,`${p.name} · ${p.version_count||1} versiones`)));select.value=projects.some(p=>p.project_id===current)?current:(state.project?.id||'');renderProjectVersions();if(!silent)message('Lista de proyectos locales actualizada.');}catch(e){if(!silent)message(e.message,'error');}setBusy(busy);}
function renderProjectVersions(){const select=$('#project-version'),project=projects.find(p=>p.project_id===$('#project-list').value);select.replaceChildren(option('','Última versión'));(project?.versions||[]).forEach(v=>{const id=typeof v==='string'?v:v.version_id;select.append(option(id,id));});setBusy(busy);}
async function saveProject(asNew=false){const name=$('#project-name').value.trim();if(!name){$('#project-name').reportValidity();return;}if(configDirty&&!confirm('Tienes cambios de configuración sin aplicar. Esta versión guardará el estado actual del motor. ¿Continuar?'))return;if(await action('project-save',{name,as_new:asNew},'Proyecto guardado localmente, sin claves ni consentimientos.'))await refreshProjects(true);}
async function generate(){const edited=state?.has_manual_edits===true;if(edited&&!confirm('Regenerar sustituirá las ediciones manuales del diseño. Guarda antes una versión si deseas conservarlas. ¿Regenerar ahora?'))return;if(configDirty){message('Guarda primero los cambios de configuración antes de generar.','error');location.hash='configuration';return;}await action('generate',edited?{confirmed_discard_edits:true}:{},'Plantilla offline creada. No se llamó al modelo ni se realizó una nueva lectura de la fuente.');}
$('#config-form').addEventListener('input',e=>{if(e?.target?.id==='generation-manual-model')return;configDirty=true;if(e?.target?.name==='runtime_token_budget')runtimeBudgetAutomatic=false;if(generationActive()){generationReviewStale=true;$('#generation-consent').checked=false;}renderSourceChoice();renderGeneration();renderOrchestrationChoice();renderAutonomy();setBusy(busy);});
$('#config-form').addEventListener('submit',async e=>{e.preventDefault();const config=readGenerationConfig();const ok=await action('config',{config});if(ok){configDirty=false;render();}});
$('#config-form').elements.agent_count.addEventListener('input',e=>{const form=$('#config-form');form.elements.council_concurrency.value=e.target.value;if(runtimeBudgetAutomatic)form.elements.runtime_token_budget.value=Math.max(24000,Number(e.target.value||1)*12000);});
$('#generate').onclick=prepareGeneration;$('#prepare-generation').onclick=prepareGeneration;$('#generate-offline').onclick=generate;$$('[data-generate]').forEach(b=>b.onclick=generate);
$('#profile-form').addEventListener('input',()=>{profileDirty=true;});
$('#profile-form').addEventListener('submit',async e=>{e.preventDefault();const a=agents().find(x=>x.id===$('#agent-id').value);if(!a)return;const edit={id:a.id,display_name:$('#agent-name').value,title:$('#agent-title').value,department:$('#agent-department').value,mission:$('#agent-mission').value,personality:$('#agent-personality').value};if($('#agent-supervisor').value!==a.reports_to)edit.reports_to=$('#agent-supervisor').value;const skills=lines($('#agent-skills').value);if(JSON.stringify(skills)!==JSON.stringify((a.skills||[]).map(s=>s.name)))edit.skills=skills;const proposed=lines($('#agent-proposed-skills').value);if(JSON.stringify(proposed)!==JSON.stringify((a.proposed_skills||[]).map(s=>typeof s==='string'?s:s.name)))edit.proposed_skills=proposed;const edits={expected_state_version:inspectorBaseVersion,agents:[edit]};if(edit.reports_to)edits.hierarchy_mode='manual';const ok=await action('edit-organization',{edits},'Perfil actualizado y estructura validada. Guarda una versión para conservarlo al cerrar el motor.');if(ok){profileDirty=false;inspectorBaseVersion=state.organization.state_version||1;permissionBaseVersion=inspectorBaseVersion;if(!permissionsDirty)$('#profile-dialog').close();else message('Perfil guardado. Tu borrador de permisos todavía está pendiente.');}});
$('#close-inspector').onclick=closeInspector;$('#cancel-inspector').onclick=closeInspector;$('#profile-dialog').addEventListener('cancel',e=>{e.preventDefault();closeInspector();});
$('#org-search').addEventListener('input',renderGraph);$('#profile-search').addEventListener('input',renderProfiles);$('#department-filter').onchange=renderProfiles;$('#profile-role-filter').onchange=renderProfiles;$('#skill-status-filter').onchange=renderProfiles;$('#skills-search').addEventListener('input',renderSkills);$('#skills-filter').onchange=renderSkills;
$('#hierarchy-reset').onclick=()=>{if(!state?.organization)return;if(confirm('¿Restaurar la jerarquía automática? Se reorganizarán los supervisores según el orden del equipo y el máximo de reportes directos. Los perfiles se conservan.'))action('edit-organization',{edits:{expected_state_version:state.organization.state_version||1,hierarchy_mode:'automatic',agents:[]}});};
$('#zoom-in').onclick=()=>{zoom+=.15;applyZoom();};$('#zoom-out').onclick=()=>{zoom-=.15;applyZoom();};$('#zoom-fit').onclick=()=>{const vp=$('#graph-viewport');zoom=Math.min(1,(vp.clientWidth-48)/graphSize.width,(vp.clientHeight-48)/graphSize.height);applyZoom();vp.scrollTop=0;vp.scrollLeft=0;};
$('#project-save-form').onsubmit=e=>{e.preventDefault();saveProject(false);};$('#project-save-new').onclick=()=>saveProject(true);$('#project-refresh').onclick=()=>refreshProjects();$('#project-list').onchange=renderProjectVersions;
$('#project-load-form').onsubmit=async e=>{e.preventDefault();const id=$('#project-list').value;if(!id)return;if((state.project?.dirty||configDirty||hasOperationalDrafts())&&!confirm('¿Cargar este proyecto y descartar los cambios sin guardar del estado actual?'))return;const data={project_id:id,confirmed:true};if($('#project-version').value)data.version_id=$('#project-version').value;const ok=await action('project-load',data);if(ok){configDirty=false;selectedCouncil='';discardOperationalDrafts();render();await refreshProjects(true);}};
$('#key-form').onsubmit=async e=>{e.preventDefault();if(busy||generationActive())return;const f=e.target,config=readGenerationConfig();const data={provider:config.provider,api_key:f.elements.api_key.value,persist:f.elements.persist.checked,auto_discover:true};f.elements.api_key.value='';if(configDirty){if(!$('#config-form').reportValidity()||!await action('config',{config}))return;configDirty=false;render();}await action('credentials',data,'Clave preparada en el motor local. No se ha llamado al proveedor.');};
$('#forget-key').onclick=()=>{if(confirm('¿Olvidar las claves de memoria y el almacén DPAPI guardado por esta app?'))action('forget-credentials');};
// El catálogo automático ya no se auto-autoriza: si hay un consentimiento pendiente
// de discover-models, la confirmación humana debe citar su approval_id y su payload_sha256.
function discoverConsent(){const p=state&&state.pending_consent;return p&&p.kind==='discover_models'?{consent_id:p.approval_id,payload_sha256:p.payload_sha256}:{};}
$('#discover-models').onclick=()=>{if(confirm(`¿Consultar ahora el catálogo de ${state.config.provider}? La clave preparada se enviará únicamente al endpoint autorizado de ese proveedor. No hace una inferencia ni demuestra precio o calidad.`))action('discover-models',Object.assign({confirmed:true},discoverConsent()));};
$('#prepare-verification').onclick=async()=>{if(await action('prepare-verification')){location.hash='repositorio';requestAnimationFrame(()=>$('#consent-box').scrollIntoView({block:'start'}));}};
$('#inventory').onclick=()=>{const deep=state.config.source_kind!=='website'&&$('#repo-scope').value==='deep';if(deep&&!confirm('¿Ampliar la lectura de GitHub hasta 60 archivos y 750 KB? Sólo inventario de lectura; no envío a un LLM. Puede quedar contenido sin leer.'))return;action('analyze-repository',deep?{profile:'deep',max_files:60,max_bytes:750000,budget_confirmed:true}:{});};
$('#prepare-analysis').onclick=()=>{const provider=state.config.provider,model=state.config.analysis_model||state.config.model,row=generationCatalogRows(provider).find(m=>(m.model||m.id)===model),manual=generationDocumentedModel(row,provider);if(manual&&!confirm('¿Preparar el análisis con el ID documentado '+model+' de '+provider+'? La disponibilidad de cuenta y sus capacidades siguen sin verificar. Esto sólo prepara el contenido para una autorización de envío posterior.'))return;action('prepare-analysis',{max_output_tokens:Number($('#analysis-tokens').value),...(manual?{manual_model_confirmed:true}:{})});};
$('#analysis-partial-consent').onchange=()=>setBusy(busy);$('#review-consent').onchange=()=>setBusy(busy);$('#budget-consent').onchange=()=>setBusy(busy);
$('#confirm-analysis').onclick=()=>{if(!state.pending_consent||!$('#review-consent').checked||!$('#budget-consent').checked||(state.pending_consent.partial_inventory_required&&!$('#analysis-partial-consent').checked))return;if(confirm('¿Enviar ahora la solicitud exacta mostrada al proveedor? Puede generar un cargo. Se consumirá este consentimiento y no habrá reintento automático.'))action('confirm-analysis',{confirmed:true,consent_id:state.pending_consent.approval_id,payload_sha256:state.pending_consent.payload_sha256,data_reviewed:true,budget_acknowledged:true,partial_inventory_acknowledged:$('#analysis-partial-consent').checked,coverage_sha256:state.pending_consent.coverage_sha256});};
$('#council-session').onchange=()=>{selectedCouncil=$('#council-session').value;const s=currentCouncil();if(s)$('#council-topic').value=s.title;renderCouncil();setBusy(busy);};
$('#council-form').onsubmit=async e=>{e.preventDefault();const topic=$('#council-topic').value.trim(),objection=$('#council-objection').value.trim(),decision=$('#council-decision').value.trim(),evidence=lines($('#council-evidence').value),agent_id=$('#council-member').value;if(!agents().length){message('Genera primero una organización.','error');return;}if(selectedCouncil&&currentCouncil()?.status!=='open_manual_record'){message('El acta está cerrada. Selecciona crear una nueva.','error');return;}const ok=await run('Guardando el acta manual local…',async()=>{if(!selectedCouncil){await request('council-create',{title:topic});selectedCouncil=state.council_sessions.at(-1).id;}if(objection){await request('council-add-entry',{session_id:selectedCouncil,agent_id,type:'objection',text:objection,evidence});$('#council-objection').value='';}if(decision){await request('council-add-entry',{session_id:selectedCouncil,agent_id,type:'decision',text:decision,evidence});$('#council-decision').value='';}},'Acta manual guardada. Ningún agente se ha iniciado ni se ha certificado consenso.');if(ok){$('#council-objection').value='';$('#council-decision').value='';$('#council-evidence').value='';}};
$('#council-close').onclick=async()=>{if(!selectedCouncil)return;const summary=prompt('Resumen de cierre manual. Este cierre no certifica participación de agentes ni resuelve la falta de evidencia:');if(summary)await action('council-close',{session_id:selectedCouncil,summary});};
$('#skill-register-form').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));data.evidence=lines(data.evidence);if(!data.owner_agent_id)delete data.owner_agent_id;if(await action('skill-register',data))e.target.reset();};
$('#remediation-form').onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));data.evidence=lines(data.evidence);if(await action('remediation-create',data))e.target.reset();};
$('#import-workbook').onclick=()=>action('import-workbook',{workbook:$('#workbook-path').value});$('#read-excel').onclick=()=>{if(!confirm('¿Abrir Excel por COM para leer la configuración del libro? Se lanzará PowerShell y se abrirá el archivo; no se guarda nada.'))return;action('read-excel',{workbook:$('#workbook-path').value,confirmed:true});};
$('#detach-workbook').onclick=()=>{if(confirm('¿Desvincular Excel? La app conservará su configuración y necesitará regenerar el diseño.'))action('detach-workbook');};
$('#reset-overrides').onclick=()=>{if(confirm('¿Quitar los overrides manuales? Regenera y aplica a Excel si deseas restaurar sus fórmulas de herencia.'))action('reset-model-overrides');};
$('#apply-excel').onclick=()=>{if(confirm('¿Aplicar los datos generados al libro seleccionado y guardarlo? Se reemplazarán los rangos de salida declarados. Se crea una copia de recuperación antes de escribir.'))action('apply-excel',{confirmed:true});};
$$('a[download]').forEach(a=>a.addEventListener('click',async e=>{e.preventDefault();if(busy||generationActive())return;if(a.getAttribute('aria-disabled')==='true'){message('Genera un diseño actualizado antes de descargar.','error');return;}setBusy(true);try{const res=await fetch(a.getAttribute('href'),{credentials:'same-origin'});if(!res.ok){const data=await res.json();throw new Error(data.error||'No se pudo exportar.');}const blob=await res.blob(),url=URL.createObjectURL(blob),link=node('a');link.href=url;link.download=downloadFilename(res.headers?.get('Content-Disposition'),a.dataset.filename||a.getAttribute('href').split('/').pop());document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);message('Archivo descargado: '+link.download+'. No se ha iniciado ningún agente.');}catch(err){message(err.message,'error');}finally{setBusy(false);}}));
window.addEventListener('hashchange',navigate);window.addEventListener('beforeunload',e=>{if(configDirty||profileDirty||permissionsDirty||hasOperationalDrafts()||generationActive()){e.preventDefault();e.returnValue='';}});
function renderSubteams(){
  const list=$('#subteam-list');list.replaceChildren();(state.subteams||[]).forEach(team=>{const card=node('article',undefined,'proposal');const members=(team.member_ids||[]).map(id=>agents().find(a=>a.id===id)?.display_name||id);card.append(node('h3',team.name),node('span',team.type==='audit'?'Auditoría propuesta':'Consultoría','tag'),node('p',team.scope),node('p',members.join(' · '),'helper'),node('p','Versión '+team.version+' · sin jefatura adicional','helper'));const edit=node('button','Editar subequipo','textbutton');edit.type='button';edit.onclick=()=>editSubteam(team);card.append(edit);list.append(card);});if(!(state.subteams||[]).length)list.append(node('p','Aún no hay subequipos guardados. Los pools del diseño siguen siendo propuestas.','helper'));
  const selected=new Set($$('#subteam-members input:checked').map(el=>el.value)),holder=$('#subteam-members');holder.replaceChildren();agents().forEach(a=>{const label=node('label',undefined,'check'),check=node('input');check.type='checkbox';check.value=a.id;check.checked=selected.has(a.id);check.onchange=renderFacilitators;label.append(check,node('span',a.display_name+' · '+a.role));holder.append(label);});renderFacilitators();
}
function renderFacilitators(){const select=$('#subteam-facilitator'),previous=select.value;select.replaceChildren(option('','Selecciona un miembro'));$$('#subteam-members input:checked').forEach(el=>{const a=agents().find(a=>a.id===el.value);if(a)select.append(option(a.id,a.display_name));});if([...select.options].some(o=>o.value===previous))select.value=previous;}
function editSubteam(team){$('#subteam-id').value=team.id;$('#subteam-name').value=team.name;$('#subteam-type').value=team.type;$('#subteam-scope').value=team.scope;$$('#subteam-members input').forEach(el=>el.checked=team.member_ids.includes(el.value));renderFacilitators();$('#subteam-facilitator').value=team.facilitator_id;$('#subteam-editor').open=true;$('#subteam-editor').scrollIntoView({block:'start'});}
$('#subteam-form').onsubmit=async e=>{e.preventDefault();const member_ids=$$('#subteam-members input:checked').map(el=>el.value);if(!member_ids.length){message('Selecciona al menos un miembro del subequipo.','error');return;}const data={name:$('#subteam-name').value,type:$('#subteam-type').value,member_ids,facilitator_id:$('#subteam-facilitator').value||member_ids[0],scope:$('#subteam-scope').value,expected_state_version:state.organization.state_version||1};if($('#subteam-id').value)data.id=$('#subteam-id').value;if(await action('subteam-save',data)){e.target.reset();$('#subteam-id').value='';renderFacilitators();}};
$('#new-subteam').onclick=()=>{$('#subteam-form').reset();$('#subteam-id').value='';renderFacilitators();};
function agentLabel(id){return agents().find(a=>a.id===id)?.display_name||(id==='OWNER_EXTERNAL'?'Owner externo':id||'Sin asignar');}
function renderCommandProfile(agent){
  const box=$('#inspector-command');box.replaceChildren();
  const chain=[],seen=new Set([agent.id]);let parent=agent.reports_to;
  while(parent&&!seen.has(parent)){seen.add(parent);chain.push(agentLabel(parent));parent=agents().find(a=>a.id===parent)?.reports_to;}
  box.append(node('h4','Cadena de mando'),node('p',[...chain.reverse(),agent.display_name].join(' → ')),node('h4','Supervisor directo'),node('p',agentLabel(agent.reports_to)));
  const direct=agents().filter(a=>a.reports_to===agent.id);box.append(node('h4','Subordinados directos'),node('p',direct.length?direct.map(a=>a.display_name+' · '+a.role).join('\n'):'Sin reportes directos.'));
  const command=agent.command||agent.command_profile||agent.command_contract||agent.supervision||{};
  box.append(node('h4','Reportes y escalado'),node('p',textValue(command.reporting_protocol||command.report_contract||command.reporting_obligations||'Informar al supervisor de objetivo, alcance, evidencias, bloqueos y siguiente paso. Una incidencia que exceda el mandato se escala; el organigrama no concede permisos runtime.')));
  for(const [key,label] of [['authority','Autoridad acotada'],['superior_directives','Instrucciones del superior'],['reasoned_dissent','Disenso razonado'],['blocking_rule','Bloqueo y escalado'],['resolved_disagreement','Después de una decisión válida']])if(command[key])box.append(node('h4',label),node('p',command[key]));
  if(agent.performance_contract?.report_fields)box.append(node('h4','Campos del reporte'),node('p',agent.performance_contract.report_fields.join(' · ')));
}
function catalogTools(){return state?.tool_catalog?.tools||[];}
function currentToolPreset(){const a=agents().find(x=>x.id===selectedAgent),roleNames={CEO:'Planner',CTO:'Implementer',ASSURANCE:'Reviewer',ARCHITECTURE:'Architect',BACKEND:'Backend',FRONTEND:'Frontend',DATA:'Data',INTEGRATION:'Integration',QUANT:'Quant',CONTRACTS:'Contracts',SECURITY:'Security',QA:'QA',PERFORMANCE:'Performance',SRE:'SRE',RELEASE:'Release',LEDGER:'Ledger',GRAPH:'GraphRouting',MARKET:'MarketMicrostructure',AI:'AIEngineering',SPEC:'Specification',OWNEROPS:'PersonalOps',E2E:'BrowserE2E',PARITY:'ModeParity',EVIDENCE:'EvidenceAuditor'};return (state?.tool_catalog?.role_presets||[]).find(p=>p.agent_id===a?.id)||(state?.tool_catalog?.role_presets||[]).find(p=>p.role===(roleNames[a?.role]||a?.name||a?.role));}
function readToolLists(){return {allow:lines($('#tools-allow').value),deny:lines($('#tools-deny').value)};}
function toolPolicyIssue(){
  const {allow,deny}=readToolLists(),known=new Set(catalogTools().map(t=>t.name));
  for(const [label,names] of [['Allow',allow],['Deny',deny]]){
    if(names.length>256)return label+': máximo 256 nombres por lista.';
    if(names.some(n=>n.length>200))return label+': cada nombre admite como máximo 200 caracteres.';
    if(new Set(names).size!==names.length)return label+': hay nombres duplicados.';
    if(names.join(',').length>51455)return label+': supera 51.455 caracteres CSV.';
    if(names.some(n=>/[,*\u0000-\u001f\u007f]/.test(n)))return label+': usa nombres exactos sin comas, comodines ni caracteres de control.';
  }
  if(!allow.length&&!deny.length)return 'Una política necesita allow o deny no vacío. Vaciar allow no equivale a bloquear todas las herramientas.';
  if(!allow.length&&!$('#inherit-parent-tools').checked)return 'Para usar sólo deny debes reconocer explícitamente la herencia presente y futura del padre.';
  const overlap=allow.find(n=>deny.includes(n));return overlap?'El nombre '+overlap+' aparece tanto en allow como en deny.':'';
}
function refreshToolCounters(){
  const {allow,deny}=readToolLists();$('#inherit-tools-label').hidden=Boolean(allow.length);for(const [label,names] of [['allow',allow],['deny',deny]])$('#'+label+'-counter').textContent=`${names.length} / 256 nombres · ${names.join(',').length.toLocaleString('es')} / 51.455 caracteres CSV`;
  const issue=toolPolicyIssue(),known=new Set(catalogTools().map(t=>t.name)),external=[...new Set([...allow,...deny])].filter(n=>!known.has(n));$('#permission-validation').textContent=issue||(external.length?external.length+' nombres externos: UNVERIFIED_EXTERNAL / UNKNOWN. Requieren comprobación exacta del runtime.':'Listas válidas como propuesta local. Disponibilidad runtime sin comprobar.');$('#permission-validation').classList.toggle('error-text',Boolean(issue));$('#save-tool-policy').disabled=busy||!state?.organization||state?.generation_stale===true||Boolean(issue);
}
function loadToolPolicy(agent){
  const policy=agent.tool_policy||agent.tool_permissions||agent.toolPermissions||{};$('#inherit-parent-tools').checked=policy.mode==='inherit_with_deny';$('#tools-allow').value=(policy.allow||[]).join('\n');$('#tools-deny').value=(policy.deny||[]).join('\n');permissionsDirty=false;permissionBaseVersion=state.organization.state_version||1;$('#permission-badge').textContent='UNKNOWN · '+(policy.allow||[]).length+' allow';refreshToolCounters();
}
function addToolDraft(name,target){
  const field=$(target==='allow'?'#tools-allow':'#tools-deny'),names=lines(field.value);if(names.includes(name))return;
  if(names.length>=256){message('La lista ya contiene 256 nombres. Quita uno antes de añadir otro.','error');return;}
  field.value=[...names,name].join('\n');permissionsDirty=true;refreshToolCounters();
}
function renderToolRecommendations(){
  const preset=currentToolPreset(),box=$('#tool-recommendations');box.replaceChildren();
  if(!preset){box.append(node('p','No hay una recomendación de rol disponible para este perfil.','helper'));return;}
  box.append(node('p','Candidatos para '+preset.role+'. Revisa el alcance antes de guardar; no se aplican automáticamente.','helper'));
  for(const [key,label] of [['allow_candidates','Candidatos relevantes para el rol'],['conditional_candidates','Requieren revisión del contexto'],['excluded_candidates','Fuera de la propuesta base']])box.append(node('h4',label),node('p',(preset[key]||[]).join(', ')||'Sin candidatos.','exact-names'));
}
function renderToolCatalog(){
  const list=$('#tool-catalog-list'),tools=catalogTools(),query=$('#tool-search').value.trim().toLowerCase(),risk=$('#tool-risk-filter').value;
  const filtered=tools.filter(t=>(!query||(t.name+' '+t.description+' '+t.category).toLowerCase().includes(query))&&(!risk||t.risk_level===risk));list.replaceChildren();
  $('#tool-catalog-count').textContent=tools.length+' aportadas · UNKNOWN';
  filtered.slice(0,40).forEach(t=>{const card=node('article',undefined,'tool-catalog-row'),meta=node('div');meta.append(node('strong',t.name,'exact-names'),node('p',t.description||'Sin descripción.','helper'),node('span',(t.category||'Sin categoría')+' · riesgo '+(t.risk_level||'sin clasificar')+' · UNKNOWN','tag'));if(t.risk_reasons?.length)meta.append(node('p',t.risk_reasons.join(' · '),'helper'));if(t.preconditions?.length){const details=node('details'),summary=node('summary','Precondiciones','helper');details.append(summary,node('p',t.preconditions.join('\n'),'helper'));meta.append(details);}const actions=node('div',undefined,'actions');['allow','deny'].forEach(target=>{const btn=node('button','+ '+target,'textbutton');btn.type='button';btn.onclick=()=>addToolDraft(t.name,target);actions.append(btn);});card.append(meta,actions);list.append(card);});
  if(!filtered.length)list.append(node('p','No hay herramientas que coincidan.','helper'));$('#tool-catalog-limit').textContent=`${Math.min(40,filtered.length)} de ${filtered.length} coincidencias. Afina la búsqueda para encontrar un nombre exacto.`;
}
['#tools-allow','#tools-deny'].forEach(id=>$(id).addEventListener('input',()=>{permissionsDirty=true;refreshToolCounters();}));
$('#inherit-parent-tools').onchange=()=>{permissionsDirty=true;refreshToolCounters();};
$('#tool-search').addEventListener('input',renderToolCatalog);$('#tool-risk-filter').onchange=renderToolCatalog;
$('#reset-tool-policy').onclick=()=>{if(permissionsDirty&&!confirm('¿Descartar el borrador de permisos y restaurar el estado guardado?'))return;const agent=agents().find(a=>a.id===selectedAgent);if(agent)loadToolPolicy(agent);};
$('#apply-tool-recommendation').onclick=()=>{const preset=currentToolPreset();if(!preset)return;const existing=readToolLists(),proposed=[...new Set([...existing.allow,...(preset.allow_candidates||[])])];if(proposed.length>256){message('La combinación supera 256 nombres. Ajusta el borrador antes de continuar.','error');return;}$('#tools-allow').value=proposed.join('\n');permissionsDirty=true;refreshToolCounters();};
$('#tool-policy-form').onsubmit=async e=>{e.preventDefault();const issue=toolPolicyIssue();if(issue){message(issue,'error');return;}if(!selectedAgent||!state.organization)return;const data={agent_id:selectedAgent,...readToolLists(),expected_state_version:permissionBaseVersion};if(!data.allow.length)data.inherit_parent_tools=$('#inherit-parent-tools').checked;if(await action('tool-policy',data,'Permisos propuestos guardados. Disponibilidad y ejecución runtime siguen sin verificar.')){loadToolPolicy(agents().find(a=>a.id===selectedAgent));inspectorBaseVersion=state.organization.state_version||1;$('#profile-version').textContent='Versión de diseño '+inspectorBaseVersion;}};
function renderCoordination(){
  const coordination=state.coordination,leases=coordination?.leases||[],list=$('#lease-list');list.replaceChildren();populateAgentSelect($('#lease-owner'));
  $('#lease-count').textContent=`${coordination?.active_writer_count??0} / ${coordination?.max_writers??3} escritores`;
  $('#coordination-version').textContent=coordination?'Versión local '+coordination.version+' · lectura '+new Date().toLocaleTimeString('es'):'Coordinación local todavía no disponible.';
  leases.forEach(lease=>{const active=lease.status==='active',record=node('article',undefined,'record lease-record');record.append(node('h3',agentLabel(lease.owner_agent_id)+' · '+lease.task_id),node('span',active?'Reserva activa':(lease.status||'Sin estado'),'tag'+(active?'':' amber')),node('p',(lease.workspace||'')+'\n'+(lease.paths||[]).join('\n'),'exact-names'),node('p','SHA base: '+lease.base_sha+'\nVence: '+localDate(lease.expires_at),'helper'));
    if(active){const actions=node('div',undefined,'actions');for(const [actionName,label] of [['lease-renew','Renovar'],['lease-release','Liberar']]){const button=node('button',label,'textbutton');button.type='button';button.onclick=()=>changeLease(actionName,lease);actions.append(button);}record.append(actions);}list.append(record);});
  if(!leases.length)list.append(node('p','No hay reservas locales registradas. La ausencia de reservas no comprueba que nadie edite esos archivos.','helper'));
  const audit=$('#lease-audit');audit.replaceChildren();(coordination?.audit||[]).slice(-12).reverse().forEach(entry=>{const record=node('article',undefined,'record');record.append(node('strong',(entry.action||entry.event||'Evento')+' · '+(entry.status||'')),node('p',entry.message||entry.reason||textValue(entry)),node('time',localDate(entry.timestamp||entry.at||entry.created_at)));audit.append(record);});if(!(coordination?.audit||[]).length)audit.append(node('p','No hay eventos de coordinación en esta sesión.','helper'));
}
function coordinationFailure(){const box=$('#coordination-error');box.textContent=$('#notice').textContent;box.hidden=false;}
async function changeLease(name,lease){const data={lease_id:lease.lease_id||lease.id,owner_agent_id:lease.owner_agent_id,task_id:lease.task_id,expected_version:state.coordination.version};if(name==='lease-renew')data.ttl_seconds=Number($('#lease-ttl').value)||900;const ok=await action(name,data,name==='lease-renew'?'Reserva local renovada.':'Reserva local liberada.');if(ok)$('#coordination-error').hidden=true;else coordinationFailure();}
$('#lease-form').onsubmit=async e=>{e.preventDefault();if(!state.coordination)return;const data=Object.fromEntries(new FormData(e.target));data.paths=lines(data.paths);data.ttl_seconds=Number(data.ttl_seconds);data.expected_version=state.coordination.version;const ok=await action('lease-acquire',data,'Rutas reservadas en el coordinador local. No se ha bloqueado el sistema de archivos.');if(ok)$('#coordination-error').hidden=true;else coordinationFailure();};
$('#refresh-coordination').onclick=()=>run('Actualizando coordinación local…',async()=>{const response=await fetch('/api/state',{credentials:'same-origin'}),payload=await response.json();if(!response.ok)throw new Error(payload.error||'No se pudo actualizar el estado.');state=payload;},'Coordinación local actualizada.');
const CHANNEL_TASK_STATUS={open:'abierta',claimed:'en curso (chasing)',submitted:'entregada (reported)',accepted:'aceptada',rejected:'rechazada',blocked:'aparada'};
function channelMembers(){return state.team_channel?.members||[];}
function channelLabel(id){if(id==='all')return 'todos';const member=channelMembers().find(m=>m.member_id===id);return member?member.name:(agents().find(a=>a.id===id)?.display_name||id);}
function renderTeamChannel(){
  const data=state.team_channel,list=$('#channel-message-list'),tasks=$('#channel-task-list');if(!$('#team-channel-panel'))return;
  list.replaceChildren();tasks.replaceChildren();
  if(!data?.available){$('#channel-count').textContent='Sin diseño';$('#channel-panel-status').textContent=data?.reason||'Genera un diseño para abrir el canal.';return;}
  $('#channel-count').textContent=(data.messages||[]).length+' mensajes · '+(data.tasks||[]).length+' tareas';
  $('#channel-panel-status').textContent='Canal en memoria de la sesión del motor: se reinicia con cada rediseño.';
  (data.messages||[]).slice().reverse().forEach(row=>{const article=node('article',undefined,'receipt');
    article.append(node('time',localDate(row.created_at)),node('span',channelLabel(row.actor)+' → '+channelLabel(row.to),'status'));
    const body=node('p');const mention=/^(@\S+)([\s\S]*)$/.exec(String(row.text||'').trim());
    if(mention){body.append(node('span',mention[1],'mention'),node('span',mention[2]));}else{body.textContent=row.text;}
    article.append(body);if(row.topic&&row.topic!=='coordination')article.append(node('span','tema: '+row.topic,'helper'));
    list.append(article);});
  if(!(data.messages||[]).length)list.append(node('p','El canal todavía no tiene mensajes en esta sesión.','empty'));
  (data.tasks||[]).slice().reverse().forEach(row=>{const article=node('article',undefined,'receipt');
    article.append(node('time',localDate(row.created_at)),node('span',row.id+' · '+(CHANNEL_TASK_STATUS[row.status]||row.status),'status'),node('span',channelLabel(row.owner_member_id)+': '+row.title,'message'));
    if(row.prompt)article.append(node('p',row.prompt,'helper'));
    tasks.append(article);});
  if(!(data.tasks||[]).length)tasks.append(node('p','Sin tareas dirigidas todavía: una @mención o una asignación directa las crea.','empty'));
  populateChannelSelects();
}
function populateChannelSelects(){
  const members=channelMembers(),fill=(selector,withAll)=>{const select=$(selector);if(!select)return;const previous=select.value;select.replaceChildren();if(withAll)select.append(option('all','Todos (all)'));members.forEach(m=>select.append(option(m.member_id,m.name+(m.role?' · '+m.role:''))));if(members.some(m=>m.member_id===previous))select.value=previous;};
  fill('#channel-sender');fill('#channel-to',true);fill('#channel-assign-sender');fill('#channel-assign-member');fill('#channel-evidence-sender');fill('#channel-task-actor');fill('#channel-inbox-member');fill('#memory-author');
  const ids=$('#channel-task-ids');if(ids){ids.replaceChildren();(state.team_channel?.tasks||[]).forEach(task=>{const entry=node('option');entry.value=task.id;ids.append(entry);});}
}
function renderTeamMemory(){
  const data=state.team_memory;if(!$('#team-memory-panel'))return;
  const fragments=$('#memory-fragment-list');fragments.replaceChildren();
  if(!data?.available){$('#memory-count').textContent='Sin diseño';$('#memory-index-text').textContent=data?.reason||'Genera un diseño para abrir la memoria.';return;}
  $('#memory-count').textContent=(data.fragments||[]).length+' fragmentos';
  $('#memory-index-text').textContent=data.index?.text||'';
  (data.fragments||[]).slice().reverse().forEach(row=>{const article=node('article',undefined,'receipt');
    article.append(node('span','['+row.plane+'] '+row.file,'status'),node('time',row.recorded_at),node('span',row.description||'','message'));fragments.append(article);});
  if(!(data.fragments||[]).length)fragments.append(node('p','MEMORY.md está vacío: guarda el primer fragmento del equipo.','empty'));
}
const channelVersion=()=>state.organization?.state_version||1;
$('#channel-publish-form').onsubmit=e=>{e.preventDefault();return action('channel-publish',{expected_state_version:channelVersion(),sender:$('#channel-sender').value,to:$('#channel-to').value,text:$('#channel-text').value,topic:$('#channel-topic').value||undefined,task_title:$('#channel-task-title').value||undefined},'Mensaje publicado en el canal. Una @mención válida crea la tarea dirigida.');};
$('#channel-assign-form').onsubmit=e=>{e.preventDefault();return action('channel-assign',{expected_state_version:channelVersion(),sender:$('#channel-assign-sender').value,member:$('#channel-assign-member').value,task:$('#channel-assign-task').value,title:undefined},'Asignación directa registrada (estado open).');};
$('#channel-evidence-form').onsubmit=e=>{e.preventDefault();const sha=$('#channel-evidence-sha').value.trim().toLowerCase();if(!/^[a-f0-9]{64}$/.test(sha)){message('El SHA-256 declarado debe ser 64 caracteres hexadecimales.','error');return false;}return action('channel-evidence',{expected_state_version:channelVersion(),sender:$('#channel-evidence-sender').value,locator:$('#channel-evidence-locator').value,sha256:sha,summary:$('#channel-evidence-summary').value},'Evidencia registrada con SHA declarado; no acredita lectura del artefacto.');};
const CHANNEL_TRANSITIONS={claim:'channel-claim',submit:'channel-submit',accept:'channel-accept',reject:'channel-reject'};
$('#channel-task-form').onsubmit=e=>{e.preventDefault();const actionName=$('#channel-task-action').value,data={expected_state_version:channelVersion(),actor:$('#channel-task-actor').value,action:actionName,task_id:$('#channel-task-id').value.trim(),note:$('#channel-task-note').value||undefined};const evidence=lines($('#channel-task-evidence').value);if(evidence.length)data.evidence_ids=evidence;if((actionName==='submit'||actionName==='accept')&&!evidence.length){message('submit y accept exigen al menos un ID de evidencia existente (regístrala antes).','error');return false;}return action(CHANNEL_TRANSITIONS[actionName],data,'Transición aplicada en el canal.');};
$('#channel-inbox-drain').onclick=()=>action('channel-inbox',{expected_state_version:channelVersion(),member:$('#channel-inbox-member').value,max_count:100},'Inbox drenado: lectura destructiva FIFO del miembro.');
$('#memory-append-form').onsubmit=e=>{e.preventDefault();const plane=$('#memory-plane').value,data={expected_state_version:channelVersion(),author:$('#memory-author').value,memory_id:$('#memory-id').value.trim(),plane,content:$('#memory-content').value,description:$('#memory-description').value||undefined};if(plane==='execution')data.task_id=$('#memory-task-id').value.trim();return action('memory-append',data,'Fragmento guardado en la memoria de equipo y MEMORY.md regenerado.');};
const governanceFormIds=['#performance-form','#performance-review-form','#promotion-form','#promotion-review-form'];
function selectRows(select,rows,placeholder,label){const previous=select.value;select.replaceChildren(option('',placeholder));rows.forEach(row=>select.append(option(row.id,label(row))));if(rows.some(row=>row.id===previous))select.value=previous;}
function formVersion(form){return Number(form.dataset.baseVersion)||state.organization.state_version||1;}
function hasOperationalDrafts(){return [...governanceFormIds,'#skill-feedback-form'].some(id=>Boolean($(id).dataset.baseVersion));}
function discardOperationalDrafts(){[...governanceFormIds,'#skill-feedback-form'].forEach(id=>{$(id).reset();clearFormVersion($(id));});$$('#performance-authors input').forEach(el=>el.checked=false);}
function bindVersionedForm(form){for(const event of ['input','change'])form.addEventListener(event,()=>{if(!form.dataset.baseVersion&&state?.organization)form.dataset.baseVersion=String(state.organization.state_version||1);});}
function clearFormVersion(form){delete form.dataset.baseVersion;}
function ancestorIds(id){const result=new Set();let a=agents().find(x=>x.id===id);while(a&&!result.has(a.reports_to)){result.add(a.reports_to);a=agents().find(x=>x.id===a.reports_to);}return result;}
function selectedPerformance(){return (state.performance_records||[]).find(r=>r.id===$('#review-performance').value);}
function renderReviewForm(){
  const record=selectedPerformance(),f=$('#performance-review-form'),select=$('#reviewer-id'),previous=select.value;select.replaceChildren(option('','Selecciona revisor independiente'));
  if(!record){$('#review-contract').textContent='Selecciona un entregable. Sin datos revisados no se asigna una puntuación.';$('#external-reviewer-fields').hidden=true;f.elements.quality_denominator.value='';f.elements.efficiency_budget.value='';return;}
  const authors=record.author_ids||[record.agent_id];agents().filter(a=>(a.functional_roles||[]).includes('auditor')&&!authors.some(id=>id===a.id||ancestorIds(id).has(a.id)||ancestorIds(a.id).has(id))).forEach(a=>select.append(option(a.id,a.display_name+' · auditor interno')));
  select.append(option('EXTERNAL','Revisor externo designado por Owner'));if([...select.options].some(o=>o.value===previous))select.value=previous;
  f.elements.quality_denominator.value=record.acceptance_criteria.length;f.elements.efficiency_budget.value=record.budget;
  $('#review-contract').textContent=`${agentLabel(record.agent_id)} · ${record.comparison_group} · ${record.acceptance_criteria.length} criterios · presupuesto ${record.budget} ${record.budget_unit}\nSHA: ${record.candidate_sha}\n${record.acceptance_criteria.map((c,i)=>(i+1)+'. '+c).join('\n')}`+(record.reviews?.length?'\nLa nueva revisión corregirá '+record.reviews.at(-1).id+' conservando el historial.':'');
  $('#external-reviewer-fields').hidden=select.value!=='EXTERNAL';
}
function renderPromotionReview(){
  const row=(state.promotion_records||[]).find(r=>r.id===$('#promotion-record').value),select=$('#promotion-status'),previous=select.value;select.replaceChildren();
  if(row?.status==='proposed')select.append(option('supervisor_reviewed','Revisión declarada del supervisor'));
  if(row?.status==='supervisor_reviewed')select.append(option('owner_approved','Aprobación declarada del Owner'));
  if(row&&['proposed','supervisor_reviewed'].includes(row.status))select.append(option('rejected','Rechazo declarado del Owner'));
  if([...select.options].some(o=>o.value===previous))select.value=previous;
  $('#promotion-review-context').textContent=row?`${agentLabel(row.agent_id)} · ${meritKind(row.kind)} · ${row.comparison_group}\nSupervisor actual: ${agentLabel(agents().find(a=>a.id===row.agent_id)?.reports_to)}. Una aprobación queda registrada como declaración manual; no se aplica al runtime.`:'Selecciona una propuesta pendiente.';
}
function meritKind(kind){return ({recognition:'Reconocimiento no financiero',promotion:'Promoción propuesta',succession:'Sucesión propuesta'})[kind]||kind;}
function meritStatus(status){return ({proposed:'Propuesta',supervisor_reviewed:'Revisión del supervisor registrada',owner_approved:'Aprobación del Owner registrada',rejected:'Rechazo registrado',awaiting_independent_review:'Pendiente de revisión independiente',reviewed_recorded:'Revisión manual registrada'})[status]||status;}
function renderGovernance(){
  const scoreboard=state.scoreboard||{},rows=state.organization?(scoreboard.rows||[]):[],body=$('#merit-ranking');body.replaceChildren();
  rows.forEach(row=>{const tr=node('tr'),profile=node('td'),button=node('button',agentLabel(row.agent_id),'textbutton');button.type='button';button.onclick=()=>openInspector(row.agent_id);profile.append(button,node('small',row.comparison_group||'Sin grupo comparable','score-meta'));const score=node('td',row.score==null?'Sin evaluar':Number(row.score).toLocaleString('es',{maximumFractionDigits:2})+' / 100','ranking-score');if(row.score!=null)score.append(node('small',Object.entries(row.dimensions||{}).map(([k,v])=>({quality:'Calidad',compliance:'Cumplimiento',efficiency:'Eficiencia',collaboration:'Colaboración',evidence:'Evidencia'}[k]||k)+': '+(v==null?'—':Number(v).toFixed(1))).join(' · '),'score-meta'));tr.append(node('td',row.rank==null?'—':'#'+row.rank),profile,score,node('td',`${row.sample_count||0} muestras · ${row.pending_count||0} pendientes · ${row.reviewer_count||0} revisores`),node('td',row.score==null?'Sin evaluar':`Revisión registrada · confianza ${({low:'baja',medium:'media',high:'alta'})[row.confidence]||row.confidence}${row.promotion_eligible?' · candidata a propuesta':''}`));body.append(tr);});
  if(!rows.length)emptyRow(body,5,'Sin evidencia revisada: no hay ranking ni puntuaciones acreditadas.');
  const summary=$('#merit-summary');summary.replaceChildren();for(const [number,label] of [[rows.filter(r=>r.score!=null).length,'Evaluaciones con score'],[(state.performance_records||[]).filter(r=>!r.reviews?.length).length,'Entregables pendientes'],[(state.promotion_records||[]).filter(r=>['proposed','supervisor_reviewed'].includes(r.status)).length,'Propuestas pendientes']]){const card=node('div');card.append(node('strong',number),node('span',label));summary.append(card);}
  if(scoreboard.note)summary.append(node('p',scoreboard.note,'helper'));
  populateAgentSelect($('#performance-agent'));const currentAuthors=new Set($$('#performance-authors input:checked').map(el=>el.value)),authors=$('#performance-authors');authors.replaceChildren();agents().forEach(a=>{const label=node('label',undefined,'check'),input=node('input');input.type='checkbox';input.value=a.id;input.checked=currentAuthors.has(a.id);label.append(input,node('span',a.display_name+' · '+a.role));authors.append(label);});
  selectRows($('#review-performance'),state.performance_records||[],'Selecciona un entregable',r=>r.title+' · '+agentLabel(r.agent_id));renderReviewForm();
  const scored=rows.filter(r=>r.score!=null).map(r=>({...r,id:JSON.stringify([r.agent_id,r.comparison_group])}));selectRows($('#promotion-score'),scored,'Selecciona una evaluación',r=>agentLabel(r.agent_id)+' · '+r.comparison_group+' · '+r.score+'/100');
  const target=$('#promotion-target'),previous=target.value;target.replaceChildren(option('','Sin cambio propuesto'),option('OWNER_EXTERNAL','Owner externo'));agents().forEach(a=>target.append(option(a.id,a.display_name+' · '+a.role)));target.value=previous;
  selectRows($('#promotion-record'),(state.promotion_records||[]).filter(r=>['proposed','supervisor_reviewed'].includes(r.status)),'Selecciona propuesta pendiente',r=>agentLabel(r.agent_id)+' · '+meritKind(r.kind));renderPromotionReview();
  const history=$('#governance-records');history.replaceChildren();(state.promotion_records||[]).slice().reverse().forEach(row=>{const card=node('article',undefined,'record');card.append(node('h3',agentLabel(row.agent_id)+' · '+meritKind(row.kind)),node('span',meritStatus(row.status),'tag'),node('p',row.recommendation),node('p',(row.evidence||[]).join('\n'),'helper'),node('p','Ningún cambio de jerarquía, permiso o runtime aplicado.','helper'));(row.events||[]).forEach(e=>card.append(node('p',meritStatus(e.status)+' · '+agentLabel(e.reviewer_id)+'\n'+e.note)));history.append(card);});
  (state.performance_records||[]).slice().reverse().forEach(row=>{const card=node('article',undefined,'record');card.append(node('h3',row.title+' · '+agentLabel(row.agent_id)),node('span',meritStatus(row.status),'tag'),node('p',row.task_id+' · '+row.comparison_group+'\nSHA: '+row.candidate_sha),node('p',(row.evidence||[]).join('\n'),'helper'));(row.reviews||[]).forEach(review=>card.append(node('p',agentLabel(review.reviewer_id)+' · revisión manual · score '+review.score+'\n'+review.rationale),node('p',(review.evidence||[]).join('\n'),'helper')));history.append(card);});
  if(!history.children.length)history.append(node('p','Sin entregables revisados ni propuestas. No se infieren méritos del rol, títulos, CV, personalidad o modelo.','helper'));
  if(scoreboard.excluded_records?.length)history.append(node('p',scoreboard.excluded_records.length+' registros excluidos del cálculo por datos inválidos; revisar los registros importados.','error-text'));
}
governanceFormIds.forEach(id=>bindVersionedForm($(id)));
$('#review-performance').onchange=()=>{const form=$('#performance-review-form');['quality_numerator','compliance_numerator','compliance_denominator','efficiency_actual','collaboration_numerator','collaboration_denominator','evidence_numerator','evidence_denominator','rationale','evidence'].forEach(name=>form.elements[name].value='');$('#review-no-conflict').checked=false;$('#review-includes-failures').checked=false;renderReviewForm();};$('#reviewer-id').onchange=()=>{$('#external-reviewer-fields').hidden=$('#reviewer-id').value!=='EXTERNAL';};$('#promotion-record').onchange=renderPromotionReview;
$('#reset-governance-drafts').onclick=()=>{if(!confirm('¿Descartar los borradores de desarrollo y usar la versión actual del diseño?'))return;governanceFormIds.forEach(id=>{$(id).reset();clearFormVersion($(id));});$$('#performance-authors input').forEach(el=>el.checked=false);renderGovernance();setBusy(busy);};
$('#performance-form').onsubmit=async e=>{e.preventDefault();if(!state.organization)return;const form=e.target,data=Object.fromEntries(new FormData(form));data.acceptance_criteria=lines(data.acceptance_criteria);data.evidence=lines(data.evidence);data.budget=Number(data.budget);data.author_ids=[...new Set([data.agent_id,...$$('#performance-authors input:checked').map(el=>el.value)])];data.expected_state_version=formVersion(form);if(await action('performance-create',data,'Entregable registrado. Pendiente de revisión independiente; ejecución no verificada.')){form.reset();clearFormVersion(form);renderGovernance();}};
$('#performance-review-form').onsubmit=async e=>{e.preventDefault();const record=selectedPerformance();if(!record)return;const form=e.target,fields=Object.fromEntries(new FormData(form));if(!$('#review-no-conflict').checked||!$('#review-includes-failures').checked){message('Faltan las declaraciones de conflicto e inclusión de fallos.','error');return;}const measurements={};['quality','compliance','collaboration','evidence'].forEach(key=>measurements[key]={numerator:Number(fields[key+'_numerator']),denominator:Number(fields[key+'_denominator'])});measurements.efficiency={budget:Number(fields.efficiency_budget),actual:Number(fields.efficiency_actual)};const data={performance_id:record.id,reviewer_id:fields.reviewer_id,measurements,evidence:lines(fields.evidence),rationale:fields.rationale,conflict_of_interest:false,includes_failures:true,expected_state_version:formVersion(form)};if(record.reviews?.length)data.supersedes_review_id=record.reviews.at(-1).id;if(fields.reviewer_id==='EXTERNAL'){const id=$('#external-reviewer-id').value.trim();data.reviewer_id=id.startsWith('EXTERNAL:')?id:'EXTERNAL:'+id;data.external_reviewer_name=$('#external-reviewer-name').value;data.appointed_by='OWNER_EXTERNAL';data.appointment_evidence=lines($('#external-reviewer-evidence').value);}if(await action('performance-review',data,'Revisión manual registrada. Score recalculado; evidencia y ejecución no verificadas por la app.')){form.reset();clearFormVersion(form);renderGovernance();}};
$('#promotion-form').onsubmit=async e=>{e.preventDefault();if(!$('#promotion-score').value)return;const form=e.target,data=Object.fromEntries(new FormData(form)),identity=JSON.parse($('#promotion-score').value);data.agent_id=identity[0];data.comparison_group=identity[1];data.evidence=lines(data.evidence);if(!data.target_supervisor_id)delete data.target_supervisor_id;data.expected_state_version=formVersion(form);if(await action('promotion-create',data,'Propuesta de desarrollo registrada; requiere revisión y decisión.')){form.reset();clearFormVersion(form);renderGovernance();}};
$('#promotion-review-form').onsubmit=async e=>{e.preventDefault();const row=(state.promotion_records||[]).find(r=>r.id===$('#promotion-record').value);if(!row)return;if(!$('#promotion-no-conflict').checked){message('Falta la declaración del revisor indicado.','error');return;}const form=e.target,data=Object.fromEntries(new FormData(form));data.promotion_id=row.id;data.reviewer_id=data.status==='supervisor_reviewed'?agents().find(a=>a.id===row.agent_id)?.reports_to:'OWNER_EXTERNAL';data.conflict_of_interest=false;data.evidence=lines(data.evidence);data.expected_state_version=formVersion(form);if(await action('promotion-update',data,'Decisión manual registrada. No modifica jerarquía, permisos ni runtime.')){form.reset();clearFormVersion(form);renderGovernance();}};

function renderSkillFeedback(){
  populateAgentSelect($('#feedback-agent'));selectRows($('#feedback-skill'),state.skill_registry||[],'Selecciona skill registrada',row=>row.name+' · v'+row.version);
  const box=$('#skill-feedback-records');box.replaceChildren();(state.skill_registry||[]).forEach(skill=>(skill.feedback||[]).slice().reverse().forEach(entry=>{const card=node('article',undefined,'record');card.append(node('h3',skill.name+' · '+agentLabel(entry.agent_id)),node('p','Fallo: '+entry.failure+'\nMejora: '+entry.proposed_change+'\nRetest declarado: '+entry.retest_result),node('p',(entry.evidence||[]).join('\n'),'helper'),node('span','No instalada · eficacia sin verificar','tag amber'));box.append(card);}));
}
bindVersionedForm($('#skill-feedback-form'));
$('#skill-feedback-form').onsubmit=async e=>{e.preventDefault();if(!state.organization)return;const form=e.target,data=Object.fromEntries(new FormData(form));data.evidence=lines(data.evidence);data.expected_state_version=formVersion(form);if(await action('skill-feedback',data,'Feedback versionado guardado. Skill no instalada ni eficacia verificada.')){form.reset();clearFormVersion(form);renderSkillFeedback();}};

// Guided generation is explicit, job-bound and asynchronous. Polling only reads local state.
const cvFieldLabels={position:'Función objetivo',organization:'Entidad ficticia',period:'Itinerario',scope:'Alcance',achievements:'Resultados aspiracionales',verification:'Verificación',program:'Programa aspiracional',degree_level:'Nivel objetivo',evaluation_required:'Evaluación requerida',institution:'Institución ficticia / plan',status:'Estado declarado',modules:'Módulos',name:'Nombre',acceptance:'Criterios de aceptación',languages:'Idiomas objetivo',working_style:'Estilo de trabajo',research_interests:'Intereses de investigación',portfolio:'Portafolio objetivo'};
function generationActive(){const job=state?.generation_job;return Boolean(job?.job_id&&!generationTerminal.has(job.status));}
function generationNeedsPolling(){return generationActive()||state?.generation_job?.receipts_pending===true;}
function readGenerationConfig(){const config=Object.fromEntries(new FormData($('#config-form')));config.council_concurrency=config.agent_count;['agent_count','max_direct_reports','implementation_concurrency','council_concurrency','llm_budget_usd','planner_max_tokens','member_timeout_ms','handoff_summary_max_chars','runtime_token_budget','quality_gate_rounds'].forEach(k=>config[k]=Number(config[k]));return config;}
function generationSourceLabel(){const mode=state?.organization?.provenance?.generation_mode;return mode==='api_generated'?'ADN diseñado mediante API · ejecución sin verificar':mode==='offline_template'?'Plantilla offline · sin generación por IA':state?.organization?'Diseño local / procedencia no informada':'Aún sin diseño';}
function redactPreview(value){if(Array.isArray(value))return value.map(redactPreview);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,/^(api[_-]?key|authorization|access_token|password|credentials?|x-api-key|pairing_code|bearer_token|connection_token|token)$/i.test(key)?'[OMITIDO]':redactPreview(item)]));return value;}
function appendFact(list,label,value){list.append(node('dt',label),node('dd',value==null||value===''?'No informado':textValue(value)));}
function updateGenerationControls(transient=false){
  const active=generationActive(),job=state?.generation_job,pending=state?.pending_consent;
  const locked=Boolean(transient||generationOperation||active),review=job?.status==='awaiting_consent'&&pending?.job_id===job.job_id;
  $$('#config-form input').concat($$('#config-form select'),$$('#config-form textarea'),$$('#key-form input')).forEach(el=>el.disabled=locked||(el.id==='persist-key'&&!state?.capabilities?.dpapi));
  ['generation-tokens','generation-batch','generation-response-mode','generation-new-project','generation-model-select','generation-manual-model'].forEach(id=>$('#'+id).disabled=locked||!state);
  $('#generation-new-project').disabled=locked||!state||generationImprovementRunIds.length>0;$('#improvement-clear').disabled=locked;
  $('#generation-discover-models').disabled=locked||!state;
  $('#prepare-generation').disabled=locked||!state;$('#generate').disabled=locked||!state;$('#copy-plan-preview').disabled=locked||configDirty||!currentAutonomy()?.plan_preview;
  $('#cancel-generation').hidden=!active;$('#cancel-generation').disabled=!active||generationCancelPending;
  $('#confirm-generation').disabled=Boolean(!review||transient||generationOperation||generationCancelPending||generationReviewStale||configDirty||!$('#generation-consent').checked);
  $('#generation-consent').disabled=!review||generationOperation||generationReviewStale||configDirty;
  $('#restore-design').disabled=locked||!state?.design_recovery?.can_restore;
  $('#resume-design-draft').disabled=locked||!state?.design_recovery?.draft_config;
  ['generation-retry','generation-diagnostic-download'].forEach(id=>{const button=$('#'+id);if(button)button.disabled=locked;});
  if(active)$$('a[download]').forEach(a=>a.setAttribute('aria-disabled','true'));
}
function generationMessage(text,kind='',jobId=null){message(text,kind);generationNoticeOwned=true;generationNoticeJobId=jobId;}

// --- Servicios y ensamblado: el libro de despliegue del gang -----------------
function renderGangServices(gang){
  const wrap=$('#gang-services');if(!wrap)return;
  if(!gang){wrap.hidden=true;return;}
  wrap.hidden=false;
  const ens=gang.ensamblado,pill=$('#gang-sync-pill'),sync=gang.sync||{};
  const color=sync.code==='SYNCED'?'#2e9e5b':sync.code==='DIVERGED'?'#d33':'#f59e0b';
  pill.textContent=(sync.label||sync.code||'').toUpperCase();pill.style.color=color;
  const facts=$('#gang-assembly-facts');facts.replaceChildren();
  const addFact=(k,v)=>{const dt=document.createElement('dt');dt.textContent=k;const dd=document.createElement('dd');dd.textContent=v;facts.append(dt,dd);};
  const btn=$('#gang-publish');
  if(!ens){addFact('Ensamblado','—');btn.disabled=true;}
  else if(ens.error){addFact('Ensamblado','RECHAZADO: '+ens.error);addFact('Detalle',ens.detail||'');btn.disabled=true;}
  else{
    const cl=ens.changelog||{};
    addFact('Artefacto',(ens.sha256||'').slice(0,16)+'…');
    addFact('Gang',ens.total+' agentes · versión '+ens.version);
    addFact('Orden','jefe antes que subordinado · '+ens.orden_total+' en la cadena');
    addFact('Cambios vs anterior','+'+((cl.added||[]).length)+' · −'+((cl.removed||[]).length)+' · ~'+((cl.changed||[]).length));
    btn.disabled=false;
  }
  const grid=$('#gang-services-grid');grid.replaceChildren();
  (gang.servicios||[]).forEach(s=>{
    const url=(gang.urls||{})[s.id];
    const chip=document.createElement('div');chip.className='gang-chip '+(s.recorded_sha256?'gang-listo':'gang-cola');
    const id=document.createElement('div');id.className='gang-id';id.textContent=s.id;
    const st=document.createElement('div');st.className='gang-st';
    st.textContent=s.recorded_sha256?String(s.recorded_sha256).slice(0,8):'sin despliegue';
    const mount=document.createElement('div');mount.className='gang-st';
    mount.textContent=url?('montado · '+url.replace('http://','')):'no montado';
    chip.append(id,st,mount);grid.append(chip);
  });
  const montadoBtn=$('#gang-mount'),desmontarBtn=$('#gang-unmount'),tickBtn=$('#gang-tick');
  if(montadoBtn){montadoBtn.hidden=!!gang.montado;desmontarBtn.hidden=!gang.montado;tickBtn.hidden=!gang.montado;}
  // Auditoria: historial de publicaciones — versiones commiteadas, abortos y rollbacks.
  const audit=$('#gang-audit');
  if(audit){
    audit.replaceChildren();
    const filas=(gang.auditoria||[]).slice().reverse();
    if(!filas.length){const p=document.createElement('p');p.className='helper';p.textContent='Sin publicaciones todavía.';audit.append(p);}
    else filas.forEach(e=>{
      const p=document.createElement('p');p.className='helper';
      const color=e.estado==='committed'?'#2e9e5b':e.estado==='staged'?'#f59e0b':'#d33';
      const b=document.createElement('strong');b.style.color=color;b.textContent=e.estado;
      p.append(String(e.clave||'').slice(0,8)+' · ',b,' · '+(e.ts||'')+(e.detalle?' — '+e.detalle:''));
      audit.append(p);
    });
  }
}

// Un agente = una solicitud, asi que el indice de cada recibo ES el agente.
// Estados: cola -> construyendo -> (continuando -> construyendo)* -> listo | fallo.
function renderGangGrid(job){
  const wrap=$('#gang-grid-wrap');if(!wrap)return;
  const total=Number(job.agent_count)||0;
  if(!total){wrap.hidden=true;return;}
  wrap.hidden=false;
  const receipts=job.request_receipts||[];
  // El ULTIMO recibo de cada agente manda: uno que trunco y continuo queda
  // 'continuando' solo mientras su continuacion no llega.
  const porAgente=new Map();
  for(const r of receipts){if(r&&typeof r.index==='number')porAgente.set(r.index,r);}
  const fracaso=generationTerminal.has(job.status)&&job.status!=='completed';
  const estados=[];let listos=0,continuando=0;
  for(let i=1;i<=total;i++){
    const r=porAgente.get(i);let est='cola';
    if(r){
      if(r.status==='validated'){est='listo';}
      else if(r.status==='continued_truncated'||r.status==='split_reissued'){est='continuando';}
      else if(fracaso&&r.status!=='billing_outcome_unknown'){est='fallo';}
      else{est='construyendo';}
    }else if(fracaso){est='fallo';}
    if(est==='listo')listos++;if(est==='continuando')continuando++;
    estados.push(est);
  }
  $('#gang-grid-count').textContent=listos+' / '+total+' agentes listos'+(continuando?' · '+continuando+' continuando donde cortaron':'')+' · ningún agente se recorta';
  const grid=$('#gang-grid');grid.replaceChildren();
  estados.forEach((est,i)=>{
    const chip=document.createElement('div');
    chip.className='gang-chip gang-'+est;
    const id=document.createElement('div');id.className='gang-id';id.textContent='a'+String(i+1).padStart(2,'0');
    const st=document.createElement('div');st.className='gang-st';st.textContent=est;
    chip.append(id,st);grid.append(chip);
  });
}

function syncGenerationNotice(job){
  if(!generationNoticeOwned||!job||(generationNoticeJobId&&generationNoticeJobId!==job.job_id))return;
  generationNoticeJobId=job.job_id;
  if(job.status==='awaiting_consent')message('Plan preparado. Revisa el contenido y los límites antes de autorizar el envío.');
  else if(generationTerminal.has(job.status)){
    const detail=typeof job.error==='string'?job.error:job.error?.message||job.message||'El motor conserva el último estado válido.';
    const stage=job.error?.source_stage||job.error?.stage||job.failed_stage;
    message(job.status==='completed'?'ADN completo preparado. Revisa y descarga las exportaciones.':(stage?'Etapa: '+stage+'. ':'')+detail+' '+generationFailureAction(job)+' '+generationBillingNote(job),job.status==='completed'?'':'error');
  }
}
function renderGeneration(){
  const job=state?.generation_job,pending=state?.pending_consent,active=generationActive();
  renderGenerationModelChoice();renderGenerationUsage(job);
  $('#improvement-selection').hidden=!generationImprovementRunIds.length;$('#improvement-selection-text').textContent='Mejora seleccionada sobre resultados: '+generationImprovementRunIds.join(', ')+'. Se conserva la identidad y N. Preparar no llama al modelo; revisarás el plan y el coste.';
  $('#generation-progress').hidden=!job;$('#generation-preview').hidden=!(job?.status==='awaiting_consent'&&pending?.job_id===job.job_id);
  if(job){
    const labels={planned:'Preparando inventario',inventory:'Leyendo la fuente',awaiting_consent:'Esperando tu aprobación',running:'Diseñando ADN mediante API',validating:'Validando perfiles y exportaciones',completed:'ADN completo preparado',failed:'La generación no se completó',cancelled:'Generación cancelada',expired:'La aprobación caducó',rejected:'Diseño rechazado por validación'};
    const percent=Math.max(0,Math.min(100,Number(job.progress)||0));$('#generation-stage').textContent=labels[job.status]||job.stage||'Generación en curso';$('#generation-percent').textContent=percent+'%';$('#generation-progress-bar').value=percent;
    $('#generation-progress').classList.toggle('generation-interrupted',generationTerminal.has(job.status)&&job.status!=='completed');
    const stageLabels={inventory:'Inventario de sólo lectura de la fuente pública',preparing_consent:'Preparando el contenido exacto para tu revisión',review:'Revisa el alcance antes de autorizar el envío',api_design:'Solicitud al proveedor en curso',validating_profiles:'Validando CV, N exacto, jerarquía y modelos',building_exports:'Construyendo y verificando los dos JSON nativos y el ZIP',ready:'Archivos preparados; DSH no se ha iniciado'};
    $('#generation-status-text').textContent=(generationTerminal.has(job.status)?'Intento finalizado':job.message||stageLabels[job.stage]||job.stage||'')+(job.max_requests?' · Iniciadas: '+generationRequestCount(job.sent_requests)+' · Completadas: '+generationRequestCount(job.completed_requests)+' / '+job.max_requests:'')+(generationReviewStale?' La configuración cambió. Cancela y prepara un plan nuevo.':'')+(job.potentially_billed?' Puede haber cargos por solicitudes enviadas.':'');
    renderGangGrid(job);
  }
  renderGangServices(state?.gang);
  const gangPublishBtn=$('#gang-publish');
  if(gangPublishBtn&&!gangPublishBtn.dataset.wired){gangPublishBtn.dataset.wired='1';gangPublishBtn.onclick=()=>{if(busy||generationActive())return;action('gang-publish',{},'Artefacto registrado en los 3 objetivos.');};}
  const gangMountBtn=$('#gang-mount'),gangUnmountBtn=$('#gang-unmount'),gangTickBtn=$('#gang-tick');
  if(gangMountBtn&&!gangMountBtn.dataset.wired){
    gangMountBtn.dataset.wired='1';
    // Montar abre 3 servidores HTTP locales con endpoints mutantes: dos pasos.
    // Primero se solicita (queda pendiente con su scope_hash y su digest, sin montar
    // nada); el segundo clic confirma ese alcance exacto.
    gangMountBtn.onclick=()=>{if(busy||generationActive())return;const p=state&&state.gang_mount_consent;if(!p)return action('gang-mount',{},'Montaje solicitado. Revisa el alcance y confirma: no se abrió ningún servidor todavía.');if(!confirm(`¿Montar 3 servidores HTTP locales con endpoints mutantes? Puerta '${p.gate}' · alcance ${String(p.scope_hash).slice(0,16)}… · SHA-256 de la solicitud ${String(p.payload_sha256).slice(0,16)}…`))return;action('gang-mount',{confirmed:true,consent_id:p.approval_id,payload_sha256:p.payload_sha256},'Servicios montados: el registro publica por 2PC real contra ellos.');};
    gangUnmountBtn.onclick=()=>{if(busy||generationActive())return;action('gang-unmount',{},'Servicios desmontados; el journal conserva la historia.');};
    gangTickBtn.onclick=()=>{if(busy||generationActive())return;action('gang-tick',{},'Tick del supervisor ejecutado.');};
  }
  if(pending?.job_id&&job?.status==='awaiting_consent'){
    const fingerprint=[pending.job_id,pending.approval_id,pending.payload_sha256,pending.coverage_sha256,pending.config_version].join(':');if(generationConsentId!==fingerprint){$('#generation-consent').checked=false;generationConsentId=fingerprint;}
    $('#generation-partial-notice').hidden=!pending.partial_inventory_required;
    const list=$('#generation-preview-summary');list.replaceChildren();
    const review=pending.coverage_review||{},coverage=review.coverage||{},inventory=coverage.inventory||{},web=review.source_kind==='website';
    appendFact(list,'Tipo de fuente',web?'Sitio web · HTML estático':'Repositorio GitHub');
    if(web){appendFact(list,'URL de origen',review.source_url);appendFact(list,'SHA-256 del conjunto observado',review.source_hash);appendFact(list,'Limitación web','Sólo páginas observadas; sin JavaScript, login ni formularios. No es un snapshot atómico del sitio remoto.');appendFact(list,'Tiempos medidos / caché',state.repo_inventory?.timings||'Ver detalle de cada página');}
    appendFact(list,web?'Cobertura del sitio':'Inventario de rutas',review.inventory_complete===true?'Completo dentro del alcance informado':'PARCIAL O DESCONOCIDO · el total de la fuente no se conoce');
    appendFact(list,web?'Páginas observadas':'Archivos seguros conocidos',review.known_safe_files);
    appendFact(list,web?'Total de páginas':'Total de archivos seguros',review.total_repository_files==null?'Desconocido · no calcular porcentaje de toda la fuente':review.total_repository_files);
    appendFact(list,'Contenido leído',String(review.read_files??pending.files?.length??0)+(web?' páginas con evidencia útil · NO es un scraping completo':' archivos seleccionados · NO es una lectura de todo el repositorio'));
    appendFact(list,'Método y límites del inventario',inventory.method?JSON.stringify(inventory):coverage.strategy||'Ver inventario exacto');
    appendFact(list,'Límites de lectura',coverage.budget||coverage.scope||state.repo_inventory?.limits||'Ver contenido exacto');
    if(!web){const metrics=state.repo_inventory?.limits||{};appendFact(list,'Mediciones de la captura',metrics.elapsed_ms==null?'No informadas':String(metrics.elapsed_ms)+' ms · caché de inventario: '+(metrics.inventory_cache_hits||0)+' · caché de archivos: '+(metrics.cache_hits||0)+' · solicitudes: '+(metrics.requests??'No informadas'));}
    appendFact(list,'Huecos de cobertura',coverage.gaps?.length?coverage.gaps:'No se afirma cobertura completa del contenido.');

    if(pending.improvement_summary)appendFact(list,'Mejora propuesta y retest',pending.improvement_summary);
    appendFact(list,'Proveedor y destino',(pending.provider||state.config.provider)+' · '+(pending.endpoint||pending.url||pending.request?.endpoint||'Ver endpoint exacto en el contenido'));
    appendFact(list,'ID exacto para la API',pending.model||state.config.model);appendFact(list,'Verificación del ID',generationVerificationLabel(job.model_verification));appendFact(list,'Autonomía del equipo exportado',pending.project_preview?.autonomy_preset||state.config.autonomy_preset||'Ver configuración exacta');appendFact(list,'Orquestador del equipo',pending.project_preview?.orchestration_backend||state.config.orchestration_backend||'teams_gui');if(state.config.objective)appendFact(list,'Objetivo declarado',state.config.objective);appendFact(list,'Perfiles solicitados (N)',pending.agent_count??pending.N??job.agent_count??state.config.agent_count);
    if(!web)appendFact(list,'Repositorio y referencia',state.config.repo_url+' · '+(pending.repository_sha||pending.preview?.repository?.commit_sha||pending.preview?.repository?.sha||state.repo_inventory?.repository?.commit_sha||state.repo_inventory?.repository?.sha||state.repo_inventory?.commit_sha||state.repo_inventory?.sha||state.config.repo_ref||'Ver inventario'));
    if(web)appendFact(list,'Páginas incluidas',(pending.preview?.evidence||[]).map(page=>page.url));else appendFact(list,'Archivos incluidos',Array.isArray(pending.files)?pending.files.length+' · '+pending.files.join(' · '):'Ver inventario exacto');appendFact(list,'Documentos incluidos',Array.isArray(pending.documents)?pending.documents.length+' · '+pending.documents.join(' · '):'Ver inventario exacto');appendFact(list,'Bytes enviados en total',pending.payload_bytes);
    appendFact(list,'Finalidad','Generar y validar un diseño de organización; no ejecutar el equipo');
    appendFact(list,'Perfiles por solicitud · efectivos',pending.effective_profiles_per_request??job.effective_profiles_per_request??pending.profiles_per_request??job.profiles_per_request??'Automático · ver solicitudes exactas');
    appendFact(list,'Formato de respuesta',(pending.response_mode??job.response_mode)==='text'?'Texto con JSON; validación estricta':'JSON nativo del proveedor');
    appendFact(list,'Máximo de solicitudes',pending.max_requests??pending.request_count??pending.requests?.length??'Ver plan exacto');
    appendFact(list,'Entrada estimada · suma de solicitudes',generationTokenValue(pending.estimated_input_tokens)+' tokens aproximados; no es consumo real');
    appendFact(list,'Método de estimación',pending.token_estimate_method||'No informado; no equivale al tokenizer del proveedor');
    appendFact(list,'Tope solicitado de salida por solicitud',pending.requested_max_output_tokens??job.max_output_tokens??'No informado');
    appendFact(list,'Tope nominal efectivo de salida',pending.max_output_tokens??pending.request_budget?.max_output_tokens??'Ver plan exacto');
    appendFact(list,'Límites de salida realmente enviados por lote',(pending.requests||[]).length?pending.requests.map(r=>'Lote '+r.index+': '+generationTokenValue(r.max_output_tokens)).join(' · '):'Ver plan exacto');
    appendFact(list,'Máximo total de salida · suma de lotes',pending.max_total_output_tokens??pending.total_max_output_tokens??pending.request_budget?.total_max_output_tokens??'Ver plan exacto');
    appendFact(list,'Por qué pueden diferir los límites','El tope nominal es un máximo. El reparto automático puede usar menos tokens en cada lote según sus perfiles. Ninguno de estos límites es consumo real.');
    appendFact(list,'Coste en USD','No calculado · no hay una tarifa verificada; puede haber cargos');
    appendFact(list,'Referencia orientativa',Number(state.config.llm_budget_usd)>0?String(state.config.llm_budget_usd)+' USD · no limita la factura del proveedor':'Sin referencia definida · vacío o 0 no significa gratuito');
    renderGenerationEvidence(pending);
    appendFact(list,'SHA-256 de la aprobación',pending.payload_sha256);appendFact(list,'Versión de configuración',pending.config_version??job.config_version);
    $('#generation-preview-payload').textContent=JSON.stringify(redactPreview(pending),null,2);
  }
  const result=$('#generation-result');result.hidden=!job||active;result.replaceChildren();
  if(job&&!active){
    if(job.status==='completed'){
      result.append(node('h3','3. Revisa y descarga'),node('p',agents().length+' / '+state.config.agent_count+' perfiles disponibles. '+generationSourceLabel()+'.'));
      const link=node('a','Abrir las dos exportaciones nativas →','secondary');link.href='#exportaciones';result.append(link);
      renderCompletedGenerationDiagnostic(result,job);
    }else renderGenerationFailure(result,job);
  }
  if(job?.status==='completed'&&job.improvement_proposal){const proposal=node('details');proposal.append(node('summary','Propuesta de mejora: cambios y retest pendiente'),node('pre',JSON.stringify(redactPreview(job.improvement_proposal),null,2)),node('p','Los cambios son propuestas. Ejecuta el retest y solicita revisión independiente antes de declarar eficacia.','helper'));result.append(proposal);}
  syncGenerationNotice(job);if(generationNeedsPolling())scheduleGenerationPoll();updateGenerationControls(busy);
}
function generationTokenValue(value){return Number.isInteger(value)&&value>=0?String(value):'No informado';}
function generationVerificationLabel(verification){return ({catalog_verified:'ID exacto observado en catálogo de cuenta; capacidades sin verificar',inference_verified:'ID exacto observado en inferencia previa; capacidades completas sin verificar',manual_documented:'Referencia documentada elegida manualmente; cuenta y capacidades sin verificar'})[verification?.status]||'No informado en este intento';}
function generationSafeUsage(value,summary=false){const clean={};for(const key of ['prompt_tokens','completion_tokens','total_tokens',...(summary?['known_requests','unknown_requests']:[])])clean[key]=Number.isSafeInteger(value?.[key])&&value[key]>=0?value[key]:null;return clean;}
const generationReceiptCodes=new Set(["unknown_design_failure", "invalid_json", "response_shape", "output_truncated", "response_incomplete", "response_refused", "unexpected_tools", "missing_content", "response_too_large", "schema_fields", "invalid_text", "invalid_count", "duplicate_value", "unreviewed_evidence", "slot_mismatch", "fiction_required", "invalid_enum", "model_mismatch", "unsafe_instructions", "sensitive_output", "output_budget_too_small", "request_budget_exceeded", "context_budget_exceeded", "input_budget_exceeded", "transport_failure", "request_timeout", "progress_failure", "core_validation", "provider_http_error", "unsupported_parameter", "unsupported_value", "invalid_parameter", "invalid_request_error", "context_length_exceeded", "max_tokens_exceeded", "insufficient_quota", "rate_limit_exceeded", "model_not_found", "invalid_api_key", "authentication_error", "permission_denied", "server_error"]);
function generationSafeReceipts(job){
  const statuses=new Set(['billing_outcome_unknown','response_received_not_yet_validated','validated']),sha=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value)?value:null,bounded=(value,max,min=0)=>Number.isInteger(value)&&value>=min&&value<=max?value:null;
  return (Array.isArray(job?.request_receipts)?job.request_receipts:[]).slice(0,16).filter(r=>r&&bounded(r.index,16,1)!==null).map(r=>({index:r.index,provider:typeof job.provider==='string'?job.provider.slice(0,100):null,model:typeof job.model==='string'?job.model.slice(0,200):null,payload_sha256:sha(r.payload_sha256),status:statuses.has(r.status)?r.status:'billing_outcome_unknown',usage:generationSafeUsage(r.usage),latency_ms:bounded(r.latency_ms,86400000),http_status:bounded(r.http_status,599,100),error_code:generationReceiptCodes.has(r.error_code)?r.error_code:null,response_id_sha256:sha(r.response_id_sha256),max_output_tokens:bounded(r.max_output_tokens,131072,1)}));
}
function renderGenerationUsage(job){
  const box=$('#generation-usage'),summary=$('#generation-usage-summary'),receipts=$('#generation-request-receipts');box.hidden=!job;summary.replaceChildren();receipts.replaceChildren();if(!job)return;
  const usage=generationSafeUsage(job.usage_summary,true),rows=generationSafeReceipts(job);
  appendFact(summary,'Tokens de entrada reales · informados por proveedor',generationTokenValue(usage.prompt_tokens));appendFact(summary,'Tokens de salida reales · informados por proveedor',generationTokenValue(usage.completion_tokens));appendFact(summary,'Tokens reales totales',generationTokenValue(usage.total_tokens));
  appendFact(summary,'Solicitudes con usage completo',generationTokenValue(usage.known_requests));appendFact(summary,'Solicitudes con usage incompleto o desconocido',generationTokenValue(usage.unknown_requests));appendFact(summary,'Coste en USD','No calculado · consulta el consumo y la factura del proveedor');
  $('#generation-usage-note').textContent=(job.receipts_pending===true?'Recibo pendiente de respuesta; puede haber cargos. Se seguirá consultando el estado local. ':'')+'Sólo se muestra usage recibido. No informado no significa 0 ni gratis. El uso puede existir aunque fallen la validación o la generación, o se cancele el intento. Los límites del plan y sus estimaciones no son consumo real. '+generationBillingNote(job);
  if(!rows.length){receipts.append(node('p',job.sent_requests===0?'Aún no hay solicitudes registradas como iniciadas en este intento.':'No hay recibos detallados disponibles para este intento; el consumo permanece sin confirmar.','helper'));return;}
  const labels={billing_outcome_unknown:'Resultado y facturación desconocidos',response_received_not_yet_validated:'Respuesta recibida; validación no confirmada',validated:'Respuesta validada localmente; facturación no confirmada'};
  rows.forEach(row=>{const card=node('article',undefined,'generation-receipt');card.append(node('h4','Solicitud '+row.index+' · '+labels[row.status]));const facts=node('dl',undefined,'generation-facts');appendFact(facts,'Proveedor / ID autorizado',[row.provider,row.model].filter(Boolean).join(' / '));appendFact(facts,'Usage real · entrada / salida / total',[row.usage.prompt_tokens,row.usage.completion_tokens,row.usage.total_tokens].map(generationTokenValue).join(' / '));appendFact(facts,'Límite de salida enviado',generationTokenValue(row.max_output_tokens));appendFact(facts,'HTTP / código seguro',String(row.http_status??'No informado')+' / '+(row.error_code||'No informado'));appendFact(facts,'Latencia observada',row.latency_ms==null?'No informada':row.latency_ms+' ms');appendFact(facts,'SHA-256 de la solicitud',row.payload_sha256);appendFact(facts,'SHA-256 del ID de respuesta',row.response_id_sha256);card.append(facts);receipts.append(card);});
}
function renderCompletedGenerationDiagnostic(result,job){
  const details=node('details',undefined,'generation-diagnostic');details.append(node('summary','Detalles técnicos y recibos del intento'),node('pre',JSON.stringify(generationDiagnostic(job),null,2)));result.append(details);
  if(state?.generation_diagnostic_available===true){const download=node('button','Descargar diagnóstico JSON','textbutton');download.id='generation-diagnostic-download';download.setAttribute('id','generation-diagnostic-download');download.type='button';download.onclick=()=>downloadGenerationDiagnostic(job.job_id);result.append(download);}
}
function generationPathList(value){return Array.isArray(value)?value.filter(v=>typeof v==='string').slice(0,100):[];}
function renderGenerationEvidence(pending){
  const summary=$('#generation-evidence-summary'),batches=$('#generation-batch-list'),details=$('#generation-batch-details'),web=pending.source_kind==='website'||pending.coverage_review?.source_kind==='website',coverage=pending.coverage_review?.coverage||pending.coverage||{},distribution=pending.evidence_distribution,files=Array.isArray(pending.preview?.files)?pending.preview.files:[],requests=Array.isArray(pending.requests)?pending.requests:[];summary.replaceChildren();batches.replaceChildren();details.hidden=!requests.length;
  summary.append(node('strong','Evidencia leída y evidencia enviada, por separado'),node('p',web?'Sólo se usan las páginas observadas, sin JavaScript ni acceso autenticado. No demuestra cobertura completa ni funcionamiento del sitio.':'Leer rutas no equivale a leer su contenido. La selección es heurística; los archivos de cada lote son su evidencia observada. No demuestra comprensión completa ni ejecución del repositorio.','helper'));
  const facts=node('dl',undefined,'generation-facts');appendFact(facts,'Cobertura de todo el contenido',coverage.whole_repository_content_complete===true?'Declarada completa por el inventario; revisa su alcance':'Parcial o desconocida');
  if(coverage.inventory?.pending_subtrees!=null)appendFact(facts,'Subárboles aún pendientes',coverage.inventory.pending_subtrees);
  if(coverage.inventory?.pending_subtree_paths?.length)appendFact(facts,'Rutas pendientes conocidas',generationPathList(coverage.inventory.pending_subtree_paths).join('\n'));
  if(distribution){appendFact(facts,web?'Páginas únicas observadas':'Archivos únicos leídos',distribution.unique_read_paths);appendFact(facts,'Apariciones de evidencia enviadas · suma de lotes',distribution.sent_file_occurrences);appendFact(facts,'Apariciones si todos se repitieran',distribution.full_repeat_file_occurrences);appendFact(facts,'Leídos pero omitidos de todos los lotes',generationPathList(distribution.omitted_from_all_batches).join('\n')||'Ninguno informado');appendFact(facts,'Método de reparto',distribution.strategy||'No informado');}
  else appendFact(facts,'Reparto de evidencia','Sin desglose disponible; revisa el contenido exacto de las solicitudes.');
  summary.append(facts);
  requests.slice(0,16).forEach(request=>{const card=node('article',undefined,'generation-batch'),facts=node('dl',undefined,'generation-facts');card.append(node('h4','Solicitud '+request.index));appendFact(facts,'Perfiles asignados',Array.isArray(request.slots)?request.slots.join(', '):'No informado');appendFact(facts,'Entrada estimada · no usage real',generationTokenValue(request.estimated_input_tokens));appendFact(facts,'Reserva conservadora de entrada · no usage real',generationTokenValue(request.conservative_input_budget));appendFact(facts,'Límite de salida enviado',generationTokenValue(request.max_output_tokens));appendFact(facts,'SHA-256 del payload aprobado',request.payload_sha256);card.append(facts);
    const pack=request.evidence_package,paths=generationPathList(request.evidence_paths);if(pack){const common=generationPathList(pack.common_paths),targeted=generationPathList(pack.targeted_paths),omitted=generationPathList(pack.omitted_read_paths);card.append(node('p','Comunes: '+(common.join(' · ')||'Ninguno informado'),'generation-paths'),node('p','Dirigidos al lote: '+(targeted.join(' · ')||'Ninguno informado'),'generation-paths'),node('p','Leídos y omitidos de este lote: '+(omitted.join(' · ')||'Ninguno informado'),'generation-paths'));}
    if(paths.length){const evidence=node('details');evidence.append(node('summary',paths.length+(web?' páginas enviadas en este lote':' archivos enviados en este lote')));paths.forEach(path=>{const file=files.find(f=>f.path===path)||{};evidence.append(node('p',[path,file.family?'familia: '+file.family:'',file.module?'módulo: '+file.module:'',file.bytes!=null?'bytes: '+file.bytes:'',file.read_source?'lectura: '+file.read_source:'',file.sha?'SHA de origen: '+file.sha:'',file.content_sha256?'SHA-256 contenido redactado: '+file.content_sha256:''].filter(Boolean).join(' · '),'generation-paths'));});card.append(evidence);}else card.append(node('p','Sin lista de archivos por lote; revisa el payload exacto.','helper'));
    batches.append(card);
  });
}
function generationRequestCount(value){return Number.isInteger(value)&&value>=0?String(value):'No confirmado';}
function generationBillingNote(job){
  if(job.potentially_billed||Number(job.sent_requests)>0)return 'Puede haber cargos por solicitudes iniciadas, aunque no se haya completado ningún perfil. Iniciar no confirma que el proveedor recibiera o facturara la solicitud. Consulta el consumo en tu proveedor antes de aprobar otro intento.';
  if(job.sent_requests===0)return 'No hay solicitudes de diseño registradas como iniciadas en este intento.';
  return 'El número de solicitudes iniciadas no está confirmado. Revisa el consumo de tu proveedor antes de aprobar otro intento.';
}
function generationFailureAction(job){
  if(job.error?.next_action)return job.error.next_action;
  if(job.status==='expired')return 'Prepara un plan nuevo y revisa su contenido para emitir una autorización nueva.';
  if(job.status==='cancelled')return 'Puedes conservar el diseño anterior o preparar otro plan cuando estés listo.';
  return 'Consulta los detalles del diagnóstico. Revisa el modelo y los límites antes de preparar un plan nuevo; no se repetirán solicitudes automáticamente.';
}
function generationDiagnostic(job){
  const report={schema:'orgdna-generation-diagnostic-ui-v2'},safeKeys=['job_id','status','stage','failed_stage','provider','model','agent_count','sent_requests','completed_requests','max_requests','completed_profiles','potentially_billed','created_at','started_at','finished_at','updated_at','response_mode','profiles_per_request','effective_profiles_per_request','max_output_tokens','effective_max_output_tokens','receipts_pending','interrupted_snapshot'];
  for(const key of safeKeys){const value=job?.[key];if(value===null||['string','number','boolean'].includes(typeof value))report[key]=typeof value==='string'?value.slice(0,300):value;}
  const error={};for(const key of ['code','category','message','next_action','stage','source_stage','provider','model','field','profile_slot','duplicate_slots','duplicate_field','batch_index','http_status','provider_error_code','provider_parameter','finish_reason','sent_requests','completed_requests','max_requests','completed_profiles','request_status','retry_requires_new_consent']){const value=job?.error?.[key];if(value===null||['string','number','boolean'].includes(typeof value))error[key]=typeof value==='string'?value.slice(0,600):value;}
  report.error=error;report.request_receipts=generationSafeReceipts(job);report.usage_summary=generationSafeUsage(job?.usage_summary,true);return report;
}
function renderGenerationFailure(result,job){
  const categories={configuration:'Configuración',compatibility:'Compatibilidad del modelo',authentication:'Autenticación del proveedor',quota:'Cuota o saldo',rate_limit:'Límite de solicitudes del proveedor',provider_unavailable:'Proveedor no disponible',transport:'Conexión con el proveedor',invalid_response:'Respuesta no válida',schema_validation:'Validación del diseño',output_limit:'Límite de salida',state:'Estado del diseño',unknown:'Causa no identificada'};
  result.append(node('h3',job.status==='cancelled'?'Trabajo cancelado':'No se publicó un ADN nuevo'));
  const facts=node('dl',undefined,'generation-facts generation-failure-facts');
  appendFact(facts,'Etapa',job.error?.source_stage||job.error?.stage||job.failed_stage||job.stage||'Desconocida');
  if(job.error?.category)appendFact(facts,'Diagnóstico',categories[job.error.category]||'Causa no identificada');if(Array.isArray(job.error?.duplicate_slots)&&job.error.duplicate_slots.length)appendFact(facts,'Perfiles en conflicto','slot(s) '+job.error.duplicate_slots.join(', ')+(job.error.duplicate_field?': '+job.error.duplicate_field:''));
  appendFact(facts,'Solicitudes iniciadas',generationRequestCount(job.sent_requests??job.error?.sent_requests));
  appendFact(facts,'Solicitudes completadas',generationRequestCount(job.completed_requests??job.error?.completed_requests)+' / '+generationRequestCount(job.max_requests??job.error?.max_requests));
  appendFact(facts,'Perfiles completados en este intento',generationRequestCount(job.completed_profiles??job.error?.completed_profiles));result.append(facts);
  result.append(node('p',typeof job.error==='string'?job.error:job.error?.message||job.message||'No hay información suficiente para identificar la causa de este intento.'));
  result.append(node('p',generationFailureAction(job),'generation-next-action'));
  if(job.error?.reading_note)result.append(node('p',job.error.reading_note,'helper'));
  result.append(node('p',generationBillingNote(job)+' No se reintenta automáticamente.','helper'));
  const details=node('details',undefined,'generation-diagnostic');details.append(node('summary','Detalles técnicos del intento'),node('pre',JSON.stringify(generationDiagnostic(job),null,2)));result.append(details);
  const actions=node('div',undefined,'actions'),retry=node('button','Preparar otro intento · sin cargo de IA','secondary');retry.id='generation-retry';retry.setAttribute('id','generation-retry');retry.type='button';retry.onclick=prepareGeneration;actions.append(retry);
  if(state?.generation_diagnostic_available===true){const download=node('button','Descargar diagnóstico JSON','textbutton');download.id='generation-diagnostic-download';download.setAttribute('id','generation-diagnostic-download');download.type='button';download.onclick=()=>downloadGenerationDiagnostic(job.job_id);actions.append(download);}
  if(state?.design_recovery?.can_restore){const recovery=node('a','Recuperar el último diseño válido →','textbutton');recovery.href='#design-recovery';actions.append(recovery);}
  result.append(actions,node('p','Preparar vuelve a leer o reutilizar la fuente y crea un plan nuevo para revisar. Sólo tu aprobación posterior puede enviar solicitudes al modelo.','helper'));
}
async function downloadGenerationDiagnostic(jobId){
  if(busy||generationOperation||generationActive()||!jobId||state?.generation_job?.job_id!==jobId||state?.generation_diagnostic_available!==true)return;
  setBusy(true);
  try{
    const response=await fetch('/download/generation-diagnostic.json?job_id='+encodeURIComponent(jobId),{credentials:'same-origin'});
    if(!response.ok){const failure=await response.json();throw new Error(failure.error||'No se pudo descargar el diagnóstico de este intento.');}
    const blob=await response.blob(),url=URL.createObjectURL(blob),link=node('a');link.href=url;link.download=downloadFilename(response.headers?.get('Content-Disposition'),'orgdna-generation-diagnostic.json');document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);message('Diagnóstico descargado para este intento. No se llamó al proveedor.');
  }catch(error){message(error.message,'error');}finally{setBusy(false);}
}
function renderDesignRecovery(){
  const recovery=state?.design_recovery,box=$('#design-recovery'),exportNote=$('#export-recovery-note');
  if(state?.generation_stale){exportNote.replaceChildren(node('span','La configuración pendiente no coincide con el diseño conservado. '));if(recovery?.available){const link=node('a','Restaura el último diseño válido para exportarlo');link.href='#design-recovery';exportNote.append(link,node('span',' o prepara y aprueba un diseño nuevo.'));}else exportNote.append(node('span','Carga una versión guardada compatible o prepara y aprueba un diseño nuevo.'));}
  box.hidden=!recovery||!(recovery.requires_restore||recovery.draft_config);if(box.hidden)return;
  if(!recovery.available){$('#design-recovery-title').textContent='Recuperación no disponible';$('#design-recovery-status').textContent='Revisión necesaria';$('#design-recovery-summary').textContent=recovery.reason||'No hay una configuración conservada compatible con este diseño.';$('#design-recovery-facts').replaceChildren();$('#design-recovery-effects').textContent='Carga una versión guardada desde Proyectos y versiones, o prepara un diseño nuevo. La recuperación no omite errores de validación.';$('#restore-design').hidden=true;$('#recovery-exports').hidden=true;$('#resume-design-draft').hidden=true;return;}
  const previous=recovery.config||{},stale=recovery.requires_restore===true;
  $('#design-recovery-title').textContent=stale?'Recupera el último diseño válido':'Diseño anterior restaurado';
  $('#design-recovery-status').textContent=stale?'Disponible para restaurar':'Disponible para exportar';
  $('#design-recovery-summary').textContent=stale?'El diseño anterior sigue conservado. La configuración pendiente es distinta; puedes restaurar la configuración que lo produjo y volver a exportarlo sin generar ni pagar otro ADN.':'Puedes exportar este diseño con su configuración original. La configuración que dejaste pendiente sigue guardada y puedes retomarla cuando quieras.';
  const facts=$('#design-recovery-facts');facts.replaceChildren();appendFact(facts,'Organización conservada',previous.repo_name||recovery.organization_id);appendFact(facts,'Perfiles del diseño',recovery.agent_count);appendFact(facts,'Proveedor / modelo de su configuración',[previous.provider,previous.model].filter(Boolean).join(' / '));appendFact(facts,'Fuente de su configuración',previous.repo_url);appendFact(facts,'Revisión del ADN',recovery.dna_revision);
  $('#design-recovery-effects').textContent=stale?'Restaurar vuelve a la configuración compatible con este diseño y guarda la configuración pendiente como borrador. No llama a proveedores, no modifica DSH y no instala ni ejecuta el equipo.':'Retomar la configuración pendiente vuelve a separar esa configuración del diseño y requiere restaurarlo o generar una revisión antes de exportar.';
  $('#restore-design').hidden=!stale;$('#recovery-exports').hidden=stale;$('#resume-design-draft').hidden=stale||!recovery.draft_config;updateGenerationControls(busy);
}
async function restoreDesign(){
  const recovery=state?.design_recovery;if(busy||generationOperation||generationActive()||!recovery?.can_restore)return;
  if(!confirm('¿Restaurar el diseño conservado de '+(recovery.agent_count??'—')+' perfiles y su configuración '+(recovery.config?.provider||'')+' / '+(recovery.config?.model||'')+'? La configuración guardada pendiente se conservará como borrador.'+(configDirty?' Los cambios del formulario que aún no guardaste se descartarán.':'')+' No se enviará ninguna solicitud al modelo ni se modificará DSH.'))return;
  await run('Restaurando el diseño conservado…',async()=>{await generationMutation('design-restore',{confirmed:true,snapshot_id:recovery.snapshot_id,expected_config_version:recovery.expected_config_version});configDirty=false;generationReviewStale=false;$('#generation-consent').checked=false;},'Diseño y configuración restaurados. Ya puedes exportarlos; no se llamó al modelo ni se modificó DSH.');
}
async function resumeDesignDraft(){
  const draft=state?.design_recovery?.draft_config;if(busy||generationOperation||generationActive()||!draft)return;
  if(!confirm('¿Retomar la configuración pendiente? El diseño conservado volverá a quedar pendiente de restaurar o regenerar antes de exportar.'+(configDirty?' Se descartarán los cambios de formulario que aún no guardaste.':'')+' No se llama al modelo.'))return;
  if(await run('Recuperando la configuración pendiente…',async()=>{await generationMutation('config',{config:draft});configDirty=false;$('#generation-consent').checked=false;},'Configuración pendiente recuperada. Revisa los cambios y prepara un plan nuevo cuando quieras.'))location.hash='configuration';
}
function readGenerationOptions(){
  const tokens=$('#generation-tokens'),batch=$('#generation-batch'),mode=$('#generation-response-mode').value,value=Number(tokens.value),batchValue=batch.value.trim();
  if(!tokens.reportValidity()||!batch.reportValidity()||!Number.isInteger(value)||value<4096||value>131072||(batchValue&&(!Number.isInteger(Number(batchValue))||Number(batchValue)<1||Number(batchValue)>32))||!['json_object','text'].includes(mode)){message('Revisa los límites: 4.096–131.072 tokens de salida y entre 1 y 32 perfiles por solicitud, o automático.','error');return null;}
  return {max_output_tokens:value,response_mode:mode,...(batchValue?{profiles_per_request:Number(batchValue)}:{})};
}

function renderGenerationIntegrity(){
  const org=state?.organization,box=$('#generation-integrity');box.hidden=!org;if(!org)return;
  $('#generation-source').textContent=generationSourceLabel();const detail=$('#generation-integrity-details');detail.replaceChildren();const facts=node('dl',undefined,'generation-facts');
  appendFact(facts,'UUID de organización',org.organization_id);appendFact(facts,'Revisión del ADN',org.dna_revision);appendFact(facts,'SHA-256 del ADN',org.dna_hash);appendFact(facts,'Completitud de perfiles',agents().length+' / '+state.config.agent_count+(agents().length===Number(state.config.agent_count)?' · N exacto':' · REVISAR: no coincide'));
  appendFact(facts,'Proveedor / modelo de generación',org.provenance?.generation_mode==='api_generated'?(org.provenance.provider+' / '+org.provenance.model):'Plantilla local; no llamada de diseño a un modelo');appendFact(facts,org.config?.source_kind==='website'?'Hash de las páginas observadas':'Commit del repositorio',org.config?.source_kind==='website'?org.provenance?.source_hash:org.provenance?.repository_sha);appendFact(facts,'Cobertura leída',org.provenance?.coverage);detail.append(facts);if(org.improvement_proposal){const proposal=node('details');proposal.append(node('summary','Mejora propuesta · validación pendiente'),node('pre',JSON.stringify(redactPreview(org.improvement_proposal),null,2)));detail.append(proposal);}
  const validation=org.validation||state.validation||{},issues=[...(validation.errors||[]),...(validation.warnings||[])];if(issues.length)detail.append(node('p',issues.map(textValue).join('\n'),'helper'));
  const completeness=org.completeness_report||validation.completeness||validation.metrics;if(completeness){const disclosure=node('details'),summary=node('summary','Informe de completitud y validación');disclosure.append(summary,node('pre',JSON.stringify(completeness,null,2)));detail.append(disclosure);}
  const artifacts=state.export_artifacts||state.generation_job?.artifacts||{},hashes=$('#export-hashes');hashes.replaceChildren();
  ['implementation','definitions','package'].forEach(key=>{const artifact=artifacts[key],link=$('#export-'+key),label=$('#export-'+key+'-name');link.removeAttribute('data-filename');if(artifact?.filename&&safeFilename(artifact.filename)){link.dataset.filename=artifact.filename;label.textContent=artifact.filename+' ↗';}else label.textContent=key==='package'?'package.zip ↗':'Nombre nativo en la descarga ↗';if(artifact?.sha256){const card=node('div');card.append(node('strong',artifact.filename||key),node('p','SHA-256: '+artifact.sha256,'exact-names'));hashes.append(card);}});
  if(!hashes.children.length)hashes.append(node('p','Hashes de archivos no disponibles en este estado. El SHA-256 del ADN identifica su contenido canónico y no sustituye el hash de cada descarga.','helper'));
}
function updateExtensionControls(transient=false){
  const locked=Boolean(transient||generationOperation||generationActive()),org=state?.organization,addon=state?.cordis_addon;
  $('#prepare-cordis').disabled=locked||!org||state.generation_stale===true;$('#choose-native-orchestration').disabled=locked||!state;
  $('#download-cordis').setAttribute('aria-disabled',String(locked||!org||state.generation_stale===true||addon?.status!=='ready'||!addon.artifact));
  ['recipe','definitions'].forEach(kind=>$('#download-cordis-'+kind).setAttribute('aria-disabled',String(locked||!org||state.generation_stale===true||addon?.status!=='ready'||!addon.integrated_exports?.[kind])));
  $('#plugin-shop-refresh').disabled=locked||!state;$('#plugin-shop-search').disabled=locked||!state?.plugin_shop?.catalog;$('#plugin-shop-wishlist').disabled=locked||!org||state.generation_stale===true||!state?.plugin_shop?.catalog;$('#plugin-shop-clear').disabled=locked||!pluginCompared.size;$('#plugin-report-save').disabled=locked||!$('#plugin-report-status').value||!$('#plugin-report-ack').checked;
  const connection=dshConnectionStatus(),connected=connection.status==='CONNECTED'&&connection.live_connection===true&&connection.identity_verified===true;
  $('#dsh-connect').disabled=locked||dshDisconnectPending||!state||!$('#dsh-pairing-consent').checked;$('#dsh-disconnect').disabled=transient||Boolean(generationOperation)||dshDisconnectPending||!state||connection.status!=='CONNECTED';$('#dsh-refresh-status').disabled=locked||!state;
  $('#dsh-read-profiles').disabled=locked||!connected||!(connection.scopes||[]).includes('teams.profiles.read')||connection.capabilities?.profiles_read?.available===false;$('#dsh-read-team').disabled=locked||!connected||!(connection.scopes||[]).includes('agentteams.state.read')||connection.capabilities?.agentteams_state_read?.available===false;$('#dsh-preview-import').disabled=locked||!connected||!org||state.generation_stale===true||!(connection.scopes||[]).includes('teams.import.preview')||connection.capabilities?.import_preview?.available===false;

}
function renderCordis(){
  const addon=state?.cordis_addon||{},labels={unprepared:'Sin preparar',ready:'Paquete preparado · no instalado',stale:'Desactualizado · volver a preparar'};
  $('#cordis-status').textContent=labels[addon.status]||'Sin preparar';const summary=$('#cordis-summary');summary.replaceChildren();
  const facts=node('dl',undefined,'generation-facts');appendFact(facts,'Perfiles en el diseño',agents().length||'Aún no generado');appendFact(facts,'Organización',state?.organization?.organization_id);appendFact(facts,'Enlace efectivo de miembros','Pendiente de vinculación y comprobación por identidad');if(addon.manifest){const manifest=addon.manifest;appendFact(facts,'Miembros del addon / nuevos propuestos',String(manifest.member_count)+' / '+String(manifest.new_agent_count));appendFact(facts,'Mismos UUID del equipo',manifest.same_roster===true?'Comprobados localmente':'Sin comprobar');appendFact(facts,'DSH revisado en código',manifest.compatibility?.source_reviewed_tools_version);appendFact(facts,'Host indicado por AgentTeams upstream',manifest.agentteams?.recommended_host_in_upstream);appendFact(facts,'Capacidad AgentTeams requerida',manifest.agentteams?.required_teammate_capacity+' compañeros + Captain incluido en N');appendFact(facts,'Adapter AgentTeams',manifest.agentteams?.live_adapter_status);}summary.append(facts);if(addon.dry_run?.blocking_reasons?.length)summary.append(node('p',addon.dry_run.blocking_reasons.join('\n'),'callout warning preformatted'));
  $('#cordis-preflight').hidden=!addon.dry_run;$('#cordis-preflight-details').textContent=addon.dry_run?JSON.stringify(redactPreview(addon.dry_run),null,2):'';
  $('#cordis-manifest').hidden=!addon.manifest;$('#cordis-manifest-details').textContent=addon.manifest?JSON.stringify(redactPreview(addon.manifest),null,2):'';
  const artifact=addon.artifact,download=$('#download-cordis');delete download.dataset.filename;$('#cordis-artifact').textContent=artifact?[artifact.filename,artifact.bytes!=null?artifact.bytes+' bytes':'',artifact.sha256?'SHA-256: '+artifact.sha256:'Hash de archivo no informado'].filter(Boolean).join('\n'):'';
  if(artifact?.filename&&safeFilename(artifact.filename))download.dataset.filename=artifact.filename;
  const integrated=$('#cordis-integrated-artifacts');integrated.replaceChildren();['recipe','definitions'].forEach(kind=>{const metadata=addon.integrated_exports?.[kind],link=$('#download-cordis-'+kind);delete link.dataset.filename;if(metadata?.filename&&safeFilename(metadata.filename))link.dataset.filename=metadata.filename;if(metadata){const detail=node('p');detail.append(node('strong',(kind==='recipe'?'Recipe integrado: ':'Definitions integradas: ')+(metadata.filename||'Nombre pendiente')),node('span',' · '+(metadata.bytes??'—')+' bytes · SHA-256: '+(metadata.sha256||'No informado')+' · Requiere addon activo'));detail.className='exact-names';integrated.append(detail);}});

  const docs=$('#cordis-docs');docs.replaceChildren(node('span','El paquete incluye instrucciones de instalación, comprobación de versiones y recuperación. Sigue el preflight del entorno antes de instalarlo.'));
  (addon.manifest?.sources||[]).forEach((url,index)=>addExternalLink(docs,'Fuente revisada '+(index+1)+' ↗',url));
  updateExtensionControls(busy);
}
$('#prepare-cordis').onclick=()=>{if(!state?.organization||state.generation_stale)return;action('cordis-prepare',{expected_state_version:state.organization.state_version||1},'Addon Cordis preparado para revisar y descargar. No se instaló ni se enlazó a un runtime.');};

function pluginRows(value){if(Array.isArray(value))return value;if(!value||typeof value!=='object')return [];if(value.id||value.plan_id)return [value];return Object.values(value).filter(item=>item&&typeof item==='object');}
function shopCandidateLabel(candidate){return [candidate.name||candidate.id,candidate.version?'v'+candidate.version:'Versión no declarada'].join(' · ');}
function safeExternalUrl(value){try{const url=new URL(String(value));return url.protocol==='https:'&&!url.username&&!url.password?url.href:null;}catch(_){return null;}}
function addExternalLink(parent,label,url){const safe=safeExternalUrl(url);if(!safe)return;const link=node('a',label);link.href=safe;link.target='_blank';link.rel='noopener noreferrer';parent.append(link);}
function candidateDetail(candidate){
  const card=node('article',undefined,'plugin-candidate'),head=node('div',undefined,'sectionhead');head.append(node('h3',shopCandidateLabel(candidate)),node('span',candidate.compatibility?.status||'UNVERIFIED','tag amber'));card.append(head,node('p',candidate.description||'Sin descripción declarada.'));
  const facts=node('dl',undefined,'generation-facts');appendFact(facts,'Origen',candidate.source);appendFact(facts,'Pin propuesto',candidate.install_spec);appendFact(facts,'Hash de entrada del catálogo',candidate.provenance?.entry_sha256);appendFact(facts,'Integridad del artefacto declarada',candidate.provenance?.source_integrity);appendFact(facts,'Categoría',candidate.category);appendFact(facts,'Capacidades propuestas',candidate.capabilities||[]);appendFact(facts,'Compatibilidad DSH declarada',candidate.compatibility?.declared_dsh||'Sin declarar');appendFact(facts,'Perfiles declarados',candidate.compatibility?.declared_profiles||[]);appendFact(facts,'Dependencias requeridas',candidate.required_peers||[]);appendFact(facts,'Confianza de la fuente',candidate.trust?.status||'UNVERIFIED');card.append(facts);
  if(candidate.trust?.warning)card.append(node('p',candidate.trust.warning,'helper'));
  const inspection=candidate.inspection;if(inspection){if(inspection.manifest_inspected===false)card.append(node('p','Sólo metadatos de release: manifiesto, scripts y dependencias del archivo todavía no inspeccionados.','callout warning'));card.append(node('h4','Riesgos observados en metadatos'),node('p',textValue(inspection.risks||'Sin riesgos listados; no equivale a seguro.'),'helper'));const detail=node('details'),summary=node('summary','Scripts, dependencias y evidencias');detail.append(summary,node('pre',JSON.stringify(redactPreview(inspection),null,2)));card.append(detail);}
  const links=node('div',undefined,'plugin-links');addExternalLink(links,'Repositorio declarado ↗',typeof candidate.repository==='string'?candidate.repository:candidate.repository?.url);addExternalLink(links,'Catálogo de origen ↗',candidate.provenance?.catalog_url);card.append(links);return card;
}
function renderPluginShop(){
  const shop=state?.plugin_shop||{},catalog=shop.catalog,summary=$('#plugin-shop-catalog'),catalogIdentity=catalog?(catalog.catalog_sha256||[catalog.source,catalog.built_at,catalog.candidate_count].join(':')):null;if(pluginCatalogIdentity!==catalogIdentity){pluginCompared.clear();for(const [key,value] of capSelected)if(value.origin==='catalog')capSelected.delete(key);capDropPlan('Catálogo actualizado; vuelve a seleccionar sus candidatos.');pluginCatalogIdentity=catalogIdentity;}$('#plugin-shop-status').textContent=catalog?'Catálogo consultado · runtime sin verificar':'Catálogo sin consultar';
  summary.textContent=catalog?[(catalog.candidate_count??catalog.total??catalog.count??catalog.candidates?.length??'')+' candidatos en catálogo',catalog.catalog_built_at||catalog.built_at||'',catalog.catalog_sha256?'SHA-256 catálogo: '+catalog.catalog_sha256:''].filter(Boolean).join(' · '):'La consulta es de sólo lectura. No instala ni ejecuta el código del catálogo.';
  const inspected=pluginRows(shop.inspected),reported=pluginRows(shop.reported_candidates),sameCurrent=(item,candidate)=>item.id===candidate.id&&item.version===candidate.version&&item.provenance?.entry_sha256===candidate.provenance?.entry_sha256&&!item.stale_against_catalog&&!item.historical_reference,enrich=candidate=>reported.find(item=>sameCurrent(item,candidate))||inspected.find(item=>sameCurrent(item,candidate))||candidate;
  const source=(shop.search?.results||[]).slice(0,100).map(enrich),category=$('#plugin-shop-category'),previous=category.value;category.replaceChildren(option('','Todas'));(shop.search?.categories||[...new Set(source.map(item=>item.category).filter(Boolean))]).sort().forEach(value=>category.append(option(value,value)));if([...category.options].some(item=>item.value===previous))category.value=previous;
  let results=source;
  $('#plugin-shop-result-count').textContent=results.length+' en esta página · '+(shop.search?.total??source.length)+' coincidencias. Filtros sobre el catálogo completo.';
  const list=$('#plugin-shop-results');list.replaceChildren();results.forEach(candidate=>{if(pluginCompared.has(candidate.id))pluginCompared.set(candidate.id,candidate);const card=node('article',undefined,'plugin-result');card.append(node('h3',shopCandidateLabel(candidate)),node('p',candidate.description||'Sin descripción declarada.'),node('span',(candidate.category||'Sin categoría')+' · '+(candidate.compatibility?.status||'UNVERIFIED'),'tag'));
    if(candidate.inspection){if(candidate.inspection.manifest_inspected===false)card.append(node('p','Release: manifiesto, scripts y dependencias aún sin inspeccionar.','helper'));const inspection=node('details');inspection.append(node('summary','Metadatos inspeccionados: riesgos y dependencias'),node('pre',JSON.stringify(redactPreview(candidate.inspection),null,2)));card.append(inspection);}if(candidate.status)card.append(node('p','Estado local: '+candidate.status+' · runtime sin verificar','helper'));
    const actions=node('div',undefined,'actions'),inspect=node('button','Inspeccionar metadatos','textbutton'),plan=node('button','Preparar plan versionado','textbutton'),compare=node('label',undefined,'check'),check=node('input');inspect.type='button';plan.type='button';check.type='checkbox';check.checked=pluginCompared.has(candidate.id);check.addEventListener('change',()=>{if(check.checked){if(pluginCompared.size>=3){check.checked=false;message('Compara hasta tres candidatos a la vez.','error');return;}pluginCompared.set(candidate.id,candidate);}else pluginCompared.delete(candidate.id);renderPluginComparison();setBusy(busy);});compare.append(check,node('span','Comparar'));
    inspect.onclick=()=>action('plugin-shop-inspect',{candidate_id:candidate.id},'Metadatos inspeccionados. Compatibilidad y ejecución siguen sin verificar.');plan.onclick=()=>action('plugin-shop-plan',{candidate_id:candidate.id},'Plan versionado preparado. No se ha instalado ni habilitado el plugin.');actions.append(capChoice(candidate,'catalog'),inspect,plan,compare);const resourceUrl=safeExternalUrl(typeof candidate.repository==='string'?candidate.repository:candidate.repository?.url);if(resourceUrl){const read=node('button','Leer fuente para workflows','textbutton');read.type='button';read.onclick=async()=>{$('#cap-reference-url').value=resourceUrl;capDropPlan();resourceEpoch++;if(await action('capability-source-read',{url:resourceUrl,item_kind:'skill_instructions'},'Fuente del recurso leída. Elige perfiles y prepara sus workflows.')){$('#resource-workflows').scrollIntoView({block:'start'});}};actions.append(read);}card.append(actions);list.append(card);});if(!results.length)list.append(node('p',catalog?'Busca un nombre o capacidad en el catálogo consultado.':'Consulta primero el catálogo público.','helper'));
  const gaps=$('#plugin-shop-gaps');gaps.replaceChildren();const wishlist=shop.wishlist;if(wishlist){gaps.append(node('h3','Brechas y candidatos propuestos'));(wishlist.gaps||[]).slice(0,20).forEach(gap=>gaps.append(node('p',gap.capability+' · '+gap.candidate_count+' candidatos · '+gap.status,'helper')));const suggestions=node('div',undefined,'actions');(wishlist.suggestions||[]).slice(0,20).forEach(suggestion=>{const button=node('button','Buscar '+suggestion.name,'textbutton');button.type='button';button.onclick=()=>{$('#plugin-shop-query').value=suggestion.name;action('plugin-shop-search',{query:suggestion.name,limit:100});};suggestions.append(button);});gaps.append(suggestions);const disclosure=node('details'),heading=node('summary','Evidencias, cobertura y límites de la propuesta');disclosure.append(heading,node('pre',JSON.stringify(redactPreview(wishlist),null,2)));gaps.append(disclosure);}
  renderPluginComparison();const plans=$('#plugin-shop-plans');plans.replaceChildren();if(pluginRows(shop.plans).length>10)plans.append(node('p','Mostrando los últimos 10 de '+pluginRows(shop.plans).length+' planes. Todos permanecen en el registro local de la sesión.','helper'));pluginRows(shop.plans).slice(-10).reverse().forEach(plan=>{const card=node('article',undefined,'plugin-plan');card.append(node('h3','Plan · '+shopCandidateLabel(plan.candidate||{})),node('span',plan.stale_against_catalog?'PLAN HISTÓRICO · versión cambió':plan.status||'PLAN_ONLY','tag amber'));const facts=node('dl',undefined,'generation-facts');appendFact(facts,'Plan / solicitud',plan.plan_id+' / '+plan.request_id);appendFact(facts,'Perfil de destino',plan.profile);appendFact(facts,'Versión / integridad fijada',plan.pin);appendFact(facts,'Riesgos',plan.risks||[]);appendFact(facts,'Bloqueos',plan.blockers||[]);appendFact(facts,'Aprobaciones necesarias',plan.approvals_required||[]);appendFact(facts,'Runtime',plan.runtime_verified===true?'Verificación declarada por la fuente; revisar evidencia':'Sin verificar · no instalado por esta app');card.append(facts);const details=node('details');details.append(node('summary','Ver comprobaciones, respaldo y rollback'),node('pre',JSON.stringify(redactPreview(plan),null,2)));card.append(details);plans.append(card);});
  const reports=$('#plugin-shop-reports');reports.replaceChildren();pluginRows(shop.reported_candidates).forEach(record=>{const report=node('details');report.append(node('summary',shopCandidateLabel(record)+' · '+record.status+' · reporte manual'+(record.historical_reference||record.stale_against_catalog?' histórico':'')),node('pre',JSON.stringify(redactPreview(record.history||[]),null,2)));reports.append(report);});
  renderPluginReportForm();updateExtensionControls(busy);
}
function renderPluginComparison(){const box=$('#plugin-shop-comparison');box.hidden=!pluginCompared.size;const cards=$('#plugin-shop-comparison-cards');cards.replaceChildren();pluginCompared.forEach(candidate=>cards.append(candidateDetail(candidate)));}
function pluginReportCandidate(){const id=$('#plugin-report-candidate').value,shop=state?.plugin_shop||{},reported=pluginRows(shop.reported_candidates).find(candidate=>candidate.id===id);return reported&&!reported.historical_reference&&!reported.stale_against_catalog?reported:pluginRows(shop.inspected).find(candidate=>candidate.id===id)||reported;}
function renderPluginReportForm(){
  const shop=state?.plugin_shop||{},select=$('#plugin-report-candidate'),previous=select.value,rows=new Map();pluginRows(shop.inspected).concat(pluginRows(shop.reported_candidates)).forEach(candidate=>{if(!rows.has(candidate.id)||!candidate.historical_reference&&!candidate.stale_against_catalog)rows.set(candidate.id,candidate);});select.replaceChildren(option('','Selecciona un candidato inspeccionado'));rows.forEach(candidate=>select.append(option(candidate.id,shopCandidateLabel(candidate))));if(rows.has(previous))select.value=previous;
  const candidate=pluginReportCandidate(),states={inspected:['approved_by_operator','Revisión aprobada según el operador'],approved_by_operator:['test_reported','Prueba reportada por el operador'],test_reported:['active_reported','Activación reportada por el operador']},next=candidate&&!candidate.historical_reference&&!candidate.stale_against_catalog?states[candidate.status]:null,status=$('#plugin-report-status');status.replaceChildren(option('','Sin transición disponible'));if(next){status.append(option(next[0],next[1]));status.value=next[0];}
  const fingerprint=candidate?[candidate.id,candidate.version,candidate.provenance?.entry_sha256,candidate.status].join(':'):null;if(pluginReportFingerprint!==fingerprint){pluginReportFingerprint=fingerprint;$('#plugin-report-ack').checked=false;$('#plugin-report-note').value='';$('#plugin-report-result').value='';const plan=pluginRows(shop.plans).filter(item=>item.candidate?.id===candidate?.id&&item.candidate?.version===candidate?.version&&item.candidate?.provenance?.entry_sha256===candidate?.provenance?.entry_sha256&&!item.stale_against_catalog).at(-1),prior=candidate?.history?.at(-1)?.evidence||{};$('#plugin-report-request').value=prior.request_id||plan?.request_id||'';$('#plugin-report-profile').value=prior.profile||plan?.profile||'orgdna-isolated';$('#plugin-report-version').value=prior.runtime_version||'';$('#plugin-report-evidence').value='';}
  $('#plugin-report-identity').textContent=candidate?'Versión: '+candidate.version+' · SHA-256 de entrada: '+candidate.provenance?.entry_sha256+' · Estado: '+candidate.status+(candidate.stale_against_catalog||candidate.historical_reference?' · Referencia histórica: vuelve a inspeccionar el catálogo actual.':''):'Inspecciona los metadatos de un candidato antes de registrar un reporte.';const runtime=Boolean(next&&next[0]!=='approved_by_operator');$('#plugin-report-runtime').hidden=!runtime;['plugin-report-profile','plugin-report-version','plugin-report-result','plugin-report-evidence'].forEach(id=>$('#'+id).required=runtime);
}
$('#plugin-report-candidate').onchange=()=>{renderPluginReportForm();setBusy(busy);};$('#plugin-report-ack').onchange=()=>setBusy(busy);
$('#plugin-shop-report-form').onsubmit=async e=>{e.preventDefault();const candidate=pluginReportCandidate(),status=$('#plugin-report-status').value;if(!candidate||!status||!$('#plugin-report-ack').checked)return;const evidence={candidate_id:candidate.id,version:candidate.version,entry_sha256:candidate.provenance?.entry_sha256,operator:$('#plugin-report-operator').value,note:$('#plugin-report-note').value,request_id:$('#plugin-report-request').value,acknowledged:true};if(status!=='approved_by_operator')Object.assign(evidence,{profile:$('#plugin-report-profile').value,runtime_version:$('#plugin-report-version').value,result:$('#plugin-report-result').value,evidence_ref:$('#plugin-report-evidence').value});await action('plugin-shop-status',{candidate_id:candidate.id,status,evidence},'Declaración registrada localmente. No se verificó ni modificó el runtime.');};

$('#plugin-shop-refresh').onclick=()=>action('plugin-shop-refresh',{source:'github_pages'},'Catálogo público consultado. Sus candidatos no se han instalado ni probado en tu runtime.');
$('#plugin-shop-search-form').onsubmit=e=>{e.preventDefault();capCatalogSearch(0);};
$('#plugin-shop-wishlist').onclick=()=>action('plugin-shop-wishlist',{expected_state_version:state.organization.state_version||1,limit:20},'Búsquedas propuestas a partir de las brechas del diseño. No se ha instalado nada.');
$('#plugin-shop-category').onchange=()=>capCatalogSearch(0);$('#plugin-shop-sort').onchange=()=>capCatalogSearch(0);$('#plugin-shop-clear').onclick=()=>{pluginCompared.clear();renderPluginShop();setBusy(busy);};

function dshConnectionStatus(){const connection=state?.dsh_connection||{};return connection.status&&typeof connection.status==='object'?connection.status:connection;}
function renderDshConnection(){
  const connection=state?.dsh_connection||{},status=dshConnectionStatus(),verified=status.status==='CONNECTED'&&status.live_connection===true&&status.identity_verified===true;
  $('#dsh-connection-status').textContent=verified?'Conexión local verificada · sólo lectura':status.status==='CONNECTED'?'Conexión parcial · identidad por verificar':'Desconectado';
  const details=$('#dsh-connection-details');details.replaceChildren();if(status.instance_id||status.versions||status.capabilities){const facts=node('dl',undefined,'generation-facts');appendFact(facts,'Instancia',status.instance_id);appendFact(facts,'Versiones declaradas por el enlace',status.versions);appendFact(facts,'Ámbitos concedidos',status.scopes);appendFact(facts,'Identidad del addon comprobada',status.identity_verified===true?'Sí, para esta conexión':'No');appendFact(facts,'Identidad de sesión runtime',status.runtime_session_identity_verified===true?'Verificada por la fuente':'Sin verificar; no inferirla del handshake del addon');appendFact(facts,'Última comprobación explícita',localDate(status.checked_at));appendFact(facts,'Caducidad del enlace',status.expires_at?localDate(Number(status.expires_at)*1000):'No informada');details.append(facts);const blockers=[['profiles_read','Perfiles'],['agentteams_state_read','Estado AgentTeams'],['import_preview','Vista previa de importación']].flatMap(([key,label])=>status.capabilities?.[key]?.available===false?[label+': '+(status.capabilities[key].reason||'Capacidad no disponible')]:[]);if(blockers.length)details.append(node('p',blockers.join('\n'),'callout warning preformatted'));if(status.capabilities){const disclosure=node('details');disclosure.append(node('summary','Capacidades disponibles y bloqueos'),node('pre',JSON.stringify(redactPreview(status.capabilities),null,2)));details.append(disclosure);}}
  ['profiles','team'].forEach(kind=>{const value=connection[kind],box=$('#dsh-'+kind+'-result');box.hidden=!value;$('#dsh-'+kind+'-json').textContent=value?JSON.stringify(redactPreview(value),null,2):'';if(value&&!verified){const old=box.querySelector('.dsh-snapshot-warning');if(!old)box.append(node('p','Lectura anterior. No hay conexión verificada actualmente.','helper dsh-snapshot-warning'));}else box.querySelector('.dsh-snapshot-warning')?.remove();});
  $('#dsh-import-result').hidden=!connection.import_preview;$('#dsh-import-json').textContent=connection.import_preview?JSON.stringify(redactPreview(connection.import_preview),null,2):'';updateExtensionControls(busy);
}
$('#dsh-pairing-consent').onchange=()=>setBusy(busy);
$('#dsh-connect-form').onsubmit=async e=>{e.preventDefault();if(busy||generationActive()||!$('#dsh-pairing-consent').checked)return;const form=e.target,pairing_code=form.elements.pairing_code.value,port=Number(form.elements.port.value);form.elements.pairing_code.value='';if(!Number.isInteger(port)||port<1024||port>65535){message('El puerto debe ser un entero entre 1.024 y 65.535.','error');return;}if(!/^[A-Za-z0-9_-]{43}$/.test(pairing_code)){message('El código debe ser el valor de 43 caracteres mostrado por el panel DSH.','error');return;}await action('dsh-connect',{port,pairing_code,confirmed:true},'Solicitud de conexión completada. Revisa la identidad, los ámbitos y capacidades devueltos por el runtime.');$('#dsh-pairing-consent').checked=false;setBusy(busy);};
async function disconnectDsh(){
  if(busy||generationOperation||dshDisconnectPending)return;dshDisconnectPending=true;dshEpoch++;updateExtensionControls(busy);
  try{const response=await fetch('/api/dsh-disconnect',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},credentials:'same-origin',body:'{}'}),payload=await response.json();if(!response.ok)throw new Error(payload.error||'El motor no confirmó la desconexión.');dshEpoch++;state.dsh_connection=payload.dsh_connection;renderDshConnection();message('Conexión local cerrada. No se ha cambiado la configuración de DSH.');}
  catch(error){message('No se pudo confirmar la desconexión: '+error.message,'error');}
  finally{dshDisconnectPending=false;updateExtensionControls(busy);}
}
$('#dsh-disconnect').onclick=disconnectDsh;
$('#dsh-refresh-status').onclick=()=>action('dsh-status');
$('#dsh-read-profiles').onclick=()=>action('dsh-read-profiles',{},'Lectura de perfiles configurados obtenida del enlace. Esto no verifica herramientas ni ejecución.');
$('#dsh-read-team-form').onsubmit=e=>{e.preventDefault();action('dsh-read-team',{team_name:$('#dsh-team-name').value.trim()},'Lectura del equipo obtenida. Consulta su procedencia y las limitaciones de identidad.');};
$('#dsh-preview-import').onclick=()=>{if(!state?.organization)return;action('dsh-preview-import',{document_kind:$('#dsh-import-kind').value,expected_state_version:state.organization.state_version||1},'Comparación en seco completada. No se importó ningún archivo al runtime.');};

function renderOrchestrationChoice(){
  const selected=$('#config-form').elements.orchestration_backend.value,native=selected==='agentteams_native';
  $('#orchestration-selection-status').textContent=native?'AgentTeams será el único orquestador: 1 Captain dentro de N y N−1 compañeros. Teams GUI exportará perfiles pasivos manual/model-tool para evitar doble dispatch. Capacidad nativa y sesiones aún requieren preflight.':'Teams GUI conserva la ejecución del equipo con el preset elegido. Usa el modo nativo si quieres que AgentTeams coordine el mismo equipo y Teams sea sólo la fuente de perfiles.';
  $('#autonomy-cost-note').textContent=native?'La autonomía cambia de orquestador. Los perfiles de Teams quedan pasivos; la ejecución nativa de AgentTeams depende de su configuración, capacidad y preflight. Las tareas autorizadas pueden consumir tokens. Esta app no inicia ni conecta el equipo al cambiar esta opción.':'En Teams GUI, always + guaranteed puede iniciar agentes y consumir tokens por cada mensaje de la sesión con el equipo seleccionado. Esto es adicional al coste de generar el ADN. El preset manual o contextual cambia la activación.';
}
$('#choose-native-orchestration').onclick=()=>{if(busy||generationOperation||generationActive())return;$('#config-form').elements.orchestration_backend.value='agentteams_native';if(state?.organization)$('#generation-new-project').checked=false;configDirty=true;renderOrchestrationChoice();renderAutonomy();setBusy(busy);location.hash='configuration';message('AgentTeams seleccionado como único orquestador. Revisa la configuración y genera una revisión para conservar la identidad del diseño actual. El runtime no se ha modificado.');};

function currentAutonomy(){return state?.generation_stale||!state?.organization?state?.autonomy_preview:state.organization.autonomy||state.autonomy_preview;}
function renderAutonomy(){
  const autonomy=currentAutonomy(),box=$('#autonomy-overview');box.hidden=!autonomy;if(!autonomy)return;
  const labels={autonomous:'Máxima autonomía',smart:'Autonomía contextual',manual:'Activación manual'};$('#autonomy-mode').textContent=labels[autonomy.preset]||autonomy.preset||'Preset del diseño';
  $('#autonomy-preview-state').textContent=configDirty?'Hay cambios sin guardar. Guarda la configuración o prepara el ADN para actualizar esta vista.':state?.organization?.autonomy===autonomy?'Contexto del ADN generado; ejecución DSH sin verificar.':'Vista previa de la configuración guardada. El diseño del equipo aún puede cambiar al analizar el repositorio.';
  const orchestration=$('#autonomy-orchestration'),control=autonomy.orchestration;orchestration.replaceChildren();if(control){const facts=node('dl',undefined,'generation-facts');appendFact(facts,'Orquestador',control.task_orchestrator||control.backend);appendFact(facts,'Fuente de perfiles',control.profile_source);appendFact(facts,'Capacidades',control.capability_runtime);appendFact(facts,'Diseño: Captain / compañeros / total',String(control.captain_count??'—')+' / '+String(control.teammate_count??'—')+' / '+String(control.total_profile_count??'—'));appendFact(facts,'Dispatch de Teams GUI',control.gui_dispatch_enabled===true?'Habilitado por este preset':'Pasivo: no duplica el orquestador nativo');appendFact(facts,'Preflight nativo',control.status||'Pendiente de verificar');orchestration.append(facts);}
  $('#autonomy-mission').textContent=textValue(autonomy.mission||'Objetivo pendiente de declarar.');
  const greeting=$('#autonomy-greeting');greeting.replaceChildren(node('h3','Presentación, capacidades y metas'));
  const contract=autonomy.greeting_contract||{};if(Array.isArray(contract))contract.forEach(item=>greeting.append(node('p',textValue(item))));else if(typeof contract==='string')greeting.append(node('p',contract));else Object.entries(contract).forEach(([key,value])=>greeting.append(node('p',key+': '+(Array.isArray(value)?value.map(textValue).join(' · '):textValue(value)))));
  if(autonomy.capabilities?.length){greeting.append(node('h4','Capacidades propuestas'));const capabilities=node('ul');autonomy.capabilities.forEach(capability=>capabilities.append(node('li',textValue(capability))));greeting.append(capabilities);}
  $('#autonomy-settings').textContent=JSON.stringify(autonomy.settings||autonomy.phase_settings||{},null,2);
  $('#autonomy-plan-preview').value=typeof autonomy.plan_preview==='string'?autonomy.plan_preview:textValue(autonomy.plan_preview);
  $('#autonomy-limitations').textContent=Array.isArray(autonomy.limitations)?autonomy.limitations.map(textValue).join('\n'):textValue(autonomy.limitations);
}
async function copyPlanPreview(){
  const field=$('#autonomy-plan-preview');if(!field.value||configDirty||generationActive())return;
  if(globalThis.navigator?.clipboard?.writeText){try{await globalThis.navigator.clipboard.writeText(field.value);message('Plan preview copiado. Pégalo en el campo correspondiente de DSH para revisarlo.');return;}catch(_){}}
  field.focus?.();field.select?.();message('Selecciona y copia el texto de Plan preview con Ctrl+C o Cmd+C. Tu navegador no permitió copiarlo automáticamente.');
}
$('#copy-plan-preview').onclick=copyPlanPreview;

function safeFilename(name){return typeof name==='string'&&name.length>0&&name.length<256&&!/[\\/\x00-\x1f\x7f]/.test(name)&&name!=='.'&&name!=='..';}
function downloadFilename(disposition,fallback){let name;const encoded=String(disposition||'').match(/filename\*=UTF-8''([^;]+)/i),plain=String(disposition||'').match(/filename="([^"]+)"|filename=([^;\s]+)/i);try{name=encoded?decodeURIComponent(encoded[1]):plain?(plain[1]||plain[2]):null;}catch(_){name=null;}return safeFilename(name)?name:safeFilename(fallback)?fallback:'orgdna-export.json';}
async function generationMutation(route,data){
  const epoch=++generationEpoch,dshRevision=dshEpoch;let response,payload;
  try{response=await fetch('/api/'+route,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},credentials:'same-origin',body:JSON.stringify(data)});payload=await response.json();}
  catch(error){if(epoch!==generationEpoch)return state;generationEpoch++;throw error;}
  if(epoch!==generationEpoch)return state;generationEpoch++;
  if(!response.ok)throw new Error(payload.error||'No se pudo completar la generación.');if(dshRevision!==dshEpoch&&state)payload.dsh_connection=state.dsh_connection;state=payload;return payload;
}
async function prepareGeneration(){
  if(busy||generationOperation||generationActive())return;
  location.hash='configuration';if(!$('#config-form').reportValidity())return;
  const options=readGenerationOptions();if(!options)return;
  const config=readGenerationConfig();if(!config.repo_url){message('Indica la URL de una fuente pública para preparar un ADN con IA.','error');return;}
  if(!(state.credentials_configured||[]).includes(config.provider)){message('Prepara primero la API key del proveedor seleccionado en el panel de clave.','error');$('#generation-studio-key').scrollIntoView({block:'center'});return;}
  const selectedModel=generationCatalogRows(config.provider).find(m=>(m.model||m.id)===config.model),manualModel=generationDocumentedModel(selectedModel,config.provider);
  if(manualModel&&!$('#generation-manual-model').checked){message('Confirma que revisaste esta referencia documentada de Z.AI. Su disponibilidad y capacidades en tu cuenta siguen sin verificar.','error');return;}
  const edited=state.has_manual_edits===true;if(edited&&!confirm('El nuevo ADN sustituirá las ediciones manuales actuales. Guarda una versión para conservarlas. ¿Preparar el nuevo diseño?'))return;
  const operationId=++generationOperationCounter;generationOperation=operationId;generationReviewStale=false;generationPlanKey=globalThis.crypto?.randomUUID?.()||'plan-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);setBusy(true);generationMessage('Leyendo la fuente y preparando un plan de envío. Aún no se llama al modelo.','busy');
  try{await generationMutation('generation-plan',{idempotency_key:generationPlanKey,config,...(manualModel?{manual_model_confirmed:true}:{}),new_project:generationImprovementRunIds.length?false:$('#generation-new-project').checked,...(generationImprovementRunIds.length?{improvement_run_ids:[...generationImprovementRunIds]}:{}),...options,...(edited?{confirmed_discard_edits:true}:{})});configDirty=false;generationImprovementRunIds=[];render();}
  catch(error){message(error.message+' No se reintentó la preparación.','error');await readGenerationState();}
  finally{if(generationOperation===operationId){generationOperation=false;setBusy(false);}if(generationNeedsPolling())scheduleGenerationPoll();}
}
async function confirmGeneration(){
  const job=state?.generation_job,pending=state?.pending_consent;if(busy||generationOperation||generationCancelPending||generationReviewStale||configDirty||job?.status!=='awaiting_consent'||pending?.job_id!==job.job_id||!$('#generation-consent').checked)return;
  const operationId=++generationOperationCounter;generationOperation=operationId;setBusy(true);generationMessage('Generando con el proveedor y el modelo aprobados.','busy',job.job_id);
  try{await generationMutation('generation-confirm',{job_id:job.job_id,consent_id:pending.approval_id,payload_sha256:pending.payload_sha256,config_version:pending.config_version??job.config_version,confirmed:true,data_reviewed:true,budget_acknowledged:true,partial_inventory_acknowledged:Boolean(pending.partial_inventory_required),coverage_sha256:pending.coverage_sha256});render();}
  catch(error){message(error.message+' No se reintenta una llamada de pago. Consulta el estado antes de preparar otra.','error');await readGenerationState();}
  finally{if(generationOperation===operationId){generationOperation=false;setBusy(false);}if(generationNeedsPolling())scheduleGenerationPoll();}
}
async function cancelGeneration(){
  const job=state?.generation_job;if(!generationActive()||generationCancelPending)return;generationCancelPending=true;updateGenerationControls();
  try{await generationMutation('generation-cancel',{job_id:job.job_id});generationReviewStale=false;if(!generationActive())generationOperation=false;render();message('Cancelación registrada. Una solicitud ya enviada podría facturarse; su resultado pendiente no se publicará.');}
  catch(error){message('No se pudo confirmar la cancelación: '+error.message+'. No des por detenida una solicitud enviada.','error');await readGenerationState();}
  finally{generationCancelPending=false;setBusy(false);}
}
async function readGenerationState(){const epoch=generationEpoch,dshRevision=dshEpoch;try{const response=await fetch('/api/state',{credentials:'same-origin'});if(!response.ok)throw new Error('El motor no respondió al consultar el estado.');const payload=await response.json();if(epoch!==generationEpoch)return;if(dshRevision!==dshEpoch&&state)payload.dsh_connection=state.dsh_connection;state=payload;render();}catch(error){message('No se pudo actualizar el estado: '+error.message+' La generación puede seguir en el motor.','error');}}
function scheduleGenerationPoll(){if(generationPollTimer!==null||generationPollInFlight||!generationNeedsPolling())return;generationPollTimer=setTimeout(async()=>{generationPollTimer=null;if(!generationNeedsPolling())return;generationPollInFlight=true;try{await readGenerationState();}finally{generationPollInFlight=false;if(generationNeedsPolling())scheduleGenerationPoll();}},1200);}
$('#confirm-generation').onclick=confirmGeneration;$('#cancel-generation').onclick=cancelGeneration;
$('#generation-consent').onchange=()=>updateGenerationControls(busy);
$('#restore-design').onclick=restoreDesign;$('#resume-design-draft').onclick=resumeDesignDraft;
['#generation-tokens','#generation-batch','#generation-response-mode','#generation-new-project'].forEach(id=>$(id).onchange=()=>{if(generationActive())generationReviewStale=true;$('#generation-consent').checked=false;renderGeneration();});


async function prepareImprovement(runIds){
  if(busy||generationOperation||generationActive()||!state?.organization)return;
  if(state.generation_stale){message('Actualiza o carga un diseño vigente antes de proponer una mejora.','error');return;}
  generationImprovementRunIds=[...runIds];$('#generation-new-project').checked=false;location.hash='configuration';
  renderGeneration();await prepareGeneration();
}
$('#improvement-clear').onclick=()=>{if(generationActive())return;generationImprovementRunIds=[];renderGeneration();};
function evaluationPlans(){return state?.evaluations?.plans||[];}
function evaluationRuns(){return state?.evaluations?.runs||[];}
function selectedEvaluationPlan(){return evaluationPlans().find(plan=>plan.id===evaluationPlanId)||evaluationPlans().at(-1);}
function updateEvaluationControls(){
  const plan=selectedEvaluationPlan(),blocked=busy||generationOperation||generationActive()||!state?.organization||state.generation_stale;
  $('#evaluation-prepare').disabled=blocked;
  $('#evaluation-start').disabled=blocked||evaluationPlanStale||!plan||!$('#evaluation-consent').checked||evaluationRuns().some(run=>run.plan_id===plan.id);
  $('#evaluation-refresh').disabled=busy;$$('[data-evaluation-cancel]').forEach(button=>button.disabled=false);
}
function renderEvaluationChoices(){
  const profiles=$('#evaluation-profile'),previousProfile=profiles.value;profiles.replaceChildren();(state?.evaluations?.profiles||[]).forEach(profile=>profiles.append(option(profile.id,profile.name||profile.id)));if([...profiles.options].some(item=>item.value===previousProfile))profiles.value=previousProfile;
  const agent=agents().find(item=>item.id===$('#evaluation-agent').value),evaluators=$('#evaluation-evaluator'),oldEvaluator=evaluators.value,skills=$('#evaluation-skill'),oldSkill=skills.value;
  evaluators.replaceChildren(option('OWNER_EXTERNAL','Owner externo · revisión humana pendiente'));agents().filter(item=>item.id!==agent?.id).forEach(item=>evaluators.append(option(item.id,agentLabel(item.id))));if([...evaluators.options].some(item=>item.value===oldEvaluator))evaluators.value=oldEvaluator;
  skills.replaceChildren(option('','Sin skill específica · sólo ejecución'));[...(agent?.skills||[]),...(agent?.proposed_skills||[])].filter(item=>item.id).forEach(item=>skills.append(option(item.id,item.name+' · '+item.id)));if([...skills.options].some(item=>item.value===oldSkill))skills.value=oldSkill;
}
function renderEvaluations(){
  populateAgentSelect($('#evaluation-agent'));renderEvaluationChoices();
  const plan=selectedEvaluationPlan(),fingerprint=plan?[plan.id,plan.plan_hash].join(':'):null;
  if(fingerprint!==evaluationPlanFingerprint){$('#evaluation-consent').checked=false;evaluationPlanFingerprint=fingerprint;}
  $('#evaluation-review').hidden=!plan;$('#evaluation-plan').textContent=plan?JSON.stringify(redactPreview(plan),null,2):'';
  const list=$('#evaluation-runs');list.replaceChildren();
  evaluationRuns().slice().reverse().forEach(run=>{const row=node('article',undefined,'record');row.append(node('h3','Prueba '+(run.id||'')+' · '+run.status),node('pre',JSON.stringify(redactPreview(run),null,2)),node('p','Resultado de esta ejecución; no certifica competencia ni concede permisos.','helper'));if(['pass','fail','timeout'].includes(run.status)&&run.evidence_ref){const improve=node('button','Proponer mejora con este resultado','secondary');improve.type='button';improve.onclick=()=>prepareImprovement([run.id]);row.append(improve);}if(['queued','running','pending'].includes(run.status)){const cancel=node('button','Cancelar prueba','textbutton');cancel.type='button';cancel.setAttribute('data-evaluation-cancel','true');cancel.onclick=async()=>{try{await request('evaluation-cancel',{run_id:run.id});render();}catch(error){message(error.message,'error');}};row.append(cancel);}list.append(row);});
  if(evaluationRuns().some(run=>['queued','running','pending'].includes(run.status))&&evaluationPollTimer===null){evaluationPollTimer=setTimeout(async()=>{evaluationPollTimer=null;await readGenerationState();},1200);}
  updateEvaluationControls();
}
$('#evaluation-form').onsubmit=async event=>{event.preventDefault();if(!event.target.reportValidity())return;const body={profile_id:$('#evaluation-profile').value,agent_id:$('#evaluation-agent').value,evaluator_id:$('#evaluation-evaluator').value.trim(),task_id:$('#evaluation-task').value.trim(),skill_ids:$('#evaluation-skill').value?[$('#evaluation-skill').value]:[],cwd:$('#evaluation-cwd').value.trim(),test_dir:$('#evaluation-tests').value.trim(),timeout_seconds:Number($('#evaluation-timeout').value)};if(await action('evaluation-prepare',body,'Plan local preparado. Revisa el comando y sus efectos antes de ejecutar.')){evaluationPlanId=evaluationPlans().at(-1)?.id;evaluationPlanStale=false;renderEvaluations();}};
$('#evaluation-consent').onchange=updateEvaluationControls;
$('#evaluation-form').addEventListener('input',()=>{evaluationPlanStale=true;$('#evaluation-consent').checked=false;renderEvaluationChoices();updateEvaluationControls();});
$('#evaluation-start').onclick=async()=>{const plan=selectedEvaluationPlan();if(!plan||evaluationPlanStale||!$('#evaluation-consent').checked)return;await action('evaluation-start',{plan_id:plan.id,plan_hash:plan.plan_hash,confirmed:true},'Ejecución solicitada. Revisa el estado y la evidencia del resultado.');};
$('#evaluation-refresh').onclick=()=>readGenerationState();



// Local restart preparation is ephemeral; no script bytes or secrets are exported.
function updateDshLauncherControls(){
  const plan=state?.dsh_launcher?.plan,locked=busy||generationOperation||generationActive();
  $('#dsh-launch-inspect').disabled=locked||!state;
  $('#dsh-launch-discover').disabled=locked||!state;$('#dsh-launch-use-included').disabled=locked||!state;
  $('#dsh-launch-legacy').disabled=locked||!state?.dsh_launcher?.legacy_retry_available;
  $('#dsh-launch-execute').disabled=locked||dshLaunchDirty||!state?.dsh_launcher?.execution_available||!state?.dsh_launcher?.backup||Boolean(state?.dsh_launcher?.run);
  $('#dsh-launch-refresh').disabled=locked||!state;
  $('#dsh-launch-backup').disabled=locked||!plan||dshLaunchDirty||!plan.backup_root_count||!$('#dsh-launch-backup-consent').checked||Boolean(state?.dsh_launcher?.backup);
  $('#dsh-launch-health').disabled=locked||!plan||dshLaunchDirty||!plan.ports?.length;
  $('#dsh-launch-clear').disabled=locked||!plan;
}
function renderDshLauncher(){
  const launcher=state?.dsh_launcher||{},labels={AWAITING_SCRIPT:'Sin plan',AWAITING_BACKUP_AND_CONFIRMATION:'Pendiente de copia y confirmación',LAUNCHER_RUNNING:'Relanzador en ejecución',LAUNCHER_EXITED_RUNTIME_UNVERIFIED:'EXE terminó · runtime sin verificar',STALE_PLAN:'Plan desactualizado'};
  $('#dsh-launch-status').textContent=dshLaunchDirty?'Rutas cambiadas: inspecciona de nuevo':labels[launcher.status]||'Sin verificar';
  $('#dsh-launch-blockers').textContent=(launcher.blockers||[]).join('\n');
  $('#dsh-launch-plan').textContent=launcher.plan?JSON.stringify(launcher.plan,null,2):'Sin plan. Usa el relanzador incluido o selecciona el EXE verificado.';
  $('#dsh-launch-discovery').textContent=launcher.discovery?.configured?'Configuración local leída: '+JSON.stringify(launcher.discovery.configured):launcher.discovery?.missing_config_note||'La lectura local se realiza sólo cuando la solicitas.';
  $('#dsh-launch-observations').textContent=launcher.plan?JSON.stringify({backup:launcher.backup,run:launcher.run,health:launcher.health,events:launcher.events},null,2):'';
  const connection=dshConnectionStatus(),verified=connection.status==='CONNECTED'&&connection.live_connection===true&&connection.identity_verified===true;
  $('#dsh-launch-integration').textContent='Relanzamiento: '+(launcher.run?'EXE '+launcher.run.status+'; no demuestra salud DSH':'no ejecutado por esta app')+'. Enlace addon: '+(verified?'conexión de lectura verificada':'no verificado')+'. Paquete Cordis: '+(state?.cordis_addon?.status==='ready'?'preparado, no prueba instalación':'sin paquete vigente')+'. Importación del equipo: no verificada. Preservación del historial tras el EXE: no verificada.';
}
$('#dsh-launch-form').oninput=()=>{dshLaunchRevision++;dshLaunchDirty=true;$('#dsh-launch-backup-consent').checked=false;renderDshLauncher();updateDshLauncherControls();updateHarnessControls();};
$('#dsh-launch-backup-consent').onchange=()=>updateDshLauncherControls();
$('#dsh-launch-form').onsubmit=async event=>{
  event.preventDefault();
  const revision=dshLaunchRevision;
  const raw=$('#dsh-launch-ports').value.trim(),parts=raw?raw.split(',').map(x=>x.trim()):[];
  if(parts.some(x=>!/^\d{4,5}$/.test(x))){message('Indica puertos numéricos separados por coma.','error');return;}
  const ok=await action('dsh-launch-inspect',{operation:$('#dsh-launch-operation').value,legacy_stop:$('#dsh-launch-legacy').checked,script_path:$('#dsh-launch-script').value.trim(),exe_path:$('#dsh-launch-exe').value.trim(),ports:parts.map(Number),backup_paths:$('#dsh-launch-roots').value.split('\n').map(x=>x.trim()).filter(Boolean)},'Inspección terminada. Revisa los bloqueos y el hash; no se ha ejecutado DSH.');
  if(ok){dshLaunchDirty=revision!==dshLaunchRevision;$('#dsh-launch-backup-consent').checked=false;renderDshLauncher();updateDshLauncherControls();}
};
$('#dsh-launch-health').onclick=()=>action('dsh-launch-health',{plan_sha256:state?.dsh_launcher?.plan?.plan_sha256},'Puertos comprobados. Escucha TCP no verifica identidad DSH.');
$('#dsh-launch-backup').onclick=()=>action('dsh-launch-backup',{plan_sha256:state?.dsh_launcher?.plan?.plan_sha256,backup_confirmed:$('#dsh-launch-backup-consent').checked},'Copia local verificada por hashes. La consistencia de bases de datos y la cobertura de otras rutas siguen sin verificar.');
$('#dsh-launch-clear').onclick=async()=>{if(await action('dsh-launch-clear',{},'Plan descartado. Las copias locales existentes se conservan.')){dshLaunchDirty=false;$('#dsh-launch-backup-consent').checked=false;renderDshLauncher();updateDshLauncherControls();}};

$('#dsh-launch-execute').onclick=()=>{
  const launcher=state?.dsh_launcher,plan=launcher?.plan;if(!plan||busy||dshLaunchDirty||launcher.run)return;
  const approved=window.confirm('Vas a ejecutar este EXE local:\n'+plan.executable_path+'\nSHA-256: '+plan.binary.sha256+'\nArgumentos: '+plan.arguments.join(' ')+'\nPlan: '+plan.plan_sha256+'\n\nOperación: '+plan.operation+'. Puede iniciar DSH o, si eliges restart, detenerlo e interrumpir trabajos. Reiniciar pierde --patch previo y limpia NODE_OPTIONS/NODE_PATH. El cierre legacy puede perder estado en memoria. Se revisó la fuente 1.1.1, pero no tu runtime: no se garantiza preservar datos, configuración efectiva o historial. La copia sólo cubre las rutas revisadas y no asegura consistencia de bases de datos. No instala ni integra el paquete.\n\n¿Autorizas esta operación exacta?');
  if(approved)action('dsh-launch-execute',{plan_sha256:plan.plan_sha256,execute_confirmed:true,interruption_acknowledged:true,preservation_unverified_acknowledged:true,legacy_stop_confirmed:plan.legacy_stop_requested===true},'Solicitud registrada. Revisa el resultado del EXE y después verifica el runtime y los perfiles.');
};
$('#dsh-launch-refresh').onclick=()=>run('Consultando estado local…',async()=>{const response=await fetch('/api/state',{credentials:'same-origin'});if(!response.ok)throw new Error('No se pudo leer el estado.');state=await response.json();},'Estado local actualizado; un EXE finalizado no demuestra integración.');

async function discoverDshLauncher(useIncluded){
  const revision=dshLaunchRevision;
  if(await action('dsh-launch-discover',{},'Configuración del relanzador leída sin ejecutarlo.')){
    if(revision!==dshLaunchRevision)return;
    const discovery=state?.dsh_launcher?.discovery,config=discovery?.configured;
    if(config){$('#dsh-launch-ports').value=String(config.port);$('#dsh-launch-roots').value=[config.home,discovery.config_path].filter(Boolean).join('\n');}
    if(useIncluded&&discovery?.included_binary_verified)$('#dsh-launch-exe').value=discovery.included_executable;
    else if(useIncluded)message('No se encontró el relanzador incluido con el hash esperado.','error');
    dshLaunchRevision++;dshLaunchDirty=true;$('#dsh-launch-backup-consent').checked=false;renderDshLauncher();updateDshLauncherControls();
  }
}
$('#dsh-launch-discover').onclick=()=>discoverDshLauncher(false);
$('#dsh-launch-use-included').onclick=()=>discoverDshLauncher(true);

// SkillHub selection is a local draft. Only the reviewed CAS plan writes assignments.
let capTab='search',capIdentity=null,capPlan=null,capPlanIdentity=null,capLibraryOffset=0,capReferenceHash=null;
const capSelected=new Map(),capTargetAgents=new Set(),capTargetTeams=new Set();
function capState(){return state?.capability_library||{};}
function capContextIdentity(){return JSON.stringify([state?.organization?.id,state?.organization?.state_version,state?.config_version,state?.generation_stale,state?.project?.id,agents().map(a=>a.id)]);}
function capSubteams(){return [...new Map([...(state?.organization?.functional_subteams||[]),...(state?.subteams||[])].map(team=>[team.id,team])).values()];}
function capTargets(){const mode=$('#cap-target-mode').value;return {mode,agent_ids:mode==='selected'?[...capTargetAgents]:[],subteam_ids:mode==='subteams'?[...capTargetTeams]:[]};}
function capTargetRows(){const target=capTargets();if(target.mode==='all')return agents();if(target.mode==='selected')return agents().filter(a=>capTargetAgents.has(a.id));const ids=new Set(capSubteams().filter(t=>capTargetTeams.has(t.id)).flatMap(t=>t.member_ids||[]));return agents().filter(a=>ids.has(a.id));}
function capDropPlan(note=''){capPlan=null;capPlanIdentity=null;$('#cap-plan-review').hidden=true;if(note)$('#cap-status').textContent=note;updateSkillHubControls();}
function capChoose(item,checked,origin='library'){const key=origin+':'+item.id;if(checked)capSelected.set(key,{origin,item});else capSelected.delete(key);capDropPlan('La selección cambió. Revisa un nuevo plan antes de añadir.');renderSkillHub();}
function capChoice(item,origin='library'){const label=node('label',undefined,'check'),check=node('input');check.type='checkbox';check.checked=capSelected.has(origin+':'+item.id);check.dataset.capSelection='true';check.dataset.capKey=origin+':'+item.id;check.onchange=()=>capChoose(item,check.checked,origin);label.append(check,node('span','Añadir al equipo'));return label;}
function capShowTab(tab){capTab=tab;$$('[data-cap-tab]').forEach(b=>{const current=b.dataset.capTab===tab;b.setAttribute('aria-selected',String(current));b.tabIndex=current?0:-1;});$('#plugin-shop').hidden=tab!=='search';['suggested','library','assignments'].forEach(name=>$('#cap-'+name).hidden=tab!==name);$('#cap-evidence').hidden=tab!=='evidence';renderSkillHub();}
function setupSkillHub(){const section=$('#habilidades'),shop=$('#plugin-shop'),evidence=$('#cap-evidence');evidence.hidden=true;while(shop.nextElementSibling&&shop.nextElementSibling!==evidence)evidence.append(shop.nextElementSibling);$$('[data-cap-tab]').forEach(button=>{button.onclick=()=>capShowTab(button.dataset.capTab);button.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=$$('[data-cap-tab]'),index=tabs.indexOf(button),next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();capShowTab(tabs[next].dataset.capTab);};});}
function renderCapTargets(){const mode=$('#cap-target-mode').value,box=$('#cap-target-options');box.hidden=mode==='all';box.replaceChildren();const rows=mode==='selected'?agents():capSubteams(),selection=mode==='selected'?capTargetAgents:capTargetTeams;rows.forEach(row=>{const label=node('label',undefined,'check'),check=node('input');check.type='checkbox';check.checked=selection.has(row.id);check.dataset.capTarget='true';check.onchange=()=>{check.checked?selection.add(row.id):selection.delete(row.id);capDropPlan('Destinatarios modificados. Revisa un nuevo plan.');renderSkillHub();};label.append(check,node('span',mode==='selected'?(row.display_name||row.title)+' · '+(row.role||row.department||''):(row.name+' · '+(row.member_ids||[]).length+' miembros')));box.append(label);});if(mode!=='all'&&!rows.length)box.append(node('p','No hay '+(mode==='selected'?'perfiles':'subequipos')+' disponibles.','helper'));const chosen=capTargetRows(),roles=[...new Set(chosen.map(a=>a.role||a.title))];$('#cap-target-summary').textContent=chosen.length+' de '+agents().length+' perfiles · '+roles.length+' roles'+(chosen.length?' · '+roles.slice(0,4).join(', '):' · Selecciona destinatarios');}
function capCard(item,selectable=true,origin='library'){const card=node('article'),title=item.name||item.title||item.id;card.append(node('h4',title),node('span',item.skill_type||item.kind||item.type||item.category||'Capacidad','tag'),node('span',item.runtime_verified===true?'Verificación registrada':'Runtime sin verificar','tag'),node('p',item.description||'Sin descripción.'));if(item.content){const detail=node('details');detail.append(node('summary','Instrucciones guardadas'),node('pre',item.content));card.append(detail);}if(item.reason||item.rationale)card.append(node('p',item.reason||item.rationale,'helper'));if(item.tool_needs?.length)card.append(node('p','Herramientas declaradas, sin acceso concedido: '+item.tool_needs.join(', '),'helper'));if(item.provenance?.type)card.append(node('p','Fuente: '+item.provenance.type,'helper'));if(item.source_evidence||item.provenance){const detail=node('details');detail.append(node('summary','Origen y trazabilidad'),node('pre',JSON.stringify(item.source_evidence||item.provenance,null,2)));card.append(detail);}if(selectable)card.append(capChoice(item,origin));if(origin==='library'&&item.content){const edit=node('button','Editar copia local','textbutton');edit.type='button';edit.onclick=()=>{capShowTab('library');$('#cap-manual-form').closest('details').open=true;$('#cap-manual-id').value=item.id;$('#cap-manual-name').value=item.name||'';$('#cap-manual-description').value=item.description||'';$('#cap-manual-instructions').value=item.content||'';$('#cap-manual-references').value=(item.references||[]).map(r=>typeof r==='string'?r:r.url).filter(Boolean).join('\n');$('#cap-manual-name').focus();};card.append(edit);}return card;}
function renderSkillHub(){if(!state||!$('#capability-hub'))return;const identity=capContextIdentity();if(capIdentity!==null&&capIdentity!==identity){capSelected.clear();capTargetAgents.clear();capTargetTeams.clear();capDropPlan('Cambió la organización o su fuente. Selección y plan descartados; revisa el estado actual.');}capIdentity=identity;renderCapTargets();$('#cap-selection-count').textContent=capSelected.size+' capacidades seleccionadas para '+capTargetRows().length+' perfiles';const data=capState(),page=data.page||{};$('#cap-library-count').textContent=(data.status?.item_count??page.total??0)+' capacidades guardadas'+(data.saved_revision_differs?' · biblioteca posterior a la versión del proyecto':'');const list=$('#cap-library-results');list.replaceChildren();(page.items||page.results||[]).forEach(item=>list.append(capCard(item)));if(!list.children.length)list.append(node('p','Todavía no hay resultados guardados. Busca en tu biblioteca o crea una skill manual.','helper'));$('#cap-library-page').textContent=(page.total||0)?((page.offset||0)+1)+'–'+Math.min((page.offset||0)+(page.items||page.results||[]).length,page.total)+' de '+page.total:'Sin resultados';const assignmentBox=$('#cap-assignment-results');assignmentBox.replaceChildren();(data.assignment_page?.items||[]).forEach(assignment=>{const card=node('article');card.append(node('h4',assignment.name||assignment.item_id||assignment.capability_id||assignment.id),node('p',agents().find(a=>a.id===assignment.agent_id)?.display_name||assignment.agent_id||'Equipo'),node('p',assignment.active?'Instrucciones activadas localmente · ejecución sin verificar':'Referencia asignada · instrucciones inactivas','helper'));assignmentBox.append(card);});if(!assignmentBox.children.length)assignmentBox.append(node('p','No hay asignaciones en el ADN actual.','helper'));const assignmentPage=data.assignment_page||{};$('#cap-assignments-page').textContent=(assignmentPage.offset||0)+' / '+(assignmentPage.total||0)+' asignaciones';const recommendations=$('#cap-suggested-results');recommendations.replaceChildren();(data.recommendations?.items||[]).forEach(item=>recommendations.append(capCard({...item,id:item.item_id,reason:'Coincidencia local: '+(item.matched_evidence_terms||[]).join(', ')})));if(!recommendations.children.length)recommendations.append(node('p','Calcula propuestas a partir de las capacidades guardadas y las necesidades declaradas.','helper'));renderCapabilityAudit();renderCapabilityReference();if(capPlan){$('#cap-plan-review').hidden=false;$('#cap-plan-json').textContent=JSON.stringify(capPlan,null,2);const planned=capPlan.preview?.assignment_preview||capPlan.preview||{};$('#cap-plan-summary').textContent=capSelected.size+' capacidades · '+(planned.agent_ids?.length||0)+' perfiles · '+(planned.changed_count||0)+' cambios · '+(planned.unchanged_count||0)+' asignaciones sin cambios. Acción: '+(planned.action||'assign');$('#cap-apply').textContent=planned.action==='activate'?'Activar instrucciones revisadas':planned.action==='deactivate'?'Desactivar instrucciones revisadas':planned.action==='unassign'?'Retirar asignaciones revisadas':'Añadir seleccionadas al equipo';const impact=$('#cap-plan-impact');impact.replaceChildren();const ul=node('ul',undefined,'cap-impact-list');capTargetRows().forEach(a=>ul.append(node('li',(a.display_name||a.title)+' · '+(a.role||a.department||'')+' · '+capSelected.size+' capacidades propuestas')));impact.append(ul);}updateSkillHubControls();}
function updateSkillHubControls(){if(!$('#cap-preview'))return;const locked=busy||generationOperation||generationActive()||!state,unavailable=locked||!state?.organization||state?.generation_stale===true||configDirty;$('#cap-preview').disabled=unavailable||!capSelected.size||!capTargetRows().length;$('#cap-apply').disabled=unavailable||!capPlan||capPlanIdentity!==capContextIdentity();$('#cap-clear').disabled=locked||!capSelected.size;$('#cap-save-selection').disabled=locked||![...capSelected.values()].some(v=>v.origin!=='library');$('#cap-plan-discard').disabled=locked||!capPlan;$('#cap-target-mode').disabled=locked;$$('[data-cap-selection],[data-cap-target]').forEach(c=>{c.disabled=locked;if(c.dataset.capKey)c.checked=capSelected.has(c.dataset.capKey);});$('#cap-suggest').disabled=unavailable||!capTargetRows().length;const page=capState().page||{};$('#cap-library-prev').disabled=locked||!(page.offset>0);$('#cap-library-next').disabled=locked||page.next_offset==null;const search=state?.plugin_shop?.search||{};$('#cap-catalog-prev').disabled=locked||!(search.offset>0);$('#cap-catalog-next').disabled=locked||search.next_offset==null;$('#cap-catalog-page').textContent=(search.total||0)?((search.offset||0)+1)+'–'+((search.offset||0)+(search.results||[]).length)+' de '+search.total:'Sin búsqueda';const assigned=capState().assignment_page||{};$('#cap-assignments-prev').disabled=locked||!(assigned.offset>0);$('#cap-assignments-next').disabled=locked||assigned.next_offset==null;$('#cap-assignment-action').disabled=locked;const audit=capState().audit_page||{};$('#cap-audit-prev').disabled=locked||!(audit.offset>0);$('#cap-audit-next').disabled=locked||audit.next_offset==null;}

setupSkillHub();

function capIdempotency(){return crypto.randomUUID?crypto.randomUUID():Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);}
function capCatalogSearch(offset=0){return action('plugin-shop-search',{query:$('#plugin-shop-query').value.trim(),limit:100,offset,category:$('#plugin-shop-category').value||null,sort:$('#plugin-shop-sort').value});}
function capLibrarySearch(offset=0){return action('capability-search',{query:$('#cap-library-query').value.trim(),offset});}
$('#cap-target-mode').onchange=()=>{capDropPlan('Destinatarios modificados. Revisa un nuevo plan.');renderSkillHub();};
$('#cap-assignment-action').onchange=()=>capDropPlan('Acción modificada. Revisa un nuevo plan.');
$('#cap-clear').onclick=()=>{capSelected.clear();capDropPlan('Selección descartada. No se cambió la biblioteca ni el ADN.');renderPluginShop();renderSkillHub();};
$('#cap-plan-discard').onclick=async()=>{if(await action('capability-discard',{},'Plan descartado. No se aplicó ningún cambio.')){capDropPlan();renderSkillHub();}};
$('#cap-preview').onclick=async()=>{if(busy)return;const current=capContextIdentity(),selection=[...capSelected.values()],body={expected_state_version:state.organization.state_version||1,expected_revision:capState().status.revision,item_ids:selection.filter(v=>v.origin==='library').map(v=>v.item.id),candidate_ids:selection.filter(v=>v.origin==='catalog').map(v=>v.item.id),catalog_identity:pluginCatalogIdentity,reference_ids:selection.filter(v=>v.origin==='reference').map(v=>v.item.id),reference_hash:capState().reference?.source_hash,selection:capTargets(),assignment_action:$('#cap-assignment-action').value};capDropPlan();if(await action('capability-preview',body,'Plan de capacidades preparado. Revisa el impacto antes de añadir.')){if(current!==capContextIdentity())return;capPlan=capState().plan;capPlanIdentity=current;renderSkillHub();}};
$('#cap-apply').onclick=async()=>{if(busy)return;if(!capPlan||capPlanIdentity!==capContextIdentity())return;const plan=capPlan;const preview=plan.preview;const body={expected_state_version:state.organization.state_version||1,plan_id:plan.id,preview_hash:preview.preview_hash,idempotency_key:capIdempotency(),confirmed:true};if(await action('capability-apply',body,'Capacidades actualizadas en el diseño local. No se instalaron plugins ni se concedieron permisos.')){capSelected.clear();capDropPlan();renderPluginShop();renderSkillHub();}else{capDropPlan('El plan no se aplicó. Revisa el error completo y prepara un plan nuevo.');}};
$('#cap-library-search').onsubmit=e=>{e.preventDefault();capLibrarySearch(0);};
$('#cap-library-prev').onclick=()=>capLibrarySearch(Math.max(0,(capState().page?.offset||0)-50));$('#cap-library-next').onclick=()=>capLibrarySearch(capState().page.next_offset);
$('#cap-catalog-prev').onclick=()=>capCatalogSearch(Math.max(0,(state.plugin_shop.search?.offset||0)-100));$('#cap-catalog-next').onclick=()=>capCatalogSearch(state.plugin_shop.search.next_offset);
$('#cap-assignments-prev').onclick=()=>action('capability-assignments',{offset:Math.max(0,(capState().assignment_page?.offset||0)-50)});$('#cap-assignments-next').onclick=()=>action('capability-assignments',{offset:capState().assignment_page.next_offset});
$('#cap-suggest').onclick=()=>action('capability-recommend',{selection:capTargets(),expected_state_version:state.organization.state_version||1},'Sugerencias locales calculadas a partir de las referencias guardadas.');
$('#cap-manual-reset').onclick=()=>$('#cap-manual-form').reset();
$('#cap-manual-form').onsubmit=async e=>{e.preventDefault();const references=lines($('#cap-manual-references').value);for(const reference of references){try{const url=new URL(reference);if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash)throw new Error();}catch(_){message('Cada referencia debe ser una URL HTTPS sin credenciales, parámetros ni fragmentos.','error');return;}}const item={kind:$('#cap-manual-type').value,name:$('#cap-manual-name').value.trim(),description:$('#cap-manual-description').value.trim(),content:$('#cap-manual-instructions').value,provenance:{type:'user_authored',evidence:'Instrucciones redactadas y revisadas localmente. Referencias no consultadas: '+(references.join(' · ')||'ninguna')}};if(await action('capability-save',{item,expected_revision:capState().status.revision,idempotency_key:capIdempotency()},'Nueva versión guardada en la biblioteca. Usa su selección para revisar una asignación.')){$('#cap-manual-form').reset();capDropPlan('Biblioteca actualizada. Revisa un nuevo plan para asignar.');renderSkillHub();}};

let capAiPollTimer=null,capAiPolling=false,capAiReviewId=null,capAiEpoch=0;
function updateCapabilityRecommendationControls(){if(!$('#cap-ai-plan'))return;const job=state?.capability_recommendations?.job,locked=busy||generationOperation||generationActive()||!state,noDesign=locked||!state?.organization||state?.generation_stale||configDirty;$('#cap-ai-plan').disabled=noDesign||job?.status==='running';$('#cap-ai-baseline').disabled=noDesign||job?.status==='running';$('#cap-ai-confirm').disabled=locked||job?.status!=='awaiting_consent'||job?.stale||!$('#cap-ai-data').checked||!$('#cap-ai-budget').checked;$('#cap-ai-cancel').disabled=locked||!job||!['running','awaiting_consent'].includes(job.status);}
function renderCapabilityRecommendations(){const job=state?.capability_recommendations?.job,review=$('#cap-ai-review');if(!review)return;review.hidden=!job||job.status!=='awaiting_consent'||job.stale;$('#cap-ai-cancel').hidden=!job||!['running','awaiting_consent'].includes(job.status);if(capAiReviewId!==job?.job_id){capAiReviewId=job?.job_id;$('#cap-ai-data').checked=false;$('#cap-ai-budget').checked=false;}$('#cap-ai-consent').textContent=job?.consent?JSON.stringify(job.consent,null,2):'';$('#cap-ai-status').textContent=job?(job.stale?'Plan obsoleto. Prepara otra recomendación.':({running:'Consultando el modelo autorizado…',awaiting_consent:'Plan preparado; ninguna llamada enviada.',completed:job.mode==='deterministic'?'Propuesta local completada sin API.':'Recomendación completada.',failed:'La recomendación falló.',cancelled:'Recomendación cancelada.'}[job.status]||job.status))+(job.error?' '+job.error:''):'Sin llamadas de recomendación.';const box=$('#cap-ai-results');box.replaceChildren();if(!job?.stale&&job?.result){const pins=new Map((job.result.candidate_pins||[]).map(item=>[item.id,item]));(job.result.agents||[]).forEach(row=>{box.append(node('h4',agents().find(a=>a.id===row.agent_id)?.display_name||row.agent_id,'cap-group-title'));(row.recommendations||[]).forEach(rec=>{const pin=pins.get(rec.candidate_id)||{id:rec.candidate_id,name:rec.candidate_id};const catalogPin=pin.provenance?.type==='catalog_snapshot';box.append(capCard({...pin,id:catalogPin?pin.provenance.source_id:pin.id,reason:rec.reason||rec.rationale||JSON.stringify(rec)},true,catalogPin?'catalog':'library'));});if(row.gaps?.length)box.append(node('p','Necesidades pendientes: '+row.gaps.map(g=>typeof g==='string'?g:JSON.stringify(g)).join('; '),'helper'));});}updateCapabilityRecommendationControls();if(job?.status==='running'&&!capAiPollTimer){capAiPollTimer=setTimeout(pollCapabilityRecommendations,1200);}else if(job?.status!=='running'&&capAiPollTimer){clearTimeout(capAiPollTimer);capAiPollTimer=null;}}
async function pollCapabilityRecommendations(){capAiPollTimer=null;if(capAiPolling)return;if(busy){capAiPollTimer=setTimeout(pollCapabilityRecommendations,1200);return;}capAiPolling=true;const epoch=capAiEpoch,jobId=state?.capability_recommendations?.job?.job_id;try{const response=await fetch('/api/state',{credentials:'same-origin'});if(!response.ok)throw new Error('HTTP '+response.status+' al consultar la recomendación.');const fresh=await response.json();if(epoch===capAiEpoch&&jobId===state?.capability_recommendations?.job?.job_id&&state){state.capability_recommendations=fresh.capability_recommendations;renderCapabilityRecommendations();}}catch(error){if(epoch===capAiEpoch&&state?.capability_recommendations?.job?.status==='running'){$('#cap-ai-status').textContent='No se pudo actualizar el estado: '+error.message;capAiPollTimer=setTimeout(pollCapabilityRecommendations,3000);}}finally{capAiPolling=false;}}
function capAiPrepare(actionName){if(busy)return;const selected=[...capSelected.values()],libraryIds=selected.filter(v=>v.origin==='library').map(v=>v.item.id),catalogIds=selected.filter(v=>v.origin==='catalog').map(v=>v.item.id);if(selected.some(v=>v.origin==='reference')){message('Para recomendar sobre una referencia, guárdala primero en la biblioteca con el botón Guardar sólo en biblioteca.','error');return;}capAiEpoch++;return action(actionName,{expected_state_version:state.organization.state_version||1,selection:capTargets(),idempotency_key:capIdempotency(),...(selected.length?{candidate_ids:libraryIds,catalog_candidate_ids:catalogIds,catalog_identity:pluginCatalogIdentity}:{} )},'Propuesta preparada. Revisa su contenido y presupuesto antes de autorizar cualquier llamada.');}
$('#cap-ai-plan').onclick=()=>capAiPrepare('capability-ai-plan');$('#cap-ai-baseline').onclick=()=>capAiPrepare('capability-ai-baseline');
$('#cap-ai-data').onchange=updateCapabilityRecommendationControls;$('#cap-ai-budget').onchange=updateCapabilityRecommendationControls;
$('#cap-ai-confirm').onclick=()=>{const job=state.capability_recommendations?.job;if(!job?.consent||!$('#cap-ai-data').checked||!$('#cap-ai-budget').checked)return;capAiEpoch++;return action('capability-ai-confirm',{job_id:job.job_id,approval_id:job.consent.approval_id,payload_sha256:job.consent.payload_sha256,confirmed:true,data_reviewed:true,budget_acknowledged:true},'Recomendación autorizada en curso. Puedes cancelarla; una llamada ya enviada puede facturarse.');};
$('#cap-ai-cancel').onclick=()=>{if(busy)return;capAiEpoch++;return action('capability-ai-cancel',{job_id:state.capability_recommendations?.job?.job_id},'Cancelación solicitada. Una llamada ya enviada puede tener coste.');};

function renderCapabilityReference(){const reference=capState().reference,hash=reference?.source_hash||null;if(capReferenceHash!==hash){for(const [key,value] of capSelected)if(value.origin==='reference')capSelected.delete(key);capReferenceHash=hash;capDropPlan();}$('#cap-reference-status').textContent=reference?((reference.source_kind==='research_snapshot'||reference.snapshot_metadata?.source_kind==='research_snapshot'||reference.snapshot_metadata?.type==='research_snapshot'||reference.item_proposals?.some(item=>item.provenance?.type==='research_snapshot'))?'Ficha de investigación previa (research_snapshot): ':'Referencia consultada: ')+reference.source_url+' · SHA-256 '+hash:'No se ha leído ninguna URL de referencia.';const box=$('#cap-reference-results');box.replaceChildren();(reference?.item_proposals||[]).forEach(item=>box.append(capCard(item,true,'reference')));$('#cap-reference-evidence').textContent=reference?JSON.stringify({evidence:reference.evidence,coverage:reference.coverage,snapshot_metadata:reference.snapshot_metadata,proposal_reviews:reference.proposal_reviews},null,2):'';}
$('#cap-reference-form').onsubmit=e=>{e.preventDefault();capDropPlan();return action('capability-source-read',{url:$('#cap-reference-url').value.trim(),item_kind:$('#cap-reference-kind').value},'Referencia leída. Revisa las propuestas y su evidencia antes de añadirlas.');};

$('#cap-save-selection').onclick=async()=>{if(busy)return;const selected=[...capSelected.values()],body={candidate_ids:selected.filter(v=>v.origin==='catalog').map(v=>v.item.id),catalog_identity:pluginCatalogIdentity,reference_ids:selected.filter(v=>v.origin==='reference').map(v=>v.item.id),reference_hash:capState().reference?.source_hash,expected_revision:capState().status.revision,idempotency_key:capIdempotency()};if(await action('capability-import',body,'Selección guardada únicamente en la biblioteca. No se asignó a ningún perfil.')){for(const [key,value] of capSelected)if(value.origin!=='library')capSelected.delete(key);(capState().last_import?.items||[]).forEach(item=>capSelected.set('library:'+item.id,{origin:'library',item}));capDropPlan();capShowTab('library');}};

let capDeploymentDirty=false;
function updateCapabilityDeploymentControls(){if(!$('#cap-deployment-prepare'))return;const deployment=capState().deployment,locked=busy||generationOperation||generationActive()||!state,unavailable=locked||!state?.organization||state.generation_stale||configDirty;$('#cap-deployment-prepare').disabled=unavailable;$('#cap-deployment-discard').disabled=locked||!deployment;$('#cap-deployment-download').setAttribute('aria-disabled',String(unavailable||!deployment||deployment.stale||capDeploymentDirty));}
function renderCapabilityDeployment(){const deployment=capState().deployment;$('#cap-deployment-status').textContent=!deployment?'Sin plan':deployment.stale||capDeploymentDirty?'Comparación desactualizada':'Pendiente de aplicar y verificar';$('#cap-deployment-review').hidden=!deployment||capDeploymentDirty;if(deployment){$('#cap-deployment-summary').textContent=(deployment.affected_member_ids||[]).length+' perfiles afectados · '+(deployment.assignment_changes||[]).length+' cambios de asignación · '+(deployment.changed_item_ids||[]).length+' capacidades modificadas · 0 agentes nuevos';$('#cap-deployment-details').textContent=JSON.stringify(deployment,null,2);$('#cap-deployment-readback').textContent='Esta conexión no aporta un readback verificado del hash SkillHub. El estado permanece pendiente aunque se descargue el delta.';}updateCapabilityDeploymentControls();}
$('#cap-deployment-file').onchange=()=>{capDeploymentDirty=true;renderCapabilityDeployment();};
$('#cap-deployment-form').onsubmit=async e=>{e.preventDefault();if(busy)return;const file=$('#cap-deployment-file').files?.[0];if(!file){message('Selecciona el manifiesto SkillHub base del equipo desplegado.','error');return;}if(file.size>2*1024*1024-4096){message('El manifiesto excede el máximo de 2 MB para esta revisión.','error');return;}let baseline;try{baseline=JSON.parse(await file.text());}catch(error){message('No se pudo leer el manifiesto JSON: '+error.message,'error');return;}if(await action('capability-deployment-plan',{baseline,expected_state_version:state.organization.state_version||1},'Actualización comparada. Revisa los hashes y perfiles afectados; el runtime sigue sin cambios.')){capDeploymentDirty=false;renderCapabilityDeployment();}};
$('#cap-deployment-discard').onclick=async()=>{if(await action('capability-deployment-discard',{},'Comparación descartada; no se publicó ninguna actualización.')){capDeploymentDirty=false;$('#cap-deployment-file').value='';renderCapabilityDeployment();}};

function renderCapabilityAudit(){const page=capState().audit_page||{},box=$('#cap-audit-results');box.replaceChildren();(page.items||[]).forEach(event=>{const detail=node('details');detail.append(node('summary','Revisión '+event.version+' · '+event.action+' · '+localDate(event.timestamp)),node('pre',JSON.stringify(event,null,2)));box.append(detail);});if(!box.children.length)box.append(node('p','Todavía no hay eventos de biblioteca.','helper'));$('#cap-audit-page').textContent=(page.offset||0)+' / '+(page.total||0)+' eventos';}
$('#cap-audit-prev').onclick=()=>action('capability-audit',{offset:Math.max(0,(capState().audit_page?.offset||0)-50)});$('#cap-audit-next').onclick=()=>action('capability-audit',{offset:capState().audit_page.next_offset});

// Resource suggestions retain their role mapping through review and application.
let resourceTimer=null,resourcePolling=false,resourceEpoch=0,resourceJobId=null,resourcePlanIdentity=null;
const resourceSelected=new Set();
function resourceState(){return state?.resource_workflows||{};}
function updateResourceControls(){if(!$('#resource-baseline'))return;const r=resourceState(),job=r.job,locked=busy||generationOperation||generationActive()||!state,unavailable=locked||!state?.organization||state?.generation_stale||configDirty,working=job?.status==='running';$('#resource-baseline').disabled=unavailable||working||!capState().reference||!capTargetRows().length;$('#resource-ai-plan').disabled=$('#resource-baseline').disabled;$('#resource-example').disabled=locked||working;$('#resource-confirm').disabled=unavailable||job?.status!=='awaiting_consent'||job?.stale||!$('#resource-data-consent').checked||!$('#resource-cost-consent').checked;$('#resource-cancel').disabled=locked||!['running','awaiting_consent'].includes(job?.status);$('#resource-preview').disabled=unavailable||job?.stale||!job?.result||!resourceSelected.size;$('#resource-apply').disabled=unavailable||!r.preview||job?.stale||resourcePlanIdentity!==resourceReviewIdentity();$('#resource-assignment-action').disabled=locked;$$('[data-resource-agent]').forEach(el=>el.disabled=locked);}
function resourceReviewIdentity(){return JSON.stringify([capContextIdentity(),resourceState().job?.job_id,[...resourceSelected].sort(),$('#resource-assignment-action').value]);}
function renderResourceWorkflows(){if(!$('#resource-results'))return;const r=resourceState(),job=r.job,box=$('#resource-results');if(resourceJobId!==job?.job_id){resourceJobId=job?.job_id;resourceSelected.clear();(job?.result?.agents||[]).forEach(row=>resourceSelected.add(row.agent_id));resourcePlanIdentity=null;$('#resource-data-consent').checked=false;$('#resource-cost-consent').checked=false;}$('#resource-status').textContent=job?(job.stale?'Resultado obsoleto. Prepara otro workflow.':({completed:job.result?.mode_notice||'Workflows preparados para revisar.',running:'Consultando el modelo autorizado…',awaiting_consent:'Solicitud preparada; todavía no se ha enviado.',cancelled:'Solicitud cancelada.',failed:'No se completó la solicitud.'}[job.status]||job.status))+(job.error?' '+job.error:''):'Lee primero una referencia o carga la ficha revisada del ejemplo.';$('#resource-consent-review').hidden=job?.status!=='awaiting_consent'||job?.stale;$('#resource-consent').textContent=job?.consent?JSON.stringify(job.consent,null,2):'';$('#resource-cancel').hidden=!['running','awaiting_consent'].includes(job?.status);box.replaceChildren();if(job?.result&&!job.stale){(job.result.agents||[]).forEach(row=>{const w=row.workflow,card=node('article',undefined,'resource-workflow'),label=node('label',undefined,'check'),check=node('input');check.type='checkbox';check.checked=resourceSelected.has(row.agent_id);check.dataset.resourceAgent=row.agent_id;check.onchange=()=>{check.checked?resourceSelected.add(row.agent_id):resourceSelected.delete(row.agent_id);resourcePlanIdentity=null;renderResourceWorkflows();};label.append(check,node('span','Incluir este workflow para '+(agents().find(a=>a.id===row.agent_id)?.display_name||row.agent_id)));card.append(label,node('h3',w.role||row.agent_id),node('p',w.objective));[['prerequisites','Requisitos previos'],['steps','Pasos condicionados'],['deliverables','Entregables'],['acceptance_tests','Pruebas de aceptación']].forEach(([key,title])=>{card.append(node('h4',title));const list=node('ol');(w[key]||[]).forEach(value=>list.append(node('li',value)));card.append(list);});card.append(node('p','Fuentes: '+(w.source_ids||[]).join(', '),'helper'));const details=node('details');details.append(node('summary','Versiones, límites, contrato y trazabilidad'),node('pre',JSON.stringify(w,null,2)));card.append(details);box.append(card);});}const planCurrent=r.preview&&resourcePlanIdentity===resourceReviewIdentity()&&!job?.stale;$('#resource-assignment-review').hidden=!planCurrent;$('#resource-assignment-plan').textContent=planCurrent?JSON.stringify(r.preview,null,2):'';updateResourceControls();if(job?.status==='running'&&!resourceTimer)resourceTimer=setTimeout(pollResourceWorkflows,1200);else if(job?.status!=='running'&&resourceTimer){clearTimeout(resourceTimer);resourceTimer=null;}}
async function pollResourceWorkflows(){resourceTimer=null;if(resourcePolling)return;if(busy){resourceTimer=setTimeout(pollResourceWorkflows,1200);return;}resourcePolling=true;const epoch=resourceEpoch,id=resourceJobId;try{const response=await fetch('/api/state',{credentials:'same-origin'});if(!response.ok)throw new Error('No se pudo actualizar el workflow.');const fresh=await response.json();if(epoch===resourceEpoch&&id===resourceJobId&&state){const previous=state.resource_workflows?.job?.status;state.resource_workflows=fresh.resource_workflows;if(previous==='running'&&fresh.resource_workflows?.job?.status==='completed'){resourceSelected.clear();(fresh.resource_workflows.job.result?.agents||[]).forEach(row=>resourceSelected.add(row.agent_id));}renderResourceWorkflows();}}catch(error){if(epoch===resourceEpoch&&state?.resource_workflows?.job?.status==='running'){$('#resource-status').textContent=error.message;resourceTimer=setTimeout(pollResourceWorkflows,3000);}}finally{resourcePolling=false;}}
function resourcePrepare(name){if(busy)return;resourceEpoch++;resourcePlanIdentity=null;return action(name,{expected_state_version:state.organization.state_version||1,selection:capTargets(),reference_hash:capState().reference?.source_hash,idempotency_key:capIdempotency()},'Workflows preparados para revisión. No se ha instalado ni ejecutado el recurso.');}
$('#resource-baseline').onclick=()=>resourcePrepare('resource-workflow-baseline');$('#resource-ai-plan').onclick=()=>resourcePrepare('resource-workflow-plan');$('#resource-example').onclick=()=>{resourceEpoch++;return action('resource-workflow-example',{},'Ficha de investigación previa cargada. El backend y su contrato permanecen sin verificar.');};$('#resource-data-consent').onchange=updateResourceControls;$('#resource-cost-consent').onchange=updateResourceControls;
$('#resource-confirm').onclick=()=>{const job=resourceState().job;if(busy||!job?.consent||!$('#resource-data-consent').checked||!$('#resource-cost-consent').checked)return;resourceEpoch++;return action('resource-workflow-confirm',{job_id:job.job_id,approval_id:job.consent.approval_id,payload_sha256:job.consent.payload_sha256,confirmed:true,data_reviewed:true,budget_acknowledged:true},'Solicitud exacta autorizada. Una llamada ya enviada puede facturarse.');};
$('#resource-cancel').onclick=()=>{resourceEpoch++;return action('resource-workflow-cancel',{job_id:resourceState().job?.job_id},'Cancelación solicitada. Las llamadas enviadas pueden tener coste.');};
$('#resource-assignment-action').onchange=()=>{resourcePlanIdentity=null;renderResourceWorkflows();};
$('#resource-preview').onclick=async()=>{if(busy)return;const identity=resourceReviewIdentity();if(await action('resource-workflow-preview',{job_id:resourceState().job.job_id,expected_state_version:state.organization.state_version||1,expected_revision:capState().status.revision,workflow_agent_ids:[...resourceSelected],action:$('#resource-assignment-action').value},'Impacto preparado con el workflow específico de cada perfil. Revisa antes de aplicar.')){if(identity===resourceReviewIdentity())resourcePlanIdentity=identity;renderResourceWorkflows();}};
$('#resource-apply').onclick=async()=>{if(busy||resourcePlanIdentity!==resourceReviewIdentity())return;const r=resourceState(),plan=r.preview;if(!plan)return;if(await action('resource-workflow-apply',{job_id:r.job.job_id,expected_state_version:state.organization.state_version||1,preview_hash:plan.preview_hash,idempotency_key:capIdempotency(),confirmed:true},'Workflows actualizados en el ADN local. La ejecución del recurso continúa pendiente de requisitos y autorización.')){resourcePlanIdentity=null;renderResourceWorkflows();}};

// GenTeam P1/M4 — sandbox con aprobacion en DOS pasos (solicitar -> aprobar -> ejecutar).
// Se declaran con `const` (no con `function`) para no alterar el contrato de funciones
// pineadas de qa_v7/dsh_baseline.json: el ejecutor del panel nunca decide, solo propone y
// muestra la decision del motor. La politica manda y la aprobacion es de un solo uso.
const sandboxView=()=>(state?.sandbox)||{available:false,reason:'Genera un diseno para abrir el sandbox del panel.',requests:[],executions:[],counts:{},policy:null,flow:{}};
const sandboxMemberLabel=id=>{const member=channelMembers().find(row=>row.member_id===id);return member?member.name+' ('+member.member_id+')':String(id||'');};
const sandboxBlockedLabel=value=>({human_approval_required:'requiere aprobacion humana',approval_consumed:'aprobacion consumida',approval_expired:'aprobacion caducada',policy_denied:'denegado por la politica',ready:'listo para ejecutar'})[value]||String(value||'');
const sandboxStatusLabel=value=>({completed:'completada',failed:'fallida',timeout:'agotada por timeout'})[value]||String(value||'');
const sandboxRequestRow=row=>{
  const card=node('article',undefined,'record sandbox-request');card.dataset.requestId=String(row.request_id||'');card.dataset.blocked=String(row.blocked_reason||'');
  card.append(node('strong','Solicitud '+String(row.request_id||'').slice(0,8)+' | '+sandboxMemberLabel(row.agent_id)+' | '+String(row.code_bytes||0)+' B | '+String(row.policy?.decision||'')));
  card.append(node('p','Puerta: '+String(row.policy?.gate||'(ninguna)')+' | estado: '+sandboxBlockedLabel(row.blocked_reason)+' | aprobada: '+(row.approved?'si ('+String(row.approver_role||'')+', '+localDate(row.approved_at)+')':'no')+' | consumida: '+(row.consumed_at?localDate(row.consumed_at):'no'),'helper'));
  card.append(node('p','scope_hash '+String(row.scope_hash||''),'helper'));
  card.append(node('p','Motivo de la politica: '+String(row.policy?.reason||''),'helper'));
  const code=node('pre',String(row.code_view||'')+(row.code_truncated?'\n… (vista truncada)':''),'sandbox-code');card.append(code);
  const actions=node('div',undefined,'actions');
  if(!row.approved&&row.executable){const approve=node('button','2 · Aprobar esta solicitud','secondary');approve.type='button';approve.onclick=()=>approveSandbox(row.request_id,row.scope_hash);actions.append(approve);}
  if(row.approved&&!row.consumed_at){const exec=node('button','3 · Ejecutar','primary');exec.type='button';exec.onclick=()=>execSandbox(row.request_id);actions.append(exec);}
  if(!row.executable)actions.append(node('span','La politica la deniega: no hay aprobacion posible','tag amber'));
  if(row.consumed_at)actions.append(node('span','Aprobacion consumida: crea una solicitud nueva','tag'));
  card.append(actions);return card;
};
const sandboxRunRow=run=>{
  const card=node('article',undefined,'record sandbox-run');
  card.append(node('strong','Ejecucion '+String(run.run_id||'').slice(0,8)+' | '+sandboxMemberLabel(run.agent_id)+' | '+sandboxStatusLabel(run.status)+' | exit '+String(run.exit_code)));
  card.append(node('p','Aprobacion: puerta '+String(run.policy?.gate||'')+' | '+String(run.policy?.decision||'')+' | approved='+String(run.policy?.approved)+' | scope_hash '+String(run.policy?.scope_hash||''),'helper'));
  card.append(node('p',run.artifact?('Artefacto firmado '+String(run.artifact.path||'')+' | sha256 '+String(run.artifact.sha256||'')):('Sin artefacto firmado: '+String(run.artifact_error||'')),'helper'));
  card.append(node('p','Evidencia '+(run.evidence_id?String(run.evidence_id):'(ninguna)')+' | entregado a '+sandboxMemberLabel(run.delivered_to)+' | timeout='+String(run.timed_out)+' | salida='+String(run.stdout_bytes)+' B','helper'));
  if(run.stdout)card.append(node('pre',String(run.stdout),'sandbox-output'));
  if(run.error)card.append(node('p',String(run.error),'helper'));
  return card;
};
const renderSandbox=()=>{
  if(!$('#sandbox-panel'))return;
  const view=sandboxView(),policy=view.policy||{},flow=view.flow||{},counts=view.counts||{};
  const select=$('#sandbox-agent'),previous=select.value;select.replaceChildren();
  channelMembers().forEach(member=>select.append(option(member.member_id,member.name+(member.role?' | '+member.role:''))));
  if(channelMembers().some(member=>member.member_id===previous))select.value=previous;
  $('#sandbox-count').textContent=String(counts.requests||0)+' solicitudes | '+String(counts.executed||0)+' ejecuciones';
  $('#sandbox-gates').textContent=view.available&&policy.gates?('Puertas de la politica '+String(policy.policy_id||'')+'@'+String(policy.policy_revision||'')+': '+policy.gates.map(row=>row.gate+'='+row.default_outcome).join(' · ')+' | red='+String(policy.network_allowed)+' | escritura='+String(policy.write_allowed)+' | autonomia='+String(policy.autonomy_ceiling)):String(view.reason||'Sin politica disponible: el sandbox no ejecuta nada.');
  $('#sandbox-policy-summary').textContent=view.available?('hash '+String(policy.policy_hash||'')+' | puertas='+String(policy.gates_total||0)+' | flujo='+String((flow.steps||[]).join(' → '))+' | aprobacion de un solo uso='+String(flow.single_use_approval)+' | caduca en '+String(flow.approval_ttl_seconds||0)+' s | deny by default='+String(flow.deny_by_default)):String(view.reason||'');
  $('#sandbox-isolation').textContent='Aislamiento del sistema operativo: '+String(view.os_isolation||'no declarado')+' (no es un sandbox del SO).';
  const requests=$('#sandbox-request-list'),runs=$('#sandbox-run-list');
  requests.replaceChildren();runs.replaceChildren();
  (view.requests||[]).forEach(row=>requests.append(sandboxRequestRow(row)));
  (view.executions||[]).forEach(run=>runs.append(sandboxRunRow(run)));
  $('#sandbox-empty-requests').hidden=Boolean((view.requests||[]).length);
  $('#sandbox-empty-runs').hidden=Boolean((view.executions||[]).length);
  const envelope=state?.sandbox_execution?state.sandbox_execution:(state?.sandbox_approval?state.sandbox_approval:state?.sandbox_request);
  const verdict=$('#sandbox-verdict');
  if(envelope){verdict.hidden=false;verdict.textContent=state?.sandbox_execution?('Ejecucion '+String(state.sandbox_execution.run_id||'').slice(0,8)+': '+sandboxStatusLabel(state.sandbox_execution.status)+', exit '+String(state.sandbox_execution.exit_code)+'. Artefacto '+(state.sandbox_execution.artifact?String(state.sandbox_execution.artifact.sha256||''):'(sin firma)')+', evidencia '+String(state.sandbox_execution.evidence_id||'(ninguna)')+'.'):(state?.sandbox_approval?('Aprobacion registrada para '+String(state.sandbox_approval.request_id||'').slice(0,8)+' ('+String(state.sandbox_approval.approver_role||'')+'); todavia no se ejecuto nada. La politica ya se consulto y la aprobacion es de un solo uso.'):('Solicitud '+String(state.sandbox_request.request_id||'').slice(0,8)+' preparada SIN ejecutar: decision '+String(state.sandbox_request.policy?.decision||'')+', puerta '+String(state.sandbox_request.policy?.gate||'(ninguna)')+', estado '+sandboxBlockedLabel(state.sandbox_request.blocked_reason)+'.'));}
  $('#sandbox-status').textContent=view.available?'Sandbox inerte hasta que solicites, apruebes y ejecutes. La politica se consulta en la solicitud y otra vez antes de ejecutar; la aprobacion se consume en el intento.':String(view.reason||'Sandbox no disponible.');
  updateSandboxControls();
};
const updateSandboxControls=()=>{
  if(!$('#sandbox-request'))return;
  const view=sandboxView(),noDesign=!state?.organization||state?.generation_stale===true,locked=busy||generationOperation||generationActive();
  $('#sandbox-request').disabled=locked||noDesign||!view.available;
  ['#sandbox-timeout','#sandbox-max-output','#sandbox-code','#sandbox-agent','#sandbox-approver-role'].forEach(id=>{const el=$(id);if(el)el.disabled=locked||noDesign;});
};
const sandboxRun=async(title,fn,good)=>{
  if(busy||generationOperation||generationActive())return false;
  const box=$('#sandbox-error');if(box){box.hidden=true;box.textContent='';}
  setBusy(true);message(title,'busy');
  try{await fn();render();message(good||'Solicitud registrada. Nada se ejecuto todavia.');return true;}
  catch(error){if(box){box.hidden=false;box.textContent=error.message;}try{const fresh=await fetch('/api/state',{credentials:'same-origin'});if(fresh.ok){state=await fresh.json();render();}}catch(_){}message(error.message,'error');return false;}
  finally{setBusy(false);}
};
const requestSandbox=()=>{
  const code=$('#sandbox-code').value;
  if(!code.trim()){message('Escribe el codigo explicito que quieres solicitar; el panel no interpreta mensajes.','error');return Promise.resolve(false);}
  return sandboxRun('Preparando solicitud de sandbox (sin ejecutar)…',()=>request('sandbox-request',{expected_state_version:state.organization.state_version||1,agent_id:$('#sandbox-agent').value,code,timeout_seconds:Number($('#sandbox-timeout').value),max_output_bytes:Number($('#sandbox-max-output').value)}),'Solicitud preparada SIN ejecutar. Revisa la puerta y apruebala explicitamente.');
};
const approveSandbox=(requestId,scopeHash)=>sandboxRun('Registrando aprobacion de un solo uso…',()=>request('sandbox-approve',{expected_state_version:state.organization.state_version||1,request_id:requestId,scope_hash:scopeHash,approver_role:$('#sandbox-approver-role').value.trim()||'operador-panel'}),'Aprobacion registrada: un solo uso, ligada al scope_hash. Todavia no se ejecuto nada.');
const execSandbox=requestId=>{
  if(!confirm('Ejecutar el codigo aprobado en el espacio aislado de ese miembro? La aprobacion se consumira pase lo que pase y el resultado se entregara al canal con su SHA-256.'))return Promise.resolve(false);
  return sandboxRun('Ejecutando en el sandbox (una sola vez)…',()=>request('sandbox-exec',{expected_state_version:state.organization.state_version||1,request_id:requestId}),'Ejecucion terminada: revisa estado, artefacto y evidencia. La aprobacion quedo consumida.');
};
$('#sandbox-request').onclick=()=>requestSandbox();
$('#sandbox-agent').onchange=()=>updateSandboxControls();

// The harness observes each boundary separately. A listener is never runtime proof.
let harnessPlanHash=null,harnessDirty=false,harnessTimer=null,harnessPolling=false,harnessEpoch=0;
function harnessInput(){return JSON.stringify(['#dsh-launch-script','#dsh-launch-exe','#dsh-launch-ports','#dsh-launch-roots','#harness-port','#harness-wait','#harness-expected'].map(id=>$(id).value));}
let harnessPreparedInput=null;
function updateHarnessControls(){if(!$('#harness-prepare'))return;const h=state?.dsh_harness||{},locked=busy||generationOperation||generationActive()||!state,waiting=h.status==='WAITING_RUNTIME';harnessDirty=Boolean(h.plan&&harnessPreparedInput!==harnessInput());$('#harness-prepare').disabled=locked||waiting;$('#harness-start').disabled=locked||harnessDirty||h.status!=='AWAITING_START_APPROVAL'||!$('#harness-start-consent').checked;$('#harness-check').disabled=locked;$('#harness-verify').disabled=locked||!h.live_connection;$('#harness-clear').disabled=locked||waiting||!h.plan;$('#harness-pair').disabled=locked||harnessDirty||!h.plan||!$('#harness-pair-consent').checked||!$('#harness-code').value.trim()||!$('#harness-port').value;}
function renderHarness(){if(!$('#harness-status'))return;const h=state?.dsh_harness||{},p=h.plan,connection=h.connection||{},readback=h.readback,launch=h.launcher||{},hash=p?.plan_sha256;if(hash!==harnessPlanHash){harnessPlanHash=hash;$('#harness-start-consent').checked=false;$('#harness-pair-consent').checked=false;}const verified=h.live_connection===true&&connection.identity_verified===true,box=$('#harness-lights');box.replaceChildren();const rows=[['App local',Boolean(state),'Responde el bridge de OrgDNA'],['Listener TCP',false,(launch.health||[]).some(x=>x.tcp_listening)?'Puerto abierto; identidad pendiente':'No observado'],['Relanzador',false,launch.run?launch.run.status+'; runtime pendiente':'No ejecutado'],['Bridge DSH',verified,verified?'Identidad autenticada, sólo lectura':'Sin emparejamiento verificado'],['Roster',verified&&h.status==='READ_ONLY_VERIFIED'&&readback?.double_readback_matches===true,readback?.double_readback_matches?(h.status==='READ_ONLY_VERIFIED'?'Dos lecturas coinciden':'Lectura anterior; verifica de nuevo'):'Sin doble lectura vigente'],['Hash esperado',verified&&h.status==='READ_ONLY_VERIFIED'&&readback?.expected_definition_matches===true,readback?.expected_definition_matches===true?(h.status==='READ_ONLY_VERIFIED'?'Definiciones coinciden':'Hash anterior; verifica de nuevo'):readback?.expected_definition_matches===false?'No coincide':'Sin hash esperado verificado'],['Hash SkillHub',false,'Readback no disponible']];rows.forEach(([title,ok,label])=>{const card=node('div',undefined,'harness-light');card.dataset.status=ok?'verified':'pending';card.append(node('strong',(ok?'● ':'○ ')+title),node('span',label,'helper'));box.append(card);});$('#harness-status').textContent=h.status||'Sin preparar';$('#harness-review').hidden=!p;$('#harness-plan').textContent=p?JSON.stringify(p,null,2):'';$('#harness-diagnostics').textContent=(h.diagnostics||[]).join('\n')+(h.status==='WAITING_RUNTIME'?'\nEsperando, máximo restante '+h.wait_remaining_seconds+' s.':'');$('#harness-evidence').textContent=JSON.stringify({connection,readback,launcher:launch.run,live_connection:h.live_connection,native_execution_verified:false},null,2);updateHarnessControls();if(h.status==='WAITING_RUNTIME'&&!harnessTimer)harnessTimer=setTimeout(pollHarness,1000);else if(h.status!=='WAITING_RUNTIME'&&harnessTimer){clearTimeout(harnessTimer);harnessTimer=null;}}
async function pollHarness(){harnessTimer=null;if(harnessPolling)return;if(busy||generationOperation||generationActive()){harnessTimer=setTimeout(pollHarness,1000);return;}harnessPolling=true;const epoch=harnessEpoch,hash=harnessPlanHash;try{const r=await fetch('/api/dsh-harness-check',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},credentials:'same-origin',body:'{}'}),fresh=await r.json();if(!r.ok)throw new Error(fresh.error||'No se pudo comprobar el inicio.');if(epoch===harnessEpoch&&hash===harnessPlanHash){state.dsh_harness=fresh.dsh_harness;state.dsh_launcher=fresh.dsh_launcher;state.dsh_connection=fresh.dsh_connection;renderHarness();renderDshLauncher();renderDshConnection();}}catch(error){if(epoch===harnessEpoch){$('#harness-diagnostics').textContent=error.message+' Usa Comprobar estado; no se repetirá el inicio.';}}finally{harnessPolling=false;}}
['#harness-port','#harness-wait','#harness-expected'].forEach(id=>$(id).oninput=()=>{$('#harness-start-consent').checked=false;$('#harness-pair-consent').checked=false;updateHarnessControls();});$('#harness-code').oninput=updateHarnessControls;$('#harness-start-consent').onchange=updateHarnessControls;$('#harness-pair-consent').onchange=updateHarnessControls;
$('#harness-prepare').onclick=async()=>{if(busy)return;const values=harnessInput(),ports=$('#dsh-launch-ports').value.trim().split(',').map(x=>x.trim()).filter(Boolean);if(ports.some(x=>!/^\d{4,5}$/.test(x))){message('Indica los puertos del relanzador separados por coma.','error');return;}harnessEpoch++;const body={operation:'reuse',script_path:$('#dsh-launch-script').value.trim(),exe_path:$('#dsh-launch-exe').value.trim(),ports:ports.map(Number),backup_paths:lines($('#dsh-launch-roots').value),wait_seconds:Number($('#harness-wait').value),...($('#harness-port').value?{bridge_port:Number($('#harness-port').value)}:{}),...($('#harness-expected').value.trim()?{expected_definition_sha256:$('#harness-expected').value.trim()}: {})};if(await action('dsh-harness-prepare',body,'Plan de conexión preparado. Revisa el respaldo, el inicio y el emparejamiento por separado.')){harnessPreparedInput=values;renderHarness();}};
$('#harness-start').onclick=()=>{if(busy||harnessDirty||!$('#harness-start-consent').checked)return;harnessEpoch++;return action('dsh-harness-start',{plan_sha256:harnessPlanHash,start_confirmed:true,backup_confirmed:true,execute_confirmed:true,interruption_acknowledged:true,preservation_unverified_acknowledged:true},'Inicio solicitado una sola vez. El estado del listener y el enlace autenticado se comprueban por separado.');};
$('#harness-check').onclick=()=>{harnessEpoch++;return action('dsh-harness-check',{},'Estado comprobado; no se ha iniciado ni reiniciado otro proceso.');};
$('#harness-verify').onclick=()=>{harnessEpoch++;return action('dsh-harness-verify',{},'Lecturas comprobadas. Revisa cada semáforo: esto no acredita ejecución de agentes.');};
$('#harness-clear').onclick=()=>{harnessEpoch++;return action('dsh-harness-clear',{},'Plan descartado. No se terminó el proceso DSH ni se revocó el emparejamiento separado.');};
$('#harness-pair-form').onsubmit=async e=>{e.preventDefault();if(busy||harnessDirty||!$('#harness-pair-consent').checked)return;harnessEpoch++;const code=$('#harness-code').value.trim();$('#harness-code').value='';await action('dsh-harness-pair',{plan_sha256:harnessPlanHash,bridge_port:Number($('#harness-port').value),pairing_code:code,pair_confirmed:true},'Emparejamiento solicitado y roster comprobado; consulta la evidencia y los límites.');$('#harness-pair-consent').checked=false;updateHarnessControls();};

setBusy(true);
navigate();
fetch('/api/state',{credentials:'same-origin'}).then(async r=>{const data=await r.json();if(!r.ok)throw new Error(data.error||'El motor no respondió.');state=data;render();navigate();message('Motor local listo. Ninguna API de proveedor se ha llamado al arrancar.');await refreshProjects(true);setBusy(false);}).catch(e=>{setBusy(false);message('No se pudo conectar con el motor local: '+e.message,'error');});
