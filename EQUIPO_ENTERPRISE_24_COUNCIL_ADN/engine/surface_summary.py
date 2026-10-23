"""surface_summary.py - de una AppSurface al summary que el proveedor YA valida.

EL CABLEADO REAL NO ES UN PROVEEDOR NUEVO. providers.prepare_summary admite dos
source_kind: github_repository y website. Lo que faltaba era producirlos desde
cualquier driver. Aqui se construyen y se VALIDAN llamando a prepare_summary: si
la forma no pasa, el summary no existe y no se manda nada.

Fuentes sin source_kind en la allowlist (blockchain, binario) NO se inventan: se
declaran con UnsuitableSurface. La allowlist del proveedor es la frontera
anti-inyeccion; agregarle un source_kind es una decision de seguridad, no una
comodidad.
"""
from __future__ import annotations
from typing import Mapping

if __package__:
    from .sources.universal_base import SourceType
    from . import providers as _prov
else:
    from sources.universal_base import SourceType
    import providers as _prov


class UnsuitableSurface(Exception):
    """La superficie no puede expresarse en un source_kind allowlisted."""


def to_summary(surface, *, max_files: int = 100) -> Mapping:
    """max_files acota el alcance: menos archivos = salida mas corta. El
    tope lo exige prepare_summary en 100; aqui se puede pedir menos."""
    if not 1 <= int(max_files) <= 100:
        raise UnsuitableSurface("max_files fuera de rango 1..100: %r" % (max_files,))
    """AppSurface -> summary validado por providers.prepare_summary."""
    if surface.source_type is SourceType.WEB:
        bruto = surface.raw or {}
        snap = bruto.get("snapshot")
        if not isinstance(snap, dict):
            raise UnsuitableSurface(
                "web sin evidencia cruda: el driver no reunio sha256/fecha/estado "
                "del cuerpo. Sin eso no hay procedencia y no se transmite.")
        import hashlib
        import json as _json
        # el proveedor CANONICALIZA la url antes de calcular el manifiesto: hay que
        # usar su misma funcion o el hash no casa nunca.
        if __package__:
            from .web_sources import canonical_url
        else:
            from web_sources import canonical_url
        snaps = [dict(snap)]
        snaps[0]["url"] = canonical_url(snaps[0].get("url"))
        manifiesto = [{"url": x.get("url"), "sha256": x.get("sha256")}
                      for x in sorted(snaps, key=lambda x: str(x.get("url")))]
        resumen = {"source_kind": "website", "source_url": surface.source_id,
                   "snapshots": snaps,
                   "source_hash": hashlib.sha256(
                       _json.dumps(manifiesto, sort_keys=True).encode()).hexdigest(),
                   "coverage": {"inventory_complete": False, "pages_fetched": len(snaps),
                                "scope": {"max_pages": 1, "max_depth": 0}}}
    elif surface.source_type is SourceType.GIT:
        bruto = surface.raw or {}
        sha = bruto.get("ref") or ""
        if not isinstance(sha, str) or len(sha) != 40:
            raise UnsuitableSurface(
                "git sin SHA fijado de 40 hex (ref=%r). El proveedor exige SHA para "
                "transmitir un repositorio; un ref movil no es una cita." % (sha,))
        rutas = [p for p in (bruto.get("paths") or [])][:int(max_files)]
        resumen = {
            "source_kind": "github_repository",
            "repository": {"url": surface.source_id, "sha": sha, "private": False},
            "files": [{"path": r, "snippet": ""} for r in rutas],
            # DEFECTO PROPIO CORREGIDO: el tree exponia 2x las rutas de files, asi
            # que el modelo podia citar una ruta con contenido NO enviado y el
            # validador lo rechazaba con razon ("cita evidencia no incluida").
            # El tree debe ser exactamente lo que se puede citar.
            "tree": [{"path": r} for r in rutas],
            "coverage": {"inventory_complete": True, "files": len(bruto.get("paths") or [])},
        }
    else:
        raise UnsuitableSurface(
            "source_type %s no tiene source_kind en la allowlist del proveedor. "
            "No se inventa uno: agregarlo es una decision de seguridad."
            % surface.source_type.value)

    try:
        return _prov.prepare_summary(resumen)   # valida o levanta; nunca "casi vale"
    except _prov.ProviderError as exc:
        # un solo modo de fallo declarado para el llamador
        raise UnsuitableSurface("el proveedor rechazo el summary: %s" % exc) from None


if __name__ == "__main__":
    if __package__:
        from .sources.universal_base import AppSurface, SourceType, SurfacePoint
    else:
        import os as _o, sys as _s
        _s.path.insert(0, _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))))
        from sources.universal_base import AppSurface, SourceType, SurfacePoint

    sha40 = "a" * 40
    snap = {"url": "https://example.com/", "sha256": "b" * 64,
            "fetched_at": "2026-10-23T00:00:00Z", "byte_count": 1256,
            "content_status": "usable_static_html", "title": "Example",
            "text_excerpt": "Example Domain", "headings": [], "links": [],
            "forms": [], "buttons": [], "inputs": [], "roles": []}
    web = AppSurface(SourceType.WEB, "https://example.com/", (), raw={"snapshot": snap})
    assert to_summary(web)["source_kind"] == "website"

    git = AppSurface(SourceType.GIT, "https://github.com/o/r", (),
                     raw={"ref": sha40, "paths": ["a.py", "b.md", "c.py"]})
    recortado = to_summary(git, max_files=2)
    assert len(recortado["files"]) == 2, len(recortado["files"])

    try:
        to_summary(git, max_files=0)
        raise SystemExit("FALLO: max_files=0 debio rechazarse")
    except UnsuitableSurface:
        pass
    try:
        to_summary(AppSurface(SourceType.BLOCKCHAIN, "ethereum:0x0", ()))
        raise SystemExit("FALLO: blockchain no debe producir summary")
    except UnsuitableSurface:
        pass
    print("OK surface_summary: website y github validados por prepare_summary, max_files acotado")
