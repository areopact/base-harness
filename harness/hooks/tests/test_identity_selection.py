"""H5: identity lane delivery, ordering, and deterministic truncation."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "lib"))

import load_identity  # noqa: E402

FIRST = "examples/IDENTITY.md"
SECOND = "examples/OPERATOR.md"


def seed(root, identity, limits=None, files=None):
    registry = Path(root) / "harness" / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "structure.json").write_text(json.dumps({"lanes": {"identity": identity}}), encoding="utf-8")
    limits = limits if limits is not None else {"claude": 700, "codex": 400}
    runtimes = {name: {"tier": "tier-1", "identity_context_limit": limit} for name, limit in limits.items()}
    runtimes["experimental-runtime"] = {"tier": "experimental", "identity_context_limit": 10}
    (registry / "runtimes.json").write_text(json.dumps({"runtimes": runtimes}), encoding="utf-8")
    for relative, text in (files or {}).items():
        target = Path(root) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


class IdentitySelectionTests(unittest.TestCase):
    def test_null_lane_emits_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            seed(temp, None, files={FIRST: "## Voice\nplain\n"})
            assert load_identity.render(temp, "claude") is None

    def test_configured_lane_with_no_files_emits_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            seed(temp, [FIRST, SECOND])
            assert load_identity.render(temp, "claude") is None

    def test_two_lane_files_are_delivered_in_declared_order(self):
        with tempfile.TemporaryDirectory() as temp:
            seed(temp, [SECOND, FIRST], files={
                FIRST: "---\naccess: internal\n---\n## Voice\nfirst body\n",
                SECOND: "---\naccess: internal\n---\n## Working style\nsecond body\n",
            })
            out = load_identity.render(temp, "claude")
            assert out.index("=== OPERATOR (%s) ===" % SECOND) < out.index("=== IDENTITY (%s) ===" % FIRST)
            assert "second body" in out and "first body" in out
            assert "access: internal" not in out

    def test_secret_labeled_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as temp:
            seed(temp, [FIRST, SECOND], files={
                FIRST: "---\naccess: secret\n---\n## Voice\nhidden body\n",
                SECOND: "## Working style\nvisible body\n",
            })
            out = load_identity.render(temp, "claude")
            assert "hidden body" not in out and "visible body" in out

    def test_over_budget_input_truncates_deterministically_with_the_exact_suffix(self):
        body = "## Voice\n" + ("voice words. " * 60) + "\n\n## Values\n" + ("value words. " * 60) + "\n\n## Anti-patterns\n" + ("anti words. " * 60)
        with tempfile.TemporaryDirectory() as temp:
            seed(temp, [FIRST], files={FIRST: body})
            first = load_identity.render(temp, "claude")
            second = load_identity.render(temp, "claude")
            assert first == second
            assert len(first) <= 700
            assert "read %s on demand]" % FIRST in first
            note = [line for line in first.splitlines() if line.startswith("[identity truncated at ")]
            assert len(note) == 1
            assert note[0].endswith("chars; read %s on demand]" % FIRST)
            # section priority: the first section is kept whole before any later one starts
            assert "## Voice" in first
            assert "## Anti-patterns" not in first

    def test_cap_comes_from_runtimes_json_per_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            seed(temp, [FIRST], limits={"claude": 650, "codex": 320})
            assert load_identity.identity_limit("claude", temp) == 650
            assert load_identity.identity_limit("codex", temp) == 320
            # unknown or unnamed runtime: the smallest tier-1 value, never the experimental one
            assert load_identity.identity_limit(None, temp) == 320
            assert load_identity.identity_limit("nonexistent", temp) == 320

    def test_missing_registry_uses_the_fixed_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            assert load_identity.identity_limit("claude", temp) == load_identity.FALLBACK_LIMIT

    def test_rendered_output_respects_the_runtime_cap(self):
        body = "## Voice\n" + ("voice words. " * 200)
        with tempfile.TemporaryDirectory() as temp:
            seed(temp, [FIRST, SECOND], limits={"claude": 900, "codex": 300}, files={FIRST: body, SECOND: body})
            claude = load_identity.render(temp, "claude")
            codex = load_identity.render(temp, "codex")
            assert len(claude) <= 900
            assert len(codex) <= 300
            assert len(codex) < len(claude)

    def test_truncate_identity_is_pure_and_bounded(self):
        text = "intro\n\n## A\n" + ("a " * 100) + "\n## B\n" + ("b " * 100)
        note_length = len(load_identity.TRUNCATION_NOTE.format(limit=120, path=FIRST))
        for limit in (40, 120, 260, 5000):
            with self.subTest(limit=limit):
                out = load_identity.truncate_identity(text, limit, FIRST)
                assert len(out) <= limit
                assert out == load_identity.truncate_identity(text, limit, FIRST)
                if len(text) <= limit:
                    assert out == text
                elif limit > note_length:
                    assert out.endswith("chars; read %s on demand]" % FIRST)
                    # a cut keeps the bulk of its budget instead of collapsing to a heading
                    assert len(out) >= limit // 2

    def test_single_paragraph_body_is_cut_at_a_word_not_its_heading(self):
        text = "## Voice\n" + ("voice words. " * 200)
        out = load_identity.truncate_identity(text, 400, FIRST)
        assert len(out) <= 400
        assert len(out) >= 300
        assert out.startswith("## Voice\nvoice words.")

    def test_runtime_from_argv_and_environment(self):
        assert load_identity.runtime_from(["--runtime", "codex"], {}) == "codex"
        assert load_identity.runtime_from(["--runtime=opencode"], {}) == "opencode"
        assert load_identity.runtime_from([], {"HARNESS_RUNTIME": "claude"}) == "claude"
        assert load_identity.runtime_from([], {}) is None


if __name__ == "__main__":
    unittest.main()
