#!/bin/sh
# Shared Python interpreter discovery (POSIX sh).
#
# Sourced by every harness/hooks/*/*.sh wrapper and by codex-dispatch.sh.
# Sets PYTHON to the first candidate that both resolves on PATH and actually
# runs, or to the empty string when none does. The caller decides what to do;
# every wrapper treats an empty PYTHON as silence and exits 0.
#
# Each candidate is execute-probed, not merely resolved: a platform may expose
# a stub named python or python3 that resolves on PATH but exits non-zero
# without running any code, or blocks waiting for an interactive install.
# Trusting the resolve alone would hand that stub the hook payload and turn
# its failure into a false verdict. Two guards: a candidate that resolves
# under a WindowsApps directory is an app-execution alias and is skipped
# without being run, and the probe itself is capped with `timeout` where
# that command exists. The probe costs one short process; the hook stays
# correct on every host.
#
# UTF-8 stdio is forced for the child so non-ASCII content in identity or
# Markdown files survives on hosts whose console default is a narrow code page.

PYTHON=""
if command -v timeout >/dev/null 2>&1; then
  _probe_timeout="timeout 5"
else
  _probe_timeout=""
fi
for _candidate in python3 python py; do
  _resolved=$(command -v "$_candidate" 2>/dev/null) || continue
  [ -n "$_resolved" ] || continue
  case "$_resolved" in
    */WindowsApps/*|*\\WindowsApps\\*) continue ;;
  esac
  $_probe_timeout "$_resolved" -c "pass" >/dev/null 2>&1 </dev/null || continue
  PYTHON="$_resolved"
  break
done
unset _probe_timeout

if [ -n "$PYTHON" ]; then
  PYTHONUTF8=1
  PYTHONIOENCODING=utf-8
  PYTHONDONTWRITEBYTECODE=1
  export PYTHONUTF8 PYTHONIOENCODING PYTHONDONTWRITEBYTECODE
fi

unset _candidate
unset _resolved
