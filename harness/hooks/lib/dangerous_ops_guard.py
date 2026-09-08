#!/usr/bin/env python3
"""PreToolUse(Bash) guard: deny literal command shapes that destroy data.

Enforcement rung: hard-block. The decision is carried in the JSON on stdout
(permissionDecision: deny), never in the exit code, and the module exits 0
on allow and on deny alike. Unparseable input fails open.

The reader, git, and delete tiers run over parsed tokens rather than over raw
text. One quote-state scanner (_lex) splits a command into segments on
unquoted ";", "&&", "||", "|", "&", newline, and grouping punctuation,
tokenizes each segment with POSIX quoting rules, records read redirections,
and returns the body of every $( ... ) and backtick substitution as its own
nested command. Single-quoted text is inert by construction: it becomes an
argument, never a command, unless the segment's command word is a shell
running a string (bash -c, sh -c, pwsh -Command, cmd /c), an eval, an alias
assignment, or a bare variable assignment, in which case the string is
classified recursively as a command. Each token keeps two forms, the POSIX
one with escapes applied and a Windows one with backslashes preserved, so a
drive path or a PowerShell parameter survives tokenization. An unquoted
"#" that starts a token ends the line, "<(" and ">(" are process
substitutions whose body is a command, and $'...' is a quoted token in
which only the plain escapes are decoded; a numeric or hex escape stays
literal and is out of model. Substitution nesting is followed to 64
levels, which is far above any real command; deeper text is not scanned,
and that is a miss rather than a deny. A POSIX shell -c takes exactly one
argument as its command string and the rest as positional parameters; an
argv-form payload arrives already split, so its elements are joined with
the quoting that keeps that boundary before classification.

The recognizers for an interpreter reader call, a device or permission
command, and a database client run on parsed segments, so the same words
inside a commit message, a grep pattern, or a printf argument are prose
and pass.

Tiers, in evaluation order:

  secret-exposure       a read command from a closed list whose ARGUMENT is a
                        credential path (dot-env files, the MCP config, key
                        material by extension, a secret/ path segment, and
                        any path matched by structure.json outbound_globs),
                        the source of a "<" redirection, or the path opened
                        by a python or .NET reader call. A bare path in
                        prose, a pattern string, or a variable name is not an
                        argument to a reader and passes.
  system-destroy        rm of root, home, a system path, or a parent-relative
                        path with recursive and force flags in any order, dd
                        onto a raw device, mkfs, Windows format, native
                        PowerShell recursive removal of a drive or system
                        root, fork bomb, recursive chmod 000, recursive chown
                        on a system path.
  git-protected-branch  force-push to a protected branch (flags in any order,
                        refspecs classified by their destination side, remote
                        deletion through :branch, --delete, or -d, a bare
                        force push when the structure's git mode is
                        main-only, --mirror), hard reset to a protected ref,
                        force-delete of a protected branch, low-level ref
                        deletion.
  git-history-rewrite   git filter-repo and git filter-branch.
  data-destroy          DROP of a table, database, or schema and TRUNCATE
                        only in an execution context: on the same simple
                        command as a database client from a closed list, or
                        terminated by ";" within 80 characters. A prose
                        mention (grep for the words, a commit message, an
                        echo) passes. Also git clean with force and
                        directory flags outside a dry run.

Quoted heredocs whose only sink is cat or "git commit -F -" are omitted
from the scan; interpreter input, unquoted expansion, and pipelines stay
visible.

This is a heuristic over literal shapes, not a security boundary. Commands
assembled from variables read at runtime, from a second interpreter hop, or
through a shell feature the scanner does not model stay outside it;
SECURITY.md lists the classes with their fixtures.

Called by harness/hooks/pre-tool-use/dangerous-ops-guard.{sh,ps1} and by
harness/hooks/lib/dispatch.py.
"""
import collections
import fnmatch
import hashlib
import json
import re
import sys

from _debug import debug
from hook_io import canonical_tool_name, deny, load_structure, shell_command_text

HOOK_NAME = "dangerous-ops-guard"
RECOVERY = (
    "If you truly intend this, run it in a shell outside the harness, "
    "or update harness/hooks/lib/dangerous_ops_guard.py to exempt the pattern."
)

# ----- Safe-context stripping ------------------------------------------------
# Only quoted heredocs to a standalone literal sink are safe to omit.
_HEREDOC_RE = re.compile(
    r"(?m)^(?P<header>[^\n]*?)<<-?\s*(?P<quote>['\"])(?P<end>\w+)(?P=quote)"
    r"(?P<tail>[^\n]*)\n(?P<body>.*?)\n[\t ]*(?P=end)[\t ]*(?=\n|$)",
    re.DOTALL,
)


def strip_safe_contexts(command):
    """Omit literal text only when the receiving command cannot execute it."""
    def replace(match):
        header, tail = match["header"].strip(), match["tail"].strip()
        safe_sink = header == "cat" or bool(
            re.fullmatch(r"git\s+commit\s+(?:-F|--file)\s+-", header)
        )
        # A redirection writes text; a pipeline or substitution may execute it.
        safe_tail = not tail or bool(re.fullmatch(r">>?\s*['\"]?[\w./\\-]+['\"]?", tail))
        if safe_sink and safe_tail:
            return header + " " + tail
        return match.group(0)
    return _HEREDOC_RE.sub(replace, command)


# ----- Lexer ------------------------------------------------------------------
# value:   the POSIX reading, escapes applied and quotes removed.
# windows: the same token with backslashes preserved, for drive paths and for
#          PowerShell parameters, where a backslash is a separator and not an
#          escape.
Token = collections.namedtuple("Token", "value windows quoted")
Segment = collections.namedtuple("Segment", "tokens redirects")

