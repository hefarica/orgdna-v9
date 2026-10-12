"""Pruebas de I4: Memory Governance (cuatro planos) y Tenant Isolation.

Offline y solo biblioteca estandar. Cubre los dos contratos congelados de R0
(`docs/plataforma/memory-record.schema.json` y `docs/plataforma/tenant-boundary.schema.json`):
declaraciones obligatorias del fragmento, caducidad efectiva y no revivible, separacion de
planos, memoria personal terminal y nunca exportada, aislamiento entre inquilinos, rutas
contenidas en el directorio del inquilino y reutilizacion del modelo de politica de I3.

Run: python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p "tests_platform_memory_tenants.py" -v
"""
from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from engine import memory_governance as memory_module
from engine import tenants as tenants_module
from engine.memory_governance import (CONTAMINATES, CROSS_PLANE_READS, CROSS_TENANT_READS,
                                      EXECUTION_LIFETIME, EXECUTION_PLANE, EXPORT_DESTINATIONS,
                                      MAX_CONTENT_CHARS, MEMORY_ERROR_CODES, MEMORY_RECORD_VERSION,
                                      PERSONAL_EXCLUSION, PLANES, PLANE_SCOPES, PROJECT_INHERITANCE,
                                      PROJECT_PLANE, PROMOTION_ROUTES, READ_RULE, RECORD_FIELDS,
                                      SCOPE_KINDS, SOURCE_KINDS, UPDATE_POLICIES,
                                      MemoryGovernanceError, MemoryStore, build_record,
                                      memory_hash, validate_record)
from engine.policy_engine import (DECISION_ALLOW, DECISION_REQUIRE, Policy, evaluate,
                                  find_prohibited_fields)
from engine.project_store import FORBIDDEN_FIELDS
from engine.tenants import (BOUNDARY_REQUIRED_FIELDS, DEFAULT_EXPORTED_DOMAINS, DOMAINS,
                            ERROR_CODES, I4_ERROR_CODES, NEVER_EXPORTED_DOMAINS,
                            SENSITIVE_VALUES_STORED, TenantBoundary, TenantError, TenantRegistry,
                            path_belongs_to, require_path_belongs_to, resolve_path, tenant_root)

FIXED_INSTANT = '2026-10-10T00:00:00Z'
LATER_INSTANT = '2026-10-10T02:00:00Z'
FAR_FUTURE = '2030-01-01T00:00:00Z'
ORG_ID = '11111111-2222-3333-4444-555555555555'
OTHER_ORG_ID = '99999999-8888-7777-6666-555555555555'
ACME = 'acme'
BETA = 'beta'
ROLE = 'operador-de-plataforma'
SCHEMA_DIR = Path(__file__).resolve().parent / 'docs' / 'plataforma'
MEMORY_SCHEMA = SCHEMA_DIR / 'memory-record.schema.json'
TENANT_SCHEMA = SCHEMA_DIR / 'tenant-boundary.schema.json'
#: Huellas publicadas en docs/PLATAFORMA_CONTRATOS_V1.md (seccion 8.2).
FROZEN_HASHES = {
    MEMORY_SCHEMA.name: 'f678780d1735c7a1570dc54a188b02e78c04e22d46db24d47e938c0c48923d41',
    TENANT_SCHEMA.name: '7e5fcf46946977d1e4137761409595bdd68e46d8b313798ea5b1a9b47374718a',
}

ALLOWED_MODULE_IMPORTS = {'copy', 'hashlib', 'json', 're', 'datetime', 'policy_engine',
                          'tenants', 'memory_governance', '__future__'}
FORBIDDEN_MODULE_IMPORTS = {'os', 'pathlib', 'socket', 'subprocess', 'urllib', 'http', 'shutil',
                            'tempfile', 'sqlite3', 'sys', 'ctypes', 'multiprocessing', 'threading',
                            'requests', 'ftplib', 'smtplib', 'asyncio', 'pickle', 'glob',
                            'webbrowser'}
FORBIDDEN_CALL_NAMES = {'open', 'eval', 'exec', 'compile', '__import__', 'input', 'print',
                        'breakpoint'}
FORBIDDEN_ATTRIBUTES = {'system', 'popen', 'run', 'call', 'check_output', 'spawn', 'urlopen',
                        'urlretrieve', 'connect', 'connect_ex', 'bind', 'listen', 'send',
                        'sendall', 'recv', 'write_text', 'write_bytes', 'read_text', 'read_bytes',
                        'unlink', 'mkdir', 'makedirs', 'rename', 'remove', 'rmdir', 'open',
                        'socketpair', 'fork'}

#: Pruebas negativas exigidas por el contrato de t5; todas deben existir en esta suite.
REQUIRED_NEGATIVE_CASES = (
    'test_record_without_declarations_is_rejected',
    'test_expired_fragment_is_never_returned',
    'test_expiry_is_latched_and_never_revived_by_an_earlier_clock',
    'test_personal_memory_is_never_exported',
    'test_personal_memory_is_not_mixed_with_secrets_or_another_organization',
    'test_cross_tenant_memory_read_is_denied',
    'test_cross_tenant_budget_read_is_denied',
    'test_cross_tenant_artifact_read_is_denied',
    'test_no_route_can_resolve_a_path_outside_the_tenant',
    'test_execution_plane_does_not_feed_project_without_explicit_promotion',
)


def make_registry(*tenants):
    registry = TenantRegistry()
    for tenant_id, organization_id in tenants:
        registry.register(TenantBoundary.default(tenant_id, organization_id,
                                                created_at=FIXED_INSTANT))
    return registry


def default_registry():
    return make_registry((ACME, ORG_ID), (BETA, OTHER_ORG_ID))


def make_policy(tenant=ACME, **kwargs):
    kwargs.setdefault('created_at', FIXED_INSTANT)
    return Policy.default(tenant, **kwargs)


def origin_fixture(ref='nota-1'):
    return {'source_kind': 'human_record', 'ref': ref, 'captured_at': FIXED_INSTANT,
            'author': ROLE}


def permissions_fixture(tenant=ACME, plane=PROJECT_PLANE, role=ROLE):
    return [{'role_ref': role, 'tenant_id': tenant, 'plane': plane}]


def record_fixture(memory_id, plane, *, tenant=ACME, content='contenido de prueba', ttl=3600,
                   scope=None, role=ROLE, update_policy='append_only', expires_at=None,
                   recorded_at=FIXED_INSTANT, confidence=0.8, permissions=None,
                   content_kind='inline_text', content_ref_sha256=None, declared_bytes=None):
    if scope is None:
        if plane == PROJECT_PLANE:
            scope = {'scope_kind': 'project', 'project_id': ORG_ID}
        elif plane == EXECUTION_PLANE:
            scope = {'scope_kind': 'task', 'task_id': 'tarea-1'}
        elif plane == 'organizational':
            scope = {'scope_kind': 'organization'}
        else:
            scope = {'scope_kind': 'personal'}
    return build_record(
        memory_id, plane, tenant_id=tenant, origin=origin_fixture(), content=content,
        recorded_at=recorded_at, scope=scope, confidence=confidence, ttl_seconds=ttl,
        expires_at=expires_at,
        read_permissions=permissions if permissions is not None
        else permissions_fixture(tenant, plane, role),
        update_policy=update_policy, content_kind=content_kind,
        content_ref_sha256=content_ref_sha256, declared_bytes=declared_bytes)


def project_record(memory_id='mem-1', **kwargs):
    return record_fixture(memory_id, PROJECT_PLANE, **kwargs)


def execution_record(memory_id='mem-exec-1', *, task_id='tarea-1', **kwargs):
    kwargs.setdefault('content', 'memoria efimera')
    kwargs.setdefault('ttl', 600)
    return record_fixture(memory_id, EXECUTION_PLANE,
                          scope={'scope_kind': 'task', 'task_id': task_id}, **kwargs)


