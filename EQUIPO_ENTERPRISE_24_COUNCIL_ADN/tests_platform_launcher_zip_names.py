"""Contrato de nombres de entrada ZIP en el respaldo del lanzador DSH.

Regresion de un defecto real y medido: los nombres de entrada se construian con
os.sep ('\\' en Windows) mientras zipfile los normaliza a '/' al escribir
(ZipInfo reemplaza os.sep). El respaldo se escribia correctamente y despues no
podia leer su propia lista de entradas:

    KeyError: "There is no item named '0\\history.json' in the archive"

Consecuencia: dsh-launch-backup no podia completarse NUNCA en Windows, y el
error real quedaba enmascarado por un except generico que decia "revisa las
rutas", apuntando al sitio equivocado.

En POSIX os.sep es '/' y el defecto es INVISIBLE: el respaldo funciona. Por eso
estos casos comprueban el FORMATO del nombre y no solo el resultado; de lo
contrario la regresion volveria sin ser detectada en Linux o macOS.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engine.dsh_launcher import DSHLauncher, LauncherError, digest


class ZipEntryNameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.script = self.root / 'DSH_RELANZAR_TODO.bat'
        self.script.write_text('@echo off\nDSH_REINICIAR.exe\n')
        self.exe = self.root / 'DSH_REINICIAR.exe'
        self.exe.write_bytes(b'MZfixture-only')
        self.data = self.root / 'state'
        self.data.mkdir()
        (self.data / 'history.json').write_text('{"history":"original"}')
        self.nested = self.data / 'sub' / 'deep'
        self.nested.mkdir(parents=True)
        (self.nested / 'leaf.txt').write_text('hoja')
        self.manager = DSHLauncher(self.root / 'backups')
        pin = patch('engine.dsh_launcher.KNOWN_BINARIES',
                    frozenset({digest(self.exe.read_bytes())}))
        pin.start()
        self.addCleanup(pin.stop)
        self.body = {'script_path': str(self.script), 'exe_path': str(self.exe),
                     'operation': 'restart', 'ports': [15000, 15001],
                     'backup_paths': [str(self.data)]}

    def tearDown(self):
        self.tmp.cleanup()

    def token(self):
        self.manager.apply('dsh-launch-inspect', self.body)
        return {'plan_sha256': self.manager.public()['plan']['plan_sha256']}

    def run_backup(self):
        token = self.token()
        self.manager.apply('dsh-launch-backup', {**token, 'backup_confirmed': True})
        return self.manager.public()['backup']

    def test_entry_name_uses_forward_slashes_only(self):
        name = DSHLauncher._entry_name(0, Path('a') / 'b' / 'c.txt')
        self.assertEqual(name, '0/a/b/c.txt')
        self.assertNotIn('\\', name)
        self.assertEqual(name.count(os.sep), 0 if os.sep != '/' else name.count('/'))

    def test_entry_name_index_prefix_is_positional(self):
        for index in (0, 1, 7, 42):
            self.assertTrue(DSHLauncher._entry_name(index, Path('x.txt')).startswith('%d/' % index))

    def test_inventory_names_are_zip_conformant(self):
        names = DSHLauncher._inventory([self.data])
        self.assertTrue(names)
        for name in names:
            self.assertNotIn('\\', name, 'nombre no conforme a APPNOTE 4.4.17.1: %r' % name)
            head, _, tail = name.partition('/')
            self.assertTrue(head.isdigit(), 'prefijo de indice ausente: %r' % name)
            self.assertTrue(tail, 'ruta vacia tras el indice: %r' % name)

    def test_nested_directories_keep_structure_with_forward_slashes(self):
        names = DSHLauncher._inventory([self.data])
        self.assertIn('0/sub/deep/leaf.txt', names)

    def test_backup_archive_names_match_declared_entries(self):
        """La asimetria exacta que causaba el KeyError.

        zipfile normaliza os.sep al escribir, pero el manifiesto interno
        conservaba el nombre sin normalizar. Si ambos lados no coinciden, la
        verificacion del propio respaldo es imposible.
        """
        backup = self.run_backup()
        archive_path = self.root / 'backups' / backup['filename']
        import zipfile
        with zipfile.ZipFile(archive_path) as z:
            stored = set(z.namelist())
            declared = {e['entry'] for e in json.loads(z.read('manifest.json'))['files']}
        self.assertEqual(stored - {'manifest.json'}, declared)
        self.assertEqual(declared, DSHLauncher._inventory([self.data]))

    def test_backup_completes_and_reports_verified_file_copy(self):
        backup = self.run_backup()
        self.assertEqual(backup['status'], 'VERIFIED_FILE_COPY')
        self.assertEqual(backup['application_consistency'], 'UNVERIFIED')
        self.assertGreaterEqual(backup['file_count'], 2)

    def test_single_file_root_uses_index_prefix(self):
        names = DSHLauncher._inventory([self.data / 'history.json'])
        self.assertEqual(names, {'0/history.json'})

    def test_masked_backup_failure_chains_the_original_cause(self):
        """El mensaje sigue siendo el mismo, pero la causa ya no se pierde.

        Con `from None` un fallo interno era indistinguible de un fallo de rutas.
        """
        token = self.token()
        with patch.object(self.manager, '_inventory', side_effect=RuntimeError('causa-interna')):
            with self.assertRaises(LauncherError) as caught:
                self.manager.apply('dsh-launch-backup', {**token, 'backup_confirmed': True})
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        self.assertEqual(str(caught.exception.__cause__), 'causa-interna')

    def test_failed_backup_leaves_no_partial_archive(self):
        token = self.token()
        with patch.object(self.manager, '_inventory', side_effect=RuntimeError('causa-interna')):
            with self.assertRaises(LauncherError):
                self.manager.apply('dsh-launch-backup', {**token, 'backup_confirmed': True})
        leftovers = list((self.root / 'backups').glob('dsh-*.zip'))
        self.assertEqual(leftovers, [])


if __name__ == '__main__':
    unittest.main()
