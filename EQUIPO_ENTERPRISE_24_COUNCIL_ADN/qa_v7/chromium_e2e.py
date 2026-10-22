"""Arnés E2E real: conduce el panel de OrgDNA en Chromium headless vía CDP (stdlib pura).

Qué hace
--------
Levanta el panel REAL de producción (`engine.bridge.LocalServer` sobre `127.0.0.1`
en un puerto efímero, con el almacén de proyecto en `%TEMP%`), lanza un Chromium
headless con perfil temporal y puerto de depuración propio, y **conduce la
interfaz** —clics, formularios y eventos reales— verificando lo que el operador
vería en el DOM y cruzándolo con lo que sirve `/api/state`.

Pasos del guion
---------------
1. `app_load`      — la app carga y muestra su título.
2. `generate`      — se genera la organización desde la UI (offline) y aparece la rejilla de agentes.
3. `channel`       — se abre Canal, se publica con `@mención` y aparece la tarea dirigida.
4. `memory`        — se guarda un fragmento y se ve el índice `MEMORY.md`.
5. `followups`     — se pulsa el tick de Compromisos y se compara el estado mostrado.
6. `sandbox_block` — sin aprobación, el panel declara el bloqueo y NO ejecuta nada.

Cada paso deja un PNG en `docs/rea/evidence/chromium/` y el informe
`docs/rea/evidence/chromium/report.json` con pasos, resultados, versión de
Chromium y SHA-256 de cada captura.

Límites declarados
------------------
- Sin dependencias nuevas: sólo stdlib + el propio paquete (`qa_v7.chromium_cdp`,
  también stdlib). Nada de selenium, playwright ni websocket-client.
- Sin red externa: todo va a `127.0.0.1` (panel y endpoint CDP).
- No modifica `engine/` ni `web/`: si un selector no existe, el paso FALLA y se
  reporta como hallazgo; no se "arregla" aquí.
- No se ejecuta por `unittest discover`: el nombre del archivo no empieza por
  `test`, así que la suite no exige Chromium en cada corrida.
- Si no hay Chromium, declara `chromium_unavailable: true` con el motivo y sale 0
  sin fingir que probó.

Uso
---
    python qa_v7/chromium_e2e.py
    python qa_v7/chromium_e2e.py --evidence-dir <ruta> --keep-profile --json
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:  # ejecutado como script: python qa_v7/chromium_e2e.py
    from qa_v7 import chromium_cdp as cdp
except ImportError:  # importado como módulo del paquete
    import chromium_cdp as cdp

EVIDENCE_RELATIVE = os.path.join('docs', 'rea', 'evidence', 'chromium')
EVIDENCE_DEFAULT = os.path.join(ROOT, EVIDENCE_RELATIVE)
COMMITMENT_TEXT = 'luego subo el informe del puerto'
MEMORY_ID = 'decision-e2e-01'
SANDBOX_CODE = "print('hola desde el sandbox del panel')"
# El panel traduce el código de bloqueo a etiqueta legible (app.js `sandboxBlockedLabel`).
BLOCKED_LABELS = {
    'human_approval_required': 'requiere aprobacion humana',
    'approval_consumed': 'aprobacion consumida',
    'approval_expired': 'aprobacion caducada',
    'policy_denied': 'denegado por la politica',
    'ready': 'listo para ejecutar',
}


class StepFailure(AssertionError):
    """Un paso del guion no cumple lo que declara. Lleva el paso y el motivo."""

    def __init__(self, step, message):
        super().__init__(f'{step}: {message}')
        self.step = step
        self.reason = message


class _SandboxUiFinding(StepFailure):
    """Fallo de UI con evidencia parcial: la seguridad se cumplió, el panel no pintó."""

    def __init__(self, step, message, detail):
        super().__init__(step, message)
        self.detail = detail


class _NullStore:
    """Almacén de credenciales nulo: el arnés no lee ni escribe secretos."""

    def load(self):
        return {}

    def delete(self):
        return None

    def save(self, value):
        raise RuntimeError('Arnés E2E: no se persisten credenciales.')


# --------------------------------------------------------------------------- #
# Panel real en un hilo
# --------------------------------------------------------------------------- #

class Panel:
    """`LocalServer` de producción sobre 127.0.0.1 con estado aislado en %TEMP%."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix='orgdna-e2e-')
        from engine.bridge import BridgeState, LocalServer
        from engine.project_store import ProjectStore

        self.state = BridgeState(
            credential_store=_NullStore(),
            project_store=ProjectStore(os.path.join(self.root, 'projects')),
        )
        self.server = LocalServer(('127.0.0.1', 0), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self):
        return self.server.server_port

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.port}'

    def stop(self):
        report = {'stopped': False, 'workdir_removed': False}
        try:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=5)
            report['stopped'] = not self.thread.is_alive()
        except Exception as exc:  # el cierre no debe tapar el resultado del guion
            report['error'] = f'{type(exc).__name__}: {exc}'
        shutil.rmtree(self.root, ignore_errors=True)
        report['workdir_removed'] = not os.path.exists(self.root)
        return report


# --------------------------------------------------------------------------- #
# Cliente HTTP de contraste (Python, fuera del navegador)
# --------------------------------------------------------------------------- #

