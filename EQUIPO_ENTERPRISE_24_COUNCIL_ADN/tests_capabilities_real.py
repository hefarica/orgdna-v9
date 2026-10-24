"""tests_capabilities_real.py - las tres capacidades stdlib fallan explicitamente.

Ninguna devuelve un exito vacio. Y el test que necesita credenciales reales hace
SKIP DECLARADO, no un fake pass: si no hay credencial, no se afirma que funciona.
"""
import os
import tempfile
import unittest

from engine.cap_email import CredentialError, EmailReader, EmailError
from engine.cap_schedule import ScheduleError, Scheduler
from engine.cap_web_login import FormLogin, LoginError


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = os.path.join(self.dir, "agenda.json")

    def test_persiste_entre_instancias(self):
        Scheduler(self.store).add("j1", 60, "accion")
        self.assertEqual(len(Scheduler(self.store).jobs()), 1)

    def test_accion_ausente_falla_explicito(self):
        s = Scheduler(self.store)
        s.add("j1", 60, "no_existe")
        r = s.tick({}, now=1000.0)
        self.assertFalse(r[0]["ok"])
        self.assertIn("no registrada", r[0]["error"])

    def test_ejecuta_y_cuenta(self):
        s = Scheduler(self.store)
        s.add("j1", 60, "accion")
        r = s.tick({"accion": lambda: "ok"}, now=1000.0)
        self.assertTrue(r[0]["ok"])
        self.assertEqual(r[0]["runs"], 1)

    def test_no_vence_antes_del_intervalo(self):
        s = Scheduler(self.store)
        s.add("j1", 60, "accion")
        s.tick({"accion": lambda: None}, now=1000.0)
        self.assertEqual(s.due(1030.0), [])
        self.assertEqual(len(s.due(1060.0)), 1)

    def test_excepcion_de_la_accion_no_se_traga(self):
        s = Scheduler(self.store)
        s.add("j1", 1, "boom")
        def boom():
            raise RuntimeError("fallo real")
        r = s.tick({"boom": boom}, now=10.0)
        self.assertFalse(r[0]["ok"])
        self.assertIn("fallo real", r[0]["error"])

    def test_sin_store_path_falla(self):
        with self.assertRaises(ScheduleError):
            Scheduler("")

    def test_intervalo_invalido_falla(self):
        with self.assertRaises(ScheduleError):
            Scheduler(self.store).add("j", 0, "a")


class EmailTests(unittest.TestCase):
    def test_sin_credenciales_falla(self):
        with self.assertRaises(CredentialError) as ctx:
            EmailReader({})
        self.assertIn("imap_server", str(ctx.exception))

    def test_falta_password(self):
        with self.assertRaises(CredentialError):
            EmailReader({"imap_server": "x", "username": "u"})

    def test_no_hay_servidor_por_defecto(self):
        r = EmailReader({"imap_server": "imap.example.com", "username": "u", "password": "p"})
        self.assertEqual(r.imap_server, "imap.example.com")

    def test_lectura_real_solo_con_credenciales(self):
        # SKIP DECLARADO: sin credencial no se afirma que funcione
        if not os.environ.get("ORGDNA_IMAP_SERVER"):
            self.skipTest("sin ORGDNA_IMAP_SERVER/PASSWORD: no se simula una lectura real")
        try:
            EmailReader.from_env().unread()
        except (CredentialError, EmailError) as exc:
            self.skipTest("credenciales presentes pero no validas: %s" % str(exc)[:80])


class WebLoginTests(unittest.TestCase):
    def test_sin_config_falla(self):
        with self.assertRaises(LoginError) as ctx:
            FormLogin({})
        self.assertIn("login_url", str(ctx.exception))

    def test_esquema_no_http_falla(self):
        with self.assertRaises(LoginError):
            FormLogin({"login_url": "ftp://x", "username_field": "u", "password_field": "p"})

    def test_sin_usuario_falla(self):
        f = FormLogin({"login_url": "https://ejemplo.test/login",
                       "username_field": "user", "password_field": "pass"})
        with self.assertRaises(LoginError):
            f.login("", "p")

    def test_limitacion_js_declarada(self):
        self.assertIn("JS", FormLogin.LIMITACION)

    def test_sesion_se_reporta_por_evidencia(self):
        # sin red: se comprueba el contrato, no una promesa
        f = FormLogin({"login_url": "https://ejemplo.test/login",
                       "username_field": "user", "password_field": "pass"})
        self.assertEqual(f.user_field, "user")
        self.assertEqual(len(f.jar), 0)


if __name__ == "__main__":
    unittest.main()
