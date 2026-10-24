"""Public, read-only HTML evidence. No browser, JavaScript, credentials or LLM.

All network reads use providers' DNS-pinned verified TLS transport. Injectable
transports are trusted fixtures only. Coverage never claims a whole website.
"""
from __future__ import annotations
import copy
import hashlib
import os
import subprocess
import json
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
try:
    from . import providers
except ImportError:
    import providers

USER_AGENT = 'OrgDNAEvidence/1.0'
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
CACHE_BYTES = 8_000_000


def canonical_url(url, base=None):
    if not isinstance(url, str):
        raise providers.ProviderError('URL web inválida.')
    target = urljoin(base, url) if base else url
    target = target.split('#', 1)[0]
    parsed = providers._url(target)
    pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=16)
    pairs = [(k, v) for k, v in pairs if not k.lower().startswith('utm_') and k.lower() not in ('fbclid', 'gclid')]
    if len(pairs) > 4 or len(parsed.query) > 256:
        raise providers.ProviderError('Demasiadas variantes de consulta.')
    if any(re.search(r'token|password|secret|api.?key|session|auth|code', k, re.I) for k, _ in pairs):
        raise providers.ProviderError('No se leen URLs con credenciales o tokens.')
    return urlunsplit(('https', parsed.hostname.lower(), parsed.path or '/', urlencode(sorted(pairs)), ''))


def _origin(url):
    return 'https://' + urlsplit(url).hostname


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []; self.headings = []; self.links = []; self.forms = []
        self.buttons = []; self.inputs = []; self.roles = []; self.text = []
        self.stack = []; self.scripts = 0; self.capture = []; self.labels = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style', 'noscript', 'template'):
            self.stack.append(tag)
            if tag == 'script': self.scripts += 1
            return
        if self.stack: return
        if tag in ('title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'button', 'label'):
            self.capture.append([tag, a, []])
        if tag == 'a' and a.get('href') and len(self.links) < 300:
            self.links.append(a['href'][:2048])
        if tag == 'form' and len(self.forms) < 50:
            self.forms.append({'method': a.get('method', 'get').lower(), 'action': a.get('action', '')[:500]})
        if tag in ('input', 'select', 'textarea') and len(self.inputs) < 100:
            self.inputs.append({'tag': tag, 'type': a.get('type', 'text')[:80], 'name': a.get('name', '')[:100],
                                'id': a.get('id', '')[:100], 'label': a.get('aria-label', self.labels.get(a.get('id'), ''))[:200]})
            for kind, attrs, _ in self.capture:
                if kind == 'label' and not attrs.get('for'):
                    attrs.setdefault('_control_indices', []).append(len(self.inputs)-1)
        if a.get('role') and len(self.roles) < 100: self.roles.append(a['role'][:80])

    def handle_endtag(self, tag):
        if self.stack:
            if tag == self.stack[-1]: self.stack.pop()
            return
        for i in range(len(self.capture)-1, -1, -1):
            kind, attrs, parts = self.capture[i]
            if kind != tag: continue
            del self.capture[i]
            text = ' '.join(' '.join(parts).split())[:500]
            if tag == 'title': self.title.append(text)
            elif tag.startswith('h'): self.headings.append({'level': int(tag[1]), 'text': text})
            elif tag == 'button': self.buttons.append(text)
            elif tag == 'label':
                if attrs.get('for'): self.labels[attrs['for']] = text
                for index in attrs.get('_control_indices', []):
                    if not self.inputs[index]['label']: self.inputs[index]['label'] = text
                for control in self.inputs:
                    if attrs.get('for') and control['id'] == attrs['for']: control['label'] = text
            break

    def handle_data(self, data):
        if self.stack: return
        text = ' '.join(data.split())
        if text and len(self.text) < 3000: self.text.append(text[:1000])
        for _, _, parts in self.capture:
            if len(parts) < 30: parts.append(text)


def _embedded_text(html):
    """Texto REAL que un SPA deja escrito en el HTML: meta, og:*, JSON-LD, __NEXT_DATA__.

    DEFECTO MEDIDO 2026-10-23 con https://pancakeswap.finance/: el HTML trae 36965
    bytes y 28066 caracteres visibles, pero casi todo es CSS inline. El parser
    ignora <style>, asi que quedaba "Home | PancakeSwap" (19 chars) ->
    javascript_shell -> CERO evidencia, y el analisis se negaba. Un sitio moderno
    entero quedaba fuera de la app.

    NO renderiza JavaScript: extrae lo que ya esta escrito en el HTML. Es estatico
    y citable, y su escasez se declara en coverage.limitations.
    """
    partes = []
    for patron in (
            r'<meta[^>]+name="description"[^>]+content="([^"]{20,})"',
            r'<meta[^>]+property="og:(?:title|description)"[^>]+content="([^"]{10,})"',
            r'<meta[^>]+name="keywords"[^>]+content="([^"]{10,})"',
            r'<script[^>]+type="application/ld\+json"[^>]*>(.{40,}?)</script>',
            r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.{80,}?)</script>',
            r'window\.__NUXT__\s*=\s*(.{80,}?);\s*</script>'):
        for m in re.finditer(patron, html, re.S | re.I):
            trozo = re.sub(r"\s+", " ", m.group(1)).strip()
            if trozo:
                partes.append(trozo[:4000])
    return " ".join(partes)[:12000]


# --- RENDER DE JAVASCRIPT (orden del operador 2026-10-23) ---------------------
# Se ROMPE a proposito la promesa "solo HTML estatico": un SPA solo se entiende
# ejecutando su JS. Se usa un NAVEGADOR YA INSTALADO en modo headless --dump-dom,
# que devuelve el DOM ya poblado. No se instala nada de Python: el paquete sigue
# siendo stdlib-only; el navegador es una dependencia de SISTEMA, declarada.
#
# Si no hay navegador, NO se finge: se devuelve el motivo y se mantiene el camino
# estatico anterior.
RENDER_JS = os.environ.get("ORGDNA_RENDER_JS", "1").strip() != "0"
RENDER_TIMEOUT = 90
RENDER_BUDGET_MS = 8000
RENDER_MAX_BYTES = 4_000_000
_NAVEGADORES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
)


def navegador_disponible():
    for ruta in _NAVEGADORES:
        if os.path.isfile(ruta) and os.access(ruta, os.X_OK):
            return ruta
    return None


