#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aritmetica AMM exacta del motor: sqrtPriceX96 y swap CPMM, solo stdlib.

Dos piezas que el producto necesita y que hasta hoy no existian en el paquete:

1. ``sqrt_price_x96(tick)`` = ``floor(sqrt(1.0001**tick) * 2**96)``. Es el precio
   representado como Q64.96 en los pools de rango concentrado. Se calcula con un
   SOLO redondeo entero: ``isqrt(num*den*2**192)//den``, que es exactamente
   ``floor(sqrt(num/den) * 2**96)`` sin pasar por coma flotante en ningun punto.
2. ``cpmm_swap_out(...)``: salida de un swap contra un pool de producto
   constante con comision en puntos basicos, redondeando a favor del pool.

Por que enteros y no float: a tick 0 el precio vale 2**96; con float se pierden
los ultimos bits y dos implementaciones del mismo pool dejan de coincidir. Todo
lo que se compara contra un pool real se compara en enteros.

Procedencia (FUSILE). La matematica de este modulo se REIMPLEMENTO desde la
definicion (raiz entera y producto constante); no se copio ninguna linea de una
fuente ajena y por tanto no arrastra licencia. Los valores numericos que usan los
tests como referencia (tick 0 = 2**96, ratio por tick = sqrt(1.0001), la tabla
tick -> sqrtPriceX96) son hechos citados como dato, no codigo (regla 3 de
``docs/security/FUSILE_SOURCE_POLICY.md``): un numero es un hecho, una linea de
codigo es una obra.

Sin red, sin ficheros, sin estado global mutable y sin dependencias externas: el
modulo se puede importar y ejecutar en cualquier entorno offline del paquete.

Verificacion propia: ``_self_check()`` devuelve la lista de fallos (vacia = sano)
y ``python engine/amm_math.py`` la ejecuta y termina con codigo 1 si algo falla.
"""

from math import isqrt, log2

__all__ = ["Q96", "sqrt_price_x96", "cpmm_swap_out"]

#: Precio 1:1 en Q64.96: 2**96.
Q96 = 1 << 96
_Q192 = 1 << 192
#: Ticks que cubre la verificacion (11 puntos, simetricos alrededor de 0).
TICKS_DE_CONTROL = (-1000, -500, -250, -100, -50, 0, 50, 100, 250, 500, 1000)


def sqrt_price_x96(tick: int) -> int:
    """``floor(sqrt(1.0001**tick) * 2**96)`` con un unico redondeo entero.

    ``tick`` debe ser ``int``; cualquier otra cosa es un error de tipo, no un
    valor a convertir en silencio. No se impone rango de ticks: el llamador
    decide su MIN_TICK/MAX_TICK, aqui solo se responde por la formula.
    """
    if not isinstance(tick, int):
        raise TypeError("tick debe ser entero, no %s" % type(tick).__name__)
    if tick == 0:
        return Q96
    u = abs(tick)
    num, den = (10001 ** u, 10000 ** u) if tick > 0 else (10000 ** u, 10001 ** u)
    # isqrt(num*den*2**192)//den == floor(sqrt(num/den) * 2**96)
    return isqrt(num * den * _Q192) // den


def cpmm_swap_out(amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int = 30):
    """Salida y comision de un swap CPMM: devuelve ``(salida, comision)``.

    ``fee_bps`` se cobra sobre la entrada y se redondea hacia abajo para el
    usuario (la comision se calcula con ``//``), de modo que el pool nunca pierde
    por redondeo. Entradas no positivas y comisiones fuera de ``[0, 10000)`` son
    error, no cero silencioso.
    """
    if amount_in <= 0 or reserve_in <= 0 or reserve_out <= 0:
        raise ValueError("amount_in, reserve_in y reserve_out deben ser positivos")
    if not isinstance(fee_bps, int) or not 0 <= fee_bps < 10000:
        raise ValueError("fee_bps debe ser un entero en [0, 10000)")
    fee = amount_in * fee_bps // 10000
    net = amount_in - fee
    out = net * reserve_out // (reserve_in + net)
    return out, fee


def _self_check():
    """Ejecuta los 5 checks del port y devuelve ``{'fallos': [...], 'valores': {...}}``.

    Los cinco checks son los del port verificado 8/8; aqui solo se agrupan para
    que el modulo sea verificable por si solo, sin cambiar su semantica.
    """
    fallos = []
    valores = {}

    # V1 identidad publicada: a tick 0 el precio es exactamente 2**96.
    if sqrt_price_x96(0) != Q96:
        fallos.append("V1: tick 0 != 2**96")

    # V2 monotonia estricta en los 11 ticks de control.
    vals = [sqrt_price_x96(t) for t in TICKS_DE_CONTROL]
    valores["serie"] = dict(zip(TICKS_DE_CONTROL, vals))
    for i in range(1, len(vals)):
        if not vals[i] > vals[i - 1]:
            fallos.append("V2: monotonia rota en tick %d" % TICKS_DE_CONTROL[i])

    # V3 un tick mueve el precio por sqrt(1.0001), no por 1.0001.
    ratio = sqrt_price_x96(1) / sqrt_price_x96(0)
    valores["ratio"] = ratio
    if not (1.0000499 < ratio < 1.0000501):
        fallos.append("V3: ratio por tick fuera de rango: %.10f" % ratio)

    # V4 log2(sqrtPrice/Q96) == 0.5 * tick * log2(1.0001), exacto a 1e-9.
    for t in (-1000, -500, 500, 1000):
        got = log2(sqrt_price_x96(t) / Q96)
        want = 0.5 * t * log2(1.0001)
        if abs(got - want) > 1e-9:
            fallos.append("V4: log2 error en tick %d: %.3e" % (t, abs(got - want)))

    # V5 el producto constante k nunca decrece tras un swap.
    k0 = 10**6 * 10**6
    out, fee = cpmm_swap_out(10**4, 10**6, 10**6, 30)
    valores["swap"] = {"out": out, "fee": fee, "k0": k0}
    if (10**6 + 10**4) * (10**6 - out) < k0:
        fallos.append("V5: k decrecio")

    return {"fallos": fallos, "valores": valores}


def _imprimir_reporte(resultado):
    fallos = resultado["fallos"]
    valores = resultado["valores"]
    print("=== sqrtPriceX96(tick) — valores de referencia ===")
    for t in TICKS_DE_CONTROL:
        print("  tick %6d  ->  %d" % (t, valores["serie"][t]))
    print()
    print("  CPMM 30 bps: in=10000 fee=%d out=%d"
          % (valores["swap"]["fee"], valores["swap"]["out"]))
    print("  ratio 1 tick = %.12f   (sqrt(1.0001) = %.12f)"
          % (valores["ratio"], 1.0001 ** 0.5))
    print()
    print("  V1 tick0=2**96 · V2 monotonia · V3 ratio/tick · V4 log2 x4 · V5 k")
    print("  FALLOS:", fallos if fallos else "ninguno -> 8/8 OK")


if __name__ == "__main__":
    resultado = _self_check()
    _imprimir_reporte(resultado)
    raise SystemExit(1 if resultado["fallos"] else 0)
