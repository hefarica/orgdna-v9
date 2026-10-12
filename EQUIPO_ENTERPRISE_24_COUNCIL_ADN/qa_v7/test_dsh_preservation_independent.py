"""Byte-preservation contract against the delivered V6 ZIP; no DSH is started."""
import ast
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASELINE = json.loads((Path(__file__).parent / 'dsh_baseline.json').read_text())

def sha(value):
    return hashlib.sha256(value).hexdigest()

class DshPreservationIndependent(unittest.TestCase):
    def test_dsh_runtime_launcher_and_cordis_bytes_unchanged(self):
        for name, expected in BASELINE['files'].items():
            with self.subTest(file=name):
                self.assertEqual(sha((ROOT / name).read_bytes()), expected)

    def test_dsh_javascript_functions_unchanged(self):
        source = (ROOT / 'web/app.js').read_text()
        actual = {}
        for match in re.finditer(r'^(?:async )?function (\w+)\(', source, re.M):
            if match[1] in BASELINE['javascript_functions']:
                end = re.search(r'^(?:async )?function ', source[match.end():], re.M)
                actual[match[1]] = sha(source[match.start():match.end() + end.start() if end else len(source)].encode())
        self.assertEqual(actual, BASELINE['javascript_functions'])

    def test_dsh_javascript_event_handlers_unchanged(self):
        source = (ROOT / 'web/app.js').read_text()
        lines = [line for line in source.splitlines() if re.match(r"\$\('#(?:dsh|harness|cordis|prepare-cordis)", line)]
        self.assertEqual(sha('\n'.join(lines).encode()), BASELINE['javascript_handler_lines_sha256'])

    def test_dsh_bridge_dispatch_branches_unchanged(self):
        source = (ROOT / 'engine/bridge.py').read_text()
        actual = {}
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.If) and ast.unparse(node.test) in BASELINE['bridge_dispatch_branches']:
                actual[ast.unparse(node.test)] = sha('\n'.join(source.splitlines()[node.lineno - 1:node.end_lineno]).encode())
        self.assertEqual(actual, BASELINE['bridge_dispatch_branches'])

if __name__ == '__main__':
    unittest.main()
