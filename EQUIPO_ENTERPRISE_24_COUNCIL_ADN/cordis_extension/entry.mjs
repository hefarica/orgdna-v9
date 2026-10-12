/** Native Harness plugin, not legacy cordis_define JavaScript. */
import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { mount } from './plugin.mjs'
import { SUPPORTED_TOOLS_VERSIONS } from './runtime.mjs'
import { registerLiveBridge } from './live_bridge.mjs'
import { installNativeProfileScopes } from './native_orchestration.mjs'
import { registerNativeStageUI } from './native_stage_ui.mjs'
export const name = 'orgdna-shared-coordination'
export const inject = ['tools']
export async function apply(ctx, config) {
  if (config?.enabled !== true && config?.live_connection?.enabled !== true && config?.native_orchestration?.enabled !== true && config?.native_stage_ui?.enabled !== true) return
  if(config.native_orchestration?.enabled===true&&config.native_stage_ui?.enabled===true)throw new Error('Choose native review UI or a pre-reviewed manual hook, not both')
  let coordination = { status: 'DISABLED' }
  if (config.enabled === true) {
    const require = createRequire(import.meta.url)
    const installed = JSON.parse(readFileSync(require.resolve('@deepseek-ai/dsh-tools/package.json'), 'utf8'))
    if (installed.name !== '@deepseek-ai/dsh-tools' || !SUPPORTED_TOOLS_VERSIONS.includes(installed.version)) throw new Error('Installed DSH Tools version not supported; addon remains unloaded')
    coordination = mount(ctx, { ...config, verified_tools_version: installed.version }, defineTool)
  }
  // Registration alone starts no listener. Native authenticated UI requires a
  // distinct human click and shows a short-lived, one-use pairing code.
  const result = { coordination, connection: { status: 'DISABLED' } }
  if (config.live_connection?.enabled === true) {
    if (typeof ctx.inject === 'function') {
      result.connection = { status: 'WAITING_FOR_NATIVE_CONNECTION' }
      ctx.inject(['connection'], connectionContext => {
        result.connection = registerLiveBridge(connectionContext, { ...config.live_connection,
          native_stage_available:()=>result.native_stage_ui?.status==='NATIVE_STAGE_UI_READY',
        })
      })
    } else {
      result.connection = { status: 'UNAVAILABLE', reason: 'Native Cordis dependency injection unavailable' }
    }
  }
  if(config.native_stage_ui?.enabled===true) {
    if(typeof ctx.inject!=='function')throw new Error('Native dependency injection unavailable')
    result.native_stage_ui={status:'WAITING_FOR_NATIVE_SERVICES'}
    ctx.inject(['connection','agentTeamGui','agents'],async nativeContext=>{
      result.native_stage_ui=await registerNativeStageUI(nativeContext,{
        ...config.native_stage_ui,expected_organization_id:config.organization_id,
        expected_member_ids:config.members?.map(member=>member.member_id),
        ...(coordination.ledger?{bindSession:(session,member)=>coordination.ledger.bindRuntimeSession(session,member)}:{}),
      })
    })
  }
  if(config.native_orchestration?.enabled===true) {
    const {foldSubagentDescriptor}=await import('@deepseek-ai/dsh-subagent')
    result.native_scopes=installNativeProfileScopes(ctx,config.native_orchestration.approved_plan,foldSubagentDescriptor,{
      owner_approved_sha256:config.native_orchestration.owner_approved_plan_sha256,
      ...(coordination.ledger?{bindSession:(session,member)=>coordination.ledger.bindRuntimeSession(session,member)}:{}),
    })
  }
  return result
}
