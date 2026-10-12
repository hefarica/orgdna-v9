#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ARRANQUE LIMPIO de OrgDNA — isomorfico, polimorfo e idempotente.

QUE GARANTIZA
  Isomorfo    : deriva su raiz de __file__. No hay ninguna ruta absoluta escrita a
                mano; funciona en C:\\, en un USB o en una copia del repo.
  Polimorfo   : se adapta a `py -3` o `python`, a que haya git o no, a que haya una
                instancia viva o ninguna, y al puerto que esa instancia estuviera
                usando. No asume 8765 ni 61720.
  Idempotente : si el codigo en disco ya es el que corre y no hay nada que traer,
                NO toca nada y lo dice. Ejecutarlo N veces deja el mismo estado.

QUE NO HACE NUNCA, POR DISENO
  - `git reset --hard`, `git clean`, `git checkout -f`: jamas. El trabajo local no
    se pisa. Si el arbol esta sucio, se informa y NO se actualiza.
  - Matar procesos por nombre. Solo termina el PID que se identifico a si mismo
    como esta aplicacion via /api/instance.
  - Tocar %LOCALAPPDATA%\\DSH_LAUNCHER ni ningun ajuste de DSH.
  - Escribir fuera del repositorio.

USO
  ARRANQUE_LIMPIO.cmd              diagnostica, actualiza si procede y arranca
  ARRANQUE_LIMPIO.cmd --check      solo diagnostica; no toca nada
  ARRANQUE_LIMPIO.cmd --yes        sin preguntas
  ARRANQUE_LIMPIO.cmd --no-update  no consulta el repo
  ARRANQUE_LIMPIO.cmd --port 8765  fuerza puerto
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

APP_ID = 'orgDNA.local.panel'
DEFAULT_PORT = 8765
MIN_PYTHON = (3, 10)
PACKAGE_DIRNAME = 'EQUIPO_ENTERPRISE_24_COUNCIL_ADN'
SEAL_SCRIPT = 'verifica_manifiesto.py'
REEXEC_FLAG = 'ORGDNA_ARRANQUE_REEXEC'

ROOT = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(ROOT, PACKAGE_DIRNAME)


def say(message=''):
    print(message, flush=True)


def step(number, title):
    say()
    say('=' * 74)
    say('  %s. %s' % (number, title))
    say('=' * 74)


def sha256_file(path):
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(1 << 16), b''):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def run(args, cwd=None, timeout=180):
    """Sin shell. Devuelve (codigo, salida_combinada)."""
    try:
        done = subprocess.run(args, cwd=cwd or ROOT, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout)
        return done.returncode, ((done.stdout or '') + (done.stderr or '')).strip()
    except FileNotFoundError:
        return 127, 'no encontrado: %s' % args[0]
    except subprocess.TimeoutExpired:
        return 124, 'agotado el tiempo: %s' % ' '.join(args)


# ---------------------------------------------------------------- identidad

def expected_build():
    """BUILD_ID que el codigo EN DISCO produciria ahora mismo.

    Se calcula en un SUBPROCESO importando engine.launcher: asi no se replica la
    formula a mano (que podria desincronizarse) ni se ejecuta nada en este proceso.
    """
    code = 'import sys; sys.path.insert(0, %r); from engine.launcher import BUILD_ID; print(BUILD_ID)' % PKG
    status, out = run([sys.executable, '-c', code], cwd=PKG, timeout=60)
    if status != 0 or not out:
        return None, out
    return out.splitlines()[-1].strip(), ''


def instance_identity(port, timeout=1.0):
    """Identidad publica del panel si ese puerto es NUESTRA aplicacion. Si no, None.

    Se sondean TODOS los puertos en escucha, y cualquiera puede hablar cualquier
    protocolo. Se captura Exception a proposito: el contrato de esta funcion es
    "devuelve None si no es nuestra aplicacion", y http.client.BadStatusLine es
    subclase de HTTPException, NO de OSError, asi que un `except OSError` la deja
    escapar y tumba el arranque entero.
    """
    url = 'http://127.0.0.1:%d/api/instance' % port
    try:
        request = urllib.request.Request(url, headers={'Host': '127.0.0.1:%d' % port})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            if response.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return None
            body = response.read(4097)
            if len(body) > 4096:
                return None
            row = json.loads(body.decode('utf-8'))
    except Exception:
        return None
    if isinstance(row, dict) and row.get('application') == APP_ID:
        return row
    return None


