"""Opt-in suite -> DSH coordinator, with no process termination or installation.

Launcher success and TCP are observations, not authentication. Each approved plan
can start the existing reviewed launcher once, always in --reuse mode. Native
addon pairing remains a separate explicit permission and lives only in memory.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re
import threading
import time
import uuid

if __package__:
    from .dsh_connection import DSHConnectionError, DSHConnectionManager
    from .dsh_launcher import LauncherError
else:
    from dsh_connection import DSHConnectionError, DSHConnectionManager
    from dsh_launcher import LauncherError

ACTIONS = frozenset({'dsh-harness-prepare', 'dsh-harness-start', 'dsh-harness-check',
                     'dsh-harness-pair', 'dsh-harness-verify', 'dsh-harness-clear'})


class HarnessError(ValueError):
    """Only fixed messages; never include child output or pairing credentials."""


def definition_hash(profiles):
    agents, squads = profiles.get('agents'), profiles.get('squads')
    if not isinstance(agents, list) or not isinstance(squads, list):
        raise HarnessError('La lectura del roster no cumple el contrato de perfiles.')
    if any(not isinstance(row, dict) or not isinstance(row.get('id'), str) for row in agents + squads):
        raise HarnessError('El roster contiene identidades de definición no válidas.')
    encoded = json.dumps({'agents': agents, 'squads': squads}, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class DSHHarness:
    def __init__(self, launcher, connection=None, *, clock=time.monotonic):
        self.launcher = launcher
        self.connection = connection if connection is not None else DSHConnectionManager()
        self._clock = clock
        self._lock = threading.RLock()
        self._deadline = None
        self._consumed = set()
        self._state = self._empty()

    @staticmethod
    def _empty():
        return {'status': 'NOT_PREPARED', 'plan': None, 'diagnostics': [],
                'connection': None, 'readback': None, 'launcher': None,
                'live_connection': False, 'native_execution_verified': False,
                'automatic_installation_available': False,
                'secrets_persisted': False, 'config_files_modified': 0,
                'start_attempted': False, 'wait_remaining_seconds': 0}

    def public(self):
        with self._lock:
            # No network in rendering. Expiration/disconnect invalidates the
            # green readback even if no explicit polling action was requested.
            cached = self.connection.cached_status()
            self._state['connection'] = cached
            self._state['live_connection'] = cached.get('live_connection') is True
            if not self._state['live_connection'] and self._state['readback'] is not None:
                self._state['readback'] = None
                self._state['status'] = 'PAIRING_REQUIRED'
            return copy.deepcopy(self._state)

    def _bound_plan(self, body):
        plan = self._state['plan']
        if not plan or body.get('plan_sha256') != plan['plan_sha256']:
            raise HarnessError('Revisa y confirma el hash del plan actual del harness.')
        return plan

    def _launcher_body(self, plan, body=None):
        return {**(body or {}), 'plan_sha256': plan['launcher_plan_sha256']}

    def _health(self, plan):
        result = self.launcher.apply('dsh-launch-health', self._launcher_body(plan))
        self._state['launcher'] = result
        return result.get('health', [])

    def _connection_state(self):
        state = self.connection.status()
        self._state['connection'] = state
        self._state['live_connection'] = state.get('live_connection') is True
        return state

    def prepare(self, body):
        if self._state['status'] == 'WAITING_RUNTIME':
            raise HarnessError('Hay un inicio pendiente. Comprueba su resultado antes de crear otro plan.')
        # Never accept restart, legacy flags, injected arguments, or caller claims
        # about runtime readiness/overlay support as authority.
        if body.get('operation', 'reuse') != 'reuse' or body.get('legacy_stop') is True:
            raise HarnessError('Este harness sólo permite reutilizar o iniciar con --reuse; nunca reiniciar.')
        timeout = body.get('wait_seconds', 30)
        if type(timeout) not in (int, float) or not 1 <= timeout <= 120:
            raise HarnessError('La espera debe ser de 1 a 120 segundos.')
        bridge_port = body.get('bridge_port')
        if bridge_port is not None:
            DSHConnectionManager._port_number(bridge_port)
        expected = body.get('expected_definition_sha256')
        if expected is not None and (not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
            raise HarnessError('El hash esperado del roster debe ser SHA-256 hexadecimal.')
        inputs = {key: body[key] for key in ('script_path', 'exe_path', 'ports', 'backup_paths') if key in body}
        inputs['operation'] = 'reuse'
        launch = self.launcher.apply('dsh-launch-inspect', inputs)
        launcher_plan = launch['plan']
        plan = {'operation_id': uuid.uuid4().hex, 'operation': 'reuse',
                'launcher_plan_sha256': launcher_plan['plan_sha256'],
                'launcher_plan': copy.deepcopy(launcher_plan),
                'bridge_port': bridge_port, 'wait_seconds': timeout,
                'expected_definition_sha256': expected,
                'steps': ['RECHECK_EXACT_PLAN', 'PRESERVE_OCCUPIED_PORTS',
                          'BACKUP_IF_START_NEEDED_AND_APPROVED', 'START_ONCE_WITH_REUSE_IF_STOPPED',
                          'BOUNDED_READINESS_CHECK', 'EXPLICIT_NATIVE_PAIRING',
                          'AUTHENTICATED_HANDSHAKE', 'DOUBLE_ROSTER_READBACK_AND_HASH'],
                'approval_required': True, 'native_pairing_separate': True,
                'installs_plugins': False, 'changes_profile': False,
                'terminates_processes': False, 'creates_persistent_access': False}
        plan['plan_sha256'] = hashlib.sha256(json.dumps(plan, sort_keys=True, allow_nan=False).encode()).hexdigest()
        self._state = self._empty()
        self._deadline = None
        self._state.update(plan=plan, launcher=launch)
        self._state['diagnostics'] = [
            'El puerto TCP y exit 0 no prueban conexión ni identidad DSH.',
            'El launcher original 1.1.1 no preserva --patch al arrancar. Este harness no lo modifica ni inventa extraArgs.',
            'La activación aditiva requiere versión instalada y soporte overlay verificados en el runtime local, namespace propio y revisión de permisos en PluginManager.',
            'Si falta el addon, actívalo mediante el flujo nativo aprobado y usa su pantalla local de emparejamiento. No se leerán cookies, tokens, logs ni historial.',
            'La suite ya está activa cuando este endpoint responde; su arranque/reutilización corresponde a engine.launcher.']
        state = self._connection_state()
        health = self._health(plan)
        if state.get('live_connection'):
            self._state['status'] = 'CONNECTED_NEEDS_READBACK'
        elif any(row.get('tcp_listening') for row in health):
            self._state['status'] = 'EXISTING_LISTENER_PAIRING_REQUIRED'
        elif launch.get('execution_available'):
            self._state['status'] = 'AWAITING_START_APPROVAL'
        else:
            self._state['status'] = 'LOCAL_PREREQUISITES_REQUIRED'
        return self.public()

    def start(self, body):
        plan = self._bound_plan(body)
        if plan['operation_id'] in self._consumed:
            return self.check({})  # Uncertain/repeated click never launches again.
        if body.get('start_confirmed') is not True:
            raise HarnessError('Aprueba este plan exacto antes de iniciar DSH.')
        if self._connection_state().get('live_connection'):
            self._state['status'] = 'CONNECTED_NEEDS_READBACK'
            return self.public()
        if any(row.get('tcp_listening') for row in self._health(plan)):
            self._state['status'] = 'EXISTING_LISTENER_PAIRING_REQUIRED'
            return self.public()  # An unrelated listener is never killed or replaced.
        launch = self._state['launcher']
        if not launch.get('execution_available'):
            self._state['status'] = 'LOCAL_PREREQUISITES_REQUIRED'
            return self.public()
        if not all(body.get(key) is True for key in ('execute_confirmed', 'interruption_acknowledged',
                                                     'preservation_unverified_acknowledged')):
            raise HarnessError('Falta aprobar ejecución y riesgos del launcher original.')
        if not launch.get('backup'):
            if body.get('backup_confirmed') is not True:
                raise HarnessError('Autoriza el respaldo de las rutas exactas antes del inicio.')
            self.launcher.apply('dsh-launch-backup', self._launcher_body(plan, body))
        # Recheck after backup: no launcher call at all if a listener appeared.
        if any(row.get('tcp_listening') for row in self._health(plan)):
            self._state['status'] = 'EXISTING_LISTENER_PAIRING_REQUIRED'
            return self.public()
        self._consumed.add(plan['operation_id'])
        self._state['start_attempted'] = True
        try:
            self._state['launcher'] = self.launcher.apply('dsh-launch-execute', self._launcher_body(plan, body))
        except LauncherError:
            self._state['status'] = 'START_FAILED_NO_RETRY'
            raise
        except Exception:
            # Even an unexpected failure can happen after process creation.
            # Keep the plan consumed and expose neither the exception nor output.
            self._state['status'] = 'START_FAILED_NO_RETRY'
            raise HarnessError('El inicio no pudo verificarse; este plan no se reintentará automáticamente.') from None
        self._deadline = self._clock() + plan['wait_seconds']
        self._state['status'] = 'WAITING_RUNTIME'
        self._state['wait_remaining_seconds'] = plan['wait_seconds']
        return self.public()

    def check(self, body=None):
        state = self._connection_state()
        if state.get('live_connection'):
            self._state['status'] = 'CONNECTED_NEEDS_READBACK' if not self._state['readback'] else 'READBACK_RECHECK_REQUIRED'
            return self.public()
        self._state['readback'] = None
        plan = self._state['plan']
        if not plan:
            return self.public()
        health = self._health(plan)
        if any(row.get('tcp_listening') for row in health):
            self._state['status'] = 'EXISTING_LISTENER_PAIRING_REQUIRED'
            self._state['wait_remaining_seconds'] = 0
        elif self._deadline is not None:
            remaining = max(0, self._deadline - self._clock())
            self._state['wait_remaining_seconds'] = round(remaining, 2)
            run = self._state['launcher'].get('run') or {}
            if run.get('status') == 'FAILED_TO_START' or (run.get('status') == 'EXITED' and run.get('exit_code') != 0):
                self._state['status'] = 'START_FAILED_NO_RETRY'
            elif remaining == 0:
                self._state['status'] = 'START_TIMEOUT_NO_RETRY'
            else:
                self._state['status'] = 'WAITING_RUNTIME'
        return self.public()

    def pair(self, body):
        plan = self._bound_plan(body)
        if body.get('pair_confirmed') is not True:
            raise HarnessError('Aprueba el emparejamiento de lectura mostrado en DSH por separado.')
        port = body.get('bridge_port', plan.get('bridge_port'))
        if plan.get('bridge_port') is not None and port != plan['bridge_port']:
            raise HarnessError('El puerto de emparejamiento cambió; prepara un nuevo plan.')
        try:
            self.connection.connect(port, body.get('pairing_code'))
            return self.verify(body)
        except DSHConnectionError:
            self._state.update(status='PAIRING_FAILED', live_connection=False, readback=None,
                               connection=self.connection.cached_status())
            raise

    def verify(self, body=None):
        body = body or {}
        if not self._connection_state().get('live_connection'):
            self._state.update(status='PAIRING_REQUIRED', readback=None)
            return self.public()
        try:
            report = self.connection.diagnose()
            first = self.connection.read_profiles()
            second = self.connection.read_profiles()
            first_hash, second_hash = definition_hash(first), definition_hash(second)
            expected = (self._state['plan'] or {}).get('expected_definition_sha256')
            final_state = self._connection_state()
            stable = first_hash == second_hash
            expected_matches = None if expected is None else second_hash == expected
            self._state['readback'] = {'profile_count': len(second['agents']), 'squad_count': len(second['squads']),
                'definition_sha256': second_hash, 'double_readback_matches': stable,
                'expected_definition_matches': expected_matches, 'diagnosis': report,
                'definition_ids_are_session_ids': False, 'runtime_session_identity_verified': False,
                'native_execution_verified': False, 'mutations_performed': False}
            self._state['status'] = ('READ_ONLY_VERIFIED' if final_state.get('live_connection') and stable and expected_matches is not False
                                     else 'READBACK_MISMATCH_OR_CONNECTION_LOST')
        except (DSHConnectionError, HarnessError, ValueError, TypeError):
            self._state.update(status='READBACK_FAILED', readback=None)
            self._connection_state()
            raise HarnessError('No se verificó el roster mediante lectura autenticada; no se ejecutó ninguna tarea.') from None
        return self.public()

    def apply(self, action, body=None):
        body = body or {}
        if not isinstance(body, dict):
            raise HarnessError('La solicitud del harness debe ser un objeto JSON.')
        with self._lock:
            if action == 'dsh-harness-prepare': return self.prepare(body)
            if action == 'dsh-harness-start': return self.start(body)
            if action == 'dsh-harness-check': return self.check(body)
            if action == 'dsh-harness-pair': return self.pair(body)
            if action == 'dsh-harness-verify': return self.verify(body)
            if action == 'dsh-harness-clear':
                if self._state['status'] == 'WAITING_RUNTIME':
                    raise HarnessError('No se puede ocultar un inicio pendiente; comprueba su resultado.')
                self._state = self._empty()
                self._deadline = None
                return self.public()  # Does not terminate DSH or revoke separate pairing.
            raise HarnessError('Acción de harness no reconocida.')
