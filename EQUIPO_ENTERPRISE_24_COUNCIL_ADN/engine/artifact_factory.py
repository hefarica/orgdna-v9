"""Artifact Factory (flujo I5) — artefactos LOCALES firmados con SHA-256 y su recibo.

Contrato consumido: `docs/plataforma/receipt-extension.schema.json` (ReceiptExtension v1,
congelado en R0): `receipt_version` = "1", los 9 campos requeridos, el enum de `produced_by`,
los codigos de `$defs.extension_rules.error_codes` y la composicion aditiva congelada
`recibo_compuesto = recibo_base UNION extension`, con claves disjuntas: la fabrica **no
redefine** ninguna de las 11 claves base ni las 3 claves de `usage` de
`engine/generation_pipeline.py:24-57`.

Que produce: informes, patches como TEXTO, tickets, runbooks y bundles. Cada artefacto se
escribe bajo la raiz DECLARADA por el llamador, lleva su `sha256` recomprobado al releerlo y
su recibo de la extension (`artifact` con `path`, `sha256`, `bytes` y `media_type`).

Que NO hace, por diseno (restriccion dura del encargo y `inert_by_default` de R0):

  * no hace push, no abre PR, no hace merge, no despliega y no ejecuta git ni ningun proceso
    externo: el modulo no importa ningun cliente de red y `INERT_FLAGS` lo declara;
  * no aplica los patches que escribe: son texto declarado (`applies_patches = False`);
  * no escribe fuera de la raiz declarada ni sobre los directorios fuente de la suite
    (`PROTECTED_DIRECTORIES`), y rechaza rutas absolutas, `..` y unidad de disco;
  * no persiste ningun ledger (decision A-1 no autorizada): los recibos se devuelven en
    memoria y el bundle es un artefacto local declarado, no un almacen;
  * no consume ni almacena credenciales: el guard de `engine/project_store.py:38-46` se aplica
    al contenido JSON de cada artefacto y un patron estricto rechaza asignaciones con forma de
    credencial en el contenido de texto;
  * no reescribe un artefacto ya entregado: el mismo nombre con otro contenido se rechaza
    (`artifact_already_written`) en lugar de sobrescribirse en silencio.

Solo biblioteca estandar (`collections.abc`, `dataclasses`, `datetime`, `hashlib`, `json`,
`pathlib`, `re`) mas el guard de credenciales de `engine/project_store.py:19`. Python 3.10+.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

try:  # Paquete: mismo patron de importacion local que engine/project_store.py:12-15.
    from .project_store import FORBIDDEN_FIELDS as _PROJECT_STORE_FORBIDDEN_FIELDS
    from .project_store import ProjectStoreError as _ProjectStoreError
    from .project_store import _reject_secret_fields as _project_store_reject_secret_fields
except ImportError:  # Modulo suelto en sys.path.
    from project_store import FORBIDDEN_FIELDS as _PROJECT_STORE_FORBIDDEN_FIELDS
    from project_store import ProjectStoreError as _ProjectStoreError
    from project_store import _reject_secret_fields as _project_store_reject_secret_fields

FACTORY_VERSION = '1'
BUNDLE_VERSION = '1'

RECEIPT_VERSION = '1'
RECEIPT_VERSION_FIELD = 'receipt_version'
REQUIRED_RECEIPT_FIELDS = ('receipt_version', 'idempotency_key', 'attempt', 'result_outcome',
                           'retry_class', 'produced_by', 'null_is_not_zero',
                           'side_effects_performed', 'recorded_at')
OPTIONAL_RECEIPT_FIELDS = ('artifact', 'consent_ref')

# Vocabulario del contrato congelado: no se reinterpreta ni se amplia.
PRODUCERS = ('task_graph', 'agent_registry', 'evidence_graph', 'policy_engine', 'memory_governance',
             'tenants', 'evaluation_harness', 'artifact_factory', 'reliability', 'connector_gateway')
RESULT_OUTCOMES = ('completed', 'failed', 'cancelled', 'unknown')
RETRY_CLASSES = ('none', 'rate_limit', 'transient', 'permanent', 'policy', 'budget', 'unknown')

# Claves base del recibo de solicitud (engine/generation_pipeline.py:24-57): la extension no
# puede redefinir ninguna.
BASE_RECEIPT_KEYS = ('index', 'provider', 'model', 'payload_sha256', 'max_output_tokens', 'status',
                     'usage', 'latency_ms', 'http_status', 'error_code', 'response_id_sha256')
BASE_USAGE_KEYS = ('prompt_tokens', 'completion_tokens', 'total_tokens')

ARTIFACT_KINDS = ('report', 'patch', 'ticket', 'runbook', 'bundle')
DEFAULT_MEDIA_TYPES = (('report', 'text/markdown'), ('patch', 'text/x-diff'),
                       ('ticket', 'text/markdown'), ('runbook', 'text/markdown'),
                       ('bundle', 'application/json'))

# Codigos congelados de `$defs.extension_rules.error_codes` (literales) y extension declarada
# de I5 para lo que esa lista no cubre (ruta, hash ausente, reescritura, ledger).
FROZEN_ERROR_CODES = ('base_key_collision', 'unsupported_version', 'unknown_producer',
                      'retry_not_authorized', 'artifact_hash_mismatch', 'null_coerced_to_zero')
EXTENSION_ERROR_CODES = ('artifact_without_hash', 'artifact_missing', 'unsafe_artifact_path',
                         'protected_root', 'artifact_already_written', 'idempotency_conflict',
                         'unknown_artifact_kind', 'missing_required_field', 'invalid_field',
                         'forbidden_field')
FACTORY_ERROR_CODES = FROZEN_ERROR_CODES + EXTENSION_ERROR_CODES

SHA256_PATTERN = re.compile(r'^[0-9a-f]{64}$')
IDEMPOTENCY_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{8,128}$')
TIMESTAMP_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$')
NAME_PATTERN = re.compile(r'^[a-z0-9][a-z0-9._-]{0,79}$')
MEDIA_TYPE_PATTERN = re.compile(r'^[a-z]+/[A-Za-z0-9][A-Za-z0-9.+-]{0,119}$')
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r'(?i)\b(credential|api[_-]?key|access[_-]?token|refresh[_-]?token|bearer[_-]?token|'
    r'client[_-]?secret|private[_-]?key|password|cookie|csrf|authorization)\b\s*[:=]')

SUITE_ROOT = Path(__file__).resolve().parent.parent
# Directorios fuente de la suite sobre los que la fabrica NO escribe: un artefacto no modifica
# el arbol entregado ni sus archivos.
PROTECTED_DIRECTORIES = ('engine', 'web', 'docs', 'prompts', 'organizacion', 'skills', 'workbook',
                         'qa_v3', 'qa_v6', 'qa_v7', 'relanzador_dsh', 'cordis_extension', 'tests')
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024

# Las 13 entradas literales de engine/project_store.py:19, copiadas a un contenedor inmutable.
PROHIBITED_FIELD_NAMES = frozenset(_PROJECT_STORE_FORBIDDEN_FIELDS)
del _PROJECT_STORE_FORBIDDEN_FIELDS

INERT_FLAGS = (
    ('network_allowed', False),
    ('spawns_processes', False),
    ('runs_git', False),
    ('pushes', False),
    ('opens_pull_requests', False),
    ('merges', False),
    ('deploys', False),
    ('sends_to_providers', False),
    ('applies_patches', False),
    ('mutates_production_instruction_files', False),
    ('stores_credentials', False),
    ('persists_a_ledger', False),
    ('writes_to_disk', True),
    ('writes_only_under_declared_root', True),
)

PATCH_NOTE = ('Patch declarado como TEXTO: la fabrica no lo aplica, no ejecuta git y no abre '
              'ninguna propuesta de cambio.')
BUNDLE_NOTE = ('Bundle local declarado con hash por miembro y sello de fabrica; no se envio a '
               'ningun proveedor y no reemplaza ningun formato de exportacion vigente.')
DOCUMENT_FOOTER = ('Documento local de la Artifact Factory (flujo I5); declara lo observado y no '
                   'constituye una garantia.')


class ArtifactFactoryError(ValueError):
    """Error tipado de la fabrica. `code` pertenece a `FACTORY_ERROR_CODES`."""

    code = 'invalid_field'

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.detail = dict(detail or {})


class BaseKeyCollisionError(ArtifactFactoryError):
    """La extension redefine una clave base o una clave de `usage`: prohibido."""
    code = 'base_key_collision'


class UnsupportedVersionError(ArtifactFactoryError):
    """Version del recibo distinta de la congelada: se rechaza, no se interpreta."""
    code = 'unsupported_version'


class UnknownProducerError(ArtifactFactoryError):
    """El productor declarado no pertenece al vocabulario aprobado."""
    code = 'unknown_producer'


class RetryNotAuthorizedError(ArtifactFactoryError):
    """Un intento nuevo de una operacion pagada exige autorizacion nueva, no reintento automatico."""
    code = 'retry_not_authorized'


class ArtifactHashMismatchError(ArtifactFactoryError):
    """El hash recomprobado no coincide con el declarado."""
    code = 'artifact_hash_mismatch'


class NullCoercedToZeroError(ArtifactFactoryError):
    """Un valor desconocido se declara `null`; convertirlo en cero esta prohibido."""
    code = 'null_coerced_to_zero'


class MissingArtifactHashError(ArtifactFactoryError):
    """Un artefacto sin `sha256` no se registra: no hay artefacto sin hash."""
    code = 'artifact_without_hash'


class ArtifactMissingError(ArtifactFactoryError):
    """El artefacto declarado no esta en la ruta declarada."""
    code = 'artifact_missing'


class UnsafeArtifactPathError(ArtifactFactoryError):
    """Ruta absoluta, con `..`, con unidad de disco o fuera de la raiz declarada."""
    code = 'unsafe_artifact_path'


class ProtectedRootError(ArtifactFactoryError):
    """La raiz declarada es un directorio fuente de la suite: la fabrica no escribe ahi."""
    code = 'protected_root'


class ArtifactAlreadyWrittenError(ArtifactFactoryError):
    """El nombre ya existe con otro contenido: un artefacto entregado no se reescribe."""
    code = 'artifact_already_written'


class IdempotencyConflictError(ArtifactFactoryError):
    """La misma `idempotency_key` con otro contenido: no es una repeticion idempotente."""
    code = 'idempotency_conflict'


class UnknownArtifactKindError(ArtifactFactoryError):
    """Tipo de artefacto fuera de `ARTIFACT_KINDS`."""
    code = 'unknown_artifact_kind'


class MissingFieldError(ArtifactFactoryError):
    """Falta un campo requerido del contrato."""
    code = 'missing_required_field'


class InvalidFieldError(ArtifactFactoryError):
    """Forma o tipo invalido para el contrato."""
    code = 'invalid_field'


class ForbiddenFieldError(ArtifactFactoryError):
    """El contenido declara un campo con forma de credencial: no se puede guardar."""
    code = 'forbidden_field'


ERROR_CLASSES = (BaseKeyCollisionError, UnsupportedVersionError, UnknownProducerError,
                 RetryNotAuthorizedError, ArtifactHashMismatchError, NullCoercedToZeroError,
                 MissingArtifactHashError, ArtifactMissingError, UnsafeArtifactPathError,
                 ProtectedRootError, ArtifactAlreadyWrittenError, IdempotencyConflictError,
                 UnknownArtifactKindError, MissingFieldError, InvalidFieldError, ForbiddenFieldError)

CODE_CLASSES = tuple((error_class.code, error_class) for error_class in ERROR_CLASSES)


# --------------------------------------------------------------------------- #
# Utilidades deterministas
# --------------------------------------------------------------------------- #
def canonical_json(value):
    """JSON canonico de R-6: `sort_keys`, separadores compactos, sin escapes ASCII."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


