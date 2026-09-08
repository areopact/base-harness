# Secrets

All secrets live only in approved, gitignored local secret stores. API keys, tokens, passwords, OAuth state, private keys, and client secrets are never written inline into a tracked config file, script, registry, or Markdown page, and an agent never reads a credential file into a session.

## Why

A secret in a tracked file is a secret in every clone, every fork, every backup, and every history rewrite that missed it. Once committed, even briefly, it must be treated as compromised, because the cost of assuming otherwise is unbounded and the cost of rotation is an afternoon. Defenses layer because each one has a gap: an ignore file prevents commits but not reads; a read guard prevents session exposure but not commits; a pre-commit scan catches known shapes but not novel ones; CI catches what reached the remote but only after it arrived.

## Application

### Config files reference variable names

Any config file that needs a credential references an environment variable by name (for example `"api_key": "${SERVICE_API_KEY}"`), never the value. When adding a service: add the key to the local store, reference the variable name in the config, and document the variable name (not the value) in the setup notes.

### The declared topology: names only

`harness/registry/environment.json` records the approved secret topology without values: variable names, symbolic location templates, owning principal, consumers, precedence, and sharing policy. It may never contain a value, a value digest, a presence result, or an absolute home path, and its validator never opens a secret store. The same variable name in two locations does not imply the same credential; each binding names a logical credential so intentional sharing and intentional separation are both explicit. Default sharing is `isolated`; any credential copied to a second principal or host is declared there with its rotation coupling and exit condition. The shipped file carries the policy block and empty locations and bindings.

### Gitignore as first defense

The local secret store (`.env` and siblings) is listed in `.gitignore`. The template also ignores common secret-bearing filenames (key material, tool rc files). A host may add a config file that references credentials by name to the ignore list as defense in depth, because even a correctly structured config file accumulates inline values through careless edits.

### Local hook floor

The versioned hooks in `.githooks/` run on every machine once bootstrap has set `core.hooksPath`:

- **pre-commit** runs one scan over the entire staged index against `.githooks/secret-patterns.txt`, a narrow, low-false-positive allowlist of identifiable key shapes. That file contains only patterns: a comment or blank line would itself become a pattern. Index-wide scanning means bait staged by one session cannot ride another session's `git add -A` into a commit. The same hook blocks secret-bearing filenames and rejects any staged gitlink, since a repository without submodules only ever sees one by accident.
- Where a pre-push hook is installed, it scans the added lines of every outgoing commit, catching secrets committed with `--no-verify`, commits from machines without the hook, and secrets added then removed inside the pushed range (a tip diff would miss those).

The hooks honor a documented skip variable for a knowing false positive on a single command. They are a seatbelt, not a security boundary: `--no-verify` bypasses them by design, and the pattern list is deliberately narrow. Authoritative coverage is a full scanner in CI; `SECURITY.md` names what the local floor does not catch.

### What an ignore file does and does not do

A runtime ignore file (for example `.claudeignore`) prevents the agent from reading the contents of excluded files during a session. It does not prevent those files from being committed. A `.gitignore` prevents commits and does nothing about reads. The two are orthogonal and are maintained independently.

### Rotation protocol

If a secret is ever committed, even briefly and even if never pushed, treat it as compromised:

1. Rotate the secret at the provider immediately.
2. Revoke the old value.
3. Audit history with `git log -S "<fragment>"` to confirm the scrub, and if the fragment is found in history, plan the history rewrite with the operator; a rewrite is a one-way door.
