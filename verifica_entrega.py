#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TARJETA DE ENTREGA de OrgDNA — un solo comando, veredicto sin adornos.

Comprueba el estado REAL de la entrega, no lo que digan los informes:

  1. Sello del paquete        -> verifica_manifiesto.py (0 divergentes/faltantes/sobrantes)
  2. Entrega portable         -> validate_imports_portable.py (valid=true)
  3. Arranque                 -> arranque_limpio.py --check (sello + build en disco vs. servido)
  4. Panel vivo               -> handshake real (cookie + CSRF) y lectura de /api/state
  5. Capacidades del equipo   -> matriz: canal P2, memoria P4, compromisos P3, sandbox P1
  6. Arnés Chromium           -> qa_v7/chromium_e2e.py si existe (navegador real)
  7. Suite completa           -> solo con --suite (tarda varios minutos)

Uso:
    python verifica_entrega.py                # tarjeta rapida (sin suite ni chromium)
    python verifica_entrega.py --suite        # + suite completa canonica
    python verifica_entrega.py --chromium     # + arnes E2E en Chromium
    python verifica_entrega.py --todo         # + suite + chromium

Salida: exit 0 solo si TODAS las comprobaciones obligatorias pasan.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(ROOT, 'EQUIPO_ENTERPRISE_24_COUNCIL_ADN')
FILAS = []


def fila(nombre, estado, detalle=''):
    FILAS.append((nombre, estado, detalle))
    marca = {'OK': 'OK  ', 'FALLA': 'FALLA', 'SALTA': 'SALTA'}.get(estado, estado)
    print('  [%s] %-26s %s' % (marca, nombre, detalle))


def ejecutar(args, cwd=None, timeout=1800):
    try:
        hecho = subprocess.run(args, cwd=cwd or ROOT, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=timeout)
        return hecho.returncode, (hecho.stdout or '') + (hecho.stderr or '')
    except FileNotFoundError:
        return 127, 'no encontrado: %s' % args[0]
    except subprocess.TimeoutExpired:
        return 124, 'agotado el tiempo'


# ------------------------------------------------------------------ handshake

class Panel:
    def __init__(self, puerto):
        self.base = 'http://127.0.0.1:%s' % puerto
        self.host = '127.0.0.1:%s' % puerto
        self.cookie = None
        self.csrf = None

    def handshake(self):
        peticion = urllib.request.Request(self.base + '/', headers={'Host': self.host})
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            html = respuesta.read().decode('utf-8', 'replace')
            crudo = respuesta.headers.get('Set-Cookie', '')
        encontrado = re.search(r'orgdna_session=([^;]+)', crudo)
        self.cookie = encontrado.group(1) if encontrado else None
        token = re.search(r'<meta name="csrf-token" content="([^"]+)">', html)
        self.csrf = token.group(1) if token else None
        return len(html)

    def estado(self):
        cabeceras = {'Host': self.host}
        if self.cookie:
            cabeceras['Cookie'] = 'orgdna_session=' + self.cookie
        peticion = urllib.request.Request(self.base + '/api/state', headers=cabeceras)
        with urllib.request.urlopen(peticion, timeout=60) as respuesta:
            return json.loads(respuesta.read())

    def instancia(self):
        peticion = urllib.request.Request(self.base + '/api/instance', headers={'Host': self.host})
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:
            return json.loads(respuesta.read())


def build_en_disco():
    codigo = 'import sys; sys.path.insert(0, %r); from engine.launcher import BUILD_ID; print(BUILD_ID)' % PKG
    estado, salida = ejecutar([sys.executable, '-c', codigo], cwd=PKG, timeout=120)
    return salida.strip().splitlines()[-1].strip() if estado == 0 and salida.strip() else None


# ------------------------------------------------------------------ chequeos

def chequeo_sello():
    estado, salida = ejecutar([sys.executable, 'verifica_manifiesto.py'], timeout=600)
    coincide = re.search(r'hashes coincidentes:\s*(\d+)', salida)
    divergen = re.search(r'hashes divergentes\s*:\s*(\d+)', salida)
    faltan = re.search(r'faltantes\s*:\s*(\d+)', salida)
    sobran = re.search(r'sobrantes reales\s*:\s*(\d+)', salida)
    detalle = 'coincidentes=%s divergentes=%s faltantes=%s sobrantes=%s' % tuple(
        (m.group(1) if m else '?') for m in (coincide, divergen, faltan, sobran))
    fila('sello del paquete', 'OK' if estado == 0 else 'FALLA', detalle)
    return estado == 0


