import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, mkdir, readFile, rm, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createReadAdapter, createLocalBridge, readTeamFiles, registerLiveBridge, PROTOCOL } from '../live_bridge.mjs'
const versions={'@deepseek-ai/dsh-tools':'0.2.1-alpha.1','@deepseek-ai/dsh-client-connection':'0.2.1-alpha.1','dsh-agent-team-gui':'1.3.0','@nanmicoder/dsh-agent-teams':'0.1.22'}
function fixture() {
  const calls=[]
  const service={
    async readDefinitionSnapshot(){calls.push('readDefinitionSnapshot');return {agents:new Map([['profile',{name:'Engineer',api_key:'sensitive',systemPrompt:'Bearer abcdefghijklmNOP'}]]),squads:new Map()}},
    async previewRecipe(doc){calls.push('previewRecipe');return {format:doc.format}},
    async previewDefinitionsImport(doc,mode){calls.push('previewDefinitionsImport');return {format:doc.format,mode}},
    dispatch(){assert.fail('Must never dispatch')},importRecipe(){assert.fail('Must never mutate')},
  }
  const ctx={get:name=>name==='agentTeamGui'?service:undefined,tools:{schemas:()=>[{name:'safe_read'}],execute:()=>assert.fail('Must never execute')}}
  return {adapter:createReadAdapter(ctx,versions),ctx,calls}
}
async function request(b,path,payload,headers={}) {
  const res=await fetch(`http://127.0.0.1:${b.port}${path}`,{method:'POST',headers:{'Content-Type':'application/json',...headers},body:JSON.stringify(payload)})
  return {status:res.status,body:await res.json()}
}
async function pair(b){return request(b,'/v1/pair',{protocol:PROTOCOL,pairing_code:b.pairing_code,nonce:'nonce-long-enough-1234567'})}
test('public service snapshot and both previews are read only; secrets removed',async()=>{
  const {adapter,calls}=fixture()
  const profiles=await adapter.profiles()
  assert.equal(profiles.definitions_are_session_ids,false)
  assert.equal(profiles.agents[0].api_key,undefined)
  assert.equal(profiles.agents[0].systemPrompt,'[REDACTED]')
  await adapter.preview({format:'agent-team-gui/recipe'})
  await adapter.preview({format:'agent-team-gui/definitions'})
  assert.deepEqual(calls,['readDefinitionSnapshot','previewRecipe','previewDefinitionsImport'])
  assert.equal(adapter.capabilities.task_plan_submit.available,false)
  assert.equal(adapter.capabilities.live_messages.available,false)
})
test('unknown versions isolate missing capability without reflection or writes',async()=>{
  const {ctx}=fixture()
  const adapter=createReadAdapter(ctx,{...versions,'dsh-agent-team-gui':'9.9.9'})
  assert.equal(adapter.capabilities.profiles_read.available,false)
  await assert.rejects(adapter.profiles(),/CAPABILITY_UNAVAILABLE/)
  assert.equal(adapter.capabilities.agentteams_state_read.available,false)
})
test('real loopback transport authenticates, rejects replay, origins and all command execution',async()=>{
  const b=await createLocalBridge(fixture().adapter,versions)
  try{
    assert.equal((await request(b,'/v1/rpc',{operation:'profiles'})).status,403)
    assert.equal((await request(b,'/v1/pair',{protocol:PROTOCOL,pairing_code:b.pairing_code,nonce:'nonce-long-enough-1234567'},{Origin:'https://evil.example'})).status,403)
    const paired=await pair(b); assert.equal(paired.status,200)
    assert.equal((await pair(b)).status,403)
    const auth={Authorization:'Bearer '+paired.body.value.session_token}
    assert.equal((await request(b,'/v1/rpc',{operation:'profiles'},auth)).body.value.source,'agentTeamGui')
    assert.equal((await request(b,'/v1/rpc',{operation:'execute',command:'agent_teams_status'},auth)).status,403)
    assert.equal((await request(b,'/v1/rpc',{operation:'disconnect'},auth)).status,200)
    assert.equal((await request(b,'/v1/rpc',{operation:'profiles'},auth)).status,403)
  }finally{await b.dispose()}
})
test('expired pairing/session and bounded failed attempts deny reads',async()=>{
  const b=await createLocalBridge(fixture().adapter,versions,{sessionMs:5})
  try{
    const result=await pair(b)
    await new Promise(r=>setTimeout(r,20))
    assert.equal((await request(b,'/v1/rpc',{operation:'profiles'},{Authorization:'Bearer '+result.body.value.session_token})).status,403)
  }finally{await b.dispose()}
  const c=await createLocalBridge(fixture().adapter,versions)
  try{
    for(let i=0;i<5;i++)await request(c,'/v1/pair',{protocol:PROTOCOL,pairing_code:'bad',nonce:'nonce-long-enough-1234567'})
    assert.equal((await pair(c)).status,403)
  }finally{await c.dispose()}
})
test('explicit-root observation preserves exact bytes and never treats definition IDs as live identities',async()=>{
  const dir=await mkdtemp(join(tmpdir(),'orgdna-readonly-'))
  try{
    await mkdir(join(dir,'team-a'))
    const filename=join(dir,'team-a','team.json')
    const row={id:'team-a',name:'Existing team',createdAt:1,taskSeq:1,captainSessionId:'captain-session',members:[{id:'actual-session',name:'Engineer',status:'idle'}],tasks:[{id:'task-1',status:'pending',assignee:'Engineer',attemptId:'attempt-1'}],halted:true}
    const bytes=JSON.stringify(row);await writeFile(filename,bytes)
    const result=await readTeamFiles(dir,'Existing team')
    assert.equal(result.teams.length,1);assert.equal(result.teams[0].halted,true)
    assert.equal(result.runtime_session_identity_verified,false)
    assert.equal(await readFile(filename,'utf8'),bytes)
    await symlink(dir,join(dir,'nested-link'))
    assert.equal((await readTeamFiles(dir)).teams.length,1)
    await assert.rejects(readTeamFiles(join(dir,'nested-link')),/UNSAFE_STATE_DIRECTORY/)
    await writeFile(filename,JSON.stringify({...row,id:'wrong-id'}))
    await assert.rejects(readTeamFiles(dir),/UNSUPPORTED_STATE_SCHEMA/)
  }finally{await rm(dir,{recursive:true,force:true})}
})
test('native registration only uses authenticated Connection registry and remains inert',async()=>{
  let route;let effects=0
  const ctx={get:name=>name==='connection'?{fetch:{register:r=>{route=r;return()=>{}}}}:undefined,effect:()=>effects++}
  const result=registerLiveBridge(ctx,{enabled:true})
  assert.equal(result.status,'PAIRING_UI_READY');assert.equal(route.path,'/api/orgdna-local-connect')
  const page=await route.fetch(new Request('http://127.0.0.1:9000/api/orgdna-local-connect'))
  assert.equal(page.status,200);assert.match(await page.text(),/Autorizar lectura/)
  assert.ok(page.headers.get('content-security-policy').includes("frame-ancestors 'none'"))
  const denied=await route.fetch(new Request('http://127.0.0.1:9000/api/orgdna-local-connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'pair',ack:'ALLOW_LOCAL_READ_ONLY_30_MINUTES'})}))
  assert.equal(denied.status,403);assert.equal(effects,1)
  assert.equal(registerLiveBridge({get:()=>undefined},{enabled:true}).status,'UNAVAILABLE')
  result.dispose()
})
