"""census_extensions.py - que duenos exige el arbol y cuales faltan del roster.

NO cambia comportamiento y NO gasta tokens: solo mide. Alimenta el tranche 4 con
datos en vez de con una lista adivinada.
"""
from __future__ import annotations
import json
import os
import sys
from collections import Counter

from engine.extension_owners import (AMBIGUOUS, EXTENSION_OWNER, FILENAME_OWNER,
                                     coverage_gate)

# data/ es estado de ejecucion: el sello ya lo excluye por diseno
# (docs/PLATAFORMA_VERIFICACION_V1.md). El censo hace lo mismo.
SKIP = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "data",
        ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea"}


def walk(root):
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for n in names:
            yield os.path.relpath(os.path.join(base, n), root).replace(os.sep, "/")


def owner_of(ext):
    return EXTENSION_OWNER.get(ext) or (AMBIGUOUS[ext][0] if ext in AMBIGUOUS else None)


def census(root, roster_names):
    exts, files = Counter(), 0
    for rel in walk(root):
        files += 1
        name = rel.rsplit("/", 1)[-1]
        if name in FILENAME_OWNER:
            exts["<filename>" + name] = exts.get("<filename>" + name, 0) + 1
            continue
        ext = ("." + name.rsplit(".", 1)[1].lower()) if "." in name else "(sin extension)"
        exts[ext] += 1

    real_exts = [e for e in exts if not e.startswith("<filename>")]
    rep = coverage_gate(real_exts)
    required = {o for o in (owner_of(e) for e in real_exts) if o}
    required |= {FILENAME_OWNER[e[10:]] for e in exts if e.startswith("<filename>")}
    missing = sorted(required - roster_names)
    covered_files = sum(c for e, c in exts.items()
                        if not e.startswith("<filename>") and owner_of(e) in roster_names)
    covered_files += sum(c for e, c in exts.items()
                         if e.startswith("<filename>") and FILENAME_OWNER[e[10:]] in roster_names)
    return {
        "root": root,
        "files": files,
        "familias_en_arbol": len(real_exts),
        "mapa_huerfanas": sorted(rep.orphans),
        "mapa_ok": rep.ok,
        "roster_cobertura_archivos_pct": round(100.0 * covered_files / files, 3) if files else 0.0,
        "duenos_requeridos": len(required),
        "duenos_presentes": len(required) - len(missing),
        "SEMILLAS_FALTANTES": missing,
        "detalle_por_dueno": sorted(
            ((o, sum(c for e, c in exts.items()
                     if not e.startswith("<filename>") and owner_of(e) == o))
             for o in missing), key=lambda t: -t[1]),
        "top_extensiones": exts.most_common(24),
    }


def roster_names():
    from engine.dna import ROLE_SEEDS
    return {s[0] for s in ROLE_SEEDS}


def main(argv):
    root = argv[1] if len(argv) > 1 else "."
    try:
        names = roster_names()
    except Exception as exc:
        print("# aviso: roster no legible (%s); SEMILLAS_FALTANTES = todos" % exc,
              file=sys.stderr)
        names = set()
    out = census(root, names)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["mapa_ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
