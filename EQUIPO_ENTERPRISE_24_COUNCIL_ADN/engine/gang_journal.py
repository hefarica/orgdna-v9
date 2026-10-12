"""Journal del gang: append-only en disco, con replay que sobrevive al crash.

Cada transaccion de publicacion deja sus transiciones escritas: staged -> committed,
o staged -> aborted, o staged -> rolled_back. Si el coordinador muere a mitad de un
commit, al reanudar el replay lee el archivo y resuelve lo quedo en duda:

    - commiteado  -> commiteado (sobrevive: ya esta en los servicios)
    - staged      -> ABORTADO POR REPLAY (fail-closed: el coordinador murio antes
                     del commit y lo honesto es abortar, nunca suponer exito)

Formato: una linea JSON por transicion (JSONL, append-only). Sin bloqueos exoticos:
escritura atomica por linea con flush inmediato.
"""
from __future__ import annotations

import json
import os
import time

COMMITTED = "committed"
STAGED = "staged"
ABORTED = "aborted"
ROLLED_BACK = "rolled_back"
ABORTED_BY_REPLAY = "aborted_by_replay"


class JournalError(ValueError):
    """El journal no se puede leer ni escribir."""


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Journal:
    """Append-only con replay. `path=None` da un journal solo en memoria (tests)."""

    def __init__(self, path=None):
        self.path = path
        self._entries = {}   # clave -> ultima transicion
        self._log = []       # historial completo (auditoria)
        if path:
            self._replay()

    # ---------------------------------------------------------------- replay

    def _replay(self):
        if not os.path.exists(self.path):
            return
        dudosos = set()
        with open(self.path, encoding="utf-8") as handle:
            for numero, linea in enumerate(handle, 1):
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    row = json.loads(linea)
                except ValueError:
                    raise JournalError("journal: linea %d no es JSON valido." % numero) from None
                clave, estado = row.get("clave"), row.get("estado")
                if not isinstance(clave, str) or estado not in (STAGED, COMMITTED, ABORTED, ROLLED_BACK):
                    raise JournalError("journal: linea %d con transicion no reconocida." % numero)
                self._entries[clave] = row
                self._log.append(row)
                if estado == STAGED:
                    dudosos.add(clave)
                else:
                    dudosos.discard(clave)
        # Politica de resolucion de lo que quedo en duda: ABORTAR. Nunca se supone
        # exito de una publicacion que no llego a commitear.
        for clave in sorted(dudosos):
            resuelta = {"clave": clave, "estado": ABORTED_BY_REPLAY, "ts": _now(),
                        "detalle": "resuelto al reanudar: el coordinador murio antes del commit"}
            self._entries[clave] = resuelta
            self._log.append(resuelta)
            self._append(resuelta)

    # ---------------------------------------------------------------- escritura

    def _append(self, row):
        if not self.path:
            return
        with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def record(self, clave, estado, detalle=None):
        if estado not in (STAGED, COMMITTED, ABORTED, ROLLED_BACK):
            raise JournalError("record: transicion no reconocida: %r" % (estado,))
        row = {"clave": clave, "estado": estado, "ts": _now()}
        if detalle:
            row["detalle"] = str(detalle)[:300]
        self._entries[clave] = row
        self._log.append(row)
        self._append(row)
        return row

    # ---------------------------------------------------------------- lectura

    def get(self, clave):
        return self._entries.get(clave)

    def history(self):
        """Historial completo, para el panel de auditoria."""
        return list(self._log)
