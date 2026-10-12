"""P3-A · Desglose del coste interno de build_package_bytes.

Instrumenta en memoria (sin tocar el árbol) para separar:
  - lectura de archivos runtime desde disco,
  - hashing (que hoy ocurre DOS veces por archivo: catalogo + manifiesto),
  - empaquetado DEFLATE,
  - validación final del bundle.

Uso: python p3a_desglose_package.py <ruta_al_arbol> [repeticiones]
"""
import sys
import time
import unittest
import zipfile

tree = sys.argv[1]
reps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
sys.path.insert(0, tree)

from engine import bundle  # noqa: E402

stats = {'sha_calls': 0, 'sha_time': 0.0, 'read_time': 0.0, 'validate_time': 0.0, 'zip_time': 0.0}

_sha_orig = bundle._sha
_read_orig = bundle._read_runtime
_validate_orig = bundle.validate_bundle


def sha_timed(data):
    started = time.perf_counter()
    try:
        return _sha_orig(data)
    finally:
        stats['sha_calls'] += 1
        stats['sha_time'] += time.perf_counter() - started


def read_timed(*args, **kwargs):
    started = time.perf_counter()
    try:
        return _read_orig(*args, **kwargs)
    finally:
        stats['read_time'] += time.perf_counter() - started


def validate_timed(*args, **kwargs):
    started = time.perf_counter()
    try:
        return _validate_orig(*args, **kwargs)
    finally:
        stats['validate_time'] += time.perf_counter() - started


_writestr_orig = zipfile.ZipFile.writestr


def writestr_timed(self, *args, **kwargs):
    started = time.perf_counter()
    try:
        return _writestr_orig(self, *args, **kwargs)
    finally:
        stats['zip_time'] += time.perf_counter() - started


bundle._sha = sha_timed
bundle._read_runtime = read_timed
bundle.validate_bundle = validate_timed
zipfile.ZipFile.writestr = writestr_timed

# Construye una organización real determinista (mismo camino que tests_capability_exports.py:15).
from engine import core  # noqa: E402

org = core.generate_organization({'agent_count': 24, 'template': 'generic', 'repo_name': 'OfflineFixture',
                                  'identity_mode': 'new',
                                  'organization_id': 'bf99bba8-93e8-4d41-97b3-ed45b73f24f9'})

print(f'ARBOL: {tree}')
print(f'ORGANIZACION: {len(org["agents"])} agentes')
print()
print(f'{"rep":>3} {"TOTAL":>8} {"sha":>8} {"read":>8} {"zip(writestr)":>14} {"validate":>9} {"docs+resto":>11} {"sha_calls":>9}')
for index in range(1, reps + 1):
    before = dict(stats)
    started = time.perf_counter()
    payload = bundle.build_package_bytes(org)
    total = time.perf_counter() - started
    sha_time = stats['sha_time'] - before['sha_time']
    read_time = stats['read_time'] - before['read_time']
    zip_time = stats['zip_time'] - before['zip_time']
    validate_time = stats['validate_time'] - before['validate_time']
    sha_calls = stats['sha_calls'] - before['sha_calls']
    docs = total - sha_time - read_time - zip_time - validate_time
    print(f'{index:>3} {total:>8.3f} {sha_time:>8.3f} {read_time:>8.3f} {zip_time:>14.3f} {validate_time:>9.3f} {docs:>11.3f} {sha_calls:>9}')

print()
print(f'PAQUETE: {len(payload)} bytes')
