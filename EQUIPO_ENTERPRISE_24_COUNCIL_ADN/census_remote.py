"""census_remote.py - censo de extensiones de un repo REMOTO sin bajar blobs.

Via primaria: clon parcial por protocolo git (--filter=blob:none --depth=1) +
ls-tree -r. Cero cuota de API REST y sin el truncado de 100k del endpoint.
Via de respaldo: api.github.com/git/trees (consume 1 request).

Los gaps se calculan contra el ROSTER REAL (los 32 ROLE_SEEDS de dna.py, con sus
duenos inferidos), no contra un modulo que aun no existe.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections import Counter

from engine.extension_owners import AMBIGUOUS, EXTENSION_OWNER, FILENAME_OWNER, coverage_gate


def paths_via_git(repo_url: str, ref: str = "HEAD"):
    """Clon parcial + ls-tree. Cero cuota de API y sin truncado."""
    tmp = tempfile.mkdtemp(prefix="census-remote-")
    try:
        r = os.path.join(tmp, "repo.git")
        g = ["git", "-c", "gc.auto=0"]
        # core.quotePath=false: sin esto git entrecomilla nombres no-ASCII y
        # aparecen extensiones FALSAS como .md" o .tsv". Ya nos paso en T1.
        subprocess.run(g + ["init", "-q", "--bare", "repo.git"], cwd=tmp,
                       check=True, capture_output=True)
        subprocess.run(g + ["remote", "add", "origin", repo_url], cwd=r,
                       check=True, capture_output=True)
        subprocess.run(g + ["fetch", "-q", "--filter=blob:none", "--depth=1",
                            "--no-tags", "origin", ref],
                       cwd=r, check=True, capture_output=True)
        sha = subprocess.run(g + ["rev-parse", "FETCH_HEAD"], cwd=r, check=True,
                             capture_output=True, text=True).stdout.strip()
        subprocess.run(g + ["-c", "core.quotePath=false", "checkout-index", "-a",
                            "--prefix=" + os.path.join(tmp, "x", "")],
                       cwd=r, capture_output=True)
        out = subprocess.run(g + ["-c", "core.quotePath=false", "ls-tree", "-r",
                                  "--name-only", "--full-tree", sha],
                             cwd=r, check=True, capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        return sha, [l for l in out.splitlines() if l.strip()]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def paths_via_api(repo_path: str) -> list:
    api = "https://api.github.com/repos/%s/git/trees/HEAD?recursive=1" % repo_path
    req = urllib.request.Request(api, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "orgdna-census",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    if data.get("truncated"):
        raise RuntimeError("el arbol de la API viene truncado: usar git")
    return [t["path"] for t in data.get("tree", []) if t.get("type") == "blob"]


def owner_of(ext: str):
    return EXTENSION_OWNER.get(ext) or (AMBIGUOUS[ext][0] if ext in AMBIGUOUS else None)


def roster_covered_owners() -> set:
    """Duenos que el roster REAL ya cubre, inferidos de su propio texto."""
    from engine.dna import ROLE_SEEDS
    from reconcile_vocabularies import infer_owners, seed_text
    covered = set()
    for seed in ROLE_SEEDS:
        covered.update(infer_owners(seed_text(seed)))
    return covered


def census_remote(source: str) -> dict:
    via = "git"
    try:
        sha, paths = paths_via_git("https://github.com/%s.git" % source)
    except Exception:
        sha, paths = "HEAD", paths_via_api(source)
        via = "api"

    exts, files = Counter(), 0
    for p in paths:
        n = p.rsplit("/", 1)[-1]
        if n in FILENAME_OWNER:
            exts["<f>" + n] += 1
            files += 1
            continue
        e = ("." + n.rsplit(".", 1)[1].lower()) if "." in n else ""
        exts[e] += 1
        files += 1

    real = [e for e in exts if not e.startswith("<f>")]
    rep = coverage_gate(real)
    required = {o for o in (owner_of(e) for e in real) if o}
    required |= {FILENAME_OWNER[e[3:]] for e in exts if e.startswith("<f>")}

    covered = roster_covered_owners()
    gaps = sorted(required - covered)
    present = required & covered

    arch_req = sum(c for e, c in exts.items()
                   if not e.startswith("<f>") and owner_of(e) in required)
    arch_cub = sum(c for e, c in exts.items()
                   if not e.startswith("<f>") and owner_of(e) in present)
    arch_cub += sum(c for e, c in exts.items()
                    if e.startswith("<f>") and FILENAME_OWNER[e[3:]] in present)

    return {
        "repo": source, "sha": sha, "via": via,
        "files": files, "familias": len(real),
        "mapa_huerfanas": sorted(rep.orphans),
        "mapa_ok": rep.ok,
        "duenos_requeridos": len(required),
        "duenos_presentes": len(present),
        "GAPS": gaps,
        "gaps_count": len(gaps),
        "cobertura_archivos_pct_hoy": round(100.0 * arch_cub / files, 2) if files else 0.0,
        "top_extensiones": exts.most_common(18),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python census_remote.py owner/repo", file=sys.stderr)
        sys.exit(1)
    out = census_remote(sys.argv[1])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(0 if out["gaps_count"] == 0 else 2)
