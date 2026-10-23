"""Genera engine/seeds_reconciled.py con DATOS LITERALES.

Convierte los 32 ROLE_SEEDS (tuplas planas de 6 campos, sin .name) al formato Seed,
infiriendo su destino desde su propio texto, y los une con los 10 gaps. Se genera
una vez y se commitea: el roster es dato, no logica.
"""
import io
import sys

from engine.dna import ROLE_SEEDS
from engine.extension_owners import EXTENSION_OWNER
from engine.seeds_gaps import GAPS
from reconcile_vocabularies import infer_owners, seed_text


def destino_para(owners):
    exts = sorted({e for e, o in EXTENSION_OWNER.items() if o in owners and e})
    return tuple(exts[:6]) if exts else (".md",)


lineas = []
lineas.append('"""seeds_reconciled.py - roster reconciliado P4-A: 32 existentes + 10 gaps.')
lineas.append("")
lineas.append("GENERADO por tools/generate_seeds_reconciled.py a partir de engine/dna.py.")
lineas.append("Los 32 existentes conservan su nombre y rol; su destino se infiere de su")
lineas.append("propio texto; los que no tienen codigo quedan con destino administrativo .md")
lineas.append('(Opcion A). NO se edita a mano: se regenera.')
lineas.append('"""')
lineas.append("from __future__ import annotations")
lineas.append("")
lineas.append("from typing import Tuple")
lineas.append("")
lineas.append("if __package__:")
lineas.append("    from .seeds_gaps import GAPS, Seed")
lineas.append("else:")
lineas.append("    from seeds_gaps import GAPS, Seed")
lineas.append("")
lineas.append("")
lineas.append("EXISTING: Tuple[Seed, ...] = (")
for s in ROLE_SEEDS:
    name, role, area, mission, _resp, _deliv = s[0], s[1], s[2], s[3], s[4], s[5]
    owners = infer_owners(seed_text(s))
    dest = destino_para(owners)
    bundle = (owners[0] + "_pack") if owners else "docs_pack"
    acc = ("destino_declarado",) + tuple("cubre:" + o for o in owners)
    goal = (mission or area or role).replace('"', "'")[:160]
    lineas.append("    Seed(%r, %r, %r," % (name, role[:80], goal))
    lineas.append("         %r, %r, %r)," % (dest, bundle, acc))
lineas.append(")")
lineas.append("")
lineas.append("")
lineas.append("ROLE_SEEDS_RECONCILED: Tuple[Seed, ...] = EXISTING + GAPS")
lineas.append("")
lineas.append("assert len(ROLE_SEEDS_RECONCILED) == 42, len(ROLE_SEEDS_RECONCILED)")
lineas.append('assert len({s.name for s in ROLE_SEEDS_RECONCILED}) == 42, "duplicados"')
lineas.append("")
lineas.append('if __name__ == "__main__":')
lineas.append('    sin_destino = [s.name for s in ROLE_SEEDS_RECONCILED if not s.destination]')
lineas.append('    print("OK seeds_reconciled: %d seeds, %d sin destino"')
lineas.append('          % (len(ROLE_SEEDS_RECONCILED), len(sin_destino)))')

ruta = r"C:\Users\HFRC\Downloads\EQUIPO_ENTERPRISE_24_COUNCIL_ADN (7)\EQUIPO_ENTERPRISE_24_COUNCIL_ADN\engine\seeds_reconciled.py"
io.open(ruta, "w", encoding="utf-8", newline="").write("\n".join(lineas) + "\n")
print("  generado engine/seeds_reconciled.py")
