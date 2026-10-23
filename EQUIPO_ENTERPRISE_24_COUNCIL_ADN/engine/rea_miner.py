"""rea_miner.py - censo del repo objetivo: extensiones, duenos, licencias AL SHA.

Este modulo mata en codigo el defecto F3: una licencia se clasifica por SPDX
leido al SHA, jamas por substring. 'BUSL-1.1+MIT' contenia 'mit' y el gate lo
leia como permisivo; con \bMit\b y orden BUSL-antes-que-MIT eso no puede pasar.
"""
from __future__ import annotations
import hashlib
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

if __package__:
    from .extension_owners import assert_coverage, resolve_owner
else:
    from extension_owners import assert_coverage, resolve_owner

_SPDX_ID = re.compile(r"SPDX-License-Identifier:\s*([A-Za-z0-9.\-+]+)")

# El ORDEN importa: BUSL antes que MIT. \b evita que 'permitted' cuente como MIT.
_LICENSE_RULES: Tuple[Tuple[str, str, bool], ...] = (
    ("BUSL-1.1", r"\bBusiness\s+Source\s+License\b|\bBUSL-1\.1\b", False),
    ("AGPL-3.0", r"\bAFFERO\s+GENERAL\s+PUBLIC\s+LICENSE\b", False),
    ("LGPL-3.0", r"\bLESSER\s+GENERAL\s+PUBLIC\s+LICENSE\b", False),
    ("GPL-3.0", r"\bGNU\s+GENERAL\s+PUBLIC\s+LICENSE\b", False),
    ("Apache-2.0", r"\bApache\s+License,?\s+Version\s+2\.0\b", True),
    ("MPL-2.0", r"\bMozilla\s+Public\s+License\b", True),
    ("BSD-3-Clause", r"\bBSD\s+3-Clause\b", True),
    ("BSD-2-Clause", r"\bBSD\s+2-Clause\b", True),
    ("MIT", r"\bMIT\s+License\b|\bPermission\s+is\s+hereby\s+granted,\s+free\s+of\s+charge\b", True),
    ("Unlicense", r"\bunencumbered\s+software\s+released\s+into\s+the\s+public\s+domain\b", True),
)
_COMPILED = tuple((sid, re.compile(pat, re.I), perm) for sid, pat, perm in _LICENSE_RULES)

SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".venv"}


@dataclass(frozen=True)
class LicenseVerdict:
    spdx_id: str
    permissive: bool
    sha256: str
    needs_review: bool


def classify_license(text: str, sha: str) -> LicenseVerdict:
    m = _SPDX_ID.search(text or "")
    if m:
        sid = m.group(1).strip()
        perm = next((p for s, _, p in _LICENSE_RULES if s.lower() == sid.lower()), False)
        return LicenseVerdict(sid, perm, sha, needs_review=False)
    for sid, rx, perm in _COMPILED:
        if rx.search(text or ""):
            return LicenseVerdict(sid, perm, sha, needs_review=False)
    return LicenseVerdict("UNKNOWN", False, sha, needs_review=True)


@dataclass
class MinerReport:
    files: int = 0
    extensions: Dict[str, int] = field(default_factory=dict)
    owners: Dict[str, str] = field(default_factory=dict)
    licenses: List[LicenseVerdict] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    gaps: List[str] = field(default_factory=list)


def _bytes(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read(256_000)
    except OSError:
        return b""


def _head(path: str) -> str:
    return _bytes(path).decode("utf-8", "replace")[:64_000]


def mine(root: str, *, max_files: int = 200_000, gate: bool = True) -> MinerReport:
    rep = MinerReport()
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            rep.files += 1
            if rep.files > max_files:
                rep.gaps.append("tope de archivos alcanzado")
                break
            path = os.path.join(base, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            ext = ("." + name.rsplit(".", 1)[1].lower()) if "." in name else ""
            head = _head(path)
            rep.extensions[ext] = rep.extensions.get(ext, 0) + 1
            try:
                rep.owners[rel] = resolve_owner(rel, head)
            except Exception:
                rep.owners[rel] = "SIN_DUENO"
                rep.gaps.append("sin dueno: " + rel)
            if name.upper().startswith("LICENSE"):
                rep.licenses.append(classify_license(head, hashlib.sha256(_bytes(path)).hexdigest()))
            if ext in (".py", ".sol", ".ts", ".rs", ".rhai") and len(rep.capabilities) < 512:
                rep.capabilities += re.findall(
                    r"^(?:def|class|contract|function|fn|pub fn)\s+(\w+)", head, re.M)[:8]
    if gate:
        assert_coverage(rep.extensions.keys())      # Gate 1, en el origen
    return rep


if __name__ == "__main__":
    v = classify_license("Business Source License 1.1 ... permitted ...", "sha")
    assert v.spdx_id == "BUSL-1.1" and v.permissive is False, v
    assert classify_license("MIT License\nPermission is hereby granted...", "s").spdx_id == "MIT"
    assert classify_license("SPDX-License-Identifier: Apache-2.0", "s").spdx_id == "Apache-2.0"
    assert classify_license("texto cualquiera", "s").needs_review is True
    assert classify_license("permitted to use", "s").spdx_id == "UNKNOWN"
    rep = mine(os.path.dirname(os.path.abspath(__file__)), gate=False)
    print("OK rea_miner: BUSL!=MIT, SPDX al SHA, UNKNOWN conservador | "
          "censo local: %d archivos, %d extensiones, %d sin dueno"
          % (rep.files, len(rep.extensions), len(rep.gaps)))
