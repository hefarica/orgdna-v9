/**
 * Opt-in native DSH ↔ OrgDNA read-only connection. No tool execution.
 * Native setup is registered ONLY inside Connection's authenticated /api route.
 * A user click creates a loopback listener and a single-use 120-second pairing.
 * Supported source seams and their limits are documented in docs/dsh_connection.md.
 */
import { createServer } from 'node:http'
import { randomBytes, randomUUID, timingSafeEqual } from 'node:crypto'
import { createRequire } from 'node:module'
import { readFileSync, constants } from 'node:fs'
import { lstat, open, readdir, realpath } from 'node:fs/promises'
import { resolve, join, isAbsolute } from 'node:path'

export const PROTOCOL = 'orgdna-local-bridge/1'
export const NATIVE_PAIRING_PATH = '/api/orgdna-local-connect'
const SUPPORTED_DSH_LIBRARIES = new Set(['0.2.0-rc.2', '0.2.1-alpha.1'])
const MAX_BODY = 1024 * 1024
const MAX_RESPONSE = 2 * 1024 * 1024
const MAX_SESSION_MS = 30 * 60 * 1000
const MAX_PAIR_MS = 120_000
const REQUIRE_ACK = 'ALLOW_LOCAL_READ_ONLY_30_MINUTES'
const PACKAGE_NAMES = ['@deepseek-ai/dsh-tools', '@deepseek-ai/dsh-client-connection', 'dsh-agent-team-gui', '@nanmicoder/dsh-agent-teams']
const SAFE_SCOPE = ['cordis.capabilities.read', 'teams.profiles.read', 'teams.import.preview', 'agentteams.state.read']
const SECRET_KEYS = new Set(['password','passwd','secret','token','apikey','authorization','cookie','credentials','sessiontoken','pairingcode','accesstoken','refreshtoken','privatekey','clientsecret','idtoken','bearertoken','accesskey','secretkey','secretaccesskey'])
const mounted = new WeakMap()
const redactText = text => text.replace(/\b(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~-]{12,})/g, '[REDACTED]')
function clean(value, depth = 0) {
  if (depth > 14 || Array.isArray(value) && value.length > 4000 || typeof value === 'string' && value.length > 100_000) throw fail('RESPONSE_TOO_LARGE')
  if (typeof value === 'string') return redactText(value).slice(0, 100_000)
  if (Array.isArray(value)) return value.slice(0, 4000).map(x => clean(x, depth + 1))
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).filter(([k]) => !SECRET_KEYS.has(k.toLowerCase().replace(/[^a-z0-9]/g, ''))).map(([k, v]) => [k, clean(v, depth + 1)]))
  return value
}
function fail(code) { const e = new Error(code); e.code = code; return e }
function equalSecret(a, b) {
  return typeof a === 'string' && typeof b === 'string' && a.length === b.length && timingSafeEqual(Buffer.from(a), Buffer.from(b))
}
function installedVersions() {
  const require = createRequire(import.meta.url)
  return Object.fromEntries(PACKAGE_NAMES.map(name => {
    try {
      const pkg = JSON.parse(readFileSync(require.resolve(name + '/package.json'), 'utf8'))
      return [name, pkg.name === name && typeof pkg.version === 'string' ? pkg.version : null]
    } catch { return [name, null] }
  }))
}
const capability = (available, reason, source) => ({ available, reason: available ? null : reason, source })

