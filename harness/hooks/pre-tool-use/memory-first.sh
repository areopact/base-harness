#!/bin/sh
# memory-first (PreToolUse wrapper, POSIX sh)
#
# Event: PreToolUse. Matcher: WebSearch|WebFetch.
# Decision: advisory naming local files whose stems match the query, or silence.
# Delegates to harness/hooks/lib/memory_first.py, which reads the JSON envelope on stdin and
# prints zero or one JSON line. Exits 0 unconditionally: a missing lib file
# or a missing Python is silence (fail open), and the decision lives in the
# JSON, never in the exit code.

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
PY="$LIB/memory_first.py"
[ -f "$PY" ] || exit 0
. "$LIB/_find_python.sh"
[ -n "$PYTHON" ] || exit 0
"$PYTHON" "$PY" "$@"
exit 0
