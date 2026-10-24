"""tests_capabilities_extra.py - ooxml, obsidian y telegram: reales y stdlib."""
import os
import tempfile
import unittest

from engine.cap_obsidian import Vault, VaultError
from engine.cap_ooxml import OoxmlError, read_text, write_docx, write_pptx
from engine.cap_telegram import TelegramBot, TelegramError

TOKEN_OK = "123456789:" + "A" * 35


class OoxmlTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_docx_valido_y_releible(self):
        ruta = os.path.join(self.d, "a.docx")
        r = write_docx(ruta, ["Espina", "Segunda"])
        self.assertEqual(r["paragraphs"], 2)
        self.assertIn("Espina", r["text"])
        self.assertIn("Segunda", read_text(ruta))

    def test_pptx_valido_y_releible(self):
        ruta = os.path.join(self.d, "a.pptx")
        r = write_pptx(ruta, ["Portada", "Hallazgos"])
        self.assertEqual(r["slides"], 2)
        self.assertIn("Hallazgos", r["text"])

    def test_extension_invalida(self):
        with self.assertRaises(OoxmlError):
            write_docx(os.path.join(self.d, "x.txt"), ["a"])

    def test_sin_contenido(self):
        with self.assertRaises(OoxmlError):
            write_docx(os.path.join(self.d, "v.docx"), [])

    def test_zip_corrupto_se_detecta_al_releer(self):
        roto = os.path.join(self.d, "roto.docx")
        with open(roto, "wb") as fh:
            fh.write(b"no soy un zip")
        with self.assertRaises(OoxmlError):
            read_text(roto)

    def test_limitacion_declarada(self):
        ruta = os.path.join(self.d, "l.docx")
        r = write_docx(ruta, ["x"])
        self.assertIn("sin estilos", r["limitation"])


class ObsidianTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.v = Vault(self.d)

    def test_escribe_indiza_y_lee(self):
        r = self.v.write("ADR 001", "vamos por [[Estrategia]]")
        self.assertEqual(r["links"], ["Estrategia"])
        self.assertEqual(self.v.notes(), ["ADR 001.md"])
        self.assertIn("Estrategia", self.v.read("ADR 001"))

    def test_rechaza_escapar_del_vault(self):
        for malo in ("../fuera", "sub/nota", "/abs/nota", ""):
            with self.assertRaises(VaultError):
                self.v._destino(malo)

    def test_rechaza_nota_vacia(self):
        with self.assertRaises(VaultError):
            self.v.write("x", "   ")

    def test_vault_inexistente(self):
        with self.assertRaises(VaultError):
            Vault(os.path.join(self.d, "no_existe"))

    def test_vault_vacio_sin_notas(self):
        self.assertEqual(self.v.notes(), [])


class TelegramTests(unittest.TestCase):
    def test_sin_token(self):
        with self.assertRaises(TelegramError):
            TelegramBot({})

    def test_token_mal_formado(self):
        for malo in ({"token": "abc"}, {"token": "123:"}, {"token": "123456789: corto"}):
            with self.assertRaises(TelegramError):
                TelegramBot(malo)

    def test_token_valido_construye(self):
        b = TelegramBot({"token": TOKEN_OK})
        self.assertEqual(b.timeout, 20)

    def test_send_message_exige_confirmacion(self):
        b = TelegramBot({"token": TOKEN_OK})
        with self.assertRaises(TelegramError) as ctx:
            b.send_message(1, "hola")
        self.assertIn("IRREVERSIBLE", str(ctx.exception))

    def test_send_message_sin_datos_falla_antes_de_red(self):
        b = TelegramBot({"token": TOKEN_OK})
        with self.assertRaises(TelegramError):
            b.send_message("", "", confirmed=True)


if __name__ == "__main__":
    unittest.main()
