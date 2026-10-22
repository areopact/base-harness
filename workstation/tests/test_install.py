"""workstation/install.py resolves each platform's targets, reports each target's state on a dry run,
shows a diff that survives CRLF-only changes, writes only new targets with --apply, skips links and
non-files, and backs up before --force replaces a file without ever overwriting an older backup."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

import install  # noqa: E402


class TargetTests(unittest.TestCase):
    def test_windows_targets(self):
        home = Path("home")
        found = {i.name: i.target for i in install.targets({"APPDATA": "roaming"}, home, windows=True)}
        self.assertEqual(found["alacritty"], Path("roaming") / "alacritty" / "alacritty.toml")
        self.assertEqual(found["herdr"], Path("roaming") / "herdr" / "config.toml")
        self.assertEqual(found["ccstatusline"], home / ".config" / "ccstatusline" / "settings.json")
        self.assertEqual(found["claude-keybindings"], home / ".claude" / "keybindings.json")

    def test_windows_fallbacks_and_herdr_override(self):
        home = Path("home")
        found = {i.name: i.target for i in install.targets({"HERDR_CONFIG_PATH": "h.toml"}, home, windows=True)}
        self.assertEqual(found["alacritty"], home / "AppData" / "Roaming" / "alacritty" / "alacritty.toml")
        self.assertEqual(found["herdr"], Path("h.toml"))

    def test_posix_targets_and_overrides(self):
        home = Path("home")
        found = {i.name: i.target for i in install.targets({}, home, windows=False)}
        self.assertEqual(found["alacritty"], home / ".config" / "alacritty" / "alacritty.toml")
        self.assertEqual(found["herdr"], home / ".config" / "herdr" / "config.toml")
        env = {"XDG_CONFIG_HOME": "xdg", "HERDR_CONFIG_PATH": "h.toml", "CLAUDE_CONFIG_DIR": "cc"}
        found = {i.name: i.target for i in install.targets(env, home, windows=False)}
        self.assertEqual(found["alacritty"], Path("xdg") / "alacritty" / "alacritty.toml")
        self.assertEqual(found["herdr"], Path("h.toml"))
        self.assertEqual(found["claude-keybindings"], Path("cc") / "keybindings.json")

    def test_every_source_exists_and_parses(self):
        for item in install.targets({}, Path("home"), windows=False):
            text = item.source.read_text(encoding="utf-8")
            if item.source.suffix == ".json":
                json.loads(text)
            else:
                tomllib.loads(text)
        json.loads((KIT / "claude" / "settings.snippet.json").read_text(encoding="utf-8"))

    def test_newline_bound_in_alacritty_and_claude_code(self):
        alacritty = tomllib.loads((KIT / "alacritty" / "alacritty.toml").read_text(encoding="utf-8"))
        shift_enter = [b for b in alacritty["keyboard"]["bindings"] if b["key"] == "Enter" and b["mods"] == "Shift"]
        self.assertEqual([b.get("chars") for b in shift_enter], ["\n"])
        chat = json.loads((KIT / "claude" / "keybindings.json").read_text(encoding="utf-8"))["bindings"][0]
        self.assertEqual(chat["context"], "Chat")
        self.assertEqual(chat["bindings"]["ctrl+enter"], "chat:newline")
        self.assertEqual(chat["bindings"]["shift+enter"], "chat:newline")


class InstallTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.items = install.targets({}, self.home, windows=False)
        self.patch = mock.patch.object(install, "targets", lambda env, home, windows: self.items)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self._tmp.cleanup()

    def run_main(self, *argv: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = install.main(list(argv))
        return code, out.getvalue()

    def write_target(self, index: int, data: bytes) -> install.Item:
        item = self.items[index]
        item.target.parent.mkdir(parents=True, exist_ok=True)
        item.target.write_bytes(data)
        return item

    def label(self, out: str, name: str) -> str:
        return next(line.split()[1] for line in out.splitlines() if line.startswith(name + " "))

    def test_dry_run_reports_states_and_writes_nothing(self):
        self.write_target(0, self.items[0].source.read_bytes())
        self.write_target(1, b"mine\n")
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertEqual(self.label(out, "alacritty"), "same")
        self.assertEqual(self.label(out, "herdr"), "differs")
        self.assertEqual(self.label(out, "ccstatusline"), "new")
        self.assertFalse(self.items[2].target.exists())
        self.assertEqual(self.items[1].target.read_bytes(), b"mine\n")

    def test_diff_shows_changed_lines_and_crlf_only_changes(self):
        self.write_target(1, b"mine\n")
        _, out = self.run_main("--only", "herdr", "--diff")
        self.assertIn("-mine", out)
        self.assertIn("+[theme]", out)
        source = self.items[1].source.read_bytes()
        self.write_target(1, source.replace(b"\n", b"\r\n"))
        _, out = self.run_main("--only", "herdr", "--diff")
        self.assertIn("+[theme]", out)
        self.assertIn("CRLF", out)

    def test_apply_writes_new_and_skips_differing(self):
        keep = self.write_target(1, b"mine\n").target
        code, out = self.run_main("--apply")
        self.assertEqual(code, 1)
        self.assertEqual(keep.read_bytes(), b"mine\n")
        for item in self.items[:1] + self.items[2:]:
            self.assertEqual(item.target.read_bytes(), item.source.read_bytes())
        code, out = self.run_main("--only", "alacritty", "--apply")
        self.assertEqual(code, 0)
        self.assertIn("same, left as is", out)

    def test_force_backs_up_before_replacing(self):
        item = self.write_target(0, b"mine\n")
        code, _ = self.run_main("--only", "alacritty", "--apply", "--force")
        self.assertEqual(code, 0)
        self.assertEqual(item.target.read_bytes(), item.source.read_bytes())
        backups = list(item.target.parent.glob("alacritty.toml.bak-*"))
        self.assertEqual([b.read_text(encoding="utf-8") for b in backups], ["mine\n"])

    def test_backup_never_overwrites_an_existing_backup(self):
        item = self.write_target(0, b"first\n")
        taken = install.backup_path(item.target, "stamp")
        taken.write_bytes(b"older\n")
        ok, _ = install.install(item, force=True, stamp="stamp")
        self.assertTrue(ok)
        self.assertEqual(taken.read_bytes(), b"older\n")
        self.assertEqual((item.target.parent / "alacritty.toml.bak-stamp-1").read_bytes(), b"first\n")
        self.assertEqual(install.backup_path(item.target, "stamp").name, "alacritty.toml.bak-stamp-2")

    def test_directory_target_is_blocked_not_a_crash(self):
        self.items[3].target.mkdir(parents=True)
        code, out = self.run_main("--only", "claude-keybindings")
        self.assertEqual((code, self.label(out, "claude-keybindings")), (0, "blocked"))
        code, out = self.run_main("--only", "claude-keybindings", "--apply", "--force")
        self.assertEqual(code, 1)
        self.assertIn("not a readable regular file", out)

    def test_symlink_target_is_never_written_through(self):
        real = self.home / "dotfiles" / "alacritty.toml"
        real.parent.mkdir()
        real.write_text("mine\n", encoding="utf-8")
        self.items[0].target.parent.mkdir(parents=True)
        try:
            os.symlink(real, self.items[0].target)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links unavailable to this user")
        code, out = self.run_main("--only", "alacritty", "--apply", "--force")
        self.assertEqual(code, 1)
        self.assertIn("symbolic link", out)
        self.assertEqual(real.read_text(encoding="utf-8"), "mine\n")

    def test_usage_errors(self):
        with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
            for argv in (["--force"], ["--only", "nope"]):
                with self.assertRaises(SystemExit) as raised:
                    install.main(argv)
                self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
