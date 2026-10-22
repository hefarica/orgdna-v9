"""Smoke real de Chromium contra el panel local, sin Playwright ni dependencias.

Qué demuestra
-------------
Que un Chromium real carga el panel de OrgDNA servido por un `LocalServer`
in-process (o por el panel ya arrancado, con `--port`) y que, **medido dentro del
navegador**, el HTML tiene su título, `window.location` es el panel y un
`fetch('/api/state')` desde la propia página devuelve HTTP 200 con cuerpo JSON.
Además guarda una captura PNG y verifica que el cierre no deja procesos ni
perfil temporal.

Qué NO hace
-----------
- No instala nada, no descarga navegadores y no sale a internet: sólo `127.0.0.1`.
- No toca `engine/`, `web/` ni el sello: el servidor in-process usa un almacén de
  proyecto en `%TEMP%`, de modo que el árbol entregado no recibe escrituras.
- No finge: si no hay Chromium, sale 0 declarando `chromium_unavailable: true`
  con el motivo, y no marca ninguna comprobación como superada.

Uso
---
    python qa_v7/chromium_smoke.py                # levanta su propio panel
    python qa_v7/chromium_smoke.py --port 8765    # usa un panel ya arrancado
    python qa_v7/chromium_smoke.py --json         # sólo el informe JSON

Salida: exit 0 sólo si todas las comprobaciones pasan (o si no hay navegador,
que se declara). Cualquier fallo devuelve 1 con el detalle en el informe.
"""

from __future__ import annotations

import argparse
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

try:  # se ejecuta como script suelto (python qa_v7/chromium_smoke.py)
    from qa_v7 import chromium_cdp as cdp
except ImportError:  # o como módulo del paquete
    import chromium_cdp as cdp

EXPECTED_TITLE = 'OrgDNA'


class _NullStore:
    """Almacén de credenciales nulo: el smoke no lee ni escribe secretos."""

    def load(self):
        return {}

    def delete(self):
        return None

    def save(self, value):
        raise RuntimeError('Fixture: el smoke no persiste credenciales.')


class InProcessPanel:
    """`LocalServer` real del panel, con almacén de proyecto en `%TEMP%`.

    Se reutiliza el servidor de producción (engine.bridge) para que el smoke
    pruebe el panel de verdad, no una maqueta. El estado se aísla en un
    directorio temporal para no escribir dentro del paquete entregado.
    """

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix='orgdna-smoke-')
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
    def base_url(self):
        return f'http://127.0.0.1:{self.port}'

    def stop(self):
        try:
            self.server.shutdown()
        except Exception:
            pass
        try:
            self.server.server_close()
        except Exception:
            pass
        try:
            self.thread.join(timeout=5)
        except Exception:
            pass
        shutil.rmtree(self.root, ignore_errors=True)
        return {'stopped': not self.thread.is_alive(), 'workdir_removed': not os.path.exists(self.root)}


def _check(report, name, ok, **detail):
    report['checks'].append(dict({'check': name, 'ok': bool(ok)}, **detail))
    return bool(ok)


def _probe_live_panel(port, timeout=5.0):
    """Comprueba que el panel indicado responde y devuelve su origen declarado."""
    status, body = cdp._http_get(port, '/api/instance', timeout=timeout)
    if status != 200:
        raise cdp.CDPError(f'/api/instance devolvió HTTP {status} en el puerto {port}')
    try:
        payload = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        raise cdp.CDPError('/api/instance no devolvió JSON válido') from None
    return {'port': port, 'origin': f'http://127.0.0.1:{port}', 'identity_keys': sorted(payload)[:8]}


