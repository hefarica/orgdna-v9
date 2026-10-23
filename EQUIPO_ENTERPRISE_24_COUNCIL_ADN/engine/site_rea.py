"""site_rea.py - ingenieria inversa de un objetivo HTML a ReplicationSpec.

DOS DECISIONES QUE CORRIGEN EL BORRADOR:

1) El modo copy/reimplement NO se decide por substring. El borrador hacia
   "MIT" in html, que es exactamente el defecto F3 (BUSL-1.1+MIT leido como
   permisivo por la subcadena mit) por TERCERA vez. Aqui el modo entra como
   parametro license_id YA clasificado por rea_miner.classify_license (SPDX al
   SHA) y solo una lista cerrada de identificadores permisivos habilita copy.

2) Sin `except:` desnudos. El propio roster exige no_bare_except como criterio
   de aceptacion; que el codigo que lo genera los use seria incoherente.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from typing import Mapping, Tuple


class ReaError(Exception):
    pass


PERMISIVAS = ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause",
              "MPL-2.0", "ISC", "Unlicense")

FRAMEWORKS = (
    ("next", r"__NEXT_DATA__|/_next/static"),
    ("nuxt", r"__NUXT__|/_nuxt/"),
    ("remix", r"__remixContext"),
    ("astro", r"astro-island|data-astro"),
    ("sveltekit", r"__sveltekit"),
    ("solid", r"solid-start"),
    ("react", r"data-reactroot"),
    ("vue", r"data-v-[0-9a-f]{6,}"),
    ("svelte", r"svelte-[0-9a-z]{6,}"),
    ("angular", r"ng-version"),
)

CAPACIDADES = (
    ("nav", r"<nav\b"), ("form", r"<form\b"), ("table", r"<table\b"),
    ("modal", r'role="dialog"|aria-modal'), ("carousel", r"carousel|swiper"),
    ("chart", r"chart\.js|recharts|plotly"), ("auth", r"sign\s?in|log\s?in|password"),
    ("search", r'type="search"'), ("pagination", r"page=\d|rel=\"next\""),
    ("upload", r'type="file"'), ("checkout", r"cart|checkout|basket"),
    ("editor", r"contenteditable|<textarea"), ("map", r"leaflet|mapbox"),
    ("video", r"<video|youtube\.com/embed"), ("payments", r"stripe|paypal"),
    ("websocket", r"ws://|wss://|socket\.io"),
)

# destino exigido por lo detectado. Declarado a la vista, no adivinado.
DESTINO_POR_CAPACIDAD = {
    "chart": (".ts",), "form": (".css",), "nav": (".css",),
    "auth": (".sql",), "checkout": (".sql",), "editor": (".css",),
    "payments": (".py",), "websocket": (".py",), "upload": (".py",),
}


@dataclass
class ReplicationSpec:
    url: str
    title: str = ""
    description: str = ""
    frameworks: Tuple[str, ...] = ()
    capabilities: Tuple[str, ...] = ()
    routes: Tuple[str, ...] = ()
    api_endpoints: Tuple[str, ...] = ()
    api_contracts: Tuple[Mapping, ...] = ()
    assets: Tuple[str, ...] = ()
    required_destinations: Tuple[str, ...] = ()
    parity_targets: Tuple[str, ...] = ("routes", "contracts", "capabilities", "assets")
    unknowns: Tuple[str, ...] = ()
    confidence: float = 0.0
    mode: str = "reimplement"


def _hits(patrones, html: str) -> Tuple[str, ...]:
    return tuple(n for n, rx in patrones if re.search(rx, html, re.I))


def analyze(url: str, html: str, *, license_id: str = "UNKNOWN",
            headers: Mapping[str, str] | None = None) -> ReplicationSpec:
    if not html:
        raise ReaError("html vacio: no hay objetivo que analizar")
    spec = ReplicationSpec(url=url)

    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    spec.title = (m.group(1).strip()[:200] if m else "")
    m = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', html, re.I)
    spec.description = (m.group(1)[:400] if m else "")

    spec.frameworks = _hits(FRAMEWORKS, html)
    spec.capabilities = _hits(CAPACIDADES, html)

    spec.routes = tuple(sorted({h for h in re.findall(r'href="(/[^"#?]*)"', html)}))[:300]
    spec.api_endpoints = tuple(sorted({
        a for a in re.findall(r'["\']((?:/api/|https?://[^"\']+/api/)[^"\']+)["\']', html)
    }))[:200]
    spec.assets = tuple(sorted({
        a for a in re.findall(
            r'(?:src|href)="([^"]+\.(?:js|css|png|jpe?g|svg|webp|woff2?))"', html, re.I)
    }))[:500]

    contratos = []
    for m in re.finditer(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            contratos.append(json.loads(m.group(1)))
        except (ValueError, TypeError):
            continue
    nd = re.search(r"window\.__NEXT_DATA__\s*=\s*(\{.*?\});", html, re.S)
    if nd:
        try:
            contratos.append({"__NEXT_DATA__": json.loads(nd.group(1))})
        except (ValueError, TypeError):
            pass
    spec.api_contracts = tuple(contratos)

    dst = set()
    if spec.frameworks:
        dst.update({".ts", ".tsx", ".js", ".jsx"})
    for cap in spec.capabilities:
        dst.update(DESTINO_POR_CAPACIDAD.get(cap, ()))
    if spec.api_endpoints:
        dst.update({".py", ".json"})
    spec.required_destinations = tuple(sorted(dst)) or (".md",)

    # incognitas honestas: no se finge certeza donde no la hay
    if spec.frameworks and not spec.routes:
        spec.unknowns += ("rutas en cliente: captura estatica insuficiente",)
    if not spec.api_endpoints:
        spec.unknowns += ("API no observable en el HTML",)
    if not spec.api_contracts:
        spec.unknowns += ("sin contratos de datos visibles",)

    # modo: SOLO por identificador SPDX ya clasificado, nunca por substring
    spec.mode = "copy" if license_id in PERMISIVAS else "reimplement"
    spec.confidence = max(0.0, min(0.95, 0.85 - 0.15 * len(spec.unknowns)))
    return spec


def to_essence(spec: ReplicationSpec) -> str:
    return "\n".join([
        "TARGET %s" % spec.url,
        "PROPOSITO %s :: %s" % (spec.title, spec.description),
        "HUELLA %s" % ("/".join(spec.frameworks) or "-"),
        "CAPACIDADES %s" % (", ".join(spec.capabilities) or "-"),
        "CONTRATOS %d · RUTAS %d · API %d · ASSETS %d"
        % (len(spec.api_contracts), len(spec.routes),
           len(spec.api_endpoints), len(spec.assets)),
        "DESTINOS %s" % (", ".join(spec.required_destinations) or "-"),
        "MODO %s" % spec.mode,
        "CONFIANZA %.2f" % spec.confidence,
    ])


if __name__ == "__main__":
    html = ('<title>Demo</title><meta name="description" content="tienda">'
            '<script>window.__NEXT_DATA__={"props":{}};</script>'
            '<link href="/a.css"><nav></nav><form></form>'
            '<a href="/precios"></a><a href="/login"></a>'
            '<script>fetch("/api/cart")</script>')
    s = analyze("https://x", html)
    assert "next" in s.frameworks and "form" in s.capabilities
    assert "/api/cart" in s.api_endpoints and "/precios" in s.routes
    assert s.mode == "reimplement", "sin SPDX explicito NO se asume permisiva"
    s2 = analyze("https://x", html, license_id="Apache-2.0")
    assert s2.mode == "copy"
    s3 = analyze("https://x", html, license_id="BUSL-1.1")
    assert s3.mode == "reimplement", "BUSL jamas es copy"
    try:
        analyze("https://x", "")
        raise SystemExit("FALLO: html vacio debio fallar")
    except ReaError:
        pass
    print("OK site_rea: modo por SPDX (no substring), %d frameworks, %d capacidades"
          % (len(s.frameworks), len(s.capabilities)))
