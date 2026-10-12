import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { randomUUID,createHash } from 'node:crypto'
import { loadSkillHub,readSkillHub } from '../skillhub.mjs'
import { inventoryInstallation } from '../skillhub-preflight.mjs'
function fixture(t) {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'skillhub-test-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}))
 const org=randomUUID(),ids=Array.from({length:30},()=>randomUUID()), namespace='orgdna_'+org.replaceAll('-','')
 const doc={protocol:'orgdna-skillhub/1',organization_id:org,namespace,member_ids:ids,revision:3,context_budget_bytes:12000,
 items:Array.from({length:35},(_,i)=>({id:`item-${i}`,kind:'skill_instructions',name:`Skill ${i}`,content:'á'.repeat(500),content_hash:'a'.repeat(64)})),assignments:[]}
 for(const agent_id of ids)for(const item of doc.items)doc.assignments.push({agent_id,item_id:item.id,kind:item.kind,content_hash:item.content_hash,active:true})
 for(const item of doc.items)item.exported_payload_sha256=createHash('sha256').update(JSON.stringify(Object.fromEntries(Object.keys(item).sort().map(k=>[k,item[k]])))).digest('hex')
 const file=path.join(dir,'library.json'); const write=()=>{const bytes=JSON.stringify(doc);fs.writeFileSync(file,bytes);return createHash('sha256').update(bytes).digest('hex')}
 const config={organization_id:org,namespace,members:ids.map(member_id=>({member_id})),skillhub:{path:file,sha256:write()}}
 return{dir,doc,ids,config,write}
}
test('30 existing identities, paginated metadata and bounded UTF8 lazy context',t=>{
 const f=fixture(t),hub=loadSkillHub(f.config)
 for(const id of f.ids){const first=readSkillHub(hub,id,{section:'skills',limit:10});assert.equal(first.rows.length,10);assert.equal(first.next_offset,10);assert.equal(first.total,35);assert.equal(first.rows[0].content,undefined)}
 const ctx=readSkillHub(hub,f.ids[0],{section:'skill_context',budget_bytes:2200})
 assert.ok(ctx.bytes<=2200);assert.equal(ctx.bytes,Buffer.byteLength(ctx.text));assert.ok(ctx.deferred_item_ids.length>0)
 assert.throws(()=>readSkillHub(hub,f.ids[0],{section:'skill_context',budget_bytes:12001}),/bounds/)
 assert.throws(()=>readSkillHub(hub,f.ids[0],{section:'skill_context',skill_ids:['foreign']}),/outside/)
})
test('hash, roster and executable instruction activation fail closed',t=>{
 const f=fixture(t);fs.appendFileSync(f.config.skillhub.path,' ');assert.throws(()=>loadSkillHub(f.config),/hash mismatch/)
 f.config.skillhub.sha256=f.write();f.config.members.pop();assert.throws(()=>loadSkillHub(f.config),/roster/)
 f.config.members=f.ids.map(member_id=>({member_id}));f.doc.items[0].kind='connector';delete f.doc.items[0].exported_payload_sha256;f.doc.items[0].exported_payload_sha256=createHash('sha256').update(JSON.stringify(Object.fromEntries(Object.keys(f.doc.items[0]).sort().map(k=>[k,f.doc.items[0][k]])))).digest('hex');f.doc.assignments.filter(a=>a.item_id==='item-0').forEach(a=>a.kind='connector');f.config.skillhub.sha256=f.write();assert.throws(()=>loadSkillHub(f.config),/cannot be activated/)
})
test('connector contracts never claim installed/authorized or send',t=>{
 const f=fixture(t),result=readSkillHub(loadSkillHub(f.config),f.ids[0],{section:'capabilities'})
 assert.equal(result.installed,false);assert.equal(result.runtime_verified,false);assert.equal(result.executed_external_action,false);assert.equal(result.connectors.length,3)
 assert.ok(result.connectors.every(c=>c.status==='BLOCKED_AUTH_AND_HEALTH'))
})
test('missing runtime preflight stays pending without spawning or mutating',t=>{
 const f=fixture(t),r=inventoryInstallation(f.dir,f.dir)
 assert.equal(r.status,'PENDING_LOCAL_VERIFICATION');assert.equal(r.processes_started,0);assert.equal(r.plugins_installed,0);assert.equal(r.runtime_activated,false)
 assert.ok(r.pending.some(p=>p.includes('No launch command')))
})

