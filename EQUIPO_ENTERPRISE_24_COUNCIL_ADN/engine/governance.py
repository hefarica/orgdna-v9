"""Offline, auditable command and merit records; no runtime authority or execution.

Scores summarize independently reviewed *recorded* evidence. They do not verify
identities, fetch artifacts, execute tests, grant tools, train models or move agents.
The caller persists returned copies atomically and provides authenticated actors.
"""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone

OWNER = 'OWNER_EXTERNAL'
VERSION = '1.0'
WEIGHTS = {'quality': 30, 'compliance': 20, 'efficiency': 15, 'collaboration': 15, 'evidence': 20}
ACTIONS = {'performance-create', 'performance-review', 'promotion-create', 'promotion-update'}
DIMENSIONS = {
    'quality': 'Criterios de aceptación y regresión satisfechos / criterios acordados; los fallos permanecen en el denominador.',
    'compliance': 'Obligaciones del mandato y límites de autoridad respetados / obligaciones evaluadas.',
    'efficiency': 'Presupuesto acordado / coste real comparable, limitado a 100; nunca tokens, velocidad o volumen sin calidad.',
    'collaboration': 'Handoffs, dependencias y compromisos útiles cumplidos / compromisos acordados.',
    'evidence': 'Afirmaciones comprobadas por revisión independiente / afirmaciones y resultados exigidos, incluidos negativos.',
}
POLICY = {
    'version': VERSION, 'weights': WEIGHTS, 'range': [0, 100], 'dimensions': DIMENSIONS,
    'aggregation': 'Media de entregables únicos dentro de un grupo comparable; no suma de actividad.',
    'missing_data': 'Sin evaluar: score=null y rank=null; ausencia de datos no equivale a cero.',
    'confidence': 'Descriptiva, no probabilidad: baja <3 muestras; media 3–9; alta ≥10 con ≥2 revisores independientes.',
    'comparison': 'Ranking sólo dentro del mismo comparison_group; funciones y dificultad no comparables no se ordenan juntas.',
    'anti_gaming': ['Criterios, presupuesto y grupo fijados antes de revisar; no autoevaluación ni revisión por cadena de mando.',
                    'No premiar volumen, ocultar fallos, omitir criterios, manipular denominadores ni castigar reportes honestos de errores.',
                    'No se infiere calidad desde persona, CV, títulos, modelo, coste o nombre de agente.',
                    'Las revisiones incluyen resultados negativos y conflictos; evidencia registrada no implica ejecución verificada por la app.'],
    'promotion': {'minimum_samples': 5, 'minimum_score': 85, 'quality_floor': 80, 'compliance_floor': 90,
                  'evidence_floor': 90, 'approval': 'Supervisor revisa y Owner aprueba; independencia adicional ante conflicto.',
                  'types': ['recognition', 'promotion', 'succession'], 'automatic': False,
                  'permissions_changed': False, 'runtime_changed': False},
    'learning': 'Aprendizaje operativo: feedback y skills/checklists versionados con fallo demostrado y retest; sin entrenamiento de pesos.',
    'runtime_enforced': False,
}


class GovernanceError(ValueError):
    pass


def _text(value, field, limit=6000, optional=False):
    if not isinstance(value, str) or len(value.encode('utf-16-le')) // 2 > limit or (not value.strip() and not optional) or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise GovernanceError(f'{field}: texto vacío, demasiado largo o no válido.')
    return value.strip()


def _number(value, field, minimum=0):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum or value > 1e12:
        raise GovernanceError(f'{field}: número finito entre {minimum} y 1e12 requerido.')
    return value


def _strings(value, field, minimum=1, maximum=32):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise GovernanceError(f'{field}: se requieren entre {minimum} y {maximum} elementos.')
    result = [_text(x, field, 2000) for x in value]
    if len(set(result)) != len(result):
        raise GovernanceError(f'{field}: elementos duplicados.')
    return result


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _agents(org):
    agents = {a['id']: a for a in org.get('agents', [])}
    if not agents:
        raise GovernanceError('Genera una organización antes de registrar méritos.')
    return agents


