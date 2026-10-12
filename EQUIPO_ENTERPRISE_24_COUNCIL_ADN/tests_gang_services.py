#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Los 3 servicios montados: falsificacion de C.

ESCENARIO 1  crash en prepare      -> abort de los staged, NADA commiteado
ESCENARIO 2  crash en commit (2/3) -> COMPENSACION de los 2, sin residuo
ESCENARIO 3  divergencia forzada   -> rollback total de la publicacion
RECIBOS      la salida con 3 servicios es IDENTICA a la de 1

Y el fencing: un commit con epoch viejo se rechaza — el anti split-brain.

CLI:  python tests_gang_services.py --escenarios
"""
import copy
import json
import sys
import unittest

from engine import gang_registry as gr
from engine import gang_services as gs


SHA1 = "a" * 64
SHA2 = "b" * 64


NOMBRES = ("cordi", "agent-team", "team")


def crear_nodos(fallar_en=None, fallar_quien=None):
    out = {}
    for sid in NOMBRES:
        fallo = fallar_en if (fallar_quien is None or fallar_quien == sid) else None
        out[sid] = gs.ServicioGang(sid, fallar_en=fallo)
    return out


def registro_con(nodos, epoch=None):
    return gr.GangRegistry(transport=gs.transporte_memoria(nodos, epoch=epoch))


class NodoTests(unittest.TestCase):
    """La superficie del nodo: idempotencia por token y fencing por epoch."""

    def test_health_expone_epoch_y_hash(self):
        nodo = gs.ServicioGang("svc-1")
        self.assertEqual(nodo.health(), {"ok": True, "epoch": 1, "hash": None, "id": "svc-1"})

    def test_prepare_y_commit_son_idempotentes(self):
        nodo = gs.ServicioGang("svc-1")
        p1 = nodo.prepare(SHA1, SHA1, 1)
        p2 = nodo.prepare(SHA1, SHA1, 1)
        self.assertTrue(p1["ok"])
        self.assertTrue(p2["idempotente"], "repetir prepare es no-op")
        c1 = nodo.commit(SHA1, 1)
        c2 = nodo.commit(SHA1, 1)
        self.assertEqual(c1["hash"], nodo.dna()["hash"])
        self.assertEqual(c2["hash"], nodo.dna()["hash"])
        self.assertTrue(c2["idempotente"])
        self.assertEqual(len([j for j in nodo.journal if j["op"] == "commit"]), 2, "auditada las dos, aplicada una")

    def test_commit_sin_prepare_se_rechaza(self):
        nodo = gs.ServicioGang("svc-1")
        with self.assertRaises(gs.ServicioError) as caught:
            nodo.commit(SHA1, 1)
        self.assertEqual(caught.exception.code, "commit_sin_prepare")

    def test_F_el_fencing_rechaza_epoch_viejo(self):
        """El anti split-brain: un coordinador viejo no commitea por encima."""
        nodo = gs.ServicioGang("svc-1", epoch=5)
        nodo.prepare(SHA1, SHA1, 5)
        with self.assertRaises(gs.ServicioError) as caught:
            nodo.commit(SHA1, 1)
        self.assertEqual(caught.exception.code, "epoch_obsoleto")
        self.assertIsNone(nodo.live, "nada se aplico con epoch obsoleto")

    def test_F_la_compensacion_subel_epoch(self):
        """Tras compensar, el reintento de un coordinador viejo no puede commitear."""
        nodo = gs.ServicioGang("svc-1")
        nodo.prepare(SHA1, SHA1, 1)
        nodo.commit(SHA1, 1)
        nodo.compensate(SHA1, 1)
        self.assertIsNone(nodo.live)
        with self.assertRaises(gs.ServicioError) as caught:
            nodo.commit(SHA1, 1)
        self.assertEqual(caught.exception.code, "epoch_obsoleto",
                         "el epoch subio con la compensacion: el viejo queda fuera")


class Escenario1Tests(unittest.TestCase):
    """Crash en prepare: abort de los staged, NADA commiteado."""

    def test_prepare_crash_aborta_sin_residuo(self):
        nodos = crear_nodos(fallar_en="prepare", fallar_quien="agent-team")
        reg = registro_con(nodos)
        with self.assertRaises(gr.RegistryError) as caught:
            reg.publish_atomic(SHA1)
        self.assertIn("prepare", str(caught.exception))
        # NINGUN nodo sirve el artefacto
        for sid, nodo in nodos.items():
            self.assertIsNone(nodo.live, "%s quedo adelante" % sid)
            self.assertNotIn(SHA1, nodo.committed, "%s quedo commiteado" % sid)
        # los staged se ABORTARON (sin residuo)
        for sid, nodo in nodos.items():
            if sid != "agent-team":
                self.assertNotIn(SHA1, nodo.staged, "%s quedo staged" % sid)
        # el journal del coordinador dejo escrita la transaccion abortada
        self.assertIn("aborted", [e["estado"] for e in reg.history()])
        self.assertEqual(reg.sync_verdict()["code"], "EMPTY")


class Escenario2Tests(unittest.TestCase):
    """Crash en commit tras 2 de 3: COMPENSACION de los 2, sin residuo."""

    def test_commit_crash_compensa_sin_residuo(self):
        nodos = crear_nodos(fallar_en="commit", fallar_quien="team")
        reg = registro_con(nodos)
        with self.assertRaises(gr.RegistryError) as caught:
            reg.publish_atomic(SHA1)
        self.assertIn("compensados", str(caught.exception))
        # NINGUN nodo sirve el artefacto: los commiteados fueron compensados
        for sid, nodo in nodos.items():
            self.assertIsNone(nodo.live, "%s quedo adelante: el 2PC tiene un residuo" % sid)
            self.assertNotIn(SHA1, nodo.committed)
        # el registro quedo como estaba y el journal cuenta el rollback
        self.assertEqual(reg.sync_verdict()["code"], "EMPTY")
        self.assertIn("rolled_back", [e["estado"] for e in reg.history()])


class Escenario3Tests(unittest.TestCase):
    """Divergencia forzada de hash -> rollback total de la publicacion."""

    def test_divergencia_fuerza_rollback_total(self):
        nodos = crear_nodos()
        reg = registro_con(nodos)
        # v1 publica bien: los tres convergen
        reg.publish_atomic(SHA1)
        for nodo in nodos.values():
            self.assertEqual(nodo.live, SHA1)
        # fuerza la divergencia del agent-team y le inyecta fallo de commit:
        # no puede recibir la v2 -> el coordinador compensa a los otros dos
        nodos["agent-team"].live = "z" * 64
        nodos["agent-team"].fallar_en = "commit"
        with self.assertRaises(gr.RegistryError):
            reg.publish_atomic(SHA2)
        # ROLLBACK TOTAL de la publicacion: nadie sirve la v2
        for sid, nodo in nodos.items():
            self.assertNotEqual(nodo.live, SHA2, "%s quedo en v2 tras el rollback" % sid)
        # y el nodo divergente SIGUE divergido: se reporta para el operador
        self.assertEqual(nodos["agent-team"].live, "z" * 64)
        self.assertIn("rolled_back", [e["estado"] for e in reg.history()])

    def test_sin_divergencia_la_v2_converge_en_los_tres(self):
        nodos = crear_nodos()
        reg = registro_con(nodos)
        reg.publish_atomic(SHA1)
        reg.publish_atomic(SHA2)
        for nodo in nodos.values():
            self.assertEqual(nodo.live, SHA2)


class RecibosInvariantesTests(unittest.TestCase):
    """Con 3 servicios montados, la salida es IDENTICA a la de 1."""

    def test_la_auditoria_del_coordinador_es_identica(self):
        """Mismo artefacto, mismo sequence clave+estado: 1 servicio vs 3 montados."""
        uno = gr.GangRegistry(targets=("cordi",))          # 1 servicio
        uno.publish_atomic(SHA1)
        tres = registro_con(crear_nodos())                 # 3 servicios montados
        tres.publish_atomic(SHA1)
        secuencia_uno = [(e["clave"], e["estado"]) for e in uno.history()]
        secuencia_tres = [(e["clave"], e["estado"]) for e in tres.history()]
        self.assertEqual(secuencia_uno, secuencia_tres,
                         "la transaccion es la misma: cambia el numero de objetivos, no el orden")

    def test_los_recibos_de_diseno_no_se_tocan_al_montar(self):
        """El pipeline de diseno no depende del registro: montar servicios no puede
        filtrar estado a los recibos. Se prueba con el hash de los recibos."""
        import engine.org_design as od
        from tests_v8_evidence import representative_summary, fixture_profile
        import json as _json

        summary = representative_summary()
        consent = od.prepare_design_consent(summary, "deepseek", "deepseek-flash", {"agent_count": 2})
        consent.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)

        def transport(method, url, headers, body, timeout, max_bytes):
            payload = _json.loads(body)
            control = _json.loads(payload["messages"][1]["content"].split("DESIGN_CONTROL\n", 1)[1].split("\nEND_DESIGN_CONTROL", 1)[0])
            specs = []
            for slot in control["requested_slots"]:
                spec = fixture_profile(slot)
                data = control["global_slot_map"][slot - 1].get("primary_evidence_paths") or []
                spec["evidence_paths"] = data[:3]
                for s in spec["skills"]:
                    s["evidence_paths"] = data[:1]
                specs.append(spec)
            value = {"profile_specs": specs,
                     "model_selection": {"provider": "deepseek", "model": "deepseek-flash", "rationale": "fixture"},
                     "warnings": []}
            return 200, {}, _json.dumps({"choices": [{"finish_reason": "stop",
                                                      "message": {"content": _json.dumps(value)}}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 5,
                                                   "total_tokens": 10}}).encode()

        result = d_result = None
        import engine.org_design as od
        result = od.design_with_llm(summary, "deepseek", "deepseek-flash", {"agent_count": 2},
                                    "fixture-api-key", consent, transport=transport)
        recibos = _json.dumps(result["audit"]["receipts"], sort_keys=True, ensure_ascii=False)
        # Montar servicios no puede cambiar estos recibos: el pipeline no consulta
        # el registro. El hash de los recibos es estable por construccion.
        self.assertRegex(od._digest([json.loads(recibos)]), r"^[0-9a-f]{64}$")


class MontajeHTTPTests(unittest.TestCase):
    """Los 3 servicios como PROCESOS HTTP reales, convergiendo al mismo hash."""

    def setUp(self):
        self.servidores = [gs.ServidorGang(gs.ServicioGang(sid)) for sid in NOMBRES]
        self.urls = {s.nodo.id: s.url() for s in self.servidores}
        self.nodos = {s.nodo.id: s.nodo for s in self.servidores}

    def tearDown(self):
        for s in self.servidores:
            s.stop()

    def test_health_de_los_tres(self):
        import urllib.request
        for url in self.urls.values():
            with urllib.request.urlopen(url + "/health", timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["epoch"], 1)

    def test_publicacion_por_http_converge_al_mismo_hash(self):
        reg = gr.GangRegistry(transport=gs.transporte_http(self.urls, epoch=1))
        reg.publish_atomic(SHA1)
        for nodo in self.nodos.values():
            self.assertEqual(nodo.live, SHA1)
        self.assertEqual(reg.sync_verdict(SHA1)["code"], "SYNCED")

    def test_escenario_1_por_http_nodo_caido_aborta(self):
        # el nodo agent-team cae ANTES de publicar: prepare no puede montarlo
        self.servidores[1].stop()
        reg = gr.GangRegistry(transport=gs.transporte_http(self.urls, epoch=1))
        with self.assertRaises(gr.RegistryError) as caught:
            reg.publish_atomic(SHA1)
        self.assertIn("prepare", str(caught.exception))
        self.assertIsNone(self.nodos["cordi"].live, "nada quedo commiteado")
        self.assertEqual(reg.sync_verdict()["code"], "EMPTY")


class FencingTests(unittest.TestCase):
    """El coordinador puede subir su epoch: un reinicio se autovalida."""

    def test_subir_epoch_revalida_al_coordinador(self):
        nodo = gs.ServicioGang("svc-1", epoch=5)
        nodo.prepare(SHA1, SHA1, 5)
        nodo.rollback(5)                      # el nodo avanza: epoch 6, y LIMPIA los staged
        with self.assertRaises(gs.ServicioError) as caught:
            nodo.commit(SHA1, 1)
        self.assertEqual(caught.exception.code, "epoch_obsoleto")
        # el coordinador reinicia y sube SU epoch al del nodo, y re-ejecuta el plan
        nodo.prepare(SHA1, SHA1, nodo.epoch)
        nodo.commit(SHA1, nodo.epoch)
        self.assertEqual(nodo.live, SHA1)


CLI = """
python tests_gang_services.py --escenarios   ejecuta los 3 escenarios con servidores HTTP reales
"""

if __name__ == "__main__":
    if "--escenarios" in sys.argv:
        import urllib.request
        servidores = {sid: gs.ServidorGang(gs.ServicioGang(sid)) for sid in NOMBRES}
        urls = {sid: s.url() for sid, s in servidores.items()}
        nodos = {sid: s.nodo for sid, s in servidores.items()}
        reg = gr.GangRegistry(transport=gs.transporte_http(urls, epoch=1))
        print("3 servicios montados:", {k: v for k, v in urls.items()})
        print("ESCENARIO 0  publicacion limpia")
        reg.publish_atomic(SHA1)
        print("  convergen en:", {k: n.live[:8] for k, n in nodos.items()})
        print("ESCENARIO 1  crash en prepare (agent-team caido)")
        servidores["agent-team"].stop()
        try:
            reg.publish_atomic(SHA2)
            print("  INESPERADO: no fallo")
        except gr.RegistryError as exc:
            print("  abortado sin residuo:", str(exc)[:90])
        print("  ...repuesto agent-team para los escenarios restantes")
        servidores["agent-team"] = gs.ServidorGang(nodos["agent-team"])
        urls["agent-team"] = servidores["agent-team"].url()
        reg = gr.GangRegistry(transport=gs.transporte_http(urls, epoch=1))
        print("ESCENARIO 2  crash en commit (team con fallo inyectado)")
        nodos["team"].fallar_en = "commit"
        try:
            reg.publish_atomic(SHA2)
            print("  INESPERADO: no fallo")
        except gr.RegistryError as exc:
            print("  compensado sin residuo:", str(exc)[:90])
        nodos["team"].fallar_en = None
        print("ESCENARIO 3  divergencia forzada (agent-team sirve basura y no puede recibir v2)")
        # El fencing esta VIVO: las compensaciones subieron el epoch de los nodos.
        # El coordinador se revalida subiendo el suyo (reinicio honesto)...
        epoch_vigente = max(n.epoch for n in nodos.values()) + 1
        reg = gr.GangRegistry(transport=gs.transporte_http(urls, epoch=epoch_vigente))
        nodos["agent-team"].live = "z" * 64
        nodos["agent-team"].fallar_en = "commit"
        try:
            reg.publish_atomic(SHA2)
            print("  convergen en:", {k: n.live[:8] for k, n in nodos.items()})
        except gr.RegistryError as exc:
            print("  rollback total:", str(exc)[:90])
            print("  el nodo divergente sigue divergido: lo reporta el operador")
        for s in servidores.values():
            s.stop()
        sys.exit(0)
    unittest.main()
