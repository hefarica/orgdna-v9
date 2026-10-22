#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Re-sella el paquete OrgDNA V9: catalogo documental + manifiesto + huella publicada.

Reproduce exactamente la regla del empaquetador (`engine/bundle.py`):
  - el catalogo enumera todos los entregables salvo el mismo y el manifiesto;
  - el manifiesto cubre todos los entregables salvo el mismo;
  - la huella publicada en el acta es el SHA-256 del manifiesto con las DOS
    lineas enmascaradas, que son las unicas cuyo digest depende del valor
    publicado (el acta es una de ellas, y por eso escribirla ahi no la invalida).

Es idempotente: deriva el conjunto de archivos del DISCO, informa de lo que
cambio respecto al manifiesto vigente y se autoverifica al final.

Uso:  python resella_paquete.py
Salida: codigo 0 si el sello queda coherente; 1 si la autoverificacion falla.
"""
import hashlib
import io
import os
import re
import sys

PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   'EQUIPO_ENTERPRISE_24_COUNCIL_ADN')
CATALOG = '03_CATALOGO_DOCUMENTAL.json'
MANIFEST = 'MANIFIESTO_SHA256.txt'
ACTA = 'docs/PLATAFORMA_ENTREGA_V9.md'
MARKER = 'PENDIENTE_DE_MANIFIESTO'
MASKED = {CATALOG, ACTA}
PROJECT = 'ArbitrageX'
AGENT_COUNT = 24

# Fuera del sello por diseno: ver el mismo criterio en verifica_manifiesto.py
#  - data/                       : estado de ejecucion que el producto reescribe.
#  - PLATAFORMA_VERIFICACION_V1  : expediente de verificacion revisable sin re-sellar.
#  - docs/rea/evidence/chromium/ : SALIDA VOLATIL del arnes E2E (PNG + report.json con
#    marca de tiempo). Sellarla obligaria a re-sellar tras cada corrida del arnes; los
#    demas ficheros de docs/rea/evidence/ (evidencia fija de la mision) SIGUEN sellados.
EXENTOS = ('data/', 'docs/PLATAFORMA_VERIFICACION_V1.md', 'docs/rea/evidence/chromium/')


def _exento(rel):
    return any(rel == p or rel.startswith(p) for p in EXENTOS)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(name):
    with open(os.path.join(PKG, name.replace('/', os.sep)), 'rb') as fh:
        return fh.read()


def write(name, data):
    with open(os.path.join(PKG, name.replace('/', os.sep)), 'wb') as fh:
        fh.write(data)


def discover():
    found = set()
    for root, dirs, files in os.walk(PKG):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), PKG).replace(os.sep, '/')
            if rel == MANIFEST or _exento(rel):
                continue
            found.add(rel)
    return found


def current_manifest_names():
    path = os.path.join(PKG, MANIFEST)
    if not os.path.isfile(path):
        return set()
    text = io.open(path, encoding='utf-8').read()
    return {line.split('  ', 1)[1] for line in text.splitlines() if line.strip()}


def _sync_declared_counts(acta_path, manifest_count, catalog_count, allowlist_count):
    """Reescribe los conteos que el acta DECLARA, para que no puedan quedar mintiendo.

    El sello ya obligaba a recomputar la huella enmascarada; los conteos en prosa y
    la linea maquina-legible `MANIFIESTO_FILE_COUNT` se actualizaban a mano y por eso
    quedaron en 342 cuando el manifiesto tenia 360. Cada patron debe aparecer
    exactamente una vez: si el acta cambia de forma, esto falla en vez de callarse.
    """
    acta = io.open(acta_path, encoding='utf-8').read()
    reemplazos = (
        (r'MANIFIESTO_FILE_COUNT \d+', 'MANIFIESTO_FILE_COUNT %d' % manifest_count),
        (r'\|\s*Manifiesto\s*\|\s*\d+ entradas', '| Manifiesto | %d entradas' % manifest_count),
        (r'\|\s*Entradas del manifiesto\s*\|\s*`\d+`\s*\|',
         '| Entradas del manifiesto | `%d` |' % manifest_count),
        (r'\|\s*Allowlist\s*\|\s*`\d+` entradas\s*\|',
         '| Allowlist | `%d` entradas |' % allowlist_count),
        (r'De las \d+ entradas', 'De las %d entradas' % manifest_count),
        (r'`03_CATALOGO_DOCUMENTAL\.json` \(\d+ entradas\)',
         '`03_CATALOGO_DOCUMENTAL.json` (%d entradas)' % catalog_count),
    )
    for pattern, replacement in reemplazos:
        matches = re.findall(pattern, acta)
        if len(matches) != 1:
            print('FALLO: el patron %r aparece %d veces en el acta (se esperaba 1)'
                  % (pattern, len(matches)))
            return False
        acta = re.sub(pattern, replacement, acta, count=1)
    io.open(acta_path, 'w', encoding='utf-8', newline='').write(acta)
    return True


def main():
    sys.path.insert(0, PKG)
    from engine.bundle import _json_bytes, RUNTIME_ALLOWLIST

    names = discover()
    others = sorted(n for n in names if n != CATALOG)
    previous = current_manifest_names()
    added, removed = sorted(names - previous), sorted(previous - names)
    print('archivos entregables : %d' % len(names))
    print('  altas vs manifiesto: %s' % (added or 'ninguna'))
    print('  bajas vs manifiesto: %s' % (removed or 'ninguna'))
    if CATALOG not in names:
        print('FALLO: falta %s' % CATALOG)
        return 1

    # 1. Huella publicada: solo depende de las lineas NO enmascaradas.
    unmasked = {n: sha(read(n)) for n in names if n not in MASKED}
    rebuilt = ''.join('%s  %s\n' % (MARKER if n in MASKED else unmasked[n], n)
                      for n in sorted(names))
    masked_hash = sha(rebuilt.encode('utf-8'))

    # 2. Publicarla en el acta (que es una linea enmascarada: no realimenta).
    acta_path = os.path.join(PKG, ACTA.replace('/', os.sep))
    acta = io.open(acta_path, encoding='utf-8').read()
    pattern = re.compile(r'MANIFIESTO_SHA256_SIN_ESPEJO [0-9a-f]{64}')
    if len(pattern.findall(acta)) != 1:
        print('FALLO: la huella debe declararse exactamente una vez en el acta')
        return 1
    acta = pattern.sub('MANIFIESTO_SHA256_SIN_ESPEJO ' + masked_hash, acta, count=1)
    io.open(acta_path, 'w', encoding='utf-8', newline='').write(acta)

    # 2-bis. Conteos declarados en el acta. Va AQUI (antes de digerir el catalogo)
    # porque el acta se digiere en el paso 3: sincronizarlo despues dejaria su linea
    # del manifiesto apuntando a los bytes viejos.
    if not _sync_declared_counts(acta_path, len(names), len(others), len(RUNTIME_ALLOWLIST)):
        return 1

    # 3. Catalogo (excluye al catalogo y al manifiesto; el acta SI va dentro).
    digests = {n: sha(read(n)) for n in others}
    catalog = _json_bytes({
        'format': 'orgdna/document-catalog', 'version': 1,
        'agent_count': AGENT_COUNT, 'project': PROJECT,
        'files': [{'path': n, 'bytes': len(read(n)), 'sha256': digests[n]} for n in others],
        'self_and_manifest_excluded': True,
        'historical_private_source_catalog_included': False,
    })
    write(CATALOG, catalog)
    digests[CATALOG] = sha(catalog)

    # 4. Manifiesto.
    manifest = ''.join(digests[n] + '  ' + n + '\n' for n in sorted(names))
    write(MANIFEST, manifest.encode('utf-8'))

    print('catalogo             : %d entradas' % len(others))
    print('manifiesto           : %d entradas  sha256 %s' % (len(names), sha(manifest.encode('utf-8'))))
    print('huella enmascarada   : %s' % masked_hash)

    # 5. Autoverificacion: recomputar la huella DESDE el manifiesto escrito.
    written = io.open(os.path.join(PKG, MANIFEST), encoding='utf-8').read()
    entries = [line.split('  ', 1) for line in written.splitlines() if line.strip()]
    if len(entries) != len(names):
        print('FALLO: el manifiesto escrito tiene %d entradas, se esperaban %d'
              % (len(entries), len(names)))
        return 1
    rebuilt2 = ''.join('%s  %s\n' % (MARKER if n in MASKED else d, n) for d, n in entries)
    recomputed = sha(rebuilt2.encode('utf-8'))
    published = pattern.findall(io.open(acta_path, encoding='utf-8').read())[0].split()[-1]
    print()
    print('=== AUTOVERIFICACION ===')
    print('  recomputada desde el manifiesto: %s' % recomputed)
    print('  publicada en el acta           : %s' % published)
    if recomputed != published:
        print('FALLO: la huella publicada no se reconstruye')
        return 1
    print('RESULTADO: sello coherente')
    return 0


if __name__ == '__main__':
    sys.exit(main())
