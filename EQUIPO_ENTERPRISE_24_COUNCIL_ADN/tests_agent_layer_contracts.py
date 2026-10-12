"""Falsificación de la capa de agentes: kinds, puerta operativa, preflight, playbooks y dossier.

Cada caso marcado REGRESIÓN fija un defecto que la ejecución encontró y que la
lectura no daba. Sin esos casos, los arreglos podrían revertirse en silencio.
"""
import copy
import unittest

from engine import agent_dossier as ad
from engine import agent_kinds as ak
from engine import context_compiler as cc
from engine import operational_gate as og
from engine import playbooks as pb
from engine import readiness_gate as rg

CATALOG = ["ops_plan", "ops_status", "research_report", "evidence_add", "visual_ascii", "visual_mermaid"]


class AgentKindsTests(unittest.TestCase):
    def test_domain_prefixed_role_resolves_to_class(self):
        self.assertEqual(ak.resolve_code({"role": "DOMAIN_07_LEGAL"}), "LEGAL")
        self.assertEqual(ak.resolve_code({"title": "Asesoría legal y contratos"}), "LEGAL")

    def test_resolution_is_deterministic(self):
        agent = {"role": "DOMAIN_03_CLOUD", "mission": "infra y devops"}
        self.assertEqual(ak.resolve_code(agent), ak.resolve_code(agent))

    def test_unknown_class_falls_back_to_general(self):
        self.assertEqual(ak.resolve_code({"role": "ZZZ_SIN_CLASE"}), ak.GENERAL_CODE)

    def test_preset_uses_only_catalog_names(self):
        preset = ak.resolve_preset({"role": "DOMAIN_07_LEGAL"}, CATALOG)
        self.assertEqual(preset["role"], "LEGAL")
        self.assertTrue(set(preset["allow_candidates"]) <= set(CATALOG))
        self.assertIn("research_report", preset["allow_candidates"])

    def test_invented_names_are_never_advertised(self):
        preset = ak.resolve_preset({"role": "DOMAIN_07_LEGAL"}, ["research_report"])
        self.assertEqual(preset["allow_candidates"], ["research_report"])

    def test_REGRESION_empty_preset_is_never_silent(self):
        """El default known_tools=() daba allow_candidates=[] sin decirlo.

        El caso 'nunca lista vacía' de la lista original era FALSO: con el catálogo
        vacío la lista está vacía, y eso es correcto porque nunca se inventa
        disponibilidad. Lo que no puede es ser invisible.
        """
        preset = ak.resolve_preset({"role": "SIN_CATALOGO"})
        self.assertEqual(preset["allow_candidates"], [])
        self.assertTrue(any("catálogo aportado" in gap for gap in preset["capability_gaps"]),
                        "una lista vacía debe declararse en capability_gaps")
        con_catalogo = ak.resolve_preset({"role": "SIN_CATALOGO"}, CATALOG)
        self.assertTrue(con_catalogo["allow_candidates"])
        self.assertEqual(len(con_catalogo["capability_gaps"]), 1)

    def test_codes_are_the_declared_catalog_plus_general(self):
        self.assertEqual(len(ak.CODES), len(ak.KINDS) + 1)
        self.assertIn(ak.GENERAL_CODE, ak.CODES)
        self.assertEqual(len(set(ak.CODES)), len(ak.CODES), "códigos duplicados")


class OperationalGateTests(unittest.TestCase):
    VERIFIED = {"status": "catalog_verified", "model": "m-1", "account_verified": True}

    def test_missing_key_blocks(self):
        with self.assertRaisesRegex(ValueError, "falta la clave"):
            og.check({}, "zai", self.VERIFIED)

    def test_unverified_model_blocks(self):
        with self.assertRaisesRegex(ValueError, "debe estar verificado"):
            og.check({"zai": "k"}, "zai", {"status": "MANUAL_NOT_VERIFIED"})

    def test_unread_source_blocks(self):
        with self.assertRaisesRegex(ValueError, "lee primero la fuente"):
            og.check({"zai": "k"}, "zai", self.VERIFIED, source_read=False)

    def test_all_faults_are_reported_together(self):
        with self.assertRaises(ValueError) as caught:
            og.check({}, "zai", {"status": "x"}, source_read=False)
        message = str(caught.exception)
        for fragment in ("credentials:", "model:", "source:"):
            self.assertIn(fragment, message)

    def test_blank_key_is_not_a_key(self):
        with self.assertRaisesRegex(ValueError, "falta la clave"):
            og.check({"zai": "   "}, "zai", self.VERIFIED)

    def test_operational_receipt_declares_offline_is_not_the_default(self):
        receipt = og.check({"zai": "k"}, "zai", self.VERIFIED)
        self.assertTrue(receipt["operational"])
        self.assertFalse(receipt["offline_template_allowed"])
        self.assertEqual(receipt["model_status"], "catalog_verified")


