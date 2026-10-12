"""Pruebas offline del Agent Registry y del Evidence Graph (flujo I2). Inertes, sin red.

Verifica los dos modulos del flujo I2 contra el contrato congelado de R0
(`docs/plataforma/evidence-node.schema.json`) y contra las reglas duras del encargo:

  * un claim sin evidencia se marca `unsupported` y nunca `verified`;
  * dos claims con evidencia contradictoria se marcan `contradicted`, sin mayoria ni
    confianza que los resuelva;
  * cada entrada del registro exige version y hash SHA-256 valido: sin hash o con hash
    invalido se rechaza;
  * cada nodo y cada entrada llevan procedencia (origen y fecha) y rechazan campos de
    credencial reutilizando `engine/project_store.py:19`;
  * el registro detecta deriva contra su snapshot versionado y nombra el campo exacto;
  * cero concesion de permisos y cero instalacion: ninguna funcion muta `toolScope` ni
    escribe en el sistema de skills.

Solo biblioteca estandar. No usa red, claves, proveedores ni modelos; no instala nada y
no modifica ningun archivo de la suite (se comprueba byte a byte). Registrar un perfil o
un nodo es una operacion de datos: no ejecuta, no autoriza y no despacha.
"""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from engine import agent_registry
from engine import evidence_graph
from engine import project_store

SUITE_ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = SUITE_ROOT / 'engine' / 'agent_registry.py'
GRAPH_PATH = SUITE_ROOT / 'engine' / 'evidence_graph.py'
SCHEMA_PATH = SUITE_ROOT / 'docs' / 'plataforma' / 'evidence-node.schema.json'
FROZEN_SCHEMA_SHA256 = '19c364da482b2bfd7f72a3ec33a2be73615e06557b72dd152eb157a4b5e09d8c'

ALLOWED_IMPORT_ROOTS = frozenset({'__future__', 'copy', 'datetime', 'hashlib', 'json', 'pathlib', 're'})
ENGINE_IMPORT_NAMES = frozenset({'project_store'})
FORBIDDEN_IMPORT_ROOTS = frozenset({'os', 'io', 'socket', 'ssl', 'urllib', 'http', 'http.client', 'ftplib',
                                    'smtplib', 'telnetlib', 'subprocess', 'shutil', 'tempfile', 'importlib',
                                    'ctypes', 'multiprocessing', 'asyncio', 'webbrowser', 'requests', 'pickle',
                                    'sqlite3', 'xmlrpc', 'signal', 'threading', 'glob', 'zipfile'})
FORBIDDEN_WRITE_CALLS = frozenset({'write_text', 'write_bytes', 'unlink', 'mkdir', 'rmdir', 'remove',
                                   'rename', 'replace', 'rmtree', 'copyfile', 'copytree', 'makedirs',
                                   'chmod', 'system', 'popen', 'run_python', 'urlopen', 'connect'})
# `str.replace(a, b)` con dos literales es la normalizacion del guard de nombres
# (`engine/project_store.py:38-46`), no `os.replace`/`Path.replace`. Se declara la
# excepcion para que quede auditada y solo exima a esa forma exacta.
STRING_ONLY_CALLS = frozenset({'replace'})
FORBIDDEN_CALL_NAMES = frozenset({'eval', 'exec', 'compile', '__import__', 'input', 'breakpoint'})
FORBIDDEN_PUBLIC_NAME = re.compile(r'(?i)^(grant|install|enable|authorize|elevate|unlock|permit|promote|'
                                   r'dispatch|execute|deploy|send|write|save|apply|mutate)')
CREDENTIAL_KEYS = ('api_key', 'accessToken', 'PASSWORD', 'api-key', 'bearer_token', 'client_secret')
PUBLIC_FUNCTIONS = ('register', 'register_profile', 'get', 'versions', 'list_entries', 'snapshot',
                    'detect_drift', 'is_drifted', 'verify_snapshot', 'allowed_models', 'model_report',
                    'check_model', 'compatible_models', 'common_models', 'verify_entry_hash',
                    'verify_instructions', 'profile_ref', 'profile_ref_record', 'inert_report',
                    'to_dict', 'to_json')

# Huella fijada una vez para la declaracion de `fixture_profile()`: si el algoritmo de
# hash (R-6), la proyeccion de veredictos o el canon de serializacion cambian, esta
# prueba lo detecta en cualquier proceso, con cualquier PYTHONHASHSEED y sin depender
# del estado de esta sesion.
FIXTURE_DIGESTS = {
    'entry': '6fff296773b0bb3a305a5c55b5ccf16e556e245a9139f3dd6bf3f4c34f007cd4',
    'snapshot': '9564c36736879aa79a9ea365a69dade88dc37c00cd10650d7c7ee1f009a27076',
    'graph': 'a3c50593e65b791d3d08a738b4bf5266008a7f53679c48195837c751887cbfa6',
    'schema': FROZEN_SCHEMA_SHA256,
    'states': {'contradicted': 0, 'insufficient': 0, 'supported': 1, 'unsupported': 0},
}
DIGEST_CODE = '''
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
from engine import agent_registry as ar
from engine import evidence_graph as eg

stamp = '2026-10-10T00:00:00Z'
root = Path(sys.argv[2])
profile = json.loads(sys.argv[3])
digest = ar.entry_hash('profile', profile['profile_id'], profile['profile_version'], profile)
registry = ar.AgentRegistry()
registry.register_profile(profile, sha256=digest, origin='tests', recorded_at=stamp)
snapshot = registry.snapshot('revisora-evidencia', origin='tests', recorded_at=stamp)
graph = eg.EvidenceGraph(root=root)
graph.add_file_evidence('ev-a', 'a.md', 'a.md contiene bytes A.', 'orgdna-local', origin='tests',
                        created_at=stamp, recorded_at=stamp)
graph.add_claim('claim-a', 'a.md contiene bytes A.', 'orgdna-local',
                refs=[{'kind': 'file', 'ref': 'a.md',
                       'sha256': hashlib.sha256((root / 'a.md').read_bytes()).hexdigest()}],
                edges=[{'target_node_id': 'ev-a', 'relation': 'supports'}],
                origin='tests', created_at=stamp, recorded_at=stamp)
audit = graph.audit()
print(json.dumps({'entry': digest, 'snapshot': snapshot['snapshot_sha256'],
                  'graph': hashlib.sha256(graph.to_json().encode('utf-8')).hexdigest(),
                  'states': audit['state_counts'], 'schema': graph.schema_sha256}, sort_keys=True))
'''


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def iso_utc(value):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def fixture_profile(profile_id='revisora-evidencia', version='1.0.0'):
    """Perfil declarativo valido de las cinco secciones del registro."""
    return {
        'profile_id': profile_id,
        'profile_version': version,
        'display_name': 'Revisora de evidencia',
        'role_ref': 'ASSURANCE',
        'instructions': {'text': 'Comprobar cada claim contra los bytes almacenados; no elevar sin hash.'},
        'skills': [{'name': 'systematic-debugging', 'version': '1.0.0',
                    'entrypoint': 'systematic-debugging/SKILL.md',
                    'sha256': '82cf4f794ffe8f5dac01be62722fc086da4939d0a1b86989fba20fe5d7f1ca17',
                    'status': 'PROPOSED', 'installation_verified': False}],
        'permissions': {'allow': ['ops_plan', 'ops_status'], 'deny': ['push']},
        'allowed_models': [
            {'model_id': 'deepseek-flash', 'provider_ref': 'deepseek', 'capabilities': ['text', 'tools']},
            {'model_id': 'deepseek-pro', 'provider_ref': 'deepseek', 'capabilities': ['text', 'tools', 'vision']},
        ],
        'tenant_id': 'orgdna-local',
    }


