import test from 'node:test'
import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { prepareNativeStagePlan,stageReviewedNativePlan,installNativeProfileScopes } from '../native_orchestration.mjs'
function fixture(){
  const organization_id=randomUUID(),captain_session_id=randomUUID(),agents=Array.from({length:24},(_,i)=>({id:randomUUID(),name:'Profile'+i,provider:'fixture',model:'fixture-model',systemPrompt:'Unique full DNA '+i+' '+('x'.repeat(25000)),toolScope:{allow:['read_fixture'],deny:['forbidden_fixture']}}))
  const definitions={format:'agent-team-gui/definitions',version:2,exportedAt:1,agents,squads:[{id:randomUUID(),activationMode:'manual'}]}
  const options={organization_id,captain_session_id,captain_member_id:agents[0].id,orchestration_backend:'agentteams_native',goal:'Prepare a reviewed fixture plan',tasks:[{id:'t1',subject:'Review fixture',member_id:agents[1].id}]}
  return {definitions,options,plan:prepareNativeStagePlan(definitions,options)}
}
test('same24 maps one captain plus23; full DNA never truncated; no dual scheduler',()=>{
  const f=fixture();assert.equal(f.plan.profiles.length,23);assert.equal(f.plan.member_count,24);assert.equal(f.plan.create.approval,'required')
  assert.equal(f.plan.enrich.operations[0].execution_prompt,f.definitions.agents[1].systemPrompt)
  assert.equal(f.plan.enrich.operations[0].execution_prompt.length>25000,true)
  assert.equal(f.plan.profiles[0].tool_scope.deny.includes('forbidden_fixture'),true)
  assert.equal(f.plan.starts_models,false)
  f.definitions.squads[0].activationMode='always';assert.throws(()=>prepareNativeStagePlan(f.definitions,f.options),/passive/)
})
test('manual native-tool deny and graph cycles fail instead of overridden',()=>{
  const f=fixture();f.definitions.agents[1].toolScope.deny.push('agent_teams_send_message')
  assert.throws(()=>prepareNativeStagePlan(f.definitions,f.options),/manual deny/)
  const g=fixture();g.options.tasks=[{id:'a',subject:'A',member_id:g.definitions.agents[1].id,dependencies:['b']},{id:'b',subject:'B',member_id:g.definitions.agents[2].id,dependencies:['a']}]
  assert.throws(()=>prepareNativeStagePlan(g.definitions,g.options),/cycle/)
})
test('exact human-reviewed plan invokes only native create staged and DNA edit',async()=>{
  const f=fixture(),calls=[],ctx={tools:{get:()=>({}),async execute(call){calls.push(call);return {value:call.name==='agent_teams_create'?{phase:'staged',team_id:f.plan.team_id}:{status:'staged'}}}}}
  const authority={owner_approved_sha256:f.plan.plan_sha256,readDefinitions:async()=>f.definitions,assertNoActiveGuiRuns:async()=>true,assertNoExistingTeam:async()=>true,scope_hook_ready:true,captain_profile_ready:true,readNativeCapacity:()=>({status:'OBSERVED',max_members:23})}
  const execution={agent:{id:f.plan.captain_session_id},callId:randomUUID(),token:Symbol('native-fixture-token'),signal:new AbortController().signal}
  const result=await stageReviewedNativePlan(ctx,f.plan,authority,execution)
  assert.deepEqual(calls.map(c=>c.name),['agent_teams_create','agent_teams_edit_plan']);assert.equal(calls[0].arguments.approval,'required')
  assert.equal(calls[0].agent,execution.agent);assert.equal(calls[0].parent,execution.token);assert.equal(result.models_started,false)
  f.plan.create.approval='automatic';await assert.rejects(stageReviewedNativePlan(ctx,f.plan,authority,execution),/immutable/)
})
test('existing run or missing native permission hook produces zero writes',async()=>{
  const f=fixture();let calls=0;const ctx={tools:{get:()=>({}),execute(){calls++}}},execution={agent:{id:f.plan.captain_session_id}}
  const authority={owner_approved_sha256:f.plan.plan_sha256,readDefinitions:async()=>f.definitions,assertNoActiveGuiRuns:async()=>false,assertNoExistingTeam:async()=>true,scope_hook_ready:true}
  await assert.rejects(stageReviewedNativePlan(ctx,f.plan,authority,execution),/GUI/);assert.equal(calls,0)
  authority.assertNoActiveGuiRuns=async()=>true;authority.scope_hook_ready=false
  await assert.rejects(stageReviewedNativePlan(ctx,f.plan,authority,execution),/permissions/);assert.equal(calls,0)
})
test('lifecycle identity comes from host descriptor; scope changes are child-local',()=>{
  const f=fixture(),handlers={},effects=[],scopes=[],guards=[]
  const ctx={on(name,fn){handlers[name]=fn;return()=>delete handlers[name]},effect(fn){effects.push(fn())}}
  const profile=f.plan.profiles[0],descriptor={mode:'continuable',label:'agent-teams:'+f.plan.team_id+':'+profile.alias,agentProvider:profile.provider,agentModel:profile.model,persona:'Native prefix\n'+profile.system_prompt}
  const agent={id:randomUUID(),session:{header:{parentSession:f.plan.captain_session_id},ownEvents:()=>[descriptor]},ctx:{tools:{restrict(scope){scopes.push(scope);return()=>{}},guard(fn){guards.push(fn);return()=>{}}},effect(fn){effects.push(fn())}}}
  installNativeProfileScopes(ctx,f.plan,events=>events[0],{owner_approved_sha256:f.plan.plan_sha256})
  handlers['agent/created']({agent,source:{kind:'created'}})
  assert.equal(scopes.length,1);assert.deepEqual(scopes[0],profile.tool_scope)
  assert.equal(guards[0]({agent,name:'forbidden_fixture'}),'Tool outside Teams profile scope')
  assert.equal(guards[0]({agent,name:'read_fixture'}),undefined)
  const wrong={...agent,id:randomUUID(),session:{...agent.session,header:{parentSession:randomUUID()}}}
  handlers['agent/created']({agent:wrong,source:{kind:'created'}})
  assert.equal(scopes.length,1,'Unrelated parent is ignored and cannot acquire an organization binding')
  effects.forEach(fn=>fn())
})