def personal_record(memory_id='mem-personal-1', **kwargs):
    kwargs.setdefault('content', 'nota personal')
    kwargs.setdefault('ttl', None)
    return record_fixture(memory_id, 'personal', **kwargs)


def approval_for(policy, action, *, gate=None, role=ROLE, approved_at=FIXED_INSTANT, one_shot=True):
    return {'gate': gate if gate is not None else policy.gates_for(action['action_kind'])[0],
            'approver_role': role, 'approved_at': approved_at,
            'scope_hash': action['scope_hash'], 'one_shot': one_shot}


def approved_action(store, policy, action_kind, plane, memory_id=None, **kwargs):
    action = store.action_for(policy, action_kind, plane, memory_id)
    return action, approval_for(policy, action, **kwargs)


def promoted_id(memory_id, to_plane):
    """Identificador derivado de la promocion, replicado aqui de forma independiente."""
    return 'mem-' + memory_module.sha256_text('%s:%s' % (memory_id, to_plane))[:16]


def mixed_planes_or_tenants(records):
    """Comprobador de contaminacion: True si una coleccion mezcla planos o inquilinos."""
    planes = {record['plane'] for record in records}
    tenants = {record['tenant_id'] for record in records}
    return len(planes) > 1 or len(tenants) > 1


def cross_tenant_read_leaks(reader, requester, owner, domain, key):
    """Falsificador: True solo si la lectura entre inquilinos se consuma."""
    try:
        reader.read(requester, owner, domain, key)
    except (TenantError, MemoryGovernanceError):
        return False
    return True


class PermissiveRegistry:
    """Lector deliberadamente roto: prueba que el falsificador de fuga no es vacuo."""

    def __init__(self, registry):
        self._registry = registry

    def read(self, requester, owner, domain, key):
        return self._registry.read(owner, owner, domain, key)


class ContractConformanceTests(unittest.TestCase):
    """La capa consume los contratos congelados de R0 byte a byte."""

    def test_frozen_schemas_are_consumed_byte_to_byte(self):
        recorded = {}
        for path in (MEMORY_SCHEMA, TENANT_SCHEMA):
            raw = path.read_bytes()
            recorded[path.name] = hashlib.sha256(raw).hexdigest()
        self.assertEqual(recorded, FROZEN_HASHES)
        memory_schema = json.loads(MEMORY_SCHEMA.read_text('utf-8'))
        tenant_schema = json.loads(TENANT_SCHEMA.read_text('utf-8'))
        self.assertEqual(memory_schema['version_field'], 'memory_record_version')
        self.assertEqual(memory_schema['properties']['memory_record_version']['const'],
                         MEMORY_RECORD_VERSION)
        self.assertEqual(tuple(memory_schema['required']), RECORD_FIELDS)
        self.assertEqual(memory_schema['properties']['plane']['enum'], list(PLANES))
        self.assertEqual(memory_schema['properties']['scope']['properties']['scope_kind']['enum'],
                         list(SCOPE_KINDS))
        self.assertEqual(memory_schema['properties']['origin']['properties']['source_kind']['enum'],
                         list(SOURCE_KINDS))
        self.assertEqual(memory_schema['properties']['update_policy']['enum'], list(UPDATE_POLICIES))
        self.assertEqual(memory_schema['properties']['cross_plane_reads']['const'], CROSS_PLANE_READS)
        self.assertEqual(memory_schema['properties']['cross_tenant_reads']['const'], CROSS_TENANT_READS)
        self.assertEqual(memory_schema['properties']['contaminates']['const'], CONTAMINATES)
        self.assertEqual(memory_schema['properties']['read_permissions']['minItems'], 1)
        plane_rules = memory_schema['$defs']['plane_rules']['properties']
        self.assertEqual(plane_rules['planes']['const'], list(PLANES))
        self.assertEqual(plane_rules['execution_lifetime']['const'], EXECUTION_LIFETIME)
        self.assertEqual(plane_rules['project_inheritance']['const'], PROJECT_INHERITANCE)
        self.assertEqual(plane_rules['personal_exclusion']['const'], PERSONAL_EXCLUSION)
        self.assertEqual(plane_rules['read_rule']['const'], READ_RULE)
        self.assertEqual(tenant_schema['version_field'], 'tenant_boundary_version')
        self.assertEqual(tuple(tenant_schema['required']), BOUNDARY_REQUIRED_FIELDS)
        self.assertEqual(tenant_schema['properties']['isolated_domains']['items']['enum'],
                         list(DOMAINS))
        self.assertEqual(tuple(tenant_schema['properties']['domain_rules']['required']), DOMAINS)
        isolation = tenant_schema['$defs']['isolation_rules']['properties']
        self.assertEqual(isolation['error_codes']['const'], list(ERROR_CODES))
        self.assertEqual(isolation['default_exported_domains']['const'],
                         list(DEFAULT_EXPORTED_DOMAINS))
        self.assertEqual(isolation['never_exported_domains']['const'], list(NEVER_EXPORTED_DOMAINS))
        self.assertEqual(isolation['read_rule']['const'],
                         'toda lectura lleva tenant_id explicito; sin coincidencia exacta se '
                         'deniega con error tipado, nunca con una lista vacia silenciosa')
        self.assertIs(isolation['opens_connections']['const'], False)
        self.assertIs(tenant_schema['properties']['sensitive_values_stored']['const'],
                      SENSITIVE_VALUES_STORED)
        self.assertIs(tenant_schema['properties']['cross_tenant_read']['const'], False)
        self.assertEqual(tenant_schema['properties']['shared_tenants']['const'], [])

    def test_declared_vocabularies_match_the_contract(self):
        self.assertEqual(MEMORY_RECORD_VERSION, '1')
        self.assertEqual(PLANE_SCOPES, {'execution': 'task', 'project': 'project',
                                        'organizational': 'organization', 'personal': 'personal'})
        self.assertIn((EXECUTION_PLANE, PROJECT_PLANE), PROMOTION_ROUTES)
        self.assertIn((EXECUTION_PLANE, 'organizational'), PROMOTION_ROUTES)
        self.assertNotIn(('personal', PROJECT_PLANE), PROMOTION_ROUTES)
        self.assertEqual(set(EXPORT_DESTINATIONS), {'package', 'external_handoff'})
        self.assertEqual(MAX_CONTENT_CHARS, 8000)
        for code in ERROR_CODES:
            self.assertIsInstance(code, str)
        for code in MEMORY_ERROR_CODES:
            self.assertIsInstance(code, str)

    def test_prohibited_fields_reuse_the_literal_motor_list(self):
        self.assertEqual(set(tenants_module.PROHIBITED_FIELDS), FORBIDDEN_FIELDS)
        self.assertEqual(len(FORBIDDEN_FIELDS), 13)
        self.assertIn('prohibited_field', I4_ERROR_CODES)
        self.assertIn('prohibited_field', MEMORY_ERROR_CODES)
        self.assertIn('engine/project_store.py:19', tenants_module.PROHIBITED_FIELDS_SOURCE)

    def test_boundary_and_record_are_versioned_and_hashed(self):
        boundary = TenantBoundary.default(ACME, ORG_ID, created_at=FIXED_INSTANT)
        clone = TenantBoundary.from_dict(boundary.as_dict())
        self.assertEqual(boundary.boundary_hash, clone.boundary_hash)
        self.assertRegex(boundary.boundary_hash, r'^[0-9a-f]{64}$')
        self.assertEqual(boundary.isolated_domains, DOMAINS)
        self.assertEqual(boundary.exported_domains(), DEFAULT_EXPORTED_DOMAINS)
        self.assertTrue(set(NEVER_EXPORTED_DOMAINS) <= set(boundary.never_exported_domains()))
        changed = TenantBoundary.default(ACME, ORG_ID, created_at=FIXED_INSTANT,
                                         declared_limits={'network_allowed': False,
                                                          'money_usd_max': 10})
        self.assertNotEqual(changed.boundary_hash, boundary.boundary_hash)
        record = project_record()
        self.assertEqual(memory_hash(record), memory_hash(copy.deepcopy(record)))
        self.assertRegex(memory_hash(record), r'^[0-9a-f]{64}$')
        self.assertNotEqual(memory_hash(record), memory_hash(project_record(content='otro')))

    def test_unsupported_versions_are_rejected(self):
        record = project_record()
        record['memory_record_version'] = '2'
        with self.assertRaises(MemoryGovernanceError) as raised:
            validate_record(record)
        self.assertEqual(raised.exception.code, 'unsupported_version')
        data = TenantBoundary.default(ACME, ORG_ID, created_at=FIXED_INSTANT).as_dict()
        data['tenant_boundary_version'] = '2'
        with self.assertRaises(TenantError) as raised:
            TenantBoundary.from_dict(data)
        self.assertEqual(raised.exception.code, 'boundary_version_unsupported')


