"""team_for_spec.py - de ReplicationSpec a equipo de agentes.

EL BORRADOR NO FUNCIONABA: `if m in roster` comparaba nombres de DUENO
(security_auditor, qa_test_engineer) contra nombres de SEED (CEO, SECURITY, QA).
Nunca casaba y el equipo salia sin mandatorios.

Aqui el indice dueno->seed se construye con dos senales:
  a) un seed cuyo NOMBRE es el dueno (los 10 gaps),
  b) un seed que declara cubre:<dueno> en su acceptance (los 32 cargos).
Cuando varios candidatos, gana el MAS ESPECIFICO (el que declara menos duenos),
que es lo que evita que CEO absorba security_auditor.

parity_verifier NO es un seed del roster: es un rol por replicacion. Se emite
como perfil sintetico para no mover MAX_AGENTS otra vez.
"""
from __future__ import annotations
import re
from typing import Dict, List, Mapping, Optional, Set, Tuple

if __package__:
    from .extension_owners import EXTENSION_OWNER, owner_of
    from .seeds_reconciled import ROLE_SEEDS_RECONCILED
else:
    from extension_owners import EXTENSION_OWNER, owner_of
    from seeds_reconciled import ROLE_SEEDS_RECONCILED

# Overrides CURADOS, a la vista. La inferencia de duenos sobre los 32 cargos es
# heuristica y en estos casos elige mal (design_systems caia en AI porque el
# generador le dio a cada seed el destino de TODOS los duenos que reclama, y el
# solapamiento queda degenerado). No se esconde: se declara y se valida abajo.
OVERRIDES: Dict[str, str] = {
    "design_systems": "FRONTEND",
    "mev_engineer": "QUANT",
    "risk_sizing_engineer": "ASSURANCE",
}

MANDATORY_OWNERS: Tuple[str, ...] = ("security_auditor", "qa_test_engineer")

PARITY_VERIFIER: Mapping[str, object] = {
    "name": "parity_verifier",
    "role": "Parity Verifier",
    "goal": "Comprobar que la replica coincide con la spec en las 4 dimensiones",
    "destination": (".json",),
    "skill_bundle": "parity_pack",
    "acceptance": ("parity_routes", "parity_contracts",
                   "parity_capabilities", "parity_assets"),
    "_synthetic": True,
}


def _tokens(texto: str) -> Set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", texto.lower()) if t}


def owner_index() -> Dict[str, str]:
    """dueno -> nombre del seed que mejor lo cubre.

    Orden de preferencia (el primero gana):
      1) solapamiento de TOKENS entre el nombre del seed y el del dueno
         (SECURITY vs security_auditor comparte 'security'; BUILD no comparte
         nada y por eso no debe ganar aunque declare menos duenos),
      2) nombre de seed == dueno (los 10 gaps),
      3) menos duenos declarados (el mas especifico).
    """
    # extensiones que posee cada dueno, para cruzar con el DESTINO del seed
    propias: Dict[str, Set[str]] = {}
    for ext, owner in EXTENSION_OWNER.items():
        propias.setdefault(owner, set()).add(ext)

    candidatos: Dict[str, List[Tuple[int, int, int, int, str]]] = {}
    for seed in ROLE_SEEDS_RECONCILED:
        declarados = [a[6:] for a in seed.acceptance if a.startswith("cubre:")]
        for owner in set(declarados) | {seed.name}:
            exacto = 0 if seed.name == owner else 1
            # senal fuerte: el destino del seed toca las extensiones del dueno
            dest_overlap = len(set(seed.destination) & propias.get(owner, set()))
            tok_overlap = len(_tokens(seed.name) & _tokens(owner))
            candidatos.setdefault(owner, []).append(
                (exacto, -dest_overlap, -tok_overlap, len(declarados), seed.name))
    indice = {owner: sorted(c)[0][4] for owner, c in candidatos.items()}
    nombres = {seed.name for seed in ROLE_SEEDS_RECONCILED}
    for owner, destino in OVERRIDES.items():
        if destino not in nombres:
            raise ValueError("override apunta a un seed inexistente: %s" % destino)
        indice[owner] = destino
    return indice


def _perfil(seed, spec, extra_acceptance=()):
    return {
        "name": seed.name,
        "role": seed.role,
        "goal": "%s | replica de %s" % (seed.goal, spec.url),
        "destination": list(seed.destination),
        "acceptance": list(seed.acceptance) + list(extra_acceptance),
        "skill_bundle": seed.skill_bundle,
    }


def build_team(spec) -> List[dict]:
    """Fail-closed: si un destino exigido no tiene dueno o seed, se levanta."""
    roster = {s.name: s for s in ROLE_SEEDS_RECONCILED}
    idx = owner_index()

    needed = set()
    sin_dueno = []
    for dest in spec.required_destinations:
        o = owner_of(dest)
        if not o:
            sin_dueno.append(dest)
            continue
        needed.add(o)
    if sin_dueno:
        raise ValueError("destinos sin dueno en el mapa: %s" % ", ".join(sin_dueno))

    faltan = sorted(o for o in needed if o not in idx)
    if faltan:
        raise ValueError("duenos exigidos sin seed en el roster: %s" % ", ".join(faltan))

    nombres, perfiles, vistos = [], [], set()
    for owner in sorted(needed):
        nombre = idx[owner]
        if nombre in vistos:
            continue
        vistos.add(nombre)
        nombres.append(owner)
        perfiles.append(_perfil(
            roster[nombre], spec,
            ["paridad:%s" % t for t in spec.parity_targets] +
            ["cubre:%s" % owner]))

    for owner in MANDATORY_OWNERS:
        nombre = idx.get(owner)
        if nombre and nombre not in vistos:
            vistos.add(nombre)
            perfiles.append(_perfil(roster[nombre], spec,
                                    ["paridad:%s" % t for t in spec.parity_targets]))

    perfiles.append(dict(PARITY_VERIFIER, acceptance=list(PARITY_VERIFIER["acceptance"]) +
                         ["paridad:%s" % t for t in spec.parity_targets]))
    return perfiles


if __name__ == "__main__":
    if __package__:
        from .site_rea import ReplicationSpec
    else:
        from site_rea import ReplicationSpec
    spec = ReplicationSpec(url="https://x", required_destinations=(".py", ".css"))
    team = build_team(spec)
    nombres = [p["name"] for p in team]
    assert "parity_verifier" in nombres, nombres
    assert len(nombres) == len(set(nombres)), "duplicados: %s" % nombres
    idx = owner_index()
    assert idx["security_auditor"] == "SECURITY", idx["security_auditor"]
    assert idx["qa_test_engineer"] == "QA", idx["qa_test_engineer"]
    assert idx["python_engineer"] == "python_engineer"
    print("OK team_for_spec: %d agentes, parity_verifier sintetico, indice especifico"
          % len(team))
