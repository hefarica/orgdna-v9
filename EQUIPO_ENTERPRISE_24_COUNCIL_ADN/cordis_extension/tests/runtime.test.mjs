import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { SharedLedger, validateConfig, PROTOCOL, SUPPORTED_TOOLS_VERSION } from '../runtime.mjs'
import { mount } from '../plugin.mjs'
import { inspectAgentTeamsMapping } from '../agentteams-adapter.mjs'

function setup(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'orgdna-cordis-test-'))
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }))
  const organization_id = randomUUID(), ids = Array.from({length: 24}, () => randomUUID()), sessions = ids.map(() => randomUUID())
  const config = {
    protocol: PROTOCOL, organization_id, namespace: 'orgdna_' + organization_id.replaceAll('-', ''),
    members: ids.map((member_id, index) => ({ member_id, name: `Member${index}`, reports_to: index ? ids[0] : 'OWNER_EXTERNAL' })),
    session_bindings: Object.fromEntries(sessions.map((id, index) => [id, ids[index]])),
    state_directory: directory, enabled: true, confirm_activation: 'ACTIVATE_EXISTING_ROSTER_ONLY', verified_tools_version: SUPPORTED_TOOLS_VERSION,
  }
  const exec = index => ({ agent: { id: sessions[index] }, signal: new AbortController().signal })
  return { config, ids, sessions, directory, exec }
}
function ledgerFor(t, fixture) { const ledger = new SharedLedger(fixture.config); t.after(() => ledger.close()); return ledger }
function write(ledger, operation, payload, execution, key = randomUUID()) { return ledger.call(operation, {payload, idempotency_key: key, expected_version: ledger.state.version}, execution) }
const ev = {locator: 'fixture://test-result', sha256: 'a'.repeat(64), summary: 'Synthetic offline test evidence; not real project evidence.'}

