"""Manual Council and improvement records. Does not run agents or certify tests."""
from __future__ import annotations
import copy
from datetime import datetime, timezone
import hashlib
import json
import uuid

ACTIONS={'subteam-save','council-create','council-add-entry','council-close','skill-register','skill-update','skill-feedback','remediation-create','remediation-update'}

class RecordError(ValueError):pass

def _now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def _id():return str(uuid.uuid4())
def _text(value,field,limit=6000,optional=False):
    if not isinstance(value,str) or len(value)>limit or (not value.strip() and not optional) or any(ord(c)<32 and c not in '\n\t' for c in value):
        raise RecordError(f'{field}: texto vacío, demasiado largo o no válido.')
    return value.strip()
def _evidence(value):
    if value is None:return []
    if not isinstance(value,list) or len(value)>30:raise RecordError('evidence debe contener como máximo 30 referencias.')
    return [_text(v,'evidence',2000) for v in value]
def _find(rows,key):
    row=next((r for r in rows if r['id']==key),None)
    if row is None:raise RecordError('No existe el registro indicado.')
    return row

def apply_record_action(organization,records,action,body):
    if action not in ACTIONS:raise RecordError('Acción de registro desconocida.')
    result=copy.deepcopy(records)
    councils=result.setdefault('council_sessions',[])
    skills=result.setdefault('skill_registry',[])
    remediations=result.setdefault('remediation_records',[])
    subteams=result.setdefault('subteams',[])
    agents={a['id']:a for a in (organization or {}).get('agents',[])}
    def agent(aid,external=False):
        if aid not in agents and not(external and aid=='OWNER_EXTERNAL'):raise RecordError('Selecciona un agente del diseño actual.')
        return aid
    if action=='subteam-save':
        if not agents:raise RecordError('Genera una organización antes de crear un subequipo.')
        kind=body.get('type')
        if kind not in {'audit','consulting'}:raise RecordError('El subequipo debe ser audit o consulting.')
        members=body.get('member_ids')
        if not isinstance(members,list) or not members or len(members)>len(agents) or len(set(members))!=len(members):
            raise RecordError('Selecciona miembros únicos de la organización actual.')
        for aid in members:agent(aid)
        facilitator=body.get('facilitator_id') or members[0]
        if facilitator not in members:raise RecordError('El facilitador debe pertenecer al subequipo.')
        row={'name':_text(body.get('name'),'name',160),'type':kind,'member_ids':members,'facilitator_id':facilitator,
             'scope':_text(body.get('scope',''),'scope',6000,optional=True),'origin':'manual_entry','status':'proposed',
             'line_management':False,'audit_independence_verified':False,'auto_launch':False}
        if body.get('id'):
            existing=_find(subteams,body['id'])
            history=list(existing.get('history',[]))+[{k:v for k,v in existing.items() if k!='history'}]
            row.update(id=existing['id'],version=existing.get('version',1)+1,history=history,created_at=existing['created_at'],updated_at=_now())
            subteams[subteams.index(existing)]=row
        else:
            if len(subteams)>=16:raise RecordError('Máximo 16 subequipos funcionales por diseño.')
            row.update(id=_id(),version=1,history=[],created_at=_now());subteams.append(row)
    elif action=='council-create':
        if not agents:raise RecordError('Genera una organización antes de crear el acta.')
        if len(councils)>=100:raise RecordError('Máximo 100 actas por proyecto; crea un proyecto nuevo para continuar.')
        digest=hashlib.sha256(json.dumps(organization,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        councils.append({'id':_id(),'title':_text(body.get('title'),'title',160),'created_at':_now(),
            'organization_sha256':digest,'status':'open_manual_record','members':list(agents),'entries':[],
            'verified_agent_run':False,'origin':'manual_entry','summary':'','version':1,
            'participation':{'required':len(agents),'contributed':0,'missing_agent_ids':list(agents),'all_members_recorded':False}})
    elif action=='council-add-entry':
        council=_find(councils,body.get('session_id'))
        if council['status']!='open_manual_record':raise RecordError('El acta está cerrada; crea una nueva para añadir aportaciones.')
        kind=body.get('type')
        if kind not in {'fact','risk','objection','proposal','decision'}:raise RecordError('Tipo de aportación no válido.')
        aid=body.get('agent_id')
        if aid not in council['members'] and not(aid=='OWNER_EXTERNAL' and kind=='decision'):raise RecordError('La identidad no pertenece al snapshot del acta.')
        if len(council['entries'])>=500:raise RecordError('El acta alcanzó 500 entradas.')
        council['entries'].append({'id':_id(),'agent_id':aid,'type':kind,'text':_text(body.get('text'),'text'),
            'evidence':_evidence(body.get('evidence')),'created_at':_now(),'origin':'manual_entry','recorded_by':'user',
            'verified_agent_run':False,'decision_executed':False})
        council['version']=council.get('version',1)+1
    elif action=='council-close':
        council=_find(councils,body.get('session_id'))
        if council['status']!='open_manual_record':raise RecordError('Esta acta ya está cerrada.')
        council['summary']=_text(body.get('summary'),'summary',10000)
        council['status']='closed_manual_record';council['closed_at']=_now()
        contributed={e['agent_id'] for e in council['entries']}
        council['missing_contributions']=[aid for aid in council['members'] if aid not in contributed]
        council['runtime_council_complete']=False
        council['version']=council.get('version',1)+1
    elif action=='skill-register':
        if len(skills)>=500:raise RecordError('Máximo 500 propuestas de skills por proyecto.')
        owner=body.get('owner_agent_id') or 'OWNER_EXTERNAL';agent(owner,external=True)
        skills.append({'id':_id(),'name':_text(body.get('name'),'name',160),'description':_text(body.get('description'),'description'),
            'owner_agent_id':owner,'status':'proposed','version':1,'installed':False,'verified':False,'origin':'manual_entry',
            'evidence':_evidence(body.get('evidence')),'created_at':_now(),'history':[]})
    elif action=='skill-update':
        row=_find(skills,body.get('skill_id'));status=body.get('status')
        if status not in {'proposed','under_review','test_reported','approved_manual','rejected'}:raise RecordError('Estado de skill no válido.')
        evidence=_evidence(body.get('evidence'))
        if status in {'test_reported','approved_manual'} and not evidence:raise RecordError('Una prueba o aprobación declarada requiere referencias de evidencia.')
        row['history'].append({'status':status,'note':_text(body.get('note'),'note'),'evidence':evidence,'recorded_at':_now(),'origin':'manual_entry'})
        row['status']=status;row['version']+=1;row['evidence']+=evidence
        row['installed']=False;row['verified']=False
    elif action=='skill-feedback':
        row=_find(skills,body.get('skill_id'))
        aid=agent(body.get('agent_id'),external=True)
        evidence=_evidence(body.get('evidence'))
        if not evidence:raise RecordError('El feedback requiere referencias de evidencia.')
        if len(row.get('feedback',[]))>=500:raise RecordError('Máximo 500 aportaciones por skill.')
        row.setdefault('feedback',[]).append({'id':_id(),'agent_id':aid,'failure':_text(body.get('failure'),'failure'),
            'proposed_change':_text(body.get('proposed_change'),'proposed_change'),'retest_result':_text(body.get('retest_result'),'retest_result'),
            'evidence':evidence,'recorded_at':_now(),'origin':'manual_entry','runtime_identity_verified':False,'verified':False})
        row['version']+=1;row['installed']=False;row['verified']=False
    elif action=='remediation-create':
        aid=agent(body.get('agent_id'))
        if body.get('skill_id'):_find(skills,body['skill_id'])
        if len(remediations)>=500:raise RecordError('Máximo 500 correcciones por proyecto.')
        remediations.append({'id':_id(),'agent_id':aid,'skill_id':body.get('skill_id'),'failure':_text(body.get('failure'),'failure'),
            'expected':_text(body.get('expected'),'expected'),'actual':_text(body.get('actual'),'actual'),
            'evidence':_evidence(body.get('evidence')),'status':'observed','events':[],'created_at':_now(),
            'origin':'manual_entry','tests_executed_by_app':False,'effectiveness_verified':False})
    elif action=='remediation-update':
        row=_find(remediations,body.get('remediation_id'));status=body.get('status')
        transitions={'observed':{'proposed','rejected'},'proposed':{'testing','rejected'},'testing':{'supervisor_review','proposed','rejected'},
            'supervisor_review':{'independent_review','proposed','rejected'},'independent_review':{'closed','proposed','rejected'},'closed':set(),'rejected':{'proposed'}}
        if status not in transitions.get(row['status'],set()):raise RecordError('La transición requiere avanzar por propuesta, pruebas, supervisor y revisión independiente.')
        evidence=_evidence(body.get('evidence'));reviewer=body.get('reviewer_id')
        if status in {'supervisor_review','independent_review','closed'} and not evidence:raise RecordError('La revisión/cierre requiere referencias de evidencia.')
        if status=='supervisor_review':
            agent(reviewer,external=True)
            if reviewer!=agents[row['agent_id']]['reports_to']:raise RecordError('La revisión de supervisor debe registrarse con el supervisor asignado.')
        if status=='independent_review':
            agent(reviewer,external=True)
            if reviewer==row['agent_id']:raise RecordError('El autor no puede ser su auditor independiente.')
            def ancestors(aid):
                seen=set()
                while aid in agents:
                    aid=agents[aid]['reports_to']
                    if aid in seen:break
                    seen.add(aid)
                return seen
            if reviewer!='OWNER_EXTERNAL' and (reviewer in ancestors(row['agent_id']) or row['agent_id'] in ancestors(reviewer)):
                raise RecordError('Hay conflicto en la cadena de mando; selecciona revisión externa independiente.')
        row['events'].append({'status':status,'note':_text(body.get('note'),'note'),'evidence':evidence,'reviewer_id':reviewer,'recorded_at':_now(),'origin':'manual_entry'})
        row['status']=status;row['evidence']+=evidence
        if status=='closed':row['closed_at']=_now()
        # Manual review is evidence recorded by the user, not execution verified
        # by a connected agent harness; never silently promote these booleans.
        row['tests_executed_by_app']=False;row['effectiveness_verified']=False
    for council in councils:
        contributed={entry['agent_id'] for entry in council.get('entries',[]) if entry.get('agent_id') in council['members']}
        missing=[aid for aid in council['members'] if aid not in contributed]
        council['participation']={'required':len(council['members']),'contributed':len(contributed),
            'missing_agent_ids':missing,'all_members_recorded':not missing,'runtime_identity_verified':False}
    return result