class ReadinessGateTests(unittest.TestCase):
    CATALOG = ["ops_plan", "ops_status", "why_find"]

    def test_REGRESION_blocked_tool_does_not_crash(self):
        """El switch era un dict literal: se evaluaba ENTERO antes de indexar, así
        que item['gap'] reventaba con KeyError en el primer bloqueo de herramienta.
        La puerta fallaba exactamente cuando tenía que bloquear."""
        for tool, code in (("nope", "tool_missing_from_catalog"),
                           ("ops_plan", "tool_denied")):
            allow = [] if code == "tool_denied" else self.CATALOG
            deny = ["ops_plan"] if code == "tool_denied" else []
            with self.subTest(code=code):
                result = rg.evaluate([tool], allow, deny, self.CATALOG)
                self.assertFalse(result["ready"])
                self.assertEqual(result["blocked_by"][0]["code"], code)
                self.assertTrue(result["next_actions"])

    def test_denied_is_distinguished_from_not_allowed(self):
        denied = rg.evaluate(["ops_plan"], self.CATALOG, ["ops_plan"], self.CATALOG)
        not_allowed = rg.evaluate(["ops_plan"], [], [], self.CATALOG)
        self.assertEqual(denied["blocked_by"][0]["code"], "tool_denied")
        self.assertEqual(not_allowed["blocked_by"][0]["code"], "tool_not_allowed")

    def test_gap_needs_a_reason_to_be_waived(self):
        blocked = rg.evaluate(["ops_plan"], self.CATALOG, [], self.CATALOG, capability_gaps=["g1"])
        self.assertEqual(blocked["blocked_by"][0]["code"], "gap_unresolved")
        blank = rg.evaluate(["ops_plan"], self.CATALOG, [], self.CATALOG,
                            capability_gaps=["g1"], waivers={"g1": "   "})
        self.assertFalse(blank["ready"])
        waived = rg.evaluate(["ops_plan"], self.CATALOG, [], self.CATALOG,
                             capability_gaps=["g1"], waivers={"g1": "eximido por el propietario"})
        self.assertTrue(waived["ready"])
        self.assertEqual(waived["waived"], ["g1"])

    def test_ready_does_not_claim_installation(self):
        result = rg.evaluate(["ops_plan"], self.CATALOG, [], self.CATALOG)
        self.assertTrue(result["ready"])
        self.assertFalse(result["installed"])
        self.assertFalse(result["runtime_verified"])

    def test_no_tool_needs_is_ready_but_warned(self):
        result = rg.evaluate([], self.CATALOG, [], self.CATALOG)
        self.assertTrue(result["ready"])
        self.assertTrue(result["warnings"])

    def test_duplicate_tool_needs_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicados"):
            rg.evaluate(["ops_plan", "ops_plan"], self.CATALOG, [], self.CATALOG)


class PlaybookTests(unittest.TestCase):
    def test_betfair_playbook_validates(self):
        self.assertTrue(pb.validate_playbook(pb.BETFAIR_VALUE_LAY))

    def test_duplicate_role_codes_are_rejected(self):
        broken = copy.deepcopy(pb.BETFAIR_VALUE_LAY)
        broken["roles"] = list(broken["roles"]) + [dict(broken["roles"][0])]
        with self.assertRaisesRegex(ValueError, "duplicados"):
            pb.validate_playbook(broken)

    def test_missing_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "faltan campos"):
            pb.validate_playbook({"id": "x"})

    def test_preflight_reports_unknown_against_the_real_catalog(self):
        from engine import tool_permissions as tp
        catalog = sorted({tool["name"] for tool in tp._catalog()["tools"]})
        plan = pb.preflight_playbook(pb.BETFAIR_VALUE_LAY, catalog)
        self.assertEqual(plan["unknown_in_catalog"], [],
                         "los seis tool_needs existen en el catálogo real de esta entrega")
        self.assertEqual(len(plan["roles"]), len(pb.BETFAIR_VALUE_LAY["roles"]))

    def test_preflight_never_invents_availability(self):
        plan = pb.preflight_playbook(pb.BETFAIR_VALUE_LAY, ["ops_plan"])
        self.assertEqual(sorted(plan["unknown_in_catalog"]),
                         sorted(set(pb.BETFAIR_VALUE_LAY["tool_needs"]) - {"ops_plan"}))

    def test_daily_target_is_declared_unset_not_invented(self):
        self.assertIsNone(pb.BETFAIR_VALUE_LAY["risk"]["daily_target_usd"])