test('same24 roster, namespaced state and actual session identity', t => {
  const f=setup(t), ledger=ledgerFor(t,f)
  assert.equal(ledger.call('state', {}, f.exec(0)).member_count,24)
  assert.throws(() => ledger.call('state', {}, {agent:{id:f.ids[0]}}),/UNBOUND_SESSION/)
  assert.throws(() => write(ledger,'message',{to:'all',text:'spoof',actor:f.ids[1]},f.exec(0)),/fields/)
})
test('all24 communicate through single shared durable bus without agents', t => {
  const f=setup(t), ledger=ledgerFor(t,f)
  for(let i=0;i<24;i++) write(ledger,'message',{to:'all',text:`Observation ${i}`},f.exec(i))
  const state=ledger.call('state',{section:'messages'},f.exec(23))
  assert.equal(state.rows.length,24); assert.equal(new Set(state.rows.map(x=>x.actor)).size,24)
  ledger.close()
  const reopened=new SharedLedger(f.config); t.after(()=>reopened.close())
  assert.equal(reopened.state.messages.length,24)
})
test('duplicate mounts/processes fail before clobbering ledger', t => {
  const f=setup(t), ledger=ledgerFor(t,f)
  assert.throws(()=>new SharedLedger(f.config),/EEXIST/)
  assert.equal(ledger.state.version,0)
})
test('CAS and idempotency never duplicate acknowledged operations', t => {
  const f=setup(t), ledger=ledgerFor(t,f)
  const args={payload:{to:'all',text:'once'},expected_version:0,idempotency_key:'stable'}
  const first=ledger.call('message',args,f.exec(0)); assert.deepEqual(ledger.call('message',args,f.exec(0)),first)
  assert.equal(ledger.state.version,1)
  assert.throws(()=>ledger.call('message',{...args,payload:{to:'all',text:'changed'}},f.exec(0)),/reused/)
  assert.throws(()=>ledger.call('message',{...args,idempotency_key:'new'},f.exec(0)),/STALE_VERSION/)
})
test('direct mailbox read respects member audience', t => {
  const f=setup(t), ledger=ledgerFor(t,f)
  write(ledger,'message',{to:f.ids[1],text:'private coordination'},f.exec(0))
  assert.equal(ledger.call('state',{section:'messages'},f.exec(1)).total,1)
  assert.equal(ledger.call('state',{section:'messages'},f.exec(2)).total,0)
})
test('task ownership, dependencies, evidence and independent review enforced', t => {
  const f=setup(t), ledger=ledgerFor(t,f)
  const evidence=write(ledger,'evidence',ev,f.exec(1)).record.id
  const task=write(ledger,'task',{action:'create',title:'Test implementation',owner_member_id:f.ids[1]},f.exec(0)).record.id
  assert.throws(()=>write(ledger,'task',{action:'claim',task_id:task,note:'foreign'},f.exec(2)),/owner/)
  write(ledger,'task',{action:'claim',task_id:task,note:'claim'},f.exec(1))
  assert.throws(()=>write(ledger,'task',{action:'submit',task_id:task,note:'missing proof'},f.exec(1)),/evidence/)
  write(ledger,'task',{action:'submit',task_id:task,note:'submitted',evidence_ids:[evidence]},f.exec(1))
  assert.throws(()=>write(ledger,'task',{action:'accept',task_id:task,note:'self',evidence_ids:[evidence]},f.exec(1)),/Independent/)
  assert.throws(()=>write(ledger,'task',{action:'accept',task_id:task,note:'manager',evidence_ids:[evidence]},f.exec(0)),/Independent/)
  assert.equal(write(ledger,'task',{action:'accept',task_id:task,note:'peer review',evidence_ids:[evidence]},f.exec(2)).record.status,'accepted')
})
test('learning stays untrained and uninstalled after independent acceptance', t => {
  const f=setup(t), ledger=ledgerFor(t,f)
  const evidence=write(ledger,'evidence',ev,f.exec(1)).record.id
  const proposal=write(ledger,'learning',{action:'propose',title:'Improve method',failure:'Prior synthetic failure',proposed_change:'Test more branches',retest_result:'Reported result',evidence_ids:[evidence]},f.exec(1)).record.id
  const row=write(ledger,'learning',{action:'accept',learning_id:proposal,note:'Reference only',evidence_ids:[evidence]},f.exec(2)).record
  assert.equal(row.status,'accepted_for_reference'); assert.equal(row.installed,false); assert.equal(row.trained,false); assert.equal(row.effectiveness_verified,false)
})
test('cancellation and symlink safety fail without writes', t => {
  const f=setup(t), ledger=ledgerFor(t,f), controller=new AbortController(); controller.abort()
  assert.throws(()=>write(ledger,'message',{to:'all',text:'cancelled'},{agent:{id:f.sessions[0]},signal:controller.signal}),/Canceled/)
  assert.equal(ledger.state.version,0)
  ledger.close()
  fs.renameSync(ledger.file,ledger.file+'.saved'); fs.symlinkSync(ledger.file+'.saved',ledger.file)
  assert.throws(()=>new SharedLedger(f.config),/Symlink/)
})
test('native plugin lifecycle cleans own tools, no Service or host provider duplicates', t => {
  const f=setup(t), registry=new Map([['existing_user_tool',{name:'existing_user_tool'}]]), effects=[]
  const ctx={tools:{get:n=>registry.get(n),register:def=>{assert.ok(def.output);assert.ok(def.parameters);registry.set(def.name,def);return()=>registry.delete(def.name)}},effect(fn){effects.push(fn())}}
  const mounted=mount(ctx,f.config,x=>x)
  assert.equal(mount(ctx,f.config,x=>x),mounted); assert.equal(registry.size,7)
  assert.throws(()=>mount(ctx,{...f.config,session_bindings:{}},x=>x),/bindings/)
  effects.forEach(fn=>fn()); assert.equal(registry.size,1); assert.ok(registry.has('existing_user_tool'))
  assert.equal(fs.existsSync(path.join(f.directory,f.config.organization_id,'active.lock')),false)
})
test('different full UUID namespaces do not collide despite shared prefix',t=>{
  const f=setup(t), other=JSON.parse(JSON.stringify(f.config))
  other.organization_id=f.config.organization_id.slice(0,30)+'123456'
  other.namespace='orgdna_'+other.organization_id.replaceAll('-','')
  assert.notEqual(validateConfig(other).namespace,validateConfig(f.config).namespace)
})
test('native review bootstrap registers inert tools before trusted captain binding',async t=>{
  const f=setup(t), registry=new Map(),effects=[]
  const ctx={tools:{get:n=>registry.get(n),register:def=>{registry.set(def.name,def);return()=>registry.delete(def.name)}},effect(fn){effects.push(fn())}}
  const config={...f.config,session_bindings:{},native_stage_ui:{enabled:true}}
  const active=mount(ctx,config,x=>x)
  assert.equal(registry.size,6)
  await assert.rejects(registry.get(config.namespace+'_state').execute({},f.exec(0)),/UNBOUND_SESSION/)
  const unbind=active.ledger.bindRuntimeSession(f.sessions[0],f.ids[0])
  const state=await registry.get(config.namespace+'_state').execute({},f.exec(0))
  assert.equal(state.member_id,f.ids[0]);assert.equal(state.bound_session_count,1)
  unbind()
  await assert.rejects(registry.get(config.namespace+'_state').execute({},f.exec(0)),/UNBOUND_SESSION/)
  effects.forEach(fn=>fn())
})
test('mapping counts captain in N and never treats snapshot as live authentication',t=>{
  const f=setup(t),snapshot={id:'existing-team',captainSessionId:f.sessions[0],halted:true,members:f.ids.slice(1).map((id,i)=>({name:`m${i+1}`,id:f.sessions[i+1],status:'idle'})),tasks:[]}
  const mapping={team_id:'existing-team',captain_member_id:f.ids[0],member_names:Object.fromEntries(f.ids.slice(1).map((id,i)=>[`m${i+1}`,id]))}
  const report=inspectAgentTeamsMapping(f.config,snapshot,mapping)
  assert.equal(report.rows.length,24);assert.deepEqual(report.errors,[]);assert.equal(report.host_identity_verified,false);assert.equal(report.resumes_team,false)
  snapshot.members.push({name:'duplicate',id:randomUUID(),status:'idle'})
  assert.equal(inspectAgentTeamsMapping(f.config,snapshot,mapping).status,'BLOCKED_MAPPING')
})
