"""Durable local writer tickets; no filesystem or DSH execution enforcement.

A single store limits writers across every project/workspace using that store.
Paths are normalized before parent/child conflict checks. These tickets coordinate
cooperative clients; an external editor can ignore them.
"""
from __future__ import annotations
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid

MAX_WRITERS = 3
MAX_BYTES = 8 * 1024 * 1024
ACTIONS = {'lease-acquire', 'lease-renew', 'lease-release'}
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()

class CoordinationError(ValueError):
    pass


def _text(value, name, limit=160):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise CoordinationError(f'{name}: texto obligatorio no válido.')
    return value.strip()


def normalize_workspace(value):
    value = _text(value, 'workspace', 2000).replace('\\', '/')
    if value.startswith('//') or '://' in value:
        raise CoordinationError('workspace debe ser una ruta local absoluta, sin URL ni UNC.')
    windows = bool(re.match(r'^[A-Za-z]:/', value))
    if not windows and not value.startswith('/'):
        raise CoordinationError('workspace debe ser una ruta absoluta POSIX o Windows.')
    if any(part == '..' for part in value.split('/')):
        raise CoordinationError('workspace no admite traversal ..')
    if windows:
        parts = [part for part in value[3:].split('/') if part not in ('', '.')]
        if any(':' in part or part.endswith((' ', '.')) for part in parts):
            raise CoordinationError('workspace Windows contiene un segmento ambiguo.')
        return value[:2].lower() + '/' + '/'.join(parts).casefold()
    return str(Path(value).resolve())


def normalize_paths(workspace, paths):
    if not isinstance(paths, list) or not paths or len(paths) > 100:
        raise CoordinationError('paths debe contener entre 1 y 100 rutas relativas.')
    windows = bool(re.match(r'^[a-z]:/', workspace))
    result = []
    for value in paths:
        value = _text(value, 'path', 2000).replace('\\', '/')
        if value.startswith('/') or ':' in value or any(part == '..' for part in value.split('/')):
            raise CoordinationError('paths sólo admite rutas relativas dentro de workspace, sin traversal.')
        parts = [part for part in value.split('/') if part not in ('', '.')]
        if windows and any(part.endswith((' ', '.')) for part in parts):
            raise CoordinationError('Una ruta Windows contiene un segmento ambiguo.')
        relative = '/'.join(parts) or '.'
        if windows:
            relative = relative.casefold()
        else:
            # Resolve existing symlinks without opening or writing any target.
            root = Path(workspace)
            resolved = (root / relative).resolve()
            if not resolved.is_relative_to(root):
                raise CoordinationError('Una ruta sale de workspace mediante un enlace simbólico.')
            relative = resolved.relative_to(root).as_posix()
        result.append(relative)
    result = sorted(set(result))
    # A parent scope already reserves its children.
    return [path for path in result if not any(parent != path and _overlap(parent, path) and
            (parent == '.' or path.startswith(parent + '/')) for parent in result)]


def _overlap(left, right):
    return left == right or left == '.' or right == '.' or left.startswith(right.rstrip('/') + '/') or right.startswith(left.rstrip('/') + '/')


def _targets(lease):
    return [lease['workspace'].rstrip('/') + ('' if path == '.' else '/' + path) for path in lease['paths']]


def _stamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


