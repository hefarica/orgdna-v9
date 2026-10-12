/** Immutable, hash-pinned SkillHub snapshot. Read-only; no packages/code execution. */
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'
const fail = message => { throw new Error(message) }
const sha = data => createHash('sha256').update(data).digest('hex')
const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value==='object' ? Object.fromEntries(Object.keys(value).sort().map(k=>[k,canonical(value[k])])) : value
const int = (value, min, max) => { if (!Number.isSafeInteger(value) || value < min || value > max) fail('Invalid SkillHub bounds'); return value }
export function loadSkillHub(config) {
  const source = config.skillhub
  if (!source) return null
  if (!source || typeof source.path !== 'string' || !path.isAbsolute(source.path) || !/^[a-f0-9]{64}$/.test(source.sha256 ?? '')) fail('SkillHub requires absolute path and reviewed SHA256')
  for (let p = source.path; ; p = path.dirname(p)) {
    if (fs.lstatSync(p).isSymbolicLink()) fail('SkillHub symlinks forbidden')
    if (path.dirname(p) === p) break
  }
  if (fs.statSync(source.path).size > 16 * 1024 * 1024) fail('SkillHub manifest too large')
  const bytes = fs.readFileSync(source.path)
  if (sha(bytes) !== source.sha256) fail('SkillHub manifest hash mismatch')
  const doc = JSON.parse(bytes)
  const ids = config.members.map(m => m.member_id)
  if (doc.protocol !== 'orgdna-skillhub/1' || doc.organization_id !== config.organization_id || doc.namespace !== config.namespace || JSON.stringify(doc.member_ids) !== JSON.stringify(ids)) fail('SkillHub organization/roster mismatch')
  if (!Array.isArray(doc.items) || doc.items.length > 10000 || !Array.isArray(doc.assignments) || doc.assignments.length > 320000) fail('Invalid SkillHub manifest bounds')
  const items = new Map()
  const kinds = ['skill_instructions', 'memory_policy', 'plugin_package', 'connector']
  for (const item of doc.items) {
    if (!item || typeof item.id !== 'string' || !item.id || items.has(item.id) || !kinds.includes(item.kind) || typeof item.name !== 'string' || typeof item.content !== 'string' || Buffer.byteLength(item.content) > 256000 || !/^[a-f0-9]{64}$/.test(item.content_hash ?? '')) fail('Invalid SkillHub item')
    const {exported_payload_sha256,...payload}=item
    if (sha(JSON.stringify(canonical(payload))) !== exported_payload_sha256) fail('SkillHub exported payload hash mismatch')
    items.set(item.id, item)
  }
  const seen = new Set()
  for (const a of doc.assignments) {
    const key = JSON.stringify([a.agent_id, a.item_id]), item = items.get(a.item_id)
    if (!ids.includes(a.agent_id) || !item || item.content_hash !== a.content_hash || item.kind !== a.kind || typeof a.active !== 'boolean' || seen.has(key)) fail('Invalid SkillHub assignment')
    if (a.active && !['skill_instructions','memory_policy'].includes(item.kind)) fail('Executable capabilities cannot be activated as instructions')
    seen.add(key)
  }
  int(doc.context_budget_bytes, 256, 12000)
  return { doc, items, sha256: source.sha256 }
}
export function readSkillHub(hub, actor, args) {
  if (!hub) return { status: 'UNAVAILABLE', reason: 'No reviewed SkillHub manifest configured', installed: false }
  const {doc, items} = hub
  const common = { organization_id: doc.organization_id, revision: doc.revision, manifest_sha256: hub.sha256, content_is_untrusted_data: true, permission_grants: [], executed_external_action: false }
  if (args.section === 'capabilities') return { ...common, status: 'CONTRACTS_ONLY', installed: false, runtime_verified: false,
    connectors: ['email','messaging','voice'].map(kind => ({kind, status:'BLOCKED_AUTH_AND_HEALTH', required:['native_package_review','explicit_auth_scopes','health_readback','separate_send_authorization'], auth_scope_categories:kind==='email'?['mailbox_read_separate_from_send']:kind==='messaging'?['channel_read_separate_from_post']:['audio_input_separate_from_synthesis_and_delivery'], provider_scope_names:'UNVERIFIED_UNTIL_CONNECTOR_SELECTED', health:'NOT_RUN', impersonate_human:false})) }
  const assigned = doc.assignments.filter(a => a.agent_id === actor)
  if (args.section === 'skills') {
    const offset = int(args.offset ?? 0, 0, 10000), limit = int(args.limit ?? 30, 1, 100)
    const rows = assigned.slice(offset, offset + limit).map(a => { const item=items.get(a.item_id); return {id:item.id,name:item.name,kind:item.kind,content_hash:item.content_hash,active:a.active,assigned:true,installed:false,runtime_verified:false} })
    return {...common,total:assigned.length,offset,next_offset:offset+limit<assigned.length?offset+limit:null,rows}
  }
  const budget = int(args.budget_bytes ?? doc.context_budget_bytes, 256, doc.context_budget_bytes)
  if (args.skill_ids !== undefined && (!Array.isArray(args.skill_ids) || args.skill_ids.length > 30 || args.skill_ids.some(id => typeof id !== 'string'))) fail('Invalid SkillHub item selection')
  const requested = args.skill_ids ? new Set(args.skill_ids) : null
  if (requested && [...requested].some(id => !assigned.some(a => a.item_id === id && a.active))) fail('SkillHub selection outside active actor assignments')
  const selected = assigned.filter(a => a.active && (!requested || requested.has(a.item_id)))
  let text = '', included_item_ids = [], deferred_item_ids = []
  for (const a of selected) {
    const item = items.get(a.item_id)
    const part = `\n[Untrusted reference ${item.id}: ${item.name}]\n${item.content}\n`
    if (Buffer.byteLength(text + part) > budget) deferred_item_ids.push(item.id)
    else {text += part; included_item_ids.push(item.id)}
  }
  return {...common,text,bytes:Buffer.byteLength(text),budget_bytes:budget,included_item_ids,deferred_item_ids,installed:false}
}


