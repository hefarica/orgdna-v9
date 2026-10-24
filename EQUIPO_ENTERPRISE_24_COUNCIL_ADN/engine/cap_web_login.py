"""cap_web_login.py - login por formulario con stdlib (urllib + cookies).

Sin Playwright, sin Selenium: el paquete es stdlib-only. LIMITACION DECLARADA: solo
formularios HTML clasicos; un sitio que autentique por JavaScript, XHR o captcha NO
se puede resolver con esto, y el modulo lo dice en vez de fingir un exito.

No hay URL, campo, ni selector por defecto: el operador los declara. El resultado
incluye la URL final y cuantas cookies se recibieron: eso es evidencia, no una
afirmacion de "authenticated".
"""
from __future__ import annotations
import http.cookiejar
import urllib.error
import urllib.parse
import urllib.request
from typing import Mapping


class LoginError(Exception):
    pass


class FormLogin:
    REQUIRED = ("login_url", "username_field", "password_field")
    LIMITACION = "solo formularios HTML sin JS; XHR/captcha/SPA no estan soportados"

    def __init__(self, config: Mapping[str, str], timeout: int = 20):
        faltan = [k for k in self.REQUIRED if not str(config.get(k) or "").strip()]
        if faltan:
            raise LoginError("WEB_LOGIN requiere %s" % ", ".join(faltan))
        self.url = str(config["login_url"]).strip()
        if not self.url.startswith(("http://", "https://")):
            raise LoginError("login_url debe ser http(s)")
        self.user_field = str(config["username_field"]).strip()
        self.pass_field = str(config["password_field"]).strip()
        self.extra = dict(config.get("extra") or {}) if isinstance(config.get("extra"), Mapping) else {}
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def login(self, username: str, password: str) -> dict:
        """POST del formulario. Devuelve evidencia real: URL final y cookies recibidas."""
        if not username or not password:
            raise LoginError("usuario y contrasena son obligatorios")
        datos = dict(self.extra)
        datos[self.user_field] = username
        datos[self.pass_field] = password
        cuerpo = urllib.parse.urlencode(datos).encode()
        req = urllib.request.Request(self.url, data=cuerpo, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "User-Agent": "OrgDNA-REA/1.0"})
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                final, estado = r.geturl(), r.status
                cuerpo_resp = r.read(4096).decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise LoginError("el servidor rechazo el formulario: HTTP %s" % exc.code)
        except (urllib.error.URLError, OSError) as exc:
            raise LoginError("no se pudo alcanzar %s: %s" % (self.url, exc))

        cookies = [c.name for c in self.jar]
        # evidencia, no afirmacion: si no hay cookies y no cambio la URL, no se
        # declara sesion iniciada.
        sesion = bool(cookies) or final != self.url
        return {
            "source": self.url,
            "final_url": final,
            "http_status": estado,
            "cookies": cookies,
            "session_established": sesion,
            "evidence_bytes": len(cuerpo_resp),
            "limitation": self.LIMITACION,
        }


if __name__ == "__main__":
    try:
        FormLogin({})
        raise SystemExit("FALLO: sin config debio fallar")
    except LoginError as e:
        assert "login_url" in str(e)
    try:
        FormLogin({"login_url": "ftp://x", "username_field": "u", "password_field": "p"})
        raise SystemExit("FALLO: esquema no http debio fallar")
    except LoginError:
        pass
    f = FormLogin({"login_url": "https://ejemplo.test/login",
                   "username_field": "user", "password_field": "pass"})
    try:
        f.login("", "p")
        raise SystemExit("FALLO: sin usuario debio fallar")
    except LoginError:
        pass
    assert "JS" in FormLogin.LIMITACION
    print("OK cap_web_login: stdlib, sin defaults, limitacion JS declarada, sesion por evidencia")
