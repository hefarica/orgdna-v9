"""Safe loopback-only launcher; never terminates processes or modifies DSH ports."""
from __future__ import annotations

import argparse
import errno
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
APP_ID = 'orgDNA.local.panel'
APP_VERSION = '3.1'
LAUNCH_PROTOCOL = 1
DEFAULT_PORT = 8765


def _build_fingerprint():
    digest = hashlib.sha256()
    for folder, pattern in (('engine', '*.py'), ('web', '*')):
        for path in sorted((ROOT / folder).glob(pattern)):
            if path.is_file():
                digest.update(path.relative_to(ROOT).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


# Snapshot at process start: an older running process must not claim new code.
BUILD_ID = _build_fingerprint()
INSTALLATION_ID = hashlib.sha256(os.path.normcase(str(ROOT)).encode()).hexdigest()


def workbook_id(workbook):
    value = os.path.normcase(str(Path(workbook).expanduser().resolve())) if workbook else ''
    return hashlib.sha256(value.encode()).hexdigest()


def instance_identity(origin, workbook=None):
    """Public, non-secret identity. Contains no paths, keys, session or CSRF tokens."""
    return {'application': APP_ID, 'version': APP_VERSION, 'protocol': LAUNCH_PROTOCOL,
            'build': BUILD_ID, 'installation': INSTALLATION_ID,
            'workbook': workbook_id(workbook), 'origin': origin}


def probe_instance(port, workbook=None, timeout=0.7):
    """No proxies, redirects, cookie access, mutation or unrelated-service heuristics."""
    origin = f'http://127.0.0.1:{port}'
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    try:
        connection.request('GET', '/api/instance', headers={'Host': f'127.0.0.1:{port}'})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('Content-Type', '').split(';')[0] != 'application/json':
            return False
        raw = response.read(4097)
        if len(raw) > 4096:
            return False
        actual = json.loads(raw)
        return isinstance(actual, dict) and actual == instance_identity(origin, workbook)
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def bind_diagnostic(exc, port):
    code = getattr(exc, 'winerror', None) or exc.errno
    if code in (errno.EADDRINUSE, 10048):
        explanation = 'El puerto ya esta ocupado.'
    elif code in (errno.EACCES, errno.EPERM, 10013):
        explanation = 'Windows o el sistema ha denegado el puerto (puede estar reservado o restringido).'
    elif code in (errno.EADDRNOTAVAIL, 10049):
        explanation = 'La direccion local no esta disponible.'
    else:
        explanation = 'No se pudo enlazar el servidor local.'
    return f'{explanation} 127.0.0.1:{port}; errno={exc.errno}; winerror={getattr(exc, "winerror", None)}; detalle={exc}'


def recoverable_bind_error(exc):
    return exc.errno in (errno.EADDRINUSE, errno.EACCES, errno.EPERM) or getattr(exc, 'winerror', None) in (10048, 10013)


def record_path(requested_port, workbook=None):
    key = f'{INSTALLATION_ID}:{requested_port}:{workbook_id(workbook)}'
    name = hashlib.sha256(key.encode()).hexdigest()
    return Path(tempfile.gettempdir()) / f'orgdna-launch-{name}.json'


def remembered_port(path):
    try:
        if path.stat().st_size > 4096:
            return None
        value = json.loads(path.read_text('utf-8')).get('port')
        return value if type(value) is int and 1 <= value <= 65535 else None
    except (OSError, ValueError, AttributeError):
        return None


def remember_port(path, port):
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix='orgdna-launch-', suffix='.tmp', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            json.dump({'port': port}, output)
        os.replace(temporary, path)
    except OSError as exc:
        print(f'Aviso: no se pudo guardar el puerto para el proximo arranque: {exc}')
    finally:
        if temporary:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass


def select_server(server_factory, port, workbook=None, strict=False, output=print, record=None):
    """Return (bound server, None) or (None, verified existing origin)."""
    if port and probe_instance(port, workbook):
        return None, f'http://127.0.0.1:{port}'
    cached = remembered_port(record) if record is not None and not strict else None
    if cached and cached != port and probe_instance(cached, workbook):
        return None, f'http://127.0.0.1:{cached}'
    try:
        return server_factory(('127.0.0.1', port), None), None
    except OSError as exc:
        output(bind_diagnostic(exc, port))
        # A second launcher may have completed between the initial probe and bind.
        if port and probe_instance(port, workbook):
            return None, f'http://127.0.0.1:{port}'
        if strict or not port or not recoverable_bind_error(exc):
            raise
        output('Ese puerto no corresponde a una instancia compatible de esta copia. Se usara un puerto libre solo para el panel OrgDNA; DSH no cambia.')
        try:
            return server_factory(('127.0.0.1', 0), None), None
        except OSError as fallback:
            output(bind_diagnostic(fallback, 0))
            raise



class StartupLock:
    """OS-backed inter-process startup lock; released automatically on process exit.

    Keep the file after unlock: unlinking it could let contenders lock two inodes.
    Windows locks one byte with msvcrt; Unix uses flock. No external dependency.
    """
    def __init__(self, path, timeout=20):
        self.path = Path(path)
        self.timeout = timeout
        self.file = None

    def __enter__(self):
        self.file = self.path.open('a+b')
        self.file.seek(0, os.SEEK_END)
        if self.file.tell() == 0:
            self.file.write(b'0')
            self.file.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            self.file.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    self.release()
                    raise
                if time.monotonic() >= deadline:
                    self.release()
                    raise TimeoutError('Otro arranque de esta copia sigue en curso. Espera a que aparezca el panel y vuelve a abrir launch.cmd.') from exc
                time.sleep(.05)

    def release(self):
        if self.file is not None:
            self.file.close()  # Closing releases the kernel lock on both platforms.
            self.file = None

    def __exit__(self, *args):
        self.release()


def main(argv=None):
    if sys.version_info < (3, 10):
        raise SystemExit('OrgDNA requiere Python 3.10 o posterior.')
    if __package__:
        from .bridge import BridgeState, LocalServer
    else:
        from bridge import BridgeState, LocalServer
    parser = argparse.ArgumentParser(description='Panel local OrgDNA sin macros ni dependencias Python externas.')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help='Puerto preferido del panel (0 elige uno libre).')
    parser.add_argument('--strict-port', action='store_true', help='No cambiar ni reutilizar otro puerto si el solicitado falla.')
    parser.add_argument('--workbook')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('--port debe estar entre 0 y 65535.')
    record = record_path(args.port, args.workbook)
    try:
        with StartupLock(record.with_suffix('.lock')) as startup_lock:
            return _run_locked(args, record, startup_lock, BridgeState, LocalServer)
    except (OSError, TimeoutError) as exc:
        raise SystemExit(f'No se pudo coordinar el arranque local: {exc}')


