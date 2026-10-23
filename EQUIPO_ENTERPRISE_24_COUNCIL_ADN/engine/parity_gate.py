"""parity_gate.py - Gate 4: la replica debe cubrir la spec, o no se sella."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Mapping, Set


class ParityError(Exception):
    pass


def _key(item) -> str:
    """Clave canonica: los contratos se comparan por contenido, no por cantidad."""
    if isinstance(item, Mapping):
        return json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
    return str(item)


@dataclass
class ParityReport:
    missing_routes: Set[str] = field(default_factory=set)
    missing_contracts: Set[str] = field(default_factory=set)
    missing_capabilities: Set[str] = field(default_factory=set)
    missing_assets: Set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not any([self.missing_routes, self.missing_contracts,
                        self.missing_capabilities, self.missing_assets])

    @property
    def detail(self) -> str:
        return "rutas=%d contratos=%d caps=%d assets=%d" % (
            len(self.missing_routes), len(self.missing_contracts),
            len(self.missing_capabilities), len(self.missing_assets))


def parity_gate(spec, replica: Mapping) -> ParityReport:
    """Compara por CONTENIDO canonico, no por cardinalidad.

    El borrador comparaba len(spec.api_contracts) - len(have_contracts): dos
    contratos distintos contaban como paridad. Aqui cada contrato se compara por
    su JSON canonico, asi que uno ausente se ve.
    """
    rep = ParityReport()
    rep.missing_routes = {_key(x) for x in spec.routes} - {_key(x) for x in replica.get("routes", ())}
    rep.missing_capabilities = {_key(x) for x in spec.capabilities} - {_key(x) for x in replica.get("capabilities", ())}
    rep.missing_assets = {_key(x) for x in spec.assets} - {_key(x) for x in replica.get("assets", ())}
    rep.missing_contracts = {_key(x) for x in spec.api_contracts} - {_key(x) for x in replica.get("contracts", ())}
    if not rep.ok:
        raise ParityError("paridad fallida: " + rep.detail)
    return rep


if __name__ == "__main__":
    if __package__:
        from .site_rea import ReplicationSpec
    else:
        from site_rea import ReplicationSpec
    spec = ReplicationSpec(url="https://x", routes=("/a", "/b"),
                           capabilities=("nav",), assets=("a.png",),
                           api_contracts=({"t": 1},))
    ok = parity_gate(spec, {"routes": ["/a", "/b", "/c"], "capabilities": ["nav", "form"],
                            "assets": ["a.png"], "contracts": [{"t": 1}]})
    assert ok.ok
    # contrato DISTINTO con el mismo conteo: el borrador lo daba por bueno
    try:
        parity_gate(spec, {"routes": ["/a", "/b"], "capabilities": ["nav"],
                           "assets": ["a.png"], "contracts": [{"t": 2}]})
        raise SystemExit("FALLO: contrato distinto debio fallar")
    except ParityError:
        pass
    try:
        parity_gate(spec, {"routes": ["/a"], "capabilities": ["nav"],
                           "assets": ["a.png"], "contracts": [{"t": 1}]})
        raise SystemExit("FALLO: ruta faltante debio fallar")
    except ParityError:
        pass
    print("OK parity_gate: 4 dimensiones por contenido canonico, fail-closed")