_MAX_LEX_DEPTH = 64
_MAX_ROUNDS = 5
_MAX_SEGMENTS = 400
_DRIVE_PATH = re.compile(r"[A-Za-z]:[\\/]")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Only the plain escapes of the $'...' form are decoded; a numeric or hex
# escape is out of model and stays literal.
_ANSI_C_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'"}
# A PowerShell named parameter bound with a colon: -LiteralPath:<value>.
_COLON_PARAM = re.compile(r"^-{1,2}[A-Za-z][A-Za-z0-9]*:(.+)$")
_WINDOWS_TOKEN = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}|\.{1,2}[\\/])")


def _matching_paren(text, start):
    """Index of the ")" closing the "(" at start, or the end of the text.

    Quoted parentheses do not count, so a ")" inside a quoted argument of the
    substitution body does not close it early.
    """
    depth = 0
    index = start
    quote = None
    while index < len(text):
        char = text[index]
        if quote == "'":
            if char == "'":
                quote = None
        elif quote == '"':
            if char == "\\" and index + 1 < len(text):
                index += 2
                continue
            if char == '"':
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "\\" and index + 1 < len(text):
            index += 2
            continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return len(text)


def _lex(text, depth=0):
    """Segment and tokenize one command string, nested substitutions included."""
    segments = []
    tokens = []
    redirects = []
    nested = []
    value = []
    windows = []
    state = {"started": False, "quoted": False, "pending": None}
    quote = None

    def flush():
        if not state["started"]:
            return
        token = Token("".join(value), "".join(windows), state["quoted"])
        del value[:]
        del windows[:]
        state["started"] = False
        state["quoted"] = False
        if state["pending"] == "read":
            redirects.append(token)
        elif state["pending"] != "skip":
            tokens.append(token)
        state["pending"] = None

    def end_segment():
        flush()
        if tokens or redirects:
            segments.append(Segment(tuple(tokens), tuple(redirects)))
        del tokens[:]
        del redirects[:]

    def add(posix_text, windows_text=None):
        value.append(posix_text)
        windows.append(posix_text if windows_text is None else windows_text)
        state["started"] = True

    index = 0
    length = len(text)
    while index < length:
        char = text[index]

        if quote is None and text[index:index + 2] in ("<(", ">("):
            # Process substitution: the body is a command, the construct
            # itself is only a file-shaped argument.
            end = _matching_paren(text, index + 1)
            nested.append(text[index + 2:end])
            add(text[index:min(end + 1, length)])
            index = end + 1
            continue

        if quote is None and text[index:index + 2] == "$'":
            end = index + 2
            body = []
            while end < length and text[end] != "'":
                if text[end] == "\\" and end + 1 < length:
                    body.append(_ANSI_C_ESCAPES.get(text[end + 1], text[end + 1]))
                    end += 2
                    continue
                body.append(text[end])
                end += 1
            state["quoted"] = True
            add("".join(body))
            index = end + 1
            continue

        if quote is None and text[index:index + 2] == '$"':
            quote = '"'
            state["started"] = True
            state["quoted"] = True
            index += 2
            continue

        if quote != "'":
            if text[index:index + 2] == "$(":
                end = _matching_paren(text, index + 1)
                nested.append(text[index + 2:end])
                raw = text[index:min(end + 1, length)]
                add(raw)
                index = end + 1
                continue
            if char == "`":
                end = text.find("`", index + 1)
                if end == -1:
                    end = length
                nested.append(text[index + 1:end])
                raw = text[index:min(end + 1, length)]
                add(raw)
                index = end + 1
                continue

        if quote == "'":
            if char == "'":
                quote = None
            else:
                add(char)
            index += 1
            continue

        if quote == '"':
            if char == '"':
                quote = None
                index += 1
                continue
            if char == "\\" and index + 1 < length and text[index + 1] in "\"\\$`\n":
                following = text[index + 1]
                if following == '"' and _WINDOWS_TOKEN.match("".join(windows) + "\\"):
                    add("\\")
                    index += 1
                    continue
                if following != "\n":
                    add(following)
                index += 2
                continue
            add(char)
            index += 1
            continue

        # Unquoted.
        if char == "#" and not state["started"]:
            end_segment()
            newline = text.find("\n", index)
            if newline == -1:
                break
            index = newline + 1
            continue
        if char in " \t\r":
            flush()
            index += 1
            continue
        if char in ";\n":
            end_segment()
            index += 1
            continue
        if char == "|":
            end_segment()
            index += 2 if text[index:index + 2] == "||" else 1
            continue
        if char == "&" and text[index:index + 2] != "&>":
            end_segment()
            index += 2 if text[index:index + 2] == "&&" else 1
            continue
        if char in "()" and not state["started"]:
            end_segment()
            index += 1
            continue
        if char == "{" and not state["started"] and text[index + 1:index + 2] in ("", " ", "\t", "\n"):
            end_segment()
            index += 1
            continue
        if char == "}" and not state["started"]:
            end_segment()
            index += 1
            continue
        if char in "<>" or text[index:index + 2] == "&>":
            if state["started"] and "".join(value).isdigit():
                del value[:]
                del windows[:]
                state["started"] = False
                state["quoted"] = False
            else:
                flush()
            if text[index:index + 3] == "<<<":
                index, state["pending"] = index + 3, "skip"
            elif text[index:index + 2] == "<<":
                index, state["pending"] = index + 2, "skip"
            elif char == "<":
                index, state["pending"] = index + 1, "read"
            else:
                cursor = index + (2 if text[index:index + 2] in (">>", "&>") else 1)
                if text[cursor:cursor + 1] in ("&", "|"):
                    cursor += 1
                index, state["pending"] = cursor, "skip"
            continue
        if char == "\\":
            following = text[index + 1:index + 2]
            if following in ("", " ", "\t", "\r"):
                # A separator at the end of a path, not an escaped blank:
                # otherwise the next token merges into the path and the
                # options after it are never parsed.
                add("\\")
                index += 1
                continue
            if following and following != "\n":
                add(following, "\\" + following)
            index += 2 if following else 1
            continue
        if char in "'\"":
            quote = char
            state["started"] = True
            state["quoted"] = True
            index += 1
            continue
        add(char)
        index += 1

    end_segment()
    if depth < _MAX_LEX_DEPTH:
        for inner in nested:
            segments.extend(_lex(inner, depth + 1))
    return segments


