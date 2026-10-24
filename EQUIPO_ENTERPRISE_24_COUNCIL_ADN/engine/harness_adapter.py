"""harness_adapter.py - mide los agentes del PRODUCTO con comprobaciones reales.

EL BORRADOR NO MEDIA: hacia `if agent.get("evidence_paths"): agentic += 1;
evidence += len(paths); falsificador += 1`. Contar rutas no es una comprobacion, e
incrementar el falsificador sin ejecutarlo es fabricar un PASS.

Aqui cada comprobacion se ejecuta y tiene falsificador:
  - cita_al_menos_dos:      len(evidence_paths) >= 2
  - cita_existe_en_el_repo: TODA ruta citada existe en el arbol del objetivo
    (esta es la fuerte: detecta alucinacion de rutas)
El falsificador rompe el invariante a proposito y la comprobacion DEBE caer.
"""
from __future__ import annotations
from typing import Callable, Iterable, Mapping, Set, Tuple


def _exts(paths: Iterable[str]) -> Tuple[str, ...]:
    out = set()
    for p in paths or ():
        if isinstance(p, str) and "." in p:
            out.add("." + p.rsplit(".", 1)[1].lower())
    return tuple(sorted(out))


def adapt(agent: Mapping) -> Mapping:
    """Esquema del producto -> campos que el gate entiende. Sin inventar nombres."""
    tp = agent.get("tool_policy") or {}
    return {
        "name": agent.get("name") or agent.get("id"),
        "role": agent.get("role") or agent.get("title") or "",
        "goal": agent.get("mission") or "",
        "destination": _exts(agent.get("evidence_paths")),
        "acceptance": [str(d)[:160] for d in (agent.get("deliverables") or [])],
        "policy_pack": {
            "id": "product_tool_policy",
            "rules": {"mode": tp.get("mode"), "allow": list(tp.get("allow") or [])},
            "_non_negotiable": ["policy_pack", "acceptance"],
        },
    }


def cita_al_menos_dos(agent: Mapping) -> bool:
    return len([p for p in (agent.get("evidence_paths") or []) if isinstance(p, str) and p.strip()]) >= 2


def cita_existe_en_el_repo_factory(rutas_repo: Set[str]) -> Callable[[Mapping], bool]:
    """Cierra sobre el arbol real. Una ruta inventada hace fallar la comprobacion."""
    def check(agent: Mapping) -> bool:
        citadas = [p for p in (agent.get("evidence_paths") or []) if isinstance(p, str)]
        if not citadas:
            return False
        return all(p in rutas_repo for p in citadas)
    return check


def medir(agents, rutas_repo: Set[str]) -> dict:
    """Ejecuta las comprobaciones y SUS falsificadores. Devuelve numeros medidos."""
    existe = cita_existe_en_el_repo_factory(rutas_repo)
    filas = []
    for a in agents:
        dos = cita_al_menos_dos(a)
        real = existe(a)
        # falsificador de `real`: se inyecta una ruta inexistente y DEBE caer
        roto = dict(a, evidence_paths=list(a.get("evidence_paths") or []) + ["__ruta_inventada__.ts"])
        cae = not existe(roto)
        filas.append({"name": a.get("name"), "dos": dos, "real": real, "falsificador_cae": cae,
                      "rutas": len(a.get("evidence_paths") or [])})
    ok = [f for f in filas if f["dos"] and f["real"]]
    return {
        "agentes": len(filas),
        "agentica": len(ok),
        "evidencia_real": sum(f["rutas"] for f in ok),
        "falsificador": sum(1 for f in filas if f["falsificador_cae"]),
        "detalle": filas,
    }