class PanelClient:
    """Lee `/api/state` desde Python para contrastar lo que muestra el DOM.

    Habla sólo con `127.0.0.1` mediante `http.client` (stdlib, sin proxies) y
    reutiliza la cookie de sesión y el token CSRF que el propio panel entrega.
    """

    def __init__(self, port, timeout=15.0):
        self.port = int(port)
        self.timeout = float(timeout)
        self.cookie = ''
        self.csrf = ''
        self.reads = 0

    def _connection(self):
        return http.client.HTTPConnection('127.0.0.1', self.port, timeout=self.timeout)

    def _request(self, method, path, body=None, extra_headers=None):
        connection = self._connection()
        headers = {'Accept': 'application/json, text/html'}
        if self.cookie:
            headers['Cookie'] = self.cookie
        if body is not None:
            headers['Content-Type'] = 'application/json'
            headers['Origin'] = f'http://127.0.0.1:{self.port}'
            if self.csrf:
                headers['X-CSRF-Token'] = self.csrf
        headers.update(extra_headers or {})
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8')
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        response_headers = dict(response.getheaders())
        connection.close()
        return status, response_headers, raw

    def open(self):
        """Abre sesión: obtiene cookie y token CSRF del propio panel."""
        status, headers, raw = self._request('GET', '/')
        if status != 200:
            raise cdp.CDPError(f'El panel devolvió HTTP {status} al abrir la raíz.')
        cookie_header = headers.get('Set-Cookie') or headers.get('set-cookie') or ''
        if 'orgdna_session=' in cookie_header:
            self.cookie = cookie_header.split(';')[0].strip()
        text = raw.decode('utf-8', 'replace')
        marker = 'name="csrf-token" content="'
        start = text.find(marker)
        if start >= 0:
            start += len(marker)
            end = text.find('"', start)
            self.csrf = text[start:end]
        if not self.cookie or not self.csrf:
            raise cdp.CDPError('El panel no entregó cookie de sesión o token CSRF.')
        return {'cookie': bool(self.cookie), 'csrf': bool(self.csrf)}

    def state(self):
        status, _, raw = self._request('GET', '/api/state')
        if status != 200:
            raise cdp.CDPError(f'/api/state devolvió HTTP {status}.')
        self.reads += 1
        try:
            return json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise cdp.CDPError('/api/state no devolvió JSON válido.') from None

    def post(self, action, payload):
        """POST directo: sólo para comprobaciones del propio arnés, no para el guion."""
        status, _, raw = self._request('POST', '/api/' + action, body=payload)
        return status, raw


# --------------------------------------------------------------------------- #
# Utilidades de DOM sobre CDP
# --------------------------------------------------------------------------- #

def _json_argument(value):
    return json.dumps(value, ensure_ascii=False)


def js(session, expression, timeout=None):
    """Evalúa un cuerpo JS (sentencias con `return`) en la página."""
    return session.evaluate('(() => {\n' + expression + '\n})()', return_by_value=True, timeout=timeout)


def exists(session, selector):
    return js(session, f'return Boolean(document.querySelector({_json_argument(selector)}));') is True


def text_of(session, selector):
    script = (f'const el = document.querySelector({_json_argument(selector)});'
              'return el ? String(el.textContent) : null;')
    return js(session, script)


def count_of(session, selector):
    script = (f'return document.querySelectorAll({_json_argument(selector)}).length;')
    return js(session, script)


def visible(session, selector):
    script = ('const el = document.querySelector(' + _json_argument(selector) + ');'
              'if (!el) return false; const rect = el.getBoundingClientRect();'
              'const style = getComputedStyle(el);'
              'return !el.hidden && style.display !== "none" && style.visibility !== "hidden"'
              ' && rect.width > 0 && rect.height > 0;')
    return js(session, script) is True


def click(session, selector):
    script = ('const el = document.querySelector(' + _json_argument(selector) + ');'
              'if (!el) return "missing"; el.click(); return "clicked";')
    result = js(session, script)
    if result != 'clicked':
        raise StepFailure('selector', f'no existe el elemento {selector}')
    return result


def set_value(session, selector, value):
    """Rellena un input/select/textarea y dispara `input` + `change` como el operador."""
    script = ('const el = document.querySelector(' + _json_argument(selector) + ');'
              'if (!el) return "missing";'
              f'el.value = {_json_argument(value)};'
              'el.dispatchEvent(new Event("input", {bubbles: true}));'
              'el.dispatchEvent(new Event("change", {bubbles: true}));'
              'return el.value;')
    result = js(session, script)
    if result == 'missing':
        raise StepFailure('selector', f'no existe el elemento {selector}')
    if str(result) != str(value):
        raise StepFailure('selector', f'{selector} no aceptó el valor {value!r} (quedó {result!r})')
    return result


def submit(session, selector):
    script = ('const el = document.querySelector(' + _json_argument(selector) + ');'
              'if (!el) return "missing";'
              'if (typeof el.requestSubmit === "function") el.requestSubmit();'
              'else el.dispatchEvent(new Event("submit", {bubbles: true, cancelable: true}));'
              'return "submitted";')
    result = js(session, script)
    if result != 'submitted':
        raise StepFailure('selector', f'no existe el formulario {selector}')
    return result


def scroll_to(session, selector):
    script = ('const el = document.querySelector(' + _json_argument(selector) + ');'
              'if (!el) return "missing"; el.scrollIntoView({block: "center"}); return "scrolled";')
    return js(session, script)


def wait_js(session, expression, timeout, description):
    """Espera a que la expresión JS sea verdadera; si no, falla nombrando el paso.

    Acepta tanto una expresión suelta (`document.readyState === "complete"`) como
    un cuerpo con sentencias y `return`.
    """
    body = expression if 'return' in expression else f'return ({expression});'
    try:
        return cdp.wait_for(session, '(() => {\n' + body + '\n})()', timeout=timeout)
    except cdp.CDPTimeout:
        raise StepFailure('espera', f'no se cumplió en {timeout}s: {description}') from None


