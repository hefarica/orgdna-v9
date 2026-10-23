"""tests_site_rea.py - T5: REA, equipo por spec y Gate 4 de paridad."""
import unittest

from engine import parity_gate as pg
from engine.parity_gate import ParityError, parity_gate
from engine.site_rea import ReaError, ReplicationSpec, analyze, to_essence
from engine.team_for_spec import build_team, owner_index

HTML = ('<title>Tienda Demo</title><meta name="description" content="catalogo">'
        '<script>window.__NEXT_DATA__={"props":{}};</script>'
        '<link href="/a.css"><nav></nav><form></form>'
        '<a href="/precios"></a><a href="/login"></a>'
        '<script>fetch("/api/cart")</script>')


class SiteReaTests(unittest.TestCase):
    def test_detecta_framework_y_capacidades(self):
        s = analyze("https://x", HTML)
        self.assertIn("next", s.frameworks)
        self.assertIn("form", s.capabilities)
        self.assertIn(".ts", s.required_destinations)

    def test_rutas_y_api(self):
        s = analyze("https://x", HTML)
        self.assertIn("/precios", s.routes)
        self.assertIn("/api/cart", s.api_endpoints)

    def test_modo_por_spdx_no_por_substring(self):
        # el defecto F3, por tercera vez, no puede volver
        self.assertEqual(analyze("https://x", HTML + "permited mit").mode, "reimplement")
        self.assertEqual(analyze("https://x", HTML, license_id="BUSL-1.1").mode, "reimplement")
        self.assertEqual(analyze("https://x", HTML, license_id="MIT").mode, "copy")

    def test_html_vacio_falla(self):
        with self.assertRaises(ReaError):
            analyze("https://x", "")

    def test_unknowns_declarados(self):
        s = analyze("https://x", "<html></html>")
        self.assertTrue(s.unknowns)
        self.assertLess(s.confidence, 0.85)

    def test_essence_no_finge(self):
        self.assertIn("MODO reimplement", to_essence(analyze("https://x", HTML)))


class TeamTests(unittest.TestCase):
    def test_indice_resuelve_mandatorios(self):
        idx = owner_index()
        self.assertEqual(idx["security_auditor"], "SECURITY")
        self.assertEqual(idx["qa_test_engineer"], "QA")

    def test_overrides_aplicados(self):
        idx = owner_index()
        self.assertEqual(idx["design_systems"], "FRONTEND")

    def test_equipo_incluye_parity_verifier(self):
        spec = ReplicationSpec(url="https://x", required_destinations=(".py",))
        team = build_team(spec)
        nombres = [p["name"] for p in team]
        self.assertIn("parity_verifier", nombres)
        self.assertEqual(len(nombres), len(set(nombres)))

    def test_perfiles_tienen_destino_y_aceptacion(self):
        spec = ReplicationSpec(url="https://x", required_destinations=(".py", ".css"))
        for p in build_team(spec):
            self.assertTrue(p["destination"], p["name"])
            self.assertTrue(p["acceptance"], p["name"])

    def test_destino_sin_dueno_falla_cerrado(self):
        spec = ReplicationSpec(url="https://x", required_destinations=(".zzz9",))
        with self.assertRaises(ValueError):
            build_team(spec)


class ParityTests(unittest.TestCase):
    def _spec(self):
        return ReplicationSpec(url="https://x", routes=("/a", "/b"),
                               capabilities=("nav",), assets=("a.png",),
                               api_contracts=({"t": 1},))

    def test_paridad_ok(self):
        rep = parity_gate(self._spec(), {"routes": ["/a", "/b", "/c"],
                                         "capabilities": ["nav", "form"],
                                         "assets": ["a.png"], "contracts": [{"t": 1}]})
        self.assertTrue(rep.ok)

    def test_ruta_faltante_falla(self):
        with self.assertRaises(ParityError):
            parity_gate(self._spec(), {"routes": ["/a"], "capabilities": ["nav"],
                                       "assets": ["a.png"], "contracts": [{"t": 1}]})

    def test_contrato_distinto_con_mismo_conteo_falla(self):
        # el borrador comparaba longitudes: {t:2} habria pasado como {t:1}
        with self.assertRaises(ParityError):
            parity_gate(self._spec(), {"routes": ["/a", "/b"], "capabilities": ["nav"],
                                       "assets": ["a.png"], "contracts": [{"t": 2}]})

    def test_capacidad_faltante_falla(self):
        with self.assertRaises(ParityError):
            parity_gate(self._spec(), {"routes": ["/a", "/b"], "capabilities": [],
                                       "assets": ["a.png"], "contracts": [{"t": 1}]})


if __name__ == "__main__":
    unittest.main()
