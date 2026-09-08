#!/usr/bin/env python3
"""Read canonical skill metadata and compute the selected skill set.

Shared by materialize.py, both adapter builders, validate_skills.py, and the
doctors. Stdlib only. The frontmatter reader understands the subset of YAML
that harness/skills/README.md prescribes: top-level scalars, folded or
literal blocks, and one nested ``metadata:`` mapping whose values are
scalars, inline lists, or dash lists.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

VALID_STATUSES = ("implemented", "spec-only", "stub")
VALID_DISTRIBUTIONS = ("native", "vendored", "runtime-provided")
VALID_LICENSES = ("MIT", "Apache-2.0", "BSD-3-Clause", "source-available", "none")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DEFAULT_SELECTION = {"schema_version": 1, "packs": ["core", "maintain"], "include": [], "exclude": []}
SKILLS_RELATIVE = "harness/skills"
MAX_DESCRIPTION_CHARS = 160
UTF8_BOM = "\ufeff"


class SkillError(ValueError):
    """A skill file is malformed."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    status: str
    directory: str
    relative: str = ""
    packs: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    distribution: str = "native"
    license: str = "none"
    requires: tuple[str, ...] = ()
    notice: str | None = None
    raw: dict = field(default_factory=dict, compare=False, hash=False)

    def public_dict(self) -> dict:
        """Deterministic, hashable view used for catalog digests."""
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "packs": list(self.packs),
            "distribution": self.distribution,
            "license": self.license,
        }


def frontmatter(text: str) -> str:
    text = text.lstrip(UTF8_BOM)
    if not text.startswith("---\n"):
        raise SkillError("missing YAML frontmatter")
    end = text.find("\n---", 4)
    if end < 0:
        raise SkillError("unterminated YAML frontmatter")
    return text[4:end]


def _unquote(value: str) -> object:
    value = value.strip()
    if value == "" or value in {"null", "~"}:
        return None
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'") and len(value) >= 2:
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_unquote(item) for item in _split_inline_list(inner)]
    if value == "true":
        return True
    if value == "false":
        return False
    return value


def _split_inline_list(inner: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    quote = None
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
            current.append(char)
        elif char == ",":
            items.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        items.append("".join(current))
    return [item for item in items if item.strip()]


def parse_frontmatter(fm: str) -> dict:
    """Parse the supported YAML subset into a dict. Unknown shapes raise."""
    lines = fm.splitlines()
    result: dict = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        if line[0].isspace():
            raise SkillError(f"unexpected indented line at top level: {line.strip()!r}")
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not match:
            raise SkillError(f"unparseable frontmatter line: {line!r}")
        key, value = match.group(1), match.group(2).strip()
        index += 1
        if value in {">", ">-", "|", "|-"}:
            block: list[str] = []
            while index < len(lines) and (not lines[index].strip() or lines[index][0].isspace()):
                block.append(lines[index].strip())
                index += 1
            if value.startswith(">"):
                result[key] = " ".join(part for part in block if part)
            else:
                result[key] = "\n".join(block).strip()
            continue
        if value == "":
            nested, index = _parse_block(lines, index)
            result[key] = nested
            continue
        result[key] = _unquote(value)
    return result


def _parse_block(lines: list[str], index: int) -> tuple[object, int]:
    """Parse an indented mapping or dash list starting at lines[index]."""
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or not lines[index][0].isspace():
        return None, index
    indent = len(lines[index]) - len(lines[index].lstrip())
    stripped = lines[index].strip()
    if stripped.startswith("- "):
        items: list[object] = []
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            current = len(line) - len(line.lstrip())
            if current < indent:
                break
            body = line.strip()
            if current == indent and body.startswith("- "):
                items.append(_unquote(body[2:]))
                index += 1
                continue
            raise SkillError(f"unsupported list shape: {line.strip()!r}")
        return items, index
    mapping: dict = {}
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.strip().startswith("#"):
            index += 1
            continue
        current = len(line) - len(line.lstrip())
        if current < indent:
            break
        if current > indent:
            raise SkillError(f"unexpected indentation: {line.strip()!r}")
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line.strip())
        if not match:
            raise SkillError(f"unparseable nested line: {line.strip()!r}")
        key, value = match.group(1), match.group(2).strip()
        index += 1
        if value == "":
            nested, index = _parse_block(lines, index)
            mapping[key] = nested if nested is not None else []
        else:
            mapping[key] = _unquote(value)
    return mapping, index


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SkillError(f"{label} must be a list of strings")
    return tuple(value)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    cut = value[: max(1, limit - 3)].rsplit(" ", 1)[0]
    if cut.count('"') % 2:
        # The word-boundary cut fell inside a quoted phrase (a trigger such as
        # "pressure-test this plan"); drop the partial phrase rather than ship
        # half of it.
        head = cut[: cut.rfind('"')].rstrip(" ,;")
        if head:
            cut = head
    return cut.rstrip(".,;:") + "..."


