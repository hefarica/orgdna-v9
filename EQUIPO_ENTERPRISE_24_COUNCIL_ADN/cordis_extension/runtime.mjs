/** Offline shared coordination ledger. No agent engine, network, or executable learning. */
import { createHash, randomUUID } from 'node:crypto'
import * as fs from 'node:fs'
import path from 'node:path'
import { loadSkillHub, readSkillHub, reloadSkillHub } from './skillhub.mjs'

export const PROTOCOL = 'orgdna-cordis/1'
export const SUPPORTED_TOOLS_VERSION = '0.2.1-alpha.1'
export const SUPPORTED_TOOLS_VERSIONS = [SUPPORTED_TOOLS_VERSION, '0.2.0-rc.2', '0.0.1-rc.1']
export const OPERATIONS = ['state', 'message', 'task', 'evidence', 'memory', 'learning', 'channel', 'team_memory']
// GenTeam P2/P4: semantica portada de engine/team_channel.py y engine/team_memory.py
// (port REA de agentscope-ai/agentscope@26ec620, Apache-2.0). Mismos invariantes:
// mencion validada contra el roster (fail-closed), inbox por miembro con drain FIFO
// destructivo y ttl, fragmentos .md inmutables con registro embebido e indice
// MEMORY.md regenerado tras cada alta con recorte proporcional + backtrack de 10.
const MENTION_RE = /^@(\S+)(?:[ \t]+(.*))?$/
const MEMORY_PLANES = ['execution', 'project', 'organizational', 'personal']
const MEMORY_ID_RE = /^[a-z0-9][a-z0-9._-]{1,63}$/
const MEMORY_INDEX_BUDGET_BYTES = 6000
const MEMORY_EMPTY_INDEX = 'Your MEMORY.md is currently empty. When you save new memories, they will appear here.'
const MEMORY_TRUNCATED_MARK = '<<<TRUNCATED>>>'
const CHANNEL_DEFAULT_DRAIN = 100
const CHANNEL_MAX_TEXT = 6000
const CHANNEL_MAX_TOPIC = 160
const CHANNEL_MAX_TITLE = 300
const CHANNEL_MAX_DEPENDENCIES = 32
const MAX_BYTES = 8 * 1024 * 1024
const MAX_EVENTS = 10000
const copy = value => JSON.parse(JSON.stringify(value))
const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex')
const fail = message => { throw new Error(message) }
const text = (value, key, max = 6000) => {
  if (typeof value !== 'string' || !value.trim() || value.length > max || /[\u0000-\u0008\u000b-\u001f]/.test(value)) fail(`Invalid ${key}`)
  return value.trim()
}
const integer = (value, key, min = 0, max = MAX_EVENTS) => {
  if (!Number.isSafeInteger(value) || value < min || value > max) fail(`Invalid ${key}`)
  return value
}
const keys = (value, allowed) => {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(k => !allowed.includes(k))) fail('Unknown or invalid payload fields')
}
const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
function noSymlink(file, allowMissing = true) {
  const absolute = path.resolve(file)
  let current = path.parse(absolute).root
  for (const part of absolute.slice(current.length).split(path.sep).filter(Boolean)) {
    current = path.join(current, part)
    try { if (fs.lstatSync(current).isSymbolicLink()) fail('Symlink paths are not allowed') }
    catch (e) { if (e.code === 'ENOENT' && allowMissing) return; throw e }
  }
}

