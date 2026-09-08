#!/bin/sh
# pre-bootstrap-detector (SessionStart wrapper, POSIX sh)
#
# Event: SessionStart. Matcher: (none).
# Decision: advisory naming the bootstrap command for this platform, or silence when every destination is materialized.
# Delegates to harness/hooks/lib/pre_bootstrap_detector.py, which reads the JSON envelope on stdin and
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
PY="$LIB/pre_bootstrap_detector.py"
[ -f "$PY" ] || exit 0
. "$LIB/_find_python.sh"
[ -n "$PYTHON" ] || exit 0
"$PYTHON" "$PY" "$@"
exit 0
