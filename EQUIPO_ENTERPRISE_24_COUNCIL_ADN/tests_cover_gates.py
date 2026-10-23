"""tests_cover_gates.py - los tres gates fallan cerrado, y el tope no se degrada."""
import unittest

from engine.extension_owners import (CoverageError, assert_coverage, assert_map_sane,
                                     coverage_gate, resolve_owner)
from engine.budget_governor import (BudgetError, assert_cap_preserved, plan_budget)
from engine.policy_pack import PolicyError, assert_injected, inject
from engine.evidence_harness import Check, HarnessError, falsify, run_harness


class Gate1CoverageTests(unittest.TestCase):
    def test_mapa_sano(self):
        assert_map_sane()

    def test_extensiones_conocidas_cubren(self):
        self.assertTrue(assert_coverage([".py", ".sol", ".ts", ".sql"]).ok)

    def test_huerfana_falla_cerrado(self):
        with self.assertRaises(CoverageError):
            assert_coverage([".zzz9"])

    def test_coverage_reporta_huerfanas(self):
        rep = coverage_gate([".py", ".zzz9"])
        self.assertFalse(rep.ok)
        self.assertEqual(rep.orphans, (".zzz9",))

    def test_ambiguos_por_ruta(self):
        self.assertEqual(resolve_owner(".github/workflows/ci.yml"), "ci_engineer")
        self.assertEqual(resolve_owner("k8s/deploy.yml"), "k8s_engineer")
        self.assertEqual(resolve_owner("Dockerfile"), "docker_engineer")


class BudgetGovernorTests(unittest.TestCase):
    def test_defecto_historico_32_falla(self):
        with self.assertRaises(BudgetError) as ctx:
            plan_budget(max_output_tokens=32, profiles=30,
                        per_profile_tokens=7753, consent_cap=4)
        self.assertIn("output_budget_too_small", str(ctx.exception))

    def test_tope_no_se_degrada(self):
        self.assertEqual(assert_cap_preserved(393216, 32), 393216)

    def test_plan_sano(self):
        p = plan_budget(max_output_tokens=393216, profiles=74,
                        per_profile_tokens=7753, consent_cap=12)
        self.assertGreaterEqual(p.per_batch, 1)
        self.assertEqual(p.max_output_tokens, 393216)
        self.assertLessEqual(p.sent_requests_cap, 12)

    def test_sin_consentimiento_falla(self):
        with self.assertRaises(BudgetError):
            plan_budget(max_output_tokens=393216, profiles=1,
                        per_profile_tokens=1000, consent_cap=0)


class Gate2PolicyTests(unittest.TestCase):
    def test_inyecta_e_inmutable(self):
        p = inject("trading_safety_v1", {"name": "x", "destination": [".py"]})
        assert_injected(p)
        self.assertIn("policy_pack", p["policy_pack"]["_non_negotiable"])

    def test_sin_pack_falla(self):
        with self.assertRaises(PolicyError):
            assert_injected({"name": "x", "acceptance": ["a"]})

    def test_pack_desconocido_falla(self):
        with self.assertRaises(PolicyError):
            inject("no_existe", {"name": "x"})


class Gate3EvidenceTests(unittest.TestCase):
    def _sizing(self):
        state = {"pct": 1.5}
        return Check("sizing_le_2pct", "falsifier",
                     lambda: state["pct"] <= 2.0,
                     lambda: state.__setitem__("pct", 2.5))

    def test_harness_completo(self):
        rep = run_harness({
            "agentic": (Check("a", "agentic", lambda: True),),
            "evidence": (Check("e1", "evidence", lambda: True),
                         Check("e2", "evidence", lambda: True)),
            "falsifier": (self._sizing(),),
        })
        self.assertTrue(rep.ok)

    def test_falsificador_sin_rotura_no_vale(self):
        self.assertFalse(falsify(Check("f", "falsifier", lambda: True)))

    def test_falsificador_que_no_cae_no_vale(self):
        # el invariante se "rompe" pero el check sigue pasando -> no es falsificador
        self.assertFalse(falsify(Check("f", "falsifier", lambda: True,
                                       lambda: None)))

    def test_cuotas_insuficientes_fallan(self):
        with self.assertRaises(HarnessError):
            run_harness({"agentic": (Check("a", "agentic", lambda: True),)})


if __name__ == "__main__":
    unittest.main()
