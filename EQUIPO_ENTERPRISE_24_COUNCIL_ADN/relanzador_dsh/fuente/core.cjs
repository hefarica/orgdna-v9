'use strict';
/* DSH REINICIAR 1.1.1 -- embedded, immutable execution core.
 * Only the launcher owns its state/logs. Never edits the Harness, packages,
 * sessions, prompts, profile patches, keys, backups or user projects.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { createRequire } = require('node:module');
const { spawn, execFile } = require('node:child_process');
const VERSION = '1.1.1';
const sleep = ms => new Promise(r => setTimeout(r, ms));
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
function fault(code, message) { return Object.assign(new Error(message), { code }); }
function json(p) { return JSON.parse(fs.readFileSync(p, 'utf8').replace(/^\uFEFF/, '')); }
function scrub(s) {
  return String(s || '').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/https?:\/\/[^\s<>"']+/gi, m => { try { const u=new URL(m); u.username='';u.password=''; for(const k of [...u.searchParams.keys()])u.searchParams.set(k,'REDACTED'); return u.href; }catch{return '<URL>';} })
    .replace(/(Bearer\s+)[A-Za-z0-9._~+\/=-]+/gi,'$1<REDACTED>')
    .replace(/((?:api[_-]?key|secret|password|access[_-]?token|authorization)\s*[=:]\s*)[^\r\n,}]+/gi,'$1<REDACTED>');
}
function emit(event, message, extra) { process.stdout.write(JSON.stringify({event,message,...extra})+'\n'); }
function atomic(p, o) {
  const t=p+'.tmp-'+crypto.randomUUID();
  fs.writeFileSync(t,JSON.stringify(o,null,2)+'\n',{flag:'wx',mode:0o600});
  try { fs.renameSync(t,p); } catch(e) { try{fs.unlinkSync(t);}catch{} throw e; }
}
function under(root, p) { const r=path.relative(path.resolve(root),path.resolve(p));return r===''||(!r.startsWith('..'+path.sep)&&r!=='..'&&!path.isAbsolute(r)); }
function tail(p, max=256*1024) {
  const fd=fs.openSync(p,'r');try{const n=fs.fstatSync(fd).size;const b=Buffer.alloc(Math.min(n,max));fs.readSync(fd,b,0,b.length,Math.max(0,n-b.length));return b.toString('utf8');}finally{fs.closeSync(fd);}
}
function expand(s) {
  if(typeof s!=='string')return s;
  return s.replace(/%([A-Za-z_][A-Za-z0-9_]*)%/g,(_,k)=>{const v=Object.entries(process.env).find(([x])=>x.toLowerCase()===k.toLowerCase());if(!v)throw fault('CONFIG_ENV','Variable de entorno desconocida: '+k);return v[1];});
}
function validateConfig(input, defaults) {
  if(!input||Array.isArray(input)||typeof input!=='object')throw fault('CONFIG_JSON','Configuracion JSON no valida.');
  const allowed=['schema','home','profile','runtime','port','startupTimeoutSeconds','stabilitySeconds','openBrowser','shutdownTimeoutSeconds','idleWaitSeconds','restartDebounceSeconds'];
  for(const k of Object.keys(input))if(!allowed.includes(k))throw fault('CONFIG_FIELD','Campo de configuracion no permitido: '+k);
  const c={...defaults,...input};
  if(c.schema!==1)throw fault('CONFIG_SCHEMA','Version de configuracion no compatible.');
  if(typeof c.profile!=='string'||!/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(c.profile))throw fault('CONFIG_PROFILE','Nombre de perfil no valido.');
  if(!Number.isInteger(c.port)||c.port<1024||c.port>65535)throw fault('CONFIG_PORT','Puerto no valido.');
  if(!Number.isInteger(c.startupTimeoutSeconds)||c.startupTimeoutSeconds<30||c.startupTimeoutSeconds>600)throw fault('CONFIG_TIMEOUT','Espera de arranque: entre 30 y 600 segundos.');
  if(!Number.isInteger(c.stabilitySeconds)||c.stabilitySeconds<3||c.stabilitySeconds>30)throw fault('CONFIG_STABILITY','Ventana de estabilidad: entre 3 y 30 segundos.');
  if(typeof c.openBrowser!=='boolean')throw fault('CONFIG_BROWSER','openBrowser debe ser true o false.');
  for(const [k,lo,hi] of [['shutdownTimeoutSeconds',10,120],['idleWaitSeconds',0,600],['restartDebounceSeconds',0,60]]){if(c[k]!==undefined&&(!Number.isInteger(c[k])||c[k]<lo||c[k]>hi))throw fault('CONFIG_TIMEOUT',k+' fuera de rango.');}
  c.home=path.resolve(expand(c.home)); c.runtime=path.resolve(expand(c.runtime));
  return c;
}
function extractUrls(text, port) {
  const clean=String(text||'').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g,'');
  const result=[];
  for(const m of clean.matchAll(/dsh\s+web:\s*(http:\/\/127\.0\.0\.1:\d+\/?\?token=[A-Za-z0-9%._~-]+)/gi)) {
    try {const u=new URL(m[1]);if(u.protocol==='http:'&&u.hostname==='127.0.0.1'&&+u.port===port&&u.pathname==='/'&&u.searchParams.getAll('token').length===1&&[...u.searchParams.keys()].length===1&&!u.username&&!u.password&&u.searchParams.get('token'))result.push(u.href);}catch{}
  }
  return [...new Set(result)].reverse();
}
function family(v) { return /^\d+\.\d+\.\d+/.exec(String(v||''))?.[0]||null; }
function assessVersions(rows) {
  const core=rows.filter(x=>x.family&&x.name.startsWith('@deepseek-ai/dsh-'));
  const generations=[...new Set(core.map(x=>x.family))];
  return {compatible:generations.length<=1,generations};
}
function rpcBody(method,args={}) { return {type:'client-request',rpcId:crypto.randomUUID(),method,payload:{args}}; }
function packageInfo(req, name) {
  const entry=req.resolve(name);let d=path.dirname(entry);
  for(let i=0;i<12;i++) {const p=path.join(d,'package.json');if(fs.existsSync(p)){const m=json(p);if(m.name===name)return {name,version:m.version,family:family(m.version),entry,manifest:p};}const up=path.dirname(d);if(up===d)break;d=up;}
  throw fault('PACKAGE_MANIFEST','No se pudo identificar el manifiesto de '+name);
}
function invokeBridge(host, payload) {
  return new Promise((resolve,reject)=>{
    execFile(host,['--probe',Buffer.from(JSON.stringify(payload)).toString('base64')],{windowsHide:true,timeout:15000,maxBuffer:512*1024},(e,out)=>{
      if(e&&!out)return reject(fault('WINDOWS_PROBE','Windows no confirmo la identidad del proceso. No se detuvo ni duplico DSH.'));
      try{const x=JSON.parse(out.replace(/^\uFEFF/,''));if(x.error)reject(fault(x.code||'WINDOWS_OPERATION',x.error));else resolve(x);}catch{reject(fault('WINDOWS_PROBE_JSON','Respuesta no interpretable al comprobar el proceso.'));}
    });
  });
}
async function authenticate(url, port) {
  const origin='http://127.0.0.1:'+port;
  const r=await fetch(url,{redirect:'manual',signal:AbortSignal.timeout(5000)});
  if(r.status!==303){await r.body?.cancel();return null;}
  const cookies=(r.headers.getSetCookie?.()||[]).filter(x=>/^dsh-auth-/i.test(x)).map(x=>x.split(';')[0]).join('; ');
  const location=r.headers.get('location')||'';
  await r.body?.cancel();
  let target;try{target=new URL(location,url);}catch{return null;}
  if(!cookies||target.origin!==origin||target.pathname!=='/'||target.search)return null;
  const h=await fetch(origin+'/',{redirect:'manual',headers:{Cookie:cookies},signal:AbortSignal.timeout(6000)});
  const body=await h.text();
  if(h.status!==200||!body.includes('__DSH_BOOT__'))return null;
  return {cookie:cookies,authStatus:303,httpStatus:200,hasBoot:true};
}
async function api(port,cookie,method,args={},payload=null) {
  const body=payload?{type:'client-request',rpcId:crypto.randomUUID(),method,payload}:rpcBody(method,args);
  const r=await fetch('http://127.0.0.1:'+port+'/api/'+method,{method:'POST',headers:{'Content-Type':'application/json',Cookie:cookie,Origin:'http://127.0.0.1:'+port},body:JSON.stringify(body),signal:AbortSignal.timeout(12000)});
  const x=await r.json();
  if(r.status!==200||x?.result?.ok!==true)throw fault('API_NOT_READY','La API '+method+' no confirmo estado correcto.');
  return x.result.value;
}
function ensureOrdinaryDirectory(p) {
  if(fs.existsSync(p)&&(!fs.lstatSync(p).isDirectory()||fs.lstatSync(p).isSymbolicLink()))throw fault('STATE_PATH','Directorio del lanzador no es una carpeta regular.');
  fs.mkdirSync(p,{recursive:true,mode:0o700});
}
// Launcher-owned lifecycle preload. Does not modify Harness files or routes.
// Only the CLI's existing SIGINT handler is invoked, from inside the same process.
const CONTROL_PRELOAD = String.raw`
import fs from 'node:fs';import net from 'node:net';import crypto from 'node:crypto';
const raw=process.env.HFRC_DSH_LIFECYCLE;delete process.env.HFRC_DSH_LIFECYCLE;
if(raw){
 const c=JSON.parse(Buffer.from(raw,'base64').toString('utf8'));let stopping=false;
 const same=(a,b)=>typeof a==='string'&&Buffer.byteLength(a)===Buffer.byteLength(b)&&crypto.timingSafeEqual(Buffer.from(a),Buffer.from(b));
 const server=net.createServer(socket=>{
  socket.setTimeout(4000,()=>socket.destroy());let text='';socket.on('error',()=>{});
  socket.on('data',chunk=>{
   text+=chunk;if(text.length>4096){socket.destroy();return;}if(!text.includes('\n'))return;
   socket.removeAllListeners('data');let q;try{q=JSON.parse(text.split('\n')[0]);}catch{socket.destroy();return;}
   if(!same(q.token,c.token)){socket.end(JSON.stringify({ok:false,code:'AUTH'})+'\n');return;}
   if(q.pid!==process.pid){socket.end(JSON.stringify({ok:false,code:'PID'})+'\n');return;}
   if(q.op==='status'){socket.end(JSON.stringify({ok:true,pid:process.pid,home:c.home,profile:c.profile,port:c.port,handlerCount:process.listenerCount('SIGINT'),stopping})+'\n');return;}
   if(q.op!=='shutdown'){socket.end(JSON.stringify({ok:false,code:'OP'})+'\n');return;}
   if(stopping){socket.end(JSON.stringify({ok:true,pid:process.pid,alreadyRequested:true})+'\n');return;}
   if(process.listenerCount('SIGINT')===0){socket.end(JSON.stringify({ok:false,code:'NO_GRACEFUL_HANDLER'})+'\n');return;}
   stopping=true;socket.end(JSON.stringify({ok:true,pid:process.pid,method:'CLI_SIGINT_HANDLER'})+'\n',()=>{
    server.close();setTimeout(()=>process.emit('SIGINT'),25);
   });
  });
 });
 server.on('error',e=>console.error('[launcher-lifecycle] '+String(e.code||'ERROR')));
 server.listen(c.pipe,()=>{
  const target=c.stateFile,tmp=target+'.tmp-'+crypto.randomUUID();
  fs.writeFileSync(tmp,JSON.stringify({schema:'hfrc.dsh.lifecycle.v1',pid:process.pid,home:c.home,profile:c.profile,port:c.port,pipe:c.pipe,token:c.token,at:new Date().toISOString()})+'\n',{flag:'wx',mode:0o600});fs.renameSync(tmp,target);server.unref();
 });
}
`;
function sessionItems(v){return Array.isArray(v)?v:Array.isArray(v?.items)?v.items:Array.isArray(v?.sessions)?v.sessions:[];}
function validSessionList(v){return Array.isArray(v)||Array.isArray(v?.items)||Array.isArray(v?.sessions);}
function identityKey(p){return p?String(p.pid)+'|'+String(p.createdUtc||''):'';}
function configFingerprint(config,manifest){
 const h=crypto.createHash('sha256'),seen=new Set();
 const add=f=>{if(fs.existsSync(f)){const real=fs.realpathSync(f);if(!seen.has(real)){seen.add(real);h.update(real).update(fs.readFileSync(real));}}};
 add(manifest);const pd=path.dirname(manifest);
 for(const n of ['cordis.patch.yml','cordis.patch.yaml','cordis.yml'])add(path.join(pd,n));
 const req=createRequire(manifest),m=json(manifest);
 for(const name of m.dsh?.profile?.bundles||[]){const info=packageInfo(req,name);add(info.manifest);const pm=json(info.manifest),patch=pm.dsh?.bundle?.patch;if(typeof patch==='string')add(path.resolve(path.dirname(info.manifest),patch));}
 // Include user preset descriptors, not node_modules or multi-GB conversations.
 const presets=path.join(config.home,'.agent-presets');if(fs.existsSync(presets))for(const d of fs.readdirSync(presets,{withFileTypes:true})){if(d.isDirectory()&&!d.isSymbolicLink()){add(path.join(presets,d.name,'agent.cordis.yml'));add(path.join(presets,d.name,'agent.cordis.yaml'));}}
 return h.update(JSON.stringify({home:config.home,runtime:config.runtime,profile:config.profile,port:config.port})).digest('hex');
}
function shouldRestart({checkOnly,reuse,recent,chosen,fingerprint,debounce=15}){
 if(checkOnly||reuse||!chosen)return false;
 const elapsed=Date.now()-Date.parse(recent?.completedAt);
 return !(recent?.status==='READY'&&recent.pid===chosen.pid&&recent.createdUtc===chosen.createdUtc&&recent.profileFingerprint===fingerprint&&recent.action==='restarted'&&elapsed>=0&&elapsed<debounce*1000);
}
function historyInventory(home){
 const roots=['sessions','.agent-presets','plugins','storages/cordis-dynamic'];const out=[],limit=Date.now()+20000;
 for(const rel of roots){const base=path.join(home,rel);if(!fs.existsSync(base))continue;const pending=[base];while(pending.length){
  if(Date.now()>limit||out.length>100000)throw fault('INVENTORY_LIMIT','No se completo el inventario de conservacion; no se cierra DSH.');
  for(const d of fs.readdirSync(pending.pop(),{withFileTypes:true})){if(d.name==='node_modules')continue;const f=path.join(d.parentPath||d.path,d.name);if(d.isSymbolicLink())continue;if(d.isDirectory())pending.push(f);else if(d.isFile()){const st=fs.statSync(f);out.push({path:path.relative(home,f),bytes:st.size,mtime:st.mtimeMs});}}
 }}return out;
}
function lifecycleRequest(state,op){return new Promise((resolve,reject)=>{
 const socket=require('node:net').connect(state.pipe);let text='',done=false;
 const end=(e,x)=>{if(done)return;done=true;socket.destroy();e?reject(e):resolve(x);};
 socket.setTimeout(6000,()=>end(fault('CONTROL_TIMEOUT','El canal de cierre no respondio. No se fuerza el proceso.')));
 socket.once('error',()=>end(fault('CONTROL_UNAVAILABLE','El canal de cierre no esta disponible.')));
 socket.once('connect',()=>socket.write(JSON.stringify({op,token:state.token,pid:state.pid})+'\n'));
 socket.on('data',b=>{text+=b;if(text.length>16384)return end(fault('CONTROL_REPLY','Respuesta de control excesiva.'));if(text.includes('\n')){try{const x=JSON.parse(text.split('\n')[0]);if(!x.ok)return end(fault(x.code||'CONTROL_REFUSED','DSH no acepto el cierre ordenado.'));end(null,x);}catch{end(fault('CONTROL_REPLY','Respuesta de control invalida.'));}}});
 socket.once('end',()=>{if(!done)end(fault('CONTROL_CLOSED','Canal cerrado sin confirmacion.'));});
});}
function pathEq(a,b){try{return process.platform==='win32'?path.resolve(a).toLowerCase()===path.resolve(b).toLowerCase():path.resolve(a)===path.resolve(b);}catch{return false;}}
function lifecycleState(root,config,chosen){
 const f=path.join(root,'state','control-'+config.profile+'-'+config.port+'.json');let s;try{s=json(f);}catch{return null;}
 if(s.schema!=='hfrc.dsh.lifecycle.v1'||s.pid!==chosen.pid||!pathEq(s.home,config.home)||s.profile!==config.profile||s.port!==config.port||!(process.platform==='win32'?/^\\\\\.\\pipe\\hfrc-dsh-life-[a-f0-9-]+$/i.test(s.pipe):typeof s.pipe==='string'&&under(path.join(root,'state'),s.pipe))||!/^[a-f0-9]{64}$/.test(s.token))return null;
 return s;
}
function logsFor(root,config,chosen,currentLog){
 const dirs=[path.join(root,'logs'),path.join(process.env.LOCALAPPDATA,'DSH_HISTORIAL_PROTEGIDO','logs')],set=new Set();if(currentLog)set.add(currentLog);
 for(const f of [path.join(root,'state','server.json'),path.join(process.env.LOCALAPPDATA,'DSH_HISTORIAL_PROTEGIDO','state','server-attempt.json')]){try{const s=json(f);if(s.pid&&s.pid!==chosen.pid)continue;if(typeof s.log==='string'&&dirs.some(d=>under(d,s.log))&&path.extname(s.log)==='.log')set.add(s.log);}catch{}}
 for(const d of dirs){if(!fs.existsSync(d))continue;const list=fs.readdirSync(d,{withFileTypes:true}).filter(x=>x.isFile()&&!x.isSymbolicLink()&&x.name.startsWith('dsh-')&&x.name.endsWith('.log')).map(x=>{const f=path.join(d,x.name);return{f,t:fs.statSync(f).mtimeMs};}).sort((a,b)=>b.t-a.t).slice(0,10);for(const x of list)set.add(x.f);}
 return [...set];
}
async function findAuthentication(root,config,chosen,currentLog,failed=new Set()){
 for(const f of logsFor(root,config,chosen,currentLog)){let txt;try{txt=tail(f);}catch{continue;}for(const url of extractUrls(txt,config.port)){const k=sha(url);if(failed.has(k))continue;try{const a=await authenticate(url,config.port);if(a)return{...a,url,log:f};failed.add(k);}catch{}}}return null;
}
function validateDependencies(manifest){
 const req=createRequire(manifest),names=['@deepseek-ai/dsh-session','@deepseek-ai/dsh-session-format-catalog','@deepseek-ai/dsh-session-persistence-jsonl','@deepseek-ai/dsh-llm','@deepseek-ai/dsh-llm-deepseek','@deepseek-ai/dsh-attachment','@deepseek-ai/dsh-subprocess','@deepseek-ai/dsh-subprocess-local'];
 const rows=names.map(n=>{try{return packageInfo(req,n);}catch{throw fault('DEPENDENCY_MISSING','No se resuelve '+n+'. Se conserva el DSH actual.');}});
 const assessed=assessVersions(rows);if(!assessed.compatible)throw fault('DEPENDENCIES_MIXED','Dependencias incompatibles: '+assessed.generations.join(' / ')+'. No se cierra DSH ni se cambian paquetes.');
 const bundles=json(manifest)?.dsh?.profile?.bundles;
 if(!Array.isArray(bundles)||bundles.some(n=>typeof n!=='string'||!n))throw fault('BUNDLES_INVALID','El perfil no declara una lista de bundles valida.');
 if(new Set(bundles).size!==bundles.length)throw fault('BUNDLES_DUPLICATE','El perfil repite un bundle. No se cierra DSH.');
 if(bundles.includes('@nanmicoder/dsh-agent-teams')&&bundles.includes('dsh-agent-squad'))throw fault('AGENT_TEAMS_DUPLICATE','Los dos bundles agent-teams estan habilitados. No se modifica el perfil ni se cierra DSH.');
 const entries=bundles.map(n=>{try{return packageInfo(req,n);}catch{throw fault('BUNDLE_UNRESOLVED','El complemento '+n+' no se resuelve. No se cierra DSH.');}});
 return {rows,bundles,entries};
}
async function getIdleSessions(config,cookie,event){
 const {port}=config,deadline=Date.now()+config.idleWaitSeconds*1000;let quiet=0;
 for(;;){const v=await api(port,cookie,'session/list',{_request:{}});if(!validSessionList(v))throw fault('SESSION_STATUS_UNKNOWN','No se identifico el estado de los chats; no se cierra DSH.');const items=sessionItems(v);
 if(items.some(x=>typeof x.running!=='boolean'||!(x.sessionId||x.id)))throw fault('SESSION_STATUS_UNKNOWN','Faltan identidades o estados de chats; no se cierra DSH.');
 const busy=items.filter(s=>s.running).length;
 if(!busy){if(++quiet>=2)return items;await sleep(750);continue;}
 quiet=0;if(Date.now()>=deadline)throw fault('SESSIONS_BUSY','Hay '+busy+' turnos activos. No se cancelaron ni se reinicio DSH.');event('Esperando '+busy+' turnos activos; se conserva su trabajo...');await sleep(3000);
 }
}
function dynamicItems(d){if(Array.isArray(d))return d;if(Array.isArray(d?.plugins))return d.plugins;throw fault('DYNAMIC_INVENTORY_UNKNOWN','No se confirmo el inventario de plugins dinamicos.');}
async function run(options){
 const root=options.stateRoot;ensureOrdinaryDirectory(root);for(const d of ['state','logs','checkpoints'])ensureOrdinaryDirectory(path.join(root,d));
 const reportPath=path.join(root,'state','last-result.json'),statePath=path.join(root,'state','server.json');let recent;try{recent=json(path.join(root,'state','last-restart.json'));}catch{}
 const report={schema:'hfrc.dsh.launcher.result.v2',launcher:VERSION,at:new Date().toISOString(),status:'CHECKING',launcherModifiesHistory:false,packagesInstalled:0,backupsTriggered:false};
 const event=message=>emit('progress',message),save=()=>atomic(reportPath,report);
 let config,entry,child,currentLog,chosen,beforeSessions=null,beforeDynamic=[],beforeFiles=null,profileHash;
 try{
 const defaults={schema:1,home:path.join(process.env.USERPROFILE,'.dsh'),runtime:path.join(process.env.USERPROFILE,'.dsh-vscode','server'),profile:'web',port:3080,startupTimeoutSeconds:240,stabilitySeconds:5,openBrowser:true,shutdownTimeoutSeconds:45,idleWaitSeconds:120,restartDebounceSeconds:15};
 const cfgPath=path.join(root,'launcher.json');if(!fs.existsSync(cfgPath))atomic(cfgPath,defaults);config=validateConfig(json(cfgPath),defaults);
 const {home,runtime,profile,port}=config;entry=path.join(runtime,'node_modules','@deepseek-ai','dsh','lib','bin.js');const manifest=path.join(home,'profiles',profile,'package.json');
 for(const f of [home,runtime,entry,manifest])if(!fs.existsSync(f))throw fault('PROFILE_MISSING','Falta '+f+'. No se crea otro entorno.');
 Object.assign(report,{home,profile,port,entry,requestedAction:options.checkOnly?'check':options.reuse?'open':'restart'});
 const native=payload=>invokeBridge(options.hostExe,{entry,profile,port,nodeExe:process.execPath,...payload}),probe=()=>native({action:'probe'});
 const guard=p=>{if(p.listeners.some(x=>x.reason==='identity_unreadable'))throw fault('IDENTITY_PERMISSION','Windows no permite identificar este DSH desde la ventana actual; se requiere autorizacion UAC. No se considera un puerto ajeno.');if(p.listeners.some(x=>!x.expected))throw fault('PORT_FOREIGN','El puerto '+port+' pertenece a un programa distinto del DSH configurado. No se detiene.');if(new Set(p.listeners.map(x=>x.pid)).size>1)throw fault('PORT_MULTIPLE','Hay varios propietarios del puerto.');if(p.processes.length>1)throw fault('MULTIPLE_DSH','Hay varios DSH para el perfil. No se duplica.');};
 event('Identificando DSH y leyendo los complementos habilitados del perfil actual...');
 let p=await probe();report.nativeProbe=p;guard(p);chosen=p.listeners[0]||p.processes[0]||null;
 const deps=validateDependencies(manifest);report.bundles=deps.bundles;report.dependencyCheck=deps.rows;profileHash=configFingerprint(config,manifest);report.profileFingerprint=profileHash;
 const disk=fs.statfsSync(root);report.freeBytes=Number(disk.bavail)*Number(disk.bsize);if(report.freeBytes<256*1024*1024)throw fault('DISK_FULL','Menos de 256 MiB libres. No se borra nada.');
 let restart=shouldRestart({checkOnly:options.checkOnly,reuse:options.reuse,recent,chosen,fingerprint:profileHash,debounce:config.restartDebounceSeconds});
 if(chosen&&!p.listeners.length){event('DSH ya esta arrancando. Se espera ese proceso sin crear otro.');restart=false;}
 if(chosen&&restart){
  event('Validando el acceso y esperando a que no haya turnos activos...');
  const oldAuth=await findAuthentication(root,config,chosen,null);if(!oldAuth)throw fault('CURRENT_AUTH_UNCONFIRMED','No se confirmo el acceso al DSH actual. No se fuerza su cierre.');
  const items=await getIdleSessions(config,oldAuth.cookie,event);beforeSessions=items.map(s=>s.sessionId||s.id);report.sessionCountBefore=beforeSessions.length;
  beforeDynamic=dynamicItems(await api(port,oldAuth.cookie,'dynamicCordisRunner/inventory')).map(x=>({id:x.pluginId,package:x.currentPackageId,status:x.latestRun?.status}));
  const dynamicState=path.join(home,'storages','cordis-dynamic','state-v1.json');
  if(beforeDynamic.length){let saved;try{saved=json(dynamicState);}catch{throw fault('DYNAMIC_STATE_NOT_DURABLE','Hay plugins dinamicos sin estado persistente legible. No se reinicia.');}if(!saved||!Array.isArray(saved.plugins)||beforeDynamic.some(d=>!d.id||!saved.plugins.some(x=>x.pluginId===d.id&&x.currentPackageId===d.package)))throw fault('DYNAMIC_STATE_NOT_DURABLE','No coincide la persistencia de plugins con el inventario activo. No se reinicia.');}
  beforeFiles=historyInventory(home);const checkpoint=path.join(root,'checkpoints',Date.now()+'-'+crypto.randomUUID());ensureOrdinaryDirectory(checkpoint);
  atomic(path.join(checkpoint,'inventory.json'),{at:new Date().toISOString(),home,profile,sessionIds:beforeSessions,dynamicPlugins:beforeDynamic,files:beforeFiles});
  fs.copyFileSync(manifest,path.join(checkpoint,'profile-package.json'),fs.constants.COPYFILE_EXCL);
  if(fs.existsSync(dynamicState)&&fs.statSync(dynamicState).size<16*1024*1024)fs.copyFileSync(dynamicState,path.join(checkpoint,'cordis-state.json'),fs.constants.COPYFILE_EXCL);
  report.checkpoint=checkpoint;
  // Final idle recheck immediately before shutdown; no model prompts are sent.
  const finalItems=await getIdleSessions({...config,idleWaitSeconds:0},oldAuth.cookie,event);beforeSessions=[...new Set([...beforeSessions,...finalItems.map(s=>s.sessionId||s.id)])];report.sessionCountBefore=beforeSessions.length;
  if(configFingerprint(config,manifest)!==profileHash)throw fault('CONFIG_CHANGED_DURING_CHECK','El perfil cambio durante la preparacion. No se cierra DSH; ejecuta de nuevo con los cambios guardados.');
  p=await probe();guard(p);if(!p.listeners.some(x=>identityKey(x)===identityKey(chosen)))throw fault('PROCESS_CHANGED','El propietario cambio antes del cierre. No se detuvo ningun proceso.');
  const oldIdentity={...chosen};report.previousPid=chosen.pid;report.previousCreatedUtc=chosen.createdUtc;
  let lifecycle=lifecycleState(root,config,chosen),method;
  if(lifecycle){const st=await lifecycleRequest(lifecycle,'status');if(st.pid!==chosen.pid||!pathEq(st.home,home)||st.profile!==profile)throw fault('CONTROL_IDENTITY','El canal no corresponde al perfil.');event('Solicitando cierre ordenado al DSH identificado...');await lifecycleRequest(lifecycle,'shutdown');method='CLI_SIGINT_HANDLER';}
  else{
   const r=await native({action:'console-stop',pid:chosen.pid,createdUtc:chosen.createdUtc});
   if(r.sent){method='WINDOWS_CTRL_C';event('Cierre ordenado enviado al DSH anterior...');}
   else{if(!options.allowLegacyStop)throw fault('LEGACY_RESTART_CONFIRMATION','Este DSH anterior no tiene canal de cierre. Se requiere confirmar una sola transicion al reinicio administrado.');event('Transicion confirmada: cerrando SOLO el DSH anterior identificado, sin turnos activos...');await native({action:'legacy-stop',pid:chosen.pid,createdUtc:chosen.createdUtc,consent:true});method='LEGACY_IDLE_EXPLICIT_STOP';}
  }
  report.shutdownMethod=method;const end=Date.now()+config.shutdownTimeoutSeconds*1000;
  while(Date.now()<end){await sleep(750);p=await probe();guard(p);if(!p.processes.some(x=>identityKey(x)===identityKey(oldIdentity))&&!p.listeners.some(x=>identityKey(x)===identityKey(oldIdentity)))break;}
  if(p.processes.some(x=>identityKey(x)===identityKey(oldIdentity)))throw fault('SHUTDOWN_TIMEOUT','DSH no completo el cierre. No se fuerza ni se inicia otro servidor.');
  chosen=p.listeners[0]||p.processes[0]||null;report.action='restarted';if(chosen)event('Un supervisor ya inicio el reemplazo; se reutiliza sin duplicarlo.');
 }
 if(!chosen){
  if(options.checkOnly)throw fault('DSH_OFFLINE','DSH esta apagado; la comprobacion no lo inicia.');
  const now=validateDependencies(manifest);report.bundles=now.bundles;profileHash=configFingerprint(config,manifest);report.profileFingerprint=profileHash;
  p=await probe();guard(p);chosen=p.listeners[0]||p.processes[0]||null;
  if(!chosen){
   event('Arrancando el mismo perfil con sus parametros y complementos actuales...');
   currentLog=path.join(root,'logs','dsh-'+new Date().toISOString().replace(/[:.]/g,'-')+'-'+crypto.randomUUID().slice(0,8)+'.log');
   const stateFile=path.join(root,'state','control-'+profile+'-'+port+'.json');
   const control={stateFile,home,profile,port,token:crypto.randomBytes(32).toString('hex'),pipe:process.platform==='win32'?'\\\\.\\pipe\\hfrc-dsh-life-'+crypto.randomUUID():path.join(root,'state','ctl-'+crypto.randomUUID().slice(0,8)+'.sock')};
   const env={...process.env,DSH_HOME:home,HFRC_DSH_LIFECYCLE:Buffer.from(JSON.stringify(control)).toString('base64')};delete env.DSH_LAUNCHER_RUN;delete env.NODE_OPTIONS;delete env.NODE_PATH;
   const fd=fs.openSync(currentLog,'wx',0o600);
   try{child=spawn(process.execPath,['--import','data:text/javascript;base64,'+Buffer.from(CONTROL_PRELOAD).toString('base64'),entry,'--profile',profile,'--host','127.0.0.1','--port',String(port),'--no-open'],{cwd:runtime,env,detached:true,windowsHide:true,stdio:['ignore',fd,fd]});}finally{fs.closeSync(fd);}
   await new Promise((res,rej)=>{child.once('spawn',res);child.once('error',rej);});child.unref();chosen={pid:child.pid};if(!report.action)report.action='started';
   atomic(statePath,{schema:'hfrc.dsh.launcher.server.v2',pid:child.pid,entry,home,profile,port,log:currentLog,startedAt:new Date().toISOString(),status:'STARTING'});
  }
 }
 if(!report.action)report.action=options.checkOnly?'checked':'reused';report.pid=chosen.pid;
 const failed=new Set(),end=Date.now()+config.startupTimeoutSeconds*1000;let auth=null,pulse=0;
 while(Date.now()<end){if(child&&child.exitCode!==null)throw fault('SERVER_EXITED','DSH termino antes de estar listo. Codigo '+child.exitCode+'.');auth=await findAuthentication(root,config,chosen,currentLog,failed);if(auth)break;if(Date.now()-pulse>6000){pulse=Date.now();p=await probe();guard(p);if(!p.processes.some(x=>x.pid===chosen.pid)&&(!child||child.exitCode!==null||child.signalCode!==null))throw fault('SERVER_DISAPPEARED','DSH termino antes de verificar la interfaz.');event('DSH esta cargando. Se comprueba el proceso; no se inicia otro...');}await sleep(1000);}
 if(!auth)throw fault('READINESS_TIMEOUT','No se confirmo el acceso autenticado. Se conserva el proceso si esta activo.');
 p=await probe();guard(p);const identity=p.listeners.find(x=>x.pid===chosen.pid&&x.expected);if(!identity)throw fault('PROCESS_CHANGED','Cambio el servidor durante la autenticacion.');
 event('Interfaz autenticada. Verificando chats, perfil y plugins...');Object.assign(report,{createdUtc:identity.createdUtc,log:auth.log,authStatus:303,httpStatus:200,hasBoot:true});
 const catalog=await api(port,auth.cookie,'session/modelCatalog'),presets=await api(port,auth.cookie,'agentPresets/list'),sessions=await api(port,auth.cookie,'session/list',{_request:{}});
 if(!validSessionList(sessions))throw fault('SESSION_STATUS_UNKNOWN','No se reconoce la lista posterior de chats.');const ids=sessionItems(sessions).map(s=>s.sessionId||s.id).filter(Boolean);report.sessionCount=ids.length;report.apiChecks=['session/modelCatalog','agentPresets/list','session/list'];
 report.presets=(presets.presets||[]).map(x=>({id:x.id,isDefault:x.isDefault}));report.modelCatalogFailureCount=(catalog.failures||[]).length;
 if(beforeSessions){const missing=beforeSessions.filter(id=>!ids.includes(id));report.chatsRetained=missing.length===0;if(missing.length)throw fault('HISTORY_NOT_RECONFIRMED','Faltan chats en la lista posterior. No se restaura ni borra nada automaticamente.');}
 const dyn=dynamicItems(await api(port,auth.cookie,'dynamicCordisRunner/inventory')).map(x=>({id:x.pluginId,package:x.currentPackageId,status:x.latestRun?.status}));report.dynamicPlugins=dyn;report.apiChecks.push('dynamicCordisRunner/inventory');
 if(beforeDynamic.some(d=>!dyn.some(x=>x.id===d.id&&x.package===d.package&&(d.status!=='running'||x.status==='running'))))throw fault('DYNAMIC_RESTORE_UNCONFIRMED','No se confirmo la restauracion de todos los plugins dinamicos. Estado anterior conservado en el punto de control.');
 if(report.bundles.includes('dsh-agent-team-gui')){const g=await api(port,auth.cookie,'agentTeamGui',null,{endpoint:'snapshot',payload:{}});report.agentTeam={agents:g.agents?.length||0,squads:g.squads?.length||0,tools:g.tools?.length||0};report.apiChecks.push('agentTeamGui/snapshot');}
 if(beforeFiles){const after=historyInventory(home),set=new Set(after.map(x=>x.path)),missing=beforeFiles.filter(x=>!set.has(x.path));report.persistedFileCountBefore=beforeFiles.length;report.persistedFileCountAfter=after.length;report.missingPersistedFiles=missing.length;if(missing.length)throw fault('FILES_NOT_RECONFIRMED','No se reconfirmaron todos los archivos persistentes. No se restaura automaticamente.');}
 await sleep(config.stabilitySeconds*1000);p=await probe();guard(p);if(!p.listeners.some(x=>identityKey(x)===identityKey(identity)))throw fault('NOT_STABLE','DSH no se mantuvo estable durante la comprobacion.');if(!await authenticate(auth.url,port))throw fault('AUTH_LOST','DSH dejo de aceptar su autenticacion.');
 report.status='READY';report.completedAt=new Date().toISOString();report.backupsPaused=fs.existsSync(path.join(process.env.LOCALAPPDATA,'DSH_HISTORIAL_PROTEGIDO','state','pause-backups.flag'));report.automaticTaskResumption=false;save();
 if(report.action==='restarted')atomic(path.join(root,'state','last-restart.json'),{status:'READY',pid:report.pid,createdUtc:report.createdUtc,profileFingerprint:report.profileFingerprint,action:'restarted',completedAt:report.completedAt});
 atomic(statePath,{schema:'hfrc.dsh.launcher.server.v2',pid:identity.pid,createdUtc:identity.createdUtc,entry,home,profile,port,log:auth.log,startedAt:identity.createdUtc,status:'READY'});
 emit('ready',report.action==='restarted'?'DSH reiniciado. Perfil, chats y complementos verificados.':'DSH disponible con tu entorno actual.',{summary:report,url:config.openBrowser&&!options.noOpen?auth.url:null});return report;
 }catch(e){report.status='FAILED';report.errorCode=e.code||'UNEXPECTED';report.error=scrub(e.message);report.completedAt=new Date().toISOString();if(currentLog){try{report.logTail=scrub(tail(currentLog,32000).split(/\r?\n/).slice(-50).join('\n'));}catch{}}try{save();}catch{}emit('failed',report.error,{code:report.errorCode,report:reportPath});process.exitCode=1;return report;}
}
module.exports={validateConfig,extractUrls,assessVersions,family,scrub,under,authenticate,api,rpcBody,run,VERSION,CONTROL_PRELOAD,sessionItems,identityKey,shouldRestart,historyInventory,lifecycleState,lifecycleRequest,configFingerprint,getIdleSessions};
if(process.env.DSH_LAUNCHER_RUN==='1'){
 let opts;try{opts=JSON.parse(Buffer.from(process.argv[1],'base64').toString('utf8'));}catch{emit('failed','Parametros del lanzador invalidos.');process.exit(2);}
 run(opts).then(()=>process.exit(process.exitCode||0)).catch(e=>{emit('failed',scrub(e.message));process.exit(1);});
}