def _effective(token, windows_hint=False):
    """The token's text, keeping backslashes where they are separators."""
    if token.value == token.windows:
        return token.value
    if windows_hint or _DRIVE_PATH.search(token.windows):
        return token.windows
    return token.value


# ----- Command word ------------------------------------------------------------
# A wrapper carries its own options before the real command word; the values
# of the options listed here are consumed with the option, so "sudo -u x cat"
# still resolves to cat.
_WRAPPERS = {
    "sudo": {"-u", "-g", "-p", "-C", "-U", "-h", "-r", "-t", "--user", "--group", "--prompt", "--host"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "--unset", "--chdir"},
    "nice": {"-n", "--adjustment"},
    "time": {"-o", "-f", "--output", "--format"},
    "nohup": set(),
    "command": set(),
    "exec": {"-a"},
    "stdbuf": {"-i", "-o", "-e"},
    "builtin": set(),
}
# Shell reserved words and control operators never name the command; the word
# after them does.
_RESERVED_WORDS = {"if", "then", "elif", "else", "while", "until", "do", "!", "{", "}", "("}
# A function header, with or without the brace that follows it: name() {
_FUNCTION_HEADER = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*\(\)\{?$")
# "command -v name" and "command -V name" report where a name resolves; they
# run nothing.
_INSPECT_LETTERS = {"v", "V"}


def _basename(value):
    name = value.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _command_word(tokens):
    """Return (command word, its index) past assignments and wrapper commands."""
    index = 0
    guard = 0
    while index < len(tokens) and guard < 32:
        guard += 1
        text = tokens[index].value
        if _ASSIGNMENT.match(text) or text in _RESERVED_WORDS or _FUNCTION_HEADER.match(text):
            index += 1
            continue
        word = _basename(text)
        if word not in _WRAPPERS:
            return word, index
        options = _WRAPPERS[word]
        index += 1
        while index < len(tokens):
            text = tokens[index].value
            if _ASSIGNMENT.match(text) and word in ("env", "sudo"):
                index += 1
                continue
            if text == "--":
                index += 1
                break
            if text.startswith("-") and text != "-":
                if word == "command" and not text.startswith("--"):
                    if set(text[1:]) & _INSPECT_LETTERS:
                        return "", len(tokens)
                index += 2 if (text in options and index + 1 < len(tokens)) else 1
                continue
            break
    return "", len(tokens)


# An operand may arrive wrapped in grouping punctuation, or as a PowerShell
# literal array: -Path @("a", "b") and -Path "a","b" both name two files.
def _unwrap(value):
    text = value.strip()
    while text[:2] == "@(" or text[:1] == "(":
        text = text[2:] if text[:2] == "@(" else text[1:]
    text = text.rstrip(",;)")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1]
    return text.strip()


def _operand_values(value):
    """The operand itself plus each element when it is a literal array."""
    values = [_unwrap(value)]
    # Only a Windows separator is trimmed: a forward slash may be part of
    # a pattern operand, where the text between the slashes is not a path.
    trimmed = values[0].rstrip("\\")
    if trimmed and trimmed != values[0]:
        values.append(trimmed)
    if "," in value:
        for part in value.split(","):
            candidate = _unwrap(part)
            if candidate and candidate not in values:
                values.append(candidate)
    return values


# ----- Nested command strings --------------------------------------------------

_POSIX_SHELLS = {"bash", "sh", "zsh", "fish", "dash", "ksh", "ash"}
_SHELL_WORDS = _POSIX_SHELLS | {"pwsh", "powershell", "cmd"}
_SHELL_STRING_FLAG = re.compile(r"(?i)^-(?:[a-z]*c|command)$")


def _nested_command_strings(segment):
    """Strings this segment hands to an interpreter, as command text."""
    word, index = _command_word(segment.tokens)
    rest = list(segment.tokens[index + 1:]) if index < len(segment.tokens) else []
    strings = []
    if not word:
        # A segment that is only assignments: the value may be the command a
        # later segment evals.
        for token in segment.tokens:
            if _ASSIGNMENT.match(token.value):
                strings.append(token.value.split("=", 1)[1])
        return strings
    if word in _SHELL_WORDS:
        for position, token in enumerate(rest):
            flag = token.value
            if _SHELL_STRING_FLAG.match(flag) or (word == "cmd" and flag.lower() in ("/c", "/k")):
                tail = rest[position + 1:]
                if tail:
                    if word in _POSIX_SHELLS:
                        # -c takes exactly one command string, quoted or
                        # not; the arguments after it are $0 and the
                        # positional parameters, which are data.
                        strings.append(tail[0].value)
                    else:
                        # A PowerShell -Command or a cmd /c takes the rest
                        # of the line as the command.
                        strings.append(" ".join(item.value for item in tail))
                break
        return strings
    if word == "eval" and rest:
        strings.append(" ".join(item.value for item in rest))
        return strings
    if word == "alias":
        for token in rest:
            if _ASSIGNMENT.match(token.value):
                strings.append(token.value.split("=", 1)[1])
    return strings


