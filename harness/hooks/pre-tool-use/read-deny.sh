#!/bin/sh
# read-deny (PreToolUse wrapper, POSIX sh)
#
# Event: PreToolUse. Matcher: Read (Claude Code only; not registered by default).
# Decision: deny (permissionDecision in the JSON) for a file labeled access: secret, or silence.
# Delegates to harness/hooks/lib/read_deny.py, which reads the JSON envelope on stdin and
# prints zero or one JSON line. Exits 0 unconditionally: a missing lib file
# or a missing Python is silence (fail open), and the decision lives in the
# JSON, never in the exit code.
#
# Shipped OFF: the wrapper returns silence unless the environment variable
# HARNESS_READ_DENY equals 1. On Codex and OpenCode the tier labels are
# documentation and this hook is not registered.
# Locate this file with shell builtins only, so the wrapper works even when
# the parent process supplies a PATH without the POSIX userland tools.
# Either separator may appear: a Windows host hands the wrapper a backslash
# path, a POSIX host a forward-slash path.
case "$0" in
  */*) DIR=${0%/*} ;;
  *\\*) DIR=${0%\\*} ;;
  *) DIR=. ;;
esac
DIR=$(cd "$DIR" && pwd)
LIB="$DIR/../lib"
PY="$LIB/read_deny.py"
[ "${HARNESS_READ_DENY:-}" = "1" ] || exit 0
[ -f "$PY" ] || exit 0
. "$LIB/_find_python.sh"
[ -n "$PYTHON" ] || exit 0
"$PYTHON" "$PY" "$@"
exit 0
