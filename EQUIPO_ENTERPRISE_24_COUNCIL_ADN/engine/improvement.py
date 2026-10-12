"""Evidence-bound design revisions, never automatic training or skill promotion.

Only finalized, hash-verified evaluation records may enter feedback. Raw test
output, commands, environment and arbitrary reviewer text are never transmitted.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re


class ImprovementError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _token(value, maximum=160):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,' + str(maximum) + '}', value):
        raise ImprovementError('Identificador de evidencia inválido.')
    return value


def build_feedback_package(runs, organization, source_hash=None):
    """Accept only backend-verified records; independently recheck immutable hashes."""
    if not isinstance(runs, list) or not 1 <= len(runs) <= 16:
        raise ImprovementError('Selecciona entre 1 y 16 evaluaciones reales terminadas.')
    agents = {a['id']: a for a in organization.get('agents', [])}
    rows, targets, seen = [], [], set()
    for run in runs:
        if not isinstance(run, dict) or run.get('status') not in {'pass', 'fail', 'timeout', 'cancelled'}:
            raise ImprovementError('Falta una evaluación terminada; no se inventa feedback de ejecución.')
        stored = run.get('artifact_result_sha256')
        core = {k: v for k, v in run.items() if k not in {'artifact_result_sha256', 'evidence_ref', 'artifact_saved'}}
        if not isinstance(stored, str) or digest(core) != stored:
            raise ImprovementError('El resultado de evaluación no coincide con su hash inmutable.')
        if run.get('organization_sha256') != digest(organization):
            raise ImprovementError('La evaluación pertenece a otra versión de organización; vuelve a evaluar el diseño actual.')
        if run.get('organization_id') != organization.get('organization_id'):
            raise ImprovementError('La evaluación pertenece a otra organización.')
        aid = run.get('agent_id')
        if aid not in agents or run.get('agent_sha256') != digest(agents[aid]):
            raise ImprovementError('La evaluación pertenece a otra versión del agente.')
        if source_hash is not None and run.get('source_sha256') != source_hash:
            raise ImprovementError('La fuente evaluada cambió; vuelve a evaluar antes de mejorar.')
        if not re.fullmatch('[a-f0-9]{64}', str(run.get('source_sha256', ''))):
            raise ImprovementError('Falta el hash de la fuente ejecutada.')
        if run['id'] in seen:
            raise ImprovementError('No repitas una evaluación en el mismo paquete.')
        seen.add(run['id'])
        if not run.get('machine_execution_observed') or not run.get('source_unchanged'):
            raise ImprovementError('La ejecución o la integridad de la fuente no están demostradas; resuelve el bloqueo y vuelve a evaluar.')
        metrics = {key: run[key] for key in ('exit_code', 'tests_run', 'tests_skipped', 'stdout_bytes', 'stderr_bytes')
                   if type(run.get(key)) is int and -1000000 <= run[key] <= 1000000000}
        reason = run.get('reason')
        allowed_reasons = {'expected_conditions_met', 'test_failed_or_no_tests_or_source_changed',
                           'output_limit_exceeded', 'timeout_limit_exceeded', 'user_cancelled',
                           'runner_error_or_source_changed', 'runner_error', 'tests_failed', 'no_tests'}
        reason = reason if reason in allowed_reasons else 'unclassified_execution_result'
        row = {'run_id': _token(run['id']), 'result_sha256': stored, 'source_sha256': run['source_sha256'],
               'agent_id': aid, 'agent_sha256': run['agent_sha256'], 'task_id': _token(run['task_id']),
               'status': run['status'], 'reason_code': reason, 'metrics': metrics,
               'skill_ids': [_token(s) for s in run.get('skill_ids', [])[:32]],
               'skill_deficiency_established': False,
               'test_result_trust': 'untrusted_process_report',
               'profile_id': run.get('tested_scope', {}).get('profile_id') if run.get('tested_scope', {}).get('profile_id') in {'python_unittest_v1', 'python_pytest_v1', 'node_test_v1'} else 'unknown_curated_profile',
               'assertions_independently_verified': False}
        rows.append(row)
        if run['status'] != 'pass':
            kind = 'test_failure_observed' if metrics.get('tests_run', 0) > 0 and run['status'] == 'fail' else 'evaluation_blocker'
            targets.append({'agent_id': aid, 'run_id': row['run_id'], 'kind': kind,
                'priority': 'high' if kind == 'test_failure_observed' else 'medium',
                'hypothesis': 'Investigar un defecto de implementación, prueba o entorno; una carencia de habilidad es sólo una hipótesis.',
                'required_change': 'Proponer método de diagnóstico y entregable reproducible vinculado al resultado; cambiar responsabilidades, entregables o método de competencia del perfil afectado.',
                'retest_criteria': ['Misma tarea y alcance documentados; nueva versión y hashes registrados.',
                                    'Unidades de prueba ejecutadas > 0, código de salida 0 y éxito del runner elegido; contrastar aserciones con revisión independiente.',
                                    'Fuente estable, sin exceder límites; revisión independiente antes de verificar competencia.']})
    if not targets:
        raise ImprovementError('Las evaluaciones seleccionadas no muestran fallos o bloqueos; no se fabrica una brecha de habilidad.')
    package = {'schema_version': 'improvement-feedback-1', 'organization_id': organization.get('organization_id'),
               'organization_sha256': digest(organization), 'evaluations': rows, 'targets': targets,
               'redaction_policy': 'allowlist_only_no_stdout_stderr_commands_environment_or_free_text',
               'status': 'proposed', 'skills_verified': False, 'weights_trained': False,
               'source_scope': 'Local file manifest and organization source anchor are distinct; repository identity equivalence is not independently established.'}
    package['feedback_sha256'] = digest(package)
    return package


def revision_view(context, count):
    if not isinstance(context, dict) or set(context) != {'organization', 'feedback'}:
        raise ImprovementError('La revisión requiere organización actual y feedback de evaluaciones verificadas.')
    org, feedback = context['organization'], context['feedback']
    if feedback.get('organization_sha256') != digest(org) or feedback.get('feedback_sha256') != digest({k:v for k,v in feedback.items() if k != 'feedback_sha256'}):
        raise ImprovementError('La revisión no coincide con el hash del feedback y la organización actual.')
    if len(org.get('agents', [])) != count:
        raise ImprovementError('Mejorar conserva N; cambia la membresía en una operación explícita separada.')
    fields = ('id', 'slot', 'name', 'display_name', 'role', 'title', 'department', 'mission', 'personality',
              'responsibilities', 'deliverables', 'skills', 'proposed_skills', 'cv', 'evidence_paths')
    result = {'organization_id': org['organization_id'], 'organization_sha256': digest(org),
              'agents': [{k: copy.deepcopy(a[k]) for k in fields if k in a} for a in org['agents']],
              'feedback': copy.deepcopy(feedback)}
    if len(json.dumps(result, ensure_ascii=False).encode()) > 400000:
        raise ImprovementError('El contexto de mejora supera 400 KB; reduce evaluaciones o perfiles antes de revisar.')
    return result


def preserve_revision_identity(specs, organization):
    if len(specs) != len(organization.get('agents', [])):
        raise ImprovementError('La mejora debe conservar todos los perfiles y sus identidades.')
    result = copy.deepcopy(specs)
    for spec, prior in zip(result, organization['agents']):
        spec['name'], spec['display_name'] = prior['name'], prior['display_name']
        # Tool roles are not an optimization surface for an LLM revision.
        if prior.get('tool_preset_role'):
            spec['tool_preset_role'] = prior['tool_preset_role']
    return result


def validate_target_changes(specs, organization, feedback):
    by_id = {a['id']: (a, spec) for a, spec in zip(organization['agents'], specs)}
    fields = ('responsibilities', 'deliverables', 'skills')
    for aid in {t['agent_id'] for t in feedback['targets']}:
        previous, spec = by_id[aid]
        previous_responsibilities = [r for r in previous.get('responsibilities', [])
                                     if not (r.startswith('Supervisar ') and 'sin sobrepasar span=' in r)]
        changed = (previous_responsibilities != spec.get('responsibilities') or
                   previous.get('deliverables') != spec.get('deliverables'))
        # Compare method descriptions, never generated skill IDs/status wrappers.
        old = [(s.get('name'), s.get('description')) for s in previous.get('skills', []) if s.get('source') != 'hierarchy_assignment']
        new = [(s.get('name'), s.get('description')) for s in spec.get('skills', [])]
        changed = changed or old != new
        if not changed:
            raise ImprovementError('El modelo no propuso una corrección funcional para el agente afectado; no basta cambiar advertencias.')


def finalize_proposal(previous, candidate, feedback):
    """Preserve protected state before validation/export; return a reviewable diff."""
    if {a['id'] for a in previous['agents']} != {a['id'] for a in candidate['agents']}:
        raise ImprovementError('La mejora cambió las identidades de la organización.')
    prior_by_id = {a['id']: a for a in previous['agents']}
    diff = []
    for agent in candidate['agents']:
        prior = prior_by_id[agent['id']]
        for field in ('name', 'display_name', 'tool_policy', 'permissions', 'restrictions', 'tool_preset_role',
                      'tools', 'tool_allowlist', 'tool_denylist', 'tool_mapping_status'):
            if field in prior:
                agent[field] = copy.deepcopy(prior[field])
            else:
                agent.pop(field, None)
        for field in ('mission', 'responsibilities', 'deliverables', 'skills', 'proposed_skills', 'cv'):
            if prior.get(field) != agent.get(field):
                diff.append({'agent_id': agent['id'], 'field': field, 'before': copy.deepcopy(prior.get(field)), 'after': copy.deepcopy(agent.get(field))})
    for key in ('winner', 'winner_score', 'scores', 'leaderboard', 'evaluation_results'):
        if key in previous:
            candidate[key] = copy.deepcopy(previous[key])
        else:
            candidate.pop(key, None)
    proposal = {'status': 'proposed', 'feedback_sha256': feedback['feedback_sha256'],
                'base_organization_sha256': digest(previous), 'diff': diff,
                'retest_plan': copy.deepcopy(feedback['targets']), 'skills_verified': False,
                'human_review_required': True, 'weights_trained': False}
    candidate['improvement_proposal'] = copy.deepcopy(proposal)
    return proposal


def validate_source_baseline(summary, organization):
    """Compare the design's source anchor, never confuse a local manifest with Git."""
    provenance = organization.get('provenance', {})
    if summary.get('source_kind') == 'website':
        current, previous = summary.get('source_hash'), provenance.get('source_hash')
    else:
        current, previous = summary.get('repository', {}).get('sha'), provenance.get('repository_sha')
    if not current or not previous or current != previous:
        raise ImprovementError('La evidencia de fuente no corresponde al diseño evaluado; vuelve a generar y evaluar antes de mejorarlo.')
