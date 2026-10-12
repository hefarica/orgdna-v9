"""Registro de despliegue del gang: los 3 objetivos y su hash, en vivo.

Los tres servicios de destino (cordi, agent-team, team) NO estan montados en este
arbol: es la verdad del preflight (BLOCKED) y aqui no se disimula. Lo que SI existe
hoy es el LIBRO: que artefacto debe servir cada objetivo, si los tres registran el
mismo hash (SYNCED) y una publicacion atomica — los tres o ninguno, con rollback.

Publicar REGISTRA el hash del artefacto sellado en los tres objetivos. No engana:
`mounted` es False hasta que exista un runtime real, y el veredicto solo dice
SINCRONIZADO cuando los tres registran exactamente el mismo SHA-256. Cuando el
runtime aterrice, este libro ya es la fuente de verdad del despliegue.
"""
from __future__ import annotations

TARGETS = ("cordi", "agent-team", "team")
NOT_MOUNTED = "Servicio no montado en este arbol (preflight BLOCKED); se registra el hash, no se ejecuta nada."


class RegistryError(ValueError):
    """La publicacion no se completo; el registro queda como estaba."""


class GangRegistry:
    """Los tres objetivos, un solo escritor, publicacion atomica con rollback."""

    def __init__(self, targets=TARGETS, publish=None):
        if not targets or len(set(targets)) != len(targets):
            raise RegistryError("targets: se requieren ids unicos.")
        self.targets = tuple(targets)
        self._recorded = {t: None for t in self.targets}
        self._publish = publish  # puerto inyectable: fn(objetivo, sha) -> None (falla = excepcion)

    def snapshot(self):
        return [{"id": t, "mounted": False, "note": NOT_MOUNTED,
                 "recorded_sha256": self._recorded[t]} for t in self.targets]

    def sync_verdict(self, artifact_sha=None):
        valores = set(self._recorded.values())
        if all(v is None for v in valores):
            return {"code": "EMPTY", "label": "sin desplegar",
                    "detail": "Ningun objetivo tiene un artefacto registrado."}
        if len(valores) > 1:
            return {"code": "DIVERGED", "label": "divergido",
                    "detail": "Los objetivos registran hashes distintos: revisa antes de confiar."}
        registrado = next(iter(valores))
        if artifact_sha and registrado != artifact_sha:
            return {"code": "STALE", "label": "desactualizado",
                    "detail": "El hash registrado no es el del artefacto actual: vuelve a publicar."}
        return {"code": "SYNCED", "label": "sincronizado",
                "detail": "Los tres objetivos registran el mismo hash del artefacto."}

    def publish_atomic(self, artifact_sha):
        """Registra el hash en los tres objetivos o en ninguno.

        Si el puerto de publicacion falla para cualquier objetivo, todo vuelve al
        estado previo y se eleva RegistryError: nunca queda un gang a medias.
        """
        if not isinstance(artifact_sha, str) or len(artifact_sha) != 64:
            raise RegistryError("publish: se requiere un SHA-256 de artefacto valido.")
        previous = dict(self._recorded)
        try:
            for target in self.targets:
                if self._publish is not None:
                    self._publish(target, artifact_sha)
                self._recorded[target] = artifact_sha
        except Exception as exc:  # noqa: BLE001 — el rollback es la garantia
            self._recorded = previous
            raise RegistryError("Publicacion atomica abortada (%s: %s); los tres objetivos quedaron como estaban."
                                % (type(exc).__name__, exc)) from None
        return {"hash": artifact_sha, "objetivos": len(self.targets), "estado": "REGISTRADO"}