@contextmanager
def local_file_lock(path):
    """Serialize threads and processes. OS lock is on the ledger, not code files."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(str(path.resolve()), threading.RLock())
    with lock:
        if path.is_symlink():
            raise CoordinationError('No se admite un enlace simbólico como bloqueo local.')
        descriptor = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        handle = os.fdopen(descriptor, 'r+b')
        try:
            if os.name == 'nt':
                import msvcrt
                if os.fstat(handle.fileno()).st_size == 0:
                    handle.write(b'\0'); handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


class CoordinationStore:
    def __init__(self, root, clock=None):
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / 'coordination.json'
        self.clock = clock or time.time

    def _read(self):
        if self.root.is_symlink() or self.path.is_symlink():
            raise CoordinationError('No se admite un enlace simbólico en el registro de coordinación.')
        if not self.path.exists():
            return {'format': 'orgdna-local-coordination', 'version': 1, 'leases': [], 'audit': []}
        if self.path.stat().st_size > MAX_BYTES:
            raise CoordinationError('El registro de coordinación excede el límite seguro.')
        try:
            data = json.loads(self.path.read_text('utf-8'))
            if (data.get('format') != 'orgdna-local-coordination' or type(data.get('version')) is not int or data['version'] < 1 or
                not isinstance(data.get('leases'), list) or not isinstance(data.get('audit'), list)):
                raise ValueError()
            ids = set()
            for lease in data['leases']:
                if not isinstance(lease, dict) or lease['id'] in ids or lease['status'] not in {'active', 'expired', 'released', 'invalidated'}:
                    raise ValueError()
                ids.add(lease['id'])
                if normalize_workspace(lease['workspace']) != lease['workspace'] or normalize_paths(lease['workspace'], lease['paths']) != lease['paths']:
                    raise ValueError()
                if type(lease['expires_at_epoch']) not in (int, float) or not math.isfinite(lease['expires_at_epoch']) or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', lease['base_sha']):
                    raise ValueError()
                _text(lease['owner_agent_id'], 'owner_agent_id'); _text(lease['task_id'], 'task_id')
                # Stored claims never become verified identities or hard locks.
                lease['runtime_identity_verified'] = False
                lease['filesystem_lock_enforced'] = False
                lease['dsh_enforced'] = False
                lease['base_sha_verified'] = False
            active = [row for row in data['leases'] if row['status'] == 'active']
            if len(active) > MAX_WRITERS:
                raise ValueError()
            for index, left in enumerate(active):
                for right in active[index + 1:]:
                    if any(_overlap(a, b) for a in _targets(left) for b in _targets(right)):
                        raise ValueError()
            return data
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise CoordinationError('Registro de coordinación no válido; no se han concedido tickets.') from None

    def _write(self, data):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(payload) > MAX_BYTES:
            raise CoordinationError('Registro de coordinación lleno; conserva el historial antes de continuar.')
        temp = self.root / ('.coordination.' + uuid.uuid4().hex + '.tmp')
        try:
            descriptor = os.open(str(temp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, 'wb') as output:
                output.write(payload); output.flush(); os.fsync(output.fileno())
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()

    def _event(self, data, action, lease, stamp, **extra):
        data['version'] += 1
        data['audit'].append({'id': str(uuid.uuid4()), 'version': data['version'], 'action': action,
            'lease_id': lease['id'], 'owner_agent_id': lease['owner_agent_id'], 'task_id': lease['task_id'],
            'recorded_at': _stamp(stamp), 'origin': 'local_ticket_registry', **extra})

    def _expire(self, data, stamp):
        changed = False
        for lease in data['leases']:
            if lease['status'] == 'active' and lease['expires_at_epoch'] <= stamp:
                lease['status'] = 'expired'; lease['ended_at'] = _stamp(stamp)
                self._event(data, 'expired', lease, stamp); changed = True
        return changed

    @staticmethod
    def _public(data):
        result = copy.deepcopy(data)
        result.update(max_writers=MAX_WRITERS, active_writer_count=sum(r['status'] == 'active' for r in data['leases']),
            enforcement='local_coordination_only', filesystem_lock_enforced=False, dsh_enforced=False,
            base_sha_verified=False, global_scope='all_projects_and_workspaces_in_this_local_store')
        return result

    def public(self):
        if not self.root.exists():
            return self._public(self._read())
        if self.root.is_symlink():
            raise CoordinationError('No se admite un enlace simbólico como registro local.')
        with local_file_lock(self.root / '.coordination.lock'):
            data = self._read()
            if self._expire(data, self.clock()):
                self._write(data)
            return self._public(data)

    def apply(self, action, body, agent_ids=None, project_id=None):
        if action not in ACTIONS or not isinstance(body, dict):
            raise CoordinationError('Acción de coordinación no válida.')
        if self.root.is_symlink():
            raise CoordinationError('No se admite un enlace simbólico como registro local.')
        with local_file_lock(self.root / '.coordination.lock'):
            data = self._read(); stamp = self.clock()
            if self._expire(data, stamp):
                self._write(data)
            owner = _text(body.get('owner_agent_id'), 'owner_agent_id')
            task_id = _text(body.get('task_id'), 'task_id')
            # Idempotency keys may replay exactly the same successful acquisition,
            # but never revive an expired lease or transfer its owner.
            request_id = body.get('request_id')
            if request_id is not None:
                request_id = _text(request_id, 'request_id')
            expected = body.get('expected_version')
            if action == 'lease-acquire':
                if agent_ids is not None and owner not in agent_ids:
                    raise CoordinationError('El propietario debe ser un agente del diseño actual.')
                workspace = normalize_workspace(body.get('workspace'))
                paths = normalize_paths(workspace, body.get('paths'))
                sha = body.get('base_sha')
                if not isinstance(sha, str) or not re.fullmatch(r'[a-fA-F0-9]{40}|[a-fA-F0-9]{64}', sha):
                    raise CoordinationError('base_sha debe ser un SHA completo de 40 o 64 caracteres hexadecimales.')
                ttl = body.get('ttl_seconds', 900)
                if type(ttl) is not int or not 60 <= ttl <= 3600:
                    raise CoordinationError('ttl_seconds debe ser un entero entre 60 y 3600.')
                fingerprint = hashlib.sha256(json.dumps([owner, task_id, workspace, paths, sha.lower(), ttl, project_id]).encode()).hexdigest()
                if request_id:
                    existing = next((r for r in data['leases'] if r.get('request_id') == request_id), None)
                    if existing:
                        if existing.get('request_fingerprint') == fingerprint and existing['status'] == 'active':
                            return self._public(data)
                        raise CoordinationError('request_id ya utilizado; no se puede cambiar ni reactivar ese ticket.')
            if type(expected) is not int or expected != data['version']:
                raise CoordinationError('Versión obsoleta de coordinación; recarga el estado y usa expected_version actual.')
            if action == 'lease-acquire':
                active = [r for r in data['leases'] if r['status'] == 'active']
                if len(active) >= MAX_WRITERS:
                    raise CoordinationError('Ya hay tres writers activos en este registro local.')
                targets = _targets({'workspace': workspace, 'paths': paths})
                for lease in active:
                    if any(_overlap(a, b) for a in targets for b in _targets(lease)):
                        raise CoordinationError('Conflicto de rutas: existe un ticket activo para esta ruta o su padre/hijo.')
                lease = {'id': str(uuid.uuid4()), 'owner_agent_id': owner, 'task_id': task_id,
                    'workspace': workspace, 'paths': paths, 'base_sha': sha.lower(), 'base_sha_verified': False, 'runtime_identity_verified': False,
                    'status': 'active', 'created_at': _stamp(stamp), 'expires_at': _stamp(stamp + ttl),
                    'expires_at_epoch': stamp + ttl, 'ttl_seconds': ttl, 'project_id': project_id,
                    'request_id': request_id, 'request_fingerprint': fingerprint, 'version': 1,
                    'filesystem_lock_enforced': False, 'dsh_enforced': False}
                data['leases'].append(lease); self._event(data, 'acquired', lease, stamp)
            else:
                lease = next((r for r in data['leases'] if r['id'] == body.get('lease_id')), None)
                if lease is None:
                    raise CoordinationError('Ticket no encontrado.')
                if (lease['owner_agent_id'], lease['task_id']) != (owner, task_id):
                    raise CoordinationError('Sólo el mismo propietario y tarea pueden renovar o liberar el ticket.')
                if lease['status'] != 'active':
                    raise CoordinationError('El ticket ya no está activo; no se puede reactivar.')
                if action == 'lease-renew':
                    ttl = body.get('ttl_seconds', lease['ttl_seconds'])
                    if type(ttl) is not int or not 60 <= ttl <= 3600:
                        raise CoordinationError('ttl_seconds debe ser un entero entre 60 y 3600.')
                    lease.update(expires_at=_stamp(stamp + ttl), expires_at_epoch=stamp + ttl, ttl_seconds=ttl)
                else:
                    lease.update(status='released', ended_at=_stamp(stamp))
                lease['version'] += 1
                self._event(data, 'renewed' if action == 'lease-renew' else 'released', lease, stamp)
            self._write(data)
            return self._public(data)
