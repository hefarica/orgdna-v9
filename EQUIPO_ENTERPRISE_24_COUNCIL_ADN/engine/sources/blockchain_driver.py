"""blockchain_driver.py - DECLARADO NO DISPONIBLE, y con el motivo exacto.

No se implementa a medias. Un driver que devuelve una superficie vacia cuando no
puede leer la cadena es peor que uno que se declara ausente: produce un informe
con forma de dato. Hasta que exista endpoint RPC y credencial de explorer
aportados por el operador, available() es False y scan_surface levanta.
"""
from __future__ import annotations
from typing import Set

if __package__:
    from .universal_base import SourceType, SourceUnavailable, UniversalDriver
else:
    from universal_base import SourceType, SourceUnavailable, UniversalDriver

MOTIVO = (
    "blockchain: sin endpoint RPC ni credencial de explorer aportados. "
    "Requiere RPC_URL (eth_getCode) y API key de explorer (ABI) en el entorno del "
    "operador; sin ellos no hay evidencia y no se simula una superficie."
)


class BlockchainDriver(UniversalDriver):
    @property
    def source_type(self) -> SourceType:
        return SourceType.BLOCKCHAIN

    def available(self):
        import os
        if not os.environ.get("RPC_URL"):
            return False, MOTIVO
        return False, MOTIVO + " (RPC_URL presente pero el lector ABI no esta implementado)"

    def scan_surface(self, target: str):
        raise SourceUnavailable(MOTIVO)

    def detect_frameworks(self, surface) -> Set[str]:
        return set()


if __name__ == "__main__":
    d = BlockchainDriver()
    ok, motivo = d.available()
    assert ok is False
    try:
        d.scan_surface("ethereum:0x0")
        raise SystemExit("FALLO: debio declararse no disponible")
    except SourceUnavailable as exc:
        assert "RPC" in str(exc)
    print("OK blockchain_driver: declarado NO disponible con motivo accionable")