/** Tested public Teams service methods; never dispatch(), import(), or scheduler tools. */
export function createReadAdapter(ctx, versions, options = {}) {
  const teams = ctx.get?.('agentTeamGui')
  const supportedTeams = versions['dsh-agent-team-gui'] === '1.3.0'
  const supportedAT = versions['@nanmicoder/dsh-agent-teams'] === '0.1.22'
  const stateRoot = options.agentteams_state_root
  const profiles = supportedTeams && typeof teams?.readDefinitionSnapshot === 'function'
  const preview = supportedTeams && typeof teams?.previewRecipe === 'function' && typeof teams?.previewDefinitionsImport === 'function'
  const filesystem = supportedAT && typeof stateRoot === 'string' && isAbsolute(stateRoot)
  const registry = typeof ctx.tools?.schemas === 'function'
  const capabilities = {
    profiles_read: capability(profiles, 'Teams 1.3.0 public readDefinitionSnapshot service is unavailable.', 'agentTeamGui'),
    import_preview: capability(preview, 'Teams 1.3.0 public preview methods are unavailable.', 'agentTeamGui'),
    agentteams_state_read: capability(filesystem, 'Requires AgentTeams 0.1.22 and an explicitly selected absolute state directory.', 'agentteams.readonly_file'),
    cordis_capabilities_read: capability(registry, 'Native tools.schemas read seam unavailable.', 'tools.schemas'),
    task_plan_submit: capability(false, 'No verified native existing-team command seam preserving action-time approvals.', null),
    live_messages: capability(false, 'Shared coordination records do not wake native agents; no approved native messaging seam is enabled.', null),
    realtime_events: capability(false, 'No verified native subscription seam for both plugins; reads are explicit, not background polling.', null),
  }
  const scopes = [profiles && SAFE_SCOPE[1], preview && SAFE_SCOPE[2], filesystem && SAFE_SCOPE[3], registry && SAFE_SCOPE[0]].filter(Boolean)
  return {
    scopes, capabilities,
    async profiles(signal) {
      if (!profiles) throw fail('CAPABILITY_UNAVAILABLE')
      const snapshot = await teams.readDefinitionSnapshot(signal)
      if (!(snapshot?.agents instanceof Map) || !(snapshot?.squads instanceof Map)) throw fail('UNSUPPORTED_PROFILE_SCHEMA')
      if (snapshot.agents.size > 2000 || snapshot.squads.size > 1000) throw fail('RESPONSE_TOO_LARGE')
      return clean({ source: 'agentTeamGui', source_version: '1.3.0',
        agents: [...snapshot.agents].map(([id, row]) => ({ ...row, id })),
        squads: [...snapshot.squads].map(([id, row]) => ({ ...row, id })),
        live_connection: true, identity_verified: true, definitions_are_session_ids: false,
        writes_performed: false, observed_at: new Date().toISOString() })
    },
    async preview(document, signal) {
      if (!preview) throw fail('CAPABILITY_UNAVAILABLE')
      let result
      if (document?.format === 'agent-team-gui/recipe') result = await teams.previewRecipe(document, {}, signal)
      else if (document?.format === 'agent-team-gui/definitions') result = await teams.previewDefinitionsImport(document, 'merge', signal)
      else throw fail('UNSUPPORTED_DOCUMENT')
      return clean({ source: 'agentTeamGui', preview: result, live_connection: true, writes_performed: false })
    },
    async teamState(teamName = '') {
      if (!filesystem) throw fail('CAPABILITY_UNAVAILABLE')
      return readTeamFiles(stateRoot, teamName)
    },
    async registry() {
      if (!registry) throw fail('CAPABILITY_UNAVAILABLE')
      const schemas = ctx.tools.schemas()
      return { source: 'tools.schemas', tools: [...schemas].slice(0, 4000).map(t => ({ name: clean(String(t.name)) })),
        registry_is_permission_grant: false, execution_enabled: false, live_connection: true }
    },
  }
}