def sha256_hex(data):
    """SHA-256 hexadecimal de bytes o de texto UTF-8."""
    payload = data.encode('utf-8') if isinstance(data, str) else bytes(data)
    return hashlib.sha256(payload).hexdigest()


def utc_now():
    """Instante UTC en el formato congelado de los contratos (reloj por defecto)."""
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def media_type_for(kind):
    """Tipo de medio declarado del artefacto; un tipo desconocido se rechaza."""
    for declared_kind, media_type in DEFAULT_MEDIA_TYPES:
        if declared_kind == kind:
            return media_type
    raise UnknownArtifactKindError('unknown_artifact_kind: "' + str(kind) + '" no pertenece a ' +
                                   ', '.join(ARTIFACT_KINDS) + '.')


def inert_flags():
    """Copia mutable de los indicadores declarados de inercia (para consumo externo)."""
    return dict(INERT_FLAGS)


def _text(value, where, minimum=1, maximum=None):
    if not isinstance(value, str):
        raise InvalidFieldError(where + ': se requiere texto; recibido ' + type(value).__name__ + '.')
    if len(value) < minimum or (maximum is not None and len(value) > maximum):
        raise InvalidFieldError(where + ': longitud fuera del rango declarado.')
    return value


def check_relative_path(path):
    """Ruta relativa obligatoria: sin absoluta, sin `..`, sin unidad de disco, sin barras invertidas."""
    _text(path, 'path', 1, 400)
    if path.startswith('/') or path.startswith('\\'):
        raise UnsafeArtifactPathError('unsafe_artifact_path: "' + path + '" es una ruta absoluta.')
    if '..' in path.split('/') or '\\' in path or ':' in path:
        raise UnsafeArtifactPathError('unsafe_artifact_path: "' + path + '" sale de la raiz '
                                      'declarada o declara una unidad de disco.')
    parts = path.split('/')
    if any(not NAME_PATTERN.match(part) for part in parts):
        raise UnsafeArtifactPathError('unsafe_artifact_path: "' + path + '" no usa el patron '
                                      'declarado ^[a-z0-9][a-z0-9._-]{0,79}$ por segmento.')
    return path


