/** Optional exact-SDK composition smoke. Requires separately installed official SDK; never installs it.
 * node this-file.mjs /path/to/isolated-sdk-root [evidence.json]
 * Browser credential storage and Teams are test doubles; native Connection auth/registry are real.
 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { resolve, join } from 'node:path'
import { mkdtemp, copyFile, rm, writeFile } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
if (!process.argv[2]) throw new Error('Provide an isolated SDK root with exact Cordis4.0.4 and Connection/Tools0.2.0-rc.2 already installed.')
const sdkRoot=resolve(process.argv[2]);const require=createRequire(join(sdkRoot,'package.json'))
const versions=Object.fromEntries(['@deepseek-ai/cordis','@deepseek-ai/dsh-client-connection','@deepseek-ai/dsh-tools'].map(name=>[name,JSON.parse(readFileSync(require.resolve(name+'/package.json'),'utf8')).version]))
assert.equal(versions['@deepseek-ai/cordis'],'4.0.4');assert.equal(versions['@deepseek-ai/dsh-client-connection'],'0.2.0-rc.2');assert.equal(versions['@deepseek-ai/dsh-tools'],'0.2.0-rc.2')
const {Context}=await import(pathToFileURL(require.resolve('@deepseek-ai/cordis')))
const {apply}=await import(pathToFileURL(require.resolve('@deepseek-ai/dsh-client-connection')))
const scratch=await mkdtemp(join(sdkRoot,'.orgdna-connection-smoke-'))
const ctx=new Context();let record;let bridge
try{
  // Test-only, ephemeral credential provider. No user account, provider key, disk credential or DSH home.
  ctx.provide('credentials',{async modifyRecord(_key,modify){const next=await modify(record);if(next!==undefined)record=next;return record}})
  ctx.provide('tools',{schemas:()=>[{name:'fixture_read_only'}]})
  await apply(ctx,{trustedHosts:[],cookieMaxAgeDays:1})
  const connection=ctx.get('connection')
  assert.equal(connection.requestRejection({headers:{host:'127.0.0.1:9000'}}),401)
  assert.equal(connection.requestRejection({headers:{host:'evil.example'}}),403)
  const launch=new URL(connection.authenticatedUrl('http://127.0.0.1:9000/'))
  let cookie;let status
  const admitted=connection.authorizeIndex({method:'GET',url:launch.pathname+launch.search,headers:{host:'127.0.0.1:9000'}},{writeHead(code,headers){status=code;cookie=headers['set-cookie'].split(';')[0]},end(){}})
  assert.equal(admitted,false);assert.equal(status,303)
  assert.equal(connection.requestRejection({headers:{host:'127.0.0.1:9000',cookie}}),undefined)
  assert.equal(connection.requestRejection({headers:{host:'127.0.0.1:9000',cookie,origin:'https://evil.example'}}),403)
  await copyFile(fileURLToPath(new URL('../live_bridge.mjs',import.meta.url)),join(scratch,'live_bridge.mjs'))
  const {registerLiveBridge}=await import(pathToFileURL(join(scratch,'live_bridge.mjs')))
  bridge=registerLiveBridge(ctx,{enabled:true});assert.equal(bridge.status,'PAIRING_UI_READY')
  assert.equal(registerLiveBridge(ctx,{enabled:true}),bridge)
  const shared=connection.createSharedFetchHandler('/api')
  async function native(request){const admission=connection.admit(request);if('rejection'in admission)return new Response('',{status:admission.rejection});return shared.fetch(request)}
  const url='http://127.0.0.1:9000/api/orgdna-local-connect'
  assert.equal((await native(new Request(url,{headers:{host:'127.0.0.1:9000'}}))).status,401)
  const headers={host:'127.0.0.1:9000',cookie,origin:'http://127.0.0.1:9000','Content-Type':'application/json'}
  const page=await native(new Request(url,{headers}));assert.equal(page.status,200)
  const created=await native(new Request(url,{method:'POST',headers,body:JSON.stringify({action:'pair',ack:'ALLOW_LOCAL_READ_ONLY_30_MINUTES'})}))
  assert.equal(created.status,200);const descriptor=await created.json()
  const paired=await fetch(`http://127.0.0.1:${descriptor.port}/v1/pair`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({protocol:'orgdna-local-bridge/1',pairing_code:descriptor.pairing_code,nonce:'official-sdk-composition-nonce'})})
  assert.equal(paired.status,200);const value=(await paired.json()).value
  assert.equal(value.versions['@deepseek-ai/dsh-client-connection'],'0.2.0-rc.2')
  assert.equal(value.capabilities.profiles_read.available,false)
  assert.equal(value.capabilities.cordis_capabilities_read.available,true)
  const revoke=await native(new Request(url,{method:'POST',headers,body:JSON.stringify({action:'revoke',ack:'ALLOW_LOCAL_READ_ONLY_30_MINUTES'})}));assert.equal(revoke.status,200)
  const evidence={status:'PASS',measured_at_utc:new Date().toISOString(),versions,
    real_sdk_components:['Cordis Context/Service/effects','Connection browser token/cookie signing and verification','Host/Origin admission','authenticated fetch registry','OrgDNA production startLiveBridge version checks','loopback single-use pairing'],
    fixtures:['memory-only credential storage','tools.schemas read-only test registry'],
    actual_dsh_application_started:false,actual_agent_teams_or_teams_started:false,actual_model_or_provider_called:false,user_computer_used:false,
    checks:['unauthenticated401','untrustedHost403','signedcookieaccepted','crossOrigin403','registrationidempotent','pairingnativeconsent','productionversioncheck','loopbacktokenissued','revocation']}
  if(process.argv[3])await writeFile(resolve(process.argv[3]),JSON.stringify(evidence,null,2)+'\n')
  process.stdout.write(JSON.stringify(evidence)+'\n')
}finally{bridge?.dispose();await ctx.fiber.dispose();await rm(scratch,{recursive:true,force:true});record=undefined}
