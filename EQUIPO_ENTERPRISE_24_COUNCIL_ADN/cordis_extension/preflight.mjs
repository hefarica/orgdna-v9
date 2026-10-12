/** Reads only the addon and installed package metadata; never loads a plugin or alters DSH. */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import { PROTOCOL, SUPPORTED_TOOLS_VERSIONS } from './runtime.mjs'

const pluginDirectory = path.dirname(fileURLToPath(import.meta.url))
export function preflight(directory = pluginDirectory) {
  // Imports in entry.mjs resolve from the actual plugin package. A manifest in
  // an outer distribution directory must never redirect dependency resolution.
  const require = createRequire(path.join(pluginDirectory, 'package.json'))
  const checks = [], blocking_reasons = []
  let version = null
  try {
    const metadata = JSON.parse(fs.readFileSync(require.resolve('@deepseek-ai/dsh-tools/package.json'), 'utf8'))
    version = metadata.version
    checks.push({ name: 'dsh_tools_version', actual: version, supported: SUPPORTED_TOOLS_VERSIONS, passed: SUPPORTED_TOOLS_VERSIONS.includes(version) })
    if (!SUPPORTED_TOOLS_VERSIONS.includes(version)) blocking_reasons.push('Installed DSH Tools version is outside the reviewed SDK targets')
  } catch { blocking_reasons.push('Cannot resolve installed @deepseek-ai/dsh-tools from addon directory; no installation was attempted') }
  let manifest, manifestPath = null
  const manifestDirectory = path.resolve(directory)
  const candidates = [path.join(manifestDirectory, 'addon-manifest.json')]
  // Two supported layouts: flat addon ZIP; distribution root + cordis_extension/.
  // No recursive search and no fallback after finding a malformed manifest.
  if (path.basename(manifestDirectory) === 'cordis_extension') candidates.push(path.join(path.dirname(manifestDirectory), 'addon-manifest.json'))
  manifestPath = candidates.find(candidate => fs.existsSync(candidate)) ?? null
  if (manifestPath === null) blocking_reasons.push('Generated addon-manifest.json is missing')
  else {
    try { manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')) }
    catch { blocking_reasons.push('Generated addon-manifest.json is unreadable or malformed') }
  }
  if (manifest && manifest.protocol !== PROTOCOL) blocking_reasons.push('Unknown addon protocol')
  checks.push({name:'addon_manifest',passed:manifest?.protocol===PROTOCOL,
    layout:manifestPath===candidates[0]?'flat_or_explicit_root':manifestPath?'parent_distribution_root':'missing'})
  blocking_reasons.push('Owner must inspect live tools and bind actual session IDs; package metadata does not verify the live runtime')
  return { status: 'BLOCKED_ACTIVATION', organization_id: manifest?.organization_id ?? null, tools_version: version,
    dependency_resolution_directory:pluginDirectory,checks, blocking_reasons, config_files_modified: 0, plugins_loaded: 0, network_calls: 0 }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log(JSON.stringify(preflight(process.argv[2]), null, 2))
  process.exitCode = 2
}
