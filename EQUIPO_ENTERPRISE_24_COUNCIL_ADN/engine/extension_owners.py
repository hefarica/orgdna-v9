"""extension_owners.py - mapa extension -> dueno + Gate 1 (cobertura, fail-closed).

La extension SOLA no alcanza: .tf es Terraform o TensorFlow, .yml es k8s, CI o
ansible. Por eso hay resolucion por ruta y por contenido, y el gate FALLA si una
extension presente no tiene dueno. Nunca se "cubre" por cantidad de agentes.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Tuple

MAX_FAMILIES = 72


class CoverageError(Exception):
    pass


EXTENSION_OWNER: Dict[str, str] = {
    ".py": "python_engineer", ".pyi": "python_engineer", ".pyx": "python_engineer",
    ".ts": "typescript_engineer", ".tsx": "typescript_engineer",
    ".js": "javascript_engineer", ".jsx": "javascript_engineer",
    ".mjs": "javascript_engineer", ".cjs": "javascript_engineer",
    ".rs": "rust_engineer", ".go": "go_engineer", ".mod": "go_engineer",
    ".java": "jvm_engineer", ".kt": "jvm_engineer", ".kts": "jvm_engineer",
    ".scala": "jvm_engineer",
    ".c": "native_engineer", ".h": "native_engineer", ".cpp": "native_engineer",
    ".hpp": "native_engineer", ".cc": "native_engineer",
    ".cs": "dotnet_engineer", ".fs": "dotnet_engineer", ".vb": "dotnet_engineer",
    ".sol": "solidity_engineer", ".vy": "vyper_engineer",
    ".cairo": "cairo_engineer", ".move": "move_engineer",
    ".sql": "data_engineer", ".ddl": "data_engineer", ".dml": "data_engineer",
    ".dbt": "dbt_engineer",
    ".tf": "terraform_engineer", ".tfvars": "terraform_engineer",
    ".hcl": "terraform_engineer",
    ".pt": "ml_engineer", ".onnx": "ml_engineer", ".pkl": "ml_engineer",
    ".ipynb": "notebook_scientist",
    ".r": "stats_engineer", ".stan": "stats_engineer",
    ".parquet": "feature_engineer", ".feather": "feature_engineer",
    ".avro": "feature_engineer",
    ".sh": "posix_automation", ".bash": "posix_automation", ".zsh": "posix_automation",
    ".ps1": "windows_automation", ".bat": "windows_automation", ".cmd": "windows_automation",
    ".vue": "vue_engineer", ".svelte": "svelte_engineer",
    ".swift": "mobile_engineer", ".dart": "mobile_engineer",
    ".css": "design_systems", ".scss": "design_systems", ".less": "design_systems",
    ".md": "docs_engineer", ".mdx": "docs_engineer", ".rst": "docs_engineer",
    ".json": "config_engineer", ".toml": "config_engineer",
    ".ini": "config_engineer", ".env": "config_engineer",
    ".proto": "schema_engineer", ".graphql": "schema_engineer",
    ".avsc": "schema_engineer",
    ".tex": "latex_engineer", ".bib": "latex_engineer",
    ".yml": "ci_engineer", ".yaml": "ci_engineer",
    ".mermaid": "diagram_engineer", ".puml": "diagram_engineer",
}

# --- Extensiones que el repo objetivo TIENE y el mapa inicial no cubria ---
# Medidas en el censo de T1 sobre hefarica/arbitragex-v2: .rhai 1341, .txt 199,
# .csv 97, .sh 110, y activos binarios (png/svg/woff2). Sin esto el Gate 1
# fallaba cerrado sobre archivos legitimos, que es un falso positivo del gate.
_MEDIDAS_EN_EL_REPO_OBJETIVO: Dict[str, str] = {
    ".rhai": "cartridge_engineer",
    ".txt": "docs_engineer", ".pdf": "docs_engineer",
    ".csv": "data_engineer", ".tsv": "data_engineer", ".xlsx": "data_engineer",
    ".xml": "config_engineer", ".cfg": "config_engineer",
    ".properties": "config_engineer", ".lock": "config_engineer",
    ".map": "config_engineer", ".editorconfig": "config_engineer",
    ".svg": "design_systems", ".png": "design_systems",
    ".jpg": "design_systems", ".jpeg": "design_systems",
    ".webp": "design_systems", ".ico": "design_systems",
    ".woff": "design_systems", ".woff2": "design_systems",
    ".ttf": "design_systems",
    ".drawio": "diagram_engineer",
    ".wat": "native_engineer", ".wasm": "native_engineer",
}
EXTENSION_OWNER.update(_MEDIDAS_EN_EL_REPO_OBJETIVO)

FILENAME_OWNER: Dict[str, str] = {
    "Dockerfile": "docker_engineer", "Makefile": "makefile_engineer",
    "CMakeLists.txt": "makefile_engineer", "justfile": "makefile_engineer",
    "LICENSE": "docs_engineer",
}

AMBIGUOUS: Dict[str, Tuple[str, ...]] = {
    ".tf": ("terraform_engineer", "ml_engineer"),
    ".yml": ("ci_engineer", "k8s_engineer", "ansible_engineer"),
    ".yaml": ("ci_engineer", "k8s_engineer", "ansible_engineer"),
    ".json": ("config_engineer", "k8s_engineer", "schema_engineer"),
    ".mod": ("go_engineer", "python_engineer"),
}

_PATH_HINTS: Tuple[Tuple["re.Pattern", str], ...] = (
    (re.compile(r"(^|/)\.github/workflows/"), "ci_engineer"),
    (re.compile(r"(^|/)(k8s|kubernetes|manifests|helm)/"), "k8s_engineer"),
    (re.compile(r"(^|/)(ansible|playbooks|roles)/"), "ansible_engineer"),
    (re.compile(r"(^|/)terraform/|\.tfvars$"), "terraform_engineer"),
    (re.compile(r"(^|/)(dbt|models)/"), "dbt_engineer"),
)

_CONTENT_HINTS: Tuple[Tuple["re.Pattern", str], ...] = (
    (re.compile(r"^\s*apiVersion:\s*", re.M), "k8s_engineer"),
    (re.compile(r'^\s*resource\s+"', re.M), "terraform_engineer"),
    (re.compile(r"^\s*on:\s*$", re.M), "ci_engineer"),
    (re.compile(r"import\s+tensorflow|tf\.keras", re.M), "ml_engineer"),
)


def _ext(path: str) -> str:
    base = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return ("." + base.rsplit(".", 1)[1].lower()) if "." in base else ""


def resolve_owner(path: str, content_head: str = "") -> str:
    """Dueno de un archivo. Ruta > contenido > orden declarado. Fail-closed."""
    base = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if base in FILENAME_OWNER:
        return FILENAME_OWNER[base]
    ext = _ext(path)
    cands = AMBIGUOUS.get(ext)
    if not cands:
        owner = EXTENSION_OWNER.get(ext)
        if owner is None:
            raise CoverageError("extension sin dueno: %r (%s)" % (ext, path))
        return owner
    for pat, owner in _PATH_HINTS:
        if pat.search(path) and owner in cands:
            return owner
    for pat, owner in _CONTENT_HINTS:
        if pat.search(content_head) and owner in cands:
            return owner
    return cands[0]


@dataclass(frozen=True)
class CoverageReport:
    present: Tuple[str, ...]
    orphans: Tuple[str, ...]
    owner_of: Mapping[str, str]

    @property
    def ok(self) -> bool:
        return not self.orphans

    @property
    def coverage(self) -> float:
        if not self.present:
            return 1.0
        return (len(self.present) - len(self.orphans)) / len(self.present)


def coverage_gate(extensions_present: Iterable[str]) -> CoverageReport:
    present = tuple(sorted({e.lower() for e in extensions_present if e}))
    orphans = tuple(e for e in present
                    if e not in EXTENSION_OWNER and e not in AMBIGUOUS)
    owner_of = {e: (EXTENSION_OWNER.get(e) or AMBIGUOUS[e][0])
                for e in present if e not in orphans}
    return CoverageReport(present, orphans, owner_of)


def assert_coverage(extensions_present: Iterable[str]) -> CoverageReport:
    rep = coverage_gate(extensions_present)
    if not rep.ok:
        raise CoverageError("extensiones huerfanas: " + ", ".join(rep.orphans))
    return rep


def assert_map_sane() -> None:
    if len(EXTENSION_OWNER) < MAX_FAMILIES:
        raise CoverageError("mapa corto: %d < %d" % (len(EXTENSION_OWNER), MAX_FAMILIES))
    for ext, cands in AMBIGUOUS.items():
        if EXTENSION_OWNER.get(ext) not in cands:
            raise CoverageError("ambiguo mal declarado: " + ext)


if __name__ == "__main__":
    assert_map_sane()
    assert assert_coverage([".py", ".sol", ".yml", ".tf", ".md"]).ok
    try:
        assert_coverage([".nope"])
        raise SystemExit("FALLO: .nope debio fallar")
    except CoverageError:
        pass
    assert resolve_owner(".github/workflows/ci.yml") == "ci_engineer"
    assert resolve_owner("k8s/deploy.yml") == "k8s_engineer"
    assert resolve_owner("Dockerfile") == "docker_engineer"
    print("OK extension_owners: %d familias, 0 huerfanas, ambiguos por ruta" % len(EXTENSION_OWNER))