def _ancestors(aid, agents):
    chain = []
    while aid in agents:
        aid = agents[aid]['reports_to']
        if aid in chain:
            raise GovernanceError('Jerarquía cíclica.')
        chain.append(aid)
        if aid == OWNER:
            break
        if aid not in agents:
            raise GovernanceError('Supervisor inexistente.')
    return chain


def _identity(aid, agents, owner_name):
    if aid == OWNER:
        return {'id': OWNER, 'name': owner_name, 'display_name': owner_name, 'role': 'OWNER'}
    a = agents[aid]
    return {k: a[k] for k in ('id', 'name', 'display_name', 'role')}


def command_contract(org, agent_id):
    agents = _agents(org)
    a = agents[agent_id]
    owner_name = org.get('config', {}).get('owner_name', 'Owner externo')
    direct = [v['id'] for v in agents.values() if v['reports_to'] == agent_id]
    return {
        'version': VERSION, 'self': _identity(agent_id, agents, owner_name),
        'reports_to': _identity(a['reports_to'], agents, owner_name),
        'chain_of_command': [_identity(x, agents, owner_name) for x in _ancestors(agent_id, agents)],
        'direct_reports': [_identity(x, agents, owner_name) for x in direct],
        'authority': 'Coordinar y revisar entregas de sus subordinados dentro del mandato.' if direct else 'Ejecutar únicamente su tarea autorizada y reportar al superior asignado.',
        'superior_directives': 'Cumplir instrucciones del superior identificado cuando sean compatibles con el objetivo del Owner, evidencia, seguridad y permisos efectivos.',
        'reasoned_dissent': 'Refutar respetuosamente con evidencia, contraejemplo, impacto y alternativa. Registrar el disenso y pedir decisión; nunca inventar hechos ni obedecer a ciegas.',
        'blocking_rule': 'Si una orden excede autoridad, contradice el objetivo, exige falsear evidencia o carece de permiso: BLOCKED, conservar evidencia y escalar por la cadena hasta Owner.',
        'resolved_disagreement': 'Tras una decisión válida del superior, ejecutar dentro del mandato; la discrepancia técnica no permite sabotaje ni desobediencia arbitraria. Un riesgo no resuelto o permiso ausente sigue bloqueando.',
        'functional_links': 'Auditoría y consultoría colaboran; no crean otra cadena de mando ni facultan aprobar trabajo propio.',
        'runtime_enforced': False,
    }


def ensure_governance(org):
    """Return a derived copy; generated identities and existing tree stay untouched."""
    result = copy.deepcopy(org)
    result['governance_policy'] = copy.deepcopy(POLICY)
    for a in result['agents']:
        a['command'] = command_contract(result, a['id'])
        a['performance_contract'] = {
            'score_range': [0, 100], 'weights': copy.deepcopy(WEIGHTS),
            'initial_status': 'sin_evaluar', 'self_grading': False,
            'report_fields': ['task_id', 'requirement_ids', 'candidate_sha', 'acceptance_criteria', 'expected', 'actual', 'negative_results', 'evidence', 'budget', 'actual_cost', 'handoffs', 'reviewer_id', 'limitations'],
            'promotion_is_recommendation': True, 'automatic_permissions': False,
        }
    return result


def validate_governance(org):
    """Validate generated contracts when present; legacy sidecars remain migratable."""
    errors = []
    if 'governance_policy' not in org:
        return errors
    if org['governance_policy'] != POLICY:
        errors.append('Política de méritos alterada o no compatible; regenerar contratos.')
    for a in org.get('agents', []):
        if a.get('command') != command_contract(org, a['id']):
            errors.append('Contrato de mando inconsistente: ' + a['id'])
    return errors


