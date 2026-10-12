/** Teams is the profile source. AgentTeams owns staging/execution. No second engine.
 * Source contracts: NanmiCoder tools.ts/members.ts; DSH agent/runtime-types.ts,
 * subagent/descriptor.ts and tools/index.ts, pinned in SOURCES.json.
 */
import { createHash, randomUUID } from 'node:crypto'
const clone = value => JSON.parse(JSON.stringify(value))
const sha = value => createHash('sha256').update(JSON.stringify(value)).digest('hex')
const requireValue = (condition, message) => { if (!condition) throw new Error(message) }
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/
export const NATIVE_MEMBER_TOOLS = ['agent_teams_claim_task','agent_teams_update_task','agent_teams_send_message','agent_teams_status']
export const NATIVE_CAPTAIN_TOOLS = ['agent_teams_create','agent_teams_edit_plan','agent_teams_status','agent_teams_create_task','agent_teams_reassign_task','agent_teams_send_message','agent_teams_amend_task']
export const NATIVE_MODEL_CONTROL_DENY = ['agent_teams_approve','agent_teams_resume']

export function assertReviewedPlan(plan, approvedHash) {
  requireValue(plan&&typeof plan==='object','Reviewed plan missing')
  const {plan_sha256,...body}=plan
  requireValue(typeof plan_sha256==='string'&&sha(body)===plan_sha256&&approvedHash===plan_sha256,'Exact immutable native plan must be approved out of band')
  return plan
}

/** Public Cordis registry/fiber metadata only; no private fields or mutations.
 * AgentTeams module must be the exact version-checked installed plugin shape. */
export function inspectNativeCapacity(ctx, agentTeamsPlugin) {
  const runtime=ctx.registry?.get?.(agentTeamsPlugin)
  const active=runtime?.fibers?[...runtime.fibers].filter(f=>f.state===2):[] // FiberState.ACTIVE in reviewed Cordis4.0.4/4.0.5-alpha.1
  if(active.length!==1 || !Number.isInteger(active[0].config?.maxMembers) || active[0].config.maxMembers<1) {
    return {status:'CAPACITY_UNVERIFIED',max_members:null,source:'public_Cordis_registry_active_fiber_config',config_changed:false}
  }
  return {status:'OBSERVED',max_members:active[0].config.maxMembers,
    member_max_depth:Number.isInteger(active[0].config.memberMaxDepth)?active[0].config.memberMaxDepth:null,
    source:'public_Cordis_registry_active_fiber_config',config_changed:false}
}