def install_error_listener(session):
    """Registra los errores no capturados de la página para poder citarlos."""
    script = ('window.__e2e_errors = window.__e2e_errors || [];'
              'if (!window.__e2e_listening) { window.__e2e_listening = true;'
              '  window.addEventListener("error", event => window.__e2e_errors.push('
              '    String((event && (event.message || (event.error && event.error.message))) || "error")));'
              '  window.addEventListener("unhandledrejection", event => window.__e2e_errors.push('
              '    "unhandledrejection: " + String((event && event.reason) || "")));'
              '}'
              'return window.__e2e_errors.length;')
    return js(session, script)


def uncaught_errors(session):
    """Lista de errores JS no capturados observados desde que se instaló el oyente."""
    try:
        value = js(session, 'return (window.__e2e_errors || []).slice(-12);')
    except cdp.CDPError:
        return []
    return [str(item) for item in (value or [])]


def navigate_hash(session, page, timeout=15.0):
    js(session, f'location.hash = {_json_argument(page)}; return true;')
    script = ('const el = document.getElementById(' + _json_argument(page) + ');'
              'return Boolean(el) && !el.hidden;')
    wait_js(session, script, timeout, f'la sección #{page} no se hizo visible')
    return True


# --------------------------------------------------------------------------- #
# Contraste DOM ↔ backend
# --------------------------------------------------------------------------- #

class Recorder:
    """Acumula aserciones y contrastes de un paso, sin ocultar ninguno."""

    def __init__(self, step):
        self.step = step
        self.assertions = []

    def check(self, name, condition, detail=None):
        entry = {'assert': name, 'ok': bool(condition)}
        if detail is not None:
            entry['detail'] = detail
        self.assertions.append(entry)
        if not condition:
            raise StepFailure(self.step, f'aserción fallida: {name}' + (f' ({detail})' if detail else ''))
        return True

    def equal(self, name, dom, backend):
        entry = {'assert': name, 'dom': dom, 'backend': backend, 'ok': dom == backend}
        self.assertions.append(entry)
        if dom != backend:
            raise StepFailure(self.step, f'divergencia DOM↔backend en {name}: DOM={dom!r} backend={backend!r}')
        return True

    def contains(self, name, haystack, needle):
        haystack = '' if haystack is None else str(haystack)
        ok = str(needle) in haystack
        self.assertions.append({'assert': name, 'ok': ok, 'needle': str(needle)})
        if not ok:
            raise StepFailure(self.step, f'{name}: {needle!r} no aparece en {haystack[:240]!r}')
        return True


def parse_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


DIAGNOSTIC_SELECTORS = ('#notice', '#channel-panel-status', '#followups-status', '#followups-error',
                        '#memory-count', '#sandbox-error', '#sandbox-status', '#sandbox-count',
                        '#sandbox-verdict')


def diagnose(session, client):
    """Foto del panel + backend en el momento del fallo, para no adivinar la causa."""
    data = {'dom': {}}
    for selector in DIAGNOSTIC_SELECTORS:
        try:
            data['dom'][selector] = text_of(session, selector)
        except cdp.CDPError as error:
            data['dom'][selector] = f'<no evaluable: {error}>'
    try:
        backend = client.state()
        channel = backend.get('team_channel') or {}
        followups = backend.get('team_followups') or {}
        sandbox = backend.get('sandbox') or {}
        memory = backend.get('team_memory') or {}
        data['backend'] = {
            'channel_members': [row.get('member_id') for row in (channel.get('members') or [])][:8],
            'channel_messages': len(channel.get('messages') or []),
            'channel_tasks': [(row.get('id'), row.get('title'), row.get('owner_member_id'))
                              for row in (channel.get('tasks') or [])][:4],
            'memory_fragments': len(memory.get('fragments') or []),
            'followups': {'available': followups.get('available'),
                          'stats': followups.get('stats'),
                          'tasks': len(followups.get('tasks') or [])},
            'sandbox': {'available': sandbox.get('available'),
                        'counts': sandbox.get('counts'),
                        'requests': [(row.get('request_id'), row.get('blocked_reason'),
                                      (row.get('policy') or {}).get('decision'))
                                     for row in (sandbox.get('requests') or [])][:3],
                        'executions': len(sandbox.get('executions') or [])},
            'receipt_tail': [(row.get('action'), row.get('status'), str(row.get('message'))[:120])
                             for row in (backend.get('receipts') or [])[-4:]],
        }
    except (cdp.CDPError, KeyError, TypeError) as error:
        data['backend_error'] = f'{type(error).__name__}: {error}'
    return data


# --------------------------------------------------------------------------- #
# Guion E2E
# --------------------------------------------------------------------------- #

def install_render_instrumentation(session):
    """Cuenta `render()` completados para detectar abortos silenciosos del panel.

    No cambia la lógica del panel: envuelve la función global `render` y cuenta
    cuántas veces **termina** (si lanza, no cuenta). Así se mide el defecto real
    observado una vez: una excepción dentro de `renderSandbox()` abortaba el resto
    de `render()` y las secciones posteriores dejaban de refrescarse.
    """
    script = ('window.__e2e_render = {calls: 0, completed: 0, instrumented: false};'
              'try {'
              '  const original = render;'
              '  render = function patchedRender() {'
              '    window.__e2e_render.calls += 1;'
              '    const value = original.apply(this, arguments);'
              '    window.__e2e_render.completed += 1;'
              '    return value;'
              '  };'
              '  window.__e2e_render.instrumented = true;'
              '} catch (error) { window.__e2e_render.error = String(error); }'
              'return window.__e2e_render;')
    return js(session, script)