class MemoryRecordTests(unittest.TestCase):
    """Declaraciones obligatorias: sin origen, scope, TTL, confianza o hash no hay alta."""

    def setUp(self):
        self.registry = default_registry()
        self.store = MemoryStore(self.registry, ACME)

    def test_record_without_declarations_is_rejected(self):
        for field in ('origin', 'scope', 'ttl_seconds', 'confidence', 'integrity',
                      'read_permissions', 'update_policy', 'tenant_id', 'plane', 'memory_id',
                      'recorded_at', 'content_ref', 'expires_at'):
            with self.subTest(declaracion=field):
                record = project_record()
                del record[field]
                with self.assertRaises(MemoryGovernanceError) as raised:
                    validate_record(record)
                self.assertEqual(raised.exception.code, 'invalid_record')
                with self.assertRaises(MemoryGovernanceError):
                    self.store.accept(record, now=FIXED_INSTANT)

    def test_origin_content_and_scope_declarations_are_validated(self):
        cases = {
            'origin sin ref': lambda r: r['origin'].pop('ref'),
            'origin sin captured_at': lambda r: r['origin'].pop('captured_at'),
            'source_kind desconocido': lambda r: r['origin'].update(source_kind='inventado'),
            'content_ref sin value': lambda r: r['content_ref'].pop('value'),
            'content_kind desconocido': lambda r: r['content_ref'].update(kind='blob'),
            'contenido por encima del limite': lambda r: r['content_ref'].update(
                value='x' * (MAX_CONTENT_CHARS + 1)),
            'scope_kind fuera del contrato': lambda r: r['scope'].update(scope_kind='inventado'),
            'scope incoherente con el plano': lambda r: r['scope'].update(scope_kind='task',
                                                                         task_id='t-1'),
            'sin project_id en plano de proyecto': lambda r: r['scope'].pop('project_id'),
        }
        for label, mutate in cases.items():
            with self.subTest(caso=label):
                record = project_record()
                mutate(record)
                with self.assertRaises(MemoryGovernanceError) as raised:
                    validate_record(record)
                self.assertEqual(raised.exception.code, 'invalid_record')

    def test_execution_plane_requires_a_task_and_project_plane_a_project(self):
        record = project_record('mem-sin-tarea')
        record['plane'] = EXECUTION_PLANE
        with self.assertRaises(MemoryGovernanceError) as raised:
            validate_record(record)
        self.assertEqual(raised.exception.code, 'invalid_record')
        with self.assertRaises(MemoryGovernanceError) as raised:
            record_fixture('mem-sin-proyecto', PROJECT_PLANE,
                           scope={'scope_kind': 'project', 'project_id': None})
        self.assertEqual(raised.exception.code, 'invalid_record')

    def test_confidence_and_ttl_declarations_are_validated(self):
        for label, mutate in {
            'confianza ausente': lambda r: r.pop('confidence'),
            'confianza nula': lambda r: r.update(confidence=None),
            'confianza sobre 1': lambda r: r.update(confidence=1.5),
            'confianza booleana': lambda r: r.update(confidence=True),
            'ttl negativo': lambda r: r.update(ttl_seconds=-1),
            'ttl booleano': lambda r: r.update(ttl_seconds=True),
            'ttl y expires_at contradictorios': lambda r: r.update(
                expires_at='2026-10-10T05:00:00Z'),
        }.items():
            with self.subTest(caso=label):
                record = project_record()
                mutate(record)
                with self.assertRaises(MemoryGovernanceError) as raised:
                    validate_record(record)
                self.assertEqual(raised.exception.code, 'invalid_record')

    def test_ttl_null_is_explicit_and_never_means_zero(self):
        record = project_record('mem-sin-caducidad', ttl=None)
        self.assertIsNone(record['ttl_seconds'])
        self.assertIsNone(record['expires_at'])
        self.store.accept(record, now=FIXED_INSTANT)
        alive = self.store.read('mem-sin-caducidad', plane=PROJECT_PLANE, role_ref=ROLE,
                                now=FAR_FUTURE)
        self.assertEqual(alive['memory_id'], 'mem-sin-caducidad')
        self.assertIsNone(alive['expires_at'])

    def test_integrity_is_recomputed_for_inline_content(self):
        record = project_record()
        tampered = copy.deepcopy(record)
        tampered['integrity']['sha256'] = 'a' * 64
        with self.assertRaises(MemoryGovernanceError) as raised:
            validate_record(tampered)
        self.assertEqual(raised.exception.code, 'invalid_record')
        wrong_bytes = copy.deepcopy(record)
        wrong_bytes['integrity']['bytes'] = record['integrity']['bytes'] + 1
        with self.assertRaises(MemoryGovernanceError) as raised:
            validate_record(wrong_bytes)
        self.assertEqual(raised.exception.code, 'invalid_record')
        file_ref = project_record('mem-file', content='ruta/fichero.txt', content_kind='file_ref',
                                  content_ref_sha256='b' * 64, declared_bytes=42)
        self.assertEqual(file_ref['integrity']['sha256'], 'b' * 64)
        self.assertEqual(file_ref['integrity']['bytes'], 42)
        with self.assertRaises(MemoryGovernanceError) as raised:
            project_record('mem-file2', content='ruta/x.txt', content_kind='file_ref')
        self.assertEqual(raised.exception.code, 'invalid_request')

    def test_credential_shaped_fields_are_rejected(self):
        record = project_record()
        record['apiKey'] = 'secreto'
        with self.assertRaises(MemoryGovernanceError) as raised:
            validate_record(record)
        self.assertEqual(raised.exception.code, 'prohibited_field')
        self.assertIn('engine/project_store.py:19', str(raised.exception))
        with self.assertRaises(TenantError) as raised:
            self.registry.store(ACME, 'projects', 'clave', {'Authorization': 'secreto'})
        self.assertEqual(raised.exception.code, 'prohibited_field')
        self.assertEqual(find_prohibited_fields(project_record()), [])

    def test_read_permissions_cannot_authorize_another_tenant_or_lack_the_plane(self):
        foreign = project_record('mem-ajeno')
        foreign['read_permissions'] = [{'role_ref': ROLE, 'tenant_id': BETA,
                                        'plane': PROJECT_PLANE}]
        with self.assertRaises(MemoryGovernanceError) as raised:
            validate_record(foreign)
        self.assertEqual(raised.exception.code, 'cross_tenant_denied')
        no_plane = project_record('mem-sin-plano')
        no_plane['read_permissions'] = [{'role_ref': ROLE, 'tenant_id': ACME, 'plane': 'personal'}]
        with self.assertRaises(MemoryGovernanceError) as raised:
            validate_record(no_plane)
        self.assertEqual(raised.exception.code, 'read_not_permitted')
        self.store.accept(project_record('mem-otro-rol'), now=FIXED_INSTANT)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.read('mem-otro-rol', plane=PROJECT_PLANE, role_ref='rol-sin-permiso',
                            now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'read_not_permitted')

    def test_update_policy_enum_is_validated(self):
        with self.assertRaises(MemoryGovernanceError) as raised:
            project_record('mem-politica', update_policy='sobreescribir')
        self.assertEqual(raised.exception.code, 'invalid_record')
        for policy in UPDATE_POLICIES:
            with self.subTest(politica=policy):
                self.assertEqual(project_record('mem-%s' % policy.replace('_', '-'),
                                                update_policy=policy)['update_policy'], policy)

    def test_record_is_not_silently_overwritten(self):
        record = project_record()
        self.store.accept(record, now=FIXED_INSTANT)
        self.assertEqual(self.store.accept(copy.deepcopy(record), now=FIXED_INSTANT)['memory_id'],
                         record['memory_id'])
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.accept(project_record(content='otro contenido'), now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'record_exists')

    def test_record_of_another_tenant_is_refused_by_the_store(self):
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.accept(project_record(tenant=BETA), now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'cross_tenant_denied')
        with self.assertRaises(TenantError) as raised:
            MemoryStore(self.registry, 'gamma')
        self.assertEqual(raised.exception.code, 'unknown_tenant')


