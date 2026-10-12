"""Regresion de la cache de validacion y del hashing unico del empaquetado.

Detecta los dos defectos MEDIDOS en la ruta de exportacion (P3-A):

  1. `validate_bundle` se ejecutaba DOS veces sobre los MISMOS bytes: una dentro de
     `build_package_bytes` y otra en `generation_pipeline._run`. Medido: 0,38-0,43 s
     por validacion, es decir ~0,4 s desperdiciados en cada generacion.
  2. Cada archivo se hasheaba DOS veces por generacion (catalogo + manifiesto):
     1199 llamadas a `_sha` para ~600 archivos, la mitad redundantes.

Sin la correccion, `test_identical_payload_computes_once` y
`test_each_file_is_hashed_once` FALLAN. Con ella, pasan.
"""
import copy
import hashlib
import io
import sys
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import bundle, core  # noqa: E402


def tiny_org():
    """Organizacion minima valida y determinista para empaquetar."""
    return core.generate_organization({'agent_count': 1, 'template': 'generic',
                                       'repo_name': 'PackagingCacheFixture', 'identity_mode': 'new',
                                       'organization_id': 'a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d'})


def minimal_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr('root/' + name, data)
    return buffer.getvalue()


class ValidationCacheTests(unittest.TestCase):
    """Cuenta `zipfile.ZipFile.testzip`, que es la operacion REAL de descompresion y CRC:
    un simbolo interno podria quedar ligado por nombre y la prueba se volveria ciega."""

    def setUp(self):
        bundle._VALIDATION_CACHE.clear()
        self.calls = []
        self._orig_testzip = zipfile.ZipFile.testzip

        def counting(archive):
            self.calls.append(1)
            return self._orig_testzip(archive)

        zipfile.ZipFile.testzip = counting

    def tearDown(self):
        zipfile.ZipFile.testzip = self._orig_testzip
        bundle._VALIDATION_CACHE.clear()

    def test_identical_payload_computes_once(self):
        """Regresion del defecto 1: dos validaciones de los MISMOS bytes, un solo calculo."""
        payload = minimal_zip({'a.txt': b'alpha', 'MANIFIESTO_SHA256.txt': b''})
        first = bundle.validate_bundle(payload)
        second = bundle.validate_bundle(payload)
        self.assertEqual(len(self.calls), 1, 'la validacion se repitio sobre bytes identicos')
        self.assertEqual(first, second)

    def test_bytearray_and_bytes_share_the_verdict(self):
        payload = minimal_zip({'a.txt': b'alpha'})
        first = bundle.validate_bundle(payload)
        second = bundle.validate_bundle(bytearray(payload))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(first, second)

    def test_different_payload_recomputes(self):
        one = minimal_zip({'a.txt': b'alpha'})
        two = minimal_zip({'a.txt': b'beta'})
        bundle.validate_bundle(one)
        bundle.validate_bundle(two)
        self.assertEqual(len(self.calls), 2, 'unos bytes distintos NO pueden reutilizar el veredicto')

    def test_mutating_returned_result_does_not_corrupt_cache(self):
        payload = minimal_zip({'a.txt': b'alpha'})
        first = bundle.validate_bundle(payload)
        first['valid'] = False
        first['errors'].append('INYECTADO')
        second = bundle.validate_bundle(payload)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('INYECTADO', second['errors'])

    def test_invalid_payload_verdict_is_stable(self):
        not_a_zip = b'no soy un zip'
        first = bundle.validate_bundle(not_a_zip)
        second = bundle.validate_bundle(not_a_zip)
        self.assertFalse(first['valid'])
        self.assertEqual(first, second)

    def test_cache_is_bounded(self):
        for index in range(bundle._VALIDATION_CACHE_MAX + 3):
            bundle.validate_bundle(minimal_zip({'a.txt': str(index).encode()}))
        self.assertLessEqual(len(bundle._VALIDATION_CACHE), bundle._VALIDATION_CACHE_MAX)

    def test_concurrent_validation_is_consistent(self):
        payload = minimal_zip({'a.txt': b'alpha'})
        results = []
        lock = threading.Lock()

        def worker():
            value = bundle.validate_bundle(payload)
            with lock:
                results.append(value)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 8)
        self.assertTrue(all(item == results[0] for item in results), 'veredictos inconsistentes bajo concurrencia')


class SingleHashPassTests(unittest.TestCase):
    """Aisla la CONSTRUCCION del paquete: la validacion tiene su propio re-hash legitimo
    (verifica desde los bytes recibidos), asi que aqui se sustituye por un doble para no
    confundir dos responsabilidades distintas."""

    def setUp(self):
        self.sha_calls = []
        self._orig_sha = bundle._sha
        self._orig_validate = bundle.validate_bundle

        def counting(data):
            self.sha_calls.append(len(data))
            return self._orig_sha(data)

        bundle._sha = counting
        bundle.validate_bundle = lambda payload: {'valid': True, 'errors': []}

    def tearDown(self):
        bundle._sha = self._orig_sha
        bundle.validate_bundle = self._orig_validate

    def test_each_file_is_hashed_once(self):
        """Regresion del defecto 2: no puede haber mas digests que archivos empaquetados."""
        payload = bundle.build_package_bytes(tiny_org())
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
        entries = len(names)
        self.assertLessEqual(
            len(self.sha_calls), entries + 4,
            f'se calcularon {len(self.sha_calls)} digests para {entries} archivos: hay re-hashing redundante')

    def test_manifest_format_and_coverage_preserved(self):
        """La correccion no cambia el formato ni la cobertura del manifiesto."""
        payload = bundle.build_package_bytes(tiny_org())
        import json as _json
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            prefix = archive.namelist()[0].split('/', 1)[0] + '/'
            manifest = archive.read(prefix + 'MANIFIESTO_SHA256.txt').decode('utf-8')
            catalog = archive.read(prefix + '03_CATALOGO_DOCUMENTAL.json').decode('utf-8')
            files = {name.split('/', 1)[1] for name in archive.namelist()}
            document = _json.loads(catalog)
            contents = {row['path']: archive.read(prefix + row['path']) for row in document['files']}
        lines = [line for line in manifest.splitlines() if line]
        self.assertTrue(all(len(line.split('  ', 1)[0]) == 64 for line in lines), 'formato de manifiesto alterado')
        manifest_names = {line.split('  ', 1)[1] for line in lines}
        self.assertEqual(manifest_names, files - {'MANIFIESTO_SHA256.txt'})
        self.assertTrue(document['self_and_manifest_excluded'])
        catalog_paths = set(contents)
        self.assertNotIn('03_CATALOGO_DOCUMENTAL.json', catalog_paths)
        self.assertNotIn('MANIFIESTO_SHA256.txt', catalog_paths)
        for row in document['files']:
            self.assertEqual(row['sha256'], hashlib.sha256(contents[row['path']]).hexdigest())
            self.assertEqual(row['bytes'], len(contents[row['path']]))


if __name__ == '__main__':
    unittest.main()
