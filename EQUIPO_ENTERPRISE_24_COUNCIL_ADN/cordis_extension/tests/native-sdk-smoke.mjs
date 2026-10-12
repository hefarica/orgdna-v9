/** Keyless real-SDK smoke. Run with the absolute directory of a reviewed install.
 * This is NOT installed-user DSH verification and makes no model/API request. */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { randomUUID } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { mount } from '../plugin.mjs'
import { PROTOCOL, SUPPORTED_TOOLS_VERSION } from '../runtime.mjs'
const sdk = process.argv[2]
if (!sdk || !path.isAbsolute(sdk)) throw new Error('Pass absolute reviewed SDK install directory')
const require = createRequire(path.join(sdk, 'package.json'))
const load = name => import(pathToFileURL(require.resolve(name)).href)
const { Context } = await load('@deepseek-ai/cordis')
const { defineTool, ToolRegistry, ToolRuntime, default: ToolsDefault } = await load('@deepseek-ai/dsh-tools')
const ToolsService = ToolRuntime ?? ToolRegistry ?? ToolsDefault
const { default: SystemPrompt } = await load('@deepseek-ai/dsh-system-prompt')
const versions = Object.fromEntries(['@deepseek-ai/cordis','@deepseek-ai/dsh-tools','@deepseek-ai/dsh-system-prompt'].map(name=>[name,JSON.parse(fs.readFileSync(require.resolve(name+'/package.json'),'utf8')).version]))
const directory=fs.mkdtempSync(path.join(os.tmpdir(),'orgdna-real-sdk-'))
const organization_id=randomUUID(), ids=Array.from({length:24},()=>randomUUID()), sessions=ids.map(()=>randomUUID())
const config={protocol:PROTOCOL,organization_id,namespace:'orgdna_'+organization_id.replaceAll('-',''),members:ids.map((member_id,i)=>({member_id,name:'Member'+i,reports_to:i?ids[0]:'OWNER_EXTERNAL'})),session_bindings:Object.fromEntries(sessions.map((s,i)=>[s,ids[i]])),state_directory:directory,enabled:true,confirm_activation:'ACTIVATE_EXISTING_ROSTER_ONLY',verified_tools_version:SUPPORTED_TOOLS_VERSION}
const ctx=new Context()
let result
try {
  await ctx.plugin(SystemPrompt,{includeHarnessIdentity:false,persona:''})
  await ctx.plugin(ToolsService,{mode:'native'})
  const existing=await ctx.plugin({name:'existing-fixture-plugin',inject:['tools'],apply(c){c.tools.register(defineTool({name:'existing_fixture_tool',description:'fixture',parameters:{},output:{schema:{type:'string'},render:(_a,v)=>[{type:'text',text:v}]},async execute(){return 'preserved'}}))}})
  const addon=await ctx.plugin({name:'orgdna-keyless-sdk-smoke',inject:['tools'],apply(c){result=mount(c,config,defineTool)}})
  assert.equal(ctx.tools.schemas().length,7)
  for(let i=0;i<24;i++) {
    const agent={id:sessions[i],ctx}
    const response=await ctx.tools.execute({name:config.namespace+'_message',arguments:{expected_version:i,idempotency_key:'sdk-message-'+i,payload:{to:'all',text:'Keyless fixture message '+i}},agent,callId:randomUUID(),signal:new AbortController().signal})
    if(response.isError) throw new Error(JSON.stringify(response))
    assert.equal(response.value.version,i+1)
  }
  const response=await ctx.tools.execute({name:config.namespace+'_state',arguments:{section:'messages'},agent:{id:sessions[23],ctx},callId:randomUUID(),signal:new AbortController().signal})
  assert.equal(response.value.rows.length,24)
  const bad=await ctx.tools.execute({name:config.namespace+'_message',arguments:{payload:{to:'all',text:'missing required fields'}},agent:{id:sessions[0],ctx},callId:randomUUID(),signal:new AbortController().signal})
  assert.equal(bad.isError,true)
  await addon.dispose()
  assert.equal(ctx.tools.schemas().length,1)
  assert.ok(ctx.tools.get('existing_fixture_tool'))
  assert.equal(fs.existsSync(path.join(directory,organization_id,'active.lock')),false)
  await existing.dispose()
  console.log(JSON.stringify({status:'PASSED',label:'SMOKE_KEYLESS_REAL_SDK_DEPENDENCIES_ONLY',versions,fixture_members:24,messages:24,schema_validation:true,native_registry_pipeline:true,own_tools_removed:true,existing_plugin_preserved:true,installed_user_runtime_verified:false,model_calls:0},null,2))
} finally { await ctx.fiber.dispose(); fs.rmSync(directory,{recursive:true,force:true}) }
