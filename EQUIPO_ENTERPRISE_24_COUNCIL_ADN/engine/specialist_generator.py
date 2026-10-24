"""specialist_generator.py - especialistas derivados del ADN, sin metricas inventadas.

NO HAY "2000%", "20x" ni "depth=20.0". Un especialista no es mas capaz por
declararlo: es mas capaz si sus capacidades se pueden comprobar. Aqui la unica
medida es COBERTURA: cuantas afirmaciones del ADN honra y con que evidencia.

REGLA DURA: una capacidad que cite una ruta ausente del ADN se rechaza. El
especialista no puede saber mas de lo que su ADN puede probar.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence, Set, Tuple


class SpecialistError(Exception):
    pass


@dataclass(frozen=True)
class Capability:
    text: str
    evidence: Tuple[str, ...]


@dataclass(frozen=True)
class Specialist:
    name: str
    competency: str
    capabilities: Tuple[Capability, ...]
    blind_spots: Tuple[str, ...]
    dna_source: str

    @property
    def cobertura(self) -> int:
        return sum(len(c.evidence) for c in self.capabilities)

    def paths(self) -> Set[str]:
        out = set()
        for c in self.capabilities:
            out.update(c.evidence)
        return out


def build_prompt(dna, max_capabilities: int = 6) -> str:
    return json.dumps({
        "tarea": "especialista_desde_adn",
        "adn_fuente": dna.source_id,
        "esencia": dna.core_claim.text,
        "RUTAS_DEL_ADN": sorted(dna.paths())[:200],
        "reglas": [
            "Toda capacidad debe citar rutas de RUTAS_DEL_ADN.",
            "Prohibido cuantificar la mejora (porcentajes, multiplicadores, 'x veces').",
            "Declara puntos ciegos: lo que este especialista NO cubre.",
        ],
        "max_capacidades": max_capabilities,
        "salida": {"name": "...", "competency": "...",
                   "capabilities": [{"text": "...", "evidence": ["ruta"]}],
                   "blind_spots": ["..."]},
    }, ensure_ascii=False, sort_keys=True)


_NUM_CLAIM = re.compile(r"\b\d+\s*(?:%|x\b|veces)|\b\d{3,}%", re.I)


def _sin_metrica_inventada(texto: str) -> None:
    if _NUM_CLAIM.search(texto or ""):
        raise SpecialistError(
            "capacidad con mejora cuantificada sin artefacto: '%s'. "
            "Un multiplicador no falsable no entra." % texto[:60])


def generate(dna, llm: Callable[[str], str], max_capabilities: int = 6) -> Specialist:
    if not callable(llm):
        raise SpecialistError("falta el llamador LLM; no se inventa uno")
    permitidas = dna.paths()
    if not permitidas:
        raise SpecialistError("el ADN no tiene evidencia; no puede haber especialista")
    bruto = llm(build_prompt(dna, max_capabilities))
    m = re.search(r"\{.*\}", bruto or "", re.S)
    if not m:
        raise SpecialistError("respuesta sin JSON")
    try:
        dados = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise SpecialistError("JSON invalido: %s" % exc)

    name = re.sub(r"\s+", " ", str(dados.get("name") or "")).strip()[:80]
    if not name:
        raise SpecialistError("especialista sin nombre")
    comp = re.sub(r"\s+", " ", str(dados.get("competency") or "")).strip()[:200]
    _sin_metrica_inventada(name)
    _sin_metrica_inventada(comp)

    caps = []
    for k, item in enumerate(dados.get("capabilities") or []):
        if not isinstance(item, dict):
            raise SpecialistError("capabilities[%d] no es objeto" % k)
        texto = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()[:300]
        _sin_metrica_inventada(texto)
        ev = item.get("evidence")
        if not isinstance(ev, list) or not ev:
            raise SpecialistError("capabilities[%d] sin evidencia" % k)
        for p in ev:
            if p not in permitidas:
                raise SpecialistError(
                    "capabilities[%d] cita '%s', que NO esta en el ADN: el "
                    "especialista no puede saber mas de lo que su ADN prueba" % (k, p))
        caps.append(Capability(texto, tuple(sorted(set(ev)))))
    if not caps:
        raise SpecialistError("especialista sin capacidades")

    ciegos = tuple(re.sub(r"\s+", " ", str(x)).strip()[:200]
                   for x in (dados.get("blind_spots") or []) if str(x).strip())
    return Specialist(name, comp, tuple(caps), ciegos, dna.source_id)


if __name__ == "__main__":
    from dna_extractor import parse_and_validate
    rutas = {"package.json", "backend/Cargo.toml"}
    dna = parse_and_validate("x", "git", json.dumps({
        "core_claim": {"text": "espina", "evidence": ["package.json"]},
        "primitives": [{"text": "crate", "evidence": ["backend/Cargo.toml"]}]}), rutas)

    ok = lambda p: json.dumps({"name": "Espina", "competency": "mantener la espina",
        "capabilities": [{"text": "verificar manifiestos", "evidence": ["package.json"]}],
        "blind_spots": ["no cubre contratos"]})
    s = generate(dna, ok)
    assert s.cobertura == 1 and s.blind_spots

    def fuera_del_adn(p):
        return json.dumps({"name": "X", "competency": "c",
            "capabilities": [{"text": "t", "evidence": ["contratos/Nuevo.sol"]}]})
    try:
        generate(dna, fuera_del_adn)
        raise SystemExit("FALLO: cita fuera del ADN debio rechazarse")
    except SpecialistError as e:
        assert "NO esta en el ADN" in str(e)

    def con_multiplicador(p):
        return json.dumps({"name": "Brujo 2000%", "competency": "c",
            "capabilities": [{"text": "t", "evidence": ["package.json"]}]})
    try:
        generate(dna, con_multiplicador)
        raise SystemExit("FALLO: metrica inventada debio rechazarse")
    except SpecialistError as e:
        assert "no falsable" in str(e)
    print("OK specialist_generator: cita fuera del ADN y metrica inventada rechazadas")
