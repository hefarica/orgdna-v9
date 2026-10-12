"""Ejecutor de la máquina de estados de remediación.

Un fallo DEMOSTRADO se convierte en una skill versionada, verificada por un revisor
independiente y publicada. Funciones puras sobre un dict de caso inmutable: sin
estado mutable compartido, sin tocar pesos, sin conceder permisos.

Estados (orden fijo):
  FAIL_OBSERVED -> ROOT_CAUSE_REVIEWED -> SKILL_DRAFTED -> SUPERVISOR_APPROVED
  -> RETEST_PASS -> INDEPENDENT_APPROVED -> PUBLISHED_VERSION
Un retest fallido devuelve el caso a SKILL_DRAFTED (intentos acotados).

No instala, no ejecuta, no entrena. La recompensa y la propagación son del llamador.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

SCHEMA_VERSION = "improvement-loop-1.0"
MAX_ATTEMPTS = 9
SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")

_STATES = (
    "FAIL_OBSERVED", "ROOT_CAUSE_REVIEWED", "SKILL_DRAFTED",
    "SUPERVISOR_APPROVED", "RETEST_PASS", "INDEPENDENT_APPROVED",
    "PUBLISHED_VERSION",
)
_ATTRIBUTIONS = frozenset(("product", "data", "environment", "skill"))
_REQUIRED_AT_PUBLISH = (
    "failure_id", "test_id", "candidate_sha", "environment", "expected",
    "observed", "evidence_paths", "root_cause", "skill", "retest_result",
    "supervisor_id", "independent_reviewer_id",
)
_SKILL_KEYS = frozenset(("skill_id", "version", "instructions", "diff", "regression", "limits", "rollback"))


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _text(value, field, maximum=4_000):
    if not isinstance(value, str):
        raise ValueError(f"{field}: se requiere texto.")
    value = value.strip()
    if not value:
        raise ValueError(f"{field}: texto vacío.")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{field}: supera {maximum} bytes UTF-8.")
    return value


def _ident(value, field):
    value = _text(value, field, 160)
    if not ID_RE.match(value):
        raise ValueError(f"{field}: identificador inválido.")
    return value


def _sha(value, field):
    value = _text(value, field, 64)
    if not SHA_RE.match(value):
        raise ValueError(f"{field}: se requiere SHA de 40 o 64 hexadecimales.")
    return value


def _strings(value, field, minimum=1, maximum=32):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field}: se requieren {minimum}..{maximum} elementos.")
    rows = [_text(item, f"{field}[{i}]", 500) for i, item in enumerate(value)]
    if len(set(rows)) != len(rows):
        raise ValueError(f"{field}: valores duplicados.")
    return rows


def _require_state(case, expected):
    state = case.get("state")
    if state not in expected:
        raise ValueError(f"case.state: se esperaba {' o '.join(expected)}; es {state}.")
    return case


def _advance(case, target):
    result = copy.deepcopy(case)
    result["state"] = target
    result["history"] = tuple(result.get("history", ())) + (target,)
    return result


def case_digest(case):
    """Digest sobre el CONTENIDO del caso, excluyendo su propio digest.

    Excluirlo es lo que hace el digest verificable. Si se plegara el digest
    anterior dentro del nuevo, nadie podria recomputarlo sin la cadena entera y
    el caso quedaria sin integridad comprobable. Misma regla que
    context_compiler.context_digest.
    """
    return _digest({key: value for key, value in case.items() if key != "digest"})


def verify_case(case):
    if not isinstance(case, dict):
        raise ValueError("case: se requiere objeto.")
    if case.get("state") not in _STATES:
        raise ValueError("case.state: desconocido.")
    if tuple(case.get("history", ())) and case["history"][-1] != case["state"]:
        raise ValueError("case.history: no termina en el estado actual.")
    if "digest" not in case:
        raise ValueError("case: falta digest.")
    if case_digest(case) != case["digest"]:
        raise ValueError("case.digest: no coincide con el contenido; caso alterado.")
    return True


def open_case(record):
    """Abre un fallo DEMOSTRADO. Sin test_id, SHA, esperado y observado no hay caso."""
    if not isinstance(record, dict):
        raise ValueError("record: se requiere objeto.")
    case = {
        "schema_version": SCHEMA_VERSION,
        "failure_id": _ident(record.get("failure_id"), "failure_id"),
        "test_id": _ident(record.get("test_id"), "test_id"),
        "author_id": _ident(record.get("author_id"), "author_id"),
        "candidate_sha": _sha(record.get("candidate_sha"), "candidate_sha"),
        "environment": _text(record.get("environment"), "environment", 500),
        "expected": _text(record.get("expected"), "expected"),
        "observed": _text(record.get("observed"), "observed"),
        "evidence_paths": _strings(record.get("evidence_paths"), "evidence_paths"),
        "reproduction": _text(record.get("reproduction", "no declarada"), "reproduction"),
        "state": "FAIL_OBSERVED",
        "history": ("FAIL_OBSERVED",),
        "attempts": 0,
        "root_cause": None,
        "attribution": None,
        "skill": None,
        "supervisor_id": None,
        "independent_reviewer_id": None,
        "retest_result": None,
        "permissions_expanded": False,
        "published_digest": None,
    }
    case["digest"] = case_digest(case)
    return case


def review_root_cause(case, root_cause, attribution):
    """Causa RAÍZ antes de tocar skill. Atribución separada de producto/datos/entorno/skill."""
    _require_state(case, ("FAIL_OBSERVED",))
    if attribution not in _ATTRIBUTIONS:
        raise ValueError("attribution: se requiere product, data, environment o skill.")
    result = _advance(case, "ROOT_CAUSE_REVIEWED")
    result["root_cause"] = _text(root_cause, "root_cause")
    result["attribution"] = attribution
    result["digest"] = case_digest(result)
    return result


def draft_skill(case, skill):
    """Borra la skill. Conserva caso fallido, regresión, límites, hash y rollback."""
    _require_state(case, ("ROOT_CAUSE_REVIEWED", "SKILL_DRAFTED"))
    if not isinstance(skill, dict):
        raise ValueError("skill: se requiere objeto.")
    unknown = set(skill) - _SKILL_KEYS
    if unknown:
        raise ValueError("skill: campos no admitidos: " + ", ".join(sorted(unknown)))
    missing = _SKILL_KEYS - set(skill)
    if missing:
        raise ValueError("skill: faltan campos: " + ", ".join(sorted(missing)))
    result = _advance(case, "SKILL_DRAFTED")
    result["attempts"] = case["attempts"] + 1
    if result["attempts"] > MAX_ATTEMPTS:
        raise ValueError(f"case.attempts: supera {MAX_ATTEMPTS} borradores.")
    result["skill"] = {
        "skill_id": _ident(skill["skill_id"], "skill.skill_id"),
        "version": _text(skill["version"], "skill.version", 40),
        "instructions": _text(skill["instructions"], "skill.instructions", 50_000),
        "diff": _text(skill["diff"], "skill.diff", 20_000),
        "regression": _text(skill["regression"], "skill.regression", 500),
        "limits": _text(skill["limits"], "skill.limits", 2_000),
        "rollback": _text(skill["rollback"], "skill.rollback", 500),
        "preserved_failure_id": case["failure_id"],
    }
    result["digest"] = case_digest(result)
    return result


def approve_supervisor(case, supervisor_id):
    _require_state(case, ("SKILL_DRAFTED",))
    result = _advance(case, "SUPERVISOR_APPROVED")
    result["supervisor_id"] = _ident(supervisor_id, "supervisor_id")
    result["digest"] = case_digest(result)
    return result


def record_retest(case, result_text, passed, evidence):
    """Retest del fallo original. Si falla, vuelve a SKILL_DRAFTED sin publicar."""
    _require_state(case, ("SUPERVISOR_APPROVED",))
    evidence = _strings(evidence, "evidence")
    if passed:
        result = _advance(case, "RETEST_PASS")
    else:
        result = _advance(case, "SKILL_DRAFTED")
    result["retest_result"] = {"text": _text(result_text, "retest_result"), "passed": bool(passed), "evidence": evidence}
    result["digest"] = case_digest(result)
    return result


def approve_independent(case, reviewer_id):
    """Revisor independiente DISTINTO del autor. Firma eficacia, no coautoría."""
    _require_state(case, ("RETEST_PASS",))
    reviewer_id = _ident(reviewer_id, "independent_reviewer_id")
    if reviewer_id == case["author_id"]:
        raise ValueError("independent_reviewer_id: no puede ser el autor.")
    result = _advance(case, "INDEPENDENT_APPROVED")
    result["independent_reviewer_id"] = reviewer_id
    result["digest"] = case_digest(result)
    return result


def publish(case, permissions_expanded=False, permissions_note=None):
    """Publica la versión. Exige evidencia completa y no ampliar permisos en silencio."""
    _require_state(case, ("INDEPENDENT_APPROVED",))
    missing = [key for key in _REQUIRED_AT_PUBLISH if case.get(key) in (None, "", [])]
    if missing:
        raise ValueError("case: evidencia incompleta para publicar: " + ", ".join(missing))
    if permissions_expanded and not permissions_note:
        raise ValueError("permissions_note: obligatoria si permissions_expanded es True.")
    result = _advance(case, "PUBLISHED_VERSION")
    result["permissions_expanded"] = bool(permissions_expanded)
    if permissions_note:
        result["permissions_note"] = _text(permissions_note, "permissions_note", 1_000)
    result["published_digest"] = case_digest(result)
    result["digest"] = case_digest(result)
    return result
