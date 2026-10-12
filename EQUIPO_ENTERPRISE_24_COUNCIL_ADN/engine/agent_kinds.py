"""Catálogo declarativo y extensible de CLASES de agente, agnóstico de dominio.

No ejecuta nada, no llama al proveedor. Da códigos estables, resolución determinista
por palabras clave y una preset general con nombres del catálogo del usuario, para
que CUALQUIER clase de agente (no sólo las 32 semillas de ingeniería) tenga preset
y pase validación. Cero dependencias de estado.
"""
from __future__ import annotations

import re

SCHEMA_VERSION = "agent-kinds-1.0"
GENERAL_CODE = "GENERAL"
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,39}$")

# (code, title, department, keywords, domain_tools)
KINDS = (
    ("LEGAL", "Asesoría legal y contratos", "Legal", ("legal", "contrato", "contract", "compliance", "normativa", "juridico", "licencia"), ("research_report", "evidence_add")),
    ("HEALTH", "Dominio clínico y salud", "Salud", ("salud", "clinico", "medic", "health", "paciente", "diagnostico"), ("research_report", "evidence_add")),
    ("FINANCE", "Finanzas y control", "Finanzas", ("finanza", "financ", "contab", "presupuesto", "tesoreria"), ("research_report", "evidence_add")),
    ("DATASCI", "Ciencia de datos e IA", "Datos", ("datos", "data", "machine", "estadistica", "modelo"), ("research_report", "evidence_add")),
    ("DESIGN", "Diseño de producto y marca", "Diseño", ("diseno", "design", "marca", "brand", "ux", "ui", "visual"), ("visual_mermaid", "visual_ascii")),
    ("GROWTH", "Crecimiento y marketing", "Marketing", ("marketing", "crecimiento", "growth", "campana", "seo"), ("research_report", "evidence_add")),
    ("SALES", "Ventas y alianzas", "Comercial", ("venta", "sales", "comercial", "alianza", "pipeline"), ("research_report", "evidence_add")),
    ("SUPPORT", "Soporte y atención", "Soporte", ("soporte", "support", "atencion", "ticket", "incidencia"), ("ops_plan", "evidence_add")),
    ("OPSLOG", "Operaciones y logística", "Operaciones", ("operacion", "logistica", "supply", "inventario", "proceso"), ("ops_plan", "ops_status")),
    ("RESEARCH", "Investigación científica", "Investigación", ("investiga", "research", "ciencia", "paper", "experimento", "hipotesis"), ("research_report", "evidence_add")),
    ("EDUCATION", "Educación y formación", "Educación", ("educa", "formacion", "curso", "docencia"), ("research_report", "evidence_add")),
    ("MANUFACT", "Manufactura y calidad física", "Manufactura", ("manufact", "fabrica", "planta", "produccion", "calidad"), ("ops_plan", "evidence_add")),
    ("PEOPLE", "Personas y cultura", "Personas", ("personas", "people", "talento", "cultura", "reclut"), ("research_report", "evidence_add")),
    ("PROCURE", "Compras y proveedores", "Compras", ("compra", "procure", "proveedor", "vendor", "suministro"), ("research_report", "evidence_add")),
    ("COMPLIANCE", "Riesgo y cumplimiento", "Riesgo", ("riesgo", "cumplimiento", "compliance", "auditoria", "control"), ("research_report", "evidence_add")),
    ("CONTENT", "Contenido y redacción", "Contenido", ("contenido", "redaccion", "copy", "editorial", "traduccion"), ("research_report", "visual_ascii")),
    ("GAME", "Videojuegos e interacción", "Entretenimiento", ("juego", "game", "jugabilidad", "nivel", "motor"), ("visual_mermaid", "evidence_add")),
    ("EMBEDDED", "Sistemas embebidos y hardware", "Hardware", ("embebido", "hardware", "firmware", "placa", "sensor"), ("ops_plan", "evidence_add")),
    ("CLOUD", "Infraestructura y nube", "Plataforma", ("nube", "cloud", "infra", "devops", "cluster"), ("ops_plan", "ops_status")),
    ("BLOCKCHAIN", "Cadena de bloques y protocolos", "Cadena", ("blockchain", "cadena", "solidity", "onchain", "token"), ("research_report", "evidence_add")),
    ("ROBOTICS", "Robótica y control", "Robótica", ("robot", "robotica", "actuador", "cinematica"), ("ops_plan", "evidence_add")),
    ("ENERGY", "Energía y sostenibilidad", "Energía", ("energia", "solar", "renovable", "emisiones"), ("research_report", "evidence_add")),
    ("PUBLIC", "Sector público y políticas", "Público", ("publico", "politica", "gobierno", "regulacion", "ciudadano"), ("research_report", "evidence_add")),
    ("HOSPITALITY", "Hospitalidad y servicio", "Servicio", ("hotel", "restaurante", "turismo", "hospitalidad"), ("ops_plan", "evidence_add")),
    ("AUTO", "Automoción y movilidad", "Movilidad", ("automocion", "vehiculo", "movilidad", "conduccion"), ("ops_plan", "evidence_add")),
    ("AERO", "Aeroespacial y defensa", "Aeroespacial", ("aero", "espacio", "satelite", "vuelo", "defensa"), ("research_report", "evidence_add")),
)

