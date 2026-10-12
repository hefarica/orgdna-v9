/** Native operator-only staging UI. Independent from the read-only paired app API. */
import { randomBytes, randomUUID } from 'node:crypto'
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { lstat, realpath } from 'node:fs/promises'
import { isAbsolute, dirname, resolve } from 'node:path'
import { readTeamFiles } from './live_bridge.mjs'
import { prepareNativeStagePlan, stageReviewedNativePlan, installNativeCaptainProfile, installNativeProfileScopes, inspectNativeCapacity } from './native_orchestration.mjs'
export const NATIVE_STAGE_PATH = '/api/orgdna-native-stage'
const REVIEW_MS = 120_000
const ACK = 'STAGE_ONLY_KEEP_NATIVE_EXECUTION_APPROVAL'
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/
const TERMINAL = new Set(['completed','partial','failed','cancelled','interrupted','skipped'])
const registrations = new WeakMap()
const requireValue=(condition,code)=>{if(!condition){const error=new Error(code);error.code=code;throw error}}
const clone=value=>JSON.parse(JSON.stringify(value))
const SAFE_ERRORS = new Set(['NATIVE_CAPABILITY_UNAVAILABLE','EXISTING_TEAM_PRESERVED','GUI_RUN_STATE_UNVERIFIED','CAPTAIN_NOT_IDLE','CAPTAIN_NOT_AVAILABLE','CAPACITY_LIMIT','CAPACITY_UNVERIFIED','REVIEW_EXPIRED_OR_USED','REVIEW_SUPERSEDED','REVIEW_HASH_MISMATCH','PROFILES_CHANGED','OWNER_GESTURE_REQUIRED','BUSY','INVALID_SELECTION'])

function versionsInstalled() {
  const require=createRequire(import.meta.url)
  return Object.fromEntries(['@deepseek-ai/dsh-tools','@deepseek-ai/dsh-client-connection','@deepseek-ai/dsh-agent','@deepseek-ai/dsh-subagent','dsh-agent-team-gui','@nanmicoder/dsh-agent-teams'].map(name=>{
    try{const pkg=JSON.parse(readFileSync(require.resolve(name+'/package.json'),'utf8'));return[name,pkg.name===name?pkg.version:null]}catch{return[name,null]}
  }))
}

/** Canonical coherent Teams source snapshot; identifiers remain definitions. */
export async function readStageDefinitions(service, squadId, signal) {
  requireValue(typeof service?.readDefinitionSnapshot==='function'&&typeof squadId==='string','NATIVE_CAPABILITY_UNAVAILABLE')
  const snapshot=await service.readDefinitionSnapshot(signal)
  requireValue(snapshot?.agents instanceof Map&&snapshot.squads instanceof Map,'NATIVE_CAPABILITY_UNAVAILABLE')
  const squad=snapshot.squads.get(squadId)
  requireValue(squad&&Array.isArray(squad.members)&&squad.members.length>0&&squad.members.length<=32,'INVALID_SELECTION')
  const memberIds=[...new Set(squad.members)].sort()
  requireValue(memberIds.length===squad.members.length&&memberIds.every(id=>UUID.test(id)),'INVALID_SELECTION')
  // Any automatic squad sharing these definitions would make the second engine ambiguous.
  const selected=new Set(memberIds)
  const related=[...snapshot.squads].filter(([,row])=>Array.isArray(row.members)&&row.members.some(id=>selected.has(id)))
  requireValue(related.every(([,row])=>row.activationMode==='manual'),'GUI_RUN_STATE_UNVERIFIED')
  return {format:'agent-team-gui/definitions',version:2,
    agents:memberIds.map(id=>{const row=snapshot.agents.get(id);requireValue(row&&typeof row==='object','INVALID_SELECTION');return {...clone(row),id}}),
    squads:related.sort(([a],[b])=>a.localeCompare(b)).map(([id,row])=>({...clone(row),id}))}
}

/** Bounded public history cannot establish idle when the 200-row cap is reached. */
export function assertGuiIdle(service) {
  requireValue(typeof service?.listRuns==='function','NATIVE_CAPABILITY_UNAVAILABLE')
  const runs=service.listRuns(undefined,200,false)
  requireValue(Array.isArray(runs)&&runs.length<200&&runs.every(row=>row&&TERMINAL.has(row.status)),'GUI_RUN_STATE_UNVERIFIED')
  return true
}

