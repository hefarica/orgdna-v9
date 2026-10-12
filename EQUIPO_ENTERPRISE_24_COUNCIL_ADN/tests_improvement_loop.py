"""Falsificación de `engine/improvement_loop.py`.

Dos correcciones respecto a la lista original, ambas declaradas:

1. El caso 5 (permisos) era INEJERCITABLE mientras `publish` exigía `skill_diff`,
   porque ese guardián está después del de evidencia. Ahora sí se recorre.
2. El caso 7 original —"reintroducir el borrador viejo (sin preserved_failure_id)
   hace fallar el caso"— es INEXPRESABLE: `draft_skill` construye el dict de la
   skill y `_SKILL_KEYS` rechaza cualquier campo ajeno, de modo que no hay forma
   de inyectar un borrador sin `preserved_failure_id`. Se sustituye por lo que sí
   es verificable: que el borrador SIEMPRE lo conserve, y que alterar el caso se
   detecte por digest.
"""
import copy
import unittest

from engine import improvement_loop as il

RECORD = {"failure_id": "F-1", "test_id": "tests_invoice.py::test_paths", "author_id": "agent-7",
          "candidate_sha": "a" * 64, "environment": "windows/py3.12", "expected": "4 paths",
          "observed": "3 paths", "evidence_paths": ["artifacts/fail-1.txt"]}
SKILL = {"skill_id": "invoice-path-check", "version": "1.1", "instructions": "Count every path.",
         "diff": "- old\n+ new", "regression": "tests_invoice.py::test_paths",
         "limits": "read-only", "rollback": "revert to 1.0"}


def to_independent(author="agent-7"):
    case = il.open_case(dict(RECORD, author_id=author))
    case = il.review_root_cause(case, "El contador ignoraba rutas repetidas", "product")
    case = il.draft_skill(case, SKILL)
    case = il.approve_supervisor(case, "sup-1")
    case = il.record_retest(case, "4 paths ahora", True, ["artifacts/pass-1.txt"])
    return il.approve_independent(case, "reviewer-9")


