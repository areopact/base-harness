# Start here

Read this before anything else in the repository. It is written for two
people at once: anyone on your team, technical or not, and the one
technical person who sets the repository up for everyone else. This guide
calls that second person the champion.

## 1. What this gives you

This gives you an AI assistant that opens your repository the same way,
with the same rules, the same skills, and the same optional memory,
whichever tool you use: Claude Code, Codex CLI, or OpenCode. A repository
is the folder of files, tracked by git, that your team works in together.
A skill is a named, repeatable task the assistant can run on request, such
as reviewing a document or drafting a policy. A memory lane is a folder
the assistant is told to read and write for one kind of information, such
as decisions or standing knowledge, so it does not have to be told the
same fact twice.

## 2. Pick your path

Solo: one person, their own repository. Work lands directly on the
main branch. Personal notes stay inside the repository, in an untracked
folder nobody else's clone carries. There is no pull request step and no
separate verify command; the assistant checks its own work with the
built-in doctor. This is the default state of a fresh clone.

Team: a shared repository with more than one contributor. Work lands
on task branches, each reviewed before it merges. The assistant runs your
team's own verify command before it commits anything, and it opens a pull
request only when you ask for one. Personal notes live outside the
repository entirely, in a folder on each person's own computer, so a
private note never rides into a pull request by accident.

Decide by asking: will anyone else ever clone this repository and send you
a change? If yes, pick team; if you are genuinely the only person touching
it, pick solo, and switch later if that changes.

## 3. Prepare your computer (everyone)

You only need to install a tool if you plan to use it, and one AI tool
(Claude Code, Codex CLI, or OpenCode) is enough to start. If any install
command below fails, treat the vendor's own page as the source of truth;
installers change more often than this guide does.

### git

What it is: the version control system that tracks every change to the
repository. Install: Windows, `winget install --id Git.Git -e`; macOS,
`xcode-select --install` or `brew install git`. Source:
https://git-scm.com/downloads. Check: `git --version`. On Windows, Git for
Windows also installs Git Bash, and the harness hooks need `bash` to be
reachable, so keep that installer's defaults.

### GitHub account and GitHub CLI (gh)

What it is: your account for hosting the repository, plus a command-line
tool for opening and managing pull requests. Install: Windows,
`winget install --id GitHub.cli -e`; macOS, `brew install gh`. Source:
https://cli.github.com. Then sign in with `gh auth login`. Check:
`gh auth status`.

### Python 3.11 or newer

What it is: the language the bootstrap scripts, doctors, and lint tools
are written in. Install: Windows, `winget install --id Python.Python.3.12 -e`;
macOS, `brew install python`. Source: https://www.python.org/downloads.
Check: `python --version` or `python3 --version`.

### Claude Code

What it is: Anthropic's terminal AI coding assistant. Install: macOS and
Linux, `curl -fsSL https://claude.ai/install.sh | bash`; Windows
PowerShell, `irm https://claude.ai/install.ps1 | iex`. Source:
https://docs.anthropic.com/en/docs/claude-code. Needs a Claude
subscription or an API key. Check: `claude --version`.

### Codex CLI

What it is: OpenAI's terminal AI coding assistant. Install:
`npm install -g @openai/codex`, which needs Node.js from
https://nodejs.org. Needs a ChatGPT plan. Check: `codex --version`.

### OpenCode

What it is: a third terminal AI coding assistant that this repository also
supports. Install: macOS and Linux,
`curl -fsSL https://opencode.ai/install | bash`, or on any platform
`npm install -g opencode-ai`. Source: https://opencode.ai. Needs a
provider key. Check: `opencode --version`.

### Obsidian (optional but recommended)

What it is: a note-reading and note-writing app that opens a folder of
Markdown files as a linked notebook. Install from
https://obsidian.md/download, then open the repository folder as a vault
so you can read and write the notes in it directly. Recommended for
anyone on the team who is more comfortable reading notes than reading a
terminal.

### Herdr (optional)

What it is: a terminal workspace manager built for AI coding agents. A
background server keeps your terminal panes alive between sessions, and
you attach to a sidebar that shows every agent's state at a glance.
Install: macOS and Linux, `curl -fsSL https://herdr.dev/install.sh | sh`;
Windows PowerShell, `powershell -ExecutionPolicy Bypass -c "irm https://herdr.dev/install.ps1 | iex"`;
Windows Command Prompt, if PowerShell is blocked,
`curl.exe -fsSLo install.cmd https://herdr.dev/install.cmd && install.cmd && del install.cmd`.
Source: https://herdr.dev. Check: `herdr --version`. Only useful once you
are running more than one agent at a time; see section 6.

## 4. Solo path, step by step

1. Click Use this template on GitHub to create your own copy, or clone
   your copy, then `cd` into the folder.
   Check: `ls` (or `dir` on Windows) shows `README.md` and a `harness/`
   folder.

