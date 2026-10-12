/** Writes one NEW addon-only overlay; never edits profile files or starts Harness. */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { validateConfig } from './runtime.mjs'
const home = path.dirname(fileURLToPath(import.meta.url))
if (process.argv.length !== 4) throw new Error('Usage: node prepare-overlay.mjs <owner-reviewed-config.json> <new-overlay.yml>')
const raw = JSON.parse(fs.readFileSync(path.resolve(process.argv[2]), 'utf8'))
const connectionOnly = raw.enabled !== true && (raw.live_connection?.enabled === true || raw.native_orchestration?.enabled === true || raw.native_stage_ui?.enabled === true)
const config = connectionOnly ? raw : validateConfig(raw)
if (!connectionOnly && (config.enabled !== true || config.confirm_activation !== 'ACTIVATE_EXISTING_ROSTER_ONLY' || (Object.keys(config.session_bindings).length === 0 && config.native_stage_ui?.enabled !== true))) throw new Error('Explicit activation and owner-reviewed bindings or native review UI required')
if (connectionOnly && (typeof config.namespace !== 'string' || !/^orgdna_[a-f0-9]{32}$/.test(config.namespace))) throw new Error('Valid generated addon namespace required')
const overlay = [{ insert: [{ id: config.namespace, name: path.join(home, 'entry.mjs'), config }] }]
// JSON is valid YAML. Exclusive creation refuses any existing output file.
fs.writeFileSync(path.resolve(process.argv[3]), JSON.stringify(overlay, null, 2) + '\n', { flag: 'wx', mode: 0o600 })
console.log('Created addon-only overlay. Harness was not started; existing configuration was not changed.')
