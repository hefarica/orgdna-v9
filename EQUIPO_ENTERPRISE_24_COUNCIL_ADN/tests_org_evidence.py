"""tests_org_evidence.py - mide lo recuperable y se niega a cargar a medias."""
import json
import os
import tempfile
import unittest

from engine.org_evidence import (NECESARIAS_PARA_ORGANIZACION, EvidenceError,
                                 inspect, load_or_refuse)

COMPLETO = {"agents": [{"evidence_paths": ["a.py"]}], "council": {"members": []},
            "dna_hash": "x", "dna_revision": 1, "config": {}, "competency_coverage": {}}


class InspectTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def _escribir(self, nombre, dados):
        ruta = os.path.join(self.d, nombre)
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(dados, fh)
        return ruta

    def test_completo_es_recuperable(self):
        r = inspect(self._escribir("ok.json", COMPLETO))
        self.assertTrue(r["can_rebuild_full_organization"])
        self.assertEqual(r["missing_for_organization"], [])
        self.assertIsNone(r["why_not"])

    def test_parcial_no_es_recuperable_y_dice_que_falta(self):
        r = inspect(self._escribir("p.json", {"agents": [{"evidence_paths": ["a", "b"]}]}))
        self.assertFalse(r["can_rebuild_full_organization"])
        self.assertEqual(set(r["missing_for_organization"]), set(NECESARIAS_PARA_ORGANIZACION))
        self.assertIn("profile_specs", r["why_not"])
        self.assertEqual(r["evidence_paths"], 2)

    def test_sin_agents_falla(self):
        with self.assertRaises(EvidenceError):
            inspect(self._escribir("v.json", {"council": {}}))

    def test_archivo_inexistente(self):
        with self.assertRaises(EvidenceError):
            inspect(os.path.join(self.d, "nada.json"))

    def test_json_invalido(self):
        ruta = os.path.join(self.d, "roto.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write("{no json")
        with self.assertRaises(EvidenceError):
            inspect(ruta)


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_carga_solo_si_es_completo(self):
        ruta = os.path.join(self.d, "ok.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump(COMPLETO, fh)
        dados = load_or_refuse(ruta)
        self.assertEqual(len(dados["agents"]), 1)

    def test_force_no_salta_la_regla(self):
        ruta = os.path.join(self.d, "p.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump({"agents": [{"evidence_paths": ["a"]}]}, fh)
        with self.assertRaises(EvidenceError):
            load_or_refuse(ruta, force=True)


if __name__ == "__main__":
    unittest.main()
