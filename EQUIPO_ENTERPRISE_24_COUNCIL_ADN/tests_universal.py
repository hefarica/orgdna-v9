"""tests_universal.py - t5.5: contrato universal, drivers y adaptacion fail-closed."""
import os
import unittest

from engine.sources.blockchain_driver import BlockchainDriver
from engine.sources.git_driver import GitDriver
from engine.sources.universal_base import (AppSurface, SourceType,
                                           SourceUnavailable, SurfacePoint,
                                           UniversalDriver)
from engine.sources.web_driver import WebDriver
from engine.universal_pipeline import adaptar


class ContratoTests(unittest.TestCase):
    def test_huella_estable_ante_orden(self):
        a = AppSurface(SourceType.GIT, "x", (SurfacePoint("a", "file"),
                                             SurfacePoint("b", "file")))
        b = AppSurface(SourceType.GIT, "y", (SurfacePoint("b", "file"),
                                             SurfacePoint("a", "file")))
        self.assertEqual(a.structure_fingerprint, b.structure_fingerprint)

    def test_huella_distingue_estructuras(self):
        a = AppSurface(SourceType.GIT, "x", (SurfacePoint("a", "file"),))
        b = AppSurface(SourceType.GIT, "x", (SurfacePoint("z", "file"),))
        self.assertNotEqual(a.structure_fingerprint, b.structure_fingerprint)

    def test_abc_no_instancia(self):
        with self.assertRaises(TypeError):
            UniversalDriver()


class GitDriverTests(unittest.TestCase):
    def test_barre_su_propio_arbol(self):
        d = GitDriver()
        ok, _ = d.available()
        self.assertTrue(ok)
        s = d.scan_surface(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.assertIs(s.source_type, SourceType.GIT)
        self.assertGreater(len(s.points), 20)
        self.assertIn(".py", s.extensions())
        self.assertTrue(s.evidence)

    def test_detecta_frameworks(self):
        # superficie sintetica: nuestro propio paquete no tiene .rs ni .sol,
        # asi que probar con el arbol local daria vacio y no probaria nada.
        s = AppSurface(SourceType.GIT, "x", (SurfacePoint("a.rs", "source_code"),
                                             SurfacePoint("b.sol", "source_code"),
                                             SurfacePoint("c.rhai", "source_code")))
        fw = GitDriver().detect_frameworks(s)
        self.assertEqual(fw, {"rust", "solidity", "rhai"})


class BlockchainTests(unittest.TestCase):
    def test_declarado_no_disponible(self):
        d = BlockchainDriver()
        ok, motivo = d.available()
        self.assertFalse(ok)
        self.assertIn("RPC", motivo)

    def test_scan_levanta_y_no_simula(self):
        with self.assertRaises(SourceUnavailable):
            BlockchainDriver().scan_surface("ethereum:0x0")


class WebDriverTests(unittest.TestCase):
    def test_esquema_invalido_falla(self):
        with self.assertRaises(SourceUnavailable):
            WebDriver().scan_surface("ftp://x/y")

    def test_contrato_disponible(self):
        ok, motivo = WebDriver().available()
        self.assertTrue(ok)
        self.assertTrue(motivo)


class AdaptarTests(unittest.TestCase):
    def _surface(self, caps=("form", "auth")):
        return AppSurface(SourceType.WEB, "https://x",
                          (SurfacePoint("/a", "route"), SurfacePoint("a.css", "asset")),
                          capabilities=set(caps), assets={"a.css"}, confidence=0.8)

    def test_perfiles_unicos_con_parity(self):
        perfiles, diag = adaptar(self._surface())
        nombres = [p["name"] for p in perfiles]
        self.assertIn("parity_verifier", nombres)
        self.assertEqual(len(nombres), len(set(nombres)))

    def test_capacidad_desconocida_se_declara(self):
        _, diag = adaptar(self._surface(("form", "cap_rara")))
        self.assertIn("cap_rara", diag["capacidades_sin_mapeo"])

    def test_diagnostico_trae_huella(self):
        _, diag = adaptar(self._surface())
        self.assertTrue(diag["fingerprint"])
        self.assertEqual(diag["source_type"], "web")

    def test_perfiles_tienen_destino_y_aceptacion(self):
        perfiles, _ = adaptar(self._surface())
        for p in perfiles:
            self.assertTrue(p["destination"], p["name"])
            self.assertTrue(p["acceptance"], p["name"])


if __name__ == "__main__":
    unittest.main()
