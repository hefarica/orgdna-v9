"""Reparacion acotada de `duplicate_value` y diagnostico accionable por slots.

Arnes: el `Fixture` del repo (`tests_org_design.py`), transporte falso sin red, y el
guard de socket activo como en esa suite. El unico contacto con el proveedor es local.

Que fija:
  (a) una primera respuesta que repite valores se REPARA: el diseno completa con dos
      solicitudes, el recibo de la reparacion queda `repaired_duplicate` y
      `audit['repairs'] == 1`;
  (b) si la respuesta reparada vuelve a repetir, el fallo es LIMPIO: `duplicate_value`
      con `duplicate_slots` exactos, sin tercera tentativa y sin reescribir datos;
  (c) sin presupuesto para reparar no se emite ninguna solicitud extra: falla con el
      diagnostico preciso y el recibo honesto (pudo haber cargos);
  (d) con tres perfiles donde chocan dos, `duplicate_slots` senala exactamente a los dos;
  (e) el diagnostico conserva el mensaje del operador y anade `duplicate_field` /
      `duplicate_slots` (claves ADITIVAS, solo nombres e indices);
  (f) la instruccion de reparacion no filtra valores del diseno, datos de la fuente,
      la clave ni el proveedor: solo nombra campo y slots.

CLI:  python -m unittest tests_org_design_repair -v
"""
import json
import socket
import tempfile
import time
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

from engine import org_design as d
from engine.bridge import BridgeState
from engine.project_store import ProjectStore
from tests_bridge import NullStore
from tests_org_design import Fixture, fixture_profile, fixture_summary
from qa_v7.fixtures import DesignTransport, PipelineProvider, PRIVATE_MARKER


def clash(field, source, target, calls=(1,)):
    """Duplica `field` del perfil `source` en `target` dentro del mismo lote."""

    def mutate(value, response, index):
        specs = value["profile_specs"]
        if index in calls and len(specs) > max(source, target):
            specs[target][field] = specs[source][field]

    return mutate


