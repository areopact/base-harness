#!/bin/sh
# Single-process hook dispatcher entry (POSIX sh) for Codex and OpenCode.
#
# Event: any of SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop.
# Matcher: set by the runtime registration (harness/adapters/codex/hooks.json,
# harness/adapters/opencode/plugins/harness-bridge.js). Decision: whatever the
# routed lib modules return, merged by harness/hooks/lib/dispatch.py into one JSON line:
# silence, an advisory, or (PreToolUse only) a deny. This wrapper exits 0
# unconditionally; the decision lives in the JSON, never in the exit code.
#
# Arguments: --runtime <codex|opencode> --event <Event>. A bare first argument
# is accepted as the event for compatibility. An unknown event or runtime, a
# missing Python, or a missing dispatcher is silence.

RUNTIME="codex"
EVENT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --runtime) shift; RUNTIME="${1:-}" ;;
    --runtime=*) RUNTIME="${1#--runtime=}" ;;
    --event) shift; EVENT="${1:-}" ;;
    --event=*) EVENT="${1#--event=}" ;;
    *) [ -n "$EVENT" ] || EVENT="$1" ;;
  esac
  [ $# -gt 0 ] && shift
done

case "$EVENT" in
  SessionStart|UserPromptSubmit|PreToolUse|PostToolUse|Stop) ;;
  *) exit 0 ;;
esac
case "$RUNTIME" in
  codex|opencode) ;;
  *) exit 0 ;;
esac

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
PY="$DIR/lib/dispatch.py"
[ -f "$PY" ] || exit 0
. "$DIR/lib/_find_python.sh"
[ -n "$PYTHON" ] || exit 0
"$PYTHON" "$PY" --event "$EVENT" --runtime "$RUNTIME"
exit 0
