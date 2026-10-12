"""Source-verified DSH autonomy proposals, bounded goals and a real Plan preview.

Settings describe a selected-team runtime, never import-time execution or authority.
The user's declared project goal is separate from authorization of its next action.
"""
from __future__ import annotations

if __package__:
    from .limits import MAX_AGENTS
else:
    from limits import MAX_AGENTS

import copy
import json
import re

PRESETS=('autonomous','smart','manual')
SOURCE_COMMIT='14ea11960b20b1f93c33541ba9df7746ed16d08a'
CONFIG_KEYS={'autonomy_preset','planning_context','response_mode','planner_max_tokens',
             'member_timeout_ms','handoff_summary_max_chars','runtime_token_budget','quality_gate_rounds','objective','orchestration_backend'}
NATIVE_OPTIONAL_KEYS={'memberTimeoutMs','tokenBudget','handoffSummaryMaxChars','qualityGate'}


def _integer(value,field,minimum,maximum):
    if type(value) is not int or not minimum<=value<=maximum:
        raise ValueError(f'{field}: entero {minimum}..{maximum} requerido.')
    return value


def _text(value,field,limit=5000):
    if not isinstance(value,str) or len(value.encode('utf-16-le'))//2>limit or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]',value):
        raise ValueError(f'{field}: texto válido de hasta {limit} UTF16 requerido.')
    return value.strip()


def normalize_autonomy_config(raw,enabled=True):
    if not isinstance(raw,dict): raise ValueError('Configuración de autonomía debe ser objeto.')
    backend=raw.get('orchestration_backend','teams_gui')
    if backend not in ('teams_gui','agentteams_native'):
        raise ValueError('orchestration_backend debe ser teams_gui o agentteams_native.')
    preset=raw.get('autonomy_preset','autonomous' if enabled else 'manual')
    if preset not in PRESETS: raise ValueError('autonomy_preset debe ser autonomous, smart o manual.')
    planning=raw.get('planning_context','current' if preset=='manual' else 'full')
    if planning not in ('current','recent','full'):raise ValueError('planning_context debe ser current, recent o full.')
    response=raw.get('response_mode','foreground')
    if response not in ('foreground','background'):raise ValueError('response_mode debe ser foreground o background.')
    n=raw.get('agent_count',raw.get('n',24))
    if isinstance(n,str) and n.isdigit():n=int(n)
    n=_integer(n,'agent_count',1,MAX_AGENTS)
    return {'autonomy_preset':preset,'orchestration_backend':backend,'planning_context':planning,'response_mode':response,
        'planner_max_tokens':_integer(raw.get('planner_max_tokens',8192),'planner_max_tokens',256,8192),
        'member_timeout_ms':_integer(raw.get('member_timeout_ms',900000),'member_timeout_ms',1000,3600000),
        'handoff_summary_max_chars':_integer(raw.get('handoff_summary_max_chars',16000),'handoff_summary_max_chars',1000,32000),
        'runtime_token_budget':_integer(raw.get('runtime_token_budget',max(24000,n*12000)),'runtime_token_budget',1,100000000),
        'quality_gate_rounds':_integer(raw.get('quality_gate_rounds',2),'quality_gate_rounds',0,2),
        'objective':_text(raw.get('objective',raw.get('project_objective','')),'objective')}