def listening_ports():
    """Puertos TCP en escucha, con su PID, via netstat. Sin dependencias externas."""
    status, out = run(['netstat', '-ano', '-p', 'tcp'], timeout=60)
    if status != 0:
        return []
    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != 'TCP' or 'LISTEN' not in parts[3].upper():
            continue
        match = re.match(r'^(?:\[[^\]]*\]|[^:]+):(\d+)$', parts[1])
        if not match:
            continue
        try:
            found.append((int(match.group(1)), int(parts[4])))
        except ValueError:
            continue
    return found


def find_running():
    """Todas las instancias vivas de ESTA aplicacion, identificadas por su propia
    respuesta HTTP. Nunca por nombre de proceso ni por numero de puerto."""
    sightings = []
    for port, pid in listening_ports():
        row = instance_identity(port)
        if row is not None:
            sightings.append({'port': port, 'pid': pid, 'build': row.get('build'),
                              'version': row.get('version'), 'installation': row.get('installation')})
    return sightings


# ---------------------------------------------------------------- actualizacion

def git_lines(*args):
    status, out = run(['git'] + list(args), timeout=180)
    return status, out


def update_from_repo():
    """Trae lo del repo SIN pisar nada. Devuelve (cambio, mensaje)."""
    status, out = git_lines('rev-parse', '--is-inside-work-tree')
    if status != 0 or out.strip() != 'true':
        return False, 'no es un repositorio git; se omite la actualizacion'
    status, remotes = git_lines('remote', '-v')
    if status != 0 or not remotes.strip():
        return False, 'sin remoto configurado; se omite la actualizacion'

    before_head = git_lines('rev-parse', 'HEAD')[1].strip()
    status, dirty = git_lines('status', '--porcelain')
    if status == 0 and dirty.strip():
        return False, ('arbol CON cambios locales: NO se actualiza para no pisarlos.\n'
                       '       Archivos afectados:\n' +
                       '\n'.join('         ' + line for line in dirty.splitlines()[:12]))

    status, fetch = git_lines('fetch', '--quiet', 'origin')
    if status != 0:
        return False, 'git fetch fallo: ' + fetch.splitlines()[0] if fetch else 'git fetch fallo'

    status, pull = git_lines('pull', '--ff-only', '--quiet', 'origin')
    if status != 0:
        first = (pull.splitlines() or ['sin detalle'])[0]
        return False, ('git pull --ff-only fallo (historiales divergentes): ' + first +
                       '\n       NO se fuerza nada. Resuelve la divergencia a mano.')

    after_head = git_lines('rev-parse', 'HEAD')[1].strip()
    if before_head == after_head:
        return False, 'ya estaba al dia (%s)' % before_head[:12]

    status, count = git_lines('rev-list', '--count', '%s..%s' % (before_head, after_head))
    say('  %s -> %s  (%s commits nuevos)' % (before_head[:12], after_head[:12],
                                             count.strip() if status == 0 else '?'))
    return True, 'actualizado a %s' % after_head[:12]


def verify_seal():
    path = os.path.join(ROOT, SEAL_SCRIPT)
    if not os.path.isfile(path):
        return None, 'no existe %s' % SEAL_SCRIPT
    status, out = run([sys.executable, path], timeout=300)
    return status == 0, (out.splitlines() or [''])[-1]


# ---------------------------------------------------------------- proceso

