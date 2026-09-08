"""OpenCode calls every export of every file inside a linked plugins/
directory as a plugin factory with the PluginInput object. A helper export
(not a plugin factory) throws on that call, which is exactly what broke the
bridge before harness-bridge.js was split from its private helper module
(harness/adapters/opencode/lib/harness-bridge-internal.js, not linked into
.opencode/plugins/). This test proves the materialized plugin file exports
only callables that survive being invoked as a plugin factory.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path

from ._paths import ROOT, bind_unittest

from urllib.request import pathname2url

MATERIALIZED_PLUGIN = ROOT / ".opencode" / "plugins" / "harness-bridge.js"
SOURCE_PLUGIN = ROOT / "harness" / "adapters" / "opencode" / "plugins" / "harness-bridge.js"

_PROBE = """
import * as mod from {plugin_path};
const repo = {repo_path};
const input = {{ directory: repo, worktree: repo }};
const results = [];
for (const [name, value] of Object.entries(mod)) {{
  if (typeof value !== "function") {{
    results.push({{ name, ok: false, error: "export is not a function" }});
    continue;
  }}
  try {{
    const returned = value(input);
    if (returned && typeof returned.then === "function") {{
      returned.catch(() => {{}});
    }}
    results.push({{ name, ok: true }});
  }} catch (error) {{
    results.push({{ name, ok: false, error: String(error && error.message || error) }});
  }}
}}
process.stdout.write(JSON.stringify(results));
"""


def _run_probe(plugin_path: Path, repo_path: Path) -> list[dict]:
    plugin_url = "file:" + pathname2url(str(plugin_path.resolve()))
    script = textwrap.dedent(_PROBE).format(
        plugin_path=json.dumps(plugin_url),
        repo_path=json.dumps(repo_path.as_posix()),
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-"],
        input=script, text=True, capture_output=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"node probe failed: {result.stderr}")
    return json.loads(result.stdout)


def test_materialized_plugin_exports_are_all_safe_factories():
    if not shutil.which("node"):
        raise unittest.SkipTest("node is not installed; plugin export probe skipped")
    plugin_path = MATERIALIZED_PLUGIN if MATERIALIZED_PLUGIN.is_file() else SOURCE_PLUGIN
    results = _run_probe(plugin_path, ROOT)
    assert results, "the plugin file exported nothing to probe"
    failures = [entry for entry in results if not entry["ok"]]
    assert not failures, f"plugin export(s) threw when invoked as a factory: {failures}"


bind_unittest(globals(), "PluginExportsBridge")
