#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regresión del defecto max_output_tokens=32 al verificar un modelo.

Qué se rompía: la sonda de verificación pide 32 tokens. Al fusionar su resultado
con el catálogo se REEMPLAZABA la fila del modelo, así que ``max_output_tokens``
quedaba en 32; ``org_design._model_limits`` devolvía ``min(requested, 32)`` y
``_plan`` abortaba con ``output_budget_too_small`` (``(32-1024)//3200 == -1``).
El diseño no podía avanzar nunca después de verificar.

Este test fija las dos mitades del arreglo:
  · la fusión conserva las capacidades de la fila previa y actualiza sólo lo que
    la sonda mide;
  · un plan con 131 072 tokens sobre esa fila produce al menos un perfil por
    solicitud y NO lanza ``output_budget_too_small``.

Contra el código anterior este archivo falla (ver N5_DEFECTO32.md, sección roja).
"""
import unittest
from unittest.mock import patch

from engine import bridge as b
from engine import org_design as d
from engine import providers as p


def catalog_row(**overrides):
    """Fila de catálogo tal como la deja discover-models: capacidades declaradas."""
    row = {"provider": "deepseek-official", "model": "deepseek-flash", "id": "deepseek-flash",
           "available": None, "availability_verified": False, "source": "live_api",
           "status": "AVAILABLE", "max_output_tokens": 393216, "context_window": 1000000,
           "input_modalities": ["text", "image"], "output_modalities": ["text"],
           "capabilities": ["json_object", "tools"], "user_rank": 3}
    row.update(overrides)
    return row


def probe_result(**overrides):
    """Resultado de verify_model con la forma REAL de providers.py (sonda de 32)."""
    result = {"provider": "deepseek", "model": "deepseek-flash",
              "endpoint": "https://fixture.invalid/chat/completions",
              "status": "VERIFIED_INFERENCE", "availability_verified": True, "available": True,
              "source": "minimal_inference_probe", "verified_at": "2026-10-22T10:00:00Z",
              "requests": 1, "max_output_tokens": 32,
              "warning": "Resultado puntual de una prueba mínima. No demuestra calidad ni todas las capacidades.",
              "truncated": False,
              "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}}
    result.update(overrides)
    return result


def fixture_summary():
    return {"repository": {"url": "https://github.com/example/unique-project", "sha": "a" * 40, "private": True},
            "files": [{"path": "src/main.py", "snippet": "def validate_invoice(value): return value > 0"},
                      {"path": "README.md", "snippet": "Invoice validation service and independent review."}],
            "tree": [{"path": "src/main.py"}, {"path": "README.md"}],
            "coverage": {"static_only": True, "inventory_complete": True, "truncated": False,
                         "read_files": 2, "unread_safe_files": 0, "whole_repository_content_complete": False,
                         "gaps": []}}


class MergeTests(unittest.TestCase):
    """La fusión: lo medido se actualiza, las capacidades del catálogo sobreviven."""

    def test_conserva_capacidades_y_actualiza_lo_medido(self):
        previous = catalog_row()
        row, preserved = b.merge_verified_model_row(previous, probe_result(), "deepseek-official", "deepseek-flash")
        # (c) capacidades intactas
        self.assertGreaterEqual(row["max_output_tokens"], 4096)
        self.assertEqual(row["max_output_tokens"], 393216)
        self.assertEqual(row["context_window"], 1000000)
        self.assertEqual(row["input_modalities"], ["text", "image"])
        self.assertEqual(row["output_modalities"], ["text"])
        self.assertEqual(row["capabilities"], ["json_object", "tools"])
        self.assertEqual(row["user_rank"], 3)
        self.assertEqual(sorted(preserved),
                         ["capabilities", "context_window", "input_modalities",
                          "max_output_tokens", "output_modalities", "user_rank"])
        # la fila previa no se muta: la fusión devuelve una copia
        self.assertEqual(previous["max_output_tokens"], 393216)
        # lo que la sonda mide sí se actualiza
        self.assertEqual(row["status"], "VERIFIED_INFERENCE")
        self.assertIs(row["availability_verified"], True)
        self.assertIs(row["available"], True)
        self.assertEqual(row["source"], "minimal_inference_probe")
        self.assertEqual(row["checked_at"], "2026-10-22T10:00:00Z")
        self.assertEqual(row["requests"], 1)
        self.assertEqual(row["usage"]["total_tokens"], 9)
        self.assertIs(row["truncated"], False)
        self.assertEqual(row["id"], "deepseek-flash")

    def test_sin_fila_previa_no_inventa_capacidades(self):
        row, preserved = b.merge_verified_model_row(None, probe_result(), "deepseek-official", "deepseek-flash")
        self.assertEqual(preserved, {})
        self.assertEqual(row["max_output_tokens"], 32)          # lo que midió la sonda
        self.assertNotIn("context_window", row)                 # no se inventa
        self.assertNotIn("capabilities", row)
        self.assertNotIn("user_rank", row)

    def test_fila_previa_sin_capacidades_no_las_inventa(self):
        vacia = {"provider": "deepseek-official", "model": "deepseek-flash", "available": None,
                 "max_output_tokens": None, "context_window": "", "capabilities": []}
        row, preserved = b.merge_verified_model_row(vacia, probe_result(), "deepseek-official", "deepseek-flash")
        self.assertEqual(preserved, {})
        self.assertEqual(row["max_output_tokens"], 32)

    def test_sonda_fallida_no_sobrescribe_la_capacidad(self):
        fallo = probe_result(status="UNVERIFIED", availability_verified=False, available=None)
        fallo.pop("usage")
        row, preserved = b.merge_verified_model_row(catalog_row(), fallo, "deepseek-official", "deepseek-flash")
        self.assertEqual(row["max_output_tokens"], 393216)
        self.assertIsNone(row["available"])
        self.assertEqual(row["status"], "UNVERIFIED")


class PlanTests(unittest.TestCase):
    """El plan que antes abortaba: 131 072 tokens sobre el catálogo verificado."""

    def test_plan_con_catalogo_verificado_alcanza_un_perfil_por_solicitud(self):
        row, _ = b.merge_verified_model_row(catalog_row(), probe_result(), "deepseek-official", "deepseek-flash")
        # La ruta real reescribe el proveedor de la fila al nombre de ruta antes de
        # planificar (engine/generation_pipeline.py:402-404), por eso aquí se replica.
        metadata = dict(row, provider="deepseek")
        consent = d.prepare_design_consent(fixture_summary(), "deepseek", "deepseek-flash",
                                          {"agent_count": 3}, max_output_tokens=131072, model_metadata=metadata)
        self.assertGreaterEqual(consent["effective_profiles_per_request"], 1)
        self.assertIs(consent["model_limits"]["availability_verified"], True)
        self.assertEqual([slot for request in consent["requests"] for slot in request["slots"]], [1, 2, 3])

    def test_la_fila_de_la_sonda_sola_si_aborta(self):
        """Control negativo: documenta el mecanismo exacto del defecto."""
        with self.assertRaises(d.DesignValidationError) as caught:
            d.prepare_design_consent(fixture_summary(), "deepseek", "deepseek-flash",
                                     {"agent_count": 3}, max_output_tokens=131072,
                                     model_metadata=dict(probe_result(), provider="deepseek"))
        self.assertEqual(caught.exception.diagnostic["code"], "output_budget_too_small")
        self.assertEqual(caught.exception.diagnostic["field"], "max_output_tokens")

    def test_tope_efectivo_es_el_declarado_no_el_de_la_sonda(self):
        row, _ = b.merge_verified_model_row(catalog_row(), probe_result(), "deepseek-official", "deepseek-flash")
        limits, effective_cap = d._model_limits(dict(row, provider="deepseek"), "deepseek", "deepseek-flash", 131072)
        self.assertEqual(effective_cap, 131072)
        self.assertEqual(limits["max_output_tokens"], 393216)


class NullStore:
    def load(self):
        return {}

    def delete(self):
        pass

    def save(self, value):
        raise RuntimeError("Fixture: almacenamiento persistente no disponible.")


class ProbeProvider:
    """Fixture offline: reproduce la forma REAL del resultado de verify_model."""

    def __init__(self):
        self.calls = []

    def prepare_model_verification_consent(self, provider, model, max_output_tokens=32):
        return {"kind": "model_verification", "endpoint": "https://fixture.invalid/chat/completions",
                "provider": provider, "model": model, "payload_sha256": "f" * 64,
                "max_output_tokens": max_output_tokens, "confirmed": False,
                "data_reviewed": False, "budget_acknowledged": False}

    def verify_model(self, provider, model, api_key, consent, max_output_tokens=32):
        self.calls.append(("verification", provider, model))
        return probe_result(provider=provider, model=model)


class RouteTests(unittest.TestCase):
    """La rama real de confirm-analysis, no sólo el helper."""

    def setUp(self):
        self.guard = patch("socket.create_connection",
                           side_effect=AssertionError("No external calls allowed in tests"))
        self.guard.start()

    def tearDown(self):
        self.guard.stop()

    def test_confirm_analysis_conserva_el_catalogo_y_permite_el_plan(self):
        provider = ProbeProvider()
        state = b.BridgeState(credential_store=NullStore(), provider_module=provider)
        state.credentials["deepseek-official"] = "fixture-key"
        state.models = [catalog_row()]
        state.execute("prepare-verification", {})
        pending = state.pending_consent
        approval = {"confirmed": True, "consent_id": pending["approval_id"],
                    "payload_sha256": pending["payload_sha256"],
                    "data_reviewed": True, "budget_acknowledged": True}
        state.execute("confirm-analysis", approval)

        self.assertEqual(provider.calls, [("verification", "deepseek", "deepseek-flash")])
        filas = [m for m in state.models
                 if (m.get("provider"), m.get("model", m.get("id"))) == ("deepseek-official", "deepseek-flash")]
        self.assertEqual(len(filas), 1, "la verificación debe reemplazar la fila, no duplicarla")
        row = filas[0]
        # lo que mide la sonda
        self.assertEqual(row["status"], "VERIFIED_INFERENCE")
        self.assertIs(row["available"], True)
        self.assertEqual(row["checked_at"], "2026-10-22T10:00:00Z")
        # lo que NO mide: capacidades del catálogo, intactas
        self.assertEqual(row["max_output_tokens"], 393216)
        self.assertEqual(row["context_window"], 1000000)
        self.assertEqual(row["user_rank"], 3)
        # el recibo deja constancia de qué se preservó
        recibo = state.receipts[-1]
        self.assertEqual(recibo["action"], "verify-model")
        self.assertIn("max_output_tokens", recibo["capacity_preserved"])
        self.assertEqual(recibo["capacity_note"], "")
        # y el plan que antes abortaba, ahora avanza: se usa la fila tal como la
        # entrega el producto (api_model_metadata + reescritura de proveedor de
        # engine/generation_pipeline.py:402-404).
        metadata = state.api_model_metadata(state.config)
        self.assertIsNotNone(metadata, "la fila verificada debe seguir siendo utilizable")
        metadata["provider"] = b.PROVIDER_ROUTES[state.config["provider"]]
        consent = d.prepare_design_consent(fixture_summary(), "deepseek", "deepseek-flash",
                                          {"agent_count": 2}, max_output_tokens=131072,
                                          model_metadata=metadata)
        self.assertGreaterEqual(consent["effective_profiles_per_request"], 1)


if __name__ == "__main__":
    unittest.main()
