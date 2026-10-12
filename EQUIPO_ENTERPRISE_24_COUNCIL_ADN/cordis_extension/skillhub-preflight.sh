#!/bin/sh
# Local/VPS read-only preflight, no sudo, install, service or config changes.
set -eu
if [ "$#" -ne 1 ]; then echo 'Usage: sh skillhub-preflight.sh /absolute/existing/dsh/runtime' >&2; exit 2; fi
command -v node >/dev/null 2>&1 || { echo 'Node missing; review package.json engines and official installation.' >&2; exit 2; }
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec node "$BASE/skillhub-preflight.mjs" "$1" "$BASE"
