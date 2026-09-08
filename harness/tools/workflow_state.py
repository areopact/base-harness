#!/usr/bin/env python3
"""Pure state, graph, artifact, and lock primitives for managed workflows.

Stdlib only. Nothing here reads host configuration: the controller passes the
repository root, and every path is validated as a portable, repository-relative
file before it is touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
RUN_STATES = (
    "framed", "planned", "executing", "integrated", "verifying",
    "reviewing", "reviewed", "ready", "completed", "blocked", "cancelled", "cancel-pending",
)
PACKAGE_STATES = ("pending", "running", "completed", "failed", "cancelled")
# Names and suffixes that no workflow artifact may resolve to: local secret
# stores and key material stay outside every controller-managed write.
PROTECTED_NAMES = {".env", ".mcp.json"}
PROTECTED_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
# Any path with both segments is a secret boundary regardless of depth.
PROTECTED_SEGMENT_PAIR = ("harness", "secret")
RESERVED_PREFIX = "_managed-"
INTERNAL_TASKS = {"plan.work-packages", "review.adversarial", "verify.deterministic"}
SECRET_ACCESS = re.compile(r"(?im)^access:\s*([\"']?)secret\1\s*(?:#.*)?$")


class WorkflowError(RuntimeError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def atomic_create_json(path: Path, value: dict[str, Any]) -> None:
    """Create a complete JSON file exactly once; concurrent creators cannot replace it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise WorkflowError(f"workflow run already exists: {path.parent.name}") from exc
        except OSError as exc:
            raise WorkflowError(f"cannot atomically claim workflow run {path.parent.name}: {exc}") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            if value and not value.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def validate_text_artifact_content(path: Path, value: str) -> None:
    """Reject secret Markdown metadata before materializing controller-captured text."""
    if path.suffix.lower() != ".md" or not value.startswith("---"):
        return
    lines = value.splitlines()
    try:
        closing = lines.index("---", 1)
    except ValueError as exc:
        raise WorkflowError(f"captured Markdown frontmatter is unclosed: {path.name}") from exc
    frontmatter = "\n".join(lines[1:closing])
    if SECRET_ACCESS.search(frontmatter):
        raise WorkflowError(f"captured artifact access is secret: {path.name}")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"cannot read workflow JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise WorkflowError(f"workflow JSON must be an object: {path}")
    return value


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _crosses_secret_boundary(parts: list[str]) -> bool:
    return all(segment in parts for segment in PROTECTED_SEGMENT_PAIR)


def _protected_resolved_path(root: Path, path: Path, label: str) -> None:
    resolved = path.resolve(strict=False)
    try:
        relative = resolved.relative_to(root.resolve())
    except (OSError, ValueError) as exc:
        raise WorkflowError(f"artifact path escapes repository after link resolution: {label!r}") from exc
    lowered = [part.lower() for part in relative.parts]
    if _crosses_secret_boundary(lowered):
        raise WorkflowError(f"artifact path resolves across the secret boundary: {label!r}")
    if any(part in PROTECTED_NAMES or part.startswith(".env.") for part in lowered):
        raise WorkflowError(f"artifact path resolves to a protected file: {label!r}")
    if resolved.suffix.lower() in PROTECTED_SUFFIXES:
        raise WorkflowError(f"artifact path resolves to a protected key file: {label!r}")
    if resolved.is_file() and resolved.suffix.lower() == ".md":
        try:
            with resolved.open("rb") as handle:
                first = handle.readline(64)
                if first.decode("utf-8-sig", errors="replace").strip() != "---":
                    return
                lines, remaining, closed = [], 16_384, False
                while remaining > 0:
                    line = handle.readline(remaining + 1)
                    if not line:
                        break
                    remaining -= len(line)
                    decoded = line.decode("utf-8", errors="replace")
                    if decoded.strip() == "---":
                        closed = True
                        break
                    lines.append(decoded)
        except OSError as exc:
            raise WorkflowError(f"cannot inspect artifact access metadata: {label!r}") from exc
        if not closed:
            raise WorkflowError(f"artifact frontmatter is unclosed or too large: {label!r}")
        frontmatter = "".join(lines)
        if SECRET_ACCESS.search(frontmatter):
            raise WorkflowError(f"artifact access is secret: {label!r}")


