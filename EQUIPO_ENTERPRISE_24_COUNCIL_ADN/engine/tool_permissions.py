"""Exact-name, least-privilege DSH proposals from the user's supplied catalog.

Reading or editing this policy never configures a runtime or installs a tool.
A saved allowlist restricts the whole visible tool set, not only this catalog.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
from functools import lru_cache

MAX_ITEMS = 256
MAX_NAME_UTF16 = 200
STATUS = 'USER_PROVIDED_NOT_RUNTIME_VERIFIED'
ROLE_NAMES = {
    'CEO': 'Planner', 'CTO': 'Implementer', 'ASSURANCE': 'Reviewer', 'ARCHITECTURE': 'Architect',
    'BACKEND': 'Backend', 'FRONTEND': 'Frontend', 'DATA': 'Data', 'INTEGRATION': 'Integration',
    'QUANT': 'Quant', 'CONTRACTS': 'Contracts', 'SECURITY': 'Security', 'QA': 'QA',
    'PERFORMANCE': 'Performance', 'SRE': 'SRE', 'RELEASE': 'Release', 'LEDGER': 'Ledger',
    'GRAPH': 'GraphRouting', 'MARKET': 'MarketMicrostructure', 'AI': 'AIEngineering',
    'SPEC': 'Specification', 'OWNEROPS': 'PersonalOps', 'E2E': 'BrowserE2E',
    'PARITY': 'ModeParity', 'EVIDENCE': 'EvidenceAuditor',
    'UX':'UX', 'PRIVACY':'Privacy', 'BUILD':'Build', 'CHAOS':'Chaos', 'DOCS':'Documentation', 'SEARCH':'Search',
}


@lru_cache(maxsize=1)
def _catalog():
    data = json.loads(Path(__file__).with_name('tool_catalog.json').read_text(encoding='utf-8'))
    names = [t['name'] for t in data['tools']]
    if len(names) != len(set(names)) or not names:
        raise ValueError('Catálogo de herramientas duplicado o vacío.')
    return data


def get_tool_catalog():
    return copy.deepcopy(_catalog())


def load_tool_catalog():
    return get_tool_catalog()


def _names(values, field, require_known=True):
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_ITEMS:
        raise ValueError(f'{field}: lista no vacía de hasta {MAX_ITEMS} nombres exactos; no se trunca.')
    result = []
    known = {t['name'] for t in _catalog()['tools']} if require_known else set()
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip() or len(value.encode('utf-16-le')) // 2 > MAX_NAME_UTF16 or any(ord(c) < 32 or ord(c) == 127 for c in value) or ',' in value or '*' in value:
            raise ValueError(f'{field}: nombre exacto inválido; sin CSV, comodines ni controles.')
        if require_known and value not in known:
            raise ValueError(f'{field}: herramienta ausente del catálogo aportado: {value}. No inventar disponibilidad.')
        result.append(value)
    if len(result) != len(set(result)):
        raise ValueError(f'{field}: nombres duplicados.')
    return result


def validate_tool_scope(scope, require_known=False):
    errors = []
    try:
        if not isinstance(scope, dict) or not scope or set(scope) - {'allow', 'deny'}:
            raise ValueError('toolScope admite allow y/o deny; no admite objeto vacío ni campos inventados.')
        allow = _names(scope['allow'], 'toolScope.allow', require_known) if 'allow' in scope else []
        deny = _names(scope['deny'], 'toolScope.deny', require_known) if 'deny' in scope else []
        if set(allow) & set(deny):
            raise ValueError('toolScope.allow y deny no pueden solaparse.')
    except (ValueError, TypeError, KeyError) as exc:
        errors.append(str(exc))
    return {'valid': not errors, 'errors': errors, 'runtime_verified': False}


# Exact catalog-backed design proposals, never a claim of executable capability.
EXTRA_PRESETS = {
    'UX': ['ops_plan','ops_status','visual_mermaid','ui.compile','ui.island','univer_screenshot','evidence_add'],
    'PRIVACY': ['ops_plan','ops_status','priv.probe','priv.mix','zk.verify','enc.ckks','evidence_add','research_report'],
    'BUILD': ['ops_plan','ops_status','ci_status','ci_predict','dep_graph','dep_impact','incremental_check_rust','incremental_check_ts','evidence_add'],
    'CHAOS': ['ops_plan','ops_status','test.prop','test.fuzz','micro.trace','net.pkt','simulacro.run','evidence_add'],
    'DOCS': ['ops_plan','ops_status','research_report','visual_mermaid','visual_ascii','univer_inspect','evidence_add'],
    'SEARCH': ['ops_plan','ops_status','run_search','run_search_review','run_requirement_research','why_find','why_recall','research_report','evidence_add'],
}


def _preset(agent):
    selected = agent.get('tool_preset_role')
    if selected is not None and selected != 'manual_review' and selected not in ROLE_NAMES:
        # Additional known roles still have no catalog-backed specialized preset.
        selected = 'manual_review'
    effective_role = selected or agent['role']
    if effective_role in EXTRA_PRESETS:
        known = {t['name']:t for t in _catalog()['tools']}
        allow = EXTRA_PRESETS[effective_role]
        if not set(allow) <= set(known): raise ValueError('Preset contiene herramientas ausentes del catálogo.')
        return {'role':ROLE_NAMES[effective_role], 'allow_candidates':list(allow),
            'conditional_candidates':[n for n in allow if known[n].get('risk_level') != 'low'],
            'excluded_candidates':[], 'capability_gaps':['Capacidad objetivo pendiente de evaluación y preflight runtime.'],
            'notes':['Preset explícito por función declarada, basado en nombres del catálogo aportado.']}
    name = ROLE_NAMES.get(selected or agent['role'], agent['name'] if selected is None else 'manual_review')
    preset = next((p for p in _catalog()['role_presets'] if p['role'] == name), None) if selected != 'manual_review' else None
    if preset:
        return preset
    # Additional roles have no supplied specialized preset; propose only planning.
    names = {t['name'] for t in _catalog()['tools']}
    return {'role': name, 'allow_candidates': [n for n in ('ops_plan', 'ops_status', 'visual_ascii') if n in names],
            'conditional_candidates': [], 'excluded_candidates': [], 'notes': ['Sin preset especializado; revisar capacidades necesarias antes de usar este perfil.']}


def _policy(agent, allow, deny, source, inherit=False):
    scope = {}
    if allow:
        scope['allow'] = list(allow)
    if deny:
        scope['deny'] = list(deny)
    report = validate_tool_scope(scope, require_known=source != 'manual_design_edit')
    if not report['valid']:
        raise ValueError('; '.join(report['errors']))
    preset = _preset(agent)
    return {
        'recommendation_version': 2, 'runtime_availability': 'UNKNOWN',
        'mode': 'inherit_with_deny' if inherit else 'allowlist', 'allow': list(allow), 'deny': list(deny),
        'source': source, 'status': STATUS, 'runtime_verified': False, 'runtime_applied': False,
        'schema': 'DSH agent.toolScope exact-name lists; maximum 256 names per list',
        'catalog_source': 'user_supplied_catalog', 'allow_count': len(allow), 'deny_count': len(deny),
        'manual_unverified_names': [n for n in allow + deny if n not in {t['name'] for t in _catalog()['tools']}],
        'manual_name_status': 'MANUAL_UNVERIFIED' if source == 'manual_design_edit' else None,
        'conditional_candidates': list(preset['conditional_candidates']),
        'capability_gaps': list(preset.get('capability_gaps', [])),
        'preconditions': {t['name']: list(t.get('preconditions', [])) for t in _catalog()['tools'] if t['name'] in allow and t.get('preconditions')},
        'excluded_candidates': list(preset['excluded_candidates']),
        'limitations': ['Una allowlist filtra TODAS las herramientas visibles, incluidas herramientas fuera del catálogo.',
                       'El catálogo no acredita shell general, edición de archivos ni navegador E2E; no ejecutar implementación hasta confirmar herramientas necesarias y autorizadas.',
                       'Si falta un nombre allowed en la sesión padre, DSH puede bloquear INVALID_DISPATCH; no quitar nombres silenciosamente.',
                       'La misma definición se comparte en Council e implementación. toolScope no impone modo read-only ni restricciones de argumentos.',
                       'Los nombres permitidos no autorizan acciones, destinos, datos, secretos, finanzas ni cambios de permisos.',
                       'Sin allow se heredan herramientas presentes y futuras del padre, sujetas a deny; no equivale a deny-all.'],
    }


def ensure_tool_policies(org):
    result = copy.deepcopy(org)
    for agent in result['agents']:
        if 'tool_policy' not in agent:
            preset = _preset(agent)
            agent['tool_policy'] = _policy(agent, preset.get('export_allow', preset['allow_candidates']), [], 'role_catalog_proposal')
        agent['tool_policy']['recommendation_version'] = 2
        agent['tool_policy']['runtime_availability'] = 'UNKNOWN'
    result['tool_permissions'] = {
        'catalog_status': STATUS, 'catalog_count': len(_catalog()['tools']),
        'source_sha256': _catalog()['provenance']['sha256'], 'max_allow': MAX_ITEMS, 'max_deny': MAX_ITEMS,
        'applied_to_runtime': False, 'export_field': 'agents[].toolScope',
        'note': 'Propuestas por perfil precargadas desde catálogo del usuario; exportar no instala ni aplica permisos. Confirmar tools visibles y capacidad de edición antes de importar.',
    }
    return result


def export_tool_scope(agent):
    policy = agent.get('tool_policy')
    if policy is None:
        return None  # Legacy sidecars keep their original inheritance behavior.
    scope = {}
    for key in ('allow', 'deny'):
        if policy.get(key):
            scope[key] = copy.deepcopy(policy[key])
    report = validate_tool_scope(scope, require_known=policy.get('source') != 'manual_design_edit')
    if not report['valid']:
        raise ValueError('; '.join(report['errors']))
    return scope


def validate_tool_policies(org):
    errors = []
    for agent in org.get('agents', []):
        if 'tool_policy' not in agent:
            continue
        p = agent['tool_policy']
        try:
            if not isinstance(p, dict) or p.get('runtime_verified') is not False or p.get('runtime_applied') is not False or p.get('status') != STATUS:
                raise ValueError('La política local no puede afirmar permisos runtime aplicados/verificados.')
            scope = export_tool_scope(agent)
            if p.get('mode') not in {'allowlist', 'inherit_with_deny'}:
                raise ValueError('Modo de permisos desconocido.')
            if p['mode'] == 'allowlist' and 'allow' not in scope:
                raise ValueError('Modo allowlist requiere allow no vacío.')
            if p['mode'] == 'inherit_with_deny' and ('allow' in scope or 'deny' not in scope):
                raise ValueError('Herencia requiere sólo deny no vacío.')
            if p.get('allow_count') != len(p.get('allow', [])) or p.get('deny_count') != len(p.get('deny', [])):
                raise ValueError('Conteo de herramientas inconsistente.')
        except (ValueError, TypeError, KeyError) as exc:
            errors.append('Política de herramientas ' + str(agent.get('name')) + ': ' + str(exc))
    return errors


def apply_tool_policy(org, body):
    """Atomic design edit with a version gate, not a runtime permission change."""
    if __package__:
        from .core import _rebuild_derived, validate_organization
    else:
        from core import _rebuild_derived, validate_organization
    if not isinstance(body, dict) or type(body.get('expected_state_version')) is not int or body['expected_state_version'] != org.get('state_version'):
        raise ValueError('Versión obsoleta: recarga antes de editar herramientas.')
    report = validate_organization(org)
    structural = [e for e in report['errors'] if not e.startswith('Modelo no disponible:')]
    if structural:
        raise ValueError('Organización inválida: ' + '; '.join(structural))
    result = ensure_tool_policies(org)
    agent = next((a for a in result['agents'] if a['id'] == body.get('agent_id')), None)
    if agent is None:
        raise ValueError('Agente inexistente.')
    if body.get('reset_to_role_proposal') is True:
        preset = _preset(agent)
        agent['tool_policy'] = _policy(agent, preset.get('export_allow', preset['allow_candidates']), [], 'role_catalog_proposal')
    else:
        raw_allow = body.get('allow', [])
        raw_deny = body.get('deny', [])
        if not isinstance(raw_allow, list) or not isinstance(raw_deny, list):
            raise ValueError('allow y deny deben ser listas de nombres exactos.')
        allow = _names(raw_allow, 'allow', require_known=False) if raw_allow else []
        deny = _names(raw_deny, 'deny', require_known=False) if raw_deny else []
        inherit = not allow
        if inherit and body.get('inherit_parent_tools') is not True:
            raise ValueError('Allow vacío no significa cero herramientas: confirma explícitamente inherit_parent_tools para heredar con deny.')
        agent['tool_policy'] = _policy(agent, allow, deny, 'manual_design_edit', inherit)
    result['state_version'] = org['state_version'] + 1
    result.setdefault('edit_history', []).append({'state_version': result['state_version'], 'action': 'tool_policy',
        'agent_id': agent['id'], 'allow_count': agent['tool_policy']['allow_count'], 'deny_count': agent['tool_policy']['deny_count'],
        'runtime_applied': False})
    return _rebuild_derived(result)


def tool_recommendation(agent):
    """Bind proposals to current identities; untouched legacy artifacts retain their format."""
    if agent.get('tool_policy',{}).get('recommendation_version') != 2:
        legacy = copy.deepcopy(next((p for p in _catalog()['role_presets'] if p['role'] == ROLE_NAMES.get(agent['role'],agent['name'])), None))
        if legacy is not None: legacy['agent_id'] = agent['id']
        return legacy
    preset = copy.deepcopy(_preset(agent))
    policy = agent.get('tool_policy',{})
    denied = set(policy.get('deny',[]))
    preset['agent_id'] = agent['id']
    preset['agent_role'] = agent['role']
    preset['advisory'] = True
    preset['status'] = 'PROPOSED_NOT_APPLIED'
    preset['runtime_availability'] = 'UNKNOWN'
    preset['runtime_verified'] = False
    preset['effective_allow'] = list(policy.get('allow',[]))
    preset['effective_deny'] = list(policy.get('deny',[]))
    preset['manual_override_preserved'] = policy.get('source') == 'manual_design_edit'
    preset['proposal_does_not_override_policy'] = True
    tools = {t['name']:t for t in _catalog()['tools']}
    preset['tool_rationales'] = []
    for name in dict.fromkeys(preset.get('allow_candidates',[]) + policy.get('allow',[]) + policy.get('deny',[])):
        t=tools.get(name,{})
        preset['tool_rationales'].append({'name':name,'runtime_availability':'UNKNOWN',
            'status':'DENIED_BY_POLICY' if name in denied else ('MANUAL_UNVERIFIED' if name not in tools else 'ROLE_PROPOSAL_NOT_VALIDATED'),
            'reason':'Encaje propuesto con '+str(agent.get('title',agent['role']))+'; catálogo: '+t.get('description','Nombre exacto manual externo sin catálogo.'),
            'basis':'declared_role_and_catalog_description' if name in tools else 'manual_design_edit',
            'project_evidence_paths':list(agent.get('evidence_paths',[])),
            'project_need_verified':False, 'preconditions':list(t.get('preconditions',[]))})
    preset['breadth_review'] = {'required':len(policy.get('allow',[]))>64,
        'reason':'Preset amplio por rol; no demuestra necesidad por repositorio. Revisar cada herramienta y reducir alcance antes de aplicar.'}
    return preset
