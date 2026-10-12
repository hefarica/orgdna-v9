"""El tick del supervisor: adopta huerfanos, revalida su epoch y reanuda desde el journal.

B en tres garantias, todas sobre primitivas que ya existen:

    ANTI SPLIT-BRAIN (lease)   la supervision la tiene QUIEN sostiene el lease. Si
                               otro supervisor lo tiene VIVO, este tick no reanuda
                               nada. Si el lease VENCIO (su dueno murio), se ADOPTA:
                               eso es el huerfano adoptado.
    REVALIDACION (fencing)     antes de reanudar, el supervisor sondea la salud de
                               los nodos y adopta el MAXIMO epoch. Un coordinador que
                               reinicia no puede commitear por encima de una
                               compensacion: se revalida primero.
    REANUDACION (idempotente)  lo que quedo en duda (staged al morir el coordinador,
                               abortado por replay al reanudar) se RE-PUBLICA con la
                               MISMA clave de contenido. Si los nodos ya lo tenian
                               montado, el prepare es no-op; si ya commitearon, todo
                               es no-op. Reintentar es gratis y no duplica nada.

El tick es EXPLICITO: este producto es offline y dirigido por panel, asi que no hay
demonio por defecto. El panel, el launcher o un cron pueden disparar tick() cuando
el operador decida montar la operacion continua.
"""
from __future__ import annotations

import os

try:
    from . import gang_journal, gang_registry, gang_services
except ImportError:  # importacion suelta (validador de portabilidad)
    import gang_journal, gang_registry, gang_services

SUPERVISION_TASK = "gang-supervision"
DEFAULT_TTL = 60  # el minimo del CoordinationStore; un tick muerto se adopta en 60s


class SupervisorError(ValueError):
    """El tick no puede ejecutarse."""


