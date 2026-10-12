#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Falsificacion del ensamblador del gang y del registro de despliegue.

Los invariantes se revierten una a una y se comprueba que sus casos se ponen rojos:
un gang con un ciclo, un huerfano, ids duplicados o N inconsistente NO se ensambla.
"""
import copy
import json
import sys
import unittest

from engine import core
from engine import gang_assembly as ga
from engine import gang_registry as gr


def org_real(n=5):
    """Organizacion REAL generada por el producto en modo plantilla (sin proveedor)."""
    org = core.generate_organization(
        {"agent_count": n, "template": "generic", "repo_name": "X", "generation_mode": "template"},
        {"source_kind": "template", "coverage": {}, "summary": ""},
        provenance={"source_kind": "template", "runtime_verified": False})
    assert core.validate_organization(org)["valid"], "el fixture debe ser una org valida"
    return org


class InvariantTests(unittest.TestCase):
    """Cada invariante, revertida, debe reventar en su caso."""

    def setUp(self):
        self.org = org_real(5)

    def test_un_gang_valido_se_ensambla_y_sella(self):
        artifact, sha = ga.assemble(self.org)
        self.assertEqual(artifact["manifest"]["total"], 5)
        self.assertEqual(artifact["manifest"]["version"], 1)
        self.assertEqual(len(artifact["orden"]), 5)
        self.assertRegex(sha, r"^[0-9a-f]{64}$")

    def test_F1_el_ciclo_se_rechaza(self):
        agentes = self.org["agents"]
        jefe, sub = agentes[0], agentes[1]
        jefe["reports_to"], sub["reports_to"] = sub["id"], jefe["id"]  # circulo
        sub.pop("supervision", None)
        with self.assertRaises(ga.AssemblyError) as caught:
            ga.assemble(self.org)
        self.assertEqual(caught.exception.code, "hierarchy_cycle")

    def test_F2_el_huerfano_se_rechaza(self):
        suelto = copy.deepcopy(self.org["agents"][1])
        suelto["id"] = "huerfano-0000"
        suelto["slot"] = 6
        suelto["reports_to"] = "NADIE"
        self.org["agents"].append(suelto)
        self.org["config"]["agent_count"] = 6
        with self.assertRaises(ga.AssemblyError) as caught:
            ga.assemble(self.org)
        self.assertEqual(caught.exception.code, "unknown_supervisor")

    def test_F3_el_desconectado_de_la_raiz_se_rechaza(self):
        a, b = self.org["agents"][1], self.org["agents"][2]
        a["reports_to"], b["reports_to"] = b["id"], a["id"]  # isla de dos
        with self.assertRaises(ga.AssemblyError) as caught:
            ga.assemble(self.org)
        self.assertIn(caught.exception.code, ("hierarchy_cycle", "orphan_agents"))

    def test_F4_los_ids_duplicados_se_rechazan(self):
        self.org["agents"][1]["id"] = self.org["agents"][0]["id"]
        with self.assertRaises(ga.AssemblyError) as caught:
            ga.assemble(self.org)
        self.assertEqual(caught.exception.code, "duplicate_id")

    def test_F5_el_N_inconsistente_se_rechaza(self):
        self.org["config"]["agent_count"] = 4
        with self.assertRaises(ga.AssemblyError) as caught:
            ga.assemble(self.org)
        self.assertEqual(caught.exception.code, "count_mismatch")

    def test_F6_los_slots_incompletos_se_rechazan(self):
        self.org["agents"][2]["slot"] = 9
        with self.assertRaises(ga.AssemblyError) as caught:
            ga.assemble(self.org)
        self.assertEqual(caught.exception.code, "invalid_slots")


class OrderTests(unittest.TestCase):
    def test_F7_el_jefe_va_antes_que_su_gente(self):
        org = org_real(6)
        artifact, _ = ga.assemble(org)
        posicion = {id_: i for i, id_ in enumerate(artifact["orden"])}
        for agente in org["agents"]:
            jefe = agente.get("reports_to")
            if jefe in posicion:
                self.assertLess(posicion[jefe], posicion[agente["id"]],
                                "el jefe debe aparecer antes que su subordinado")

    def test_F8_el_orden_es_determinista(self):
        org = org_real(5)
        primero, _ = ga.assemble(org)
        segundo, _ = ga.assemble(copy.deepcopy(org))
        self.assertEqual(primero["orden"], segundo["orden"])

    def test_el_sello_es_determinista_y_detecta_cambios(self):
        org = org_real(5)
        _, sha1 = ga.assemble(org)
        _, sha2 = ga.assemble(copy.deepcopy(org))
        self.assertEqual(sha1, sha2)
        org["agents"][1]["display_name"] = "Otro Nombre"
        _, sha3 = ga.assemble(org)
        self.assertNotEqual(sha1, sha3)


class ChangelogTests(unittest.TestCase):
    def test_la_segunda_version_lleva_el_diff(self):
        org = org_real(5)
        v1, _ = ga.assemble(org)
        # cambia un agente
        org["agents"][2]["display_name"] = "Renombrado"
        v2, sha2 = ga.assemble(org, previous=v1)
        self.assertEqual(v2["manifest"]["version"], 2)
        self.assertEqual(v2["manifest"]["previous_sha256"], v1["manifest"]["sha256"])
        self.assertEqual(v2["manifest"]["changelog"]["changed"], [org["agents"][2]["id"]])
        self.assertEqual(v2["manifest"]["changelog"]["added"], [])
        self.assertEqual(v2["manifest"]["changelog"]["removed"], [])
        self.assertNotEqual(sha2, v1["manifest"]["sha256"])


class RegistryTests(unittest.TestCase):
    def test_F9_publicacion_atomica_los_tres_o_ninguno(self):
        fallos = {"team"}
        def puerto(objetivo, sha):
            if objetivo in fallos:
                raise RuntimeError("servicio caido")
        reg = gr.GangRegistry(publish=puerto)
        with self.assertRaises(gr.RegistryError):
            reg.publish_atomic("a" * 64)
        # rollback: NINGUN objetivo quedo registrado
        self.assertTrue(all(fila["recorded_sha256"] is None for fila in reg.snapshot()))
        self.assertEqual(reg.sync_verdict()["code"], "EMPTY")

    def test_el_veredicto_exige_los_tres_iguales(self):
        reg = gr.GangRegistry()
        self.assertEqual(reg.sync_verdict()["code"], "EMPTY")
        reg.publish_atomic("b" * 64)
        self.assertEqual(reg.sync_verdict("b" * 64)["code"], "SYNCED")
        self.assertEqual(reg.sync_verdict("c" * 64)["code"], "STALE")

    def test_la_divergencia_se_declara(self):
        reg = gr.GangRegistry()
        reg._recorded["cordi"] = "d" * 64
        reg._recorded["agent-team"] = "e" * 64
        reg._recorded["team"] = "d" * 64
        self.assertEqual(reg.sync_verdict()["code"], "DIVERGED")

    def test_la_salud_es_la_verdad_no_promesa(self):
        reg = gr.GangRegistry()
        reg.publish_atomic("f" * 64)
        fila = reg.snapshot()[0]
        self.assertFalse(fila["mounted"], "no hay runtime: mounted es False aunque haya hash")
        self.assertIn("no montado", fila["note"])

    def test_un_sha_invalido_se_rechaza(self):
        reg = gr.GangRegistry()
        with self.assertRaises(gr.RegistryError):
            reg.publish_atomic("no-es-un-sha")


class AdapterTests(unittest.TestCase):
    """El ensamblador contra organizaciones REALES del producto, de 1 a 32."""

    def test_organizaciones_reales_de_varios_tamanos(self):
        for n in (1, 4, 12, 32):
            with self.subTest(n=n):
                artifact, sha = ga.assemble(org_real(n))
                self.assertEqual(artifact["manifest"]["total"], n)
                self.assertEqual(len(set(artifact["orden"])), n)
                self.assertRegex(sha, r"^[0-9a-f]{64}$")


class BridgeIntegrationTests(unittest.TestCase):
    """El bridge expone el gang en el estado y publica atomicamente."""

    def setUp(self):
        from engine import bridge
        self.bridge = bridge
        self.state = bridge.BridgeState()

    def test_el_estado_expone_el_gang_sin_organizacion(self):
        gang = self.state.public()['gang']
        self.assertIsNone(gang['ensamblado'])
        self.assertEqual(len(gang['servicios']), 3)
        self.assertEqual(gang['sync']['code'], 'EMPTY')

    def test_con_organizacion_el_ensamblado_aparece_sellado(self):
        self.state.organization = org_real(5)
        gang = self.state.public()['gang']
        self.assertIsNone(gang['ensamblado'].get('error'))
        self.assertEqual(gang['ensamblado']['total'], 5)
        self.assertRegex(gang['ensamblado']['sha256'], r'^[0-9a-f]{64}$')

    def test_publicar_registra_los_tres_y_queda_synced(self):
        self.state.organization = org_real(4)
        self.state.execute('gang-publish', {})
        gang = self.state.public()['gang']
        self.assertEqual(gang['sync']['code'], 'SYNCED')
        self.assertTrue(all(f['recorded_sha256'] for f in gang['servicios']))
        self.assertTrue(all(not f['mounted'] for f in gang['servicios']),
                        'la salud no se promete: no hay runtime')

    def test_publicar_sin_organizacion_falla_cerrado(self):
        with self.assertRaises(self.bridge.BridgeError):
            self.state.execute('gang-publish', {})

    def test_una_organizacion_rota_se_declara_como_error(self):
        org = org_real(5)
        org['agents'][1]['id'] = org['agents'][0]['id']
        self.state.organization = org
        gang = self.state.public()['gang']
        self.assertEqual(gang['ensamblado']['error'], 'duplicate_id')


if __name__ == "__main__":
    unittest.main()