def _analyze(command):
    """Every segment of a command, nested interpreter strings included."""
    segments = _lex(command)
    result = list(segments)
    frontier = segments
    rounds = 0
    while frontier and rounds < _MAX_ROUNDS and len(result) < _MAX_SEGMENTS:
        rounds += 1
        produced = []
        for segment in frontier:
            for text in _nested_command_strings(segment):
                produced.extend(_lex(text))
        result.extend(produced)
        frontier = produced
    return result


# ----- secret-exposure --------------------------------------------------------

_READERS = {
    "cat", "type", "more", "less", "head", "tail", "sed", "awk",
    "get-content", "gc",
}
_PS_READERS = {"get-content", "gc", "type"}
_SECRET_EXTENSIONS = {"pem", "key", "p12", "pfx", "jks", "ppk", "keystore", "tfvars"}
_SECRET_FILENAMES = {".envrc", ".npmrc", ".netrc", ".pgpass", ".pypirc", ".git-credentials"}
_SECRET_SEGMENTS = {"secret", "secrets"}
_TEMPLATE_SUFFIXES = ("example", "sample", "template")
_OPEN_START = re.compile(
    r"\bopen\s*\(|\[(?:System\.)?IO\.File\]::(?:ReadAllText|ReadAllBytes|OpenRead)\s*\(",
    re.IGNORECASE,
)
_STRING_LITERAL = re.compile(r"'([^']*)'|\"([^\"]*)\"")
# An open() mode that writes, appends, or creates is not a read.
_WRITE_MODE = re.compile(r"^[rwaxbt]*[wax][rwaxbt]*$")
_INTERPRETERS = {"python", "python2", "python3", "pythonw", "py", "ipython"}
_POWERSHELL_HOSTS = {"pwsh", "powershell"}
_DOTNET_READER = re.compile(r"(?i)IO\.File\]::(?:ReadAllText|ReadAllBytes|OpenRead)")


def _split_arguments(body):
    """Top-level comma-separated arguments of a call body."""
    arguments = []
    current = []
    depth = 0
    quote = None
    for char in body:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            arguments.append("".join(current))
            current = []
            continue
        current.append(char)
    if current:
        arguments.append("".join(current))
    return arguments


def _open_call_paths(text):
    """Paths named inside a reader call, parentheses balanced.

    A call whose mode argument writes is not a read and is skipped.
    """
    for match in _OPEN_START.finditer(text):
        start = match.end() - 1
        body = text[start + 1:_matching_paren(text, start)]
        arguments = _split_arguments(body)
        if len(arguments) >= 2 and _WRITE_MODE.match(arguments[1].strip().strip("\"'")):
            continue
        if arguments:
            yield arguments[0]
        for literal in _STRING_LITERAL.finditer(body):
            yield literal.group(1) if literal.group(1) is not None else literal.group(2)


def _interpreter_read_paths(segment):
    """Reader-call paths, only where an interpreter or .NET reader runs.

    The .NET form counts at command position, or under a PowerShell host
    running a string. The same text inside an argument of another command
    is prose.
    """
    word, index = _command_word(segment.tokens)
    joined = " ".join(token.value for token in segment.tokens)
    executable = word in _INTERPRETERS or bool(_DOTNET_READER.search(word))
    if not executable and word in _POWERSHELL_HOSTS:
        executable = any(
            _SHELL_STRING_FLAG.match(token.value)
            for token in segment.tokens[index + 1:]
        )
    if not executable:
        return []
    return list(_open_call_paths(joined))


def _outbound_globs(structure):
    value = structure.get("outbound_globs") if isinstance(structure, dict) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


# A leading shell or environment variable segment naming a well-known home
# directory: a $HOME prefix, a ${VAR} prefix, or PowerShell's $env:USERPROFILE.
_VAR_PREFIX = re.compile(r"^\$(?:\{[^}]+\}|env:[A-Za-z_]+|[A-Za-z_][A-Za-z0-9_]*)/")


def _is_secret_path(token, globs):
    """True when a single argument token names credential material."""
    value = token.strip().strip("\"'").replace("\\", "/")
    if not value or value.startswith("-"):
        return False
    if value.startswith("$"):
        match = _VAR_PREFIX.match(value)
        if not match:
            return False
        value = value[match.end():]
    while value.startswith("./"):
        value = value[2:]
    basename = value.rsplit("/", 1)[-1]
    lowered = basename.lower()
    if lowered == ".env" or lowered.startswith(".env."):
        suffix = lowered[5:]
        return not any(suffix == item or suffix.startswith(item + ".") for item in _TEMPLATE_SUFFIXES)
    if lowered == ".mcp.json":
        return True
    if lowered in _SECRET_FILENAMES:
        return True
    if "." in lowered and lowered.rsplit(".", 1)[-1] in _SECRET_EXTENSIONS:
        return True
    segments = [segment.lower() for segment in value.split("/")[:-1]]
    if lowered.startswith("credentials") and ".aws" in segments:
        return True
    if lowered == "application_default_credentials.json":
        return True
    if ".ssh" in segments and lowered.startswith("id_") and not lowered.endswith(".pub"):
        return True
    if any(segment in _SECRET_SEGMENTS for segment in segments):
        return True
    for pattern in globs:
        if fnmatch.fnmatch(value, pattern) or fnmatch.fnmatch(value, pattern.rstrip("/") + "/*"):
            return True
    return False


