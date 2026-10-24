"""tests_harness_adapter.py - el adaptador mide, y su falsificador cae."""
import unittest

from engine.harness_adapter import adapt, cita_al_menos_dos, cita_existe_en_el_repo_factory, medir

RUTAS = {"a.py", "b.ts", "c.json", "Dockerfile"}
AGENTE = {
    "name": "P01_X", "role": "CEO", "mission": "m",
    "evidence_paths": ["a.py", "c.json"],
    "deliverables": ["uno", "dos"],
    "tool_policy": {"mode": "allowlist", "allow": ["ops_plan"]},
}


class AdaptTests(unittest.TestCase):
    def test_mapea_campos_reales(self):
        a = adapt(AGENTE)
        self.assertEqual(a["name"], "P01_X")
        self.assertEqual(a["destination"], (".json", ".py"))  # ordenado, estable
        self.assertEqual(len(a["acceptance"]), 2)
        self.assertEqual(a["policy_pack"]["rules"]["mode"], "allowlist")

    def test_deliverables_strings_no_revientan(self):
        a = adapt(dict(AGENTE, deliverables=["texto plano"]))
        self.assertEqual(a["acceptance"], ["texto plano"])


class ComprobacionTests(unittest.TestCase):
    def test_dos_rutas_pasa(self):
        self.assertTrue(cita_al_menos_dos(AGENTE))

    def test_una_ruta_falla(self):
        self.assertFalse(cita_al_menos_dos(dict(AGENTE, evidence_paths=["a.py"])))

    def test_rutas_reales_pasan(self):
        self.assertTrue(cita_existe_en_el_repo_factory(RUTAS)(AGENTE))

    def test_ruta_inventada_falla(self):
        falso = dict(AGENTE, evidence_paths=["a.py", "inventada.ts"])
        self.assertFalse(cita_existe_en_el_repo_factory(RUTAS)(falso))

    def test_sin_rutas_falla(self):
        self.assertFalse(cita_existe_en_el_repo_factory(RUTAS)(dict(AGENTE, evidence_paths=[])))


class MedirTests(unittest.TestCase):
    def test_cuenta_y_falsificador_cae(self):
        r = medir([AGENTE, dict(AGENTE, name="P02_Y")], RUTAS)
        self.assertEqual(r["agentes"], 2)
        self.assertEqual(r["agentica"], 2)
        self.assertEqual(r["evidencia_real"], 4)
        self.assertEqual(r["falsificador"], 2)

    def test_agente_con_ruta_inventada_no_cuenta(self):
        malo = dict(AGENTE, name="P_MALO", evidence_paths=["a.py", "no_existe.ts"])
        r = medir([malo], RUTAS)
        self.assertEqual(r["agentica"], 0)
        self.assertEqual(r["evidencia_real"], 0)
        # el falsificador sigue cayendo: su invariante es rompible
        self.assertEqual(r["falsificador"], 1)


if __name__ == "__main__":
    unittest.main()
