"""Validate this package offline. Python 3.10+, standard library only.
Usage: python validate_imports_portable.py [package.zip | unpacked_directory]
No old scripts, network, credentials, model calls or project execution are used.
"""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.bundle import validate_bundle, validate_directory

if __name__ == '__main__':
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    try:
        report = validate_directory(target) if target.is_dir() else validate_bundle(target.read_bytes())
    except (OSError, ValueError) as exc:
        report = {'valid': False, 'errors': [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report['valid'] else 1)
