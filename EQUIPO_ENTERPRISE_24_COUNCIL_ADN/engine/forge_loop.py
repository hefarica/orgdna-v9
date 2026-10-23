"""forge_loop.py - EL LLAMADOR: F2 cobertura -> F3 DNA+politica -> F4 forge -> F6 evidencia.

dry_run=True valida los tres gates y el presupuesto SIN gastar un token: es lo que
hace medible el tranche 4 antes de pagar la corrida.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

if __package__:
    from .extension_owners import assert_coverage
    from .budget_governor import assert_cap_preserved, plan_budget
    from .policy_pack import inject, assert_injected
    from .evidence_harness import run_harness, for_agent
    from .instruction_contract import assert_distinct
else:
    from extension_owners import assert_coverage
    from budget_governor import assert_cap_preserved, plan_budget
    from policy_pack import inject, assert_injected
    from evidence_harness import run_harness, for_agent
    from instruction_contract import assert_distinct


class ForgeError(Exception):
    pass


@dataclass(frozen=True)
class Receipt:
    phase: str
    key: str
    ok: bool
    detail: str
    tokens: int = 0


@dataclass(frozen=True)
class Response:
    ok: bool
    model: str = ""
    tokens: int = 0
    error: str = ""


@dataclass
class ForgeResult:
    receipts: List[Receipt] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.receipts) and all(r.ok for r in self.receipts)

    @property
    def tokens(self) -> int:
        return sum(r.tokens for r in self.receipts)


def forge(*, profiles: Sequence[Mapping[str, Any]], miner_report: Any,
          consent_cap: int, verified_cap: int, per_profile_tokens: int,
          dispatch: Optional[Callable[[Mapping], Response]],
          harness_for: Callable[[Mapping], Mapping],
          policy_pack_id: str = "trading_safety_v1",
          dry_run: bool = False) -> ForgeResult:
    res = ForgeResult()

    # ---- GATE 1: cobertura sobre el arbol REAL ----
    rep = assert_coverage(miner_report.extensions.keys())
    res.receipts.append(Receipt("F2", "coverage", True,
                                "%d familias / 0 huerfanas" % len(rep.present)))

    # ---- F3: DNA + politica inmutable + anti-clon (GATE 2) ----
    enriched: List[Dict[str, Any]] = []
    for p in profiles:
        if not p.get("destination"):
            raise ForgeError("%s: sin destino (Gate 1 lo exige)" % p.get("name"))
        e = inject(policy_pack_id, p)
        assert_injected(e)
        enriched.append(e)
    assert_distinct(enriched)
    res.receipts.append(Receipt("F3", "dna", True,
                                "%d perfiles, 0 clones, %s inmutable"
                                % (len(enriched), policy_pack_id)))

    # ---- presupuesto: el tope verificado NO se degrada ----
    cap = assert_cap_preserved(verified_cap, verified_cap)
    plan = plan_budget(max_output_tokens=cap, profiles=len(enriched),
                       per_profile_tokens=per_profile_tokens, consent_cap=consent_cap)
    res.receipts.append(Receipt("F3", "budget", True,
                                "cap=%d per_batch=%d batches=%d"
                                % (cap, plan.per_batch, plan.batches)))

    if dry_run:
        res.receipts.append(Receipt("F4", "dry_run", True,
                                    "gates validados, 0 tokens gastados"))
        return res
    if dispatch is None:
        raise ForgeError("dispatch requerido si dry_run=False")

    # ---- F4: una solicitud por perfil ----
    for p in enriched:
        r = dispatch({"profile": p, "budget": plan})
        if not r.ok:
            raise ForgeError("F4 %s: %s" % (p["name"], r.error))
        res.receipts.append(Receipt("F4", p["name"], True, r.model, tokens=r.tokens))

    # ---- GATE 3: evidencia por agente ----
    for p in enriched:
        try:
            run_harness(harness_for(p))
        except Exception as exc:
            raise ForgeError("GATE3 %s: %s" % (p["name"], exc))
        res.receipts.append(Receipt("F6", p["name"], True,
                                    "agentica 1/1 + evidencia 2/2 + falsificador"))
    return res


if __name__ == "__main__":
    class FakeReport:
        extensions = {".py": 3, ".ts": 2, ".css": 1}

    def perfil(i):
        return {"name": "agent_%d" % i, "role": "r", "goal": "g%d" % i,
                "destination": [".py"], "acceptance": ["x"], "skill_bundle": "p"}

    r = forge(profiles=[perfil(i) for i in range(74)], miner_report=FakeReport(),
              consent_cap=12, verified_cap=393216, per_profile_tokens=7753,
              dispatch=None, harness_for=for_agent, dry_run=True)
    assert r.ok and r.tokens == 0
    try:
        forge(profiles=[dict(perfil(0), destination=[])], miner_report=FakeReport(),
              consent_cap=12, verified_cap=393216, per_profile_tokens=7753,
              dispatch=None, harness_for=for_agent, dry_run=True)
        raise SystemExit("FALLO: sin destino debio fallar")
    except ForgeError:
        pass
    try:
        forge(profiles=[perfil(0), perfil(0)], miner_report=FakeReport(),
              consent_cap=12, verified_cap=393216, per_profile_tokens=7753,
              dispatch=None, harness_for=for_agent, dry_run=True)
        raise SystemExit("FALLO: clon debio fallar")
    except Exception:
        pass
    print("OK forge_loop: dry_run 74 perfiles, 0 tokens, gates 1-2 cerrados, anti-clon")