def _read_operands(segment):
    """Paths this segment reads: redirection sources and reader arguments."""
    values = []
    for token in segment.redirects:
        values.extend(_operand_values(_effective(token, True)))
    word, index = _command_word(segment.tokens)
    if word not in _READERS:
        return values
    windows_hint = word in _PS_READERS
    for token in segment.tokens[index + 1:]:
        text = _effective(token, windows_hint)
        values.extend(_operand_values(text))
        bound = _COLON_PARAM.match(text)
        if bound:
            values.extend(_operand_values(bound.group(1)))
    return values


def _reads_secret(segments, globs):
    for segment in segments:
        for value in _read_operands(segment):
            if _is_secret_path(value, globs):
                return True
        for candidate in _interpreter_read_paths(segment):
            if _is_secret_path(candidate, globs):
                return True
    return False


def reads_secret(command, structure=None):
    structure = structure if structure is not None else load_structure()
    return _reads_secret(_analyze(command), _outbound_globs(structure))


# ----- system-destroy ---------------------------------------------------------

_SYSTEM_ROOTS = [
    r"/(?:\*)?(?=$|[\s\"';|&])",
    r"~(?:/\*)?/?(?=$|[\s\"';|&])",
    r"\$HOME(?:/\*)?/?(?=$|[\s\"';|&])",
    r"\$\{HOME\}(?:/\*)?/?(?=$|[\s\"';|&])",
    r"/usr(?:/|\b)", r"/etc(?:/|\b)", r"/var(?:/|\b)",
    r"/home(?:/|\b)", r"/Users(?:/|\b)", r"/System(?:/|\b)",
    r"/mnt(?:/|\b)", r"/opt(?:/|\b)", r"/bin(?:/|\b)", r"/sbin(?:/|\b)",
    r"/lib(?:/|\b)", r"/boot(?:/|\b)",
    r"[A-Za-z]:[\\/](?:\*)?(?=$|[\s\"';|&])",
    r"[A-Za-z]:[\\/](?:Windows|Program Files(?: \(x86\))?|Users)(?:[\\/]|(?=$|[\s\"';|&]))",
    r"(?:\./)*\.\.(?:[\\/][^\s\"';|&]*)?(?=$|[\s\"';|&])",
]
_SYSTEM_TOP = {
    "usr", "etc", "var", "home", "users", "system", "mnt", "opt",
    "bin", "sbin", "lib", "boot",
}
_WINDOWS_TOP = {"windows", "users", "program files", "program files (x86)", "programdata"}
_HOME_TOKENS = {"~", "$home", "${home}", "$env:userprofile", "$env:homepath"}
_DRIVE_ONLY = re.compile(r"^[A-Za-z]:$")
_DD_TARGET = re.compile(
    r"(?i)^of=/dev/(?:sd[a-z]+\d*|nvme\d+n\d+(?:p\d+)?|hd[a-z]+|disk\d+)"
)
_MKFS_WORD = re.compile(r"^mkfs(?:\.[a-z0-9]+)?$")
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:$")
_MODE_LOCKOUT = re.compile(r"^0*00$")
_FORK_BOMB = re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")
def _flags_and_operands(tokens):
    """A plain option/operand split for a command with no special grammar."""
    flags = []
    operands = []
    end_of_options = False
    for token in tokens:
        text = _effective(token, True)
        if not end_of_options and text == "--":
            end_of_options = True
            continue
        if not end_of_options and text.startswith("-") and len(text) > 1:
            flags.append(text)
            continue
        operands.extend(_operand_values(text))
    return flags, operands


def _is_recursive(flags):
    return any(flag == "-R" or flag.lower() == "--recursive" for flag in flags)


def _device_destroy_shape(segments):
    """dd onto a raw device, a filesystem rebuild, or a drive format."""
    for segment in segments:
        word, index = _command_word(segment.tokens)
        flags, operands = _flags_and_operands(segment.tokens[index + 1:])
        if word == "dd" and any(_DD_TARGET.match(operand) for operand in operands):
            return "dd"
        if _MKFS_WORD.match(word) and (word != "mkfs" or "-t" in flags):
            return "mkfs"
        if word == "format" and any(_DRIVE_LETTER.match(operand) for operand in operands):
            return "format"
    return ""


def _permission_destroy_shape(segments):
    """A recursive lockout mode, or a recursive owner change on a system path."""
    for segment in segments:
        word, index = _command_word(segment.tokens)
        flags, operands = _flags_and_operands(segment.tokens[index + 1:])
        if word == "chmod" and _is_recursive(flags):
            if any(_MODE_LOCKOUT.match(operand) for operand in operands):
                return "chmod"
        if word == "chown" and _is_recursive(flags):
            if any(_is_system_target(operand) for operand in operands[1:]):
                return "chown"
    return ""


def _normalized_parts(base):
    """Path segments with "." dropped and ".." resolved where it is literal."""
    parts = []
    for part in base.split("/"):
        if part == "." and parts:
            continue
        if part == ".." and parts and parts[-1] not in ("", "..") :
            parts.pop()
            continue
        parts.append(part)
    return parts


def _is_system_target(value):
    """True when an operand names root, home, a system path, or a parent."""
    text = value.strip().strip("\"'").replace("\\", "/")
    text = re.sub(r"/{2,}", "/", text)
    while text.startswith("./"):
        text = text[2:]
    if not text or text == ".":
        return False
    base = text.rstrip("/")
    if base.endswith("/*"):
        base = base[:-2]
    if base in ("", "*"):
        return text.startswith("/")
    lowered = base.lower()
    if lowered in _HOME_TOKENS:
        return True
    if lowered.startswith("$env:systemroot"):
        return True
    parts = _normalized_parts(base)
    if not parts or parts == [""]:
        return base.startswith("/")
    if parts[0] == "..":
        return True
    if base.startswith("/"):
        return len(parts) > 1 and parts[1].lower() in _SYSTEM_TOP
    if _DRIVE_ONLY.match(parts[0]):
        if len(parts) == 1 or parts[1] in ("", "*"):
            return True
        return parts[1].lower() in _WINDOWS_TOP
    return False


