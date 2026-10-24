"""cap_telegram.py - Telegram con stdlib (urllib). Token OBLIGATORIO.

La API de Telegram es HTTP: no hace falta python-telegram-bot. Sin token valido
falla en el constructor, con el formato exigido y sin leer variables de entorno
implicitas: el llamador lo aporta.

`send_message` es IRREVERSIBLE (sale a un tercero): exige confirmed=True. Sin eso
no envia. No hay reintentos automaticos ni cola: un envio confirmado es un envio.
"""
from __future__ import annotations
import json
import re
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.telegram.org/bot%s/%s"
TOKEN_RE = re.compile(r"^\d{6,}:[A-Za-z0-9_-]{30,}$")


class TelegramError(Exception):
    pass


class TelegramBot:
    REQUIRED = ("token",)

    def __init__(self, config: dict, timeout: int = 20):
        token = str((config or {}).get("token") or "").strip()
        if not token:
            raise TelegramError("Telegram requiere token de bot")
        if not TOKEN_RE.match(token):
            raise TelegramError("token con formato invalido (esperado <digitos>:<35+ chars>)")
        self._token = token
        self.timeout = timeout

    def _call(self, metodo: str, datos: dict = None):
        url = API % (self._token, metodo)
        cuerpo = urllib.parse.urlencode(datos).encode() if datos else None
        req = urllib.request.Request(url, data=cuerpo, headers={"User-Agent": "OrgDNA-REA/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                datos_resp = json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise TelegramError("%s: HTTP %s" % (metodo, exc.code))
        except (urllib.error.URLError, OSError) as exc:
            raise TelegramError("%s: no se pudo alcanzar la API: %s" % (metodo, exc))
        if not isinstance(datos_resp, dict) or datos_resp.get("ok") is not True:
            raise TelegramError("%s: respuesta no-ok: %s" % (metodo, str(datos_resp)[:120]))
        return datos_resp.get("result")

    def get_me(self) -> dict:
        r = self._call("getMe") or {}
        return {"source": "telegram:getMe", "id": r.get("id"), "username": r.get("username"),
                "is_bot": r.get("is_bot")}

    def send_message(self, chat_id, text: str, confirmed: bool = False) -> dict:
        if confirmed is not True:
            raise TelegramError("send_message es IRREVERSIBLE: exige confirmed=True")
        if not str(chat_id).strip() or not str(text).strip():
            raise TelegramError("chat_id y text son obligatorios")
        r = self._call("sendMessage", {"chat_id": chat_id, "text": str(text)[:4000]}) or {}
        return {"source": "telegram:sendMessage", "message_id": r.get("message_id"),
                "date": r.get("date"), "chat_id": (r.get("chat") or {}).get("id")}


if __name__ == "__main__":
    for malo in ({}, {"token": "abc"}, {"token": "123:"}):
        try:
            TelegramBot(malo); raise SystemExit("FALLO: token %r aceptado" % malo)
        except TelegramError:
            pass
    b = TelegramBot({"token": "123456789:" + "A" * 35})
    try:
        b.send_message(1, "hola")
        raise SystemExit("FALLO: send_message sin confirmed debio rechazarse")
    except TelegramError as e:
        assert "IRREVERSIBLE" in str(e)
    print("OK cap_telegram: token obligatorio y validado, envio irreversible exige confirmed")
