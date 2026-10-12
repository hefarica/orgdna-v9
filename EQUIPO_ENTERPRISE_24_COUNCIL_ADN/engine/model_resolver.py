"""Resuelve el nombre visible de un modelo a su ID exacto de API, sin adivinar.

`bridge.py:905-906` prohibe reinterpretar un alias **en silencio**. Este modulo no
rompe esa regla: solo acepta una correspondencia cuando la forma normalizada del
candidato es **exactamente igual** a la de la cadena escrita. No hay coincidencia
parcial, ni subcadena, ni puntuacion de parecido, ni eleccion entre varios. Por
construccion NO puede mapear un modelo a otro distinto.

Normalizar = casefold + quedarse con lo alfanumerico. Por eso
`DeepSeek-V41-Flash` coincide con el nombre `DeepSeek-V4.1-Flash`: es la MISMA
notacion escrita de otra forma, no otro modelo. El punto, el guion y el espacio no
son identidad.

Determinista, sin red, sin estado mutable, sin efectos al importar.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA_VERSION = "model-resolver-1.0"
MAX_TEXT = 200
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def normalize(value):
    """Forma canonica: casefold y solo alfanumericos. Vacia si no queda nada."""
    if not isinstance(value, str):
        return ""
    return _NON_ALNUM.sub("", value.casefold())[:MAX_TEXT]


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}: se requiere texto.")
    if len(value.encode("utf-8")) > MAX_TEXT:
        raise ValueError(f"{field}: supera {MAX_TEXT} bytes.")
    return value.strip()


def _row_id(row):
    return str(row.get("id") or row.get("model") or "")


def _candidate(row, matched_on):
    out = {"id": _row_id(row), "matched_on": matched_on}
    if isinstance(row.get("name"), str) and row["name"]:
        out["name"] = row["name"]
    if isinstance(row.get("source"), str):
        out["source"] = row["source"]
    if row.get("available") is not None:
        out["available"] = row["available"]
    return out


def resolve(requested, rows):
    """Resuelve `requested` contra las filas de UN proveedor ya filtradas.

    Devuelve dict con status:
      exact      la cadena ya es un ID de la lista (misma cadena o misma notacion)
      resolved   coincide EXACTAMENTE con el nombre visible de UN solo candidato
      ambiguous  coincide con varios: NO se elige, se listan
      unknown    no coincide con nada: NO se inventa
    """
    requested = _text(requested, "requested")
    if not isinstance(rows, list):
        raise ValueError("rows: se requiere lista.")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"rows[{index}]: se requiere objeto.")
        if not _row_id(row):
            raise ValueError(f"rows[{index}]: sin id ni model.")

    wanted = normalize(requested)
    if not wanted:
        return {"schema_version": SCHEMA_VERSION, "status": "unknown", "requested": requested,
                "model_id": None, "matched_on": None, "candidates": [],
                "reason": "la cadena no contiene ningun caracter alfanumerico utilizable"}

    # 1) Identificador: comparacion por forma canonica, que cubre la misma notacion.
    by_id = [row for row in rows if normalize(_row_id(row)) == wanted]
    if len(by_id) == 1:
        row = by_id[0]
        literal = _row_id(row) == requested
        return {"schema_version": SCHEMA_VERSION,
                "status": "exact" if literal else "resolved",
                "requested": requested, "model_id": _row_id(row), "matched_on": "id",
                "candidates": [_candidate(row, "id")],
                "reason": ("el ID coincide literalmente" if literal else
                           "misma forma canonica que el ID %r" % _row_id(row))}
    if len(by_id) > 1:
        return {"schema_version": SCHEMA_VERSION, "status": "ambiguous", "requested": requested,
                "model_id": None, "matched_on": "id",
                "candidates": [_candidate(row, "id") for row in by_id],
                "reason": "varias filas comparten esa forma canonica de ID"}

    # 2) Nombre visible: solo igualdad canonica EXACTA con UN candidato.
    by_name = [row for row in rows
               if isinstance(row.get("name"), str) and normalize(row["name"]) == wanted]
    if len(by_name) == 1:
        row = by_name[0]
        return {"schema_version": SCHEMA_VERSION, "status": "resolved",
                "requested": requested, "model_id": _row_id(row), "matched_on": "name",
                "candidates": [_candidate(row, "name")],
                "reason": "el nombre visible %r corresponde exactamente a esa forma canonica"
                          % row["name"]}
    if len(by_name) > 1:
        return {"schema_version": SCHEMA_VERSION, "status": "ambiguous", "requested": requested,
                "model_id": None, "matched_on": "name",
                "candidates": [_candidate(row, "name") for row in by_name],
                "reason": "varios nombres visibles comparten esa forma canonica: no se elige"}

    return {"schema_version": SCHEMA_VERSION, "status": "unknown", "requested": requested,
            "model_id": None, "matched_on": None, "candidates": [],
            "reason": "ninguna fila de ese proveedor coincide, ni por ID ni por nombre visible"}


def digest(resolution):
    return hashlib.sha256(_dump(resolution).encode("utf-8")).hexdigest()


def describe(resolution):
    """Linea corta y accionable para el operador. Nunca afirma disponibilidad."""
    status = resolution.get("status")
    if status == "exact":
        return "El ID %s es exacto." % resolution["model_id"]
    if status == "resolved":
        found = resolution["candidates"][0]
        return ("%r es el nombre visible de %s (ID de API %s). Misma forma canonica, "
                "asi que es el mismo modelo escrito de otra forma."
                % (resolution["requested"], found.get("name"), resolution["model_id"]))
    if status == "ambiguous":
        ids = ", ".join(str(row.get("id")) for row in resolution["candidates"])
        return ("%r coincide con varios modelos (%s): elige el ID exacto a mano; "
                "el sistema no elige por ti." % (resolution["requested"], ids))
    return ("%r no corresponde a ningun ID ni nombre visible de ese proveedor. "
            "No se inventa ninguna coincidencia." % resolution["requested"])
