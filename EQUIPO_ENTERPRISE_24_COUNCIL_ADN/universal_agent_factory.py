"""universal_agent_factory.py - compone ADN -> especialistas -> equipo, sobre lo que EXISTE.

LO QUE ESTE MODULO NO DECLARA: no hay "20x" ni "2000%". Una capacidad esta
`implemented` solo si hay un modulo real detras que se puede llamar aqui; si falta
credencial, motor o dependencia, se declara `declared_absent` CON el bloqueo
exacto. Una tabla de 14 capacidades "activadas" donde la mitad son stubs es
inflacion de capacidad, y en este proyecto eso es un defecto, no un feature.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Mapping, Sequence, Tuple

if __package__:
    from .limits import MAX_AGENTS
    from .sources.git_driver import GitDriver
    from .sources.universal_base import SourceType, SourceUnavailable
    from .sources.web_driver import WebDriver
    from .dna_extractor import DnaError, extract
    from .specialist_generator import SpecialistError, generate
else:
    # modulo de raiz: la raiz del paquete va al path y se importa con prefijo engine.
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from engine.limits import MAX_AGENTS
    from engine.sources.git_driver import GitDriver
    from engine.sources.universal_base import SourceType, SourceUnavailable
    from engine.sources.web_driver import WebDriver
    from engine.dna_extractor import DnaError, extract
    from engine.specialist_generator import SpecialistError, generate


class FactoryError(Exception):
    pass


# --- registro HONESTO: implemented | declared_absent(+blocker) | partial(+limite)
CAPABILITIES: Dict[str, Mapping[str, str]] = {
    "REA":         {"status": "implemented", "module": "engine.site_rea / engine.sources.git_driver"},
    "FUSILAR":     {"status": "implemented", "module": "engine.rea_miner + docs/security/FUSILE_SOURCE_POLICY.md"},
    "SCRAPE":      {"status": "implemented", "module": "engine.sources.web_driver (estatico, robots.txt)"},
    "MICROSERVICE":{"status": "implemented", "module": "engine.bridge (HTTP loopback, CSRF)"},
    "EXCEL":       {"status": "partial", "module": "engine.bridge excel_call",
                    "blocker": "adaptador COM real NO ejercitado; solo doble de prueba"},
    "WEB_LOGIN":   {"status": "declared_absent", "module": "-",
                    "blocker": "no hay paso de credenciales; no se autentica"},
    "OCR":         {"status": "declared_absent", "module": "-",
                    "blocker": "no hay motor OCR en dependencias (stdlib-only)"},
    "EMAIL":       {"status": "declared_absent", "module": "-",
                    "blocker": "sin IMAP/SMTP configurado ni credencial"},
    "WHATSAPP":    {"status": "declared_absent", "module": "-",
                    "blocker": "requiere WhatsApp Business API y token"},
    "TELEGRAM":    {"status": "declared_absent", "module": "-",
                    "blocker": "requiere bot token"},
    "PPT":         {"status": "declared_absent", "module": "-",
                    "blocker": "sin libreria de presentaciones"},
    "WORD":        {"status": "declared_absent", "module": "-",
                    "blocker": "sin libreria de documentos"},
    "OBSIDIAN":    {"status": "declared_absent", "module": "-",
                    "blocker": "no hay ruta de vault configurada"},
    "SCHEDULE":    {"status": "declared_absent", "module": "engine.scheduler (existe, sin cablear)",
                    "blocker": "nada lo invoca: no hay disparador en produccion"},
}


def available() -> Tuple[str, ...]:
    return tuple(n for n, v in CAPABILITIES.items() if v["status"] == "implemented")


def absent() -> Tuple[str, ...]:
    return tuple(n for n, v in CAPABILITIES.items() if v["status"] == "declared_absent")


@dataclass(frozen=True)
class OperatorParams:
    domains: Tuple[str, ...]
    max_agents: int = 12
    mission: str = ""
    fusion_mode: bool = False
    hierarchy_depth: int = 2

    def __post_init__(self):
        if not self.domains:
            raise FactoryError("sin dominios no hay fabrica")
        if type(self.max_agents) is not int or not 1 <= self.max_agents <= MAX_AGENTS:
            raise FactoryError("max_agents debe ser 1..%d (MAX_AGENTS)" % MAX_AGENTS)


def driver_para(target: str):
    t = target.strip()
    if t.startswith(("http://", "https://")) and ("github.com" in t or "gitlab.com" in t or t.endswith(".git")):
        return GitDriver(), "git"
    if t.startswith(("http://", "https://")):
        return WebDriver(), "web"
    if os.path.isdir(t):
        return GitDriver(), "git"
    raise FactoryError(
        "fuente no soportada: %s. Hoy hay evidencia real para git y web estatica; "
        "blockchain/binario/API no tienen source_kind en la allowlist del proveedor." % t)


def plan(params: OperatorParams) -> dict:
    """Planifica SIN gastar: valida fuentes y limites, y declara capacidades."""
    fuentes = []
    for d in params.domains:
        driver, tipo = driver_para(d)
        fuentes.append({"target": d, "type": tipo})
    return {
        "dominios": fuentes,
        "max_agents": params.max_agents,
        "hierarchy_depth": params.hierarchy_depth,
        "fusion_mode": params.fusion_mode,
        "capacidades_implementadas": list(available()),
        "capacidades_ausentes": {n: CAPABILITIES[n]["blocker"] for n in absent()},
        "nota": "plan sin gasto: no se ha llamado a ningun proveedor",
    }


def build(params: OperatorParams, llm: Callable[[str], str],
          per_specialist: int = 1) -> dict:
    """Extrae ADN por dominio y genera especialistas. El LLM se INYECTA."""
    if not callable(llm):
        raise FactoryError("falta el llamador LLM; no se inventa uno")

    adns, especialistas = [], []
    for d in params.domains:
        driver, tipo = driver_para(d)
        superficie = driver.scan_surface(d)
        rutas = set(superficie.raw.get("paths") or [])
        if not rutas:
            raise FactoryError(
                "%s: la superficie no expone rutas citables; no se puede exigir evidencia" % d)
        adn = extract(superficie, rutas, llm, surface_text=" ".join(sorted(rutas)[:200]))
        adns.append(adn)
        for _ in range(max(1, per_specialist)):
            especialistas.append(generate(adn, llm))

    total = min(params.max_agents, len(especialistas))
    return {
        "fuentes": [a.source_id for a in adns],
        "adns": len(adns),
        "citas_adn": sum(a.total_citas for a in adns),
        "especialistas_generados": len(especialistas),
        "especialistas_usados": total,
        "cobertura_verificada": sum(s.cobertura for s in especialistas[:total]),
        "capacidades_implementadas": list(available()),
        "capacidades_ausentes": {n: CAPABILITIES[n]["blocker"] for n in absent()},
        "fusion_mode": params.fusion_mode,
    }


if __name__ == "__main__":
    assert len(CAPABILITIES) == 14
    assert set(available()) == {"REA", "FUSILAR", "SCRAPE", "MICROSERVICE"}
    assert "SCHEDULE" in absent()
    assert CAPABILITIES["EXCEL"]["status"] == "partial"

    p = plan(OperatorParams(domains=("https://github.com/hefarica/arbitragex-v2",), max_agents=12))
    assert p["max_agents"] == 12 and p["capacidades_ausentes"]

    try:
        OperatorParams(domains=("x",), max_agents=MAX_AGENTS + 1)
        raise SystemExit("FALLO: max_agents sobre MAX_AGENTS debio rechazarse")
    except FactoryError:
        pass
    try:
        driver_para("ethereum:0x1234")
        raise SystemExit("FALLO: blockchain debio declararse no soportado")
    except FactoryError as e:
        assert "allowlist" in str(e)
    print("OK agent_factory: 4 implementadas / 1 parcial / 9 ausentes declaradas, plan sin gasto")