def render_stats(session):
    try:
        return js(session, 'return window.__e2e_render || {calls: 0, completed: 0, instrumented: false};') or {}
    except cdp.CDPError:
        return {}


def step_app_load(session, panel, client, recorder):
    """(a) La app carga y muestra el título."""
    cdp.navigate(session, panel.origin + '/', timeout=30)
    wait_js(session, 'document.readyState === "complete"', 20, 'readyState complete')
    wait_js(session, 'Boolean(document.querySelector("#home-title"))', 20, 'existe #home-title y el panel pintó')

    title = js(session, 'return document.title;')
    heading = text_of(session, '#home-title')
    recorder.contains('title', title, 'OrgDNA')
    recorder.check('home_heading', bool(heading and heading.strip()), {'heading': (heading or '').strip()[:80]})

    backend = client.state()
    recorder.equal('backend_sin_organizacion', backend.get('organization'), None)
    recorder.check('seccion_inicio_visible', visible(session, '#inicio'))
    install_error_listener(session)
    instrumentation = install_render_instrumentation(session) or {}
    return {'document_title': title, 'heading': (heading or '').strip()[:120],
            'panel_version': (backend.get('instance') or {}).get('version'),
            'render_instrumented': bool(instrumentation.get('instrumented'))}


def step_generate(session, panel, client, recorder, timeout):
    """(b) POST /api/generate desde la UI y la rejilla de agentes aparece."""
    if not exists(session, '#generate-offline'):
        raise StepFailure('generate', 'hallazgo: no existe el botón #generate-offline en el panel')
    click(session, '#generate-offline')
    wait_js(session, 'document.querySelectorAll("#profile-grid button.profile-card").length > 0',
            timeout, 'la rejilla de perfiles no se pobló tras generar')
    wait_js(session, 'typeof state !== "undefined" && Boolean(state.organization && state.organization.agents)',
            timeout, 'el estado del panel no refleja la organización generada')

    cards = count_of(session, '#profile-grid button.profile-card')
    stat_agents = text_of(session, '#stat-agents')
    profile_count = text_of(session, '#profile-count')
    backend = client.state()
    organization = backend.get('organization') or {}
    agents = organization.get('agents') or []

    recorder.check('hay_agentes', len(agents) > 0, {'agents': len(agents)})
    recorder.equal('dom_tarjetas_igual_backend', cards, len(agents))
    recorder.equal('stat_agents_igual_backend', parse_int(stat_agents), len(agents))
    recorder.contains('profile_count_formato', profile_count or '', f'{len(agents)} / {len(agents)} perfiles')
    recorder.check('generacion_offline_sin_proveedor',
                   (backend.get('generation') or {}).get('status') in (None, 'completed', 'offline'),
                   {'generation_status': (backend.get('generation') or {}).get('status')})
    navigate_hash(session, 'perfiles')
    recorder.check('rejilla_visible', visible(session, '#profile-grid'))
    return {'agents': len(agents), 'cards': cards, 'profile_count': (profile_count or '').strip(),
            'agent_names': [row.get('display_name') for row in agents[:4]]}


def step_channel(session, panel, client, recorder, timeout, mention_ref, sender_ref):
    """(c) Abrir Canal, publicar con @mención y ver la tarea creada."""
    navigate_hash(session, 'council')
    for selector in ('#channel-publish-form', '#channel-sender', '#channel-to', '#channel-text',
                     '#channel-task-list'):
        if not exists(session, selector):
            raise StepFailure('channel', f'hallazgo: falta el selector {selector}')
    message = f'@{mention_ref} {COMMITMENT_TEXT}'
    set_value(session, '#channel-sender', sender_ref)
    set_value(session, '#channel-to', 'all')
    set_value(session, '#channel-text', message)
    submit(session, '#channel-publish-form')
    wait_js(session, 'document.querySelectorAll("#channel-task-list article").length > 0',
            timeout, 'la tarea dirigida no apareció en el DOM del canal')

    backend = client.state()
    channel = backend.get('team_channel') or {}
    tasks = channel.get('tasks') or []
    messages = channel.get('messages') or []
    count_text = text_of(session, '#channel-count')
    task_text = js(session, 'return [...document.querySelectorAll("#channel-task-list article")]'
                            '.map(el => String(el.textContent)).join("\\n");')
    message_text = js(session, 'return [...document.querySelectorAll("#channel-message-list article")]'
                               '.map(el => String(el.textContent)).join("\\n");')

    recorder.check('tarea_creada', len(tasks) >= 1, {'tasks': len(tasks)})
    recorder.equal('dom_tareas_igual_backend', count_of(session, '#channel-task-list article'), len(tasks))
    recorder.equal('dom_mensajes_igual_backend', count_of(session, '#channel-message-list article'), len(messages))
    recorder.contains('contador_canal', count_text or '', f'{len(messages)} mensajes')
    recorder.contains('contador_canal_tareas', count_text or '', f'{len(tasks)} tareas')
    task = tasks[0]
    recorder.contains('tarea_en_dom', task_text, task.get('id'))
    recorder.contains('titulo_tarea_en_dom', task_text, task.get('title'))
    recorder.contains('mencion_pintada', message_text, '@' + str(mention_ref))
    recorder.equal('tarea_dirigida_al_miembro', task.get('owner_member_id'), sender_ref)
    scroll_to(session, '#channel-task-list')
    return {'task_id': task.get('id'), 'task_title': task.get('title'),
            'owner_member_id': task.get('owner_member_id'), 'messages': len(messages),
            'channel_count': (count_text or '').strip()}