export function validateConfig(config) {
  if (!config || config.protocol !== PROTOCOL || !uuid(config.organization_id)) fail('Invalid addon identity')
  if (!Array.isArray(config.members) || config.members.length < 1 || config.members.length > 32) fail('Invalid roster')
  const ids = config.members.map(member => member.member_id)
  if (ids.some(id => !uuid(id)) || new Set(ids).size !== ids.length) fail('Duplicate or invalid member IDs')
  if (config.namespace !== 'orgdna_' + config.organization_id.replaceAll('-', '')) fail('Namespace mismatch')
  const bindings = config.session_bindings
  if (!bindings || typeof bindings !== 'object' || Array.isArray(bindings)) fail('session_bindings must be an object')
  if (Object.entries(bindings).some(([session, member]) => !uuid(session) || !ids.includes(member))) fail('Session binding outside roster')
  if (new Set(Object.values(bindings)).size !== Object.values(bindings).length) fail('One live session per member; duplicate binding refused')
  if (typeof config.state_directory !== 'string' || !path.isAbsolute(config.state_directory)) fail('An explicit absolute addon state_directory is required')
  return copy(config)
}

export class SharedLedger {
  constructor(configuration) {
    this.config = validateConfig(configuration)
    this.skillhub = loadSkillHub(this.config)
    this.members = new Map(this.config.members.map(member => [member.member_id, member]))
    this.closed = false
    this.directory = path.join(this.config.state_directory, this.config.organization_id)
    noSymlink(this.directory)
    fs.mkdirSync(this.directory, { recursive: true, mode: 0o700 })
    this.file = path.join(this.directory, 'coordination.json')
    this.lock = path.join(this.directory, 'active.lock')
    noSymlink(this.file); noSymlink(this.lock)
    // A stale lock is deliberately NOT stolen. Owner must inspect recovery guide.
    this.lockFd = fs.openSync(this.lock, 'wx', 0o600)
    try {
      fs.writeFileSync(this.lockFd, JSON.stringify({ pid: process.pid, started_at: new Date().toISOString(), organization_id: this.config.organization_id }))
      this.state = fs.existsSync(this.file) ? this.read() : {
        protocol: PROTOCOL, organization_id: this.config.organization_id,
        member_ids: [...this.members.keys()], version: 0,
        messages: [], tasks: [], evidence: [], memory: [], learning: [], audit: [], receipts: {},
        inboxes: {},
      }
      if (!fs.existsSync(this.file)) this.persist(this.state)
    } catch (error) { this.close(); throw error }
  }
  read() {
    if (fs.statSync(this.file).size > MAX_BYTES) fail('Ledger exceeds safety limit')
    const state = JSON.parse(fs.readFileSync(this.file, 'utf8'))
    if (state.protocol !== PROTOCOL || state.organization_id !== this.config.organization_id ||
        JSON.stringify(state.member_ids) !== JSON.stringify([...this.members.keys()]) ||
        !Number.isSafeInteger(state.version) || state.version < 0 ||
        ['messages', 'tasks', 'evidence', 'memory', 'learning', 'audit'].some(k => !Array.isArray(state[k])) ||
        (state.inboxes !== undefined && (typeof state.inboxes !== 'object' || Array.isArray(state.inboxes) || Object.keys(state.inboxes).some(k => !this.members.has(k)))) ||
        !state.receipts || typeof state.receipts !== 'object') fail('Ledger identity/schema mismatch; no migration or overwrite performed')
    if (state.inboxes === undefined) state.inboxes = {}
    return state
  }
  persist(value) {
    const data = JSON.stringify(value)
    if (Buffer.byteLength(data) > MAX_BYTES) fail('Ledger full; archive explicitly before continuing')
    noSymlink(this.file); noSymlink(this.directory, false)
    const temp = path.join(this.directory, `.write-${randomUUID()}.tmp`)
    let fd
    try {
      fd = fs.openSync(temp, 'wx', 0o600)
      fs.writeFileSync(fd, data); fs.fsyncSync(fd); fs.closeSync(fd); fd = undefined
      fs.renameSync(temp, this.file)
    } finally {
      if (fd !== undefined) fs.closeSync(fd)
      if (fs.existsSync(temp)) fs.unlinkSync(temp)
    }
  }
  close() {
    if (this.closed) return
    this.closed = true
    if (this.lockFd !== undefined) {
      const held = fs.fstatSync(this.lockFd)
      fs.closeSync(this.lockFd)
      this.lockFd = undefined
      try {
        const current = fs.lstatSync(this.lock)
        if (current.ino === held.ino && current.dev === held.dev && !current.isSymbolicLink()) fs.unlinkSync(this.lock)
      } catch (error) { if (error.code !== 'ENOENT') throw error }
    }
  }
  actor(execution) {
    if (this.closed) fail('Addon unloaded')
    if (execution?.signal?.aborted) fail('Canceled before ledger operation')
    const sessionId = execution?.agent?.id
    const memberId = Object.hasOwn(this.config.session_bindings, sessionId ?? '') ? this.config.session_bindings[sessionId] : null
    if (!this.members.has(memberId)) fail('UNBOUND_SESSION: owner must verify and bind this live session to an existing roster member')
    return memberId
  }
  bindRuntimeSession(sessionId, memberId) {
    if (this.closed || !uuid(sessionId) || !this.members.has(memberId)) fail('Invalid trusted runtime binding')
    const existing=this.config.session_bindings[sessionId]
    if(existing===memberId)return()=>{}
    if(existing || Object.values(this.config.session_bindings).includes(memberId)) fail('Conflicting live session binding; no identity replaced')
    this.config.session_bindings[sessionId]=memberId
    let disposed=false
    return()=>{if(disposed)return;disposed=true;if(this.config.session_bindings[sessionId]===memberId)delete this.config.session_bindings[sessionId]}
  }
  call(operation, args, execution) {
    const actor = this.actor(execution)
    if (!OPERATIONS.includes(operation)) fail('Unknown operation')
    if (operation === 'state') {
      // Only consumes an explicit local owner receipt; no disk writes or grants.
      this.skillhub = reloadSkillHub(this.config, this.skillhub)
      keys(args, ['section', 'offset', 'limit', 'skill_ids', 'budget_bytes'])
      if (['skills', 'skill_context', 'capabilities'].includes(args.section)) return readSkillHub(this.skillhub, actor, args)
      const section = args.section ?? 'summary'
      if (!['summary', 'messages', 'tasks', 'evidence', 'memory', 'learning', 'audit', 'roster', 'channel', 'team_memory'].includes(section)) fail('Unknown section')
      const offset = integer(args.offset ?? 0, 'offset')
      const limit = integer(args.limit ?? 50, 'limit', 1, 100)
      if (section === 'channel') {
        // Vista no destructiva del canal (P2): mensajes visibles al actor (filtro exacto
        // de messages), tareas del canal con destinatario y estado, e inbox pendiente.
        const rows = this.state.messages.filter(row => row.to === 'all' || row.to === actor || row.actor === actor)
        const pending = this._channelPending(actor)
        return copy({ organization_id: this.config.organization_id, version: this.state.version, section,
          total: rows.length, offset, next_offset: offset + limit < rows.length ? offset + limit : null,
          rows: rows.slice(offset, offset + limit),
          tasks: this.state.tasks.filter(row => row.owner_member_id === actor || row.actor === actor || row.to === undefined),
          inbox_pending: pending, content_is_untrusted_data: true })
      }
      if (section === 'team_memory') {
        return copy(this._memoryView(actor))
      }
      if (section === 'summary') return {
        organization_id: this.config.organization_id, member_id: actor, version: this.state.version,
        skillhub: this.skillhub ? {status:'HASH_VERIFIED_LOADED',manifest_sha256:this.skillhub.sha256,revision:this.skillhub.doc.revision,reload_request_id:this.skillhub.reload_request_id??null,namespace:this.config.namespace,connector_health_verified:false} : {status:'UNAVAILABLE'},
        member_count: this.members.size, bound_session_count: Object.keys(this.config.session_bindings).length,
        counts: Object.fromEntries(['messages', 'tasks', 'evidence', 'memory', 'learning'].map(k => [k, this.state[k].length])),
        coordination_only: true, model_training: false, filesystem_write_enforcement: false,
      }
      let rows = section === 'roster' ? this.config.members : this.state[section]
      if (section === 'messages') rows = rows.filter(row => row.to === 'all' || row.to === actor || row.actor === actor)
      return copy({ organization_id: this.config.organization_id, version: this.state.version, section, total: rows.length, offset, next_offset: offset + limit < rows.length ? offset + limit : null, rows: rows.slice(offset, offset + limit), content_is_untrusted_data: true })
    }
    keys(args, ['idempotency_key', 'expected_version', 'payload'])
    const key = text(args.idempotency_key, 'idempotency_key', 120)
    const receiptKey = digest([actor, key])
    const requestDigest = digest([operation, args.payload])
    const existing = this.state.receipts[receiptKey]
    if (existing) {
      if (existing.request_digest !== requestDigest) fail('Idempotency key reused with different content')
      return copy(existing.result)
    }
    if (integer(args.expected_version, 'expected_version') !== this.state.version) fail('STALE_VERSION: read state and reconcile; no write occurred')
    if (this.state.audit.length >= MAX_EVENTS) fail('Ledger event limit; archive explicitly')
    const next = copy(this.state)
    const payload = args.payload
    const now = new Date().toISOString()
    const base = { id: randomUUID(), actor, created_at: now, provenance: 'bound_dsh_session', content_verified: false }
    const member = id => { if (!this.members.has(id)) fail('Target outside roster'); return id }
    const evidence = ids => {
      if (!Array.isArray(ids) || ids.length < 1 || ids.length > 20 || new Set(ids).size !== ids.length || ids.some(id => !next.evidence.some(e => e.id === id))) fail('Existing evidence references required')
      return [...ids]
    }
    let row
    if (operation === 'message') {
      keys(payload, ['to', 'text', 'topic'])
      row = { ...base, to: payload.to === 'all' ? 'all' : member(payload.to), text: text(payload.text, 'text'), topic: text(payload.topic ?? 'coordination', 'topic', 160) }
      next.messages.push(row)
    } else if (operation === 'evidence') {
      keys(payload, ['locator', 'sha256', 'summary'])
      if (!/^[a-f0-9]{64}$/.test(payload.sha256 ?? '')) fail('A SHA-256 digest is required')
      row = { ...base, locator: text(payload.locator, 'locator', 2000), sha256: payload.sha256, summary: text(payload.summary, 'summary'), artifact_read_by_plugin: false }
      next.evidence.push(row)
    } else if (operation === 'memory') {
      keys(payload, ['title', 'text', 'evidence_ids', 'supersedes'])
      const supersedes = payload.supersedes ?? null
      if (supersedes && !next.memory.some(m => m.id === supersedes)) fail('Unknown memory revision')
      row = { ...base, title: text(payload.title, 'title', 160), text: text(payload.text, 'text'), evidence_ids: evidence(payload.evidence_ids), supersedes, status: 'recorded_not_verified' }
      next.memory.push(row)
    } else if (operation === 'task') {
      keys(payload, ['action', 'task_id', 'title', 'owner_member_id', 'depends_on', 'evidence_ids', 'note'])
      if (payload.action === 'create') {
        const dependencies = payload.depends_on ?? []
        if (!Array.isArray(dependencies) || dependencies.length > 32 || new Set(dependencies).size !== dependencies.length || dependencies.some(id => !next.tasks.some(t => t.id === id))) fail('Dependencies must be existing unique tasks')
        row = { ...base, title: text(payload.title, 'title', 300), owner_member_id: member(payload.owner_member_id), depends_on: dependencies, status: 'open', evidence_ids: [], history: [] }
        next.tasks.push(row)
      } else {
        row = next.tasks.find(t => t.id === payload.task_id)
        if (!row) fail('Unknown task')
        const action = payload.action
        if (['claim', 'block', 'submit'].includes(action) && actor !== row.owner_member_id) fail('Only assigned owner may act')
        if (action === 'claim' && ['open', 'blocked', 'rejected'].includes(row.status)) {
          if (row.depends_on.some(id => next.tasks.find(t => t.id === id).status !== 'accepted')) fail('Dependencies not accepted')
          row.status = 'claimed'
        } else if (action === 'block' && row.status === 'claimed') row.status = 'blocked'
        else if (action === 'submit' && row.status === 'claimed') { row.evidence_ids = evidence(payload.evidence_ids); row.status = 'submitted' }
        else if (['accept', 'reject'].includes(action) && row.status === 'submitted') {
          this.independent(actor, row.owner_member_id)
          row.review_evidence_ids = evidence(payload.evidence_ids)
          row.status = action === 'accept' ? 'accepted' : 'rejected'
          row.reviewer_member_id = actor
        } else fail('Invalid task transition')
        row.history.push({ actor, action, at: now, note: text(payload.note, 'note'), evidence_ids: payload.evidence_ids ?? [] })
        row.updated_at = now
      }
    } else if (operation === 'learning') {
      keys(payload, ['action', 'learning_id', 'title', 'failure', 'proposed_change', 'retest_result', 'evidence_ids', 'note'])
      if (payload.action === 'propose') {
        row = { ...base, title: text(payload.title, 'title', 160), failure: text(payload.failure, 'failure'), proposed_change: text(payload.proposed_change, 'proposed_change'), retest_result: text(payload.retest_result, 'retest_result'), evidence_ids: evidence(payload.evidence_ids), status: 'proposed', installed: false, trained: false, effectiveness_verified: false, history: [] }
        next.learning.push(row)
      } else {
        row = next.learning.find(l => l.id === payload.learning_id)
        if (!row || row.status !== 'proposed') fail('Unknown or reviewed learning proposal')
        if (!['accept', 'reject'].includes(payload.action)) fail('Invalid learning transition')
        this.independent(actor, row.actor)
        row.status = payload.action === 'accept' ? 'accepted_for_reference' : 'rejected'
        row.history.push({ actor, at: now, note: text(payload.note, 'note'), evidence_ids: evidence(payload.evidence_ids) })
      }
    } else if (operation === 'channel') {
      // P2: canal dirigido + @mencion + asignacion tipo colega. Port de engine/team_channel.py
      // (agentscope-ai/agentscope@26ec620: _team_pipeline.py + _in_memory_message_bus.py).
      keys(payload, ['action', 'to', 'text', 'topic', 'ttl_secs', 'member', 'task', 'title',
                     'depends_on', 'max_count'])
      const action = payload.action
      if (action === 'publish') {
        const target = payload.to === 'all' ? 'all' : member(payload.to)
        const body = text(payload.text, 'text', CHANNEL_MAX_TEXT)
        const topicValue = text(payload.topic ?? 'coordination', 'topic', CHANNEL_MAX_TOPIC)
        const ttl = payload.ttl_secs ?? null
        if (ttl !== null && (typeof ttl !== 'number' || !Number.isFinite(ttl) || ttl < 0)) fail('Invalid ttl_secs')
        // Validacion completa ANTES de mutar (fail-closed): la mencion debe existir.
        const mention = MENTION_RE.exec(body)
        let preparedTask = null
        if (mention !== null) {
          const mentioned = this._resolveChannelRef(mention[1])
          if (!mentioned) fail(`unknown_member: la mencion @${mention[1]} no esta en el roster`)
          preparedTask = this._prepareChannelTask(actor, mentioned, (mention[2] ?? '').trim(), payload.title ?? null, payload.depends_on ?? [], next)
        }
        const message = { ...base, to: target, text: body, topic: topicValue }
        next.messages.push(message)
        let task = null
        if (preparedTask !== null) {
          task = { ...preparedTask, id: randomUUID(), actor, created_at: now,
                   provenance: 'bound_dsh_session', content_verified: false, status: 'open',
                   evidence_ids: [], history: [] }
          next.tasks.push(task)
        }
        next.inboxes ??= {}
        const recipients = target === 'all' ? [...this.members.keys()] : [target]
        const expireAt = ttl === null ? null : Date.now() / 1000 + ttl
        for (const recipient of recipients) {
          next.inboxes[recipient] ??= []
          // Purga de expirados ANTES del append (bus Mode A) y fan-out de 'all' por destinatario.
          next.inboxes[recipient] = next.inboxes[recipient].filter(entry => entry.expire_at === null || entry.expire_at > Date.now() / 1000)
          next.inboxes[recipient].push({ message_id: message.id, expire_at: expireAt })
        }
        row = { id: randomUUID(), message, task, inbox_pending: this._channelPendingEntries(next, actor).length }
      } else if (action === 'inbox') {
        // Drain destructivo FIFO del inbox del actor; el resto persiste (Mode A).
        const maxCount = integer(payload.max_count ?? CHANNEL_DEFAULT_DRAIN, 'max_count', 1, 1000)
        next.inboxes ??= {}
        const alive = (next.inboxes[actor] ?? []).filter(entry => entry.expire_at === null || entry.expire_at > Date.now() / 1000)
        const deliver = alive.slice(0, maxCount)
        next.inboxes[actor] = alive.slice(maxCount)
        const byId = new Map(next.messages.map(entry => [entry.id, entry]))
        row = { id: randomUUID(), drained: deliver.map(entry => byId.get(entry.message_id)).filter(Boolean),
                remaining: next.inboxes[actor].length }
      } else if (action === 'inbox_clear') {
        next.inboxes ??= {}
        const cleared = (next.inboxes[actor] ?? []).length
        delete next.inboxes[actor]
        row = { id: randomUUID(), cleared }
      } else if (action === 'assign') {
        const owner = this._resolveChannelRef(payload.member)
        if (!owner) fail('unknown_member: el destinatario no esta en el roster')
        const taskText = text(payload.task, 'task', CHANNEL_MAX_TEXT)
        row = { ...this._prepareChannelTask(actor, owner, taskText, payload.title ?? null, payload.depends_on ?? [], next),
                id: randomUUID(), actor, created_at: now, provenance: 'bound_dsh_session',
                content_verified: false, status: 'open', evidence_ids: [], history: [] }
        next.tasks.push(row)
      } else fail('Invalid channel action')
    } else if (operation === 'team_memory') {
      // P4: memoria Markdown de equipo. Port de engine/team_memory.py (agentscope-ai/
      // agentscope@26ec620: _middleware.py filesystem memory). Fragmentos inmutables con
      // registro embebido + indice MEMORY.md regenerado tras cada alta; la gobernanza
      // completa de planos/permisos vive en el engine Python, aqui el ledger es la
      // autoridad local del addon.
      keys(payload, ['action', 'memory_id', 'plane', 'content', 'description', 'ttl_seconds'])
      if (payload.action !== 'append') fail('Invalid team_memory action')
      const memoryId = payload.memory_id
      if (typeof memoryId !== 'string' || !MEMORY_ID_RE.test(memoryId)) fail('Invalid memory_id')
      if (!MEMORY_PLANES.includes(payload.plane)) fail('Invalid plane')
      const content = text(payload.content, 'content', CHANNEL_MAX_TEXT)
      const description = payload.description === undefined ? content.slice(0, 120) : text(payload.description, 'description', 160)
      const ttl = payload.ttl_seconds ?? null
      if (ttl !== null && (typeof ttl !== 'number' || !Number.isFinite(ttl) || ttl < 0)) fail('Invalid ttl_seconds')
      const fragment = this._appendTeamMemory(actor, payload.plane, memoryId, content, description, ttl, now)
      const view = this._memoryView(actor)
      row = { id: randomUUID(), memory_id: memoryId, plane: payload.plane, member: actor, fragment,
              index_path: view.index_path, fragments: view.fragments.length, recorded_at: now }
    }
    next.version += 1
    const result = { organization_id: next.organization_id, version: next.version, record: copy(row), executed_external_action: false }
    next.audit.push({ seq: next.version, actor, operation, record_id: row.id, at: now, request_digest: requestDigest })
    next.receipts[receiptKey] = { request_digest: requestDigest, result }
    // Cancellation checked again before the single synchronous durable commit.
    this.actor(execution)
    this.persist(next)
    this.state = next
    return copy(result)
  }
  _resolveChannelRef(ref) {
    // member_id exacto primero, luego name exacto (resolve() de engine/team_channel.py).
    if (typeof ref !== 'string') return null
    if (this.members.has(ref)) return ref
    for (const member of this.members.values()) if (member.name === ref) return member.member_id
    return null
  }
  _prepareChannelTask(actor, owner, prompt, title, dependsOn, next) {
    // Validacion sin mutar (fail-closed): prompt requerido, title derivado, deps existentes.
    const promptValue = text(prompt, 'task', CHANNEL_MAX_TEXT)
    const titleValue = title === null || title === undefined || title === ''
      ? promptValue.slice(0, CHANNEL_MAX_TITLE) : text(title, 'title', CHANNEL_MAX_TITLE)
    const dependencies = dependsOn ?? []
    if (!Array.isArray(dependencies) || dependencies.length > CHANNEL_MAX_DEPENDENCIES ||
        new Set(dependencies).size !== dependencies.length ||
        dependencies.some(id => !next.tasks.some(task => task.id === id))) fail('Dependencies must be existing unique tasks')
    return { actor, owner_member_id: owner, title: titleValue, prompt: promptValue, depends_on: dependencies }
  }
  _channelPendingEntries(state, actor) {
    state.inboxes ??= {}
    return (state.inboxes[actor] ?? []).filter(entry => entry.expire_at === null || entry.expire_at > Date.now() / 1000)
  }
  _channelPending(actor) { return this._channelPendingEntries(this.state, actor).length }
  _memoryDir(member) { return path.join(this.directory, 'team-memory', member) }
  _memoryRecord(member, plane, memoryId, content, description, ttl, actor, now) {
    return { memory_id: memoryId, plane, tenant: this.config.organization_id, member,
             actor, recorded_at: now, description, content, ttl_seconds: ttl }
  }
  _liveFragments(member) {
    const dir = this._memoryDir(member)
    const rows = []
    for (const plane of MEMORY_PLANES) {
      const planeDir = path.join(dir, plane)
      if (!fs.existsSync(planeDir)) continue
      for (const name of fs.readdirSync(planeDir)) {
        if (!name.endsWith('.md')) continue
        const raw = fs.readFileSync(path.join(planeDir, name), 'utf8')
        const match = /<!-- team_memory:record (.*) -->/.exec(raw)
        if (match === null) continue
        try { rows.push(JSON.parse(match[1])) } catch { /* archivo sin registro valido: se ignora */ }
      }
    }
    const nowSeconds = Date.now() / 1000
    return rows
      .filter(record => typeof record.recorded_at_epoch !== 'number' || record.ttl_seconds === null ||
                        record.recorded_at_epoch + record.ttl_seconds > nowSeconds)
      .sort((left, right) => String(right.recorded_at).localeCompare(String(left.recorded_at)) || String(right.memory_id).localeCompare(String(left.memory_id)))
  }
  _appendTeamMemory(actor, plane, memoryId, content, description, ttl, now) {
    const record = this._memoryRecord(actor, plane, memoryId, content, description, ttl, actor, now)
    record.recorded_at_epoch = Date.now() / 1000
    const fragmentDir = path.join(this._memoryDir(actor), plane)
    noSymlink(fragmentDir, true)
    fs.mkdirSync(fragmentDir, { recursive: true, mode: 0o700 })
    const fragmentPath = path.join(fragmentDir, `${memoryId}.md`)
    const canonical = JSON.stringify(record)
    const body = content.replace(/\n+$/, '')
    const markdown = `---\nname: ${memoryId}.md\ndescription: ${description}\ntype: ${plane}\ntenant: ${this.config.organization_id}\nmember: ${actor}\nrecorded_at: ${now}\n---\n${body}\n\n<!-- team_memory:record ${canonical} -->\n`
    if (fs.existsSync(fragmentPath)) {
      const existing = fs.readFileSync(fragmentPath, 'utf8')
      const match = /<!-- team_memory:record (.*) -->/.exec(existing)
      if (match === null || match[1] !== canonical) fail('record_exists: el fragmento ya esta materializado con otro contenido; el store es append-only')
      return path.relative(this._memoryDir(actor), fragmentPath)
    }
    fs.writeFileSync(fragmentPath, markdown, { mode: 0o600 })
    this._writeMemoryIndex(actor)
    return path.relative(this._memoryDir(actor), fragmentPath)
  }
  _memoryIndexLines(member) {
    return this._liveFragments(member).map(record => {
      const date = String(record.recorded_at ?? '').slice(0, 10) || 'unknown'
      const line = `- [${record.plane}] ${record.memory_id}.md (${date})`
      return record.description ? `${line}: ${record.description}` : line
    })
  }
  _writeMemoryIndex(member) {
    const dir = this._memoryDir(member)
    noSymlink(dir, true)
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 })
    const lines = this._memoryIndexLines(member)
    fs.writeFileSync(path.join(dir, 'MEMORY.md'), lines.length ? lines.join('\n') + '\n' : '', { mode: 0o600 })
  }
  _truncateBytes(value, budgetBytes) {
    // Recorte proporcional con backtrack de a 10 caracteres (formula del fuente, bytes UTF-8).
    if (budgetBytes <= 0) return ''
    const total = Buffer.byteLength(value, 'utf8')
    if (total <= budgetBytes) return value
    let index = Math.trunc((budgetBytes / total) * value.length)
    while (index > 0 && Buffer.byteLength(value.slice(0, index), 'utf8') > budgetBytes) index = Math.max(0, index - 10)
    return value.slice(0, index)
  }
  _memoryView(member) {
    const dir = this._memoryDir(member)
    const indexPath = path.join(dir, 'MEMORY.md')
    const original = fs.existsSync(indexPath) ? fs.readFileSync(indexPath, 'utf8') : this._memoryIndexLines(member).join('\n')
    const content = this._truncateBytes(original, MEMORY_INDEX_BUDGET_BYTES)
    const truncated = content.length !== original.length
    const totalLines = original.split('\n').length - (original.endsWith('\n') ? 1 : 0)
    const remainLines = content.split('\n').length - (content.endsWith('\n') ? 1 : 0)
    const omitted = truncated ? totalLines - remainLines : 0
    const reminder = truncated
      ? `\n${MEMORY_TRUNCATED_MARK}\n<system-reminder>The remaining ${omitted} lines have been omitted due to context length limits. Use the \`Read\` tool with offset ${remainLines} to access the rest of '${indexPath}'.</system-reminder>`
      : null
    const visible = content || MEMORY_EMPTY_INDEX
    return { member, index_path: indexPath, content, content_bytes: Buffer.byteLength(content, 'utf8'),
             budget_bytes: MEMORY_INDEX_BUDGET_BYTES, truncated, remain_lines: remainLines,
             omitted_lines: omitted, reminder, text: visible + (reminder ?? ''),
             fragments: this._liveFragments(member).map(record => ({
               memory_id: record.memory_id, plane: record.plane, description: record.description,
               recorded_at: record.recorded_at, fragment: path.join(record.plane, `${record.memory_id}.md`) })),
             placeholder_leak: (visible + (reminder ?? '')).includes('{memory_dir}') }
  }
  independent(reviewer, author) {
    const ancestors = id => {
      const result = new Set()
      while (this.members.has(id)) {
        id = this.members.get(id).reports_to
        if (result.has(id)) fail('Invalid management cycle')
        result.add(id)
      }
      return result
    }
    if (reviewer === author || ancestors(author).has(reviewer) || ancestors(reviewer).has(author)) fail('Independent reviewer outside author management chain required')
  }
}