def _event(result, action, row, body, now):
    events = result.setdefault('governance_events', [])
    event = {'sequence': len(events) + 1, 'action': action, 'record_id': row['id'],
             'at': now, 'actor_id': body.get('recorded_by', 'LOCAL_USER'),
             'origin': 'manual_entry', 'runtime_identity_verified': False,
             'previous_hash': events[-1]['hash'] if events else None, 'record_sha256': _digest(row)}
    event['hash'] = _digest(event)
    events.append(event)


def _find(rows, rid):
    found = next((r for r in rows if r.get('id') == rid), None)
    if found is None:
        raise GovernanceError('Registro de méritos inexistente.')
    return found


def _reviewer(reviewer_id, record, agents, body):
    authors = record['author_ids']
    if not isinstance(reviewer_id, str):
        raise GovernanceError('reviewer_id debe ser identificador de texto.')
    if reviewer_id in authors:
        raise GovernanceError('Autoevaluación o coautoría: el revisor no puede calificar su propio trabajo.')
    if body.get('conflict_of_interest') is not False:
        raise GovernanceError('El revisor debe declarar ausencia de conflicto de interés.')
    if body.get('includes_failures') is not True:
        raise GovernanceError('La revisión debe incluir fallos, omisiones y evidencia negativa.')
    if reviewer_id == OWNER:
        # The Owner authorizes, but is not a substitute invented independent auditor.
        raise GovernanceError('Owner debe nombrar un revisor externo independiente, no autoasignarse independencia.')
    if reviewer_id not in agents:
        if not isinstance(reviewer_id, str) or not re.fullmatch(r'EXTERNAL:[A-Za-z0-9._@+-]{1,120}', reviewer_id):
            raise GovernanceError('Revisor desconocido: usa agente independiente o EXTERNAL:identificador.')
        _text(body.get('external_reviewer_name'), 'external_reviewer_name', 160)
        if body.get('appointed_by') != OWNER:
            raise GovernanceError('El revisor externo requiere designación registrada del Owner.')
        _strings(body.get('appointment_evidence'), 'appointment_evidence')
    else:
        for author in authors:
            if reviewer_id in _ancestors(author, agents) or author in _ancestors(reviewer_id, agents):
                raise GovernanceError('Conflicto de cadena de mando: se requiere otro revisor independiente.')
        if 'auditor' not in agents[reviewer_id].get('functional_roles', []):
            raise GovernanceError('El revisor interno debe tener función auditora.')


def normalize_measurements(measurements):
    if not isinstance(measurements, dict) or set(measurements) != set(WEIGHTS):
        raise GovernanceError('measurements requiere quality, compliance, efficiency, collaboration y evidence.')
    dimensions = {}
    normalized = {}
    for name in WEIGHTS:
        values = measurements[name]
        if not isinstance(values, dict):
            raise GovernanceError('Cada medición requiere un objeto con numerador/denominador o presupuesto/coste.')
        if name == 'efficiency':
            if set(values) != {'budget', 'actual'}:
                raise GovernanceError('efficiency requiere exactamente budget y actual.')
            budget = _number(values.get('budget'), 'budget', 0.000001)
            actual = _number(values.get('actual'), 'actual', 0.000001)
            dimensions[name] = min(100.0, 100 * budget / actual)
            normalized[name] = {'budget': budget, 'actual': actual}
        else:
            if set(values) != {'numerator', 'denominator'}:
                raise GovernanceError(name + ' requiere exactamente numerator y denominator.')
            numerator = _number(values.get('numerator'), name + '.numerator')
            denominator = _number(values.get('denominator'), name + '.denominator', 0.000001)
            if numerator > denominator:
                raise GovernanceError('Numerador no puede superar denominador.')
            dimensions[name] = 100 * numerator / denominator
            normalized[name] = {'numerator': numerator, 'denominator': denominator}
    return normalized, {k: round(v, 4) for k, v in dimensions.items()}