function nativeCaptain(ctx,id) {
  requireValue(UUID.test(id??'')&&typeof ctx.agents?.get==='function'&&typeof ctx.agents?.roots==='function','CAPTAIN_NOT_AVAILABLE')
  const captain=ctx.agents.get(id)
  requireValue(captain?.id===id&&ctx.agents.roots().some(root=>root.id===id)&&typeof captain.runMaintenance==='function','CAPTAIN_NOT_AVAILABLE')
  requireValue(captain.status==='idle','CAPTAIN_NOT_IDLE')
  return captain
}

/** Trusted dependencies come from addon composition, never from request/model arguments. */
export function createNativeStageController(ctx, {service,stateRoot,foldSubagentDescriptor,bindSession,readNativeCapacity,expected_organization_id,expected_member_ids,reviewMs=REVIEW_MS}) {
  let pending=null,busy=false,disposed=false,prepareRevision=0
  const lifetime = new AbortController()
  const applied=new Map()
  const ttl=Math.min(Math.max(reviewMs,1),REVIEW_MS)
  const existingCheck=async(captainId,teamId)=>{
    let snapshot
    try { snapshot=await readTeamFiles(stateRoot) } catch(error) {
      if(error?.code!=='ENOENT')throw error
      // A missing selected root means no team exists there. Native create owns directory creation.
      try { await lstat(stateRoot); throw new Error('Unsafe missing root') } catch(missing) { if(missing?.code!=='ENOENT')throw missing }
      requireValue(await realpath(dirname(stateRoot))===resolve(dirname(stateRoot)),'NATIVE_CAPABILITY_UNAVAILABLE')
      snapshot={teams:[]}
    }
    requireValue(!snapshot.teams.some(team=>team.id===teamId||team.captainSessionId===captainId||team.members.some(member=>member.id===captainId)),'EXISTING_TEAM_PRESERVED')
    return true
  }
  const source=(squadId,signal)=>readStageDefinitions(service,squadId,signal)
  const capacityCheck=plan=>{
    const capacity=typeof readNativeCapacity==='function'?readNativeCapacity():null
    requireValue(capacity?.status==='OBSERVED'&&Number.isInteger(capacity.max_members)&&capacity.max_members>=1,'CAPACITY_UNVERIFIED')
    const required=plan.member_count-1
    if(capacity.max_members<required){const error=new Error('CAPACITY_LIMIT');error.code='CAPACITY_LIMIT';error.details={max_members:capacity.max_members,required_teammates:required,total_members_including_captain:plan.member_count,config_changed:false};throw error}
    return {...capacity,required_teammates:required,total_members_including_captain:plan.member_count}
  }
  return {
    async operate(action,payload={},signal=AbortSignal.timeout(30_000)) {
      requireValue(!disposed,'NATIVE_CAPABILITY_UNAVAILABLE')
      signal=AbortSignal.any([signal,lifetime.signal])
      requireValue(!busy,'BUSY')
      if(action==='catalog') {
        const snapshot=await service.readDefinitionSnapshot(signal)
        requireValue(snapshot?.agents instanceof Map&&snapshot?.squads instanceof Map,'NATIVE_CAPABILITY_UNAVAILABLE')
        return {squads:[...snapshot.squads].filter(([,r])=>r.activationMode==='manual').map(([id,r])=>({id,name:r.name,members:r.members})),
          profiles:[...snapshot.agents].map(([id,r])=>({id,name:r.name,provider:r.provider,model:r.model})),
          captains:ctx.agents.roots().filter(a=>a.status==='idle'&&typeof a.runMaintenance==='function').map(a=>({session_id:a.id,provider:a.options?.provider,model:a.options?.model})),
          native_execution_approval_still_required:true}
      }
      if(action==='prepare') {
        const revision=++prepareRevision
        requireValue(payload&&typeof payload==='object'&&typeof payload.squad_id==='string','INVALID_SELECTION')
        requireValue(!expected_organization_id||payload.organization_id===expected_organization_id,'INVALID_SELECTION')
        const captain=nativeCaptain(ctx,payload.captain_session_id)
        requireValue(!applied.has(captain.id),'EXISTING_TEAM_PRESERVED')
        assertGuiIdle(service)
        const definitions=await source(payload.squad_id,signal)
        if(expected_member_ids){const actual=definitions.agents.map(a=>a.id).sort(),expected=[...expected_member_ids].sort();requireValue(JSON.stringify(actual)===JSON.stringify(expected),'INVALID_SELECTION')}
        const plan=prepareNativeStagePlan(definitions,{orchestration_backend:'agentteams_native',organization_id:payload.organization_id,
          captain_member_id:payload.captain_member_id,captain_session_id:captain.id,goal:payload.goal,tasks:payload.tasks})
        const native_capacity=capacityCheck(plan)
        await existingCheck(captain.id,plan.team_id)
        requireValue(captain.options?.provider===plan.captain_profile.provider&&captain.options?.model===plan.captain_profile.model,'INVALID_SELECTION')
        requireValue(!disposed&&revision===prepareRevision,'REVIEW_SUPERSEDED')
        const nonce=randomBytes(32).toString('base64url')
        pending={plan,squadId:payload.squad_id,nonce,expires:Date.now()+ttl,captain}
        return {status:'REVIEW_REQUIRED',native_capacity,plan:clone(plan),review_nonce:nonce,expires_at:pending.expires,
          consequences:['Create one native staged plan only if this captain has no existing team.','Bind full Teams prompts and reviewed scope-local tool restrictions.','Keep all members unspawned until a separate native user approval.'],
          approval_ack:ACK}
      }
      requireValue(action==='stage'&&payload.ack===ACK,'OWNER_GESTURE_REQUIRED')
      prepareRevision++
      const ticket=pending;pending=null // Every attempted approval consumes the one-use review.
      requireValue(ticket&&Date.now()<ticket.expires&&payload.review_nonce===ticket.nonce,'REVIEW_EXPIRED_OR_USED')
      requireValue(payload.plan_sha256===ticket.plan.plan_sha256,'REVIEW_HASH_MISMATCH')
      busy=true
      try {
        const captain=nativeCaptain(ctx,ticket.plan.captain_session_id)
        requireValue(captain===ticket.captain,'CAPTAIN_NOT_AVAILABLE')
        requireValue(!applied.has(captain.id),'EXISTING_TEAM_PRESERVED')
        return await captain.runMaintenance(async maintenanceSignal=>{
          const combined=AbortSignal.any([signal,maintenanceSignal])
          combined.throwIfAborted()
          const current=await source(ticket.squadId,combined)
          // Rebuild exactly the same source-dependent plan before applying scoped effects.
          const regenerated=prepareNativeStagePlan(current,{orchestration_backend:'agentteams_native',organization_id:ticket.plan.organization_id,
            captain_member_id:ticket.plan.captain_member_id,captain_session_id:captain.id,goal:ticket.plan.create.description,
            tasks:ticket.plan.create.plan.tasks.map(t=>({id:t.id,subject:t.subject,description:t.description,member_id:t.assignee==='captain'?ticket.plan.captain_member_id:ticket.plan.profiles.find(p=>p.alias===t.assignee)?.definition_id,dependencies:t.dependencies}))})
          requireValue(regenerated.plan_sha256===ticket.plan.plan_sha256,'PROFILES_CHANGED')
          assertGuiIdle(service);capacityCheck(ticket.plan);await existingCheck(captain.id,ticket.plan.team_id)
          requireValue(typeof ctx.tools?.execute==='function'&&ctx.tools.get('agent_teams_create',captain)&&ctx.tools.get('agent_teams_edit_plan',captain),'NATIVE_CAPABILITY_UNAVAILABLE')
          let childScopes,captainProfile,captainBinding
          try {
            childScopes=installNativeProfileScopes(ctx,ticket.plan,foldSubagentDescriptor,{owner_approved_sha256:ticket.plan.plan_sha256,...(bindSession?{bindSession}:{})})
            captainProfile=installNativeCaptainProfile(captain,ticket.plan,ticket.plan.plan_sha256)
            if(bindSession)captainBinding=bindSession(captain.id,ticket.plan.captain_member_id)
          } catch(error) {try{childScopes?.dispose()}finally{try{captainProfile?.dispose()}finally{captainBinding?.()}}throw error}
          // Retain bounded guards after an uncertain native result: a staged plan may already exist.
          applied.set(captain.id,{childScopes,captainProfile,captainBinding,plan_sha256:ticket.plan.plan_sha256})
          return stageReviewedNativePlan(ctx,ticket.plan,{owner_approved_sha256:ticket.plan.plan_sha256,
            readDefinitions:()=>source(ticket.squadId,combined),readNativeCapacity,assertNoActiveGuiRuns:()=>assertGuiIdle(service),assertNoExistingTeam:existingCheck,
            scope_hook_ready:childScopes.status==='LIFECYCLE_HOOK_READY',captain_profile_ready:captainProfile.status==='CAPTAIN_PROFILE_BOUND'},
            {agent:captain,callId:randomUUID(),signal:combined})
        })
      } finally {busy=false}
    },
    dispose(){disposed=true;prepareRevision++;lifetime.abort();pending=null;const errors=[];for(const {childScopes,captainProfile,captainBinding} of applied.values())for(const dispose of [()=>childScopes.dispose(),()=>captainProfile.dispose(),captainBinding])try{dispose?.()}catch(error){errors.push(error)}applied.clear();if(errors.length)throw new AggregateError(errors,'Native stage cleanup failed')},
  }
}