def terminate_process(pid):
    """Termina un PID probando varias vías, de la mas directa a la mas indirecta.

    Medido en este host: `taskkill /PID N /F` responde "Acceso denegado" mientras
    que TerminateProcess (lo que hace Stop-Process) SI termina el mismo PID, con el
    mismo usuario y la misma integridad. No se sabe por que taskkill falla aqui; lo
    que se sabe es que la via directa funciona, asi que va primero.

    Devuelve (ok, detalle). El detalle incluye el motivo COMPLETO, no su encabezado:
    el error de taskkill ocupa dos lineas y quedarse con la primera ocultaba el
    "Motivo: Acceso denegado", que es justo lo que hacia falta saber.
    """
    reasons = []

    # 1) Via directa: TerminateProcess sobre un handle con PROCESS_TERMINATE.
    if os.name == 'nt':
        try:
            import ctypes
            PROCESS_TERMINATE = 0x0001
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
            if handle:
                try:
                    if kernel32.TerminateProcess(handle, 1):
                        return True, 'terminada (TerminateProcess)'
                    reasons.append('TerminateProcess fallo (error %d)' % kernel32.GetLastError())
                finally:
                    kernel32.CloseHandle(handle)
            else:
                reasons.append('OpenProcess denego el acceso (error %d)' % kernel32.GetLastError())
        except Exception as exc:
            reasons.append('ctypes: %s' % exc)

    # 2) taskkill.
    status, out = run(['taskkill', '/PID', str(pid), '/F'], timeout=60)
    if status == 0:
        return True, 'terminada (taskkill)'
    reasons.append('taskkill: ' + ' '.join(out.split()))

    # 3) PowerShell Stop-Process.
    status, out = run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                       'Stop-Process -Id %d -Force' % int(pid)], timeout=60)
    if status == 0:
        return True, 'terminada (Stop-Process)'
    reasons.append('Stop-Process: ' + ' '.join(out.split()))

    return False, ' | '.join(reasons)


def port_is_free(port):
    """True si nada escucha ya en ese puerto (incluido algo que no sea nuestra app)."""
    for candidate, _pid in listening_ports():
        if candidate == port:
            return False
    return True


def stop_instance(pid, port):
    ok, detail = terminate_process(pid)
    if not ok:
        return False, detail
    for _ in range(40):
        if instance_identity(port, timeout=0.4) is None:
            return True, detail
        time.sleep(0.25)
    return False, detail + ' | el puerto %d sigue respondiendo' % port


