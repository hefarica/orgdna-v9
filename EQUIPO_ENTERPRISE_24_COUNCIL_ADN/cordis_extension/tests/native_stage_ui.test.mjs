import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, rm, mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { createNativeStageController, createNativeStageFetchHandler, readStageDefinitions, assertGuiIdle } from '../native_stage_ui.mjs'
const ids={captain:'11111111-1111-4111-8111-111111111111',member:'22222222-2222-4222-8222-222222222222',squad:'33333333-3333-4333-8333-333333333333',session:'44444444-4444-4444-8444-444444444444',org:'55555555-5555-4555-8555-555555555555'}
async function fixture(extra={}) {
  const root=await mkdtemp(join(tmpdir(),'orgdna-native-ui-'))
  const calls=[],guards=[],bindings=[],events=[]
  const scopeTools={restrict:value=>{bindings.push(value);return()=>{}},guard:fn=>{guards.push(fn);return()=>{}}}
  const captain={id:ids.session,status:'idle',options:{provider:'deepseek',model:'fixture'},ctx:{tools:scopeTools,systemPrompt:{section:()=>()=>{}},effect:()=>{}},async runMaintenance(fn){calls.push('maintenance');return fn(new AbortController().signal)}}
  const defs={agents:new Map([[ids.captain,{name:'Captain',systemPrompt:'Captain DNA',provider:'deepseek',model:'fixture',toolScope:{allow:['read_file']}}],[ids.member,{name:'Engineer',systemPrompt:'Engineer DNA',provider:'deepseek',model:'fixture',toolScope:{allow:['read_file']}}]]),squads:new Map([[ids.squad,{name:'Org',members:[ids.captain,ids.member],activationMode:'manual'}]])}
  let runs=[]
  const service={async readDefinitionSnapshot(){return structuredClone(defs)},listRuns(){return runs}}
  const ctx={agents:{get:id=>id===captain.id?captain:undefined,roots:()=>[captain]},tools:{get:()=>({}),async execute(exec){calls.push(exec.name);assert.equal(exec.agent,captain);assert.equal(exec.parent,undefined);assert.ok(exec.signal instanceof AbortSignal);if(exec.name==='agent_teams_create'){assert.equal(exec.arguments.approval,'required');return{isError:false,value:{phase:'staged',team_id:exec.arguments.name}}}if(exec.name==='agent_teams_edit_plan'){assert.equal(exec.arguments.operations[0].execution_prompt,'Engineer DNA');return{isError:false,value:{status:'staged'}}}assert.fail('Unexpected native call')}},on:(event,fn)=>{events.push(event);return()=>{}},effect:()=>{}}
  const controller=createNativeStageController(ctx,{service,stateRoot:root,foldSubagentDescriptor:()=>undefined,readNativeCapacity:()=>({status:'OBSERVED',max_members:8,config_changed:false}),...extra})
  const input={squad_id:ids.squad,organization_id:ids.org,captain_member_id:ids.captain,captain_session_id:ids.session,goal:'Review the existing repository',tasks:[{id:'t1',subject:'Inspect',member_id:ids.member,dependencies:[]}]}
  const approve=ticket=>({review_nonce:ticket.review_nonce,plan_sha256:ticket.plan.plan_sha256,ack:'STAGE_ONLY_KEEP_NATIVE_EXECUTION_APPROVAL'})
  return{root,calls,defs,captain,controller,service,input,approve,guards,bindings,events,setRuns:value=>runs=value,async cleanup(){controller.dispose();await rm(root,{recursive:true,force:true})}}
}
test('operator reviews immutable full DNA; native stage only goes through maintenance and tool pipeline',async()=>{
  const f=await fixture()
  try{
    const ticket=await f.controller.operate('prepare',f.input)
    assert.equal(ticket.status,'REVIEW_REQUIRED');assert.equal(f.calls.length,0)
    assert.equal(ticket.plan.captain_profile.system_prompt,'Captain DNA')
    assert.equal(ticket.plan.profiles[0].system_prompt,'Engineer DNA')
    const result=await f.controller.operate('stage',f.approve(ticket))
    assert.equal(result.status,'STAGED_AWAITING_NATIVE_USER_APPROVAL')
    assert.deepEqual(f.calls,['maintenance','agent_teams_create','agent_teams_edit_plan'])
    assert.equal(result.models_started,false);assert.equal(result.auto_approved,false)
    await assert.rejects(f.controller.operate('stage',f.approve(ticket)),/REVIEW_EXPIRED_OR_USED/)
    await assert.rejects(f.controller.operate('prepare',f.input),/EXISTING_TEAM_PRESERVED/)
  }finally{await f.cleanup()}
})
test('changed Teams source after review consumes gesture and performs no write',async()=>{
  const f=await fixture()
  try{
    const ticket=await f.controller.operate('prepare',f.input)
    f.defs.agents.get(ids.member).systemPrompt='Changed after review'
    await assert.rejects(f.controller.operate('stage',f.approve(ticket)),/PROFILES_CHANGED/)
    assert.deepEqual(f.calls,['maintenance']);assert.equal(f.bindings.length,0)
    await assert.rejects(f.controller.operate('stage',f.approve(ticket)),/REVIEW_EXPIRED_OR_USED/)
  }finally{await f.cleanup()}
})
test('wrong hash, expired ticket, and busy captain deny staging',async()=>{
  const f=await fixture({reviewMs:10})
  try{
    let ticket=await f.controller.operate('prepare',f.input)
    await assert.rejects(f.controller.operate('stage',{...f.approve(ticket),plan_sha256:'0'.repeat(64)}),/REVIEW_HASH_MISMATCH/)
    ticket=await f.controller.operate('prepare',f.input)
    await new Promise(r=>setTimeout(r,20))
    await assert.rejects(f.controller.operate('stage',f.approve(ticket)),/REVIEW_EXPIRED_OR_USED/)
    f.captain.status='running'
    await assert.rejects(f.controller.operate('prepare',f.input),/CAPTAIN_NOT_IDLE/)
    assert.equal(f.calls.length,0)
  }finally{await f.cleanup()}
})
test('active, unknown and capped GUI history cannot claim another engine idle',async()=>{
  const f=await fixture()
  try{
    for(const runs of [[{status:'running'}],[{status:'new-unknown'}],Array.from({length:200},()=>({status:'completed'}))]){
      f.setRuns(runs)
      assert.throws(()=>assertGuiIdle(f.service),/GUI_RUN_STATE_UNVERIFIED/)
      await assert.rejects(f.controller.operate('prepare',f.input),/GUI_RUN_STATE_UNVERIFIED/)
    }
    f.setRuns([]);f.defs.squads.get(ids.squad).activationMode='always'
    await assert.rejects(readStageDefinitions(f.service,ids.squad),/GUI_RUN_STATE_UNVERIFIED/)
    assert.equal(f.calls.length,0)
  }finally{await f.cleanup()}
})
test('existing active or staged team is preserved byte-for-byte; no second crew',async()=>{
  const f=await fixture()
  try{
    await mkdir(join(f.root,'existing'))
    const team={id:'existing',name:'Existing',captainSessionId:ids.session,createdAt:1,taskSeq:0,phase:'staged',members:[],tasks:[]}
    await writeFile(join(f.root,'existing','team.json'),JSON.stringify(team))
    await assert.rejects(f.controller.operate('prepare',f.input),/EXISTING_TEAM_PRESERVED/)
    assert.equal(f.calls.length,0)
  }finally{await f.cleanup()}
})
test('native page rejects CSRF and has no automatic call to approve/run/resume',async()=>{
  const f=await fixture()
  try{
    const handler=createNativeStageFetchHandler(f.controller)
    const page=await handler(new Request('http://127.0.0.1:9000/api/orgdna-native-stage'))
    assert.equal(page.status,200);assert.match(page.headers.get('content-security-policy'),/frame-ancestors 'none'/)
    const denied=await handler(new Request('http://127.0.0.1:9000/api/orgdna-native-stage',{method:'POST',headers:{'Content-Type':'application/json',Origin:'https://evil.example'},body:JSON.stringify({action:'prepare',payload:f.input})}))
    assert.equal(denied.status,409);assert.equal((await denied.json()).error,'OWNER_GESTURE_REQUIRED')
    for(const action of ['approve','run','resume','execute'])await assert.rejects(f.controller.operate(action,{}),/OWNER_GESTURE_REQUIRED/)
    assert.equal(f.calls.length,0)
  }finally{await f.cleanup()}
})
test('trusted manifest constrains organization and complete roster selection',async()=>{
  const f=await fixture({expected_organization_id:ids.org,expected_member_ids:[ids.captain,ids.member]})
  try{
    await assert.rejects(f.controller.operate('prepare',{...f.input,organization_id:ids.squad}),/INVALID_SELECTION/)
    f.defs.squads.get(ids.squad).members=[ids.captain]
    await assert.rejects(f.controller.operate('prepare',f.input),/INVALID_SELECTION/)
    assert.equal(f.calls.length,0)
  }finally{await f.cleanup()}
})
test('late preparation cannot replace a newer reviewed ticket',async()=>{
  const f=await fixture()
  try{
    const original=f.service.readDefinitionSnapshot
    let release;let first=true
    f.service.readDefinitionSnapshot=async()=>{if(first){first=false;await new Promise(r=>release=r)}return original()}
    const old=f.controller.operate('prepare',{...f.input,goal:'Old goal'})
    await new Promise(r=>setTimeout(r,1))
    const latest=await f.controller.operate('prepare',{...f.input,goal:'New goal'})
    release()
    await assert.rejects(old,/REVIEW_SUPERSEDED/)
    assert.equal(latest.plan.create.description,'New goal')
    const result=await f.controller.operate('stage',f.approve(latest))
    assert.equal(result.status,'STAGED_AWAITING_NATIVE_USER_APPROVAL')
  }finally{await f.cleanup()}
})
test('form edits invalidate review and stale browser responses are ignored',async()=>{
  const {runInNewContext}=await import('node:vm')
  const f=await fixture()
  try{
    const page=await createNativeStageFetchHandler(f.controller)(new Request('http://127.0.0.1:9000/api/orgdna-native-stage'))
    const html=await page.text(),script=html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)[1]
    const elements=new Map()
    const element=id=>{if(!elements.has(id))elements.set(id,{value:id==='tasks'?'[]':'fixture',checked:false,disabled:false,textContent:'',handlers:{},addEventListener(event,fn){this.handlers[event]=fn}});return elements.get(id)}
    let respond
    runInNewContext(script,{document:{getElementById:element},fetch:()=>new Promise(resolve=>respond=resolve),location:{pathname:'/api/orgdna-native-stage'},JSON,Error})
    const pending=element('form').onsubmit({preventDefault(){}})
    element('goal').value='Changed while preparing';element('form').handlers.input()
    respond({ok:true,json:async()=>({plan:{plan_sha256:'old'},review_nonce:'old'})})
    await pending
    assert.equal(element('review').textContent,'')
    element('ack').checked=true;element('ack').onchange()
    assert.equal(element('stage').disabled,true)
  }finally{await f.cleanup()}
})
test('capacity is observed twice and cannot be fabricated or increased by the form',async()=>{
  let maximum=2
  const f=await fixture({readNativeCapacity:()=>({status:'OBSERVED',max_members:maximum,config_changed:false})})
  try{
    const third='66666666-6666-4666-8666-666666666666'
    f.defs.agents.set(third,{name:'Reviewer',systemPrompt:'Review DNA',provider:'deepseek',model:'fixture',toolScope:{allow:['read_file']}})
    f.defs.squads.get(ids.squad).members.push(third)
    const ticket=await f.controller.operate('prepare',{...f.input,maxMembers:999})
    assert.equal(ticket.native_capacity.max_members,2)
    assert.equal(ticket.native_capacity.required_teammates,2)
    maximum=1
    await assert.rejects(f.controller.operate('stage',f.approve(ticket)),error=>error.code==='CAPACITY_LIMIT'&&error.details.max_members===1&&error.details.required_teammates===2)
    assert.deepEqual(f.calls,['maintenance']);assert.equal(f.bindings.length,0)
    maximum=undefined
    await assert.rejects(f.controller.operate('prepare',f.input),/CAPACITY_UNVERIFIED/)
  }finally{await f.cleanup()}
})
