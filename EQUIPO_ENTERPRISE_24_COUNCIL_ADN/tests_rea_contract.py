"""tests_rea_contract.py - anti-clon y SPDX al SHA: los dos defectos que ya mordieron."""
import os
import tempfile
import unittest

from engine.extension_owners import CoverageError, assert_coverage, resolve_owner
from engine.instruction_contract import (ContractError, assert_distinct,
                                         build_prompt, clamp, reconcile)
from engine.rea_miner import classify_license, mine

PERFIL = {"name": "x", "role": "r", "goal": "g", "destination": [".py"],
          "policy_pack": {"id": "p"}, "acceptance": ["a"]}


class LicenciaTests(unittest.TestCase):
    def test_busl_con_mit_no_es_mit(self):
        v = classify_license("Business Source License 1.1 permitted", "s")
        self.assertEqual(v.spdx_id, "BUSL-1.1")
        self.assertFalse(v.permissive)

    def test_permitted_no_es_mit(self):
        self.assertEqual(classify_license("permitted to use freely", "s").spdx_id,
                         "UNKNOWN")

    def test_spdx_explicito_manda(self):
        self.assertEqual(
            classify_license("SPDX-License-Identifier: Apache-2.0", "s").spdx_id,
            "Apache-2.0")

    def test_mit_real(self):
        self.assertTrue(
            classify_license("MIT License\nPermission is hereby granted, free of charge", "s").permissive)

    def test_desconocida_es_conservadora(self):
        v = classify_license("texto suelto sin licencia", "s")
        self.assertEqual(v.spdx_id, "UNKNOWN")
        self.assertFalse(v.permissive)
        self.assertTrue(v.needs_review)


class CoberturaEnElOrigenTests(unittest.TestCase):
    def test_extensiones_del_repo_real_tienen_dueno(self):
        # las que el censo de T1 encontro: rhai, txt, csv, sh, md, json
        for ext in (".rhai", ".txt", ".csv", ".sh", ".md", ".json", ".png", ".woff2"):
            self.assertTrue(assert_coverage([ext]).ok, ext)

    def test_huerfana_sigue_fallando(self):
        with self.assertRaises(CoverageError):
            assert_coverage([".zzz9"])

    def test_rhai_tiene_dueno_propio(self):
        self.assertEqual(resolve_owner("cartridges/a.rhai"), "cartridge_engineer")

    def test_mine_con_gate_cierra(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "a.py"), "w").close()
            open(os.path.join(d, "b.sol"), "w").close()
            rep = mine(d)
            self.assertEqual(rep.files, 2)
            self.assertIn(".py", rep.extensions)


class AntiClonTests(unittest.TestCase):
    def test_perfil_completo_reconcilia(self):
        c = clamp(PERFIL)
        salida = build_prompt(c)
        self.assertIn("no suavizar", salida)
        data = dict(PERFIL, backstory="b", toolset=[], skill_bundle="s",
                    evidence_harness={})
        self.assertEqual(reconcile(__import__("json").dumps(data), c)["name"], "x")

    def test_frozen_alterado_rechaza(self):
        import json
        c = clamp(PERFIL)
        data = dict(PERFIL, goal="OTRO", backstory="b", toolset=[],
                    skill_bundle="s", evidence_harness={})
        with self.assertRaises(ContractError):
            reconcile(json.dumps(data), c)

    def test_clon_exacto_rechaza(self):
        with self.assertRaises(ContractError):
            assert_distinct([PERFIL, dict(PERFIL)])

    def test_perfiles_distintos_pasan(self):
        otro = dict(PERFIL)
        otro["name"] = "y"
        otro["goal"] = "otro"
        assert_distinct([PERFIL, otro])

    def test_sin_frozen_rechaza(self):
        with self.assertRaises(ContractError):
            clamp({"name": "x"})


if __name__ == "__main__":
    unittest.main()