const PAGE=`<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>OrgDNA: preparar AgentTeams</title><body><h1>Preparar AgentTeams desde Teams</h1><p>Esta pantalla nativa prepara un plan nuevo únicamente si el capitán no pertenece a otro equipo. Conserva los perfiles de Teams. No reemplaza equipos ni inicia miembros. La ejecución requerirá otra aprobación en AgentTeams. Mantén el addon cargado mientras existan sus agentes.</p><button id="load">Consultar perfiles y capitanes disponibles</button><pre id="catalog"></pre><form id="form"><label>UUID de la organización <input id="org" required></label><br><label>UUID de squad Teams <input id="squad" required></label><br><label>UUID del perfil capitán <input id="profile" required></label><br><label>UUID de sesión capitán existente <input id="session" required></label><br><label>Objetivo <textarea id="goal" required></textarea></label><br><label>Tareas JSON: id, subject, member_id, dependencies <textarea id="tasks">[]</textarea></label><br><button>Preparar revisión</button></form><p>Revisa todos los perfiles, prompts, herramientas añadidas y tareas. Este permiso solo prepara el plan; no lo ejecuta.</p><pre id="review"></pre><label><input type="checkbox" id="ack">He revisado el plan y sus permisos. Autorizo únicamente prepararlo.</label><button id="stage" disabled>Autorizar preparación nativa</button><pre id="result" aria-live="polite"></pre><script nonce="__NONCE__">let ticket=null,epoch=0;const el=id=>document.getElementById(id);async function call(action,payload){const r=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,payload})});const v=await r.json();if(!r.ok)throw Error((v.error||'BLOCKED')+(v.details?' '+JSON.stringify(v.details):''));return v}el('load').onclick=async()=>{try{el('catalog').textContent=JSON.stringify(await call('catalog',{}),null,2)}catch(e){el('result').textContent=e.message}};function invalidate(){epoch++;ticket=null;el('stage').disabled=true;el('ack').checked=false;el('review').textContent='';}el('form').addEventListener('input',invalidate);el('form').addEventListener('change',invalidate);el('form').onsubmit=async e=>{e.preventDefault();const version=++epoch;ticket=null;el('stage').disabled=true;el('ack').checked=false;try{const prepared=await call('prepare',{organization_id:el('org').value.trim(),squad_id:el('squad').value.trim(),captain_member_id:el('profile').value.trim(),captain_session_id:el('session').value.trim(),goal:el('goal').value,tasks:JSON.parse(el('tasks').value)});if(version!==epoch)return;ticket=prepared;el('review').textContent=JSON.stringify({native_capacity:ticket.native_capacity,plan:ticket.plan},null,2);el('result').textContent='Revisión lista. Caduca en dos minutos.'}catch(e){if(version===epoch)el('result').textContent=e.message}};el('ack').onchange=()=>el('stage').disabled=!ticket||!el('ack').checked;el('stage').onclick=async()=>{const selected=ticket;epoch++;ticket=null;el('stage').disabled=true;el('ack').checked=false;if(!selected)return;try{const value=await call('stage',{review_nonce:selected.review_nonce,plan_sha256:selected.plan.plan_sha256,ack:'${ACK}'});el('result').textContent=JSON.stringify(value,null,2)}catch(e){el('result').textContent=e.message+'; revisa el estado nativo y no recrees automáticamente el equipo.'}};</script></body></html>`

