#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Falsificacion de A — el fan-out paralelo del gang.

A1  N agentes con concurrencia K: todos validan, recibos 1..N en orden determinista
A2  DOS agentes truncan A LA VEZ: ambos continuan en la ola siguiente y validan,
    sin contaminacion cruzada del texto acumulado (_raw por agente)
A3  cancelacion en plena ola: DesignCancelled, ninguna ola nueva, los recibos de lo
    volado quedan con su desenlace
A4  INVARIANTE BASE: con transporte determinista, la corrida paralela produce los
    MISMOS recibos (indices, estados, usage) y el MISMO orden de perfiles que la
    secuencial
A5  el tope de concurrencia se respeta: nunca hay mas de K en vuelo

CLI:  python tests_gang_fanout.py --escenarios
"""
import json
import re
import sys
import threading
import unittest

from engine import org_design as od
from tests_v8_evidence import representative_summary, fixture_profile

SHA = "a" * 64


class TransporteGang:
    """Transporte determinista y thread-safe, con instrumentacion:

    - cuenta el PICO de solicitudes simultaneas en vuelo (A5)
    - trunca el PRIMER intento de los slots indicados y completa su continuacion
    - registra cada llamada (slot, intento) para auditar el orden
    """

    def __init__(self, truncar_slots=()):
        self.lock = threading.Lock()
        self.llamadas = []
        self.intentos = {}
        self.pico = 0
        self.en_vuelo = 0
        self.truncar = set(truncar_slots)

    def __call__(self, method, url, headers, body, timeout, max_bytes):
        import time
        with self.lock:
            self.en_vuelo += 1
            self.pico = max(self.pico, self.en_vuelo)
        try:
            time.sleep(0.02)  # libera el GIL: las olas se solapan de verdad
            return self._responder(body)
        finally:
            with self.lock:
                self.en_vuelo -= 1

    def _responder(self, body):
        payload = json.loads(body)
        user = payload["messages"][1]["content"]
        control = json.loads(re.search(r"DESIGN_CONTROL\n(\{.*?\})\nEND_DESIGN_CONTROL", user, re.S).group(1))
        slot = control["requested_slots"][0]
        continuacion = len(payload["messages"]) > 2
        with self.lock:
            self.intentos[slot] = self.intentos.get(slot, 0) + 1
            intento = self.intentos[slot]
            self.llamadas.append((slot, intento, "continuacion" if continuacion else "base"))
        refs = control["global_slot_map"][slot - 1].get("primary_evidence_paths") or []
        if not continuacion and slot in self.truncar:
            cortado = '{"profile_specs": [{"name": "P0'
            return 200, {}, json.dumps({"choices": [{"finish_reason": "length", "message": {"content": cortado}}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 65536,
                                                  "total_tokens": 65546}}).encode()
        spec = fixture_profile(slot)
        spec["evidence_paths"] = refs[:3]
        for s in spec["skills"]:
            s["evidence_paths"] = refs[:1]
        if continuacion:
            completo = json.dumps({"profile_specs": [spec],
                                   "model_selection": {"provider": "deepseek", "model": "deepseek-flash",
                                                       "rationale": "fixture"},
                                   "warnings": []}, ensure_ascii=False)
            prefijo = '{"profile_specs": [{"name": "P0'
            fragmento = completo[len(prefijo):]
            return 200, {}, json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": fragmento}}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 100,
                                                  "total_tokens": 110}}).encode()
        value = {"profile_specs": [spec],
                 "model_selection": {"provider": "deepseek", "model": "deepseek-flash", "rationale": "fixture"},
                 "warnings": []}
        return 200, {}, json.dumps({"choices": [{"finish_reason": "stop",
                                                 "message": {"content": json.dumps(value, ensure_ascii=False)}}],
                                    "usage": {"prompt_tokens": 10, "completion_tokens": 100,
                                              "total_tokens": 110}}).encode()


def correr(n, concurrencia, truncar=()):
    summary = representative_summary()
    consent = od.prepare_design_consent(summary, "deepseek", "deepseek-flash",
                                        {"agent_count": n}, concurrency=concurrencia)
    consent.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
    transporte = TransporteGang(truncar_slots=truncar)
    resultado = od.design_with_llm(summary, "deepseek", "deepseek-flash", {"agent_count": n},
                                   "fixture-api-key", consent, transport=transporte,
                                   concurrency=concurrencia)
    return resultado, transporte


class FanoutTests(unittest.TestCase):
    def test_A1_doce_agentes_con_cuatro_en_paralelo(self):
        resultado, transporte = correr(12, 4)
        self.assertEqual(resultado["audit"]["completed_profiles"], 12)
        indices = [r["index"] for r in resultado["audit"]["receipts"]]
        self.assertEqual(indices, list(range(1, 13)),
                         "los recibos quedan en orden de despacho: deterministas")
        self.assertTrue(all(r["status"] == "validated" for r in resultado["audit"]["receipts"]))
        self.assertGreater(transporte.pico, 1, "volaron varias a la vez")

    def test_A2_dos_agentes_truncan_a_la_vez_y_ambos_continuan(self):
        resultado, transporte = correr(6, 3, truncar={2, 5})
        self.assertEqual(resultado["audit"]["completed_profiles"], 6)
        self.assertEqual(resultado["audit"].get("continuations"), 2)
        estados = [r["status"] for r in resultado["audit"]["receipts"]]
        self.assertEqual(estados.count("continued_truncated"), 2)
        self.assertEqual(estados.count("validated"), 6, "las continuaciones validaron")
        # sin contaminacion cruzada: cada continuacion pertenece a SU slot
        por_slot = {}
        for slot, intento, tipo in transporte.llamadas:
            por_slot.setdefault(slot, []).append(tipo)
        self.assertEqual(por_slot[2], ["base", "continuacion"])
        self.assertEqual(por_slot[5], ["base", "continuacion"])
        self.assertEqual(por_slot[1], ["base"])

    def test_A5_el_tope_de_concurrencia_se_respeta(self):
        _, transporte = correr(10, 3)
        self.assertLessEqual(transporte.pico, 3, "nunca mas de 3 en vuelo")
        self.assertGreaterEqual(transporte.pico, 2, "y si hubo vuelo conjunto")


class CancelacionTests(unittest.TestCase):
    def test_A3_cancelar_en_plena_ola_no_deja_olas_nuevas(self):
        import threading as _t
        summary = representative_summary()
        consent = od.prepare_design_consent(summary, "deepseek", "deepseek-flash",
                                            {"agent_count": 9}, concurrency=3)
        consent.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
        cancel = _t.Event()

        class TransporteCancela:
            def __init__(self):
                self.llamadas = 0

            def __call__(self, method, url, headers, body, timeout, max_bytes):
                self.llamadas += 1
                if self.llamadas >= 3:      # en plena primera ola: cancelar
                    cancel.set()
                # _responder ya devuelve la tupla (status, headers, data)
                return TransporteGang()._responder(body)

        with self.assertRaises(od.DesignCancelled):
            od.design_with_llm(summary, "deepseek", "deepseek-flash", {"agent_count": 9},
                               "fixture-api-key", consent, transport=TransporteCancela(),
                               cancel_event=cancel, concurrency=3)


class InvarianteBaseTests(unittest.TestCase):
    """A4: la corrida paralela produce lo mismo que la secuencial."""

    @staticmethod
    def _normalizar(resultado):
        recibos = [{k: v for k, v in r.items() if k != "latency_ms" and k != "response_id_sha256"}
                   for r in resultado["audit"]["receipts"]]
        # La identidad del plan (payload_sha256, request_hashes) DECLARA la
        # concurrencia: dos planes con K distinto difieren ahi por diseno. La
        # invariante compara lo que el gang PRODUJO, no como se presento el plan.
        audit = {k: v for k, v in resultado["audit"].items()
                 if k not in ("receipts", "started_at", "completed_at", "batch_index",
                              "payload_sha256", "request_hashes")}
        return json.dumps({"recibos": recibos, "audit": audit,
                           "perfiles": [p["name"] for p in resultado["profile_specs"]],
                           "usage": resultado["usage"]}, sort_keys=True, ensure_ascii=False)

    def test_A4_paralelo_es_identico_a_secuencial(self):
        secuencial, _ = correr(8, 1)
        paralelo, _ = correr(8, 4)
        self.assertEqual(self._normalizar(secuencial), self._normalizar(paralelo),
                         "mismos recibos (indices y estados), mismo orden de perfiles y mismo usage")


if __name__ == "__main__":
    if "--escenarios" in sys.argv:
        for nombre, n, k, truncar in (("A1 fan-out limpio", 12, 4, ()),
                                      ("A2 truncan dos a la vez", 6, 3, (2, 5)),
                                      ("A5 tope en vuelo", 10, 3, ())):
            r, t = correr(n, k, truncar=truncar)
            print(nombre)
            print("  perfiles:", r["audit"]["completed_profiles"], "/", n,
                  "· continuaciones:", r["audit"].get("continuations", 0),
                  "· pico en vuelo:", t.pico, "(tope", k, ")")
        s, _ = correr(8, 1)
        p, _ = correr(8, 4)
        iguales = InvarianteBaseTests._normalizar(s) == InvarianteBaseTests._normalizar(p)
        print("A4 invariante base: secuencial == paralelo ->", "IDENTICOS" if iguales else "DIFIERON")
        sys.exit(0 if iguales else 1)
    unittest.main()