def check_declared_root(root):
    """Raiz declarada admisible: fuera de los directorios fuente de la suite y de la propia raiz."""
    resolved = Path(root).expanduser()
    try:
        resolved = resolved.resolve()
    except OSError as error:
        raise UnsafeArtifactPathError('unsafe_artifact_path: la raiz declarada no se puede '
                                      'resolver (' + type(error).__name__ + ').') from None
    if resolved.exists() and not resolved.is_dir():
        raise UnsafeArtifactPathError('unsafe_artifact_path: la raiz declarada existe y no es un '
                                      'directorio.')
    if resolved == SUITE_ROOT:
        raise ProtectedRootError('protected_root: la raiz declarada es la raiz de la suite; la '
                                 'fabrica escribe en un subdirectorio propio o fuera de ella.')
    if resolved.is_relative_to(SUITE_ROOT):
        parts = resolved.relative_to(SUITE_ROOT).parts
        if parts and parts[0] in PROTECTED_DIRECTORIES:
            raise ProtectedRootError('protected_root: "' + parts[0] + '" es un directorio fuente de '
                                     'la suite; ningun artefacto se escribe ahi.')
    return resolved


def _guard_text_content(value, where):
    """Un contenido de texto con una asignacion con forma de credencial no se guarda."""
    if SECRET_ASSIGNMENT_PATTERN.search(value):
        raise ForbiddenFieldError('forbidden_field: ' + where + ' contiene una asignacion con forma '
                                  'de credencial; no se guarda ni se envia a ningun proveedor.')
    return value


