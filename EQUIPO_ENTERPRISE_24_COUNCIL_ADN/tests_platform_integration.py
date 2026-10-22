"""Integracion y empaquetado V9 (`t9`, INT-A): allowlist literal, manifiesto, accion de solo lectura y acta.

Verifica offline, con biblioteca estandar y sin ejecutar ningun plano:

1. `RUNTIME_ALLOWLIST` es una tupla LITERAL de nombres exactos, sin globs, sin patrones y sin
   duplicados, y cubre los 11 modulos, las 8 pruebas y los 13 documentos de plataforma.
2. Todo archivo `engine/*.py` de la entrega esta en la allowlist; toda entrada de la allowlist
   existe en disco y figura en `MANIFIESTO_SHA256.txt` con su hash correcto (bundle.py).
3. El manifiesto cubre EXACTAMENTE `bundle._expected_package_paths`, no se lista a si mismo,
   y la huella publicada en el acta es reconstruible con el marcador declarado.
4. La unica accion nueva de `engine/bridge.py` (`platform-planes-status`) es estrictamente de
   solo lectura: no muta estado, no anade recibos, no ensucia el proyecto, no abre red, no
   lanza procesos, no consume consentimiento ni presupuesto y no ejecuta ningun plano.
5. Lo que el acta declara NOT_RUN lo declara de verdad y sin atribuir ejecucion a los planos.
6. Los formatos de exportacion existentes conservan su version, y las pruebas previas no se
   han modificado (se comprueba contra la lista maquina-legible del acta y contra los pins).
7. F-T4-2: `policy.v2.schema.json` es aditivo (v1 intacto byte a byte), `$defs.mandatory_gates`
   es una restriccion referenciada y evaluable, y las rutas de accion del motor I3 conforman
   14/14 bajo v2 (bajo v1 fallaban exactamente las 2 rutas sin puerta medidas por su propietario).

Codificacion: este host tiene cp1252 como encoding por defecto, asi que TODO archivo de texto se
lee con `encoding='utf-8'`. Ninguna prueba previa se modifica ni se corrige desde aqui.
"""
import ast
import hashlib
import json
import re
import socket
import tempfile
import unittest
from pathlib import Path

import tests_platform_eval_artifacts as eval_artifacts_suite
import tests_platform_policy as policy_suite
from engine import bundle
from engine import policy_engine as pe
from engine.bridge import BridgeState
from engine.project_store import ProjectStore
from tests_bridge import NullStore

SUITE_ROOT = Path(__file__).resolve().parent
BUNDLE_PATH = SUITE_ROOT / 'engine' / 'bundle.py'
BRIDGE_PATH = SUITE_ROOT / 'engine' / 'bridge.py'
MANIFEST_PATH = SUITE_ROOT / 'MANIFIESTO_SHA256.txt'
ACTA_PATH = SUITE_ROOT / 'docs' / 'PLATAFORMA_ENTREGA_V9.md'
CONTRATOS_PATH = SUITE_ROOT / 'docs' / 'PLATAFORMA_CONTRATOS_V1.md'
POLICY_V1 = SUITE_ROOT / 'docs' / 'plataforma' / 'policy.schema.json'
POLICY_V2 = SUITE_ROOT / 'docs' / 'plataforma' / 'policy.v2.schema.json'

#: Pin de R0 para v1, replicado por tests_platform_policy.py:39 (no se modifica).
POLICY_V1_SHA256 = 'c6026c70690115c7e37ac0d080510f6f19b36cabc76c89701e7d5443bf54118e'
ACTA_DOC = 'docs/PLATAFORMA_ENTREGA_V9.md'

PLATFORM_MODULES = (
    'engine/task_graph.py', 'engine/agent_registry.py', 'engine/evidence_graph.py',
    'engine/policy_engine.py', 'engine/memory_governance.py', 'engine/tenants.py',
    'engine/reliability.py', 'engine/connector_gateway.py', 'engine/evaluation_harness.py',
    'engine/artifact_factory.py', 'engine/approval_receipt.py',
)
PLATFORM_TESTS = (
    'tests_platform_task_graph.py', 'tests_platform_registry_evidence.py',
    'tests_platform_policy.py', 'tests_platform_memory_tenants.py',
    'tests_platform_eval_artifacts.py', 'tests_platform_reliability_connectors.py',
    'tests_platform_approval_receipt.py', 'tests_platform_integration.py',
)
PLATFORM_DOCS = (
    'docs/PLATAFORMA_CONTRATOS_V1.md', 'docs/PLATAFORMA_DECISIONES.md',
    'docs/PLATAFORMA_REVISION_RV1.md', 'docs/PLATAFORMA_REVISION_RV2.md',
    'docs/PLATAFORMA_APROBACION_V1.md', 'docs/PLATAFORMA_ENTREGA_V9.md',
    'docs/plataforma/taskspec.schema.json', 'docs/plataforma/evidence-node.schema.json',
    'docs/plataforma/policy.schema.json', 'docs/plataforma/policy.v2.schema.json',
    'docs/plataforma/memory-record.schema.json', 'docs/plataforma/tenant-boundary.schema.json',
    'docs/plataforma/receipt-extension.schema.json',
)
PLATFORM_NEW = PLATFORM_MODULES + PLATFORM_TESTS + PLATFORM_DOCS

