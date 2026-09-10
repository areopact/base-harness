#!/bin/sh
# write-deny (PreToolUse wrapper, POSIX sh)
#
# Event: PreToolUse. Matcher: Write|Edit|NotebookEdit (Claude Code); Codex and
# OpenCode reach the same module through harness/hooks/codex-dispatch.
# Decision: deny (permissionDecision in the JSON) for a target path matched by
# structure.json write_deny.globs and not by write_deny.except, or silence.
# Delegates to harness/hooks/lib/write_deny.py, which reads the JSON envelope on
# stdin and prints zero or one JSON line. Exits 0 unconditionally: a missing
# lib file or a missing Python is silence (fail open), and the decision lives
# in the JSON, never in the exit code.
#
# Shipped OFF: the default write_deny.globs is empty, so the module is silent
# until the host names the paths it reserves for its human authors.
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
PY="$LIB/write_deny.py"
[ -f "$PY" ] || exit 0
. "$LIB/_find_python.sh"
[ -n "$PYTHON" ] || exit 0
"$PYTHON" "$PY" "$@"
exit 0