class ExpiryTests(unittest.TestCase):
    """Caducidad efectiva: un fragmento vencido no se devuelve y no se revive."""

    def setUp(self):
        self.registry = default_registry()
        self.store = MemoryStore(self.registry, ACME)

    def test_expired_fragment_is_never_returned(self):
        self.store.accept(project_record(ttl=60), now=FIXED_INSTANT)
        self.assertEqual(self.store.read('mem-1', plane=PROJECT_PLANE, role_ref=ROLE,
                                         now='2026-10-10T00:00:30Z')['memory_id'], 'mem-1')
        for label, call in {
            'read': lambda: self.store.read('mem-1', plane=PROJECT_PLANE, role_ref=ROLE,
                                            now=LATER_INSTANT),
            'describe': lambda: self.store.describe('mem-1', plane=PROJECT_PLANE, role_ref=ROLE,
                                                    now=LATER_INSTANT),
        }.items():
            with self.subTest(ruta=label):
                with self.assertRaises(MemoryGovernanceError) as raised:
                    call()
                self.assertEqual(raised.exception.code, 'memory_expired')
        self.assertEqual(self.store.list_plane(PROJECT_PLANE, role_ref=ROLE, now=LATER_INSTANT), ())
        self.assertEqual(self.store.list_plane(PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT), ())
        self.assertIn('mem-1', self.store.expired_ids(PROJECT_PLANE))
        self.assertEqual(self.store.expired_reason(PROJECT_PLANE, 'mem-1'), 'ttl')

    def test_expiry_is_latched_and_never_revived_by_an_earlier_clock(self):
        self.store.accept(project_record(ttl=60), now=FIXED_INSTANT)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.read('mem-1', plane=PROJECT_PLANE, role_ref=ROLE, now=LATER_INSTANT)
        self.assertEqual(raised.exception.code, 'memory_expired')
        for clock in (FIXED_INSTANT, '2026-10-10T00:00:30Z', LATER_INSTANT, FAR_FUTURE):
            with self.subTest(reloj=clock):
                with self.assertRaises(MemoryGovernanceError) as raised:
                    self.store.read('mem-1', plane=PROJECT_PLANE, role_ref=ROLE, now=clock)
                self.assertEqual(raised.exception.code, 'memory_expired')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.describe('mem-1', plane=PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'memory_expired')

    def test_sweep_marks_expired_records(self):
        self.store.accept(project_record('mem-vivo', ttl=None), now=FIXED_INSTANT)
        self.store.accept(project_record('mem-vencido', content='otro', ttl=60), now=FIXED_INSTANT)
        marked = self.store.sweep(now=LATER_INSTANT)
        self.assertEqual(marked, ('mem-vencido',))
        self.assertEqual(self.store.expired_ids(), ('mem-vencido',))
        self.assertEqual([view['memory_id'] for view in
                          self.store.list_plane(PROJECT_PLANE, role_ref=ROLE, now=LATER_INSTANT)],
                         ['mem-vivo'])
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.read('mem-vencido', plane=PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'memory_expired')

    def test_ttl_zero_expires_immediately_but_is_still_marked(self):
        record = project_record('mem-cero', ttl=0)
        self.assertEqual(record['expires_at'], memory_module.add_seconds(FIXED_INSTANT, 0))
        self.assertEqual(memory_module.parse_instant(record['expires_at']),
                         memory_module.parse_instant(record['recorded_at']))
        self.store.accept(record, now=FIXED_INSTANT)
        self.assertIn('mem-cero', self.store.expired_ids(PROJECT_PLANE))
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.read('mem-cero', plane=PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'memory_expired')

    def test_expired_record_is_never_promoted_nor_exported(self):
        policy = make_policy()
        self.store.accept(execution_record('mem-exec-vencido', ttl=60), now=FIXED_INSTANT)
        self.store.accept(project_record('mem-proy-vencido', ttl=60), now=FIXED_INSTANT)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.promote(policy, 'mem-exec-vencido', from_plane=EXECUTION_PLANE,
                               to_plane=PROJECT_PLANE,
                               scope={'scope_kind': 'project', 'project_id': ORG_ID},
                               role_ref=ROLE, read_permissions=permissions_fixture(),
                               now=LATER_INSTANT)
        self.assertEqual(raised.exception.code, 'memory_expired')
        action, approval = approved_action(self.store, policy, 'send_message_out', PROJECT_PLANE,
                                           'project-export')
        exported, decision = self.store.export_records(policy, plane=PROJECT_PLANE, role_ref=ROLE,
                                                       approval=approval, now=LATER_INSTANT)
        self.assertEqual(decision['decision'], DECISION_ALLOW)
        self.assertEqual(exported, ())
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.read('mem-proy-vencido', plane=PROJECT_PLANE, role_ref=ROLE,
                            now=LATER_INSTANT)
        self.assertEqual(raised.exception.code, 'memory_expired')


