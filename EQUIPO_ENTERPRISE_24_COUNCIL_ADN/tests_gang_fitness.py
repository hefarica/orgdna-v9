#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Falsificacion del fitness: cada factor, revertido, mueve el numero.

Un fitness que no cambia cuando la corrida empeora es decoracion.
"""
import sys
import unittest

from engine import gang_fitness as gf


def recibo(index, status="validated", latency=1000, tokens=3000):
    return {"index": index, "status": status, "latency_ms": latency,
            "usage": {"prompt_tokens": 10, "completion_tokens": tokens, "total_tokens": tokens + 10}}


class FitnessTests(unittest.TestCase):
    def test_corrida_perfecta_puntua_alto(self):
        r = gf.fitness([recibo(i) for i in range(1, 5)], 4)
        self.assertEqual(r["exito"], 1.0)
        self.assertGreater(r["fitness"], 0.9)

    def test_un_agente_fallido_baja_el_exito(self):
        buenos = [recibo(i) for i in range(1, 4)]
        roto = recibo(4, status="response_refused")
        alto = gf.fitness(buenos + [recibo(4)], 4)
        bajo = gf.fitness(buenos + [roto], 4)
        self.assertLess(bajo["fitness"], alto["fitness"])

    def test_F_la_latencia_penaliza(self):
        rapido = gf.fitness([recibo(i, latency=1000) for i in range(1, 5)], 4)
        lento = gf.fitness([recibo(i, latency=120000) for i in range(1, 5)], 4)
        self.assertLess(lento["fitness"], rapido["fitness"],
                        "el fitness debe castigar la latencia extrema")

    def test_F_el_costo_penaliza(self):
        barato = gf.fitness([recibo(i, tokens=3000) for i in range(1, 5)], 4)
        caro = gf.fitness([recibo(i, tokens=30000) for i in range(1, 5)], 4)
        self.assertLess(caro["fitness"], barato["fitness"])

    def test_F_las_continuaciones_penalizan_poco_a_proposito(self):
        limpio = gf.fitness([recibo(i) for i in range(1, 5)], 4, continuations=0)
        continuado = gf.fitness([recibo(i) for i in range(1, 5)], 4, continuations=8)
        self.assertLess(continuado["fitness"], limpio["fitness"])
        self.assertGreater(continuado["fitness"], 0.9 * limpio["fitness"],
                           "continuar NO debe castigar como un fallo: es el precio de no recortar")

    def test_el_ultimo_recibo_del_agente_manda(self):
        # el agente 1 trunco-continuado (2 recibos) termina validado: cuenta como listo
        recibos = [recibo(1, status="continued_truncated"), recibo(1), recibo(2)]
        r = gf.fitness(recibos, 2)
        self.assertEqual(r["validados"], 2)
        self.assertEqual(r["exito"], 1.0)

    def test_entradas_invalidas_se_rechazan(self):
        with self.assertRaises(gf.FitnessError):
            gf.fitness([], 4)
        with self.assertRaises(gf.FitnessError):
            gf.fitness([recibo(1)], 0)
        with self.assertRaises(gf.FitnessError):
            gf.fitness([recibo(1)], 1, timeout_ms=0)
        with self.assertRaises(gf.FitnessError):
            gf.fitness([recibo(1)], 1, continuations=-1)

    def test_comparar_es_el_canary_en_una_linea(self):
        base = gf.fitness([recibo(i) for i in range(1, 5)], 4)
        mejor = gf.fitness([recibo(i, latency=500) for i in range(1, 5)], 4)
        self.assertTrue(gf.comparar(mejor, base))
        self.assertFalse(gf.comparar(base, mejor))


if __name__ == "__main__":
    unittest.main()
