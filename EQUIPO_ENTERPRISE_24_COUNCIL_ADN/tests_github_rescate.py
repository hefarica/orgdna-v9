#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""El rescate del 403 de GitHub: token legitimo y verdad sobre la cuota.

GITHUB-Token del operador -> cuota 60/h -> 5.000/h. La via LEGITIMA: nunca evasion.
"""
import json
import unittest

from engine import providers as p

COMMIT_SHA = "c" * 40
TREE_SHA = "1" * 40


def transporte_repo(vistos, token=None):
    """Fixture del canal GitHub con las rutas en el orden correcto:
    /git/commits/ es mas especifica que /commits/ y va PRIMERO."""

    def transporte(method, url, headers, body, timeout, max_bytes):
        vistos[url] = dict(headers)
        if "/git/commits/" in url:
            data = json.dumps({"sha": COMMIT_SHA, "tree": {"sha": TREE_SHA}}).encode()
            return 200, {}, data
        if url.endswith("/repos/usuario/repo"):
            data = json.dumps({"full_name": "usuario/repo", "default_branch": "main",
                               "private": False}).encode()
            return 200, {}, data
        if url.endswith("/commits/main"):
            return 200, {}, COMMIT_SHA.encode()  # formato github_sha: el SHA crudo
        if "/git/trees/" in url:
            data = json.dumps({"tree": [], "truncated": False, "sha": TREE_SHA}).encode()
            return 200, {}, data
        return 200, {}, b"{}"
    return transporte


class TokenTests(unittest.TestCase):
    def test_el_token_viaja_como_bearer_en_todas_las_llamadas(self):
        vistos = {}
        p.analyze_repository("https://github.com/usuario/repo", github_token="ghp_token_falso_del_test",
                             transport=transporte_repo(vistos))
        api = [u for u in vistos if "api.github.com" in u]
        self.assertTrue(api, "debe llamar a la API de GitHub")
        sin_auth = [u for u in api if vistos[u].get("Authorization") != "Bearer ghp_token_falso_del_test"]
        self.assertEqual(sin_auth, [], "TODAS las llamadas a GitHub deben ir autenticadas")

    def test_sin_token_van_anonimas(self):
        vistos = {}
        p.analyze_repository("https://github.com/usuario/repo", transport=transporte_repo(vistos))
        api = [u for u in vistos if "api.github.com" in u]
        sin_auth = [u for u in api if "Authorization" not in vistos[u]]
        self.assertEqual(len(sin_auth), len(api), "sin token, todas anonimas")


class Cuota403Tests(unittest.TestCase):
    def test_el_fallo_403_preserva_el_reset_de_la_cuota(self):
        reset = 1791800000
        exc = p._http_failure(403, b'{"message": "API rate limit exceeded"}',
                              headers={"X-RateLimit-Reset": str(reset)})
        self.assertIsInstance(exc, p.HTTPFailure)
        self.assertGreaterEqual(exc.reset_seconds, 0)

    def test_sin_cabeceras_no_miente(self):
        exc = p._http_failure(403, b"{}")
        self.assertFalse(hasattr(exc, "reset_seconds") and exc.reset_seconds,
                         "sin cabecera de reset no se inventa un tiempo")


if __name__ == "__main__":
    unittest.main()