class RepairDesignTests(unittest.TestCase):
    """Reparacion acotada por solicitud, sin red y con stdlib pura."""

    def setUp(self):
        self.guard = patch("socket.create_connection",
                           side_effect=AssertionError("No external calls allowed in tests"))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.summary = fixture_summary()

    def consent(self, n=2, profiles_per_request=2, **kwargs):
        value = d.prepare_design_consent(self.summary, "deepseek", "deepseek-flash",
                                         {"agent_count": n}, profiles_per_request=profiles_per_request, **kwargs)
        value.update(confirmed=True, data_reviewed=True, budget_acknowledged=True)
        return value

    def design(self, fixture, n=2, profiles_per_request=2, consent=None, **kwargs):
        return d.design_with_llm(self.summary, "deepseek", "deepseek-flash", {"agent_count": n},
                                 "FIXTURE_PRIVATE_KEY", consent or self.consent(n, profiles_per_request, **kwargs),
                                 transport=fixture, profiles_per_request=profiles_per_request, **kwargs)

    def failure(self, fixture, n=2, profiles_per_request=2, **kwargs):
        with self.assertRaises(d.DesignError) as caught:
            self.design(fixture, n, profiles_per_request, **kwargs)
        return caught.exception

    # (a) primera repeticion: reparada, diseno completo
    def test_a_first_duplicate_is_repaired_and_the_design_completes(self):
        fixture = Fixture(mutate=clash("mission", 0, 1))
        result = self.design(fixture)
        self.assertEqual(result["status"], "PROPOSED_REQUIRES_REVIEW")
        self.assertEqual(len(result["profile_specs"]), 2)
        self.assertEqual(result["audit"]["requests"], 2)
        self.assertEqual(result["audit"]["repairs"], 1)
        self.assertEqual([row["status"] for row in result["audit"]["receipts"]],
                         ["repaired_duplicate", "validated"])
        self.assertEqual(len(fixture.calls), 2)
        # La reemision conserva el control del lote (mismos slots) y anade la instruccion.
        second = fixture.calls[1]["payload"]
        self.assertIn("DESIGN_CONTROL", second["messages"][1]["content"])
        self.assertEqual(second["messages"][-1]["role"], "user")
        self.assertIn("campo 'mission'", second["messages"][-1]["content"])
        self.assertIn("slots 1, 2", second["messages"][-1]["content"])
        # Los perfiles entregados son los reparados: distintos en el campo del choque.
        self.assertNotEqual(result["profile_specs"][0]["mission"], result["profile_specs"][1]["mission"])

    # (b) segunda repeticion: fallo limpio, sin tercera tentativa
    def test_b_second_duplicate_fails_clean_with_exact_slots(self):
        fixture = Fixture(mutate=clash("mission", 0, 1, calls=(1, 2)))
        exc = self.failure(fixture)
        self.assertEqual(exc.diagnostic["code"], "duplicate_value")
        self.assertEqual(exc.diagnostic["duplicate_field"], "mission")
        self.assertEqual(exc.diagnostic["duplicate_slots"], [1, 2])
        self.assertEqual(exc.status, "FAILED")
        self.assertEqual(len(fixture.calls), 2)            # sin tercera tentativa
        self.assertEqual(exc.audit["repairs"], 1)          # se reparo una vez, no dos
        self.assertEqual(exc.audit["completed_profiles"], 0)  # nada reescrito en silencio
        self.assertEqual(exc.audit["requests"], 2)

    # (c) sin presupuesto: ni una solicitud extra
    def test_c_without_budget_the_repair_is_never_emitted(self):
        fixture = Fixture(mutate=clash("mission", 0, 1))
        exc = self.failure(fixture, consent=self.consent(2, 2, max_requests=1), max_requests=1)
        self.assertEqual(exc.diagnostic["code"], "duplicate_value")
        self.assertEqual(exc.diagnostic["duplicate_field"], "mission")
        self.assertEqual(exc.diagnostic["duplicate_slots"], [1, 2])
        self.assertEqual(len(fixture.calls), 1)            # 0 llamadas extra
        self.assertEqual(exc.audit["requests"], 1)
        self.assertEqual(exc.audit["repairs"], 0)
        # Honestidad de facturacion: la solicitud se envio y su resultado no se valido.
        # generation_pipeline.py:825-826 solo marca potentially_billed=False si sent==0,
        # asi que este fallo conserva el cargo potencial en la superficie del panel.
        self.assertEqual(exc.audit["receipts"][-1]["status"], "response_received_not_yet_validated")
        self.assertEqual(exc.status, "FAILED")
        self.assertNotEqual(exc.status, "PROPOSED_REQUIRES_REVIEW")

    # (d) tres perfiles, chocan dos: los slots son exactos
    def test_d_three_profiles_report_exactly_the_two_that_clash(self):
        fixture = Fixture(mutate=clash("personality", 0, 2))
        result = self.design(fixture, n=3, profiles_per_request=3)
        self.assertEqual(result["audit"]["repairs"], 1)
        self.assertEqual(result["audit"]["requests"], 2)
        instruction = fixture.calls[1]["payload"]["messages"][-1]["content"]
        self.assertIn("campo 'personality'", instruction)
        self.assertIn("slots 1, 3", instruction)
        repeated = self.failure(Fixture(mutate=clash("personality", 0, 2, calls=(1, 2))),
                                n=3, profiles_per_request=3)
        self.assertEqual(repeated.diagnostic["duplicate_slots"], [1, 3])
        self.assertEqual(repeated.diagnostic["duplicate_field"], "personality")

    # (e) diagnostico accionable sin cambiar el mensaje del operador
    def test_e_diagnostic_adds_slots_and_keeps_the_operator_message(self):
        exc = self.failure(Fixture(mutate=clash("mission", 0, 1, calls=(1, 2))))
        category, message, action = d._FAILURES["duplicate_value"]
        self.assertEqual(exc.diagnostic["message"], message)
        self.assertEqual(exc.diagnostic["next_action"], action)
        self.assertEqual(exc.diagnostic["category"], category)
        self.assertEqual(exc.diagnostic["field"], "profile_specs.mission")
        self.assertRegex(exc.diagnostic["duplicate_field"], r"^[a-z_]+$")
        slots = exc.diagnostic["duplicate_slots"]
        self.assertEqual(slots, sorted(set(slots)))
        self.assertTrue(all(type(slot) is int and 1 <= slot <= d.MAX_AGENTS for slot in slots))

    # (f) la instruccion no filtra valores ni datos
    def test_f_repair_instruction_carries_no_values_source_or_key(self):
        fixture = Fixture(mutate=clash("mission", 0, 1))
        self.design(fixture)
        instruction = fixture.calls[1]["payload"]["messages"][-1]["content"]
        for leaked in ("FIXTURE_PRIVATE_KEY", "unique-project", "validate_invoice",
                       "Invoice validation service", "Persona Ficticia", "Competencia",
                       "deepseek", "verificación de contratos"):
            with self.subTest(filtrado=leaked):
                self.assertNotIn(leaked, instruction)
        self.assertLess(len(instruction), 700)
        self.assertEqual(instruction.count("{"), 0)

    # La colision de `_unique` informa por si misma de los slots
    def test_unique_reports_the_clashing_slots(self):
        profiles = [fixture_profile(slot) for slot in (1, 2, 3)]
        profiles[2]["mission"] = profiles[0]["mission"]
        with self.assertRaises(d.DesignValidationError) as caught:
            d._unique(profiles)
        diagnostic = caught.exception.diagnostic
        self.assertEqual(diagnostic["code"], "duplicate_value")
        self.assertEqual(diagnostic["duplicate_slots"], [1, 3])
        self.assertEqual(diagnostic["duplicate_field"], "mission")

    # Un duplicado dentro de una lista del perfil tambien nombra campo y slot
    def test_list_duplicate_inside_a_profile_names_field_and_slot(self):
        with self.assertRaises(d.DesignValidationError) as caught:
            d._list(["Revisar contratos", "revisar CONTRATOS"], 1, 4,
                    field="profile_specs[2].responsibilities")
        diagnostic = caught.exception.diagnostic
        self.assertEqual(diagnostic["code"], "duplicate_value")
        self.assertEqual(diagnostic["duplicate_slots"], [3])
        self.assertEqual(diagnostic["duplicate_field"], "responsibilities")

    # Camino sin repeticiones: ni reparacion ni recibo marcado
    def test_successful_design_never_repairs(self):
        fixture = Fixture()
        result = self.design(fixture)
        self.assertEqual(result["audit"]["repairs"], 0)
        self.assertEqual(result["audit"]["requests"], 1)
        self.assertEqual([row["status"] for row in result["audit"]["receipts"]], ["validated"])
        self.assertEqual(len(fixture.calls), 1)


