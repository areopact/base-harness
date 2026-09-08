#!/bin/sh
# Launch OpenCode with the harness-managed skill root.
#
# OpenCode also searches other runtimes' skill directories, so a direct
# `opencode` invocation can see unselected or runtime-specific wrappers. This
# wrapper disables those external roots and refuses to start when the selected
# skill tree has not been materialized, which keeps skill selection enforcing.
# The doctor fails when the OpenCode skill link does not resolve into that tree.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Four levels up from the launch directory is the repository root.
ROOT="$SCRIPT_DIR"
for _level in 1 2 3 4; do ROOT="$(dirname "$ROOT")"; done
JUNCTIONS="$ROOT"/harness/bootstrap/junctions.json

selected_dir=""
for candidate in python3 python py; do
  if command -v "$candidate" >/dev/null 2>&1; then
    selected_dir="$("$candidate" - "$JUNCTIONS" <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(data["per_skill"]["opencode"]["dst_dir"])
except Exception:
    pass
PY
)"
    [ -n "$selected_dir" ] && break
  fi
done

if [ -z "$selected_dir" ]; then
  echo "opencode-harness: cannot read per_skill.opencode.dst_dir from $JUNCTIONS; run bootstrap first" >&2
  exit 1
fi
if [ ! -d "$ROOT/$selected_dir" ]; then
  echo "opencode-harness: selected skill tree $selected_dir is not materialized; run bootstrap first" >&2
  exit 1
fi

export OPENCODE_DISABLE_EXTERNAL_SKILLS=1
cd "$ROOT"
exec opencode "$@"
