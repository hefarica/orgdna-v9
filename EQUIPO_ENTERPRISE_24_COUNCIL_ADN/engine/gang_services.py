"""Los nodos de servicio del gang: la superficie C, montada de verdad.

CONTRATO DE SERVICIO (regla de oro — token = clave de contenido = determinista):
    GET  /health    -> { ok, epoch, hash }
    GET  /dna       -> { hash }
    POST /prepare   {token, epoch} -> { ok }      idempotente
    POST /commit    {token, epoch} -> { ok }      idempotente
    POST /abort     {token, epoch} -> { ok }
    POST /compensate{token, epoch} -> { ok }      revierte live y SUBE el epoch
    POST /dna/rollback {epoch}    -> { ok }      revierte live y SUBE el epoch

FENCING (anti split-brain): toda operacion lleva epoch. Un epoch MENOR que el del
nodo se rechaza como obsoleto — ya lo reemplazo un coordinador mas nuevo. compensate
y rollback SUBEN el epoch: tras una compensacion, el reintento de un coordinador
viejo no puede commitear por encima.

Los nodos almacenan el SELLO (hash) del artefacto, no sus bytes: el artefacto vive
en el project store y los servicios declaran QUE sello sirven. Por eso el token
(clave de contenido) y el hash son la misma cosa.

`ServidorGang` monta un nodo como proceso HTTP real (puerto efimero). Los
transportes adaptan los nodos a la interfaz del coordinador
`transport(op, objetivo, sha)` — el coordinador no sabe si el objetivo es memoria
o HTTP: eso es el polimorfismo.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from . import gang_journal as _gj
except ImportError:  # importacion suelta (validador de portabilidad)
    import gang_journal as _gj

SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class ServicioError(ValueError):
    """La operacion se rechaza; `code` y `epoch` viajan para el coordinador."""

    def __init__(self, code, message, epoch=None):
        super().__init__(message)
        self.code = code
        self.epoch = epoch


class ServicioGang:
    """Un nodo: superficie con idempotencia por token y fencing por epoch."""

    def __init__(self, service_id, epoch=1, fallar_en=None):
        self.id = service_id
        self.epoch = int(epoch)
        self.fallar_en = fallar_en          # None | 'prepare' | 'commit' (inyeccion de fallos)
        self.staged = {}                    # token -> sha
        self.committed = {}                 # token -> sha
        self.live = None                    # el sello que el nodo sirve
        self.prev_live = None               # el sello anterior (compensacion/rollback)
        self.journal = []                   # auditoria local de transiciones

    # ------------------------------------------------------------------ internos

    def _j(self, op, token, estado, detalle=None):
        self.journal.append({"op": op, "token": token, "estado": estado,
                             "epoch": self.epoch, "detalle": detalle,
                             "ts": _gj._now()})
        return self.journal[-1]

    def _fence(self, epoch):
        if not isinstance(epoch, int) or epoch < 1:
            raise ServicioError("invalid_epoch", "epoch requerido (entero >= 1).", self.epoch)
        if epoch < self.epoch:
            raise ServicioError("epoch_obsoleto",
                                "epoch obsoleto: %d < %d. Otro coordinador ya avanzo." % (epoch, self.epoch),
                                self.epoch)
        self.epoch = epoch

    def _fault(self, op, token):
        if self.fallar_en == op:
            self._j(op, token, "fallo_inyectado", "fallo inyectado para falsificacion")
            raise ServicioError("fault_injected", "Fallo inyectado en %s." % op, self.epoch)

    # ------------------------------------------------------------------ GET

    def health(self):
        return {"ok": True, "epoch": self.epoch, "hash": self.live, "id": self.id}

    def dna(self):
        return {"hash": self.live, "epoch": self.epoch}

    # ------------------------------------------------------------------ POST

    def prepare(self, token, sha, epoch):
        self._fence(epoch)
        self._fault("prepare", token)
        if token in self.committed:
            self._j("prepare", token, "idempotente", "ya commiteado")
            return {"ok": True, "idempotente": True}
        if token in self.staged:
            self._j("prepare", token, "idempotente", "ya montado")
            return {"ok": True, "idempotente": True}
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            raise ServicioError("invalid_sha", "sha requerido (64 hex).", self.epoch)
        self.staged[token] = sha
        return {"ok": True, "idempotente": False, "estado": self._j("prepare", token, "staged")["estado"]}

    def commit(self, token, epoch):
        self._fence(epoch)
        self._fault("commit", token)
        if token in self.committed:
            self._j("commit", token, "idempotente", "ya commiteado")
            return {"ok": True, "idempotente": True, "hash": self.live}
        if token not in self.staged:
            raise ServicioError("commit_sin_prepare",
                                "commit de un token sin prepare: rechazado.", self.epoch)
        self.prev_live = self.live
        self.live = self.staged.pop(token)
        self.committed[token] = self.live
        return {"ok": True, "hash": self.live, "estado": self._j("commit", token, "committed")["estado"]}

    def abort(self, token, epoch):
        self._fence(epoch)
        self._fault("abort", token)
        self.staged.pop(token, None)
        return {"ok": True, "estado": self._j("abort", token, "aborted")["estado"]}

    def compensate(self, token, epoch):
        """Revierte live al sello anterior y SUBE el epoch: el reintento de un
        coordinador viejo no puede commitear por encima de la compensacion."""
        self._fence(epoch)
        self._fault("compensate", token)
        if token in self.committed:
            self.live = self.prev_live
            del self.committed[token]
        self.epoch += 1
        return {"ok": True, "estado": self._j("compensate", token, "compensated")["estado"]}

    def rollback(self, epoch):
        """Rollback total del nodo al sello anterior. Sube el epoch."""
        self._fence(epoch)
        self.live = self.prev_live
        self.staged.clear()
        self.epoch += 1
        return {"ok": True, "epoch": self.epoch, "estado": self._j("rollback", None, "rolled_back")["estado"]}


# --------------------------------------------------------------------------- servidor

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silencio: los tests son los que auditan
        return

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        nodo = self.server.nodo
        if self.path == "/health":
            self._json(200, nodo.health())
        elif self.path == "/dna":
            self._json(200, nodo.dna())
        else:
            self._json(404, {"error": "ruta desconocida"})

    def do_POST(self):
        nodo = self.server.nodo
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            self._json(400, {"error": "JSON invalido"})
            return
        rutas = {"/prepare": "prepare", "/commit": "commit", "/abort": "abort",
                 "/compensate": "compensate", "/dna/rollback": "rollback"}
        op = rutas.get(self.path.split("?")[0])
        if op is None:
            self._json(404, {"error": "ruta desconocida"})
            return
        try:
            if op == "rollback":
                self._json(200, nodo.rollback(int(body.get("epoch") or 0)))
            elif op == "prepare":
                self._json(200, nodo.prepare(body.get("token"), body.get("sha"),
                                             int(body.get("epoch") or 0)))
            elif op == "commit":
                self._json(200, nodo.commit(body.get("token"), int(body.get("epoch") or 0)))
            elif op == "abort":
                self._json(200, nodo.abort(body.get("token"), int(body.get("epoch") or 0)))
            else:  # compensate
                self._json(200, nodo.compensate(body.get("token"), int(body.get("epoch") or 0)))
        except ServicioError as exc:
            self._json(409, {"error": exc.code, "detalle": str(exc), "epoch": exc.epoch})


class ServidorGang:
    """Monta un nodo como servidor HTTP REAL en un puerto efimero."""

    def __init__(self, servicio, host="127.0.0.1", port=0):
        self.nodo = servicio
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.nodo = servicio
        self.host, self.puerto = self.httpd.server_address[0], self.httpd.server_address[1]
        # Sin serve_forever el servidor nunca atiende: los requests colgarian.
        self._hilo = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._hilo.start()

    def url(self):
        return "http://%s:%d" % (self.host, self.puerto)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# --------------------------------------------------------------------------- transportes

def transporte_memoria(nodos, epoch=None):
    """Adaptador en memoria: nodos = {id: ServicioGang}. Directo, sin red."""
    def transporte(op, target, token):
        nodo = nodos.get(target)
        if nodo is None:
            raise RuntimeError("objetivo desconocido: %r" % (target,))
        epoch_usada = epoch() if callable(epoch) else (epoch if epoch is not None else nodo.epoch)
        if op == "prepare":
            nodo.prepare(token, token, epoch_usada)
        elif op == "commit":
            nodo.commit(token, epoch_usada)
        elif op == "abort":
            nodo.abort(token, epoch_usada)
        elif op == "compensate":
            nodo.compensate(token, epoch_usada)
        else:
            raise RuntimeError("op desconocida: %r" % (op,))
    return transporte


def transporte_http(urls, epoch=None):
    """Adaptador HTTP: urls = {id: base}. Un nodo caido lanza -> el coordinador
    compensa: eso ES el escenario 1."""
    import urllib.error
    import urllib.request

    rutas = {"prepare": "/prepare", "commit": "/commit", "abort": "/abort", "compensate": "/compensate"}

    def transporte(op, target, token):
        base = urls.get(target)
        if base is None:
            raise RuntimeError("objetivo desconocido: %r" % (target,))
        ruta = rutas.get(op)
        if ruta is None:
            raise RuntimeError("op sin ruta HTTP: %r" % (op,))
        cuerpo = {"token": token, "sha": token}   # token = clave de contenido = sha
        if epoch is not None:
            cuerpo["epoch"] = epoch() if callable(epoch) else epoch
        req = urllib.request.Request(base + ruta,
                                     data=json.dumps(cuerpo).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detalle = exc.read().decode("utf-8", "replace")
            raise RuntimeError("servicio %s rechazo %s: %s" % (target, op, detalle[:200])) from None
        return payload
    return transporte
