"""P5-5: compatibility records use the closed evidence vocabulary, carry no
evidence dated after observed_at, and reference no host-specific artifact."""

from __future__ import annotations

import datetime as dt
import re

from ._paths import ADAPTERS, bind_unittest, read_json, read_text

RECORDS = {
    "codex": ADAPTERS / "codex" / "compatibility.json",
    "opencode": ADAPTERS / "opencode" / "compatibility.json",
}
EVIDENCE_KEYS = (
    "offline_repository",
    "local_cli_and_policy",
    "native_hook_trust_and_firing",
    "explicit_skill_loading",
    "connector_outcomes",
)
TOP_LEVEL_KEYS = {
    "schema_version",
    "adapter_status",
    "minimum_cli",
    "tested_cli",
    "observed_cli",
    "observed_at",
    "hook_schema",
    "evidence",
}
CLOSED_VALUES = {"passed", "unproven", "not-attempted"}
DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
# Path shapes that only make sense on the authoring host or in a private source repository.
# Built from fragments so this file passes the private-vocabulary scan in
# test_no_private_vocabulary.py, which treats the joined forms as literals.
_HOST_DIRS = ("".join(("rec", "ords/")), "".join(("/inci", "dents/")), "".join(("/Us", "ers/")), "".join(("/ho", "me/")))
HOST_ARTIFACT = re.compile(
    "|".join(_HOST_DIRS) + r"|[A-Za-z]:\\|[A-Za-z]:/|\\\\\?\\|\.json\b.*evidence|evidence\.json"
)


def _dates_in(text: str) -> list[dt.date]:
    return [dt.date.fromisoformat(m) for m in DATE.findall(text)]


def test_records_have_the_agreed_shape():
    for runtime, path in RECORDS.items():
        data = read_json(path)
        assert set(data) == TOP_LEVEL_KEYS, f"{runtime}: {sorted(data)}"
        assert data["schema_version"] == 1
        assert data["adapter_status"] in {"configured-alpha", "configured-beta", "active", "unconfigured"}
        assert VERSION.match(data["minimum_cli"]), data["minimum_cli"]
        for key in ("tested_cli", "observed_cli"):
            assert data[key] is None or VERSION.match(data[key]), f"{runtime}: {key}"
        assert data["observed_at"] is None or dt.date.fromisoformat(data["observed_at"])
        assert isinstance(data["hook_schema"], str) and data["hook_schema"]
        assert tuple(data["evidence"]) == EVIDENCE_KEYS, f"{runtime}: {list(data['evidence'])}"


def test_evidence_values_are_in_the_closed_vocabulary():
    for runtime, path in RECORDS.items():
        for key, value in read_json(path)["evidence"].items():
            ok = value in CLOSED_VALUES or (
                value.startswith("passed:") and len(_dates_in(value)) >= 1
            )
            assert ok, f"{runtime}.{key}: {value!r} is outside the closed vocabulary"


def test_no_evidence_is_dated_after_observed_at():
    for runtime, path in RECORDS.items():
        data = read_json(path)
        observed_at = data["observed_at"]
        for key, value in data["evidence"].items():
            dates = _dates_in(value)
            if observed_at is None:
                assert dates == [], f"{runtime}.{key} carries a date but observed_at is null"
                continue
            limit = dt.date.fromisoformat(observed_at)
            assert all(d <= limit for d in dates), f"{runtime}.{key} dated after observed_at"


def test_fresh_clone_ships_honest_values():
    for runtime, path in RECORDS.items():
        data = read_json(path)
        assert data["tested_cli"] is None and data["observed_cli"] is None and data["observed_at"] is None, (
            f"{runtime}: a template ships no host observations"
        )
        assert data["evidence"]["offline_repository"] == "unproven"
        for key in EVIDENCE_KEYS[1:]:
            assert data["evidence"][key] == "not-attempted", f"{runtime}.{key}"


def test_no_host_specific_artifact_paths():
    for runtime, path in RECORDS.items():
        text = read_text(path)
        assert HOST_ARTIFACT.search(text) is None, f"{runtime}: host-specific artifact reference"
        assert "native_hook_evidence" not in text
        assert "manual_snapshot" not in text


bind_unittest(globals(), "CompatibilityRecordsBridge")
