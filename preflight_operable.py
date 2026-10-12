#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preflight operable de OrgDNA — 7 pasos, solo lectura salvo el 7.

REGLA DE ORO
    Un paso en BLOCKED NO es un paso en PASA.
    "Falta verificar" != "verificado".
    Nunca se eleva el veredicto por inferencia.

CODIGOS DE SALIDA
    0 = PASA      2 = BLOCKED (falta verificar, no roto)      1 = FALLA

USO
    python preflight_operable.py            los 7 pasos, en orden
    python preflight_operable.py --step 1   un solo paso
    python preflight_operable.py --json     artefacto para maquina

Nada de aqui escribe en el host, instala, activa ni llama a un proveedor.
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

ROOT = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(ROOT, 'EQUIPO_ENTERPRISE_24_COUNCIL_ADN')
EXT = os.path.join(PKG, 'cordis_extension')

PASS, FAIL, BLOCKED = 'PASS', 'FAIL', 'BLOCKED'
EXIT = {PASS: 0, FAIL: 1, BLOCKED: 2}


def _run(args, cwd=None, timeout=180):
    try:
        done = subprocess.run(args, cwd=cwd or ROOT, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout)
        return done.returncode, ((done.stdout or '') + (done.stderr or '')).strip()
    except FileNotFoundError:
        return 127, 'no encontrado: %s' % args[0]
    except subprocess.TimeoutExpired:
        return 124, 'agotado el tiempo'


def _read(path):
    try:
        with open(path, encoding='utf-8') as handle:
            return handle.read()
    except OSError:
        return None


# ---------------------------------------------------------------- paso 1

def step1(_):
    """Integridad del paquete: el validador y el sello, no una impresion."""
    validator = os.path.join(PKG, 'validate_imports_portable.py')
    if not os.path.isfile(validator):
        return BLOCKED, 'no encuentro validate_imports_portable.py'
    code, out = _run([sys.executable, validator])
    if code != 0:
        return FAIL, 'el validador devolvio %d' % code
    if '"valid": true' not in out:
        return FAIL, 'el validador no declara valid=true'
    seal = os.path.join(ROOT, 'verifica_manifiesto.py')
    if os.path.isfile(seal):
        scode, sout = _run([sys.executable, seal])
        if scode != 0:
            return FAIL, 'el sello SHA-256 no verifica'
        entries = re.search(r'entradas manifiesto:\s*(\d+)', sout)
        return PASS, 'valid=true y sello OK (%s entradas)' % (entries.group(1) if entries else '?')
    return PASS, 'valid=true (no hay verificador de sello en este nivel)'


# ---------------------------------------------------------------- paso 2

def step2(_):
    """Compatibilidad de versiones: exige LEER la lista soportada, no suponerla."""
    runtime_mjs = os.path.join(EXT, 'runtime.mjs')
    text = _read(runtime_mjs)
    if text is None:
        return BLOCKED, 'no encuentro cordis_extension/runtime.mjs'
    match = re.search(r'SUPPORTED_TOOLS_VERSIONS\s*=\s*(?:Object\.freeze\()?\s*\[([^\]]*)\]', text)
    if not match:
        return BLOCKED, 'SUPPORTED_TOOLS_VERSIONS no se puede leer de runtime.mjs'
    supported = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
    if not supported:
        return BLOCKED, 'SUPPORTED_TOOLS_VERSIONS esta vacia'
    code, out = _run(['node', '--version'], timeout=60)
    if code != 0:
        return BLOCKED, 'node no esta disponible para leer la version instalada'
    node_version = out.strip()
    try:
        require = subprocess.run(['node', '-e',
                                  "try{console.log(require('@deepseek-ai/dsh-tools/package.json').version)}catch(e){process.exit(3)}"],
                                 cwd=EXT, capture_output=True, text=True, timeout=90,
                                 encoding='utf-8', errors='replace')
    except OSError:
        return BLOCKED, 'node no ejecutable'
    if require.returncode != 0:
        return BLOCKED, ('@deepseek-ai/dsh-tools no es resoluble desde cordis_extension; '
                         'soportadas: %s (node %s)' % (','.join(supported), node_version))
    installed = (require.stdout or '').strip()
    if installed not in supported:
        return FAIL, 'dsh-tools %s no esta en SUPPORTED_TOOLS_VERSIONS (%s)' % (installed, ','.join(supported))
    return PASS, 'dsh-tools %s soportada (node %s)' % (installed, node_version)