class PlaneSeparationTests(unittest.TestCase):
    """Cuatro planos separados, plano de ejecucion efimero y plano personal terminal."""

    def setUp(self):
        self.registry = default_registry()
        self.store = MemoryStore(self.registry, ACME)
        self.policy = make_policy()

    def test_four_planes_share_no_read_index(self):
        self.store.accept(project_record('mem-1'), now=FIXED_INSTANT)
        self.store.accept(execution_record('mem-exec-1'), now=FIXED_INSTANT)
        self.store.accept(personal_record('mem-personal-1'), now=FIXED_INSTANT)
        for plane in ('execution', 'personal', 'organizational'):
            with self.subTest(plano=plane):
                with self.assertRaises(MemoryGovernanceError) as raised:
                    self.store.read('mem-1', plane=plane, role_ref=ROLE, now=FIXED_INSTANT)
                self.assertEqual(raised.exception.code, 'cross_plane_denied')
        self.assertEqual([view['memory_id'] for view in
                          self.store.list_plane(PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)],
                         ['mem-1'])
        self.assertEqual([view['memory_id'] for view in
                          self.store.list_plane(EXECUTION_PLANE, role_ref=ROLE, now=FIXED_INSTANT)],
                         ['mem-exec-1'])
        self.assertFalse(mixed_planes_or_tenants(
            self.store.list_plane(EXECUTION_PLANE, role_ref=ROLE, now=FIXED_INSTANT)))
        self.assertFalse(mixed_planes_or_tenants(
            self.store.list_plane('personal', role_ref=ROLE, now=FIXED_INSTANT)))
        self.assertEqual(set(PLANES), {'execution', 'project', 'organizational', 'personal'})

    def test_execution_plane_expires_when_its_task_closes(self):
        self.store.accept(execution_record('mem-exec-1', task_id='tarea-1'), now=FIXED_INSTANT)
        self.store.accept(execution_record('mem-exec-2', task_id='tarea-2'), now=FIXED_INSTANT)
        self.assertEqual(self.store.read('mem-exec-1', plane=EXECUTION_PLANE, role_ref=ROLE,
                                         now=FIXED_INSTANT)['memory_id'], 'mem-exec-1')
        closed = self.store.close_task('tarea-1', now=FIXED_INSTANT)
        self.assertEqual(closed, ('mem-exec-1',))
        self.assertEqual(self.store.closed_tasks, frozenset({'tarea-1'}))
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.read('mem-exec-1', plane=EXECUTION_PLANE, role_ref=ROLE, now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'task_closed')
        self.assertEqual(self.store.expired_reason(EXECUTION_PLANE, 'mem-exec-1'), 'task_closed')
        self.assertEqual(self.store.list_plane(EXECUTION_PLANE, role_ref=ROLE, now=FIXED_INSTANT)[0]
                         ['memory_id'], 'mem-exec-2')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.read('mem-exec-1', plane=EXECUTION_PLANE, role_ref=ROLE, now=FAR_FUTURE)
        self.assertEqual(raised.exception.code, 'task_closed')

    def test_closed_task_accepts_no_new_execution_memory(self):
        self.store.close_task('tarea-1', now=FIXED_INSTANT)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.accept(execution_record('mem-exec-nuevo', task_id='tarea-1'),
                              now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'task_closed')

    def test_execution_plane_does_not_feed_project_without_explicit_promotion(self):
        self.store.accept(execution_record('mem-exec-1'), now=FIXED_INSTANT)
        self.assertEqual(self.store.list_plane(PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT), ())
        target_id = promoted_id('mem-exec-1', PROJECT_PLANE)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.read(target_id, plane=PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'record_not_found')
        action = self.store.action_for(self.policy, 'store_memory', PROJECT_PLANE, target_id)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.promote(self.policy, 'mem-exec-1', from_plane=EXECUTION_PLANE,
                               to_plane=PROJECT_PLANE,
                               scope={'scope_kind': 'project', 'project_id': ORG_ID},
                               role_ref=ROLE, read_permissions=permissions_fixture(),
                               now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'human_approval_required')
        self.assertEqual(raised.exception.decision['gate'], 'write')
        self.assertEqual(self.store.list_plane(PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT), ())
        promoted, decision = self.store.promote(
            self.policy, 'mem-exec-1', from_plane=EXECUTION_PLANE, to_plane=PROJECT_PLANE,
            scope={'scope_kind': 'project', 'project_id': ORG_ID}, role_ref=ROLE,
            read_permissions=permissions_fixture(), approval=approval_for(self.policy, action),
            now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_ALLOW)
        self.assertEqual(promoted['memory_id'], target_id)
        self.assertEqual(promoted['plane'], PROJECT_PLANE)
        self.assertEqual(promoted['origin'], execution_record()['origin'])
        self.assertEqual(promoted['content_ref']['value'], 'memoria efimera')
        self.assertEqual(promoted['ttl_seconds'], 600)
        self.assertEqual(self.store.read(target_id, plane=PROJECT_PLANE, role_ref=ROLE,
                                         now=FIXED_INSTANT)['memory_id'], target_id)
        self.assertEqual(self.store.read('mem-exec-1', plane=EXECUTION_PLANE, role_ref=ROLE,
                                         now=FIXED_INSTANT)['memory_id'], 'mem-exec-1')

    def test_promotion_requires_declared_target_scope_and_permissions(self):
        self.store.accept(execution_record('mem-exec-1'), now=FIXED_INSTANT)
        target_id = promoted_id('mem-exec-1', PROJECT_PLANE)
        action, approval = approved_action(self.store, self.policy, 'store_memory', PROJECT_PLANE,
                                           target_id)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.promote(self.policy, 'mem-exec-1', from_plane=EXECUTION_PLANE,
                               to_plane=PROJECT_PLANE,
                               scope={'scope_kind': 'task', 'task_id': 'tarea-1'}, role_ref=ROLE,
                               read_permissions=permissions_fixture(), approval=approval,
                               now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'invalid_record')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.promote(self.policy, 'mem-exec-1', from_plane=EXECUTION_PLANE,
                               to_plane=PROJECT_PLANE,
                               scope={'scope_kind': 'project', 'project_id': ORG_ID},
                               role_ref=ROLE, read_permissions=[], approval=approval,
                               now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'invalid_record')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.promote(self.policy, 'mem-exec-1', from_plane=EXECUTION_PLANE,
                               to_plane=PROJECT_PLANE,
                               scope={'scope_kind': 'project', 'project_id': ORG_ID},
                               role_ref=ROLE, approval=approval, now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'read_not_permitted')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.promote(self.policy, 'mem-exec-1', from_plane=EXECUTION_PLANE,
                               to_plane=PROJECT_PLANE,
                               scope={'scope_kind': 'project', 'project_id': ORG_ID},
                               role_ref='rol-sin-permiso',
                               read_permissions=permissions_fixture(), approval=approval,
                               now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'read_not_permitted')

    def test_personal_plane_is_terminal(self):
        self.store.accept(personal_record('mem-personal-1'), now=FIXED_INSTANT)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.promote(self.policy, 'mem-personal-1', from_plane='personal',
                               to_plane=PROJECT_PLANE,
                               scope={'scope_kind': 'project', 'project_id': ORG_ID},
                               role_ref=ROLE, read_permissions=permissions_fixture(),
                               now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'personal_plane_not_exportable')
        self.store.accept(project_record('mem-1'), now=FIXED_INSTANT)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.promote(self.policy, 'mem-1', from_plane=PROJECT_PLANE, to_plane='personal',
                               scope={'scope_kind': 'personal'}, role_ref=ROLE,
                               read_permissions=permissions_fixture(ACME, 'personal'),
                               now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'promotion_not_allowed')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.promote(self.policy, 'mem-1', from_plane=PROJECT_PLANE,
                               to_plane=EXECUTION_PLANE,
                               scope={'scope_kind': 'task', 'task_id': 'tarea-1'}, role_ref=ROLE,
                               read_permissions=permissions_fixture(ACME, EXECUTION_PLANE),
                               now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'promotion_not_allowed')
        self.assertEqual([view['memory_id'] for view in
                          self.store.list_plane('personal', role_ref=ROLE, now=FIXED_INSTANT)],
                         ['mem-personal-1'])

    def test_personal_memory_is_never_exported(self):
        self.store.accept(personal_record('mem-personal-1'), now=FIXED_INSTANT)
        for destination in EXPORT_DESTINATIONS:
            with self.subTest(destino=destination):
                with self.assertRaises(MemoryGovernanceError) as raised:
                    self.store.export_records(self.policy, plane='personal', role_ref=ROLE,
                                              destination=destination, now=FIXED_INSTANT)
                self.assertEqual(raised.exception.code, 'personal_plane_not_exportable')
        plan = self.registry.export_plan(ACME)
        self.assertIn('memories', plan['never_exported_in_package'])
        self.assertIn('sensitive_material', plan['never_exported_in_package'])
        self.assertNotIn('memories', plan['exported_in_package'])
        self.assertNotIn('sensitive_material', plan['exported_in_package'])
        self.assertEqual(tuple(plan['exported_in_package']), DEFAULT_EXPORTED_DOMAINS)
        personal_path = self.store.record_path('mem-personal-1', 'personal')
        self.assertTrue(path_belongs_to(ACME, personal_path))
        self.assertFalse(path_belongs_to(BETA, personal_path))
        self.assertNotIn('personal', self.store.record_path('mem-1', PROJECT_PLANE))

    def test_memories_domain_never_travels_in_the_package(self):
        self.store.accept(project_record('mem-1'), now=FIXED_INSTANT)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.export_records(self.policy, plane=PROJECT_PLANE, role_ref=ROLE,
                                      destination='package', now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'domain_not_exportable')
        self.assertIn('memories', NEVER_EXPORTED_DOMAINS)

    def test_personal_memory_is_not_mixed_with_secrets_or_another_organization(self):
        self.store.accept(personal_record('mem-personal-1'), now=FIXED_INSTANT)
        beta_store = MemoryStore(self.registry, BETA)
        with self.assertRaises(MemoryGovernanceError) as raised:
            beta_store.accept(personal_record('mem-personal-1', tenant=ACME), now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'cross_tenant_denied')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.accept(personal_record('mem-personal-2',
                                              permissions=[{'role_ref': ROLE, 'tenant_id': BETA,
                                                            'plane': 'personal'}]),
                              now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'cross_tenant_denied')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.accept(personal_record('mem-personal-3',
                                              permissions=[{'role_ref': ROLE, 'tenant_id': ACME,
                                                            'plane': PROJECT_PLANE}]),
                              now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'read_not_permitted')
        with self.assertRaises(TenantError) as raised:
            self.registry.store(ACME, 'sensitive_material', 'clave-del-inquilino', {'ref': 'x'})
        self.assertEqual(raised.exception.code, 'sensitive_domain_not_materializable')
        personal = self.store.read('mem-personal-1', plane='personal', role_ref=ROLE,
                                   now=FIXED_INSTANT)
        self.store.accept(project_record('mem-1'), now=FIXED_INSTANT)
        project = self.store.read('mem-1', plane=PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)
        self.assertFalse(mixed_planes_or_tenants([personal]))
        self.assertFalse(mixed_planes_or_tenants([project]))
        self.assertFalse(mixed_planes_or_tenants(
            self.store.list_plane(PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)))
        self.assertFalse(mixed_planes_or_tenants(
            self.store.list_plane('personal', role_ref=ROLE, now=FIXED_INSTANT)))
        self.assertTrue(mixed_planes_or_tenants([personal, project]))

    def test_project_does_not_inherit_organizational_or_personal_memory(self):
        self.store.accept(personal_record('mem-personal-1'), now=FIXED_INSTANT)
        self.store.accept(record_fixture('mem-org-1', 'organizational',
                                         content='conocimiento organizacional', ttl=None),
                          now=FIXED_INSTANT)
        for memory_id in ('mem-personal-1', 'mem-org-1'):
            with self.subTest(fragmento=memory_id):
                with self.assertRaises(MemoryGovernanceError) as raised:
                    self.store.read(memory_id, plane=PROJECT_PLANE, role_ref=ROLE,
                                    now=FIXED_INSTANT)
                self.assertEqual(raised.exception.code, 'cross_plane_denied')
        self.assertEqual(self.store.list_plane(PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT), ())
        self.assertEqual(self.store.list_plane('organizational', role_ref=ROLE,
                                               now=FIXED_INSTANT)[0]['memory_id'], 'mem-org-1')


