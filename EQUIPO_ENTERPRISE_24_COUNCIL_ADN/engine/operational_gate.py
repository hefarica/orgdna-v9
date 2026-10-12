"""Puerta de MODO OPERATIVO: el diseño por API y su clave son obligatorios.

Funciones puras. No llama al proveedor; sólo decide si se puede preparar el envío.
La plantilla offline deja de ser un camino silencioso: queda como respaldo explícito.
"""
from __future__ import annotations

SCHEMA_VERSION = "operational-gate-1.0"
VERIFIED_STATUSES = ("catalog_verified", "inference_verified", "manual_documented")


def check(credentials, provider, model_choice, source_read=True):
    """Recibo operativo o ValueError determinista con todas las faltas juntas."""
    errors = []
    key = (credentials or {}).get(provider)
    if not isinstance(key, str) or not key.strip():
        errors.append("credentials: falta la clave del proveedor '" + str(provider) + "'; el diseño por API es obligatorio.")
    if not isinstance(model_choice, dict) or model_choice.get("status") not in VERIFIED_STATUSES:
        errors.append("model: el ID debe estar verificado (catálogo o inferencia) antes de preparar.")
    if not source_read:
        errors.append("source: lee primero la fuente; el diseño exige evidencia leída.")
    if errors:
        raise ValueError("; ".join(errors))
    return {"schema_version": SCHEMA_VERSION, "operational": True,
            "provider": provider, "model": model_choice.get("model"),
            "model_status": model_choice.get("status"),
            "account_verified": bool(model_choice.get("account_verified")),
            "offline_template_allowed": False,
            "note": "Modo operativo: clave presente y modelo verificado. La plantilla offline es respaldo explícito, no camino por defecto."}