def canonical_artifact(root: Path, relative: str, *, allow_missing: bool = True) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise WorkflowError("artifact path must be a non-empty repository-relative file")
    if "\\" in relative or Path(relative).is_absolute() or re.match(r"^[A-Za-z]:", relative):
        raise WorkflowError(f"artifact path must be portable and relative: {relative!r}")
    raw_parts = Path(relative).parts
    lowered = [part.lower() for part in raw_parts]
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise WorkflowError(f"artifact path is not normalized: {relative!r}")
    if _crosses_secret_boundary(lowered):
        raise WorkflowError(f"artifact path crosses the secret boundary: {relative!r}")
    if any(part in PROTECTED_NAMES or part.startswith(".env.") for part in lowered):
        raise WorkflowError(f"artifact path is protected: {relative!r}")
    if Path(relative).suffix.lower() in PROTECTED_SUFFIXES:
        raise WorkflowError(f"artifact path has a protected key suffix: {relative!r}")
    path = root / relative
    if not _inside(root, path):
        raise WorkflowError(f"artifact path escapes repository: {relative!r}")
    _protected_resolved_path(root, path, relative)
    if path.exists() and not path.is_file():
        raise WorkflowError(f"artifact path must name a file, not a directory: {relative!r}")
    if not allow_missing and not path.is_file():
        raise WorkflowError(f"artifact file is missing: {relative!r}")
    return path


def validate_artifact_paths(root: Path, values: list[str]) -> list[str]:
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise WorkflowError("artifact_paths must be a list of repository-relative files")
    normalized = []
    for item in values:
        path = canonical_artifact(root, item)
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        if rel in normalized:
            raise WorkflowError(f"duplicate artifact path: {rel}")
        normalized.append(rel)
    return normalized


