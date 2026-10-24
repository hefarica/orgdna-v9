"""cap_obsidian.py - vault de Obsidian con stdlib (pathlib). Sin dependencias.

Un vault es una carpeta de .md. El modulo NO escribe fuera del vault: valida que
cada ruta resuelta quede dentro, y rechaza '..', rutas absolutas y nombres con
separadores. Un sync que se sale del vault no es un sync: es un borrado creativo.
"""
from __future__ import annotations
import os
import re
from pathlib import Path
from typing import List

WIKILINK = re.compile(r"\[\[([^\]|#]+)")
_NOMBRE = re.compile(r"^[A-Za-z0-9 _.\-\u00c0-\u017f]{1,120}$")


class VaultError(Exception):
    pass


class Vault:
    def __init__(self, root: str, subdir: str = "notas"):
        if not root:
            raise VaultError("falta la ruta del vault")
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise VaultError("el vault no existe o no es carpeta: %s" % root)
        self.subdir = subdir
        if not _NOMBRE.match(subdir or ""):
            raise VaultError("subdir invalido: %r" % subdir)

    def _destino(self, nombre: str) -> Path:
        if not nombre or not _NOMBRE.match(nombre):
            raise VaultError("nombre invalido: %r (sin rutas ni separadores)" % nombre)
        base = (self.root / self.subdir).resolve()
        destino = (base / (nombre if nombre.endswith(".md") else nombre + ".md")).resolve()
        if base != destino.parent:
            raise VaultError("la ruta escaparia del vault: %s" % destino)
        return destino

    def write(self, nombre: str, texto: str) -> dict:
        if not isinstance(texto, str) or not texto.strip():
            raise VaultError("texto vacio: una nota sin cuerpo no es una nota")
        destino = self._destino(nombre)
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(texto, encoding="utf-8")
        except OSError as exc:
            raise VaultError("no se pudo escribir %s: %s" % (destino, exc))
        return {"source": str(destino), "bytes": destino.stat().st_size,
                "links": self.links(destino.name)}

    def notes(self) -> List[str]:
        base = (self.root / self.subdir).resolve()
        if not base.exists():
            return []
        return sorted(p.name for p in base.glob("*.md") if p.is_file())

    def read(self, nombre: str) -> str:
        destino = self._destino(nombre)
        if not destino.is_file():
            raise VaultError("no existe la nota: %s" % destino.name)
        return destino.read_text(encoding="utf-8")

    def links(self, nombre: str) -> List[str]:
        try:
            texto = self.read(nombre)
        except VaultError:
            return []
        return sorted({m.strip() for m in WIKILINK.findall(texto) if m.strip()})


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    v = Vault(d)
    r = v.write("ADR 001", "Decidimos [[Estrategia]] por [[Riesgo|riesgo]]")
    assert r["links"] == ["Estrategia", "Riesgo"], r
    assert v.notes() == ["ADR 001.md"]
    assert "Riesgo" in v.read("ADR 001")
    for malo in ("../fuera", "sub/nota", "/abs/nota", ""):
        try:
            v._destino(malo); raise SystemExit("FALLO: nombre %r aceptado" % malo)
        except VaultError:
            pass
    try:
        v.write("x", "  ")
        raise SystemExit("FALLO: nota vacia aceptada")
    except VaultError:
        pass
    try:
        Vault("")
        raise SystemExit("FALLO: sin root aceptado")
    except VaultError:
        pass
    print("OK cap_obsidian: escribe dentro del vault, indices y wikilinks, rechaza escapes")
