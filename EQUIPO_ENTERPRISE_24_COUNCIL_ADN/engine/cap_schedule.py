"""cap_schedule.py - programador REAL con stdlib (threading + JSON), sin APScheduler.

El paquete no tiene requirements.txt ni pyproject: es stdlib-only. APScheduler seria
la primera dependencia externa de producto, y una dependencia no declarada es una
dependencia que no existe en la maquina del operador.

Este programador no promete un bucle en produccion: expone tick(now) para que un
llamador externo lo dispare. Sin llamador, no corre nada — y eso se declara.
"""
from __future__ import annotations
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional


class ScheduleError(Exception):
    pass


@dataclass
class Job:
    job_id: str
    interval_seconds: int
    action_name: str
    last_run: float = 0.0
    runs: int = 0


class Scheduler:
    """Persistente en JSON. `tick(now)` ejecuta lo vencido y devuelve recibos."""

    def __init__(self, store_path: str):
        if not store_path:
            raise ScheduleError("falta store_path: sin persistencia no hay agenda")
        self.store_path = store_path
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.store_path):
            return
        try:
            with open(self.store_path, encoding="utf-8") as fh:
                dados = json.load(fh)
        except (OSError, ValueError) as exc:
            raise ScheduleError("agenda ilegible: %s" % exc)
        for row in dados.get("jobs", []):
            job = Job(row["job_id"], int(row["interval_seconds"]),
                      row["action_name"], float(row.get("last_run", 0.0)),
                      int(row.get("runs", 0)))
            self._jobs[job.job_id] = job

    def _save(self) -> None:
        dados = {"jobs": [{"job_id": j.job_id, "interval_seconds": j.interval_seconds,
                           "action_name": j.action_name, "last_run": j.last_run,
                           "runs": j.runs} for j in self._jobs.values()]}
        tmp = self.store_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(dados, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.store_path)
        except OSError as exc:
            raise ScheduleError("no se pudo persistir la agenda: %s" % exc)

    def add(self, job_id: str, interval_seconds: int, action_name: str) -> dict:
        if not job_id or not action_name:
            raise ScheduleError("job_id y action_name son obligatorios")
        if type(interval_seconds) is not int or interval_seconds < 1:
            raise ScheduleError("interval_seconds debe ser entero >= 1")
        with self._lock:
            self._jobs[job_id] = Job(job_id, interval_seconds, action_name)
            self._save()
        return {"job_id": job_id, "interval_seconds": interval_seconds,
                "action_name": action_name, "persisted": self.store_path}

    def due(self, now: float) -> List[Job]:
        return [j for j in self._jobs.values()
                if now - j.last_run >= j.interval_seconds]

    def tick(self, actions: Mapping[str, Callable[[], object]],
             now: Optional[float] = None) -> List[dict]:
        """Ejecuta lo vencido. Una accion ausente es un fallo declarado, no un exito."""
        ahora = time.time() if now is None else float(now)
        recibos = []
        for job in self.due(ahora):
            fn = actions.get(job.action_name)
            if fn is None:
                recibos.append({"job_id": job.job_id, "ok": False,
                                "error": "accion no registrada: %s" % job.action_name})
                continue
            try:
                res = fn()
                ok, err = True, None
            except Exception as exc:
                res, ok, err = None, False, "%s: %s" % (type(exc).__name__, exc)
            with self._lock:
                job.last_run = ahora
                job.runs += 1
                self._save()
            recibos.append({"job_id": job.job_id, "ok": ok, "error": err,
                            "runs": job.runs, "result": repr(res)[:120] if res is not None else None})
        return recibos

    def jobs(self) -> List[dict]:
        return [{"job_id": j.job_id, "interval_seconds": j.interval_seconds,
                 "action_name": j.action_name, "runs": j.runs,
                 "last_run": j.last_run} for j in self._jobs.values()]


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    store = os.path.join(d, "agenda.json")
    s = Scheduler(store)
    s.add("extraer", 60, "extraer_adn")
    assert s.tick({}, now=1000.0)[0]["ok"] is False, "accion ausente debe fallar"
    s2 = Scheduler(store)
    assert len(s2.jobs()) == 1, "la agenda debe persistir"
    r = s2.tick({"extraer_adn": lambda: "hecho"}, now=2000.0)
    assert r and r[0]["ok"] and r[0]["runs"] == 1, "una accion ausente no cuenta como ejecucion"
    assert s2.due(2030.0) == [], "no vence antes del intervalo"
    try:
        Scheduler("")
        raise SystemExit("FALLO: sin store_path debio fallar")
    except ScheduleError:
        pass
    print("OK cap_schedule: persistente, accion ausente falla, tick verificable con now inyectado")