class TenantIsolationTests(unittest.TestCase):
    """Aislamiento entre inquilinos, con falsificadores explicitos."""

    def setUp(self):
        self.registry = default_registry()
        for tenant, budget in ((ACME, 0), (BETA, 250)):
            self.registry.store(tenant, 'memories', 'memoria-1', {'memory_id': 'memoria-1',
                                                                  'tenant_id': tenant})
            self.registry.store(tenant, 'artifacts', 'artefacto-1', {'artifact_id': 'artefacto-1',
                                                                     'tenant_id': tenant})
            self.registry.store(tenant, 'budgets', 'presupuesto-1', {'network_allowed': False,
                                                                     'money_usd_max': budget})
        self.denied_codes = set(ERROR_CODES) | set(I4_ERROR_CODES)

    def test_cross_tenant_memory_read_is_denied(self):
        self.assertFalse(cross_tenant_read_leaks(self.registry, BETA, ACME, 'memories',
                                                 'memoria-1'))
        with self.assertRaises(TenantError) as raised:
            self.registry.read(BETA, ACME, 'memories', 'memoria-1')
        self.assertEqual(raised.exception.code, 'cross_tenant_denied')
        self.assertNotEqual(raised.exception.code, 'record_not_found')
        self.assertIn(raised.exception.code, self.denied_codes)
        self.assertTrue(cross_tenant_read_leaks(PermissiveRegistry(self.registry), BETA, ACME,
                                                'memories', 'memoria-1'))
        acme_store = MemoryStore(self.registry, ACME)
        acme_store.accept(project_record('mem-acme'), now=FIXED_INSTANT)
        beta_store = MemoryStore(self.registry, BETA)
        with self.assertRaises(MemoryGovernanceError) as raised:
            beta_store.read('mem-acme', plane=PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'record_not_found')
        self.assertEqual(beta_store.list_plane(PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT), ())

    def test_cross_tenant_budget_read_is_denied(self):
        registry = TenantRegistry()
        registry.register(TenantBoundary.default(ACME, ORG_ID, created_at=FIXED_INSTANT,
                                                 declared_limits={'network_allowed': False,
                                                                  'money_usd_max': 0}))
        registry.register(TenantBoundary.default(BETA, OTHER_ORG_ID, created_at=FIXED_INSTANT,
                                                 declared_limits={'network_allowed': False,
                                                                  'money_usd_max': 250}))
        with self.assertRaises(TenantError) as raised:
            registry.read_budget(BETA, ACME)
        self.assertEqual(raised.exception.code, 'cross_tenant_denied')
        self.assertFalse(cross_tenant_read_leaks(registry, BETA, ACME, 'budgets',
                                                 'presupuesto-1'))
        self.assertEqual(registry.read_budget(ACME, ACME)['money_usd_max'], 0)
        self.assertEqual(registry.read_budget(BETA, BETA)['money_usd_max'], 250)
        with self.assertRaises(TenantError) as raised:
            self.registry.read_budget(BETA, ACME)
        self.assertEqual(raised.exception.code, 'cross_tenant_denied')
        self.assertFalse(cross_tenant_read_leaks(self.registry, BETA, ACME, 'budgets',
                                                 'presupuesto-1'))
        self.assertEqual(self.registry.read_budget(ACME, ACME), {'network_allowed': False})

    def test_cross_tenant_artifact_read_is_denied(self):
        with self.assertRaises(TenantError) as raised:
            self.registry.read_artifact(BETA, ACME, 'artefacto-1')
        self.assertEqual(raised.exception.code, 'cross_tenant_denied')
        self.assertFalse(cross_tenant_read_leaks(self.registry, BETA, ACME, 'artifacts',
                                                 'artefacto-1'))
        self.assertEqual(self.registry.read_artifact(ACME, ACME, 'artefacto-1')['tenant_id'], ACME)
        self.assertEqual(self.registry.read_artifact(BETA, BETA, 'artefacto-1')['tenant_id'], BETA)

    def test_cross_tenant_read_is_never_an_empty_list(self):
        for domain in DOMAINS:
            with self.subTest(dominio=domain):
                with self.assertRaises(TenantError) as raised:
                    self.registry.read(BETA, ACME, domain)
                self.assertEqual(raised.exception.code, 'cross_tenant_denied')

    def test_unknown_tenant_and_undeclared_domain_are_typed_errors(self):
        with self.assertRaises(TenantError) as raised:
            self.registry.boundary('gamma')
        self.assertEqual(raised.exception.code, 'unknown_tenant')
        with self.assertRaises(TenantError) as raised:
            self.registry.read(ACME, 'gamma', 'memories', 'memoria-1')
        self.assertEqual(raised.exception.code, 'unknown_tenant')
        with self.assertRaises(TenantError) as raised:
            self.registry.read(ACME, ACME, 'otro-dominio', 'x')
        self.assertEqual(raised.exception.code, 'domain_not_declared')
        with self.assertRaises(TenantError) as raised:
            self.registry.read(ACME, ACME, 'memories', 'no-existe')
        self.assertEqual(raised.exception.code, 'record_not_found')
        with self.assertRaises(TenantError) as raised:
            self.registry.store(ACME, 'memories', '', {'x': 1})
        self.assertEqual(raised.exception.code, 'invalid_entry')

    def test_identifiers_are_disjoint_across_tenants(self):
        for domain in ('memories', 'artifacts', 'budgets'):
            with self.subTest(dominio=domain):
                by_tenant = self.registry.ids_across_tenants(domain)
                self.assertEqual(set(by_tenant), {ACME, BETA})
                qualified = self.registry.qualified_ids_across_tenants(domain)
                intersection = set(qualified[ACME]) & set(qualified[BETA])
                self.assertEqual(intersection, set())
                self.assertEqual(qualified[ACME], tuple(sorted('%s:%s:%s' % (ACME, domain, key)
                                                               for key in by_tenant[ACME])))
                self.assertNotEqual(qualified[ACME], qualified[BETA])
        self.assertEqual(self.registry.read(ACME, ACME, 'memories', 'memoria-1')['tenant_id'], ACME)
        self.assertEqual(self.registry.read(BETA, BETA, 'memories', 'memoria-1')['tenant_id'], BETA)
        self.assertEqual(self.registry.read_artifact(ACME, ACME, 'artefacto-1')['tenant_id'], ACME)
        self.assertEqual(self.registry.read_artifact(BETA, BETA, 'artefacto-1')['tenant_id'], BETA)

    def test_sensitive_material_domain_never_materializes_values(self):
        for tenant in (ACME, BETA):
            with self.subTest(inquilino=tenant):
                with self.assertRaises(TenantError) as raised:
                    self.registry.store(tenant, 'sensitive_material', 'material-1',
                                        {'ref': 'externo'})
                self.assertEqual(raised.exception.code, 'sensitive_domain_not_materializable')
                self.assertEqual(self.registry.entry_count(tenant, 'sensitive_material'), 0)
        boundary = self.registry.boundary(ACME)
        self.assertIs(boundary.rule('sensitive_material')['store_kind'], 'none')
        self.assertEqual(boundary.rule('memories')['store_kind'], 'in_memory')
        self.assertIs(boundary.as_dict()['sensitive_values_stored'], False)

    def test_boundary_rules_cannot_open_shared_or_cross_tenant_reads(self):
        for overrides, code in (
                ({'cross_tenant_read': True}, 'cross_tenant_denied'),
                ({'shared_tenants': [BETA]}, 'cross_tenant_denied'),
                ({'sensitive_values_stored': True}, 'sensitive_domain_not_materializable'),
                ({'domain_rules': {'memories': {'exported_in_package': True}}}, 'invalid_entry'),
                ({'domain_rules': {'memories': {'cross_tenant_read': True}}}, 'cross_tenant_denied'),
                ({'domain_rules': {'sensitive_material': {'store_kind': 'in_memory'}}},
                 'sensitive_domain_not_materializable'),
                ({'isolated_domains': ['organizations']}, 'domain_not_declared')):
            with self.subTest(cambio=sorted(overrides)):
                with self.assertRaises(TenantError) as raised:
                    TenantBoundary.default(ACME, ORG_ID, created_at=FIXED_INSTANT,
                                           overrides=overrides)
                self.assertEqual(raised.exception.code, code)