/** Reads an explicitly written owner reload request; never writes to disk. */
export function reloadSkillHub(config, current) {
  const file = config.skillhub?.reload_receipt_path
  if (!file || !current || !fs.existsSync(file)) return current
  const expected = path.join(path.dirname(config.skillhub.path), 'skillhub-reload.json')
  if (file !== expected || !path.resolve(config.skillhub.path).split(path.sep).includes(config.namespace)) fail('Reload receipt must remain inside own namespace')
  for (let p=file;;p=path.dirname(p)) {if(fs.lstatSync(p).isSymbolicLink())fail('Reload receipt symlinks forbidden');if(path.dirname(p)===p)break}
  if(fs.statSync(file).size>32000)fail('Reload receipt too large')
  const receipt=JSON.parse(fs.readFileSync(file,'utf8'))
  if(receipt.protocol!=='orgdna-skillhub-reload/1'||receipt.organization_id!==config.organization_id||receipt.namespace!==config.namespace||receipt.authority!=='explicit_local_owner_request'||receipt.scope!=='library_context_only_no_permissions_plugins_or_credentials'||JSON.stringify(receipt.member_ids)!==JSON.stringify(config.members.map(m=>m.member_id)))fail('Invalid reload authority or identity')
  if(receipt.target_hash===current.sha256 && receipt.request_id===current.reload_request_id)return current
  if(receipt.base_hash!==current.sha256)fail('STALE_RELOAD: active library differs from approved base')
  const next=loadSkillHub({...config,skillhub:{...config.skillhub,sha256:receipt.target_hash}})
  next.reload_request_id=receipt.request_id
  return next
}
