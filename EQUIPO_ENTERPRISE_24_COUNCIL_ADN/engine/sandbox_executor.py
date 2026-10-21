"""Sandbox Executor (P1 GenTeam): ejecucion aislada por agente bajo puertas + entrega al canal.

Port REA de OpenBMB/ChatDev@a2ea4a2 (Apache-2.0): semantica de
runtime/node/executor/python_executor.py, reescrita bajo las puertas de
engine/policy_engine.py. Vectores: test_code_execution_security.py,
test_session_workspace_security.py, test_attachment_boundary_security.py.

ESTO NO ES UN SANDBOX DEL SISTEMA OPERATIVO (doctrina de engine/evaluation_runs.py:1-7,
'sandboxed': False en :76 y :173): el codigo corre como subprocess del interprete del
usuario y, por tanto, con sus permisos de lectura de disco. El aislamiento que SI provee
es el que el fuente probaba con sus suites de seguridad:

  1. GATE ANTES DE TODO (port de I1/I2, utils/code_execution.py): NINGUNA ejecucion sin
     que una puerta `require_human_approval` del policy_engine este aprobada. El
     interruptor del fuente (una variable de entorno del servidor) se REESCRIBE como la
     accion `write_file` del contrato v1: toda ejecucion exige escribir el script en el
     workspace, y esa escritura levanta la puerta 'write' bajo la politica por defecto
     (engine/policy_engine.py:115-128, GATES en :86). Sin aprobacion valida ->
     SandboxPolicyError con el NOMBRE de la puerta, y no existe workspace, ni script, ni
     proceso (vectores python_node_env_no_puede_habilitar y
     processor_deshabilitado_no_muta_fs). La aprobacion es un registro declarativo
     `one_shot` atado por `scope_hash` al binomio (politica, accion); NADA que venga del
     agente (env del hijo, argumentos, codigo) puede habilitar la ejecucion.
  2. WORKSPACE DEDICADO por agente POR EJECUCION bajo data/ (data/work/<agente>/<run>/):
     directorio temporal limpiable via cleanup(). El fuente persistia el workspace con
     contador `_run-N`; el destino decide workspace fresco por corrida (cuaderno §5:
     decision explicita, no heredada).
  3. SUBPROCESS con timeout OBLIGATORIO (1..300 s; default 60 s, valor de referencia del
     fuente entity/configs/node/python_runner.py), argv-lista con shell=False (port de
     I9), env MINIMO (convencion del destino: engine/evaluation_runs.py:372-374, sin
     claves heredadas), y captura de stdout/stderr ACOTADA por tope de bytes con kill al
     superarlo (el fuente NO truncaba salida: el cuaderno §4 exige que el port anada su
     propio tope — mejora consciente, no paridad).
  4. ENTREGA (cierra P1): al terminar, el resultado se firma como artefacto 'report' via
     engine/artifact_factory.py (sha256 + recibo, result_outcome completed/failed,
     consent_ref = scope_hash de la aprobacion) y se devuelve al canal via
     engine/team_channel.py: evidencia (record_evidence), mensaje dirigido AL DESTINATARIO
     QUE ASIGNO (actor de la tarea o receptor explicito) y, si habia tarea,
     claim + submit con la evidencia firmada.
  5. BORDES del fuente portados como vectores (docs/rea/chatdev_vectors.json):
     timeout vencido (exit_code del proceso + timed_out=True distinguible de crash),
     codigo con error (resultado estructurado con marcador, NO excepcion), salida enorme
     (acotada + output_truncated + kill), ruta que intenta escapar del workspace
     (componente-unico sin / \\ : ni controles, '.'/'..'/blank Rechazados: port de I4/I7,
     utils/workspace_paths.py::validate_path_component).

Que NO hace, por diseno:

  * no ejecuta NADA si la decision es deny o require sin aprobacion honrada: la
    aplicacion queda inerte salvo aprobacion explicita (politica por defecto: las ocho
    puertas en require_human_approval);
  * no toca ni relaja ninguna puerta del policy_engine: solo llama a evaluate()/scope_hash()
    y rechaza lo que el motor no autoriza (incluida una aprobacion de otra puerta, de otro
    alcance, ya consumida por el runtime llamador, o con reclamos de autenticacion);
  * no parsea mensajes ni cercas ```python```: la entrada `code` es codigo explicito del
    llamador (divergencia declarada: _extract_code no se porta; el codigo vacio se
    rechaza como error de validacion ANTES de la puerta);
  * no mata arboles de procesos en Windows (los Job Objects de evaluation_runs no se
    portan): el kill alcanza al hijo directo; declarado como limite;
  * no consume la aprobacion one_shot (el policy_engine la detecta, no la consume:
    policy_engine.py:26-27); el runtime llamador declara los alcances consumidos;
  * no persiste ningun ledger: artefacto en disco bajo la raiz declarada de la fabrica,
    resto en memoria (decision A-1 de artifact_factory).

Procedencia (fuente -> destino):

  python_executor.py::execute (orden gate->workspace->write->spawn->capture)  -> SandboxExecutor.execute
  python_executor.py::_run_process (timeout parcial, decode replace)          -> _run_bounded + timed_out
  python_executor.py::_write_script_file (nombre elegido por el sistema)      -> script '<agente>.py'
  python_executor.py::_build_failure_message (marcador + exit_code)           -> EXECUTION_FAILED_MARKER
  entity/configs/node/python_runner.py (timeout int>0, default 60)            -> validacion de timeout
  utils/code_execution.py::require_unsafe_code_execution (I1/I2)              -> _authorize (puerta 'write')
  utils/workspace_paths.py::validate_path_component (I4/I7)                   -> validate_component
  utils/exceptions.py (SecurityError/ValidationError distinguibles)           -> SandboxPolicyError/SandboxConfigError
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

try:  # importacion como paquete del motor (patron de engine/policy_engine.py:70-73)
    from . import policy_engine as pe
    from . import team_channel as tc
    from .artifact_factory import ArtifactFactory, ArtifactFactoryError
except ImportError:  # raiz de la suite en sys.path
    import policy_engine as pe
    import team_channel as tc
    from artifact_factory import ArtifactFactory, ArtifactFactoryError

#: Default del fuente para el timeout del ejecutor (python_runner.py, citado como hecho).
DEFAULT_TIMEOUT_SECONDS = 60
MAX_TIMEOUT_SECONDS = 300
#: Topes de salida: mismos limites declarados por engine/evaluation_runs.py:133-134.
DEFAULT_MAX_OUTPUT_BYTES = 65536
MIN_MAX_OUTPUT_BYTES = 1024
MAX_MAX_OUTPUT_BYTES = 262144

#: Raiz de datos por defecto del repo (no existe todavia: se crea recien tras la puerta).
DEFAULT_DATA_ROOT = Path(__file__).resolve().parent.parent / 'data'
WORK_ROOT_NAME = 'work'
ARTIFACTS_ROOT_NAME = 'artifacts'

#: Honesto como evaluation_runs: esto NO aisla del sistema operativo.
OS_ISOLATION_NOTE = ('ninguna: subprocess del interprete del usuario con timeout, env '
                     'minimo y workspace dedicado; no es un sandbox del sistema operativo')

#: Port del marcador estable '==CODE EXECUTION FAILED==' del fuente.
EXECUTION_FAILED_MARKER = '==SANDBOX EXECUTION FAILED=='
TIMEOUT_MESSAGE = 'El script no termino dentro de {timeout}s'
OUTPUT_OVERFLOW_MESSAGE = ('La salida supero el tope de {limit} bytes y el proceso fue '
                           'terminado (output_limit_exceeded)')
NO_CODE_MESSAGE = 'No executable code segment found: el codigo recibido esta vacio'

#: Port de validate_path_component (I4): componente-unico sin separadores, drives ni controles.
_COMPONENT_FORBIDDEN_RE = re.compile(r'[/\\:\x00-\x1f\x7f]')
#: Segmento admisible para nombres de artefacto (artifact_factory.NAME_PATTERN es minusculas).
_SLUG_RE = re.compile(r'[^a-z0-9._-]')

RUN_STATUSES = ('completed', 'failed', 'timeout')
TASK_CLAIMABLE = ('open', 'blocked', 'rejected')  # team_channel.CLAIMABLE_FROM


class SandboxPolicyError(Exception):
    """La puerta humana no esta aprobada (o la politica deniega): NADA se ejecuto.

    `gate` lleva el nombre de la puerta que exige aprobacion ('write' por defecto)
    o None cuando la politica deniega sin puerta. Port distinguible de
    utils/exceptions.py::SecurityError.
    """

    def __init__(self, message, gate=None, decision=None):
        super().__init__(message)
        self.gate = gate
        self.decision = copy.deepcopy(decision) if decision is not None else None


class SandboxConfigError(ValueError):
    """Entrada invalida (agente, codigo, timeout, tope, tarea/receptor): nada se ejecuto.

    Port distinguible de utils/exceptions.py::ValidationError.
    """


def validate_component(value, field):
    """Valida un componente unico de ruta (port de I4/I7: validate_path_component).

    Rechaza: no-texto, vacio/solo espacios, separadores (/ y \\), unidad de disco (:),
    caracteres de control y NUL, '.' y '..'. Un componente valido jamas escapa del
    workspace por nombre.
    """
    if not isinstance(value, str):
        raise SandboxConfigError(f'{field}: se requiere texto.')
    trimmed = value.strip()
    if not trimmed:
        raise SandboxConfigError(f'{field}: vacio o solo espacios.')
    if trimmed in ('.', '..'):
        raise SandboxConfigError(f"{field}: '{trimmed}' no es un componente admisible.")
    if _COMPONENT_FORBIDDEN_RE.search(trimmed):
        raise SandboxConfigError(f'{field}: {value!r} contiene separadores, unidad de '
                                 'disco o caracteres de control (posible escape del '
                                 'workspace).')
    return trimmed


def _clip(text, limit):
    """Recorta un texto a `limit` caracteres marcando el corte (hallazgos de reporte)."""
    if len(text) <= limit:
        return text
    return text[:limit] + f'…[recortado, {len(text)} caracteres totales]'


class SandboxExecutor:
    """Ejecutor aislado por agente: puerta -> workspace -> script -> subprocess acotado.

    `policy` es una instancia `pe.Policy` o su dict (contrato v1). `approver` es un
    callable EN MEMORIA `approver(gate=..., action=..., expected_scope_hash=..., 
    decision=...) -> registro de aprobacion | None`: cuando la puerta exige aprobacion,
    el ejecutor se la consulta UNA vez; None significa que el aprobador no autoriza y el
    run muere sin ejecutar nada. Sin `approver` configurado, toda puerta que se levante
    bloquea (inercia por defecto). `data_root`localiza workspaces (`work/`) y artefactos
    (`artifacts/`); por defecto `data/` del repo.
    """

    def __init__(self, policy, *, data_root=None, approver=None, clock=None):
        if isinstance(policy, pe.Policy):
            self._policy = policy
        elif isinstance(policy, dict):
            self._policy = pe.Policy.from_dict(policy)
        else:
            raise SandboxConfigError('policy: se requiere una instancia Policy o su dict v1.')
        if approver is not None and not callable(approver):
            raise SandboxConfigError('approver: se requiere callable o None.')
        self._approver = approver
        self._clock = clock if clock is not None else time.time
        self._data_root = Path(data_root).expanduser().resolve() if data_root is not None \
            else DEFAULT_DATA_ROOT.resolve()
        # La fabrica valida su raiz declarada (check_declared_root) sin escribir nada:
        # la primera mutacion de disco ocurre recien en write(), ya tras la puerta.
        self._factory = ArtifactFactory(self._data_root / ARTIFACTS_ROOT_NAME)

    # ------------------------------------------------------------- validacion

    def _validated(self, agent_id, code, timeout_seconds, max_output_bytes):
        agent = validate_component(agent_id, 'agent_id')
        if not isinstance(code, str) or not code.strip():
            # Divergencia declarada: la entrada es codigo explicito, no un mensaje;
            # el borde 'sin segmento de codigo' del fuente se rechaza por validacion.
            raise SandboxConfigError('code: ' + NO_CODE_MESSAGE + '.')
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) \
                or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise SandboxConfigError('timeout_seconds: entero entre 1 y '
                                     f'{MAX_TIMEOUT_SECONDS} (obligatorio).')
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) \
                or not MIN_MAX_OUTPUT_BYTES <= max_output_bytes <= MAX_MAX_OUTPUT_BYTES:
            raise SandboxConfigError('max_output_bytes: entero entre '
                                     f'{MIN_MAX_OUTPUT_BYTES} y {MAX_MAX_OUTPUT_BYTES}.')
        return agent

    def _resolve_delivery(self, channel, agent_id, recipient, task_id):
        """Valida canal/receptor/tarea ANTES de la puerta (resolve no muta nada)."""
        if channel is None:
            if recipient is not None or task_id is not None:
                raise SandboxConfigError('recipient/task_id exigen un canal (channel=None).')
            return None, None, None
        if not isinstance(channel, tc.TeamChannel):
            raise SandboxConfigError('channel: se requiere un TeamChannel.')
        try:
            member = channel.resolve(agent_id)
        except tc.ChannelError as error:
            raise SandboxConfigError(f'agent_id: {error}') from None
        task = None
        if task_id is not None:
            if not isinstance(task_id, str):
                raise SandboxConfigError('task_id: se requiere texto.')
            rows = [row for row in channel.ledger_view()['tasks'] if row['id'] == task_id]
            if not rows:
                raise SandboxConfigError(f'unknown_task: no existe la tarea {task_id!r}.')
            task = rows[0]
            if task['owner_member_id'] != member.member_id:
                raise SandboxConfigError('task_id: solo el dueno asignado puede ejecutar '
                                         'y entregar esta tarea.')
        if recipient is not None:
            target_ref = recipient
        elif task is not None:
            target_ref = task['actor']          # entrega al destinatario que asigno
        else:
            raise SandboxConfigError('recipient: requerido para entregar al canal '
                                     '(o pasa task_id para derivarlo del asignador).')
        try:
            target = channel.resolve(target_ref)
        except tc.ChannelError as error:
            raise SandboxConfigError(f'recipient: {error}') from None
        return member, target, task

    # ---------------------------------------------------------------- puerta

    def _authorize(self, action):
        """Port de I1/I2: decide contra el policy_engine ANTES de tocar el filesystem.

        Devuelve (decision_final, aprobacion_usada). Toda salida que no sea allow
        lanza SandboxPolicyError con el nombre de la puerta: no hay ruta silenciosa.
        """
        scope_hash = self._policy.scope_hash(action)
        action['scope_hash'] = scope_hash
        decision = pe.evaluate(self._policy, action)
        if decision['decision'] == pe.DECISION_DENY:
            raise SandboxPolicyError(
                "deny: la politica deniega esta ejecucion (%s)" % decision['reason'],
                gate=decision['gate'], decision=decision)
        if decision['decision'] == pe.DECISION_ALLOW:
            return decision, None
        # require_human_approval: la puerta exige registro declarativo one_shot.
        gate = decision['gate']
        if self._approver is None:
            raise SandboxPolicyError(
                "gate '%s': requiere aprobacion humana y no hay aprobador configurado; "
                'no se ejecuta nada (app inerte salvo aprobacion explicita).' % gate,
                gate=gate, decision=decision)
        approval = self._approver(gate=gate, action=copy.deepcopy(action),
                                  expected_scope_hash=scope_hash,
                                  decision=copy.deepcopy(decision))
        if approval is None:
            raise SandboxPolicyError(
                "gate '%s': el aprobador no autorizo la ejecucion; no se ejecuta nada." % gate,
                gate=gate, decision=decision)
        final = pe.evaluate(self._policy, action, approval=approval)
        if final['decision'] != pe.DECISION_ALLOW:
            raise SandboxPolicyError(
                "gate '%s': la aprobacion presentada no autoriza esta ejecucion (%s)."
                % (gate, final['reason']), gate=gate, decision=final)
        return final, approval

    # ------------------------------------------------------------- subprocess

    @staticmethod
    def _stop(process):
        """Kill del hijo: grupo en POSIX (port del killpg del fuente), directo en Windows."""
        try:
            if os.name == 'posix':
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except (ProcessLookupError, OSError, ValueError):
            pass

    def _run_bounded(self, argv, cwd, timeout_seconds, max_output_bytes):
        """Spawn con captura acotada (port de _run_process + tope propio del destino).

        Lectores en hilos con tope de bytes COMBINADO y kill al superarlo (patron del
        destino en engine/evaluation_runs.py:350-364); decode con errors='replace'
        (eleccion del ejecutor del fuente; el procesador usaba 'ignore', descartada).
        """
        env = {}
        if os.name == 'nt' and os.environ.get('SystemRoot'):
            env['SystemRoot'] = os.environ['SystemRoot']   # sin claves heredadas (:372-374)
        process = subprocess.Popen(argv, cwd=str(cwd), env=env, shell=False,  # I9
                                   stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=(os.name == 'posix'))
        buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        counts = {'stdout': 0, 'stderr': 0}
        lock = threading.Lock()
        overflow = threading.Event()

        def reader(stream, name):
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    with lock:
                        counts[name] += len(chunk)
                        left = max_output_bytes - sum(len(buf) for buf in buffers.values())
                        buffers[name].extend(chunk[:max(0, left)])
                        if sum(counts.values()) > max_output_bytes:
                            overflow.set()
                            break
            finally:
                stream.close()

        readers = [threading.Thread(target=reader, args=(process.stdout, 'stdout'), daemon=True),
                   threading.Thread(target=reader, args=(process.stderr, 'stderr'), daemon=True)]
        for worker in readers:
            worker.start()
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        while process.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                self._stop(process)
                break
            if overflow.is_set():
                self._stop(process)
                break
            time.sleep(0.02)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._stop(process)
        self._stop(process)
        for worker in readers:
            worker.join(timeout=1)
        with lock:
            return {'exit_code': process.returncode,
                    'timed_out': timed_out,
                    'output_truncated': overflow.is_set(),
                    'stdout': bytes(buffers['stdout']).decode('utf-8', 'replace'),
                    'stderr': bytes(buffers['stderr']).decode('utf-8', 'replace'),
                    'stdout_bytes': counts['stdout'],
                    'stderr_bytes': counts['stderr']}

    # ---------------------------------------------------------------- ejecucion

    def execute(self, agent_id, code, *, channel=None, recipient=None, task_id=None,
                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES):
        """Ejecuta `code` aislado para `agent_id` y entrega el artefacto firmado al canal.

        Orden portado del fuente (gate -> workspace -> script -> spawn -> captura ->
        mensaje): nada se escribe en disco ni se lanza proceso antes de que la puerta
        'write' este aprobada. Los fallos DE EJECUCION (timeout, exit != 0, salida
        enorme) son resultado estructurado, no excepcion (port de _build_failure_message).
        """
        agent = self._validated(agent_id, code, timeout_seconds, max_output_bytes)
        member, target, task = self._resolve_delivery(channel, agent_id, recipient, task_id)
        agent_key = member.member_id if member is not None else agent

        # (2) PUERTA: antes de mkdir, script o proceso (I2).
        run_id = uuid.uuid4().hex
        workspace_rel = '%s/%s/%s' % (WORK_ROOT_NAME, agent_key, run_id)
        script_name = agent_key + '.py'           # nombre elegido por el sistema (fuente)
        action = {'action_kind': 'write_file',
                  'target': '%s/%s' % (workspace_rel, script_name),
                  'idempotency_key': 'sandbox-' + run_id}
        decision, approval = self._authorize(action)

        # (3) WORKSPACE dedicado por agente por ejecucion (tras la puerta).
        workspace = self._data_root / workspace_rel.replace('/', os.sep)
        workspace.mkdir(parents=True, exist_ok=False)
        script_path = workspace / script_name
        payload = code if code.endswith('\n') else code + '\n'
        script_path.write_text(payload, encoding='utf-8')

        # (5) SPAWN acotado con el interprete del proceso (argv fijo, shell=False).
        argv = [sys.executable, '-I', '-B', str(script_path)]
        raw = self._run_bounded(argv, workspace, timeout_seconds, max_output_bytes)

        if raw['timed_out']:
            status, error = 'timeout', TIMEOUT_MESSAGE.format(timeout=timeout_seconds)
        elif raw['output_truncated']:
            status, error = 'failed', OUTPUT_OVERFLOW_MESSAGE.format(limit=max_output_bytes)
        elif raw['exit_code'] == 0:
            status, error = 'completed', None
        else:
            status = 'failed'
            error = ' '.join(part for part in (
                EXECUTION_FAILED_MARKER,
                'exit_code=%s' % raw['exit_code'],
                ('stderr: ' + _clip(raw['stderr'], 400)) if raw['stderr'] else None) if part)
        ok = status == 'completed'

        run = {'run_id': run_id, 'agent_id': agent_key, 'status': status, 'ok': ok,
               'exit_code': raw['exit_code'], 'timed_out': raw['timed_out'],
               'output_truncated': raw['output_truncated'],
               'stdout': raw['stdout'], 'stderr': raw['stderr'],
               'stdout_bytes': raw['stdout_bytes'], 'stderr_bytes': raw['stderr_bytes'],
               'error': error, 'sandboxed': False, 'os_isolation': OS_ISOLATION_NOTE,
               'workspace': str(workspace), 'script_path': str(script_path),
               'policy': {'action_kind': 'write_file',
                          'gate': decision['gate'],
                          'decision': decision['decision'],
                          'scope_hash': action['scope_hash'],
                          'approved': approval is not None},
               'artifact': None, 'artifact_error': None,
               'delivered_to': None, 'evidence_id': None,
               'task_id': task['id'] if task is not None else None,
               'task_status': task['status'] if task is not None else None,
               'delivery_error': None}

        # (4) FIRMA del artefacto (report) + ENTREGA al canal.
        record = self._sign_artifact(run)
        self._deliver(run, channel, member, target, record)
        return run

    # ---------------------------------------------------------------- firma

    def _sign_artifact(self, run):
        """Firma el resultado como report de la fabrica; el guard de credenciales manda."""
        slug = _SLUG_RE.sub('', run['agent_id'].lower())[:30] or 'agente'
        name = 'sandbox-%s-%s' % (slug, run['run_id'])
        findings = [
            'Ejecutor: %s — run %s (status %s, exit_code=%s).'
            % (run['agent_id'], run['run_id'], run['status'], run['exit_code']),
            'Puerta policy_engine: write_file / gate %s (decision %s, aprobada=%s, '
            'scope_hash %s).' % (run['policy']['gate'], run['policy']['decision'],
                                 run['policy']['approved'], run['policy']['scope_hash']),
            'Limites: timeout por config; tope de salida aplicado; env minimo del hijo.',
            'stdout (%d bytes): %s' % (run['stdout_bytes'], _clip(run['stdout'], 1200) or '(vacio)'),
            'stderr (%d bytes): %s' % (run['stderr_bytes'], _clip(run['stderr'], 1200) or '(vacio)'),
            'error: %s' % (run['error'] or '(ninguno)'),
            'Aislamiento declarado: %s.' % OS_ISOLATION_NOTE,
        ]
        options = {'result_outcome': 'completed' if run['ok'] else 'failed',
                   'retry_class': 'none',
                   'idempotency_key': 'sbx-' + run['run_id']}
        if run['policy']['approved']:
            options['consent_ref'] = run['policy']['scope_hash']  # sha256: ata el artefacto al consentimiento
        try:
            record = self._factory.write_report(name, 'Ejecucion sandbox de %s' % run['agent_id'],
                                                findings, **options)
        except ArtifactFactoryError as error:
            # No se relaja ningun guard de la fabrica (p.ej. forbidden_field si la salida
            # impresa tiene forma de credencial): el run ya ocurrio y se reporta sin firma.
            run['artifact_error'] = error.code
            return None
        run['artifact'] = {'path': record.path, 'sha256': record.sha256,
                           'bytes': record.bytes, 'media_type': record.media_type,
                           'receipt': copy.deepcopy(record.receipt)}
        return record

    # ---------------------------------------------------------------- entrega

    def _deliver(self, run, channel, member, target, record):
        """Entrega al canal: evidencia + mensaje dirigido + claim/submit de la tarea."""
        if channel is None:
            return
        try:
            evidence_id = None
            if record is not None:
                locator = str(self._factory.root / record.path)
                evidence = channel.record_evidence(member.member_id, locator, record.sha256,
                                                   'run sandbox %s (%s)' % (run['run_id'],
                                                                            run['status']))
                evidence_id = evidence['id']
            if record is not None:
                cuerpo = ('[sandbox] %s run %s: %s (exit_code=%s). Artefacto firmado %s '
                          'sha256=%s.' % (run['agent_id'], run['run_id'], run['status'],
                                          run['exit_code'], record.path, record.sha256))
            else:
                cuerpo = ('[sandbox] %s run %s: %s (exit_code=%s). Sin artefacto firmado '
                          '(%s); la salida no viaja.' % (run['agent_id'], run['run_id'],
                                                         run['status'], run['exit_code'],
                                                         run['artifact_error']))
            channel.publish(member.member_id, to=target.member_id, text=cuerpo,
                            topic='sandbox')
            run['delivered_to'] = target.member_id
            run['evidence_id'] = evidence_id
            if run['task_id'] is not None:
                rows = [row for row in channel.ledger_view()['tasks']
                        if row['id'] == run['task_id']]
                estado = rows[0]['status'] if rows else None
                if estado in TASK_CLAIMABLE:
                    channel.claim(member.member_id, run['task_id'],
                                  note='sandbox run %s' % run['run_id'])
                    estado = 'claimed'
                if estado == 'claimed':
                    if evidence_id is not None:
                        channel.submit(member.member_id, run['task_id'], [evidence_id],
                                       output=cuerpo)
                        estado = 'submitted'
                    else:
                        # sin evidencia firmada no hay submit honesto: la tarea queda
                        # claimed y el motivo viaja en delivery_error (fail-honest).
                        run['delivery_error'] = ('tarea %s sin submit: no hay artefacto '
                                                 'firmado que citar como evidencia.'
                                                 % run['task_id'])
                run['task_status'] = estado
        except tc.ChannelError as error:
            # La ejecucion ya ocurrio: el fallo de entrega se reporta, no se descarta.
            run['delivery_error'] = 'ChannelError: %s' % error

    # ---------------------------------------------------------------- limpieza

    def cleanup(self, run, agent_id=None):
        """Borra el workspace de un run (limpiable por diseno). Symlink: unlink, no rmtree."""
        if isinstance(run, dict):
            workspace = Path(run['workspace'])
        else:
            agent = validate_component(agent_id or '', 'agent_id')
            workspace = self._data_root / WORK_ROOT_NAME / agent / str(run)
        if workspace.is_symlink():
            workspace.unlink()
            return True
        if workspace.is_dir():
            shutil.rmtree(workspace)
            return True
        return False

    def cleanup_agent(self, agent_id):
        """Borra TODOS los workspaces del agente (directorio bajo data/work/<agente>/)."""
        agent = validate_component(agent_id, 'agent_id')
        root = self._data_root / WORK_ROOT_NAME / agent
        if root.is_symlink():
            root.unlink()
            return True
        if root.is_dir():
            shutil.rmtree(root)
            return True
        return False


__all__ = ['DEFAULT_TIMEOUT_SECONDS', 'MAX_TIMEOUT_SECONDS', 'DEFAULT_MAX_OUTPUT_BYTES',
           'MIN_MAX_OUTPUT_BYTES', 'MAX_MAX_OUTPUT_BYTES', 'DEFAULT_DATA_ROOT',
           'OS_ISOLATION_NOTE', 'EXECUTION_FAILED_MARKER', 'TIMEOUT_MESSAGE',
           'OUTPUT_OVERFLOW_MESSAGE', 'NO_CODE_MESSAGE', 'RUN_STATUSES',
           'SandboxPolicyError', 'SandboxConfigError',
           'validate_component', 'SandboxExecutor']