export function createNativeStageFetchHandler(controller) {
  return async request=>{
    const headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff'}
    if(request.method==='GET') {
      const nonce=randomBytes(16).toString('base64url')
      return new Response(PAGE.replace('__NONCE__',nonce),{headers:{...headers,'Content-Type':'text/html; charset=utf-8','Content-Security-Policy':`default-src 'none'; script-src 'nonce-${nonce}'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'`}})
    }
    try {
      requireValue(request.method==='POST'&&request.headers.get('origin')===new URL(request.url).origin&&request.headers.get('content-type')==='application/json','OWNER_GESTURE_REQUIRED')
      const raw=await request.text();requireValue(raw.length<=256*1024,'INVALID_SELECTION')
      const data=JSON.parse(raw);requireValue(data&&typeof data==='object','INVALID_SELECTION')
      return Response.json(await controller.operate(data.action,data.payload,request.signal),{headers})
    } catch(error) {return Response.json({error:SAFE_ERRORS.has(error?.code)?error.code:'NATIVE_STAGE_BLOCKED',...(error?.code==='CAPACITY_LIMIT'?{details:error.details}:{}),models_started:null,execution_state:'UNVERIFIED_ON_ERROR',auto_approved:false,inspect_native_state:true},{status:409,headers})}
  }
}