def _financial_project(config,analysis):
    repository=analysis.get('repository',{}) if isinstance(analysis.get('repository'),dict) else {}
    observed_name=repository.get('full_name') or repository.get('url')
    url_name=(config.get('repo_url') or '').rstrip('/').split('/')[-1].removesuffix('.git')
    project_name=(str(observed_name).rstrip('/').split('/')[-1].removesuffix('.git') if observed_name else url_name or config.get('repo_name',''))
    if 'arbitragex' in project_name.casefold():
        return True
    objective=config.get('objective',config.get('project_objective',''))
    if isinstance(objective,str) and re.search(r'(?:operar|operaci[oó]n|operate|trading).{0,70}(?:capital real|real capital)|(?:desplegar|deploy).{0,70}mainnet|(?:beneficio|profit).{0,40}(?:neto|net|USD)',objective,re.I):
        return True
    observed=set(x.get('path') if isinstance(x,dict) else x for x in analysis.get('repository_files',[]) if isinstance(x,(str,dict)))
    for item in analysis.get('signals',[]):
        if isinstance(item,dict) and item.get('evidence_path') in observed and any(k in item.get('technology','').casefold() for k in ('defi','arbitrage','trading','market microstructure')):
            return True
    return False


def mission_for_project(config,analysis=None):
    analysis=analysis if isinstance(analysis,dict) else {}
    objective=config.get('objective',config.get('project_objective',''))
    if isinstance(objective,str) and objective.strip(): return _text(objective,'objective')
    if _financial_project(config,analysis):
        name=config.get('repo_name') or 'el proyecto financiero seleccionado'
        return ('Desarrollar, validar y desplegar '+name+' en mainnet para operar con capital real '
                'dentro de un mandato y presupuesto de riesgo explícitos, y buscar beneficio neto realizado '
                'positivo en USD después de gas, fees, slippage, financiación, pérdidas e infraestructura. '
                'La rentabilidad es un objetivo que debe demostrarse; no está garantizada ni acreditada por simulaciones.')
    name=config.get('repo_name') or 'el repositorio seleccionado'
    return ('Comprender y completar '+name+' con un plan específico del código, entregar funcionalidad útil '
            'y comprobada, y preparar su despliegue y operación dentro del mandato, presupuesto y permisos '
            'aplicables; demostrar calidad y resultados con evidencia reproducible.')


def _ancestors(aid,byid):
    seen=set()
    while aid in byid:
        aid=byid[aid].get('reports_to')
        if aid in seen: return set(byid)
        if aid not in byid: break
        seen.add(aid)
    return seen


def _quality_gate(agents,rounds):
    if not isinstance(agents,list) or len(agents)<3:return None
    byid={a['id']:a for a in agents if isinstance(a,dict) and 'id' in a}
    reviewers=[a for a in byid.values() if 'auditor' in a.get('functional_roles',[]) and a.get('role')!='CEO']
    repair_codes=('CTO','BACKEND','FRONTEND','DATA','INTEGRATION','BUILD')
    repairs=[a for a in byid.values() if a.get('tool_preset_role',a.get('role')) in repair_codes and 'auditor' not in a.get('functional_roles',[])]
    repairs.sort(key=lambda a:repair_codes.index(a.get('tool_preset_role',a.get('role'))))
    reviewers.sort(key=lambda a:({'ASSURANCE':0,'EVIDENCE':1,'QA':2,'SECURITY':3}.get(a.get('tool_preset_role',a.get('role')),4),a.get('slot',99)))
    for repair in repairs:
        for reviewer in reviewers:
            rid,wid=reviewer['id'],repair['id']
            if rid==wid or rid in _ancestors(wid,byid) or wid in _ancestors(rid,byid):continue
            return {'reviewerAgentId':rid,'repairAgentId':wid,'maxRounds':rounds,
                'criteria':'Sólo gates de ingeniería sobre SHA exacto y artefactos reproducibles. El planner reserva al revisor fuera de la autoría de producción y de pruebas usadas como única aceptación; no duplicar nodos/agentes en el DAG. Confirmar independencia real por artefacto, no inferirla del CV ni del árbol. Si hay conflicto: BLOCKED y Owner nombra revisión independiente. Cada reparación requiere fallo demostrado, alcance acotado y retest; máximo de rondas indicado, sin ocultar FAIL/BLOCKED/NOT_RUN. No repetir transacciones, movimientos de capital, despliegues ni efectos no idempotentes como reparación automática. Un saludo o ausencia de mandato produce sólo diagnóstico y propuesta, nunca ejecución.'}
    return None


