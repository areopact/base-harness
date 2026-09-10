#!/bin/sh
# Offline hook test driver (POSIX sh).
#
# 1. Runs the Python suite (pytest when importable, else unittest discovery).
# 2. Pipes every fixture under tests/fixtures/<group>/ through the wrapper
#    that serves that group and diffs the wrapper's stdout against
#    tests/expected/<group>/<name>.expected, byte for byte after trailing
#    newlines are dropped. The wrapper must exit 0 in every case.
# 3. Smokes the Codex/OpenCode dispatcher with one deny fixture.
#
# Hermetic: writes nothing outside the operating system temporary directory,
# performs no network call, and starts no runtime.

case "$0" in
  */*) SCRIPT_DIR=${0%/*} ;;
  *\\*) SCRIPT_DIR=${0%\\*} ;;
  *) SCRIPT_DIR=. ;;
esac
SCRIPT_DIR=$(cd "$SCRIPT_DIR" && pwd)
HOOKS=$(cd "$SCRIPT_DIR/.." && pwd)
ROOT=$(cd "$HOOKS/../.." && pwd)

# Pin structure lookups to the template's shipped default (test-only
# override, see hook_io.py) so the fixture replay below stays deterministic
# on any host: an adopted host's structure.json can carry a different git
# mode and unset lanes, which would flip a fixture's expected verdict.
export HARNESS_STRUCTURE_FILE="$ROOT/harness/tools/templates/structure.default.json"

. "$HOOKS/lib/_find_python.sh"
if [ -z "$PYTHON" ]; then
  echo "FAIL: no working Python interpreter on PATH" >&2
  exit 1
fi

cd "$ROOT" || exit 1
if "$PYTHON" -c "import pytest" >/dev/null 2>&1; then
  "$PYTHON" -m pytest "$SCRIPT_DIR" -q -p no:cacheprovider || exit 1
else
  "$PYTHON" -m unittest discover -s "$SCRIPT_DIR" -p 'test_*.py' || exit 1
fi

fail=0
count=0

run_group() {
  group=$1
  wrapper=$2
  for fixture in "$SCRIPT_DIR/fixtures/$group"/*.json; do
    [ -f "$fixture" ] || continue
    name=$(basename "$fixture" .json)
    expected_file="$SCRIPT_DIR/expected/$group/$name.expected"
    case "$name" in
      *-flag-off)
        actual=$(unset HARNESS_READ_DENY; sh "$wrapper" < "$fixture") ;;
      *)
        if [ "$group" = "read-deny" ]; then
          actual=$(HARNESS_READ_DENY=1 sh "$wrapper" < "$fixture")
        else
          actual=$(sh "$wrapper" < "$fixture")
        fi ;;
    esac
    rc=$?
    expected=$(cat "$expected_file" 2>/dev/null)
    count=$((count + 1))
    if [ "$rc" -ne 0 ]; then
      echo "FAIL: $group/$name: wrapper exited $rc" >&2
      fail=1
    elif [ "$actual" != "$expected" ]; then
      echo "FAIL: $group/$name: stdout differs from expected" >&2
      echo "  expected: $expected" >&2
      echo "  actual:   $actual" >&2
      fail=1
    fi
  done
}

run_group guard "$HOOKS/pre-tool-use/dangerous-ops-guard.sh"
run_group openpyxl "$HOOKS/pre-tool-use/openpyxl-guard.sh"
run_group frontmatter "$HOOKS/post-tool-use/frontmatter-guard.sh"
run_group read-deny "$HOOKS/pre-tool-use/read-deny.sh"
# write-deny is shipped off; its group replays against its own structure file.
PINNED_STRUCTURE=$HARNESS_STRUCTURE_FILE
export HARNESS_STRUCTURE_FILE="$SCRIPT_DIR/fixtures/write-deny-structure.json"
run_group write-deny "$HOOKS/pre-tool-use/write-deny.sh"
if [ -n "$PINNED_STRUCTURE" ]; then export HARNESS_STRUCTURE_FILE=$PINNED_STRUCTURE; else unset HARNESS_STRUCTURE_FILE; fi

[ "$fail" -eq 0 ] || exit 1
echo "wrapper fixture diff: $count fixtures PASS"

actual=$(sh "$HOOKS/codex-dispatch.sh" --runtime codex --event PreToolUse \
  < "$SCRIPT_DIR/fixtures/guard/bypass-force-push-main.json")
case "$actual" in
  *'"permissionDecision": "deny"'*) ;;
  *) echo "FAIL: POSIX dispatcher smoke test" >&2; exit 1 ;;
esac
echo "POSIX dispatcher smoke: PASS"
exit 0
