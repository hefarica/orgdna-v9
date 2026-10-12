"""Ephemeral, opt-in loopback client for the OrgDNA native Cordis addon.

No discovery, browser-cookie reuse, config editing, process execution, or task
execution. A user-approved native pairing grants bounded read-only scopes.
"""
from __future__ import annotations
import copy
import hashlib
import http.client
import json
import re
import secrets
import threading
from urllib.parse import urlsplit
import time

PROTOCOL = 'orgdna-local-bridge/1'
SCOPES = frozenset({'cordis.capabilities.read', 'teams.profiles.read', 'teams.import.preview', 'agentteams.state.read'})
PACKAGE_NAMES = frozenset({'@deepseek-ai/dsh-tools', '@deepseek-ai/dsh-client-connection', 'dsh-agent-team-gui', '@nanmicoder/dsh-agent-teams'})
CAPABILITIES = frozenset({'profiles_read', 'import_preview', 'agentteams_state_read', 'cordis_capabilities_read', 'task_plan_submit', 'live_messages', 'realtime_events'})
CAPABILITY_SOURCES = frozenset({'agentTeamGui', 'agentteams.readonly_file', 'tools.schemas'})
MAX_RESPONSE = 2 * 1024 * 1024
SUPPORTED_DSH_LIBRARIES = frozenset({'0.2.0-rc.2', '0.2.1-alpha.1'})


class DSHConnectionError(ValueError):
    """Safe error text; never includes credentials, response bodies, or paths."""