# ---------------------------------------------------------------- paso 3

def step3(_):
    """Capacidad nativa. `maxMembers` es un PARAMETRO DEL PLUGIN, no un registro publico.

    Si no esta declarado, el default del plugin decide y NO se puede afirmar capacidad:
    eso es BLOCKED, nunca "suficiente".
    """
    candidates = []
    for base, _dirs, files in os.walk(ROOT):
        for name in files:
            if name.endswith(('.json', '.mjs', '.md')):
                path = os.path.join(base, name)
                rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
                # Los fixtures de test declaran maxMembers inventados (999): no son
                # capacidad del host. Incluirlos daria un PASS falso.
                if '/tests/' in rel or rel.startswith('tests/') or '/test_' in rel or 'fixture' in rel.lower():
                    continue
                text = _read(path)
                if text and 'maxMembers' in text:
                    candidates.append(path)
    if not candidates:
        return BLOCKED, 'maxMembers no aparece declarado en ningun artefacto: la capacidad NO esta verificada'
    found = {}
    for path in candidates[:40]:
        text = _read(path) or ''
        for value in re.findall(r"maxMembers['\"]?\s*[:=]\s*(\d+)", text):
            found.setdefault(int(value), []).append(os.path.relpath(path, ROOT))
    if not found:
        return BLOCKED, ('maxMembers se menciona pero sin valor declarado en %d archivos: '
                         'el default del plugin decide y no se puede afirmar capacidad' % len(candidates))
    sizes = sorted(found)
    return PASS, ('maxMembers declarado: %s. Comparalo con N-1 y decide TU: este paso no '
                  'cambia la configuracion del host.' % ', '.join(str(v) for v in sizes))


# ---------------------------------------------------------------- paso 4

def step4(_):
    """Ausencia de doble motor. Requiere el HOST: aqui solo se comprueba que el
    contrato existe y que la autoridad es INYECTADA."""
    text = _read(os.path.join(EXT, 'native_orchestration.mjs'))
    if text is None:
        return BLOCKED, 'no encuentro native_orchestration.mjs'
    needed = ('assertNoActiveGuiRuns', 'assertNoExistingTeam')
    missing = [name for name in needed if name not in text]
    if missing:
        return BLOCKED, 'el contrato no declara: %s' % ', '.join(missing)
    entry = _read(os.path.join(EXT, 'entry.mjs')) or ''
    if 'Choose native review UI or a pre-reviewed manual hook, not both' not in entry:
        return BLOCKED, 'entry.mjs no declara la exclusion mutua de los dos modos'
    return BLOCKED, ('el contrato existe y la exclusion es explicita, pero comprobar que NO hay GUI '
                     'activa ni equipo nativo exige el host: no se puede afirmar desde aqui')


# ---------------------------------------------------------------- paso 5

def step5(_):
    """Bindings sesion->perfil: la pieza mas fragil. Si no se puede verificar, DETENTE."""
    patterns = ('identity-map.json', 'identity_map.json')
    for name in patterns:
        for base, _dirs, files in os.walk(ROOT):
            if name in files:
                path = os.path.join(base, name)
                try:
                    data = json.loads(_read(path) or '{}')
                except ValueError:
                    return FAIL, '%s no es JSON valido' % os.path.relpath(path, ROOT)
                bindings = data.get('session_bindings') or {}
                members = data.get('members') or []
                if not bindings:
                    return FAIL, ('%s declara session_bindings vacio: el producto lanza '
                                  'UNBOUND_SESSION (verificado en runtime.test.mjs:94)'
                                  % os.path.relpath(path, ROOT))
                return PASS, '%s: %d bindings para %d miembros' % (os.path.relpath(path, ROOT),
                                                                   len(bindings), len(members))
    return BLOCKED, ('no hay identity-map.json: los bindings sesion->perfil no estan producidos. '
                     'Es la pieza donde el cerebro unico se parte: DETENTE aqui')


