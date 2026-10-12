"""Deterministic proposals for fictional agent teams. No execution or human profiling."""
from __future__ import annotations
import re
from collections import defaultdict

OWNER = 'OWNER_EXTERNAL'
ALGORITHM = 'functional-role-affinity-v1'
FAMILIES = {
    'engineering': {'CTO','ARCHITECTURE','BACKEND','FRONTEND','INTEGRATION','BUILD','RELEASE','SRE','PERFORMANCE','UX'},
    'assurance': {'QA','ASSURANCE','SECURITY','PRIVACY','EVIDENCE','E2E','PARITY','CHAOS'},
    'research': {'DATA','QUANT','GRAPH','MARKET','AI','SEARCH','CONTRACTS','LEDGER'},
    'operations': {'OWNEROPS','DOCS','SPEC'},
}
LEADERS = {'CEO': 0, 'CTO': 1, 'ARCHITECTURE': 2, 'QA': 3, 'ASSURANCE': 4, 'DATA': 5, 'QUANT': 6}

def _role(agent):
    return agent.get('tool_preset_role') if agent.get('tool_preset_role') not in (None, 'manual_review') else agent.get('role')

def _family(agent):
    return next((key for key, roles in FAMILIES.items() if _role(agent) in roles), 'custom')

def _terms(agent):
    text = ' '.join([agent.get('department',''), agent.get('mission','')] + [s.get('name','') for s in agent.get('skills',[]) if s.get('source') != 'hierarchy_assignment'])
    return set(re.findall(r'[\wáéíóúñ]{4,}', text.casefold())) - {'para','with','from','como','sobre','tarea','trabajo','evidencia','objetivo','objetivos','proyecto'}

def functional_hierarchy(agents, span):
    """Parent precedes child in a stable priority order, so cycles cannot form."""
    if not agents or agents[0].get('role') != 'CEO' or not 1 <= span <= 8:
        raise ValueError('Jerarquía funcional requiere CEO raíz y span 1..8.')
    root = agents[0]
    ordered = [root] + sorted(agents[1:], key=lambda a:(LEADERS.get(_role(a), 20), _role(a)=='OWNEROPS', a.get('slot',0), a['id']))
    parents = {root['id']: OWNER}; depths = {root['id']: 1}; counts = defaultdict(int)
    rationales = [{'agent_id':root['id'], 'manager_id':OWNER, 'reason':'CEO único bajo Owner externo.'}]
    assigned = [root]
    for agent in ordered[1:]:
        candidates = [a for a in assigned if counts[a['id']] < span]
        def score(parent):
            # Personal operations is not a technical supervisor unless topology makes it unavoidable.
            mismatch = _role(parent) == 'OWNEROPS' and _family(agent) != 'operations'
            affinity = len(_terms(parent) & _terms(agent)) / max(1, len(_terms(parent) | _terms(agent)))
            return (not mismatch, 30 * (_family(parent)==_family(agent) and _family(agent)!='custom')
                    + 12 * (_role(parent) in ('CTO','ARCHITECTURE') and _family(agent) in ('engineering','research'))
                    + 10 * (_role(parent)=='CEO') + 8 * (_role(parent) in LEADERS) + 10*affinity
                    - 4*depths[parent['id']] - 2*counts[parent['id']], -parent.get('slot',0))
        parent = max(candidates, key=score)
        parents[agent['id']] = parent['id']; counts[parent['id']] += 1
        depths[agent['id']] = depths[parent['id']] + 1; assigned.append(agent)
        rationales.append({'agent_id':agent['id'], 'manager_id':parent['id'],
            'declared_family':_family(agent), 'manager_declared_family':_family(parent),
            'reason':'Afinidad de rol/preset, departamento y competencias declaradas; prioridad de liderazgo, capacidad de span y desempate estable. No acredita capacidad de supervisión.',
            'capacity_fallback':_family(parent) != _family(agent) and _role(parent) not in ('CEO','CTO','ARCHITECTURE')})
    return parents, rationales

def apply_functional_hierarchy(agents, span):
    parents, rationales = functional_hierarchy(agents, span)
    by_id = {a['id']:a for a in agents}
    for a in agents: a['reports_to']=parents[a['id']]; a['direct_reports']=[]
    for a in agents:
        if a['reports_to'] != OWNER: by_id[a['reports_to']]['direct_reports'].append(a['id'])
        depth=0; current=a['id']
        while current != OWNER: depth+=1; current=parents[current]
        a['depth']=depth-1
    return rationales

def derive_design_reports(org):
    agents=org['agents']; groups=defaultdict(list); evidence=defaultdict(list); specialties=defaultdict(list)
    for a in agents:
        groups[' '.join(a.get('mission','').casefold().split())].append(a['id'])
        evidence[tuple(sorted(a.get('evidence_paths',[])))].append(a['id'])
        specialties[tuple(sorted(s.get('name','').casefold() for s in a.get('skills',[]) if s.get('source')!='hierarchy_assignment'))].append(a['id'])
    gaps=[]
    for kind, values in [('duplicate_mission',groups),('shared_evidence',evidence),('duplicate_specialties',specialties)]:
        for signature, members in values.items():
            if signature and len(members)>1:
                gaps.append({'kind':kind,'agent_ids':members,'status':'REVIEW_REQUIRED',
                             'reason':'La evidencia compartida puede ser legítima; revisar entregables y responsabilidades diferenciadas.' if kind=='shared_evidence' else 'Diferenciación insuficiente en el campo normalizado.'})
    org['profile_differentiation']={'scope':'current_fictional_agent_team_only','global_uniqueness_claimed':False,
        'credentials_verified':False,'status':'REVIEW_REQUIRED' if gaps else 'NO_EXACT_DUPLICATES_FOUND', 'gaps':gaps,
        'limitations':'Compara misión, evidencias y competencias declaradas; no prueba calidad, novedad mundial ni capacidades reales.'}
    proposals=[]
    for kind,label in [('auditor','Auditoría independiente'),('consultant','Consultoría especializada')]:
        members=[a['id'] for a in agents if kind in a.get('functional_roles',[])]
        proposals.append({'id':'proposal_'+kind,'name':label,'member_ids':members,'status':'PROPOSED_NOT_ACTIVATED',
            'rationale':'Miembros actuales por función declarada; vínculos funcionales sin cambiar mando, permisos o número de agentes.',
            'independence':'No revisar trabajo propio ni de ascendientes/descendientes; conflicto exige auditor externo nombrado por Owner.',
            'assignment_evidence':[r for r in org.get('audit_assignments',[]) if r.get('reviewer_id') in members] if kind=='auditor' else [],
            'gap':'Sin miembros con esta función; Owner debe designar explícitamente.' if not members else None,
            'auto_execute':False,'human_profiling':False})
    org['functional_subteam_proposals']=proposals
    return org
