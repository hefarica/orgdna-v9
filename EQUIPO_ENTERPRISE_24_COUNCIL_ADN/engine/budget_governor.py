"""budget_governor.py - el tope se PRESERVA. per_batch>=1 o falla cerrado.

Este modulo existe por un defecto real: verificar el modelo dejaba
max_output_tokens=32, con lo que per_batch = (32-1024)//3200 = -1 y el diseno
abortaba con output_budget_too_small. El tope verificado NUNCA se degrada.
"""
from __future__ import annotations
from dataclasses import dataclass


class BudgetError(Exception):
    pass


@dataclass(frozen=True)
class BudgetPlan:
    max_output_tokens: int
    profiles: int
    per_profile_tokens: int
    per_batch: int
    batches: int
    sent_requests_cap: int


def assert_cap_preserved(verified_cap: int, candidate: int) -> int:
    if verified_cap <= 0:
        raise BudgetError("tope verificado invalido (<=0)")
    return verified_cap if candidate < verified_cap else candidate


def plan_budget(*, max_output_tokens: int, profiles: int,
                per_profile_tokens: int, consent_cap: int) -> BudgetPlan:
    if max_output_tokens <= 0:
        raise BudgetError("max_output_tokens<=0: el tope se degrado (%r)" % (max_output_tokens,))
    if profiles <= 0:
        raise BudgetError("profiles<=0 (%r)" % (profiles,))
    if per_profile_tokens <= 0:
        raise BudgetError("per_profile_tokens<=0 (%r)" % (per_profile_tokens,))
    per_batch = max_output_tokens // per_profile_tokens
    if per_batch < 1:
        raise BudgetError(
            "output_budget_too_small: tope=%d perfil=%d -> per_batch=%d"
            % (max_output_tokens, per_profile_tokens, per_batch))
    batches = (profiles + per_batch - 1) // per_batch
    if consent_cap <= 0:
        raise BudgetError("techo de consentimiento no declarado")
    return BudgetPlan(max_output_tokens, profiles, per_profile_tokens,
                      per_batch, batches, min(batches, consent_cap))


if __name__ == "__main__":
    try:
        plan_budget(max_output_tokens=32, profiles=30,
                    per_profile_tokens=7753, consent_cap=4)
        raise SystemExit("FALLO: 32 debio fallar")
    except BudgetError as e:
        assert "output_budget_too_small" in str(e)
    p = plan_budget(max_output_tokens=393216, profiles=74,
                    per_profile_tokens=7753, consent_cap=12)
    assert p.per_batch >= 1 and p.max_output_tokens == 393216
    assert assert_cap_preserved(393216, 32) == 393216
    print("OK budget_governor: tope preservado, per_batch=%d, batches=%d"
          % (p.per_batch, p.batches))
