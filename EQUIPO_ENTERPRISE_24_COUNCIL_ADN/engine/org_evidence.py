"""org_evidence.py - que se puede RECUPERAR de un archivo de evidencia, y que no.

Nace de un defecto real: una corrida pagada (248591 tokens) genero 12 agentes y el
proyecto nunca se guardo; al reiniciar, la app quedo con organization=None. Este
modulo NO finge una recuperacion: mide que hay en el archivo y declara que falta.

REGLA: si el archivo no permite reconstruir una organizacion VALIDA, no se carga
nada. Una media organizacion que parece completa es peor que ninguna.
"""
from __future__ import annotations
import json
import os
from typing import Mapping

NECESARIAS_PARA_ORGANIZACION = ("council", "dna_hash", "dna_revision", "config",
                                "competency_coverage")


class EvidenceError(Exception):
    pass


def inspect(evidence_path: str) -> Mapping:
    """Lee la evidencia y dice exactamente que se puede y que no."""
    if not evidence_path or not os.path.isfile(evidence_path):
        raise EvidenceError("no existe la evidencia: %s" % evidence_path)
    try:
        with open(evidence_path, encoding="utf-8") as fh:
            dados = json.load(fh)
    except (OSError, ValueError) as exc:
        raise EvidenceError("evidencia ilegible: %s" % exc)
    if not isinstance(dados, dict):
        raise EvidenceError("la evidencia no es un objeto JSON")

    agentes = dados.get("agents")
    if not isinstance(agentes, list) or not agentes:
        raise EvidenceError("no hay 'agents' utilizables en la evidencia")

    citas = sum(len(a.get("evidence_paths") or []) for a in agentes if isinstance(a, dict))
    faltan = [k for k in NECESARIAS_PARA_ORGANIZACION if k not in dados]
    return {
        "source": os.path.abspath(evidence_path),
        "agents": len(agentes),
        "evidence_paths": citas,
        "recoverable": {"agents": len(agentes), "evidence_paths": citas},
        "missing_for_organization": faltan,
        "can_rebuild_full_organization": not faltan,
        "why_not": (None if not faltan else
                    "El archivo guarda agentes finales, no los profile_specs que "
                    "core.generate_organization necesita, y le faltan %s. Cargar solo "
                    "los agentes produciria una organizacion a medias que parece "
                    "completa." % ", ".join(faltan)),
        "recommendation": ("cargar" if not faltan else
                           "no cargar: re-generar con auto-save, o exportar la "
                           "evidencia solo como dato citable"),
    }


def load_or_refuse(evidence_path: str, force: bool = False) -> Mapping:
    """Carga SOLO si la organizacion es reconstruible. `force` no salta esta regla."""
    r = inspect(evidence_path)
    if not r["can_rebuild_full_organization"]:
        raise EvidenceError(
            "se niega a cargar una organizacion incompleta: %s" % r["why_not"])
    with open(evidence_path, encoding="utf-8") as fh:
        return json.load(fh)


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    completo = os.path.join(d, "ok.json")
    json.dump({"agents": [{"evidence_paths": ["a.py"]}], "council": {"members": []},
               "dna_hash": "x", "dna_revision": 1, "config": {}, "competency_coverage": {}},
              open(completo, "w", encoding="utf-8"))
    r = inspect(completo)
    assert r["can_rebuild_full_organization"] and r["missing_for_organization"] == []

    parcial = os.path.join(d, "parcial.json")
    json.dump({"agents": [{"evidence_paths": ["a.py", "b.py"]}]}, open(parcial, "w", encoding="utf-8"))
    r2 = inspect(parcial)
    assert r2["can_rebuild_full_organization"] is False
    assert r2["agents"] == 1 and r2["evidence_paths"] == 2
    assert "council" in r2["missing_for_organization"]
    try:
        load_or_refuse(parcial, force=True)
        raise SystemExit("FALLO: force no debe saltar la regla")
    except EvidenceError:
        pass
    try:
        inspect(os.path.join(d, "no_existe.json"))
        raise SystemExit("FALLO: archivo inexistente aceptado")
    except EvidenceError:
        pass
    print("OK org_evidence: mide lo recuperable y RECHAZA cargar una organizacion a medias")