export function prepareNativeStagePlan(definitions, options) {
  requireValue(options?.orchestration_backend === 'agentteams_native', 'Select exactly one native orchestration backend first')
  requireValue(UUID.test(options.organization_id ?? '') && UUID.test(options.captain_session_id ?? ''), 'Verified organization and captain session identities required')
  requireValue(definitions?.format === 'agent-team-gui/definitions' && definitions.version === 2 && Array.isArray(definitions.agents), 'Teams definitions v2 snapshot required')
  const agents=definitions.agents
  requireValue(agents.length>=1 && agents.length<=32 && new Set(agents.map(a=>a.id)).size===agents.length && agents.every(a=>UUID.test(a.id)), 'Invalid existing profile roster')
  requireValue(agents.some(a=>a.id===options.captain_member_id), 'Captain must be ONE existing profile inside N')
  requireValue(definitions.squads.every(s=>s.activationMode==='manual'), 'Teams squads must be passive catalog entries in native mode; do not run both schedulers')
  const goal=options.goal
  requireValue(typeof goal==='string' && goal.trim() && goal.length<=6000,'A bounded reviewed goal is required')
  const profileHash=sha(definitions),teamId='orgdna-'+options.organization_id
  const captain=agents.find(a=>a.id===options.captain_member_id)
  const captainProfile={definition_id:captain.id,provider:captain.provider,model:captain.model,system_prompt:captain.systemPrompt,tool_scope:clone(captain.toolScope??{})}
  requireValue(!NATIVE_CAPTAIN_TOOLS.some(t=>captainProfile.tool_scope.deny?.includes(t)),'Captain manual deny blocks native orchestration; review instead of overriding it')
  if(captainProfile.tool_scope.allow){for(const t of NATIVE_CAPTAIN_TOOLS)if(!captainProfile.tool_scope.allow.includes(t))captainProfile.tool_scope.allow.push(t);requireValue(captainProfile.tool_scope.allow.length<=256,'Captain native scope exceeds 256 names')}
  const profiles=agents.filter(a=>a!==captain).map(a=>({definition_id:a.id,alias:'m-'+a.id.replaceAll('-',''),name:a.name,provider:a.provider,model:a.model,system_prompt:a.systemPrompt,tool_scope:clone(a.toolScope??{})}))
  for(const p of profiles) {
    requireValue(typeof p.system_prompt==='string' && p.system_prompt.trim(),'Every profile needs its own full prompt')
    requireValue(typeof p.provider==='string' && typeof p.model==='string','Provider/model must come from Teams')
    requireValue(!NATIVE_MEMBER_TOOLS.some(t=>p.tool_scope.deny?.includes(t)), 'A manual deny blocks native member bookkeeping; do not override it')
    if(p.tool_scope.allow) {
      for(const name of NATIVE_MEMBER_TOOLS) if(!p.tool_scope.allow.includes(name)) p.tool_scope.allow.push(name)
      requireValue(p.tool_scope.allow.length<=256,'Native member scope exceeds 256 names')
    }
  }
  const taskSpecs=options.tasks??[]
  requireValue(Array.isArray(taskSpecs)&&taskSpecs.length<=100,'Bounded task plan required')
  const aliases=new Map(profiles.map(p=>[p.definition_id,p.alias]))
  const tasks=taskSpecs.map(t=>{
    requireValue(t&&typeof t.id==='string'&&typeof t.subject==='string'&&aliases.has(t.member_id),'Inline tasks require existing teammate owners; native inline-plan does not accept captain tasks')
    return {id:t.id,subject:t.subject,description:t.description??'',assignee:aliases.get(t.member_id),dependencies:clone(t.dependencies??[])}
  })
  requireValue(new Set(tasks.map(t=>t.id)).size===tasks.length,'Duplicate task IDs')
  const byId=new Map(tasks.map(t=>[t.id,t])),seen=new Set(),visiting=new Set()
  const visit=id=>{if(seen.has(id))return;requireValue(!visiting.has(id),'Task dependency cycle');visiting.add(id);const t=byId.get(id);requireValue(t&&Array.isArray(t.dependencies),'Unknown dependency');for(const dep of t.dependencies)visit(dep);visiting.delete(id);seen.add(id)}
  for(const t of tasks)visit(t.id)
  const plan={protocol:'orgdna-native-stage/1',organization_id:options.organization_id,team_id:teamId,captain_session_id:options.captain_session_id,captain_member_id:captain.id,
    member_count:agents.length,new_definition_count:0,profile_snapshot_sha256:profileHash,profiles,captain_profile:captainProfile,
    create:{name:teamId,description:goal,approval:'required',plan:{members:profiles.map(p=>({name:p.alias,role:p.name,provider:p.provider,model:p.model})),tasks}},
    enrich:{operations:profiles.map(p=>({action:'update_member',member_name:p.alias,execution_prompt:p.system_prompt,provider:p.provider,model:p.model}))},
    requested_native_member_scopes:profiles.map(p=>({definition_id:p.definition_id,alias:p.alias,tool_scope:p.tool_scope})),
    starts_models:false,approves_team:false,changes_profile_files:false,requires_no_active_gui_runs:true,requires_native_scope_hook:true,
    model_control_deny:NATIVE_MODEL_CONTROL_DENY,execution_approval_surface:'native_AgentTeams_user_UI_only'}
  return {...plan,plan_sha256:sha(plan)}
}

/** Requires trusted adapter callbacks and an out-of-band owner-approved hash.
 * Never accept owner_approved_sha256 from model tool arguments. */
