"""Explicitly approved, bounded local test runs. This is NOT an OS sandbox.

Only a curated unittest argv is supported. Repository tests are executable code
and have the user's OS access. No API calls, installation, skills promotion or
DSH dispatch is performed here. Raw subprocess output is never persisted or
returned: arbitrary test output cannot be reliably scrubbed of unknown secrets.
"""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
import uuid


class EvaluationError(ValueError):
    pass


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _file_sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            h.update(block)
    return h.hexdigest()


EXCLUDED_DIRECTORIES = {'.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.venv', 'venv', 'node_modules'}

def _snapshot(root, test_root=None):
    """Bounded complete file-content manifest, excluding runtime/cache outputs."""
    excluded = EXCLUDED_DIRECTORIES
    manifest, total = [], 0
    def walk_error(error):
        raise EvaluationError('No se pudo leer toda la fuente; evaluación bloqueada.') from error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        inside_tests = test_root is not None and Path(directory).is_relative_to(test_root)
        dirs[:] = sorted(d for d in dirs if inside_tests or d not in excluded)
        for name in dirs + sorted(files):
            path = Path(directory) / name
            if path.is_symlink():
                raise EvaluationError('El árbol de evaluación no admite symlinks; elige una copia autocontenida.')
        for name in sorted(files):
            path = Path(directory) / name
            if not inside_tests and path.suffix in {'.pyc', '.pyo'}:
                continue
            if not path.is_file():
                raise EvaluationError('El árbol debe contener sólo archivos regulares.')
            size = path.stat().st_size
            total += size
            if size > 20_000_000 or total > 100_000_000 or len(manifest) >= 10000:
                raise EvaluationError('Fuente demasiado grande: máximo 10.000 archivos, 20 MB por archivo, 100 MB total.')
            manifest.append([str(path.relative_to(root)), _file_sha(path)])
    if not manifest:
        raise EvaluationError('La fuente no contiene archivos evaluables.')
    return {'sha256': _sha(manifest), 'files': len(manifest), 'bytes': total,
            'excluded_directories_outside_tests': sorted(excluded), 'complete_test_tree': str(test_root.relative_to(root)) if test_root else None, 'scope': 'local_file_content_manifest_not_git_commit'}


