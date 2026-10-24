"""Public, read-only HTML evidence. No browser, JavaScript, credentials or LLM.

All network reads use providers' DNS-pinned verified TLS transport. Injectable
transports are trusted fixtures only. Coverage never claims a whole website.
"""
from __future__ import annotations
import copy
import hashlib
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


def _extract(url, data):
    parser = _HTML()
    parser.feed(data.decode('utf-8', errors='replace'))
    text = ' '.join(parser.text)[:12000]
    usable = bool(len(text) >= 40 or parser.headings or parser.forms or parser.buttons or parser.inputs)
    embedded_only = False
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
            'javascript_rendered': False, 'embedded_only': embedded_only}


def clear_cache():
    with _CACHE_LOCK: _CACHE.clear()


def analyze_website(url, *, max_pages=12, max_bytes=600000, max_depth=2,
                    max_requests=30, deadline_seconds=30, concurrency=4,
                    cache_ttl=300, transport=None):
    """Collect bounded same-origin evidence; errors and omissions are explicit.

    Deadline prevents scheduling new reads; an in-flight TLS/DNS operation may
    finish later. Robots rules are reread even when HTML snapshots are cached.
    """
    for value, low, high, name in ((max_pages,1,100,'pages'),(max_bytes,1024,4000000,'bytes'),
            (max_depth,0,5,'depth'),(max_requests,1,300,'requests'),(deadline_seconds,1,120,'deadline'),
            (concurrency,1,8,'parallelism'),(cache_ttl,0,3600,'TTL')):
        providers._bounded_int(value,low,high,name)
    start = time.monotonic(); deadline = start + deadline_seconds
    root = canonical_url(url); origin = _origin(root)
    lock = threading.Lock(); stats = {'requests':0,'bytes':0,'cache_hits':0}
    gaps = []; snapshots = []; seen = set(); discovered = set(); variants = {}
    namespace = id(transport) if transport is not None else 'public_tls'

    def gap(target, reason):
        with lock:
            if len(gaps) < 500: gaps.append({'url': target, 'reason': reason})

    def fetch(target, limit):
        with lock:
            if time.monotonic() >= deadline: raise providers.ProviderError('deadline_budget')
            if stats['requests'] >= max_requests: raise providers.ProviderError('request_budget')
            if stats['bytes'] + limit + 1 > max_bytes: raise providers.ProviderError('byte_budget')
            stats['requests'] += 1
            # Reserve bytes before concurrent requests; release unused allowance.
            stats['bytes'] += limit + 1
        data = b''; consumed = limit + 1
        try:
            status, headers, data = (transport or providers._https_transport)(
                'GET', target, {'User-Agent':USER_AGENT,'Accept':'text/html,text/plain;q=0.9',
                                'Accept-Encoding':'identity'}, None,
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
    manifest = [{'url':p['url'],'sha256':p['sha256']} for p in sorted(snapshots,key=lambda p:p['url'])]
    source_hash = hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    evidence = [{'url':p['url'],'sha256':p['sha256'],'text':p['text_excerpt']} for p in snapshots if p['content_status']=='usable_static_html']
    coverage = {'status':'partial' if evidence else 'no_usable_evidence','complete':False,
                'inventory_complete':False,'pages_fetched':len(snapshots),'pages_attempted':len(seen),
                'discovered_urls':len(discovered),'requests':stats['requests'],'bytes':stats['bytes'],
                'gaps':gaps,'scope':{'origin':origin,'max_pages':max_pages,'max_depth':max_depth,
                'max_requests':max_requests,'max_bytes':max_bytes,'deadline_seconds':deadline_seconds},
                'limitations':['static_html_only','no_javascript_rendering','no_authenticated_pages',
                               'same_origin_only','not_a_complete_site_inventory','in_flight_network_may_exceed_deadline']}
    return {'source_kind':'website','source_url':root,'source_hash':source_hash,
            'snapshots':snapshots,'coverage':coverage,'evidence':evidence,
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
