"""instruction_contract.py - el LLM no quita, no pone, no suaviza.

Congela la identidad de cada perfil. Si la respuesta altera un campo frozen, el
perfil se rechaza: es lo que impide que 74 agentes degeneren en 74 variaciones
del mismo texto. assert_distinct caza el clon por firma.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Tuple


class ContractError(Exception):
    pass


FROZEN: Tuple[str, ...] = (
    "name", "role", "goal", "destination", "policy_pack", "acceptance",
)
EXPAND: Tuple[str, ...] = (
    "backstory", "toolset", "skill_bundle", "evidence_harness",
)


@dataclass(frozen=True)
class Clamp:
    frozen: Mapping[str, Any]

    @property
    def signature(self) -> Tuple:
        return tuple(
            (k, json.dumps(self.frozen[k], sort_keys=True, ensure_ascii=False))
            for k in FROZEN if k in self.frozen
        )


def clamp(profile: Mapping[str, Any]) -> Clamp:
    missing = [k for k in FROZEN if k not in profile]
    if missing:
        raise ContractError("perfil sin campos congelados: " + ", ".join(missing))
    return Clamp({k: profile[k] for k in FROZEN})


def build_prompt(c: Clamp) -> str:
    return json.dumps({
        "task": "forge_profile",
        "output": "json",
        "frozen": dict(c.frozen),
        "expand": list(EXPAND),
        "rules": [
            "no quitar", "no poner", "no suavizar los campos frozen",
            "devolver los campos frozen IDENTICOS", "expandir solo los de expand",
        ],
    }, ensure_ascii=False, sort_keys=True)


_JSON = re.compile(r"\{.*\}", re.S)


def reconcile(text: str, c: Clamp) -> Mapping[str, Any]:
    m = _JSON.search(text or "")
    if not m:
        raise ContractError("respuesta sin JSON")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise ContractError("JSON invalido: %s" % exc)
    for k in FROZEN:
        if k not in data:
            raise ContractError("frozen ausente: " + k)
        if json.dumps(data[k], sort_keys=True, ensure_ascii=False) != \
                json.dumps(c.frozen[k], sort_keys=True, ensure_ascii=False):
            raise ContractError("frozen alterado: " + k)
    for k in EXPAND:
        if k not in data:
            raise ContractError("expand ausente: " + k)
    return data


def assert_distinct(profiles) -> None:
    seen = {}
    for p in profiles:
        sig = clamp(p).signature
        if sig in seen:
            raise ContractError("perfil clon: %s == %s"
                                % (p.get("name"), seen[sig]))
        seen[sig] = p.get("name")


if __name__ == "__main__":
    a = {"name": "x", "role": "r", "goal": "g", "destination": [".py"],
         "policy_pack": {"id": "p"}, "acceptance": ["a"]}
    ok = json.dumps({**a, "backstory": "b", "toolset": [],
                     "skill_bundle": "s", "evidence_harness": {}})
    reconcile(ok, clamp(a))
    # goals distintos -> NO son clones: assert_distinct debe PASAR
    b = dict(a)
    b["goal"] = "OTRO"
    assert_distinct([a, b])
    # clon exacto -> rechazo
    try:
        assert_distinct([a, dict(a)])
        raise SystemExit("FALLO: debio detectar clon exacto")
    except ContractError:
        pass
    # frozen alterado -> rechazo
    bad = json.dumps({**a, "goal": "OTRO", "backstory": "b", "toolset": [],
                      "skill_bundle": "s", "evidence_harness": {}})
    try:
        reconcile(bad, clamp(a))
        raise SystemExit("FALLO: frozen alterado debio rechazarse")
    except ContractError:
        pass
    # expand ausente -> rechazo
    try:
        reconcile(json.dumps(a), clamp(a))
        raise SystemExit("FALLO: expand ausente debio rechazarse")
    except ContractError:
        pass
    print("OK instruction_contract: frozen clavado, anti-clon, expand obligatorio")
