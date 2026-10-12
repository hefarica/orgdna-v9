"""Compilador de contexto acotado y determinista: un agente, una tarea, un slice.

Stdlib puro. Sin red, sin efectos al importar, sin contenedores mutables de módulo.
La selección corre por niveles de prioridad explícitos con una relevancia
determinista; NADA se descarta en silencio: cada omisión se reporta con su motivo.
Los mismos bytes de request producen siempre el mismo digest.

No es recuperación semántica: es selección por solape de términos con presupuesto.
El módulo no ejecuta agentes, no llama al proveedor y no concede permisos.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA_VERSION = "context-compile-1.0"

DEFAULT_BUDGET_BYTES = 12_000
MIN_BUDGET_BYTES = 1_024
MAX_BUDGET_BYTES = 96_000
MAX_ITEMS_PER_SECTION = 64
MAX_TEXT_BYTES = 8_000
BYTES_PER_TOKEN = 3          # misma estimación conservadora que usa el motor
_ITEM_OVERHEAD = 24          # encuadre por elemento, contabilizado

# El orden de _TIERS es el orden de selección. `mandate` nunca se descarta.
_TIERS = ("mandate", "task", "evidence", "skill", "memory", "handoff")
_NEVER_DROP = frozenset(("mandate",))
_REQUEST_KEYS = frozenset(("agent", "task", "objective", "evidence", "skill", "memory", "handoff", "budget_bytes"))

_STOPWORDS = frozenset((
    "the", "and", "for", "with", "from", "that", "this", "into", "are", "was",
    "were", "will", "not", "but", "its", "our", "their", "all", "any", "can",
    "los", "las", "del", "que", "con", "por", "para", "una", "unos", "unas",
    "como", "sobre", "entre", "desde", "hasta", "este", "esta", "estos", "estas",
    "sus", "mas", "sin", "son", "sea", "ser", "hay", "muy", "cada", "toda",
))

# Claves admitidas por elemento. Rechazar las ajenas es la misma disciplina que
# _REQUEST_KEYS y que _SKILL_KEYS del bucle de mejora: un campo desconocido es un
# error del llamante, no algo que se ignora en silencio.
_ITEM_KEYS = {
    "evidence": frozenset(("id", "path", "text")),
    "skill": frozenset(("id", "name", "version", "instructions")),
    "memory": frozenset(("id", "kind", "text")),
    "handoff": frozenset(("id", "from", "to", "summary")),
}
_TOKEN = re.compile(r"[0-9a-z_]{3,}")


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _text(value, field, maximum=MAX_TEXT_BYTES):
    if not isinstance(value, str):
        raise ValueError(f"{field}: se requiere texto.")
    value = value.strip()
    if not value:
        raise ValueError(f"{field}: texto vacío.")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{field}: supera {maximum} bytes UTF-8.")
    return value


def _bounded_int(value, field, minimum, maximum):
    if type(value) is not int:
        raise ValueError(f"{field}: se requiere entero.")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field}: entero {minimum}..{maximum} requerido.")
    return value


def _terms(text):
    return frozenset(token for token in _TOKEN.findall(text.casefold()) if token not in _STOPWORDS)


def _relevance(query, text):
    terms = _terms(text)
    if not terms:
        return 0.0
    overlap = len(query & terms)
    if not overlap:
        return 0.0
    return round(overlap / (len(terms) ** 0.5), 6)


def _item(kind, ident, text, provenance=None):
    row = {"id": ident, "kind": kind, "text": text, "bytes": len(text.encode("utf-8"))}
    if provenance:
        row["provenance"] = provenance
    return row


def _agent_items(agent):
    if not isinstance(agent, dict):
        raise ValueError("agent: se requiere objeto.")
    items = []
    for key in ("name", "role", "title", "mission", "personality", "reports_to"):
        if agent.get(key) not in (None, ""):
            items.append(_item("mandate", "agent." + key, _text(agent[key], "agent." + key)))
    if not items:
        raise ValueError("agent: se requiere al menos un campo de mandato (name, role, mission...).")
    return items


def _task_items(task):
    if not isinstance(task, dict):
        raise ValueError("task: se requiere objeto.")
    items = []
    for key in ("task_id", "title", "objective", "acceptance"):
        if task.get(key) in (None, ""):
            continue
        value = task[key]
        if isinstance(value, list):
            value = "; ".join(_text(v, "task." + key, 400) for v in value)
        items.append(_item("task", "task." + key, _text(value, "task." + key)))
    return items


def _from_list(kind, raw, builder):
    if not isinstance(raw, list):
        raise ValueError(f"{kind}: se requiere lista.")
    if len(raw) > MAX_ITEMS_PER_SECTION:
        raise ValueError(f"{kind}: máximo {MAX_ITEMS_PER_SECTION} elementos.")
    allowed = _ITEM_KEYS[kind]
    items, seen = [], set()
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"{kind}[{index}]: se requiere objeto.")
        unknown = set(row) - allowed
        if unknown:
            raise ValueError(f"{kind}[{index}]: campos no admitidos: " + ", ".join(sorted(unknown)))
        ident = _text(row.get("id"), f"{kind}[{index}].id", 240)
        if ident in seen:
            raise ValueError(f"{kind}[{index}].id: duplicado.")
        seen.add(ident)
        items.append(builder(kind, ident, row, index))
    return items


def _evidence_item(kind, ident, row, index):
    path = _text(row.get("path"), f"evidence[{index}].path", 500)
    body = _text(row.get("text"), f"evidence[{index}].text")
    return _item(kind, ident, f"{path}\n{body}", {"path": path})


def _skill_item(kind, ident, row, index):
    name = _text(row.get("name"), f"skill[{index}].name", 200)
    version = _text(row.get("version"), f"skill[{index}].version", 40)
    instructions = _text(row.get("instructions"), f"skill[{index}].instructions")
    return _item(kind, ident, f"{name} v{version}\n{instructions}", {"name": name, "version": version})


def _memory_item(kind, ident, row, index):
    mkind = _text(row.get("kind"), f"memory[{index}].kind", 60)
    body = _text(row.get("text"), f"memory[{index}].text")
    return _item(kind, ident, f"[{mkind}] {body}", {"kind": mkind})


def _handoff_item(kind, ident, row, index):
    source = _text(row.get("from"), f"handoff[{index}].from", 120)
    target = _text(row.get("to"), f"handoff[{index}].to", 120)
    summary = _text(row.get("summary"), f"handoff[{index}].summary")
    return _item(kind, ident, f"{source} -> {target}\n{summary}", {"from": source, "to": target})


def _query(request, task):
    parts = [_dump(task)]
    if request.get("objective"):
        parts.append(_text(request["objective"], "objective"))
    if isinstance(request.get("agent"), dict):
        parts.append(_dump(request["agent"]))
    return _terms(" ".join(parts))


def compile_context(request):
    """Devuelve un paquete de contexto acotado, determinista y con digest."""
    if not isinstance(request, dict):
        raise ValueError("request: se requiere objeto.")
    unknown = set(request) - _REQUEST_KEYS
    if unknown:
        raise ValueError("request: campos no admitidos: " + ", ".join(sorted(unknown)))

    budget = _bounded_int(request.get("budget_bytes", DEFAULT_BUDGET_BYTES),
                          "budget_bytes", MIN_BUDGET_BYTES, MAX_BUDGET_BYTES)
    task = request.get("task", {})
    query = _query(request, task)

    by_kind = {kind: [] for kind in _TIERS}
    by_kind["mandate"] = _agent_items(request.get("agent"))
    by_kind["task"] = _task_items(task)
    by_kind["evidence"] = _from_list("evidence", request.get("evidence", []), _evidence_item)
    by_kind["skill"] = _from_list("skill", request.get("skill", []), _skill_item)
    by_kind["memory"] = _from_list("memory", request.get("memory", []), _memory_item)
    by_kind["handoff"] = _from_list("handoff", request.get("handoff", []), _handoff_item)

    for kind in _TIERS:
        for row in by_kind[kind]:
            row["relevance"] = 0.0 if kind in _NEVER_DROP else _relevance(query, row["text"])
        if kind not in _NEVER_DROP:
            by_kind[kind].sort(key=lambda row: (-row["relevance"], row["id"]))

    used, omitted, kept = 0, [], {kind: [] for kind in _TIERS}
    for kind in _TIERS:
        for row in by_kind[kind]:
            cost = row["bytes"] + _ITEM_OVERHEAD
            if kind in _NEVER_DROP or used + cost <= budget:
                used += cost
                kept[kind].append(row)
            else:
                omitted.append({"id": row["id"], "kind": kind, "reason": "budget", "bytes": row["bytes"]})

    warnings = []
    if used > budget:
        warnings.append("mandate_exceeds_budget: el mandato solo supera el presupuesto; el resto se omite.")
    if omitted:
        warnings.append("items_omitted_by_budget: " + str(len(omitted)) + " elementos no entraron.")
    if not kept["evidence"]:
        warnings.append("no_evidence: ninguna evidencia entró; el contexto es evidencia-limitado.")

    sections = [{"kind": kind, "items": kept[kind]} for kind in _TIERS if kept[kind]]
    package = {
        "schema_version": SCHEMA_VERSION,
        "agent_id": (request.get("agent") or {}).get("id"),
        "task_id": (task or {}).get("task_id"),
        "sections": sections,
        "budget": {"limit_bytes": budget, "used_bytes": used,
                   "limit_tokens_est": -(-budget // BYTES_PER_TOKEN),
                   "used_tokens_est": -(-used // BYTES_PER_TOKEN),
                   "estimate_method": "UTF-8 bytes / 3, no tokenizer"},
        "omitted": omitted,
        "selection": {"method": "tiered_overlap_not_semantic", "tiers": list(_TIERS),
                      "never_dropped": sorted(_NEVER_DROP)},
        "warnings": warnings,
    }
    package["digest"] = context_digest(package)
    return package


def context_digest(package):
    payload = {key: value for key, value in package.items() if key != "digest"}
    return _digest(payload)


def verify_context(package):
    """Recomputa el digest; devuelve True o lanza con motivo determinista."""
    if not isinstance(package, dict) or "digest" not in package:
        raise ValueError("package: falta digest.")
    if context_digest(package) != package["digest"]:
        raise ValueError("package.digest: no coincide con el contenido; contexto alterado.")
    return True