def artifact_revision(root: Path, paths: list[str]) -> str:
    hasher = hashlib.sha256()
    for relative in sorted(validate_artifact_paths(root, paths)):
        path = canonical_artifact(root, relative)
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        if path.is_file():
            hasher.update(b"file\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
        else:
            hasher.update(b"missing\0")
    return hasher.hexdigest()


def read_artifacts_for_review(root: Path, paths: list[str], limit: int = 2_000_000) -> str:
    blocks, used = [], 0
    for relative in sorted(validate_artifact_paths(root, paths)):
        path = canonical_artifact(root, relative, allow_missing=False)
        data = path.read_bytes()
        used += len(data)
        if used > limit:
            raise WorkflowError(f"review packet exceeds {limit} bytes")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkflowError(f"review artifact is not UTF-8 text: {relative}") from exc
        blocks.append(f"FILE: {relative}\n{text}")
    return "\n\n".join(blocks)


class ExclusiveLock:
    """A lock file that never expires: release requires a confirmed-stopped owner."""

    def __init__(self, path: Path, owner: dict[str, Any]):
        self.path = path
        self.owner = owner
        self.token = secrets.token_hex(16)
        self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {**self.owner, "token": self.token}
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            existing = "unreadable"
            try:
                existing = self.path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
            raise WorkflowError(f"canonical writer lock is already held: {existing}") from exc
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        self.acquired = True

    def release(self, *, process_stopped: bool) -> None:
        if not self.acquired:
            return
        if not process_stopped:
            raise WorkflowError("writer lock cannot be released until the owned process is confirmed stopped")
        current = read_json(self.path)
        if current.get("token") != self.token:
            raise WorkflowError("writer lock ownership changed; refusing release")
        self.path.unlink()
        self.acquired = False


def _package(raw: dict[str, Any], root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id", "task_id", "prompt", "artifact_paths", "result_artifact",
        "dependencies", "explicit_model_override", "timeout_seconds", "max_turns", "floor_flags",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise WorkflowError(f"package has unknown fields: {', '.join(unknown)}")
    package_id = raw.get("id")
    if not isinstance(package_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", package_id):
        raise WorkflowError(f"invalid package id: {package_id!r}")
    if package_id.startswith(RESERVED_PREFIX):
        raise WorkflowError(f"package id uses reserved prefix {RESERVED_PREFIX}")
    task_id = raw.get("task_id")
    if task_id not in policy["tasks"]:
        raise WorkflowError(f"unknown task ID: {task_id!r}")
    if task_id in INTERNAL_TASKS:
        raise WorkflowError(f"task {task_id} is controller-managed and cannot be supplied")
    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise WorkflowError(f"package {package_id} needs a non-empty prompt")
    dependencies = raw.get("dependencies", [])
    if not isinstance(dependencies, list) or any(not isinstance(item, str) for item in dependencies):
        raise WorkflowError(f"package {package_id} dependencies must be string IDs")
    timeout = raw.get("timeout_seconds", 900)
    max_turns = raw.get("max_turns", 24)
    if not isinstance(timeout, int) or not 1 <= timeout <= 3600:
        raise WorkflowError(f"package {package_id} timeout_seconds must be 1..3600")
    if not isinstance(max_turns, int) or not 1 <= max_turns <= 100:
        raise WorkflowError(f"package {package_id} max_turns must be 1..100")
    override = raw.get("explicit_model_override")
    if override is not None and not isinstance(override, dict):
        raise WorkflowError(f"package {package_id} explicit_model_override must be a recorded object")
    floor_flags = raw.get("floor_flags", {})
    allowed_flags = {"numeric_deliverable", "dense_legal_financial", "external_write", "bidirectional_conflict", "high_stakes"}
    if not isinstance(floor_flags, dict) or set(floor_flags) - allowed_flags:
        raise WorkflowError(f"package {package_id} floor_flags contains unsupported keys")
    if any(not isinstance(value, bool) for value in floor_flags.values()):
        raise WorkflowError(f"package {package_id} floor_flags values must be booleans")
    artifact_paths = validate_artifact_paths(root, raw.get("artifact_paths", []))
    result_artifact = raw.get("result_artifact")
    if result_artifact is not None:
        result_artifact = validate_artifact_paths(root, [result_artifact])[0]
        if artifact_paths != [result_artifact]:
            raise WorkflowError(
                f"package {package_id} result_artifact must be its one explicit artifact path"
            )
    return {
        "id": package_id,
        "task_id": task_id,
        "prompt": prompt.strip(),
        "artifact_paths": artifact_paths,
        "result_artifact": result_artifact,
        "dependencies": list(dict.fromkeys(dependencies)),
        "explicit_model_override": override,
        "timeout_seconds": timeout,
        "max_turns": max_turns,
        "floor_flags": {key: bool(floor_flags.get(key, False)) for key in sorted(allowed_flags)},
        "managed_kind": "worker",
    }


def _assert_acyclic(packages: list[dict[str, Any]]) -> None:
    ids = {package["id"] for package in packages}
    for package in packages:
        missing = sorted(set(package["dependencies"]) - ids)
        if missing:
            raise WorkflowError(f"package {package['id']} has unknown dependencies: {', '.join(missing)}")
        if package["id"] in package["dependencies"]:
            raise WorkflowError(f"package {package['id']} depends on itself")
    visiting, visited = set(), set()
    graph = {package["id"]: package["dependencies"] for package in packages}

    def visit(node: str) -> None:
        if node in visiting:
            raise WorkflowError(f"dependency cycle includes {node}")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for package_id in graph:
        visit(package_id)


def normalize_spec(raw: dict[str, Any], root: Path, policy: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version", "runtime", "planning_depth", "mode", "requirements",
        "acceptance_criteria", "source_evidence", "work_packages", "ratification",
    }
    forbidden = sorted(set(raw) & {"receipts", "results", "passed", "native_evidence"})
    if forbidden:
        raise WorkflowError(f"input cannot import result or receipt fields: {', '.join(forbidden)}")
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise WorkflowError(f"workflow spec has unknown fields: {', '.join(unknown)}")
    if raw.get("schema_version", 1) != SCHEMA_VERSION:
        raise WorkflowError(f"unsupported workflow schema_version: {raw.get('schema_version')!r}")
    runtime = raw.get("runtime")
    if runtime not in policy["runtime_constraints"]:
        raise WorkflowError(f"unsupported runtime: {runtime!r}")
    planning = raw.get("planning_depth", "T2")
    if planning not in {"T2", "T3"}:
        raise WorkflowError("managed workflow planning_depth must be T2 or T3")
    mode = raw.get("mode", "managed")
    if mode not in {"managed", "strict"}:
        raise WorkflowError("mode must be managed or strict")
    requirements = raw.get("requirements")
    if not isinstance(requirements, str) or not requirements.strip():
        raise WorkflowError("requirements must be non-empty text")
    criteria = raw.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria or any(not isinstance(item, str) or not item.strip() for item in criteria):
        raise WorkflowError("acceptance_criteria must be a non-empty string list")
    evidence = raw.get("source_evidence", [])
    if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
        raise WorkflowError("source_evidence must be a string list")
    ratification = raw.get("ratification")
    if not isinstance(ratification, dict) or ratification.get("actor") != "main" or ratification.get("authorized") is not True:
        raise WorkflowError("ratification must record {actor: main, authorized: true}")
    package_rows = raw.get("work_packages")
    if not isinstance(package_rows, list) or not package_rows:
        raise WorkflowError("work_packages must contain at least one substantive package")
    packages = [_package(item, root, policy) for item in package_rows if isinstance(item, dict)]
    if len(packages) != len(package_rows):
        raise WorkflowError("every work package must be an object")
    ids = [package["id"] for package in packages]
    if len(ids) != len(set(ids)):
        raise WorkflowError("work package IDs must be unique")
    _assert_acyclic(packages)

    writers: dict[str, str] = {}
    for package in packages:
        native_writer = task_writes_canonical(policy, package["task_id"])
        if native_writer and package["result_artifact"]:
            raise WorkflowError(f"writer package {package['id']} cannot also capture its result")
        writes_production = native_writer or bool(package["result_artifact"])
        if writes_production and not package["artifact_paths"]:
            raise WorkflowError(f"writer package {package['id']} must name explicit artifact files")
        if writes_production:
            for artifact in package["artifact_paths"]:
                prior = writers.get(artifact)
                if prior:
                    raise WorkflowError(f"canonical artifact {artifact} has two writers: {prior}, {package['id']}")
                writers[artifact] = package["id"]
    if not writers:
        raise WorkflowError("managed execution requires at least one explicit canonical artifact writer")
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime": runtime,
        "planning_depth": planning,
        "mode": mode,
        "requirements": requirements.strip(),
        "acceptance_criteria": [item.strip() for item in criteria],
        "source_evidence": evidence,
        "ratification": ratification,
        "work_packages": packages,
    }


def task_writes_canonical(policy: dict[str, Any], task_id: str) -> bool:
    """Treat every authored non-scratch write scope as canonical mutation."""
    task = policy["tasks"][task_id]
    tool = policy["tool_profiles"][task["tool_profile"]]
    scope = str(tool["write_scope"]).strip().lower()
    return not (scope == "none" or scope.startswith("scratch") or scope.startswith(".tmp/"))


def seed_managed_packages(spec: dict[str, Any]) -> list[dict[str, Any]]:
    workers = [dict(package) for package in spec["work_packages"]]
    worker_ids = [package["id"] for package in workers]
    artifacts = sorted({path for package in workers for path in package["artifact_paths"]})
    planner = {
        "id": "_managed-plan", "task_id": "plan.work-packages", "prompt": "",
        "artifact_paths": [], "dependencies": [], "explicit_model_override": None,
        "timeout_seconds": 600, "max_turns": 12, "managed_kind": "planner",
        "floor_flags": {},
    }
    if spec["planning_depth"] == "T3":
        analyst = {
            "id": "_managed-analysis", "task_id": "resolve.conflict", "prompt": "",
            "artifact_paths": [], "dependencies": ["_managed-plan"],
            "explicit_model_override": None, "timeout_seconds": 600, "max_turns": 12,
            "managed_kind": "analyst", "floor_flags": {},
        }
        for worker in workers:
            worker["dependencies"] = list(dict.fromkeys(["_managed-analysis", *worker["dependencies"]]))
        verifier = {
            "id": "_managed-verify", "task_id": "verify.deterministic", "prompt": "",
            "artifact_paths": artifacts, "dependencies": worker_ids,
            "explicit_model_override": None, "timeout_seconds": 600, "max_turns": 12,
            "managed_kind": "verifier",
            "floor_flags": {},
        }
        review_dependencies = [*worker_ids, "_managed-verify"]
        body = [analyst, *workers, verifier]
    else:
        for worker in workers:
            worker["dependencies"] = list(dict.fromkeys(["_managed-plan", *worker["dependencies"]]))
        review_dependencies = worker_ids
        body = workers
    reviewer = {
        "id": "_managed-review", "task_id": "review.adversarial", "prompt": "",
        "artifact_paths": artifacts, "dependencies": review_dependencies,
        "explicit_model_override": None, "timeout_seconds": 900, "max_turns": 18,
        "managed_kind": "reviewer", "review_of": worker_ids,
        "floor_flags": {},
    }
    packages = [planner, *body, reviewer]
    _assert_acyclic(packages)
    return packages


def topological(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = {package["id"]: package for package in packages}
    ordered, done = [], set()
    while remaining:
        ready = sorted(
            (package for package in remaining.values() if set(package["dependencies"]) <= done),
            key=lambda item: item["id"],
        )
        if not ready:
            raise WorkflowError("workflow graph is cyclic or incomplete")
        for package in ready:
            ordered.append(package)
            done.add(package["id"])
            del remaining[package["id"]]
    return ordered