def registered(profile=None, **kwargs):
    """Registro con el perfil de fixture ya insertado por la via con hash obligatorio."""
    profile = copy.deepcopy(profile or fixture_profile())
    registry = agent_registry.AgentRegistry(**kwargs)
    digest = agent_registry.entry_hash('profile', profile['profile_id'], profile['profile_version'], profile)
    registry.register_profile(profile, sha256=digest, origin='docs/PLATAFORMA_CONTRATOS_V1.md',
                              recorded_at='2026-10-10T00:00:00Z')
    return registry, profile


class FixtureMixin:
    """Raiz temporal con bytes reales: la recomprobacion de hash es genuina, no simulada."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write('a.md', 'bytes A\n')
        self.write('b.md', 'bytes B\n')
        self.write('log.txt', 'salida de la prueba\n')
        self.tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp2.cleanup)

    def write(self, name, text):
        path = self.root / name
        path.write_text(text, encoding='utf-8')
        return path

    def digest_of(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def graph(self):
        return evidence_graph.EvidenceGraph(root=self.root)


# --------------------------------------------------------------------------- #
# Agent Registry: version y hash
# --------------------------------------------------------------------------- #
class RegistryHashTests(FixtureMixin, unittest.TestCase):
    def test_entry_without_hash_is_rejected(self):
        registry, profile = registered(fixture_profile())
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register('profile', 'otra-perfil', '1.0.0', {'profile_id': 'otra-perfil',
                                                                  'profile_version': '1.0.0'},
                              origin='tests')
        self.assertEqual(caught.exception.code, 'missing_hash')
        self.assertEqual(caught.exception.detail['entry_id'], 'otra-perfil')

    def test_entry_with_malformed_hash_is_rejected(self):
        for bad in ('zz', 'A' * 64, 'f' * 63, 'f' * 65, 7, None):
            with self.subTest(hash=bad):
                registry, _ = registered(fixture_profile())
                content = {'allow': ['ops_plan'], 'deny': ['push']}
                code = 'missing_hash' if bad is None else 'invalid_hash'
                with self.assertRaises(agent_registry.RegistryError) as caught:
                    registry.register('permissions', 'x.permissions', '1.0.0', content, sha256=bad,
                                      origin='tests')
                self.assertEqual(caught.exception.code, code)

    def test_entry_with_mismatched_hash_is_rejected_and_reports_both(self):
        registry, _ = registered(fixture_profile())
        content = {'allow': ['ops_plan'], 'deny': ['push']}
        expected = agent_registry.entry_hash('permissions', 'x.permissions', '1.0.0', content)
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register('permissions', 'x.permissions', '1.0.0', content, sha256='0' * 64,
                              origin='tests')
        self.assertEqual(caught.exception.code, 'hash_mismatch')
        self.assertEqual(caught.exception.detail['observed'], expected)
        self.assertEqual(caught.exception.detail['declared'], '0' * 64)

    def test_missing_or_invalid_version_is_rejected(self):
        registry, _ = registered(fixture_profile())
        content = {'name': 'x', 'version': '1.0.0', 'sha256': 'a' * 64}
        for version, code in ((None, 'invalid_version'), ('v1', 'invalid_version'), ('1.0', 'invalid_version'),
                              (1.0, 'invalid_version')):
            with self.subTest(version=version):
                digest = agent_registry.entry_hash('skills', 'x.skill', version, content)
                with self.assertRaises(agent_registry.RegistryError) as caught:
                    registry.register('skills', 'x.skill', version, content, sha256=digest, origin='tests')
                self.assertEqual(caught.exception.code, code)

    def test_unknown_entry_kind_is_rejected_by_the_frozen_vocabulary(self):
        registry, _ = registered(fixture_profile())
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register('agents', 'x', '1.0.0', {'a': 1}, sha256='a' * 64, origin='tests')
        self.assertEqual(caught.exception.code, 'unsupported_entry_kind')
        self.assertEqual(set(caught.exception.detail['admitted']), set(agent_registry.ENTRY_KINDS))

    def test_a_registered_version_is_never_overwritten(self):
        registry, _ = registered(fixture_profile())
        content = {'allow': ['ops_plan'], 'deny': ['push']}
        digest = agent_registry.entry_hash('permissions', 'x.permissions', '1.0.0', content)
        registry.register('permissions', 'x.permissions', '1.0.0', content, sha256=digest, origin='tests')
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register('permissions', 'x.permissions', '1.0.0', content, sha256=digest, origin='tests')
        self.assertEqual(caught.exception.code, 'duplicate_entry')
        older = {'allow': ['ops_status'], 'deny': ['push']}
        digest_older = agent_registry.entry_hash('permissions', 'x.permissions', '0.9.0', older)
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register('permissions', 'x.permissions', '0.9.0', older, sha256=digest_older, origin='tests')
        self.assertEqual(caught.exception.code, 'version_regression')

    def test_skill_entry_without_its_own_hash_is_rejected(self):
        registry, _ = registered(fixture_profile())
        for content in ({'name': 'sin-hash', 'version': '1.0.0'},
                        {'name': 'hash-corto', 'version': '1.0.0', 'sha256': 'abc'}):
            with self.subTest(content=content):
                digest = agent_registry.entry_hash('skills', 'x.skill', '1.0.0', content)
                with self.assertRaises(agent_registry.RegistryError) as caught:
                    registry.register('skills', 'x.skill', '1.0.0', content, sha256=digest, origin='tests')
                self.assertEqual(caught.exception.code, 'invalid_hash')

    def test_the_five_sections_are_versioned_and_their_hashes_recompute(self):
        registry, profile = registered(fixture_profile())
        rows = registry.section_entries('revisora-evidencia')
        self.assertEqual({row['entry_kind'] for row in rows},
                         {'profile', 'instructions', 'skills', 'permissions', 'models'})
        for row in rows:
            with self.subTest(entry=row['entry_id']):
                report = registry.verify_entry_hash(row['entry_kind'], row['entry_id'])
                self.assertTrue(report['valid'], report)
                self.assertEqual(report['stored'], report['recomputed'])
                self.assertRegex(report['recomputed'], r'^[0-9a-f]{64}$')
                self.assertEqual(report['entry_version'], profile['profile_version'])

    def test_profile_version_must_match_the_entry_version(self):
        registry = agent_registry.AgentRegistry()
        profile = fixture_profile()
        digest = agent_registry.entry_hash('profile', 'revisora-evidencia', '2.0.0', profile)
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register('profile', 'revisora-evidencia', '2.0.0', profile, sha256=digest,
                              origin='tests')
        self.assertEqual(caught.exception.code, 'profile_mismatch')
        self.assertEqual(caught.exception.detail['entry_version'], '2.0.0')
        other = fixture_profile('implementadora')
        digest = agent_registry.entry_hash('profile', 'otra-identidad', '1.0.0', other)
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register('profile', 'otra-identidad', '1.0.0', other, sha256=digest, origin='tests')
        self.assertEqual(caught.exception.code, 'profile_mismatch')
        self.assertEqual(registry.list_entries(), [])


# --------------------------------------------------------------------------- #
# Agent Registry: procedencia y guard de credenciales
# --------------------------------------------------------------------------- #
class RegistryAtomicityTests(FixtureMixin, unittest.TestCase):
    def test_a_failed_derived_section_leaves_no_partial_profile(self):
        registry = agent_registry.AgentRegistry()
        profile = fixture_profile()
        digest = agent_registry.entry_hash('profile', profile['profile_id'], profile['profile_version'], profile)
        with patch.object(agent_registry, 'MAX_ENTRIES', 3):
            with self.assertRaises(agent_registry.RegistryError) as caught:
                registry.register_profile(profile, sha256=digest, origin='tests')
        self.assertEqual(caught.exception.code, 'capacity_exceeded')
        self.assertEqual(registry.list_entries(), [])
        self.assertEqual(registry.section_entries('revisora-evidencia'), [])
        self.assertEqual(registry.inert_report()['entries'], 0)
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.get('profile', 'revisora-evidencia')
        self.assertEqual(caught.exception.code, 'unknown_entry')
        # Con la capacidad intacta, el mismo perfil se registra completo.
        registry.register_profile(profile, sha256=digest, origin='tests')
        self.assertEqual(len(registry.section_entries('revisora-evidencia')), 5)


class RegistryProvenanceTests(FixtureMixin, unittest.TestCase):
    def test_every_entry_requires_origin_and_date(self):
        registry = agent_registry.AgentRegistry()
        profile = fixture_profile()
        digest = agent_registry.entry_hash('profile', profile['profile_id'], profile['profile_version'], profile)
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register_profile(profile, sha256=digest)
        self.assertEqual(caught.exception.code, 'missing_provenance')
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register_profile(profile, sha256=digest, origin='   ')
        self.assertEqual(caught.exception.code, 'missing_provenance')
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register_profile(profile, sha256=digest, origin='tests', recorded_at='10/10/2026')
        self.assertEqual(caught.exception.code, 'missing_provenance')
        entry = registry.register_profile(profile, sha256=digest, origin='tests')['entry']
        self.assertEqual(entry['provenance']['origin'], 'tests')
        self.assertRegex(entry['provenance']['recorded_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$')

    def test_credential_field_names_are_rejected_by_the_project_store_guard(self):
        registry, _ = registered(fixture_profile())
        for key in CREDENTIAL_KEYS:
            with self.subTest(field=key):
                content = {'allow': ['ops_plan'], key: 'valor'}
                digest = agent_registry.entry_hash('permissions', 'x.permissions', '1.0.0', content)
                with self.assertRaises(agent_registry.RegistryError) as caught:
                    registry.register('permissions', 'x.permissions', '1.0.0', content, sha256=digest,
                                      origin='tests')
                self.assertEqual(caught.exception.code, 'prohibited_field')
                # El mismo objeto lo rechaza el guard literal del motor.
                with self.assertRaises(project_store.ProjectStoreError):
                    project_store._reject_secret_fields(content)
        self.assertIn('api_key', project_store.FORBIDDEN_FIELDS)
        self.assertTrue(agent_registry.credential_like('access_token'))
        self.assertTrue(agent_registry.credential_like('accessToken'))
        self.assertFalse(agent_registry.credential_like('tokens'))

    def test_install_and_grant_assertions_are_refused(self):
        registry, _ = registered(fixture_profile())
        cases = (('skills', {'name': 'x', 'version': '1.0.0', 'sha256': 'a' * 64,
                             'installation_verified': True}),
                 ('permissions', {'allow': ['ops_plan'], 'applied': True}),
                 ('skills', {'name': 'x', 'version': '1.0.0', 'sha256': 'a' * 64, 'status': 'INSTALLED'}))
        for kind, content in cases:
            with self.subTest(kind=kind):
                digest = agent_registry.entry_hash(kind, 'x.entry', '1.0.0', content)
                with self.assertRaises(agent_registry.RegistryError) as caught:
                    registry.register(kind, 'x.entry', '1.0.0', content, sha256=digest, origin='tests')
                self.assertEqual(caught.exception.code, 'install_forbidden')
        content = {'allow': ['ops_plan']}
        digest = agent_registry.entry_hash('permissions', 'x.permissions', '1.0.0', content)
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register('permissions', 'x.permissions', '1.0.0', content, sha256=digest,
                              origin='tests', state='installed')
        self.assertEqual(caught.exception.code, 'install_forbidden')

    def test_remote_references_and_embedded_credentials_are_refused(self):
        registry, _ = registered(fixture_profile())
        for text_ref, code in (('https://example.com/guia.md', 'remote_reference_forbidden'),
                               ('https://usuario:secreto@example.com/guia.md', 'embedded_credential'),
                               ('/etc/passwd', 'path_out_of_scope'),
                               ('../../fuera.md', 'path_out_of_scope')):
            with self.subTest(ref=text_ref):
                content = {'text_ref': text_ref}
                digest = agent_registry.entry_hash('instructions', 'x.instructions', '1.0.0', content)
                with self.assertRaises(agent_registry.RegistryError) as caught:
                    registry.register('instructions', 'x.instructions', '1.0.0', content, sha256=digest,
                                      origin='tests')
                self.assertEqual(caught.exception.code, code)


# --------------------------------------------------------------------------- #
# Agent Registry: snapshot y deriva
# --------------------------------------------------------------------------- #
class RegistryDriftTests(FixtureMixin, unittest.TestCase):
    def test_snapshot_is_versioned_hashed_and_immutable(self):
        registry, profile = registered(fixture_profile())
        first = registry.snapshot('revisora-evidencia', origin='tests')
        self.assertEqual(first['snapshot_version'], 1)
        self.assertGreater(first['field_count'], 0)
        self.assertRegex(first['snapshot_sha256'], r'^[0-9a-f]{64}$')
        self.assertTrue(registry.verify_snapshot('revisora-evidencia')['valid'])
        second = registry.snapshot('revisora-evidencia', origin='tests')
        self.assertEqual(second['snapshot_version'], 2)
        self.assertEqual(first['snapshot_sha256'], registry.snapshots('revisora-evidencia')[0]['snapshot_sha256'])
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.snapshot('perfil-inexistente', origin='tests')
        self.assertEqual(caught.exception.code, 'unknown_entry')

    def test_identical_profile_reports_no_drift(self):
        registry, profile = registered(fixture_profile())
        registry.snapshot('revisora-evidencia', origin='tests')
        report = registry.detect_drift('revisora-evidencia', copy.deepcopy(profile))
        self.assertFalse(report['drifted'])
        self.assertEqual(report['drift'], [])
        self.assertEqual(report['changed_fields'], [])
        self.assertEqual(report['resolution'], 'exact_field_diff')
        self.assertFalse(registry.is_drifted('revisora-evidencia', copy.deepcopy(profile)))

    def test_drift_names_the_exact_changed_field_for_each_section(self):
        registry, profile = registered(fixture_profile())
        registry.snapshot('revisora-evidencia', origin='tests')
        mutations = (
            ('instructions', lambda value: value.update(instructions={'text': 'Otra instruccion.'}),
             'instructions.text'),
            ('skills', lambda value: value['skills'][0].update(sha256='f' * 64),
             'skills[name=systematic-debugging].sha256'),
            ('permissions', lambda value: value['permissions']['allow'].append('ops_status'),
             'permissions.allow'),
            ('allowed_models', lambda value: value['allowed_models'][0]['capabilities'].append('vision'),
             'allowed_models[model_id=deepseek-flash].capabilities'),
            ('profile_version', lambda value: value.update(profile_version='1.0.1'), 'entry_version'),
        )
        for label, mutate, expected in mutations:
            with self.subTest(field=label):
                current = copy.deepcopy(profile)
                mutate(current)
                report = registry.detect_drift('revisora-evidencia', current)
                self.assertTrue(report['drifted'])
                self.assertEqual(report['field_count'], 1, report['drift'])
                self.assertEqual(report['changed_fields'], [expected])
                self.assertEqual(report['drift'][0]['change'], 'changed')
                self.assertFalse(registry.is_drifted('revisora-evidencia', copy.deepcopy(profile)))

    def test_drift_detects_removed_and_added_fields_without_noise(self):
        registry, profile = registered(fixture_profile())
        registry.snapshot('revisora-evidencia', origin='tests')
        removed = copy.deepcopy(profile)
        removed['permissions'].pop('deny')
        report = registry.detect_drift('revisora-evidencia', removed)
        self.assertEqual(report['changed_fields'], ['permissions.deny'])
        self.assertEqual(report['drift'][0]['change'], 'removed')
        added = copy.deepcopy(profile)
        added['allowed_models'].append({'model_id': 'tercero', 'provider_ref': 'otro',
                                        'capabilities': ['text']})
        report = registry.detect_drift('revisora-evidencia', added)
        self.assertEqual(report['changed_fields'],
                         ['allowed_models[model_id=tercero].capabilities',
                          'allowed_models[model_id=tercero].model_id',
                          'allowed_models[model_id=tercero].provider_ref'])
        self.assertTrue(all(row['change'] == 'added' for row in report['drift']))
        self.assertNotIn('allowed_models[model_id=deepseek-flash].capabilities', report['changed_fields'])

    def test_tampered_snapshot_is_detected(self):
        registry, _ = registered(fixture_profile())
        registry.snapshot('revisora-evidencia', origin='tests')
        self.assertTrue(registry.verify_snapshot('revisora-evidencia')['valid'])
        stored = registry._snapshots['revisora-evidencia'][0]
        stored['fields']['permissions.allow'] = json.dumps(['ops_plan', 'ops_status', 'ops_status'])
        report = registry.verify_snapshot('revisora-evidencia')
        self.assertFalse(report['valid'])
        self.assertNotEqual(report['stored'], report['recomputed'])

    def test_drift_without_a_snapshot_is_a_typed_error(self):
        registry, profile = registered(fixture_profile())
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.detect_drift('revisora-evidencia', profile)
        self.assertEqual(caught.exception.code, 'unknown_snapshot')

    def test_drift_against_another_registered_version_uses_the_entry_view(self):
        registry, profile = registered(fixture_profile())
        registry.snapshot('revisora-evidencia', origin='tests')
        upgraded = copy.deepcopy(profile)
        upgraded['profile_version'] = '1.0.1'
        upgraded['permissions']['allow'].append('visual_ascii')
        digest = agent_registry.entry_hash('profile', 'revisora-evidencia', '1.0.1', upgraded)
        registry.register_profile(upgraded, sha256=digest, origin='tests')
        report = registry.detect_drift_against_registered('revisora-evidencia', 'revisora-evidencia')
        self.assertTrue(report['drifted'])
        self.assertEqual(report['changed_fields'], ['entry_version', 'permissions.allow'])
        self.assertEqual(report['declared_entry_version'], '1.0.1')


# --------------------------------------------------------------------------- #
# Agent Registry: modelos permitidos
# --------------------------------------------------------------------------- #
class RegistryModelTests(FixtureMixin, unittest.TestCase):
    def test_a_model_outside_the_declared_set_is_not_allowed(self):
        registry, _ = registered(fixture_profile())
        report = registry.model_report('revisora-evidencia', ['deepseek-flash', 'modelo-ajeno'])
        self.assertEqual(report['outside_declared_set'], ['modelo-ajeno'])
        self.assertEqual(report['outside_declared_set_count'], 1)
        self.assertEqual(report['enabled_models'], [])
        self.assertEqual(report['network_calls'], 0)
        verdict = registry.check_model('revisora-evidencia', 'modelo-ajeno')
        self.assertFalse(verdict['allowed'])
        self.assertEqual(verdict['reason'], 'not_in_allowed_models')
        self.assertFalse(verdict['enabled'])

    def test_capability_gap_is_reported_without_granting_anything(self):
        registry, _ = registered(fixture_profile())
        ok = registry.check_model('revisora-evidencia', 'deepseek-pro', ['vision'])
        self.assertTrue(ok['allowed'])
        self.assertEqual(ok['reason'], 'declared_and_capable')
        self.assertFalse(ok['enabled'])
        gap = registry.check_model('revisora-evidencia', 'deepseek-flash', ['vision'])
        self.assertFalse(gap['allowed'])
        self.assertEqual(gap['reason'], 'missing_capability')
        self.assertEqual(gap['missing_capabilities'], ['vision'])
        self.assertEqual(registry.compatible_models('revisora-evidencia', ['vision']), ['deepseek-pro'])
        self.assertFalse(any(registry.get('models', 'revisora-evidencia.models')['content']
                             ['allowed_models'][index].get('enabled', False) for index in (0, 1)))

    def test_a_model_outside_the_declared_catalog_is_refused_at_registration(self):
        registry = agent_registry.AgentRegistry(known_models=['deepseek-flash'])
        content = {'allowed_models': [{'model_id': 'gpt-9', 'provider_ref': 'otro', 'capabilities': ['text']}]}
        digest = agent_registry.entry_hash('models', 'x.models', '1.0.0', content)
        with self.assertRaises(agent_registry.RegistryError) as caught:
            registry.register('models', 'x.models', '1.0.0', content, sha256=digest, origin='tests')
        self.assertEqual(caught.exception.code, 'unknown_model')
        self.assertEqual(caught.exception.detail['model_id'], 'gpt-9')

    def test_duplicate_or_incomplete_model_declarations_are_refused(self):
        registry = agent_registry.AgentRegistry()
        cases = (([{'model_id': 'm', 'provider_ref': 'p', 'capabilities': ['text']},
                   {'model_id': 'm', 'provider_ref': 'p', 'capabilities': ['text']}], 'duplicate_model'),
                 ([{'model_id': 'm', 'provider_ref': 'p'}], 'invalid_content'),
                 ([{'model_id': 'm', 'provider_ref': 'https://api.example.com', 'capabilities': ['text']}],
                  'remote_reference_forbidden'))
        for models, code in cases:
            with self.subTest(code=code):
                content = {'allowed_models': models}
                digest = agent_registry.entry_hash('models', 'x.models', '1.0.0', content)
                with self.assertRaises(agent_registry.RegistryError) as caught:
                    registry.register('models', 'x.models', '1.0.0', content, sha256=digest, origin='tests')
                self.assertEqual(caught.exception.code, code)

    def test_common_models_between_profiles_is_an_intersection(self):
        registry, first = registered(fixture_profile())
        second = fixture_profile('implementadora', '1.0.0')
        second['allowed_models'] = [{'model_id': 'deepseek-flash', 'provider_ref': 'deepseek',
                                     'capabilities': ['text', 'tools']}]
        second['permissions'] = {'allow': ['ops_plan'], 'deny': ['push']}
        digest = agent_registry.entry_hash('profile', 'implementadora', '1.0.0', second)
        registry.register_profile(second, sha256=digest, origin='tests')
        report = registry.common_models(['revisora-evidencia', 'implementadora'])
        self.assertEqual(report['common_models'], ['deepseek-flash'])
        self.assertEqual(report['outside_declared_set_count'], 0)
        self.assertEqual(registry.profile_ref('implementadora'),
                         'agent-registry:profile:implementadora@1.0.0#%s'
                         % agent_registry.entry_hash('profile', 'implementadora', '1.0.0', second)[:12])
        self.assertLessEqual(len(registry.profile_ref_record('implementadora')['agent_ref']), 120)
        self.assertFalse(registry.profile_ref_record('implementadora')['executable'])


# --------------------------------------------------------------------------- #
# Evidence Graph: estados del claim
# --------------------------------------------------------------------------- #
class GraphClaimStateTests(FixtureMixin, unittest.TestCase):
    def test_claim_without_evidence_is_unsupported_and_never_verified(self):
        graph = self.graph()
        graph.add_claim('claim-vacio', 'El motor no escribe en disco.', 'orgdna-local', origin='tests')
        status = graph.claim_status('claim-vacio')
        self.assertEqual(status['claim_state'], 'unsupported')
        self.assertEqual(status['schema_verdict'], 'unevidenced')
        self.assertFalse(status['verified'])
        self.assertEqual(status['evidence_refs'], 0)
        self.assertNotIn('verified', evidence_graph.CLAIM_STATES)
        self.assertNotIn('verified', evidence_graph.graph_capabilities()['claim_states'])
        self.assertEqual(graph.unsupported_claims(), ['claim-vacio'])
        self.assertEqual(graph.node('claim-vacio')['verdict'], 'unevidenced')

    def test_a_support_edge_does_not_elevate_a_claim_without_references(self):
        graph = self.graph()
        graph.add_file_evidence('ev-archivo', 'a.md', 'a.md contiene bytes A.', 'orgdna-local', origin='tests')
        graph.add_claim('claim-sin-refs', 'Afirmacion sin referencias propias.', 'orgdna-local', origin='tests')
        graph.add_edge('ev-archivo', 'claim-sin-refs', 'supports', note='Soporte declarado.')
        self.assertEqual(graph.claim_state('claim-sin-refs'), 'unsupported')
        self.assertFalse(graph.claim_status('claim-sin-refs')['verified'])
        self.assertEqual(graph.supported_claims(), [])

    def test_references_without_a_recomputed_hash_are_insufficient(self):
        graph = self.graph()
        graph.add_claim('claim-hash-falso', 'a.md contiene otras cosas.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': '0' * 64}], origin='tests')
        self.assertEqual(graph.claim_state('claim-hash-falso'), 'insufficient')
        self.assertEqual(graph.claim_status('claim-hash-falso')['schema_verdict'], 'insufficient')
        graph.add_test_evidence('ev-prueba', 'tests_v8_evidence.py', 'Prueba V8.', 'orgdna-local', origin='tests')
        self.assertEqual(graph.node('ev-prueba')['verdict'], 'insufficient')
        graph.add_claim('claim-prueba', 'La prueba V8 se ejecuto.', 'orgdna-local',
                        refs=[{'kind': 'test', 'ref': 'tests_v8_evidence.py',
                               'observed_at': '2026-10-10T00:00:00Z'}], origin='tests')
        self.assertEqual(graph.claim_state('claim-prueba'), 'insufficient')
        self.assertEqual(graph.claim_status('claim-prueba')['recompute_basis'], ['not_recomputable'])

    def test_a_test_reference_without_observed_at_is_rejected_by_the_contract(self):
        graph = self.graph()
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_claim('claim-sin-fecha', 'Prueba sin fecha de observacion.', 'orgdna-local',
                            refs=[{'kind': 'test', 'ref': 'tests_v8_evidence.py'}], origin='tests')
        self.assertEqual(caught.exception.code, 'invalid_node')
        self.assertTrue(any('observed_at' in error for error in caught.exception.detail['errors']),
                        caught.exception.detail['errors'])
        self.assertEqual(graph.node_ids(), [])

    def test_supported_requires_a_recomputed_sha256(self):
        graph = self.graph()
        graph.add_claim('claim-soportado', 'a.md contiene bytes A.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': self.digest_of('a.md')}],
                        origin='tests')
        status = graph.claim_status('claim-soportado')
        self.assertEqual(status['claim_state'], 'supported')
        self.assertTrue(status['verified'])
        self.assertEqual(status['verified_refs'], 1)
        self.assertEqual(status['recompute_basis'], ['file_sha256'])
        self.assertTrue(graph.node('claim-soportado')['evidence_refs'][0]['verified'])
        self.assertEqual(graph.supported_claims(), ['claim-soportado'])
        self.assertEqual(graph.assert_no_unverified_supported(),
                         {'claims_supported': 1, 'supported_without_recomputed_hash': 0})

    def test_a_test_reference_is_verified_only_through_a_local_artifact(self):
        graph = self.graph()
        graph.attach_artifact('test', 'log.txt', 'log.txt')
        graph.add_test_evidence('ev-log', 'log.txt', 'El registro de la prueba existe.', 'orgdna-local',
                                origin='tests', sha256=self.digest_of('log.txt'),
                                observed_at='2026-10-10T00:00:00Z')
        ref = graph.node('ev-log')['evidence_refs'][0]
        self.assertEqual(ref['kind'], 'test')
        self.assertEqual(ref['observed_at'], '2026-10-10T00:00:00Z')
        self.assertTrue(ref['verified'])
        self.assertEqual(graph.node('ev-log')['verdict'], 'supported')
        artifact = graph.attach_artifact('test', 'otro.txt', 'log.txt')
        self.assertEqual(artifact['sha256'], self.digest_of('log.txt'))

    def test_file_reference_requires_an_existing_local_file(self):
        graph = self.graph()
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_file_evidence('ev-ausente', 'no-existe.md', 'Falta.', 'orgdna-local', origin='tests')
        self.assertEqual(caught.exception.code, 'file_unavailable')
        node = graph.add_file_evidence('ev-declarado', 'no-existe.md', 'Declarado sin bytes.',
                                       'orgdna-local', origin='tests', sha256='a' * 64)
        self.assertFalse(node['evidence_refs'][0]['verified'])
        self.assertEqual(node['verdict'], 'insufficient')
        audit = graph.audit()
        self.assertEqual([row['basis'] for row in audit['unavailable_refs']], ['file_unavailable'])

    def test_credential_fields_in_a_reference_are_rejected_by_the_guard(self):
        graph = self.graph()
        for key in CREDENTIAL_KEYS:
            with self.subTest(field=key):
                with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
                    graph.add_node('nodo-credencial', 'claim', 'Con credencial.', 'orgdna-local',
                                   evidence_refs=[{'kind': 'file', 'ref': 'a.md',
                                                   'sha256': self.digest_of('a.md'), key: 'x'}],
                                   origin='tests')
                self.assertEqual(caught.exception.code, 'prohibited_field')
                with self.assertRaises(project_store.ProjectStoreError):
                    project_store._reject_secret_fields({'ref': {key: 'x'}})
        self.assertTrue(evidence_graph.credential_like('bearer_token'))
        self.assertTrue(evidence_graph.credential_like('bearerToken'))
        self.assertTrue(evidence_graph.credential_like('client-secret'))
        self.assertFalse(evidence_graph.credential_like('tokens'))


# --------------------------------------------------------------------------- #
# Evidence Graph: contradicciones explicitas
# --------------------------------------------------------------------------- #
class GraphContradictionTests(FixtureMixin, unittest.TestCase):
    def _pair(self, graph=None):
        graph = graph or self.graph()
        digest = self.digest_of('a.md')
        graph.add_claim('claim-afirma', 'a.md contiene bytes A.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': digest}], origin='tests')
        graph.add_claim('claim-niega', 'a.md no contiene bytes A.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': digest}], origin='tests')
        return graph

    def test_two_claims_with_contradictory_evidence_are_both_contradicted(self):
        graph = self._pair()
        self.assertEqual(graph.claim_state('claim-afirma'), 'supported')
        graph.add_edge('claim-niega', 'claim-afirma', 'contradicts',
                       note='Afirmaciones incompatibles sobre los mismos bytes.')
        for node_id in ('claim-afirma', 'claim-niega'):
            with self.subTest(node=node_id):
                status = graph.claim_status(node_id)
                self.assertEqual(status['claim_state'], 'contradicted')
                self.assertEqual(status['schema_verdict'], 'contradicted')
                self.assertFalse(status['verified'])
                self.assertEqual(status['resolution'], 'explicit_contradiction')
        self.assertEqual(graph.contradicted_claims(), ['claim-afirma', 'claim-niega'])
        report = graph.contradiction_report()
        self.assertEqual(report['contradiction_count'], 1)
        self.assertEqual(report['resolution'], 'explicit_only')
        self.assertFalse(report['resolved_by_majority'])
        self.assertFalse(report['resolved_by_confidence'])
        self.assertFalse(report['support_counts_compared'])
        self.assertEqual(graph.supported_claims(), [])
        self.assertEqual(graph.assert_no_unverified_supported()['supported_without_recomputed_hash'], 0)

    def test_majority_and_confidence_never_resolve_a_contradiction(self):
        graph = self.graph()
        digest = self.digest_of('a.md')
        graph.add_claim('claim-mayoria', 'a.md contiene bytes A.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': digest},
                              {'kind': 'file', 'ref': 'a.md', 'sha256': digest},
                              {'kind': 'file', 'ref': 'a.md', 'sha256': digest}], origin='tests')
        self.assertEqual(graph.claim_state('claim-mayoria'), 'supported')
        graph.add_claim('claim-minoria', 'a.md esta vacio.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'b.md', 'sha256': self.digest_of('b.md')}],
                        origin='tests')
        graph.add_edge('claim-minoria', 'claim-mayoria', 'contradicts', note='Una sola contradiccion.')
        status = graph.claim_status('claim-mayoria')
        self.assertEqual(status['claim_state'], 'contradicted')
        self.assertEqual(status['recomputed_refs'], 3)
        self.assertEqual(status['contradiction_count'], 1)
        self.assertFalse(status['resolved_by_majority'])
        self.assertFalse(status['resolved_by_confidence'])
        self.assertFalse(status['support_counts_compared'])
        self.assertEqual(status['decided_by'], 'frozen_verdict_rules_v1')
        for field in ('confidence', 'confidence_score', 'majority'):
            with self.subTest(field=field):
                with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
                    graph.add_node('nodo-confianza', 'claim', 'Con confianza.', 'orgdna-local',
                                   evidence_refs=[{'kind': 'file', 'ref': 'a.md',
                                                   'sha256': digest, field: 0.9}], origin='tests')
                self.assertEqual(caught.exception.code, 'invalid_node')
                self.assertTrue(any('confidence' in error or field in error
                                    for error in caught.exception.detail['errors']))

    def test_divergent_hashes_for_the_same_reference_are_a_contradiction(self):
        graph = self.graph()
        graph.add_claim('claim-uno', 'a.md contiene bytes A.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': self.digest_of('a.md')}],
                        origin='tests')
        graph.add_node('nodo-divergente', 'evidence', 'El mismo archivo con otro estado.', 'orgdna-local',
                       evidence_refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': 'f' * 64}], origin='tests')
        self.assertEqual(graph.claim_state('claim-uno'), 'contradicted')
        report = graph.contradiction_report()
        divergent = [row for row in report['contradictions'] if row['kind'] == 'divergent_evidence']
        self.assertEqual(len(divergent), 1)
        self.assertEqual(divergent[0]['evidence_ref'], {'kind': 'file', 'ref': 'a.md'})
        self.assertEqual(divergent[0]['sha256_values'], sorted(['f' * 64, self.digest_of('a.md')]))
        self.assertIn('nodo-divergente', divergent[0]['nodes'])
        self.assertFalse(report['resolved_by_majority'])

    def test_contradiction_propagates_along_support_and_dependency_edges(self):
        graph = self.graph()
        graph.add_file_evidence('ev-a', 'a.md', 'a.md contiene bytes A.', 'orgdna-local', origin='tests')
        graph.add_claim('claim-depende', 'Lo observado en a.md se sostiene.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'b.md', 'sha256': self.digest_of('b.md')}],
                        origin='tests')
        graph.add_edge('claim-depende', 'ev-a', 'depends_on', note='Depende del archivo observado.')
        self.assertEqual(graph.claim_state('claim-depende'), 'supported')
        graph.add_node('ev-divergente', 'evidence', 'El archivo con otro estado.', 'orgdna-local',
                       evidence_refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': 'f' * 64}], origin='tests')
        self.assertEqual(graph.claim_state('claim-depende'), 'contradicted')
        self.assertIn('claim-depende', graph.contradicted_nodes())
        self.assertEqual(graph.node('claim-depende')['verdict'], 'contradicted')

    def test_audit_reports_unverified_supported_and_stale_flags(self):
        graph = self.graph()
        digest = self.digest_of('a.md')
        graph.add_claim('claim-archivo', 'a.md contiene bytes A.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': digest}], origin='tests')
        audit = graph.audit()
        self.assertEqual(audit['supported_without_recomputed_hash'], [])
        self.assertEqual(audit['unsupported_with_verified_ref'], [])
        self.assertEqual(audit['stale_verified_flags'], [])
        self.assertEqual(audit['node_errors'], {})
        self.assertEqual(audit['nodes'], 1)
        self.assertEqual(audit['inert']['resolves_by_majority'], False)
        self.assertEqual(audit['counters']['write_operations'], 0)
        self.write('a.md', 'bytes A modificados\n')
        audit = graph.audit()
        self.assertEqual(len(audit['stale_verified_flags']), 1)
        flag = audit['stale_verified_flags'][0]
        self.assertEqual(flag['node_id'], 'claim-archivo')
        self.assertTrue(flag['stored_verified'])
        self.assertFalse(flag['recomputed_verified'])
        self.assertEqual(flag['recompute_basis'], 'file_sha256')
        self.assertEqual(graph.claim_state('claim-archivo'), 'insufficient')

    def test_a_forward_edge_to_an_unknown_node_is_reported_not_hidden(self):
        graph = self.graph()
        graph.add_claim('claim-referencia-futura', 'Cita un nodo aun no registrado.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': self.digest_of('a.md')}],
                        edges=[{'target_node_id': 'nodo-futuro', 'relation': 'supports'}], origin='tests')
        report = graph.audit()
        self.assertEqual(report['dangling_edges'],
                         [{'source_node_id': 'claim-referencia-futura', 'target_node_id': 'nodo-futuro',
                           'relation': 'supports'}])
        self.assertEqual(graph.claim_state('claim-referencia-futura'), 'supported')
        self.assertEqual(graph.contradicted_nodes(), set())
        self.assertEqual(graph.edges()[0]['target_node_id'], 'nodo-futuro')

    def test_unknown_node_or_edge_target_is_a_typed_error(self):
        graph = self.graph()
        graph.add_claim('claim-a', 'Afirmacion.', 'orgdna-local', origin='tests')
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_edge('claim-a', 'no-existe', 'supports')
        self.assertEqual(caught.exception.code, 'unknown_node')
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_edge('claim-a', 'claim-a', 'supports')
        self.assertEqual(caught.exception.code, 'invalid_edge')
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_edge('claim-a', 'claim-a', 'apoya')
        self.assertEqual(caught.exception.code, 'invalid_edge')
        self.assertEqual(graph.node('claim-a')['edges'], [])
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.claim_state('no-existe')
        self.assertEqual(caught.exception.code, 'unknown_node')


# --------------------------------------------------------------------------- #
# Evidence Graph: contrato congelado y procedencia
# --------------------------------------------------------------------------- #
class GraphContractTests(FixtureMixin, unittest.TestCase):
    def test_every_node_carries_provenance_and_matches_the_frozen_schema(self):
        graph = self.graph()
        self.assertEqual(graph.schema_sha256, FROZEN_SCHEMA_SHA256)
        self.assertEqual(hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(), FROZEN_SCHEMA_SHA256)
        nodes = [
            graph.add_claim('claim-contrato', 'El contrato v1 rige el grafo.', 'orgdna-local', origin='docs/PLATAFORMA_CONTRATOS_V1.md'),
            graph.add_file_evidence('ev-contrato', 'a.md', 'a.md contiene bytes A.', 'orgdna-local', origin='tests'),
            graph.add_test_evidence('ev-test', 'tests_v8_evidence.py', 'Prueba V8 declarada.', 'orgdna-local', origin='tests'),
            graph.add_tool_output_evidence('ev-tool', 'ops_status', 'Salida de tool declarada.', 'orgdna-local', origin='tests'),
            graph.add_api_result_evidence('ev-api', 'resultado-local-01', 'Resultado local declarado.', 'orgdna-local', origin='tests'),
            graph.add_decision('ev-decision', 'Se congela el contrato v1.', 'orgdna-local',
                               'docs/PLATAFORMA_DECISIONES.md#D-R0-2', origin='docs/PLATAFORMA_DECISIONES.md'),
        ]
        aliases = {node['node_id']: graph.kind_alias(node['node_id']) for node in nodes}
        self.assertEqual(set(aliases.values()), {'claim', 'file', 'test', 'tool_output', 'api', 'decision'})
        for node in nodes:
            with self.subTest(node=node['node_id']):
                self.assertEqual(evidence_graph.validate_instance(node, graph.schema), [])
                self.assertEqual(graph.validate_nodes()[node['node_id']], [])
                self.assertRegex(node['created_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$')
                provenance = graph.provenance(node['node_id'])
                self.assertTrue(provenance['origin'])
                self.assertRegex(provenance['recorded_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$')
                self.assertEqual(node['evidence_node_version'], evidence_graph.GRAPH_VERSION)
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_claim('claim-sin-origen', 'Sin procedencia.', 'orgdna-local')
        self.assertEqual(caught.exception.code, 'missing_provenance')
        payload = json.loads(graph.to_json())
        self.assertEqual(evidence_graph.canonical_json(payload), graph.to_json())
        self.assertEqual(len(payload['nodes']), 6)
        self.assertEqual(payload['schema']['sha256'], FROZEN_SCHEMA_SHA256)

    def test_unknown_tenant_or_invalid_optional_field_is_rejected(self):
        graph = self.graph()
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_claim('claim-sin-tenant', 'Sin inquilino.', 'ab')
        self.assertEqual(caught.exception.code, 'invalid_node')
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_claim('UNO', 'Identificador fuera del patron.', 'orgdna-local', origin='tests')
        self.assertEqual(caught.exception.code, 'invalid_node')
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_claim('claim-vacio', '   ', 'orgdna-local', origin='tests')
        self.assertEqual(caught.exception.code, 'invalid_node')
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_claim('claim-plano', 'Plano no declarado.', 'orgdna-local', origin='tests',
                            plane='personal-secreto')
        self.assertEqual(caught.exception.code, 'invalid_node')
        self.assertTrue(any('enumeracion' in error for error in caught.exception.detail['errors']),
                        caught.exception.detail['errors'])
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            graph.add_claim('claim-superado', 'Campo superado con tipo ajeno.', 'orgdna-local', origin='tests',
                            superseded_by=7)
        self.assertEqual(caught.exception.code, 'invalid_node')
        self.assertEqual(graph.node_ids(), [])
        self.assertEqual(graph.audit()['node_errors'], {})

    def test_tampered_or_missing_contract_is_refused(self):
        graph = self.graph()
        self.assertEqual(graph.schema_path, str(SCHEMA_PATH))
        tampered = Path(self.tmp2.name) / 'evidence-node.schema.json'
        document = json.loads(SCHEMA_PATH.read_text('utf-8'))
        document['prohibited_fields'] = document['prohibited_fields'][:-1]
        tampered.write_text(json.dumps(document), encoding='utf-8')
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            evidence_graph.EvidenceGraph(root=self.root, schema_path=tampered)
        self.assertEqual(caught.exception.code, 'unsupported_schema')
        changed = json.loads(SCHEMA_PATH.read_text('utf-8'))
        changed['properties']['node_kind']['enum'] = ['claim', 'evidence']
        other = Path(self.tmp2.name) / 'otro.schema.json'
        other.write_text(json.dumps(changed), encoding='utf-8')
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            evidence_graph.EvidenceGraph(root=self.root, schema_path=other)
        self.assertEqual(caught.exception.code, 'unsupported_schema')
        with self.assertRaises(evidence_graph.EvidenceGraphError) as caught:
            evidence_graph.EvidenceGraph(root=self.root, schema_path=Path(self.tmp2.name) / 'inexistente.json')
        self.assertEqual(caught.exception.code, 'missing_schema')

    def test_the_validator_supports_the_keywords_the_contract_uses(self):
        graph = self.graph()
        node = graph.add_claim('claim-validador', 'Validacion declarada.', 'orgdna-local', origin='tests')
        broken = dict(node, node_kind='afirmacion')
        errors = evidence_graph.validate_instance(broken, graph.schema)
        self.assertTrue(any('enumeracion' in error for error in errors), errors)
        ref_errors = evidence_graph.validate_instance(dict(node, evidence_refs=[{'kind': 'file', 'ref': 'a.md'}]),
                                                      graph.schema)
        self.assertTrue(any('sha256' in error for error in ref_errors), ref_errors)
        naming = evidence_graph.validate_instance(dict(node, api_key='x'), graph.schema)
        self.assertTrue(any('api_key' in error for error in naming), naming)
        unsupported = evidence_graph.validate_instance(node, {'type': 'object', 'patternProperties': {}})
        self.assertTrue(any('no soportada' in error for error in unsupported), unsupported)
        self.assertEqual(evidence_graph.validate_instance(node, graph.schema), [])


# --------------------------------------------------------------------------- #
# Inertitud: sin red, sin escritura, sin permisos, sin instalacion
# --------------------------------------------------------------------------- #
class InertnessTests(FixtureMixin, unittest.TestCase):
    def _tree_state(self):
        state = {}
        targets = [REGISTRY_PATH, GRAPH_PATH, SUITE_ROOT / 'MANIFIESTO_SHA256.txt',
                   SUITE_ROOT / 'engine' / 'bundle.py', SUITE_ROOT / 'engine' / 'project_store.py',
                   SUITE_ROOT / 'engine' / 'tool_permissions.py', SCHEMA_PATH]
        for folder in ('skills', 'web', 'docs/plataforma'):
            base = SUITE_ROOT / folder
            if base.is_dir():
                targets.extend(sorted(path for path in base.rglob('*') if path.is_file()
                                      and '__pycache__' not in path.parts))
        for path in targets:
            if path.is_file():
                state[path.relative_to(SUITE_ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        state['<raiz>'] = '|'.join(sorted(item.name for item in SUITE_ROOT.iterdir()))
        return state

    def test_module_imports_only_stdlib_and_the_engine(self):
        for path in (REGISTRY_PATH, GRAPH_PATH):
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text('utf-8'))
                roots = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        roots.update(alias.name.split('.')[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        roots.add((node.module or '').split('.')[0])
                self.assertFalse(roots & FORBIDDEN_IMPORT_ROOTS, roots & FORBIDDEN_IMPORT_ROOTS)
                self.assertFalse(roots - ALLOWED_IMPORT_ROOTS - ENGINE_IMPORT_NAMES, roots)
                source = path.read_text('utf-8')
                for token in ('socket', 'urllib', 'requests', 'subprocess', 'shutil', 'tempfile',
                              'http.client', 'os.system'):
                    self.assertNotIn('import ' + token, source)

    def test_module_never_writes_installs_or_grants(self):
        for path in (REGISTRY_PATH, GRAPH_PATH):
            with self.subTest(module=path.name):
                tree = ast.parse(path.read_text('utf-8'))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        receiver = getattr(node.func, 'value', None)
                        if isinstance(receiver, ast.Name) and receiver.id == 're':
                            continue  # `re.compile` no compila codigo
                        name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)
                        string_api = (name in STRING_ONLY_CALLS and len(node.args) == 2
                                      and all(isinstance(argument, ast.Constant)
                                              and isinstance(argument.value, str) for argument in node.args))
                        if not string_api:
                            self.assertNotIn(name, FORBIDDEN_WRITE_CALLS, '%s:%s' % (path.name, name))
                        self.assertNotIn(name, FORBIDDEN_CALL_NAMES, '%s:%s' % (path.name, name))
                        if name == 'open':
                            modes = [argument for argument in node.args[1:]] + \
                                    [keyword.value for keyword in node.keywords if keyword.arg == 'mode']
                            for mode in modes:
                                self.assertNotIn(getattr(mode, 'value', ''), ('w', 'a', 'x', 'w+', 'r+'))
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Attribute):
                                self.assertNotIn(target.attr.lower(), {'toolscope', 'tool_scope', 'skills'})

    def test_running_every_operation_leaves_the_suite_byte_identical(self):
        before = self._tree_state()
        registry, profile = registered(fixture_profile())
        registry.snapshot('revisora-evidencia', origin='tests')
        registry.detect_drift('revisora-evidencia', copy.deepcopy(profile))
        registry.model_report('revisora-evidencia', ['deepseek-flash', 'ajeno'])
        registry.check_model('revisora-evidencia', 'deepseek-pro', ['vision'])
        registry.common_models(['revisora-evidencia'])
        registry.verify_entry_hash('profile', 'revisora-evidencia')
        registry.verify_instructions('revisora-evidencia')
        registry.inert_report()
        registry.to_json()
        graph = self.graph()
        graph.add_file_evidence('ev-inerte', 'a.md', 'a.md contiene bytes A.', 'orgdna-local', origin='tests')
        graph.add_test_evidence('ev-inerte-2', 'log.txt', 'Registro local.', 'orgdna-local', origin='tests',
                                artifact='log.txt', sha256=self.digest_of('log.txt'))
        graph.add_claim('claim-inerte', 'a.md contiene bytes A.', 'orgdna-local',
                        refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': self.digest_of('a.md')}],
                        edges=[{'target_node_id': 'ev-inerte', 'relation': 'supports'}], origin='tests')
        graph.add_edge('ev-inerte-2', 'claim-inerte', 'depends_on')
        graph.add_decision('decision-inerte', 'Se congela el contrato v1.', 'orgdna-local',
                           'docs/PLATAFORMA_DECISIONES.md', origin='tests')
        graph.audit()
        graph.assert_no_unverified_supported()
        graph.to_json()
        after = self._tree_state()
        self.assertEqual(after, before)
        self.assertEqual(before['<raiz>'], after['<raiz>'])
        self.assertIn('engine/agent_registry.py', after)
        self.assertIn('engine/evidence_graph.py', after)
        self.assertEqual(set(before), set(after))

    def test_registry_capacity_guard_and_zero_counters(self):
        registry, _ = registered(fixture_profile())
        report = registry.inert_report()
        self.assertEqual(report['inert_by_default'], True)
        self.assertFalse(report['install_capability'])
        self.assertFalse(report['grant_capability'])
        self.assertFalse(report['tool_scope_mutated'])
        self.assertEqual(report['skills_written'], 0)
        self.assertEqual(set(report['counters'].values()), {0})
        self.assertEqual(report['entry_kinds']['profile'], 1)
        self.assertEqual(registry.to_json(), agent_registry.canonical_json(json.loads(registry.to_json())))
        capabilities = agent_registry.registry_capabilities()
        self.assertEqual(capabilities['flags'], agent_registry.INERT_FLAGS)
        graph_capabilities = evidence_graph.graph_capabilities()
        self.assertEqual(graph_capabilities['flags'], evidence_graph.INERT_FLAGS)
        self.assertFalse(graph_capabilities['flags']['writes_to_disk'])
        self.assertFalse(graph_capabilities['flags']['resolves_by_majority'])
        self.assertTrue(graph_capabilities['flags']['reads_files_for_hashing'])

    def test_public_surface_grants_and_installs_nothing(self):
        for module, owner in ((agent_registry, agent_registry.AgentRegistry),
                              (evidence_graph, evidence_graph.EvidenceGraph)):
            with self.subTest(module=module.__name__):
                public = [name for name in dir(owner) if not name.startswith('_')]
                offending = [name for name in public if FORBIDDEN_PUBLIC_NAME.match(name)]
                self.assertEqual(offending, [])
        for name in PUBLIC_FUNCTIONS:
            self.assertTrue(hasattr(agent_registry.AgentRegistry, name), name)
        self.assertTrue(all(not FORBIDDEN_PUBLIC_NAME.match(name)
                            for name in agent_registry.registry_capabilities()['entry_kinds']))

    def test_the_suite_declares_at_least_fourteen_cases(self):
        source = Path(__file__).read_text('utf-8')
        declared = re.findall(r'\n    def (test_[a-z0-9_]+)\(', source)
        self.assertGreaterEqual(len(declared), 14, declared)
        self.assertEqual(len(declared), len(set(declared)))
        required = ('test_claim_without_evidence_is_unsupported_and_never_verified',
                    'test_two_claims_with_contradictory_evidence_are_both_contradicted',
                    'test_entry_without_hash_is_rejected',
                    'test_entry_with_malformed_hash_is_rejected',
                    'test_every_node_carries_provenance_and_matches_the_frozen_schema',
                    'test_every_entry_requires_origin_and_date',
                    'test_drift_names_the_exact_changed_field_for_each_section',
                    'test_running_every_operation_leaves_the_suite_byte_identical')
        for name in required:
            self.assertIn(name, declared, name)


class DeterminismTests(FixtureMixin, unittest.TestCase):
    """R-6: el mismo contenido produce la misma huella en cualquier proceso."""

    def test_independent_constructions_share_entry_snapshot_and_graph_hash(self):
        first, profile = registered(fixture_profile())
        second, _ = registered(fixture_profile())
        self.assertEqual(agent_registry.entry_hash('profile', profile['profile_id'],
                                                   profile['profile_version'], profile),
                         agent_registry.entry_hash('profile', profile['profile_id'],
                                                   profile['profile_version'], copy.deepcopy(profile)))
        self.assertEqual(first.get('profile', 'revisora-evidencia')['content_sha256'],
                         second.get('profile', 'revisora-evidencia')['content_sha256'])
        first.snapshot('revisora-evidencia', origin='tests', recorded_at='2026-10-10T00:00:00Z')
        second.snapshot('revisora-evidencia', origin='tests', recorded_at='2026-10-10T00:00:00Z')
        self.assertEqual(first.snapshots('revisora-evidencia')[0]['snapshot_sha256'],
                         second.snapshots('revisora-evidencia')[0]['snapshot_sha256'])
        stamp = '2026-10-10T00:00:00Z'
        graphs = []
        for _ in range(2):
            graph = self.graph()
            graph.add_file_evidence('ev-a', 'a.md', 'a.md contiene bytes A.', 'orgdna-local',
                                    origin='tests', created_at=stamp, recorded_at=stamp)
            graph.add_claim('claim-a', 'a.md contiene bytes A.', 'orgdna-local',
                            refs=[{'kind': 'file', 'ref': 'a.md', 'sha256': self.digest_of('a.md')}],
                            origin='tests', created_at=stamp, recorded_at=stamp)
            graphs.append(graph.to_json())
        self.assertEqual(graphs[0], graphs[1])
        self.assertEqual(json.loads(graphs[0])['assessment']['claim-a']['claim_state'], 'supported')

    def test_hashes_are_stable_across_processes_and_hash_seeds(self):
        profile = fixture_profile()
        outputs = []
        for seed in ('1', '2', 'random'):
            environment = dict(os.environ, PYTHONHASHSEED=seed, PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-c', DIGEST_CODE, str(SUITE_ROOT), str(self.root),
                                     json.dumps(profile, ensure_ascii=True)],
                                    capture_output=True, text=True, env=environment, timeout=90)
            self.assertEqual(result.returncode, 0, result.stderr[-400:])
            outputs.append(result.stdout.strip())
        self.assertEqual(len(set(outputs)), 1, outputs)
        self.assertEqual(json.loads(outputs[0]), FIXTURE_DIGESTS)


if __name__ == '__main__':
    unittest.main()
