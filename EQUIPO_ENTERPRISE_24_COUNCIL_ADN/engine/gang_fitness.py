"""Fitness del gang, medido sobre los RECIBOS FACTURADOS REALES.

Nada de metricas declarativas: el fitness se calcula sobre lo que el proveedor
cobra y reporta — el recibo de cada solicitud con su latencia y sus tokens. Es la
metrica que la capa de evolucion necesita para puntuar una generacion contra otra.

Formula (ponderacion del diseno del gang):
    fitness = 0.60 * exito + 0.20 * latencia + 0.15 * costo + 0.05 * continuaciones

    exito           = agentes cuyo ULTIMO recibo es 'validated' / total
    latencia        = 1 / (1 + latencia_promedio_ms / timeout_ms)
    costo           = 1 / (1 + tokens_salida_totales / techo_por_agente * total)
    continuaciones  = 1 / (1 + continuaciones / total)

El campo `continuando` no es un vicio: es el precio de no recortar. Pesa poco (0.05)
a proposito — preferimos un gang que se continua antes que uno recortado.
"""
from __future__ import annotations

WEIGHTS = {"exito": 0.60, "latencia": 0.20, "costo": 0.15, "continuaciones": 0.05}
DEFAULT_TIMEOUT_MS = 60_000
DEFAULT_COST_CEILING_PER_AGENT = 100_000
VALIDATED = "validated"


class FitnessError(ValueError):
    """Los recibos o el total no bastan para puntuar."""


def _numero(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def fitness(receipts, total_agents, *, timeout_ms=DEFAULT_TIMEOUT_MS,
            cost_ceiling_per_agent=DEFAULT_COST_CEILING_PER_AGENT, continuations=0):
    """Puntua una corrida del gang sobre sus recibos facturados.

    `receipts` son los recibos del job (incluye las reemisiones y continuaciones:
    cada una es una solicitud facturada y por eso cuenta). `total_agents` es el N
    aprobado. Devuelve el desglose, no solo el numero, para que el panel muestre
    de donde salio cada punto.
    """
    if not isinstance(total_agents, int) or total_agents < 1:
        raise FitnessError("total_agents: entero >= 1.")
    if not isinstance(receipts, list) or not receipts:
        raise FitnessError("receipts: sin recibos facturados no hay fitness que puntuar.")
    if not isinstance(continuations, int) or continuations < 0:
        raise FitnessError("continuations: entero >= 0.")
    if timeout_ms <= 0 or cost_ceiling_per_agent <= 0:
        raise FitnessError("timeout_ms y cost_ceiling_per_agent deben ser positivos.")

    # El ULTIMO recibo de cada indice manda (una continuacion reemplaza al intento
    # truncado que la precedio).
    por_agente = {}
    for row in receipts:
        if isinstance(row, dict) and isinstance(row.get("index"), int):
            por_agente[row["index"]] = row
    if not por_agente:
        raise FitnessError("receipts: ningun recibo con indice de agente.")

    validados = [r for r in por_agente.values() if r.get("status") == VALIDATED]
    exito = len(validados) / total_agents

    latencias = [lat for r in por_agente.values()
                 for lat in [_numero(r.get("latency_ms"))] if lat is not None]
    latencia_prom = (sum(latencias) / len(latencias)) if latencias else 0.0
    factor_latencia = 1.0 / (1.0 + latencia_prom / timeout_ms)

    costos = [tok for r in por_agente.values()
              for tok in [_numero((r.get("usage") or {}).get("completion_tokens"))] if tok is not None]
    costo_total = sum(costos)
    factor_costo = 1.0 / (1.0 + costo_total / (cost_ceiling_per_agent * total_agents))

    factor_continuaciones = 1.0 / (1.0 + continuations / max(total_agents, 1))

    score = (WEIGHTS["exito"] * exito + WEIGHTS["latencia"] * factor_latencia
             + WEIGHTS["costo"] * factor_costo + WEIGHTS["continuaciones"] * factor_continuaciones)

    return {"fitness": round(score, 4), "exito": round(exito, 4), "validados": len(validados),
            "total_agentes": total_agents,
            "latencia_ms_promedio": round(latencia_prom, 1),
            "costo_tokens_salida": costo_total,
            "continuaciones": continuations,
            "factores": {"latencia": round(factor_latencia, 4),
                         "costo": round(factor_costo, 4),
                         "continuaciones": round(factor_continuaciones, 4)},
            "pesos": dict(WEIGHTS),
            "runtime_verified": False,
            "nota": "Fitness sobre recibos facturados; no acredita calidad del contenido."}


def comparar(actual, base):
    """La promocion del canary en una linea: solo sube si supera a la base."""
    if not isinstance(actual, dict) or not isinstance(base, dict):
        raise FitnessError("comparar: se requieren dos resultados de fitness.")
    return actual["fitness"] > base["fitness"]
