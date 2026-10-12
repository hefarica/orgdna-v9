"""Registro de despliegue del gang: 2PC idempotente con compensacion y journal.

Los tres servicios de destino (cordi, agent-team, team) NO estan montados en este
arbol: es la verdad del preflight (BLOCKED) y aqui no se disimula. Lo que SI existe
es la transaccion completa:

    IDEMPOTENTE  la clave de publicacion es el SHA-256 del artefacto (clave de
                 contenido). Reintentar con la misma clave es un no-op: no se toca
                 ningun servicio y devuelve el resultado ya commiteado.
    ATOMICO      fase 1 (prepare en los tres) — si uno falla, se aborta lo montado.
                 fase 2 (commit en los tres) — si uno falla, se COMPENSA lo ya
                 commiteado. Nunca queda un servicio adelantado.
    REANUDABLE   cada transicion queda en el journal (en disco si se da un path).
                 Un crash a mitad de commit se resuelve al reanudar: lo commiteado
                 sobrevive, lo que quedo staged se ABORTA (fail-closed).

`mounted` sigue siendo False hasta que exista un runtime real: se registra el hash
del artefacto sellado, no se ejecuta nada.
"""
from __future__ import annotations

try:
    from . import gang_journal
except ImportError:  # importacion suelta (validador de portabilidad)
    import gang_journal

TARGETS = ("cordi", "agent-team", "team")
NOT_MOUNTED = "Servicio no montado en este arbol (preflight BLOCKED); se registra el hash, no se ejecuta nada."


class RegistryError(ValueError):
    """La publicacion no se completo; el registro queda como estaba."""


class GangRegistry:
    """Los tres objetivos, 2PC idempotente con compensacion, sobre un journal."""

    def __init__(self, targets=TARGETS, publish=None, transport=None, journal=None):
        if not targets or len(set(targets)) != len(targets):
            raise RegistryError("targets: se requieren ids unicos.")
        self.targets = tuple(targets)
        self._recorded = {t: None for t in self.targets}
        # Puerto polimorfico: transport(op, objetivo, sha). Cualquier transporte
        # (HTTP, IPC, memoria) implementa la misma interfaz; el coordinador no cambia.
        self._transport = transport
        if publish is not None and transport is None:
            self._transport = lambda op, target, sha: publish(target, sha) if op == "prepare" else None
        self.journal = journal if isinstance(journal, gang_journal.Journal) else gang_journal.Journal()
        self._restore_from_journal()

    def _restore_from_journal(self):
        """Un coordinador que reanuda RECONSTRUYE su estado desde el journal.

        La ultima publicacion commiteada es el hash registrado en los tres objetivos
        (la publicacion es atomica: los tres o ninguno). Sin esto, un reinicio con
        journal en disco daria falsos EMPTY para un artefacto ya commiteado.
        """
        ultimo = None
        for entrada in self.journal.history():
            if entrada.get("estado") == gang_journal.COMMITTED:
                ultimo = entrada.get("clave")
        if isinstance(ultimo, str) and len(ultimo) == 64:
            self._recorded = {t: ultimo for t in self.targets}

    # ---------------------------------------------------------------- puertos

    def _op(self, op, target, sha):
        if self._transport is None:
            return  # transporte por defecto: registrar (no hay runtime que ejecutar)
        return self._transport(op, target, sha)

    # ---------------------------------------------------------------- estado

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

    def history(self):
        """Historial de publicaciones para el panel de auditoria."""
        return self.journal.history()

    # ---------------------------------------------------------------- 2PC

    def publish_atomic(self, artifact_sha):
        """Publicacion en dos fases, idempotente por clave de contenido.

        La clave es el propio SHA-256: reintentar la misma publicacion es un no-op
        (cero side effects) y devuelve el resultado ya commiteado. Si prepare falla
        se aborta lo montado; si commit falla se compensa lo commiteado. El journal
        deja escrita cada transicion, tambien en disco si se configuro path.
        """
        if not isinstance(artifact_sha, str) or len(artifact_sha) != 64:
            raise RegistryError("publish: se requiere un SHA-256 de artefacto valido.")

        # IDEMPOTENCIA: ya commiteada esta clave -> no-op, sin tocar servicios.
        previa = self.journal.get(artifact_sha)
        if previa and previa.get("estado") == gang_journal.COMMITTED:
            # El estado en memoria refleja lo commiteado: esa publicacion si llego
            # a los tres objetivos, aunque esta instancia arranque despues.
            self._recorded = {t: artifact_sha for t in self.targets}
            return {"hash": artifact_sha, "objetivos": len(self.targets),
                    "estado": "REGISTRADO", "idempotente": True,
                    "publicado_en": previa.get("ts")}

        previous = dict(self._recorded)
        self.journal.record(artifact_sha, gang_journal.STAGED, "fase 1: prepare en %d objetivos" % len(self.targets))

        # Fase 1: prepare. El que falla aborta a los ya montados.
        montados = []
        try:
            for target in self.targets:
                self._op("prepare", target, artifact_sha)
                montados.append(target)
        except Exception as exc:  # noqa: BLE001 — el abort es la garantia
            for target in montados:
                self._op("abort", target, artifact_sha)
            self.journal.record(artifact_sha, gang_journal.ABORTED,
                                 "prepare fallo en un objetivo; %d abortados" % len(montados))
            raise RegistryError("Publicacion atomica abortada en prepare (%s: %s); nada quedo registrado."
                                % (type(exc).__name__, exc)) from None

        # Fase 2: commit. El que falla obliga a COMPENSAR lo ya commiteado.
        commiteados = []
        try:
            for target in self.targets:
                self._op("commit", target, artifact_sha)
                commiteados.append(target)
                self._recorded[target] = artifact_sha
        except Exception as exc:  # noqa: BLE001 — la compensacion es la garantia
            for target in commiteados:
                self._op("compensate", target, artifact_sha)
            self._recorded = previous
            self.journal.record(artifact_sha, gang_journal.ROLLED_BACK,
                                 "commit fallo; %d commiteados compensados, registro restaurado" % len(commiteados))
            raise RegistryError("Commit fallo (%s: %s); %d objetivos compensados y el registro quedo como estaba."
                                % (type(exc).__name__, exc, len(commiteados))) from None

        self.journal.record(artifact_sha, gang_journal.COMMITTED,
                             "fase 2 completa: %d objetivos" % len(self.targets))
        return {"hash": artifact_sha, "objetivos": len(self.targets),
                "estado": "REGISTRADO", "idempotente": False}