def _render_dom(url, timeout=RENDER_TIMEOUT):
    """Devuelve (html_bytes, nombre_navegador) o (None, motivo). Nunca silencioso."""
    if not RENDER_JS:
        return None, "render_desactivado_por_configuracion"
    binario = navegador_disponible()
    if binario is None:
        return None, "sin_navegador_instalado"
    orden = [binario, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--disable-dev-shm-usage", "--hide-scrollbars", "--disable-extensions",
             "--virtual-time-budget=%d" % RENDER_BUDGET_MS, "--dump-dom", url]
    try:
        salida = subprocess.run(orden, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return None, "render_timeout"
    except OSError as exc:
        return None, "render_no_ejecutable:%s" % type(exc).__name__
    if salida.returncode != 0:
        return None, "render_exit_%d" % salida.returncode
    if not salida.stdout or len(salida.stdout) > RENDER_MAX_BYTES:
        return None, "render_sin_salida" if not salida.stdout else "render_demasiado_grande"
    nombre = os.path.basename(binario).lower().replace(".exe", "")
    return salida.stdout, nombre


def _extract(url, data):
    parser = _HTML()
    parser.feed(data.decode('utf-8', errors='replace'))
    text = ' '.join(parser.text)[:12000]
    usable = bool(len(text) >= 40 or parser.headings or parser.forms or parser.buttons or parser.inputs)
    embedded_only = False
    rendered_js = False
    render_nota = None
    if not usable:
        # 1) primero el render real: es lo que da contenido de verdad en un SPA
        html_render, nota = _render_dom(url)
        if html_render:
            p2 = _HTML()
            p2.feed(html_render.decode('utf-8', errors='replace'))
            texto_render = ' '.join(p2.text)[:12000]
            if len(texto_render) >= 40 or p2.headings or p2.forms or p2.buttons or p2.inputs:
                parser = p2
                text = texto_render
                usable = True
                rendered_js = True
                render_nota = nota
        else:
            render_nota = nota
    if not usable:
        # Cascaron JS: antes de rendirse, la metadata y los datos embebidos.
        embebido = _embedded_text(data.decode('utf-8', errors='replace'))
        if len(embebido) >= 40:
            text = embebido
            usable = True
            embedded_only = True
    return {'url': url, 'fetched_at': datetime.now(timezone.utc).isoformat(),
            'sha256': hashlib.sha256(data).hexdigest(), 'byte_count': len(data),
            'title': ' '.join(parser.title)[:500], 'headings': parser.headings[:100],
            'links': parser.links, 'forms': parser.forms, 'buttons': parser.buttons[:100],
            'inputs': parser.inputs, 'roles': sorted(set(parser.roles)), 'text_excerpt': text,
            'content_status': 'usable_static_html' if usable else ('javascript_shell' if parser.scripts else 'no_usable_evidence'),
            'javascript_rendered': rendered_js, 'embedded_only': embedded_only,
            'render_engine': render_nota}


def clear_cache():
    with _CACHE_LOCK: _CACHE.clear()


# --- CANALES DE DATOS DE SPA, SIN JAVASCRIPT (medidos en t16, contrato de t17) --
# Un SPA moderno suele exponer sus datos sin ejecutar JS, por tres canales que se
# midieron de verdad: Nuxt 3 sirve /_payload.json; el App Router de Next sirve el
# arbol flight cuando la peticion lleva la CABECERA RSC: 1; y los propios bundles
# .js del sitio citan endpoints JSON que no hay que adivinar.
#
# NO se implementa /_next/data/<buildId>/<ruta>.json: t16 lo midio MUERTO en
# pancakeswap (HTTP 200 con content-type text/html y el cuerpo del shell). Un 200
# enganya: aqui se valida el CUERPO, nunca el codigo de estado (trampa T1).
#
# Filtrar solo por application/json descarta el canal RSC (text/x-component): la
# lista blanca incluye ambos (trampa T2).
#
# Esta via es ADICIONAL y estatica: no toca el render headless existente, no
# descarga navegador, no envia credenciales y no ejecuta el payload.
SPA_CAPS = {
    'payload_max_bytes': 8 * 1024 * 1024, 'payload_timeout': 25,
    'bundle_max_bytes': 4 * 1024 * 1024, 'bundle_timeout': 20,
    'max_bundles': 30, 'max_bundle_bytes': 30 * 1024 * 1024,
    'derived_max_bytes': 8 * 1024 * 1024, 'derived_timeout': 25,
    'max_derived': 8, 'robots_max_bytes': 64 * 1024, 'robots_timeout': 10,
    'max_requests': 35, 'max_bytes': 40 * 1024 * 1024,
    'min_payload_bytes': 1024,
}
SPA_CONTENT_TYPES = ('application/json', 'text/x-component')
SPA_CROSS_ORIGIN_MARK = 'CONFIRMED: spa2 cross-origin derivado'
SPA_NUXT_MARKS = (b'__NUXT_DATA__', b'window.__NUXT__', b'/_payload.json', b'/_nuxt/')
SPA_NEXT_MARKS = (b'__NEXT_DATA__', b'self.__next_f', b'/_next/static/')
SPA_ASSET_SUFFIXES = ('.js', '.mjs', '.css', '.png', '.jpg', '.jpeg', '.svg', '.gif', '.webp',
                      '.woff', '.woff2', '.ttf', '.ico', '.map', '.wasm', '.avif', '.mp4', '.json.license')
_SPA_ABS_URL = re.compile(r'https://([A-Za-z0-9](?:[A-Za-z0-9.-]{0,61}[A-Za-z0-9])?)/[A-Za-z0-9._~%\-/]{1,200}')
_SPA_REL_JSON = re.compile(r'["\'(](/(?:[A-Za-z0-9._~%\-]+/)*[A-Za-z0-9._~%\-]+\.json)["\')]')
_SPA_SCRIPT_SRC = re.compile(rb'<script[^>]+src=["\']([^"\']{1,500})["\']', re.I)
_SPA_FLIGHT_LINE = re.compile(rb'^[0-9a-fA-F]{1,8}:')


def _spa_shell_body(data):
    """T1: un cuerpo que empieza por '<' es el shell, con cualquier content-type."""
    return data[:512].lstrip().lower().startswith(b'<')


def _spa_json_body(data):
    """Validador del canal JSON: no shell, parsea, raiz contenedor, tamano minimo.

    El orden importa: T1 dice que el shell se descarta SIEMPRE, con cualquier mime
    y cualquier tamano; el tamano minimo es una condicion posterior.
    """
    if _spa_shell_body(data):
        return False, 'shell_body'
    if len(data) < SPA_CAPS['min_payload_bytes']:
        return False, 'payload_too_small'
    try:
        value = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return False, 'invalid_json'
    if not isinstance(value, (dict, list)):
        return False, 'json_root_not_container'
    return True, 'ok'


def _spa_flight_body(data):
    """Validador del canal RSC/flight: no shell, lineas id:payload con referencias $."""
    if _spa_shell_body(data):
        return False, 'shell_body'
    if len(data) < SPA_CAPS['min_payload_bytes']:
        return False, 'payload_too_small'
    if not any(_SPA_FLIGHT_LINE.match(line) for line in data.splitlines()[:2000]):
        return False, 'not_flight_stream'
    if b'$' not in data[:400000]:
        return False, 'flight_without_refs'
    return True, 'ok'


def _spa_text(data, channel):
    """Texto citable del payload. Se DESERIALIZA; jamas se ejecuta (X6)."""
    if channel == 'next_rsc':
        return data.decode('utf-8', errors='replace')[:12000]
    try:
        return json.dumps(json.loads(data.decode('utf-8')), ensure_ascii=False)[:12000]
    except (UnicodeDecodeError, ValueError):
        return data.decode('utf-8', errors='replace')[:12000]


def _spa_content_type(headers):
    return str(headers.get('content-type', '')).split(';')[0].strip().lower()


def _spa_spa_markers(html):
    """Deteccion barata y sin red: que canales son PLAUSIBLES para este HTML."""
    found = {'nuxt': any(mark in html for mark in SPA_NUXT_MARKS),
             'next': any(mark in html for mark in SPA_NEXT_MARKS)}
    bundles = []
    for raw in _SPA_SCRIPT_SRC.findall(html)[:120]:
        try:
            src = raw.decode('utf-8', errors='replace')
        except Exception:
            continue
        if '/_next/static/' in src or '/_nuxt/' in src or re.search(r'/static/js/[^/]+\.js$', src):
            bundles.append(src)
    found['spa_bundles'] = bundles[:SPA_CAPS['max_bundles']]
    return found


def _spa_derived_candidates(text):
    """URLs de datos que el bundle CITA (no se inventa ninguna: X4)."""
    origin_less = []
    for match in _SPA_REL_JSON.finditer(text):
        origin_less.append(('relativo', match.group(1)))
    for match in _SPA_ABS_URL.finditer(text):
        host = match.group(1).lower()
        if re.fullmatch(r'\d+\.\d+\.\d+\.\d+', host):
            continue
        url = match.group(0)
        if url.lower().endswith(SPA_ASSET_SUFFIXES):
            continue
        origin_less.append(('absoluto', url))
    return origin_less


def _spa_host_derivado_ok(url):
    """E1.2: hostname exacto, HTTPS, puerto 443, sin userinfo, sin IP literal."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    host = parsed.hostname or ''
    return (parsed.scheme == 'https' and bool(host) and '/' not in host and port in (None, 443)
            and not parsed.username and not parsed.password
            and not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', host)
            and bool(re.fullmatch(r'[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?', host)))


def _spa_channels(root, root_html, fetch, robots, gap, deadline, allow_derived_cross_origin=False, restante=None):
    """Lee datos de SPA por los canales MEDIDOS. Devuelve el registro, nunca lanza.

    Orden: (1) Nuxt /_payload.json, (2) Next con la CABECERA RSC: 1, (3) endpoints
    JSON citados por los bundles same-origin del propio sitio. Todo es same-origin
    por defecto: lo cross-origin exige `allow_derived_cross_origin` (firma E1 del
    operador); sin esa firma se registra el motivo y NO se pide (X3).
    """
    origin = _origin(root)
    if restante is None:
        restante = lambda: SPA_CAPS['max_bytes']
    state = {'requests': 0, 'bytes': 0}
    doc = {'channel': None, 'js_rendered': False, 'mechanism': None, 'origin': origin,
           'attempts': [], 'payloads': [], 'bundles_read': [], 'cross_origin_candidates': [],
           'determinism': {'reads': 2, 'stable': None},
           'allow_derived_cross_origin': bool(allow_derived_cross_origin),
           'limits': {'payload_max_bytes': SPA_CAPS['payload_max_bytes'],
                      'payload_timeout': SPA_CAPS['payload_timeout'],
                      'bundle_max_bytes': SPA_CAPS['bundle_max_bytes'],
                      'max_bundles': SPA_CAPS['max_bundles'],
                      'derived_max_bytes': SPA_CAPS['derived_max_bytes'],
                      'max_derived': SPA_CAPS['max_derived'],
                      'max_requests': SPA_CAPS['max_requests'], 'max_bytes': SPA_CAPS['max_bytes'],
                      'content_types': list(SPA_CONTENT_TYPES)},
           'limitations': ['no_javascript_execution', 'same_origin_only_unless_signed',
                           'static_payload_may_be_partial', 'not_a_complete_site_inventory']}

    def note(channel, url, reason, **extra):
        item = {'channel': channel, 'url': url, 'reason': reason}
        item.update(extra)
        doc['attempts'].append(item)
        gap(url, channel + ':' + reason)

    def read(url, cap_bytes, timeout, extra_headers=None, robots_parser=None):
        if state['requests'] >= SPA_CAPS['max_requests']:
            raise providers.ProviderError('spa_request_budget')
        if state['bytes'] + cap_bytes > SPA_CAPS['max_bytes']:
            raise providers.ProviderError('spa_byte_budget')
        if time.monotonic() >= deadline:
            raise providers.ProviderError('deadline_budget')
        parser = robots_parser if robots_parser is not None else robots
        if parser is not None and not parser.can_fetch(USER_AGENT, url):
            raise providers.ProviderError('robots_disallowed')
        # El presupuesto de bytes del sitio es UNO solo: se pide lo que queda, no el cap
        # global. Sin esto, cualquier payload pedia 8 MiB y moria en byte_budget.
        disponible = restante() - 1
        limite = min(cap_bytes, disponible)
        if limite < SPA_CAPS['min_payload_bytes']:
            raise providers.ProviderError('spa_byte_budget')
        status, headers, data = fetch(url, limite, extra_headers)
        state['requests'] += 1
        state['bytes'] += len(data)
        return status, {str(k).lower(): v for k, v in headers.items()}, data

    def aceptar(channel, url, headers, data, derived_from=None):
        doc['payloads'].append({'channel': channel, 'url': url,
                                'sha256': hashlib.sha256(data).hexdigest(),
                                'byte_count': len(data), 'content_type': _spa_content_type(headers),
                                'derived_from': derived_from, 'text': _spa_text(data, channel)})
        if doc['channel'] is None:
            doc['channel'] = channel
            doc['mechanism'] = {'nuxt_payload': 'GET /_payload.json (Nuxt 3)',
                                'next_rsc': 'GET misma URL con cabecera RSC: 1 (App Router)',
                                'derived_endpoints': 'endpoints JSON citados por bundles same-origin'}[channel]
        return True

    def canal(channel, url, validador, content_types, extra_headers=None):
        """Una lectura valida; solo si el cuerpo sirve se paga la SEGUNDA (P9)."""
        try:
            st1, hd1, d1 = read(url, SPA_CAPS['payload_max_bytes'], SPA_CAPS['payload_timeout'], extra_headers)
        except Exception as exc:
            note(channel, url, str(exc) if isinstance(exc, providers.ProviderError) else 'read_failed')
            return False
        if st1 != 200:
            note(channel, url, 'HTTP_' + str(st1), byte_count=len(d1))
            return False
        ctype = _spa_content_type(hd1)
        if ctype not in content_types:
            note(channel, url, 'content_type_no_permitido:' + (ctype or 'ausente'),
                 content_type=ctype, byte_count=len(d1))
            return False
        ok, reason = validador(d1)
        if not ok:
            note(channel, url, reason, content_type=ctype, byte_count=len(d1),
                 sha256=hashlib.sha256(d1).hexdigest())
            return False
        try:
            st2, hd2, d2 = read(url, SPA_CAPS['payload_max_bytes'], SPA_CAPS['payload_timeout'], extra_headers)
        except Exception as exc:
            note(channel, url, 'segunda_lectura:' + (str(exc) if isinstance(exc, providers.ProviderError) else 'read_failed'))
            return False
        sha1, sha2 = hashlib.sha256(d1).hexdigest(), hashlib.sha256(d2).hexdigest()
        if st2 != 200 or sha1 != sha2:
            doc['determinism'] = {'reads': 2, 'stable': False}
            note(channel, url, 'no_determinista', sha256=sha1, sha256_segunda=sha2)
            return False
        doc['determinism'] = {'reads': 2, 'stable': True}
        return aceptar(channel, url, hd1, d1)

    markers = _spa_spa_markers(root_html or b'')
    if root_html is None:
        doc['limitations'].append('root_html_no_disponible')
    if not (markers['nuxt'] or markers['next'] or markers['spa_bundles']):
        doc['limitations'].append('sin_marcadores_de_spa')
        return doc

    # (1) Nuxt 3
    if markers['nuxt']:
        canal('nuxt_payload', origin + '/_payload.json', _spa_json_body, ('application/json',))

    # (2) Next App Router: la CABECERA RSC: 1 es el discriminador; ?_rsc=1 NO sirve
    if markers['next'] and doc['channel'] is None:
        canal('next_rsc', root, _spa_flight_body, ('text/x-component',), {'RSC': '1'})

    # (3) Endpoints JSON citados por los bundles same-origin del sitio
    if markers['spa_bundles'] and doc['channel'] is None:
        _spa_derived_endpoints(root, origin, markers['spa_bundles'], read, note, aceptar, doc)
    return doc


def _spa_derived_endpoints(root, origin, bundles, read, note, aceptar, doc):
    """Lee bundles same-origin y deriva de ellos endpoints JSON citados (X4)."""
    vistos = set()
    bundle_bytes = 0
    for src in bundles[:SPA_CAPS['max_bundles']]:
        try:
            bundle_url = canonical_url(src, root)
        except (providers.ProviderError, ValueError, TypeError):
            note('derived_endpoints', str(src)[:500], 'bundle_url_invalida')
            continue
        if _origin(bundle_url) != origin:
            note('derived_endpoints', bundle_url, 'bundle_cross_origin')
            continue
        if bundle_url in vistos:
            continue
        vistos.add(bundle_url)
        try:
            status, headers, data = read(bundle_url, SPA_CAPS['bundle_max_bytes'],
                                         SPA_CAPS['bundle_timeout'])
        except Exception as exc:
            note('derived_endpoints', bundle_url,
                 str(exc) if isinstance(exc, providers.ProviderError) else 'read_failed')
            continue
        if status != 200:
            note('derived_endpoints', bundle_url, 'HTTP_' + str(status))
            continue
        bundle_bytes += len(data)
        if bundle_bytes > SPA_CAPS['max_bundle_bytes']:
            note('derived_endpoints', bundle_url, 'bundle_byte_budget')
            break
        sha_bundle = hashlib.sha256(data).hexdigest()
        doc['bundles_read'].append({'url': bundle_url, 'sha256': sha_bundle, 'byte_count': len(data)})
        texto = data.decode('utf-8', errors='replace')
        candidatos = []
        for kind, value in _spa_derived_candidates(texto):
            try:
                target = canonical_url(value, root) if kind == 'relativo' else value
            except (providers.ProviderError, ValueError, TypeError):
                continue
            if target not in candidatos:
                candidatos.append(target)
        for target in candidatos[:SPA_CAPS['max_derived']]:
            if len(doc['payloads']) >= SPA_CAPS['max_derived']:
                note('derived_endpoints', target, 'derived_budget', derived_from=sha_bundle)
                continue
            cross = _origin(target) != origin
            if cross:
                host = urlsplit(target).hostname or ''
                doc['cross_origin_candidates'].append({'url': target, 'host': host,
                                                       'derived_from': sha_bundle})
                if not doc['allow_derived_cross_origin']:
                    note('derived_endpoints', target, 'cross_origin_sin_firma',
                         derived_from=sha_bundle, host=host)
                    continue
                if not _spa_host_derivado_ok(target):
                    note('derived_endpoints', target, 'host_derivado_invalido', derived_from=sha_bundle)
                    continue
                derivado_robots = _spa_robots_derivado(target, read, note, sha_bundle)
                if derivado_robots is False:
                    continue
            else:
                derivado_robots = None
            try:
                status, headers, data = read(target, SPA_CAPS['derived_max_bytes'],
                                             SPA_CAPS['derived_timeout'],
                                             robots_parser=derivado_robots)
            except Exception as exc:
                note('derived_endpoints', target,
                     str(exc) if isinstance(exc, providers.ProviderError) else 'read_failed',
                     derived_from=sha_bundle)
                continue
            if status != 200:
                note('derived_endpoints', target, 'HTTP_' + str(status), derived_from=sha_bundle)
                continue
            ctype = _spa_content_type(headers)
            ok, reason = _spa_json_body(data)
            if ctype not in SPA_CONTENT_TYPES:
                note('derived_endpoints', target, 'content_type_no_permitido:' + (ctype or 'ausente'),
                     content_type=ctype, derived_from=sha_bundle)
            elif not ok:
                note('derived_endpoints', target, reason, content_type=ctype, derived_from=sha_bundle)
            else:
                aceptar('derived_endpoints', target, headers, data, derived_from=sha_bundle)


def _spa_robots_derivado(target, read, note, sha_bundle):
    """E1.4: robots del host derivado ANTES del primer fetch; 5xx = STOP."""
    origen = 'https://' + (urlsplit(target).hostname or '')
    try:
        status, headers, data = read(origen + '/robots.txt', SPA_CAPS['robots_max_bytes'],
                                     SPA_CAPS['robots_timeout'])
    except Exception as exc:
        note('derived_endpoints', origen + '/robots.txt',
             str(exc) if isinstance(exc, providers.ProviderError) else 'robots_derivado_ilegible',
             derived_from=sha_bundle)
        return False
    if status in (404, 410):
        parser = RobotFileParser(); parser.parse([]); return parser
    if status != 200:
        note('derived_endpoints', origen + '/robots.txt', 'robots_derivado_HTTP_' + str(status),
             derived_from=sha_bundle)
        return False
    parser = RobotFileParser()
    parser.parse(data.decode('utf-8', errors='replace').splitlines())
    return parser


SPA_CHANNELS = ('nuxt_payload', 'next_rsc', 'derived_endpoints')
SPA_ATTEMPT_EXTRAS = ('sha256', 'sha256_segunda', 'host', 'byte_count', 'content_type', 'derived_from')
_SPA_HEX64 = re.compile(r'[0-9a-f]{64}')


def _prepare_spa_data(spa, root, text):
    """Normaliza y verifica los datos de SPA para la puerta de consentimiento.

    Sin red. Rechaza cualquier payload cuya procedencia no cuadre (origen distinto
    al de la pagina sin firma, sha no hexadecimal, js_rendered distinto de False) y
    devuelve una forma que es punto fijo: validar(validar(x)) == validar(x).
    """
    if not isinstance(spa, dict):
        raise providers.ProviderError('Datos de SPA inválidos.')
    canal = spa.get('channel')
    if canal is not None and canal not in SPA_CHANNELS:
        raise providers.ProviderError('Canal de SPA inválido.')
    if spa.get('js_rendered') is not False:
        raise providers.ProviderError('Los datos de SPA no declaran js_rendered:false.')
    permitido = spa.get('allow_derived_cross_origin') is True
    salida = {'channel': canal, 'js_rendered': False,
              'mechanism': text(spa.get('mechanism') or '', 300) or None,
              'origin': _origin(root), 'allow_derived_cross_origin': permitido,
              'attempts': [], 'payloads': [], 'bundles_read': [], 'cross_origin_candidates': [],
              'determinism': {'reads': providers._bounded_int(
                                  (spa.get('determinism') or {}).get('reads', 0), 0, 10, 'determinism reads'),
                              'stable': (spa.get('determinism') or {}).get('stable')},
              'limits': {}, 'limitations': []}
    if salida['determinism']['stable'] not in (True, False, None):
        raise providers.ProviderError('Determinismo de SPA inválido.')
    limites = spa.get('limits') if isinstance(spa.get('limits'), dict) else {}
    for clave, alto in (('payload_max_bytes', 8388608), ('payload_timeout', 60),
                        ('bundle_max_bytes', 8388608), ('max_bundles', 30),
                        ('derived_max_bytes', 8388608), ('max_derived', 16),
                        ('max_requests', 35), ('max_bytes', 41943040)):
        if clave in limites:
            salida['limits'][clave] = providers._bounded_int(limites[clave], 1, alto, clave)
    if 'content_types' in limites:
        tipos = limites['content_types']
        if not isinstance(tipos, list) or len(tipos) > 8 or any(t not in SPA_CONTENT_TYPES for t in tipos):
            raise providers.ProviderError('Content-types de SPA inválidos.')
        salida['limits']['content_types'] = list(tipos)
    intentos = spa.get('attempts') if isinstance(spa.get('attempts'), list) else []
    if len(intentos) > 200:
        raise providers.ProviderError('Intentos de SPA fuera de límite.')
    for intento in intentos:
        if not isinstance(intento, dict) or intento.get('channel') not in SPA_CHANNELS:
            raise providers.ProviderError('Intento de SPA inválido.')
        item = {'channel': intento['channel'], 'url': text(intento.get('url', ''), 2048),
                'reason': text(intento.get('reason', ''), 500)}
        for extra in SPA_ATTEMPT_EXTRAS:
            if extra not in intento:
                continue
            if extra in ('sha256', 'sha256_segunda', 'derived_from'):
                if not isinstance(intento[extra], str) or not _SPA_HEX64.fullmatch(intento[extra]):
                    raise providers.ProviderError('Huella de intento de SPA inválida.')
                item[extra] = intento[extra]
            elif extra == 'byte_count':
                item[extra] = providers._bounded_int(intento[extra], 0, 41943040, extra)
            else:
                item[extra] = text(intento[extra], 300)
        salida['attempts'].append(item)
    payloads = spa.get('payloads') if isinstance(spa.get('payloads'), list) else []
    if len(payloads) > 16:
        raise providers.ProviderError('Payloads de SPA fuera de límite.')
    for dato in payloads:
        if not isinstance(dato, dict) or dato.get('channel') not in SPA_CHANNELS:
            raise providers.ProviderError('Payload de SPA inválido.')
        target = canonical_url(dato.get('url'))
        sha = dato.get('sha256')
        ctype = dato.get('content_type')
        if not isinstance(sha, str) or not _SPA_HEX64.fullmatch(sha):
            raise providers.ProviderError('Huella de payload de SPA inválida.')
        if ctype not in SPA_CONTENT_TYPES:
            raise providers.ProviderError('Content-type de payload de SPA inválido.')
        derivado = dato.get('derived_from')
        if derivado is not None and (not isinstance(derivado, str) or not _SPA_HEX64.fullmatch(derivado)):
            raise providers.ProviderError('Origen derivado de payload inválido.')
        if _origin(target) != _origin(root) and not (permitido and derivado):
            raise providers.ProviderError('Payload de SPA fuera del origen de la página sin firma.')
        salida['payloads'].append({'channel': dato['channel'], 'url': target, 'sha256': sha,
                                   'byte_count': providers._bounded_int(dato.get('byte_count'), 0, 41943040, 'payload bytes'),
                                   'content_type': ctype, 'derived_from': derivado,
                                   'text': text(dato.get('text', ''))})
    bundles = spa.get('bundles_read') if isinstance(spa.get('bundles_read'), list) else []
    if len(bundles) > 30:
        raise providers.ProviderError('Bundles de SPA fuera de límite.')
    for bundle in bundles:
        if not isinstance(bundle, dict) or not isinstance(bundle.get('sha256'), str) \
                or not _SPA_HEX64.fullmatch(bundle['sha256']):
            raise providers.ProviderError('Bundle de SPA inválido.')
        salida['bundles_read'].append({'url': canonical_url(bundle.get('url')), 'sha256': bundle['sha256'],
                                       'byte_count': providers._bounded_int(bundle.get('byte_count'), 0, 41943040, 'bundle bytes')})
    candidatos = spa.get('cross_origin_candidates') if isinstance(spa.get('cross_origin_candidates'), list) else []
    if len(candidatos) > 32:
        raise providers.ProviderError('Candidatos cross-origin fuera de límite.')
    for candidato in candidatos:
        if not isinstance(candidato, dict):
            raise providers.ProviderError('Candidato cross-origin inválido.')
        host = candidato.get('host')
        derivado = candidato.get('derived_from')
        if not isinstance(host, str) or not host or len(host) > 253 \
                or not isinstance(derivado, str) or not _SPA_HEX64.fullmatch(derivado):
            raise providers.ProviderError('Candidato cross-origin sin procedencia.')
        salida['cross_origin_candidates'].append({'url': text(candidato.get('url', ''), 2048),
                                                  'host': text(host, 253), 'derived_from': derivado})
    limitaciones = spa.get('limitations') if isinstance(spa.get('limitations'), list) else []
    if len(limitaciones) > 20:
        raise providers.ProviderError('Limitaciones de SPA fuera de límite.')
    salida['limitations'] = [text(item, 200) for item in limitaciones]
    return salida



def analyze_website(url, *, max_pages=12, max_bytes=600000, max_depth=2,
                    max_requests=30, deadline_seconds=30, concurrency=4,
                    cache_ttl=300, transport=None, allow_derived_cross_origin=False):
    """Collect bounded same-origin evidence; errors and omissions are explicit.

    Deadline prevents scheduling new reads; an in-flight TLS/DNS operation may
    finish later. Robots rules are reread even when HTML snapshots are cached.

    ``allow_derived_cross_origin`` nace en False: abrir hosts que el sitio cita
    fuera de su origen exige la firma del operador (`CONFIRMED: spa2 cross-origin
    derivado`), no una decision del lector. Sin ella, esos endpoints se registran
    con su motivo y NO se piden.
    """
    for value, low, high, name in ((max_pages,1,100,'pages'),(max_bytes,1024,4000000,'bytes'),
            (max_depth,0,5,'depth'),(max_requests,1,300,'requests'),(deadline_seconds,1,120,'deadline'),
            (concurrency,1,8,'parallelism'),(cache_ttl,0,3600,'TTL')):
        providers._bounded_int(value,low,high,name)
    start = time.monotonic(); deadline = start + deadline_seconds
    root = canonical_url(url); origin = _origin(root)
    lock = threading.Lock(); stats = {'requests':0,'bytes':0,'cache_hits':0}
    gaps = []; snapshots = []; seen = set(); discovered = set(); variants = {}
    root_html = {'data': None}
    namespace = id(transport) if transport is not None else 'public_tls'

    def gap(target, reason):
        with lock:
            if len(gaps) < 500: gaps.append({'url': target, 'reason': reason})

    def restante():
        with lock: return max(0, max_bytes - stats['bytes'])

    def fetch(target, limit, extra_headers=None):
        with lock:
            if time.monotonic() >= deadline: raise providers.ProviderError('deadline_budget')
            if stats['requests'] >= max_requests: raise providers.ProviderError('request_budget')
            if stats['bytes'] + limit + 1 > max_bytes: raise providers.ProviderError('byte_budget')
            stats['requests'] += 1
            # Reserve bytes before concurrent requests; release unused allowance.
            stats['bytes'] += limit + 1
        data = b''; consumed = limit + 1
        headers_salida = {'User-Agent':USER_AGENT,'Accept':'text/html,text/plain;q=0.9',
                          'Accept-Encoding':'identity'}
        for nombre, valor in (extra_headers or {}).items():
            headers_salida[str(nombre)] = str(valor)
        try:
            status, headers, data = (transport or providers._https_transport)(
                'GET', target, headers_salida, None,
                max(1, min(10, int(deadline-time.monotonic()))), limit)
            if not isinstance(data, bytes) or len(data)>limit: raise providers.ProviderError('response_byte_limit')
            consumed = len(data)
            return status, {str(k).lower():v for k,v in headers.items()}, data
        finally:
            with lock: stats['bytes'] -= max(0, limit + 1 - consumed)

    robots = RobotFileParser(); robots_url = origin + '/robots.txt'
    robots_ok = False; crawl_delay = 0
    try:
        status, headers, data = fetch(robots_url, min(64000,max_bytes-1))
        if status in (404,410): robots.parse([]); robots_ok = True
        elif status == 200:
            if b'<html' in data[:500].lower(): raise providers.ProviderError('robots_invalid_html')
            robots.parse(data.decode('utf-8',errors='replace').splitlines()); robots_ok = True
            crawl_delay = robots.crawl_delay(USER_AGENT) or 0
            rate = robots.request_rate(USER_AGENT)
            if rate: crawl_delay = max(crawl_delay,rate.seconds/rate.requests)
        else: gap(robots_url, 'robots_unavailable_HTTP_' + str(status))
    except Exception as exc:
        gap(robots_url, str(exc) if isinstance(exc,providers.ProviderError) else 'robots_unavailable')
    if not robots_ok: gap(root,'robots_unverified_no_crawl')
    last_read = time.monotonic()

    def page(target):
        original = target
        try:
            for hop in range(4):
                if not robots.can_fetch(USER_AGENT,target): gap(target,'robots_disallowed'); return None
                key = (namespace,target)
                with _CACHE_LOCK:
                    cached = _CACHE.get(key)
                    if cache_ttl and cached and time.monotonic()-cached[0] <= cache_ttl:
                        result = copy.deepcopy(cached[1]); result['cache_hit'] = True
                        with lock: stats['cache_hits'] += 1
                        return result
                with lock: remaining = max_bytes-stats['bytes']
                allowance = min(150000, max(0,max(0,remaining-1) // concurrency))
                if allowance < 256: raise providers.ProviderError('byte_budget')
                status, headers, data = fetch(target,allowance)
                if status in (301,302,303,307,308):
                    location = headers.get('location')
                    if not location: raise providers.ProviderError('redirect_missing_location')
                    redirected = canonical_url(location,target)
                    if _origin(redirected)!=origin: raise providers.ProviderError('cross_origin_redirect_blocked')
                    if crawl_delay: raise providers.ProviderError('redirect_deferred_for_robots_delay')
                    target = redirected; continue
                if status != 200: raise providers.ProviderError('HTTP_'+str(status))
                if headers.get('content-encoding','identity').lower() not in ('','identity'):
                    raise providers.ProviderError('unsupported_content_encoding')
                if not any(kind in headers.get('content-type','').lower() for kind in ('text/html','application/xhtml+xml')):
                    raise providers.ProviderError('non_html_content')
                result = _extract(target,data); result['cache_hit'] = False
                if original == root: root_html['data'] = data
                if original != target: result['requested_url'] = original
                with _CACHE_LOCK:
                    _CACHE[key] = (time.monotonic(),copy.deepcopy(result),transport); _CACHE.move_to_end(key)
                    while len(_CACHE)>100 or sum(v[1]['byte_count'] for v in _CACHE.values())>CACHE_BYTES:
                        _CACHE.popitem(last=False)
                return result
            raise providers.ProviderError('redirect_budget')
        except Exception as exc:
            gap(original,str(exc) if isinstance(exc,providers.ProviderError) else 'read_failed')
            return None

    queue = [(root,0)] if robots_ok else []
    while queue and len(seen)<max_pages and time.monotonic()<deadline:
        size = min(1 if crawl_delay else concurrency,max_pages-len(seen),len(queue))
        batch, queue = queue[:size], queue[size:]
        if crawl_delay:
            wait = max(0,last_read+crawl_delay-time.monotonic())
            if time.monotonic()+wait>=deadline: gap(root,'robots_delay_exceeds_deadline'); break
            time.sleep(wait)
        seen.update(target for target,_ in batch)
        with ThreadPoolExecutor(max_workers=size) as executor:
            results = list(executor.map(page,[target for target,_ in batch]))
        last_read = time.monotonic()
        for (_,depth),result in zip(batch,results):
            if not result: continue
            if result['url'] not in {p['url'] for p in snapshots}: snapshots.append(result)
            if result['content_status']!='usable_static_html': gap(result['url'],result['content_status'])
            for href in result['links']:
                try: target = canonical_url(href,result['url'])
                except (ValueError,TypeError): continue
                if _origin(target)!=origin: continue
                if target in seen or target in discovered: continue
                discovered.add(target)
                path = urlsplit(target).path
                if re.search(r'/(?:logout|signout|delete|unsubscribe)(?:/|$)',path,re.I):
                    gap(target,'unsafe_action_link'); continue
                variants[path] = variants.get(path,0)+1
                if variants[path]>3: gap(target,'query_variant_budget'); continue
                if depth>=max_depth: gap(target,'depth_budget'); continue
                if len(queue)>=max_pages*5: gap(target,'frontier_budget'); continue
                queue.append((target,depth+1))
    for target,_ in queue: gap(target,'page_or_deadline_budget')
    # --- Canales de datos de SPA (estaticos, sin navegador) -------------------
    # Adicional: si el sitio no es un SPA ni expone datos, no se pide nada y el
    # resultado queda exactamente como antes. Cacheado por origen para que una
    # segunda lectura no repita peticiones (los tests de cache lo exigen).
    clave_spa = (namespace, origin, 'spa_data')
    spa_datos = None
    with _CACHE_LOCK:
        cacheado = _CACHE.get(clave_spa)
        if cache_ttl and cacheado and time.monotonic()-cacheado[0] <= cache_ttl:
            # No cuenta como cache_hit de PAGINA: timings['cache_hits'] mide snapshots HTML.
            spa_datos = copy.deepcopy(cacheado[1]['spa_data'])
    if spa_datos is None:
        if robots_ok:
            spa_datos = _spa_channels(root, root_html.get('data'), fetch, robots, gap, deadline,
                                      allow_derived_cross_origin, restante)
        else:
            spa_datos = {'channel': None, 'js_rendered': False, 'attempts': [], 'payloads': [],
                         'limitations': ['robots_unverified_no_spa_channels'], 'determinism': {'reads': 0, 'stable': None},
                         'allow_derived_cross_origin': bool(allow_derived_cross_origin),
                         'bundles_read': [], 'cross_origin_candidates': [], 'origin': origin}
        with _CACHE_LOCK:
            _CACHE[clave_spa] = (time.monotonic(),
                                 {'byte_count': sum(p['byte_count'] for p in spa_datos.get('payloads', [])),
                                  'spa_data': copy.deepcopy(spa_datos)}, transport)
            _CACHE.move_to_end(clave_spa)
            while len(_CACHE)>100 or sum(v[1].get('byte_count',0) for v in _CACHE.values())>CACHE_BYTES:
                _CACHE.popitem(last=False)
    manifest = [{'url':p['url'],'sha256':p['sha256']} for p in sorted(snapshots,key=lambda p:p['url'])]
    source_hash = hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    evidence = [{'url':p['url'],'sha256':p['sha256'],'text':p['text_excerpt']} for p in snapshots if p['content_status']=='usable_static_html']
    # Los payloads de SPA entran como evidencia PROPIA: el mecanismo, el sha256 del
    # cuerpo leido y la marca js_rendered:false viajan con el dato (P5/P6).
    for dato in spa_datos.get('payloads', []):
        evidence.append({'url':dato['url'],'sha256':dato['sha256'],'text':dato['text'],
                         'channel':dato['channel'],'js_rendered':False,'derived_from':dato.get('derived_from')})
    limitaciones = ['static_html_only','no_javascript_rendering','no_authenticated_pages',
                    'same_origin_only','not_a_complete_site_inventory','in_flight_network_may_exceed_deadline']
    if spa_datos.get('payloads'):
        limitaciones.append('spa_data_via_static_channels_without_javascript')
    coverage = {'status':'partial' if evidence else 'no_usable_evidence','complete':False,
                'inventory_complete':False,'pages_fetched':len(snapshots),'pages_attempted':len(seen),
                'discovered_urls':len(discovered),'requests':stats['requests'],'bytes':stats['bytes'],
                'gaps':gaps,'scope':{'origin':origin,'max_pages':max_pages,'max_depth':max_depth,
                'max_requests':max_requests,'max_bytes':max_bytes,'deadline_seconds':deadline_seconds},
                'limitations':limitaciones}
    return {'source_kind':'website','source_url':root,'source_hash':source_hash,
            'snapshots':snapshots,'coverage':coverage,'evidence':evidence,'spa_data':spa_datos,
            'summary':{'titles':[p['title'] for p in snapshots],'usable_pages':len(evidence)},
            'timings':{'elapsed_seconds':round(time.monotonic()-start,4),'cache_hits':stats['cache_hits'],
                       'concurrency':concurrency}}


def prepare_website_summary(summary):
    """Allowlist/redact static website evidence for the existing consent gate.

    SHA256 identifies the original fetched body, not its redacted excerpt.
    This function does no network I/O and never grants provider consent.
    """
    if not isinstance(summary,dict) or summary.get('source_kind')!='website':
        raise providers.ProviderError('Resumen web inválido.')
    root = canonical_url(summary.get('source_url'))
    raw = summary.get('snapshots')
    if not isinstance(raw,list) or len(raw)>100:
        raise providers.ProviderError('Snapshots web inválidos.')
    result = {'source_kind':'website','source_url':root,'snapshots':[],'evidence':[]}
    urls = set()
    def text(value, limit=12000):
        return providers.redact_text(providers._text(value,limit,allow_empty=True))
    for page in raw:
        if not isinstance(page,dict): raise providers.ProviderError('Snapshot web inválido.')
        target = canonical_url(page.get('url'))
        sha = page.get('sha256'); fetched = page.get('fetched_at')
        if _origin(target)!=_origin(root) or target in urls or not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{64}',sha):
            raise providers.ProviderError('Procedencia de snapshot inválida.')
        urls.add(target)
        try:
            date = datetime.fromisoformat(fetched.replace('Z','+00:00'))
            if date.tzinfo is None: raise ValueError()
        except (AttributeError,TypeError,ValueError):
            raise providers.ProviderError('Fecha de snapshot inválida.') from None
        status = page.get('content_status')
        if status not in ('usable_static_html','javascript_shell','no_usable_evidence'):
            raise providers.ProviderError('Estado de evidencia web inválido.')
        count = providers._bounded_int(page.get('byte_count'),0,4000000,'snapshot bytes')
        item = {'url':target,'sha256':sha,'fetched_at':fetched,'byte_count':count,
                'content_status':status,'javascript_rendered':False,
                'title':text(page.get('title',''),500),'text_excerpt':text(page.get('text_excerpt','')),
                'headings':[],'links':[],'forms':[],'buttons':[],'inputs':[],'roles':[]}
        for key, cap in (('headings',100),('links',300),('forms',50),('buttons',100),('inputs',100),('roles',100)):
            values = page.get(key,[])
            if not isinstance(values,list) or len(values)>cap:
                raise providers.ProviderError('Elementos HTML fuera de límite.')
            for value in values:
                if key=='headings':
                    if not isinstance(value,dict): raise providers.ProviderError('Encabezado inválido.')
                    item[key].append({'level':providers._bounded_int(value.get('level'),1,6,'heading'),'text':text(value.get('text',''),500)})
                elif key in ('forms','inputs'):
                    if not isinstance(value,dict): raise providers.ProviderError('Control HTML inválido.')
                    fields = ('method','action') if key=='forms' else ('tag','type','name','id','label')
                    item[key].append({field:text(value.get(field,''),500) for field in fields})
                else: item[key].append(text(value,2048 if key=='links' else 500))
        result['snapshots'].append(item)
        if status=='usable_static_html':
            if not item['text_excerpt'] and not any(item[k] for k in ('headings','forms','buttons','inputs')):
                raise providers.ProviderError('Snapshot sin evidencia utilizable.')
            result['evidence'].append({'url':target,'sha256':sha,'text':item['text_excerpt']})
    manifest = [{'url':p['url'],'sha256':p['sha256']} for p in sorted(result['snapshots'],key=lambda p:p['url'])]
    computed = hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    if summary.get('source_hash')!=computed: raise providers.ProviderError('Hash de manifiesto web inválido.')
    result['source_hash'] = computed
    coverage = summary.get('coverage',{})
    if not isinstance(coverage,dict): raise providers.ProviderError('Cobertura web inválida.')
    result['coverage'] = {'status':'partial' if result['evidence'] else 'no_usable_evidence',
                          'complete':False,'inventory_complete':False,'pages_fetched':len(raw),
                          'limitations':['static_html_only','no_javascript_rendering','no_authenticated_pages',
                                         'same_origin_only','not_a_complete_site_inventory']}
    for key in ('pages_attempted','discovered_urls','requests','bytes'):
        if key in coverage: result['coverage'][key] = providers._bounded_int(coverage[key],0,10000000,key)
    gaps = coverage.get('gaps',[])
    if not isinstance(gaps,list) or len(gaps)>500: raise providers.ProviderError('Brechas web inválidas.')
    result['coverage']['gaps'] = []
    for gap in gaps:
        if not isinstance(gap,dict): raise providers.ProviderError('Brecha web inválida.')
        result['coverage']['gaps'].append({'url':text(gap.get('url',''),2048),'reason':text(gap.get('reason',''),500)})
    scope = coverage.get('scope',{})
    if not isinstance(scope,dict): raise providers.ProviderError('Alcance web inválido.')
    result['coverage']['scope'] = {'origin':_origin(root)}
    for key,low,high in (('max_pages',1,100),('max_depth',0,5),('max_requests',1,300),
                         ('max_bytes',1024,4000000),('deadline_seconds',1,120)):
        if key in scope:
            result['coverage']['scope'][key] = providers._bounded_int(scope[key],low,high,key)
    timings = summary.get('timings',{})
    if not isinstance(timings,dict): raise providers.ProviderError('Tiempos web inválidos.')
    result['timings'] = {}
    for key,low,high in (('cache_hits',0,100),('concurrency',1,8)):
        if key in timings: result['timings'][key] = providers._bounded_int(timings[key],low,high,key)
    elapsed = timings.get('elapsed_seconds')
    if elapsed is not None:
        if type(elapsed) not in (int,float) or not 0 <= elapsed <= 86400:
            raise providers.ProviderError('Tiempo web inválido.')
        result['timings']['elapsed_seconds'] = elapsed
    result['summary'] = {'titles':[p['title'] for p in result['snapshots']], 'usable_pages':len(result['evidence'])}
    # Datos de SPA: se verifican y viajan con su mecanismo y su sha256. Si el sitio
    # expone datos sin JS, la evidencia existe aunque el HTML sea solo el cascaron.
    if summary.get('spa_data') is not None:
        spa = _prepare_spa_data(summary['spa_data'], root, text)
        result['spa_data'] = spa
        for dato in spa['payloads']:
            result['evidence'].append({'url':dato['url'],'sha256':dato['sha256'],'text':dato['text'],
                                       'channel':dato['channel'],'js_rendered':False,
                                       'derived_from':dato['derived_from']})
        result['summary']['usable_pages'] = len(result['evidence'])
    if 'objective' in summary: result['objective'] = text(summary['objective'],5000)
    docs = summary.get('documents',[])
    if not isinstance(docs,list) or len(docs)>30: raise providers.ProviderError('Documentos web inválidos.')
    result['documents'] = []
    for doc in docs:
        if not isinstance(doc,dict): raise providers.ProviderError('Documento inválido.')
        result['documents'].append({'name':text(doc.get('name',''),200),'text':text(doc.get('text',''),200000)})
    if not result['evidence']: raise providers.ProviderError('No hay evidencia HTML utilizable para analizar.')
    if len(providers._dump(result).encode())>providers.MAX_INPUT_BYTES:
        raise providers.ProviderError('El resumen web supera el límite de 1.2 MB.')
    return result


def website_evidence_refs(summary):
    """Return exact URL evidence identifiers after provenance validation."""
    safe = prepare_website_summary(summary)
    return [item['url'] for item in safe['evidence']]
