"""dna_extractor.py - destila una fuente a ADN, con CADA afirmacion citando evidencia real.

LO QUE ESTE MODULO NO HACE, y es deliberado:
  - No promete "2000%", "20x" ni "brutal". Un multiplicador de capacidad no es
    medible ni falsable, y sin falsacion no hay gate. Ese lenguaje se queda fuera.
  - No inventa contenido: la unica fuente de verdad es la superficie ya barrida mas
    el arbol de rutas reales del objetivo.

LA REGLA DURA: cada afirmacion (mental_model, primitive, pattern, anti_pattern)
debe citar al menos una ruta, y TODA ruta citada debe existir en el arbol. Una
sola cita inventada invalida el ADN entero: es preferible un ADN incompleto y
honesto a uno completo y falso.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence, Set, Tuple


class DnaError(Exception):
    """El ADN no se puede sostener con evidencia."""


CAMPOS = ("mental_models", "primitives", "patterns", "anti_patterns")
MIN_CITAS = 1


@dataclass(frozen=True)
class DnaClaim:
    text: str
    evidence: Tuple[str, ...]


@dataclass(frozen=True)
class DnaProfile:
    source_id: str
    source_type: str
    core_claim: DnaClaim
    claims: Mapping[str, Tuple[DnaClaim, ...]] = field(default_factory=dict)

    @property
    def total_citas(self) -> int:
        return len(self.core_claim.evidence) + sum(
            len(c.evidence) for grupo in self.claims.values() for c in grupo)

    def paths(self) -> Set[str]:
        out = set(self.core_claim.evidence)
        for grupo in self.claims.values():
            for c in grupo:
                out.update(c.evidence)
        return out


def _texto(valor, limite=400) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()[:limite]


def build_prompt(source_id: str, surface_text: str, rutas: Sequence[str]) -> str:
    """Prompt con esquema cerrado. Se le prohibe citar lo que no esta en la lista."""
    return json.dumps({
        "tarea": "destilar_adn",
        "fuente": source_id,
        "reglas": [
            "Toda afirmacion debe citar al menos una ruta de RUTAS_VALIDAS.",
            "Citar una ruta que no este en RUTAS_VALIDAS invalida toda la respuesta.",
            "No atribuyas capacidades cuantificadas (porcentajes, multiplicadores).",
        ],
        "RUTAS_VALIDAS": list(rutas)[:200],
        "salida": {
            "core_claim": {"text": "la esencia irreducible", "evidence": ["ruta"]},
            "mental_models": [{"text": "...", "evidence": ["ruta"]}],
            "primitives": [{"text": "...", "evidence": ["ruta"]}],
            "patterns": [{"text": "...", "evidence": ["ruta"]}],
            "anti_patterns": [{"text": "...", "evidence": ["ruta"]}],
        },
        "CONTENIDO": surface_text[:24000],
    }, ensure_ascii=False, sort_keys=True)


def _claim(bruto, campo: str, rutas: Set[str]) -> DnaClaim:
    if not isinstance(bruto, dict):
        raise DnaError("%s: se esperaba un objeto con text/evidence" % campo)
    texto = _texto(bruto.get("text"))
    if not texto:
        raise DnaError("%s: afirmacion vacia" % campo)
    ev = bruto.get("evidence")
    if not isinstance(ev, list) or not ev:
        raise DnaError("%s: sin evidencia ('%s')" % (campo, texto[:50]))
    citas = []
    for p in ev:
        if not isinstance(p, str) or not p.strip():
            raise DnaError("%s: cita vacia" % campo)
        if p not in rutas:
            raise DnaError("%s: cita INVENTADA '%s' (no existe en el arbol)" % (campo, p))
        citas.append(p)
    return DnaClaim(texto, tuple(sorted(set(citas))))


def parse_and_validate(source_id: str, source_type: str, resposta: str,
                       rutas: Iterable[str]) -> DnaProfile:
    """Valida o levanta. No hay 'casi vale': una cita inventada invalida el ADN."""
    validas = set(rutas)
    m = re.search(r"\{.*\}", resposta or "", re.S)
    if not m:
        raise DnaError("respuesta sin JSON")
    try:
        dados = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise DnaError("JSON invalido: %s" % exc)

    core = _claim(dados.get("core_claim"), "core_claim", validas)
    grupos = {}
    for campo in CAMPOS:
        itens = dados.get(campo, [])
        if not isinstance(itens, list):
            raise DnaError("%s: se esperaba lista" % campo)
        grupos[campo] = tuple(_claim(i, "%s[%d]" % (campo, k), validas)
                              for k, i in enumerate(itens))
    if not any(grupos.values()):
        raise DnaError("ADN vacio: ninguna afirmacion respaldada")
    return DnaProfile(source_id, source_type, core, grupos)


def extract(surface, rutas: Iterable[str], llm: Callable[[str], str],
            surface_text: str = "") -> DnaProfile:
    """Extrae ADN. El LLM se INYECTA: este modulo no gasta ni elige proveedor."""
    if not callable(llm):
        raise DnaError("falta el llamador LLM; no se inventa uno")
    validas = tuple(sorted(set(rutas)))
    if not validas:
        raise DnaError("sin rutas validas no hay nada que citar")
    prompt = build_prompt(surface.source_id, surface_text, validas)
    return parse_and_validate(surface.source_id, surface.source_type.value,
                              llm(prompt), validas)


if __name__ == "__main__":
    rutas = {"package.json", "backend/Cargo.toml"}
    ok = json.dumps({"core_claim": {"text": "espina", "evidence": ["package.json"]},
                     "primitives": [{"text": "crate", "evidence": ["backend/Cargo.toml"]}]})
    p = parse_and_validate("x", "git", ok, rutas)
    assert p.total_citas == 2 and p.paths() == rutas

    malo = json.dumps({"core_claim": {"text": "espina", "evidence": ["inventada.ts"]}})
    try:
        parse_and_validate("x", "git", malo, rutas)
        raise SystemExit("FALLO: cita inventada debio rechazarse")
    except DnaError as e:
        assert "INVENTADA" in str(e)

    sin_ev = json.dumps({"core_claim": {"text": "espina", "evidence": []}})
    try:
        parse_and_validate("x", "git", sin_ev, rutas)
        raise SystemExit("FALLO: afirmacion sin evidencia debio rechazarse")
    except DnaError:
        pass

    assert "2000" not in build_prompt("x", "", rutas)
    assert "multiplicadores" in build_prompt("x", "", rutas)
    print("OK dna_extractor: %d citas validadas, cita inventada rechazada, sin metricas inventadas"
          % p.total_citas)
