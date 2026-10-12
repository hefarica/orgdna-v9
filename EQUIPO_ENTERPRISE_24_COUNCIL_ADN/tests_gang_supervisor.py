#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Falsificacion de B — el tick del supervisor.

ESCENARIO B1  crash entre prepare y commit -> el nuevo supervisor REANUDA desde el
              journal y los 3 convergen SIN duplicar (el prepare fue no-op)
ESCENARIO B2  adopcion por lease VENCIDA (dueno muerto, reloj inyectado) -> adopta
ESCENARIO B3  split-brain: lease VIVA de otro supervisor -> el tick NO reanuda nada
ESCENARIO B4  fencing en la reanudacion: nodos con epoch alto -> el tick se
              revalida ANTES de publicar y converge

CLI:  python tests_gang_supervisor.py --escenarios
"""
import os
import sys
import tempfile
import unittest

from engine import coordination
from engine import gang_journal as gj
from engine import gang_services as gs
from engine import gang_supervisor as sp

SHA = "a" * 64
NOMBRES = ("cordi", "agent-team", "team")


def crear_nodos():
    return {sid: gs.ServicioGang(sid) for sid in NOMBRES}


class ReanudacionTests(unittest.TestCase):
    """B1: crash entre prepare y commit."""

    def test_B1_el_crash_entre_fases_se_reanuda_sin_duplicar(self):
        with tempfile.TemporaryDirectory() as tmp:
            jpath = os.path.join(tmp, "journal.jsonl")
            # El coordinador A preparo en los tres... y murio antes del commit.
            nodos = crear_nodos()
            for nodo in nodos.values():
                nodo.prepare(SHA, SHA, 1)
            jA = gj.Journal(jpath)
            jA.record(SHA, gj.STAGED, "coordinador A: prepare hecho, crash antes del commit")
            # Reinicio: el journal replays aborta lo staged (fail-closed)...
            historial = gj.Journal(jpath).history()
            self.assertIn(gj.ABORTED_BY_REPLAY, [e["estado"] for e in historial])
            # ...y el supervisor B lo reanuda con la MISMA clave.
            sup = sp.Supervisor(journal=gj.Journal(jpath), nodos=nodos)
            reporte = sup.tick()
            # los tres convergen
            for sid, nodo in nodos.items():
                self.assertEqual(nodo.live, SHA, "%s no convergio" % sid)
            # y NO duplico: el prepare fue no-op en los tres
            preparaciones = [j for n in nodos.values() for j in n.journal if j["op"] == "prepare"]
            idempotentes = [j for j in preparaciones if j["estado"] == "idempotente"]
            self.assertEqual(len(idempotentes), 3, "el prepare reanudado debe ser no-op en los tres")
            self.assertEqual(reporte["reanudados"], [{"clave": SHA[:8], "idempotente": False}])
            # y el journal dejo la reanudacion commiteada
            self.assertIn(gj.COMMITTED, [e["estado"] for e in gj.Journal(jpath).history()])

    def test_sin_pendientes_el_tick_es_no_op_limpio(self):
        sup = sp.Supervisor(journal=gj.Journal(), nodos=crear_nodos())
        reporte = sup.tick()
        self.assertEqual(reporte["reanudados"], [])
        self.assertEqual(reporte["epoch"], 1)

    def test_lo_ya_commiteado_se_reanuda_como_no_op(self):
        """Idempotencia de punta a punta: si ya estaba commiteado, reintentar es gratis."""
        with tempfile.TemporaryDirectory() as tmp:
            jpath = os.path.join(tmp, "journal.jsonl")
            nodos = crear_nodos()
            sup0 = sp.Supervisor(journal=gj.Journal(jpath), nodos=nodos)
            reg = sup0._registro()
            primera = reg.publish_atomic(SHA)
            segunda = reg.publish_atomic(SHA)  # reintento tras el commit: no-op
            self.assertFalse(primera["idempotente"])
            self.assertTrue(segunda["idempotente"], "reintentar lo commiteado es gratis")
            # y el supervisor no encuentra NADA pendiente: el tick queda limpio
            sup = sp.Supervisor(journal=gj.Journal(jpath), nodos=nodos)
            self.assertEqual(sup.pendientes(), [])
            self.assertEqual(sup.tick()["reanudados"], [])


class FencingTests(unittest.TestCase):
    """B4: el tick se revalida ANTES de publicar."""

    def test_B4_nodos_con_epoch_alto_se_revalidan_y_convergen(self):
        nodos = crear_nodos()
        # una compensacion previa subio el epoch de los tres
        for nodo in nodos.values():
            nodo.prepare("c" * 64, "c" * 64, 1)
            nodo.commit("c" * 64, 1)
            nodo.compensate("c" * 64, 1)   # epoch -> 2
        with tempfile.TemporaryDirectory() as tmp:
            jpath = os.path.join(tmp, "journal.jsonl")
            gj.Journal(jpath).record(SHA, gj.STAGED)
            sup = sp.Supervisor(journal=gj.Journal(jpath), nodos=nodos)
            self.assertEqual(sup.epoch, 1, "arranca en 1")
            reporte = sup.tick()
            self.assertEqual(reporte["epoch"], 2, "el tick revalido al epoch de los nodos")
            for nodo in nodos.values():
                self.assertEqual(nodo.live, SHA)

    def test_sin_revalidacion_el_publish_falliria_por_fencing(self):
        """La prueba inversa: sin el tick (sin revalidar), el 2PC rechaza."""
        nodos = crear_nodos()
        nodos["team"].prepare("c" * 64, "c" * 64, 1)
        nodos["team"].commit("c" * 64, 1)
        nodos["team"].compensate("c" * 64, 1)  # epoch 2
        from engine import gang_registry as gr
        reg = gr.GangRegistry(transport=gs.transporte_memoria(nodos, epoch=1))
        with self.assertRaises(gr.RegistryError):
            reg.publish_atomic(SHA)


class LeaseTests(unittest.TestCase):
    """B2 y B3: adopcion por vencimiento y anti split-brain."""

    def _store(self, tmp, reloj):
        return coordination.CoordinationStore(os.path.join(tmp, "coord.json"), clock=lambda: reloj["t"])

    def test_B2_lease_vencida_se_adopta(self):
        reloj = {"t": 1000.0}
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp, reloj)
            # el supervisor A toma el lease y MUERE (el reloj avanza mas del TTL)
            store.apply("lease-acquire", {"owner_agent_id": "sup-A", "task_id": sp.SUPERVISION_TASK,
                                          "workspace": tmp, "paths": ["_gang_supervision"],
                                          "base_sha": SHA, "ttl_seconds": 60,
                                          "expected_version": store.public()["version"]})
            reloj["t"] += 120  # mas del TTL: la lease de A esta vencida
            nodos = crear_nodos()
            with tempfile.TemporaryDirectory() as tmp2:
                jpath = os.path.join(tmp2, "journal.jsonl")
                sup = sp.Supervisor(journal=gj.Journal(jpath), nodos=nodos,
                                    store=store, workspace=tmp, owner="sup-B")
                reporte = sup.tick()
                self.assertTrue(reporte["adoptado"], "la lease vencida de sup-A se adopto")
                self.assertIsNotNone(reporte["lease"])

    def test_B3_lease_viva_de_otro_detiene_el_tick(self):
        reloj = {"t": 5000.0}
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp, reloj)
            store.apply("lease-acquire", {"owner_agent_id": "sup-B", "task_id": sp.SUPERVISION_TASK,
                                          "workspace": tmp, "paths": ["_gang_supervision"],
                                          "base_sha": SHA, "ttl_seconds": 3600,
                                          "expected_version": store.public()["version"]})
            with tempfile.TemporaryDirectory() as tmp2:
                jpath = os.path.join(tmp2, "journal.jsonl")
                gj.Journal(jpath).record(SHA, gj.STAGED)  # hay algo que reanudar...
                nodos = crear_nodos()
                supA = sp.Supervisor(journal=gj.Journal(jpath), nodos=nodos,
                                     store=store, workspace=tmp, owner="sup-A")
                reporte = supA.tick()
                self.assertEqual(reporte["lease"], "otro-supervisor-activo")
                self.assertEqual(reporte["reanudados"], [], "...y NO reanudo nada: anti split-brain")
                for nodo in nodos.values():
                    self.assertIsNone(nodo.live, "nadie commiteo nada")


class SupervisorInterfaceTests(unittest.TestCase):
    def test_argumentos_validados(self):
        with self.assertRaises(sp.SupervisorError):
            sp.Supervisor(journal="no-es-journal", nodos=crear_nodos())
        with self.assertRaises(sp.SupervisorError):
            sp.Supervisor(journal=gj.Journal())  # sin nodos ni urls

    def test_pendientes_solo_cuenta_lo_que_quedo_en_duda(self):
        # aborted_by_replay solo lo escribe el REPLAY (nunca record): se fabrica con
        # un journal en disco cuya carga resuelve lo staged.
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "j.jsonl")
            j = gj.Journal(p)
            j.record("a" * 64, gj.STAGED)
            j.record("b" * 64, gj.COMMITTED)
            sup = sp.Supervisor(journal=gj.Journal(p), nodos=crear_nodos())
            self.assertEqual(sup.pendientes(), ["a" * 64])


if __name__ == "__main__":
    if "--escenarios" in sys.argv:
        print("ESCENARIO B1  crash entre prepare y commit")
        with tempfile.TemporaryDirectory() as tmp:
            jpath = os.path.join(tmp, "journal.jsonl")
            nodos = crear_nodos()
            for n in nodos.values():
                n.prepare(SHA, SHA, 1)
            gj.Journal(jpath).record(SHA, gj.STAGED, "crash antes del commit")
            sup = sp.Supervisor(journal=gj.Journal(jpath), nodos=nodos)
            r = sup.tick()
            print("  reanudados:", r["reanudados"])
            print("  convergen en:", {k: n.live[:8] for k, n in nodos.items()})
        print("ESCENARIO B2  adopcion por lease vencida")
        reloj = {"t": 1000.0}
        with tempfile.TemporaryDirectory() as tmp:
            store = coordination.CoordinationStore(os.path.join(tmp, "coord.json"), clock=lambda: reloj["t"])
            store.apply("lease-acquire", {"owner_agent_id": "sup-A", "task_id": sp.SUPERVISION_TASK,
                                          "workspace": tmp, "paths": ["_gang_supervision"],
                                          "base_sha": SHA, "ttl_seconds": 60,
                                          "expected_version": store.public()["version"]})
            reloj["t"] += 120
            with tempfile.TemporaryDirectory() as tmp2:
                jpath = os.path.join(tmp2, "journal.jsonl")
                sup = sp.Supervisor(journal=gj.Journal(jpath), nodos=crear_nodos(),
                                    store=store, workspace=tmp, owner="sup-B")
                r = sup.tick()
                print("  adoptado:", r["adoptado"], "· lease:", bool(r["lease"]))
        print("ESCENARIO B3  split-brain: lease viva de otro supervisor")
        reloj = {"t": 5000.0}
        with tempfile.TemporaryDirectory() as tmp:
            store = coordination.CoordinationStore(os.path.join(tmp, "coord.json"), clock=lambda: reloj["t"])
            store.apply("lease-acquire", {"owner_agent_id": "sup-B", "task_id": sp.SUPERVISION_TASK,
                                          "workspace": tmp, "paths": ["_gang_supervision"],
                                          "base_sha": SHA, "ttl_seconds": 3600,
                                          "expected_version": store.public()["version"]})
            with tempfile.TemporaryDirectory() as tmp2:
                jpath = os.path.join(tmp2, "journal.jsonl")
                gj.Journal(jpath).record(SHA, gj.STAGED)
                nodos = crear_nodos()
                r = sp.Supervisor(journal=gj.Journal(jpath), nodos=nodos,
                                  store=store, workspace=tmp, owner="sup-A").tick()
                print("  lease:", r["lease"], "· reanudados:", r["reanudados"])
        print("ESCENARIO B4  fencing: el tick revalida el epoch antes de publicar")
        nodos = crear_nodos()
        for n in nodos.values():
            n.prepare("c" * 64, "c" * 64, 1)
            n.commit("c" * 64, 1)
            n.compensate("c" * 64, 1)
        with tempfile.TemporaryDirectory() as tmp:
            jpath = os.path.join(tmp, "journal.jsonl")
            gj.Journal(jpath).record(SHA, gj.STAGED)
            r = sp.Supervisor(journal=gj.Journal(jpath), nodos=nodos).tick()
            print("  epoch revalidado a:", r["epoch"], "· convergen en:", {k: n.live[:8] for k, n in nodos.items()})
        sys.exit(0)
    unittest.main()