class AgentDossierTests(unittest.TestCase):
    ENTRIES = [{"facet": "laboral", "text": "Ingeniero de plataforma con diez anos en pagos y riesgo"},
               {"facet": "profesional", "text": "Ingeniero de plataforma: pagos, riesgo y cumplimiento"},
               {"facet": "objetivo", "text": "Automatizar arbitraje de cuotas con riesgo acotado"}]

    def test_invalid_facet_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "facet"):
            ad.build_dossier([{"facet": "inventado", "text": "x"}])

    def test_unknown_entry_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "campos no admitidos"):
            ad.build_dossier([{"facet": "laboral", "text": "x", "extra": 1}])

    def test_identical_text_relates_and_does_not_merge(self):
        dossier = ad.build_dossier([{"id": "a", "facet": "laboral", "text": "pagos riesgo plataforma"},
                                    {"id": "b", "facet": "profesional", "text": "pagos riesgo plataforma"}])
        self.assertEqual(dossier["counts"]["entries"], 2)
        self.assertEqual(dossier["counts"]["relations"], 1)
        self.assertEqual(dossier["relations"][0]["weight"], 3)

    def test_tampered_dossier_is_detected(self):
        dossier = ad.build_dossier(self.ENTRIES)
        self.assertTrue(ad.verify_dossier(dossier))
        altered = copy.deepcopy(dossier)
        altered["entries"][0]["text"] = "ALTERADO"
        with self.assertRaisesRegex(ValueError, "alterado"):
            ad.verify_dossier(altered)

    def test_truncation_is_by_relation_and_reports_omissions(self):
        many = [{"facet": "laboral", "text": "experiencia %d en pagos riesgo cumplimiento" % i} for i in range(70)]
        dossier = ad.build_dossier(many)
        items = ad.to_context_items(dossier, limit=10)["memory"]
        self.assertIn("dossier.omitidos", [row["id"] for row in items])

    def test_REGRESION_default_fits_the_context_compiler(self):
        """to_context_items(limit=64) devolvía 66 elementos de memoria porque añade
        'relaciones' y 'omitidos', y context_compiler los RECHAZABA: la llamada por
        defecto no podía alimentar a su consumidor."""
        many = [{"facet": "laboral", "text": "experiencia %d en pagos riesgo cumplimiento normativo" % i}
                for i in range(70)]
        dossier = ad.build_dossier(many)
        ctx = ad.to_context_items(dossier)
        self.assertEqual(len(ctx["memory"]), cc.MAX_ITEMS_PER_SECTION)
        package = cc.compile_context({
            "agent": {"id": "a", "mission": ctx["mandate"]["mission"]},
            "task": {"task_id": "t", "objective": "pagos riesgo"},
            "memory": ctx["memory"]})
        used = sum(len(s["items"]) for s in package["sections"] if s["kind"] == "memory")
        self.assertEqual(used, cc.MAX_ITEMS_PER_SECTION)
        with self.assertRaisesRegex(ValueError, "el tope de memoria"):
            ad.to_context_items(dossier, limit=64)

    def test_emitted_memory_uses_exactly_the_compiler_keys(self):
        ctx = ad.to_context_items(ad.build_dossier(self.ENTRIES))
        for row in ctx["memory"]:
            self.assertTrue(set(row) <= cc._ITEM_KEYS["memory"], row)
            self.assertTrue(set(row) >= {"id", "kind", "text"}, row)


if __name__ == "__main__":
    unittest.main()
