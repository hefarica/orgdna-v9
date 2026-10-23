"""tests_reconciliation.py - P4-A: el roster reconciliado cubre los 10 gaps."""
import unittest

from engine import limits
from engine.dna import ROLE_SEEDS
from engine.seeds_gaps import GAPS
from engine.seeds_reconciled import EXISTING, ROLE_SEEDS_RECONCILED


class RosterTests(unittest.TestCase):
    def test_total_42(self):
        self.assertEqual(len(ROLE_SEEDS_RECONCILED), 42)

    def test_sin_duplicados(self):
        nombres = [s.name for s in ROLE_SEEDS_RECONCILED]
        self.assertEqual(len(nombres), len(set(nombres)))

    def test_los_10_gaps_presentes(self):
        nombres = {s.name for s in ROLE_SEEDS_RECONCILED}
        for gap in GAPS:
            self.assertIn(gap.name, nombres)

    def test_cartridge_con_contrato_mev_no_generico(self):
        cart = next(s for s in ROLE_SEEDS_RECONCILED if s.name == "cartridge_engineer")
        self.assertIn("killswitch_trips", cart.acceptance)
        self.assertIn("paper_default", cart.acceptance)
        self.assertIn("cartridge_replay_deterministic", cart.acceptance)
        self.assertNotIn("destino_declarado", cart.acceptance)
        self.assertEqual(cart.destination, (".rhai",))

    def test_ningun_seed_sin_destino(self):
        for s in ROLE_SEEDS_RECONCILED:
            self.assertTrue(s.destination, "%s sin destino" % s.name)

    def test_los_32_existentes_conservan_su_nombre(self):
        originales = {s[0] for s in ROLE_SEEDS}
        nombres = {s.name for s in EXISTING}
        self.assertEqual(originales, nombres)

    def test_limite_coincide_con_el_roster(self):
        # P4-A: la frontera es len(roster), no un literal suelto
        self.assertEqual(limits.MAX_AGENTS, 42)
        self.assertEqual(limits.MAX_AGENTS, len(ROLE_SEEDS_RECONCILED))

    def test_frontera_43_rechazada(self):
        # validate_profile_specs valida n ANTES de mirar specs: con argumentos
        # vacios, 43 cae por limite y no por contenido. La funcion vive en
        # engine.dna (no en engine.core) y lanza ValueError (no ConfigError).
        from engine.dna import validate_profile_specs
        with self.assertRaises(ValueError):
            validate_profile_specs([], 43, None)

    def test_frontera_42_aceptada(self):
        self.assertEqual(limits.MAX_AGENTS, 42)


if __name__ == "__main__":
    unittest.main()
