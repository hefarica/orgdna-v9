"""Contrato de instrucción: el LLM hace EXACTAMENTE lo indicado. Ni quita, ni pone, ni suaviza.

El LLM es OBLIGATORIO: se le llama siempre. Pero su salida se contrasta contra un
contrato construido de TUS palabras (playbook + dossier), no de la salida del modelo.
Tres faltas, con tus tres verbos:
  dropped  -> quito algo declarado
  added    -> puso algo no declarado
  softened -> cambio un valor fijado (numero, codigo, palabra obligatoria)
reconcile repara SOLO con reglas declaradas y reporta cada reparacion; lo irreparable
se rechaza. retry_prompt devuelve la correccion literal que se le indica al modelo.
Puro y determinista. No llama al proveedor.
"""
from __future__ import annotations

import hashlib
import json

SCHEMA_VERSION = "instruction-contract-1.0"
MAX_PROSE_BYTES_DEFAULT = 1_200
MAX_PROSE_BYTES_LIMIT = 8_000
_SPEC_KEYS = frozenset(("required_ids", "pinned", "prose", "must_mention", "order",
                        "max_prose_bytes", "defaults"))


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_dump(value).encode("utf-8")).hexdigest()


def _same(left, right):
    return type(left) is type(right) and left == right


def _blank(value):
    return not isinstance(value, str) or not value.strip()


def build_contract(spec):
    if not isinstance(spec, dict):
        raise ValueError("spec: se requiere objeto.")
    unknown = set(spec) - _SPEC_KEYS
    if unknown:
        raise ValueError("spec: campos no admitidos: " + ", ".join(sorted(unknown)))
    required = list(spec.get("required_ids", []))
    if not required or len(set(required)) != len(required) or any(not isinstance(i, str) or not i.strip() for i in required):
        raise ValueError("required_ids: lista no vacía, sin duplicados, de textos.")
    pinned = {k: dict(v) for k, v in (spec.get("pinned") or {}).items()}
    prose = {k: list(v) for k, v in (spec.get("prose") or {}).items()}
    mention = {k: list(v) for k, v in (spec.get("must_mention") or {}).items()}
    defaults = {k: dict(v) for k, v in (spec.get("defaults") or {}).items()}
    for ident in set(pinned) | set(prose) | set(mention) | set(defaults):
        if ident not in required:
            raise ValueError("contrato: id no declarado en required_ids: " + ident)
    for ident in required:
        slots = set(pinned.get(ident, {})) | set(prose.get(ident, []))
        if not slots:
            raise ValueError("contrato: " + ident + " sin campos declarados.")
        if set(pinned.get(ident, {})) & set(prose.get(ident, [])):
            raise ValueError("contrato: " + ident + " con campo en pinned y prose a la vez.")
    order = list(spec.get("order") or required)
    if sorted(order) != sorted(required):
        raise ValueError("order: debe contener exactamente required_ids.")
    maximum = spec.get("max_prose_bytes", MAX_PROSE_BYTES_DEFAULT)
    if type(maximum) is not int or not 1 <= maximum <= MAX_PROSE_BYTES_LIMIT:
        raise ValueError("max_prose_bytes fuera de rango.")
    contract = {"schema_version": SCHEMA_VERSION, "required_ids": required, "order": order,
                "pinned": pinned, "prose": prose, "must_mention": mention,
                "defaults": defaults, "max_prose_bytes": maximum}
    contract["digest"] = contract_digest(contract)
    return contract


def contract_digest(contract):
    return _digest({k: v for k, v in contract.items() if k != "digest"})


def verify_contract(contract):
    if not isinstance(contract, dict) or "digest" not in contract:
        raise ValueError("contract: falta digest.")
    if contract_digest(contract) != contract["digest"]:
        raise ValueError("contract.digest: no coincide; contrato alterado.")
    return True


def check(response, contract):
    """Contrasta la salida del modelo. Devuelve las faltas; no repara nada."""
    verify_contract(contract)
    if not isinstance(response, dict):
        raise ValueError("response: se requiere objeto.")
    dropped, added, softened = [], [], []
    for ident in response:
        if ident not in contract["required_ids"]:
            added.append({"id": ident, "field": None, "reason": "id no declarado"})
    for ident in contract["required_ids"]:
        if ident not in response:
            dropped.append({"id": ident, "field": None, "reason": "id ausente"})
            continue
        row = response[ident]
        if not isinstance(row, dict):
            raise ValueError("response." + ident + ": se requiere objeto.")
        declared = set(contract["pinned"].get(ident, {})) | set(contract["prose"].get(ident, []))
        for field in row:
            if field not in declared:
                added.append({"id": ident, "field": field, "reason": "campo no declarado"})
        for field in declared:
            if field not in row:
                dropped.append({"id": ident, "field": field, "reason": "campo declarado ausente"})
        for field, value in contract["pinned"].get(ident, {}).items():
            if field in row and not _same(row[field], value):
                softened.append({"id": ident, "field": field, "expected": value, "got": row[field]})
        for field in contract["prose"].get(ident, []):
            if field not in row:
                continue
            text = row[field]
            if _blank(text):
                dropped.append({"id": ident, "field": field, "reason": "prosa vacía"})
                continue
            if len(text.encode("utf-8")) > contract["max_prose_bytes"]:
                added.append({"id": ident, "field": field, "reason": "prosa supera el límite"})
            haystack = text.casefold()
            for term in contract["must_mention"].get(ident, []):
                if term.casefold() not in haystack:
                    softened.append({"id": ident, "field": field, "expected_term": term, "got": None})
    present = [i for i in response if i in contract["required_ids"]]
    expected_order = [i for i in contract["order"] if i in response]
    reordered = [] if present == expected_order else [{"expected": expected_order, "got": present}]
    return {"schema_version": SCHEMA_VERSION,
            "clean": not (dropped or added or softened or reordered),
            "dropped": dropped, "added": added, "softened": softened, "reordered": reordered,
            "counts": {"dropped": len(dropped), "added": len(added),
                       "softened": len(softened), "reordered": len(reordered)}}


