"""tests_dna_fusion.py - ADN, especialistas y fusion: la evidencia manda, el 2000% no entra."""
import json
import unittest

from engine.dna_extractor import DnaError, build_prompt, extract, parse_and_validate
from engine.fusion_engine import FusionError, fuse
from engine.specialist_generator import SpecialistError, generate

RUTAS = {"package.json", "backend/Cargo.toml", "contracts/Makefile"}


def dna_valido(extra=None):
    d = {"core_claim": {"text": "espina", "evidence": ["package.json"]},
         "primitives": [{"text": "crate", "evidence": ["backend/Cargo.toml"]}]}
    if extra:
        d.update(extra)
    return parse_and_validate("src", "git", json.dumps(d), RUTAS)


class DnaTests(unittest.TestCase):
    def test_valido(self):
        p = dna_valido()
        self.assertEqual(p.total_citas, 2)
        self.assertIn("package.json", p.paths())

    def test_cita_inventada(self):
        malo = json.dumps({"core_claim": {"text": "x", "evidence": ["no/existe.ts"]}})
        with self.assertRaises(DnaError) as ctx:
            parse_and_validate("s", "git", malo, RUTAS)
        self.assertIn("INVENTADA", str(ctx.exception))

    def test_sin_evidencia(self):
        malo = json.dumps({"core_claim": {"text": "x", "evidence": []}})
        with self.assertRaises(DnaError):
            parse_and_validate("s", "git", malo, RUTAS)

    def test_adn_vacio(self):
        solo = json.dumps({"core_claim": {"text": "x", "evidence": ["package.json"]}})
        with self.assertRaises(DnaError):
            parse_and_validate("s", "git", solo, RUTAS)

    def test_prompt_prohibe_multiplicadores(self):
        p = build_prompt("s", "", sorted(RUTAS))
        self.assertIn("multiplicadores", p)
        self.assertNotIn("2000", p)

    def test_extract_sin_llm_no_inventa(self):
        class S:
            source_id = "s"; source_type = type("T", (), {"value": "git"})
        with self.assertRaises(DnaError):
            extract(S(), RUTAS, None)


class SpecialistTests(unittest.TestCase):
    def test_valido(self):
        s = generate(dna_valido(), lambda p: json.dumps({
            "name": "Espina", "competency": "mantener",
            "capabilities": [{"text": "verificar", "evidence": ["package.json"]}],
            "blind_spots": ["no cubre contratos"]}))
        self.assertEqual(s.cobertura, 1)
        self.assertTrue(s.blind_spots)

    def test_cita_fuera_del_adn(self):
        with self.assertRaises(SpecialistError) as ctx:
            generate(dna_valido(), lambda p: json.dumps({
                "name": "X", "competency": "c",
                "capabilities": [{"text": "t", "evidence": ["otra/Cosa.sol"]}]}))
        self.assertIn("NO esta en el ADN", str(ctx.exception))

    def test_metrica_inventada(self):
        with self.assertRaises(SpecialistError) as ctx:
            generate(dna_valido(), lambda p: json.dumps({
                "name": "Brujo 2000%", "competency": "c",
                "capabilities": [{"text": "t", "evidence": ["package.json"]}]}))
        self.assertIn("no falsable", str(ctx.exception))

    def test_sin_blind_spots_se_acepta_pero_queda_vacio(self):
        s = generate(dna_valido(), lambda p: json.dumps({
            "name": "Y", "competency": "c",
            "capabilities": [{"text": "t", "evidence": ["package.json"]}]}))
        self.assertEqual(s.blind_spots, ())


class FusionTests(unittest.TestCase):
    def _dos(self):
        return [dna_valido()]

    def test_fusion_valida(self):
        f = fuse(self._dos(), "hibrido", lambda p: json.dumps({
            "capabilities": [{"text": "unir", "evidence": ["package.json"]}],
            "gaps": ["sin datos on-chain"]}))
        self.assertEqual(f.citas, 1)
        self.assertTrue(f.gaps)

    def test_cita_ausente_en_todas(self):
        with self.assertRaises(FusionError) as ctx:
            fuse(self._dos(), "h", lambda p: json.dumps({
                "capabilities": [{"text": "x", "evidence": ["nada/Nope.sol"]}]}))
        self.assertIn("ausente en TODAS", str(ctx.exception))

    def test_metrica_inventada(self):
        with self.assertRaises(FusionError):
            fuse(self._dos(), "h", lambda p: json.dumps({
                "capabilities": [{"text": "mejora 2000%", "evidence": ["package.json"]}]}))

    def test_sin_fuentes(self):
        with self.assertRaises(FusionError):
            fuse([], "h", lambda p: "{}")


if __name__ == "__main__":
    unittest.main()
