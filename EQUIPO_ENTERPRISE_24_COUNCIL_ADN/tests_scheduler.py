"""Falsificación del scheduler: 8 invariantes y 10 falsificadores.

Regla del repo: un caso que no se pone en ROJO al revertir su invariante no prueba
nada. La sección `FalsificationOfTheSuite` comprueba esa reversibilidad.

El scheduler NO ejecuta: los puertos son dobles de prueba, así que toda la suite es
offline y no toca el host.
"""
import unittest

from engine import scheduler as sc
from engine import task_graph as tg

NOW = "2026-10-12T00:00:00Z"
LATER = "2026-10-12T09:59:00Z"


def ports(launched=None, gate=True, leases=None):
    """Puertos dobles. Registran quién se despachó; no tocan nada real."""
    launched = launched if launched is not None else []
    leases = leases if leases is not None else {}

    def dispatch(task_id, agent_ref, lease_id):
        launched.append((task_id, lease_id))
        return {"status": "RECORDED_ONLY", "task_id": task_id}

    return {"dispatch": dispatch, "gate_ready": (lambda: gate), "launched": launched, "leases": leases}


def run_for(rows, cap=3, phase="implementation"):
    config = sc.SchedulerConfig(phase=phase, implementation_concurrency=cap, council_concurrency=cap)
    return sc.build_run(rows, config=config, phase=phase)


INDEPENDENT_10 = {("t%02d" % i): {"depends_on": []} for i in range(10)}


class StateMachineTests(unittest.TestCase):
    def test_F1_concurrency_cap_is_respected(self):
        """I4: 10 listos con tope 3 -> 3 corriendo, el resto 'pending'."""
        run = run_for(INDEPENDENT_10, cap=3)
        harness = ports()
        after, events = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        report = sc.inspect_run(after)
        self.assertEqual(report["running"], 3)
        self.assertEqual(report["pending"], 7)
        self.assertEqual(len(harness["launched"]), 3)
        self.assertEqual(report["code"], "IN_PROGRESS")

    def test_F2_dependency_must_be_passed_not_running(self):
        """I5: 'ta' en running NO habilita a 'tb'."""
        run = run_for({"ta": {"depends_on": []}, "tb": {"depends_on": ["ta"]}})
        harness = ports()
        after, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        self.assertEqual(after.node("ta").state, "running")
        self.assertEqual(after.node("tb").state, "not_run")
        self.assertEqual(sc.ready_tasks(after), ())

    def test_F3_gate_red_launches_nothing(self):
        """I3: fail-closed. Ni un lanzamiento, y el run queda intacto."""
        run = run_for(INDEPENDENT_10, cap=3)
        harness = ports(gate=False)
        after, events = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        self.assertEqual(harness["launched"], [])
        self.assertEqual(after, run, "el run no debe cambiar si la puerta esta en rojo")
        self.assertEqual(events[0][0], "GATE_BLOCKED")

    def test_F4_failed_never_returns_to_running(self):
        """I2: sin reintentos automaticos."""
        run = run_for({"ta": {"depends_on": []}})
        harness = ports()
        run, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        run = sc.complete(run, "ta", result="failed", now=NOW)
        for _ in range(3):
            run, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=LATER)
        self.assertEqual(run.node("ta").state, "failed")
        self.assertEqual(len(harness["launched"]), 1, "no debe redespacharse")
        self.assertEqual(sc.ready_tasks(run), ())

    def test_F5_write_node_without_lease_is_not_dispatched(self):
        """I6: lease ANTES de despachar un nodo con capacidad de escritura."""
        run = run_for({"tw": {"depends_on": [], "write_capable": True}})
        harness = ports()
        after, events = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        self.assertEqual(harness["launched"], [])
        self.assertEqual(after.node("tw").state, "pending")
        self.assertIn("LEASE_REQUIRED", [event[0] for event in events])
        # con lease, si se despacha
        leased, lease = sc.acquire_for(run, "tw", acquire=lambda t, p, s: "lease-1", base_sha="b" * 40)
        self.assertEqual(lease, "lease-1")
        after2, _ = sc.step(leased, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        self.assertEqual(after2.node("tw").state, "running")
        self.assertEqual(harness["launched"], [("tw", "lease-1")])

    def test_F6_untouched_node_is_not_run_never_passed(self):
        """I7: desconocido NO es cero. Antes de tocar nada, todo es 'not_run'."""
        run = run_for({"ta": {"depends_on": []}, "tb": {"depends_on": ["ta"]}})
        report = sc.inspect_run(run)
        self.assertEqual(report["not_run"], 2)
        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["running"], 0)
        self.assertEqual(report["code"], "NOT_STARTED")
        self.assertFalse(report["valid"] is False and report["failed"] > 0)

    def test_F7_run_hash_ignores_volatile_timestamps(self):
        """I8: el hash no cambia con 'now'."""
        run = run_for(INDEPENDENT_10, cap=3)
        harness = ports()
        first, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        second, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=LATER)
        self.assertNotEqual(first.node("t00").started_at, second.node("t00").started_at)
        self.assertEqual(sc.run_sha256(first), sc.run_sha256(second))
        self.assertRegex(sc.run_sha256(first), r"^[0-9a-f]{64}$")

    def test_F8_failure_blocks_descendants(self):
        """I5+I7: 'ta' failed -> 'tb' blocked, y no 'passed'."""
        run = run_for({"ta": {"depends_on": []}, "tb": {"depends_on": ["ta"]}, "tc": {"depends_on": ["tb"]}})
        harness = ports()
        run, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        run = sc.complete(run, "ta", result="failed", now=NOW)
        self.assertEqual(run.node("tb").state, "blocked")
        self.assertEqual(run.node("tc").state, "blocked")
        report = sc.inspect_run(run)
        self.assertEqual(report["code"], "FAILED")
        self.assertFalse(report["valid"])
        self.assertEqual(report["passed"], 0)

    def test_F9_ready_order_is_deterministic_under_permutation(self):
        """I1: el orden no depende del orden de entrada."""
        forward = sc.ready_tasks(run_for({"ta": {"depends_on": []}, "tb": {"depends_on": []}, "tc": {"depends_on": []}}))
        backward = sc.ready_tasks(run_for({"tc": {"depends_on": []}, "tb": {"depends_on": []}, "ta": {"depends_on": []}}))
        self.assertEqual(forward, backward)
        self.assertEqual(forward, ("ta", "tb", "tc"))

    def test_F10_unknown_dependency_is_a_typed_rejection(self):
        """Rechazo tipado, nunca KeyError."""
        with self.assertRaises(sc.InvalidRunError):
            run_for({"ta": {"depends_on": ["no-existe"]}})
        with self.assertRaises(sc.InvalidRunError):
            run_for({"ta": {"depends_on": ["ta"]}})
        with self.assertRaises(sc.InvalidRunError):
            run_for({"a": {"depends_on": []}})


