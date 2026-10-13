#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La ultima milla: el PANEL monta los 3 servicios y todo queda en la aplicacion.

M1  montar desde el bridge -> 3 procesos HTTP reales, urls expuestas en el estado
M2  publicar con servicios montados -> 2PC REAL por HTTP, los nodos convergen
M3  desmontar -> el registro vuelve a grabar y el journal CONSERVA la historia
M4  el tick del supervisor se dispara desde el panel
M5  montar dos veces / tick sin montar -> fallo cerrado honesto
"""
import unittest

from engine import bridge
from engine import core
from engine import gang_registry as gr


def org_real(n=4):
    return core.generate_organization(
        {"agent_count": n, "template": "generic", "repo_name": "X", "generation_mode": "template"},
        {"source_kind": "template", "coverage": {}, "summary": ""},
        provenance={"source_kind": "template", "runtime_verified": False})


class MontajeTests(unittest.TestCase):
    def setUp(self):
        self.state = bridge.BridgeState(gang_registry=gr.GangRegistry())

    def tearDown(self):
        if getattr(self.state, "gang_servers", None):
            for servidor in self.state.gang_servers.values():
                servidor.stop()

    def test_M1_montar_expone_tres_procesos_reales(self):
        self.state.execute("gang-mount", {})
        gang = self.state.public()["gang"]
        self.assertTrue(gang["montado"])
        self.assertEqual(len(gang["urls"]), 3)
        self.assertIn("cordi", gang["urls"])
        self.assertTrue(all(url.startswith("http://127.0.0.1:") for url in gang["urls"].values()))
        # procesos ATENDIENDO de verdad
        import json as _json
        import urllib.request
        with urllib.request.urlopen(gang["urls"]["cordi"] + "/health", timeout=5) as resp:
            self.assertTrue(_json.loads(resp.read().decode("utf-8"))["ok"])

    def test_M2_publicar_con_servicios_montados_es_2pc_real(self):
        self.state.organization = org_real(4)
        self.state.execute("gang-mount", {})
        self.state.execute("gang-publish", {})
        sha = self.state.public()["gang"]["ensamblado"]["sha256"]
        for servidor in self.state.gang_servers.values():
            self.assertEqual(servidor.nodo.live, sha,
                             "el nodo %s recibio el sello por HTTP real" % servidor.nodo.id)
        gang = self.state.public()["gang"]
        self.assertEqual(gang["sync"]["code"], "SYNCED")
        self.assertTrue(all(not f["mounted"] for f in gang["servicios"]),
                        "la honestidad no cambia: mounted sigue siendo False (local, no DSH)")

    def test_M3_desmontar_restaura_el_grabador_y_conserva_el_journal(self):
        self.state.organization = org_real(3)
        self.state.execute("gang-mount", {})
        self.state.execute("gang-publish", {})
        antes = len(self.state.public()["gang"]["auditoria"])
        urls = dict(self.state.gang_servers and {sid: s.url() for sid, s in self.state.gang_servers.items()} or {})
        self.state.execute("gang-unmount", {})
        gang = self.state.public()["gang"]
        self.assertFalse(gang["montado"])
        self.assertEqual(gang["urls"], {})
        self.assertGreaterEqual(len(gang["auditoria"]), antes, "la historia sobrevive al desmonte")
        # y el puerto muerto de verdad
        import urllib.request
        with self.assertRaises(Exception):
            urllib.request.urlopen(urls["cordi"] + "/health", timeout=2)
        # publicar sin montar vuelve a grabar (registro local)
        self.state.execute("gang-publish", {})
        self.assertEqual(self.state.public()["gang"]["sync"]["code"], "SYNCED")

    def test_M4_el_tick_del_supervisor_se_dispara_desde_el_panel(self):
        self.state.execute("gang-mount", {})
        self.state.execute("gang-tick", {})
        # sin pendientes: reporte limpio y sin nodos tocados
        for servidor in self.state.gang_servers.values():
            self.assertIsNone(servidor.nodo.live)

    def test_M5_fallos_cerrados_honestos(self):
        with self.assertRaises(bridge.BridgeError):
            self.state.execute("gang-tick", {})          # sin montar no hay nada que supervisar
        self.state.execute("gang-mount", {})
        with self.assertRaises(bridge.BridgeError):
            self.state.execute("gang-mount", {})          # ya montados
        self.state.execute("gang-unmount", {})
        with self.assertRaises(bridge.BridgeError):
            self.state.execute("gang-unmount", {})        # ya desmontados


if __name__ == "__main__":
    unittest.main()
