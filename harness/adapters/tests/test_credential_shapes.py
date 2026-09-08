"""The credential-shape list is carried in five places and must not drift.

SECURITY.md promises that the Claude deny list, the OpenCode deny list,
``.gitignore``, the pre-commit filename block, and the dangerous-ops guard
agree on which filenames are credential material. This test is that promise:
the canonical list lives here, and each surface is checked against it, so a
shape added in one place fails the suite until it is added in the others.
"""

from __future__ import annotations

import fnmatch
import re
import sys

from ._paths import ADAPTERS, ROOT, bind_unittest, read_json, read_text

HOOK_LIB = ROOT / "harness" / "hooks" / "lib"
if str(HOOK_LIB) not in sys.path:
    sys.path.insert(0, str(HOOK_LIB))

import dangerous_ops_guard  # noqa: E402

# Exact filenames that are credential material wherever they sit.
BASENAMES = (
    ".env",
    ".envrc",
    ".mcp.json",
    ".npmrc",
    ".netrc",
    ".pgpass",
    ".pypirc",
    ".git-credentials",
)
# Extensions that mark a file as key material wherever it sits.
EXTENSIONS = ("pem", "key", "pfx", "ppk", "p12", "keystore", "tfvars", "jks")
# Paths that are credential material because of where they sit, not their basename.
# Each entry: (probe path, .gitignore line, pre-commit-matching, Claude deny entry, OpenCode read key).
SSH_PRIVATE_KEYS = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "id_ecdsa_sk", "id_ed25519_sk")
CONTEXTUAL = (
    (".aws/credentials", ".aws/credentials", "Read(**/.aws/credentials)", "**/.aws/credentials"),
    (".aws/credentials.bak", ".aws/credentials.*", "Read(**/.aws/credentials.*)", "**/.aws/credentials.*"),
    ("application_default_credentials.json", "application_default_credentials.json", "Read(**/application_default_credentials.json)", "**/application_default_credentials.json"),
) + tuple(
    (f".ssh/{key}", f".ssh/{key}", f"Read(**/.ssh/{key})", f"**/.ssh/{key}") for key in SSH_PRIVATE_KEYS
)

# Broader forms the guard alone treats as credential material at read time
# (any credentials* wildcard under .aws, any private id_* key under .ssh
# beyond the six named CONTEXTUAL keys): a deliberate one-surface widening,
# not drift. SECURITY.md documents this; the negative-space test below pins
# the boundary so a future widening of the other four static surfaces is a
# deliberate test update, not silent drift past this promise.
GUARD_ONLY_BROADER_FORMS = (
    ".aws/credentials_backup",
    ".ssh/id_custom",
    ".ssh/id_rsa.bak",
    # The guard also treats ANY path under a secret/ or secrets/ segment as
    # credential material regardless of filename; no static surface below
    # expresses a directory-segment rule, only exact filename globs.
    "notes" + "/secret/readme.md",
    "notes" + "/secrets/readme.md",
)

# The reverse direction: shapes the Claude and OpenCode native Read deny
# lists treat as credential material that the guard and pre-commit
# deliberately exempt. Read(**/.env.*) and "**/.env.*": "deny" have no
# negation mechanism, so a committed template .env file is unreadable
# through the native Read tool on those two runtimes even though the guard
# and pre-commit exempt it and the shell path (Bash cat, etc.) stays open.
NATIVE_DENY_ONLY_EXTRAS = (
    ".env.example",
    ".env.sample",
    ".env.template",
)

# Two precedence orders that follow from the rules above directly, each a
# real cross-surface behavior, not drift to silently fix. (probe, guard
# treats it as secret, pre-commit blocks it, one-line description.)
PRECEDENCE_CASES = (
    (
        "notes" + "/secrets/" + ".env.example",
        False,
        False,
        "the guard's template exemption is checked before, and wins over, the secret(s)/ segment rule",
    ),
    (
        ".env.example.local",
        False,
        True,
        "the guard's suffix check accepts anything starting with example., "
        "looser than pre-commit's -ivE exemption which requires the suffix to end exactly in example, sample, or template",
    ),
)

GITIGNORE = ROOT / ".gitignore"
PRE_COMMIT = ROOT / ".githooks" / "pre-commit"
CLAUDE_SETTINGS = ADAPTERS / "claude" / "settings.base.json"
OPENCODE_CONFIG = ADAPTERS / "opencode" / "opencode.json"