# ---------------------------------------------------------------- paso 6

def step6(_):
    """Ruta del Captain frente al perfil: si difieren, el staging falla. No se fuerza."""
    routes = {}
    for base, _dirs, files in os.walk(PKG):
        for name in files:
            if name.endswith('.json') and ('recipe' in name or 'definitions' in name or 'council' in name):
                path = os.path.join(base, name)
                text = _read(path) or ''
                for model in set(re.findall(r'"model"\s*:\s*"([^"]+)"', text)):
                    routes.setdefault(model, set()).add(os.path.relpath(path, PKG))
    if not routes:
        return BLOCKED, 'no hay artefactos de equipo con ruta declarada que comparar'
    if len(routes) == 1:
        return PASS, 'una sola ruta de modelo en los artefactos: %s' % list(routes)[0]
    summary = '; '.join('%s (%d archivos)' % (m, len(f)) for m, f in sorted(routes.items()))
    return FAIL, ('hay MAS DE UNA ruta de modelo entre los artefactos: %s. El producto exige que '
                  'la ruta del Captain coincida con la del perfil y falla si difieren: no se '
                  'auto-ajusta.' % summary)


# ---------------------------------------------------------------- paso 7

def step7(_):
    """Herramientas registradas: exige readback contra una sesion montada. Sin host, BLOCKED."""
    hits = []
    for base, _dirs, files in os.walk(EXT):
        for name in files:
            if not name.endswith('.mjs'):
                continue
            text = _read(os.path.join(base, name)) or ''
            if "_state" in text or 'addonNamespace' in text:
                hits.append(os.path.relpath(os.path.join(base, name), EXT))
    if not hits:
        return BLOCKED, 'el contrato de readback del namespace no aparece en cordis_extension/'
    return BLOCKED, ('el readback exige una sesion vinculada y el addon montado. Este paso es el '
                     'UNICO que toca el host y va DESPUES de la revision humana de permisos: '
                     'sin host, no se puede afirmar MOUNTED')


STEPS = (
    (1, 'Integridad del paquete', step1),
    (2, 'Compatibilidad de versiones', step2),
    (3, 'Capacidad nativa (maxMembers)', step3),
    (4, 'Ausencia de doble motor', step4),
    (5, 'Bindings sesion->perfil', step5),
    (6, 'Ruta del Captain', step6),
    (7, 'Herramientas registradas (readback)', step7),
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--step', type=int, default=None)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    chosen = [row for row in STEPS if args.step is None or row[0] == args.step]
    if not chosen:
        print('paso invalido: 1..7')
        return 1

    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    results, worst = [], PASS
    for number, title, function in chosen:
        try:
            status, evidence = function(None)
        except Exception as exc:                                    # noqa: BLE001
            status, evidence = BLOCKED, 'el paso lanzo %s: %s' % (type(exc).__name__, exc)
        results.append({'id': number, 'title': title, 'status': status, 'evidence': evidence})
        if not args.json:
            print('  [%-7s] %d. %s' % (status, number, title))
            print('            %s' % evidence)
        if EXIT[status] > EXIT[worst]:
            worst = status

    report = {'preflight': {'host': os.environ.get('COMPUTERNAME', 'unknown'),
                            'runner': sys.executable, 'started_at': started,
                            'root': ROOT, 'steps': results,
                            'verdict': ('READY_TO_STAGE' if worst == PASS else
                                        '%s(%s)' % (worst, ','.join(str(row['id']) for row in results
                                                                    if row['status'] == worst))),
                            'writes_performed': False, 'model_calls_performed': False,
                            'rule': 'Un paso en BLOCKED no es un paso en PASA.'}}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print()
        print('  VEREDICTO: %s' % report['preflight']['verdict'])
        print('  (BLOCKED significa "falta verificar", nunca "verificado")')
    return EXIT[worst]


if __name__ == '__main__':
    sys.exit(main())