def run(port=None, screenshot_dir=None, keep_profile=False, timeout=30.0):
    """Ejecuta el smoke completo y devuelve el informe (sin imprimir)."""
    started_at = time.time()
    report = {
        'tool': 'qa_v7/chromium_smoke',
        'chromium_available': False,
        'chromium_unavailable': False,
        'mode': 'live-panel' if port else 'in-process-panel',
        'checks': [],
        'browser': None,
        'panel': None,
        'screenshot': None,
        'cleanup': None,
        'error': None,
    }
    found = cdp.find_browser()
    report['browser'] = found
    if not found:
        report['chromium_unavailable'] = True
        report['reason'] = ('chromium_unavailable: no se localizó Chrome, Chromium ni Edge en rutas '
                            'estándar ni en ORGDNA_CHROMIUM; no se ejecutó ninguna comprobación')
        report['duration_s'] = round(time.time() - started_at, 3)
        report['ok'] = None  # ni éxito ni fallo: no probado
        return report
    report['chromium_available'] = True
    panel = None
    handle = None
    session = None
    try:
        if port:
            report['panel'] = _probe_live_panel(port)
        else:
            panel = InProcessPanel()
            report['panel'] = {'port': panel.port, 'origin': panel.base_url, 'mode': 'in-process'}
        base = report['panel']['origin']
        handle = cdp.launch(headless=True, timeout=timeout)
        report['launch'] = handle.as_dict()
        session = cdp.CDPSession.connect(handle.port, target_filter='page', timeout=timeout)
        session.enable('Page')
        session.enable('Runtime')
        cdp.navigate(session, base + '/', timeout=timeout)

        title = cdp.evaluate(session, 'document.title')
        _check(report, 'title_present', isinstance(title, str) and EXPECTED_TITLE in title, title=title)

        location = cdp.evaluate(session, 'JSON.stringify({origin: location.origin, path: location.pathname})')
        try:
            place = json.loads(location) if isinstance(location, str) else {}
        except ValueError:
            place = {}
        _check(report, 'location_is_panel', place.get('origin') == base and place.get('path') == '/',
               location=place, expected_origin=base)

        state_status = cdp.evaluate(
            session, "fetch('/api/state', {headers: {'Accept': 'application/json'}}).then(r => r.status)",
            return_by_value=True)
        _check(report, 'fetch_api_state_200', state_status == 200, status=state_status)

        state_keys = cdp.evaluate(
            session, "fetch('/api/state').then(r => r.json()).then(v => Object.keys(v).length)",
            return_by_value=True)
        _check(report, 'api_state_json_body', isinstance(state_keys, int) and state_keys > 0, keys=state_keys)

        body_ok = cdp.evaluate(session, 'document.body !== null && document.body.tagName === "BODY"')
        _check(report, 'dom_body_present', body_ok is True)

        heading = cdp.evaluate(
            session, "(document.querySelector('#home-title') || {}).textContent || ''")
        _check(report, 'dom_value_read', isinstance(heading, str) and heading.strip() != '',
               text=(heading or '').strip()[:80])

        root = cdp.dom_document(session, depth=1)
        _check(report, 'dom_get_document', root.get('nodeName') == '#document',
               node_name=root.get('nodeName'), child_count=root.get('childNodeCount'))

        destination = screenshot_dir or os.path.join(tempfile.gettempdir(), 'orgdna_chromium_smoke')
        target = os.path.join(destination, 'panel_' + time.strftime('%Y%m%d_%H%M%S') + '.png')
        capture = cdp.screenshot(session, target)
        report['screenshot'] = capture
        _check(report, 'screenshot_saved', capture['bytes'] > 1024, path=capture['path'],
               bytes=capture['bytes'], sha256=capture['sha256'])
    except cdp.CDPError as exc:
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if session is not None:
            session.close()
        report['cleanup'] = cdp.terminate(handle, keep_profile=keep_profile)
        if panel is not None:
            report['panel_cleanup'] = panel.stop()
    cleanup = report.get('cleanup') or {}
    orphans = (cleanup.get('orphans') or {})
    _check(report, 'cleanup_orphans_checked', bool(orphans.get('checked')),
           checked=orphans.get('checked'), reason=orphans.get('reason'))
    _check(report, 'no_orphan_browser_processes', orphans.get('checked') and not orphans.get('pids'),
           pids=orphans.get('pids'))
    _check(report, 'profile_removed', cleanup.get('profile_removed') is True,
           profile_removed=cleanup.get('profile_removed'))
    report['duration_s'] = round(time.time() - started_at, 3)
    report['ok'] = bool(report['checks']) and all(item['ok'] for item in report['checks']) \
        and report['error'] is None
    return report


def _printable(report):
    """Informe con la cola de stderr acotada, para consolas cp1252."""
    copy = dict(report)
    if isinstance(copy.get('cleanup'), dict):
        cleanup = dict(copy['cleanup'])
        kept = []
        for action in cleanup.get('killed_tree') or []:
            entry = dict(action)
            detail = str(entry.get('detail') or '')
            if len(detail) > 300:
                entry['detail'] = detail[:300] + '…'
            kept.append(entry)
        cleanup['killed_tree'] = kept
        copy['cleanup'] = cleanup
    return copy


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description='Smoke real de Chromium (CDP en stdlib) contra el panel local de OrgDNA.')
    parser.add_argument('--port', type=int, default=None,
                        help='Puerto de un panel ya arrancado; si se omite, el smoke levanta uno in-process.')
    parser.add_argument('--screenshot-dir', default=None,
                        help='Directorio de la captura (por omisión %%TEMP%%/orgdna_chromium_smoke).')
    parser.add_argument('--keep-profile', action='store_true',
                        help='No borrar el perfil temporal (diagnóstico; deja huérfanos a propósito).')
    parser.add_argument('--timeout', type=float, default=30.0, help='Plazo por operación, en segundos.')
    parser.add_argument('--json', action='store_true', help='Emitir sólo el informe JSON.')
    args = parser.parse_args(argv)
    report = run(port=args.port, screenshot_dir=args.screenshot_dir,
                 keep_profile=args.keep_profile, timeout=args.timeout)
    printable = _printable(report)
    if report['chromium_unavailable']:
        print(json.dumps({'chromium_unavailable': True, 'reason': report['reason']},
                         ensure_ascii=False, indent=2))
        return 0
    if not args.json:
        print(f"panel      : {report['panel']}")
        print(f"navegador  : {(report.get('browser') or {}).get('path')}")
        for item in report['checks']:
            extra = {k: v for k, v in item.items() if k not in ('check', 'ok')}
            print(f"  [{'ok' if item['ok'] else 'FALLO'}] {item['check']} {json.dumps(extra, ensure_ascii=False)[:160]}")
        if report.get('error'):
            print(f"error      : {report['error']}")
        print(f"duración   : {report['duration_s']}s")
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