def short_description(description: str) -> str:
    """Compact the description while keeping the WHEN trigger language."""
    compact = " ".join(description.split())
    when = re.search(r"\s+WHEN:\s*(.+?)(?:\s+WHEN NOT:|$)", compact)
    if not when:
        return _truncate(compact, MAX_DESCRIPTION_CHARS)
    summary = _truncate(compact[: when.start()].strip(), 100)
    trigger_budget = MAX_DESCRIPTION_CHARS - len(summary) - len(" WHEN: ")
    trigger = _truncate(when.group(1).strip(), max(20, trigger_budget))
    return f"{summary} WHEN: {trigger}"


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def display_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("-"))


def load_skill(skill_md: Path, relative: str | None = None) -> Skill:
    """Parse one SKILL.md. relative is the repo-relative POSIX skill directory."""
    directory = skill_md.parent.name
    if relative is None:
        relative = f"{SKILLS_RELATIVE}/{directory}"
    data = parse_frontmatter(frontmatter(skill_md.read_text(encoding="utf-8-sig")))
    name = data.get("name") or directory
    if name != directory:
        raise SkillError(f"name '{name}' must match directory '{directory}'")
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SkillError("missing description")
    metadata = data.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise SkillError("metadata must be a mapping")
    status = metadata.get("status", data.get("status"))
    if status not in VALID_STATUSES:
        raise SkillError(f"invalid or missing metadata.status '{status}'")
    distribution = metadata.get("distribution", "native")
    if distribution not in VALID_DISTRIBUTIONS:
        raise SkillError(f"invalid metadata.distribution '{distribution}'")
    license_value = metadata.get("license", "none")
    if not isinstance(license_value, str):
        raise SkillError("metadata.license must be a string")
    notice = metadata.get("notice")
    if notice is not None and not isinstance(notice, str):
        raise SkillError("metadata.notice must be a string or null")
    return Skill(
        name=name,
        description=" ".join(description.split()),
        status=status,
        directory=directory,
        relative=relative,
        packs=_string_list(metadata.get("packs"), "metadata.packs"),
        triggers=_string_list(metadata.get("triggers"), "metadata.triggers"),
        distribution=distribution,
        license=license_value,
        requires=_string_list(metadata.get("requires"), "metadata.requires"),
        notice=notice,
        raw=data,
    )


def read_skills(source: Path) -> dict[str, Skill]:
    """Read every skill under source (harness/skills). An absent tree is empty.

    Native skills live at ``<name>/SKILL.md``; vendored skills live at
    ``_vendor/<source>/<name>/SKILL.md``. Every other underscore or dot
    prefixed directory is ignored.
    """
    skills: dict[str, Skill] = {}
    errors: list[str] = []
    source = Path(source)
    if not source.is_dir():
        return skills
    candidates = [p for p in source.glob("*/SKILL.md") if not p.parent.name.startswith(("_", "."))]
    candidates += list(source.glob("_vendor/*/*/SKILL.md"))
    for skill_md in sorted(candidates):
        relative = f"{SKILLS_RELATIVE}/{skill_md.parent.relative_to(source).as_posix()}"
        try:
            skill = load_skill(skill_md, relative)
        except (OSError, SkillError, UnicodeDecodeError) as exc:
            errors.append(f"{relative}/SKILL.md: {exc}")
            continue
        if skill.name in skills:
            errors.append(f"{relative}/SKILL.md: duplicate skill name '{skill.name}' (also {skills[skill.name].relative})")
            continue
        skills[skill.name] = skill
    if errors:
        raise SkillError("\n".join(errors))
    return skills


def load_selection(root: Path) -> dict:
    """Read harness/registry/selection.json; a missing file is the default."""
    path = root / "harness" / "registry" / "selection.json"
    if not path.is_file():
        return json.loads(json.dumps(DEFAULT_SELECTION))
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SkillError("selection.json must contain one object")
    merged = json.loads(json.dumps(DEFAULT_SELECTION))
    merged.update(value)
    for key in ("packs", "include", "exclude"):
        items = merged.get(key)
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise SkillError(f"selection.json {key} must be a list of strings")
    return merged


def select_skills(skills: dict[str, Skill], selection: dict) -> tuple[list[str], list[str]]:
    """Return (selected names sorted, warnings). Effective set per the contract."""
    packs = set(selection.get("packs", []))
    include = list(selection.get("include", []))
    exclude = list(selection.get("exclude", []))
    warnings: list[str] = []
    chosen = {name for name, skill in skills.items() if packs.intersection(skill.packs)}
    for name in include:
        if name in skills:
            chosen.add(name)
        else:
            warnings.append(f"selection include names a skill that does not exist: {name}")
    for name in exclude:
        if name not in skills:
            warnings.append(f"selection exclude names a skill that does not exist: {name}")
        chosen.discard(name)
    return sorted(chosen), warnings


def selected_skills(root: Path) -> tuple[dict[str, Skill], list[str], list[str]]:
    """Convenience: (all skills, selected names, warnings) for a repository."""
    skills = read_skills(root / "harness" / "skills")
    selected, warnings = select_skills(skills, load_selection(root))
    return skills, selected, warnings
