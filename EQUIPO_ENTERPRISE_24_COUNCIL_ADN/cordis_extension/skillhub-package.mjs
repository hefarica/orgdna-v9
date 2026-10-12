/** Exclusive versioned file publication only. No installation, activation or shell. */
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
const sha=x=>createHash('sha256').update(x).digest('hex')
const home=path.dirname(fileURLToPath(import.meta.url))
function safe(p){p=path.resolve(p);for(let q=p;;q=path.dirname(q)){if(fs.existsSync(q)&&fs.lstatSync(q).isSymbolicLink())throw new Error('Symlink forbidden');if(path.dirname(q)===q)break}return p}
function relative(name){if(typeof name!=='string'||name.includes('\\')||name.includes(':')||path.isAbsolute(name)||name.split('/').some(s=>!s||s==='..'||s==='.')||name==='.publication.json')throw new Error('Unsafe manifest path');return name}
function version(v){if(typeof v!=='string'||! /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(v)||v==='.'||v==='..')throw new Error('Unsafe package version');return v}
function identity(m){if(!/^orgdna_[a-f0-9]{32}$/.test(m.namespace??'')||m.namespace!=='orgdna_'+String(m.organization_id).replaceAll('-',''))throw new Error('Invalid organization namespace')}
export function publishPackage(source,destination,release,{approve=false}={}){
 source=safe(source);destination=safe(destination);version(release)
 const manifestBytes=fs.readFileSync(safe(path.join(source,'addon-manifest.json'))),manifest=JSON.parse(manifestBytes);identity(manifest)
 if(manifest.protocol!=='orgdna-cordis/1'||!manifest.file_sha256||Object.keys(manifest.file_sha256).length>1000)throw new Error('Invalid additive package manifest')
 const files=new Map([['addon-manifest.json',manifestBytes]])
 for(const [name,digest]of Object.entries(manifest.file_sha256)){relative(name);const file=safe(path.join(source,name));if(fs.statSync(file).size>8*1024*1024)throw new Error('File too large');const bytes=fs.readFileSync(file);if(sha(bytes)!==digest)throw new Error('Source hash mismatch: '+name);files.set(name,bytes)}
 if([...files.values()].reduce((n,b)=>n+b.length,0)>64*1024*1024)throw new Error('Package too large')
 const target=safe(path.join(destination,manifest.namespace,release));if(fs.existsSync(target))throw new Error('Version exists; no overwrite')
 const receipt={protocol:'orgdna-skillhub-publication/1',organization_id:manifest.organization_id,namespace:manifest.namespace,version:release,files:Object.fromEntries([...files].map(([name,data])=>[name,sha(data)])),runtime_activated:false}
 const result={status:'PREVIEW_ONLY',target,receipt,existing_files_modified:0,backup:'Existing versions preserved; no overwrite.',pending:'Run local preflight, review supported native loading mechanism, then read back live tools/profile UUIDs/SkillHub hash.'}
 if(!approve)return result
 fs.mkdirSync(safe(path.dirname(target)),{recursive:true});fs.mkdirSync(target)
 try{for(const[name,data]of files){const out=path.join(target,name);fs.mkdirSync(path.dirname(out),{recursive:true});fs.writeFileSync(out,data,{flag:'wx',mode:0o600})}
 fs.writeFileSync(path.join(target,'.publication.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx',mode:0o600})
 for(const[name,hash]of Object.entries(receipt.files))if(sha(fs.readFileSync(path.join(target,name)))!==hash)throw new Error('Publication readback mismatch')
 }catch(error){fs.rmSync(target,{recursive:true});throw error}
 result.status='PUBLISHED_BYTES_VERIFIED_NOT_ACTIVATED';return result
}
export function rollbackPackage(target,{approve=false}={}){
 target=safe(target);const receipt=JSON.parse(fs.readFileSync(safe(path.join(target,'.publication.json'))));identity(receipt);version(receipt.version)
 if(receipt.protocol!=='orgdna-skillhub-publication/1'||path.basename(target)!==receipt.version||path.basename(path.dirname(target))!==receipt.namespace)throw new Error('Publication identity mismatch')
 const actual=[];function walk(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){const f=safe(path.join(dir,e.name));if(e.isDirectory())walk(f);else if(e.isFile())actual.push(path.relative(target,f).split(path.sep).join('/'));else throw new Error('Unexpected file type')}}walk(target)
 const expected=[...Object.keys(receipt.files),'.publication.json'].sort();if(JSON.stringify(actual.sort())!==JSON.stringify(expected))throw new Error('Foreign/missing file; rollback refused')
 for(const[name,hash]of Object.entries(receipt.files)){relative(name);if(sha(fs.readFileSync(path.join(target,name)))!==hash)throw new Error('Modified file; rollback refused')}
 if(approve)fs.rmSync(target,{recursive:true})
 return{status:approve?'ROLLED_BACK_OWN_VERSION':'ROLLBACK_PREVIEW',other_plugins_modified:false,native_deactivation:'Not performed. Detach active addon in native runtime before rollback.'}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{const[action,destination,release]=process.argv.slice(2);let result
 if(action==='--preview'||action==='--publish-reviewed')result=publishPackage(home,destination,release,{approve:action==='--publish-reviewed'})
 else if(action==='--rollback-preview'||action==='--rollback-reviewed')result=rollbackPackage(destination,{approve:action==='--rollback-reviewed'})
 else throw new Error('Usage: node skillhub-package.mjs --preview|--publish-reviewed DESTINATION VERSION; --rollback-preview|--rollback-reviewed OWN_VERSION_DIRECTORY. No DSH activation occurs.')
 console.log(JSON.stringify(result,null,2))}catch(error){console.error(error.message);process.exitCode=2}
}