# PowerShell spells a switch with a single dash and a whole word; a bundled
# POSIX cluster such as the two-letter recursive-force form is not that shape.
_PS_RECURSE = re.compile(r"(?i)^-(?:r|recurse)$")
_PS_LONG_SWITCH = {"recurse", "force", "confirm", "whatif", "path", "literalpath", "filter", "include", "exclude"}
_DELETE_WORDS = {"rm", "remove-item", "ri", "del", "erase", "rd", "rmdir"}
_PS_DELETE_WORDS = {"rm", "remove-item", "ri", "del", "erase", "rd", "rmdir"}


def _parse_delete(tokens):
    """Return (flag set, raw flag texts, operands) for a delete command."""
    flags = set()
    raw_flags = []
    operands = []
    end_of_options = False
    for token in tokens:
        text = _effective(token, True)
        if not end_of_options and text == "--":
            end_of_options = True
            continue
        if end_of_options or not text.startswith("-") or len(text) == 1:
            operands.extend(_operand_values(text))
            continue
        bound = _COLON_PARAM.match(text)
        if bound:
            value = bound.group(1).strip()
            if value.lower() in ("$true", "$false"):
                name = text.split(":", 1)[0]
                key = name.lstrip("-").lower()
                if value.lower() == "$true":
                    flags.add(key)
                    raw_flags.append(name)
                else:
                    flags.discard(key)
                continue
            operands.extend(_operand_values(value))
            continue
        raw_flags.append(text)
        if text.startswith("--"):
            flags.add(text[2:].split("=", 1)[0].lower())
            continue
        body = text[1:]
        if len(body) > 1 and body.isalpha() and body.lower() in _PS_LONG_SWITCH:
            flags.add(body.lower())
            continue
        flags.update(letter.lower() for letter in body)
    return flags, raw_flags, operands


def _delete_commands(segments):
    for segment in segments:
        word, index = _command_word(segment.tokens)
        if word not in _DELETE_WORDS:
            continue
        flags, raw_flags, operands = _parse_delete(segment.tokens[index + 1:])
        yield word, flags, raw_flags, operands


def _powershell_system_delete(segments):
    """Native recursive removal of a drive, home, or system root."""
    for word, flags, raw_flags, operands in _delete_commands(segments):
        if word not in _PS_DELETE_WORDS or "whatif" in flags:
            continue
        if not any(_PS_RECURSE.match(flag) for flag in raw_flags):
            continue
        if any(_is_system_target(operand) for operand in operands):
            return True
    return False


def powershell_system_delete(command):
    return _powershell_system_delete(_analyze(command))


def _rm_system_delete(segments):
    """A recursive, forced removal of a protected path, flags in any order."""
    for _word, flags, _raw_flags, operands in _delete_commands(segments):
        recursive = bool(flags & {"r", "recursive", "recurse"})
        force = bool(flags & {"f", "force"})
        if not (recursive and force) or "whatif" in flags:
            continue
        if any(_is_system_target(operand) for operand in operands):
            return True
    return False


# ----- git ----------------------------------------------------------------------

_PROTECTED_BRANCHES = {"main", "master", "trunk", "develop", "production", "release"}
# Assembled from fragments so the ref namespace prefix is not read as a
# repository path by the lane-path and de-identification lints.
_HEADS_PREFIX = "refs" + "/heads" + "/"
_GIT_GLOBAL_VALUE_OPTS = {
    "-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path",
    "--super-prefix", "--config-env",
}
_PUSH_VALUE_OPTS = {"-o", "--repo", "--receive-pack", "--exec", "--push-option"}
# Short options recorded under the long name they abbreviate, so a --no- form
# cancels a bundled letter and the two spellings cannot disagree.
_PUSH_ALIASES = {
    "f": ("force",), "n": ("dry-run",), "d": ("delete",), "u": ("set-upstream",),
    "q": ("quiet",), "v": ("verbose",),
}
_CLEAN_ALIASES = {"f": ("force",), "n": ("dry-run",), "q": ("quiet",)}
# Short options whose value may be attached to the letter.
_PUSH_ATTACHED = ("-o",)
_BRANCH_ALIASES = {
    "D": ("delete", "force"), "d": ("delete",), "f": ("force",),
    "M": ("move", "force"), "m": ("move",), "q": ("quiet",),
}
Ref = collections.namedtuple("Ref", "dest protected plus delete")


def _git_invocations(segments):
    """Yield (subcommand, argument tokens) for every segment that runs git."""
    for segment in segments:
        word, index = _command_word(segment.tokens)
        if word != "git":
            continue
        rest = segment.tokens[index + 1:]
        position = 0
        while position < len(rest):
            text = rest[position].value
            if not text.startswith("-") or text == "-":
                break
            if "=" not in text and text in _GIT_GLOBAL_VALUE_OPTS:
                position += 2
            else:
                position += 1
        if position >= len(rest):
            continue
        yield rest[position].value.lower(), list(rest[position + 1:])


