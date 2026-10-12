"""Project-local capability references. No fetch, installation, grants or execution.

SQLite is private application state, never a ZIP member. Registry size is governed
by byte quotas, not an arbitrary count. Activation is explicit and context bounded.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

KINDS = ('skill_instructions', 'plugin_package', 'connector', 'memory_policy')
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_ITEM_BYTES = 128 * 1024
DEFAULT_STORAGE_BYTES = 256 * 1024 * 1024
MAX_CONTEXT_BYTES = 24000
SOURCE_TYPES = ('catalog_snapshot', 'page_evidence', 'html_summary', 'user_authored')
FORBIDDEN = {'password', 'credentials', 'api_key', 'apikey', 'access_token', 'refresh_token', 'client_secret', 'private_key', 'authorization', 'cookie', 'pending_consent'}

class CapabilityLibraryError(ValueError):
    pass


def _dump(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise CapabilityLibraryError('Datos no serializables.') from None


def _hash(value):
    return hashlib.sha256(_dump(value).encode()).hexdigest()


def _text(value, maximum=2048):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > maximum or '\x00' in value:
        raise CapabilityLibraryError('Texto ausente o demasiado largo.')
    return value.strip()


def _safe(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if re.sub(r'[^a-z_]', '', str(k).lower()) in FORBIDDEN:
                raise CapabilityLibraryError('Las credenciales y autorizaciones no pertenecen a la biblioteca.')
            _safe(v)
    elif isinstance(value, list):
        for v in value:
            _safe(v)
    elif isinstance(value, str) and re.search(r'-----BEGIN .*PRIVATE KEY-----|\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,})|\bBearer\s+[A-Za-z0-9._-]{16,}', value):
        raise CapabilityLibraryError('Se detectó un posible secreto; no se guardó.')


def _bounded(value, maximum=MAX_REQUEST_BYTES):
    raw = _dump(value)
    if len(raw.encode()) > maximum:
        raise CapabilityLibraryError('La solicitud supera la cuota de bytes; usar lotes paginados.')
    _safe(value)
    return raw


def _page(offset, limit):
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise CapabilityLibraryError('Paginación inválida (1–200 por página).')


def _org(org):
    if not isinstance(org, dict) or not isinstance(org.get('agents'), list) or not org['agents']:
        raise CapabilityLibraryError('Se requiere la organización actual.')
    ids = [a.get('id') for a in org['agents']]
    if any(not isinstance(a, str) or not a for a in ids) or len(set(ids)) != len(ids):
        raise CapabilityLibraryError('IDs actuales de agentes inválidos.')
    identity = org.get('organization_id') or org.get('config', {}).get('organization_id') or _hash(ids)
    return str(identity), org.get('state_version', 1), _hash(org)


def select_agents(org, selection):
    _org(org)
    if not isinstance(selection, dict):
        raise CapabilityLibraryError('Selección inválida.')
    ids = [a['id'] for a in org['agents']]
    mode = selection.get('mode')
    if mode == 'all':
        selected = ids
    elif mode == 'selected':
        selected = selection.get('agent_ids', [])
    elif mode == 'subteam':
        team = next((t for t in org.get('functional_subteams', []) if t.get('id') == selection.get('subteam_id')), None)
        if team is None:
            raise CapabilityLibraryError('El subequipo ya no existe.')
        selected = team.get('member_ids', [])
    else:
        raise CapabilityLibraryError('Modo de selección inválido.')
    if not isinstance(selected, list) or not selected or any(a not in ids for a in selected):
        raise CapabilityLibraryError('Seleccionar IDs de agentes de la organización actual.')
    return [a for a in ids if a in selected]


class CapabilityLibrary:
    def __init__(self, path, project_id, storage_bytes=DEFAULT_STORAGE_BYTES):
        self.path = Path(path)
        self.project_id = _text(project_id, 160)
        if type(storage_bytes) is not int or storage_bytes < MAX_REQUEST_BYTES:
            raise CapabilityLibraryError('Cuota de almacenamiento inválida.')
        self.storage_bytes = storage_bytes
        if self.path.is_symlink() or any(p.is_symlink() for p in self.path.parents):
            raise CapabilityLibraryError('No se admiten enlaces simbólicos para la biblioteca.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS projects(project TEXT PRIMARY KEY, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS items(project TEXT, id TEXT, body TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY(project,id));
            CREATE TABLE IF NOT EXISTS assignments(project TEXT, agent TEXT, item TEXT, active INTEGER NOT NULL, PRIMARY KEY(project,agent,item));
            CREATE TABLE IF NOT EXISTS events(project TEXT, version INTEGER, body TEXT NOT NULL, PRIMARY KEY(project,version));
            CREATE TABLE IF NOT EXISTS requests(project TEXT, key TEXT, fingerprint TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(project,key));
            ''')
            db.execute('INSERT OR IGNORE INTO projects VALUES (?,0)', (self.project_id,))
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def _connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _revision(self, db):
        return db.execute('SELECT revision FROM projects WHERE project=?', (self.project_id,)).fetchone()[0]

    def _cas(self, db, expected):
        if type(expected) is not int or expected != self._revision(db):
            raise CapabilityLibraryError('Versión de biblioteca obsoleta; recargar y volver a previsualizar.')

    def _cached(self, db, key, body):
        _text(key, 200)
        row = db.execute('SELECT fingerprint,result FROM requests WHERE project=? AND key=?', (self.project_id, key)).fetchone()
        if row:
            if row[0] != _hash(body):
                raise CapabilityLibraryError('Clave idempotente reutilizada para otra solicitud.')
            return json.loads(row[1])

    def _finish(self, db, key, request, result, event):
        version = self._revision(db) + 1
        result = dict(result, revision=version)
        event = dict(event, version=version, timestamp=datetime.now(timezone.utc).isoformat())
        db.execute('UPDATE projects SET revision=? WHERE project=?', (version, self.project_id))
        db.execute('INSERT INTO events VALUES (?,?,?)', (self.project_id, version, _dump(event)))
        db.execute('INSERT INTO requests VALUES (?,?,?,?)', (self.project_id, key, _hash(request), _dump(result)))
        self._check_quota(db)
        return result

    def _check_quota(self, db):
        used = sum(db.execute('SELECT COALESCE(SUM(length(CAST(body AS BLOB))),0) FROM '+table+' WHERE project=?', (self.project_id,)).fetchone()[0] for table in ('items', 'events'))
        used += db.execute('SELECT COALESCE(SUM(length(CAST(result AS BLOB))+length(CAST(key AS BLOB))+length(fingerprint)),0) FROM requests WHERE project=?', (self.project_id,)).fetchone()[0]
        used += db.execute('SELECT COALESCE(SUM(length(CAST(agent AS BLOB))+length(CAST(item AS BLOB))+64),0) FROM assignments WHERE project=?', (self.project_id,)).fetchone()[0]
        if used > self.storage_bytes:
            raise CapabilityLibraryError('Cuota de almacenamiento alcanzada; transacción cancelada.')

    def fork(self, new_project_id, expected_revision=None):
        """Clone into a fresh validated namespace in this private project-store DB.

        Definitions, assignments and audit history are copied, never credentials,
        pending confirmations or request replay keys. Source and destination can
        subsequently evolve independently. Destination must not already exist.
        """
        import uuid
        try:
            parsed = uuid.UUID(str(new_project_id))
        except (ValueError, TypeError, AttributeError):
            raise CapabilityLibraryError('El destino de Save As requiere un UUID nuevo validado.') from None
        if str(new_project_id) not in (parsed.hex, str(parsed)):
            raise CapabilityLibraryError('Formato de identidad de destino inválido.')
        destination = str(new_project_id)
        with self._connection(True) as db:
            revision = self._revision(db)
            self._cas(db, revision if expected_revision is None else expected_revision)
            if db.execute('SELECT 1 FROM projects WHERE project=?', (destination,)).fetchone():
                raise CapabilityLibraryError('El destino ya existe; Save As nunca sobrescribe otra biblioteca.')
            db.execute('INSERT INTO projects VALUES (?,?)', (destination, revision+1))
            db.execute('INSERT INTO items SELECT ?,id,body,kind,name FROM items WHERE project=?', (destination, self.project_id))
            db.execute('INSERT INTO assignments SELECT ?,agent,item,active FROM assignments WHERE project=?', (destination, self.project_id))
            db.execute('INSERT INTO events SELECT ?,version,body FROM events WHERE project=?', (destination, self.project_id))
            event = {'action': 'fork', 'version': revision+1, 'source_project_id': self.project_id, 'source_revision': revision,
                     'timestamp': datetime.now(timezone.utc).isoformat(), 'history_policy': 'copied_history_independent_future',
                     'runtime_verified': False, 'permission_changes': []}
            db.execute('INSERT INTO events VALUES (?,?,?)', (destination, revision+1, _dump(event)))
            view = self._transaction_view(db)
            view.project_id = destination
            view._check_quota(db)
        return CapabilityLibrary(self.path, destination, storage_bytes=self.storage_bytes)

    def status(self):
        with self._connection() as db:
            count = db.execute('SELECT COUNT(*) FROM items WHERE project=?', (self.project_id,)).fetchone()[0]
            assigned = db.execute('SELECT COUNT(*),COALESCE(SUM(active),0),COUNT(DISTINCT agent) FROM assignments WHERE project=?', (self.project_id,)).fetchone()
            return {'project_id': self.project_id, 'revision': self._revision(db), 'item_count': count, 'assigned_count': assigned[0], 'active_count': assigned[1], 'assigned_agent_count': assigned[2], 'installed': False, 'runtime_verified': False, 'storage_quota_bytes': self.storage_bytes, 'storage_quota_scope': 'logical_payload_not_sqlite_file_size', 'request_quota_bytes': MAX_REQUEST_BYTES, 'count_limit': None}

    def import_items(self, items, expected_revision, idempotency_key):
        request = {'items': items, 'expected_revision': expected_revision}
        _bounded(request)
        if not isinstance(items, list) or not items:
            raise CapabilityLibraryError('Se requiere una lista de capacidades.')
        clean = {}
        for item in items:
            if not isinstance(item, dict) or set(item) - {'id', 'kind', 'name', 'description', 'content', 'tags', 'role_evidence', 'tool_needs', 'provenance'}:
                raise CapabilityLibraryError('Campos de capacidad no admitidos.')
            if item.get('kind') not in KINDS:
                raise CapabilityLibraryError('Tipo de capacidad inválido.')
            source = item.get('provenance')
            if not isinstance(source, dict) or source.get('type') not in SOURCE_TYPES or not source.get('evidence'):
                raise CapabilityLibraryError('Se requiere evidencia de fuente ya consultada o autoría local.')
            _text(source['evidence'], 32000)
            if set(source) - {'type', 'evidence', 'url', 'source_id', 'retrieved_at', 'sha256'}:
                raise CapabilityLibraryError('Provenance admite evidencia, URL y hash; nunca credenciales.')
            if source.get('sha256') is not None and (not isinstance(source['sha256'], str) or not re.fullmatch(r'[a-fA-F0-9]{64}', source['sha256'])):
                raise CapabilityLibraryError('Hash de fuente inválido.')
            if source.get('url'):
                from urllib.parse import urlsplit
                parsed = urlsplit(_text(source['url'], 2048))
                if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
                    raise CapabilityLibraryError('La fuente requiere referencia HTTPS sin credenciales ni parámetros; disponibilidad no verificada.')
            body = {**item, 'name': _text(item.get('name'), 256), 'content': item.get('content', ''), 'description': item.get('description', '')}
            for field in ('content', 'description'):
                if not isinstance(body[field], str):
                    raise CapabilityLibraryError('El contenido debe ser texto.')
            for field in ('tags', 'role_evidence', 'tool_needs'):
                values = item.get(field, [])
                if not isinstance(values, list) or len(values) > 128:
                    raise CapabilityLibraryError('Lista de capacidades inválida.')
                body[field] = list(dict.fromkeys(_text(v, 512) for v in values))
            body.pop('id', None)
            content_hash = _hash(body)
            body.update(id=_text(item.get('id', content_hash), 200), content_hash=content_hash, evidence_hash=_hash(source), installed=False, runtime_verified=False, permission_grant=False)
            _bounded(body, MAX_ITEM_BYTES)
            if body['id'] in clean and clean[body['id']] != body:
                raise CapabilityLibraryError('ID duplicado con contenido diferente.')
            clean[body['id']] = body
        with self._connection(True) as db:
            cached = self._cached(db, idempotency_key, request)
            if cached is not None:
                return cached
            self._cas(db, expected_revision)
            added = []
            for key, body in clean.items():
                old = db.execute('SELECT body FROM items WHERE project=? AND id=?', (self.project_id, key)).fetchone()
                if old:
                    if json.loads(old[0]) != body:
                        raise CapabilityLibraryError('Los registros son inmutables; importar una nueva versión con otro ID.')
                    continue
                db.execute('INSERT INTO items VALUES (?,?,?,?,?)', (self.project_id, key, _dump(body), body['kind'], body['name']))
                added.append(key)
            return self._finish(db, idempotency_key, request, {'imported_count': len(added), 'deduplicated_count': len(items)-len(added)}, {'action': 'import', 'item_ids': added})

    def search(self, query='', kind=None, offset=0, limit=50):
        _page(offset, limit)
        if not isinstance(query, str) or len(query) > 500 or (kind is not None and kind not in KINDS):
            raise CapabilityLibraryError('Filtro inválido.')
        where, args = 'project=?', [self.project_id]
        if query:
            where += " AND (name LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')"
            pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            args += [pattern, pattern]
        if kind:
            where += ' AND kind=?'
            args.append(kind)
        with self._connection() as db:
            total = db.execute('SELECT COUNT(*) FROM items WHERE '+where, args).fetchone()[0]
            rows = db.execute('SELECT body FROM items WHERE '+where+' ORDER BY name,id LIMIT ? OFFSET ?', args+[limit, offset]).fetchall()
            result, used = [], 0
            for row in rows:
                body = json.loads(row[0]); size = len(row[0].encode())
                if used + size > MAX_REQUEST_BYTES:
                    break
                result.append(body); used += size
            return {'items': result, 'total': total, 'offset': offset, 'next_offset': offset+len(result) if offset+len(result)<total else None, 'revision': self._revision(db)}

    def _transaction_view(self, db):
        """Private facade shares the caller's transaction without nested commits."""
        view = object.__new__(CapabilityLibrary)
        view.path, view.project_id, view.storage_bytes = self.path, self.project_id, self.storage_bytes
        @contextmanager
        def connection(write=False):
            yield db
        view._connection = connection
        return view

    def preview_import_items(self, org, items, existing_ids, selection, expected_revision=None, action='assign'):
        """Simulate import+assignment in memory only; persistent DB stays untouched."""
        _bounded({'items': items, 'existing_ids': existing_ids, 'selection': selection})
        if not isinstance(items, list) or not isinstance(existing_ids, list):
            raise CapabilityLibraryError('Candidatos y referencias existentes deben ser listas.')
        # A SQLite snapshot provides consistent simulation without local writes.
        memory = sqlite3.connect(':memory:')
        memory.row_factory = sqlite3.Row
        try:
            with self._connection() as db:
                db.backup(memory)
            view = self._transaction_view(memory)
            revision = view._revision(memory) if expected_revision is None else expected_revision
            view._cas(memory, revision)
            request = {'project_id': self.project_id, 'items': items, 'existing_ids': existing_ids, 'selection': selection, 'action': action, 'revision': revision, 'organization_hash': _org(org)[2]}
            import_key = 'staged-import:' + _hash(request)
            if items:
                view.import_items(items, revision, import_key)
            imported_ids = []
            if items:
                # Only newly supplied records have to be resolved; default IDs are
                # hashes of canonical input, so use exact persisted row matching.
                for raw in items:
                    if raw.get('id'):
                        imported_ids.append(raw['id'])
                    else:
                        canonical = dict(raw, name=_text(raw.get('name'), 256), content=raw.get('content', ''), description=raw.get('description', ''))
                        for field in ('tags', 'role_evidence', 'tool_needs'):
                            canonical[field] = list(dict.fromkeys(_text(v, 512) for v in raw.get(field, [])))
                        canonical.pop('id', None)
                        imported_ids.append(_hash(canonical))
            assignment = view.preview(org, existing_ids+imported_ids, selection, action)
            result = dict(request, assignment_preview=assignment, imported_item_ids=sorted(set(imported_ids)), candidate_hash=_hash(items), installs=[], permission_changes=[])
            _bounded(result)
            return dict(result, preview_hash=_hash(result))
        finally:
            memory.close()

    def apply_import_preview(self, org, preview, idempotency_key):
        """Commit reviewed candidates and assignments atomically, never install."""
        _bounded(preview)
        request = {'combined_preview': preview, 'organization_hash': _org(org)[2]}
        with self._connection(True) as db:
            cached = self._cached(db, idempotency_key, request)
            if cached is not None:
                return cached
            self._cas(db, preview.get('revision'))
            unsigned = dict(preview); unsigned.pop('preview_hash', None)
            if (preview.get('preview_hash') != _hash(unsigned) or preview.get('project_id') != self.project_id or preview.get('organization_hash') != _org(org)[2] or preview.get('candidate_hash') != _hash(preview.get('items'))):
                raise CapabilityLibraryError('El plan combinado o la organización cambió.')
            view = self._transaction_view(db)
            import_request = {key: preview[key] for key in ('project_id', 'items', 'existing_ids', 'selection', 'action', 'revision', 'organization_hash')}
            if preview['items']:
                view.import_items(preview['items'], preview['revision'], 'staged-import:'+_hash(import_request))
            expected_ids = []
            for raw in preview['items']:
                if raw.get('id'):
                    expected_ids.append(raw['id'])
                else:
                    canonical = dict(raw, name=_text(raw.get('name'), 256), content=raw.get('content', ''), description=raw.get('description', ''))
                    for field in ('tags', 'role_evidence', 'tool_needs'):
                        canonical[field] = list(dict.fromkeys(_text(v, 512) for v in raw.get(field, [])))
                    canonical.pop('id', None)
                    expected_ids.append(_hash(canonical))
            assignment = preview['assignment_preview']
            if (preview['imported_item_ids'] != sorted(set(expected_ids)) or
                    assignment.get('item_ids') != sorted(set(expected_ids+preview['existing_ids'])) or
                    assignment.get('selection') != preview['selection'] or assignment.get('action') != preview['action']):
                raise CapabilityLibraryError('Los candidatos y destinos no coinciden con el plan combinado.')
            # apply recomputes all assignment effects against the same transaction.
            result = view.apply(org, preview['assignment_preview'], 'staged-apply:'+_hash(request))
            result = dict(result, imported_item_ids=preview['imported_item_ids'], atomic_import_and_assignment=True)
            db.execute('INSERT INTO requests VALUES (?,?,?,?)', (self.project_id, idempotency_key, _hash(request), _dump(result)))
            self._check_quota(db)
            return result

    def read_items(self, item_ids):
        """Exact-ID bounded reads for consent-bound shortlists; no network."""
        _bounded(item_ids)
        if not isinstance(item_ids, list):
            raise CapabilityLibraryError('Se requiere una lista de IDs.')
        result = []
        with self._connection() as db:
            for iid in dict.fromkeys(_text(i, 200) for i in item_ids):
                row = db.execute('SELECT body FROM items WHERE project=? AND id=?', (self.project_id, iid)).fetchone()
                if row is None:
                    raise CapabilityLibraryError('La capacidad no existe en este proyecto.')
                result.append(json.loads(row[0]))
        _bounded(result)
        return result

    def audit_page(self, offset=0, limit=50):
        _page(offset, limit)
        with self._connection() as db:
            rows = db.execute('SELECT body FROM events WHERE project=? ORDER BY version DESC LIMIT ? OFFSET ?', (self.project_id, limit, offset)).fetchall()
            total = db.execute('SELECT COUNT(*) FROM events WHERE project=?', (self.project_id,)).fetchone()[0]
            result, used = [], 0
            for row in rows:
                size = len(row[0].encode())
                if used+size > MAX_REQUEST_BYTES:
                    break
                result.append(json.loads(row[0])); used += size
            return {'items': result, 'total': total, 'offset': offset, 'next_offset': offset+len(result) if offset+len(result)<total else None, 'revision': self._revision(db)}

    def _preview(self, db, org, item_ids, selection, action, expected_revision):
        self._cas(db, expected_revision)
        if action not in ('assign', 'activate', 'deactivate', 'unassign'):
            raise CapabilityLibraryError('Acción de asignación inválida.')
        _bounded({'item_ids': item_ids, 'selection': selection})
        if not isinstance(item_ids, list) or not item_ids:
            raise CapabilityLibraryError('Seleccionar al menos una capacidad.')
        item_ids = sorted(set(_text(i, 200) for i in item_ids))
        agents = select_agents(org, selection)
        items = {}
        for i in item_ids:
            row = db.execute('SELECT body FROM items WHERE project=? AND id=?', (self.project_id, i)).fetchone()
            if row is None:
                raise CapabilityLibraryError('La capacidad no existe en este proyecto.')
            items[i] = json.loads(row[0])
        effects = []
        for aid in agents:
            for iid in item_ids:
                row = db.execute('SELECT active FROM assignments WHERE project=? AND agent=? AND item=?', (self.project_id, aid, iid)).fetchone()
                before = None if row is None else bool(row[0])
                after = (False if before is None else before) if action == 'assign' else True if action == 'activate' else False if action == 'deactivate' and before is not None else None
                if action == 'activate' and items[iid]['kind'] in ('plugin_package', 'connector'):
                    raise CapabilityLibraryError('Plugins y conectores sólo se asignan; no se activan ni instalan aquí.')
                if before != after:
                    effects.append({'agent_id': aid, 'item_id': iid, 'before': before, 'after': after})
        identity, version, digest = _org(org)
        result = {'project_id': self.project_id, 'organization_id': identity, 'organization_revision': version, 'organization_hash': digest, 'revision': expected_revision, 'action': action, 'item_ids': item_ids, 'selection': selection, 'agent_ids': agents, 'effects': effects, 'changed_count': len(effects), 'unchanged_count': len(agents)*len(item_ids)-len(effects), 'permission_changes': [], 'installs': [], 'tool_needs': sorted({v for item in items.values() for v in item['tool_needs']}), 'tool_availability': 'unverified'}
        _bounded(result)
        return dict(result, preview_hash=_hash(result))

    def preview(self, org, item_ids, selection, action='assign', expected_revision=None):
        with self._connection() as db:
            return self._preview(db, org, item_ids, selection, action, self._revision(db) if expected_revision is None else expected_revision)

    def _effects(self, db, effects):
        for effect in effects:
            args = (self.project_id, effect['agent_id'], effect['item_id'])
            if effect['after'] is None:
                db.execute('DELETE FROM assignments WHERE project=? AND agent=? AND item=?', args)
            else:
                db.execute('INSERT INTO assignments VALUES (?,?,?,?) ON CONFLICT(project,agent,item) DO UPDATE SET active=excluded.active', args+(int(effect['after']),))

    def apply(self, org, preview, idempotency_key):
        _bounded(preview)
        request = {'preview': preview, 'organization_hash': _org(org)[2]}
        with self._connection(True) as db:
            cached = self._cached(db, idempotency_key, request)
            if cached is not None:
                return cached
            fresh = self._preview(db, org, preview.get('item_ids'), preview.get('selection'), preview.get('action'), preview.get('revision'))
            if fresh != preview:
                raise CapabilityLibraryError('La organización o previsualización cambió; volver a previsualizar.')
            self._effects(db, fresh['effects'])
            return self._finish(db, idempotency_key, request, {'changed_count': fresh['changed_count'], 'assigned_agent_ids': fresh['agent_ids'], 'installed': False, 'runtime_verified': False, 'permission_changes': []}, {'action': fresh['action'], 'organization_hash': fresh['organization_hash'], 'effects': fresh['effects']})

    def undo(self, org, version, expected_revision, idempotency_key):
        request = {'undo': version, 'revision': expected_revision, 'organization_hash': _org(org)[2]}
        with self._connection(True) as db:
            cached = self._cached(db, idempotency_key, request)
            if cached is not None:
                return cached
            self._cas(db, expected_revision)
            row = db.execute('SELECT body FROM events WHERE project=? AND version=?', (self.project_id, version)).fetchone()
            if row is None:
                raise CapabilityLibraryError('Versión no encontrada.')
            event = json.loads(row[0])
            if 'effects' not in event or event.get('organization_hash') != _org(org)[2]:
                raise CapabilityLibraryError('Esta versión no permite deshacer en la organización actual.')
            # Reject ABA edits too: equal current values do not erase later history.
            touched = {(e['agent_id'], e['item_id']) for e in event['effects']}
            for later in db.execute('SELECT body FROM events WHERE project=? AND version>?', (self.project_id, version)):
                if any((e['agent_id'], e['item_id']) in touched for e in json.loads(later[0]).get('effects', [])):
                    raise CapabilityLibraryError('Una edición posterior tocó esta asignación; deshacer primero esa edición.')
            effects = []
            for e in event['effects']:
                current = db.execute('SELECT active FROM assignments WHERE project=? AND agent=? AND item=?', (self.project_id, e['agent_id'], e['item_id'])).fetchone()
                if (None if current is None else bool(current[0])) != e['after']:
                    raise CapabilityLibraryError('Una edición posterior cambió esta asignación.')
                effects.append(dict(e, before=e['after'], after=e['before']))
            self._effects(db, effects)
            return self._finish(db, idempotency_key, request, {'changed_count': len(effects)}, {'action': 'undo', 'undo_version': version, 'organization_hash': _org(org)[2], 'effects': effects})

    def manifest_page(self, offset=0, limit=100, agent_ids=None):
        _page(offset, limit)
        where, args = 'project=?', [self.project_id]
        if agent_ids is not None:
            if not isinstance(agent_ids, (list, tuple, set)) or len(agent_ids) > 1000:
                raise CapabilityLibraryError('Roster de asignaciones inválido.')
            ids = sorted(set(_text(a, 200) for a in agent_ids))
            if ids:
                where += ' AND agent IN ('+','.join('?' for _ in ids)+')'
                args += ids
            else:
                where += ' AND 0'
        with self._connection() as db:
            rows = db.execute('SELECT agent,item,active FROM assignments WHERE '+where+' ORDER BY agent,item LIMIT ? OFFSET ?', args+[limit, offset]).fetchall()
            total = db.execute('SELECT COUNT(*) FROM assignments WHERE '+where, args).fetchone()[0]
            items = []
            for row in rows:
                body = json.loads(db.execute('SELECT body FROM items WHERE project=? AND id=?', (self.project_id, row['item'])).fetchone()[0])
                items.append({'agent_id': row['agent'], 'item_id': row['item'], 'kind': body['kind'], 'content_hash': body['content_hash'], 'active': bool(row['active']), 'assigned': True, 'installed': False, 'runtime_verified': False})
            return {'schema_version': 1, 'project_id': self.project_id, 'revision': self._revision(db), 'items': items, 'total': total, 'offset': offset, 'next_offset': offset+len(rows) if offset+len(rows)<total else None, 'permission_grants': []}

    def active_context(self, org, agent_id, budget_bytes=12000):
        """Exact default export readback; custom budgets are unpinned previews."""
        select_agents(org, {'mode': 'selected', 'agent_ids': [agent_id]})
        if type(budget_bytes) is not int or not 0 <= budget_bytes <= MAX_CONTEXT_BYTES:
            raise CapabilityLibraryError('Presupuesto de contexto inválido.')
        if budget_bytes == 12000 and 'config' in org and 'audit_assignments' in org and org.get('organization_id'):
            if __package__:
                from .agent_context import compile_agent_context
                from .capability_deployment import export_skillhub_library
            else:
                from agent_context import compile_agent_context
                from capability_deployment import export_skillhub_library
            snapshot = export_skillhub_library(self, org)
            return compile_agent_context(org, snapshot)['agents'][agent_id]
        if __package__:
            from .agent_context import compose_context
        else:
            from agent_context import compose_context
        with self._connection() as db:
            rows = db.execute('SELECT i.body FROM items i JOIN assignments a ON a.project=i.project AND a.item=i.id WHERE a.project=? AND a.agent=? AND a.active=1 ORDER BY i.id', (self.project_id, agent_id))
            items = [json.loads(row[0]) for row in rows]
        base = ''
        if 'config' in org and 'audit_assignments' in org:
            if __package__:
                from .core import _render_prompt
            else:
                from core import _render_prompt
            base = _render_prompt(next(a for a in org['agents'] if a['id'] == agent_id), org)
        result = compose_context(base, items, budget_bytes=budget_bytes)
        result['manifest_scope'] = 'live_library_preview_unpinned; export pins full snapshot hash'
        return result

    def recommend(self, org, selection, offset=0, limit=50):
        _page(offset, limit)
        selected = select_agents(org, selection)
        agents = [a for a in org['agents'] if a['id'] in selected]
        evidence = []
        for a in agents:
            for field in ('role', 'role_key', 'responsibilities', 'competency_gaps', 'proposed_skills'):
                evidence.append(_dump(a.get(field, '')))
        evidence += [_dump(g) for g in org.get('competency_gaps', []) if not g.get('agent_id') or g['agent_id'] in selected]
        tokens = set(re.findall(r'\w{3,}', ' '.join(evidence).casefold()))
        matches = []
        with self._connection() as db:
            for row in db.execute('SELECT body FROM items WHERE project=?', (self.project_id,)):
                item = json.loads(row[0])
                candidate_tokens = set(re.findall(r'\w{3,}', ' '.join([item['name'], item['description']]+item['tags']+item['role_evidence']).casefold()))
                overlap = sorted(tokens & candidate_tokens)
                if overlap:
                    matches.append({'item_id': item['id'], 'name': item['name'], 'kind': item['kind'], 'score': len(overlap), 'matched_evidence_terms': overlap, 'status': 'candidate_unverified', 'auto_install': False, 'tool_needs': item['tool_needs'], 'evidence_hash': _hash(evidence), 'source': item['provenance']})
        matches.sort(key=lambda x: (-x['score'], x['item_id']))
        return {'items': matches[offset:offset+limit], 'total': len(matches), 'next_offset': offset+limit if offset+limit<len(matches) else None, 'method': 'deterministic_declared_role_gap_overlap', 'llm_advisory_contract': {'advisory_only': True, 'requires_source_ids': True, 'may_install': False, 'may_grant_permissions': False, 'may_claim_runtime_verification': False}}