def step_memory(session, panel, client, recorder, timeout, author_ref):
    """(d) Alta de fragmento y visualización del índice MEMORY.md."""
    for selector in ('#memory-append-form', '#memory-plane', '#memory-id', '#memory-content',
                     '#memory-index-text', '#memory-count'):
        if not exists(session, selector):
            raise StepFailure('memory', f'hallazgo: falta el selector {selector}')
    set_value(session, '#memory-author', author_ref)
    set_value(session, '#memory-plane', 'project')
    set_value(session, '#memory-id', MEMORY_ID)
    set_value(session, '#memory-content',
              'Decisión E2E: el arnés conduce el panel en Chromium y cruza DOM con /api/state.')
    set_value(session, '#memory-description', 'Decisión registrada por el arnés E2E')
    submit(session, '#memory-append-form')
    wait_js(session, f'String(document.querySelector("#memory-index-text").textContent).includes({_json_argument(MEMORY_ID)})',
            timeout, 'el índice MEMORY.md no muestra el fragmento recién guardado')

    backend = client.state()
    memory = backend.get('team_memory') or {}
    fragments = memory.get('fragments') or []
    index_text = text_of(session, '#memory-index-text') or ''
    count_text = text_of(session, '#memory-count') or ''
    recorder.check('fragmento_persistido', len(fragments) >= 1, {'fragments': len(fragments)})
    recorder.equal('dom_fragmentos_igual_backend', count_of(session, '#memory-fragment-list article'),
                   len(fragments))
    recorder.contains('contador_memoria', count_text, f'{len(fragments)} fragmentos')
    recorder.contains('indice_mrmory_titulo', text_of(session, '#team-memory-panel summary') or '', 'MEMORY.md')
    recorder.contains('fragmento_en_indice', index_text, f'{MEMORY_ID}.md')
    recorder.contains('descripcion_en_indice', index_text, 'Decisión registrada por el arnés E2E')
    recorder.check('plano_project', any(row.get('plane') == 'project' for row in fragments),
                   {'planes': [row.get('plane') for row in fragments]})
    scroll_to(session, '#memory-index-text')
    return {'fragments': len(fragments), 'memory_id': MEMORY_ID,
            'index_excerpt': index_text.strip()[:200]}


def step_followups(session, panel, client, recorder, timeout, sender_ref=None):
    """(e) Pulsar tick de Compromisos y comprobar el estado mostrado."""
    for selector in ('#followups-tick', '#followups-status', '#followups-stat-active'):
        if not exists(session, selector):
            raise StepFailure('followups', f'hallazgo: falta el selector {selector}')
    recorder.check('tick_habilitado', js(session, 'return !document.querySelector("#followups-tick").disabled;') is True)
    click(session, '#followups-tick')
    wait_js(session, 'String(document.querySelector("#followups-status").textContent).startsWith("Tick ejecutado")',
            timeout, 'el panel no confirmó el tick de Compromisos')

    backend = client.state()
    followups = backend.get('team_followups') or {}
    stats = followups.get('stats') or {}
    dom_stats = {key: parse_int(text_of(session, f'#followups-stat-{key}'))
                 for key in ('active', 'chasing', 'escalated', 'reported')}
    status_text = text_of(session, '#followups-status') or ''
    tasks = followups.get('tasks') or []
    recorder.check('disponible', followups.get('available') is True, {'available': followups.get('available')})
    for key, value in dom_stats.items():
        recorder.equal(f'stat_{key}', value, int(stats.get(key) or 0))
    recorder.check('compromiso_detectado', int(stats.get('active') or 0) >= 1,
                   {'active': stats.get('active'), 'tasks': len(tasks),
                    'events': followups.get('events')})
    if sender_ref and tasks:
        recorder.equal('compromiso_del_emisor', tasks[0].get('owner_member_id'), sender_ref)
    recorder.contains('estado_tick_en_dom', status_text, 'Tick ejecutado')
    recorder.contains('eventos_en_dom', text_of(session, '#followups-events') or '', 'commitment')
    recorder.check('autoridad_declarada',
                   'identity_verified=false' in (text_of(session, '#followups-authority') or ''),
                   {'authority': (text_of(session, '#followups-authority') or '')[:160]})
    recorder.equal('lista_dom_igual_backend', count_of(session, '#followups-task-list article'), len(tasks))
    scroll_to(session, '#followups-panel')
    return {'stats': dom_stats, 'status': status_text.strip()[:160],
            'tasks': len(tasks), 'events': len(followups.get('events') or []),
            'snippet': (tasks[0].get('snippet') if tasks else '')}


