"""reconcile_vocabularies.py - cruza los ROLE_SEEDS reales con los duenos del mapa.

NO tiene tabla manual: lee de engine/dna.py el texto de cada seed (rol, area,
mision, responsabilidades) y lo cruza contra los duenos de extension. Lo que no
cruza es unmapped (cargo sin codigo); lo que el arbol exige y nadie cubre es gap.
"""
from __future__ import annotations
import json
import re
import sys
from typing import Dict, List, Set

from census_extensions import census, owner_of, roster_names
from engine.extension_owners import AMBIGUOUS, EXTENSION_OWNER, FILENAME_OWNER

# ---------------------------------------------------------------------------
# Vocabulario tecnico: palabras que, si aparecen en el texto del seed, lo ligan a
# una familia. Se declara a la vista; no se infiere por magia.
# ---------------------------------------------------------------------------
FAMILIA = {
    "python_engineer": ("python", "pytest", "unittest", "stdlib", "pip"),
    "rust_engineer": ("rust", "cargo", "crate", "crates", "clippy", "ownership",
                      "workspace", "sistemas"),
    "typescript_engineer": ("typescript", "tsc", "tipado", "control-plane",
                            "endpoint", "api", "servicio", "backend"),
    "javascript_engineer": ("javascript", "esm", "node", "npm"),
    "go_engineer": ("golang", "go"),
    "solidity_engineer": ("solidity", "contrato", "contract", "evm", "on-chain",
                          "executor"),
    "data_engineer": ("sql", "migracion", "migración", "migration", "esquema",
                      "base de datos", "postgres", "sqlite", "datos", "ingesta", "etl"),
    "ml_engineer": ("modelo", "ml", "entrenamiento", "inferencia", "ia", "ai"),
    "design_systems": ("css", "diseño", "interfaz", "accesibilidad", "ux", "ui",
                       "frontend", "movil", "móvil"),
    "docs_engineer": ("documentacion", "documentación", "manual", "acta", "informe",
                      "especificacion", "especificación", "spec"),
    "config_engineer": ("configuracion", "configuración", "manifiesto", "toml", "yaml",
                        "arquitectura", "grafo", "graph"),
    "security_auditor": ("seguridad", "security", "auditoria", "auditoría", "integridad",
                         "hash", "credencial", "privacidad", "privacy", "evidencia"),
    "windows_automation": ("powershell", "windows", "bat"),
    "posix_automation": ("shell", "bash", "posix"),
    "docker_engineer": ("docker", "contenedor", "imagen"),
    "k8s_engineer": ("kubernetes", "k8s", "helm"),
    "ci_engineer": ("ci", "pipeline", "workflow", "github actions", "release",
                    "despliegue", "sre", "rendimiento", "performance"),
    "qa_test_engineer": ("test", "prueba", "cobertura", "regresion", "regresión",
                         "parity", "paridad", "e2e", "chaos", "caos"),
    "cartridge_engineer": ("rhai", "cartucho", "cartridge"),
    "mev_engineer": ("mev", "arbitraje", "arbitrage", "relay", "bundle", "quant",
                     "estrategia"),
    "risk_sizing_engineer": ("riesgo", "risk", "sizing", "killswitch", "drawdown",
                             "coste", "costo", "cost", "market", "mercado", "ledger"),
    "docs_engineer_alt": (),
}

_TXT_FIELDS = (1, 2, 3, 4)          # role, area, mission, responsibilities


def seed_text(seed) -> str:
    # El NOMBRE del seed es la senal mas fuerte: un seed llamado SRE cuya prosa no
    # dice "sre" quedaba sin mapear. Se incluye siempre.
    partes = [str(seed[0])]
    partes += [str(seed[i]) for i in _TXT_FIELDS if i < len(seed) and seed[i]]
    if isinstance(seed[4] if len(seed) > 4 else None, (list, tuple)):
        partes.append(" ".join(str(x) for x in seed[4]))
    return " ".join(partes).lower()


_RX_CACHE: Dict[str, "re.Pattern"] = {}


def _rx(palabra: str) -> "re.Pattern":
    rx = _RX_CACHE.get(palabra)
    if rx is None:
        # FRONTERA DE PALABRA: 'ci' NO debe casar dentro de 'ejecucion'.
        # Es exactamente el defecto que en F3 leia "BUSL-1.1+MIT" como permisiva.
        rx = re.compile(r"(?<![\w\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1])"
                        + re.escape(palabra)
                        + r"(?![\w\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1])", re.I)
        _RX_CACHE[palabra] = rx
    return rx


def infer_owners(text: str) -> List[str]:
    hits = []
    for owner, palabras in FAMILIA.items():
        if owner.endswith("_alt"):
            continue
        for p in palabras:
            p = p.strip()
            if len(p) < 3:
                continue
            if _rx(p).search(text):
                hits.append(owner)
                break
    return sorted(set(hits))


def reconcile(root: str) -> dict:
    from engine.dna import ROLE_SEEDS

    censo = census(root, roster_names())
    required: Set[str] = set(censo["SEMILLAS_FALTANTES"])

    mapped: Dict[str, List[str]] = {}
    unmapped: List[str] = []
    for seed in ROLE_SEEDS:
        name = seed[0]
        owners = infer_owners(seed_text(seed))
        if owners:
            mapped[name] = owners
        else:
            unmapped.append(name)

    covered: Set[str] = {o for owners in mapped.values() for o in owners}
    gaps = sorted(required - covered)

    # extensiones que quedarian sin dueno real tras sumar los gaps
    nuevo_roster = covered | set(gaps)
    presentes = [e for e in censo.get("top_extensiones", [])]
    import collections as _c
    # extensiones realmente presentes, con su conteo
    from census_extensions import walk
    cuenta = _c.Counter()
    for rel in walk(root):
        nm = rel.rsplit("/", 1)[-1]
        if nm in FILENAME_OWNER:
            continue
        cuenta[("." + nm.rsplit(".", 1)[1].lower()) if "." in nm else "(sin extension)"] += 1
    sin_dueno = sorted(e for e in cuenta if owner_of(e) and owner_of(e) not in nuevo_roster)
    archivos_sin_dueno = sum(cuenta[e] for e in sin_dueno)
    total_archivos = sum(cuenta.values())

    return {
        "root": root,
        "seeds_existentes": len(ROLE_SEEDS),
        "duenos_requeridos_por_el_arbol": len(required),
        "mapeados": len(mapped),
        "unmapped": unmapped,
        "gaps": gaps,
        "cubiertos": sorted(covered),
        "extensiones_que_seguirian_sin_dueno": sin_dueno,
        "archivos_sin_dueno": archivos_sin_dueno,
        "total_archivos": total_archivos,
        "cobertura_archivos_pct_tras_gaps": round(100.0 * (total_archivos - archivos_sin_dueno) / total_archivos, 2) if total_archivos else 0.0,
        "roster_objetivo": len(covered | set(gaps)),
        "detalle_mapeo": mapped,
    }


def main(argv):
    out = reconcile(argv[1] if len(argv) > 1 else ".")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if not out["gaps"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
