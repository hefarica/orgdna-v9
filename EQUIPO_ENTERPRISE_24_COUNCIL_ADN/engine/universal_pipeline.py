"""universal_pipeline.py - de CUALQUIER superficie observable a equipo de agentes.

DOS COSAS QUE NO HACE, a diferencia del borrador:

1) No compara nombres de DUENO contra nombres de SEED. Eso dejaba el equipo casi
   vacio. Usa owner_index() de team_for_spec, que resuelve dueno->seed con tres
   senales y overrides curados.

2) No traga capacidades desconocidas. Una capacidad sin mapeo se DECLARA en
   unmapped; una que mapea a un dueno sin seed levanta ValueError. El borrador
   hacia `if name in roster` y seguia como si nada.
"""
from __future__ import annotations
from typing import Dict, List, Mapping, Set, Tuple

if __package__:
    from .extension_owners import owner_of
    from .seeds_reconciled import ROLE_SEEDS_RECONCILED
    from .team_for_spec import PARITY_VERIFIER, owner_index
else:
    from extension_owners import owner_of
    from seeds_reconciled import ROLE_SEEDS_RECONCILED
    from team_for_spec import PARITY_VERIFIER, owner_index


# capacidad observada -> dueno real del mapa (nombres que EXISTEN)
CAPACIDAD_A_DUENO: Dict[str, str] = {
    "onchain": "solidity_engineer",
    "swap": "mev_engineer",
    "mev": "mev_engineer",
    "strategy_cartridges": "cartridge_engineer",
    "auth": "security_auditor",
    "frontend": "design_systems",
    "nav": "design_systems",
    "form": "design_systems",
    "chart": "design_systems",
    "editor": "design_systems",
    "automation": "posix_automation",
    "payment": "python_engineer",
    "payments": "python_engineer",
    "realtime": "python_engineer",
    "websocket": "python_engineer",
    "upload": "python_engineer",
    "checkout": "data_engineer",
    "search": "data_engineer",
    "table": "data_engineer",
    "nft": "solidity_engineer",
    "staking": "solidity_engineer",
}

MANDATORIOS: Tuple[str, ...] = ("security_auditor", "qa_test_engineer")


def adaptar(surface) -> Tuple[List[dict], Dict[str, object]]:
    """superficie -> (perfiles, diagnostico). Fail-closed ante dueno sin seed."""
    roster = {s.name: s for s in ROLE_SEEDS_RECONCILED}
    idx = owner_index()

    duenos: Set[str] = set()
    for ext in surface.extensions():
        o = owner_of(ext)
        if o:
            duenos.add(o)

    sin_mapeo = sorted(c for c in surface.capabilities if c not in CAPACIDAD_A_DUENO)
    for cap in sorted(surface.capabilities):
        dueno = CAPACIDAD_A_DUENO.get(cap)
        if dueno:
            duenos.add(dueno)

    irresolubles = sorted(o for o in duenos if o not in idx)
    if irresolubles:
        raise ValueError("duenos sin seed resoluble: %s" % ", ".join(irresolubles))

    perfiles, vistos = [], set()
    for dueno in sorted(duenos):
        nombre = idx[dueno]
        if nombre in vistos:
            continue
        vistos.add(nombre)
        s = roster[nombre]
        perfiles.append({
            "name": s.name, "role": s.role,
            "goal": "%s | replica de %s" % (s.goal, surface.source_id),
            "destination": list(s.destination),
            "acceptance": list(s.acceptance) + ["parity_verified", "cubre:%s" % dueno],
            "skill_bundle": s.skill_bundle,
        })

    for dueno in MANDATORIOS:
        nombre = idx.get(dueno)
        if nombre and nombre not in vistos:
            vistos.add(nombre)
            s = roster[nombre]
            perfiles.append({
                "name": s.name, "role": s.role, "goal": s.goal,
                "destination": list(s.destination),
                "acceptance": list(s.acceptance) + ["parity_verified"],
                "skill_bundle": s.skill_bundle,
            })

    perfiles.append(dict(PARITY_VERIFIER,
                         acceptance=list(PARITY_VERIFIER["acceptance"]) + ["parity_verified"]))

    diagnostico = {
        "source_type": surface.source_type.value,
        "source_id": surface.source_id,
        "fingerprint": surface.structure_fingerprint,
        "puntos": len(surface.points),
        "extensiones": len(surface.extensions()),
        "duenos": sorted(duenos),
        "capacidades_sin_mapeo": sin_mapeo,
        "desconocidas_declaradas": list(surface.unknowns),
        "confianza": surface.confidence,
    }
    return perfiles, diagnostico


def replicar(driver, target: str, *, dry_run: bool = True, consent_cap: int = 12,
             verified_cap: int = 393216, per_profile_tokens: int = 7753,
             dispatch=None):
    """superficie -> equipo -> forge (dry_run por defecto). NO sella."""
    from engine.forge_loop import forge
    from engine.evidence_harness import for_agent

    surface = driver.scan_surface(target)
    perfiles, diag = adaptar(surface)

    class _Censo:
        extensions = {e: 1 for e in surface.extensions()} or {".md": 1}

    res = forge(profiles=perfiles, miner_report=_Censo(), consent_cap=consent_cap,
                verified_cap=verified_cap, per_profile_tokens=per_profile_tokens,
                dispatch=dispatch, harness_for=for_agent, dry_run=dry_run)
    return {"surface": surface, "perfiles": perfiles, "diagnostico": diag, "result": res}


if __name__ == "__main__":
    if __package__:
        from .sources.universal_base import AppSurface, SourceType, SurfacePoint
    else:
        import os as _o, sys as _s
        _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
        from sources.universal_base import AppSurface, SourceType, SurfacePoint

    s = AppSurface(SourceType.WEB, "https://x",
                   (SurfacePoint("/a", "route"), SurfacePoint("a.css", "asset")),
                   capabilities={"form", "auth", "cap_desconocida"},
                   assets={"a.css"}, confidence=0.8)
    perfiles, diag = adaptar(s)
    nombres = [p["name"] for p in perfiles]
    assert "parity_verifier" in nombres
    assert len(nombres) == len(set(nombres))
    assert "cap_desconocida" in diag["capacidades_sin_mapeo"], "debe declararse"
    assert diag["fingerprint"]
    print("OK universal_pipeline: %d perfiles, %d sin mapeo declaradas"
          % (len(perfiles), len(diag["capacidades_sin_mapeo"])))
