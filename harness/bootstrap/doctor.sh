#!/bin/sh
# base-harness Claude Code doctor (POSIX entry point; also Git Bash on Windows).
#
# Read-only. Prints one line per check in the shared six-layer format and the
# roll-up block; exit 0 when the repository layer passes. Delegates to
# doctor_claude.py after the same Python execute-probe bootstrap.sh uses.

set -u

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
DOCTOR="$SCRIPT_DIR/doctor_claude.py"

PY=""
for candidate in python3 python py; do
  if "$candidate" -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "doctor: no working Python 3 on PATH (tried python3, python, py). Install CPython 3.11+ and rerun." >&2
  exit 2
fi
if [ ! -f "$DOCTOR" ]; then
  echo "doctor: $DOCTOR is missing" >&2
  exit 2
fi

exec "$PY" -B "$DOCTOR" "$@"