export async function stageReviewedNativePlan(ctx, plan, authority, execution) {
  plan=clone(assertReviewedPlan(plan,authority?.owner_approved_sha256))
  const {plan_sha256,...body}=plan
  requireValue(sha(body)===plan_sha256,'Plan changed after review')
  requireValue(authority?.owner_approved_sha256===plan_sha256,'Exact native plan must be approved out of band')
  requireValue(execution?.agent?.id===plan.captain_session_id,'Wrong native captain execution')
  requireValue(typeof authority.readDefinitions==='function' && typeof authority.assertNoActiveGuiRuns==='function' && typeof authority.assertNoExistingTeam==='function','Trusted live SSOT/no-active-runtime capability unavailable')
  requireValue(sha(await authority.readDefinitions())===plan.profile_snapshot_sha256,'Teams profiles changed after review')
  requireValue(await authority.assertNoActiveGuiRuns()===true,'Teams GUI workers are active or status is unverified')
  requireValue(await authority.assertNoExistingTeam(plan.captain_session_id,plan.team_id)===true,'Existing AgentTeams team must be reused; no replacement created')
  requireValue(authority.scope_hook_ready===true,'Scoped native permissions must be installed before staging')
  requireValue(authority.captain_profile_ready===true,'Captain DNA, route and scoped permissions must be verified before staging')
  const capacity=await authority.readNativeCapacity?.()
  requireValue(capacity?.status==='OBSERVED'&&Number.isInteger(capacity.max_members),'CAPACITY_UNVERIFIED: inspect active native plugin configuration')
  requireValue(capacity.max_members>=plan.member_count-1,'CAPACITY_LIMIT: existing native maxMembers is below N-1; no setting was changed')
  requireValue(typeof ctx.tools?.execute==='function' && ctx.tools.get('agent_teams_create',execution.agent) && ctx.tools.get('agent_teams_edit_plan',execution.agent),'Native staging tools unavailable in captain scope')
  const run=async(name,args)=>{
    execution.signal?.throwIfAborted()
    const response=await ctx.tools.execute({name,arguments:args,agent:execution.agent,callId:randomUUID(),rootCallId:execution.rootCallId??execution.callId,parent:execution.token,signal:execution.signal})
    if(response.isError) throw new Error('Native stage failed; inspect the existing staged plan, never recreate automatically')
    return response.value
  }
  const created=await run('agent_teams_create',plan.create)
  requireValue(created?.phase==='staged' && created.team_id===plan.team_id,'Unexpected native receipt; stop without approval or retry')
  try {
    const enriched=plan.profiles.length?await run('agent_teams_edit_plan',plan.enrich):{status:'staged'}
    requireValue(enriched?.status==='staged','Native plan is not staged; stop')
    return {status:'STAGED_AWAITING_NATIVE_USER_APPROVAL',team_id:plan.team_id,organization_id:plan.organization_id,profile_snapshot_sha256:plan.profile_snapshot_sha256,member_count:plan.member_count,models_started:false,auto_approved:false}
  } catch(error) {
    throw new Error('A native staged plan exists but full DNA enrichment failed. Keep it staged; repair that same plan and do not create another.',{cause:error})
  }
}

/** Bind the existing captain, with an exact route check and a scoped DNA section.
 * It never changes model selection, settings or providers to force a match. */
export function installNativeCaptainProfile(captain,plan,approvedHash) {
  plan=clone(assertReviewedPlan(plan,approvedHash))
  const profile=plan.captain_profile
  requireValue(captain?.id===plan.captain_session_id,'Existing captain session mismatch')
  requireValue(captain.options?.provider===profile.provider&&captain.options?.model===profile.model,'Captain model route differs from Teams; explicitly select the reviewed route first')
  requireValue(typeof captain.ctx?.systemPrompt?.section==='function'&&typeof captain.ctx?.tools?.restrict==='function'&&typeof captain.ctx.tools.guard==='function','Captain scoped prompt/tool APIs missing')
  const disposers=[]
  try {
    if(Object.keys(profile.tool_scope).length)disposers.push(captain.ctx.tools.restrict(clone(profile.tool_scope)))
    disposers.push(captain.ctx.tools.guard(exec=>{
      if(exec.agent!==captain)return 'Captain scope identity mismatch'
      if(NATIVE_MODEL_CONTROL_DENY.includes(exec.name))return 'Staging approval does not permit model-driven approve/resume; use the native owner UI'
      if(profile.tool_scope.deny?.includes(exec.name)||(profile.tool_scope.allow&&!profile.tool_scope.allow.includes(exec.name)))return 'Tool outside approved captain profile'
    }))
    disposers.push(captain.ctx.systemPrompt.section({name:'orgdna:captain:'+plan.organization_id,order:130,text:profile.system_prompt,interpolate:false}))
    let disposed=false
    const dispose=()=>{if(disposed)return;disposed=true;const errors=[];for(const fn of disposers.reverse()){try{fn()}catch(e){errors.push(e)}}if(errors.length)throw new AggregateError(errors,'Captain profile cleanup failed')}
    captain.ctx.effect(()=>dispose)
    return {status:'CAPTAIN_PROFILE_BOUND',definition_id:profile.definition_id,session_id:captain.id,route_verified:true,dispose}
  } catch(error){for(const fn of disposers.reverse()){try{fn()}catch{}}throw error}
}