GENERAL_TOOLS = ("ops_plan", "ops_status", "research_report", "visual_ascii", "visual_mermaid", "evidence_add")
CODES = tuple(kind[0] for kind in KINDS) + (GENERAL_CODE,)


def _clean(value):
    return re.sub(r"domain_\d+_", "", str(value or "").casefold())


def resolve_code(agent):
    """Clase por palabras clave. Determinista (primer empate gana). GENERAL si nada encaja."""
    if not isinstance(agent, dict):
        raise ValueError("agent: se requiere objeto.")
    haystack = " ".join(_clean(agent.get(k, "")) for k in ("role", "title", "department", "mission"))
    best, best_score = GENERAL_CODE, 0
    for code, _title, _department, keywords, _tools in KINDS:
        score = sum(1 for keyword in keywords if keyword in haystack)
        if score > best_score:
            best, best_score = code, score
    return best


def _preset(role_name, tools, known, notes, extra_gaps=()):
    gaps = ["Capacidad objetivo pendiente de evaluación y preflight runtime."]
    gaps.extend(extra_gaps)
    return {"role": role_name, "allow_candidates": list(tools), "conditional_candidates": [],
            "excluded_candidates": [], "capability_gaps": gaps,
            "notes": list(notes), "kind_resolution": "declared_class_by_keyword_not_semantic"}


def _empty_gap(tools):
    """Una lista vacia NO puede ser silenciosa: el catálogo aportado no cubre la clase."""
    if tools:
        return ()
    return ("Sin herramientas del catálogo aportado para esta clase: pasa known_tools antes de usar el preset.",)


def resolve_preset(agent, known_tools=()):
    """Preset para cualquier clase. Sólo nombres que existan en el catálogo del usuario."""
    known = set(known_tools)
    code = resolve_code(agent)
    if code == GENERAL_CODE:
        tools = [n for n in GENERAL_TOOLS if n in known]
        return _preset(GENERAL_CODE, tools, known,
                       ["Clase general: revisar capacidades necesarias antes de usar este perfil."],
                       _empty_gap(tools))
    for kind_code, title, _department, _keywords, domain_tools in KINDS:
        if kind_code == code:
            tools = [n for n in dict.fromkeys(GENERAL_TOOLS[:2] + domain_tools) if n in known]
            return _preset(kind_code, tools, known,
                           ["Preset por clase declarada, basado en nombres del catálogo aportado."],
                           _empty_gap(tools))
    raise ValueError("resolve_preset: clase no resuelta.")  # inalcanzable por construcción


def kind_title(code):
    for kind_code, title, _d, _k, _t in KINDS:
        if kind_code == code:
            return title
    return "General"
