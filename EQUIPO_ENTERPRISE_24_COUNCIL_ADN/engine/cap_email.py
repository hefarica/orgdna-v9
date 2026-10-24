"""cap_email.py - lectura IMAP real con stdlib. Credenciales EXPLICITAS, nunca asumidas.

Sin credenciales falla en el constructor. No hay endpoint por defecto, ni
autoconfiguracion, ni lectura de ~/.netrc: el operador declara servidor y usuario.
No envia correo: solo lectura. El envio (smtplib) se deja fuera a proposito porque
es una accion irreversible hacia terceros.
"""
from __future__ import annotations
import imaplib
import os
from typing import Mapping


class CredentialError(Exception):
    pass


class EmailError(Exception):
    pass


class EmailReader:
    REQUIRED = ("imap_server", "username", "password")
    LIMITE = 20

    def __init__(self, config: Mapping[str, str], timeout: int = 20):
        faltan = [k for k in self.REQUIRED if not str(config.get(k) or "").strip()]
        if faltan:
            raise CredentialError(
                "EMAIL requiere %s. No se asume ningun servidor por defecto."
                % ", ".join(faltan))
        self.imap_server = str(config["imap_server"]).strip()
        self.username = str(config["username"]).strip()
        self.password = str(config["password"])
        self.timeout = timeout

    @classmethod
    def from_env(cls):
        cfg = {k: os.environ.get("ORGDNA_" + k.upper(), "") for k in cls.REQUIRED}
        return cls(cfg)

    def _connect(self):
        try:
            imap = imaplib.IMAP4_SSL(self.imap_server, timeout=self.timeout)
        except Exception as exc:
            raise EmailError("no se pudo abrir IMAP %s: %s" % (self.imap_server, exc))
        try:
            imap.login(self.username, self.password)
        except Exception as exc:
            try:
                imap.logout()
            except Exception:
                pass
            raise CredentialError("credenciales rechazadas por %s: %s" % (self.imap_server, exc))
        return imap

    def unread(self, folder: str = "INBOX") -> dict:
        """Devuelve datos REALES de la bandeja, o levanta. Nunca un exito vacio."""
        imap = self._connect()
        try:
            tip, dados = imap.select(folder, readonly=True)
            if tip != "OK":
                raise EmailError("no se pudo abrir la carpeta %s" % folder)
            tip, lista = imap.search(None, "UNSEEN")
            if tip != "OK":
                raise EmailError("busqueda UNSEEN rechazada")
            ids = (lista[0] or b"").split()
            return {
                "source": "imap://%s/%s" % (self.imap_server, folder),
                "unread": len(ids),
                "sample_ids": [i.decode() for i in ids[: self.LIMITE]],
            }
        finally:
            try:
                imap.logout()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        EmailReader({})
        raise SystemExit("FALLO: sin credenciales debio fallar")
    except CredentialError as e:
        assert "imap_server" in str(e)
    try:
        EmailReader({"imap_server": "x", "username": "u"})
        raise SystemExit("FALLO: faltando password debio fallar")
    except CredentialError as e:
        assert "password" in str(e)
    r = EmailReader({"imap_server": "imap.example.com", "username": "u", "password": "p"})
    assert r.imap_server == "imap.example.com"
    print("OK cap_email: credenciales obligatorias, sin servidor por defecto, sin envio")