def _ordered(response, contract):
    return {ident: response[ident] for ident in contract["order"] if ident in response}


def reconcile(response, contract):
    """Repara SOLO lo que una regla declarada permite. Devuelve (salida, reparaciones); lo demás lanza."""
    report = check(response, contract)
    if report["clean"]:
        return _ordered(response, contract), []
    result = {ident: dict(row) for ident, row in response.items() if ident in contract["required_ids"]}
    repairs = []
    for item in report["added"]:
        ident, field = item["id"], item["field"]
        if field is None:
            continue  # id añadido: fuera (el contrato manda)
        result[ident].pop(field, None)
        repairs.append({"code": "removed_added", "id": ident, "field": field})
    for item in report["dropped"]:
        ident, field = item["id"], item["field"]
        if field is None:
            raise ValueError("reconcile: id declarado ausente, no se inventa: " + ident)
        default = contract["defaults"].get(ident, {})
        if field not in default:
            raise ValueError("reconcile: campo ausente sin default: " + ident + "." + field)
        result[ident][field] = default[field]
        repairs.append({"code": "filled_default", "id": ident, "field": field})
    for item in report["softened"]:
        ident, field = item["id"], item["field"]
        if "expected_term" in item:
            raise ValueError("reconcile: falta palabra obligatoria en prosa: " + ident + "." + field
                             + " -> " + str(item["expected_term"]))
        expected, got = item["expected"], item["got"]
        if isinstance(expected, str) and isinstance(got, str) and expected.strip().casefold() == got.strip().casefold():
            result[ident][field] = expected
            repairs.append({"code": "restored_case", "id": ident, "field": field})
        elif (isinstance(expected, (int, float)) and not isinstance(expected, bool)
              and not isinstance(got, bool) and isinstance(got, (int, float, str))):
            # `got` puede llegar como NUMERO JSON (2) y no como texto ("2"): el modelo
            # devuelve 2 donde el contrato fija 2.0. Numericamente es el mismo valor, asi
            # que se restaura el tipo fijado en vez de declararlo irreparable. Un numero
            # realmente distinto (2.5) sigue siendo irreparable.
            try:
                equal = float(got) == float(expected)
            except (TypeError, ValueError):
                raise ValueError("reconcile: numero no comparable: " + ident + "." + field) from None
            if not equal:
                raise ValueError("reconcile: numero distinto e irreparable: " + ident + "." + field)
            result[ident][field] = expected
            repairs.append({"code": "restored_number", "id": ident, "field": field})
        else:
            raise ValueError("reconcile: valor fijado distinto e irreparable: " + ident + "." + field)
    return _ordered(result, contract), repairs


def retry_prompt(contract, report):
    """La corrección literal que se le indica al modelo. Nada más."""
    if report.get("clean"):
        return None
    lines = ["Corrige EXACTAMENTE esto y nada más. No quites, no añadas, no suavices."]
    for item in report["dropped"]:
        lines.append("FALTA " + item["id"] + ("." + item["field"] if item["field"] else " (id completo)"))
    for item in report["added"]:
        lines.append("SOBRA " + item["id"] + ("." + item["field"] if item["field"] else " (id no declarado)"))
    for item in report["softened"]:
        if "expected_term" in item:
            lines.append("FALTA en prosa " + item["id"] + "." + item["field"] + " la palabra: " + item["expected_term"])
        else:
            lines.append("VALOR FIJADO " + item["id"] + "." + item["field"] + " debe ser "
                         + _dump(item["expected"]) + " no " + _dump(item["got"]))
    for item in report["reordered"]:
        lines.append("ORDEN requerido: " + ", ".join(item["expected"]))
    return "\n".join(lines)


def contract_from_playbook(playbook):
    """El contrato nace del playbook (tus palabras), no del modelo."""
    codes = [role["code"] for role in playbook["roles"]]
    pinned = {code: {"tool_needs": list(playbook["tool_needs"]),
                     "max_odds": float(playbook["market"]["max_odds"]),
                     "max_loss_per_losing_bet_usd": float(playbook["risk"]["max_loss_per_losing_bet_usd"])}
              for code in codes}
    return build_contract({"required_ids": codes, "order": codes, "pinned": pinned,
                           "prose": {code: ["mission"] for code in codes},
                           "defaults": {code: {"mission": "sin misión declarada"} for code in codes}})