class PathIsolationTests(unittest.TestCase):
    """Ninguna ruta sale del directorio del inquilino y ningun modulo escribe."""

    def setUp(self):
        self.registry = default_registry()
        self.store = MemoryStore(self.registry, ACME)

    def test_no_route_can_resolve_a_path_outside_the_tenant(self):
        escapes = ('../beta/memoria.json', 'memories/../../beta/x', '/etc/passwd',
                   'C:/Windows/system32', '//servidor/recurso', 'https://ejemplo.invalid/x',
                   'memorias/..', '', '   ', 'a\\..\\b', 'carpeta/\x00/x',
                   'carpeta/fichero.txt:flujo')
        for relative in escapes:
            with self.subTest(ruta=relative):
                with self.assertRaises(TenantError) as raised:
                    resolve_path(ACME, relative)
                self.assertEqual(raised.exception.code, 'outside_tenant_root')
        for memory_id in ('../x', 'C:/Windows/system32', '//servidor/recurso', '..', '',
                          'Mayusculas', 'con espacio'):
            with self.subTest(identificador=memory_id):
                with self.assertRaises(MemoryGovernanceError) as raised:
                    self.store.record_path(memory_id, PROJECT_PLANE)
                self.assertIn(raised.exception.code, ('invalid_record', 'outside_tenant_root'))

    def test_every_resolved_path_stays_inside_the_tenant_root(self):
        root = tenant_root(ACME)
        self.assertEqual(root, 'tenants/acme')
        for relative in ('memoria.json', 'memories/project/mem-1', './memories//project//mem-1'):
            with self.subTest(ruta=relative):
                resolved = resolve_path(ACME, relative)
                self.assertTrue(resolved.startswith(root + '/'))
                self.assertTrue(path_belongs_to(ACME, resolved))
                self.assertFalse(path_belongs_to(BETA, resolved))
                self.assertEqual(require_path_belongs_to(ACME, resolved), resolved)
        self.assertEqual(self.store.record_path('mem-1', PROJECT_PLANE),
                         'tenants/acme/memories/project/mem-1')
        self.assertEqual(self.store.assert_path_in_tenant('tenants/acme/x'), 'tenants/acme/x')
        with self.assertRaises(TenantError) as raised:
            self.store.assert_path_in_tenant('tenants/beta/memories/project/mem-1')
        self.assertEqual(raised.exception.code, 'outside_tenant_root')
        with self.assertRaises(TenantError) as raised:
            require_path_belongs_to(ACME, 'tenants/acme-otro/x')
        self.assertEqual(raised.exception.code, 'outside_tenant_root')
        self.assertTrue(path_belongs_to(ACME, root))
        self.assertFalse(path_belongs_to(ACME, 'tenants/acme-otro'))
        self.assertFalse(path_belongs_to(ACME, None))

    def test_modules_never_write_files_or_open_network(self):
        for module in (tenants_module, memory_module):
            with self.subTest(modulo=module.__name__):
                source = Path(module.__file__).read_text('utf-8')
                tree = ast.parse(source)
                imported = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name.split('.')[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imported.add((node.module or '').split('.')[0] or 'relativo')
                self.assertEqual(imported - ALLOWED_MODULE_IMPORTS, set())
                self.assertEqual(imported & FORBIDDEN_MODULE_IMPORTS, set())
                offenders = []
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALL_NAMES:
                        offenders.append(node.func.id)
                    elif isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRIBUTES:
                        offenders.append(node.func.attr)
                self.assertEqual(offenders, [])
                for forbidden in ('data/projects', 'registry.sqlite3'):
                    self.assertNotIn(forbidden, source)

    def test_whole_api_runs_with_file_and_network_tripwires(self):
        policy = make_policy()
        with patch.object(builtins, 'open', side_effect=AssertionError('escritura de fichero')), \
                patch.object(socket, 'socket', side_effect=AssertionError('apertura de red')):
            boundary = self.registry.boundary(ACME)
            self.assertEqual(boundary.tenant_id, ACME)
            self.registry.store(ACME, 'projects', 'proyecto-1', {'id': 'proyecto-1'})
            self.registry.read(ACME, ACME, 'projects', 'proyecto-1')
            self.registry.export_plan(ACME)
            self.store.accept(project_record('mem-1'), now=FIXED_INSTANT)
            self.store.accept(execution_record('mem-exec-1'), now=FIXED_INSTANT)
            self.store.accept(personal_record('mem-personal-1'), now=FIXED_INSTANT)
            self.store.read('mem-1', plane=PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)
            self.store.describe('mem-1', plane=PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)
            self.store.list_plane(PROJECT_PLANE, role_ref=ROLE, now=FIXED_INSTANT)
            self.store.sweep(now=LATER_INSTANT)
            self.store.close_task('tarea-1', now=FIXED_INSTANT)
            self.store.record_path('mem-1', PROJECT_PLANE)
            _, approval = approved_action(self.store, policy, 'store_memory', PROJECT_PLANE,
                                          'mem-2')
            self.store.store_with_policy(policy, project_record('mem-2'), approval=approval,
                                         now=FIXED_INSTANT)
            self.store.read_with_policy(policy, 'mem-2', plane=PROJECT_PLANE, role_ref=ROLE,
                                        now=FIXED_INSTANT)
            _, promotion_approval = approved_action(self.store, policy, 'store_memory',
                                                    'organizational',
                                                    promoted_id('mem-2', 'organizational'))
            promoted, _ = self.store.promote(policy, 'mem-2', from_plane=PROJECT_PLANE,
                                             to_plane='organizational',
                                             scope={'scope_kind': 'organization'}, role_ref=ROLE,
                                             read_permissions=permissions_fixture(
                                                 ACME, 'organizational'),
                                             approval=promotion_approval, now=FIXED_INSTANT)
            self.assertEqual(promoted['memory_id'],
                             promoted_id('mem-2', 'organizational'))
            _, export_approval = approved_action(self.store, policy, 'send_message_out',
                                                 PROJECT_PLANE, 'project-export')
            exported, _ = self.store.export_records(policy, plane=PROJECT_PLANE, role_ref=ROLE,
                                                    approval=export_approval, now=FIXED_INSTANT)
            self.assertEqual([record['memory_id'] for record in exported], ['mem-2'])
            self.assertIn('mem-1', self.store.expired_ids(PROJECT_PLANE))


class PolicyReuseTests(unittest.TestCase):
    """La capa de memoria reutiliza el modelo de politica y las puertas humanas de I3."""

    def setUp(self):
        self.registry = default_registry()
        self.store = MemoryStore(self.registry, ACME)
        self.policy = make_policy()
        self.store.accept(project_record('mem-1'), now=FIXED_INSTANT)

    def test_memory_read_is_authorized_through_the_policy(self):
        record, decision = self.store.read_with_policy(self.policy, 'mem-1', plane=PROJECT_PLANE,
                                                       role_ref=ROLE, now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_ALLOW)
        self.assertEqual(record['memory_id'], 'mem-1')
        action = self.store.action_for(self.policy, 'read_repo', PROJECT_PLANE, 'mem-1')
        self.assertEqual(evaluate(self.policy, action, now=FIXED_INSTANT)['decision'],
                         DECISION_ALLOW)
        gated = make_policy(overrides={'action_gates': {'read_repo': ['secrets']}})
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.read_with_policy(gated, 'mem-1', plane=PROJECT_PLANE, role_ref=ROLE,
                                        now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'human_approval_required')
        self.assertEqual(raised.exception.decision['gate'], 'secrets')
        _, approval = approved_action(self.store, gated, 'read_repo', PROJECT_PLANE, 'mem-1')
        record, decision = self.store.read_with_policy(gated, 'mem-1', plane=PROJECT_PLANE,
                                                       role_ref=ROLE, approval=approval,
                                                       now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_ALLOW)
        self.assertEqual(record['content_ref']['value'], 'contenido de prueba')

    def test_read_gate_does_not_override_isolation(self):
        gated = make_policy(overrides={'action_gates': {'read_repo': ['secrets']}})
        _, approval = approved_action(self.store, gated, 'read_repo', PROJECT_PLANE, 'mem-1')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.read_with_policy(gated, 'mem-1', plane='personal', role_ref=ROLE,
                                        approval=approval, now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'cross_plane_denied')

    def test_policy_change_invalidates_a_previous_approval(self):
        _, approval = approved_action(self.store, self.policy, 'store_memory', PROJECT_PLANE,
                                      'mem-nueva')
        _, decision = self.store.store_with_policy(self.policy, project_record('mem-nueva'),
                                                   approval=approval, now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_ALLOW)
        changed = self.policy.with_overrides({'limits': {'spend_usd_max': 5.0}})
        self.assertNotEqual(changed.policy_hash, self.policy.policy_hash)
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.store_with_policy(changed, project_record('mem-otra'), approval=approval,
                                         now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'human_approval_required')
        self.assertEqual(raised.exception.decision['decision'], DECISION_REQUIRE)
        _, fresh = approved_action(self.store, changed, 'store_memory', PROJECT_PLANE, 'mem-otra')
        _, decision = self.store.store_with_policy(changed, project_record('mem-otra'),
                                                   approval=fresh, now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_ALLOW)

    def test_write_and_promotion_go_through_the_human_write_gate(self):
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.store_with_policy(self.policy, project_record('mem-2'), now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'human_approval_required')
        self.assertEqual(raised.exception.decision['gate'], 'write')
        action, approval = approved_action(self.store, self.policy, 'store_memory', PROJECT_PLANE,
                                           'mem-2')
        stored, decision = self.store.store_with_policy(self.policy, project_record('mem-2'),
                                                       approval=approval, now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_ALLOW)
        self.assertEqual(stored['memory_id'], 'mem-2')
        self.assertEqual(decision['action']['scope_hash'], action['scope_hash'])
        self.assertIs(decision['side_effects_performed'], False)

    def test_external_handoff_goes_through_the_connectors_gate(self):
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.export_records(self.policy, plane=PROJECT_PLANE, role_ref=ROLE,
                                      now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'human_approval_required')
        self.assertEqual(raised.exception.decision['gate'], 'connectors')
        self.assertIs(raised.exception.decision['limits']['network_allowed'], False)
        _, approval = approved_action(self.store, self.policy, 'send_message_out', PROJECT_PLANE,
                                      'project-export')
        exported, decision = self.store.export_records(self.policy, plane=PROJECT_PLANE,
                                                       role_ref=ROLE, approval=approval,
                                                       now=FIXED_INSTANT)
        self.assertEqual(decision['decision'], DECISION_ALLOW)
        self.assertEqual([record['memory_id'] for record in exported], ['mem-1'])
        self.assertFalse(mixed_planes_or_tenants(exported))
        for record in exported:
            self.assertEqual(record['tenant_id'], ACME)
            self.assertEqual(record['plane'], PROJECT_PLANE)

    def test_action_for_is_the_exact_scope_a_human_signs(self):
        action = self.store.action_for(self.policy, 'store_memory', PROJECT_PLANE, 'mem-9')
        self.assertEqual(action['target'], 'memory://acme/project/mem-9')
        self.assertEqual(action['scope_hash'], self.policy.scope_hash(action))
        self.assertEqual(approval_for(self.policy, action)['scope_hash'], action['scope_hash'])
        other = self.store.action_for(self.policy, 'store_memory', PROJECT_PLANE, 'mem-10')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.store_with_policy(self.policy, project_record('mem-9'),
                                         approval=dict(approval_for(self.policy, action),
                                                       scope_hash=other['scope_hash']),
                                         now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'human_approval_required')
        with self.assertRaises(MemoryGovernanceError) as raised:
            self.store.store_with_policy(self.policy, project_record('mem-9'),
                                         approval=dict(approval_for(self.policy, action),
                                                       one_shot=False),
                                         now=FIXED_INSTANT)
        self.assertEqual(raised.exception.code, 'human_approval_required')


class SuiteSizeTests(unittest.TestCase):
    """El contrato exige al menos 16 casos, incluidos todos los negativos anteriores."""

    def test_at_least_sixteen_cases_and_all_required_negatives(self):
        names = set()
        for value in globals().values():
            if isinstance(value, type) and issubclass(value, unittest.TestCase):
                names.update(name for name in dir(value) if name.startswith('test_'))
        self.assertGreaterEqual(len(names), 16)
        for required in REQUIRED_NEGATIVE_CASES:
            with self.subTest(caso=required):
                self.assertIn(required, names)


if __name__ == '__main__':
    unittest.main()