def build_autonomy(config,analysis=None,agents=None):
    config=config if isinstance(config,dict) else {}
    analysis=analysis if isinstance(analysis,dict) else {}
    agents=agents if isinstance(agents,list) else []
    enabled=True
    normalized=normalize_autonomy_config(config,enabled=enabled)
    backend=normalized['orchestration_backend']
    preset=normalized['autonomy_preset'];n=config.get('agent_count',config.get('n',24))
    if isinstance(n,str) and n.isdigit():n=int(n)
    n=_integer(n,'agent_count',1,MAX_AGENTS)
    concurrency=config.get('implementation_concurrency',3)
    concurrency=min(n,_integer(concurrency,'implementation_concurrency',1,3))
    base={'activationMode':'always' if preset=='autonomous' else preset,'triggerMode':'guaranteed',
          'executionMode':'parallel','contextMode':'fork','failurePolicy':'stop',
          'planningContext':normalized['planning_context'],'plannerMaxTokens':normalized['planner_max_tokens'],
          'responseMode':normalized['response_mode']}
    # Legacy manual exports keep their narrow schema. Explicit presets expose the
    # same source-supported bounded options without inventing unlimited execution.
    if preset!='manual' or config.get('autonomy_preset') is not None:
        base.update(memberTimeoutMs=normalized['member_timeout_ms'],tokenBudget=normalized['runtime_token_budget'],
                    handoffSummaryMaxChars=normalized['handoff_summary_max_chars'])
    implementation=dict(base,memberSelectionMode='adaptive',maxConcurrency=concurrency)
    council=dict(base,memberSelectionMode='all',maxConcurrency=n)
    gate=_quality_gate(agents,normalized['quality_gate_rounds'])
    if gate and (preset!='manual' or config.get('autonomy_preset') is not None):implementation['qualityGate']=gate
    if backend=='agentteams_native':
        for settings in (implementation,council):
            settings.update(activationMode='manual',triggerMode='model-tool')
            settings.pop('qualityGate',None)
    orchestration={'backend':backend,'profile_source':'Teams GUI definitions (fuente única de perfiles)',
        'task_orchestrator':'AgentTeams' if backend=='agentteams_native' else 'Teams GUI',
        'capability_runtime':'Cordis (requiere preflight)' if backend=='agentteams_native' else 'Herramientas visibles verificadas en preflight',
        'captain_count':1,'teammate_count':n-1,'total_profile_count':n,'gui_dispatch_enabled':backend=='teams_gui',
        'captain_profile_id':agents[0].get('id') if agents else None,
        'teammate_profile_ids':[a['id'] for a in agents[1:] if isinstance(a,dict) and 'id' in a],
        'status':'NATIVE_PREFLIGHT_REQUIRED' if backend=='agentteams_native' else 'RUNTIME_PREFLIGHT_REQUIRED',
        'preflight_required':['Verificar versiones, límites de miembros, cuotas y herramientas realmente disponibles; no inferir instalación desde export.',
            'Confirmar que no hay un squad GUI activo ni otro equipo Captain que duplique esta organización.',
            'Mapear el Captain existente al perfil CEO y crear únicamente N−1 teammates con estos mismos perfiles.',
            'Verificar aplicación efectiva de cada toolScope en la ruta AgentTeams; si no está comprobada, bloquear ejecución.',
            'Presentar y obtener aprobaciones nativas de creación y plan que el runtime exija; no desactivar controles.',
            'Copiar ADN íntegro de cada perfil a execution_prompt del plan; verificar hash, SHA y cobertura antes de ejecutar.'] if backend=='agentteams_native' else ['Seleccionar el squad correcto en la sesión y verificar modelos, herramientas y permisos.'],
        'runtime_verified':False,'installed':False,'active_agent_count':None,
        'engineering_quality_gate_proposal':copy.deepcopy(gate) if backend=='agentteams_native' else None}
    contract=(f'ORCHESTRATION_BACKEND={backend}. '+
        (f'Teams GUI conserva los {n} perfiles como fuente única y queda pasivo (manual/model-tool): no llamar dispatch_to_squad. AgentTeams es el único orquestador; usar 1 Captain existente (CEO) + {n-1} teammates = {n} agentes totales, nunca Captain + N. Cordis aporta capacidades tras preflight, sin afirmar instalación. Antes de crear/ejecutar: no squad GUI activo ni equipo nativo duplicado; aprobar creación/plan cuando el runtime lo exija; verificar ADN completo en execution_prompt y cumplimiento real de toolScope. Sin enforcement comprobado, BLOCKED. Máximo 3 escritores; revisión independiente y fases Council/implementación en el mismo equipo.' if backend=='agentteams_native' else
         'Teams GUI es el único orquestador de esta variante; no crear además un equipo AgentTeams para los mismos perfiles. Cambiar de backend requiere selección explícita, preflight y cerrar la ejecución anterior.'))
    orchestration['prompt_contract']=contract
    mission=mission_for_project(dict(config,objective=normalized['objective']),analysis)
    financial=_financial_project(config,analysis)
    repository=analysis.get('repository',{}) if isinstance(analysis.get('repository'),dict) else {}
    sha=repository.get('sha') or 'SHA pendiente de lectura/verificación'
    coverage=analysis.get('coverage',{}) if isinstance(analysis.get('coverage'),dict) else {}
    paths=analysis.get('repository_files',[])
    if not isinstance(paths,list):paths=[]
    evidence=[x.get('path') if isinstance(x,dict) else x for x in paths if isinstance(x,(dict,str))]
    evidence=[x for x in evidence if isinstance(x,str)]
    titles=list(dict.fromkeys(a.get('title') for a in agents if isinstance(a,dict) and isinstance(a.get('title'),str)))
    capabilities=titles or list(dict.fromkeys(x.get('technology',x.get('name','')) for x in analysis.get('signals',[]) if isinstance(x,dict)))
    capabilities=[x for x in capabilities if x][:32]
    greeting=('Ante «hola», un saludo o una petición abierta, el CEO/líder presenta la misión del proyecto, '
              'SHA y cobertura realmente leídos, capacidades objetivo y herramientas por verificar, brechas, '
              'riesgos, un plan priorizado y las decisiones/autorizaciones que faltan. '
              'Es una orientación y propuesta de diagnóstico sólo lectura; no es autorización para mover fondos, '
              'gastar capital, desplegar, editar producción ni relanzar a todo el equipo. '
              'En implementación, selección adaptive y máximo 3 escritores sólo para tareas autorizadas y disjuntas. '
              'Si el usuario selecciona Council, pueden participar los N agentes sólo lectura; el CEO consolida '
              'sus informes después, en una tarea individual nueva, sin otro dispatch Council-all.')
    if backend=='agentteams_native':
        greeting=greeting.replace('Si el usuario selecciona Council, pueden participar los N agentes sólo lectura; el CEO consolida sus informes después, en una tarea individual nueva, sin otro dispatch Council-all.', 'Council es una fase de deliberación sólo lectura dentro del mismo equipo AgentTeams; el Captain consolida los informes en una tarea propia posterior, sin activar un squad GUI ni crear otro equipo.')
        greeting+=' Modo nativo: el Captain existente presenta la organización; no se dispara Teams GUI. Los otros N−1 perfiles sólo existen como teammates tras creación y preflight confirmados; no afirmar que N agentes están activos.'
    limitations=[
        'Importar/exportar no selecciona un equipo en la sesión, no inicia agentes ni habilita herramientas. El dispatch automático depende del equipo seleccionado y del plugin DSH instalado.',
        'always + guaranteed puede generar una ejecución y consumo de tokens por cada mensaje de la sesión con equipo seleccionado; Council puede consumir N intervenciones. Cambiar a manual o Solo evita ese automatismo.',
        'smart permite que el planner decida no activar el equipo. failurePolicy stop evita reintentos ciegos de efectos no idempotentes.',
        'El límite de tokens propuesto es por run y no equivale a un presupuesto monetario ni de capital; confirmar costes, cuotas y saldo del proveedor antes de operar.',
        'full usa el contexto disponible de la sesión: no garantiza memoria entre sesiones ni lectura completa del repositorio. Prompts, títulos y presets no son ACL.',
        'Un objetivo de rentabilidad, despliegue o capital real no acredita resultados ni autoriza automáticamente una transacción. Beneficio neto realizado: desconocido hasta conciliación independiente.',
        'Las herramientas son propuestas exactas del catálogo, no instalación ni permiso. Mantener mandato, permisos efectivos, leases, máximo 3 escritores y revisión independiente.']
    if backend=='agentteams_native':
        limitations[0]='Modo nativo: Teams GUI es catálogo pasivo. Importar no crea ni arranca AgentTeams/Cordis; Captain y herramientas nativas requieren preflight y aprobaciones aplicables.'
        limitations[1]='Los squads se exportan manual/model-tool para impedir doble dispatch. La meta de autonomía se implementa en Captain/AgentTeams, no lanzando también los N perfiles desde Teams GUI.'
        limitations.append('No se declara toolScope enforcement nativo ni instalación verificados. Si el adaptador no demuestra el aislamiento de herramientas por agente, el plan de ejecución queda bloqueado.')
    if not gate:limitations.append('QualityGate automático omitido: no hay par interno de revisor e implementador con independencia estructural y funciones suficientes; Owner debe resolver la revisión, sin inventar IDs.')
    else:limitations.append(('Propuesta de gates para AgentTeams' if backend=='agentteams_native' else 'QualityGate')+' permite hasta '+str(normalized['quality_gate_rounds'])+' reparaciones de ingeniería; la independencia por artefacto y el mandato se comprueban en cada run. No se aplica al Council.')
    coverage_summary=json.dumps(coverage,ensure_ascii=False,sort_keys=True,separators=(',',':'))
    if len(coverage_summary)>3500:coverage_summary=coverage_summary[:3500]+'… [detalle completo en el sidecar; este preview es un resumen]'
    reference_paths='; '.join(evidence[:12]) or 'ninguna ruta leída; primero recopilar evidencia en modo lectura'
    plan=(f'PLAN PREVIEW · {config.get("repo_name") or "Repositorio pendiente"}\n'
          f'Repositorio: {config.get("repo_url") or repository.get("url") or "URL pendiente"}\n'
          f'SHA de referencia: {sha}\n'
          f'Objetivo declarado: {mission}\n'
          f'Evidencia de entrada ({len(evidence)} rutas leídas): {reference_paths}\n'
          f'Cobertura declarada por el lector: {coverage_summary or "pendiente"}\n'
          f'Equipo: N={n}; implementación adaptive, máximo {concurrency} escritores; Council all/{n} sólo lectura.\n'
          '1. CEO: confirmar mandato, objetivo medible, snapshot, cobertura omitida, herramientas y permisos; distinguir hechos, inferencias y propuestas. Un saludo sólo activa esta presentación y propuesta de diagnóstico.\n'
          '2. Contrastar la arquitectura y las brechas contra archivos leídos; asignar un responsable existente por entregable, dependencias y criterios de aceptación. Si falta evidencia, proponer su lectura antes de inferir capacidades.\n'
          '3. Preparar DAG específico de este repositorio con task_id, run_id, phase_id, candidate_sha, dueño, archivos exclusivos, lease, pruebas, presupuesto, handoff y rollback. Un nodo por agente; reservar al revisor independiente fuera de la autoría del candidato.\n'
          '4. Implementar únicamente tareas concretas autorizadas con máximo 3 escritores aislados. Conservar FAIL/BLOCKED/NOT_RUN, probar errores y regresión; comparar candidato exacto y evidencia independiente.\n')
    if financial:
        plan+=('5. '+(config.get('repo_name') or 'Proyecto financiero')+': verificar contratos y redes objetivo, financiación, claves bajo control humano, atomicidad, balances, gas, fees, slippage, deuda y fallos adversariales. Comparar simulación/testnet/mainnet sin equiparar sus pruebas. Preparar despliegue mainnet y operación con capital real sólo después de auditoría, mandato y presupuesto de pérdida/exposición aprobados, monitorización y parada segura.\n'
               '6. Medir beneficio neto realizado en USD por operación y periodo mediante conciliación independiente de entradas, salidas, balances, gas, comisiones, slippage, financiación, pérdidas e infraestructura. No presentar una oportunidad teórica ni una simulación como beneficio realizado; resultado actual desconocido.\n')
    else:
        plan+=('5. Preparar entrega o despliegue pertinente al repositorio: integración, migraciones, configuración, observabilidad, recuperación y pruebas E2E. Identificar cambios que requieren autorización antes de realizarlos.\n'
               '6. Verificar resultados reales de usuario, SHA desplegado, contratos, salud semántica y rollback; no confundir healthcheck, plan, mock o ausencia de logs con aceptación.\n')
    plan+=('Decisiones pendientes: alcance y definición de éxito; presupuesto API/operativo; entorno y destinos de despliegue; autorización específica de cambios, fondos y límites de riesgo cuando correspondan; acceso efectivo a herramientas; revisión independiente.\n'
           'Respuesta esperada: resumen de hechos con rutas/SHA; brechas y riesgos; plan priorizado con criterios verificables; solicitudes de autorización necesarias. Este texto se pega en el campo de tarea del Plan preview; no existe un campo previewTask en el JSON nativo.')
    plan=contract+'\n'+plan
    return {'version':'1.0','preset':preset,'orchestration':orchestration,'orchestration_contract':contract,'settings':{'implementation':implementation,'council':council},
        'mission':mission,'financial_goal':financial,'realized_net_usd':None,'profit_verified':False,
        'greeting_contract':greeting,'plan_preview':plan,'capabilities':capabilities,'limitations':limitations,
        'source':{'commit':SOURCE_COMMIT,'schema':'src/spec.ts','limits':'src/limits.ts',
                  'runtime':'src/index.ts selected-session team pre-step; tools/application/execution-service.ts'},
        'quality_gate_status':('AGENTTEAMS_REVIEW_GATES_REQUIRED' if backend=='agentteams_native' else 'PROPOSED_REQUIRES_ARTIFACT_INDEPENDENCE' if gate else 'REQUIRES_INDEPENDENT_REVIEW_SETUP'),
        'runtime_verified':False,'applied_to_runtime':False}


def validate_autonomy(org):
    value=org.get('autonomy')
    if value is None:return []  # Older persisted designs remain readable.
    expected=build_autonomy(org.get('config',{}),org.get('analysis',{}),org.get('agents',[]))
    if isinstance(value,dict) and 'orchestration' not in value and 'orchestration_backend' not in org.get('config',{}):
        # Read-compatible v3 GUI-only snapshots predate the explicit backend field.
        # Validate their original content; a native selection can never enter here.
        legacy=copy.deepcopy(expected)
        legacy.pop('orchestration',None);contract=legacy.pop('orchestration_contract',None)
        if contract and legacy.get('plan_preview','').startswith(contract+'\n'):
            legacy['plan_preview']=legacy['plan_preview'][len(contract)+1:]
        return [] if value==legacy else ['Metadatos de autonomía previos no coinciden con el diseño; reconstruir antes de exportar.']
    return [] if value==expected else ['Metadatos de autonomía/objetivo no coinciden con configuración, perfiles o evidencia; reconstruir antes de exportar.']