/** Scope-local monotonic constraints, bound from model-hidden host descriptors.
 * Must be mounted BEFORE native user approval. Unknown APIs/identities fail closed.
 * Profiles and lifecycle bindings are supplied from the exact reviewed stage plan.
 */
export function installNativeProfileScopes(ctx, plan, foldSubagentDescriptor, options={}) {
  plan=clone(assertReviewedPlan(plan,options.owner_approved_sha256))
  requireValue(typeof ctx.on==='function' && typeof ctx.effect==='function' && typeof foldSubagentDescriptor==='function','Native serial lifecycle and descriptor API required')
  const profiles=new Map(plan.profiles.map(p=>[p.alias,p]))
  const installed=new WeakSet(),disposers=new Set()
  const bind=payload=>{
    // Only the audited serial event is accepted; legacy session-start is not used.
    if(!payload || !Object.hasOwn(payload,'source')) return
    const agent=payload.agent
    if(agent?.session?.header?.parentSession!==plan.captain_session_id)return
    requireValue(typeof agent?.session?.ownEvents==='function','Native ownEvents descriptor seam unavailable')
    const descriptor=foldSubagentDescriptor(agent.session.ownEvents())
    if(descriptor?.mode!=='continuable' || !descriptor.label?.startsWith('agent-teams:'+plan.team_id+':')) return
    requireValue(agent.session.header.parentSession===plan.captain_session_id,'AgentTeams child has wrong trusted parent')
    const alias=descriptor.label.slice(('agent-teams:'+plan.team_id+':').length),profile=profiles.get(alias)
    requireValue(profile,'AgentTeams alias absent from approved immutable roster')
    requireValue(descriptor.agentProvider===profile.provider && descriptor.agentModel===profile.model && typeof descriptor.persona==='string' && descriptor.persona.includes(profile.system_prompt.trim()),'Native descriptor does not preserve approved profile DNA/route')
    requireValue(typeof agent.ctx?.tools?.restrict==='function' && typeof agent.ctx.tools.guard==='function','Scope-local tool restrictions unavailable')
    if(installed.has(agent))return
    const own=[]
    try {
      if(Object.keys(profile.tool_scope).length)own.push(agent.ctx.tools.restrict(clone(profile.tool_scope)))
      // A scope-local guard also denies scope-local tools outside the profile.
      // It never force-allows or removes another policy/AgentTeams restriction.
      own.push(agent.ctx.tools.guard(exec=>{
        if(exec.agent!==agent)return 'Scoped Agent identity mismatch'
        const scope=profile.tool_scope
        if(scope.deny?.includes(exec.name) || (scope.allow && !scope.allow.includes(exec.name)))return 'Tool outside Teams profile scope'
      }))
      if(options.bindSession)own.push(options.bindSession(agent.id,profile.definition_id))
      let disposed=false
      const dispose=()=>{if(disposed)return;disposed=true;disposers.delete(dispose);installed.delete(agent);const errors=[];for(const fn of own.reverse()){try{fn?.()}catch(e){errors.push(e)}}if(errors.length)throw new AggregateError(errors,'Native scope cleanup failed')}
      agent.ctx.effect(()=>dispose)
      disposers.add(dispose);installed.add(agent)
    } catch(error){for(const dispose of own.reverse()){try{dispose?.()}catch{}}throw error}
  }
  const stop=ctx.on('agent/created',bind)
  // Stop AgentTeams work before unloading this permission adapter. No durable
  // profile/settings mutation is made; child disposal owns its scoped effects.
  let disposed=false
  const dispose=()=>{if(disposed)return;disposed=true;const errors=[];try{stop()}catch(e){errors.push(e)}for(const fn of [...disposers]){try{fn()}catch(e){errors.push(e)}}if(errors.length)throw new AggregateError(errors,'Native scope unload failed')}
  ctx.effect(()=>dispose)
  return {status:'LIFECYCLE_HOOK_READY',member_count:plan.member_count,scope_global:false,dispose}
}