def _guard_json_content(payload, media_type, where):
    """El guard del motor se aplica al contenido JSON: ninguna clave puede ser una credencial."""
    try:
        value = json.loads(payload.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        if media_type == 'application/json':
            raise InvalidFieldError('invalid_field: ' + where + ' declara application/json y su '
                                    'contenido no es JSON valido.') from None
        return payload
    try:
        _project_store_reject_secret_fields(value)
    except _ProjectStoreError as error:
        raise ForbiddenFieldError('forbidden_field: ' + where + ' contiene un campo de credencial '
                                  'que no se puede guardar (' + str(error) + ').') from None
    return payload


# --------------------------------------------------------------------------- #
# Recibo de la extension (Recibo base UNION extension, claves disjuntas)
# --------------------------------------------------------------------------- #
def artifact_ref(path, sha256, nbytes, media_type=None):
    """Referencia de artefacto del contrato. Sin `sha256` no hay referencia: se rechaza."""
    check_relative_path(path)
    if not isinstance(sha256, str) or not SHA256_PATTERN.match(sha256):
        raise MissingArtifactHashError('artifact_without_hash: "' + str(path) + '" no declara un '
                                       'sha256 hexadecimal de 64 caracteres; un artefacto sin hash '
                                       'no se registra.')
    if isinstance(nbytes, bool) or not isinstance(nbytes, int) or nbytes < 0:
        raise InvalidFieldError('bytes: se requiere un entero >= 0; un tamano desconocido se declara '
                                'null, nunca 0.')
    media = media_type if media_type is not None else media_type_for(path.split('/')[0])
    if not MEDIA_TYPE_PATTERN.match(str(media)):
        raise InvalidFieldError('media_type: forma invalida "' + str(media) + '".')
    return {'path': path, 'sha256': sha256, 'bytes': nbytes, 'media_type': media}


def _check_idempotency_key(value):
    if not isinstance(value, str) or not IDEMPOTENCY_PATTERN.match(value):
        raise InvalidFieldError('idempotency_key: se requiere el patron ^[A-Za-z0-9._:-]{8,128}$.')
    return value


def _check_attempt(attempt, authorized_retry):
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 16:
        raise InvalidFieldError('attempt: se requiere un entero entre 1 y 16.')
    if attempt > 1 and authorized_retry is not True:
        raise RetryNotAuthorizedError('retry_not_authorized: el intento ' + str(attempt) + ' exige '
                                      'autorizacion nueva; la fabrica no reintenta sola una '
                                      'operacion pagada.')
    return attempt


def _check_consent_ref(consent_ref):
    if consent_ref is None:
        return None
    if isinstance(consent_ref, bool) or not isinstance(consent_ref, str) or \
            not SHA256_PATTERN.match(consent_ref):
        raise NullCoercedToZeroError('null_coerced_to_zero: consent_ref es el sha256 del '
                                     'consentimiento o null; un valor vacio no se aproxima a cero.')
    return consent_ref


def build_receipt(*, idempotency_key, attempt=1, result_outcome='completed', retry_class='none',
                  produced_by='artifact_factory', artifact=None, consent_ref=None,
                  recorded_at=None, authorized_retry=False, receipt_version=RECEIPT_VERSION):
    """Construye y valida el recibo de la extension. Emitirlo no ejecuta la operacion."""
    if receipt_version != RECEIPT_VERSION:
        raise UnsupportedVersionError('unsupported_version: la version del recibo es "' +
                                      str(receipt_version) + '"; el contrato vigente es "' +
                                      RECEIPT_VERSION + '".')
    if produced_by not in PRODUCERS:
        raise UnknownProducerError('unknown_producer: "' + str(produced_by) + '" no pertenece a los '
                                   'productores declarados del contrato.')
    if result_outcome not in RESULT_OUTCOMES:
        raise InvalidFieldError('result_outcome: se requiere uno de ' + ', '.join(RESULT_OUTCOMES) + '.')
    if retry_class not in RETRY_CLASSES:
        raise InvalidFieldError('retry_class: se requiere uno de ' + ', '.join(RETRY_CLASSES) + '.')
    timestamp = recorded_at if recorded_at is not None else utc_now()
    if not isinstance(timestamp, str) or not TIMESTAMP_PATTERN.match(timestamp):
        raise InvalidFieldError('recorded_at: se requiere un instante ISO-8601 UTC con sufijo Z.')
    if artifact is not None:
        if not isinstance(artifact, Mapping):
            raise InvalidFieldError('artifact: se requiere una referencia de artefacto o null.')
        artifact = artifact_ref(artifact.get('path'), artifact.get('sha256'), artifact.get('bytes'),
                                artifact.get('media_type'))
    receipt = {'receipt_version': RECEIPT_VERSION,
               'idempotency_key': _check_idempotency_key(idempotency_key),
               'attempt': _check_attempt(attempt, authorized_retry),
               'result_outcome': result_outcome, 'retry_class': retry_class,
               'produced_by': produced_by, 'artifact': artifact,
               'consent_ref': _check_consent_ref(consent_ref), 'null_is_not_zero': True,
               'side_effects_performed': False, 'recorded_at': timestamp}
    return validate_receipt_or_raise(receipt)


def validate_receipt(receipt):
    """Informe de validacion del recibo (no lanza): `valid`, `code`, `message` y detalle."""
    report = {'valid': False, 'code': None, 'message': '', 'collisions': (),
              'missing_required_fields': (), 'unknown_keys': ()}
    if not isinstance(receipt, Mapping):
        report.update(code='invalid_field', message='El recibo debe ser un objeto.')
        return report
    collisions = tuple(sorted(set(receipt) & (set(BASE_RECEIPT_KEYS) | set(BASE_USAGE_KEYS))))
    unknown = tuple(sorted(set(receipt) - set(REQUIRED_RECEIPT_FIELDS) - set(OPTIONAL_RECEIPT_FIELDS)))
    missing = tuple(name for name in REQUIRED_RECEIPT_FIELDS if name not in receipt)
    report.update(collisions=collisions, missing_required_fields=missing, unknown_keys=unknown)
    if collisions:
        report.update(code='base_key_collision', message='La extension redefine claves base: ' +
                                                         ', '.join(collisions) + '.')
        return report
    if receipt.get(RECEIPT_VERSION_FIELD) != RECEIPT_VERSION:
        report.update(code='unsupported_version', message='Version de recibo no soportada.')
        return report
    if missing:
        report.update(code='missing_required_field', message='Faltan campos requeridos: ' +
                                                             ', '.join(missing) + '.')
        return report
    if unknown:
        report.update(code='invalid_field', message='El recibo declara claves fuera del contrato: ' +
                                                    ', '.join(unknown) + '.')
        return report
    if receipt.get('produced_by') not in PRODUCERS:
        report.update(code='unknown_producer', message='Productor no declarado.')
        return report
    if receipt.get('result_outcome') not in RESULT_OUTCOMES or \
            receipt.get('retry_class') not in RETRY_CLASSES:
        report.update(code='invalid_field', message='result_outcome o retry_class fuera del enum.')
        return report
    attempt = receipt.get('attempt')
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 16:
        report.update(code='invalid_field', message='attempt debe ser un entero entre 1 y 16.')
        return report
    if receipt.get('null_is_not_zero') is not True or receipt.get('side_effects_performed') is not False:
        report.update(code='invalid_field', message='Las invariantes del contrato no se cumplen.')
        return report
    timestamp = receipt.get('recorded_at')
    if not isinstance(timestamp, str) or not TIMESTAMP_PATTERN.match(timestamp):
        report.update(code='invalid_field', message='recorded_at debe ser un instante ISO-8601 Z.')
        return report
    if 'consent_ref' in receipt and receipt['consent_ref'] is not None:
        value = receipt['consent_ref']
        if isinstance(value, bool) or not isinstance(value, str) or not SHA256_PATTERN.match(value):
            report.update(code='null_coerced_to_zero', message='consent_ref debe ser sha256 o null.')
            return report
    if 'artifact' in receipt and receipt['artifact'] is not None:
        artifact = receipt['artifact']
        if not isinstance(artifact, Mapping) or not SHA256_PATTERN.match(str(artifact.get('sha256'))):
            report.update(code='artifact_without_hash', message='El artefacto no declara sha256.')
            return report
        try:
            artifact_ref(artifact.get('path'), artifact.get('sha256'), artifact.get('bytes'),
                         artifact.get('media_type'))
        except ArtifactFactoryError as error:
            report.update(code=error.code, message=str(error))
            return report
    report.update(valid=True, code=None, message='')
    return report


def validate_receipt_or_raise(receipt):
    """Devuelve el recibo si valida; si no, lanza el error tipado de su codigo."""
    report = validate_receipt(receipt)
    if report['valid']:
        return receipt
    for code, error_class in CODE_CLASSES:
        if code == report['code']:
            raise error_class(report['message'])
    raise InvalidFieldError(report['message'] or 'Recibo invalido.')


# --------------------------------------------------------------------------- #
# Documentos declarativos (texto puro, sin efectos)
# --------------------------------------------------------------------------- #
def _numbered(items, empty_note):
    lines = []
    for index, item in enumerate(items, 1):
        lines.append(str(index) + '. ' + _text(str(item), 'documento', 1, 2000))
    return lines or ['0. ' + empty_note]


def report_document(title, findings, *, audience='operador'):
    """Informe markdown declarativo con hallazgos numerados."""
    lines = ['# Informe: ' + _text(title, 'title', 1, 200), '', '## Destinatario', '',
             'Rol declarado: ' + _text(audience, 'audience', 1, 120), '', '## Hallazgos', '']
    lines.extend(_numbered(findings, 'Sin hallazgos declarados.'))
    lines.extend(['', '## Estado', '', DOCUMENT_FOOTER, ''])
    return '\n'.join(lines)


def patch_document(changes, *, note=None):
    """Patch como TEXTO (diff unificado simplificado). No se aplica y no ejecuta git."""
    lines = ['# Patch declarativo', '', PATCH_NOTE, '']
    if note is not None:
        lines.extend(['Nota: ' + _text(note, 'note', 1, 600), ''])
    found = False
    for change in changes:
        if not isinstance(change, Mapping):
            raise InvalidFieldError('patch: cada cambio requiere {file, before, after}.')
        found = True
        target = _text(str(change.get('file', '')), 'patch.file', 1, 300)
        lines.extend(['--- a/' + target, '+++ b/' + target])
        for line in str(change.get('before', '')).splitlines() or ['']:
            lines.append('-' + line)
        for line in str(change.get('after', '')).splitlines() or ['']:
            lines.append('+' + line)
        lines.append('')
    if not found:
        lines.extend(['Sin cambios declarados.', ''])
    lines.extend([DOCUMENT_FOOTER, ''])
    return '\n'.join(lines)


def ticket_document(ticket_id, summary, steps, *, severity='medium', owner_role='operador'):
    """Ticket markdown declarativo con pasos, severidad y responsable declarado."""
    lines = ['# Ticket ' + _text(ticket_id, 'ticket_id', 1, 60), '', '## Resumen', '',
             _text(summary, 'summary', 1, 600), '', '## Severidad', '',
             'Severidad declarada: ' + _text(severity, 'severity', 1, 40), '',
             'Responsable declarado: ' + _text(owner_role, 'owner_role', 1, 120), '',
             '## Pasos', '']
    lines.extend(_numbered(steps, 'Sin pasos declarados.'))
    lines.extend(['', DOCUMENT_FOOTER, ''])
    return '\n'.join(lines)


def runbook_document(title, steps, *, stop_conditions=(), rollback='reversion declarada'):
    """Runbook markdown declarativo con pasos, condiciones de parada y reversion."""
    lines = ['# Runbook: ' + _text(title, 'title', 1, 200), '', '## Pasos', '']
    lines.extend(_numbered(steps, 'Sin pasos declarados.'))
    lines.extend(['', '## Condiciones de parada', ''])
    lines.extend(_numbered(stop_conditions, 'Sin condiciones de parada declaradas.'))
    lines.extend(['', '## Reversion', '', _text(rollback, 'rollback', 1, 600), '',
                  DOCUMENT_FOOTER, ''])
    return '\n'.join(lines)


# --------------------------------------------------------------------------- #
# Fabrica
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ArtifactRecord:
    """Artefacto escrito: ruta relativa, hash, tamano y recibo de la extension."""
    kind: str
    path: str
    sha256: str
    bytes: int
    media_type: str
    receipt: Mapping
    created: bool

    def to_dict(self):
        return json.loads(canonical_json({'kind': self.kind, 'path': self.path,
                                          'sha256': self.sha256, 'bytes': self.bytes,
                                          'media_type': self.media_type, 'created': self.created,
                                          'receipt': self.receipt}))


class ArtifactFactory:
    """Fabrica local de artefactos bajo una raiz declarada. No envia, no publica y no despliega.

    `root` es la unica ruta donde se escribe; `clock` permite fijar `recorded_at` para pruebas
    deterministas. Los recibos viven en memoria (la persistencia de un ledger no esta autorizada:
    decision A-1) y el bundle es un artefacto local declarado.
    """

    def __init__(self, root, *, producer='artifact_factory', clock=None):
        if producer not in PRODUCERS:
            raise UnknownProducerError('unknown_producer: "' + str(producer) + '" no pertenece a los '
                                       'productores declarados del contrato.')
        self._root = check_declared_root(root)
        self._producer = producer
        self._clock = clock if clock is not None else utc_now
        self._records = []
        self._by_key = {}

    @property
    def root(self):
        return self._root

    @property
    def producer(self):
        return self._producer

    def _absolute(self, relative):
        """Ruta absoluta verificada dentro de la raiz declarada, sin enlaces intermedios."""
        check_relative_path(relative)
        target = (self._root / relative).resolve()
        if not target.is_relative_to(self._root):
            raise UnsafeArtifactPathError('unsafe_artifact_path: "' + relative + '" resuelve fuera de '
                                          'la raiz declarada.')
        current = self._root / relative
        while current != self._root:
            if current.is_symlink():
                raise UnsafeArtifactPathError('unsafe_artifact_path: "' + relative + '" atraviesa un '
                                              'enlace simbolico; la fabrica no lo sigue.')
            if current.parent == current:
                raise UnsafeArtifactPathError('unsafe_artifact_path: ruta no valida.')
            current = current.parent
        return target

    def _encode(self, content, where):
        if isinstance(content, str):
            payload = content.encode('utf-8')
            _guard_text_content(content, where)
        elif isinstance(content, (bytes, bytearray)):
            payload = bytes(content)
        else:
            raise InvalidFieldError(where + ': se requiere texto o bytes; recibido ' +
                                    type(content).__name__ + '.')
        if not payload:
            raise InvalidFieldError(where + ': un artefacto vacio no se escribe.')
        if len(payload) > MAX_ARTIFACT_BYTES:
            raise InvalidFieldError(where + ': el artefacto supera el limite declarado de ' +
                                    str(MAX_ARTIFACT_BYTES) + ' bytes.')
        return payload

    def write(self, kind, name, content, *, idempotency_key=None, attempt=1,
              result_outcome='completed', retry_class='none', consent_ref=None,
              authorized_retry=False, media_type=None, recorded_at=None):
        """Escribe un artefacto y devuelve su registro con hash y recibo.

        Repetir la misma `idempotency_key` con el mismo contenido devuelve el mismo registro y no
        duplica el efecto; con otro contenido se rechaza (`idempotency_conflict`).
        """
        media = media_type if media_type is not None else media_type_for(kind)
        if kind not in ARTIFACT_KINDS:
            raise UnknownArtifactKindError('unknown_artifact_kind: "' + str(kind) + '" no pertenece a ' +
                                           ', '.join(ARTIFACT_KINDS) + '.')
        _text(name, 'name', 1, 80)
        if '/' in name:
            raise UnsafeArtifactPathError('unsafe_artifact_path: el nombre "' + name + '" declara una '
                                          'subruta; el artefacto vive en <tipo>/<nombre>.')
        relative = check_relative_path(kind + '/' + name)
        payload = self._encode(content, 'artefacto ' + relative)
        _guard_json_content(payload, media, 'artefacto ' + relative)
        digest = hashlib.sha256(payload).hexdigest()
        key = _check_idempotency_key(idempotency_key) if idempotency_key is not None else \
            'artifact-' + kind + '-' + digest[:32]
        previous = self._by_key.get(key)
        if previous is not None:
            if previous.sha256 != digest:
                raise IdempotencyConflictError('idempotency_conflict: la clave "' + key + '" ya se uso '
                                               'con otro contenido; no se reescribe.')
            return self._record(previous.kind, previous.path, previous.sha256, previous.bytes,
                                previous.media_type, previous.receipt, False)
        target = self._absolute(relative)
        created = True
        if target.exists():
            if target.read_bytes() != payload:
                raise ArtifactAlreadyWrittenError('artifact_already_written: "' + relative + '" ya '
                                                  'existe con otro contenido; un artefacto entregado '
                                                  'no se reescribe.')
            created = False
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        receipt = build_receipt(idempotency_key=key, attempt=attempt, result_outcome=result_outcome,
                                retry_class=retry_class, produced_by=self._producer,
                                artifact=artifact_ref(relative, digest, len(payload), media),
                                consent_ref=consent_ref,
                                recorded_at=recorded_at if recorded_at is not None else self._clock(),
                                authorized_retry=authorized_retry)
        record = self._record(kind, relative, digest, len(payload), media, receipt, created)
        self._records.append(record)
        self._by_key[key] = record
        return record

    def _record(self, kind, path, digest, nbytes, media, receipt, created):
        return ArtifactRecord(kind=kind, path=path, sha256=digest, bytes=nbytes, media_type=media,
                              receipt=receipt, created=created)

    def write_report(self, name, title, findings, **options):
        return self.write('report', name, report_document(title, findings,
                                                          audience=options.pop('audience', 'operador')),
                          **options)

    def write_patch(self, name, changes, **options):
        return self.write('patch', name, patch_document(changes, note=options.pop('note', None)),
                          **options)

    def write_ticket(self, name, ticket_id, summary, steps, **options):
        return self.write('ticket', name, ticket_document(ticket_id, summary, steps,
                                                          severity=options.pop('severity', 'medium'),
                                                          owner_role=options.pop('owner_role',
                                                                                 'operador')),
                          **options)

    def write_runbook(self, name, title, steps, **options):
        return self.write('runbook', name, runbook_document(title, steps,
                                                            stop_conditions=options.pop('stop_conditions', ()),
                                                            rollback=options.pop('rollback',
                                                                                 'reversion declarada')),
                          **options)

    def read_bytes(self, record):
        """Relee y recomprueba el hash antes de devolver los bytes."""
        target = self._absolute(record.path)
        if not target.is_file():
            raise ArtifactMissingError('artifact_missing: "' + record.path + '" no esta en la raiz '
                                       'declarada.')
        payload = target.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != record.sha256:
            raise ArtifactHashMismatchError('artifact_hash_mismatch: "' + record.path + '" no coincide '
                                            'con el hash declarado.')
        return payload

    def read_text(self, record):
        """Relee el artefacto de texto recomprobando su hash."""
        return self.read_bytes(record).decode('utf-8')

    def verify(self, record):
        """Informe de verificacion sin excepcion: hash recomprobado y tamano observado."""
        target = self._absolute(record.path)
        if not target.is_file():
            return {'valid': False, 'code': 'artifact_missing', 'path': record.path,
                    'declared_sha256': record.sha256, 'observed_sha256': None,
                    'declared_bytes': record.bytes, 'observed_bytes': None}
        payload = target.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        valid = digest == record.sha256
        return {'valid': valid, 'code': None if valid else 'artifact_hash_mismatch',
                'path': record.path, 'declared_sha256': record.sha256, 'observed_sha256': digest,
                'declared_bytes': record.bytes, 'observed_bytes': len(payload)}

    def write_bundle(self, name, records, **options):
        """Escribe el bundle: manifiesto local con el hash y el recibo de cada miembro."""
        entries = []
        for record in records:
            if not isinstance(record, ArtifactRecord):
                raise InvalidFieldError('bundle: cada miembro debe ser un ArtifactRecord.')
            entries.append({'kind': record.kind, 'path': record.path, 'sha256': record.sha256,
                            'bytes': record.bytes, 'media_type': record.media_type,
                            'receipt': record.receipt})
        if not entries:
            raise InvalidFieldError('bundle: un bundle sin miembros no declara nada verificable.')
        members = tuple(entries)
        document = {'bundle_version': BUNDLE_VERSION, 'factory_version': FACTORY_VERSION,
                    'bundle_name': _text(name, 'name', 1, 80),
                    'created_at': options.get('recorded_at') or self._clock(),
                    'member_count': len(members), 'members': [dict(member) for member in members],
                    'factory_seal': sha256_hex(canonical_json(members)),
                    'seal_rule': 'SHA-256 sobre JSON canonico de members',
                    'side_effects_performed': False, 'note': BUNDLE_NOTE}
        return self.write('bundle', name + '.json', canonical_json(document), **options)

    def verify_bundle(self, record):
        """Recomprueba el sello del bundle y el hash de cada miembro contra el disco."""
        document = json.loads(self.read_text(record))
        members = document.get('members')
        listed = members if isinstance(members, list) else []
        seal_ok = sha256_hex(canonical_json(tuple(listed))) == document.get('factory_seal') and bool(listed)
        checked = []
        for member in listed:
            entry = {'path': member.get('path'), 'declared_sha256': member.get('sha256')}
            try:
                target = self._absolute(str(member.get('path')))
                payload = target.read_bytes() if target.is_file() else None
                entry['observed_sha256'] = None if payload is None else hashlib.sha256(payload).hexdigest()
                entry['valid'] = entry['observed_sha256'] == member.get('sha256')
                entry['code'] = None if entry['valid'] else (
                    'artifact_missing' if payload is None else 'artifact_hash_mismatch')
            except ArtifactFactoryError as error:
                entry.update(observed_sha256=None, valid=False, code=error.code)
            checked.append(entry)
        valid = bool(seal_ok) and all(entry['valid'] for entry in checked)
        failing = next((entry['code'] for entry in checked if not entry['valid']), None)
        return {'valid': valid, 'code': None if valid else (failing or 'artifact_hash_mismatch'),
                'bundle_version': document.get('bundle_version'), 'seal_valid': bool(seal_ok),
                'member_count': len(checked), 'members': checked}

    def list_records(self):
        """Registros escritos por esta fabrica, en orden de escritura (memoria, no ledger)."""
        return tuple(self._records)