def step_sandbox_block(session, panel, client, recorder, timeout, agent_ref):
    """(f) Sin aprobación, el panel declara el bloqueo y NO ejecuta."""
    for selector in ('#sandbox-request', '#sandbox-code', '#sandbox-verdict', '#sandbox-count',
                     '#sandbox-run-list', '#sandbox-status'):
        if not exists(session, selector):
            raise StepFailure('sandbox_block', f'hallazgo: falta el selector {selector}')
    recorder.equal('sin_ejecuciones_antes', count_of(session, '#sandbox-run-list article'), 0)
    set_value(session, '#sandbox-agent', agent_ref)
    set_value(session, '#sandbox-code', SANDBOX_CODE)
    set_value(session, '#sandbox-timeout', '30')
    recorder.check('boton_solicitar_habilitado',
                   js(session, 'return !document.querySelector("#sandbox-request").disabled;') is True)
    before_render = render_stats(session)
    click(session, '#sandbox-request')

    # El veredicto puede no llegar porque `render()` falle al pintar la solicitud:
    # se espera el veredicto O un error JS, para nombrar la causa en vez de agotar
    # un plazo genérico. La propiedad de seguridad se comprueba igual abajo.
    ui_error = ''
    deadline = time.monotonic() + min(timeout, 20.0)
    while time.monotonic() < deadline:
        shown = js(session, 'const v=document.querySelector("#sandbox-verdict");'
                            'return Boolean(v) && !v.hidden;') is True
        if shown:
            break
        errors = uncaught_errors(session)
        if errors:
            ui_error = ' | '.join(errors[-2:])
            break
        time.sleep(0.2)

    backend = client.state()
    sandbox = backend.get('sandbox') or {}
    requests = sandbox.get('requests') or []
    executions = sandbox.get('executions') or []
    verdict = text_of(session, '#sandbox-verdict') or ''
    count_text = text_of(session, '#sandbox-count') or ''
    status_text = text_of(session, '#sandbox-status') or ''
    policy_summary = text_of(session, '#sandbox-policy-summary') or ''
    request = requests[0] if requests else {}

    recorder.check('solicitud_registrada', len(requests) == 1, {'requests': len(requests)})
    recorder.contains('veredicto_sin_ejecutar', verdict, 'preparada SIN ejecutar')
    recorder.equal('dom_solicitudes_igual_backend', parse_int((count_text.split('|')[0] or '').strip().split(' ')[0]),
                   int((sandbox.get('counts') or {}).get('requests') or 0))
    recorder.equal('dom_ejecuciones_igual_backend', count_of(session, '#sandbox-run-list article'), len(executions))
    recorder.equal('backend_sin_ejecuciones', len(executions), 0)
    recorder.check('sin_aprobacion', request.get('approved') is False and request.get('consumed_at') is None,
                   {'approved': request.get('approved'), 'consumed_at': request.get('consumed_at')})
    recorder.check('bloqueo_declarado_por_politica',
                   bool(request.get('blocked_reason')) or bool((request.get('policy') or {}).get('gate')),
                   {'blocked_reason': request.get('blocked_reason'),
                    'gate': (request.get('policy') or {}).get('gate'),
                    'decision': (request.get('policy') or {}).get('decision')})
    recorder.contains('veredicto_menciona_estado', verdict,
                      BLOCKED_LABELS.get(str(request.get('blocked_reason') or ''),
                                         str(request.get('blocked_reason') or '')))
    card_text = js(session, 'return [...document.querySelectorAll("#sandbox-request-list article")]'
                            '.map(el => String(el.textContent)).join("\\n");') or ''
    recorder.contains('tarjeta_muestra_estado', card_text,
                      BLOCKED_LABELS.get(str(request.get('blocked_reason') or ''),
                                         str(request.get('blocked_reason') or '')))
    # Doble comprobación exigida: el CÓDIGO queda registrado en el atributo de la
    # tarjeta (data-blocked) y el humano lee la ETIQUETA en la prosa.
    blocked_attribute = js(session, 'const el = document.querySelector("#sandbox-request-list [data-blocked]");'
                                    'return el ? String(el.dataset.blocked) : null;')
    recorder.equal('atributo_blocked_codigo', blocked_attribute,
                   str(request.get('blocked_reason') or ''))
    recorder.contains('politica_deny_by_default', policy_summary, 'deny by default=true')
    recorder.check('panel_no_afirma_ejecucion', 'ejecutad' not in verdict.lower(),
                   {'verdict': verdict[:200]})
    recorder.contains('estado_sandbox_inerte', status_text, 'Sandbox inerte')

    # Caso propio exigido por el capitán: el defecto que sólo se veía en un
    # navegador real (`sandboxBlocked()` inexistente) queda cubierto de forma
    # permanente. Además de no haber error, se comprueba que `render()` TERMINA
    # tras la solicitud: eso prueba que las secciones posteriores a renderSandbox
    # (renderCordis, renderDshConnection, renderHarness, …) vuelven a refrescarse.
    error_box = text_of(session, '#sandbox-error') or ''
    notice_text = text_of(session, '#notice') or ''
    after_render = render_stats(session)
    recorder.check('sandbox_render_defined',
                   'is not defined' not in error_box and 'is not defined' not in notice_text
                   and not uncaught_errors(session),
                   {'sandbox_error': error_box[:200], 'notice': notice_text[:200],
                    'uncaught': uncaught_errors(session)[:3]})
    recorder.equal('tarjeta_solicitud_renderizada',
                   count_of(session, '#sandbox-request-list article'), len(requests))
    if after_render.get('instrumented'):
        recorder.check('render_completa_tras_solicitud',
                       int(after_render.get('completed') or 0) > int(before_render.get('completed') or 0),
                       {'before': before_render.get('completed'), 'after': after_render.get('completed'),
                        'calls': after_render.get('calls')})
    scroll_to(session, '#sandbox-panel')
    detail = {'requests': len(requests), 'executions': len(executions),
              'blocked_reason': request.get('blocked_reason'),
              'policy': request.get('policy'), 'verdict': verdict.strip()[:220],
              'ui_error': ui_error, 'render_before': before_render.get('completed'),
              'render_after': after_render.get('completed'),
              'render_instrumented': after_render.get('instrumented')}
    if ui_error and not verdict.strip():
        # Hallazgo de UI, no de seguridad: el backend bloqueó y no ejecutó, pero el
        # panel no puede pintar la solicitud. Se nombra la excepción tal cual.
        raise _SandboxUiFinding('sandbox_block',
                                f'hallazgo de UI en web/app.js: el panel no renderiza la solicitud de '
                                f'sandbox ({ui_error}). Bloqueo y 0 ejecuciones verificados en el backend.',
                                detail)
    recorder.check('veredicto_presente', bool(verdict.strip()), {'verdict': verdict[:200]})
    return detail


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #

