# Workstation kit

Optional terminal setup for running Claude Code, Codex, and OpenCode side by side under [Herdr](https://herdr.dev) in [Alacritty](https://alacritty.org), with a five-line Claude Code status line from [ccstatusline](https://github.com/sirmalloc/ccstatusline). It is the configuration the maintainer works in every day, cleaned of personal paths.

This folder is not part of the kernel. Bootstrap, `init.py`, and `adopt.py` never read it, nothing here lands in a repository, and every file goes to your user configuration folders only when you run the installer. Skip it entirely if you use another terminal.

## What you get

- **Shift+Enter inserts a newline** in the Claude Code prompt under Herdr, instead of sending the message.
- **Agent and tab switching from the keyboard:** Ctrl+Tab and Ctrl+Shift+Tab move between agents in Herdr's sidebar; Ctrl+Alt+] and Ctrl+Alt+[ move between tabs (the Herdr prefix forms `ctrl+b` then `n` or `p` still work).
- **A sidebar coloured by runtime:** Claude Code orange, Codex blue, OpenCode grey, each with its tab, workspace, and state icon.
- **A status line** with five rows: context use, model, thinking effort, and output style; token totals and speed; session name, clock, cost, free memory, and the skills invoked; plan usage with the five-hour and weekly reset timers; git root, branch, changes, and worktree.

| File | Goes to (Windows) | Goes to (macOS, Linux) |
|---|---|---|
| `workstation/alacritty/alacritty.toml` | `%APPDATA%\alacritty\alacritty.toml` | `~/.config/alacritty/alacritty.toml` (or under `$XDG_CONFIG_HOME`) |
| `workstation/herdr/config.toml` | `%APPDATA%\herdr\config.toml` | `~/.config/herdr/config.toml` |
| `workstation/ccstatusline/settings.json` | `~/.config/ccstatusline/settings.json` | `~/.config/ccstatusline/settings.json` |
| `workstation/claude/keybindings.json` | `~/.claude/keybindings.json` | `~/.claude/keybindings.json` |
| `workstation/claude/settings.snippet.json` | merged by hand into `~/.claude/settings.json` | same |

`HERDR_CONFIG_PATH` and `CLAUDE_CONFIG_DIR` move the Herdr and Claude Code targets when set; the installer honours both.

## Why Shift+Enter needs three files

A newline in the prompt passes through three layers, and each needs its part:

1. **Alacritty** sends Shift+Enter as a bare line feed (`alacritty.toml`: `{ key = "Enter", mods = "Shift", chars = "\u000A" }`). Without the binding, Shift+Enter is a plain Enter and sends the message.
2. **Herdr** answers the kitty keyboard protocol query, so Claude Code switches to that protocol, and the line feed reaches it as **ctrl+enter**, not as shift+enter.
3. **Claude Code** turns ctrl+enter into a newline only through `keybindings.json` (`"ctrl+enter": "chat:newline"`, next to `"shift+enter"` for terminals that report Shift+Enter directly).

Copying the terminal configurations without `keybindings.json` leaves Shift+Enter dead under Herdr. `\` then Enter inserts a newline with no binding at all. Ctrl+J sends the same line feed as Shift+Enter, so under Herdr it works only with the keybinding too. Alt+Enter does not reach Claude Code under Alacritty, so it is not bound. Layers 2 and 3 were observed live on the setup under Tested with; nothing in this folder can prove them on another stack, which is what the key-probe in Check it works is for.

Codex and OpenCode newline behaviour under this stack has not been tested; the bindings above are Claude Code's.

## Install

1. Install the tools: Alacritty from https://alacritty.org, Herdr as in [`START_HERE.md`](../START_HERE.md) section 2, and ccstatusline globally with `npm install -g ccstatusline`. Install it globally and call it by name: launching it through `npx` on every prompt costs seconds per call, which is enough for hooks to time out when several sessions run at once. Update it with `npm install -g ccstatusline@latest`.
2. From the repository root, look first, then copy:

   ```
   python workstation/install.py --diff
   python workstation/install.py --apply
   ```

   The first command writes nothing and prints `new`, `same`, `differs`, `link`, or `blocked` for each target, with a diff for each one that differs. `--apply` writes the new ones, leaves identical ones alone, and skips any file that differs from the kit; it exits 1 when it skipped anything. To replace a differing file, add `--force`: the old file is first copied to `<name>.bak-<timestamp>` beside it, with a `-1`, `-2` suffix if that name is taken. A target that is a symbolic link (say, into your dotfiles repository) or is not a regular file is always skipped; edit it by hand. Limit a run with `--only alacritty,herdr,ccstatusline,claude-keybindings` (any subset).
3. Merge `workstation/claude/settings.snippet.json` into `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR/settings.json` when that is set) by hand: the `statusLine` block, and the two `ccstatusline --hook` entries under `hooks.PreToolUse` (matcher `Skill`) and `hooks.UserPromptSubmit`. Add them next to any hooks you already have rather than replacing the arrays. The hooks feed the status line's skills widget; without them the rest of the status line still works. The installer never edits this file because it also holds your permissions, plugins, and other hooks.
4. Edit the commented placeholders if you want them: the shell and starting folder in `alacritty.toml` (`[general]`, `[terminal.shell]`) and in Herdr's `config.toml` (`[terminal]`). On macOS, delete the Ctrl+V paste binding in `alacritty.toml`; Cmd+V already pastes there.

## Check it works

- `herdr config check` prints `Config: ok`. A running Herdr server picks up changes with `herdr server reload-config`.
- Alacritty reloads its configuration on save; open a new window if a binding does not take.
- In Claude Code inside a Herdr pane, Shift+Enter starts a new line in the prompt. `keybindings.json` reloads without a restart.
- The status line shows five rows. The plan usage row reads a Claude subscription's limits and may stay empty on API-key billing.
- Ctrl+Tab moves the sidebar selection to the next agent.

If Shift+Enter still sends the message, find out what the stack delivers: bind a candidate key name (for example `"ctrl+j": "chat:newline"`) in `keybindings.json`, press the physical key, and see whether it inserts a newline. The file reloads live, so each guess costs one keypress.

## Undo

Every file `--force` replaced has a `<name>.bak-<timestamp>` copy (or `-1`, `-2` suffixed) beside it; rename it back. A file the installer created new can be deleted. Remove the merged entries from `settings.json` by hand.

## Tested with

Windows 11 with Alacritty 0.17.0, Herdr 0.9.0, Claude Code 2.1.304, and ccstatusline 2.2.32. The macOS and Linux targets follow each tool's documented paths and are covered by the installer's tests, but this setup has not been run live on either.
