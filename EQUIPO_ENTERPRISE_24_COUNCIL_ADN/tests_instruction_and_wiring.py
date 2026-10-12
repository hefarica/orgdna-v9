"""Falsificación del contrato de instrucción y del cableado a la biblioteca.

El caso REGRESIÓN del número es el que más importa: `reconcile` declaraba
irreparable un `2` devuelto por el modelo frente a un `2.0` fijado, y la
idempotencia del cableado fallaba precisamente al reintentar.
"""
import copy
import os
import tempfile
import unittest

from engine import capability_library as cl
from engine import improvement_loop as il
from engine import instruction_contract as ic
from engine import playbooks as pb
from engine import remediation_wiring as rw

RECORD = {"failure_id": "F-1", "test_id": "tests_invoice.py::test_paths", "author_id": "agent-7",
          "candidate_sha": "a" * 64, "environment": "windows/py3.12", "expected": "4 paths",
          "observed": "3 paths", "evidence_paths": ["artifacts/fail-1.txt"]}
SKILL = {"skill_id": "invoice-path-check", "version": "1.1", "instructions": "Cuenta cada ruta.",
         "diff": "- old\n+ new", "regression": "tests_invoice.py::test_paths", "limits": "read-only",
         "rollback": "revertir a 1.0"}


def published(instructions=None, version="1.1", failure_id="F-1"):
    case = il.open_case(dict(RECORD, failure_id=failure_id))
    case = il.review_root_cause(case, "El contador ignoraba rutas repetidas", "product")
    case = il.draft_skill(case, dict(SKILL, version=version,
                                     instructions=instructions or SKILL["instructions"]))
    case = il.approve_supervisor(case, "sup-1")
    case = il.record_retest(case, "4 paths ahora", True, ["artifacts/pass-1.txt"])
    case = il.approve_independent(case, "reviewer-9")
    return il.publish(case)


class InstructionContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = ic.contract_from_playbook(pb.BETFAIR_VALUE_LAY)
        self.codes = [role["code"] for role in pb.BETFAIR_VALUE_LAY["roles"]]
        self.good = {code: {"tool_needs": list(pb.BETFAIR_VALUE_LAY["tool_needs"]),
                            "max_odds": 2.0, "max_loss_per_losing_bet_usd": 2.0,
                            "mission": "Misión declarada para " + code} for code in self.codes}

    def test_exact_response_is_clean(self):
        report = ic.check(self.good, self.contract)
        self.assertTrue(report["clean"])
        self.assertEqual(ic.reconcile(self.good, self.contract)[1], [])

    def test_dropped_role_is_refused_never_invented(self):
        broken = {c: dict(self.good[c]) for c in self.codes if c != "ORCH"}
        self.assertIn("ORCH", [item["id"] for item in ic.check(broken, self.contract)["dropped"]])
        with self.assertRaisesRegex(ValueError, "no se inventa"):
            ic.reconcile(broken, self.contract)

    def test_added_role_is_removed_and_reported(self):
        extra = dict(self.good, INTRUSO={"tool_needs": [], "max_odds": 2.0,
                                         "max_loss_per_losing_bet_usd": 2.0, "mission": "x"})
        out, repairs = ic.reconcile(extra, self.contract)
        self.assertNotIn("INTRUSO", out)
        self.assertIn("INTRUSO", [item["id"] for item in ic.check(extra, self.contract)["added"]])

    def test_added_field_is_removed(self):
        dirty = copy.deepcopy(self.good)
        dirty["VALUE"]["campo_inventado"] = "x"
        out, repairs = ic.reconcile(dirty, self.contract)
        self.assertNotIn("campo_inventado", out["VALUE"])
        self.assertEqual([r["code"] for r in repairs], ["removed_added"])

    def test_REGRESION_integer_for_pinned_float_is_restored(self):
        """El modelo devuelve 2 como NÚMERO JSON, no como texto. `reconcile` sólo
        sabía reparar `got` de tipo str, así que declaraba irreparable un valor
        numéricamente idéntico: el caso 5 de la lista original no podía pasar."""
        soft = copy.deepcopy(self.good)
        soft["VALUE"]["max_odds"] = 2
        self.assertFalse(ic.check(soft, self.contract)["clean"])
        out, repairs = ic.reconcile(soft, self.contract)
        self.assertEqual(out["VALUE"]["max_odds"], 2.0)
        self.assertIs(type(out["VALUE"]["max_odds"]), float)
        self.assertEqual([r["code"] for r in repairs], ["restored_number"])

    def test_different_number_is_irreparable(self):
        hard = copy.deepcopy(self.good)
        hard["VALUE"]["max_odds"] = 2.5
        with self.assertRaisesRegex(ValueError, "irreparable"):
            ic.reconcile(hard, self.contract)

    def test_boolean_is_not_a_number(self):
        hard = copy.deepcopy(self.good)
        hard["VALUE"]["max_odds"] = True
        with self.assertRaisesRegex(ValueError, "irreparable"):
            ic.reconcile(hard, self.contract)

    def test_blank_prose_gets_the_declared_default(self):
        blank = copy.deepcopy(self.good)
        blank["VALUE"]["mission"] = "   "
        out, repairs = ic.reconcile(blank, self.contract)
        self.assertEqual(out["VALUE"]["mission"], "sin misión declarada")
        self.assertEqual([r["code"] for r in repairs], ["filled_default"])

    def test_reordering_is_restored(self):
        reordered = {c: dict(self.good[c]) for c in reversed(self.codes)}
        out, _ = ic.reconcile(reordered, self.contract)
        self.assertEqual(list(out), self.codes)

    def test_missing_mandatory_term_is_refused(self):
        contract = ic.build_contract({"required_ids": ["R"], "prose": {"R": ["mission"]},
                                      "must_mention": {"R": ["riesgo acotado"]}})
        with self.assertRaisesRegex(ValueError, "palabra obligatoria"):
            ic.reconcile({"R": {"mission": "texto sin la frase"}}, contract)

    def test_tampered_contract_is_detected(self):
        altered = copy.deepcopy(self.contract)
        altered["max_prose_bytes"] = 99
        with self.assertRaisesRegex(ValueError, "alterado"):
            ic.check(self.good, altered)

    def test_retry_prompt_lists_only_real_faults(self):
        broken = {c: dict(self.good[c]) for c in self.codes if c != "ORCH"}
        prompt = ic.retry_prompt(self.contract, ic.check(broken, self.contract))
        self.assertIn("FALTA ORCH", prompt)
        self.assertNotIn("SOBRA", prompt)
        self.assertIsNone(ic.retry_prompt(self.contract, ic.check(self.good, self.contract)))

    def test_contract_rejects_undeclared_ids_and_order_mismatch(self):
        with self.assertRaisesRegex(ValueError, "required_ids"):
            ic.build_contract({"required_ids": ["A"], "pinned": {"B": {"x": 1}}})
        with self.assertRaisesRegex(ValueError, "order"):
            ic.build_contract({"required_ids": ["A", "B"], "order": ["A"],
                               "prose": {"A": ["m"], "B": ["m"]}})


class RemediationWiringTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="wiring_lib_")
        self.library = cl.CapabilityLibrary(os.path.join(self.dir, "library.sqlite3"), "proj-1")
        self.case = published()

    def test_unpublished_case_is_refused(self):
        with self.assertRaisesRegex(ValueError, "PUBLISHED_VERSION"):
            rw.item_id(il.open_case(RECORD))

    def test_tampered_case_is_refused_before_adapting(self):
        broken = copy.deepcopy(self.case)
        broken["expected"] = "999 paths"
        with self.assertRaisesRegex(ValueError, "alterado"):
            rw.library_item(broken)

    def test_foreign_preserved_failure_id_is_refused(self):
        broken = copy.deepcopy(self.case)
        broken["skill"]["preserved_failure_id"] = "F-OTRO"
        broken["digest"] = il.case_digest(broken)
        with self.assertRaisesRegex(ValueError, "preserved_failure_id"):
            rw.item_id(broken)

    def test_item_id_is_deterministic_and_version_sensitive(self):
        self.assertEqual(rw.item_id(self.case), rw.item_id(self.case))
        other = copy.deepcopy(self.case)
        other["skill"] = dict(other["skill"], version="1.2")
        other["digest"] = il.case_digest(other)
        self.assertNotEqual(rw.item_id(self.case), rw.item_id(other))

    def test_adapter_fills_the_two_real_gaps(self):
        """improvement_loop no produce `name` ni `provenance`: el adaptador los cubre."""
        item = rw.library_item(self.case, tags=["pagos"], tool_needs=["ops_plan"])
        self.assertEqual(sorted(item),
                         ["content", "description", "id", "kind", "name", "provenance",
                          "role_evidence", "tags", "tool_needs"])
        self.assertEqual(item["provenance"]["type"], "user_authored")
        self.assertIn(item["provenance"]["type"], cl.SOURCE_TYPES)
        self.assertRegex(item["provenance"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertLessEqual(len(item["provenance"]["evidence"].encode("utf-8")), 32000)

    def test_context_skill_matches_the_compiler_keys_exactly(self):
        from engine import context_compiler as cc
        skill = rw.context_skill(self.case)
        self.assertEqual(set(skill), set(cc._ITEM_KEYS["skill"]))

    def test_skill_is_injected_once(self):
        base = {"agent": {"id": "a", "mission": "m"}, "task": {"task_id": "t"}}
        once = rw.add_skill_to_request(self.case, base)
        twice = rw.add_skill_to_request(self.case, once)
        self.assertEqual(len(once["skill"]), 1)
        self.assertEqual(len(twice["skill"]), 1)

    def test_conflicting_duplicate_id_is_refused(self):
        base = {"agent": {"id": "a", "mission": "m"}, "task": {"task_id": "t"},
                "skill": [dict(rw.context_skill(self.case), instructions="OTRA COSA")]}
        with self.assertRaisesRegex(ValueError, "duplicado con contenido distinto"):
            rw.add_skill_to_request(self.case, base)

    def test_real_library_accepts_the_item(self):
        plan = rw.import_plan(self.case, self.library.status()["revision"], tags=["pagos"],
                              tool_needs=["ops_plan"])
        self.library.import_items(**plan)
        self.assertEqual(self.library.status()["revision"], 1)
        self.assertEqual(self.library.status()["item_count"], 1)

    def test_REGRESION_replay_key_is_consistent_with_the_revision(self):
        """Una clave estable por (failure_id, version) con una revisión leída EN VIVO
        es una contradicción: tras el primer import la revisión cambia, y el reintento
        del mismo caso lanzaba 'Clave idempotente reutilizada para otra solicitud'
        justo en el escenario para el que existe la idempotencia."""
        plan = rw.import_plan(self.case, self.library.status()["revision"], tags=["pagos"],
                              tool_needs=["ops_plan"])
        self.library.import_items(**plan)
        retry = rw.import_plan(self.case, self.library.status()["revision"], tags=["pagos"],
                               tool_needs=["ops_plan"])
        self.library.import_items(**retry)          # no lanza
        self.assertEqual(self.library.status()["item_count"], 1, "reimportar no duplica")
        self.assertNotEqual(plan["idempotency_key"], retry["idempotency_key"])
        self.assertIn(":r1", retry["idempotency_key"])

    def test_real_library_enforces_immutability(self):
        self.library.import_items(**rw.import_plan(self.case, self.library.status()["revision"],
                                                  tags=["pagos"], tool_needs=["ops_plan"]))
        same_version_other_body = published(instructions="OTRA COSA completamente distinta.")
        self.assertEqual(rw.item_id(same_version_other_body), rw.item_id(self.case))
        plan = rw.import_plan(same_version_other_body, self.library.status()["revision"],
                              tags=["pagos"], tool_needs=["ops_plan"])
        with self.assertRaisesRegex(cl.CapabilityLibraryError, "inmutables"):
            self.library.import_items(**plan)

    def test_new_version_imports_as_a_new_item(self):
        self.library.import_items(**rw.import_plan(self.case, self.library.status()["revision"],
                                                  tags=["pagos"], tool_needs=["ops_plan"]))
        newer = published(version="1.2")
        self.library.import_items(**rw.import_plan(newer, self.library.status()["revision"],
                                                  tags=["pagos"], tool_needs=["ops_plan"]))
        self.assertEqual(self.library.status()["item_count"], 2)


if __name__ == "__main__":
    unittest.main()