def launch(port, extra=()):
    """Arranca el panel. `extra` reenvia a engine.launcher los argumentos que no son
    de este motor (--strict-port, --no-browser, --workbook ...), para que la interfaz
    documentada de launch.cmd siga funcionando igual."""
    args = [sys.executable, '-m', 'engine.launcher', '--port', str(port)] + list(extra)
    flags = 0
    if os.name == 'nt':
        flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0)
    try:
        subprocess.Popen(args, cwd=PKG, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return False, str(exc)
    return True, 'lanzado'


def pid_for_port(port):
    for candidate, pid in listening_ports():
        if candidate == port:
            return pid
    return None


def wait_ready(port, want_build, known_pids=(), seconds=45):
    """Espera a que aparezca una instancia con el build esperado.

    Con --port 0 engine.launcher elige un puerto libre, asi que la instancia nueva
    se descubre por su IDENTIDAD y por no estar entre los PIDs previos, nunca por el
    numero de puerto. Devuelve (fila, puerto_real) o (None, port).
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port:
            row = instance_identity(port, timeout=0.8)
            pid = pid_for_port(port)
            if row is not None and pid is not None and pid not in known_pids:
                return dict(row, pid=pid), port
        else:
            for row in find_running():
                if row['build'] == want_build and row['pid'] not in known_pids:
                    return row, row['port']
        time.sleep(0.5)
    return None, port


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument('--check', action='store_true', help='solo diagnostico; no toca nada')
    parser.add_argument('--yes', action='store_true', help='sin preguntas')
    parser.add_argument('--no-update', action='store_true', help='no consulta el repo')
    parser.add_argument('--port', type=int, default=None, help='fuerza el puerto')
    # parse_known_args: lo que no sea de este motor (--strict-port, --no-browser,
    # --workbook) se reenvia intacto a engine.launcher, para no romper la interfaz
    # documentada de launch.cmd.
    args, reenviar = parser.parse_known_args()
    if reenviar:
        say('#  se reenvia a engine.launcher: %s' % ' '.join(reenviar))

    started = time.time()
    say('#' * 74)
    say('#  ARRANQUE LIMPIO — OrgDNA')
    say('#  raiz: %s' % ROOT)
    say('#  modo: %s' % ('SOLO DIAGNOSTICO' if args.check else 'arranque'))
    say('#' * 74)

    if not os.path.isdir(PKG):
        say('FALLO: no encuentro %s junto a este script.' % PACKAGE_DIRNAME)
        return 2

    # ---- 1. Runtime -------------------------------------------------------
    step(1, 'Runtime')
    version = '.'.join(str(part) for part in sys.version_info[:3])
    say('  python           : %s' % version)
    say('  ejecutable       : %s' % sys.executable)
    if sys.version_info[:2] < MIN_PYTHON:
        say('  FALLO: se requiere Python %d.%d o posterior.' % MIN_PYTHON)
        return 2
    # Sin dependencias externas: verificado por AST sobre engine/ en la entrega.
    say('  dependencias     : ninguna (solo biblioteca estandar)')

    # ---- 2. Integridad ANTES ---------------------------------------------
    step(2, 'Integridad del arbol (antes)')
    ok, detail = verify_seal()
    if ok is None:
        say('  aviso: %s' % detail)
        seal_before = None
    else:
        say('  sello SHA-256    : %s' % ('OK' if ok else 'ROTO'))
        say('  %s' % detail)
        seal_before = ok
        if not ok:
            say('  FALLO: el arbol no verifica su propio sello. NO se arranca ni se actualiza.')
            say('         Repara con: python resella_paquete.py')
            return 3

    self_hash_before = sha256_file(os.path.abspath(__file__))
    head_before = git_lines('rev-parse', 'HEAD')[1].strip() if os.path.isdir(os.path.join(ROOT, '.git')) else ''

    # ---- 3. Actualizacion -------------------------------------------------
    step(3, 'Actualizacion desde el repo')
    updated = False
    if args.check or args.no_update:
        say('  omitida (%s)' % ('--check' if args.check else '--no-update'))
    else:
        updated, message = update_from_repo()
        say('  %s' % message)

    # ---- 4. Integridad DESPUES --------------------------------------------
    step(4, 'Integridad del arbol (despues)')
    if updated:
        ok, detail = verify_seal()
        say('  sello SHA-256    : %s' % ('OK' if ok else 'ROTO'))
        say('  %s' % detail)
        if not ok:
            say('  FALLO: la actualizacion dejo el sello roto. NO se arranca.')
            say('         Vuelve atras con: git reset --soft %s' % head_before[:12])
            return 3
    else:
        say('  sin cambios en el codigo; el sello previo sigue valiendo')

    # ---- 5. Autoreemplazo -------------------------------------------------
    self_path = os.path.abspath(__file__)
    if updated and sha256_file(self_path) != self_hash_before:
        if os.environ.get(REEXEC_FLAG) == '1':
            say('  el lanzador cambio otra vez; se continua con esta version para no entrar en bucle')
        else:
            say('  EL LANZADOR SE ACTUALIZO. Se relanza con la version nueva.')
            os.environ[REEXEC_FLAG] = '1'
            os.execv(sys.executable, [sys.executable, self_path] + sys.argv[1:])

    # ---- 6. Identidad esperada y estado vivo ------------------------------
    step(5, 'Codigo en disco frente a lo que corre')
    want, error = expected_build()
    if want is None:
        say('  FALLO: no puedo calcular el BUILD_ID del disco: %s' % error)
        return 2
    say('  build en disco   : %s' % want[:16])

    running = find_running()
    if not running:
        say('  instancias vivas : ninguna')
    for row in running:
        state = 'AL DIA' if row['build'] == want else 'OBSOLETA'
        say('  instancia        : puerto %d  pid %d  build %s  -> %s'
            % (row['port'], row['pid'], str(row['build'])[:16], state))

    stale = [row for row in running if row['build'] != want]
    current = [row for row in running if row['build'] == want]

    if not stale and current:
        say()
        say('RESULTADO: nada que hacer. La instancia que corre ya tiene este codigo.')
        say('  panel: http://127.0.0.1:%d' % current[0]['port'])
        say('  (idempotente: ejecutarlo de nuevo deja exactamente el mismo estado)')
        return 0

    if args.check:
        say()
        if stale:
            say('RESULTADO (diagnostico): hay %d instancia(s) OBSOLETA(s) en %s.'
                % (len(stale), ', '.join(str(r['port']) for r in stale)))
            say('  ejecuta sin --check para cerrarlas y arrancar el codigo nuevo')
        else:
            say('RESULTADO (diagnostico): ninguna instancia viva. Hay que arrancar.')
        return 0

    # ---- 7. Parada + arranque ---------------------------------------------
    port = args.port if args.port is not None else (
        stale[0]['port'] if stale else (current[0]['port'] if current else DEFAULT_PORT))
    known_pids = {row['pid'] for row in running}
    stop_failures = []

    if stale:
        step(6, 'Parada de la instancia obsoleta')
        say('  AVISO: los recibos de generacion viven EN MEMORIA hasta Guardar proyecto.')
        say('         Cerrar ahora puede perder recibos no guardados del intento en curso.')
        for row in stale:
            say('  a detener        : puerto %d  pid %d' % (row['port'], row['pid']))
        if not args.yes:
            try:
                answer = input('  ¿Cerrar y arrancar el codigo nuevo? [S/N]: ').strip().casefold()
            except EOFError:
                answer = 'n'
            if answer not in ('s', 'si', 'y', 'yes'):
                say('  cancelado por el operador. No se ha tocado nada.')
                return 1
        for row in stale:
            ok, detail = stop_instance(row['pid'], row['port'])
            say('  pid %-7d       : %s' % (row['pid'], detail))
            if not ok:
                stop_failures.append(row)
    else:
        step(6, 'Parada')
        say('  nada que detener')

    # Cerrar era OPCIONAL. Si una instancia obsoleta sigue viva y ocupa el puerto
    # deseado, NO se aborta: se arranca en un puerto libre. Lo que importa es servir
    # el codigo nuevo, no liberar el puerto viejo.
    if port and not port_is_free(port):
        say('  puerto %d sigue ocupado: se arranca en un puerto libre' % port)
        port = 0

    step(7, 'Arranque')
    ok, detail = launch(port, reenviar)
    if not ok:
        say('  FALLO al lanzar: %s' % detail)
        return 4
    say('  lanzado en       : %s' % ('puerto %d' % port if port else 'un puerto libre (--port 0)'))

    row, real_port = wait_ready(port, want, known_pids)
    if row is None:
        say('  FALLO: el panel no respondio en 45 s. Revisa la ventana del lanzador.')
        return 4
    port = real_port

    matches = row.get('build') == want
    say('  build servido    : %s' % str(row.get('build'))[:16])
    say('  build en disco   : %s' % want[:16])
    say()
    if stop_failures:
        say('  AVISO: %d instancia(s) siguen vivas con codigo VIEJO en %s.'
            % (len(stop_failures), ', '.join(str(r['port']) for r in stop_failures)))
        say('         No pude cerrarlas (ver el motivo arriba). Libera esos puertos desde')
        say('         el Administrador de tareas, o ejecuta este lanzador como Administrador.')
        say('         La instancia NUEVA ya esta sirviendo el codigo nuevo.')
        say()
    if matches:
        say('RESULTADO: OK — el panel sirve el codigo NUEVO.')
        say('  panel: http://127.0.0.1:%d' % port)
        if updated:
            say('  actualizado desde el repo en esta ejecucion')
        say('  tiempo total: %.1f s' % (time.time() - started))
        return 0
    say('RESULTADO: el panel arranco pero sirve un build DISTINTO al del disco.')
    say('  Esto no deberia ocurrir: revisa si hay otra copia del paquete en el PATH.')
    return 4


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say()
        say('interrumpido por el operador')
        sys.exit(130)