class DSHConnectionManager:
    def __init__(self, *, timeout=3.0):
        self._timeout = min(max(float(timeout), 0.1), 10.0)
        self._lock = threading.RLock()
        self._port = None
        self._connection = None
        self._connection_port = None
        self._token = None
        self._secret_values = set()
        self._instance = None
        self._expires = 0
        self._state = self._disconnected('NOT_PAIRED')

    @staticmethod
    def _disconnected(reason):
        return {'status': 'DISCONNECTED', 'live_connection': False,
                'identity_verified': False, 'reason': reason,
                'protocol': PROTOCOL, 'scopes': [], 'capabilities': {},
                'read_only': True, 'checked_at': None}

    def _clear(self, reason):
        if self._connection:
            self._connection.close()
        self._connection = self._connection_port = None
        self._port = self._token = self._instance = None
        self._secret_values.clear()
        self._expires = 0
        self._state = self._disconnected(reason)

    @staticmethod
    def _port_number(port):
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise DSHConnectionError('Usa el puerto local entero mostrado por el addon de DSH (1024–65535).')
        return port

    def _request(self, path, payload, *, token=None, port=None):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if len(body) > 1024 * 1024:
            raise DSHConnectionError('La solicitud supera el límite local permitido.')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        # Fixed numeric IPv4 prevents DNS, SSRF, proxy forwarding and redirects.
        selected_port = port or self._port
        if self._connection is None or self._connection_port != selected_port:
            if self._connection:
                self._connection.close()
            self._connection = http.client.HTTPConnection('127.0.0.1', selected_port, timeout=self._timeout)
            self._connection_port = selected_port
        conn = self._connection
        try:
            conn.request('POST', path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read(MAX_RESPONSE + 1)
            if response.status != 200 or len(raw) > MAX_RESPONSE or 'application/json' not in (response.getheader('Content-Type') or ''):
                raise DSHConnectionError('DSH rechazó la solicitud local; vuelve a comprobar el permiso y la conexión.')
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get('ok') is not True or not isinstance(value.get('value'), dict):
                raise DSHConnectionError('Respuesta de conexión DSH no compatible.')
            return value['value']
        except DSHConnectionError:
            conn.close(); self._connection = self._connection_port = None
            raise
        except (OSError, ValueError, http.client.HTTPException):
            conn.close(); self._connection = self._connection_port = None
            raise DSHConnectionError('No se pudo verificar el addon local de DSH.') from None

    def _validate_handshake(self, value, nonce):
        if (value.get('protocol') != PROTOCOL or value.get('nonce') != nonce
                or value.get('owner_approved') is not True or value.get('read_only') is not True
                or value.get('permissions_acknowledged') is not True):
            raise DSHConnectionError('El handshake no demuestra el consentimiento de lectura local.')
        instance = value.get('instance_id')
        if not isinstance(instance, str) or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', instance):
            raise DSHConnectionError('La identidad de instancia DSH no es válida.')
        if self._instance and not secrets.compare_digest(instance, self._instance):
            raise DSHConnectionError('La instancia DSH cambió. Empareja de nuevo.')
        scopes = value.get('scopes')
        if not isinstance(scopes, list) or not scopes or not all(isinstance(s, str) and s in SCOPES for s in scopes):
            raise DSHConnectionError('El addon solicitó permisos distintos de los de lectura aprobados.')
        versions = value.get('versions')
        if not isinstance(versions, dict) or not isinstance(versions.get('@deepseek-ai/dsh-tools'), str) or versions.get('@deepseek-ai/dsh-tools') not in SUPPORTED_DSH_LIBRARIES or versions.get('@deepseek-ai/dsh-client-connection') != versions.get('@deepseek-ai/dsh-tools'):
            raise DSHConnectionError('La versión DSH no está cubierta por este adaptador verificado.')
        versions = {name: version for name, version in versions.items() if name in PACKAGE_NAMES and (version is None or isinstance(version, str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?', version))}
        caps = value.get('capabilities')
        if not isinstance(caps, dict) or not isinstance(caps.get('task_plan_submit'), dict) or caps['task_plan_submit'].get('available') is not False:
            raise DSHConnectionError('El addon no declara correctamente sus límites de ejecución.')
        safe_caps = {}
        for key in CAPABILITIES:
            cap = caps.get(key)
            if not isinstance(cap, dict) or not isinstance(cap.get('available'), bool):
                raise DSHConnectionError('El contrato de capacidades DSH no es válido.')
            source = cap.get('source')
            safe_caps[key] = {'available': cap['available'], 'source': source if isinstance(source, str) and source in CAPABILITY_SOURCES else None,
                              'reason': None if cap['available'] else 'Capacidad no disponible en la interfaz y versiones verificadas.'}
        if any(safe_caps[key]['available'] for key in ('task_plan_submit', 'live_messages', 'realtime_events')):
            raise DSHConnectionError('La conexión declara acciones fuera del alcance de lectura.')
        caps = safe_caps
        expires = value.get('expires_at')
        if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not time.time() < expires <= time.time() + 1805:
            raise DSHConnectionError('La sesión local ha caducado o tiene una duración no permitida.')
        # Never copy arbitrary server keys, tokens, paths or secrets into app state.
        self._instance, self._expires = instance, expires
        native_stage_url = value.get('native_stage_url')
        verified_stage_url = None
        if isinstance(native_stage_url, str) and value.get('native_stage_permission_separate') is True:
            try:
                parsed = urlsplit(native_stage_url)
                if parsed.scheme in ('http', 'https') and parsed.hostname in ('127.0.0.1', 'localhost', '::1') and not parsed.username and not parsed.password and parsed.path == '/api/orgdna-native-stage' and not parsed.query and not parsed.fragment and (parsed.port is None or 1 <= parsed.port <= 65535):
                    verified_stage_url = native_stage_url
            except ValueError:
                pass
        self._state = {'status': 'CONNECTED', 'live_connection': True, 'identity_verified': True,
                       'identity_scope': 'paired_native_addon_instance', 'runtime_session_identity_verified': False,
                       'instance_id': instance, 'protocol': PROTOCOL, 'versions': copy.deepcopy(versions),
                       'scopes': list(scopes), 'capabilities': copy.deepcopy(caps), 'read_only': True,
                       'permissions_acknowledged': True, 'owner_approved': True,
                       'runtime_compatibility': 'SOURCE_SEAMS_CHECKED_FULL_PLUGIN_COMBINATION_UNVERIFIED',
                       'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                       'expires_at': expires, 'reason': None, 'native_stage_url': verified_stage_url,
                       'native_stage_permission_separate': verified_stage_url is not None}

    def connect(self, port, pairing_code):
        with self._lock:
            port = self._port_number(port)
            if not isinstance(pairing_code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', pairing_code):
                raise DSHConnectionError('Usa el código efímero mostrado en la pantalla local de DSH.')
            # A new explicit attempt replaces the previous in-memory pairing.
            self.disconnect()
            nonce = secrets.token_urlsafe(24)
            try:
                value = self._request('/v1/pair', {'protocol': PROTOCOL, 'pairing_code': pairing_code, 'nonce': nonce}, port=port)
                token = value.get('session_token')
                if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
                    raise DSHConnectionError('El addon no devolvió una sesión efímera válida.')
                self._validate_handshake(value, nonce)
                self._port, self._token = port, token
                self._secret_values = {token, pairing_code}
                # Verify possession of the session immediately, not just pairing response.
                self._refresh()
            except DSHConnectionError:
                self._clear('PAIRING_NOT_VERIFIED')
                raise
            return copy.deepcopy(self._state)

    def _refresh(self):
        nonce = secrets.token_urlsafe(24)
        value = self._request('/v1/rpc', {'operation': 'handshake', 'nonce': nonce}, token=self._token)
        self._validate_handshake(value, nonce)

    def status(self, refresh=True):
        with self._lock:
            if self._token and time.time() >= self._expires:
                self._clear('SESSION_EXPIRED')
            if self._token and refresh:
                try:
                    self._refresh()
                except DSHConnectionError:
                    self._clear('CONNECTION_NOT_VERIFIED')
            result = copy.deepcopy(self._state)
            result['cached'] = not refresh
            return result

    def cached_status(self):
        return self.status(refresh=False)

    def disconnect(self):
        with self._lock:
            if self._token:
                try:
                    self._request('/v1/rpc', {'operation': 'disconnect'}, token=self._token)
                except DSHConnectionError:
                    pass
            self._clear('DISCONNECTED_BY_USER')
            return copy.deepcopy(self._state)

    def _sanitize(self, value, depth=0):
        if depth > 14:
            raise DSHConnectionError('La respuesta DSH excede la profundidad permitida.')
        sensitive_keys = {'password', 'passwd', 'secret', 'token', 'apikey', 'authorization', 'cookie', 'credentials',
                          'sessiontoken', 'pairingcode', 'accesstoken', 'refreshtoken', 'privatekey', 'clientsecret',
                          'idtoken', 'bearertoken', 'accesskey', 'secretkey', 'secretaccesskey'}
        if isinstance(value, dict):
            return {key: self._sanitize(item, depth + 1) for key, item in value.items()
                    if re.sub(r'[^a-z0-9]', '', key.lower()) not in sensitive_keys}
        if isinstance(value, list):
            return [self._sanitize(item, depth + 1) for item in value]
        if isinstance(value, str):
            for secret in self._secret_values:
                value = value.replace(secret, '[REDACTED]')
            return re.sub(r'\b(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~-]{12,})', '[REDACTED]', value)
        return value

    def _read(self, operation, scope, payload=None):
        with self._lock:
            state = self.status()
            if not state['live_connection'] or scope not in state['scopes']:
                raise DSHConnectionError('La conexión o esta capacidad de lectura no está disponible.')
            try:
                return self._sanitize(self._request('/v1/rpc', {'operation': operation, **(payload or {})}, token=self._token))
            except DSHConnectionError:
                self._clear('READ_NOT_VERIFIED')
                raise

    def read_capabilities(self):
        return self._read('capabilities', 'cordis.capabilities.read')

    def read_profiles(self):
        return self._read('profiles', 'teams.profiles.read')

    def read_team(self, team_name=''):
        if not isinstance(team_name, str) or len(team_name) > 200 or any(ord(c) < 32 for c in team_name):
            raise DSHConnectionError('El nombre del equipo no es válido.')
        return self._read('team_state', 'agentteams.state.read', {'team_name': team_name})

    def preview_import(self, document):
        if not isinstance(document, dict):
            raise DSHConnectionError('La vista previa requiere un documento JSON válido.')
        return self._read('import_preview', 'teams.import.preview', {'document': document})

    def diagnose(self):
        """Collect real read-only pairing evidence; never generates a greeting or runs a model."""
        with self._lock:
            state = self.status()
            report = {'status': 'READINESS_INCOMPLETE', 'checked_at': state.get('checked_at'),
                      'connection': state, 'observations': {}, 'writes_performed': False,
                      'model_calls_performed': False, 'end_to_end_orchestration_verified': False,
                      'agentteams_uses_teams_ssot': 'UNVERIFIED',
                      'native_agent_wakeup_verified': False, 'live_session_bindings_verified': False}
            if not state['live_connection']:
                report['status'] = 'DISCONNECTED'
                return report
            for scope, operation, key in [('teams.profiles.read', self.read_profiles, 'teams'),
                                           ('agentteams.state.read', self.read_team, 'agentteams'),
                                           ('cordis.capabilities.read', self.read_capabilities, 'cordis')]:
                if scope not in state['scopes']:
                    report['observations'][key] = {'available': False}
                    continue
                try:
                    value = operation()
                except DSHConnectionError:
                    report['connection'] = self.cached_status()
                    report['status'] = 'READ_FAILED'
                    return report
                if key == 'teams':
                    stable = {'agents': value.get('agents', []), 'squads': value.get('squads', [])}
                    report['observations'][key] = {'available': True, 'source': value.get('source'),
                        'profile_count': len(stable['agents']), 'squad_count': len(stable['squads']),
                        'definition_sha256': hashlib.sha256(json.dumps(stable, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                        'definition_ids_are_session_ids': False}
                elif key == 'agentteams':
                    report['observations'][key] = {'available': True, 'source': value.get('source'),
                        'teams': [{'id': row.get('id'), 'member_count_including_captain': len(row.get('members', [])) + 1,
                                   'task_count': len(row.get('tasks', [])), 'phase': row.get('phase'),
                                   'halted': row.get('halted') is True} for row in value.get('teams', [])],
                        'runtime_session_identity_verified': False}
                else:
                    report['observations'][key] = {'available': True, 'source': value.get('source'),
                        'registered_tool_count': len(value.get('tools', [])), 'registry_is_permission_grant': False}
            report['connection'] = self.cached_status()
            return report

    def prepare_task_plan(self, plan):
        if not isinstance(plan, dict):
            raise DSHConnectionError('El plan debe ser un objeto JSON.')
        encoded = json.dumps(plan, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if len(encoded) > 256 * 1024:
            raise DSHConnectionError('El plan es demasiado grande.')
        return {'status': 'BLOCKED_CAPABILITY', 'dispatch_supported': False,
                'plan_sha256': hashlib.sha256(encoded).hexdigest(), 'approval_required': True,
                'reason': 'No hay una interfaz nativa verificada que envíe planes al equipo existente preservando las aprobaciones de DSH.',
                'creates_team': False, 'restarts_team': False}

    def submit_task_plan(self, plan, confirmation_hash=None):
        raise DSHConnectionError('CAPABILITY_UNAVAILABLE: el envío de planes no está habilitado en esta versión.')