class RemediationStateMachineTests(unittest.TestCase):
    def test_cannot_draft_skill_before_root_cause(self):
        case = il.open_case(RECORD)
        with self.assertRaisesRegex(ValueError, "case.state: se esperaba ROOT_CAUSE_REVIEWED"):
            il.draft_skill(case, SKILL)

    def test_cannot_skip_every_intermediate_state(self):
        case = il.open_case(RECORD)
        for step in (lambda c: il.approve_supervisor(c, "sup-1"),
                     lambda c: il.record_retest(c, "x", True, ["p"]),
                     lambda c: il.approve_independent(c, "reviewer-9"),
                     lambda c: il.publish(c)):
            with self.subTest(step=step), self.assertRaises(ValueError):
                step(case)

    def test_independent_reviewer_cannot_be_the_author(self):
        case = il.review_root_cause(il.open_case(RECORD), "causa", "product")
        case = il.draft_skill(case, SKILL)
        case = il.approve_supervisor(case, "sup-1")
        case = il.record_retest(case, "4 paths", True, ["artifacts/pass-1.txt"])
        with self.assertRaisesRegex(ValueError, "no puede ser el autor"):
            il.approve_independent(case, "agent-7")

    def test_failed_retest_returns_to_draft_and_never_publishes(self):
        case = il.open_case(RECORD)
        case = il.review_root_cause(case, "causa", "product")
        case = il.draft_skill(case, SKILL)
        case = il.approve_supervisor(case, "sup-1")
        case = il.record_retest(case, "sigue en 3 paths", False, ["artifacts/fail-2.txt"])
        self.assertEqual(case["state"], "SKILL_DRAFTED")
        self.assertFalse(case["retest_result"]["passed"])
        with self.assertRaisesRegex(ValueError, "se esperaba RETEST_PASS"):
            il.approve_independent(case, "reviewer-9")
        with self.assertRaises(ValueError):
            il.publish(case)

    def test_publish_is_fail_closed_on_incomplete_evidence(self):
        approved = to_independent()
        for key in il._REQUIRED_AT_PUBLISH:
            with self.subTest(missing=key):
                broken = copy.deepcopy(approved)
                broken.pop(key)
                broken["digest"] = il.case_digest(broken)
                with self.assertRaisesRegex(ValueError, key):
                    il.publish(broken)

    def test_permissions_expansion_requires_an_explicit_note(self):
        approved = to_independent()
        with self.assertRaisesRegex(ValueError, "permissions_note"):
            il.publish(approved, permissions_expanded=True)
        published = il.publish(approved, permissions_expanded=True,
                               permissions_note="Se amplía a lectura de tests; aprobado por el propietario.")
        self.assertTrue(published["permissions_expanded"])
        self.assertEqual(published["state"], "PUBLISHED_VERSION")

    def test_happy_path_publishes_with_digest_and_full_history(self):
        published = il.publish(to_independent())
        self.assertEqual(published["state"], "PUBLISHED_VERSION")
        self.assertRegex(published["published_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(list(published["history"]), list(il._STATES))
        self.assertFalse(published["permissions_expanded"])

    def test_draft_always_preserves_the_failing_case(self):
        case = il.draft_skill(il.review_root_cause(il.open_case(RECORD), "causa", "product"), SKILL)
        self.assertEqual(case["skill"]["preserved_failure_id"], RECORD["failure_id"])
        for field in ("skill_id", "version", "instructions", "diff", "regression", "limits", "rollback"):
            self.assertIn(field, case["skill"])

    def test_skill_keys_are_closed_against_injection(self):
        case = il.review_root_cause(il.open_case(RECORD), "causa", "product")
        with self.assertRaisesRegex(ValueError, "campos no admitidos"):
            il.draft_skill(case, dict(SKILL, campo_ajeno=1))
        with self.assertRaisesRegex(ValueError, "faltan campos"):
            il.draft_skill(case, {"skill_id": "s", "version": "1"})

    def test_case_digest_is_recomputable_and_detects_tampering(self):
        case = to_independent()
        self.assertEqual(il.case_digest(case), case["digest"], "el digest debe excluirse a sí mismo")
        self.assertTrue(il.verify_case(case))
        tampered = copy.deepcopy(case)
        tampered["expected"] = "999 paths INVENTADOS"
        with self.assertRaisesRegex(ValueError, "caso alterado"):
            il.verify_case(tampered)

    def test_attempts_are_bounded(self):
        case = il.review_root_cause(il.open_case(RECORD), "causa", "product")
        for _ in range(il.MAX_ATTEMPTS):
            case = il.draft_skill(case, SKILL)
        self.assertEqual(case["attempts"], il.MAX_ATTEMPTS)
        with self.assertRaisesRegex(ValueError, "borradores"):
            il.draft_skill(case, SKILL)

    def test_attribution_is_closed(self):
        case = il.open_case(RECORD)
        with self.assertRaisesRegex(ValueError, "attribution"):
            il.review_root_cause(case, "causa", "porque si")

    def test_malformed_identifiers_and_shas_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "candidate_sha"):
            il.open_case(dict(RECORD, candidate_sha="zz"))
        with self.assertRaisesRegex(ValueError, "failure_id"):
            il.open_case(dict(RECORD, failure_id=" con espacio"))
        with self.assertRaisesRegex(ValueError, "evidence_paths"):
            il.open_case(dict(RECORD, evidence_paths=[]))

    def test_transitions_are_pure_and_do_not_mutate_the_input(self):
        case = il.open_case(RECORD)
        before = copy.deepcopy(case)
        il.review_root_cause(case, "causa", "product")
        self.assertEqual(case, before, "la transición no debe mutar el caso recibido")


if __name__ == "__main__":
    unittest.main()
