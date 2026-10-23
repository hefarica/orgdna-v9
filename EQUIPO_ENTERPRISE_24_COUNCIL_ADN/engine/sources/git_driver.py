"""git_driver.py - repositorios Git como fuente (local o remoto, sin bajar blobs).

Reusa la tecnica ya medida en census_remote: clon parcial --filter=blob:none y
ls-tree con core.quotePath=false. Cero cuota de API y sin truncado.
"""
from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
from typing import Set, Tuple

if __package__:
    from .universal_base import (AppSurface, SourceType, SourceUnavailable,
                                 SurfacePoint, UniversalDriver)
else:
    from universal_base import (AppSurface, SourceType, SourceUnavailable,
                                SurfacePoint, UniversalDriver)

SKIP = {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "data"}

FUENTES = (".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".rs", ".sol", ".go",
           ".sql", ".rhai", ".sh", ".ps1", ".cs", ".java", ".c", ".cpp", ".vue",
           ".svelte", ".cairo", ".move", ".vy")
CONFIG = (".json", ".toml", ".yaml", ".yml", ".ini", ".env", ".cfg", ".hcl")
ASSETS = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".ico", ".woff", ".woff2",
          ".ttf", ".mp4", ".webm")


def _clase(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    ext = ("." + base.rsplit(".", 1)[1].lower()) if "." in base else ""
    if ext in FUENTES:
        return "source_code"
    if ext in CONFIG:
        return "config"
    if ext in ASSETS:
        return "asset"
    return "file"


class GitDriver(UniversalDriver):
    @property
    def source_type(self) -> SourceType:
        return SourceType.GIT

    def available(self):
        return True, "git en PATH"

    def _paths(self, target: str):
        if os.path.isdir(target):
            salida = []
            for base, dirs, names in os.walk(target):
                dirs[:] = [d for d in dirs if d not in SKIP]
                for n in names:
                    salida.append(os.path.relpath(os.path.join(base, n), target)
                                  .replace(os.sep, "/"))
            return "local", salida
        tmp = tempfile.mkdtemp(prefix="git-driver-")
        try:
            r = os.path.join(tmp, "repo.git")
            g = ["git", "-c", "gc.auto=0"]
            subprocess.run(g + ["init", "-q", "--bare", "repo.git"], cwd=tmp,
                           check=True, capture_output=True)
            subprocess.run(g + ["remote", "add", "origin", target], cwd=r,
                           check=True, capture_output=True)
            subprocess.run(g + ["fetch", "-q", "--filter=blob:none", "--depth=1",
                                "--no-tags", "origin", "HEAD"], cwd=r,
                           check=True, capture_output=True, timeout=180)
            sha = subprocess.run(g + ["rev-parse", "FETCH_HEAD"], cwd=r, check=True,
                                 capture_output=True, text=True).stdout.strip()
            out = subprocess.run(g + ["-c", "core.quotePath=false", "ls-tree", "-r",
                                      "--name-only", "--full-tree", sha],
                                 cwd=r, check=True, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace").stdout
            return sha, [l for l in out.splitlines() if l.strip()]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def scan_surface(self, target: str) -> AppSurface:
        ok, motivo = self.available()
        if not ok:
            raise SourceUnavailable(motivo)
        ref, paths = self._paths(target)
        puntos = []
        for p in paths:
            base = p.rsplit("/", 1)[-1]
            if base in ("Dockerfile", "Makefile", "LICENSE", ".gitignore"):
                puntos.append(SurfacePoint(p, "config"))
            else:
                puntos.append(SurfacePoint(p, _clase(p)))
        caps = set()
        extensiones = {p.path.rsplit(".", 1)[-1].lower() for p in puntos if "." in p.path}
        if "sol" in extensiones:
            caps.add("onchain")
        if "rhai" in extensiones:
            caps.add("strategy_cartridges")
        if {"tsx", "jsx", "vue", "svelte"} & extensiones:
            caps.add("frontend")
        if {"sh", "ps1"} & extensiones:
            caps.add("automation")
        return AppSurface(
            SourceType.GIT, target, tuple(puntos), caps,
            contracts=(), assets={p.path for p in puntos if p.type == "asset"},
            evidence=("ref %s" % ref, "%d rutas en el arbol" % len(paths)),
            confidence=0.95,
            raw={"ref": ref, "paths": list(paths)})

    def detect_frameworks(self, surface: AppSurface) -> Set[str]:
        ext = set(surface.extensions())
        fw = set()
        if ".rs" in ext:
            fw.add("rust")
        if {".ts", ".tsx"} & ext:
            fw.add("typescript")
        if ".sol" in ext:
            fw.add("solidity")
        if ".rhai" in ext:
            fw.add("rhai")
        return fw


if __name__ == "__main__":
    import os as _os
    d = GitDriver()
    ok, m = d.available()
    assert ok
    s = d.scan_surface(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    assert s.source_type is SourceType.GIT
    assert len(s.points) > 20, len(s.points)
    assert ".py" in s.extensions()
    print("OK git_driver: %d puntos, %d extensiones, huella %s"
          % (len(s.points), len(s.extensions()), s.structure_fingerprint))
