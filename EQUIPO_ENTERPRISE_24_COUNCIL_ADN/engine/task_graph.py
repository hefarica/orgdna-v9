"""Task Graph Engine (flujo I1) — declarativo, inerte y local.

Contrato consumido: `docs/plataforma/taskspec.schema.json` (TaskSpec v1 / TaskGraph v1,
congelado en R0; `version_field` = `taskspec_version` = "1"; reglas en `$defs.graph_rules`).

Que hace este modulo: construir y validar declaraciones de tareas (`TaskSpec`) y su DAG
(`TaskGraph`): version del contrato, identificadores, dependencias, ciclos, orden
topologico determinista, autonomia declarada por tarea, presupuesto por tarea,
criterios de aceptacion, falsificadores, `idempotency_key` y hash SHA-256 determinista.

Que NO hace, por diseno y por contrato (`inert_by_default` del congelamiento R0):

  * no ejecuta, no programa ni despacha ninguna tarea, y no escribe ningun artefacto;
  * no concede permisos ni eleva autonomia: `autonomy_level` es un TECHO declarado, y un
    nivel con capacidad de escritura (`prepare`, `execute-approved`) exige el flag
    explicito `approved=True` en la construccion; sin el, la tarea no se construye;
  * no instala nada, no consume credenciales y no llama a ningun proveedor;
  * no abre red ni ficheros: todas las funciones son puras sobre sus argumentos y no
    mutan estado global (el modulo no define ningun contenedor mutable de nivel de
    modulo: constantes, tuplas, frozensets, patrones compilados y clases).

Solo biblioteca estandar (`collections.abc`, `dataclasses`, `hashlib`, `json`, `math`,
`re`) mas el guard de credenciales de `engine/project_store.py:19`. Python 3.10+.

Dominio de entrada admitido (declarado, no supuesto):

  * una **declaracion JSON**: un `Mapping` coherente, como el que produce `json.loads`
    —`__contains__`, `get` y la iteracion de claves describen el mismo contenido—, con
    valores de tipos JSON y sin ciclos de referencias;
  * o un `TaskSpec` ya construido, aceptado por `build_graph`, `canonical_task_list`,
    `compute_graph_sha256` y `duplicate_idempotency_keys`;
  * cualquier otra cosa (un `str`, un numero, un `None`, una lista de elementos que no son
    `TaskSpec` ni `Mapping`) se rechaza con `InvalidFieldError`, y una clave obligatoria
    ausente produce `MissingFieldError`; dentro del dominio admitido nunca se propaga
    `AttributeError` ni `KeyError`, porque la presencia se decide con el valor leido.
  * profundidad maxima de contenedores anidados recorridos: `MAX_DECLARATION_DEPTH`. Un
    documento mas profundo, o una estructura de Python con referencias circulares, se
    rechaza con `InvalidFieldError` (no con `RecursionError`). Las estructuras del contrato
    v1 tienen 3 niveles como maximo, asi que el tope no restringe el contrato: el propio
    `json.loads` aplica un limite equivalente.
  * todas las lecturas usan el centinela `_MISSING` (`data.get(name, _MISSING)`) y deciden
    con el valor leido, de modo que la ausencia de clave no depende de un `in` que pueda
    contradecir a `get`.

Decisiones de consumo del contrato congelado, declaradas para auditoria:

  * `DEFAULTED_REQUIRED_FIELDS` = `('autonomy_level',)`: el contrato declara ese campo en
    `required` y ademas `default: "observe"`; el campo ausente aplica el default del
    contrato (no es una adivinanza) y cualquier otro campo obligatorio ausente falla con
    `MissingFieldError`. Un `null` explicito no aplica el default: se rechaza.
  * `autonomy_approved` es procedencia de construccion, no parte de la declaracion: el
    contrato v1 es `additionalProperties: false` y no lo admite, asi que no se serializa
    ni entra en el hash. `TaskSpec.__post_init__` lo verifica en TODA ruta de
    construccion, por lo que ninguna ruta (incluido `dataclasses.replace`) puede elevar
    el nivel sin el flag.
  * `GRAPH_ERROR_CODES` es el vocabulario congelado de `$defs.graph_rules.error_codes` y
    es el vocabulario del validador de grafo: todo rechazo estructural del grafo usa uno
    de esos diez codigos. `FIELD_ERROR_CODES` documenta la extension de I1 para errores
    de campo (campo obligatorio ausente, forma invalida, nombre con forma de credencial y
    falta de aprobacion), que la lista congelada no cubre porque no es estructural.
  * El hash es el de `$defs.graph_rules.hash_rule`: SHA-256 sobre JSON canonico
    (`sort_keys=True`, `separators=(',',':')`, `ensure_ascii=False`) de la lista de
    TaskSpec ya ordenada topologicamente. El envoltorio del grafo (`policy_ref`,
    `created_at` del grafo) es metadato y no entra en el hash.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import math
import re

try:  # Paquete: mismo patron de importacion local que engine/project_store.py:12-15.
    from .project_store import FORBIDDEN_FIELDS as _PROJECT_STORE_FORBIDDEN_FIELDS
except ImportError:  # Modulo suelto en sys.path.
    from project_store import FORBIDDEN_FIELDS as _PROJECT_STORE_FORBIDDEN_FIELDS

TASKSPEC_VERSION = '1'
GRAPH_VERSION = '1'

AUTONOMY_LEVELS = ('observe', 'propose', 'prepare', 'execute-approved')
DEFAULT_AUTONOMY_LEVEL = 'observe'
WRITE_CAPABLE_AUTONOMY_LEVELS = ('prepare', 'execute-approved')

CRITERION_STATES = ('pending', 'passed', 'failed', 'not_run')
DEFAULT_CRITERION_STATE = 'pending'

BUDGET_FIELDS = ('tokens', 'money_usd', 'time_seconds', 'requests')
CRITERION_FIELDS = ('criterion', 'verify', 'status')
FALSIFIER_FIELDS = ('falsifier_id', 'statement', 'how_detected')

TASKSPEC_FIELDS = ('taskspec_version', 'task_id', 'title', 'intent', 'agent_ref',
                   'autonomy_level', 'depends_on', 'budget', 'acceptance_criteria',
                   'falsifiers', 'idempotency_key', 'evidence_refs', 'created_at')
TASKSPEC_REQUIRED_FIELDS = ('taskspec_version', 'task_id', 'title', 'intent', 'autonomy_level',
                            'depends_on', 'budget', 'acceptance_criteria', 'falsifiers',
                            'idempotency_key')
DEFAULTED_REQUIRED_FIELDS = ('autonomy_level',)

# Reglas congeladas, citadas literalmente desde taskspec.schema.json:$defs.graph_rules.
ORDER_RULE = ('nivel = longitud de la cadena de dependencias mas larga desde una raiz; '
              'dentro del nivel, orden lexicografico ascendente por task_id')
HASH_RULE = ("SHA-256 hexadecimal sobre JSON canonico (sort_keys=True, separators=(',',':'), "
             'ensure_ascii=False) de la lista de TaskSpec ya ordenada topologicamente')

TASK_ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9_-]{1,63}$')
IDEMPOTENCY_KEY_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{8,128}$')
TIMESTAMP_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$')

# Centinela de lectura: distingue "clave ausente" de "clave presente con valor null" sin
# depender de `in`/`[]` (que un Mapping inconsistente puede contradecir).
_MISSING = object()
# Tope de profundidad de contenedores anidados recorridos. El contrato v1 usa 3 niveles
# como maximo; el tope solo convierte una entrada fuera de dominio en error tipado.
MAX_DECLARATION_DEPTH = 32
CREDENTIAL_NAME_PATTERN = re.compile(r'(?i)(credential|api[_-]?key|access[_-]?token|'
                                     r'refresh[_-]?token|bearer[_-]?token|client[_-]?secret|'
                                     r'private[_-]?key|password|cookie|csrf|'
                                     r'pending[_-]?consent|authorization)')

# Las 13 entradas literales de engine/project_store.py:19, copiadas a contenedores
# inmutables para que el modulo no exponga ningun contenedor mutable.
PROHIBITED_FIELD_NAMES = frozenset(_PROJECT_STORE_FORBIDDEN_FIELDS)
_STRIPPED_PROHIBITED_NAMES = frozenset(re.sub(r'[^a-z0-9]', '', name)
                                       for name in PROHIBITED_FIELD_NAMES)
del _PROJECT_STORE_FORBIDDEN_FIELDS

# Vocabulario cerrado del validador de grafo, literal de $defs.graph_rules.error_codes.
GRAPH_ERROR_CODES = ('cycle_detected', 'duplicate_task_id', 'unknown_dependency', 'self_dependency',
                     'empty_graph', 'unsupported_version', 'invalid_idempotency_key',
                     'missing_acceptance_criterion', 'missing_falsifier', 'negative_budget')
# Extension declarada de I1 para errores de campo, fuera del alcance de esa lista.
FIELD_ERROR_CODES = ('missing_required_field', 'invalid_field', 'forbidden_field', 'approval_required')
ERROR_CODES = GRAPH_ERROR_CODES + FIELD_ERROR_CODES


class TaskGraphError(ValueError):
    """Base tipada del Task Graph Engine: esta base no se lanza.

    Cada rechazo se lanza con una subclase concreta listada en `ERROR_CLASSES`, y el `code`
    de esa subclase pertenece a `ERROR_CODES`.
    """
    code = 'invalid_task_graph'


class GraphValidationError(TaskGraphError):
    """Base de los rechazos estructurales del grafo: esta base tampoco se lanza.

    Todas sus subclases concretas declaran un `code` de `GRAPH_ERROR_CODES`, el vocabulario
    congelado del validador de grafo.
    """


class MissingFieldError(TaskGraphError):
    """Falta un campo obligatorio del contrato.

    La presencia se decide con el valor leido por `data.get(name, _MISSING)`, nunca con un
    `in` seguido de `data[name]`: para el dominio admitido (mapeos coherentes) no se propaga
    `KeyError` ni `AttributeError`.
    """
    code = 'missing_required_field'


class InvalidFieldError(TaskGraphError):
    """Forma o tipo invalido para el contrato v1."""
    code = 'invalid_field'


class ForbiddenFieldError(TaskGraphError):
    """Nombre de campo con forma de credencial o consentimiento (nunca un valor)."""
    code = 'forbidden_field'


class ApprovalRequiredError(TaskGraphError):
    """Nivel de autonomia con capacidad de escritura sin flag de aprobacion explicito."""
    code = 'approval_required'


class UnsupportedVersionError(GraphValidationError):
    """Version de contrato distinta de la congelada; no se degrada a la interpretacion v1."""
    code = 'unsupported_version'


class EmptyGraphError(GraphValidationError):
    """Grafo sin tareas."""
    code = 'empty_graph'


class DuplicateTaskIdError(GraphValidationError):
    """Identificador de tarea repetido dentro del grafo."""
    code = 'duplicate_task_id'


class UnknownDependencyError(GraphValidationError):
    """Dependencia que no corresponde a ninguna tarea del grafo."""
    code = 'unknown_dependency'


class SelfDependencyError(GraphValidationError):
    """Tarea que se declara dependiente de si misma."""
    code = 'self_dependency'


class CycleError(GraphValidationError):
    """Ciclo de dependencias: el orden topologico no existe."""
    code = 'cycle_detected'


class InvalidIdempotencyKeyError(GraphValidationError):
    """Clave de idempotencia fuera del patron del contrato."""
    code = 'invalid_idempotency_key'


class MissingAcceptanceCriterionError(GraphValidationError):
    """Tarea sin criterio de aceptacion medible (minItems 1)."""
    code = 'missing_acceptance_criterion'


class MissingFalsifierError(GraphValidationError):
    """Tarea sin falsificador declarado (minItems 1)."""
    code = 'missing_falsifier'


class NegativeBudgetError(GraphValidationError):
    """Magnitud de presupuesto negativa."""
    code = 'negative_budget'


ERROR_CLASSES = (MissingFieldError, InvalidFieldError, ForbiddenFieldError, ApprovalRequiredError,
                 UnsupportedVersionError, EmptyGraphError, DuplicateTaskIdError,
                 UnknownDependencyError, SelfDependencyError, CycleError,
                 InvalidIdempotencyKeyError, MissingAcceptanceCriterionError,
                 MissingFalsifierError, NegativeBudgetError)


def _describe(value):
    """Descripcion corta y segura de un valor para el mensaje. Nunca copia el valor crudo."""
    if isinstance(value, str):
        return json.dumps(value[:24], ensure_ascii=True)
    return type(value).__name__


def _is_sequence(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _require_mapping(value, field_name):
    if not isinstance(value, Mapping):
        raise InvalidFieldError(f'{field_name}: se requiere un objeto JSON; recibido {_describe(value)}.')
    return value


def _require_sequence(value, field_name):
    if not _is_sequence(value):
        raise InvalidFieldError(f'{field_name}: se requiere una lista; recibido {_describe(value)}.')
    return value


def _check_text(value, field_name, minimum=1, maximum=None):
    if not isinstance(value, str):
        raise InvalidFieldError(f'{field_name}: se requiere texto; recibido {_describe(value)}.')
    if len(value) < minimum or (maximum is not None and len(value) > maximum):
        raise InvalidFieldError(f'{field_name}: longitud fuera de {minimum}..{maximum} caracteres del contrato v1.')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        # La regla de hash congelada exige UTF-8; un texto no codificable no tendria hash determinista.
        raise InvalidFieldError(f'{field_name}: el texto no es codificable en UTF-8; el hash canonico no seria determinista.') from None
    return value


def _check_identifier(value, field_name):
    if not isinstance(value, str) or not TASK_ID_PATTERN.fullmatch(value):
        raise InvalidFieldError(f'{field_name}: se requiere un identificador que cumpla ^[a-z0-9][a-z0-9_-]{{1,63}}$; recibido {_describe(value)}.')
    return value


def _check_version(value, expected, field_name):
    if value != expected:
        raise UnsupportedVersionError(f'unsupported_version: {field_name} debe ser "{expected}"; recibido {_describe(value)}. '
                                      'Un contrato v1 no se degrada a otra interpretacion.')
    return value


def _check_timestamp(value, field_name):
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.fullmatch(value):
        raise InvalidFieldError(f'{field_name}: se requiere una marca UTC tipo 2026-10-10T00:00:00Z; recibido {_describe(value)}.')
    return value


def _check_idempotency_key(value):
    if not isinstance(value, str) or not IDEMPOTENCY_KEY_PATTERN.fullmatch(value):
        raise InvalidIdempotencyKeyError('invalid_idempotency_key: se requiere texto de 8..128 caracteres del patron '
                                         '^[A-Za-z0-9._:-]{8,128}$; reutilizar la clave no duplica el efecto declarado.')
    return value


def forbidden_field_name(name):
    """True si el NOMBRE de campo tiene forma de credencial o consentimiento.

    Reutiliza la lista literal de `engine/project_store.py:19` con la normalizacion del
    guard de `engine/project_store.py:38-46` (camelCase->snake_case, `-`->`_` y variante
    sin caracteres no alfanumericos) y, ademas, el patron estricto del contrato congelado.
    Comprueba nombres de campo, nunca valores. `tokens` (magnitud de presupuesto, decision
    D-R0-1) no coincide con ningun nombre de credencial.
    """
    text = str(name)
    camel = re.sub(r'(?<!^)(?=[A-Z])', '_', text).lower().replace('-', '_')
    if camel in PROHIBITED_FIELD_NAMES:
        return True
    if re.sub(r'[^a-z0-9]', '', text.lower()) in _STRIPPED_PROHIBITED_NAMES:
        return True
    return bool(CREDENTIAL_NAME_PATTERN.search(text))


def _reject_credential_names(value, path='registro', depth=0):
    """Recorre los nombres de campo del registro y rechaza los que tengan forma de credencial.

    Acotado por `MAX_DECLARATION_DEPTH`: una estructura mas profunda o con referencias
    circulares se rechaza con `InvalidFieldError`, nunca con `RecursionError`.
    """
    if depth > MAX_DECLARATION_DEPTH:
        location = '.'.join(path.split('.')[:2])
        raise InvalidFieldError(f'{location}: la declaracion supera la profundidad maxima admitida '
                                f'({MAX_DECLARATION_DEPTH} niveles anidados); el dominio es un documento JSON de '
                                'profundidad acotada.')
    if isinstance(value, Mapping):
        for key in value:
            name = str(key)
            if forbidden_field_name(name):
                raise ForbiddenFieldError(f'forbidden_field: el nombre de campo {_describe(name)} de {path} coincide con la lista '
                                          'de campos prohibidos de engine/project_store.py:19 y no se puede declarar.')
            item = value.get(key, _MISSING)
            if item is not _MISSING:
                # Se lee con centinela, nunca con `value[key]`: un mapeo inconsistente no
                # puede convertir el recorrido en un KeyError crudo.
                _reject_credential_names(item, f'{path}.{name}', depth + 1)
    elif _is_sequence(value):
        for index, item in enumerate(value):
            _reject_credential_names(item, f'{path}[{index}]', depth + 1)


def _read_values(data, names, field_name, required=True):
    """Lee `names` con centinela y decide con el valor leido.

    Devuelve `{nombre: valor}`; `_MISSING` marca la clave ausente. Con `required=True` la
    ausencia produce `MissingFieldError` y la lectura no depende de `in`/`[]`.
    """
    values = {}
    for name in names:
        value = data.get(name, _MISSING)
        if value is _MISSING and required:
            raise MissingFieldError(f'{field_name}: falta el campo obligatorio "{name}" (required del contrato v1).')
        values[name] = value
    return values


def _unknown_names(data, declared, field_name):
    unknown = sorted(str(name) for name in data if name not in declared)
    if unknown:
        raise InvalidFieldError(f'{field_name}: campo no declarado en el contrato v1: ' + ', '.join(unknown) + '.')
    return data


def is_write_capable_level(level):
    """Declara si un nivel tiene capacidad de escritura. NO concede ninguna capacidad."""
    return level in WRITE_CAPABLE_AUTONOMY_LEVELS


def _check_autonomy(level, approved):
    if level is None:
        raise InvalidFieldError('autonomy_level: null no es un nivel declarado; omitir el campo aplica el default '
                                f'"{DEFAULT_AUTONOMY_LEVEL}".')
    if not isinstance(level, str) or level not in AUTONOMY_LEVELS:
        raise InvalidFieldError('autonomy_level: se requiere uno de ' + ', '.join(AUTONOMY_LEVELS) + '.')
    if is_write_capable_level(level) and approved is not True:
        raise ApprovalRequiredError(f'approval_required: autonomy_level "{level}" declara capacidad de escritura y exige el flag '
                                    'explicito approved=True; sin aprobacion el nivel no se construye y el techo efectivo es '
                                    f'"{DEFAULT_AUTONOMY_LEVEL}".')
    return level


def _check_counter(value, field_name):
    if type(value) is not int:
        raise InvalidFieldError(f'{field_name}: se requiere un entero; recibido {_describe(value)}.')
    if value < 0:
        raise NegativeBudgetError(f'negative_budget: {field_name} no admite valores negativos.')
    return value


def _check_money(value, field_name):
    if isinstance(value, bool) or type(value) not in (int, float):
        raise InvalidFieldError(f'{field_name}: se requiere un numero; recibido {_describe(value)}.')
    if not math.isfinite(value):
        raise InvalidFieldError(f'{field_name}: se requiere un numero finito; un presupuesto desconocido no se aproxima a cero.')
    if value < 0:
        raise NegativeBudgetError(f'negative_budget: {field_name} no admite valores negativos.')
    return float(value)


@dataclass(frozen=True)
class Budget:
    """Presupuesto declarado por tarea. Un presupuesto no es un limite de facturacion."""
    tokens: int
    money_usd: float
    time_seconds: int
    requests: int

    def __post_init__(self):
        object.__setattr__(self, 'tokens', _check_counter(self.tokens, 'budget.tokens'))
        object.__setattr__(self, 'money_usd', _check_money(self.money_usd, 'budget.money_usd'))
        object.__setattr__(self, 'time_seconds', _check_counter(self.time_seconds, 'budget.time_seconds'))
        object.__setattr__(self, 'requests', _check_counter(self.requests, 'budget.requests'))

    def to_dict(self):
        return {'tokens': self.tokens, 'money_usd': self.money_usd,
                'time_seconds': self.time_seconds, 'requests': self.requests}


def _build_budget(value, field_name='budget'):
    if isinstance(value, Budget):
        return value
    data = _require_mapping(value, field_name)
    _reject_credential_names(data, field_name)
    data = _unknown_names(data, BUDGET_FIELDS, field_name)
    magnitudes = _read_values(data, BUDGET_FIELDS, field_name)
    return Budget(tokens=_check_counter(magnitudes['tokens'], 'budget.tokens'),
                  money_usd=_check_money(magnitudes['money_usd'], 'budget.money_usd'),
                  time_seconds=_check_counter(magnitudes['time_seconds'], 'budget.time_seconds'),
                  requests=_check_counter(magnitudes['requests'], 'budget.requests'))


@dataclass(frozen=True)
class AcceptanceCriterion:
    """Criterio medible y verificable offline. `not_run` nunca se aproxima a `passed`."""
    criterion: str
    verify: str
    status: str = DEFAULT_CRITERION_STATE

    def __post_init__(self):
        _check_text(self.criterion, 'acceptance_criteria.criterion', 1, 600)
        _check_text(self.verify, 'acceptance_criteria.verify', 1, 600)
        if self.status not in CRITERION_STATES:
            raise InvalidFieldError('acceptance_criteria.status: se requiere uno de ' + ', '.join(CRITERION_STATES) + '.')

    def to_dict(self):
        return {'criterion': self.criterion, 'verify': self.verify, 'status': self.status}


@dataclass(frozen=True)
class Falsifier:
    """Observacion que refutaria el resultado declarado y como se detectaria."""
    falsifier_id: str
    statement: str
    how_detected: str

    def __post_init__(self):
        _check_identifier(self.falsifier_id, 'falsifiers.falsifier_id')
        _check_text(self.statement, 'falsifiers.statement', 1, 600)
        _check_text(self.how_detected, 'falsifiers.how_detected', 1, 600)

    def to_dict(self):
        return {'falsifier_id': self.falsifier_id, 'statement': self.statement,
                'how_detected': self.how_detected}


def _build_criterion(item, field_name='acceptance_criteria'):
    if isinstance(item, AcceptanceCriterion):
        return item
    data = _require_mapping(item, field_name)
    _reject_credential_names(data, field_name)
    data = _unknown_names(data, CRITERION_FIELDS, field_name)
    values = _read_values(data, ('criterion', 'verify', 'status'), field_name, required=False)
    if values['criterion'] is _MISSING or values['verify'] is _MISSING:
        absent = sorted(name for name in ('criterion', 'verify') if values[name] is _MISSING)
        raise MissingFieldError(f'{field_name}: falta el campo obligatorio "{absent[0]}" (required del contrato v1).')
    status = DEFAULT_CRITERION_STATE if values['status'] is _MISSING else values['status']
    return AcceptanceCriterion(criterion=values['criterion'], verify=values['verify'], status=status)


def _build_falsifier(item, field_name='falsifiers'):
    if isinstance(item, Falsifier):
        return item
    data = _require_mapping(item, field_name)
    _reject_credential_names(data, field_name)
    data = _unknown_names(data, FALSIFIER_FIELDS, field_name)
    values = _read_values(data, FALSIFIER_FIELDS, field_name)
    return Falsifier(falsifier_id=values['falsifier_id'], statement=values['statement'],
                     how_detected=values['how_detected'])


def _check_criteria(value):
    items = _require_sequence(value, 'acceptance_criteria')
    if not items:
        raise MissingAcceptanceCriterionError('missing_acceptance_criterion: la tarea no declara ningun criterio de aceptacion '
                                              'medible (minItems 1).')
    return tuple(_build_criterion(item) for item in items)


def _check_falsifiers(value):
    items = _require_sequence(value, 'falsifiers')
    if not items:
        raise MissingFalsifierError('missing_falsifier: la tarea no declara ningun falsificador (minItems 1); un resultado sin '
                                    'falsificador declarado no se considera verificado.')
    return tuple(_build_falsifier(item) for item in items)


def _check_dependencies(value, own_id):
    items = _require_sequence(value, 'depends_on')
    dependencies = []
    for dependency in items:
        _check_identifier(dependency, 'depends_on')
        if dependency == own_id:
            raise SelfDependencyError(f'self_dependency: la tarea "{own_id}" no puede depender de si misma.')
        if dependency in dependencies:
            raise InvalidFieldError(f'depends_on: "{dependency}" esta declarada mas de una vez (el contrato exige uniqueItems).')
        dependencies.append(dependency)
    return tuple(dependencies)


def _check_evidence_refs(value):
    items = _require_sequence(value, 'evidence_refs')
    return tuple(_check_text(item, 'evidence_refs', 1, 400) for item in items)


@dataclass(frozen=True)
class TaskSpec:
    """TaskSpec v1 inmutable. Construir no ejecuta, no programa y no autoriza nada.

    `autonomy_level` es un techo declarado. `autonomy_approved` es la procedencia de la
    aprobacion explicita: no pertenece a la declaracion del contrato v1
    (`additionalProperties: false`), no se serializa y no entra en el hash, pero se
    verifica en toda ruta de construccion para que ningun camino eleve el nivel sin ella.
    """
    task_id: str
    title: str
    intent: str
    budget: Budget
    idempotency_key: str
    depends_on: tuple[str, ...] = ()
    autonomy_level: str = DEFAULT_AUTONOMY_LEVEL
    agent_ref: str | None = None
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = ()
    falsifiers: tuple[Falsifier, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    created_at: str | None = None
    taskspec_version: str = TASKSPEC_VERSION
    autonomy_approved: bool = field(default=False, compare=False, repr=False)

    def __post_init__(self):
        _check_version(self.taskspec_version, TASKSPEC_VERSION, 'taskspec_version')
        _check_identifier(self.task_id, 'task_id')
        _check_text(self.title, 'title', 1, 160)
        _check_text(self.intent, 'intent', 1, 4000)
        if self.agent_ref is not None:
            _check_text(self.agent_ref, 'agent_ref', 1, 120)
        _check_autonomy(self.autonomy_level, self.autonomy_approved)
        _check_idempotency_key(self.idempotency_key)
        if self.created_at is not None:
            _check_timestamp(self.created_at, 'created_at')
        # Normalizacion inmutable: secuencias a tuplas y elementos a valores validados.
        object.__setattr__(self, 'budget', _build_budget(self.budget))
        object.__setattr__(self, 'depends_on', _check_dependencies(self.depends_on, self.task_id))
        object.__setattr__(self, 'acceptance_criteria', _check_criteria(self.acceptance_criteria))
        object.__setattr__(self, 'falsifiers', _check_falsifiers(self.falsifiers))
        object.__setattr__(self, 'evidence_refs', _check_evidence_refs(self.evidence_refs))

    @property
    def autonomy_state(self):
        """Alias de solo lectura del nivel declarado (vocabulario del encargo I1)."""
        return self.autonomy_level

    def to_dict(self):
        """Declaracion canonica del contrato v1: solo propiedades del schema."""
        declaration = {'taskspec_version': self.taskspec_version, 'task_id': self.task_id,
                       'title': self.title, 'intent': self.intent,
                       'autonomy_level': self.autonomy_level, 'depends_on': list(self.depends_on),
                       'budget': self.budget.to_dict(),
                       'acceptance_criteria': [item.to_dict() for item in self.acceptance_criteria],
                       'falsifiers': [item.to_dict() for item in self.falsifiers],
                       'idempotency_key': self.idempotency_key,
                       'evidence_refs': list(self.evidence_refs)}
        if self.agent_ref is not None:
            declaration['agent_ref'] = self.agent_ref
        if self.created_at is not None:
            declaration['created_at'] = self.created_at
        return declaration


@dataclass(frozen=True)
class TaskGraph:
    """TaskGraph v1 inmutable y autoverificable: orden y hash se recomprueban al construir."""
    tasks: tuple[TaskSpec, ...]
    topological_order: tuple[str, ...]
    graph_sha256: str
    graph_version: str = GRAPH_VERSION
    taskspec_version: str = TASKSPEC_VERSION
    policy_ref: str | None = None
    created_at: str | None = None

    def __post_init__(self):
        _check_version(self.graph_version, GRAPH_VERSION, 'graph_version')
        _check_version(self.taskspec_version, TASKSPEC_VERSION, 'taskspec_version')
        if not self.tasks:
            raise EmptyGraphError('empty_graph: el grafo no declara ninguna tarea (minItems 1).')
        if any(not isinstance(task, TaskSpec) for task in self.tasks):
            raise InvalidFieldError('tasks: se requiere una lista de TaskSpec ya construidos y validados.')
        identifiers = [task.task_id for task in self.tasks]
        duplicated = sorted({identifier for identifier in identifiers if identifiers.count(identifier) > 1})
        if duplicated:
            raise DuplicateTaskIdError('duplicate_task_id: identificadores repetidos en el grafo: ' + ', '.join(duplicated) + '.')
        known = {str(identifier) for identifier in identifiers}
        missing = sorted({(task.task_id, dependency) for task in self.tasks for dependency in task.depends_on
                          if dependency not in known})
        if missing:
            raise UnknownDependencyError('unknown_dependency: ' + '; '.join(f'{task_id} -> {dependency}'
                                                                           for task_id, dependency in missing) + '.')
        order = _topological_order(self.tasks)
        if tuple(self.topological_order) != order:
            raise InvalidFieldError('topological_order: no coincide con el orden determinista congelado (' + ORDER_RULE + ').')
        positions = {task_id: index for index, task_id in enumerate(order)}
        ordered = tuple(sorted(self.tasks, key=lambda task: positions[task.task_id]))
        if self.graph_sha256 != compute_graph_sha256(ordered):
            raise InvalidFieldError('graph_sha256: no coincide con la declaracion ordenada; el grafo se recalcula, no se corrige.')
        if self.policy_ref is not None:
            _check_text(self.policy_ref, 'policy_ref', 1, 200)
        if self.created_at is not None:
            _check_timestamp(self.created_at, 'created_at')
        object.__setattr__(self, 'tasks', ordered)
        object.__setattr__(self, 'topological_order', order)

    def to_dict(self):
        """Envolvente declarativa del DAG: tareas ya en orden topologico."""
        declaration = {'graph_version': self.graph_version, 'taskspec_version': self.taskspec_version,
                       'tasks': [task.to_dict() for task in self.tasks],
                       'graph_sha256': self.graph_sha256,
                       'topological_order': list(self.topological_order)}
        if self.policy_ref is not None:
            declaration['policy_ref'] = self.policy_ref
        if self.created_at is not None:
            declaration['created_at'] = self.created_at
        return declaration


def _canonical_bytes(payload):
    """JSON canonico del contrato congelado. Falla en vez de aproximar."""
    try:
        text = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
        return text.encode('utf-8')
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise InvalidFieldError('invalid_field: la declaracion no se puede canonicalizar como JSON UTF-8 (' +
                                type(error).__name__ + ').') from None


def _declaration_of(spec):
    """Declaracion JSON de un `TaskSpec` o la propia declaracion si ya es un `Mapping`."""
    if isinstance(spec, TaskSpec):
        return spec.to_dict()
    return _require_mapping(spec, 'tasks')


def canonical_task_list(specs):
    """JSON canonico de la lista de declaraciones, en el orden recibido.

    Admite `TaskSpec` o declaraciones JSON (`Mapping`); cualquier otro tipo se rechaza con
    `InvalidFieldError`. Es un canonicalizador: no revalida el contenido de una declaracion
    cruda (para validarla, construirla con `build_taskspec`/`build_graph`).
    """
    payload = [_declaration_of(spec) for spec in _require_sequence(specs, 'tasks')]
    return _canonical_bytes(payload).decode('utf-8')


def compute_graph_sha256(specs):
    """SHA-256 de la lista ya en orden topologico ($defs.graph_rules.hash_rule).

    Admite `TaskSpec` o declaraciones JSON (`Mapping`), igual que `canonical_task_list`.
    """
    return hashlib.sha256(_canonical_bytes([_declaration_of(spec)
                                            for spec in _require_sequence(specs, 'tasks')])).hexdigest()


def _topological_order(specs):
    """Orden determinista: nivel = cadena de dependencias mas larga desde una raiz; nivel, luego task_id."""
    index = {spec.task_id: spec for spec in specs}
    levels = {}
    unresolved = set(index)
    while unresolved:
        ready = sorted(task_id for task_id in unresolved
                       if all(dependency in levels for dependency in index[task_id].depends_on))
        if not ready:
            raise CycleError('cycle_detected: ciclo de dependencias en el grafo: ' +
                             ' -> '.join(_cycle_path(index, unresolved)) + '.')
        for task_id in ready:
            dependencies = index[task_id].depends_on
            levels[task_id] = 0 if not dependencies else 1 + max(levels[dependency] for dependency in dependencies)
        unresolved.difference_update(ready)
    return tuple(sorted(index, key=lambda task_id: (levels[task_id], task_id)))


def _cycle_path(index, unresolved):
    """Camino determinista de un ciclo dentro de los nodos NO resueltos (informativo).

    Solo avanza a dependencias que siguen en `unresolved`: un nodo no resuelto tiene al
    menos una dependencia fuera de `levels` (si no, habria sido `ready`), asi que
    `candidates` nunca esta vacio y el recorrido no puede abandonar el conjunto no resuelto
    ni levantar `IndexError`.
    """
    seen = []
    positions = {}
    node = sorted(unresolved)[0]
    while node not in positions:
        positions[node] = len(seen)
        seen.append(node)
        candidates = sorted(dependency for dependency in index[node].depends_on if dependency in unresolved)
        node = candidates[0]
    return tuple(seen[positions[node]:]) + (node,)


def _declared_task_id(record):
    """task_id declarado, si se puede leer; `None` si el registro no es `TaskSpec` ni `Mapping`."""
    if isinstance(record, TaskSpec):
        return record.task_id
    if isinstance(record, Mapping):
        candidate = record.get('task_id', _MISSING)
        return candidate if isinstance(candidate, str) else None
    return None


def _declared_value(spec, name, field_name):
    """Lee un campo de un `TaskSpec` o de una declaracion JSON (`Mapping`).

    Admite exactamente esos dos tipos, como el resto de las funciones de lista del modulo.
    Una clave ausente produce `MissingFieldError`; cualquier otro tipo, `InvalidFieldError`:
    nunca `AttributeError` ni `KeyError`.
    """
    if isinstance(spec, TaskSpec):
        return getattr(spec, name)
    if isinstance(spec, Mapping):
        value = spec.get(name, _MISSING)
        if value is _MISSING:
            raise MissingFieldError(f'{field_name}: la declaracion no declara el campo obligatorio "{name}".')
        return value
    raise InvalidFieldError(f'{field_name}: se admite un TaskSpec o una declaracion JSON (Mapping); '
                            f'recibido {_describe(spec)}.')


def _approval_for(task_id, approved):
    """Aprobacion explicita POR TAREA: True (todas), lista de task_id o mapa {task_id: True}."""
    if approved is True:
        return True
    if approved is False or approved is None:
        return False
    if isinstance(approved, Mapping):
        return approved.get(task_id) is True
    if _is_sequence(approved):
        return task_id in approved
    raise InvalidFieldError('approved: se requiere True, False, una lista de task_id o un mapa {task_id: True}; '
                            f'recibido {_describe(approved)}.')


def build_taskspec(record, *, approved=False):
    """Construye un TaskSpec v1 validado a partir de su declaracion.

    Admite una declaracion JSON (`Mapping` coherente, como el de `json.loads`); cualquier
    otro tipo se rechaza con `InvalidFieldError`. Las lecturas usan el centinela `_MISSING`,
    asi que una clave ausente produce `MissingFieldError` y nunca `KeyError`.

    `approved` es la aprobacion explicita del operador (solo `True` cuenta) para declarar
    un nivel con capacidad de escritura. Esta funcion no ejecuta la tarea, no la programa,
    no la autoriza en runtime y no escribe nada.
    """
    data = _require_mapping(record, 'TaskSpec')
    _reject_credential_names(data, 'TaskSpec')
    data = _unknown_names(data, TASKSPEC_FIELDS, 'TaskSpec')
    values = _read_values(data, TASKSPEC_FIELDS, 'TaskSpec', required=False)
    missing = tuple(name for name in TASKSPEC_REQUIRED_FIELDS
                    if values[name] is _MISSING and name not in DEFAULTED_REQUIRED_FIELDS)
    if missing:
        raise MissingFieldError('TaskSpec: faltan campos obligatorios del contrato v1: ' + ', '.join(missing) + '.')
    for optional in ('agent_ref', 'created_at'):
        if values[optional] is None:
            raise InvalidFieldError(f'{optional}: null no es un valor declarado por el contrato v1; omitir el campo si no se declara.')
    return TaskSpec(task_id=values['task_id'], title=values['title'], intent=values['intent'],
                    budget=_build_budget(values['budget']),
                    idempotency_key=_check_idempotency_key(values['idempotency_key']),
                    depends_on=values['depends_on'],
                    autonomy_level=(DEFAULT_AUTONOMY_LEVEL if values['autonomy_level'] is _MISSING
                                    else values['autonomy_level']),
                    agent_ref=None if values['agent_ref'] is _MISSING else values['agent_ref'],
                    acceptance_criteria=values['acceptance_criteria'],
                    falsifiers=values['falsifiers'],
                    evidence_refs=() if values['evidence_refs'] is _MISSING else values['evidence_refs'],
                    created_at=None if values['created_at'] is _MISSING else values['created_at'],
                    taskspec_version=values['taskspec_version'],
                    autonomy_approved=_approval_for(values['task_id'], approved))


def build_graph(records, *, approved=False, policy_ref=None, created_at=None):
    """Construye y valida un TaskGraph v1: DAG aciclico, orden determinista y hash.

    Cada elemento de `records` es un `TaskSpec` ya construido o una declaracion JSON
    (`Mapping` coherente); cualquier otro tipo se rechaza con `InvalidFieldError` y una clave
    obligatoria ausente produce `MissingFieldError`, nunca `AttributeError`.

    Valida identificadores duplicados, dependencias inexistentes, auto-dependencias,
    ciclos, presupuesto, criterios, falsificadores, idempotencia y autonomia declarada.
    No ejecuta, no programa y no despacha: solo declara y rechaza lo invalido.

    Las comprobaciones estructurales se repiten en `TaskGraph.__post_init__` a proposito:
    el grafo se autoverifica y no depende de que ningun constructor confie en este builder.
    """
    items = _require_sequence(records, 'TaskGraph.tasks')
    if not items:
        raise EmptyGraphError('empty_graph: el grafo no declara ninguna tarea (minItems 1).')
    specs = []
    for record in items:
        if isinstance(record, TaskSpec):
            specs.append(record)
        else:
            specs.append(build_taskspec(record, approved=_approval_for(_declared_task_id(record), approved)))
    identifiers = [spec.task_id for spec in specs]
    duplicated = sorted({identifier for identifier in identifiers if identifiers.count(identifier) > 1})
    if duplicated:
        raise DuplicateTaskIdError('duplicate_task_id: identificadores repetidos en el grafo: ' + ', '.join(duplicated) + '.')
    known = set(identifiers)
    missing = sorted({(spec.task_id, dependency) for spec in specs for dependency in spec.depends_on
                      if dependency not in known})
    if missing:
        raise UnknownDependencyError('unknown_dependency: ' + '; '.join(f'{task_id} -> {dependency}'
                                                                       for task_id, dependency in missing) + '.')
    order = _topological_order(specs)
    positions = {task_id: index for index, task_id in enumerate(order)}
    ordered = tuple(sorted(specs, key=lambda spec: positions[spec.task_id]))
    return TaskGraph(tasks=ordered, topological_order=order, graph_sha256=compute_graph_sha256(ordered),
                     policy_ref=policy_ref, created_at=created_at)


def duplicate_idempotency_keys(specs):
    """Claves de idempotencia repetidas dentro de la lista. Es un informe, no un rechazo.

    Admite `TaskSpec` o declaraciones JSON (`Mapping`), igual que `canonical_task_list`:
    una clave ausente produce `MissingFieldError` y un elemento de otro tipo,
    `InvalidFieldError`; nunca `AttributeError`.
    """
    keys = [_declared_value(spec, 'idempotency_key', 'duplicate_idempotency_keys')
            for spec in _require_sequence(specs, 'tasks')]
    return tuple(sorted({key for key in keys if keys.count(key) > 1}))


def inspect_graph(records, *, approved=False, policy_ref=None, created_at=None):
    """Veredicto declarativo sin excepcion: valido, o codigo del vocabulario y mensaje.

    Un grafo invalido devuelve `graph_sha256` y `task_count` en `None` (null), nunca 0:
    nada desconocido se convierte en cero.
    """
    try:
        graph = build_graph(records, approved=approved, policy_ref=policy_ref, created_at=created_at)
    except TaskGraphError as error:
        return {'valid': False, 'code': error.code, 'message': str(error), 'task_count': None,
                'topological_order': (), 'graph_sha256': None, 'duplicate_idempotency_keys': ()}
    return {'valid': True, 'code': None, 'message': '', 'task_count': len(graph.tasks),
            'topological_order': graph.topological_order, 'graph_sha256': graph.graph_sha256,
            'duplicate_idempotency_keys': duplicate_idempotency_keys(graph.tasks)}