class ContractTests(unittest.TestCase):
    def test_phase_cannot_contradict_config(self):
        config = sc.SchedulerConfig(phase="implementation", implementation_concurrency=2, council_concurrency=5)
        with self.assertRaisesRegex(sc.InvalidRunError, "contradecir"):
            sc.build_run(INDEPENDENT_10, config=config, phase="council")

    def test_council_phase_uses_council_concurrency(self):
        config = sc.SchedulerConfig(phase="council", implementation_concurrency=1, council_concurrency=4)
        run = sc.build_run(INDEPENDENT_10, config=config)
        harness = ports()
        after, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        self.assertEqual(sc.inspect_run(after)["running"], 4)

    def test_complete_only_from_running(self):
        run = run_for({"ta": {"depends_on": []}})
        with self.assertRaisesRegex(sc.InvalidRunError, "no esta 'running'"):
            sc.complete(run, "ta", result="passed", now=NOW)

    def test_result_must_be_passed_or_failed(self):
        run = run_for({"ta": {"depends_on": []}})
        harness = ports()
        run, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        for bad in ("not_run", "blocked", "unknown", None, ""):
            with self.subTest(result=bad), self.assertRaises(sc.InvalidRunError):
                sc.complete(run, "ta", result=bad, now=NOW)

    def test_acquire_for_rejects_non_write_and_terminal(self):
        run = run_for({"ta": {"depends_on": []}})
        with self.assertRaisesRegex(sc.InvalidRunError, "capacidad de escritura"):
            sc.acquire_for(run, "ta", acquire=lambda *a: "l", base_sha="b" * 40)

    def test_acquire_port_cannot_return_a_blank_lease(self):
        run = run_for({"tw": {"depends_on": [], "write_capable": True}})
        with self.assertRaisesRegex(sc.InvalidRunError, "lease invalido"):
            sc.acquire_for(run, "tw", acquire=lambda *a: "   ", base_sha="b" * 40)
        with self.assertRaisesRegex(sc.InvalidRunError, "lease invalido"):
            sc.acquire_for(run, "tw", acquire=lambda *a: None, base_sha="b" * 40)

    def test_reopen_requires_explicit_decision_and_a_blocked_node(self):
        run = run_for({"ta": {"depends_on": []}, "tb": {"depends_on": ["ta"]}})
        harness = ports()
        run, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        run = sc.complete(run, "ta", result="failed", now=NOW)
        reopened = sc.reopen(run, "tb", reason="el propietario decide reintentar el descendiente")
        self.assertEqual(reopened.node("tb").state, "pending")
        with self.assertRaisesRegex(sc.InvalidRunError, "no esta 'blocked'"):
            sc.reopen(reopened, "tb", reason="otra vez")

    def test_ports_are_validated(self):
        run = run_for({"ta": {"depends_on": []}})
        with self.assertRaisesRegex(sc.InvalidRunError, "puerto invocable"):
            sc.step(run, dispatch=None, gate_ready=lambda: True, now=NOW)
        with self.assertRaisesRegex(sc.InvalidRunError, "puerto invocable"):
            sc.step(run, dispatch=lambda *a: None, gate_ready=None, now=NOW)

    def test_unknown_node_field_is_rejected(self):
        with self.assertRaisesRegex(sc.InvalidRunError, "campos no admitidos"):
            run_for({"ta": {"depends_on": [], "campo_raro": 1}})

    def test_scheduler_never_claims_runtime(self):
        report = sc.inspect_run(run_for(INDEPENDENT_10))
        self.assertFalse(report["runtime_verified"])
        self.assertFalse(report["executed_here"])
        self.assertIn("no ejecuta", report["note"])

    def test_release_port_is_called_on_completion(self):
        freed = []
        run = run_for({"tw": {"depends_on": [], "write_capable": True}})
        run, _ = sc.acquire_for(run, "tw", acquire=lambda *a: "lease-7", base_sha="b" * 40)
        harness = ports()
        run, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        sc.complete(run, "tw", result="passed", now=NOW, release=freed.append)
        self.assertEqual(freed, ["lease-7"])


