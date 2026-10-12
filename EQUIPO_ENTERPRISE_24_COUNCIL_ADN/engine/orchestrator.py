"""El ciguenal: pone puertos REALES sobre el scheduler y conduce el bucle.

El scheduler DECIDE; este modulo lo CONDUCE. La diferencia importa: aqui viven las
aristas que faltaban, y aqui es donde se dice la verdad sobre lo que se puede y lo
que no se puede tocar de verdad.

Puertos reales que se cablean aqui:
    gate_ready  -> readiness_gate.evaluate  (herramientas del catalogo + allow/deny)
    acquire     -> coordination.CoordinationStore 'lease-acquire'  (tickets reales)
    release     -> coordination 'lease-release'
    dispatch    -> SE INYECTA. No hay runtime en este arbol y NO se inventa uno:
                   el puerto por defecto LANZA DispatchUnavailable, asi que el bucle
                   termina en BLOCKED sin afirmar nada.
    poll        -> SE INYECTA. Sin runtime, None.

TERMINACION POR PROGRESO, no por contador: si un tick no cambia el run y quedan nodos
sin terminar, se para. Asi un dispatch que no avanza no puede girar en vacio, y el
resultado es BLOCKED, nunca un 'passed' inventado.

Fail-closed. Sin reintentos automaticos. Sin efectos al importar.
"""
from __future__ import annotations

import hashlib
import json
import os

from . import coordination
from . import readiness_gate
from . import scheduler

SCHEMA_VERSION = "orchestrator-1.0"
DEFAULT_TTL_SECONDS = 900
MAX_STEPS = 512


class OrchestratorError(ValueError):
    """Base de los rechazos del orquestador."""


class NoRuntimeError(scheduler.DispatchUnavailable):
    """No hay runtime al que despachar. Se lanza; no se simula."""


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- puerta real

def build_gate(tool_needs, allow, deny, catalog_names, capability_gaps=(), waivers=None):
    """Envuelve readiness_gate.evaluate en el puerto `gate_ready`.

    `readiness_gate` NUNCA lanza: devuelve un veredicto. Aqui se convierte en un
    booleano fail-closed: solo `ready is True` abre la puerta.
    """
    needs = list(tool_needs)

    def gate_ready():
        verdict = readiness_gate.evaluate(needs, list(allow), list(deny), list(catalog_names),
                                          capability_gaps=capability_gaps, waivers=waivers)
        return verdict.get("ready") is True

    gate_ready.verdict = lambda: readiness_gate.evaluate(needs, list(allow), list(deny),
                                                         list(catalog_names),
                                                         capability_gaps=capability_gaps, waivers=waivers)
    return gate_ready


def tool_catalog_names():
    """Nombres del catalogo real del usuario. Nunca se inventan disponibilidades."""
    try:
        from . import tool_permissions
    except ImportError:                                                 # pragma: no cover
        import tool_permissions
    return sorted({tool["name"] for tool in tool_permissions._catalog()["tools"]})


# ---------------------------------------------------------------- leases reales

def _active_lease(state, owner, task_id):
    """El identificador del ticket vive en la clave `id` de la fila, NO en `lease_id`.

    Comprobado contra el registro real: las claves de una fila son
    (id, owner_agent_id, task_id, status, paths, base_sha, expires_at, ...).
    """
    for row in state.get("leases", []):
        if row.get("owner_agent_id") == owner and row.get("task_id") == task_id and row.get("status") == "active":
            return row.get("id") or row.get("lease_id")
    return None


def make_lease_ports(store, owner_agent_id, workspace, ttl_seconds=DEFAULT_TTL_SECONDS):
    """Puertos acquire/release sobre el registro de coordinacion REAL.

    `CoordinationStore.apply` exige `expected_version` (concurrencia optimista) y
    devuelve el ESTADO publico, no el ticket: el lease se localiza despues por
    (owner, task_id). Los tickets son cooperativos — lo dice el propio modulo — asi que
    esto coordina clientes que colaboran, no impide que un editor externo escriba.
    """
    if not hasattr(store, "apply") or not hasattr(store, "public"):
        raise OrchestratorError("store: se requiere un CoordinationStore.")
    owner_agent_id = str(owner_agent_id).strip()
    if not owner_agent_id:
        raise OrchestratorError("owner_agent_id: se requiere texto.")
    workspace = coordination.normalize_workspace(workspace)

    def acquire(task_id, paths, base_sha):
        state = store.apply("lease-acquire", {
            "owner_agent_id": owner_agent_id, "task_id": task_id, "workspace": workspace,
            "paths": list(paths), "base_sha": base_sha, "ttl_seconds": ttl_seconds,
            "expected_version": store.public()["version"]})
        row = _active_lease(state, owner_agent_id, task_id)
        if not row:
            raise OrchestratorError("lease-acquire no devolvio un ticket activo para %r." % task_id)
        return row

    def release(lease_id):
        # `CoordinationStore.apply` exige task_id para TODAS las acciones (no solo para
        # adquirir), y el puerto del scheduler solo recibe el lease_id. Se busca el
        # ticket en el estado publico en vez de guardar un mapa propio: asi el puerto
        # sigue siendo sin estado y no puede desincronizarse.
        state = store.public()
        row = next((r for r in state.get("leases", [])
                    if (r.get("id") or r.get("lease_id")) == lease_id), None)
        if row is None:
            raise OrchestratorError("release: ticket desconocido: %r." % (lease_id,))
        store.apply("lease-release", {"owner_agent_id": owner_agent_id, "task_id": row["task_id"],
                                      "lease_id": lease_id, "expected_version": state["version"]})
        return None

    return acquire, release