class EvaluationRuns:
    PROFILE = {'id': 'python_unittest_v1', 'name': 'Python unittest local',
               'description': 'Ejecuta pruebas Python del directorio elegido. Sin shell ni instalación. Sin aislamiento del sistema operativo.',
               'requires_user_confirmation': True, 'sandboxed': False}

    PROFILES = [PROFILE, {**PROFILE, 'id': 'python_pytest_v1', 'name': 'Python pytest local'},
                {**PROFILE, 'id': 'node_test_v1', 'name': 'Node.js test local'}]

    def __init__(self, artifact_dir=None):
        self.lock = threading.RLock()
        self.plans, self.runs, self.processes, self.cancellations = {}, {}, {}, {}
        self.artifact_dir = Path(artifact_dir).resolve() if artifact_dir else None
        if self.artifact_dir:
            self.artifact_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _identities(body, organization):
        if not isinstance(organization, dict):
            raise EvaluationError('Genera una organización antes de evaluar.')
        agents = {a['id']: a for a in organization.get('agents', [])}
        aid, evaluator = body.get('agent_id'), body.get('evaluator_id')
        if aid not in agents or evaluator not in {*agents, 'OWNER_EXTERNAL'}:
            raise EvaluationError('Autor y evaluador deben pertenecer al diseño actual (o evaluador OWNER_EXTERNAL).')
        if evaluator == aid:
            raise EvaluationError('El autor no puede actuar como evaluador independiente de su resultado.')
        skills = {s.get('id') for s in agents[aid].get('skills', []) + agents[aid].get('proposed_skills', []) if isinstance(s, dict)}
        skill_ids = body.get('skill_ids', [])
        if not isinstance(skill_ids, list) or len(skill_ids) > 32 or any(not isinstance(x, str) or x not in skills for x in skill_ids):
            raise EvaluationError('skill_ids debe referenciar competencias del perfil actual.')
        task = body.get('task_id')
        if not isinstance(task, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}', task):
            raise EvaluationError('task_id debe ser un identificador explícito de tarea.')
        return {'organization_id': organization.get('organization_id'), 'state_version': organization.get('state_version', 1),
                'organization_sha256': _sha(organization), 'agent_sha256': _sha(agents[aid]),
                'organization_source_sha256': organization.get('provenance', {}).get('source_hash'),
                'repository_sha': organization.get('provenance', {}).get('repository_sha'), 'agent_id': aid, 'evaluator_id': evaluator,
                'task_id': task, 'skill_ids': sorted(set(skill_ids))}

    def prepare(self, body, organization):
        if not isinstance(body, dict) or body.get('profile_id') not in {p['id'] for p in self.PROFILES}:
            raise EvaluationError('Selecciona un perfil curado unittest, pytest o node_test.')
        if any(k in body for k in ('argv', 'command', 'env', 'shell', 'executable')):
            raise EvaluationError('El perfil curado no admite comandos, ejecutables ni variables de entorno arbitrarios.')
        identities = self._identities(body, organization)
        cwd = Path(body.get('cwd', '')).expanduser()
        if not cwd.is_absolute() or not cwd.is_dir() or cwd.is_symlink():
            raise EvaluationError('cwd debe ser un directorio absoluto existente.')
        cwd = cwd.resolve()
        if self.artifact_dir and self.artifact_dir.is_relative_to(cwd):
            raise EvaluationError('El destino de evidencia está dentro de cwd y alteraría la fuente. Selecciona un repositorio separado del almacenamiento de la app.')
        test_dir = body.get('test_dir', 'tests')
        if not isinstance(test_dir, str) or not test_dir or Path(test_dir).is_absolute() or '..' in Path(test_dir).parts:
            raise EvaluationError('test_dir debe ser relativo y estar dentro de cwd.')
        if set(Path(test_dir).parts) & EXCLUDED_DIRECTORIES:
            raise EvaluationError('test_dir no puede estar en directorios excluidos del digest.')
        tests = (cwd / test_dir).resolve()
        if not tests.is_relative_to(cwd) or not tests.is_dir():
            raise EvaluationError('No existe el directorio de pruebas dentro de cwd.')
        timeout = body.get('timeout_seconds', 30)
        output = body.get('output_limit_bytes', 65536)
        if type(timeout) is not int or not 1 <= timeout <= 120 or type(output) is not int or not 1024 <= output <= 262144:
            raise EvaluationError('Límites: timeout 1–120 segundos; salida total 1024–262144 bytes.')
        profile = body['profile_id']
        executable = Path(sys.executable).resolve()
        version = sys.version.split()[0]
        harness = None
        if profile == 'python_unittest_v1':
            harness = Path(__file__).resolve()
            argv = [str(executable), '-I', '-B', str(harness), '--unittest', str(cwd), str(tests)]
        elif profile == 'python_pytest_v1':
            if importlib.util.find_spec('pytest') is None:
                raise EvaluationError('pytest no está instalado en el Python de esta app. Instálalo tú o selecciona otro perfil.')
            argv = [str(executable), '-I', '-B', '-m', 'pytest', str(tests), '-q', '-p', 'no:cacheprovider', '-o', 'addopts=', '-o', 'pythonpath=' + str(cwd)]
        else:
            located = shutil.which('node')
            if not located:
                raise EvaluationError('Node.js no está disponible en PATH. Instálalo tú o selecciona otro perfil.')
            executable = Path(located).resolve()
            if executable.name.lower() not in {'node', 'node.exe'}:
                raise EvaluationError('El ejecutable resuelto no es Node.js.')
            targets = sorted(str(p) for p in tests.rglob('*') if p.is_file() and not (set(p.relative_to(cwd).parts) & EXCLUDED_DIRECTORIES) and re.fullmatch(r'(?:test[_.-].*|.*[_.-]test)\.(?:js|cjs|mjs)', p.name))
            if not targets or len(targets) > 100:
                raise EvaluationError('Node requiere 1–100 archivos test_*.js o *.test.js/cjs/mjs en test_dir.')
            argv = [str(executable), '--test', '--test-reporter=tap', *targets]
            # Version is collected only inside the confirmed run, never execute an unknown binary while preparing.
            version = 'pending_confirmed_run'
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise EvaluationError('El intérprete Python absoluto no está disponible.')
        plan = {'id': str(uuid.uuid4()), 'profile_id': profile, **identities,
                'cwd': str(cwd), 'test_dir': str(tests.relative_to(cwd)),
                'argv': argv, 'executable_version': version,
                'harness_sha256': _file_sha(harness) if harness else None,
                'executable_sha256': _file_sha(executable), 'source': _snapshot(cwd, tests),
                'timeout_seconds': timeout, 'output_limit_bytes': output,
                'environment': 'empty_except_windows_systemroot; no inherited API keys',
                'expected_conditions': ['exit_code == 0', 'selected runner reports at least one passed test',
                                        'selected runner final status success', 'source unchanged after run', 'output limit not exceeded'],
                'created_at': time.time(), 'expires_at': time.time() + 900,
                'sandboxed': False, 'source_identity_verified': False,
                'source_relationship': 'User-selected local source; no automatic proof that cwd equals the analyzed remote repository/commit.',
                'risk_notice': 'Las pruebas son código local: pueden leer archivos, usar red y modificar el sistema con tus permisos. No hay sandbox. Revisa la fuente antes de confirmar.',
                'log_policy': 'Raw stdout/stderr withheld; only fixed-format runner counts and bounded byte counters retained.',
                'skills_verified': False, 'skills_installed': False, 'skills_proposed': []}
        plan['plan_hash'] = _sha(plan)
        with self.lock:
            if len(self.plans) >= 100:
                raise EvaluationError('Límite de 100 planes por sesión; reinicia la app para continuar.')
            self.plans[plan['id']] = copy.deepcopy(plan)
        return copy.deepcopy(plan)

    def start(self, plan_id, plan_hash, organization):
        with self.lock:
            plan = self.plans.get(plan_id)
            if not plan or not isinstance(plan_hash, str) or plan_hash != plan['plan_hash']:
                raise EvaluationError('Confirma el hash exacto del plan mostrado antes de ejecutar.')
            existing = next((r for r in self.runs.values() if r['plan_id'] == plan_id), None)
            if existing:
                return copy.deepcopy(existing)
            if time.time() > plan['expires_at']:
                raise EvaluationError('Plan caducado; prepara y confirma uno nuevo.')
            if _sha(organization) != plan['organization_sha256']:
                raise EvaluationError('El diseño o sus perfiles cambiaron; prepara un plan nuevo.')
            if _file_sha(Path(plan['argv'][0])) != plan['executable_sha256'] or _snapshot(Path(plan['cwd']), Path(plan['cwd']) / plan['test_dir']) != plan['source'] or (plan['harness_sha256'] and _file_sha(Path(__file__).resolve()) != plan['harness_sha256']):
                raise EvaluationError('La fuente o el ejecutable cambiaron; prepara y confirma un plan nuevo.')
            if any(r['status'] in {'queued', 'running'} for r in self.runs.values()):
                raise EvaluationError('Ya hay una evaluación activa. Espera o cancélala.')
            run_id = str(uuid.uuid4())
            run = {'id': run_id, 'plan_id': plan_id, 'plan_hash': plan_hash, 'status': 'queued',
                   'created_at': time.time(), 'agent_id': plan['agent_id'], 'evaluator_id': plan['evaluator_id'],
                   'task_id': plan['task_id'], 'skill_ids': plan['skill_ids'],
                   'organization_id': plan['organization_id'], 'organization_sha256': plan['organization_sha256'],
                   'state_version': plan['state_version'], 'agent_sha256': plan['agent_sha256'],
                   'organization_source_sha256': plan['organization_source_sha256'], 'repository_sha': plan['repository_sha'], 'source_sha256': plan['source']['sha256'],
                   'tested_scope': {'profile_id': plan['profile_id'], 'test_dir': plan['test_dir'], 'argv': plan['argv']},
                   'machine_verified': False, 'verification_scope': 'local test execution only; not overall agent capability',
                   'source_identity_verified': False,
                   'source_relationship': 'User-selected local source; remote repository identity not verified.',
                   'test_result_trust': 'untrusted_process_report',
                   'execution_unit': ('node test or whole test file; assertions not independently measured' if plan['profile_id'] == 'node_test_v1' else 'runner-reported test case'),
                   'dependency_environment': 'global runtime dependencies; not hermetic or pinned by source digest',
                   'independent_review_required': True, 'independent_review_verified': False,
                   'skills_verified': False, 'skills_installed': False, 'skills_proposed': [], 'sandboxed': False}
            self.runs[run_id] = run
            self.cancellations[run_id] = threading.Event()
            threading.Thread(target=self._execute, args=(run_id, copy.deepcopy(plan)), daemon=True).start()
            return copy.deepcopy(run)

    def get(self, run_id):
        with self.lock:
            if run_id not in self.runs:
                raise EvaluationError('No existe esa evaluación.')
            return copy.deepcopy(self.runs[run_id])

    def verified_result(self, run_id, organization=None, verify_current_source=True):
        """Return a completed result from this manager, never import client assertions."""
        run = self.get(run_id)
        if run['status'] in {'queued', 'running'}:
            raise EvaluationError('La evaluación todavía no terminó.')
        canonical = {k: v for k, v in run.items() if k not in {'artifact_result_sha256', 'evidence_ref', 'artifact_saved'}}
        if _sha(canonical) != run.get('artifact_result_sha256'):
            raise EvaluationError('El digest del resultado no coincide.')
        if organization is not None and _sha(organization) != run['organization_sha256']:
            raise EvaluationError('El resultado pertenece a otro estado organizacional; vuelve a evaluar.')
        if verify_current_source:
            plan = self.plans.get(run['plan_id'])
            if not plan or _snapshot(Path(plan['cwd']), Path(plan['cwd']) / plan['test_dir'])['sha256'] != run['source_sha256']:
                raise EvaluationError('La fuente cambió después de evaluar; vuelve a ejecutar las pruebas.')
        return run

    def public(self):
        with self.lock:
            return {'profiles': copy.deepcopy(self.PROFILES), 'plans': copy.deepcopy(list(self.plans.values())),
                    'runs': copy.deepcopy(list(self.runs.values())), 'results_persisted': self.artifact_dir is not None,
                    'sandboxed': False, 'automatic_execution': False}

    def cancel(self, run_id):
        with self.lock:
            run = self.get(run_id)
            if run['status'] in {'queued', 'running'}:
                self.cancellations[run_id].set()
            return self.get(run_id)

    @staticmethod
    def _windows_job(process):
        """Attach a suspended child to a kill-on-close job before resuming it."""
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
                        ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        job = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not job:
            raise EvaluationError('No se pudo crear el contenedor de procesos Windows.')
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))):
            kernel.CloseHandle(job)
            raise EvaluationError('No se pudo vincular el proceso suspendido; ejecución cancelada.')
        process._evaluation_job = (kernel, job)
        resume = ctypes.WinDLL('ntdll').NtResumeProcess
        resume.argtypes = [wintypes.HANDLE]
        if resume(wintypes.HANDLE(int(process._handle))) != 0:
            raise EvaluationError('No se pudo iniciar el proceso vinculado.')

    @staticmethod
    def _stop(process):
        try:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                job = getattr(process, '_evaluation_job', None)
                if job:
                    job[0].CloseHandle(job[1])
                    process._evaluation_job = None
                if process.poll() is None:
                    process.kill()
        except (ProcessLookupError, OSError):
            pass

    def _node_version(self, executable, env):
        """Bound version probe after approval, including malicious/broken binaries."""
        process = subprocess.Popen([executable, '--version'], env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   start_new_session=(os.name == 'posix'), creationflags=(4 if os.name == 'nt' else 0))
        data = bytearray()
        def read():
            try:
                while len(data) <= 128:
                    chunk = process.stdout.read(128)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > 128:
                        self._stop(process)
            finally:
                process.stdout.close()
        try:
            if os.name == 'nt':
                self._windows_job(process)
            worker = threading.Thread(target=read, daemon=True)
            worker.start()
            process.wait(timeout=2)
            self._stop(process)
            worker.join(timeout=1)
            version = bytes(data).decode('ascii', 'ignore').strip()
            if process.returncode != 0 or len(data) > 128 or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', version):
                raise EvaluationError('No se pudo verificar la versión Node.js.')
            return version
        finally:
            self._stop(process)

    def _execute(self, run_id, plan):
        event = self.cancellations[run_id]
        result = {'exit_code': None, 'tests_run': 0, 'stdout_bytes': 0, 'stderr_bytes': 0,
                  'stdout': '[raw output withheld to protect unknown credentials]',
                  'stderr': '[raw output withheld to protect unknown credentials]',
                  'source_unchanged': False, 'output_limit_exceeded': False}
        process = None
        launch_ready = False
        status, reason = 'fail', 'runner_error'
        buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        counts = {'stdout': 0, 'stderr': 0}
        count_lock = threading.Lock()
        overflow = threading.Event()
        def reader(stream, name):
            try:
                while True:
                    data = stream.read(4096)
                    if not data:
                        break
                    with count_lock:
                        counts[name] += len(data)
                        left = plan['output_limit_bytes'] - sum(len(b) for b in buffers.values())
                        buffers[name].extend(data[:max(0, left)])
                        if sum(counts.values()) > plan['output_limit_bytes']:
                            overflow.set()
                            break
            finally:
                stream.close()
        try:
            if event.is_set():
                status, reason = 'cancelled', 'user_cancelled'
            else:
                # A second check narrows prepare/start races. This is not immutable isolation.
                if _snapshot(Path(plan['cwd']), Path(plan['cwd']) / plan['test_dir']) != plan['source'] or _file_sha(Path(plan['argv'][0])) != plan['executable_sha256'] or (plan['harness_sha256'] and _file_sha(Path(__file__).resolve()) != plan['harness_sha256']):
                    raise EvaluationError('source_changed_before_launch')
                env = {'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'} if plan['profile_id'] == 'python_pytest_v1' else {}
                if os.name == 'nt' and os.environ.get('SystemRoot'):
                    env['SystemRoot'] = os.environ['SystemRoot']
                if plan['profile_id'] == 'node_test_v1':
                    result['executable_version'] = self._node_version(plan['argv'][0], env)
                process = subprocess.Popen(plan['argv'], cwd=plan['cwd'], env=env, shell=False,
                                           stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           start_new_session=(os.name == 'posix'),
                                           creationflags=(0x4 if os.name == 'nt' else 0))
                if os.name == 'nt':
                    self._windows_job(process)
                launch_ready = True
                with self.lock:
                    self.processes[run_id] = process
                    self.runs[run_id].update(status='running', started_at=time.time())
                readers = [threading.Thread(target=reader, args=(getattr(process, n), n), daemon=True) for n in buffers]
                for worker in readers:
                    worker.start()
                deadline = time.monotonic() + plan['timeout_seconds']
                while process.poll() is None:
                    if event.is_set() or overflow.is_set() or time.monotonic() >= deadline:
                        self._stop(process)
                        break
                    time.sleep(.02)
                process.wait(timeout=5)
                # Kill any descendants still holding pipes after the main test process exits.
                self._stop(process)
                for worker in readers:
                    worker.join(timeout=1)
                with count_lock:
                    result.update(stdout_bytes=counts['stdout'], stderr_bytes=counts['stderr'])
                    output = bytes(buffers['stderr']).decode('utf-8', 'replace')
                matches = re.findall(r'^Ran ([0-9]+) tests? in [0-9.]+s\r?$', output, re.MULTILINE)
                result['tests_run'] = int(matches[-1]) if matches else 0
                ok = bool(re.search(r'(?:^|\n)OK(?: \(skipped=[0-9]+\))?\s*$', output))
                skipped = re.search(r'OK \(skipped=([0-9]+)\)\s*$', output)
                result['tests_skipped'] = int(skipped.group(1)) if skipped else 0
                if plan['profile_id'] == 'python_pytest_v1':
                    output = bytes(buffers['stdout']).decode('utf-8', 'replace')
                    passed = re.findall(r'(?:^|[, ])([0-9]+) passed(?:[, \n]|$)', output)
                    result['tests_run'] = int(passed[-1]) if passed else 0
                    result['tests_skipped'] = 0
                    ok = result['tests_run'] > 0
                elif plan['profile_id'] == 'node_test_v1':
                    output = bytes(buffers['stdout']).decode('utf-8', 'replace')
                    def tap_count(name):
                        hits = re.findall(r'^# ' + name + r' ([0-9]+)\r?$', output, re.MULTILINE)
                        return int(hits[-1]) if hits else 0
                    result['tests_run'] = tap_count('tests')
                    result['tests_skipped'] = tap_count('skipped')
                    ok = tap_count('pass') > 0 and tap_count('fail') == 0
                result['exit_code'] = process.returncode
                result['output_limit_exceeded'] = overflow.is_set()
                result['source_unchanged'] = (_snapshot(Path(plan['cwd']), Path(plan['cwd']) / plan['test_dir']) == plan['source'] and _file_sha(Path(plan['argv'][0])) == plan['executable_sha256'] and (not plan['harness_sha256'] or _file_sha(Path(__file__).resolve()) == plan['harness_sha256']))
                if event.is_set():
                    status, reason = 'cancelled', 'user_cancelled'
                elif overflow.is_set():
                    status, reason = 'fail', 'output_limit_exceeded'
                elif time.monotonic() >= deadline:
                    status, reason = 'timeout', 'timeout_limit_exceeded'
                elif process.returncode == 0 and result['tests_run'] > result['tests_skipped'] and ok and result['source_unchanged']:
                    status, reason = 'pass', 'expected_conditions_met'
                else:
                    status, reason = 'fail', 'test_failed_or_no_tests_or_source_changed'
        except Exception:
            # Exception strings can contain repository-generated secrets: do not expose.
            if process:
                self._stop(process)
            reason = 'runner_error_or_source_changed'
        finally:
            for value in buffers.values():
                value.clear()
            with self.lock:
                run = self.runs[run_id]
                run.update(result, status=status, reason=reason, finished_at=time.time(),
                           machine_verified=(status == 'pass'), machine_execution_observed=launch_ready)
                run['artifact_result_sha256'] = _sha(run)
                run['evidence_ref'] = 'evaluation://' + run_id + '/' + run['artifact_result_sha256']
                if self.artifact_dir:
                    try:
                        target = self.artifact_dir / (run_id + '.json')
                        payload = {'plan': plan, 'result': run}
                        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
                        run['artifact_saved'] = True
                    except OSError:
                        run['artifact_saved'] = False
                self.processes.pop(run_id, None)


if __name__ == '__main__':
    # Closed local harness: isolated Python starts stdlib unittest before adding the
    # explicitly approved source root, so ordinary project imports are supported.
    if len(sys.argv) != 4 or sys.argv[1] != '--unittest':
        raise SystemExit(2)
    import unittest
    sys.path.insert(0, sys.argv[2])
    suite = unittest.defaultTestLoader.discover(sys.argv[3], pattern='test*.py')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
