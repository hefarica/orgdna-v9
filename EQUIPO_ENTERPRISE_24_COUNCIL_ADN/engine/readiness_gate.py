"""Puerta de preflight: el agente no arranca hasta tener TODAS las herramientas.

Pura. Devuelve bloqueos y siguientes acciones deterministas; el llamador las ejecuta
y vuelve a evaluar (bucle hasta ready). ready NO acredita ejecucion ni instalacion.
"""
from __future__ import annotations

SCHEMA_VERSION = "readiness-gate-1.0"


def evaluate(tool_needs, allow, deny, catalog_names, capability_gaps=(), waivers=None):
    for name, value in (("tool_needs", tool_needs), ("allow", allow), ("deny", deny), ("catalog_names", catalog_names)):
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"{name}: se requiere lista.")
    needs = list(tool_needs)
    if len(set(needs)) != len(needs):
        raise ValueError("tool_needs: duplicados.")
    catalog, allowed, denied = set(catalog_names), set(allow), set(deny)
    waivers = dict(waivers or {})
    blocked, satisfied, waived = [], [], []
    for name in needs:
        if name not in catalog:
            blocked.append({"code": "tool_missing_from_catalog", "tool": name})
        elif name in denied:
            blocked.append({"code": "tool_denied", "tool": name})
        elif name not in allowed:
            blocked.append({"code": "tool_not_allowed", "tool": name})
        else:
            satisfied.append(name)
    for gap in capability_gaps:
        if gap in waivers and str(waivers[gap]).strip():
            waived.append(gap)
        else:
            blocked.append({"code": "gap_unresolved", "gap": gap})
    blocked.sort(key=lambda b: (b["code"], b.get("tool") or b.get("gap")))
    # OJO: un dict literal como switch se evalua ENTERO antes de indexar, asi que
    # `item["gap"]` reventaba con KeyError en el primer bloqueo de herramienta:
    # la puerta fallaba exactamente cuando tenia que bloquear. Se usa if/elif.
    actions = []
    for item in blocked:
        code = item["code"]
        if code == "tool_missing_from_catalog":
            actions.append("importar al catálogo: " + item["tool"])
        elif code == "tool_not_allowed":
            actions.append("añadir a allow: " + item["tool"])
        elif code == "tool_denied":
            actions.append("quitar de deny: " + item["tool"])
        elif code == "gap_unresolved":
            actions.append("resolver o eximir el hueco: " + item["gap"])
        else:
            raise ValueError("readiness_gate: código de bloqueo desconocido: " + str(code))
    warnings = [] if needs else ["no_tools_declared: sin tool_needs no hay preflight demostrable."]
    return {"schema_version": SCHEMA_VERSION, "ready": not blocked, "blocked_by": blocked,
            "satisfied": satisfied, "waived": waived, "next_actions": actions, "warnings": warnings,
            "runtime_verified": False, "installed": False,
            "note": "ready sólo acredita nombres en catálogo y allow; nada se instala aquí."}
