#!/bin/sh
# base-harness Codex adapter doctor (POSIX wrapper). Offline by default; pass
# --runtime, --network, --auth, or --probe-skill-loading to opt into probes.

set -u
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

PY=""
for candidate in python3 python py; do
  if "$candidate" -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "doctor-codex: no working Python 3 on PATH (tried python3, python, py)." >&2
  exit 2
fi

[ "$#" -eq 0 ] && set -- --offline
exec "$PY" -B "$SCRIPT_DIR/doctor_codex.py" "$@"
