"""fusion_engine.py - combina ADNs y DECLARA lo que no se puede fusionar.

NO inventa "sinergia". Una capacidad hibrida cita rutas de CUALQUIERA de las
fuentes; si cita algo que ninguna prueba, se rechaza. Y lo que no cubre se
declara en `gaps` en vez de rellenarse.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Mapping, Sequence, Set, Tuple


class FusionError(Exception):
    pass


@dataclass(frozen=True)
class HybridCapability:
    text: str
    evidence: Tuple[str, ...]
    sources: Tuple[str, ...]


@dataclass(frozen=True)
class Fusion:
    target: str
    capabilities: Tuple[HybridCapability, ...]
    gaps: Tuple[str, ...]
    sources: Tuple[str, ...]

    @property
    def citas(self) -> int:
        return sum(len(c.evidence) for c in self.capabilities)


def build_prompt(profiles, target: str) -> str:
    rutas = sorted({p for perfil in profiles for p in perfil.paths()})
    return json.dumps({
        "tarea": "fusion_adn",
        "objetivo": target,
        "fuentes": {p.source_id: sorted(p.paths()) for p in profiles},
        "RUTAS_DISPONIBLES": rutas[:300],
        "reglas": [
            "Cada capacidad hibrida debe citar rutas de RUTAS_DISPONIBLES.",
            "Si algo no se puede sostener con esas rutas, va en 'gaps'. No se rellena.",
            "Prohibido cuantificar mejora.",
        ],
        "salida": {"capabilities": [{"text": "...", "evidence": ["ruta"]}],
                   "gaps": ["que NO se puede sostener"]},
    }, ensure_ascii=False, sort_keys=True)


_NUM = re.compile(r"\b\d+\s*(?:%|x\b|veces)|\b\d{3,}%", re.I)


def fuse(profiles: Sequence, target: str, llm: Callable[[str], str]) -> Fusion:
    if not profiles:
        raise FusionError("sin ADNs no hay fusion")
    if not callable(llm):
        raise FusionError("falta el llamador LLM; no se inventa uno")
    disponibles = {p for perfil in profiles for p in perfil.paths()}
    if not disponibles:
        raise FusionError("ningun ADN aporta evidencia")

    bruto = llm(build_prompt(profiles, target))
    m = re.search(r"\{.*\}", bruto or "", re.S)
    if not m:
        raise FusionError("respuesta sin JSON")
    try:
        dados = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise FusionError("JSON invalido: %s" % exc)

    caps = []
    for k, item in enumerate(dados.get("capabilities") or []):
        if not isinstance(item, dict):
            raise FusionError("capabilities[%d] no es objeto" % k)
        texto = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()[:300]
        if _NUM.search(texto):
            raise FusionError("capacidad con mejora cuantificada sin artefacto: '%s'" % texto[:60])
        ev = item.get("evidence")
        if not isinstance(ev, list) or not ev:
            raise FusionError("capabilities[%d] sin evidencia" % k)
        for p in ev:
            if p not in disponibles:
                raise FusionError("capabilities[%d] cita '%s', ausente en TODAS las fuentes" % (k, p))
        fuentes = tuple(sorted(p.source_id for p in profiles if set(ev) & p.paths()))
        caps.append(HybridCapability(texto, tuple(sorted(set(ev))), fuentes))

    gaps = tuple(re.sub(r"\s+", " ", str(g)).strip()[:200]
                 for g in (dados.get("gaps") or []) if str(g).strip())
    if not caps:
        raise FusionError("fusion sin capacidades; no se declara exito vacio")
    return Fusion(target, tuple(caps), gaps, tuple(p.source_id for p in profiles))


if __name__ == "__main__":
    from dna_extractor import parse_and_validate
    r1 = {"package.json", "backend/Cargo.toml"}
    r2 = {"contracts/Makefile"}
    d1 = parse_and_validate("repo", "git", json.dumps({
        "core_claim": {"text": "a", "evidence": ["package.json"]},
        "primitives": [{"text": "manifest", "evidence": ["package.json"]}]}), r1)
    d2 = parse_and_validate("contratos", "git", json.dumps({
        "core_claim": {"text": "b", "evidence": ["contracts/Makefile"]},
        "primitives": [{"text": "build", "evidence": ["contracts/Makefile"]}]}), r2)

    ok = lambda p: json.dumps({"capabilities": [{"text": "unir manifiestos y build",
        "evidence": ["package.json", "contracts/Makefile"]}], "gaps": ["sin datos on-chain"]})
    f = fuse([d1, d2], "hibrido", ok)
    assert f.citas == 2 and len(f.sources) == 2 and f.gaps

    def fuera(p):
        return json.dumps({"capabilities": [{"text": "x", "evidence": ["nada/Nope.sol"]}]})
    try:
        fuse([d1, d2], "hibrido", fuera)
        raise SystemExit("FALLO: cita ausente debio rechazarse")
    except FusionError as e:
        assert "ausente en TODAS" in str(e)

    def inflado(p):
        return json.dumps({"capabilities": [{"text": "mejora 2000%", "evidence": ["package.json"]}]})
    try:
        fuse([d1, d2], "hibrido", inflado)
        raise SystemExit("FALLO: metrica inventada debio rechazarse")
    except FusionError:
        pass
    print("OK fusion_engine: fusion con fuentes cruzadas, cita ausente y metrica rechazadas")