def _timestamp(now):
    if now is None:
        # Deterministic tests/callers can inject the timestamp. No external actions.
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    now = _text(now, 'timestamp', 80)
    try:
        parsed = datetime.fromisoformat(now.replace('Z', '+00:00'))
    except ValueError as exc:
        raise GovernanceError('Timestamp ISO8601 requerido.') from exc
    if parsed.tzinfo is None:
        raise GovernanceError('Timestamp requiere zona horaria.')
    return now


def apply_governance_action(organization, records, action, body, now=None):
    """Copy-on-write record transition. Does not apply any promotion or permissions."""
    if action not in ACTIONS or not isinstance(body, dict) or not isinstance(records, dict):
        raise GovernanceError('Acción o datos de méritos no válidos.')
    agents = _agents(organization)
    result = copy.deepcopy(records)
    performances = result.setdefault('performance_records', [])
    promotions = result.setdefault('promotion_records', [])
    now = _timestamp(now)
    integrity = validate_record_integrity(result)
    if not integrity['valid']:
        raise GovernanceError('Historial de méritos inconsistente: ' + '; '.join(integrity['errors']))
    if len(result.get('governance_events', [])) >= 10000:
        raise GovernanceError('Máximo 10000 eventos de méritos por proyecto.')
    if action == 'performance-create':
        if len(performances) >= 2000:
            raise GovernanceError('Máximo 2000 entregables por proyecto.')
        aid = body.get('agent_id')
        if aid not in agents:
            raise GovernanceError('Agente inexistente.')
        task_id = _text(body.get('task_id'), 'task_id', 160)
        if any(r['task_id'] == task_id for r in performances):
            raise GovernanceError('task_id ya registrado: no duplicar entregables para inflar volumen.')
        authors = body.get('author_ids') or [aid]
        authors = _strings(authors, 'author_ids')
        if aid not in authors or any(x not in agents for x in authors):
            raise GovernanceError('Autores deben ser agentes del diseño e incluir al responsable.')
        sha = _text(body.get('candidate_sha'), 'candidate_sha', 64)
        if not re.fullmatch(r'[a-fA-F0-9]{7,64}', sha):
            raise GovernanceError('candidate_sha requiere hash hexadecimal de 7–64 caracteres.')
        criteria = _strings(body.get('acceptance_criteria'), 'acceptance_criteria')
        group = _text(body.get('comparison_group'), 'comparison_group', 160)
        budget = _number(body.get('budget'), 'budget', 0.000001)
        row = {'id': 'perf-' + _digest([task_id, aid])[:20], 'agent_id': aid, 'task_id': task_id,
               'author_ids': authors, 'title': _text(body.get('title'), 'title', 200),
               'comparison_group': group, 'acceptance_criteria': criteria, 'budget': budget,
               'budget_unit': _text(body.get('budget_unit'), 'budget_unit', 80),
               'candidate_sha': sha.lower(), 'evidence': _strings(body.get('evidence'), 'evidence'),
               'status': 'awaiting_independent_review', 'reviews': [], 'created_at': now,
               'supervisor_id_at_submission': agents[aid]['reports_to'], 'origin': 'manual_entry',
               'tests_executed_by_app': False, 'evidence_verified_by_app': False}
        performances.append(row)
    elif action == 'performance-review':
        row = _find(performances, body.get('performance_id'))
        reviewer_id = body.get('reviewer_id')
        _reviewer(reviewer_id, row, agents, body)
        measurements, dimensions = normalize_measurements(body.get('measurements'))
        if measurements['quality']['denominator'] != len(row['acceptance_criteria']):
            raise GovernanceError('quality.denominator debe incluir todos los criterios de aceptación acordados.')
        if measurements['efficiency']['budget'] != row['budget']:
            raise GovernanceError('No se puede cambiar el presupuesto acordado al calificar.')
        evidence = _strings(body.get('evidence'), 'evidence')
        rationale = _text(body.get('rationale'), 'rationale')
        if row['reviews'] and not body.get('supersedes_review_id') == row['reviews'][-1]['id']:
            raise GovernanceError('Una corrección debe identificar la revisión anterior; el historial se conserva.')
        review = {'id': row['id'] + '-review-' + str(len(row['reviews']) + 1),
                  'reviewer_id': reviewer_id, 'measurements': measurements, 'dimensions': dimensions,
                  'score': round(sum(dimensions[k] * WEIGHTS[k] / 100 for k in WEIGHTS), 2),
                  'evidence': evidence, 'rationale': rationale, 'candidate_sha': row['candidate_sha'],
                  'supersedes_review_id': body.get('supersedes_review_id'),
                  'conflict_of_interest': False, 'includes_failures': True, 'created_at': now,
                  'origin': 'manual_entry', 'evidence_verified_by_app': False,
                  'external_reviewer_name': body.get('external_reviewer_name'),
                  'appointed_by': body.get('appointed_by'), 'appointment_evidence': body.get('appointment_evidence', []),
                  'author_ids': list(row['author_ids']),
                  'hierarchy_at_review': {aid: agents[aid]['reports_to'] for aid in agents}}
        row['reviews'].append(review)
        row['status'] = 'reviewed_recorded'
    elif action == 'promotion-create':
        aid = body.get('agent_id')
        if aid not in agents:
            raise GovernanceError('Agente inexistente.')
        kind = body.get('kind')
        if kind not in {'recognition', 'promotion', 'succession'}:
            raise GovernanceError('kind debe ser recognition, promotion o succession.')
        group = _text(body.get('comparison_group'), 'comparison_group', 160)
        score = next((r for r in build_scoreboard(organization, result)['rows'] if r['agent_id'] == aid and r['comparison_group'] == group), None)
        if score is None or score['score'] is None:
            raise GovernanceError('Sin evaluación independiente no se puede recomendar recompensa o ascenso.')
        if kind != 'recognition' and not score['promotion_eligible']:
            raise GovernanceError('No cumple umbrales/muestras para recomendar promoción o sucesión.')
        if any(r['agent_id'] == aid and r['kind'] == kind and r['status'] in {'proposed', 'supervisor_reviewed'} for r in promotions):
            raise GovernanceError('Ya existe una recomendación pendiente del mismo tipo.')
        target = body.get('target_supervisor_id')
        if target is not None and (target not in agents and target != OWNER):
            raise GovernanceError('Supervisor destino inexistente.')
        if target == aid:
            raise GovernanceError('Un agente no puede supervisarse a sí mismo.')
        row = {'id': 'merit-' + _digest([aid, kind, len(promotions), now])[:20], 'agent_id': aid,
               'kind': kind, 'comparison_group': group, 'status': 'proposed',
               'recommendation': _text(body.get('recommendation'), 'recommendation'),
               'target_supervisor_id': target, 'score_snapshot': score,
               'supervisor_id': agents[aid]['reports_to'], 'evidence': _strings(body.get('evidence'), 'evidence'),
               'created_at': now, 'events': [], 'origin': 'manual_entry',
               'runtime_changed': False, 'permissions_changed': False, 'hierarchy_applied': False}
        promotions.append(row)
    else:
        row = _find(promotions, body.get('promotion_id'))
        status = body.get('status')
        transitions = {'proposed': {'supervisor_reviewed', 'rejected'},
                       'supervisor_reviewed': {'owner_approved', 'rejected'},
                       'owner_approved': set(), 'rejected': set()}
        if status not in transitions.get(row['status'], set()):
            raise GovernanceError('Transición inválida: propuesta → supervisor → Owner; sin aprobaciones automáticas.')
        reviewer = body.get('reviewer_id')
        if status == 'supervisor_reviewed':
            if reviewer != agents[row['agent_id']]['reports_to'] or reviewer == row['agent_id']:
                raise GovernanceError('Debe revisar el supervisor actual del agente.')
            if body.get('conflict_of_interest') is not False:
                raise GovernanceError('El supervisor debe declarar ausencia de conflicto; ante conflicto escalar al Owner.')
        elif reviewer != OWNER:
            raise GovernanceError('La decisión final requiere Owner.')
        if status == 'owner_approved':
            current = next((r for r in build_scoreboard(organization, result)['rows'] if r['agent_id'] == row['agent_id'] and r['comparison_group'] == row['comparison_group']), None)
            if current is None or current['score'] is None or (row['kind'] != 'recognition' and not current['promotion_eligible']):
                raise GovernanceError('Evidencia actual ya no sostiene esta recomendación; no aprobar snapshot obsoleto.')
            row['approval_score_snapshot'] = current
        row['events'].append({'status': status, 'reviewer_id': reviewer, 'note': _text(body.get('note'), 'note'),
                              'evidence': _strings(body.get('evidence'), 'evidence'), 'at': now,
                              'origin': 'manual_entry', 'identity_verified_by_app': False})
        row['status'] = status
    _event(result, action, row, body, now)
    return result


