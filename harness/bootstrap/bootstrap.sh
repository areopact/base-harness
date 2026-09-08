#!/bin/sh
# base-harness bootstrap (POSIX entry point; also Git Bash on Windows).
#
# Materializes the runtime paths declared in harness/bootstrap/junctions.json
# (.claude/, .codex/, .agents/, .opencode/, opencode.json, AGENTS.md) from the
# canonical harness/ tree, materializes the selected skills per runtime,
# prunes deselected harness-managed entries, runs the optional extension
# point, and registers the git pre-commit floor. All of that logic lives in
# materialize.py; this script only finds a working Python and delegates, so
# the POSIX and Windows entry points cannot diverge.
#
# Modes:
#   bootstrap.sh            create or repair every destination
#   bootstrap.sh --check    verify only; exit 1 on drift; changes nothing
#   bootstrap.sh --copy     recursive copies instead of links (link-hostile filesystems)
#   bootstrap.sh --force    replace a conflicting unmanaged FILE; real directories are never removed
#
# Exit codes: 0 clean, 1 drift or unresolved conflict, 2 missing prerequisite,
# 3 manifest parse failure.

set -u

CHECK=0; COPY=0; FORCE=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --copy) COPY=1 ;;
    --force|-f) FORCE=1 ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "bootstrap: unknown flag: $arg (use --check, --copy, --force)" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$SCRIPT_DIR/../.." && pwd)
ENGINE="$SCRIPT_DIR/materialize.py"
MANIFEST="$SCRIPT_DIR/junctions.json"

# Execute-probe for Python. A PATH entry named python may be an app-store
# alias or a broken shim that exits non-zero without running code; only a
# candidate that actually executes a trivial program is accepted.
PY=""
for candidate in python3 python py; do
  if "$candidate" -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "bootstrap: no working Python 3 on PATH (tried python3, python, py; an alias that only opens an app store does not count). Install CPython 3.11+ and rerun." >&2
  exit 2
fi
PY_PATH=$(command -v "$PY" 2>/dev/null || echo "$PY")

# Hook wrappers are bash scripts. Without bash the contract text still
# governs, so this is a warning, not a failure.
if ! command -v bash >/dev/null 2>&1; then
  echo "  WARN     bash is not on PATH: hook wrappers will not run in this environment; the contract text in AGENTS.md still governs"
fi

if [ ! -f "$ENGINE" ]; then
  echo "bootstrap: engine missing at $ENGINE" >&2
  exit 2
fi
if [ ! -f "$MANIFEST" ]; then
  echo "bootstrap: manifest missing at $MANIFEST (harness/bootstrap/junctions.json)" >&2
  exit 3
fi

echo "bootstrap: python = $PY_PATH"

set --
[ "$CHECK" = 1 ] && set -- "$@" --check
[ "$COPY" = 1 ] && set -- "$@" --copy
[ "$FORCE" = 1 ] && set -- "$@" --force

# The engine derives the repository root from its own location, so no path
# crosses the shell boundary (Git Bash would otherwise rewrite it).
"$PY" -B "$ENGINE" "$@"
exit $?
