"""Bounded local preflight for the supplied DSH restart wrapper.

The existing launcher binary is not audited. Only an explicit, hash-bound user
operation can run that exact EXE after backup; this never guarantees preservation.
All session input is ephemeral and excluded from project/export persistence.
"""
from __future__ import annotations
import copy
from datetime import datetime
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import threading
import time
import uuid
import zipfile

ACTIONS = frozenset({'dsh-launch-discover', 'dsh-launch-inspect', 'dsh-launch-health', 'dsh-launch-backup', 'dsh-launch-execute', 'dsh-launch-clear'})
MAX_SCRIPT = 256 * 1024
MAX_BACKUP = 512 * 1024 * 1024
MAX_FILES = 20000
CONTRACT_VERSION = 'DSH_REINICIAR/1.1.1'
KNOWN_BINARIES = frozenset({
    'c149d0bf8b7d7a14ce81f7008a6c8b98dc02aa78aecb708342138093eeeb3fd0'})
SAFE_ARGUMENTS = ['--headless', '--no-open']

class LauncherError(ValueError):
    pass


def on_windows():
    return os.name == "nt"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def no_links(path):
    """Reject symlinks and Windows junctions on every ancestor."""
    for part in (path, *path.parents):
        s = part.lstat()
        if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:
            raise LauncherError('No se admiten enlaces simbólicos ni junctions en las rutas seleccionadas.')


def regular(path):
    no_links(path)
    if not path.is_file():
        raise LauncherError('Selecciona un archivo local existente.')


def file_hash(path, limit):
    regular(path)
    if path.stat().st_size > limit:
        raise LauncherError('El archivo supera el límite de lectura local.')
    h = hashlib.sha256()
    with path.open('rb') as stream:
        total = 0
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise LauncherError('El archivo cambió o supera el límite de lectura.')
            h.update(chunk)
    return h.hexdigest(), total


def local_path(value, suffix=None):
    if not isinstance(value, str) or not value or len(value) > 2048 or any(c in value for c in '\x00\r\n'):
        raise LauncherError('Indica una ruta absoluta local válida.')
    # No UNC/network shares, device paths or Windows alternate data streams.
    if value.startswith(('\\\\', '//')) or (os.name == 'nt' and ':' in value[2:]):
        raise LauncherError('Usa una ruta local, sin recursos de red ni streams alternativos.')
    p = Path(value)
    if not p.is_absolute() or (suffix and p.suffix.lower() not in suffix):
        raise LauncherError('Ruta absoluta o extensión no válida.')
    return p


@contextmanager
def locked_executable(path, expected_sha):
    """Windows read handle denies binary writes/deletes until CreateProcess returns."""
    import ctypes
    import msvcrt
    from ctypes import wintypes
    no_links(path)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0x80000000, 0x1, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise LauncherError('No se pudo bloquear el EXE contra cambios durante el inicio.')
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except Exception:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(fd, 'rb') as stream:
        h = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
        if h.hexdigest() != expected_sha:
            raise LauncherError('El EXE cambió antes de ejecutarse. Prepara un plan nuevo.')
        yield