MANIFEST_LINE = re.compile(r'^([0-9a-f]{64})  (.+)$')
GLOB_CHARS = ('*', '?', '[', ']', '{', '}')
FORBIDDEN_IMPORT_ROOTS = frozenset({'socket', 'ssl', 'urllib', 'http', 'requests', 'httpx',
                                    'ftplib', 'smtplib', 'telnetlib', 'subprocess', 'shutil',
                                    'ctypes', 'multiprocessing', 'asyncio', 'webbrowser'})
ALLOWED_IMPORT_ROOTS = frozenset({'__future__', 'collections', 'dataclasses', 'enum', 'functools',
                                  'hashlib', 'itertools', 'json', 'math', 'pathlib', 're', 'types',
                                  'typing', 'uuid', 'string', 'textwrap', 'decimal', 'datetime',
                                  'copy', 'operator', 'statistics', 'bisect', 'heapq', 'random',
                                  'unicodedata'})
ENGINE_IMPORT_NAMES = frozenset({'task_graph', 'agent_registry', 'evidence_graph', 'policy_engine',
                                 'memory_governance', 'tenants', 'reliability', 'connector_gateway',
                                 'evaluation_harness', 'artifact_factory', 'approval_receipt',
                                 'project_store', 'engine_relative'})
NOT_RUN_ITEMS = ('conectores vivos', '24/7', 'Chromium', 'proveedor real', 'DSH')


def read_text(path):
    """Lectura fiel a los bytes: sin traduccion de saltos de linea ni encoding implicito."""
    return Path(path).read_bytes().decode('utf-8')


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def manifest_entries():
    """Entradas del manifiesto con el MISMO formato que exige engine/bundle.py (654)."""
    entries = []
    for line in read_text(MANIFEST_PATH).splitlines():
        match = MANIFEST_LINE.match(line)
        if match:
            entries.append((match.group(1), match.group(2)))
    return entries


def export_paths_on_disk():
    """Rutas de exportacion reales del directorio (recipe, backup, council, manifest)."""
    root_names = sorted(p.name for p in SUITE_ROOT.glob('agent-team-*.json'))
    implementation = [name for name in root_names if name.startswith('agent-team-recipe-')]
    definitions = [name for name in root_names if name.startswith('agent-team-backup-')]
    council = sorted(p.name for p in (SUITE_ROOT / 'extras').glob('agent-team-recipe-*.json'))
    assert len(implementation) == 1 and len(definitions) == 1 and len(council) == 1, (
        'se esperaba exactamente una recipe de implementacion, un backup y una recipe de Council')
    return {'implementation.json': implementation[0], 'definitions.json': definitions[0],
            'council.json': 'extras/' + council[0],
            'export-manifest.json': 'agent-team-export-manifest.json'}


def expected_package_paths():
    org = json.loads(read_text(SUITE_ROOT / 'organizacion' / 'ORGANIZACION.json'))
    return bundle._expected_package_paths(org, export_paths_on_disk())


def acta_lines(prefix):
    """Lineas maquina-legibles del acta que empiezan por el prefijo dado."""
    return [line.split(' ', 1)[1].strip() for line in read_text(ACTA_PATH).splitlines()
            if line.startswith(prefix + ' ')]


