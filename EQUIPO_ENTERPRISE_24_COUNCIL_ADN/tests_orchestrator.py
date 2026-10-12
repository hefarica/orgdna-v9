"""Falsificación del orquestador (el cigüeñal).

Lo que se prueba de verdad aquí: que la puerta es la REAL (readiness_gate), que los
leases son los REALES (coordination), y que sin runtime el bucle NO afirma nada.
"""
import os
import tempfile
import unittest

from engine import coordination
from engine import orchestrator as orch
from engine import scheduler as sc


NOW = "2026-10-12T00:00:00Z"
GRAPH = {"ta": {"depends_on": []}, "tb": {"depends_on": []}, "tc": {"depends_on": ["ta", "tb"]}}


def run_for(cap=3):
    return sc.build_run(GRAPH, config=sc.SchedulerConfig(implementation_concurrency=cap, council_concurrency=1))


def yes():
    return True


def no():
    return False


class GateTests(unittest.TestCase):
    """La puerta es readiness_gate REAL, no un lambda."""

    def test_missing_tool_closes_the_gate_and_nothing_launches(self):
        gate = orch.build_gate(["herramienta-inexistente"], ["herramienta-inexistente"], [],
                               ["ops_plan", "ops_status"])
        self.assertFalse(gate())
        launched = []
        run, events = sc.step(run_for(), dispatch=lambda *a: launched.append(a),
                              gate_ready=gate, now=NOW)
        self.assertEqual(launched, [])
        self.assertEqual(sc.inspect_run(run)["not_run"], 3)

    def test_denied_tool_closes_the_gate(self):
        gate = orch.build_gate(["ops_plan"], ["ops_plan"], ["ops_plan"], ["ops_plan"])
        self.assertFalse(gate())

    def test_ready_tools_open_the_gate(self):
        gate = orch.build_gate(["ops_plan"], ["ops_plan"], [], ["ops_plan"])
        self.assertTrue(gate())

    def test_the_verdict_is_available_for_evidence(self):
        gate = orch.build_gate(["nope"], ["nope"], [], ["ops_plan"])
        verdict = gate.verdict()
        self.assertFalse(verdict["ready"])
        self.assertEqual(verdict["blocked_by"][0]["code"], "tool_missing_from_catalog")

    def test_real_catalog_is_read_not_invented(self):
        names = orch.tool_catalog_names()
        self.assertIn("ops_plan", names)
        self.assertGreater(len(names), 50)