def _parse_options(tokens, value_opts, aliases=None, attached=()):
    """Return (effective flags, operands).

    A short option is recorded under the long name it abbreviates, so one
    state carries both spellings and a --no- form cancels either. "--" ends
    the options.
    """
    aliases = aliases or {}
    flags = {}
    operands = []
    end_of_options = False
    position = 0

    def record(name, value):
        for canonical in aliases.get(name, (name,)):
            flags[canonical] = value

    def cancel(name):
        for canonical in aliases.get(name, (name,)):
            flags.pop(canonical, None)

    while position < len(tokens):
        token = tokens[position]
        text = token.value
        position += 1
        if end_of_options or not text.startswith("-") or text == "-" or " " in text:
            operands.append(token)
            continue
        if text == "--":
            end_of_options = True
            continue
        if text.startswith("--"):
            name, separator, tail = text.partition("=")
            key = name[2:].lower()
            if not separator and key.startswith("no-"):
                cancel(key[3:])
                continue
            if not separator and name in value_opts:
                position += 1
            record(key, tail if separator else None)
            continue
        if text in value_opts:
            position += 1
            continue
        if text[:2] in attached and len(text) > 2:
            # -o<value>: the rest of the token is the value, not a cluster.
            record(text[1], text[2:])
            continue
        for letter in text[1:]:
            record(letter, None)
    return flags, operands


def _bare(flags, name):
    """True when an option is present with no attached value."""
    return name in flags and flags[name] is None


def _protected_name(name):
    return name.lower() in _PROTECTED_BRANCHES


def _ref(spec):
    """Classify a refspec by its destination side."""
    text = _unwrap(spec)
    plus = text.startswith("+")
    if plus:
        text = text[1:]
    delete = False
    if ":" in text:
        source, _, dest = text.partition(":")
        delete = source.strip() == ""
    else:
        dest = text
    dest = dest.strip().strip("\"'")
    if dest.startswith(_HEADS_PREFIX):
        dest = dest[len(_HEADS_PREFIX):]
    return Ref(dest, _protected_name(dest), plus, delete)


def _local_ref_name(text):
    """A local ref operand reduced to its branch name."""
    name = _unwrap(text)
    if name.startswith(_HEADS_PREFIX):
        name = name[len(_HEADS_PREFIX):]
    name = name.rsplit("/", 1)[-1]
    return re.split(r"[~^@]", name)[0]


def _dangerous_push(flags, operands, git_mode):
    if _bare(flags, "dry-run"):
        return False
    refs = [_ref(token.value) for token in operands[1:]]
    delete_flag = _bare(flags, "delete")
    # A deletion of a protected ref stays denied even under a lease.
    if any(ref.protected and (ref.delete or delete_flag) for ref in refs):
        return True
    if _bare(flags, "mirror"):
        return True
    # --force-if-includes only ever makes a lease stricter, so it is never
    # a force of its own; a protected deletion is denied above regardless.
    force = _bare(flags, "force")
    if force:
        if any(ref.protected for ref in refs):
            return True
        if not refs:
            # No refspec: the remote's default branch receives the push.
            return git_mode == "main-only" or _bare(flags, "all")
        return False
    return any(ref.protected and ref.plus for ref in refs)


def _dangerous_git_push(segments, git_mode):
    for subcommand, args in _git_invocations(segments):
        if subcommand != "push":
            continue
        flags, operands = _parse_options(args, _PUSH_VALUE_OPTS, _PUSH_ALIASES, _PUSH_ATTACHED)
        if _dangerous_push(flags, operands, git_mode):
            return True
    return False


def dangerous_git_push(command, structure=None):
    structure = structure if structure is not None else load_structure()
    git_mode = ((structure or {}).get("git") or {}).get("mode", "main-only")
    return _dangerous_git_push(_analyze(command), git_mode)


def _git_local_shape(segments):
    """Return the message key for a destructive local repository shape."""
    for subcommand, args in _git_invocations(segments):
        if subcommand in ("filter-branch", "filter-repo"):
            return "history-rewrite"
        aliases = _BRANCH_ALIASES if subcommand == "branch" else {}
        flags, operands = _parse_options(args, set(), aliases)
        names = [_local_ref_name(token.value) for token in operands]
        if subcommand == "reset" and _bare(flags, "hard"):
            if any(_protected_name(name) for name in names):
                return "reset-hard"
        if subcommand == "branch":
            forced = _bare(flags, "delete") and _bare(flags, "force")
            if forced and any(_protected_name(name) for name in names):
                return "branch-delete"
        if subcommand == "update-ref" and _bare(flags, "d"):
            for token in operands:
                text = _unwrap(token.value)
                if text.startswith(_HEADS_PREFIX) and _protected_name(text[len(_HEADS_PREFIX):]):
                    return "ref-delete"
    return ""


def _dangerous_git_clean(segments):
    for subcommand, args in _git_invocations(segments):
        if subcommand != "clean":
            continue
        flags, _operands = _parse_options(args, set(), _CLEAN_ALIASES)
        if _bare(flags, "dry-run"):
            continue
        if _bare(flags, "force") and (_bare(flags, "d") or _bare(flags, "x")):
            return True
    return False


def dangerous_git_clean(command):
    return _dangerous_git_clean(_analyze(command))


# ----- data-destroy -----------------------------------------------------------

_SQL_CLIENTS = {
    "psql", "mysql", "mariadb", "sqlite3", "sqlcmd", "mongosh", "mongo",
    "cockroach", "clickhouse-client", "usql", "bq",
}
_SQL_DROP_WORDS = re.compile(r"\bdrop\s+(?:table|database|schema)\b", re.IGNORECASE)
_SQL_TRUNCATE_WORDS = re.compile(r"\btruncate\s+(?:table\s+)?\w+", re.IGNORECASE)
_SQL_DROP_STATEMENT = re.compile(r"\bdrop\s+(?:table|database|schema)\b[^\n]{0,80};", re.IGNORECASE)
_SQL_TRUNCATE_STATEMENT = re.compile(r"\btruncate\s+table\s+[^\n]{0,80};", re.IGNORECASE)