def _run_locked(args, record, startup_lock, BridgeState, LocalServer):
    try:
        server, existing = select_server(LocalServer, args.port, args.workbook, args.strict_port, record=record)
    except OSError:
        raise SystemExit('No se pudo iniciar OrgDNA. No se ha cerrado ningun proceso ni cambiado DSH. Prueba launch.cmd --port 0 o revisa las restricciones locales.')
    if existing:
        print('OrgDNA ya esta abierto (misma copia y version): ' + existing)
        if not args.no_browser:
            webbrowser.open(existing)
        return
    state = None
    try:
        state = BridgeState(args.workbook)
        server.state = state
        remember_port(record, server.server_address[1])
        print('OrgDNA: ' + server.origin)
        if server.server_address[1] != args.port:
            print('Usa este enlace para el panel. Los enlaces antiguos de Excel conservan su puerto; usa las descargas del panel o actualiza esos enlaces expresamente.')
        print('Solo este equipo. Sin llamadas API al arrancar. Ctrl+C para cerrar y borrar claves de memoria.')
        if not args.no_browser:
            webbrowser.open(server.origin)
        # Release only from the live server loop, after state and identity are
        # available. Concurrent launchers recheck the fallback record under lock.
        original_service_actions = getattr(server, 'service_actions', lambda: None)
        def ready_service_actions():
            startup_lock.release()
            original_service_actions()
        server.service_actions = ready_service_actions
        server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt:
        pass
    finally:
        if state is not None:
            with state.lock:
                state.generation.invalidate('La app se cerro. No se enviaran lotes nuevos; una solicitud ya transmitida puede tener coste.')
                if state.integrations.dsh_manager is not None:
                    state.integrations.dsh_manager.disconnect()
                state.credentials.clear()
                state._sensitive_values.clear()
            if state.repo_cache is not None:
                state.repo_cache.clear()
        server.server_close()


if __name__ == '__main__':
    main()
