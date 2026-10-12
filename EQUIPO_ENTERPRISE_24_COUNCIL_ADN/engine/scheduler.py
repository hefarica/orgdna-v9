"""Recorre un TaskGraph validado y decide QUE nodo puede lanzarse. No ejecuta.

Rol: orquestador declarativo CON ESTADO, no ejecutor. Todo contacto con el host entra
por PUERTOS inyectados, de modo que el modulo se prueba entero offline.

Puertos (callables que inyecta el llamador; aqui no se importa nada del host):
    dispatch(task_id, agent_ref, lease_id) -> receipt
    acquire(task_id, paths, base_sha)      -> lease_id
    release(lease_id)                      -> None
    verify(criterion)                      -> bool
    gate_ready()                           -> bool

Invariante rector: FAIL-CLOSED. Ante duda, NO se lanza.

Estados, con significado exacto y sin solaparse:
    not_run  declarado y NUNCA evaluado (no todas sus dependencias estan en 'passed')
    pending  evaluado y esperando (sin slot libre, o sin lease exigible)
    running  despachado
    passed   verificado
    failed   no verificado o error de despacho
    blocked  una dependencia fallo o se bloqueo; solo una decision explicita lo saca
'not_run' JAMAS pasa a 'passed': `complete` exige 'running'.

Determinista, sin estado mutable de modulo, sin red, sin efectos al importar.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = "scheduler-1.0"

RUN_STATES = ("not_run", "pending", "running", "passed", "failed", "blocked")
TERMINAL_STATES = ("passed", "failed", "blocked")
PHASES = ("implementation", "council")
MAX_IMPLEMENTATION_CONCURRENCY = 3
MAX_COUNCIL_CONCURRENCY = 64
MAX_NODES = 1024
_ID_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
_VOLATILE_FIELDS = ("started_at", "ended_at")


class SchedulerError(ValueError):
    """Base de todos los rechazos del scheduler."""


class InvalidRunError(SchedulerError):
    """El Run o el grafo recibido no cumple lo que la funcion exige."""


class DispatchUnavailable(SchedulerError):
    """El puerto NO puede despachar porque no hay runtime. NO es un fallo del nodo.

    Distincion deliberada: si el runtime no existe, no se ha intentado nada, asi que
    el nodo NO pasa a 'failed' — se queda 'pending' y se registra el motivo. Marcarlo
    'failed' afirmaria que algo fallo, y no fallo: no se pudo empezar.
    """


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _check_id(value, field):
    if not isinstance(value, str) or not 2 <= len(value) <= 64 or not set(value) <= _ID_CHARS:
        raise InvalidRunError("%s: identificador invalido (%r)." % (field, value))
    if value[0] in "_-":
        raise InvalidRunError("%s: debe empezar por letra o digito." % field)
    return value


def _check_text(value, field, maximum=500):
    if not isinstance(value, str) or not value.strip():
        raise InvalidRunError("%s: se requiere texto." % field)
    if len(value.encode("utf-8")) > maximum:
        raise InvalidRunError("%s: supera %d bytes." % (field, maximum))
    return value


def _check_port(value, field):
    if not callable(value):
        raise InvalidRunError("%s: se requiere un puerto invocable." % field)
    return value


class Node:
    """Nodo inmutable. `evolved()` devuelve uno nuevo; nunca se muta in situ."""

    __slots__ = ("task_id", "depends_on", "write_capable", "paths", "agent_ref",
                 "state", "lease_id", "attempt", "started_at", "ended_at")

    def __init__(self, task_id, depends_on=(), write_capable=False, paths=(), agent_ref=None,
                 state="not_run", lease_id=None, attempt=0, started_at=None, ended_at=None):
        if state not in RUN_STATES:
            raise InvalidRunError("state: desconocido (%r)." % (state,))
        self.task_id = _check_id(task_id, "task_id")
        self.depends_on = tuple(depends_on)
        self.write_capable = bool(write_capable)
        self.paths = tuple(paths)
        self.agent_ref = agent_ref
        self.state = state
        self.lease_id = lease_id
        self.attempt = int(attempt)
        self.started_at = started_at
        self.ended_at = ended_at

    def _key(self):
        return tuple((name, getattr(self, name)) for name in self.__slots__)

    def __eq__(self, other):
        return type(other) is Node and self._key() == other._key()

    def __hash__(self):
        return hash(("Node", self._key()))

    def evolved(self, **changes):
        current = {name: getattr(self, name) for name in self.__slots__}
        current.update(changes)
        return Node(**current)


class SchedulerConfig:
    """Tope de concurrencia por fase. El Council es de solo lectura."""

    __slots__ = ("phase", "implementation_concurrency", "council_concurrency")

    def __init__(self, phase="implementation", implementation_concurrency=3, council_concurrency=1):
        if phase not in PHASES:
            raise InvalidRunError("phase: se requiere " + " o ".join(PHASES) + ".")
        if type(implementation_concurrency) is not int or not 1 <= implementation_concurrency <= MAX_IMPLEMENTATION_CONCURRENCY:
            raise InvalidRunError("implementation_concurrency: entero 1..%d." % MAX_IMPLEMENTATION_CONCURRENCY)
        if type(council_concurrency) is not int or not 1 <= council_concurrency <= MAX_COUNCIL_CONCURRENCY:
            raise InvalidRunError("council_concurrency: entero 1..%d." % MAX_COUNCIL_CONCURRENCY)
        self.phase = phase
        self.implementation_concurrency = implementation_concurrency
        self.council_concurrency = council_concurrency

    @property
    def max_concurrent(self):
        return self.council_concurrency if self.phase == "council" else self.implementation_concurrency

    def _key(self):
        return tuple((name, getattr(self, name)) for name in self.__slots__)

    def __eq__(self, other):
        return type(other) is SchedulerConfig and self._key() == other._key()

    def __hash__(self):
        return hash(("SchedulerConfig", self._key()))


class Run:
    """Snapshot inmutable del estado de un grafo en una fase."""

    __slots__ = ("schema_version", "graph_sha256", "config", "order", "nodes")

    def __init__(self, graph_sha256, config, order, nodes, schema_version=SCHEMA_VERSION):
        self.schema_version = schema_version
        self.graph_sha256 = graph_sha256
        self.config = config
        self.order = tuple(order)
        self.nodes = tuple(nodes)

    def node(self, task_id):
        for row in self.nodes:
            if row.task_id == task_id:
                return row
        raise InvalidRunError("task_id: no esta en este run: %r." % (task_id,))

    def evolved(self, nodes):
        return Run(self.graph_sha256, self.config, self.order, nodes, self.schema_version)

    def _key(self):
        return (self.schema_version, self.graph_sha256, self.config, self.order, self.nodes)

    def __eq__(self, other):
        return type(other) is Run and self._key() == other._key()

    def __hash__(self):
        return hash(("Run", self._key()))


# --------------------------------------------------------------------- adaptador

def _write_capable_levels():
    """La capacidad de escritura la define el contrato v1, no el scheduler.

    Se lee de la constante del grafo para que no existan dos listas que puedan
    divergir. `execute-approved` ya exige `approved=True` al CONSTRUIR el grafo.
    """
    try:
        from . import task_graph
    except ImportError:
        import task_graph
    return task_graph.WRITE_CAPABLE_AUTONOMY_LEVELS


def canonical_order(rows):
    """Orden determinista: nivel = cadena de dependencias mas larga desde una raiz,
    desempate lexicografico. Es la MISMA regla que documenta task_graph.ORDER_RULE.

    Sin esto el orden dependeria del orden de insercion del mapeo de entrada y
    `ready_tasks` dejaria de ser determinista; lo delata el caso F9.
    """
    level, visiting = {}, set()

    def depth(task_id):
        if task_id in level:
            return level[task_id]
        if task_id in visiting:
            raise InvalidRunError("grafo: ciclo detectado en %r." % task_id)
        visiting.add(task_id)
        deps = rows[task_id]["depends_on"]
        value = 0 if not deps else 1 + max(depth(dep) for dep in deps)
        visiting.discard(task_id)
        level[task_id] = value
        return value

    for task_id in rows:
        depth(task_id)
    return tuple(sorted(rows, key=lambda t: (level[t], t)))


def _normalize(source):
    """Normaliza a (graph_sha256, orden_declarado_o_None, {task_id: dict}).

    1. Un TaskGraph REAL: se leen `topological_order`, `tasks` y `graph_sha256`; la
       capacidad de escritura sale de `autonomy_level` con la constante del contrato.
    2. Un mapeo {task_id: {...}}: limite documentado del adaptador, para poder probar
       el scheduler sin construir un grafo.
    """
    order = getattr(source, "topological_order", None)
    tasks = getattr(source, "tasks", None)
    if order is not None and tasks is not None:
        levels = _write_capable_levels()
        rows = {}
        for spec in tasks:
            rows[spec.task_id] = {"depends_on": tuple(spec.depends_on),
                                  "write_capable": spec.autonomy_level in levels,
                                  "agent_ref": getattr(spec, "agent_ref", None),
                                  "paths": ()}
        return str(getattr(source, "graph_sha256", "")), tuple(order), rows

    if isinstance(source, dict):
        rows = {}
        for task_id, row in source.items():
            if not isinstance(row, dict):
                raise InvalidRunError("graph[%r]: se requiere objeto." % (task_id,))
            unknown = set(row) - {"depends_on", "write_capable", "agent_ref", "paths"}
            if unknown:
                raise InvalidRunError("graph[%r]: campos no admitidos: %s." % (task_id, ", ".join(sorted(unknown))))
            rows[task_id] = {"depends_on": tuple(row.get("depends_on", ())),
                             "write_capable": bool(row.get("write_capable", False)),
                             "agent_ref": row.get("agent_ref"),
                             "paths": tuple(row.get("paths", ()))}
        return "", None, rows

    raise InvalidRunError("graph: se requiere un TaskGraph construido o un mapeo {task_id: {...}}.")


def build_run(graph, *, config, phase=None):
    """Snapshot inmutable. TODOS los nodos empiezan en 'not_run': declarados, sin tocar."""
    if not isinstance(config, SchedulerConfig):
        raise InvalidRunError("config: se requiere SchedulerConfig.")
    if phase is not None and phase != config.phase:
        raise InvalidRunError("phase: no puede contradecir config.phase (%r vs %r); no hay sobreescritura silenciosa."
                              % (phase, config.phase))
    graph_sha256, declared, rows = _normalize(graph)
    if not rows:
        raise InvalidRunError("graph: sin tareas.")
    if len(rows) > MAX_NODES:
        raise InvalidRunError("graph: maximo %d tareas." % MAX_NODES)
    for task_id in rows:
        _check_id(task_id, "graph.task_id")
    for task_id, row in rows.items():
        for dep in row["depends_on"]:
            if dep not in rows:
                raise InvalidRunError("grafo: dependencia desconocida %r en %r." % (dep, task_id))
            if dep == task_id:
                raise InvalidRunError("grafo: %r depende de si misma." % task_id)
    ranked = canonical_order(rows)
    if declared is not None and tuple(declared) != ranked:
        raise InvalidRunError("orden del grafo incoherente con la regla determinista: declarado %r, calculado %r."
                              % (tuple(declared), ranked))
    nodes = tuple(Node(task_id=task_id, depends_on=rows[task_id]["depends_on"],
                       write_capable=rows[task_id]["write_capable"],
                       paths=rows[task_id]["paths"], agent_ref=rows[task_id]["agent_ref"])
                  for task_id in ranked)
    return Run(graph_sha256, config, ranked, nodes)


# --------------------------------------------------------------------- consulta

def ready_tasks(run):
    """Nodos lanzables, en orden determinista. Listo <=> TODAS sus dependencias 'passed'.

    Solo se consideran los que aun no se evaluaron ('not_run') o esperan ('pending').
    Un 'failed' o 'blocked' no vuelve a estar listo jamas: no hay reintento automatico.
    """
    if not isinstance(run, Run):
        raise InvalidRunError("run: se requiere un Run del scheduler.")
    passed = {n.task_id for n in run.nodes if n.state == "passed"}
    by_id = {n.task_id: n for n in run.nodes}
    out = []
    for task_id in run.order:
        node = by_id[task_id]
        if node.state not in ("not_run", "pending"):
            continue
        if all(dep in passed for dep in node.depends_on):
            out.append(task_id)
    return tuple(out)


def descendants(run, task_id):
    """Cierre de descendientes de un nodo, en orden determinista."""
    run.node(task_id)
    children = {n.task_id: [] for n in run.nodes}
    for node in run.nodes:
        for dep in node.depends_on:
            children[dep].append(node.task_id)
    seen, queue = set(), list(children.get(task_id, ()))
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        queue.extend(children.get(current, ()))
    return tuple(t for t in run.order if t in seen)


# --------------------------------------------------------------------- transiciones

def step(run, *, dispatch, gate_ready, now):
    """Un tick: lanza listos hasta el tope de concurrencia. Devuelve (Run nuevo, eventos).

    `gate_ready` es la puerta de preflight. Si no esta en verde NO se lanza nada y el
    run queda intacto: fail-closed, sin efectos parciales.
    """
    if not isinstance(run, Run):
        raise InvalidRunError("run: se requiere un Run del scheduler.")
    _check_port(dispatch, "dispatch")
    _check_port(gate_ready, "gate_ready")
    now = _check_text(now, "now", 40)
    if not gate_ready():
        return run, (("GATE_BLOCKED", None, "el preflight no esta en verde: cero lanzamientos"),)

    slots = run.config.max_concurrent - sum(1 for n in run.nodes if n.state == "running")
    by_id = {n.task_id: n for n in run.nodes}
    changes, events = {}, []
    for task_id in ready_tasks(run):
        node = by_id[task_id]
        if slots <= 0:
            if node.state == "not_run":
                changes[task_id] = node.evolved(state="pending")
            events.append(("PENDING_NO_SLOT", task_id, "sin slot libre"))
            continue
        if node.write_capable and not node.lease_id:
            if node.state == "not_run":
                changes[task_id] = node.evolved(state="pending")
            events.append(("LEASE_REQUIRED", task_id, "nodo con capacidad de escritura sin lease: no se despacha"))
            continue
        try:
            receipt = dispatch(task_id, node.agent_ref, node.lease_id)
        except DispatchUnavailable as exc:
            # No hay runtime: no se ha intentado nada. El nodo no falla, espera.
            if node.state == "not_run":
                changes[task_id] = node.evolved(state="pending")
            events.append(("DISPATCH_UNAVAILABLE", task_id, str(exc)[:300]))
            continue
        except Exception as exc:                                        # noqa: BLE001
            # Error real de despacho: falla el nodo y se bloquean sus descendientes.
            changes[task_id] = node.evolved(state="failed", started_at=now, ended_at=now,
                                            attempt=node.attempt + 1)
            for other in descendants(run, task_id):
                row = run.node(other)
                if row.state not in TERMINAL_STATES:
                    changes[other] = row.evolved(state="blocked", ended_at=now)
            events.append(("DISPATCH_FAILED", task_id, "%s: %s" % (type(exc).__name__, exc)))
            continue
        changes[task_id] = node.evolved(state="running", started_at=now, attempt=node.attempt + 1)
        events.append(("DISPATCHED", task_id, "" if receipt is None else _dump(receipt)[:400]))
        slots -= 1
    nodes = tuple(changes.get(n.task_id, n) for n in run.nodes)
    return run.evolved(nodes), tuple(events)


def complete(run, task_id, *, result, now, release=None):
    """Cierra un nodo 'running'. Un 'failed' bloquea a TODOS sus descendientes."""
    if not isinstance(run, Run):
        raise InvalidRunError("run: se requiere un Run del scheduler.")
    if result not in ("passed", "failed"):
        raise InvalidRunError("result: se requiere 'passed' o 'failed'.")
    now = _check_text(now, "now", 40)
    node = run.node(task_id)
    if node.state != "running":
        raise InvalidRunError("complete: el nodo %r no esta 'running'; es %r." % (task_id, node.state))
    changes = {task_id: node.evolved(state=result, ended_at=now)}
    if result == "failed":
        for other in descendants(run, task_id):
            row = run.node(other)
            if row.state not in TERMINAL_STATES:
                changes[other] = row.evolved(state="blocked", ended_at=now)
    if release is not None and node.lease_id:
        _check_port(release, "release")
        release(node.lease_id)
    nodes = tuple(changes.get(n.task_id, n) for n in run.nodes)
    return run.evolved(nodes)


def acquire_for(run, task_id, *, acquire, base_sha):
    """Obtiene lease ANTES de despachar un nodo con capacidad de escritura."""
    if not isinstance(run, Run):
        raise InvalidRunError("run: se requiere un Run del scheduler.")
    _check_port(acquire, "acquire")
    base_sha = _check_text(base_sha, "base_sha", 64)
    node = run.node(task_id)
    if not node.write_capable:
        raise InvalidRunError("acquire_for: el nodo %r no declara capacidad de escritura; no necesita lease." % task_id)
    if node.lease_id:
        raise InvalidRunError("acquire_for: el nodo %r ya tiene lease." % task_id)
    if node.state not in ("not_run", "pending"):
        raise InvalidRunError("acquire_for: el nodo %r ya no esta pendiente; es %r." % (task_id, node.state))
    lease = acquire(task_id, list(node.paths), base_sha)
    if not isinstance(lease, str) or not lease.strip():
        raise InvalidRunError("acquire: el puerto devolvio un lease invalido.")
    lease = lease.strip()
    changes = {task_id: node.evolved(lease_id=lease)}
    nodes = tuple(changes.get(n.task_id, n) for n in run.nodes)
    return run.evolved(nodes), lease


def reopen(run, task_id, *, reason):
    """Saca un nodo de 'blocked' por DECISION EXPLICITA. Nunca ocurre solo."""
    reason = _check_text(reason, "reason", 300)
    node = run.node(task_id)
    if node.state != "blocked":
        raise InvalidRunError("reopen: el nodo %r no esta 'blocked'; es %r." % (task_id, node.state))
    changes = {task_id: node.evolved(state="pending")}
    nodes = tuple(changes.get(n.task_id, n) for n in run.nodes)
    return run.evolved(nodes)


# --------------------------------------------------------------------- veredicto

def run_sha256(run):
    """SHA-256 determinista. EXCLUYE started_at/ended_at: son volatiles, no estado."""
    if not isinstance(run, Run):
        raise InvalidRunError("run: se requiere un Run del scheduler.")
    payload = {"schema_version": run.schema_version, "graph_sha256": run.graph_sha256,
               "phase": run.config.phase, "max_concurrent": run.config.max_concurrent,
               "order": list(run.order),
               "nodes": [{name: getattr(node, name) for name in node.__slots__ if name not in _VOLATILE_FIELDS}
                         for node in run.nodes]}
    return _digest(payload)


def inspect_run(run):
    """Veredicto SIN excepcion. 'not_run' se reporta como 'not_run', nunca como 'passed'."""
    if not isinstance(run, Run):
        raise InvalidRunError("run: se requiere un Run del scheduler.")
    counts = {state: 0 for state in RUN_STATES}
    for node in run.nodes:
        counts[node.state] += 1
    total = len(run.nodes)
    if total == 0:
        code = "EMPTY"
    elif counts["failed"]:
        code = "FAILED"
    elif counts["blocked"]:
        code = "BLOCKED"
    elif counts["running"] or counts["pending"]:
        code = "IN_PROGRESS"
    elif counts["not_run"]:
        code = "NOT_STARTED"
    else:
        code = "COMPLETE"
    report = {"schema_version": SCHEMA_VERSION, "code": code, "total": total,
              "valid": counts["failed"] == 0 and counts["blocked"] == 0,
              "runtime_verified": False, "executed_here": False,
              "note": "El scheduler DECIDE; no ejecuta, no instala y no acredita runtime."}
    report.update(counts)
    report["run_sha256"] = run_sha256(run)
    return report