export async function registerNativeStageUI(ctx,options={}) {
  if(options.enabled!==true)return {status:'DISABLED'}
  if(registrations.has(ctx))return registrations.get(ctx)
  const versions=versionsInstalled()
  const libraries=['@deepseek-ai/dsh-tools','@deepseek-ai/dsh-client-connection','@deepseek-ai/dsh-agent','@deepseek-ai/dsh-subagent']
  if(!libraries.every(name=>versions[name]==='0.2.0-rc.2')||versions['dsh-agent-team-gui']!=='1.3.0'||versions['@nanmicoder/dsh-agent-teams']!=='0.1.22')return {status:'UNAVAILABLE',reason:'Exact native staging package combination is not verified.'}
  const service=ctx.get?.('agentTeamGui'),connection=ctx.get?.('connection')
  if(typeof connection?.fetch?.register!=='function'||typeof service?.readDefinitionSnapshot!=='function'||typeof service?.listRuns!=='function'||typeof ctx.agents?.get!=='function'||typeof ctx.agents?.roots!=='function'||!isAbsolute(options.agentteams_state_root??''))return {status:'UNAVAILABLE',reason:'Native services, captain lookup, or explicit AgentTeams state directory missing.'}
  if(!UUID.test(options.expected_organization_id??'')||!Array.isArray(options.expected_member_ids)||!options.expected_member_ids.length||options.expected_member_ids.length>32||!options.expected_member_ids.every(id=>UUID.test(id)))return {status:'UNAVAILABLE',reason:'Trusted organization and exact existing profile roster are required.'}
  const agentTeamsPlugin=await import('@nanmicoder/dsh-agent-teams')
  const readNativeCapacity=()=>inspectNativeCapacity(ctx,agentTeamsPlugin)
  const {foldSubagentDescriptor}=await import('@deepseek-ai/dsh-subagent')
  if(typeof foldSubagentDescriptor!=='function')return {status:'UNAVAILABLE',reason:'Native child descriptor seam unavailable.'}
  const controller=createNativeStageController(ctx,{service,stateRoot:options.agentteams_state_root,foldSubagentDescriptor,bindSession:options.bindSession,readNativeCapacity,expected_organization_id:options.expected_organization_id,expected_member_ids:options.expected_member_ids})
  const unregister=connection.fetch.register({path:NATIVE_STAGE_PATH,methods:['GET','POST'],requestBody:'buffered',fetch:createNativeStageFetchHandler(controller)})
  let disposed=false
  const dispose=()=>{if(disposed)return;disposed=true;try{const pending=unregister();pending?.catch?.(()=>{})}finally{controller.dispose();registrations.delete(ctx)}}
  ctx.effect(()=>dispose)
  const result={status:'NATIVE_STAGE_UI_READY',native_stage_path:NATIVE_STAGE_PATH,creates_staged_plan_only:true,execution_approval_separate:true,dispose}
  registrations.set(ctx,result);return result
}
