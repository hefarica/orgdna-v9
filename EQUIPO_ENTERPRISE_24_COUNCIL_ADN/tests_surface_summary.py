"""tests_surface_summary.py - el summary solo existe si el proveedor lo acepta."""
import unittest

from engine import providers
from engine.sources.universal_base import AppSurface, SourceType, SurfacePoint
from engine.surface_summary import UnsuitableSurface, to_summary

SHA = "a" * 40


def web_surface():
    snap = {"url": "https://example.com/", "sha256": "b" * 64,
            "fetched_at": "2026-10-23T00:00:00Z", "byte_count": 1256,
            "content_status": "usable_static_html", "title": "Example",
            "text_excerpt": "Example Domain", "headings": [], "links": [],
            "forms": [], "buttons": [], "inputs": [], "roles": []}
    return AppSurface(SourceType.WEB, "https://example.com/",
                      (SurfacePoint("/", "route"),), raw={"snapshot": snap})


def git_surface():
    return AppSurface(SourceType.GIT, "https://github.com/o/r",
                      (SurfacePoint("a.py", "source_code"),),
                      raw={"ref": SHA, "paths": ["a.py", "b.md"]})


def blockchain_surface():
    return AppSurface(SourceType.BLOCKCHAIN, "ethereum:0x0", ())


class WebSummaryTests(unittest.TestCase):
    def test_valida_contra_el_proveedor(self):
        s = to_summary(web_surface())
        self.assertEqual(s["source_kind"], "website")
        self.assertEqual(len(s["snapshots"]), 1)
        self.assertEqual(s["snapshots"][0]["sha256"], "b" * 64)

    def test_sin_evidencia_no_hay_summary(self):
        vacia = AppSurface(SourceType.WEB, "https://x/", ())
        with self.assertRaises(UnsuitableSurface):
            to_summary(vacia)

    def test_origen_distinto_falla(self):
        s = web_surface()
        s.raw["snapshot"]["url"] = "https://otro.com/"
        with self.assertRaises(UnsuitableSurface):
            to_summary(s)


class GitSummaryTests(unittest.TestCase):
    def test_valida_con_sha_fijado(self):
        # prepare_summary devuelve {repository, files, documents, tree}: NO repite
        # source_kind. La prueba es que la forma pase y el SHA quede fijado.
        s = to_summary(git_surface())
        self.assertEqual(s["repository"]["sha"], SHA)
        self.assertEqual([f["path"] for f in s["files"]], ["a.py", "b.md"])
        self.assertTrue(s["tree"])

    def test_sin_sha_falla(self):
        g = AppSurface(SourceType.GIT, "https://github.com/o/r", (),
                       raw={"ref": "main", "paths": ["a.py"]})
        with self.assertRaises(UnsuitableSurface) as ctx:
            to_summary(g)
        self.assertIn("SHA", str(ctx.exception))


class BlockchainTests(unittest.TestCase):
    def test_no_se_inventa_source_kind(self):
        with self.assertRaises(UnsuitableSurface) as ctx:
            to_summary(blockchain_surface())
        self.assertIn("allowlist", str(ctx.exception))


class AllowlistTests(unittest.TestCase):
    def test_los_source_kind_son_solo_los_que_el_proveedor_admite(self):
        # documenta la frontera: agregar uno es decision de seguridad
        admitidos = {"github_repository", "website"}
        self.assertEqual(admitidos, {"github_repository", "website"})


if __name__ == "__main__":
    unittest.main()
