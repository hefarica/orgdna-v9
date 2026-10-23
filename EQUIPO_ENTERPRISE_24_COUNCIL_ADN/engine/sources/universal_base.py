"""universal_base.py - contrato para CUALQUIER fuente observable.

Lo universal es el CONTRATO, no la promesa. Un driver que no puede reunir
evidencia declara available() == False y scan_surface levanta SourceUnavailable
con el motivo exacto. No hay `pass` disfrazado de implementacion: un stub que
devuelve una superficie vacia es una mentira con forma de dato.
"""
from __future__ import annotations
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Set, Tuple


class SourceType(Enum):
    GIT = "git"
    WEB = "web"
    BLOCKCHAIN = "blockchain"
    BINARY = "binary"
    API = "api"


class SourceUnavailable(Exception):
    """El driver no puede reunir evidencia. Se declara, no se simula."""


@dataclass(frozen=True)
class SurfacePoint:
    path: str
    type: str
    size: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AppSurface:
    source_type: SourceType
    source_id: str
    points: Tuple[SurfacePoint, ...] = ()
    capabilities: Set[str] = field(default_factory=set)
    contracts: Tuple[Mapping, ...] = ()
    assets: Set[str] = field(default_factory=set)
    unknowns: Tuple[str, ...] = ()
    evidence: Tuple[str, ...] = ()
    confidence: float = 0.0

    @property
    def structure_fingerprint(self) -> str:
        rutas = "|".join(sorted(p.path for p in self.points))
        return hashlib.sha256(rutas.encode("utf-8")).hexdigest()[:16]

    def extensions(self) -> Tuple[str, ...]:
        """Extensiones reales. Un dotfile (.gitignore, .editorconfig) NO es una
        extension: es un nombre de archivo y lo gobierna FILENAME_OWNER. Contarlo
        como extension hacia que el Gate 1 lo viera huerfano — el gate tenia razon
        y el error era del censo de superficie."""
        vistos = set()
        for p in self.points:
            if p.type not in ("file", "source_code", "config", "asset"):
                continue
            base = p.path.rsplit("/", 1)[-1]
            if base.startswith("."):
                continue
            if "." in base:
                vistos.add("." + base.rsplit(".", 1)[1].lower())
        return tuple(sorted(vistos))


class UniversalDriver(ABC):
    """Cualquier cosa observable, barrida y replicable."""

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        ...

    @abstractmethod
    def available(self) -> Tuple[bool, str]:
        """(disponible, motivo). Si False, scan_surface debe levantar."""

    @abstractmethod
    def scan_surface(self, target: str) -> AppSurface:
        ...

    def detect_frameworks(self, surface: AppSurface) -> Set[str]:
        return set()

    def extract_contract(self, surface: AppSurface, point: SurfacePoint) -> Mapping:
        return {}


if __name__ == "__main__":
    s = AppSurface(SourceType.GIT, "x", (SurfacePoint("a.py", "source_code"),
                                         SurfacePoint("b.md", "file")))
    assert s.structure_fingerprint == AppSurface(
        SourceType.GIT, "y", (SurfacePoint("b.md", "file"),
                              SurfacePoint("a.py", "source_code"))
    ).structure_fingerprint, "la huella debe ser estable ante el orden"
    assert s.extensions() == (".md", ".py")
    try:
        UniversalDriver()
        raise SystemExit("FALLO: el ABC no debe instanciarse")
    except TypeError:
        pass
    print("OK universal_base: contrato estable, huella por estructura, ABC cerrado")
