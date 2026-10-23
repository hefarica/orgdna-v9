"""evidence_harness.py - Gate 3. agentica>=1, evidencia>=2, falsificador==1.

Un test que no cae al romper su invariante no prueba nada. El falsificador es
obligatorio: se rompe el invariante a proposito y la comprobacion DEBE fallar.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, List, Mapping, Optional, Tuple


class HarnessError(Exception):
    pass


@dataclass
class Check:
    name: str
    kind: str
    fn: Callable[[], bool]
    break_invariant: Optional[Callable[[], None]] = None


@dataclass
class Report:
    agentic: int = 0
    evidence: int = 0
    falsifier: int = 0
    failures: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (self.agentic >= 1 and self.evidence >= 2
                and self.falsifier >= 1 and not self.failures)


def _run(c: Check) -> bool:
    try:
        return bool(c.fn())
    except Exception:
        return False


def falsify(c: Check) -> bool:
    """Pasa, y al romper el invariante FALLA. Sin break_invariant no vale."""
    if not _run(c):
        return False
    if c.break_invariant is None:
        return False
    try:
        c.break_invariant()
    except Exception:
        return True
    return not _run(c)


def run_harness(checks: Mapping[str, Tuple[Check, ...]]) -> Report:
    rep = Report()
    for kind, group in checks.items():
        attr = "falsifier" if kind == "falsifier" else kind
        for c in group:
            if not hasattr(rep, attr):
                raise HarnessError("tipo de comprobacion desconocido: " + kind)
            ok = falsify(c) if kind == "falsifier" else _run(c)
            if not ok:
                rep.failures.append("%s:%s" % (kind, c.name))
                continue
            setattr(rep, attr, getattr(rep, attr) + 1)
    if not rep.ok:
        raise HarnessError("evidencia insuficiente: %s"
                           % (", ".join(rep.failures) or "cuotas no alcanzadas"))
    return rep


if __name__ == "__main__":
    state = {"pct": 1.5}
    sizing = Check("sizing_le_2pct", "falsifier",
                   lambda: state["pct"] <= 2.0,
                   lambda: state.__setitem__("pct", 2.5))
    rep = run_harness({
        "agentic": (Check("arranca_sin_red", "agentic", lambda: True),),
        "evidence": (Check("destino_declarado", "evidence", lambda: True),
                     Check("killswitch_presente", "evidence", lambda: True)),
        "falsifier": (sizing,),
    })
    assert rep.ok and rep.falsifier == 1
    # sin break_invariant NO cuenta como falsificador
    try:
        run_harness({"agentic": (Check("a", "agentic", lambda: True),),
                     "evidence": (Check("e1", "evidence", lambda: True),
                                  Check("e2", "evidence", lambda: True)),
                     "falsifier": (Check("f", "falsifier", lambda: True),)})
        raise SystemExit("FALLO: falsificador sin rotura debio fallar")
    except HarnessError:
        pass
    print("OK evidence_harness: agentica=1 evidencia=2 falsificador=1")