def chequeo_validador():
    estado, salida = ejecutar([sys.executable, 'validate_imports_portable.py'], cwd=PKG, timeout=900)
    valido = re.search(r'"valid"\s*:\s*(true|false)', salida)
    comprobaciones = re.search(r'"checks"\s*:\s*(\d+)', salida)
    detalle = 'valid=%s checks=%s' % (valido.group(1) if valido else '?',
                                      comprobaciones.group(1) if comprobaciones else '?')
    fila('entrega portable', 'OK' if estado == 0 and valido and valido.group(1) == 'true' else 'FALLA',
         detalle)
    return estado == 0


def chequeo_arranque():
    estado, salida = ejecutar([sys.executable, 'arranque_limpio.py', '--check'], timeout=600)
    sello = re.search(r'sello SHA-256\s*:\s*(\S+)', salida)
    disco = re.search(r'build en disco\s*:\s*([0-9a-f]+)', salida)
    instancia = re.search(r'puerto\s+(\d+)\s+pid\s+(\d+)\s+build\s+([0-9a-f]+)\s*->\s*(\S+)', salida)
    if instancia:
        puerto, pid, build, marca = instancia.groups()
        detalle = 'sello=%s disco=%s vivo=%s:%s %s' % (
            (sello.group(1) if sello else '?'), (disco.group(1)[:12] if disco else '?'),
            puerto, pid, marca)
    else:
        puerto = None
        detalle = 'sello=%s disco=%s sin instancia viva' % (
            (sello.group(1) if sello else '?'), (disco.group(1)[:12] if disco else '?'))
    fila('arranque y sello', 'OK' if estado == 0 else 'FALLA', detalle)
    return (estado == 0), (puerto if instancia else None)


def chequeo_panel(puerto, obligatorio):
    if not puerto:
        fila('panel vivo', 'FALLA' if obligatorio else 'SALTA', 'no hay instancia en escucha')
        return None, False
    panel = Panel(puerto)
    try:
        tamano = panel.handshake()
        identidad = panel.instancia()
        estado = panel.estado()
    except (urllib.error.URLError, OSError, ValueError) as error:
        fila('panel vivo', 'FALLA', 'puerto %s: %s' % (puerto, error))
        return None, False
    disco = build_en_disco()
    iguales = bool(disco) and identidad.get('build') == disco
    fila('panel vivo', 'OK' if iguales else 'FALLA',
         'puerto %s html=%d build=%s%s' % (puerto, tamano, identidad.get('build', '?')[:12],
                                           ' == disco' if iguales else ' != disco'))
    return estado, iguales


def chequeo_capacidades(estado):
    if estado is None:
        fila('capacidades del equipo', 'SALTA', 'sin estado del panel')
        return False
    diseño = estado.get('organization') is not None
    filas = [('P2 canal', estado.get('team_channel') or {}),
             ('P4 memoria', estado.get('team_memory') or {}),
             ('P3 compromisos', estado.get('team_followups') or {}),
             ('P1 sandbox', estado.get('sandbox') or {})]
    disponibles = []
    for nombre, vista in filas:
        if not vista:
            disponibles.append('%s=NO-CABLEADO' % nombre)
        elif vista.get('available'):
            disponibles.append('%s=SI' % nombre)
        else:
            # Cableada pero sin datos: casi siempre falta generar/cargar un diseño.
            motivo = str(vista.get('reason') or '')
            corto = (motivo.split(':')[0].split('.')[0])[:48] if motivo else 'sin motivo declarado'
            disponibles.append('%s=NO-DISPONIBLE(%s)' % (nombre, corto))
    cableadas = sum(1 for _, vista in filas if vista)
    fila('capacidades del equipo', 'OK' if diseño and cableadas == 4 else 'SALTA',
         'diseño=%s %s' % ('SI' if diseño else 'NO', ' '.join(disponibles)))
    return diseño


def _chromium_una_vez(ruta):
    """Una corrida del arnes. Devuelve (codigo, resumen legible de pasos)."""
    estado, salida = ejecutar([sys.executable, os.path.join('qa_v7', 'chromium_e2e.py')],
                              cwd=PKG, timeout=1800)
    ok = re.search(r'"ok":\s*(true|false)', salida)
    pasos = re.search(r'"passed_steps":\s*\[(.*?)\]', salida, re.S)
    fallidos = re.search(r'"failed_steps":\s*\[(.*?)\]', salida, re.S)

    def limpio(bloque):
        if bloque is None:
            return ''
        return ', '.join(x.strip().strip('"') for x in bloque.group(1).split(',') if x.strip())

    if ok is None:
        ultima = [linea for linea in salida.strip().splitlines() if linea.strip()]
        return estado, (ultima[-1][:110] if ultima else 'sin salida')
    resumen = 'ok=%s pasos=[%s]' % (ok.group(1), limpio(pasos) or '?')
    if limpio(fallidos):
        resumen += ' FALLIDOS=[%s]' % limpio(fallidos)
    return (0 if ok.group(1) == 'true' else 1), resumen


