"""Verifica si la memoizacion de validate_bundle absorbe la duplicacion medida en t20.

t20 localizo que la canalizacion ejecuta 19 `validate_bundle` completos por corrida sobre
los MISMOS bytes. Se cuentan por separado:
  - llamadas totales a validate_bundle,
  - calculos REALES (cache misses, via _validate_bundle_uncached).
Si la memoizacion funciona, los calculos reales deben ser ~1 por payload distinto.

Uso: python p3a_verifica_memo.py <ruta_al_arbol> [nombre_del_test]
"""
import sys
import unittest

tree = sys.argv[1]
test_name = (sys.argv[2] if len(sys.argv) > 2
             else 'tests_generation_pipeline.GenerationPipelineTests.'
                  'test_partial_inventory_requires_bound_explicit_acknowledgement')
sys.path.insert(0, tree)

from engine import bundle  # noqa: E402

counts = {'total': 0, 'real': 0}

_validate_orig = bundle.validate_bundle
_uncached_orig = bundle._validate_bundle_uncached


def validate_counting(payload):
    counts['total'] += 1
    return _validate_orig(payload)


def uncached_counting(payload):
    counts['real'] += 1
    return _uncached_orig(payload)


bundle.validate_bundle = validate_counting
bundle._validate_bundle_uncached = uncached_counting

suite = unittest.TestLoader().loadTestsFromName(test_name)
result = unittest.TextTestRunner(verbosity=0).run(suite)

print()
print('TEST      :', test_name)
print('RESULTADO :', 'OK' if result.wasSuccessful() else 'FALLO')
print('validate_bundle llamadas totales :', counts['total'])
print('calculos REALES (cache misses)   :', counts['real'])
print('ahorro por memoizacion           :', counts['total'] - counts['real'], 'validaciones evitadas')
