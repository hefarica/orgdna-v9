"""tests_forge_loop.py - el eje falla cerrado y el dry_run no gasta."""
import json
import unittest

from engine.evidence_harness import Check, for_agent, falsify
from engine.forge_dispatch import ProviderResponse, dispatch_factory
from engine.forge_loop import ForgeError, forge


class Reporte:
    extensions = {".py": 3, ".ts": 2, ".css": 1}


def perfil(i=0):
    return {"name": "agent_%d" % i, "role": "r", "goal": "g%d" % i,
            "destination": [".py"], "acceptance": ["x"], "skill_bundle": "p"}


def forge_kw(**over):
    kw = dict(miner_report=Reporte(), consent_cap=12, verified_cap=393216,
              per_profile_tokens=7753, dispatch=None, harness_for=for_agent,
              dry_run=True)
    kw.update(over)
    return kw


class ForgeLoopTests(unittest.TestCase):
    def test_dry_run_no_gasta(self):
        res = forge(profiles=[perfil(i) for i in range(74)], **forge_kw())
        self.assertTrue(res.ok)
        self.assertEqual(res.tokens, 0)
        self.assertTrue(any(r.phase == "F2" for r in res.receipts))
        self.assertTrue(any(r.key == "budget" for r in res.receipts))

    def test_sin_destino_falla(self):
        p = perfil(0)
        p["destination"] = []
        with self.assertRaises(ForgeError):
            forge(profiles=[p], **forge_kw())

    def test_clon_falla(self):
        with self.assertRaises(Exception):
            forge(profiles=[perfil(0), dict(perfil(0))], **forge_kw())

    def test_extension_huerfana_falla_gate1(self):
        class Malo:
            extensions = {".zzz9": 1}
        with self.assertRaises(Exception):
            forge(profiles=[perfil()], miner_report=Malo(), consent_cap=12,
                  verified_cap=393216, per_profile_tokens=7753, dispatch=None,
                  harness_for=for_agent, dry_run=True)

    def test_dispatch_real_con_tokens(self):
        def provider(prompt, cap):
            sobre = json.loads(prompt)
            p = dict(sobre["frozen"])
            p.update(backstory="b", toolset=[], skill_bundle="s", evidence_harness={})
            return ProviderResponse(json.dumps(p), "deepseek-flash", 12)

        res = forge(profiles=[perfil(i) for i in range(3)],
                    **forge_kw(dispatch=dispatch_factory(provider, verified_model="deepseek-flash"),
                               dry_run=False))
        self.assertTrue(res.ok)
        self.assertEqual(res.tokens, 36)

    def test_modelo_no_verificado_falla(self):
        def provider(prompt, cap):
            sobre = json.loads(prompt)
            p = dict(sobre["frozen"])
            p.update(backstory="b", toolset=[], skill_bundle="s", evidence_harness={})
            return ProviderResponse(json.dumps(p), "otro", 9)

        with self.assertRaises(ForgeError):
            forge(profiles=[perfil()],
                  **forge_kw(dispatch=dispatch_factory(provider, verified_model="deepseek-flash"),
                             dry_run=False))


class ForAgentTests(unittest.TestCase):
    def test_falsificador_cae_al_romperlo(self):
        checks = for_agent({"name": "a", "destination": [".py"],
                            "acceptance": ["x"], "policy_pack": {"id": "p"}})
        self.assertTrue(falsify(checks["falsifier"][0]))

    def test_perfil_sin_destino_no_pasa(self):
        checks = for_agent({"name": "a", "destination": [], "acceptance": [],
                            "policy_pack": {"id": "p"}})
        self.assertFalse(falsify(checks["falsifier"][0]))


if __name__ == "__main__":
    unittest.main()
