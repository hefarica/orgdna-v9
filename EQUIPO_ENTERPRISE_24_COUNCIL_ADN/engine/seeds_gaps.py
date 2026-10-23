"""seeds_gaps.py - los 10 gaps de la UNION (objetivo + nuestro paquete).

cartridge_engineer NO lleva contrato generico: son 1341 archivos .rhai, el 12,3%
del arbol del objetivo y el nucleo del dominio MEV. Su aceptacion es la del
producto: killswitch, sizing <=2%, neto >=3x gas, paper por defecto y replay
determinista del cartucho.
"""
from __future__ import annotations
from typing import NamedTuple, Tuple


class Seed(NamedTuple):
    name: str
    role: str
    goal: str
    destination: Tuple[str, ...]
    skill_bundle: str
    acceptance: Tuple[str, ...]


GAPS: Tuple[Seed, ...] = (
    Seed("cartridge_engineer", "Cartridge Engineer",
         "Estrategias MEV en Rhai bajo la politica del producto",
         (".rhai",), "mev_cartridge_pack",
         ("killswitch_trips", "sizing_le_2pct", "net_gte_3x_gas",
          "paper_default", "cartridge_replay_deterministic")),
    Seed("docker_engineer", "Docker Engineer",
         "Imagenes reproducibles y minimas", (".dockerignore",), "docker_pack",
         ("pinned_digest", "no_root", "multi_stage")),
    Seed("terraform_engineer", "Terraform Engineer",
         "IaC con estado remoto y plan limpio", (".tf", ".tfvars", ".hcl"),
         "terraform_pack", ("plan_no_drift", "state_lock")),
    Seed("makefile_engineer", "Makefile Engineer",
         "Targets correctos y sin .PHONY faltante", (".mk",), "makefile_pack",
         ("phony_declared", "parallel_safe")),
    Seed("python_engineer", "Python Engineer",
         "Codigo idiomatico, tipado y sin fugas", (".py", ".pyi", ".pyx"),
         "python_pack", ("mypy_clean", "no_bare_except")),
    Seed("javascript_engineer", "JavaScript Engineer",
         "ESM correcto y tree-shakeable", (".js", ".mjs", ".cjs", ".jsx"),
         "js_pack", ("esm_valid", "no_global_leak")),
    Seed("posix_automation", "POSIX Automation",
         "Shell con strict mode y pipefail", (".sh", ".bash", ".zsh"),
         "posix_pack", ("strict_mode", "errexit", "pipefail")),
    Seed("windows_automation", "Windows Automation",
         "PowerShell con error handling y transcript", (".ps1", ".bat", ".cmd"),
         "windows_pack", ("error_action_stop", "transcript_logging")),
    Seed("diagram_engineer", "Diagram Engineer",
         "Diagramas como codigo verificables", (".mmd", ".puml", ".drawio"),
         "diagram_pack", ("renders_valid", "diffable_source")),
    Seed("dotnet_engineer", ".NET Engineer",
         "CLR seguro y nullable enabled", (".cs", ".fs", ".vb"),
         "dotnet_pack", ("nullable_enabled", "async_await_valid")),
)

assert len(GAPS) == 10, len(GAPS)
assert len({s.name for s in GAPS}) == 10, "duplicados en GAPS"

if __name__ == "__main__":
    print("OK seeds_gaps: %d seeds, %d unicos, cartridge con %d criterios"
          % (len(GAPS), len({s.name for s in GAPS}),
             len(GAPS[0].acceptance)))
