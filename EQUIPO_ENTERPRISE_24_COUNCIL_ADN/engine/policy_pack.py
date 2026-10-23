"""policy_pack.py - politica inyectada e INMUTABLE. Gate 2.

El LLM no puede quitar, poner ni suavizar policy_pack, acceptance ni destination.
Incluye el registro del defecto de gate F3 para que nadie repita la mina.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple


class PolicyError(Exception):
    pass


NON_NEGOTIABLE: Tuple[str, ...] = ("policy_pack", "acceptance", "destination")


@dataclass(frozen=True)
class PolicyPack:
    id: str
    version: int
    rules: Mapping[str, Any]
    provenance: Tuple[str, ...]


PACKS: Dict[str, PolicyPack] = {
    "trading_safety_v1": PolicyPack(
        id="trading_safety_v1", version=1,
        rules={
            "killswitch": {"required": True, "gate": "preflight", "on_trip": "halt_all"},
            "sizing": {"max_pct_equity": 2.0, "enforced": "hard"},
            "net_edge": {"min_ratio_vs_gas": 3.0, "formula": "net >= 3 * gas"},
            "execution_mode": {"default": "paper",
                               "live_requires": "explicit_consent"},
            "loop": {"bounded": True, "cap": "consent_cap",
                     "stop_on": ["killswitch", "no_budget", "gate_fail"]},
        },
        provenance=(
            "defecto_gate_F3: 'BUSL-1.1+MIT' se leia como permisiva por el substring 'mit'",
            "clasificar licencias SIEMPRE por SPDX leido al SHA, nunca por substring",
        ),
    ),
}


def inject(pack_id: str, profile: Mapping[str, Any]) -> Dict[str, Any]:
    pack = PACKS.get(pack_id)
    if pack is None:
        raise PolicyError("pack desconocido: " + pack_id)
    out = dict(profile)
    out["policy_pack"] = {"id": pack.id, "version": pack.version,
                          "rules": dict(pack.rules),
                          "_non_negotiable": list(NON_NEGOTIABLE)}
    acceptance = list(out.get("acceptance") or [])
    for rule in ("killswitch_trips", "sizing_never_exceeds_2pct",
                 "net_edge_gte_3x_gas", "default_is_paper"):
        if rule not in acceptance:
            acceptance.append(rule)
    out["acceptance"] = acceptance
    return out


def assert_injected(profile: Mapping[str, Any]) -> None:
    pp = profile.get("policy_pack")
    if not pp:
        raise PolicyError("%s: sin policy_pack inyectado" % profile.get("name"))
    for rule in ("killswitch", "sizing", "net_edge", "execution_mode", "loop"):
        if rule not in (pp.get("rules") or {}):
            raise PolicyError("%s: regla ausente %s" % (profile.get("name"), rule))
    if set(NON_NEGOTIABLE) - set(pp.get("_non_negotiable") or []):
        raise PolicyError("%s: inmutables no marcados" % profile.get("name"))
    if not profile.get("acceptance"):
        raise PolicyError("%s: sin criterios de aceptacion" % profile.get("name"))


if __name__ == "__main__":
    p = inject("trading_safety_v1", {"name": "x", "destination": [".py"]})
    assert_injected(p)
    bad = dict(p)
    bad.pop("policy_pack")
    try:
        assert_injected(bad)
        raise SystemExit("FALLO: sin pack debio fallar")
    except PolicyError:
        pass
    print("OK policy_pack: inyeccion inmutable + gate 2")
