"""forge_dispatch.py - el puente entre forge_loop y un proveedor LLM.

Se mantiene FUERA de generation_pipeline.py a proposito: ese modulo esta vivo,
testeado y es grande (871 lineas); agregarle un factory es riesgo sin beneficio.
Aqui solo se compone: contrato -> prompt -> proveedor -> reconcile -> Response.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, List, Mapping, Optional

if __package__:
    from .forge_loop import Response
    from .instruction_contract import (ContractError, build_prompt, clamp,
                                       reconcile)
    from .budget_governor import plan_budget
else:
    from forge_loop import Response
    from instruction_contract import (ContractError, build_prompt, clamp,
                                      reconcile)
    from budget_governor import plan_budget


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    model: str
    usage_total: int


Provider = Callable[[str, int], ProviderResponse]


def dispatch_factory(provider: Provider, *, verified_model: str,
                     ledger: Optional[List[dict]] = None) -> Callable[[Mapping], Response]:
    """Devuelve un dispatch que falla cerrado si el modelo o el contrato no cuadran."""
    def dispatch(request: Mapping) -> Response:
        profile = request["profile"]
        budget = request["budget"]
        c = clamp(profile)
        pr = provider(build_prompt(c), budget.max_output_tokens)
        if pr.model != verified_model:
            return Response(False, error="modelo no verificado: %s != %s"
                            % (pr.model, verified_model))
        try:
            reconcile(pr.text, c)
        except ContractError as exc:
            return Response(False, error="contrato: %s" % exc)
        if ledger is not None:
            ledger.append({"name": profile.get("name"), "tokens": pr.usage_total})
        return Response(True, pr.model, pr.usage_total)
    return dispatch


if __name__ == "__main__":
    import json
    perfil = {"name": "x", "role": "r", "goal": "g", "destination": [".py"],
              "policy_pack": {"id": "p"}, "acceptance": ["a"]}

    def provider_ok(prompt, cap):
        sobre = json.loads(prompt)
        perfil = dict(sobre["frozen"])
        perfil.update(backstory="b", toolset=[], skill_bundle="s",
                      evidence_harness={})
        return ProviderResponse(json.dumps(perfil), "deepseek-flash", 12)

    plan = plan_budget(max_output_tokens=393216, profiles=1,
                       per_profile_tokens=7753, consent_cap=1)
    r = dispatch_factory(provider_ok, verified_model="deepseek-flash")(
        {"profile": perfil, "budget": plan})
    assert r.ok and r.tokens == 12, r.error

    def provider_otro(prompt, cap):
        sobre = json.loads(prompt)
        perfil = dict(sobre["frozen"])
        perfil.update(backstory="b", toolset=[], skill_bundle="s",
                      evidence_harness={})
        return ProviderResponse(json.dumps(perfil), "otro-modelo", 9)

    r2 = dispatch_factory(provider_otro, verified_model="deepseek-flash")(
        {"profile": perfil, "budget": plan})
    assert not r2.ok and "no verificado" in r2.error
    print("OK forge_dispatch: contrato reconciliado, modelo no verificado falla cerrado")