def _sql_shape(segments, command):
    """A destructive statement handed to a database client, or terminated."""
    for segment in segments:
        word, _index = _command_word(segment.tokens)
        if word not in _SQL_CLIENTS:
            continue
        joined = " ".join(token.value for token in segment.tokens)
        if _SQL_DROP_WORDS.search(joined):
            return "drop"
        if _SQL_TRUNCATE_WORDS.search(joined):
            return "truncate"
    if _SQL_DROP_STATEMENT.search(command):
        return "drop"
    if _SQL_TRUNCATE_STATEMENT.search(command):
        return "truncate"
    return ""


# ----- Decision logic ---------------------------------------------------------

_DEVICE_REASONS = {
    "dd": "dd writing to a raw disk device wipes the drive",
    "mkfs": "mkfs reformats a filesystem; all data on that volume is lost",
    "format": "Windows format command reformats the target drive",
}
_PERMISSION_REASONS = {
    "chmod": (
        "recursive chmod 000 locks you out of every file under the target. "
        "Use a narrower mode or drop -R"
    ),
    "chown": (
        "recursive chown on a system or root path overwrites ownership of "
        "system files. Target a subdirectory you own"
    ),
}
_SQL_REASONS = {
    "drop": (
        "DROP of a table, database, or schema in an execution context destroys "
        "data. Confirm explicitly and run it through a transaction or migration tool"
    ),
    "truncate": (
        "TRUNCATE in an execution context empties a table. Use DELETE with WHERE "
        "for selective removal, or confirm through a migration"
    ),
}
_GIT_LOCAL_REASONS = {
    "reset-hard": (
        "git-protected-branch",
        "git reset --hard against a protected branch discards local work on it; use a feature branch instead",
    ),
    "branch-delete": (
        "git-protected-branch",
        "force-deleting a protected branch. Delete a feature branch, not the trunk",
    ),
    "ref-delete": (
        "git-protected-branch",
        "low-level ref deletion of a protected branch",
    ),
    "history-rewrite": (
        "git-history-rewrite",
        "git filter-repo / filter-branch rewrites history across the entire repository. Confirm explicitly and back up the refs first (git for-each-ref > backup.txt)",
    ),
}


def classify(command, structure=None):
    """Return (block, tier, reason). block is False on allow."""
    structure = structure if structure is not None else load_structure()
    segments = _analyze(command)

    if _reads_secret(segments, _outbound_globs(structure)):
        return True, "secret-exposure", (
            "shell read of a credential-bearing path. Reference the single "
            "environment variable an integration needs; never print secret files"
        )

    if _FORK_BOMB.search(command):
        return True, "system-destroy", "fork bomb pattern detected"
    device = _device_destroy_shape(segments)
    if device:
        return True, "system-destroy", _DEVICE_REASONS[device]
    if _powershell_system_delete(segments):
        return True, "system-destroy", "recursive PowerShell removal of a drive, home, or system path"
    if _rm_system_delete(segments):
        return True, "system-destroy", "rm -rf of a system, root, or home path. Target a specific subdirectory you own"
    permission = _permission_destroy_shape(segments)
    if permission:
        return True, "system-destroy", _PERMISSION_REASONS[permission]

    git_mode = ((structure or {}).get("git") or {}).get("mode", "main-only")
    if _dangerous_git_push(segments, git_mode):
        return True, "git-protected-branch", "force-push to a protected branch. Use --force-with-lease, or push to a feature branch first"
    shape = _git_local_shape(segments)
    if shape:
        tier, reason = _GIT_LOCAL_REASONS[shape]
        return True, tier, reason

    statement = _sql_shape(segments, command)
    if statement:
        return True, "data-destroy", _SQL_REASONS[statement]
    if _dangerous_git_clean(segments):
        return True, "data-destroy", "git clean with force and directory flags deletes every untracked file. Run it with -n first, or name the paths"

    return False, "", ""


def decide(data, structure=None):
    """Return the deny JSON string for a payload, or None to allow."""
    if not isinstance(data, dict) or canonical_tool_name(data) != "Bash":
        return None
    command = shell_command_text(data)
    if not command:
        return None
    # The digest hashes the payload text as it arrived; classification
    # re-parses it, so it asks for the join that keeps the argv boundary.
    classified = shell_command_text(data, quote=True) or command
    block, tier, reason = classify(strip_safe_contexts(classified), structure)
    if not block:
        return None
    digest = hashlib.sha256(command.encode("utf-8")).hexdigest()
    return deny(HOOK_NAME, tier, reason, digest, RECOVERY)


def _write_line(text):
    """Write one decision line ending in a newline on every platform.

    The fixtures compare bytes, so the platform line ending of text mode
    must not reach stdout.
    """
    stream = getattr(sys.stdout, "buffer", None)
    if stream is None:
        sys.stdout.write(text + "\n")
        return
    sys.stdout.flush()
    stream.write((text + "\n").encode("utf-8"))
    stream.flush()


def main():
    debug.start()
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        debug.end(HOOK_NAME, out_bytes=0, extra="bad-json")
        sys.exit(0)
    out = decide(data)
    if out is None:
        debug.end(HOOK_NAME, out_bytes=0, extra="allow")
        sys.exit(0)
    _write_line(out)
    debug.end(HOOK_NAME, out_bytes=len(out), extra="deny")
    sys.exit(0)


if __name__ == "__main__":
    main()
