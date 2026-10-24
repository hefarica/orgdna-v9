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
    "EXCEL":       {"status": "partial", "module": "engine.bridge excel_call + read_xlsx_snapshot",
                    "blocker": "MEDIDO 2026-10-23: Excel.Application COM disponible; "
                               "excel_call('Read') exige el libro ABIERTO en una instancia "
                               "activa (precondicion, no defecto) y read_xlsx_snapshot (stdlib) "
                               "abre y valida el archivo guardado. La escritura en vivo no se "
                               "ejercito: requiere un libro real del operador"},
    "WEB_LOGIN":   {"status": "implemented_requires_credentials",
                    "module": "engine.cap_web_login (stdlib urllib + cookies)",
                    "blocker": "requiere login_url, username_field, password_field; "
                               "solo formularios HTML sin JS"},
    "OCR":         {"status": "declared_absent", "module": "-",
                    "blocker": "no hay motor OCR en dependencias (stdlib-only)"},
    "EMAIL":       {"status": "implemented_requires_credentials",
                    "module": "engine.cap_email (stdlib imaplib, solo lectura)",
                    "blocker": "requiere imap_server, username, password; no envia correo"},
    "WHATSAPP":    {"status": "declared_absent", "module": "-",
                    "blocker": "requiere WhatsApp Business API y token"},
    "TELEGRAM":    {"status": "implemented_requires_credentials",
                    "module": "engine.cap_telegram (stdlib urllib, getMe/sendMessage)",
                    "blocker": "requiere token de bot; sendMessage exige confirmed=True"},
    "PPT":         {"status": "implemented",
                    "module": "engine.cap_ooxml (zipfile + xml, OOXML minimo)",
                    "blocker": "sin estilos, tablas ni imagenes; OOXML valido, no disenado"},
    "WORD":        {"status": "implemented",
                    "module": "engine.cap_ooxml (zipfile + xml, OOXML minimo)",
                    "blocker": "sin estilos, tablas ni imagenes; OOXML valido, no disenado"},
    "OBSIDIAN":    {"status": "implemented",
                    "module": "engine.cap_obsidian (pathlib, wikilinks, sin escapes)",
                    "blocker": "requiere ruta de vault existente; escribe solo dentro de el"},
    "SCHEDULE":    {"status": "implemented",
                    "module": "engine.cap_schedule (stdlib threading + JSON)",
                    "blocker": "expone tick(now); SIN llamador en produccion, no corre solo"},
}


def available() -> Tuple[str, ...]:
    return tuple(n for n, v in CAPABILITIES.items() if v["status"] == "implemented")


def needs_credentials() -> Tuple[str, ...]:
    return tuple(n for n, v in CAPABILITIES.items()
                 if v["status"] == "implemented_requires_credentials")


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


# --- Fuentes REALES anadidas: HuggingFace (metadata publica) y archivo local ---
# Ambas devuelven (source_id, tipo, rutas_citables, texto). Las rutas son lo que se
# FETCHEO de verdad: son las unicas que el ADN puede citar.

HF_API = "https://huggingface.co/api/models/%s"
HF_RAW = "https://huggingface.co/%s/raw/main/%s"


def fetch_huggingface(model_id: str, timeout: int = 20):
    """Metadata publica + README. Sin token: solo superficie publica."""
    import urllib.error
    import urllib.request

    mid = model_id.strip().strip("/").replace("https://huggingface.co/", "")
    if not mid:
        raise FactoryError("model_id vacio")
    rutas, textos = [], []
    api = HF_API % mid
    try:
        req = urllib.request.Request(api, headers={"User-Agent": "OrgDNA-REA/1.0",
                                                  "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            meta = json.loads(r.read().decode("utf-8", "replace"))
        rutas.append(api)
        textos.append(json.dumps(meta, ensure_ascii=False)[:20000])
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FactoryError("no se pudo leer la metadata de %s: %s" % (mid, exc))

    for archivo in ("README.md", "config.json"):
        url = HF_RAW % (mid, archivo)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OrgDNA-REA/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                textos.append("=== %s ===\n%s" % (archivo, r.read().decode("utf-8", "replace")[:20000]))
            rutas.append(url)
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return "hf:" + mid, "huggingface", tuple(rutas), "\n\n".join(textos)


def fetch_file(path: str, limite: int = 200000):
    """Archivo local de texto. La ruta citada es la ruta real en disco."""
    import os
    if not os.path.isfile(path):
        raise FactoryError("no es un archivo: %s" % path)
    try:
        with open(path, "rb") as fh:
            datos = fh.read(limite)
    except OSError as exc:
        raise FactoryError("no se pudo leer %s: %s" % (path, exc))
    texto = datos.decode("utf-8", "replace")
    if not texto.strip():
        raise FactoryError("%s no tiene texto utilizable" % path)
    return "file:" + os.path.abspath(path), "file", (os.path.abspath(path),), texto


def driver_para(target: str):
    t = target.strip()
    # ORDEN importa: HF y archivo se resuelven ANTES que las ramas genericas http,
    # o huggingface.co caeria en 'web' y se scrappearia la pagina en vez de usar su API.
    if t.startswith("hf:") or "huggingface.co/" in t:
        return None, "huggingface"
    if t.startswith(("http://", "https://")) and ("github.com" in t or "gitlab.com" in t or t.endswith(".git")):
        return GitDriver(), "git"
    if os.path.isdir(t):
        return GitDriver(), "git"
    if os.path.isfile(t):
        return None, "file"
    if t.startswith(("http://", "https://")):
        return WebDriver(), "web"
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
        if tipo == "huggingface":
            sid, stipo, rutas, texto = fetch_huggingface(d)
        elif tipo == "file":
            sid, stipo, rutas, texto = fetch_file(d)
        else:
            superficie = driver.scan_surface(d)
            rutas = tuple(superficie.raw.get("paths") or ())
            sid, stipo, texto = superficie.source_id, superficie.source_type.value, \
                " ".join(sorted(rutas)[:200])
        if not rutas:
            raise FactoryError(
                "%s: la superficie no expone rutas citables; no se puede exigir evidencia" % d)

        class _S:
            pass
        sup = _S()
        sup.source_id = sid
        sup.source_type = type("T", (), {"value": stipo})
        adn = extract(sup, rutas, llm, surface_text=texto)
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
    assert set(available()) == {"REA", "FUSILAR", "SCRAPE", "MICROSERVICE", "SCHEDULE",
                                "PPT", "WORD", "OBSIDIAN"}
    assert set(needs_credentials()) == {"EMAIL", "WEB_LOGIN", "TELEGRAM"}
    assert set(absent()) == {"OCR", "WHATSAPP"}
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
    print("OK agent_factory: 8 implementadas / 3 con credencial / 1 parcial / 2 ausentes")
