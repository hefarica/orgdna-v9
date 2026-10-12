/** Test double of public Teams service. Never loads, starts or contacts DSH. */
import { createReadAdapter, createLocalBridge } from '../live_bridge.mjs'
const versions = {'@deepseek-ai/dsh-tools':'0.2.1-alpha.1','@deepseek-ai/dsh-client-connection':'0.2.1-alpha.1','dsh-agent-team-gui':'1.3.0','@nanmicoder/dsh-agent-teams':null}
const teamService = {
  async readDefinitionSnapshot() { return {agents:new Map([['definition-only-A',{name:'Engineer',systemPrompt:'Review code',provider:'spawn',model:'fixture'}]]),squads:new Map([['squad-A',{name:'Existing squad',members:['definition-only-A']} ]])} },
  async previewRecipe(document) { return {status:'preview',format:document.format,creates:0,updates:1,source:'official-service-double'} },
  async previewDefinitionsImport(document, mode) { return {status:'preview',format:document.format,mode,source:'official-service-double'} },
}
const ctx = {get:name=>name==='agentTeamGui'?teamService:undefined,tools:{schemas:()=>[{name:'read_file'}]}}
const bridge=await createLocalBridge(createReadAdapter(ctx,versions),versions)
const {dispose,...descriptor}=bridge
process.stdout.write(JSON.stringify(descriptor)+'\n')
process.stdin.resume()
process.stdin.on('end',()=>void dispose())
process.on('SIGTERM',()=>void dispose().then(()=>process.exit(0)))
