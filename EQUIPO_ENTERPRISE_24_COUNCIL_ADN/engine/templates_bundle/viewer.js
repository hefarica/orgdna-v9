'use strict';
const data=JSON.parse(document.getElementById('profile-data').textContent);
const el=id=>document.getElementById(id);
const normalize=value=>String(value).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
let filtered=[],selected=null;
function renderProfile(){
  selected=filtered.find(p=>p.id===el('roster').value)||filtered[0]||null;
  el('copy').disabled=!selected;el('download').disabled=!selected;el('status').textContent='';
  el('title').textContent=selected?selected.name+' · '+selected.display_name:'Sin resultados';
  el('meta').textContent=selected?selected.title+'\nID: '+selected.id+'\nSupervisor: '+selected.supervisor+'\nReportes directos: '+selected.direct_reports+'\nModelo: '+selected.provider+' / '+selected.model+' · '+selected.model_status:'';
  el('mission').textContent=selected?selected.mission:'';
  el('prompt').textContent=selected?selected.systemPrompt:'';
  el('profile').textContent=selected?JSON.stringify({cv:selected.cv,skills:selected.skills,supervision:selected.supervision,journeys:selected.journeys},null,2):'';
  el('command-summary').textContent=selected?selected.name+' → '+selected.command.chain_of_command.map(p=>p.name).join(' → '):'';
  el('command').textContent=selected?JSON.stringify(selected.command,null,2):'';
  const scope=selected&&selected.permissions.toolScope;
  el('permission-summary').textContent=selected?(scope&&scope.allow?'Allow: '+scope.allow.length+' nombres exactos.':'Allow omitida: hereda herramientas visibles del padre.')+' Deny: '+(scope&&scope.deny?scope.deny.length:0)+'. Disponibilidad y permisos efectivos pendientes de verificar. Una lista no autoriza cada acción.':'';
  el('permissions').textContent=selected?JSON.stringify(selected.permissions,null,2):'';
  el('performance-summary').textContent=selected?'Sin evaluar en este paquete. Score y ranking: sin datos. Los resultados del proyecto local no se incluyen; esto no borra su historial. Ascensos y recompensas son recomendaciones sujetas a revisión y aprobación.':'';
  el('performance').textContent=selected?JSON.stringify({initial_state:selected.performance,contract:selected.performance_contract},null,2):'';
}
function filterProfiles(){
  const words=normalize(el('search').value).split(/\s+/).filter(Boolean);
  const previous=selected&&selected.id;
  filtered=data.profiles.filter(p=>words.every(w=>normalize(JSON.stringify(p)).includes(w)));
  el('roster').replaceChildren();
  for(const p of filtered){const option=document.createElement('option');option.value=p.id;option.textContent=p.slot+'. '+p.name+' · '+p.display_name;el('roster').appendChild(option);}
  if(filtered.some(p=>p.id===previous))el('roster').value=previous;else if(filtered.length)el('roster').value=filtered[0].id;
  el('count').textContent=filtered.length+' de '+data.profiles.length+' perfiles';renderProfile();
}
el('heading').textContent=data.project+' · '+data.profiles.length+' perfiles';
el('overview').textContent=data.profiles.length+' participantes Council en lectura; hasta '+data.coordination_policy.max_writers+' escritores coordinados por registro local. El registro no bloquea archivos ni ejecuta DSH.';
el('governance-policy').textContent=JSON.stringify(data.governance_policy,null,2);
el('coordination-policy').textContent=JSON.stringify(data.coordination_policy,null,2);
el('skill-distinction').textContent=JSON.stringify(data.tool_catalog.skill_distinction,null,2);
function filterTools(){
  const words=normalize(el('tool-search').value).split(/\s+/).filter(Boolean);
  const tools=data.tool_catalog.tools.filter(t=>words.every(word=>normalize(JSON.stringify(t)).includes(word)));
  el('tool-count').textContent=tools.length+' de '+data.tool_catalog.tools.length+' herramientas';
  el('tool-catalog').textContent=tools.map(t=>t.name+' · '+t.category+' · riesgo '+t.risk_level+'\n'+t.description+'\nRoles propuestos: '+t.recommended_roles.join(', ')+'\nDisponibilidad: '+t.availability).join('\n\n')||'Sin resultados';
}
el('tool-search').addEventListener('input',filterTools);
el('search').addEventListener('input',filterProfiles);
el('clear').addEventListener('click',()=>{el('search').value='';filterProfiles();el('search').focus();});
el('roster').addEventListener('change',renderProfile);
el('copy').addEventListener('click',async()=>{
  if(!selected)return;
  try{if(!navigator.clipboard)throw new Error('Clipboard unavailable');await navigator.clipboard.writeText(selected.systemPrompt);el('status').textContent='Prompt copiado.';}
  catch(error){const range=document.createRange();range.selectNodeContents(el('prompt'));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);el('status').textContent='Copia automática no disponible. Texto seleccionado: usa Ctrl+C o Cmd+C.';}
});
el('download').addEventListener('click',()=>{if(!selected)return;const blob=new Blob([selected.systemPrompt],{type:'text/plain;charset=utf-8'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=selected.filename.split('/').pop();a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
filterProfiles();
filterTools();