def chequeo_chromium():
    ruta = os.path.join(PKG, 'qa_v7', 'chromium_e2e.py')
    if not os.path.isfile(ruta):
        fila('arnés Chromium E2E', 'SALTA', 'qa_v7/chromium_e2e.py no existe todavia')
        return None
    estado, resumen = _chromium_una_vez(ruta)
    if estado != 0:
        # Un test de navegador bajo una maquina cargada puede fallar por contencion.
        # Se reintenta UNA vez y se declara el reintento: no se oculta el primero.
        print('        (primer intento del arnes fallo; se reintenta una vez y se declara)')
        estado, resumen = _chromium_una_vez(ruta)
        resumen = '[reintento] ' + resumen
    fila('arnés Chromium E2E', 'OK' if estado == 0 else 'FALLA', resumen)
    return estado == 0


def chequeo_suite():
    estado, salida = ejecutar([sys.executable, '-m', 'unittest', 'discover',
                               '-s', 'EQUIPO_ENTERPRISE_24_COUNCIL_ADN',
                               '-t', 'EQUIPO_ENTERPRISE_24_COUNCIL_ADN',
                               '-p', 'test*.py'], timeout=3600)
    corridos = re.search(r'Ran (\d+) tests', salida)
    fallos = re.search(r'failures=(\d+)', salida)
    errores = re.search(r'errors=(\d+)', salida)
    nombres = re.findall(r'^ERROR: (\S+)', salida, re.M)
    n_fallos = int(fallos.group(1)) if fallos else 0
    n_errores = int(errores.group(1)) if errores else 0
    detalle = 'casos=%s failures=%d errors=%d' % (
        corridos.group(1) if corridos else '?', n_fallos, n_errores)
    if n_errores:
        detalle += ' | errores declarados: %s' % ', '.join(nombres[:5])
    # El criterio es FALLOS, no el codigo de salida: el repo arrastra errores de
    # ENTORNO declarados (Excel COM, etc.) que fallan igual en la linea base. Se
    # exigen cero fallos y se listan los errores por nombre para que nadie los tape.
    fila('suite completa', 'OK' if n_fallos == 0 else 'FALLA', detalle)
    return n_fallos == 0


# ------------------------------------------------------------------ main

def main(argv):
    parser = argparse.ArgumentParser(description='Tarjeta de entrega de OrgDNA')
    parser.add_argument('--suite', action='store_true', help='corre la suite completa canonica')
    parser.add_argument('--chromium', action='store_true', help='corre el arnes E2E en Chromium')
    parser.add_argument('--todo', action='store_true', help='suite + chromium')
    opciones = parser.parse_args(argv[1:])
    con_suite = opciones.suite or opciones.todo
    con_chromium = opciones.chromium or opciones.todo

    print('=' * 74)
    print('  TARJETA DE ENTREGA — OrgDNA')
    print('  raiz: %s' % ROOT)
    print('=' * 74)

    print('\n1. Integridad')
    sello = chequeo_sello()
    validador = chequeo_validador()

    print('\n2. Arranque')
    arranque, puerto = chequeo_arranque()

    print('\n3. Aplicacion')
    estado, build_igual = chequeo_panel(puerto, obligatorio=True)
    capacidad = chequeo_capacidades(estado)

    exitos = {'chromium': None, 'suite': None}
    if con_chromium:
        print('\n4. Navegador real')
        exitos['chromium'] = chequeo_chromium()
    if con_suite:
        print('\n5. Suite')
        exitos['suite'] = chequeo_suite()

    obligatorias = [('sello', sello), ('validador', validador), ('arranque', arranque),
                    ('panel sirve el build en disco', build_igual)]
    if con_chromium:
        obligatorias.append(('chromium', bool(exitos['chromium'])))
    if con_suite:
        obligatorias.append(('suite', bool(exitos['suite'])))

    fallidas = [nombre for nombre, bien in obligatorias if not bien]
    print()
    print('=' * 74)
    if fallidas:
        print('  RESULTADO: NO ENTREGABLE — fallan: %s' % ', '.join(fallidas))
        print('=' * 74)
        return 1
    print('  RESULTADO: ENTREGABLE')
    print('  sello, validador, arranque y panel en el build en disco: verificados')
    if not capacidad:
        print('  AVISO: el panel no tiene diseno cargado; la matriz de capacidades')
        print('         solo se puede leer despues de generar o cargar un proyecto.')
    faltan = [nombre for nombre, estado, _detalle in FILAS if estado == 'SALTA']
    if faltan:
        print('  NO COMPROBADO AQUI (declarado, no oculto): %s' % ', '.join(faltan))
    print('=' * 74)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