def _gitignore_secrets_block() -> list[str]:
    lines = read_text(GITIGNORE).splitlines()
    start = next(i for i, line in enumerate(lines) if "secrets and local state" in line)
    block: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("# ---"):
            break
        if line and not line.startswith("#"):
            block.append(line.strip())
    return block


def test_gitignore_secrets_block_carries_every_shape():
    block = _gitignore_secrets_block()
    missing = [name for name in BASENAMES if name not in block]
    missing += [f"*.{ext}" for ext in EXTENSIONS if f"*.{ext}" not in block]
    assert not missing, f".gitignore secrets block is missing {missing}"
    assert ".env.*" in block


def _pre_commit_filename_regex() -> re.Pattern:
    """The first grep stage alone (-iE, the deny match): what the block
    would flag before the template exemption below is applied."""
    for line in read_text(PRE_COMMIT).splitlines():
        if "grep -iE" in line and "envrc" in line:
            match = re.search(r"grep -iE '([^']+)'", line)
            assert match, "pre-commit filename grep is not in the expected quoted form"
            return re.compile(match.group(1), re.IGNORECASE)
    raise AssertionError("pre-commit has no filename grep mentioning envrc")


def _pre_commit_exempt_regex() -> re.Pattern:
    """The second grep stage (-ivE): the template-suffix exemption piped
    after the deny match, pulling .env.example, .env.sample, and
    .env.template back out of the block."""
    for line in read_text(PRE_COMMIT).splitlines():
        if "grep -ivE" in line:
            match = re.search(r"grep -ivE '([^']+)'", line)
            assert match, "pre-commit template exemption grep is not in the expected quoted form"
            return re.compile(match.group(1), re.IGNORECASE)
    raise AssertionError("pre-commit has no -ivE template exemption grep")


def _pre_commit_blocks(path: str) -> bool:
    """True iff the pre-commit filename block actually rejects path,
    composing BOTH piped grep stages the way the real pipeline does
    (matched by -iE AND NOT matched by -ivE). Checking the -iE stage alone
    would miss a widened exemption pattern that started swallowing a real
    credential shape; this composition catches it."""
    return bool(_pre_commit_filename_regex().search(path)) and not _pre_commit_exempt_regex().search(path)


def _any_depth_match(pattern: str, probe: str) -> bool:
    """fnmatch-style match of one glob pattern against a probe path: tried
    as written, and, when the pattern has no explicit any-depth prefix,
    also with one prepended. A bare gitignore entry (".env") or an
    un-prefixed glob matches at any depth in that surface's real
    semantics; plain fnmatch alone does not model that on its own, since
    it never adds an implicit leading '*/'."""
    if fnmatch.fnmatch(probe, pattern):
        return True
    if not pattern.startswith(("*/", "**/")):
        return fnmatch.fnmatch(probe, "*/" + pattern)
    return False


def _gitignore_would_ignore(probe: str) -> bool:
    """Effective gitignore result over the ordered secrets block: git's
    own semantics are last-match-wins and negation-aware (a later `!`
    pattern un-ignores an earlier match), evaluated here with fnmatch-style
    any-depth matching per pattern rather than a literal-entry check."""
    ignored = False
    for entry in _gitignore_secrets_block():
        negate = entry.startswith("!")
        pattern = entry[1:] if negate else entry
        if _any_depth_match(pattern, probe):
            ignored = not negate
    return ignored


def _claude_glob_entries() -> list[str]:
    deny = read_json(CLAUDE_SETTINGS)["permissions"]["deny"]
    globs = []
    for entry in deny:
        match = re.fullmatch(r"Read\((.+)\)", entry)
        if match:
            globs.append(match.group(1))
    return globs


def _claude_would_deny(probe: str) -> bool:
    """Effective Claude Read-deny result: the glob inside each Read(...)
    entry, matched with the same any-depth fnmatch semantics, not a
    literal-entry membership check."""
    return any(_any_depth_match(pattern, probe) for pattern in _claude_glob_entries())


def _opencode_would_deny(probe: str) -> bool:
    """Effective OpenCode read-permission result: every key whose value is
    "deny" (the wildcard "*": "allow" default is excluded), matched with
    the same any-depth fnmatch semantics, not a literal-key membership
    check."""
    read = read_json(OPENCODE_CONFIG)["permission"]["read"]
    return any(
        value == "deny" and _any_depth_match(pattern, probe)
        for pattern, value in read.items()
        if pattern != "*"
    )