class Supervisor:
    """Un tick = lease -> revalidar epoch -> reanudar -> reporte."""

    def __init__(self, journal, nodos=None, urls=None, store=None, workspace=None,
                 owner=None, ttl=DEFAULT_TTL, clock=None):
        if not isinstance(journal, gang_journal.Journal):
            raise SupervisorError("journal: se requiere un gang_journal.Journal.")
        self.journal = journal
        self.nodos = nodos or {}
        self.urls = urls or {}
        if not self.nodos and not self.urls:
            raise SupervisorError("Se requieren los nodos (memoria) o las urls (HTTP) para sondear salud.")
        self.store = store
        self.workspace = workspace
        self.owner = owner or ("supervisor-%d" % os.getpid())
        self.ttl = int(ttl)
        # El supervisor y el store comparten reloj: si no se inyecta otro, usa el del
        # store (con reloj real o inyectado, la vista del vencimiento es la misma).
        self.clock = clock or getattr(store, "clock", None)
        self.epoch = 1

    # ------------------------------------------------------------------ salud

    def _ahora(self):
        if self.clock is not None:
            return self.clock()
        import time
        return time.time()

    def salud(self):
        """Epoch y hash de cada nodo, por salud real (memoria o HTTP)."""
        estado = {}
        if self.nodos:
            for sid, nodo in self.nodos.items():
                estado[sid] = nodo.health()
        else:
            import json
            import urllib.request
            for sid, base in self.urls.items():
                try:
                    with urllib.request.urlopen(base + "/health", timeout=5) as resp:
                        estado[sid] = json.loads(resp.read().decode("utf-8"))
                except Exception as exc:  # noqa: BLE001 — la salud caida se reporta, no se oculta
                    estado[sid] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        return estado

    def revalidar_epoch(self):
        """Adopta el MAXIMO epoch de los nodos vivos: un reinicio se autovalida."""
        maximo = self.epoch
        for fila in self.salud().values():
            if isinstance(fila.get("epoch"), int) and fila["epoch"] > maximo:
                maximo = fila["epoch"]
        self.epoch = maximo
        return self.epoch

    # ------------------------------------------------------------------ registro 2PC

    def _registro(self):
        """El coordinador 2PC con el epoch VIGENTE del supervisor (lambda: dinamico)."""
        if self.nodos:
            transporte = gang_services.transporte_memoria(self.nodos, epoch=lambda: self.epoch)
        else:
            transporte = gang_services.transporte_http(self.urls, epoch=lambda: self.epoch)
        return gang_registry.GangRegistry(transport=transporte, journal=self.journal)

    # ------------------------------------------------------------------ lease

    def _lease_actual(self):
        """La lease de supervision vista AHORA: (fila | None, viva: bool)."""
        if self.store is None:
            return None, False
        ahora = self._ahora()
        for fila in self.store.public().get("leases", []):
            if fila.get("task_id") != SUPERVISION_TASK:
                continue
            viva = fila.get("status") == "active" and fila.get("expires_at_epoch", 0) > ahora
            return fila, viva
        return None, False

    def _tomar_lease(self, base_sha):
        version = self.store.public()["version"]
        cuerpo = {"owner_agent_id": self.owner, "task_id": SUPERVISION_TASK,
                  "workspace": str(self.workspace), "paths": ["_gang_supervision"],
                  "base_sha": base_sha, "ttl_seconds": self.ttl,
                  "expected_version": version}
        estado = self.store.apply("lease-acquire", cuerpo)
        fila = next((r for r in estado.get("leases", [])
                     if r.get("task_id") == SUPERVISION_TASK and r.get("status") == "active"), None)
        return (fila or {}).get("id")

    # ------------------------------------------------------------------ tick

    def pendientes(self):
        """Claves que quedaron en duda: staged al morir, abortadas por replay."""
        claves = []
        for entrada in self.journal.history():
            if entrada.get("estado") in (gang_journal.ABORTED_BY_REPLAY,):
                clave = entrada.get("clave")
                if clave not in claves:
                    claves.append(clave)
        return claves

    def tick(self):
        """Un ciclo completo. Devuelve el reporte; jamas lanza por lo reanudable."""
        reporte = {"owner": self.owner, "epoch_antes": self.epoch,
                   "lease": None, "adoptado": False, "reanudados": [], "salud": {}}

        # 0. Salud y revalidacion del epoch (antes de tocar nada).
        reporte["salud"] = {sid: (fila.get("epoch") if fila.get("ok") else "caido")
                            for sid, fila in self.salud().items()}
        self.revalidar_epoch()
        reporte["epoch"] = self.epoch

        pendientes = self.pendientes()
        base = pendientes[0] if pendientes else "0" * 64

        # 1. Lease: quien supervisa. Un lease VIVO de otro supervisor detiene este
        #    tick entero (anti split-brain a nivel supervisor).
        if self.store is not None:
            fila, viva = self._lease_actual()
            if viva and fila.get("owner_agent_id") != self.owner:
                reporte["lease"] = "otro-supervisor-activo"
                reporte["reanudados"] = []
                return reporte
            adoptado = bool(fila and fila.get("owner_agent_id") != self.owner)  # vencida o de un muerto
            lease_id = self._tomar_lease(base)
            reporte["lease"] = lease_id
            reporte["adoptado"] = adoptado

        # 2. Reanudacion: la MISMA clave de contenido, idempotente.
        for clave in pendientes:
            try:
                resultado = self._registro().publish_atomic(clave)
                reporte["reanudados"].append({"clave": clave[:8],
                                              "idempotente": bool(resultado.get("idempotente"))})
            except gang_registry.RegistryError as exc:
                # La reanudacion fallida NO tumba el tick: queda en el reporte para
                # el operador y el journal ya dejo escrita la transaccion fallida.
                reporte["reanudados"].append({"clave": clave[:8], "error": str(exc)[:160]})

        # 3. Renovacion del latido: el proximo tick renueva tomando el lease de nuevo.
        return reporte