class MiniSchemaValidator:
    """Validador del subconjunto de JSON Schema que usan los contratos de plataforma.

    Implementacion independiente del motor y de cualquier libreria: se usa para decidir si un
    documento (una decision de politica) conforma el esquema. Palabras clave soportadas:
    $ref local, type, const, enum, properties, additionalProperties, propertyNames, required,
    minLength, maxLength, pattern, minimum, maximum, minItems, maxItems, uniqueItems, items,
    allOf, anyOf, oneOf, not, if/then/else. Las palabras clave de anotacion se ignoran.
    """

    _MISSING = object()

    def __init__(self, document):
        self.root = document

    def resolve(self, ref):
        if not ref.startswith('#'):
            raise ValueError('solo se admiten referencias locales: %s' % ref)
        node = self.root
        pointer = ref[1:]
        if pointer in ('', '/'):
            return node
        for part in pointer.lstrip('/').split('/'):
            part = part.replace('~1', '/').replace('~0', '~')
            if not isinstance(node, dict) or part not in node:
                raise ValueError('referencia no resoluble: %s' % ref)
            node = node[part]
        return node

    def unresolved_refs(self, schema=_MISSING):
        """Todas las referencias locales deben resolverse: un $ref roto no valida nada."""
        schema = self.root if schema is MiniSchemaValidator._MISSING else schema
        broken = []
        if isinstance(schema, dict):
            if '$ref' in schema:
                try:
                    self.resolve(schema['$ref'])
                except ValueError as exc:
                    broken.append(str(exc))
            for value in schema.values():
                broken.extend(self.unresolved_refs(value))
        elif isinstance(schema, list):
            for item in schema:
                broken.extend(self.unresolved_refs(item))
        return broken

    def errors(self, instance, schema=_MISSING, path='$'):
        schema = self.root if schema is MiniSchemaValidator._MISSING else schema
        if schema is True:
            return []
        if schema is False:
            return ['%s: no se admite ningun valor' % path]
        if not isinstance(schema, dict):
            raise ValueError('esquema invalido en %s' % path)
        if '$ref' in schema:
            return self.errors(instance, self.resolve(schema['$ref']), path)
        found = []
        if 'type' in schema:
            types = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
            if not any(self._is_type(instance, name) for name in types):
                return ['%s: tipo distinto de %s' % (path, types)]
        if 'const' in schema and instance != schema['const']:
            found.append('%s: distinto de const %r' % (path, schema['const']))
        if 'enum' in schema and instance not in schema['enum']:
            found.append('%s: fuera de enum' % path)
        if isinstance(instance, str):
            if 'minLength' in schema and len(instance) < schema['minLength']:
                found.append('%s: mas corto que minLength' % path)
            if 'maxLength' in schema and len(instance) > schema['maxLength']:
                found.append('%s: mas largo que maxLength' % path)
            if 'pattern' in schema and not re.search(schema['pattern'], instance):
                found.append('%s: no cumple pattern' % path)
        if isinstance(instance, (int, float)) and not isinstance(instance, bool):
            if 'minimum' in schema and instance < schema['minimum']:
                found.append('%s: menor que minimum' % path)
            if 'maximum' in schema and instance > schema['maximum']:
                found.append('%s: mayor que maximum' % path)
        if isinstance(instance, list):
            if 'minItems' in schema and len(instance) < schema['minItems']:
                found.append('%s: menos elementos que minItems' % path)
            if 'maxItems' in schema and len(instance) > schema['maxItems']:
                found.append('%s: mas elementos que maxItems' % path)
            if schema.get('uniqueItems'):
                rendered = [json.dumps(item, sort_keys=True) for item in instance]
                if len(set(rendered)) != len(rendered):
                    found.append('%s: elementos duplicados con uniqueItems' % path)
            if 'items' in schema:
                for index, item in enumerate(instance):
                    found.extend(self.errors(item, schema['items'], '%s[%d]' % (path, index)))
        if isinstance(instance, dict):
            for name in schema.get('required', []):
                if name not in instance:
                    found.append('%s: falta %s' % (path, name))
            if 'propertyNames' in schema:
                for name in instance:
                    if self.errors(name, schema['propertyNames'], '%s.%s(nombre)' % (path, name)):
                        found.append('%s: nombre de propiedad no admitido: %s' % (path, name))
            properties = schema.get('properties', {})
            for name, value in instance.items():
                if name in properties:
                    found.extend(self.errors(value, properties[name], '%s.%s' % (path, name)))
                else:
                    extra = schema.get('additionalProperties', True)
                    if extra is False:
                        found.append('%s: propiedad no admitida: %s' % (path, name))
                    elif isinstance(extra, dict):
                        found.extend(self.errors(value, extra, '%s.%s' % (path, name)))
        if 'not' in schema and not self.errors(instance, schema['not'], path):
            found.append('%s: satisface un esquema prohibido (not)' % path)
        if 'allOf' in schema:
            for sub in schema['allOf']:
                found.extend(self.errors(instance, sub, path))
        if 'anyOf' in schema and not any(not self.errors(instance, sub, path) for sub in schema['anyOf']):
            found.append('%s: no satisface ninguna rama anyOf' % path)
        if 'oneOf' in schema:
            hits = sum(1 for sub in schema['oneOf'] if not self.errors(instance, sub, path))
            if hits != 1:
                found.append('%s: satisface %d ramas oneOf (se exige exactamente una)' % (path, hits))
        if 'if' in schema:
            if not self.errors(instance, schema['if'], path):
                found.extend(self.errors(instance, schema.get('then', {}), path))
            else:
                found.extend(self.errors(instance, schema.get('else', {}), path))
        return found

    @staticmethod
    def _is_type(instance, name):
        if name == 'object':
            return isinstance(instance, dict)
        if name == 'array':
            return isinstance(instance, list)
        if name == 'string':
            return isinstance(instance, str)
        if name == 'boolean':
            return isinstance(instance, bool)
        if name == 'integer':
            return isinstance(instance, int) and not isinstance(instance, bool)
        if name == 'number':
            return isinstance(instance, (int, float)) and not isinstance(instance, bool)
        if name == 'null':
            return instance is None
        raise ValueError('tipo no soportado: %s' % name)


def action_route_documents():
    """Rutas medidas: una por tipo de accion (con aprobacion si levanta puerta) + las dos sin puerta."""
    policy = policy_suite.make_policy()
    routes = {}
    for kind in pe.ACTION_KINDS:
        action = {'action_kind': kind, 'target': 'objetivo'}
        if policy.gates_for(kind):
            scoped, record = policy_suite.approval_for(policy, action)
            routes['tipo:%s' % kind] = pe.evaluate(policy, scoped, approval=record,
                                                   now=policy_suite.FIXED_INSTANT)
        else:
            routes['tipo:%s' % kind] = pe.evaluate(policy, action, now=policy_suite.FIXED_INSTANT)
    for kind in ('read_repo', 'run_tests'):
        routes['allow_sin_puerta:%s' % kind] = pe.evaluate(
            policy, {'action_kind': kind, 'target': 'src/app.py'}, now=policy_suite.FIXED_INSTANT)
    return routes


