"""P3-A · Sonda de coste por etapa de la ruta de exportación.

Mide, para UN test concreto, cuánto tiempo se consume en cada etapa de `building_exports`:
construcción del snapshot, sellado del paquete y validación del bundle.

No modifica ningún archivo del árbol: instrumenta en memoria los atributos de módulo,
que es como `generation_pipeline._run` los resuelve en tiempo de llamada.

Uso:  python p3a_sonda_export.py <ruta_al_arbol> [nombre_del_test]
"""
import sys
import time
import unittest

tree = sys.argv[1]
test_name = (sys.argv[2] if len(sys.argv) > 2
             else 'tests_generation_pipeline.GenerationPipelineTests.'
                  'test_partial_inventory_requires_bound_explicit_acknowledgement')
sys.path.insert(0, tree)

from engine import export_artifacts, bundle  # noqa: E402

timings = {}


def wrap(module, name, label):
    original = getattr(module, name)

    def timed(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            elapsed = time.perf_counter() - started
            timings[label] = timings.get(label, 0.0) + elapsed
            timings[label + '__n'] = timings.get(label + '__n', 0) + 1

    setattr(module, name, timed)


wrap(export_artifacts, 'build_export_snapshot', 'snapshot')
wrap(bundle, 'build_package_bytes', 'package')
wrap(bundle, 'validate_bundle', 'validate')

suite = unittest.TestLoader().loadTestsFromName(test_name)
result = unittest.TextTestRunner(verbosity=0).run(suite)

print()
print('ARBOL     :', tree)
print('TEST      :', test_name)
print('RESULTADO :', 'OK' if result.wasSuccessful() else 'FALLO')
total = 0.0
for key in ('snapshot', 'package', 'validate'):
    value = timings.get(key, 0.0)
    count = timings.get(key + '__n', 0)
    total += value
    print(f'  {key:10} {value:8.3f} s   ({count} llamada/s)')
print(f'  {"TOTAL":10} {total:8.3f} s')