def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def _first_ref(members, key, exclude=()):
    """Primer miembro utilizable como referencia (sin espacios ni '@')."""
    for member in members:
        if str(member.get('member_id') or '') in exclude:
            continue
        candidate = str(member.get(key) or '')
        if candidate and not any(char.isspace() for char in candidate) and '@' not in candidate:
            return candidate
    return ''


def _member_name(members, member_id):
    for member in members:
        if str(member.get('member_id') or '') == str(member_id or ''):
            return str(member.get('name') or '')
    return ''


def run(evidence_dir=None, keep_profile=False, timeout=40.0, shoot=True):
    """Ejecuta el guion completo y devuelve (informe, código de salida)."""
    started = time.time()
    evidence = os.path.abspath(evidence_dir or EVIDENCE_DEFAULT)
    report = {
        'tool': 'qa_v7/chromium_e2e.py',
        'protocol': 'CDP sobre WebSocket RFC 6455 (stdlib)',
        'chromium_available': False,
        'chromium_unavailable': False,
        'evidence_dir': evidence,
        'steps': [],
        'browser': None,
        'panel': None,
        'findings': [],
        'cleanup': None,
        'error': None,
    }
    found = cdp.find_browser()
    report['browser'] = found
    if not found:
        report['chromium_unavailable'] = True
        report['reason'] = ('chromium_unavailable: no se localizó Chrome, Chromium ni Edge en rutas '
                            'estándar ni en ORGDNA_CHROMIUM; no se ejecutó ningún paso')
        report['duration_s'] = round(time.time() - started, 3)
        report['ok'] = None
        return report, 0
    report['chromium_available'] = True
    if shoot:
        os.makedirs(evidence, exist_ok=True)
    panel = None
    handle = None
    session = None
    try:
        panel = Panel()
        client = PanelClient(panel.port, timeout=timeout)
        session_info = client.open()
        report['panel'] = {'port': panel.port, 'origin': panel.origin,
                           'mode': 'in-process LocalServer', 'session': session_info}
        handle = cdp.launch(headless=True, timeout=timeout)
        report['browser_info'] = {'version': handle.version_info.get('Browser'),
                                  'protocol_version': handle.version_info.get('Protocol-Version'),
                                  'pid': handle.pid, 'launch_port': handle.port,
                                  'profile': handle.profile, 'path': handle.binary}
        session = cdp.CDPSession.connect(handle.port, target_filter='page', timeout=timeout)
        session.enable('Page')
        session.enable('Runtime')

        # Refs tomadas del backend real (miembros del canal), no inventadas: la
        # @mención usa el token `name`; los selects y el sandbox usan `member_id`.
        bootstrap = client.state()
        members = ((bootstrap.get('team_channel') or {}).get('members') or [])
        mention_ref = _first_ref(members, 'name')
        sender_ref = _first_ref(members, 'member_id')
        if not mention_ref or not sender_ref:
            report['findings'].append({
                'id': 'E2E-F1',
                'severity': 'medium',
                'problem': 'El roster del canal no está disponible antes de generar: las referencias se '
                           'resuelven tras el paso de generación.',
                'requiredFix': 'Ninguno en este arnés: se re-resuelven en el paso de canal.'})

        def run_step(name, function, *args):
            step_started = time.time()
            recorder = Recorder(name)
            record = {'step': name, 'ok': False, 'assertions': []}
            try:
                detail = function(session, panel, client, recorder, *args)
                record['ok'] = True
                record['detail'] = detail
            except StepFailure as failure:
                record['failure'] = {'reason': failure.reason, 'step': failure.step,
                                     'diagnostics': diagnose(session, client)}
                if getattr(failure, 'detail', None):
                    record['failure']['detail'] = failure.detail
            except cdp.CDPError as error:
                record['failure'] = {'reason': f'{type(error).__name__}: {error}', 'step': name,
                                     'diagnostics': diagnose(session, client)}
            finally:
                record['assertions'] = recorder.assertions
                record['uncaught_errors'] = uncaught_errors(session)
                record['duration_s'] = round(time.time() - step_started, 3)
                if shoot and session is not None:
                    shot_path = os.path.join(evidence, f'step_{len(report["steps"]):02d}_{name}.png')
                    try:
                        capture = cdp.screenshot(session, shot_path)
                        record['screenshot'] = {
                            'path': capture['path'],
                            'relative': os.path.relpath(capture['path'], ROOT).replace(os.sep, '/'),
                            'bytes': capture['bytes'], 'sha256': capture['sha256']}
                    except cdp.CDPError as error:
                        record['screenshot_error'] = f'{type(error).__name__}: {error}'
                report['steps'].append(record)
            return record['ok']

        ok_app = run_step('app_load', step_app_load)
        if not ok_app:
            raise StepFailure('app_load', 'sin app cargada no tiene sentido seguir')

        ok_generate = run_step('generate', step_generate, timeout)
        if ok_generate:
            after = client.state()
            members = ((after.get('team_channel') or {}).get('members') or [])
            # El motor de seguimiento ignora los mensajes de su propia identidad de
            # coordinación (el miembro raíz): el emisor del compromiso debe ser otro.
            coordinator = str((after.get('team_followups') or {}).get('agent_member_id') or '')
            sender_ref = _first_ref(members, 'member_id', exclude=(coordinator,)) or sender_ref
            mention_ref = _member_name(members, sender_ref) or _first_ref(members, 'name') or mention_ref
            report['references'] = {'coordinator_member_id': coordinator, 'sender_member_id': sender_ref,
                                    'mention_token': mention_ref}
        if not ok_generate:
            raise StepFailure('generate', 'sin organización no se pueden recorrer canal, memoria ni sandbox')
        if not mention_ref or not sender_ref:
            raise StepFailure('channel', 'hallazgo: el canal no expone miembros utilizables (@mención por name, resto por member_id)')
        coordinator = str((report.get('references') or {}).get('coordinator_member_id') or '')
        if coordinator and sender_ref == coordinator:
            raise StepFailure('channel', 'el emisor del compromiso coincide con la identidad de coordinación '
                                         'del motor de seguimiento; el tick lo descartaría por diseño')

        run_step('channel', step_channel, timeout, mention_ref, sender_ref)
        run_step('memory', step_memory, timeout, sender_ref)
        run_step('followups', step_followups, timeout, sender_ref)
        run_step('sandbox_block', step_sandbox_block, timeout, sender_ref)
    except StepFailure as failure:
        report['error'] = str(failure)
    except cdp.CDPError as error:
        report['error'] = f'{type(error).__name__}: {error}'
    except Exception as error:  # ningún fallo debe impedir el informe ni la limpieza
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        if session is not None:
            session.close()
        report['cleanup'] = cdp.terminate(handle, keep_profile=keep_profile)
        if panel is not None:
            report['panel_cleanup'] = panel.stop()

    cleanup = report.get('cleanup') or {}
    orphans = cleanup.get('orphans') or {}
    report['orphans'] = {'checked': bool(orphans.get('checked')), 'pids': orphans.get('pids') or [],
                         'tree_cleared': cleanup.get('tree_cleared'),
                         'profile_removed': cleanup.get('profile_removed')}
    failures = [step for step in report['steps'] if not step.get('ok')]
    report['failed_steps'] = [step['step'] for step in failures]
    report['passed_steps'] = [step['step'] for step in report['steps'] if step.get('ok')]
    report['screenshot_digests'] = {step['step']: step['screenshot']['sha256']
                                    for step in report['steps'] if step.get('screenshot')}
    report['all_steps_present'] = [step['step'] for step in report['steps']] == [
        'app_load', 'generate', 'channel', 'memory', 'followups', 'sandbox_block']
    report['ok'] = bool(report['all_steps_present'] and not failures and not report['error']
                        and report['orphans']['checked'] and not report['orphans']['pids'])
    report['duration_s'] = round(time.time() - started, 3)
    if shoot:
        try:
            with open(os.path.join(evidence, 'report.json'), 'w', encoding='utf-8') as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
            report['report_path'] = os.path.join(evidence, 'report.json')
        except OSError as error:
            report['report_error'] = f'{type(error).__name__}: {error}'
            report['ok'] = False
    return report, (0 if report['ok'] else 1)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description='Arnés E2E: conduce el panel de OrgDNA en Chromium headless vía CDP (stdlib).')
    parser.add_argument('--evidence-dir', default=None,
                        help='Directorio de evidencia (por omisión docs/rea/evidence/chromium).')
    parser.add_argument('--keep-profile', action='store_true',
                        help='No borrar el perfil temporal de Chromium (diagnóstico).')
    parser.add_argument('--timeout', type=float, default=40.0, help='Plazo por paso, en segundos.')
    parser.add_argument('--no-shoot', action='store_true', help='No escribir capturas ni informe.')
    parser.add_argument('--json', action='store_true', help='Emitir sólo el informe JSON.')
    args = parser.parse_args(argv)
    report, code = run(evidence_dir=args.evidence_dir, keep_profile=args.keep_profile,
                       timeout=args.timeout, shoot=not args.no_shoot)
    if report['chromium_unavailable']:
        print(json.dumps({'chromium_unavailable': True, 'reason': report['reason']},
                         ensure_ascii=False, indent=2))
        return 0
    if not args.json:
        browser = report.get('browser_info') or {}
        print(f"panel    : {report.get('panel', {}).get('origin')}")
        print(f"chromium : {browser.get('path')} · {browser.get('version')}")
        for step in report['steps']:
            extra = step.get('failure') or step.get('detail') or {}
            print(f"  [{'ok' if step['ok'] else 'FALLO'}] {step['step']} "
                  f"({len(step['assertions'])} aserciones, {step['duration_s']}s) "
                  f"{json.dumps(extra, ensure_ascii=False)[:200]}")
        if report.get('error'):
            print(f"error    : {report['error']}")
        print(f"evidencia: {report.get('evidence_dir')}")
        print(f"duración : {report['duration_s']}s")
    print(json.dumps({key: report.get(key) for key in
                      ('ok', 'chromium_available', 'chromium_unavailable', 'passed_steps',
                       'failed_steps', 'screenshot_digests', 'orphans', 'report_path', 'duration_s')},
                     ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
