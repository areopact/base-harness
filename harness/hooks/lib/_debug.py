"""Opt-in debug trace for harness hooks.

Enabled only when the environment variable HARNESS_HOOK_DEBUG_DIR names a
directory. One tab-separated line per hook invocation is appended to
<dir>/hooks-debug.log:

  <iso8601-ts>\t<event>\t<exit_code>\t<out_bytes>\t<latency_ms>\t<extra>

When the variable is unset nothing is written anywhere: hooks hold no state,
and there is no default log path. The tracer never raises.

Usage from a hook lib:

    from _debug import debug

    def main():
        debug.start()
        ...
        debug.end("hook-name", exit_code=0, out_bytes=len(out))
"""
import os
import sys
import time
from datetime import datetime


class _Debug:
    """Single instance imported as `debug` from this module."""

    def __init__(self):
        self.directory = os.environ.get("HARNESS_HOOK_DEBUG_DIR") or ""
        self.enabled = bool(self.directory)
        self._t0 = None

    def start(self):
        if self.enabled:
            self._t0 = time.perf_counter()

    def end(self, event, exit_code=0, out_bytes=0, extra=""):
        if not self.enabled:
            return
        try:
            t0 = self._t0 if self._t0 is not None else time.perf_counter()
            latency_ms = int((time.perf_counter() - t0) * 1000)
            ts = datetime.now().isoformat(timespec="seconds")
            parts = [ts, event, str(exit_code), str(out_bytes), f"{latency_ms}ms"]
            if extra:
                parts.append(extra)
            target = os.path.join(self.directory, "hooks-debug.log")
            with open(target, "a", encoding="utf-8") as handle:
                handle.write("\t".join(parts) + "\n")
        except Exception:
            pass


debug = _Debug()


if __name__ == "__main__":
    print("enabled" if debug.enabled else "disabled", file=sys.stderr)
