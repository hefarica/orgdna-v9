"""tests_spa_render.py - el render headless se declara y nunca finge.

Sin red y sin lanzar el navegador en los tests: se comprueba el CONTRATO y las
rutas de fallo, que es lo que puede romperse en silencio.
"""
import os
import unittest

from engine import web_sources as w

ESTATICO = (b"<html><head><title>Doc</title></head><body><h1>Uno</h1>"
            b"<p>Contenido real y suficiente para pasar el umbral de cuarenta.</p></body></html>")
CASCARON = b"<html><head><title>Corto</title></head><body><div id='app'></div><script>boot()</script></body></html>"


class NavegadorTests(unittest.TestCase):
    def test_deteccion_devuelve_ruta_o_none(self):
        ruta = w.navegador_disponible()
        self.assertTrue(ruta is None or os.path.isfile(ruta))

    def test_lista_de_navegadores_no_esta_vacia(self):
        self.assertGreaterEqual(len(w._NAVEGADORES), 3)


class RenderDesactivadoTests(unittest.TestCase):
    def test_con_render_off_devuelve_motivo(self):
        previo = w.RENDER_JS
        try:
            w.RENDER_JS = False
            html, motivo = w._render_dom("https://example.com")
            self.assertIsNone(html)
            self.assertEqual(motivo, "render_desactivado_por_configuracion")
        finally:
            w.RENDER_JS = previo


class ExtractTests(unittest.TestCase):
    def test_estatico_usable_sin_render(self):
        previo = w.RENDER_JS
        try:
            w.RENDER_JS = False
            r = w._extract("https://example.com/", ESTATICO)
            self.assertEqual(r["content_status"], "usable_static_html")
            self.assertFalse(r["javascript_rendered"])
            self.assertFalse(r["embedded_only"])
        finally:
            w.RENDER_JS = previo

    def test_cascaron_sin_render_ni_metadata_es_shell(self):
        previo = w.RENDER_JS
        try:
            w.RENDER_JS = False
            r = w._extract("https://spa.example/", CASCARON)
            self.assertIn(r["content_status"], ("javascript_shell", "no_usable_evidence"))
            self.assertFalse(r["javascript_rendered"])
            self.assertIsNotNone(r["render_engine"])  # motivo declarado, no silencio
        finally:
            w.RENDER_JS = previo

    def test_declara_el_motor_cuando_hay_render(self):
        r = w._extract("https://example.com/", ESTATICO)
        self.assertIn("render_engine", r)
        self.assertIn("javascript_rendered", r)


if __name__ == "__main__":
    unittest.main()
