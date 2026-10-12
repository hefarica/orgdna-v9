/** Read-only local installation inventory. Never imports DSH or executes CLI code. */
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
const sha = data => createHash('sha256').update(data).digest('hex')
function read(file, max = 4 * 1024 * 1024) {
  for(let p=path.resolve(file);;p=path.dirname(p)) {if(fs.lstatSync(p).isSymbolicLink())throw new Error('Symlink not allowed');if(path.dirname(p)===p)break}
  if(fs.statSync(file).size>max)throw new Error('File exceeds preflight size limit')
  return fs.readFileSync(file)
}
export function inventoryInstallation(runtimeDirectory, packageDirectory = path.dirname(fileURLToPath(import.meta.url))) {
  const report={status:'PENDING_LOCAL_VERIFICATION',config_files_modified:0,network_calls:0,processes_started:0,plugins_installed:0,runtime_activated:false,checks:[],pending:[]}
  if(!runtimeDirectory || !path.isAbsolute(runtimeDirectory))throw new Error('Provide the absolute existing DSH runtime directory')
  const [major,minor]=process.versions.node.split('.').map(Number)
  report.checks.push({name:'node_engine',actual:process.versions.node,required:'>=22.19.0',passed:major>22||(major===22&&minor>=19)})
  const modules=path.join(runtimeDirectory,'node_modules')
  for(const name of ['@deepseek-ai/dsh','@deepseek-ai/dsh-tools','@nanmicoder/dsh-agent-teams']) {
    try {const bytes=read(path.join(modules,name,'package.json')), metadata=JSON.parse(bytes)
      if(metadata.name!==name)throw new Error('Package identity mismatch')
      report.checks.push({package:name,version:metadata.version,package_sha256:sha(bytes),status:'METADATA_READ_NOT_RUNTIME_VERIFIED'})
    }catch(e){report.checks.push({package:name,status:'UNVERIFIED',reason:e.message})}
  }
  try {
    const entry=path.join(modules,'@deepseek-ai/dsh/lib/bin.js'), bytes=read(entry)
    report.entry={path:entry,sha256:sha(bytes),bytes:bytes.length}
  }catch(e){report.pending.push('Read installed DSH entry: '+e.message)}
  try {
    const bytes=read(path.join(packageDirectory,'addon-manifest.json')), manifest=JSON.parse(bytes)
    report.addon={organization_id:manifest.organization_id,namespace:manifest.namespace,manifest_sha256:sha(bytes),files_verified:0}
    for(const [name,digest] of Object.entries(manifest.file_sha256??{})) {
      if(name.includes('\\') || path.isAbsolute(name) || name.split('/').some(v=>v==='..'||v==='.'||!v))throw new Error('Unsafe manifest file path')
      if(sha(read(path.join(packageDirectory,name)))!==digest)throw new Error('Hash mismatch: '+name)
      report.addon.files_verified++
    }
  }catch(e){report.pending.push('Verify addon byte manifest: '+e.message)}
  report.pending.push('Inspect installed CLI source/help to verify exact overlay syntax. No launch command is generated while unknown.',
    'Original DSH_REINICIAR launcher does not forward --patch; do not append unsupported flags.',
    'Use native review for versioned plugin install/activation; approve persistent authentication scopes separately.',
    'Read back actual existing profile UUIDs, live session bindings, six namespaced tools and SkillHub manifest hash.',
    'Email, messaging and voice require connector-specific auth scopes, health and explicit send authorization.')
  return report
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try{console.log(JSON.stringify(inventoryInstallation(process.argv[2],process.argv[3]),null,2));process.exitCode=2}
  catch(error){console.error(error.message);process.exitCode=2}
}
