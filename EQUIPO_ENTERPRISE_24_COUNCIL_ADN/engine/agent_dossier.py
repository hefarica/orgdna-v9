"""Dossier local: de tus palabras a contexto organizado y relacionado.

Determinista y puro. Fuente = texto local; nada sale al mundo. Normaliza, deduplica
y RELACIONA por co-ocurrencia, y emite en las formas exactas de context_compiler
(mandate/memory). El LLM es opcional: si se le llama, sólo PROPONE entradas; la
organizacion la hace build_dossier, no el modelo.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA_VERSION = "agent-dossier-1.0"
FACETS = ("laboral", "profesional", "personal", "objetivo")
MAX_ENTRIES = 200
MAX_ENTRY_BYTES = 8_000
MAX_CONTEXT_ITEMS = 64          # tope del nivel memory de context_compiler
MAX_AUX_ITEMS = 2               # "relaciones" + "omitidos": los añade to_context_items
MAX_ENTRIES_IN_CONTEXT = MAX_CONTEXT_ITEMS - MAX_AUX_ITEMS
MIN_SHARED_FOR_RELATION = 2
MAX_RELATIONS = 200
MAX_TERMS = 4_000
_ENTRY_KEYS = frozenset(("id", "facet", "text"))
_TOKEN = re.compile(r"[0-9a-z_]{3,}")
_STOPWORDS = frozenset((
    "the", "and", "for", "with", "from", "that", "this", "into", "are", "was", "were",
    "will", "not", "but", "its", "our", "their", "all", "any", "can", "los", "las",
    "del", "que", "con", "por", "para", "una", "unos", "unas", "como", "sobre", "entre",
    "desde", "hasta", "este", "esta", "estos", "estas", "sus", "mas", "sin", "son",
    "sea", "ser", "hay", "muy", "cada",
))


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _text(value, field, maximum=MAX_ENTRY_BYTES):
    if not isinstance(value, str):
        raise ValueError(f"{field}: se requiere texto.")
    value = " ".join(value.split())
    if not value:
        raise ValueError(f"{field}: texto vacío.")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{field}: supera {maximum} bytes UTF-8.")
    return value


def _terms(text):
    return list(dict.fromkeys(t for t in _TOKEN.findall(text.casefold()) if t not in _STOPWORDS))


def build_dossier(entries):
    """Organiza tus palabras. Cada entrada es {facet, text, id?}. Relaciona por co-ocurrencia."""
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ENTRIES:
        raise ValueError(f"entries: lista de 1..{MAX_ENTRIES} elementos.")
    clean, seen, index = [], set(), {}
    for position, row in enumerate(entries):
        if not isinstance(row, dict):
            raise ValueError(f"entries[{position}]: se requiere objeto.")
        unknown = set(row) - _ENTRY_KEYS
        if unknown:
            raise ValueError(f"entries[{position}]: campos no admitidos: " + ", ".join(sorted(unknown)))
        if row.get("facet") not in FACETS:
            raise ValueError(f"entries[{position}].facet: se requiere uno de {', '.join(FACETS)}.")
        ident = _text(row.get("id", f"d{position:03d}"), f"entries[{position}].id", 80)
        if ident in seen:
            raise ValueError(f"entries[{position}].id: duplicado.")
        seen.add(ident)
        body = _text(row.get("text"), f"entries[{position}].text")
        terms = _terms(body)
        clean.append({"id": ident, "facet": row["facet"], "text": body, "terms": terms})
        for term in terms:
            index.setdefault(term, []).append(ident)
    relations = []
    for left in range(len(clean)):
        for right in range(left + 1, len(clean)):
            shared = sorted(set(clean[left]["terms"]) & set(clean[right]["terms"]))
            if len(shared) >= MIN_SHARED_FOR_RELATION:
                relations.append({"a": clean[left]["id"], "b": clean[right]["id"],
                                  "shared": shared[:20], "weight": len(shared)})
    relations.sort(key=lambda r: (-r["weight"], r["a"], r["b"]))
    dossier = {"schema_version": SCHEMA_VERSION, "entries": clean,
               "terms": dict(sorted(index.items())[:MAX_TERMS]), "relations": relations[:MAX_RELATIONS],
               "counts": {"entries": len(clean), "terms": len(index), "relations": len(relations)}}
    dossier["digest"] = dossier_digest(dossier)
    return dossier


def dossier_digest(dossier):
    return _digest({key: value for key, value in dossier.items() if key != "digest"})


def verify_dossier(dossier):
    if not isinstance(dossier, dict) or "digest" not in dossier:
        raise ValueError("dossier: falta digest.")
    if dossier_digest(dossier) != dossier["digest"]:
        raise ValueError("dossier.digest: no coincide; dossier alterado.")
    return True


def to_context_items(dossier, limit=MAX_ENTRIES_IN_CONTEXT):
    """Emite mandate + memory (formas exactas de context_compiler). Elige por relación, no al azar.

    `limit` cuenta ENTRADAS, y está acotado a MAX_ENTRIES_IN_CONTEXT y no a
    MAX_CONTEXT_ITEMS: to_context_items añade hasta dos elementos propios
    ("dossier.relaciones" y "dossier.omitidos"), de modo que un límite de 64
    producía 66 elementos de memoria y context_compiler los RECHAZABA
    ("memory: máximo 64 elementos"). El valor por defecto tiene que poder
    alimentar al consumidor sin que el llamante tenga que saber este detalle.
    """
    verify_dossier(dossier)
    if not 1 <= limit <= MAX_ENTRIES_IN_CONTEXT:
        raise ValueError(f"limit: 1..{MAX_ENTRIES_IN_CONTEXT} entradas "
                         f"(el tope de memoria es {MAX_CONTEXT_ITEMS} y {MAX_AUX_ITEMS} son propios).")
    entries = dossier["entries"]
    omitted = 0
    if len(entries) > limit:
        degree = {entry["id"]: 0 for entry in entries}
        for relation in dossier["relations"]:
            degree[relation["a"]] += relation["weight"]
            degree[relation["b"]] += relation["weight"]
        entries = sorted(entries, key=lambda e: (-degree[e["id"]], e["id"]))[:limit]
        omitted = len(dossier["entries"]) - limit
    memory = [{"id": "dossier." + entry["id"], "kind": "dossier_" + entry["facet"],
               "text": "[" + entry["facet"] + "] " + entry["text"]} for entry in entries]
    if dossier["relations"]:
        lines = [r["a"] + " <-> " + r["b"] + " (" + ",".join(r["shared"]) + ")" for r in dossier["relations"][:40]]
        memory.append({"id": "dossier.relaciones", "kind": "dossier_relaciones", "text": "\n".join(lines)})
    if omitted:
        memory.append({"id": "dossier.omitidos", "kind": "dossier_omitidos",
                       "text": f"{omitted} entradas fuera del tope de {limit}; subir presupuesto o dividir el dossier."})
    return {"mandate": {"mission": "Contexto personal y profesional del usuario, organizado y relacionado localmente.",
                        "personality": "Usa el dossier propio; no lo inventa ni lo amplía sin evidencia."},
            "memory": memory}