def test_pre_commit_filename_block_matches_every_shape():
    unmatched = [name for name in BASENAMES if not _pre_commit_blocks(f"./{name}")]
    unmatched += [f"*.{ext}" for ext in EXTENSIONS if not _pre_commit_blocks(f"./k.{ext}")]
    assert not unmatched, f"pre-commit filename block does not match {unmatched}"
    assert _pre_commit_blocks("./.env.local")


def test_claude_deny_list_carries_every_shape():
    deny = set(read_json(CLAUDE_SETTINGS)["permissions"]["deny"])
    missing = [name for name in BASENAMES if f"Read(**/{name})" not in deny]
    missing += [f"*.{ext}" for ext in EXTENSIONS if f"Read(**/*.{ext})" not in deny]
    assert not missing, f"Claude settings.base.json deny list is missing {missing}"
    assert "Read(**/.env.*)" in deny


def test_opencode_read_deny_carries_every_shape():
    read = read_json(OPENCODE_CONFIG)["permission"]["read"]
    missing = [name for name in BASENAMES if read.get(f"**/{name}") != "deny"]
    missing += [f"*.{ext}" for ext in EXTENSIONS if read.get(f"**/*.{ext}") != "deny"]
    assert not missing, f"opencode.json read permission is missing {missing}"
    assert read.get("**/.env.*") == "deny"


def test_guard_treats_every_shape_as_credential_material():
    is_secret = dangerous_ops_guard._is_secret_path
    allowed = [name for name in BASENAMES if not is_secret(f"./{name}", [])]
    allowed += [f"*.{ext}" for ext in EXTENSIONS if not is_secret(f"./k.{ext}", [])]
    assert not allowed, f"dangerous_ops_guard does not treat {allowed} as credential material"
    assert is_secret("./.env.local", [])
    assert not is_secret("./.env.example", [])


def test_contextual_shapes_are_carried_by_every_surface():
    block = _gitignore_secrets_block()
    deny = set(read_json(CLAUDE_SETTINGS)["permissions"]["deny"])
    read = read_json(OPENCODE_CONFIG)["permission"]["read"]
    is_secret = dangerous_ops_guard._is_secret_path
    missing = []
    for probe, ignore_line, claude_entry, opencode_key in CONTEXTUAL:
        if ignore_line not in block:
            missing.append(f".gitignore lacks {ignore_line}")
        if not _pre_commit_blocks(probe):
            missing.append(f"pre-commit does not match {probe}")
        if claude_entry not in deny:
            missing.append(f"Claude deny lacks {claude_entry}")
        if read.get(opencode_key) != "deny":
            missing.append(f"opencode read lacks {opencode_key}")
        if not is_secret(probe, []):
            missing.append(f"guard allows {probe}")
    assert not missing, missing


def test_guard_only_broader_forms_are_deliberately_guard_only():
    """.aws/credentials_backup, .ssh/id_custom, and .ssh/id_rsa.bak are
    credential material to the guard (which sees the full argument text of
    a live command) but must NOT be carried by the other four static
    surfaces (exact globs matching only the canonical CONTEXTUAL shapes).
    A future widening of the four static surfaces to match these broader
    forms must update this test, not drift silently past it."""
    block = _gitignore_secrets_block()
    deny = set(read_json(CLAUDE_SETTINGS)["permissions"]["deny"])
    read = read_json(OPENCODE_CONFIG)["permission"]["read"]
    is_secret = dangerous_ops_guard._is_secret_path
    for probe in GUARD_ONLY_BROADER_FORMS:
        assert is_secret(probe, []), f"guard should treat {probe} as credential material"
        assert probe not in block, f".gitignore unexpectedly carries the literal broader form {probe}"
        assert not _pre_commit_blocks(f"./{probe}"), f"pre-commit filename block unexpectedly matches the broader form {probe}"
        assert f"Read(**/{probe})" not in deny, f"Claude deny list unexpectedly carries {probe}"
        assert read.get(f"**/{probe}") != "deny", f"opencode read permission unexpectedly carries {probe}"