def owner_battery_documents():
    """Las 13 rutas etiquetadas del propietario de I3, importadas sin modificarlas."""
    policy = policy_suite.make_policy()
    return dict(policy_suite.decision_battery(policy))


def source_import_roots(path):
    """Raices importadas; las importaciones relativas se etiquetan como 'engine_relative'."""
    tree = ast.parse(read_text(path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and not node.module:
                roots.add('engine_relative')
            else:
                roots.add((node.module or '').split('.')[0])
    return roots


class AllowlistIsLiteralTests(unittest.TestCase):
    """Criterio: la allowlist es una lista literal de nombres exactos, sin globs ni patrones."""

    def literal_allowlist(self):
        tree = ast.parse(read_text(BUNDLE_PATH))
        assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'RUNTIME_ALLOWLIST'
                               for target in node.targets)]
        self.assertEqual(len(assignments), 1, 'RUNTIME_ALLOWLIST debe asignarse una sola vez')
        value = assignments[0].value
        self.assertIsInstance(value, ast.Tuple, 'RUNTIME_ALLOWLIST debe ser una tupla literal')
        names = []
        for element in value.elts:
            self.assertIsInstance(element, ast.Constant,
                                  'cada entrada debe ser un nombre literal, sin concatenacion')
            self.assertIsInstance(element.value, str)
            names.append(element.value)
        return tuple(names)

    def test_allowlist_is_a_single_literal_tuple_without_globs(self):
        names = self.literal_allowlist()
        self.assertEqual(names, bundle.RUNTIME_ALLOWLIST,
                         'la allowlist en disco y la importada deben coincidir')
        offending = sorted(name for name in names if any(char in name for char in GLOB_CHARS))
        self.assertEqual(offending, [])
        self.assertFalse([name for name in names if name.startswith('/') or '..' in name.split('/')])
        for token in ('glob', 'rglob', 'fnmatch', 'Pattern'):
            self.assertNotIn(token, read_text(BUNDLE_PATH).split('RUNTIME_ALLOWLIST')[1][:60])

    def test_allowlist_has_no_duplicates_and_every_entry_exists(self):
        names = self.literal_allowlist()
        self.assertEqual(len(names), len(set(names)), 'hay entradas duplicadas')
        missing = sorted(name for name in names if not (SUITE_ROOT / name).is_file())
        self.assertEqual(missing, [], 'toda entrada de la allowlist debe existir (bundle._read_runtime)')

    def test_every_engine_module_in_the_delivery_is_allowlisted(self):
        modules = {'engine/' + path.name for path in (SUITE_ROOT / 'engine').glob('*.py')}
        self.assertEqual(sorted(modules - set(bundle.RUNTIME_ALLOWLIST)), [])
        # 66 -> 70: revision explicita GenTeam P1-P4 (engine/team_channel.py,
        # engine/team_memory.py, engine/sandbox_executor.py, engine/followups.py).
        # 70 -> 72: revision explicita GenTeam M1-M2 (engine/team_process.py,
        # engine/team_loop.py), integrada y sellada en t27.
        self.assertEqual(len(modules), 72, 'el numero de modulos de engine/ cambia sin revision')

    def test_platform_modules_tests_and_documents_are_allowlisted(self):
        allowlist = set(bundle.RUNTIME_ALLOWLIST)
        for group, label in ((PLATFORM_MODULES, 'modulos'), (PLATFORM_TESTS, 'pruebas'),
                             (PLATFORM_DOCS, 'documentos')):
            with self.subTest(grupo=label):
                self.assertEqual(sorted(set(group) - allowlist), [])
                self.assertEqual(len(group), len(set(group)))


