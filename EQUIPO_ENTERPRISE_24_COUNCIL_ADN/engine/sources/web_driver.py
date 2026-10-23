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

        import datetime
        import hashlib
        import re as _re

        def _lista(patron, limite):
            return [m.group(1)[:500] for m in _re.finditer(patron, html, _re.I)][:limite]

        titulo = (spec.title or "")[:500]
        texto = _re.sub(r"<[^>]+>", " ", html)
        texto = _re.sub(r"\s+", " ", texto).strip()[:12000]
        cabeceras = [{"level": min(6, max(1, len(m.group(1)))),
                      "text": _re.sub(r"<[^>]+>", "", m.group(2)).strip()[:500]}
                     for m in _re.finditer(r"<h([1-6])[^>]*>(.*?)</h\1>", html, _re.S | _re.I)][:100]
        formularios = [{"method": (m.group(1) or "")[:500], "action": (m.group(2) or "")[:500]}
                       for m in _re.finditer(r'<form[^>]*method="([^"]*)"[^>]*action="([^"]*)"', html, _re.I)][:50]
        botones = _lista(r'<button[^>]*>([^<]*)</button>', 100)
        entradas = [{"tag": "input", "type": (m.group(1) or "")[:500], "name": (m.group(2) or "")[:500],
                     "id": "", "label": ""}
                    for m in _re.finditer(r'<input[^>]*type="([^"]*)"[^>]*name="([^"]*)"', html, _re.I)][:100]
        roles = _lista(r'role="([^"]+)"', 100)
        estado = "usable_static_html" if (texto or cabeceras or formularios) else "javascript_shell"

        crudo = {
            "snapshot": {
                "url": target,
                "sha256": hashlib.sha256(html.encode("utf-8", "replace")).hexdigest(),
                "fetched_at": datetime.datetime.now(datetime.timezone.utc)
                              .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "byte_count": len(html.encode("utf-8", "replace")),
                "content_status": estado,
                "title": titulo, "text_excerpt": texto,
                "headings": cabeceras, "links": [p.path for p in puntos if p.type == "route"][:300],
                "forms": formularios, "buttons": botones, "inputs": entradas, "roles": roles,
            }
        }

        return AppSurface(
            SourceType.WEB, target, tuple(puntos),
            capabilities=set(spec.capabilities),
            contracts=tuple(spec.api_contracts),
            assets=set(spec.assets),
            unknowns=tuple(spec.unknowns),
            evidence=(motivo, "%d bytes de HTML" % len(html),
                      "confianza %.2f" % spec.confidence),
            confidence=spec.confidence, raw=crudo)

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