2. Run `python harness/tools/init.py --profile solo --yes`. It prints the
   solo preset it just set: git mode `main-only`, personal notes at
   `brain/local`, all five memory lanes at their shipped default,
   `contract.mode` `rendered`, and `/brain/local/` added to `.gitignore`.
   It then prints the next two commands to run: the pack selector and
   bootstrap. Then run `python harness/tools/init.py --brain` once: it
   creates the `brain/` folders the memory lanes point at (`brain/shared`
   is tracked and shared, `brain/local` stays on your computer), each with
   a README that says what goes there.
   Check: run `python harness/tools/init.py` with no flags; it prints the
   current host shape and confirms the profile reads `solo`; and
   `brain/shared/knowledge/` now exists.

3. Bootstrap for your platform. macOS or Linux:
   ```sh
   bash harness/bootstrap/bootstrap.sh
   ```
   Windows (PowerShell):
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File harness\bootstrap\bootstrap.ps1
   ```
   Check: macOS or Linux, `bash harness/bootstrap/bootstrap.sh --check`;
   Windows, `powershell -NoProfile -ExecutionPolicy Bypass -File harness\bootstrap\bootstrap.ps1 -Check`.
   Either prints that there is no drift.

4. Run the doctor for whichever tool you installed. All three, if you want
   the full picture:
   ```sh
   bash harness/bootstrap/doctor.sh                          # Claude Code
   python harness/bootstrap/doctor_codex.py --offline        # Codex CLI
   python harness/bootstrap/doctor_opencode.py --offline     # OpenCode
   ```
   On Windows without a POSIX shell, the Claude Code doctor is
   `powershell -NoProfile -ExecutionPolicy Bypass -File harness\bootstrap\doctor.ps1`.
   Check: each command ends in a line that starts with `Result:` and names
   `repository PASS`.

5. Optional: open the folder in Obsidian. Choose "Open folder as vault"
   and select the repository folder.
   Check: the file tree in Obsidian's left sidebar matches the files you
   see in your file manager.

6. Start your first session: run `claude` inside the folder, then type
   `/doctor`.
   Check: the assistant runs the same three doctor commands and reports
   each one's `Result:` line back to you.

7. Write a short note into `brain/shared/knowledge/` (any fact you want
   the assistant to remember next session), then ask for `/commit`.
   Check: the assistant reports the commit hash and subject, the exact
   paths it staged, the branch it verified (your default branch), the git
   mode it applied (`main-only`), which verification it ran and why, the
   host profile it applied (`solo`, so no pull request), and what it did
   with the decisions and knowledge lanes.

## 5. Team path, step by step

### For the champion

1. Create the repository: click Use this template on GitHub for a new
   one, or adopt an existing repository from a clone of this template:
   ```sh
   python harness/tools/adopt.py <path-to-your-repository> --apply
   ```
   Leaving off `--apply` (or `-y`) is a dry run: it prints every action
   and writes nothing, so run it once without the flag first and read what
   it plans to do.
   Check: `git status` and `git diff` in the target repository show
   exactly the files adopt described; review the diff and merge or delete
   every `.harness.md` sibling file it created before moving on.

2. Run `python harness/tools/init.py --profile team --yes`. On a brand new
   template clone, this sets the whole team preset in one pass: git mode
   `branches`, personal notes outside the repository at
   `~/.harness-local/<repo-name>`, and the team lane preset. On a
   repository that already configured its own lanes or git mode, which an
   adopted repository always does, `--yes` changes `host.profile` only
   and prints exactly what it kept. Then run
   `python harness/tools/init.py --brain` once so the shared memory folders
   under `brain/shared` exist for the whole team (the local folder is not
   used on a team repository; personal notes live outside it).
   Check: `python harness/tools/init.py` with no flags prints the current
   host shape; confirm it reads `team`.

3. Bootstrap for your platform, the same commands as the solo path above.
   Check: the same `--check` or `-Check` command reports no drift.

4. Commit the setup on a task branch, since git mode is now `branches`:
   ```sh
   git checkout -b <task-branch-name>
   git add <the files init.py and bootstrap created>
   git commit
   ```
   Check: `git branch --show-current` shows your task branch, not the
   default branch.

5. Push the branch:
   ```sh
   git push -u origin <task-branch-name>
   ```
   Check: the branch appears on GitHub, or `gh pr status` shows it as
   pushed.

6. Open the pull request:
   ```sh
   gh pr create
   ```
   Check: `gh pr view` opens and shows the pull request you just created.

7. Merge it through your team's usual review. The assistant never merges
   its own pull request; that is always a human decision.
   Check: GitHub shows the pull request as merged.

### For each member

1. Clone the repository and `cd` into it.
   Check: `ls` shows `README.md` and a `harness/` folder.

2. Bootstrap for your platform, the same commands as the solo path above.
   Check: `--check` or `-Check` reports no drift.

3. Run the three doctor commands from the solo path, step 4.
   Check: each ends in a `Result:` line naming `repository PASS`.

4. Your personal notes live outside the repository, at
   `~/.harness-local/<repo-name>` (named from the repository's `origin`
   remote, or from the folder name when there is no remote). Nothing you
   write there is ever committed.
   Check: that folder exists after your first session that writes a
   personal note.

5. Work on a task branch:
   ```sh
   git checkout -b <task-branch-name>
   ```
   Check: `git branch --show-current` shows your task branch.

6. Ask for `/commit`. Before it stages anything, it discovers and runs
   your team's own verify command, in this order, first hit wins:
   `host.verify_command` in `harness/registry/structure.json` when it is
   set, then `package.json`'s `scripts.verify`, then a `Makefile` target
   literally named `verify`, then the harness's own lint as the default
   when none of those exist. The assistant never pushes or opens a pull
   request unless you separately ask for that in the same turn, and it
   never merges its own pull request.
   Check: the commit summary states, in words, which verification source
   ran and why.

## 6. Working with several agents at once (Herdr)

Herdr lets you run more than one agent side by side and read their state
from one sidebar instead of watching several terminal windows.

1. Launch `herdr` inside the repository folder.
2. Start `claude`, `codex`, or `opencode` in a pane.
3. Run `herdr integration install claude` (and `codex`, and `opencode`,
   for whichever you use) so the sidebar shows each pane as working,
   blocked waiting for input, or done.
4. Split panes with the prefix `ctrl+b` then `v` (opens to the right) or
   `-` (opens below); open a new tab with `ctrl+b` then `c`; detach with
   `ctrl+b` then `q`; reattach later with `herdr`; see every binding with
   `ctrl+b` then `?`.

One pattern that works: pane one runs `/research` on a question, pane two
drafts the document that answer feeds, pane three runs `/review` on the
draft, and you read the sidebar instead of watching three terminals at
once.

## 7. Samples

Three worked examples, using only skills that exist in this template:
brainstorm, research, review, humanize, eli5, prompt, doctor, commit, and
skillify.

### A policy draft

1. Type `/brainstorm outline a short remote-work expense policy` (or just
   say "brainstorm the outline"). Brainstorm writes nothing on its own;
   the options, trade-offs, and a tentative recommendation appear in the
   conversation.
2. Once you pick a direction, ask the assistant to write it as a file, for
   example `docs/remote-work-expense-policy.md`.
3. Type `/review docs/remote-work-expense-policy.md` (or say "review this
   spec"). Review is read-first and adversarial; it writes back to the
   file only if you authorize a change.
4. Type `/humanize docs/remote-work-expense-policy.md` (or say "clean up
   this copy"). Humanize rewrites the file in place through a draft,
   audit, and final loop.
5. Type `/commit` (or say "commit this"). What the commit looks like: one
   commit, subject something like `docs(policy): add remote-work expense
   policy`, the new file staged, a `Co-Authored-By` footer.

### A question answered with sources

1. Type `/research <your question>` (or say "research this question"). By
   default this is quick mode: a memory-first check of what the
   repository already knows, then a web pass, then a fresh check by a
   second reader who did not write the answer, then one cited answer in
   the conversation. No file is created unless you ask for one.
2. If you want the answer kept, ask the assistant to save it as a page,
   for example under the knowledge lane if one is configured, then type
   `/commit`.
3. What the commit looks like: something like `docs(knowledge): record
   <topic>`, with the new page staged.

### An explanation for a non-expert

1. Type `/eli5 <a document already in the repository>` (or say "explain
   this simply"). The result is a self-contained picture explainer,
   written to a scratch location and handed to you to open. It is never
   saved into the repository by default.
2. There is nothing to commit unless you separately ask the assistant to
   also keep a copy in the repository.

### Making your own skill

When the same correction keeps coming up, three or more times, say "this
keeps happening" or invoke `/skillify`. It starts by checking whether an
existing skill, rule, or reference can absorb the fix, and only proposes a
genuinely new skill when the intent, the output, and the boundary of when
to use it are all distinct from anything that already exists.

## 8. When something goes wrong

Run, in order:

```sh
python harness/tools/lint.py --strict
```

then re-run bootstrap for your platform with the check flag
(`--check` on macOS or Linux, `-Check` on Windows), then ask for `/doctor`
again. If a doctor line still reads `FAIL` or `WARN`, run bootstrap for
your platform without the check flag, then check again; the line says
which file or link it expected.

`UNKNOWN` in a doctor report is not a failure. It means no evidence has
been collected yet for that layer, not that the check failed. The offline
doctors only ever populate the `configured` layer; the deeper layers
(`loaded`, `trusted`, `fired`, `enforced`, `outcome-proven`) stay `UNKNOWN`
until someone has run a live session and recorded it.

## 9. What the assistant will not do without asking

- Push to a remote, or force-push.
- Open or merge a pull request.
- Read a credential file.

What stays yours: reviewing and merging any change, and the decision to
share anything outside the repository.

## 10. Where the deeper material is

- `README.md`: the full setup and requirements reference.
- `docs/HOST-SHAPES.md`: exactly what changes between a solo repository,
  a team repository, and an adopted one.
- `docs/LANES.md`: what a memory lane is and how each one behaves.
- `docs/PACKS.md`: the full skill catalog.
- `docs/VERIFICATION.md`: what has actually been run and observed, and
  when.
