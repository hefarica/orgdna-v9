#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Producto: la aritmetica AMM del motor responde lo que un pool real responde.

Este test no comprueba que el modulo compile: comprueba los cinco checks del
port verificado y los bordes donde una implementacion comoda (float, cero
silencioso, comision negativa) daria un numero plausible y equivocado.

Los valores de referencia son hechos citados como dato, no codigo de terceros:
tick 0 vale 2**96, un tick mueve el precio por sqrt(1.0001) y el swap de
referencia (10**4 sobre reservas 10**6/10**6 al 0,30 %) entrega 9871 con 30 de
comision. Se citan en `docs/security/FUSILE_SOURCE_POLICY.md` regla 3.
"""
import unittest

from engine import amm_math as am


class AritmeticaAmmTests(unittest.TestCase):
    # --- V1: identidad publicada -------------------------------------------
    def test_tick_cero_vale_q96(self):
        self.assertEqual(am.sqrt_price_x96(0), 2 ** 96)
        self.assertEqual(am.sqrt_price_x96(0), am.Q96)

    # --- V2: monotonia estricta --------------------------------------------
    def test_monotonia_estricta_en_once_ticks(self):
        ticks = am.TICKS_DE_CONTROL
        self.assertEqual(len(ticks), 11)
        valores = [am.sqrt_price_x96(t) for t in ticks]
        for anterior, siguiente in zip(valores, valores[1:]):
            self.assertGreater(siguiente, anterior)

    # --- V3: un tick es sqrt(1.0001), no 1.0001 ----------------------------
    def test_ratio_por_tick_es_raiz_de_1_0001(self):
        ratio = am.sqrt_price_x96(1) / am.sqrt_price_x96(0)
        self.assertAlmostEqual(ratio, 1.0001 ** 0.5, places=12)
        # Y no confundirlo con 1.0001, que seria el error de bulto.
        self.assertLess(ratio, 1.0001)

    # --- V4: log2 del precio contra la definicion --------------------------
    def test_log2_coincide_con_la_definicion_en_cuatro_ticks(self):
        from math import log2
        for t in (-1000, -500, 500, 1000):
            got = log2(am.sqrt_price_x96(t) / am.Q96)
            esperado = 0.5 * t * log2(1.0001)
            self.assertLess(abs(got - esperado), 1e-9, "tick %d" % t)

    # --- V5: el producto constante no decrece ------------------------------
    def test_cpmm_el_producto_constante_no_decrece(self):
        r_in = r_out = 10 ** 6
        out, fee = am.cpmm_swap_out(10 ** 4, r_in, r_out, 30)
        self.assertGreaterEqual((r_in + 10 ** 4) * (r_out - out), r_in * r_out)
        self.assertGreater(out, 0)

    def test_cpmm_vector_de_referencia(self):
        # 10**4 al 0,30 % -> comision 30; salida 9970*10**6//(10**6+9970) = 9871.
        self.assertEqual(am.cpmm_swap_out(10 ** 4, 10 ** 6, 10 ** 6, 30), (9871, 30))

    def test_self_check_no_reporta_fallos(self):
        resultado = am._self_check()
        self.assertEqual(resultado["fallos"], [])
        self.assertIn(0, resultado["valores"]["serie"])

    # --- divergencia conocida, documentada y ejecutable ---------------------
    def test_divergencia_conocida_de_redondeo_contra_v3_core(self):
        """El port redondea hacia abajo; el contrato canonico redondea hacia arriba.

        Valores de referencia leidos de `Uniswap/v3-core@aab5aa01`
        `test/__snapshots__/TickMath.spec.ts.snap` (hechos citados como dato,
        FUSILE regla 3). Para tick negativo el contrato devuelve exactamente una
        unidad mas que este modulo porque redondea al alza. No es un fallo oculto:
        es una decision de redondeo registrada aqui para que quien la cambie tenga
        que cambiarla a proposito.
        """
        referencia_v3 = {
            -50: 79030349367926598376800521322,
            -100: 78833030112140176575862854579,
            -250: 78244023372248365697264290337,
            -500: 77272108795590369356373805297,
            -1000: 75364347830767020784054125655,
        }
        for tick, esperado_v3 in referencia_v3.items():
            nuestro = am.sqrt_price_x96(tick)
            self.assertEqual(esperado_v3 - nuestro, 1,
                             "tick %d: se esperaba divergencia de 1 unidad" % tick)
        # Control: a tick 0 no hay redondeo posible y ambos coinciden.
        self.assertEqual(am.sqrt_price_x96(0), 79228162514264337593543950336)

    # --- bordes obligatorios ------------------------------------------------
    def test_tick_no_entero_es_type_error(self):
        for malo in (1.0, "100", None, [1]):
            with self.assertRaises(TypeError):
                am.sqrt_price_x96(malo)

    def test_amount_in_no_positivo_es_value_error(self):
        for malo in (0, -1, -10 ** 6):
            with self.assertRaises(ValueError):
                am.cpmm_swap_out(malo, 10 ** 6, 10 ** 6, 30)

    def test_reservas_no_positivas_son_value_error(self):
        with self.assertRaises(ValueError):
            am.cpmm_swap_out(10 ** 4, 0, 10 ** 6, 30)
        with self.assertRaises(ValueError):
            am.cpmm_swap_out(10 ** 4, 10 ** 6, -5, 30)

    def test_fee_fuera_de_rango_es_value_error(self):
        for mala in (-1, 10000, 20000):
            with self.assertRaises(ValueError):
                am.cpmm_swap_out(10 ** 4, 10 ** 6, 10 ** 6, mala)

    def test_fee_cero_es_swap_sin_comision(self):
        out, fee = am.cpmm_swap_out(10 ** 4, 10 ** 6, 10 ** 6, 0)
        self.assertEqual(fee, 0)
        self.assertEqual(out, 10 ** 4 * 10 ** 6 // (10 ** 6 + 10 ** 4))


if __name__ == "__main__":
    unittest.main()
