"""Cableado publish() -> capability_library -> context_compiler (nivel skill).

Adaptador PURO. No importa la biblioteca ni el compilador: sólo produce las formas
que ambos aceptan, para no acoplar y no ejecutar efectos al importar.

Contratos verificados contra el arbol, no supuestos:
- capability_library.import_items(items, expected_revision, idempotency_key): lista
  blanca de 9 claves {id,kind,name,description,content,tags,role_evidence,tool_needs,
  provenance}; kind in KINDS; provenance OBLIGATORIA {type in SOURCE_TYPES,
  evidence<=32000}; admite url/source_id/retrieved_at/sha256; INMUTABLE.
- context_compiler: por skill exactamente {id,name,version,instructions}.
- improvement_loop: skill sin name y sin provenance.

Identidad determinista: mismo caso -> mismo id -> reimportacion idempotente.
Cambiar instrucciones SIN subir version es un error, no una sobrescritura silenciosa.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = "remediation-wiring-1.0"
LIBRARY_KIND = "skill_instructions"
PROVENANCE_TYPE = "user_authored"
MAX_NAME = 256
MAX_DESCRIPTION = 2_048
MAX_EVIDENCE = 32_000
MAX_CONTENT = 120_000          # margen bajo MAX_ITEM_BYTES (128 KB) del cuerpo completo
MAX_TAG = 512


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _loop():
    try:
        from . import improvement_loop
    except ImportError:
        import improvement_loop
    return improvement_loop


def _require_published(case):
    """Integridad primero: un caso alterado no se cablea."""
    loop = _loop()
    if not isinstance(case, dict):
        raise ValueError("case: se requiere objeto.")
    loop.verify_case(case)
    if case.get("state") != "PUBLISHED_VERSION":
        raise ValueError("case.state: se requiere PUBLISHED_VERSION; es " + str(case.get("state")) + ".")
    skill = case.get("skill")
    if not isinstance(skill, dict):
        raise ValueError("case.skill: ausente en un caso publicado.")
    if skill.get("preserved_failure_id") != case.get("failure_id"):
        raise ValueError("case.skill.preserved_failure_id: no coincide con el caso.")
    return skill


def _texts(values, field):
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field}: se requiere lista.")
    out = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field}: se requieren textos no vacíos.")
        if len(value.encode("utf-8")) > MAX_TAG:
            raise ValueError(f"{field}: elemento supera {MAX_TAG} bytes.")
        out.append(value)
    return list(dict.fromkeys(out))


def item_id(case):
    """Identidad inmutable por (failure_id, skill_id, version). Version nueva -> id nuevo."""
    skill = _require_published(case)
    return "skill." + _digest({"failure_id": case["failure_id"],
                               "skill_id": skill["skill_id"],
                               "version": skill["version"]})[:40]


def skill_name(case):
    skill = _require_published(case)
    return (skill["skill_id"] + " v" + skill["version"])[:MAX_NAME]


def library_item(case, tags=(), tool_needs=()):
    """Elemento listo para capability_library.import_items. Provenance derivada del caso."""
    skill = _require_published(case)
    content = _dump({"instructions": skill["instructions"], "diff": skill["diff"],
                     "regression": skill["regression"], "limits": skill["limits"],
                     "rollback": skill["rollback"]})
    if len(content.encode("utf-8")) > MAX_CONTENT:
        raise ValueError("content: el skill publicado supera el limite de un elemento de biblioteca.")
    evidence = _dump({"root_cause": case["root_cause"], "attribution": case["attribution"],
                      "expected": case["expected"], "observed": case["observed"],
                      "evidence_paths": list(case["evidence_paths"]),
                      "candidate_sha": case["candidate_sha"],
                      "supervisor_id": case["supervisor_id"],
                      "independent_reviewer_id": case["independent_reviewer_id"],
                      "published_digest": case.get("published_digest")})
    if len(evidence.encode("utf-8")) > MAX_EVIDENCE:
        raise ValueError("provenance.evidence: supera 32000 bytes; recortar evidencia, no el digest.")
    item = {
        "id": item_id(case),
        "kind": LIBRARY_KIND,
        "name": skill_name(case),
        "description": case["root_cause"][:MAX_DESCRIPTION],
        "content": content,
        "tags": _texts(list(tags) + [skill["skill_id"], "v" + skill["version"], case["attribution"]], "tags"),
        "role_evidence": _texts(list(case["evidence_paths"]), "role_evidence"),
        "tool_needs": _texts(list(tool_needs), "tool_needs"),
        "provenance": {"type": PROVENANCE_TYPE, "evidence": evidence,
                       "sha256": case.get("published_digest")},
    }
    if len(_dump(item).encode("utf-8")) > 128 * 1024:
        raise ValueError("item: supera MAX_ITEM_BYTES de la biblioteca.")
    return item


def replay_key(case, expected_revision):
    """Clave de solicitud CONSISTENTE con la revision que se va a declarar.

    Una clave estable por (failure_id, version) con una revision leida EN VIVO es
    una contradiccion: capability_library._cached compara la clave contra el
    request completo, que incluye 'expected_revision'. Tras el primer import la
    revision cambia, asi que el reintento del MISMO caso construye otro request con
    la MISMA clave y lanza 'Clave idempotente reutilizada para otra solicitud' --
    justo en el escenario para el que existe la idempotencia.

    La idempotencia REAL la da item_id(), que es determinista por
    (failure_id, skill_id, version): reimportar el mismo caso no duplica el
    elemento. Esta clave protege la solicitud, y por eso incluye la revision.
    """
    if type(expected_revision) is not int:
        raise ValueError("expected_revision: se requiere entero.")
    skill = _require_published(case)
    return "remediation:%s:%s:r%d" % (case["failure_id"], skill["version"], expected_revision)


def import_plan(case, expected_revision, idempotency_key=None, tags=(), tool_needs=()):
    """Argumentos exactos para capability_library.import_items(**plan).

    Si no se aporta idempotency_key se usa replay_key(), que es la forma correcta.
    Aportar una clave estable junto a una revision viva reproduce el error de
    'Clave idempotente reutilizada'.
    """
    if type(expected_revision) is not int:
        raise ValueError("expected_revision: se requiere entero.")
    key = idempotency_key if idempotency_key is not None else replay_key(case, expected_revision)
    if not isinstance(key, str) or not key.strip():
        raise ValueError("idempotency_key: se requiere texto.")
    return {"items": [library_item(case, tags, tool_needs)],
            "expected_revision": expected_revision, "idempotency_key": key}


def context_skill(case):
    """Elemento exacto del nivel skill de context_compiler."""
    skill = _require_published(case)
    return {"id": item_id(case), "name": skill_name(case),
            "version": skill["version"], "instructions": skill["instructions"]}


def add_skill_to_request(case, request, extra_skills=()):
    """Inyecta la skill en el nivel skill de un request de context_compiler, sin duplicar ids."""
    if not isinstance(request, dict):
        raise ValueError("request: se requiere objeto.")
    seen = {}
    for row in list(request.get("skill", [])) + list(extra_skills) + [context_skill(case)]:
        if not isinstance(row, dict) or "id" not in row:
            raise ValueError("skill: cada elemento requiere id.")
        if row["id"] in seen and seen[row["id"]] != row:
            raise ValueError("skill: id duplicado con contenido distinto: " + row["id"])
        seen[row["id"]] = row
    return dict(request, skill=[seen[key] for key in seen])