class ManifestTests(unittest.TestCase):
    """Criterio: todo lo anadido esta en la allowlist Y en el manifiesto con su hash correcto."""

    def test_manifest_lists_exactly_the_expected_package_paths(self):
        listed = {name for _, name in manifest_entries()}
        expected = expected_package_paths() - {'MANIFIESTO_SHA256.txt'}
        self.assertEqual(sorted(expected - listed), [], 'el manifiesto no cubre todo lo esperado')
        self.assertEqual(sorted(listed - expected), [], 'el manifiesto lista archivos de mas')

    def test_every_manifest_entry_matches_the_file_bytes(self):
        mismatched = sorted(name for digest, name in manifest_entries()
                            if sha256_file(SUITE_ROOT / name) != digest)
        self.assertEqual(mismatched, [])

    def test_manifest_does_not_list_itself_and_uses_the_frozen_format(self):
        entries = manifest_entries()
        names = [name for _, name in entries]
        self.assertNotIn('MANIFIESTO_SHA256.txt', names)
        self.assertEqual(names, sorted(names), 'las entradas deben ir ordenadas por nombre')
        raw = read_text(MANIFEST_PATH)
        self.assertTrue(raw.endswith('\n'))
        self.assertEqual(len([line for line in raw.splitlines() if line]),
                         len([line for line in raw.splitlines() if MANIFEST_LINE.match(line)]),
                         'toda linea del manifiesto debe cumplir "<sha256><dos espacios><ruta>"')

    def test_manifest_covers_every_platform_artifact(self):
        listed = {name for _, name in manifest_entries()}
        self.assertEqual(sorted(set(PLATFORM_NEW) - listed), [])

    def test_published_manifest_hash_is_reconstructible_with_masked_lines(self):
        """La huella publicada se recomputa sobre el manifiesto entregado enmascarando dos lineas.

        El paquete es circular por necesidad: el acta publica una huella del manifiesto, el
        manifiesto cubre el catalogo documental y el catalogo cubre al acta. La huella publicada
        es, por tanto, la del manifiesto con las lineas declaradas enmascaradas con el marcador;
        esas dos son las unicas cuyo digest depende del valor publicado. Aqui se reproduce el
        calculo sobre los bytes entregados.
        """
        acta = read_text(ACTA_PATH)
        published = acta_lines('MANIFIESTO_SHA256_SIN_ESPEJO')
        marker = acta_lines('MANIFIESTO_MARCADOR')
        masked = acta_lines('MANIFIESTO_LINEAS_ENMASCARADAS')
        declared_count = acta_lines('MANIFIESTO_FILE_COUNT')
        self.assertEqual((len(published), len(marker), len(masked), len(declared_count)), (1, 1, 1, 1))
        self.assertEqual(acta.count(published[0]), 1, 'la huella publicada debe aparecer una sola vez')
        masked_names = masked[0].split()
        self.assertEqual(sorted(masked_names), ['03_CATALOGO_DOCUMENTAL.json', ACTA_DOC])
        self.assertEqual(int(declared_count[0]), len(manifest_entries()))
        rebuilt = []
        for digest, name in manifest_entries():
            rebuilt.append('%s  %s\n' % (marker[0] if name in masked_names else digest, name))
        self.assertEqual(sha256_bytes(''.join(rebuilt).encode('utf-8')), published[0])
        # Y las dos lineas enmascaradas son exactamente las que el catalogo necesita para cubrir al acta.
        catalog = json.loads(read_text(SUITE_ROOT / '03_CATALOGO_DOCUMENTAL.json'))
        catalogued = {row['path'] for row in catalog['files']}
        self.assertIn(ACTA_DOC, catalogued)
        self.assertNotIn('03_CATALOGO_DOCUMENTAL.json', catalogued)
        self.assertNotIn('MANIFIESTO_SHA256.txt', catalogued)


