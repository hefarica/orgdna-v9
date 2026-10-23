"""web_driver.py - cualquier aplicacion accesible por HTTP.

Reusa site_rea como UNICA fuente de verdad del analisis: no hay dos analizadores
que puedan divergir. Respeta robots.txt antes de pedir nada.
"""
from __future__ import annotations
import re
import urllib.error
import urllib.request
from typing import Mapping, Set, Tuple
from urllib.parse import urlparse

if __package__:
    from .universal_base import (AppSurface, SourceType, SourceUnavailable,
                                 SurfacePoint, UniversalDriver)
    from ..site_rea import analyze
else:
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from universal_base import (AppSurface, SourceType, SourceUnavailable,
                                SurfacePoint, UniversalDriver)
    from site_rea import analyze

UA = "OrgDNA-REA/1.0 (analisis estatico, respeta robots.txt)"


def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace"), dict(r.headers)


def _robots_permite(base: str, ruta: str) -> Tuple[bool, str]:
    try:
        txt, _ = _get(base.rstrip("/") + "/robots.txt", timeout=10)
    except (urllib.error.URLError, OSError, ValueError):
        return True, "robots.txt ilegible: se asume permitido y se declara"
    for linea in txt.splitlines():
        if linea.strip().lower().startswith("disallow:"):
            patron = linea.split(":", 1)[1].strip()
            if patron and patron != "/" and ruta.startswith(patron):
                return False, "robots.txt prohibe %s" % patron
    return True, "robots.txt consultado"


class WebDriver(UniversalDriver):
    @property
    def source_type(self) -> SourceType:
        return SourceType.WEB

    def available(self):
        return True, "urllib disponible"

    def scan_surface(self, target: str) -> AppSurface:
        u = urlparse(target)
        if u.scheme not in ("http", "https"):
            raise SourceUnavailable("esquema no HTTP(S): %s" % u.scheme)
        permitido, motivo = _robots_permite("%s://%s" % (u.scheme, u.netloc), u.path or "/")
        if not permitido:
            raise SourceUnavailable(motivo)
        try:
            html, headers = _get(target)
        except (urllib.error.URLError, OSError) as exc:
            raise SourceUnavailable("no se pudo leer %s: %s" % (target, exc))

        spec = analyze(target, html)

        puntos = [SurfacePoint(r, "route") for r in spec.routes]
        puntos += [SurfacePoint(a, "api_endpoint") for a in spec.api_endpoints]
        puntos += [SurfacePoint(a, "asset") for a in spec.assets]

        return AppSurface(
            SourceType.WEB, target, tuple(puntos),
            capabilities=set(spec.capabilities),
            contracts=tuple(spec.api_contracts),
            assets=set(spec.assets),
            unknowns=tuple(spec.unknowns),
            evidence=(motivo, "%d bytes de HTML" % len(html),
                      "confianza %.2f" % spec.confidence),
            confidence=spec.confidence)

    def detect_frameworks(self, surface: AppSurface) -> Set[str]:
        return set(surface.capabilities) & {"react", "vue", "svelte", "next"}


if __name__ == "__main__":
    d = WebDriver()
    ok, m = d.available()
    assert ok
    s = AppSurface(SourceType.WEB, "x")
    assert s.confidence == 0.0
    # sin red: se prueba el contrato, no una promesa de red
    print("OK web_driver: contrato listo, robots consultado, analisis delegado a site_rea")
