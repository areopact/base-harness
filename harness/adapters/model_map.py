"""Load an adapter's model map and mark unresolved families.

The four family keys are fixed by the routing policy. A ``null`` provider id
is legal and means "unresolved on this runtime"; the loader records it as
``UNKNOWN`` so a doctor prints UNKNOWN instead of substituting a default.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RUNTIMES = ("claude", "codex", "opencode")
FAMILY_KEYS = ("fast", "balanced", "strong", "strong-main")
PERMISSION_CLASSES = ("read-only", "edit", "shell")

RESOLVED = "resolved"
UNKNOWN = "UNKNOWN"


class ModelMapError(ValueError):
    """The model map is missing, malformed, or violates the shared shape."""


def model_map_path(runtime: str, root: Path | None = None) -> Path:
    if runtime not in RUNTIMES:
        raise ModelMapError(f"unknown runtime: {runtime}")
    return Path(root or ROOT) / "harness" / "adapters" / runtime / "model-map.json"


def load_model_map(runtime: str, root: Path | None = None) -> dict:
    """Return the map plus a per-family resolution state.

    Result keys: ``runtime``, ``families`` (as written, nulls kept),
    ``permission_classes``, ``resolution`` (family -> "resolved" or
    "UNKNOWN"), ``unresolved`` (sorted family names with a null id).
    Raises ModelMapError on a malformed file; never fills in a default id.
    """
    path = model_map_path(runtime, root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ModelMapError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ModelMapError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelMapError(f"{path} must contain one JSON object")
    if data.get("schema_version") != 1:
        raise ModelMapError(f"{path}: schema_version must be 1")
    if data.get("runtime") not in (None, runtime):
        raise ModelMapError(f"{path}: runtime field does not match {runtime}")

    families = data.get("families")
    if not isinstance(families, dict):
        raise ModelMapError(f"{path}: families must be an object")
    if tuple(sorted(families)) != tuple(sorted(FAMILY_KEYS)):
        raise ModelMapError(
            f"{path}: families must carry exactly {sorted(FAMILY_KEYS)}, got {sorted(families)}"
        )
    resolution: dict[str, str] = {}
    for family, provider_id in families.items():
        if provider_id is None:
            resolution[family] = UNKNOWN
        elif isinstance(provider_id, str) and provider_id.strip():
            resolution[family] = RESOLVED
        else:
            raise ModelMapError(f"{path}: family {family!r} must be a non-empty string or null")

    classes = data.get("permission_classes")
    if not isinstance(classes, dict):
        raise ModelMapError(f"{path}: permission_classes must be an object")
    for name in PERMISSION_CLASSES:
        tools = classes.get(name)
        if not isinstance(tools, list) or not all(isinstance(t, str) and t for t in tools):
            raise ModelMapError(f"{path}: permission_classes.{name} must be a list of tool names")

    return {
        "runtime": runtime,
        "path": str(path),
        "families": dict(families),
        "permission_classes": {k: list(v) for k, v in classes.items()},
        "resolution": resolution,
        "unresolved": sorted(f for f, state in resolution.items() if state == UNKNOWN),
    }


def doctor_lines(runtime: str, root: Path | None = None) -> list[tuple[str, str, str]]:
    """Return (layer, state, message) triples in the doctor's vocabulary."""
    try:
        loaded = load_model_map(runtime, root)
    except ModelMapError as exc:
        return [("configured", "FAIL", f"model map: {exc}")]
    lines = [("configured", "OK", f"model map carries the four family keys ({runtime})")]
    for family in FAMILY_KEYS:
        if loaded["resolution"][family] == UNKNOWN:
            lines.append(("configured", "UNKNOWN", f"model family {family}: provider id unresolved (null)"))
        else:
            lines.append(("configured", "OK", f"model family {family}: {loaded['families'][family]}"))
    return lines


if __name__ == "__main__":
    import sys

    for name in (sys.argv[1:] or RUNTIMES):
        for layer, state, message in doctor_lines(name):
            print(f"  [{layer:<14}] {state:<7} {message}")
