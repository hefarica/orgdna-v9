"""Falsificación de `engine/context_compiler.py`.

Criterio: si el módulo fuera vacuo (sin selección real, sin cota, sin digest),
estos casos deben fallar. El caso 3 —"budget diminuto"— necesita un fixture que
REALMENTE desborde el presupuesto: con un fixture pequeño caben 638 bytes en 1024
y no se omite nada, de modo que la aserción original era inejercitable. Se
dimensiona aquí a propósito para que la ruta de omisión se recorra de verdad.
"""
import copy
import unittest

from engine import context_compiler as cc

AGENT = {"id": "agent-7", "name": "Ana", "role": "reviewer",
         "mission": "Verify invoice evidence", "personality": "methodical", "reports_to": "ceo-1"}
TASK = {"task_id": "t-1", "title": "Review invoice", "objective": "Verify invoice evidence paths",
        "acceptance": ["evidence cited", "no invented paths"]}
BASE = {
    "agent": AGENT, "task": TASK, "objective": "Verify invoice evidence",
    "evidence": [{"id": "ev-1", "path": "src/invoice.py", "text": "invoice evidence parser"},
                 {"id": "ev-2", "path": "docs/other.md", "text": "unrelated material about gardening"}],
    "skill": [{"id": "sk-1", "name": "invoice-review", "version": "1.0",
               "instructions": "Verify each invoice evidence path before citing it."}],
    "memory": [{"id": "me-1", "kind": "fact", "text": "invoice evidence must be cited exactly"}],
    "handoff": [{"id": "ho-1", "from": "a-1", "to": "b-1", "summary": "invoice evidence handed over"}],
}


def _flat(package):
    return {row["id"]: row for section in package["sections"] for row in section["items"]}


class ContextCompilerTests(unittest.TestCase):
    def test_same_request_gives_same_digest(self):
        first, second = cc.compile_context(BASE), cc.compile_context(BASE)
        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual(cc.context_digest(first), first["digest"])

    def test_digest_excludes_itself_and_detects_tampering(self):
        package = cc.compile_context(BASE)
        self.assertTrue(cc.verify_context(package))
        altered = copy.deepcopy(package)
        altered["sections"][0]["items"][0]["text"] = "ALTERADO"
        with self.assertRaisesRegex(ValueError, "alterado"):
            cc.verify_context(altered)
        with self.assertRaisesRegex(ValueError, "falta digest"):
            cc.verify_context({"sections": []})

    def test_small_budget_omits_with_reason_and_warns(self):
        # Fixture dimensionado para desbordar 1024 bytes: si no desborda, esta
        # asercion seria inejercitable (era el defecto de la lista original).
        long_agent = dict(AGENT, mission="M" * 600)
        long_task = dict(TASK, objective="T" * 500)
        package = cc.compile_context(dict(BASE, agent=long_agent, task=long_task, budget_bytes=1024))
        kinds = [section["kind"] for section in package["sections"]]
        self.assertIn("mandate", kinds, "el mandato nunca se descarta")
        self.assertTrue(package["omitted"], "debía omitirse algo")
        for row in package["omitted"]:
            self.assertEqual(row["reason"], "budget")
            self.assertIn(row["kind"], cc._TIERS)
        self.assertTrue(any(w.startswith("items_omitted_by_budget") for w in package["warnings"]))
        self.assertLessEqual(package["budget"]["used_bytes"], package["budget"]["limit_bytes"])

    def test_mandate_alone_over_budget_is_kept_and_flagged(self):
        huge = dict(AGENT, mission="M" * 1500)
        package = cc.compile_context(dict(BASE, agent=huge, budget_bytes=1024))
        self.assertIn("mandate", [s["kind"] for s in package["sections"]])
        self.assertGreater(package["budget"]["used_bytes"], 1024)
        self.assertTrue(any(w.startswith("mandate_exceeds_budget") for w in package["warnings"]))

    def test_duplicate_id_is_rejected(self):
        bad = dict(BASE, evidence=[{"id": "d", "path": "a.py", "text": "uno"},
                                   {"id": "d", "path": "b.py", "text": "dos"}])
        with self.assertRaisesRegex(ValueError, r"evidence\[1\]\.id: duplicado"):
            cc.compile_context(bad)

    def test_unknown_request_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "campos no admitidos"):
            cc.compile_context(dict(BASE, campo_raro=1))

    def test_unknown_field_inside_item_is_rejected(self):
        # El contrato de A dice «campo desconocido -> ValueError con ruta de campo»
        # sin limitarlo al request. Ignorar un campo ajeno dentro de un elemento
        # seria una asimetria frente a _REQUEST_KEYS y frente a _SKILL_KEYS de B.
        for kind, row in (("evidence", {"id": "e", "path": "a.py", "text": "t", "extra": 1}),
                          ("skill", {"id": "s", "name": "n", "version": "1", "instructions": "i", "extra": 1}),
                          ("memory", {"id": "m", "kind": "k", "text": "t", "extra": 1}),
                          ("handoff", {"id": "h", "from": "a", "to": "b", "summary": "s", "extra": 1})):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, r"\[0\]: campos no admitidos"):
                cc.compile_context(dict(BASE, **{kind: [row]}))

    def test_relevance_orders_overlapping_item_first(self):
        package = cc.compile_context(BASE)
        items = [row for section in package["sections"] if section["kind"] == "evidence"
                 for row in section["items"]]
        self.assertEqual([row["id"] for row in items], ["ev-1", "ev-2"])
        self.assertGreater(items[0]["relevance"], items[1]["relevance"])

    def test_budget_bounds_are_enforced(self):
        for value in (cc.MIN_BUDGET_BYTES - 1, cc.MAX_BUDGET_BYTES + 1, True, "12000", 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cc.compile_context(dict(BASE, budget_bytes=value))

    def test_missing_or_empty_mandate_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "agent: se requiere objeto"):
            cc.compile_context(dict(BASE, agent=None))
        with self.assertRaisesRegex(ValueError, "al menos un campo de mandato"):
            cc.compile_context(dict(BASE, agent={"id": "x"}))

    def test_section_item_cap_is_enforced(self):
        rows = [{"id": "e%d" % i, "path": "p%d.py" % i, "text": "t"} for i in range(cc.MAX_ITEMS_PER_SECTION + 1)]
        with self.assertRaisesRegex(ValueError, "máximo"):
            cc.compile_context(dict(BASE, evidence=rows))

    def test_no_evidence_warning_when_evidence_is_empty(self):
        package = cc.compile_context(dict(BASE, evidence=[]))
        self.assertTrue(any(w.startswith("no_evidence") for w in package["warnings"]))

    def test_module_declares_it_is_not_semantic_retrieval(self):
        package = cc.compile_context(BASE)
        self.assertEqual(package["selection"]["method"], "tiered_overlap_not_semantic")
        self.assertEqual(package["selection"]["never_dropped"], ["mandate"])
        self.assertIn("no tokenizer", package["budget"]["estimate_method"])


if __name__ == "__main__":
    unittest.main()