def _review_valid(record, review, agents):
    """Never trust saved score fields or accept malformed/self-graded imports."""
    try:
        authors = _strings(record.get('author_ids'), 'author_ids')
        if record.get('agent_id') not in authors or any(aid not in agents for aid in authors):
            return None
        _strings(record.get('acceptance_criteria'), 'acceptance_criteria')
        if review.get('candidate_sha') != record['candidate_sha']:
            return None
        reviewer = review['reviewer_id']
        historical = copy.deepcopy(agents)
        hierarchy = review.get('hierarchy_at_review')
        if not isinstance(hierarchy, dict) or set(hierarchy) != set(agents):
            return None
        for aid, parent in hierarchy.items():
            historical[aid]['reports_to'] = parent
        _reviewer(reviewer, record, historical, review)
        normalized, dimensions = normalize_measurements(review['measurements'])
        if normalized['quality']['denominator'] != len(record['acceptance_criteria']) or normalized['efficiency']['budget'] != record['budget']:
            return None
        _strings(review.get('evidence'), 'evidence')
        _text(review.get('rationale'), 'rationale')
        return dimensions
    except (GovernanceError, ValueError, KeyError, TypeError):
        return None


def validate_record_integrity(records):
    """Detect changed/truncated manual records; hashes are not digital signatures."""
    errors = []
    previous = None
    latest = {}
    events = records.get('governance_events', [])
    if not isinstance(events, list):
        return {'valid': False, 'errors': ['governance_events debe ser lista.'], 'authenticated': False}
    for index, event in enumerate(events, 1):
        if not isinstance(event, dict):
            errors.append('Evento no válido.'); continue
        unsigned = {k: v for k, v in event.items() if k != 'hash'}
        if event.get('sequence') != index or event.get('previous_hash') != previous or event.get('hash') != _digest(unsigned):
            errors.append('Cadena de auditoría alterada en evento ' + str(index))
        previous = event.get('hash')
        latest[event.get('record_id')] = event.get('record_sha256')
    found = set()
    for collection in ('performance_records', 'promotion_records'):
        rows = records.get(collection, [])
        if not isinstance(rows, list):
            errors.append(collection + ' debe ser lista.'); continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('id'), str):
                errors.append('Registro sin ID válido.'); continue
            rid = row['id']
            if rid in found:
                errors.append('ID de registro duplicado: ' + rid)
            found.add(rid)
            if latest.get(rid) != _digest(row):
                errors.append('Registro alterado o sin evento de auditoría: ' + rid)
    if set(latest) != found:
        errors.append('Historial referencia registros ausentes.')
    return {'valid': not errors, 'errors': errors, 'authenticated': False,
            'note': 'Hashes detectan inconsistencias, no autentican al autor ni sustituyen firmas o revisión externa.'}