class DSHLauncher:
    def __init__(self, backup_root):
        self.backup_root = Path(backup_root)
        self.lock = threading.RLock()
        self._inputs = None
        self._process = None
        self._consumed = {}
        self._legacy_eligible_sha = None
        self._legacy_eligible_config = None
        self._discovery = None
        self._state = self._empty()

    @staticmethod
    def _empty():
        return {'status': 'AWAITING_SCRIPT', 'execution_available': False,
                'integration_status': 'NOT_VERIFIED', 'plan': None, 'backup': None, 'run': None, 'legacy_retry_available': False,
                'health': [], 'events': [],
                'blockers': ['Selecciona el BAT original y el EXE que utiliza. Revisa rutas, copia y riesgos antes de autorizar una operación.']}

    def public(self):
        with self.lock:
            result = copy.deepcopy(self._state)
            result['discovery'] = copy.deepcopy(self._discovery)
            return result

    def _event(self, code):
        # Fixed event identifiers only; never child output, paths, script or secrets.
        self._state['events'] = (self._state['events'] + [{'at': time.time(), 'code': code}])[-30:]

    def _config_data(self):
        result = {'configured': None, 'config_sha256': None, 'prerequisites': []}
        if not on_windows() or not os.environ.get('LOCALAPPDATA'):
            return result
        path = Path(os.environ['LOCALAPPDATA']) / 'DSH_LAUNCHER' / 'launcher.json'
        if not path.exists():
            return result
        sha, _ = file_hash(path, 64 * 1024)
        with path.open('rb') as stream:
            raw = stream.read(64 * 1024 + 1)
        if digest(raw) != sha:
            raise LauncherError('La configuración del launcher cambió durante la lectura.')
        try:
            value = json.loads(raw)
            allowed = {'schema', 'home', 'runtime', 'profile', 'port', 'startupTimeoutSeconds', 'stabilitySeconds', 'openBrowser', 'shutdownTimeoutSeconds', 'idleWaitSeconds', 'restartDebounceSeconds'}
            if not isinstance(value, dict) or set(value) - allowed:
                raise ValueError()
            if value.get('schema') != 1 or type(value.get('port')) is not int or not 1024 <= value['port'] <= 65535 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', value.get('profile', '')):
                raise ValueError()
            env = {k.lower(): v for k, v in os.environ.items()}
            def expanded_path(item):
                if not isinstance(item, str):
                    raise ValueError()
                expanded = re.sub(r'%([^%]+)%', lambda m: env.get(m.group(1).lower(), m.group(0)), item)
                if '%' in expanded:
                    raise ValueError()
                return local_path(expanded)
            home = expanded_path(value.get('home'))
            runtime = expanded_path(value.get('runtime'))
        except (ValueError, TypeError, AttributeError):
            raise LauncherError('launcher.json no declara schema, home, runtime, profile y port válidos. No se aplican defaults silenciosos.') from None
        configured = {'home': str(home), 'runtime': str(runtime), 'profile': value['profile'], 'port': value['port']}
        checks = [{'kind': label, 'exists': target.exists()} for label, target in [
            ('DSH_HOME', home), ('DSH_RUNTIME', runtime),
            ('PROFILE_PACKAGE', home / 'profiles' / value['profile'] / 'package.json'),
            ('DSH_ENTRY', runtime / 'node_modules' / '@deepseek-ai' / 'dsh' / 'lib' / 'bin.js')]]
        return {'configured': configured, 'config_path': str(path), 'config_sha256': sha, 'prerequisites': checks}

    def discover(self):
        result = self._config_data()
        if self._legacy_eligible_config and result.get('config_sha256') != self._legacy_eligible_config:
            self._legacy_eligible_sha = self._legacy_eligible_config = None
            self._state['legacy_retry_available'] = False
        included = Path(__file__).resolve().parent.parent / 'relanzador_dsh' / 'DSH_REINICIAR.exe'
        result['included_executable'] = str(included) if included.is_file() else None
        result['included_binary_verified'] = bool(included.is_file() and file_hash(included, 256 * 1024 * 1024)[0] in KNOWN_BINARIES)
        result['missing_config_note'] = 'Sin configuración explícita no se ejecutará. El source propone perfil web y puerto 3080; son propuestas, no puertos verificados de tu instalación.'
        self._discovery = result

    @staticmethod
    def _read_process_signal(stream):
        # Drain bounded lines; retain only these fixed machine-readable events.
        # Never store, display or export stdout text, URLs, auth or summary bodies.
        signal, buffer, dropping = None, b'', False
        if stream is None:
            return None
        while True:
            chunk = stream.read(4096)
            if not chunk or not isinstance(chunk, bytes):
                break
            for part in chunk.splitlines(keepends=True):
                if not dropping:
                    buffer += part
                    if len(buffer) > 64 * 1024:
                        buffer, dropping = b'', True
                if part.endswith((b'\n', b'\r')):
                    if not dropping:
                        if re.fullmatch(rb'Codigo: LEGACY_RESTART_CONFIRMATION \| Diagnostico: [^\r\n]+[\r\n]*', buffer):
                            signal = 'LEGACY_RESTART_CONFIRMATION'
                        try:
                            event = json.loads(buffer)
                            if event.get('status') == 'ALREADY_RESTARTING':
                                signal = 'ALREADY_RESTARTING'
                            elif event.get('event') == 'failed' and event.get('code') == 'LEGACY_RESTART_CONFIRMATION':
                                signal = 'LEGACY_RESTART_CONFIRMATION'
                            elif event.get('event') == 'ready':
                                signal = 'READY_REPORTED'
                        except (ValueError, AttributeError):
                            pass
                    buffer, dropping = b'', False
        return signal

    def inspect(self, body):
        legacy = body.get('legacy_stop') is True
        operation = body.get('operation', 'reuse')
        if operation not in {'reuse', 'restart'}:
            raise LauncherError('Selecciona reutilizar o reiniciar explícitamente.')
        if legacy and operation != 'restart':
            raise LauncherError('Legacy sólo corresponde a un reinicio explícito.')
        self._inputs = None
        self._state = self._empty()
        path = local_path(body.get('script_path'), {'.bat', '.cmd'}) if body.get('script_path') else None
        sha, size, script = None, 0, ''
        if path:
            sha, size = file_hash(path, MAX_SCRIPT)
            raw = path.read_bytes()
            if digest(raw) != sha:
                raise LauncherError('El BAT cambió durante la lectura; vuelve a inspeccionarlo.')
            script = raw.decode('utf-8-sig', errors='replace')
        exe = local_path(body.get('exe_path'), {'.exe'}) if body.get('exe_path') else None
        binary = None
        if exe:
            binary_sha, binary_size = file_hash(exe, 256 * 1024 * 1024)
            with exe.open('rb') as stream:
                pe = stream.read(2) == b'MZ'
            binary = {'sha256': binary_sha, 'bytes': binary_size, 'pe_header': pe, 'known_delivery': binary_sha in KNOWN_BINARIES}
        if legacy and (not binary or self._legacy_eligible_sha != binary['sha256']):
            raise LauncherError('El modo legacy sólo se ofrece después del error específico de una operación segura correlacionada.')
        supplied = body.get('ports', [])
        if not isinstance(supplied, list) or len(supplied) > 16 or any(type(p) is not int or not 1024 <= p <= 65535 for p in supplied):
            raise LauncherError('Indica hasta 16 puertos enteros entre 1024 y 65535.')
        found = sorted({int(p) for p in re.findall(r'(?:127\.0\.0\.1:|localhost:|--port[= ]+)([0-9]{4,5})(?!\d)', script) if 1024 <= int(p) <= 65535})
        ports = sorted(set(supplied)) if supplied else found
        backup_paths = body.get('backup_paths', [])
        if not isinstance(backup_paths, list) or len(backup_paths) > 8:
            raise LauncherError('Indica hasta ocho rutas de respaldo.')
        roots = [local_path(p) for p in backup_paths]
        if len(set(map(str, roots))) != len(roots):
            raise LauncherError('Las rutas de respaldo están duplicadas.')
        self.discover()
        configured = self._discovery.get('configured')
        checks = self._discovery.get('prerequisites', [])
        if configured and not supplied:
            ports = [configured['port']]
        config_matches = bool(configured and configured['port'] in ports)
        if legacy and self._legacy_eligible_config != self._discovery.get('config_sha256'):
            raise LauncherError('Cambió la configuración desde el fallo legacy. Vuelve a comprobar la operación segura.')
        blockers = ['Contrato 1.1.1 revisado en fuente; ejecución Windows y preservación real no verificadas. La integración automática sigue pendiente.', 'Reiniciar pierde --patch previo y limpia NODE_OPTIONS/NODE_PATH. Reutilizar es la opción inicial. Revisa tu configuración efectiva antes de autorizar reinicio.']
        if binary and not binary['known_delivery']:
            blockers.append('El SHA del EXE no coincide con fuente/DSH_REINICIAR.exe de la entrega 1.1.1 revisada. Este adaptador no puede ejecutarlo.')
        if '--allow-legacy-stop' in script.lower():
            blockers.append('El BAT original solicita cierre legacy. Este panel primero usa --headless --no-open --restart SIN ese permiso. Legacy puede perder estado en memoria y exige otra operación confirmada.')
        if not exe:
            blockers.append('Falta seleccionar el DSH_REINICIAR.exe exacto utilizado por el BAT.')
        if not on_windows():
            blockers.append('El diagnóstico de instalación y el relanzador requieren Windows local.')
        if not ports:
            blockers.append('El BAT no declara puertos verificables. Indica los puertos originales; no se asignan otros.')
        if not roots:
            blockers.append('Faltan rutas explícitas de configuración e historial para preparar respaldo.')
        if not config_matches:
            blockers.append('Falta launcher.json explícito compatible o su puerto no coincide con los seleccionados. No se ejecutará con defaults adivinados.')
        if any(not c['exists'] for c in checks):
            blockers.append('Faltan requisitos de la instalación DSH local.')
        # Content itself is intentionally never returned; even command arguments
        # and variable names can contain credentials. Review the original locally.
        plan = {'operation_id': uuid.uuid4().hex, 'script_sha256': sha, 'script_bytes': size, 'binary': binary,
                'wrapper_calls_restart_exe': bool(re.search(r'DSH_REINICIAR\.exe', script, re.I)),
                'wrapper_legacy_stop_requested': '--allow-legacy-stop' in script.lower(), 'legacy_stop_requested': legacy,
                'ports': ports, 'ports_source': 'user' if supplied else ('launcher_config' if configured else 'literal_script'),
                'launcher_config_sha256': self._discovery.get('config_sha256'),
                'backup_root_count': len(roots), 'prerequisites': checks,
                'script_preview': 'Contenido omitido para no revelar secretos. Revisa el BAT original en tu editor local.',
                'compatibility': 'PRESERVATION_UNVERIFIED', 'launcher_does_not_write_config': True, 'binary_effects': 'RUNTIME_UNVERIFIED', 'contract_version': CONTRACT_VERSION, 'operation': operation, 'arguments': SAFE_ARGUMENTS + ['--' + operation] + (['--allow-legacy-stop'] if legacy else []),
                'executable_path': str(exe) if exe else None, 'script_path': str(path),
                'backup_paths': list(map(str, roots)), 'execution_risk': 'El reinicio puede perder --patch previo y limpia NODE_OPTIONS/NODE_PATH; puede interrumpir sesiones, escribir estado/config del launcher y usar autenticación existente. Legacy puede perder datos en memoria. No conserva necesariamente la configuración efectiva. Respaldo parcial; no garantiza restauración.'}
        # Bind selected paths and operation ID into the consent digest; never persist them.
        binding = {'plan': plan, 'script_path': str(path) if path else None, 'exe_path': str(exe) if exe else None, 'backup_paths': list(map(str, roots))}
        plan['plan_sha256'] = digest(json.dumps(binding, sort_keys=True).encode())
        self._inputs = (path, exe, roots)
        self._state.update(status='AWAITING_BACKUP_AND_CONFIRMATION', plan=plan, blockers=blockers,
            legacy_retry_available=bool(binary and self._legacy_eligible_sha == binary['sha256']),
            execution_available=bool(on_windows() and binary and binary['pe_header'] and binary['known_delivery'] and config_matches and roots and ports and all(c['exists'] for c in checks)))
        self._event('PREFLIGHT_COMPLETED_PRESERVATION_UNVERIFIED')

    def _verified_plan(self, body):
        plan = self._state['plan']
        if not plan or self._state['status'] == 'STALE_PLAN' or body.get('plan_sha256') != plan['plan_sha256']:
            raise LauncherError('El plan falta o cambió; vuelve a inspeccionar y revisar su hash.')
        path, exe, roots = self._inputs
        if (path and file_hash(path, MAX_SCRIPT)[0] != plan['script_sha256']) or (exe and file_hash(exe, 256 * 1024 * 1024)[0] != plan['binary']['sha256']):
            self._state['status'] = 'STALE_PLAN'
            raise LauncherError('El BAT o EXE cambió. Prepara un plan nuevo antes de continuar.')
        if plan.get('launcher_config_sha256'):
            current = self._config_data()
            if current.get('config_sha256') != plan['launcher_config_sha256']:
                raise LauncherError('launcher.json cambió desde el plan. Inspecciona de nuevo.')
        return plan, roots

    def health(self, body):
        plan, _ = self._verified_plan(body)
        health = []
        for port in plan['ports']:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.3):
                    listening = True
            except OSError:
                listening = False
            health.append({'port': port, 'tcp_listening': listening, 'identity_verified': False})
        self._state['health'] = health
        self._event('TCP_CHECK_ONLY_NO_RUNTIME_IDENTITY')

    @staticmethod
    def _entry_name(index, relative):
        """Nombre de entrada ZIP conforme a APPNOTE 4.4.17.1 (barra inclinada).

        Path.__truediv__ usa os.sep, que en Windows es '\\': el nombre quedaba
        como '0\\history.json'. zipfile normaliza os.sep al escribir (ZipInfo),
        asi que el archivo guardaba '0/history.json' mientras este manifiesto
        interno conservaba el nombre sin normalizar. La copia se escribia bien y
        fallaba al verificarse contra su propia lista: dsh-launch-backup no podia
        completarse nunca en Windows y el error real quedaba enmascarado.
        as_posix() fija el separador en los dos lados: se busca lo que se escribio.
        """
        return '%d/%s' % (index, relative.as_posix())

    @staticmethod
    def _inventory(roots):
        names = set()
        for index, root in enumerate(roots):
            no_links(root)
            candidates = root.rglob('*') if root.is_dir() else [root]
            for path in candidates:
                no_links(path)
                if path.is_file():
                    names.add(DSHLauncher._entry_name(index, path.relative_to(root) if root.is_dir() else Path(path.name)))
                    if len(names) > MAX_FILES:
                        raise LauncherError('Demasiados archivos en las rutas de respaldo.')
        return names

    def backup(self, body):
        plan, roots = self._verified_plan(body)
        if body.get('backup_confirmed') is not True or not roots:
            raise LauncherError('Revisa y autoriza las rutas de respaldo antes de copiar archivos.')
        if self._state['backup']:
            raise LauncherError('Este plan ya tiene una copia. Inspecciona de nuevo para crear otra.')
        files = []
        total = 0
        for index, root in enumerate(roots):
            no_links(root)
            if not root.exists():
                raise LauncherError('Una ruta de respaldo no existe.')
            candidates = root.rglob('*') if root.is_dir() else [root]
            for p in candidates:
                if p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) & 0x400:
                    raise LauncherError('El respaldo contiene un enlace o junction; no se sigue.')
                if p.is_dir():
                    continue
                regular(p)
                size = p.stat().st_size
                total += size
                if total > MAX_BACKUP or len(files) >= MAX_FILES:
                    raise LauncherError('Respaldo demasiado grande: máximo 512 MiB y 20.000 archivos. Usa un respaldo nativo fuera de la app.')
                files.append((p, DSHLauncher._entry_name(index, p.relative_to(root) if root.is_dir() else Path(p.name))))
        if not files:
            raise LauncherError('Las rutas no contienen archivos para respaldar.')
        # Never create output inside the selected source or through an existing link.
        destination = self.backup_root.absolute()
        if any(root == destination or root in destination.parents for root in roots):
            raise LauncherError('La carpeta de copias está dentro de una ruta de origen. Selecciona rutas más precisas.')
        for parent in (self.backup_root, *self.backup_root.parents):
            if parent.exists() or parent.is_symlink():
                no_links(parent)
        # A private per-user location on Windows; no uploads/download links.
        self.backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        no_links(self.backup_root)
        if not on_windows():
            os.chmod(self.backup_root, 0o700)
        target = self.backup_root / ('dsh-' + uuid.uuid4().hex + '.zip')
        entries = []
        copied = 0
        try:
            with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_STORED) as z:
                for path, name in files:
                    regular(path)
                    with path.open('rb') as stream:
                        raw = stream.read(MAX_BACKUP - copied + 1)
                    copied += len(raw)
                    if copied > MAX_BACKUP:
                        raise LauncherError('Un archivo creció durante el respaldo.')
                    entries.append({'entry': name, 'sha256': digest(raw), 'bytes': len(raw)})
                    z.writestr(name, raw)
                z.writestr('manifest.json', json.dumps({'plan_sha256': plan['plan_sha256'], 'files': entries}))
            if not on_windows():
                os.chmod(target, 0o600)
            with zipfile.ZipFile(target) as z:
                if z.testzip() or any(digest(z.read(e['entry'])) != e['sha256'] for e in entries):
                    raise LauncherError('La verificación del respaldo falló.')
            if self._inventory(roots) != {e['entry'] for e in entries}:
                raise LauncherError('La lista de archivos cambió durante el respaldo.')
            # Ensure the source files still match. This does not claim DB consistency.
            if any(file_hash(p, MAX_BACKUP)[0] != e['sha256'] for (p, _), e in zip(files, entries)):
                raise LauncherError('Los datos cambiaron durante la copia. Cierra DSH manualmente y repite.')
            sha, size = file_hash(target, MAX_BACKUP + 20 * 1024 * 1024)
            self._state['backup'] = {'status': 'VERIFIED_FILE_COPY', 'filename': target.name,
                'sha256': sha, 'bytes': size, 'file_count': len(entries),
                'application_consistency': 'UNVERIFIED', 'destination': str(self.backup_root),
                'warning': 'Puede contener credenciales. Protege esta carpeta. No demuestra consistencia de una base de datos activa ni cobertura de rutas omitidas.'}
            self._event('BACKUP_FILE_HASHES_VERIFIED')
        except Exception as cause:
            target.unlink(missing_ok=True)
            # Se conserva el mensaje y el tipo (el contrato visible no cambia),
            # pero la causa original queda encadenada. Con `from None` un fallo
            # interno era indistinguible de un fallo de rutas: el diagnostico
            # apuntaba al sitio equivocado.
            raise LauncherError('No se completó un respaldo verificable. Revisa las rutas y cierra DSH manualmente antes de repetir.') from cause

    @staticmethod
    def _result_path():
        base = os.environ.get('LOCALAPPDATA')
        return Path(base) / 'DSH_LAUNCHER' / 'state' / 'last-result.json' if base else None

    def _result_file_hash(self):
        try:
            path = self._result_path()
            return file_hash(path, 64 * 1024)[0] if path and path.exists() else None
        except (OSError, LauncherError):
            return None

    def _read_result(self, run, previous_hash, operation):
        absent = {'status': 'UNVERIFIED', 'binding': 'NO_NEW_CORRELATED_RESULT'}
        if run.get('process_signal') == 'ALREADY_RESTARTING':
            return absent
        try:
            path = self._result_path()
            sha = self._result_file_hash()
            if not path or not sha or sha == previous_hash:
                return absent
            with path.open('rb') as stream:
                raw = stream.read(64 * 1024 + 1)
            if digest(raw) != sha or len(raw) > 64 * 1024:
                return absent
            value = json.loads(raw)
            if value.get('schema') != 'hfrc.dsh.launcher.result.v2' or str(value.get('launcher')) != '1.1.1':
                return absent
            start = datetime.fromisoformat(value['at'].replace('Z', '+00:00')).timestamp()
            end = datetime.fromisoformat(value['completedAt'].replace('Z', '+00:00')).timestamp()
            if not (run['started_at'] <= start <= end <= run['finished_at'] + 2):
                return absent
            status = value.get('status')
            if status not in {'READY', 'FAILED'} or value.get('requestedAction') != ('restart' if operation == 'restart' else 'open'):
                return absent
            result = {'status': status, 'sha256': sha, 'binding': 'TIME_AND_HASH_ONLY_NO_RUN_ID',
                'runtime_identity_verified': False, 'preservation_verified': False}
            if status == 'FAILED':
                result['error_code'] = 'LEGACY_RESTART_CONFIRMATION' if value.get('errorCode') == 'LEGACY_RESTART_CONFIRMATION' else 'LAUNCHER_FAILED'
            if type(value.get('pid')) is int and value['pid'] > 0:
                result['reported_runtime_pid'] = value['pid']
            if type(value.get('port')) is int and 1024 <= value['port'] <= 65535:
                result['reported_port'] = value['port']
            if value.get('action') in {'restarted', 'started', 'reused', 'checked'}:
                result['reported_action'] = value['action']
            return result
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return absent

    def execute(self, body):
        plan, _ = self._verified_plan(body)
        if plan['plan_sha256'] in self._consumed:
            self._state['run'] = self._consumed[plan['plan_sha256']]
            self._state['status'] = 'LAUNCHER_RUNNING' if self._state['run']['status'] == 'RUNNING' else 'LAUNCHER_EXITED_RUNTIME_UNVERIFIED'
            return  # At most once per exact plan, even after uncertain response.
        if not self._state['execution_available'] or not on_windows():
            raise LauncherError('Faltan requisitos locales: Windows, BAT reconocido, EXE válido, rutas y puertos originales.')
        if not all(body.get(k) is True for k in ('execute_confirmed', 'interruption_acknowledged', 'preservation_unverified_acknowledged')):
            raise LauncherError('Confirma esta operación exacta, la interrupción de sesiones y el riesgos de esta operación.')
        backup = self._state['backup']
        if not backup or backup['status'] != 'VERIFIED_FILE_COPY':
            raise LauncherError('Primero crea y verifica el respaldo de las rutas revisadas.')
        backup_path = self.backup_root / backup['filename']
        if file_hash(backup_path, MAX_BACKUP + 20 * 1024 * 1024)[0] != backup['sha256']:
            raise LauncherError('El respaldo cambió o falta. Prepara otro plan y una copia nueva.')
        # Recheck every copied source against the archive manifest at action time.
        with zipfile.ZipFile(backup_path) as z:
            manifest = json.loads(z.read('manifest.json'))
        if self._inventory(self._inputs[2]) != {e['entry'] for e in manifest['files']}:
            raise LauncherError('Las rutas cambiaron desde el respaldo. Prepara una copia nueva.')
        for entry in manifest['files']:
            parts = Path(entry['entry']).parts
            root = self._inputs[2][int(parts[0])]
            source = root.joinpath(*parts[1:]) if root.is_dir() else root
            if file_hash(source, MAX_BACKUP)[0] != entry['sha256']:
                raise LauncherError('Los datos cambiaron desde el respaldo. Inspecciona y copia de nuevo.')
        self._verified_plan(body)
        exe = self._inputs[1]
        if plan['binary']['sha256'] not in KNOWN_BINARIES:
            raise LauncherError('El EXE no corresponde al contrato revisado.')
        if plan['legacy_stop_requested'] and body.get('legacy_stop_confirmed') is not True:
            raise LauncherError('El cierre legacy necesita confirmación específica por el riesgo de pérdida de estado en memoria.')
        before_result = self._result_file_hash()
        # No shell, BAT invocation, user arguments, process enumeration or kill.
        self._state['run'] = {'id': uuid.uuid4().hex, 'status': 'STARTING', 'exit_code': None, 'started_at': time.time(), 'runtime_ready': False}
        self._consumed[plan['plan_sha256']] = self._state['run']
        try:
            with locked_executable(exe, plan['binary']['sha256']):
                self._process = subprocess.Popen([str(exe), *plan['arguments']], cwd=str(exe.parent),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    shell=False, close_fds=True)
        except (OSError, LauncherError):
            self._state['run']['status'] = 'FAILED_TO_START'
            self._event('EXE_FAILED_TO_START_NO_OUTPUT_RECORDED')
            raise LauncherError('Windows no pudo iniciar el EXE. No se reintentará este plan automáticamente.') from None
        self._state['status'] = 'LAUNCHER_RUNNING'
        self._state['run']['status'] = 'RUNNING'
        self._state['run']['launcher_process_pid'] = self._process.pid if type(self._process.pid) is int else None
        self._event('USER_CONFIRMED_EXE_STARTED')
        process = self._process
        run = self._state['run']
        run_id = run['id']
        def observe():
            signal = self._read_process_signal(process.stdout)
            code = process.wait()
            with self.lock:
                run.update(status='EXITED', exit_code=code, finished_at=time.time(), process_signal=signal)
                run['launcher_result'] = self._read_result(run, before_result, plan['operation'])
                if (plan['operation'] == 'restart' and not plan['legacy_stop_requested'] and code != 0 and signal == 'LEGACY_RESTART_CONFIRMATION'):
                    self._legacy_eligible_sha = plan['binary']['sha256']
                    self._legacy_eligible_config = plan.get('launcher_config_sha256')
                else:
                    self._legacy_eligible_sha = self._legacy_eligible_config = None
                if (self._state.get('run') or {}).get('id') != run_id:
                    return
                self._state['legacy_retry_available'] = bool(self._legacy_eligible_sha == plan['binary']['sha256'] and not plan['legacy_stop_requested'])
                self._state['status'] = 'LAUNCHER_EXITED_RUNTIME_UNVERIFIED'
                self._event('EXE_EXITED_RUNTIME_IDENTITY_STILL_UNVERIFIED')
        threading.Thread(target=observe, daemon=True).start()

    def apply(self, action, body):
        with self.lock:
            try:
                if self._process is not None and self._process.poll() is None and action in {'dsh-launch-inspect', 'dsh-launch-clear', 'dsh-launch-backup'}:
                    raise LauncherError('El relanzador sigue ejecutándose. Actualiza su estado antes de preparar otro plan.')
                if action == 'dsh-launch-discover': self.discover()
                elif action == 'dsh-launch-inspect': self.inspect(body)
                elif action == 'dsh-launch-health': self.health(body)
                elif action == 'dsh-launch-backup': self.backup(body)
                elif action == 'dsh-launch-clear':
                    self._state = self._empty(); self._inputs = None
                    self._legacy_eligible_sha = self._legacy_eligible_config = None
                elif action == 'dsh-launch-execute': self.execute(body)
                else: raise LauncherError('Acción de relanzador no reconocida.')
            except (OSError, KeyError):
                raise LauncherError('No se pudo leer la ruta local seleccionada. Comprueba su existencia y acceso.') from None
            return self.public()