class BridgeReadOnlyActionTests(unittest.TestCase):
    """Criterio: la accion nueva es estrictamente de solo lectura y no ejecuta ningun plano."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.state = BridgeState(credential_store=NullStore(),
                                 project_store=ProjectStore(root / 'projects'))

    def watched_state(self):
        watched = [BUNDLE_PATH, BRIDGE_PATH, MANIFEST_PATH, ACTA_PATH, POLICY_V1, POLICY_V2,
                   CONTRATOS_PATH] + [SUITE_ROOT / name for name in PLATFORM_MODULES]
        return {path.relative_to(SUITE_ROOT).as_posix(): sha256_file(path)
                for path in watched if path.is_file()}

    def test_action_is_registered_and_returns_the_declared_payload(self):
        result = self.state.execute('platform-planes-status', {})
        self.assertEqual(result['action'], 'platform-planes-status')
        self.assertEqual([plane['plane'] for plane in result['planes']],
                         ['G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'O1'])
        declared = [item['path'] for plane in result['planes']
                    for item in plane['modules'] + plane['contracts']]
        expected = set(PLATFORM_MODULES) | {
            'docs/plataforma/taskspec.schema.json', 'docs/plataforma/evidence-node.schema.json',
            'docs/plataforma/policy.schema.json', 'docs/plataforma/policy.v2.schema.json',
            'docs/plataforma/memory-record.schema.json', 'docs/plataforma/tenant-boundary.schema.json',
            'docs/plataforma/receipt-extension.schema.json', 'docs/PLATAFORMA_APROBACION_V1.md'}
        self.assertEqual(sorted(set(declared)), sorted(expected))

    def test_action_reports_a_consistent_allowlist_and_manifest(self):
        result = self.state.execute('platform-planes-status', {})['delivery']
        self.assertEqual(result['missing_on_disk'], [])
        self.assertEqual(result['not_in_runtime_allowlist'], [])
        self.assertEqual(result['not_in_manifest'], [])
        self.assertEqual(result['manifest_hash_mismatches'], [])
        self.assertEqual(result['runtime_allowlist_entries'], len(bundle.RUNTIME_ALLOWLIST))
        self.assertEqual(result['manifest_file_count'], len(manifest_entries()))
        self.assertEqual(result['manifest_sha256'], sha256_file(MANIFEST_PATH))

    def test_action_adds_no_receipt_and_does_not_dirty_the_project(self):
        before_receipts = list(self.state.receipts)
        before_project = dict(self.state.project)
        before_organization = self.state.organization
        before_consent = self.state.pending_consent
        self.state.execute('platform-planes-status', {})
        self.assertEqual(self.state.receipts, before_receipts)
        self.assertEqual(self.state.project, before_project)
        self.assertIs(self.state.organization, before_organization)
        self.assertIs(self.state.pending_consent, before_consent)
        self.assertEqual(self.state.project['dirty'], before_project['dirty'])

    def test_action_flags_declare_no_effect(self):
        result = self.state.execute('platform-planes-status', {})
        for flag in ('read_only',):
            self.assertTrue(result[flag])
        for flag in ('executed', 'network_used', 'consent_consumed', 'spend_performed',
                     'planes_executed'):
            self.assertFalse(result[flag])
        self.assertEqual(result['receipts_added'], 0)
        for plane in result['planes']:
            self.assertEqual(plane['declaration'], 'inert_by_default')
            self.assertFalse(plane['runtime_verified'])
            self.assertFalse(plane['executed_by_this_action'])

    def test_action_does_not_touch_the_delivered_artifacts(self):
        before = self.watched_state()
        self.state.execute('platform-planes-status', {})
        self.assertEqual(self.watched_state(), before)

    def test_action_opens_no_socket_and_starts_no_process(self):
        opened = []
        original_socket = socket.socket
        original_create = socket.create_connection

        def forbidden_socket(*args, **kwargs):
            opened.append('socket')
            raise AssertionError('la accion de solo lectura no puede abrir sockets')

        def forbidden_connection(*args, **kwargs):
            opened.append('create_connection')
            raise AssertionError('la accion de solo lectura no puede abrir conexiones')

        socket.socket = forbidden_socket
        socket.create_connection = forbidden_connection
        self.addCleanup(setattr, socket, 'socket', original_socket)
        self.addCleanup(setattr, socket, 'create_connection', original_create)
        result = self.state.execute('platform-planes-status', {})
        self.assertFalse(result['network_used'])
        self.assertEqual(opened, [])

    def test_action_is_deterministic_between_calls(self):
        first = self.state.execute('platform-planes-status', {})
        second = self.state.execute('platform-planes-status', {})
        for payload in (first, second):
            payload.pop('generated_at')
        self.assertEqual(first, second)

    def test_action_branch_is_the_only_new_one_and_imports_no_plane(self):
        text = read_text(BRIDGE_PATH)
        self.assertEqual(text.count("action == 'platform-planes-status'"), 1)
        tree = ast.parse(text)
        handler = next(node for node in ast.walk(tree)
                       if isinstance(node, ast.FunctionDef) and node.name == 'platform_planes_status')
        imported = set()
        for node in ast.walk(handler):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level and not node.module:
                    imported.add('engine_relative')
                else:
                    imported.add((node.module or '').split('.')[0])
        self.assertEqual(sorted(imported), ['bundle', 'engine_relative'],
                         'el handler solo puede apoyarse en engine.bundle para leer la allowlist')
        for token in ('open(', 'write_bytes', 'subprocess', 'os.system', 'eval(', 'exec('):
            with self.subTest(token=token):
                self.assertNotIn(token, ast.unparse(handler))


class ActaAndScopeTests(unittest.TestCase):
    """Criterio: el acta no atribuye ejecucion a los planos y los formatos no cambian de version."""

    def test_acta_declares_the_not_run_items(self):
        acta = read_text(ACTA_PATH)
        lowered = acta.lower()
        self.assertIn('not_run', lowered)
        for item in NOT_RUN_ITEMS:
            with self.subTest(item=item):
                self.assertIn(item.lower(), lowered)

    def test_acta_does_not_attribute_verified_execution_to_the_planes(self):
        acta = read_text(ACTA_PATH)
        self.assertIn('no acredita ejecución', acta.lower())
        forbidden = ('runtime verificado: true', 'ejecutado en produccion', 'conector vivo verificado',
                     'probado contra el proveedor', 'garantiza cero fallos')
        for phrase in forbidden:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, acta.lower())

    def test_acta_modified_set_contains_no_previous_test_file(self):
        modified = acta_lines('MODIFICADO')
        added = acta_lines('NUEVO')
        self.assertTrue(modified and added)
        tests_touched = [path for path in modified + added
                         if Path(path).name.startswith('tests_')
                         and Path(path).name != 'tests_platform_integration.py']
        self.assertEqual(tests_touched, [], 'ninguna prueba previa puede aparecer como tocada')
        for path in modified + added + acta_lines('INTEGRADO'):
            with self.subTest(path=path):
                self.assertTrue((SUITE_ROOT.parent / path).is_file() or (SUITE_ROOT / path).is_file())

    def test_acta_declares_the_full_integration_scope(self):
        modified = {Path(path).name for path in acta_lines('MODIFICADO')}
        added = {Path(path).name for path in acta_lines('NUEVO')}
        integrated = {Path(path).name for path in acta_lines('INTEGRADO')}
        declared = modified | added | integrated
        for name in PLATFORM_NEW:
            with self.subTest(integrado=name):
                self.assertIn(Path(name).name, declared)
        for expected in ('bundle.py', 'MANIFIESTO_SHA256.txt', 'bridge.py',
                         'PLATAFORMA_ENTREGA_V9.md', 'policy.v2.schema.json',
                         'PLATAFORMA_CONTRATOS_V1.md', 'PLATAFORMA_APROBACION_V1.md',
                         'tests_platform_integration.py'):
            with self.subTest(declarado=expected):
                self.assertIn(expected, modified | added)
        frozen = {Path(name).name for name in PLATFORM_MODULES} | {
            'tests_platform_task_graph.py', 'tests_platform_registry_evidence.py',
            'tests_platform_policy.py', 'tests_platform_memory_tenants.py',
            'tests_platform_eval_artifacts.py', 'tests_platform_reliability_connectors.py',
            'tests_platform_approval_receipt.py'}
        self.assertEqual(modified & frozen, set(), 'los planos y sus pruebas no se modifican aqui')

    def test_acta_declares_o9_as_a_current_limitation(self):
        """O-9 declarado como limitacion vigente, sin prometer comprobaciones que el codigo no haga."""
        acta = read_text(ACTA_PATH)
        self.assertTrue(re.search(r'O[\u2011-]9', acta), 'el acta debe nombrar O-9')
        for fragment in ('declaración cruda', 'build_taskspec', 'build_graph', 'compute_graph_sha256',
                         'canonical_task_list', 'limitación'):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, acta)
        lowered = acta.lower()
        self.assertIn('no promete ninguna comprobación', lowered)
        self.assertIn('no se autoriza cambio de código', lowered)

    def test_export_format_versions_are_unchanged(self):
        manifest = json.loads(read_text(SUITE_ROOT / 'agent-team-export-manifest.json'))
        self.assertEqual((manifest['format'], manifest['version']), ('orgdna/export-manifest', 1))
        paths = export_paths_on_disk()
        recipe = json.loads(read_text(SUITE_ROOT / paths['implementation.json']))
        definitions = json.loads(read_text(SUITE_ROOT / paths['definitions.json']))
        council = json.loads(read_text(SUITE_ROOT / paths['council.json']))
        self.assertEqual((recipe['format'], recipe['version']), ('agent-team-gui/recipe', 1))
        self.assertEqual((council['format'], council['version']), ('agent-team-gui/recipe', 1))
        self.assertEqual((definitions['format'], definitions['version']),
                         ('agent-team-gui/definitions', 2))
        artifact_source = read_text(SUITE_ROOT / 'engine' / 'export_artifacts.py')
        self.assertIn("'format': 'orgdna/export-manifest', 'version': 1", artifact_source)
        store_source = read_text(SUITE_ROOT / 'engine' / 'project_store.py')
        self.assertIn("{'format':'orgdna-local-project','version':1,", store_source)


class PolicyV2ClosesFT42Tests(unittest.TestCase):
    """F-T4-2: revision 2 aditiva, mandatory_gates evaluable y rutas conformes."""

    def setUp(self):
        self.v1 = json.loads(read_text(POLICY_V1))
        self.v2 = json.loads(read_text(POLICY_V2))
        self.validator_v1 = MiniSchemaValidator(self.v1)
        self.validator_v2 = MiniSchemaValidator(self.v2)

    def test_v1_bytes_are_untouched_and_still_pinned(self):
        self.assertEqual(sha256_file(POLICY_V1), POLICY_V1_SHA256)
        self.assertEqual(sha256_file(POLICY_V1), policy_suite.FROZEN_SCHEMA_SHA256)

    def test_v2_is_additive_and_declares_its_revision(self):
        self.assertEqual(self.v2['schema_revision'], '2')
        self.assertEqual(self.v2['supersedes']['sha256'], sha256_file(POLICY_V1))
        self.assertEqual(self.v2['version_field'], 'policy_contract_version')
        self.assertEqual(self.v2['properties']['policy_contract_version']['const'],
                         pe.POLICY_CONTRACT_VERSION)
        self.assertEqual(self.v2['payload_version'], pe.POLICY_CONTRACT_VERSION)
        self.assertTrue(self.v2['inert_by_default'])
        self.assertEqual(set(self.v2['prohibited_fields']), set(pe.PROHIBITED_FIELDS))
        self.assertEqual(self.validator_v2.unresolved_refs(), [])

    def test_mandatory_gates_is_a_referenced_machine_checkable_restriction(self):
        gates = self.v2['$defs']['mandatory_gates']
        self.assertEqual(gates['enum'], list(pe.GATES))
        rendered = read_text(POLICY_V2)
        references = rendered.count('"$ref": "#/$defs/mandatory_gates"')
        self.assertGreaterEqual(references, 4,
                                'mandatory_gates debe referenciarse desde gate, allOf y los registros')
        self.assertNotIn('"properties"', json.dumps(gates),
                         'la restriccion ya no es la anotacion v1 con properties/const')
        self.assertEqual(self.v1['$defs']['mandatory_gates']['properties']['gates']['const'],
                         list(pe.GATES))

    def test_action_kind_routes_conform_under_v2_and_fail_under_v1(self):
        routes = action_route_documents()
        by_kind = {label.split(':', 1)[1]: document for label, document in routes.items()
                   if label.startswith('tipo:')}
        self.assertEqual(sorted(by_kind), sorted(pe.ACTION_KINDS))
        self.assertEqual(len(routes), 14, '12 tipos de accion + 2 rutas de allow sin puerta')
        failed_v2 = sorted(label for label, document in routes.items() if self.validator_v2.errors(document))
        failed_v1 = sorted(label for label, document in routes.items() if self.validator_v1.errors(document))
        self.assertEqual(failed_v2, [], 'las 14 rutas (12 tipos + 2 allow sin puerta) deben conformar v2')
        self.assertEqual(failed_v1, ['allow_sin_puerta:read_repo', 'allow_sin_puerta:run_tests',
                                     'tipo:read_repo', 'tipo:run_tests'])
        # Las 2 no conformidades medidas por el propietario de I3, y solo esas 2.
        self.assertEqual(sorted({label.split(':', 1)[1] for label in failed_v1}),
                         ['read_repo', 'run_tests'])

    def test_owner_battery_conforms_under_v2(self):
        battery = owner_battery_documents()
        self.assertEqual(len(battery), 13)
        failed = sorted(label for label, document in battery.items() if self.validator_v2.errors(document))
        self.assertEqual(failed, [])
        failed_v1 = sorted(label for label, document in battery.items()
                           if self.validator_v1.errors(document))
        self.assertEqual(failed_v1, ['accion sin puertas'])

    def test_negative_fixtures_are_rejected_by_v2(self):
        policy = policy_suite.make_policy()
        deploy = {'action_kind': 'deploy', 'target': 'entorno-produccion'}
        scoped, record = policy_suite.approval_for(policy, deploy)
        allowed = pe.evaluate(policy, scoped, approval=record, now=policy_suite.FIXED_INSTANT)
        self.assertEqual(self.validator_v2.errors(allowed), [])
        fixtures = {
            'allow con puerta sin aprobacion': dict(allowed, approval=None),
            'allow con puerta equivocada': dict(allowed, gate='spend'),
            'require sin puerta': dict(pe.evaluate(policy, deploy, now=policy_suite.FIXED_INSTANT),
                                       gate=None),
            'aprobacion sin puerta declarada': dict(allowed, gate=None),
            'puerta fuera de las ocho': dict(allowed, gate='otra'),
            'allow sin puerta con aprobacion': dict(
                pe.evaluate(policy, {'action_kind': 'read_repo', 'target': 'src/app.py'},
                            now=policy_suite.FIXED_INSTANT), approval=record),
            'version de payload distinta': dict(allowed, policy_contract_version='2'),
            'campo de credencial': dict(allowed, api_key='x'),
        }
        for label, document in fixtures.items():
            with self.subTest(caso=label):
                self.assertNotEqual(self.validator_v2.errors(document), [])

    def test_independent_validator_matches_a_third_party_library(self):
        try:
            import jsonschema
        except ImportError:
            raise unittest.SkipTest('jsonschema no esta instalado en este host; se declara como NOT_RUN')
        external_v1 = jsonschema.Draft202012Validator(self.v1)
        external_v2 = jsonschema.Draft202012Validator(self.v2)
        routes = dict(action_route_documents())
        routes.update({'bateria:%s' % label: document for label, document in owner_battery_documents().items()})
        mine_v1 = {label for label, document in routes.items() if self.validator_v1.errors(document)}
        mine_v2 = {label for label, document in routes.items() if self.validator_v2.errors(document)}
        theirs_v1 = {label for label, document in routes.items()
                     if list(external_v1.iter_errors(document))}
        theirs_v2 = {label for label, document in routes.items()
                     if list(external_v2.iter_errors(document))}
        self.assertEqual(mine_v1, theirs_v1)
        self.assertEqual(mine_v2, theirs_v2)
        self.assertEqual(mine_v2, set())

    def test_frozen_consumers_pins_still_hold_without_touching_their_files(self):
        """Los dos consumidores congelados siguen verdes porque v1 no cambia."""
        self.assertEqual(policy_suite.SCHEMA_PATH, POLICY_V1)
        self.assertEqual(policy_suite.FROZEN_SCHEMA_SHA256, sha256_file(POLICY_V1))
        self.assertEqual(self.v1['$defs']['mandatory_gates']['properties']['gates']['const'],
                         list(pe.GATES))
        self.assertEqual(eval_artifacts_suite.POLICY_SCHEMA_PATH, POLICY_V1)
        frozen = json.loads(read_text(eval_artifacts_suite.POLICY_SCHEMA_PATH))
        self.assertEqual(list(eval_artifacts_suite.evaluation_harness.MANDATORY_GATES),
                         frozen['$defs']['mandatory_gates']['properties']['gates']['const'])

    def test_contracts_document_repins_both_policy_rows(self):
        document = read_text(CONTRATOS_PATH)
        self.assertIn(sha256_file(POLICY_V1), document)
        self.assertIn(sha256_file(POLICY_V2), document)
        self.assertIn('policy.v2.schema.json', document)


class PlatformModulesAreInertTests(unittest.TestCase):
    """Criterio transversal: los planos no importan red, procesos ni dependencias externas."""

    def test_modules_import_only_stdlib_and_the_engine(self):
        for name in PLATFORM_MODULES:
            path = SUITE_ROOT / name
            with self.subTest(module=name):
                roots = source_import_roots(path)
                self.assertFalse(roots & FORBIDDEN_IMPORT_ROOTS, roots & FORBIDDEN_IMPORT_ROOTS)
                self.assertEqual(roots - ALLOWED_IMPORT_ROOTS - ENGINE_IMPORT_NAMES, set())

    def test_modules_contain_no_network_or_process_tokens(self):
        for name in PLATFORM_MODULES:
            source = read_text(SUITE_ROOT / name)
            with self.subTest(module=name):
                for token in ('import socket', 'import urllib', 'import requests', 'subprocess.run',
                              'os.system', 'socket.socket'):
                    self.assertNotIn(token, source)


if __name__ == '__main__':
    unittest.main()
