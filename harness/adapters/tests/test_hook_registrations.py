"""P5-3: every hook implementation is registered in the adapters that support it.

The expected implementation list below is the adapter package's own statement
of what it registers. When harness/registry/runtimes.json is present, its
hook_events block is cross-checked too; when absent, the registry checks are
skipped and the inline expectations still run.
"""

from __future__ import annotations

import re
import unittest

from ._paths import ADAPTERS, ROOT, bind_unittest, read_json, read_text

RUNTIMES_JSON = ROOT / "harness" / "registry" / "runtimes.json"
CLAUDE_SETTINGS = ADAPTERS / "claude" / "settings.base.json"
CODEX_HOOKS = ADAPTERS / "codex" / "hooks.json"
OPENCODE_BRIDGE = ADAPTERS / "opencode" / "plugins" / "harness-bridge.js"
# The dispatcher-command strings live in the bridge's private helper module
# (kept out of the linked plugins/ directory so OpenCode never treats it as
# a second plugin factory); combine both files where those strings are checked.
OPENCODE_BRIDGE_LIB = ADAPTERS / "opencode" / "lib" / "harness-bridge-internal.js"

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")

# What the Claude adapter registers, as <event-dir>/<hook-name>, per event.
EXPECTED_CLAUDE = {
    "SessionStart": ["session-start/load-identity", "session-start/pre-bootstrap-detector"],
    "PreToolUse": [
        "pre-tool-use/memory-first",
        "pre-tool-use/dangerous-ops-guard",
        "pre-tool-use/openpyxl-guard",
        "pre-tool-use/delegation-guard",
    ],
    "PostToolUse": ["post-tool-use/frontmatter-guard", "post-tool-use/prose-lint", "post-tool-use/delegation-guard"],
    "Stop": ["stop/close-the-loop"],
}

# Matcher expected per Claude hook (None means no matcher: fires for every source).
EXPECTED_CLAUDE_MATCHERS = {
    "session-start/load-identity": None,
    "session-start/pre-bootstrap-detector": None,
    "pre-tool-use/memory-first": "WebSearch|WebFetch",
    "pre-tool-use/dangerous-ops-guard": "Bash",
    "pre-tool-use/openpyxl-guard": "Bash",
    "pre-tool-use/delegation-guard": "Agent|Workflow",
    "post-tool-use/frontmatter-guard": "Write|Edit",
    "post-tool-use/prose-lint": "Write|Edit",
    "post-tool-use/delegation-guard": "Agent|Workflow",
    "stop/close-the-loop": None,
}

NEVER_REGISTERED = "pre-tool-use/read-deny"

COMMAND_SHAPE = re.compile(r'^bash "\$\{CLAUDE_PROJECT_DIR\}/harness/hooks/([a-z-]+)/([a-z-]+)\.sh"$')