/** Explicit-root read-only fallback. No file creation, locks, mailbox acknowledgements or scheduler. */
export async function readTeamFiles(stateRoot, teamName = '') {
  if (!isAbsolute(stateRoot) || typeof teamName !== 'string' || teamName.length > 200) throw fail('INVALID_STATE_SELECTION')
  const root = resolve(stateRoot)
  if (await realpath(root) !== root || !(await lstat(root)).isDirectory()) throw fail('UNSAFE_STATE_DIRECTORY')
  const entries = (await readdir(root, { withFileTypes: true })).filter(e => e.isDirectory() && !e.isSymbolicLink() && /^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$/.test(e.name) && e.name !== 'archive')
  if (entries.length > 256) throw fail('STATE_DIRECTORY_TOO_LARGE')
  const teams = []
  for (const entry of entries) {
    const filename = join(root, entry.name, 'team.json')
    let handle
    try {
      if (await realpath(join(root, entry.name)) !== join(root, entry.name)) throw fail('UNSAFE_STATE_DIRECTORY')
      const stat = await lstat(filename)
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size > MAX_BODY) throw fail('UNSAFE_STATE_FILE')
      handle = await open(filename, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0))
      const before = await handle.stat()
      if (!before.isFile() || before.size > MAX_BODY || before.ino !== stat.ino || before.dev !== stat.dev) throw fail('STATE_CHANGED')
      const text = await handle.readFile('utf8')
      const after = await handle.stat()
      if (text.length > MAX_BODY || after.size !== before.size || after.mtimeMs !== before.mtimeMs) throw fail('STATE_CHANGED')
      const row = JSON.parse(text.replace(/^\uFEFF/, ''))
      if (row?.id !== entry.name || typeof row.name !== 'string' || typeof row.captainSessionId !== 'string'
          || !Array.isArray(row.members) || !Array.isArray(row.tasks) || row.members.length > 256 || row.tasks.length > 2000
          || typeof row.createdAt !== 'number' || !Number.isInteger(row.taskSeq)
          || row.members.some(m => typeof m.id !== 'string' || typeof m.name !== 'string' || typeof m.status !== 'string')
          || row.tasks.some(t => typeof t.id !== 'string' || typeof t.status !== 'string')) throw fail('UNSUPPORTED_STATE_SCHEMA')
      if (teamName && row.id !== teamName && row.name !== teamName) continue
      teams.push(clean({ id: row.id, name: row.name, captainSessionId: row.captainSessionId,
        phase: row.phase ?? 'running', halted: row.halted === true, escalated: row.escalated === true,
        members: row.members.filter(m => m.status !== 'removed').map(m => ({ id: m.id, name: m.name, status: m.status, role: m.role, provider: m.provider, model: m.model })),
        tasks: row.tasks.map(t => ({ id: t.id, subject: t.subject, status: t.status, assignee: t.assignee, attemptId: t.attemptId ?? null, dependencies: t.dependencies ?? [] })),
        captured_file_mtime: after.mtimeMs }))
    } catch (error) {
      if (error?.code === 'ENOENT') continue
      throw fail(error?.code && /^[A-Z_]{3,50}$/.test(error.code) ? error.code : 'STATE_READ_FAILED')
    } finally { await handle?.close() }
  }
  return { source: 'agentteams.readonly_file', source_version: '0.1.22', schema_revision: '98aac03-teamstate', teams,
    live_connection: true, runtime_session_identity_verified: false, creates_members: false, resumes_team: false,
    writes_performed: false, observed_at: new Date().toISOString() }
}