class LeasePortTests(unittest.TestCase):
    """Los leases son el registro de coordinación REAL, con expected_version."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orch_lease_")
        self.store = coordination.CoordinationStore(os.path.join(self.tmp, "coord.json"))
        self.acquire, self.release = orch.make_lease_ports(self.store, "agent-01", self.tmp)

    def test_round_trip_against_the_real_store(self):
        before = self.store.public()["version"]
        lease = self.acquire("ta", ["src/x.py"], "a" * 40)
        self.assertTrue(lease)
        self.assertEqual(self.store.public()["active_writer_count"], 1)
        self.assertGreater(self.store.public()["version"], before)
        self.release(lease)
        self.assertEqual(self.store.public()["active_writer_count"], 0)

    def test_coordination_still_declares_it_is_cooperative(self):
        """No se hereda ninguna garantía que el módulo no da."""
        public = self.store.public()
        self.assertFalse(public["filesystem_lock_enforced"])
        self.assertFalse(public["dsh_enforced"])
        self.assertEqual(public["enforcement"], "local_coordination_only")

    def test_bad_base_sha_is_rejected_by_the_real_store(self):
        with self.assertRaises(coordination.CoordinationError):
            self.acquire("ta", ["src/x.py"], "no-es-un-sha")

    def test_write_node_needs_a_lease_before_dispatch(self):
        graph = {"tw": {"depends_on": [], "write_capable": True, "paths": ["src/y.py"]}}
        run = sc.build_run(graph, config=sc.SchedulerConfig())
        launched = []
        after, events = sc.step(run, dispatch=lambda *a: launched.append(a), gate_ready=yes, now=NOW)
        self.assertEqual(launched, [])
        self.assertIn("LEASE_REQUIRED", [e[0] for e in events])
        run, lease = sc.acquire_for(after, "tw", acquire=self.acquire, base_sha="b" * 40)
        after, _ = sc.step(run, dispatch=lambda *a: launched.append(a), gate_ready=yes, now=NOW)
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0][2], lease)


class NoRuntimeTests(unittest.TestCase):
    """El caso REAL de este árbol: no hay runtime. El bucle no puede afirmar nada."""

    def test_default_dispatch_refuses_and_the_run_stays_blocked(self):
        report = orch.drive(run_for(), gate_ready=yes, now=NOW)
        self.assertEqual(report["passed"], 0, "sin runtime NO puede haber un 'passed'")
        # 'ta' y 'tb' se EVALUARON y quedaron esperando -> pending. 'tc' depende de
        # ambos, asi que nunca se evaluo -> not_run. 'not_run' no es 'pending'.
        self.assertEqual(report["pending"], 2)
        self.assertEqual(report["not_run"], 1)
        self.assertEqual(report["code"], "IN_PROGRESS")
        self.assertEqual(report["stopped_because"], "NO_PROGRESS")
        self.assertFalse(report["runtime_verified"])
        self.assertFalse(report["executed_here"])

    def test_the_refusal_says_why_and_where(self):
        report = orch.drive(run_for(), gate_ready=yes, now=NOW)
        codes = [event[0] for event in report["events"]]
        self.assertIn("DISPATCH_UNAVAILABLE", codes)
        detail = [e[2] for e in report["events"] if e[0] == "DISPATCH_UNAVAILABLE"][0]
        self.assertIn("CAPABILITY_UNAVAILABLE", detail, "debe citar el stub real")
        self.assertIn("dsh_connection.py:303", detail)

    def test_no_runtime_does_not_mark_nodes_failed(self):
        """'no se pudo empezar' NO es 'falló': los nodos quedan not_run/pending."""
        report = orch.drive(run_for(), gate_ready=yes, now=NOW)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["blocked"], 0)

    def test_blocked_reasons_are_grouped_for_the_operator(self):
        report = orch.drive(run_for(), gate_ready=yes, now=NOW)
        grouped = orch.blocked_reasons(report)
        self.assertIn("DISPATCH_UNAVAILABLE", grouped)
        self.assertTrue(grouped["DISPATCH_UNAVAILABLE"])


class LoopTests(unittest.TestCase):
    def test_happy_path_terminates_and_marks_everything_passed(self):
        dispatched = []

        def dispatch(task_id, agent_ref, lease_id):
            dispatched.append(task_id)
            return {"status": "ACCEPTED"}

        report = orch.drive(run_for(), dispatch=dispatch, poll=lambda task_id: "passed",
                            gate_ready=yes, now=NOW)
        self.assertEqual(report["code"], "COMPLETE")
        self.assertEqual(report["passed"], 3)
        self.assertEqual(report["stopped_because"], "TERMINAL")
        self.assertEqual(sorted(dispatched), ["ta", "tb", "tc"])
        self.assertTrue(report["valid"])

    def test_a_failing_node_blocks_its_descendants(self):
        def dispatch(task_id, agent_ref, lease_id):
            return {"status": "ACCEPTED"}

        report = orch.drive(run_for(), dispatch=dispatch,
                            poll=lambda task_id: "failed" if task_id == "ta" else "passed",
                            gate_ready=yes, now=NOW)
        self.assertEqual(report["failed"], 1)
        self.assertGreaterEqual(report["blocked"], 1)
        self.assertFalse(report["valid"])
        self.assertEqual(report["code"], "FAILED")

    def test_stalled_poll_stops_by_progress_not_by_spinning(self):
        """`poll` que nunca resuelve: el bucle para, no gira en vacío."""
        report = orch.drive(run_for(), dispatch=lambda *a: {"ok": True}, poll=lambda task_id: None,
                            gate_ready=yes, now=NOW)
        self.assertEqual(report["stopped_because"], "NO_PROGRESS")
        self.assertEqual(report["passed"], 0)
        self.assertLess(report["steps"], 10, "no debe girar en vacío")

    def test_a_real_dispatch_error_fails_the_node(self):
        def exploding(task_id, agent_ref, lease_id):
            raise RuntimeError("el host rechazo el plan")

        report = orch.drive(run_for(), dispatch=exploding, gate_ready=yes, now=NOW)
        # 'ta' y 'tb' fallan; 'tc' es descendiente de ambos y queda BLOQUEADO, no failed.
        self.assertEqual(report["failed"], 2)
        self.assertEqual(report["blocked"], 1)
        self.assertIn("DISPATCH_FAILED", [e[0] for e in report["events"]])

    def test_no_runtime_and_a_real_error_are_distinguished(self):
        """El mismo nodo, dos causas distintas, dos estados distintos."""
        unavailable = orch.drive(run_for(), gate_ready=yes, now=NOW)
        broken = orch.drive(run_for(), dispatch=lambda *a: (_ for _ in ()).throw(RuntimeError("x")),
                            gate_ready=yes, now=NOW)
        self.assertEqual(unavailable["failed"], 0, "no hay runtime: nada fallo")
        self.assertEqual(unavailable["blocked"], 0)
        self.assertEqual(broken["failed"], 2, "hay error real: si fallo")
        self.assertGreater(broken["blocked"], 0)

    def test_gate_red_stops_everything(self):
        report = orch.drive(run_for(), dispatch=lambda *a: {"ok": True}, poll=lambda t: "passed",
                            gate_ready=no, now=NOW)
        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["not_run"], 3)
        self.assertIn("GATE_BLOCKED", [e[0] for e in report["events"]])

    def test_cap_is_respected_across_ticks(self):
        def dispatch(task_id, agent_ref, lease_id):
            return {"ok": True}

        seen = []

        def poll(task_id):
            seen.append(task_id)
            return "passed"

        report = orch.drive(run_for(cap=1), dispatch=dispatch, poll=poll, gate_ready=yes, now=NOW)
        self.assertEqual(report["code"], "COMPLETE")
        self.assertEqual(sorted(seen), ["ta", "tb", "tc"])

    def test_ports_and_arguments_are_validated(self):
        with self.assertRaisesRegex(orch.OrchestratorError, "gate_ready"):
            orch.drive(run_for(), gate_ready=None, now=NOW)
        with self.assertRaisesRegex(orch.OrchestratorError, "run:"):
            orch.drive("no es un run", gate_ready=yes, now=NOW)
        with self.assertRaisesRegex(orch.OrchestratorError, "now:"):
            orch.drive(run_for(), gate_ready=yes, now="   ")
        with self.assertRaisesRegex(orch.OrchestratorError, "max_steps"):
            orch.drive(run_for(), gate_ready=yes, now=NOW, max_steps=0)

    def test_report_is_deterministic_and_digested(self):
        first = orch.drive(run_for(), gate_ready=yes, now=NOW)
        second = orch.drive(run_for(), gate_ready=yes, now=NOW)
        self.assertEqual(first["events_sha256"], second["events_sha256"])
        self.assertRegex(first["events_sha256"], r"^[0-9a-f]{64}$")


class NoRuntimeClaimTests(unittest.TestCase):
    def test_the_orchestrator_never_claims_runtime(self):
        report = orch.drive(run_for(), gate_ready=yes, now=NOW)
        self.assertFalse(report["runtime_verified"])
        self.assertFalse(report["executed_here"])
        self.assertIn("no acredita runtime", report["note"])


if __name__ == "__main__":
    unittest.main()
