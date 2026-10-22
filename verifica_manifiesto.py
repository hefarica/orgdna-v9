#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verificador independiente del sello SHA-256 del paquete OrgDNA V9.

Recalcula los hashes de TODAS las entradas de MANIFIESTO_SHA256.txt sobre los
bytes reales en disco y reporta cualquier discrepancia. No depende de ningún
módulo del producto: solo stdlib, para poder ejecutarlo en un clon limpio y
demostrar que el sello sobrevive al transporte por Git.

Uso:
    python verifica_manifiesto.py [ruta_al_paquete]

Salida: código 0 si todas las entradas coinciden; 1 si hay discrepancia,
faltantes o sobrantes.
"""
import hashlib
import os
import sys

PKG_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'EQUIPO_ENTERPRISE_24_COUNCIL_ADN')

# Rutas del paquete deliberadamente FUERA del sello. No son un olvido:
#  - data/ es estado de ejecución (versiones de proyecto, registro de
#    capacidades) que el producto reescribe al usarse; sellarlo lo invalidaría
#    en el primer arranque.
#  - docs/PLATAFORMA_VERIFICACION_V1.md es el expediente de verificación, que
#    debe poder revisarse sin obligar a re-sellar el paquete entero.
# Cualquier OTRO archivo no declarado sí es un fallo.
EXENTOS = (
    'data/',
    'docs/PLATAFORMA_VERIFICACION_V1.md',
)


def _exento(rel):
    for prefix in EXENTOS:
        if rel == prefix or rel.startswith(prefix):
            return True
    return False


def main(argv):
    pkg = argv[1] if len(argv) > 1 else PKG_DEFAULT
    manifest = os.path.join(pkg, 'MANIFIESTO_SHA256.txt')
    if not os.path.isfile(manifest):
        print('FALLO: no existe %s' % manifest)
        return 1

    with open(manifest, 'rb') as fh:
        raw = fh.read()
    lines = [l for l in raw.decode('utf-8').split('\n') if l.strip()]

    ok = 0
    bad = []
    missing = []
    declared = set()
    for line in lines:
        if '  ' not in line:
            bad.append((line, 'linea mal formada (sin doble espacio)'))
            continue
        digest, name = line.split('  ', 1)
        declared.add(name)
        path = os.path.join(pkg, name.replace('/', os.sep))
        if not os.path.isfile(path):
            missing.append(name)
            continue
        with open(path, 'rb') as fh:
            real = hashlib.sha256(fh.read()).hexdigest()
        if real == digest:
            ok += 1
        else:
            bad.append((name, 'declarado %s / real %s' % (digest[:16], real[:16])))

    # Sobrantes: archivos del paquete que el manifiesto no declara.
    skip_dirs = {'__pycache__'}
    skip_names = {'MANIFIESTO_SHA256.txt'}
    extra = []
    exentos = []
    for root, dirs, files in os.walk(pkg):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), pkg).replace(os.sep, '/')
            if os.path.basename(rel) in skip_names:
                continue
            if rel in declared:
                continue
            if _exento(rel):
                exentos.append(rel)
            else:
                extra.append(rel)

    print('paquete           : %s' % pkg)
    print('entradas manifiesto: %d' % len(lines))
    print('hashes coincidentes: %d' % ok)
    print('hashes divergentes : %d' % len(bad))
    print('faltantes          : %d' % len(missing))
    print('exentos declarados : %d' % len(exentos))
    print('sobrantes reales   : %d' % len(extra))
    for name, why in bad:
        print('  DIVERGE   %s  (%s)' % (name, why))
    for name in missing:
        print('  FALTA     %s' % name)
    for name in extra:
        print('  SOBRANTE  %s' % name)

    if bad or missing or extra or ok != len(lines):
        print('\nRESULTADO: FALLO')
        return 1
    print('\nRESULTADO: OK - integridad del sello verificada sobre bytes en disco')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