def _claude_commands():
    data = read_json(CLAUDE_SETTINGS)
    for event, groups in data["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                yield event, group.get("matcher"), hook["command"]


def _claude_registered():
    registered = {}
    for event, matcher, command in _claude_commands():
        match = COMMAND_SHAPE.match(command)
        assert match, f"command does not have the quoted shape: {command}"
        registered.setdefault(event, []).append((f"{match.group(1)}/{match.group(2)}", matcher))
    return registered


def test_claude_registers_exactly_the_expected_implementations():
    registered = _claude_registered()
    for event, expected in EXPECTED_CLAUDE.items():
        names = [name for name, _ in registered.get(event, [])]
        assert names == expected, f"{event}: registered {names}, expected {expected}"
    assert set(registered) == set(EXPECTED_CLAUDE), "unexpected events registered"


def test_claude_matchers_match_the_tool_each_hook_reads():
    for event, entries in _claude_registered().items():
        for name, matcher in entries:
            assert matcher == EXPECTED_CLAUDE_MATCHERS[name], f"{event} {name}: matcher {matcher!r}"


def test_read_deny_is_registered_nowhere():
    for path in (CLAUDE_SETTINGS, CODEX_HOOKS, OPENCODE_BRIDGE):
        assert "read-deny" not in read_text(path), f"read-deny appears in {path.name}"
        assert "read_deny" not in read_text(path), f"read_deny appears in {path.name}"


def test_every_claude_command_quotes_the_project_dir_and_survives_backslashes():
    for _, _, command in _claude_commands():
        assert '"${CLAUDE_PROJECT_DIR}/' in command, f"project dir not quoted: {command}"
        assert "${CLAUDE_PROJECT_DIR}" not in command.replace('"${CLAUDE_PROJECT_DIR}/', ""), (
            f"an unquoted CLAUDE_PROJECT_DIR reference remains: {command}"
        )
        assert "\\" not in command, f"backslash in command string: {command}"
        assert command.count('"') == 2, f"expected exactly one quoted path: {command}"
        assert command.endswith('.sh"'), f"quote must close right after the script path: {command}"
        assert "$CLAUDE_PROJECT_DIR" not in command.replace("${CLAUDE_PROJECT_DIR}", ""), (
            f"use the braced form so a following slash is not read as part of the name: {command}"
        )


def test_codex_registers_one_dispatcher_entry_per_event():
    # Codex carries no UserPromptSubmit dispatcher entry: no implementation
    # exists for it and the empty block cost ~480ms per prompt for nothing.
    codex_events = tuple(event for event in EVENTS if event != "UserPromptSubmit")
    data = read_json(CODEX_HOOKS)
    assert list(data) == ["hooks"]
    assert tuple(data["hooks"]) == codex_events, f"events out of order or missing: {list(data['hooks'])}"
    for event in codex_events:
        groups = data["hooks"][event]
        assert len(groups) == 1, f"{event}: expected one matcher group"
        hooks = groups[0]["hooks"]
        assert len(hooks) == 1, f"{event}: expected one dispatcher hook"
        hook = hooks[0]
        assert hook["type"] == "command"
        assert hook["command"] == (
            "bash -c 'cd \"$(git rev-parse --show-toplevel)\" && bash harness/hooks/codex-dispatch.sh"
            f" --runtime codex --event {event}'"
        ), hook["command"]
        assert hook["commandWindows"].endswith(f"codex-dispatch.ps1') -Runtime codex -Event {event}"), hook["commandWindows"]
        assert "git rev-parse --show-toplevel" in hook["command"]
        assert "git rev-parse --show-toplevel" in hook["commandWindows"]


def test_codex_hooks_have_no_comment_keys_anywhere():
    text = read_text(CODEX_HOOKS)
    assert '"_' not in text, "an underscore-prefixed key is present in hooks.json"


def test_codex_pretooluse_matcher_covers_the_tools_the_hooks_read():
    data = read_json(CODEX_HOOKS)
    matcher = data["hooks"]["PreToolUse"][0]["matcher"]
    for token in ("Bash", "shell_command", "WebSearch", "WebFetch", "Edit", "Write", "apply_patch", "Agent", "spawn_agent"):
        assert token in matcher.split("|"), f"PreToolUse matcher lacks {token}"
    post = data["hooks"]["PostToolUse"][0]["matcher"]
    for token in ("Edit", "Write", "apply_patch", "Agent", "spawn_agent"):
        assert token in post.split("|"), f"PostToolUse matcher lacks {token}"


def test_opencode_bridge_dispatches_pretooluse_and_sessionstart_through_the_dispatcher():
    text = read_text(OPENCODE_BRIDGE)
    lib_text = read_text(OPENCODE_BRIDGE_LIB)
    assert "codex-dispatch.sh" in lib_text and "codex-dispatch.ps1" in lib_text
    assert '"--runtime", "opencode"' in lib_text
    assert 'dispatch(root, "PreToolUse"' in text
    assert 'dispatch(root, "SessionStart"' in text
    assert '"tool.execute.before"' in text
    assert '"experimental.chat.system.transform"' in text
    assert 'permissionDecision === "deny"' in lib_text
    assert "throw new Error" in text
    for event in ("PostToolUse", "UserPromptSubmit", "Stop"):
        assert f'dispatch(root, "{event}"' not in text, f"OpenCode has no surface for {event}"


class RegistryCrossCheck(unittest.TestCase):
    """Cross-check against harness/registry/runtimes.json when it exists."""

    def setUp(self):
        if not RUNTIMES_JSON.exists():
            self.skipTest("harness/registry/runtimes.json not present; registry cross-check skipped")
        self.hook_events = read_json(RUNTIMES_JSON)["hook_events"]

    def _support(self, event: str, runtime: str, implementation: str) -> str:
        entry = self.hook_events[event]["runtimes"].get(runtime, {})
        override = entry.get("implementation_support", {})
        return override.get(implementation, entry.get("support", "unsupported"))

    def test_registry_implementations_appear_in_supporting_adapters(self):
        claude = {name for entries in _claude_registered().values() for name, _ in entries}
        codex_events = set(read_json(CODEX_HOOKS)["hooks"])
        bridge = read_text(OPENCODE_BRIDGE)
        for event, spec in self.hook_events.items():
            for implementation in spec.get("implementations", []):
                if implementation == NEVER_REGISTERED:
                    continue
                if self._support(event, "claude", implementation) != "unsupported":
                    self.assertIn(implementation, claude, f"claude lacks {implementation}")
                if self._support(event, "codex", implementation) != "unsupported":
                    self.assertIn(event, codex_events, f"codex dispatcher lacks {event}")
                if self._support(event, "opencode", implementation) != "unsupported":
                    self.assertIn(f'dispatch(root, "{event}"', bridge, f"opencode bridge lacks {event}")

    def test_read_deny_is_never_registered_even_if_the_registry_lists_it(self):
        for spec in self.hook_events.values():
            if NEVER_REGISTERED in spec.get("implementations", []):
                for path in (CLAUDE_SETTINGS, CODEX_HOOKS, OPENCODE_BRIDGE):
                    self.assertNotIn("read-deny", read_text(path))

    def test_claude_registers_nothing_the_registry_does_not_list(self):
        listed = {impl for spec in self.hook_events.values() for impl in spec.get("implementations", [])}
        for entries in _claude_registered().values():
            for name, _ in entries:
                self.assertIn(name, listed, f"{name} registered in claude settings but absent from runtimes.json")


bind_unittest(globals(), "HookRegistrationsBridge")