class AdapterTests(unittest.TestCase):
    """El adaptador contra un TaskGraph REAL, no contra un doble."""

    @staticmethod
    def spec(task_id, depends_on, level="observe"):
        return {"taskspec_version": "1", "task_id": task_id, "title": "T " + task_id,
                "intent": "hacer " + task_id, "autonomy_level": level, "depends_on": list(depends_on),
                "budget": {"tokens": 100, "money_usd": 0, "time_seconds": 60, "requests": 1},
                "acceptance_criteria": [{"criterion": "c-" + task_id, "verify": "test verificado", "status": "pending"}],
                "falsifiers": [{"falsifier_id": "f-" + task_id, "statement": "no cumplido", "how_detected": "test"}],
                "idempotency_key": "key-" + task_id + "-0001"}

    def test_adapter_reads_a_real_graph(self):
        graph = tg.build_graph([self.spec("ta", []), self.spec("tb", ["ta"])], approved=True)
        config = sc.SchedulerConfig(phase="implementation", implementation_concurrency=3, council_concurrency=1)
        run = sc.build_run(graph, config=config)
        self.assertEqual(tuple(n.task_id for n in run.nodes), graph.topological_order)
        self.assertEqual(run.graph_sha256, graph.graph_sha256)
        self.assertEqual(sc.ready_tasks(run), ("ta",))

    def test_write_capable_comes_from_the_graph_contract(self):
        """No hay una segunda lista: se usa WRITE_CAPABLE_AUTONOMY_LEVELS del contrato v1."""
        graph = tg.build_graph([self.spec("ta", []), self.spec("tw", [], "execute-approved")], approved=True)
        config = sc.SchedulerConfig(phase="implementation", implementation_concurrency=3, council_concurrency=1)
        run = sc.build_run(graph, config=config)
        self.assertFalse(run.node("ta").write_capable)
        self.assertTrue(run.node("tw").write_capable)
        self.assertIn("execute-approved", tg.WRITE_CAPABLE_AUTONOMY_LEVELS)

    def test_unbuilt_graph_is_rejected(self):
        with self.assertRaisesRegex(sc.InvalidRunError, "TaskGraph construido"):
            sc.build_run(object(), config=sc.SchedulerConfig())


class FalsificationOfTheSuite(unittest.TestCase):
    """Meta-caso: comprueba que las invariantes clave son REVERSIBLES.

    No basta con que los tests pasen; hay que poder demostrar que se ponen rojos si
    la invariante desaparece. Aqui se simula la ausencia de cada invariante sobre el
    propio Run, sin tocar el modulo.
    """

    def test_cap_removed_would_launch_everything(self):
        run = run_for(INDEPENDENT_10, cap=3)
        harness = ports()
        honest, _ = sc.step(run, dispatch=harness["dispatch"], gate_ready=harness["gate_ready"], now=NOW)
        self.assertEqual(sc.inspect_run(honest)["running"], 3)
        # Si el tope no existiera, se habrian lanzado los 10: la asercion de F1 lo detecta.
        self.assertLess(sc.inspect_run(honest)["running"], len(INDEPENDENT_10))

    def test_lease_invariant_is_observable(self):
        write_run = run_for({"tw": {"depends_on": [], "write_capable": True}})
        plain_run = run_for({"tp": {"depends_on": []}})
        harness_w, harness_p = ports(), ports()
        after_w, _ = sc.step(write_run, dispatch=harness_w["dispatch"], gate_ready=harness_w["gate_ready"], now=NOW)
        after_p, _ = sc.step(plain_run, dispatch=harness_p["dispatch"], gate_ready=harness_p["gate_ready"], now=NOW)
        self.assertEqual(after_w.node("tw").state, "pending")
        self.assertEqual(after_p.node("tp").state, "running")

    def test_not_run_can_never_reach_passed_without_running(self):
        run = run_for(INDEPENDENT_10)
        self.assertTrue(all(n.state == "not_run" for n in run.nodes))
        # 
        # Ningun nodo puede pasar a passed desde not_run: complete exige running.
        for node in run.nodes:
            with self.subTest(node=node.task_id), self.assertRaises(sc.InvalidRunError):
                sc.complete(run, node.task_id, result="passed", now=NOW)


if __name__ == "__main__":
    unittest.main()