function send(res, status, value) {
  const body = JSON.stringify(value)
  if (Buffer.byteLength(body) > MAX_RESPONSE) { res.writeHead(413); res.end(); return }
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' })
  res.end(body)
}
async function body(req) {
  if (req.headers['content-type'] !== 'application/json') throw fail('INVALID_REQUEST')
  const chunks = []; let size = 0
  for await (const chunk of req) { size += chunk.length; if (size > MAX_BODY) throw fail('REQUEST_TOO_LARGE'); chunks.push(chunk) }
  try { const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8')); if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw 0; return parsed }
  catch { throw fail('INVALID_JSON') }
}

/** Core transport; production callers use startLiveBridge, tests supply official-service doubles. */
export async function createLocalBridge(adapter, versions, { sessionMs = MAX_SESSION_MS, pairMs = MAX_PAIR_MS, nativeStageUrl = null } = {}) {
  if (!adapter.scopes.length || adapter.scopes.some(s => !SAFE_SCOPE.includes(s))) throw fail('NO_READ_CAPABILITIES')
  sessionMs = Math.max(1, Math.min(sessionMs, MAX_SESSION_MS)); pairMs = Math.max(1, Math.min(pairMs, MAX_PAIR_MS))
  const instance = randomUUID()
  let pairingCode = randomBytes(32).toString('base64url')
  const pairDeadline = Date.now() + pairMs
  let token = null; let expiry = 0; let attempts = 0; let closing = false
  const handshake = nonce => ({ protocol: PROTOCOL, nonce, instance_id: instance, versions,
    scopes: adapter.scopes, capabilities: adapter.capabilities, owner_approved: true, permissions_acknowledged: true,
    read_only: true, expires_at: expiry / 1000, ...(nativeStageUrl ? {native_stage_url:nativeStageUrl,native_stage_permission_separate:true} : {}) })
  const server = createServer(async (req, res) => {
    try {
      const local = req.socket.remoteAddress === '127.0.0.1' || req.socket.remoteAddress === '::ffff:127.0.0.1'
      const expectedHost = '127.0.0.1:' + server.address()?.port
      // Browser requests never talk directly to this API; the app's local Python process does.
      if (!local || req.headers.host !== expectedHost || req.headers.origin || req.headers['sec-fetch-site'] || req.headers['x-forwarded-for']) throw fail('UNTRUSTED_ORIGIN')
      if (req.method !== 'POST' || !['/v1/pair', '/v1/rpc'].includes(req.url)) throw fail('INVALID_ROUTE')
      const data = await body(req)
      if (req.url === '/v1/pair') {
        if (++attempts > 5 || !pairingCode || Date.now() > pairDeadline || !equalSecret(data.pairing_code, pairingCode) || data.protocol !== PROTOCOL) throw fail('PAIRING_REJECTED')
        if (typeof data.nonce !== 'string' || data.nonce.length < 16 || data.nonce.length > 100) throw fail('INVALID_NONCE')
        pairingCode = null
        token = randomBytes(32).toString('base64url'); expiry = Date.now() + sessionMs
        send(res, 200, { ok: true, value: { ...handshake(data.nonce), session_token: token } }); return
      }
      if (!token || Date.now() >= expiry || !equalSecret(req.headers.authorization, 'Bearer ' + token)) throw fail('SESSION_REJECTED')
      let result
      if (data.operation === 'handshake') result = handshake(data.nonce)
      else if (data.operation === 'profiles') result = await adapter.profiles(AbortSignal.timeout(3000))
      else if (data.operation === 'import_preview') result = await adapter.preview(data.document, AbortSignal.timeout(3000))
      else if (data.operation === 'team_state') result = await adapter.teamState(data.team_name ?? '')
      else if (data.operation === 'capabilities') result = await adapter.registry()
      else if (data.operation === 'disconnect') { token = null; result = { disconnected: true } }
      else throw fail('CAPABILITY_UNAVAILABLE')
      if (data.operation !== 'handshake') {
        const encoded = JSON.stringify(clean(result))
        result = JSON.parse(token ? encoded.split(token).join('[REDACTED]') : encoded)
      }
      send(res, 200, { ok: true, value: result })
    } catch (error) {
      const code = ['PAIRING_REJECTED', 'SESSION_REJECTED', 'UNTRUSTED_ORIGIN'].includes(error?.code) ? error.code : 'READ_REJECTED'
      send(res, 403, { ok: false, error: { code } })
    }
  })
  server.requestTimeout = 5000; server.headersTimeout = 5000; server.keepAliveTimeout = 5000
  await new Promise((ok, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', ok) })
  const dispose = async () => {
    if (closing) return
    closing = true; pairingCode = token = null; clearInterval(timer)
    server.closeAllConnections?.(); await new Promise(ok => server.close(ok))
  }
  const timer = setInterval(() => { if ((!token && Date.now() >= pairDeadline) || (token && Date.now() >= expiry)) void dispose() }, 1000)
  timer.unref()
  return { port: server.address().port, pairing_code: pairingCode, instance_id: instance,
    expires_in_seconds: Math.ceil(pairMs / 1000), read_only: true, scopes: [...adapter.scopes], dispose }
}

export async function startLiveBridge(ctx, options = {}) {
  if (options.owner_ack !== REQUIRE_ACK) throw fail('OWNER_APPROVAL_REQUIRED')
  const versions = installedVersions()
  if (!SUPPORTED_DSH_LIBRARIES.has(versions['@deepseek-ai/dsh-tools']) || versions['@deepseek-ai/dsh-client-connection'] !== versions['@deepseek-ai/dsh-tools']) throw fail('UNSUPPORTED_DSH_VERSION')
  let nativeStageUrl = null
  if (typeof options.native_stage_available === 'function' && options.native_stage_available() === true && typeof options.native_origin === 'string') {
    const origin = new URL(options.native_origin)
    if (['http:', 'https:'].includes(origin.protocol) && ['127.0.0.1', 'localhost', '[::1]'].includes(origin.hostname) && !origin.username && !origin.password) nativeStageUrl = origin.origin + '/api/orgdna-native-stage'
  }
  return createLocalBridge(createReadAdapter(ctx, versions, options), versions, {nativeStageUrl})
}

const PAIRING_PAGE = `<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>OrgDNA: conexión local</title><body><h1>Conectar OrgDNA a DSH</h1><p>Este permiso dura como máximo 30 minutos. Permite leer perfiles de Teams, previsualizar importaciones y observar el equipo existente cuando su directorio esté autorizado. No ejecuta tareas ni cambia perfiles o permisos. No compartas el código en chats.</p><button id="approve">Autorizar lectura local durante 30 minutos</button><button id="revoke">Revocar conexión</button><pre id="result" aria-live="polite"></pre><script nonce="__NONCE__">const output=document.getElementById('result');async function act(action){output.textContent='Verificando…';try{const response=await fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,ack:'${REQUIRE_ACK}'})});const data=await response.json();output.textContent=response.ok?JSON.stringify(data,null,2):'No se pudo habilitar esta capacidad. Comprueba versiones y servicios del addon.'}catch{output.textContent='Conexión no verificada.'}}document.getElementById('approve').onclick=()=>act('pair');document.getElementById('revoke').onclick=()=>act('revoke');</script></body></html>`

/** Registration alone opens no listener and changes no DSH state or grants. */
export function registerLiveBridge(ctx, options = {}) {
  if (options.enabled !== true) return { status: 'DISABLED' }
  const connection = ctx.get?.('connection')
  if (typeof connection?.fetch?.register !== 'function') return { status: 'UNAVAILABLE', reason: 'Authenticated native Connection fetch registry unavailable.' }
  const previous = mounted.get(ctx)
  if (previous) return previous
  let active = null; let creating = false
  const unregister = connection.fetch.register({ path: NATIVE_PAIRING_PATH, methods: ['GET', 'POST'], requestBody: 'buffered',
    async fetch(request) {
      const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer' }
      if (request.method === 'GET') {
        const nonce = randomBytes(16).toString('base64url')
        return new Response(PAIRING_PAGE.replace('__NONCE__', nonce), { headers: { ...headers, 'Content-Type': 'text/html; charset=utf-8', 'Content-Security-Policy': `default-src 'none'; script-src 'nonce-${nonce}'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'` } })
      }
      try {
        // Native Connection verifies browser auth + trusted host/origin before this handler.
        if (request.method !== 'POST' || request.headers.get('origin') !== new URL(request.url).origin || request.headers.get('content-type') !== 'application/json') throw fail('OWNER_APPROVAL_REQUIRED')
        const raw = await request.text(); if (raw.length > 1024) throw fail('REQUEST_TOO_LARGE')
        const data = JSON.parse(raw)
        if (data.ack !== REQUIRE_ACK || !['pair', 'revoke'].includes(data.action) || creating) throw fail('OWNER_APPROVAL_REQUIRED')
        creating = true
        try {
          await active?.dispose(); active = null
          if (data.action === 'revoke') return Response.json({ status: 'REVOKED' }, { headers })
          active = await startLiveBridge(ctx, { ...options, owner_ack: data.ack, native_origin: new URL(request.url).origin })
          const { dispose, ...descriptor } = active
          active = { dispose } // Never retain the displayed code in native setup state.
          return Response.json(descriptor, { headers })
        } finally { creating = false }
      } catch { return Response.json({ error: 'PAIRING_UNAVAILABLE' }, { status: 403, headers }) }
    },
  })
  let disposed = false
  const dispose = () => {
    if (disposed) return
    disposed = true
    try { const pending = unregister?.(); pending?.catch?.(() => {}) } finally { void active?.dispose(); mounted.delete(ctx) }
  }
  ctx.effect?.(() => dispose)
  const result = { status: 'PAIRING_UI_READY', native_pairing_path: NATIVE_PAIRING_PATH, read_only: true, dispose }
  mounted.set(ctx, result)
  return result
}
