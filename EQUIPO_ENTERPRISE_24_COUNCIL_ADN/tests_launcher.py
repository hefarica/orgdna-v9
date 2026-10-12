"""Offline startup regression tests. No real browser, DSH or external requests."""
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from engine import launcher


class LauncherTests(unittest.TestCase):
    def serve(self, payload, status=200):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                data = payload(self.server.server_address[1]) if callable(payload) else payload
                self.wfile.write(json.dumps(data).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_identity_is_minimal(self):
        value = launcher.instance_identity('http://127.0.0.1:8765', '/private/file.xlsx')
        self.assertNotIn('/private', json.dumps(value))
        self.assertNotIn('csrf', value)
        self.assertNotIn('session', value)

    def test_valid_instance(self):
        port = self.serve(lambda p: launcher.instance_identity(f'http://127.0.0.1:{p}'))
        self.assertTrue(launcher.probe_instance(port))

    def test_foreign_service(self):
        port = self.serve({'status': 'ok', 'service': 'DSH'})
        self.assertFalse(launcher.probe_instance(port))

    def test_wrong_installation_version_build_workbook_origin(self):
        for field in ('installation', 'version', 'build', 'workbook', 'origin', 'application', 'protocol'):
            with self.subTest(field=field):
                def data(port):
                    value = launcher.instance_identity(f'http://127.0.0.1:{port}')
                    value[field] = 'other'
                    return value
                port = self.serve(data)
                self.assertFalse(launcher.probe_instance(port))

    def test_reuse_never_binds(self):
        with patch.object(launcher, 'probe_instance', return_value=True):
            factory = unittest.mock.Mock()
            server, origin = launcher.select_server(factory, 8765)
            factory.assert_not_called()
            self.assertIsNone(server)
            self.assertEqual(origin, 'http://127.0.0.1:8765')

    def test_busy_falls_back_without_touching_service(self):
        with patch.object(launcher, 'probe_instance', return_value=False):
            factory = unittest.mock.Mock(side_effect=[OSError(errno.EADDRINUSE, 'busy'), 'bound'])
            self.assertEqual(launcher.select_server(factory, 8765, output=lambda _: None), ('bound', None))
            self.assertEqual(factory.call_args_list, [unittest.mock.call(('127.0.0.1', 8765), None), unittest.mock.call(('127.0.0.1', 0), None)])

    def test_windows_denied_recovers(self):
        failure = OSError(errno.EACCES, 'reserved')
        failure.winerror = 10013
        self.assertTrue(launcher.recoverable_bind_error(failure))
        self.assertIn('winerror=10013', launcher.bind_diagnostic(failure, 8765))
        self.assertIn('reservado', launcher.bind_diagnostic(failure, 8765))

    def test_unexpected_errno_does_not_fallback(self):
        with patch.object(launcher, 'probe_instance', return_value=False):
            factory = unittest.mock.Mock(side_effect=OSError(errno.EMFILE, 'resource limit'))
            with self.assertRaises(OSError):
                launcher.select_server(factory, 8765, output=lambda _: None)
            self.assertEqual(factory.call_count, 1)

    def test_strict_port_does_not_fallback(self):
        with patch.object(launcher, 'probe_instance', return_value=False):
            factory = unittest.mock.Mock(side_effect=OSError(errno.EADDRINUSE, 'busy'))
            with self.assertRaises(OSError):
                launcher.select_server(factory, 8765, strict=True, output=lambda _: None)
            self.assertEqual(factory.call_count, 1)

    def test_bind_race_reuses_compatible_instance(self):
        with patch.object(launcher, 'probe_instance', side_effect=[False, True]):
            factory = unittest.mock.Mock(side_effect=OSError(errno.EADDRINUSE, 'busy'))
            self.assertEqual(launcher.select_server(factory, 8765, output=lambda _: None), (None, 'http://127.0.0.1:8765'))
            self.assertEqual(factory.call_count, 1)

    def test_record_is_validated_and_existing_port_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'instance.json'
            launcher.remember_port(path, 45678)
            self.assertEqual(launcher.remembered_port(path), 45678)
            with patch.object(launcher, 'probe_instance', side_effect=[False, True]) as probe:
                factory = unittest.mock.Mock()
                self.assertEqual(launcher.select_server(factory, 8765, record=path), (None, 'http://127.0.0.1:45678'))
                factory.assert_not_called()
                self.assertEqual(probe.call_args_list[-1], unittest.mock.call(45678, None))
            for bad in ('null', '[]', '{"port": true}', '{"port": "45678"}', '{"port": 65536}', 'broken'):
                path.write_text(bad)
                self.assertIsNone(launcher.remembered_port(path))

    def test_startup_lock_serializes_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'startup.lock'
            with launcher.StartupLock(path):
                with self.assertRaises(TimeoutError):
                    with launcher.StartupLock(path, timeout=.05):
                        self.fail('second lock acquired')
            with launcher.StartupLock(path, timeout=.05):
                pass
            self.assertTrue(path.exists())

    def test_windows_lock_adapter_locks_one_byte(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = launcher.StartupLock(Path(folder) / 'startup.lock')
            api = unittest.mock.Mock(LK_NBLCK=2)
            with patch.dict('sys.modules', {'msvcrt': api}), patch.object(launcher.os, 'name', 'nt'):
                with lock:
                    api.locking.assert_called_once_with(lock.file.fileno(), 2, 1)
                self.assertIsNone(lock.file)

    def test_invalid_cli_port(self):
        with self.assertRaises(SystemExit) as exc:
            launcher.main(['--port', '-1'])
        self.assertEqual(exc.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