import {publishPackage,rollbackPackage} from '../skillhub-package.mjs'
test('standalone publication hashes bytes, refuses overwrite and foreign rollback, keeps other plugins',t=>{
 const f=fixture(t),source=path.join(f.dir,'source'),dest=path.join(f.dir,'published');fs.mkdirSync(source);fs.mkdirSync(dest)
 fs.writeFileSync(path.join(dest,'other-plugin.json'),'untouched')
 const data=Buffer.from('// no execution');fs.writeFileSync(path.join(source,'entry.mjs'),data)
 fs.writeFileSync(path.join(source,'addon-manifest.json'),JSON.stringify({protocol:'orgdna-cordis/1',organization_id:f.doc.organization_id,namespace:f.doc.namespace,file_sha256:{'entry.mjs':createHash('sha256').update(data).digest('hex')}}))
 const preview=publishPackage(source,dest,'v1');assert.equal(fs.existsSync(preview.target),false)
 const result=publishPackage(source,dest,'v1',{approve:true});assert.equal(result.status,'PUBLISHED_BYTES_VERIFIED_NOT_ACTIVATED');assert.equal(result.receipt.runtime_activated,false)
 assert.throws(()=>publishPackage(source,dest,'v1',{approve:true}),/exists/)
 fs.writeFileSync(path.join(result.target,'foreign.txt'),'leave me');assert.throws(()=>rollbackPackage(result.target,{approve:true}),/Foreign/);fs.unlinkSync(path.join(result.target,'foreign.txt'))
 assert.equal(rollbackPackage(result.target).status,'ROLLBACK_PREVIEW');assert.equal(fs.existsSync(result.target),true)
 rollbackPackage(result.target,{approve:true});assert.equal(fs.readFileSync(path.join(dest,'other-plugin.json'),'utf8'),'untouched')
})

import {SharedLedger, PROTOCOL} from '../runtime.mjs'
test('explicit two-stage CAS publication plus owner reload receipt updates only memory and returns hash',t=>{
 const f=fixture(t),own=path.join(f.dir,f.doc.namespace);fs.mkdirSync(own)
 f.config.skillhub.path=path.join(own,'skillhub-library.json');fs.writeFileSync(f.config.skillhub.path,JSON.stringify(f.doc))
 f.config.skillhub.reload_receipt_path=path.join(own,'skillhub-reload.json')
 const session=randomUUID();Object.assign(f.config,{protocol:PROTOCOL,state_directory:path.join(f.dir,'state'),session_bindings:{[session]:f.ids[0]}})
 const ledger=new SharedLedger(f.config);t.after(()=>ledger.close());const execution={agent:{id:session}}
 const old=ledger.call('state',{section:'summary'},execution).skillhub.manifest_sha256
 const ledgerBytes=fs.readFileSync(ledger.file)
 f.doc.revision=4;const bytes=JSON.stringify(f.doc),next=createHash('sha256').update(bytes).digest('hex');fs.writeFileSync(f.config.skillhub.path,bytes)
 // Merely publishing different bytes does NOT authorize runtime reload.
 assert.equal(ledger.call('state',{section:'summary'},execution).skillhub.manifest_sha256,old)
 const request={protocol:'orgdna-skillhub-reload/1',organization_id:f.doc.organization_id,namespace:f.doc.namespace,member_ids:f.ids,base_hash:old,target_hash:next,request_id:randomUUID(),authority:'explicit_local_owner_request',scope:'library_context_only_no_permissions_plugins_or_credentials'}
 fs.writeFileSync(f.config.skillhub.reload_receipt_path,JSON.stringify(request))
 const result=ledger.call('state',{section:'summary'},execution)
 assert.equal(result.skillhub.manifest_sha256,next);assert.equal(result.skillhub.reload_request_id,request.request_id);assert.equal(result.skillhub.revision,4)
 assert.deepEqual(fs.readFileSync(ledger.file),ledgerBytes)
 assert.equal(ledger.call('state',{section:'summary'},execution).skillhub.manifest_sha256,next)
 // A stale or different organization request cannot replace current snapshot.
 fs.writeFileSync(f.config.skillhub.reload_receipt_path,JSON.stringify({...request,target_hash:old,base_hash:old,request_id:randomUUID()}))
 assert.throws(()=>ledger.call('state',{section:'summary'},execution),/STALE_RELOAD/)
 assert.equal(ledger.skillhub.sha256,next)
})