# ---------------------------------------------------------------- despacho

def no_runtime_dispatch(task_id, agent_ref, lease_id):
    """Puerto de despacho por defecto: NO simula nada. Lo dice y para."""
    raise NoRuntimeError("no hay runtime de AgentTeams/DSH en este arbol: el envio de planes "
                         "lanza CAPABILITY_UNAVAILABLE en engine/dsh_connection.py:303-304. "
                         "El nodo %r NO se despacha." % task_id)


# ---------------------------------------------------------------- el bucle

def _state_signature(run):
    return tuple((node.task_id, node.state, node.lease_id, node.attempt) for node in run.nodes)


def drive(run, *, dispatch=None, poll=None, gate_ready, now, acquire=None, release=None,
          base_sha=None, max_steps=MAX_STEPS):
    """Conduce el bucle hasta un estado terminal o hasta que deje de avanzar.

    `poll(task_id)` devuelve 'passed', 'failed' o None (aun corriendo). Sin runtime,
    `dispatch` por defecto lanza NoRuntimeError y el bucle termina en BLOCKED sin
    afirmar nada.

    Termina por PROGRESO: si un tick no cambia el run y quedan nodos sin terminar,
    para. Nunca convierte 'not_run' ni 'pending' en 'passed'.
    """
    if not isinstance(run, scheduler.Run):
        raise OrchestratorError("run: se requiere un Run del scheduler.")
    if not callable(gate_ready):
        raise OrchestratorError("gate_ready: se requiere un puerto invocable.")
    dispatch = dispatch or no_runtime_dispatch
    poll = poll or (lambda task_id: None)
    now = str(now).strip()
    if not now:
        raise OrchestratorError("now: se requiere texto.")
    if type(max_steps) is not int or not 1 <= max_steps <= MAX_STEPS:
        raise OrchestratorError("max_steps: entero 1..%d." % MAX_STEPS)

    events, steps = [], 0
    for _ in range(max_steps):
        before = _state_signature(run)
        run, tick = scheduler.step(run, dispatch=dispatch, gate_ready=gate_ready, now=now)
        events.extend(tick)
        steps += 1

        # Cerrar lo que el runtime haya confirmado. `poll` es lo unico que puede
        # convertir un 'running' en terminal, y solo devolviendo el veredicto.
        for node in list(run.nodes):
            if node.state != "running":
                continue
            verdict = poll(node.task_id)
            if verdict in ("passed", "failed"):
                run = scheduler.complete(run, node.task_id, result=verdict, now=now, release=release)
                events.append(("COMPLETED", node.task_id, verdict))

        if _state_signature(run) == before:
            return _report(run, events, steps, "NO_PROGRESS", now)
        report = scheduler.inspect_run(run)
        if report["running"] == 0 and report["pending"] == 0 and report["not_run"] == 0:
            return _report(run, events, steps, "TERMINAL", now)

    return _report(run, events, steps, "MAX_STEPS", now)


def _report(run, events, steps, stopped_because, now):
    report = scheduler.inspect_run(run)
    report.update({
        "schema_version": SCHEMA_VERSION,
        "stopped_because": stopped_because,
        "steps": steps,
        "events": [list(event) for event in events],
        "event_count": len(events),
        "finished_at": now,
        "runtime_verified": False,
        "executed_here": False,
        "note": ("El orquestador CONDUCE el bucle; no instala, no activa y no acredita runtime. "
                 "Cualquier nodo que no este 'passed' lo esta por una razon registrada."),
    })
    report["events_sha256"] = _digest(report["events"])
    return report


def blocked_reasons(report):
    """Motivos agrupados, para que BLOCKED no sea un misterio."""
    grouped = {}
    for code, task_id, detail in report.get("events", []):
        if code in ("GATE_BLOCKED", "DISPATCH_UNAVAILABLE", "DISPATCH_FAILED",
                    "LEASE_REQUIRED", "PENDING_NO_SLOT"):
            grouped.setdefault(code, []).append({"task": task_id, "detail": detail})
    return grouped