def build_scoreboard(organization, records):
    agents = _agents(organization)
    buckets = {}
    excluded = []
    integrity = validate_record_integrity(records)
    seen_tasks = set()
    for record in records.get('performance_records', []):
        if not isinstance(record, dict) or record.get('agent_id') not in agents:
            excluded.append({'record_id': record.get('id') if isinstance(record, dict) else None, 'reason': 'invalid_agent_or_record'})
            continue
        key = (record['agent_id'], record.get('comparison_group'))
        bucket = buckets.setdefault(key, {'pending': 0, 'samples': []})
        if record.get('task_id') in seen_tasks:
            excluded.append({'record_id': record.get('id'), 'reason': 'duplicate_task'})
            continue
        seen_tasks.add(record.get('task_id'))
        reviews = record.get('reviews', [])
        review = reviews[-1] if isinstance(reviews, list) and reviews else None
        dims = _review_valid(record, review, agents) if isinstance(review, dict) and integrity['valid'] else None
        if dims is None:
            bucket['pending'] += 1
            if review is not None:
                excluded.append({'record_id': record.get('id'), 'reason': 'invalid_review'})
        else:
            bucket['samples'].append((record, review, dims))
    for aid in agents:
        if not any(key[0] == aid for key in buckets):
            buckets[(aid, None)] = {'pending': 0, 'samples': []}
    rows = []
    for (aid, group), bucket in buckets.items():
        samples = bucket['samples']
        count = len(samples)
        reviewers = sorted({s[1]['reviewer_id'] for s in samples})
        dims = {k: round(sum(s[2][k] for s in samples) / count, 4) if count else None for k in WEIGHTS}
        score = round(sum(dims[k] * WEIGHTS[k] / 100 for k in WEIGHTS), 2) if count else None
        confidence = 'sin_evaluar' if not count else ('high' if count >= 10 and len(reviewers) >= 2 else 'medium' if count >= 3 else 'low')
        eligible = bool(count >= 5 and score >= 85 and dims['quality'] >= 80 and dims['compliance'] >= 90 and dims['evidence'] >= 90 and bucket['pending'] == 0)
        rows.append({'agent_id': aid, 'name': agents[aid]['name'], 'display_name': agents[aid]['display_name'],
                     'comparison_group': group, 'score': score, 'dimensions': dims, 'rank': None,
                     'status': 'evaluated_recorded' if count else 'sin_evaluar', 'sample_count': count,
                     'pending_count': bucket['pending'], 'reviewer_count': len(reviewers), 'reviewer_ids': reviewers,
                     'confidence': confidence, 'confidence_is_probability': False,
                     'promotion_eligible': eligible, 'promotion_requires_approval': True,
                     'source_record_ids': [s[0]['id'] for s in samples],
                     'source_review_ids': [s[1]['id'] for s in samples],
                     'evidence_verified_by_app': False, 'runtime_verified': False})
    for group in {r['comparison_group'] for r in rows if r['score'] is not None}:
        ranked = sorted([r for r in rows if r['comparison_group'] == group and r['score'] is not None], key=lambda r: (-r['score'], r['name']))
        for row in ranked:
            # Equal performance ties; sample volume cannot win a tie.
            row['rank'] = 1 + sum(other['score'] > row['score'] for other in ranked)
    rows.sort(key=lambda r: (r['comparison_group'] or '', r['score'] is None, -(r['score'] or 0), r['name']))
    return {'version': VERSION, 'weights': copy.deepcopy(WEIGHTS), 'rows': rows,
            'excluded_records': excluded, 'integrity': integrity, 'automatic_promotions': False,
            'evidence_status': 'manual_records_not_runtime_verified',
            'note': 'Ranking descriptivo por grupo comparable; revisiones registradas, no pruebas ejecutadas por la app. Más muestras mejoran contexto, nunca suman puntos.'}
