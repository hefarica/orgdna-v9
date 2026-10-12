/** Real-package, keyless staging composition. Not a deployed DSH/LLM end-to-end test.
 * Usage: node native_agentteams_stage_smoke.mjs /absolute/isolated/sdk-root [report.json]
 * Requires the reviewed official packages already installed. Installs nothing.
 * Agent/session/profile/adapter metadata are explicit inert fixtures; Cordis,
 * Tools, AgentRegistry, LLM registry, Subagent, SystemPrompt and AgentTeams are real.
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { randomUUID, createHash } from 'node:crypto'
import { mkdtemp, readFile, writeFile, rm, readdir } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import { resolve, join, isAbsolute } from 'node:path'
import { prepareNativeStagePlan, stageReviewedNativePlan, installNativeProfileScopes, installNativeCaptainProfile, inspectNativeCapacity, NATIVE_MEMBER_TOOLS } from '../native_orchestration.mjs'
import { mount } from '../plugin.mjs'
import { PROTOCOL, OPERATIONS } from '../runtime.mjs'

assert.ok(process.argv[2] && isAbsolute(process.argv[2]), 'Pass absolute isolated SDK root')
const sdkRoot=resolve(process.argv[2]), require=createRequire(join(sdkRoot,'package.json'))
const load=name=>import(pathToFileURL(require.resolve(name)).href)
const packages=['@deepseek-ai/cordis','@deepseek-ai/dsh-tools','@deepseek-ai/dsh-agent','@deepseek-ai/dsh-llm','@deepseek-ai/dsh-subagent','@deepseek-ai/dsh-system-prompt','@deepseek-ai/dsh-scope','@nanmicoder/dsh-agent-teams']
const versions=Object.fromEntries(packages.map(name=>[name,JSON.parse(readFileSync(require.resolve(name+'/package.json'),'utf8')).version]))
assert.equal(versions['@deepseek-ai/cordis'],'4.0.4')
assert.equal(versions['@nanmicoder/dsh-agent-teams'],'0.1.22')
for(const name of packages.filter(name=>name.startsWith('@deepseek-ai/dsh-')))assert.equal(versions[name],'0.2.0-rc.2')
const [{Context},{ToolRuntime,defineTool},{AgentRegistry},{LlmRuntime,LlmAdapter},{SubagentRuntime,foldSubagentDescriptor,snapshotSubagentDescriptor},{SystemPrompt},{createScope},AgentTeams]=await Promise.all(packages.map(load))
const workspace=await mkdtemp(join(sdkRoot,'.orgdna-agentteams-smoke-')), stateDir='fixture-team-store'
const ctx=new Context(), scopes=[], bindings=new Map(), nativeCalls=[], diagnostics=[]
let harnessCtx
let modelCalls=0, metadataReads=0, agentCreated=0, forbiddenToolCalls=0, callbackReads=0
const hash=text=>createHash('sha256').update(text).digest('hex')
const ids=Array.from({length:24},()=>randomUUID()), captainId=randomUUID(), organizationId=randomUUID()
const addonNamespace='orgdna_'+organizationId.replaceAll('-',''), addonToolNames=OPERATIONS.map(operation=>addonNamespace+'_'+operation)
const definitions={format:'agent-team-gui/definitions',version:2,exportedAt:1,
  agents:ids.map((id,i)=>({id,name:'Native Fixture '+i,provider:i%2?'fixture-provider-b':'fixture-provider-a',model:'fixture-model-'+i%3,
    systemPrompt:'FULL DNA '+i+' / español 日本語 /\n'+('Unique charter '+i+' '.repeat(i%3+1)).repeat(1700)+'\nEND DNA '+i,
    toolScope:{allow:['fixture_read','fixture_manual_deny',...addonToolNames],deny:['fixture_manual_deny']}})),
  squads:[{id:randomUUID(),activationMode:'manual'}]}
const originalDefinitions=JSON.stringify(definitions)
const tasks=Array.from({length:24},(_,i)=>({id:'seed-'+i,subject:'Fixture task '+i,description:'Keyless staging only',member_id:ids[1+i%23],dependencies:i>0?['seed-'+(i-1)]:[]}))
const plan=prepareNativeStagePlan(definitions,{organization_id:organizationId,captain_session_id:captainId,captain_member_id:ids[0],orchestration_backend:'agentteams_native',goal:'Stage the existing 24-profile fixture roster without approval or model execution',tasks})
class InertCatalogAdapter extends LlmAdapter {
  async listModels(provider){metadataReads++;return Array.from({length:3},(_,i)=>({provider,id:'fixture-model-'+i,name:'Fixture Model '+i}))}
  async resolveModel(provider,model){metadataReads++;return {provider,id:model,name:model}}
  async *stream(){modelCalls++;throw new Error('No model transport is allowed in this staging test')}
}
function fixtureAgent(id,profile,descriptor,parentSession) {
  const agent={id,status:'idle',options:{provider:profile.provider,model:profile.model},
    session:{id,header:{cwd:workspace,...parentSession?{parentSession}:{}},ownEvents:()=>descriptor?[{type:'subagent/descriptor',data:descriptor}]:[],requestHeader:()=>undefined},
    async whenIdle(){},cancel(){throw new Error('Unexpected fixture cancellation')},steer(){throw new Error('Unexpected fixture message delivery')}}
  const scope=createScope(harnessCtx,agent);scopes.push(scope);agent.ctx=scope.ctx;return agent
}
async function call(agent,name,args={}) {
  return await ctx.tools.execute({name,arguments:args,agent,callId:randomUUID(),signal:new AbortController().signal})
}
let report
try {
  ctx.on('internal/error',error=>diagnostics.push(String(error)))
  await ctx.plugin(SystemPrompt,{includeHarnessIdentity:false,includeRuntimeContext:false})
  await ctx.plugin(ToolRuntime,{mode:'native'})
  await ctx.plugin(AgentRegistry)
  await ctx.plugin(LlmRuntime)
  await ctx.plugin(SubagentRuntime,{maxDepth:1,maxActiveSubagents:32})
  await ctx.plugin({name:'native-smoke-fixture-host',inject:['tools','agents','llm','subagents','systemPrompt'],apply(c){harnessCtx=c}})
  ctx.llm.registerAdapter(['fixture-provider-a','fixture-provider-b'],new InertCatalogAdapter())
  ctx.on('agent/created',()=>{agentCreated++})
  const fixtureTools=await ctx.plugin({name:'native-smoke-fixture-tools',inject:['tools'],apply(c){
    for(const name of ['fixture_read','fixture_manual_deny','fixture_unlisted']) c.tools.register(defineTool({name,description:'Inert fixture tool',parameters:{},output:{schema:{type:'string'},render:(_a,v)=>[{type:'text',text:v}]},async execute(){if(name==='fixture_read')callbackReads++;else forbiddenToolCalls++;return name}}))
    c.tools.guard(exec=>{if(exec.name.startsWith('agent_teams_')){nativeCalls.push(exec.name);if(!['agent_teams_create','agent_teams_edit_plan','agent_teams_send_message'].includes(exec.name))return 'Native execution/approval/status forbidden in staging smoke'}})
  }})
  const nativePlugin=await ctx.plugin(AgentTeams,{stateDir,maxMembers:23,memberMaxDepth:0,slashCommand:false,profiles:{}})
  assert.ok(ctx.tools.get('agent_teams_create'),'Actual AgentTeams tools must be registered')
  assert.ok(ctx.tools.get('agent_teams_edit_plan'))
  const captain=fixtureAgent(captainId,definitions.agents[0])
  await captain.ctx.agents.register(captain)
  assert.equal(ctx.agents.get(captainId),captain)
  const addonConfig={protocol:PROTOCOL,organization_id:organizationId,namespace:addonNamespace,
    members:definitions.agents.map((profile,i)=>({member_id:profile.id,name:profile.name,reports_to:i?ids[0]:'OWNER_EXTERNAL'})),
    session_bindings:{[captainId]:ids[0]},state_directory:join(workspace,'fixture-shared-ledger'),
    enabled:true,confirm_activation:'ACTIVATE_EXISTING_ROSTER_ONLY',verified_tools_version:versions['@deepseek-ai/dsh-tools']}
  let addon
  const addonPlugin=await ctx.plugin({name:'native-smoke-combined-coordination-addon',inject:['tools'],apply(c){addon=mount(c,addonConfig,defineTool)}})
  assert.equal(addon.status,'MOUNTED');assert.deepEqual(addon.registered_tools,addonToolNames)
  const captainProfile=installNativeCaptainProfile(captain,plan,plan.plan_sha256)
  const captainAssembly=await captain.ctx.systemPrompt.assemble({agent:captain,scope:captain})
  const captainDna=captainAssembly.sections.find(section=>section.name==='orgdna:captain:'+organizationId)
  assert.equal(captainDna.text,definitions.agents[0].systemPrompt)
  assert.equal(captainDna.interpolate,false,'DNA is literal and cannot be changed by prompt-variable interpolation')
  assert.equal(ctx.tools.get('agent_teams_approve',captain),undefined)
  assert.equal(ctx.tools.get('agent_teams_resume',captain),undefined)
  for(const name of addonToolNames)assert.ok(ctx.tools.get(name,captain))
  assert.ok(ctx.tools.get('agent_teams_create',captain));assert.ok(ctx.tools.get('agent_teams_send_message',captain))
  const hook=installNativeProfileScopes(ctx,plan,foldSubagentDescriptor,{owner_approved_sha256:plan.plan_sha256,
    bindSession(sessionId,definitionId){assert.ok(!bindings.has(sessionId));const release=addon.ledger.bindRuntimeSession(sessionId,definitionId);bindings.set(sessionId,definitionId);return()=>{release();bindings.delete(sessionId)}}})
  const authority={owner_approved_sha256:plan.plan_sha256,
    readNativeCapacity:async()=>inspectNativeCapacity(ctx,AgentTeams),
    readDefinitions:async()=>definitions,assertNoActiveGuiRuns:async()=>true,
    assertNoExistingTeam:async()=>{try{return (await readdir(join(workspace,stateDir))).length===0}catch(error){if(error.code==='ENOENT')return true;throw error}},
    scope_hook_ready:hook.status==='LIFECYCLE_HOOK_READY',captain_profile_ready:captainProfile.status==='CAPTAIN_PROFILE_BOUND'}
  const execution={agent:captain,callId:randomUUID(),signal:new AbortController().signal}
  await assert.rejects(stageReviewedNativePlan(ctx,plan,{...authority,owner_approved_sha256:'not-approved'},execution),/immutable/)
  await assert.rejects(stageReviewedNativePlan(ctx,plan,{...authority,assertNoActiveGuiRuns:async()=>false},execution),/GUI/)
  await assert.rejects(stageReviewedNativePlan(ctx,plan,{...authority,readDefinitions:async()=>({...definitions,exportedAt:2})},execution),/changed after review/)
  assert.equal(nativeCalls.length,0,'Missing authority, concurrent scheduler and changed SSOT must fail before native writes')
  assert.equal(await authority.assertNoExistingTeam(),true)
  const staged=await stageReviewedNativePlan(ctx,plan,authority,execution)
  assert.equal(staged.status,'STAGED_AWAITING_NATIVE_USER_APPROVAL')
  assert.deepEqual(nativeCalls,['agent_teams_create','agent_teams_edit_plan'])
  const statePath=join(workspace,stateDir,plan.team_id,'team.json'), state=JSON.parse(await readFile(statePath,'utf8'))
  assert.equal(state.phase,'staged');assert.equal(state.planReviewState,'awaiting_review')
  assert.equal(state.captainSessionId,captainId);assert.equal(state.members.length+1,24);assert.equal(state.tasks.length,24)
  for(const member of state.members){
    const profile=plan.profiles.find(p=>p.alias===member.name);assert.ok(profile)
    assert.equal(member.id,'');assert.equal(member.status,'idle');assert.equal(member.executionPrompt,profile.system_prompt)
    assert.equal(member.provider,profile.provider);assert.equal(member.model,profile.model)
  }
  const seedMap=new Map(state.tasks.map(t=>[t.profileSeedId,t.id]))
  for(const task of state.tasks){const expected=plan.create.plan.tasks.find(t=>t.id===task.profileSeedId);assert.equal(task.status,'pending');assert.equal(task.attempt,0);assert.equal(task.attemptId,undefined);assert.equal(task.assignee,expected.assignee);assert.deepEqual(task.dependencies,expected.dependencies.map(id=>seedMap.get(id)))}
  assert.equal(ctx.agents.list().length,1,'Staging must not create any child agents')
  assert.equal(agentCreated,1);assert.equal(modelCalls,0)
  const captainToolNames=ctx.tools.schemas(captain).map(t=>t.name)
  const durableHashBeforeLifecycle=hash(await readFile(statePath,'utf8'))
  await assert.rejects(stageReviewedNativePlan(ctx,plan,authority,execution),/Existing AgentTeams team/)
  assert.deepEqual(nativeCalls,['agent_teams_create','agent_teams_edit_plan'],'An existing team cannot trigger a second native create')
  const stagingCalls=[...nativeCalls]
  // Source-audited safety boundary in AgentTeams 0.1.22 tools.js:
  // dispatchMember returns false for phase=staged before route resolution or
  // spawnMember. This tests only the durable mailbox, not live conversation.
  assert.deepEqual(NATIVE_MEMBER_TOOLS,['agent_teams_claim_task','agent_teams_update_task','agent_teams_send_message','agent_teams_status'])
  const messageArgs={to:state.members[0].name,content:'Staged fixture message: preserve recipient and Unicode ✓ 日本語'}
  const messageMetadataReads=metadataReads, messageRegistryCount=ctx.agents.list().length
  assert.equal(JSON.parse(await readFile(statePath,'utf8')).phase,'staged')
  const messageResult=await call(captain,'agent_teams_send_message',messageArgs)
  assert.equal(messageResult.isError,false);assert.equal(messageResult.value.delivered,'mailbox')
  assert.equal(messageResult.value.to,messageArgs.to);assert.equal(messageResult.value.from,'captain')
  const mailboxPath=join(workspace,stateDir,plan.team_id,'inbox',messageArgs.to+'.jsonl')
  const readMailbox=async()=> (await readFile(mailboxPath,'utf8')).trim().split('\n').map(line=>JSON.parse(line))
  const mailbox=await readMailbox();assert.equal(mailbox.length,1)
  assert.equal(mailbox[0].id,messageResult.value.message_id);assert.equal(mailbox[0].content,messageArgs.content)
  assert.equal(mailbox[0].from,'captain');assert.equal(mailbox[0].to,messageArgs.to)
  for(const field of ['deliveredAt','readAt','deliveryClaimedAt'])assert.equal(mailbox[0][field],undefined)
  const duplicateMessage=await call(captain,'agent_teams_send_message',messageArgs)
  assert.equal(duplicateMessage.isError,false);assert.equal(duplicateMessage.value.delivered,'duplicate')
  assert.equal(duplicateMessage.value.message_id,messageResult.value.message_id);assert.equal((await readMailbox()).length,1)
  assert.equal(metadataReads,messageMetadataReads);assert.equal(modelCalls,0)
  assert.equal(ctx.agents.list().length,messageRegistryCount)
  assert.equal(hash(await readFile(statePath,'utf8')),durableHashBeforeLifecycle)
  const messagingEvidence={scope:'native_durable_mailbox_only',member_tools:[...NATIVE_MEMBER_TOOLS],native_send_tool_available:true,
    actual_tool_calls:2,new_messages:1,duplicate_reuses_message_id:true,correct_sender_and_recipient:true,content_bytes_preserved:true,
    delivered:'mailbox',read_or_live_delivery_recorded:false,delivery_lease_released:true,phase_stayed_staged:true,
    new_agent_registry_entries:0,new_model_calls:0,new_provider_metadata_reads:0,
    live_conversation_verified:false,source_contract:'AgentTeams 0.1.22 tools.js dispatchMember checks phase === staged before resolveMemberLlmSelection/spawnMember; send_message releases the mailbox delivery lease when dispatch returns false.'}
  // Separate lifecycle-fixture check: public Registry serial announcement and
  // public descriptor serialization/folding, never Subagent.start/approval.
  const childFixtures=[]
  for(const profile of plan.profiles){
    const descriptor=snapshotSubagentDescriptor({mode:'continuable',provider:'spawn',label:'agent-teams:'+plan.team_id+':'+profile.alias,agentProvider:profile.provider,agentModel:profile.model,persona:'Native fixture prefix\n'+profile.system_prompt})
    const child=fixtureAgent(randomUUID(),profile,descriptor,captainId);childFixtures.push(child)
    await child.ctx.agents.register(child)
    assert.equal(bindings.get(child.id),profile.definition_id,'The awaited agent/created hook must bind before registry registration resolves')
    assert.equal(ctx.tools.get('fixture_manual_deny',child),undefined)
    assert.equal(ctx.tools.get('fixture_unlisted',child),undefined)
    const allowed=await call(child,'fixture_read');assert.equal(allowed.isError,false);assert.equal(allowed.value,'fixture_read')
    const denied=await call(child,'fixture_manual_deny');assert.equal(denied.isError,true)
    // A new scoped tool cannot escape a profile allow-list; the monotonic guard rejects it.
    child.ctx.tools.register(defineTool({name:'fixture_local_escape',description:'Denied local fixture',parameters:{},output:{schema:{type:'string'},render:(_a,v)=>[{type:'text',text:v}]},async execute(){forbiddenToolCalls++;return 'must not execute'}}))
    const localDenied=await call(child,'fixture_local_escape');assert.equal(localDenied.isError,true)
  }
  assert.equal(bindings.size,23);assert.equal(callbackReads,23);assert.equal(forbiddenToolCalls,0)
  const firstProfile=plan.profiles[0]
  const unrelated=fixtureAgent(randomUUID(),firstProfile,snapshotSubagentDescriptor({mode:'continuable',provider:'spawn',label:'agent-teams:'+plan.team_id+':'+firstProfile.alias,agentProvider:firstProfile.provider,agentModel:firstProfile.model,persona:firstProfile.system_prompt}),randomUUID())
  await unrelated.ctx.agents.register(unrelated)
  assert.equal(bindings.has(unrelated.id),false,'The same label with a different trusted parent never gets a profile binding')
  // Both systems are mounted in this exact Context. The ledger's only initial
  // binding was the captain; every teammate binding came from the real serial
  // hook after trusted parent/descriptor checks. No model controls the identity.
  const combinedAgents=[captain,...childFixtures]
  const combinedAgentCountBefore=ctx.agents.list().length
  for(let i=0;i<combinedAgents.length;i++) {
    const agent=combinedAgents[i]
    for(const name of addonToolNames)assert.ok(ctx.tools.get(name,agent),'Every reviewed profile exposes all six addon tools')
    const summary=await call(agent,addonNamespace+'_state',{section:'summary'})
    assert.equal(summary.isError,false);assert.equal(summary.value.member_id,ids[i]);assert.equal(summary.value.bound_session_count,24)
    const result=await call(agent,addonNamespace+'_message',{expected_version:i,idempotency_key:'combined-message-'+i,payload:{to:'all',text:'Combined native-context fixture message '+i}})
    assert.equal(result.isError,false);assert.equal(result.value.version,i+1)
    assert.equal(result.value.record.actor,ids[i]);assert.equal(result.value.record.provenance,'bound_dsh_session')
  }
  const combinedMailbox=await call(childFixtures[22],addonNamespace+'_state',{section:'messages'})
  assert.equal(combinedMailbox.isError,false);assert.equal(combinedMailbox.value.rows.length,24)
  assert.deepEqual(new Set(combinedMailbox.value.rows.map(row=>row.actor)),new Set(ids))
  const unbound=await call(unrelated,addonNamespace+'_state',{section:'summary'})
  assert.equal(unbound.isError,true);assert.match(JSON.stringify(unbound),/UNBOUND_SESSION/)
  const spoofed=await call(childFixtures[0],addonNamespace+'_message',{expected_version:24,idempotency_key:'combined-spoof',payload:{to:'all',text:'Must not persist',actor:ids[0]}})
  assert.equal(spoofed.isError,true)
  const combinedSummary=await call(captain,addonNamespace+'_state',{section:'summary'})
  assert.equal(combinedSummary.value.version,24);assert.equal(combinedSummary.value.counts.messages,24)
  const combinedDisk=JSON.parse(await readFile(join(addonConfig.state_directory,organizationId,'coordination.json'),'utf8'))
  assert.equal(combinedDisk.messages.length,24);assert.equal(combinedDisk.audit.length,24)
  assert.deepEqual(combinedDisk.member_ids,ids)
  assert.ok(ctx.tools.get('agent_teams_create',captain));assert.ok(ctx.tools.get('agent_teams_send_message',captain))
  assert.equal((await readMailbox()).length,1,'Addon messages never cross into native AgentTeams mailboxes')
  assert.equal(modelCalls,0);assert.equal(metadataReads,messageMetadataReads)
  assert.equal(ctx.agents.list().length,combinedAgentCountBefore)
  const combinedEvidence={same_cordis_context:true,same_tool_runtime:true,agentteams_plugin_active:true,
    six_addon_tools_registered:true,all_six_visible_in_all_24_reviewed_fixture_profiles:true,
    initial_captain_bindings:1,teammate_bindings_from_serial_native_hook:23,verified_bound_sessions:24,
    addon_message_calls_through_tool_runtime:24,distinct_bound_authors:24,readback_from_teammate:true,durable_messages:24,
    unrelated_parent_session_rejected:true,model_supplied_actor_rejected:true,failed_calls_leave_version_24:true,
    native_team_store_unchanged:true,native_mailbox_separate:true,addon_is_coordination_only:true,
    model_calls:0,subagent_spawns:0,real_agent_conversation_verified:false}
  assert.deepEqual(ctx.tools.schemas(captain).map(t=>t.name),captainToolNames,'Member restrictions must leave captain scope unchanged')
  assert.ok(ctx.tools.get('fixture_unlisted'),'Member restrictions must leave global registry unchanged')
  assert.equal(hash(await readFile(statePath,'utf8')),durableHashBeforeLifecycle,'Lifecycle fixtures must not mutate the staged team')
  assert.equal(JSON.stringify(definitions),originalDefinitions,'Teams fixture definitions remain byte-identical')
  assert.equal(modelCalls,0)
  report={status:'PASS',label:'REAL_NATIVE_AGENTTEAMS_STAGING_COMPOSITION_WITH_EXPLICIT_INERT_FIXTURES',measured_at_utc:new Date().toISOString(),versions,
    provenance:{test_script_sha256:hash(await readFile(new URL(import.meta.url))),native_orchestration_sha256:hash(await readFile(new URL('../native_orchestration.mjs',import.meta.url))),addon_plugin_sha256:hash(await readFile(new URL('../plugin.mjs',import.meta.url))),addon_runtime_sha256:hash(await readFile(new URL('../runtime.mjs',import.meta.url))),dependency_lock_sha256:hash(await readFile(join(sdkRoot,'package-lock.json'))),agentteams_entry_sha256:hash(await readFile(require.resolve('@nanmicoder/dsh-agent-teams')))},
    native_plugin_config:{maxMembers:23,memberMaxDepth:0,slashCommand:false,stateDir:'ephemeral isolated fixture-team-store'},
    real_components:['Cordis Context/plugin lifecycle','DSH ToolRuntime schema/guard/execution pipeline','DSH AgentRegistry serial agent/created dispatch','DSH LlmRuntime metadata routing','DSH SubagentRuntime service and public descriptor APIs','DSH SystemPrompt and scoped tools','AgentTeams public plugin registration, create, edit_plan and durable staged store','OrgDNA prepare/stage/scope helpers','OrgDNA addon mount and all six production tool registrations in the same Context','OrgDNA SharedLedger durable messages and bindRuntimeSession wired directly to the verified serial scope hook'],
    fixtures:['24 Teams v2 profiles with unique long Unicode DNA','inert captain Agent/Session in official registry','two metadata-only LlmAdapter routes; stream throws','23 inert child lifecycle Agent/Session objects, explicitly registered after staging for separate scope verification','host-owned reviewed-plan consent fixture; no claim of real user or GUI approval','no Teams GUI service; trusted fixture callback reports zero active GUI runs'],
    staging:{profile_count:24,captain_count:1,new_native_member_count:23,total_members:24,task_count:24,all_unspawned:true,all_tasks_pending:true,active_child_agents_after_staging:0,phase:state.phase,plan_review_state:state.planReviewState,registry_tool_calls:stagingCalls,metadata_reads:metadataReads,provider_model_preserved:true,full_prompt_bytes_preserved:true,prompt_sha256:state.members.map(member=>({alias:member.name,bytes:Buffer.byteLength(member.executionPrompt),sha256:hash(member.executionPrompt)})),captain_prompt:{full_bytes_preserved:true,interpolation_disabled:true,bytes:Buffer.byteLength(captainDna.text),sha256:hash(captainDna.text)},dependency_mapping_preserved:true,team_captain_identity_preserved:true,definitions_unchanged:true,model_approve_resume_tools_hidden:true},
    native_messaging:messagingEvidence,
    combined_native_and_addon:combinedEvidence,
    negative_preflight:{missing_review_zero_native_calls:true,active_gui_scheduler_zero_native_calls:true,changed_profiles_zero_native_calls:true,existing_team_zero_duplicate_native_calls:true},
    lifecycle_scope_fixture:{count:23,public_serial_hook:true,bindings_before_register_returns:true,allowed_tool_callbacks:callbackReads,forbidden_tool_callbacks:forbiddenToolCalls,manual_denies_preserved:true,local_tool_escape_rejected:true,unrelated_parent_not_bound:true,captain_and_global_scopes_unchanged:true,staged_store_unchanged:true},
    actual_model_or_provider_api_calls:modelCalls,actual_subagent_spawns:0,actual_native_team_approved:false,actual_dsh_application_started:false,actual_user_profiles_read:false,user_computer_used:false,
    not_verified:['live DSH host startup and authenticated UI flow','real Teams service and user profile IDs','Subagent spawn/provider integration and actual session persistence','Captain receives hola through model and coordinates real children','native user approval and post-approval task execution','provider credentials and network responses'],deployment_constraints:['Native AgentTeams maxMembers must allow N-1 teammates; its unmodified default is 8, so a 24-profile team needs an explicitly reviewed limit of at least 23.'],diagnostics}
  await addonPlugin.dispose()
  for(const name of addonToolNames)assert.equal(ctx.tools.get(name),undefined)
  assert.ok(ctx.tools.get('agent_teams_create',captain));assert.ok(ctx.tools.get('agent_teams_send_message',captain));assert.ok(ctx.tools.get('fixture_read'))
  await assert.rejects(readFile(join(addonConfig.state_directory,organizationId,'active.lock')),{code:'ENOENT'})
  report.combined_native_and_addon.cleanup={six_addon_tools_removed:true,addon_ownership_lock_released:true,native_agentteams_tools_preserved:true,unrelated_fixture_tools_preserved:true}
  await nativePlugin.dispose();assert.equal(ctx.tools.get('agent_teams_create'),undefined);assert.ok(ctx.tools.get('fixture_read'))
  // Recompose the actual native plugin with maxMembers OMITTED, preserving
  // its schema default. Both the OrgDNA preflight and native tool must reject.
  const capacityStateDir='fixture-default-capacity-store'
  const capacityPlugin=await ctx.plugin(AgentTeams,{stateDir:capacityStateDir,memberMaxDepth:0,slashCommand:false,profiles:{}})
  const observedCapacity=inspectNativeCapacity(ctx,AgentTeams)
  assert.equal(observedCapacity.status,'OBSERVED');assert.equal(observedCapacity.max_members,8)
  const capacityPlan=plan
  const capacityNoTeam=async()=>{try{return (await readdir(join(workspace,capacityStateDir))).length===0}catch(error){if(error.code==='ENOENT')return true;throw error}}
  const capacityNativeCalls=nativeCalls.length,capacityMetadataReads=metadataReads,capacityAgentCount=ctx.agents.list().length
  await assert.rejects(stageReviewedNativePlan(ctx,capacityPlan,{...authority,owner_approved_sha256:capacityPlan.plan_sha256,assertNoExistingTeam:capacityNoTeam},execution),/CAPACITY_LIMIT/)
  assert.equal(nativeCalls.length,capacityNativeCalls)
  const capacityResult=await call(captain,'agent_teams_create',capacityPlan.create)
  assert.equal(capacityResult.isError,true)
  assert.match(JSON.stringify(capacityResult),/23 members but maxMembers is 8/)
  await assert.rejects(readdir(join(workspace,capacityStateDir)),{code:'ENOENT'})
  assert.equal(metadataReads,capacityMetadataReads);assert.equal(modelCalls,0);assert.equal(ctx.agents.list().length,capacityAgentCount)
  assert.equal(hash(await readFile(statePath,'utf8')),durableHashBeforeLifecycle)
  report.default_capacity={configured_max_members_omitted:true,observed_max_members:8,required_teammates:23,
    observed_via:observedCapacity.source,helper_rejected:'CAPACITY_LIMIT',helper_native_calls:0,native_tool_called:1,native_tool_rejected:true,
    native_error:'profile "inline-plan" has 23 members but maxMembers is 8',state_root_created:false,existing_staged_team_unchanged:true,new_agent_registry_entries:0,new_provider_metadata_reads:0,new_model_calls:0,settings_changed:false}
  hook.dispose();assert.equal(bindings.size,0)
  captainProfile.dispose()
  const afterCaptainDispose=await captain.ctx.systemPrompt.assemble({agent:captain,scope:captain})
  assert.ok(!afterCaptainDispose.sections.some(section=>section.name==='orgdna:captain:'+organizationId))
  await capacityPlugin.dispose();assert.equal(ctx.tools.get('agent_teams_create'),undefined);assert.ok(ctx.tools.get('fixture_read'))
  report.disposal={profile_bindings_removed:true,captain_profile_section_removed:true,agentteams_tools_removed:true,unrelated_fixture_plugin_preserved:true}
  await fixtureTools.dispose()
  if(process.argv[3])await writeFile(resolve(process.argv[3]),JSON.stringify(report,null,2)+'\n')
  process.stdout.write(JSON.stringify(report,null,2)+'\n')
} finally {
  for(const scope of scopes.reverse())await scope.dispose()
  await ctx.fiber.dispose()
  await rm(workspace,{recursive:true,force:true})
}
