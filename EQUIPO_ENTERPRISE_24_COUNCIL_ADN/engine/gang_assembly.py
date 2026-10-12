"""Ensbla el gang: los N ADN se fusionan en UN artefacto sellado y ordenado.

El gang no es una lista suelta: es un grafo. Cada agente sabe quien lo supervisa
(`reports_to`) y a quien supervisa (`direct_reports`). El ensamblado:

    1. valida los invariantes (N exacto, ids unicos, slots completos, jefes reales),
    2. resuelve el grafo de supervision y RECHAZA ciclos y huerfanos,
    3. ordena topologicamente (el jefe va antes que su gente; desempate por slot),
    4. sella el artefacto con SHA-256 y le pone version y changelog contra el
       artefacto anterior del mismo proyecto.

Fail-closed: un gang con un agente desconectado o un ciclo NO se ensambla. Eso es lo
que evita publicar un equipo que no se habla entre si.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = "gang-assembly-1.0"
ROOT = "OWNER_EXTERNAL"


class AssemblyError(ValueError):
    """El gang no se puede ensamblar tal como esta."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _compact(agent):
    """La vista minima del agente que viaja en el artefacto (y que detecta cambios)."""
    return {"slot": agent.get("slot"), "id": agent.get("id"), "name": agent.get("name"),
            "role": agent.get("role"), "reports_to": agent.get("reports_to"),
            "display_name": agent.get("display_name")}


def topological_order(agents):
    """Jefes antes que subordinados; desempate determinista por slot.

    Kahn sobre las aristas jefe -> subordinado. Un ciclo se detecta porque quedan
    nodos sin emitir; un huerfano porque nunca es alcanzado desde ROOT.
    """
    by_id = {a["id"]: a for a in agents}
    children = {ROOT: []}
    children.update({a["id"]: [] for a in agents})
    indegree = {a["id"]: 0 for a in agents}
    for agent in agents:
        jefe = agent.get("reports_to")
        if jefe == ROOT:
            children[ROOT].append(agent["id"])      # arista de raiz: no genera indegree
        elif jefe in by_id:
            children[jefe].append(agent["id"])      # arista interna: jefe antes que subordinado
            indegree[agent["id"]] += 1
    # Raices: sin jefe dentro del grafo (ROOT o externo). Determinista por slot.
    frontera = sorted([a["id"] for a in agents if indegree[a["id"]] == 0],
                      key=lambda i: (by_id[i].get("slot") or 0, i))
    orden, vistos = [], set()
    while frontera:
        actual = frontera.pop(0)
        orden.append(actual)
        vistos.add(actual)
        for sub in sorted(children[actual], key=lambda i: (by_id[i].get("slot") or 0, i)):
            indegree[sub] -= 1
            if indegree[sub] == 0:
                frontera.append(sub)
        frontera.sort(key=lambda i: (by_id[i].get("slot") or 0, i))
    if len(orden) != len(agents):
        ciclo = sorted(set(by_id) - vistos)
        raise AssemblyError("hierarchy_cycle",
                            "Ciclo en la jerarquia: estos agentes se supervisan en circulo: %s."
                            % ", ".join(ciclo[:6]))
    # Huerfanos: nadie llega a ellos desde ROOT siguiendo la supervision.
    alcanzables, cola = set(), [ROOT]
    while cola:
        actual = cola.pop()
        for sub in children.get(actual, ()):
            if sub not in alcanzables:
                alcanzables.add(sub)
                cola.append(sub)
    huerfanos = sorted(set(by_id) - alcanzables)
    if huerfanos:
        raise AssemblyError("orphan_agents",
                            "Agentes desconectados de la jerarquia (nadie los supervisa desde la raiz): %s."
                            % ", ".join(by_id[i].get("name", i) for i in huerfanos[:6]))
    return orden


def assemble(organization, previous=None):
    """Fusiona la organizacion en el artefacto sellado del gang.

    `previous` es el artefacto anterior (o None): con el se calculan version y
    changelog (agregados / quitados / cambiados). Devuelve (artefacto, sha256).
    """
    if not isinstance(organization, dict) or not isinstance(organization.get("agents"), list) \
            or not organization["agents"]:
        raise AssemblyError("no_organization", "No hay organizacion que ensamblar.")
    agents = organization["agents"]
    config = organization.get("config") or {}
    total = config.get("agent_count")
    if isinstance(total, int) and total != len(agents):
        raise AssemblyError("count_mismatch",
                            "La organizacion declara %d agentes y trae %d." % (total, len(agents)))
    ids = [a.get("id") for a in agents]
    if any(not isinstance(i, str) or not i for i in ids):
        raise AssemblyError("invalid_id", "Hay agentes sin id valido.")
    if len(set(ids)) != len(ids):
        raise AssemblyError("duplicate_id", "Hay ids de agente duplicados.")
    slots = sorted(a.get("slot") for a in agents if isinstance(a.get("slot"), int))
    if slots != list(range(1, len(agents) + 1)):
        raise AssemblyError("invalid_slots", "Los slots no son 1..N completos: %s." % slots[:8])
    conocidos = set(ids) | {ROOT}
    for agent in agents:
        if agent.get("reports_to") not in conocidos:
            raise AssemblyError("unknown_supervisor",
                                "%s reporta a un jefe que no existe: %r." % (agent.get("name"), agent.get("reports_to")))

    orden = topological_order(agents)
    by_id = {a["id"]: _compact(a) for a in agents}

    prev_version = 0
    changelog = {"added": sorted(by_id), "removed": [], "changed": []}
    previous_sha = None
    if isinstance(previous, dict):
        manifest = previous.get("manifest") or {}
        prev_version = manifest.get("version") or 0
        previous_sha = manifest.get("sha256")
        prev_agents = {row["id"]: row for row in previous.get("agentes") or []}
        changelog = {"added": sorted(set(by_id) - set(prev_agents)),
                     "removed": sorted(set(prev_agents) - set(by_id)),
                     "changed": sorted(i for i in set(by_id) & set(prev_agents) if by_id[i] != prev_agents[i])}

    # Idempotente: si el gang no cambio (sin altas, bajas ni cambios), el artefacto
    # ES el anterior — mismo sello, misma version. La version solo sube cuando el
    # gang cambia de verdad; re-ensamblar lo mismo no puede divergir el hash.
    if isinstance(previous, dict) and previous.get("manifest", {}).get("sha256") \
            and not (changelog["added"] or changelog["removed"] or changelog["changed"]):
        return previous, previous["manifest"]["sha256"]

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "contrato": {"agent_count": len(agents), "template": config.get("template"),
                     "provider": config.get("provider"), "model": config.get("model"),
                     "invariantes": ["N exacto y slots 1..N", "ids unicos", "jerarquia sin ciclos",
                                     "ningun agente huerfano", "jefes reales"]},
        "orden": orden,
        "agentes": [by_id[i] for i in orden],
        "manifest": {"total": len(agents), "version": prev_version + 1,
                     "changelog": changelog, "previous_sha256": previous_sha},
    }
    sha = _digest(artifact)
    artifact["manifest"]["sha256"] = sha
    return artifact, sha