class RepairPipelineHonesty(unittest.TestCase):
    """Superficie del panel: el fallo llega accionable y sin inventar un verde."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.guard = patch.object(socket, "create_connection",
                                  side_effect=AssertionError("No external API allowed"))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.provider = PipelineProvider()
        self.state = BridgeState(credential_store=NullStore(), provider_module=self.provider,
                                 project_store=ProjectStore(Path(self.temp.name) / "projects"))
        self.state.execute("credentials", {"provider": "deepseek-official", "api_key": PRIVATE_MARKER})
        self.state.execute("config", {"config": {"repo_url": "https://github.com/example/repair-fixture",
                                                 "repo_name": "Repair fixture", "template": "generic",
                                                 "agent_count": 2, "council_concurrency": 2,
                                                 "model": "fixture-model"}})
        self.state.execute("discover-models", {"confirmed": True})
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.provider.transport.release.set()
        active = self.state.generation._active()
        if active:
            self.state.execute("generation-cancel", {"job_id": active["job_id"]})

    def _wait(self, status):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            job = self.state.public()["generation_job"]
            if job and job["status"] == status:
                return job
            time.sleep(.005)
        self.fail("estado no alcanzado: " + repr(self.state.generation.public()))

    def _approval(self):
        pending = self.state.pending_consent
        return {"job_id": pending["job_id"], "consent_id": pending["approval_id"],
                "payload_sha256": pending["payload_sha256"], "config_version": pending["config_version"],
                "confirmed": True, "data_reviewed": True, "budget_acknowledged": True,
                "coverage_sha256": pending["coverage_sha256"], "partial_inventory_acknowledged": True}

    def test_duplicate_value_reaches_the_panel_actionable_and_billed(self):
        def mutate(value, response, index):
            for spec in value["profile_specs"]:
                if spec["name"].startswith("P02_"):
                    spec["mission"] = fixture_profile(1)["mission"]

        transport = DesignTransport(mutate=mutate)
        self.provider.transport = transport
        self.state.execute("generation-plan", {"idempotency_key": str(uuid.uuid4()), "new_project": False})
        self._wait("awaiting_consent")
        self.state.execute("generation-confirm", self._approval())
        job = self._wait("failed")
        self.assertEqual(job["failed_stage"], "api_design")
        self.assertTrue(job["potentially_billed"])          # no inventa un verde
        self.assertTrue(job["error"]["retry_requires_new_consent"])
        self.assertEqual(job["error"]["code"], "duplicate_value")
        self.assertEqual(job["error"]["duplicate_field"], "mission")
        self.assertEqual(job["error"]["duplicate_slots"], [1, 2])
        # 2 lotes planificados + 1 reparacion: nunca una tercera tentativa del mismo lote.
        self.assertEqual(len(transport.calls), 3)
        # La reparacion tiene recibo propio (indice 3): la solicitud extra es VISIBLE.
        self.assertEqual([row["index"] for row in job["request_receipts"]], [1, 2, 3])
        self.assertEqual(job["usage_summary"]["known_requests"], 3)
        # DEUDA CERRADA por el capitan: 'repaired_duplicate' entra en RECEIPT_STATUSES,
        # asi que el panel NO degrada la reparacion a 'billing_outcome_unknown'. Antes de
        # cerrarla, este mismo caso afirmaba lo contrario (assertNotIn).
        panel_statuses = [row["status"] for row in job["request_receipts"]]
        self.assertIn("repaired_duplicate", panel_statuses)
        # DEUDA CERRADA tambien: `sent_requests` se acota al TECHO consentido
        # (MAX_REQUESTS), no al numero PLANIFICADO, de modo que la solicitud extra de la
        # reparacion se informa en vez de quedar como None (que ocultaba un cargo posible).
        self.assertEqual(job["sent_requests"], 3)
        self.assertEqual(job["max_requests"], 2)
        serial = json.dumps(self.state.public(), ensure_ascii=False)
        self.assertNotIn(PRIVATE_MARKER, serial)


if __name__ == "__main__":
    unittest.main()