def test_native_deny_lists_are_stricter_than_guard_and_pre_commit_for_env_templates():
    """The reverse direction: the guard and pre-commit exempt a template
    .env file, but Claude's Read(**/.env.*) deny entry and OpenCode's
    "**/.env.*": "deny" read permission have no negation mechanism, so
    both runtimes' native Read tool cannot open a tracked template file.
    The shell path (Bash cat, etc.) stays open on both runtimes; this is a
    real per-surface behavioral difference, documented in SECURITY.md, not
    something to fix by narrowing the deny lists here."""
    deny = set(read_json(CLAUDE_SETTINGS)["permissions"]["deny"])
    read = read_json(OPENCODE_CONFIG)["permission"]["read"]
    is_secret = dangerous_ops_guard._is_secret_path
    for probe in NATIVE_DENY_ONLY_EXTRAS:
        assert not is_secret(probe, []), f"guard should exempt template file {probe}"
        assert not _pre_commit_blocks(f"./{probe}"), f"pre-commit should exempt template file {probe}"
    # Claude and OpenCode carry only the blanket .env.* deny glob, with no
    # narrower entry that would exempt a template suffix specifically: a
    # future carve-out would be a new deny-list entry, not an env-var trick.
    assert "Read(**/.env.*)" in deny
    assert not any(entry.startswith("Read(") and "example" in entry for entry in deny)
    assert read.get("**/.env.*") == "deny"
    assert not any("example" in key for key in read)


def test_public_ssh_keys_stay_readable():
    assert not _pre_commit_blocks(".ssh/id_ed25519.pub")
    assert not dangerous_ops_guard._is_secret_path(".ssh/id_ed25519.pub", [])
    deny = read_json(CLAUDE_SETTINGS)["permissions"]["deny"]
    assert not any(".pub" in entry for entry in deny)


def test_effective_matching_pins_the_guard_only_ssh_boundary():
    """Entry-level membership checks (above) only prove a specific literal
    string is absent from a list; they pass even if a WIDER glob was added
    that would still match a guard-only extra without adding any literal
    matching entry (a hypothetical .ssh/id_* line in .gitignore, or
    Read(**/.ssh/id_*) / "**/.ssh/id_*": "deny" entries, would still catch
    id_custom, and would ALSO wrongly catch id_ed25519.pub, a public key
    that must stay readable). This test evaluates each surface's CURRENT
    patterns against two probes using that surface's real matching
    semantics, so a widening like that fails here even with no new
    literal entry to check for."""
    probe_private = "x" + "/.ssh/id_custom"
    probe_public = "x" + "/.ssh/id_ed25519.pub"
    is_secret = dangerous_ops_guard._is_secret_path

    assert is_secret(probe_private, []), "guard should treat id_custom as credential material"
    assert not _gitignore_would_ignore(probe_private), ".gitignore effectively matches id_custom (widened?)"
    assert not _pre_commit_blocks(probe_private), "pre-commit effectively matches id_custom (widened?)"
    assert not _claude_would_deny(probe_private), "Claude deny list effectively matches id_custom (widened?)"
    assert not _opencode_would_deny(probe_private), "opencode read permission effectively matches id_custom (widened?)"

    assert not is_secret(probe_public, []), "guard should never treat a public key as credential material"
    assert not _gitignore_would_ignore(probe_public), ".gitignore effectively matches a public key (widened?)"
    assert not _pre_commit_blocks(probe_public), "pre-commit effectively matches a public key (widened?)"
    assert not _claude_would_deny(probe_public), "Claude deny list effectively matches a public key (widened?)"
    assert not _opencode_would_deny(probe_public), "opencode read permission effectively matches a public key (widened?)"


def test_precedence_cases_between_the_guard_and_pre_commit():
    for probe, guard_is_secret, pre_commit_blocks, description in PRECEDENCE_CASES:
        assert dangerous_ops_guard._is_secret_path(probe, []) == guard_is_secret, description
        assert _pre_commit_blocks_helper(probe) == pre_commit_blocks, description


def _pre_commit_blocks_helper(probe: str) -> bool:
    return _pre_commit_blocks(probe if probe.startswith(("./", "/")) else f"./{probe}")


def test_template_exemption_beats_the_secret_segment_rule_at_the_guard():
    """Confirms the exemption in the first PRECEDENCE_CASES row is doing
    real work: an ordinary (non-template) file in the same secrets/
    directory IS credential material, so the template file's exemption is
    a genuine override, not a case where the directory rule never applied."""
    ordinary = "notes" + "/secrets/readme.md"
    assert dangerous_ops_guard._is_secret_path(ordinary, [])


bind_unittest(globals(), "CredentialShapeTests")
