#!/usr/bin/env python3
"""Managed T2/T3 workflow controller with native child-process evidence.

The controller plans a ratified work-package spec, seeds the mandatory
planner, reviewer, and (for T3) analyst and verifier stages, runs each package
as a controller-owned native child process, and records receipts under the
machine-state workflows directory (one folder per run id). Nothing here parses
base-routing.md: the policy is
loaded through routing_policy and native selections come from native_routing.

Usage:
    python harness/tools/workflow.py [--opt-in] plan <spec.json>
    python harness/tools/workflow.py [--opt-in] start <spec.json> [--run-id ID]
    python harness/tools/workflow.py [--opt-in] run|resume|status|cancel <run-id>

Gate: the delegation engine is opt-in. The CLI refuses to run when
harness/registry/structure.json sets delegation.mandatory to false and the
--opt-in flag is absent; it prints the one-line reason and exits 2.

Stdlib only, plus routing_policy and workflow_state from this directory.
"""

from __future__ import annotations

# A sibling module in this directory shares its name with the standard
# library's select module, and a script's own directory heads sys.path. Keep
# this directory at the tail of sys.path so the stdlib wins for "import select"
# while sibling modules still resolve, and pin the stdlib module before any
# later import (subprocess on POSIX needs it) can be shadowed.
import os as _os
import sys as _sys

_TOOLS_DIR = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:] = [entry for entry in _sys.path if _os.path.abspath(entry or _os.curdir) != _TOOLS_DIR]
_sys.path.append(_TOOLS_DIR)
import selectors as _selectors  # noqa: E402,F401  (imports the stdlib select module)

import argparse
import hashlib
import importlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from workflow_state import (
    ExclusiveLock,
    WorkflowError,
    artifact_revision,
    atomic_create_json,
    atomic_write_json,
    atomic_write_text,
    canonical_artifact,
    digest,
    normalize_spec,
    read_artifacts_for_review,
    read_json,
    seed_managed_packages,
    task_writes_canonical,
    topological,
    validate_text_artifact_content,
)


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = Path(__file__).resolve().parent
import routing_policy as rp  # noqa: E402

STRUCTURE = Path("harness/registry/structure.json")


def delegation_mandatory(root: Path) -> bool:
    """Read structure.json delegation.mandatory through the registry loader.

    harness_registry.load_structure() is the validating loader. When it is not
    importable (a partial checkout), fall back to a direct read of the same
    file with the contract default (false). A malformed file also reads as
    false: the gate only opens on an explicit true.
    """
    try:
        import harness_registry  # type: ignore

        structure = harness_registry.load_structure(root)
    except Exception:  # noqa: BLE001 - any loader failure means "not mandatory"
        path = Path(root) / STRUCTURE
        try:
            structure = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return False
    delegation = structure.get("delegation") if isinstance(structure, dict) else None
    return isinstance(delegation, dict) and delegation.get("mandatory") is True


def delegation_gate(root: Path, opt_in: bool) -> str | None:
    """Return the one-line refusal reason, or None when the controller may run."""
    if opt_in or delegation_mandatory(root):
        return None
    return (
        "workflow: delegation is opt-in on this host "
        f"({STRUCTURE.as_posix()} delegation.mandatory is false); pass --opt-in to run"
    )


def safe_child_env() -> dict[str, str]:
    """Preserve runtime authentication while removing parent child-model forcing."""
    child = dict(os.environ)
    child.pop("CLAUDE_CODE_SUBAGENT_MODEL", None)
    return child


def _selection_support(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "supported" if value else "unsupported"
    if isinstance(value, dict):
        return str(value.get("status", value.get("execution", "unknown")))
    return "unknown"


def _effective_model_matches(selection: dict[str, Any], evidence: dict[str, Any]) -> bool:
    if evidence.get("status") != "proven":
        return True
    observed = evidence.get("model")
    if not isinstance(observed, str) or not observed:
        return False
    approved = selection.get("observed_effective_model")
    if isinstance(approved, str) and approved:
        return observed == approved
    return observed == selection["native_model"]


def _normalize_model_evidence(selection: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    if evidence.get("status") != "proven" or _effective_model_matches(selection, evidence):
        return evidence
    if selection.get("observed_effective_model"):
        return evidence
    return {
        **evidence,
        "status": "unverified",
        "source": "native event emitted a model without an adapter-approved effective observation",
    }


def resolve_native(
    root: Path,
    policy: dict[str, Any],
    package: dict[str, Any],
    runtime: str,
    resolver: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    flags = {key: value for key, value in package.get("floor_flags", {}).items() if value}
    floor = rp.composite_floor(policy, package["task_id"], **flags)
    original_tier = rp.CAPABILITY_RANK[policy["profiles"][policy["tasks"][package["task_id"]]["executor"]]["tier"]]
    resolved_tier = rp.CAPABILITY_RANK[policy["profiles"][floor["executor_profile"]]["tier"]]
    if resolved_tier < original_tier:
        raise WorkflowError(f"composite floor lowered capability for {package['id']}")
    if resolver is None:
        try:
            module = importlib.import_module("native_routing")
            resolver = module.resolve_native
        except (ImportError, AttributeError) as exc:
            raise WorkflowError("native routing resolver is unavailable; generate native adapters first") from exc
    try:
        selection = resolver(
            root,
            package["task_id"],
            runtime,
            profile=floor["executor_profile"],
            explicit_model_override=package.get("explicit_model_override"),
            phase="execute",
        )
    except Exception as exc:  # adapters return actionable details through their exception
        raise WorkflowError(f"native routing failed for {package['id']}: {exc}") from exc
    if not isinstance(selection, dict):
        raise WorkflowError(f"native routing returned no selection for {package['id']}")
    required = {
        "task_id", "profile", "role", "role_id", "model_family", "native_model", "tool_profile",
        "native_permissions", "native_tools", "missing_capabilities",
        "permission_limitations", "support", "effective_model_evidence",
        "observed_effective_model", "source_hash", "output_check", "escalation",
    }
    missing = sorted(key for key in required if key not in selection)
    if missing:
        raise WorkflowError(f"native selection for {package['id']} misses: {', '.join(missing)}")
    if selection["task_id"] != package["task_id"] or selection["profile"] != floor["executor_profile"]:
        raise WorkflowError(f"native selection for {package['id']} does not match requested task/profile")
    if selection["source_hash"] != rp.policy_digest(policy):
        raise WorkflowError(f"native selection for {package['id']} uses a stale policy hash")
    if selection["role"] == "main":
        raise WorkflowError(f"managed package {package['id']} resolved to forbidden main-only profile")
    if not isinstance(selection["native_model"], str) or not selection["native_model"]:
        raise WorkflowError(f"native selection for {package['id']} has no exact model")
    normal_families = set(policy["runtime_constraints"][runtime]["child_families"])
    if selection["model_family"] not in normal_families and package.get("explicit_model_override") is None:
        raise WorkflowError(f"native selection for {package['id']} exceeds the normal child model ceiling")
    missing_capabilities = selection["missing_capabilities"]
    if not isinstance(missing_capabilities, list):
        raise WorkflowError(f"native selection for {package['id']} has invalid capability evidence")
    if missing_capabilities:
        raise WorkflowError(
            f"native selection for {package['id']} misses capabilities: "
            + ", ".join(str(value) for value in missing_capabilities)
        )
    if not isinstance(selection["permission_limitations"], list):
        raise WorkflowError(f"native selection for {package['id']} has invalid permission limitations")
    support = _selection_support(selection["support"])
    if support.startswith("blocked") or support.startswith("unsupported") or support in {"false", "unknown"}:
        raise WorkflowError(f"native selection for {package['id']} is blocked by support gate: {support}")
    selection = dict(selection)
    selection["composite_floor"] = floor
    return selection


def _tool_list(value: Any) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    if isinstance(value, str) and value:
        return [item for item in value.split(",") if item]
    return []


def build_command(
    runtime: str,
    selection: dict[str, Any],
    max_turns: int,
    *,
    output_last_message: Path | None = None,
) -> list[str]:
    model = selection["native_model"]
    role = (
        selection.get("role_id") or selection.get("native_role")
        or selection.get("role_name") or selection["task_id"].replace(".", "-")
    )
    if runtime == "claude":
        command = [
            "claude", "-p", "--output-format", "stream-json", "--verbose",
            "--model", model, "--agent", role, "--no-session-persistence",
            "--max-turns", str(max_turns), "--strict-mcp-config",
        ]
        tools = _tool_list(selection["native_tools"])
        command.extend(["--tools", ",".join(tools)])
        return command
    if runtime == "codex":
        permission = selection["native_permissions"]
        if isinstance(permission, dict):
            permission = permission.get("sandbox_mode")
        if permission not in {"read-only", "workspace-write"}:
            raise WorkflowError(f"unsupported Codex sandbox translation: {permission!r}")
        command = [
            "codex", "exec", "-m", model, "--sandbox", permission, "--json",
            "-c", "agents.enabled=false",
        ]
        effort = selection.get("native_effort")
        if isinstance(effort, str) and effort:
            # Codex accepts raw string overrides; embedded quotes are corrupted
            # by Windows npm .cmd wrappers before they reach its TOML parser.
            command.extend(["-c", f"model_reasoning_effort={effort}"])
        if output_last_message is not None:
            command.extend(["--output-last-message", str(output_last_message)])
        command.append("-")
        return command
    if runtime == "opencode":
        return ["opencode", "run", "--format", "json", "--model", model, "--agent", role, "-"]
    raise WorkflowError(f"unsupported runtime: {runtime}")


def _json_lines(stdout: str) -> tuple[list[dict[str, Any]], list[str]]:
    events, text = [], []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            text.append(stripped)
            continue
        if isinstance(value, dict):
            events.append(value)
        else:
            text.append(str(value))
    return events, text


def _walk(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _native_check_facts(runtime: str, events: list[dict[str, Any]]) -> list[dict[str, str]]:
    shell_names = {"Bash", "bash", "shell", "command_execution"}
    tool_uses: dict[str, dict[str, str]] = {}
    facts: list[dict[str, str]] = []

    def add_fact(event_ref: Any, tool: Any, command: Any) -> None:
        if not isinstance(tool, str) or tool not in shell_names or not isinstance(command, str) or not command.strip():
            return
        fact = {
            "event_ref": str(event_ref or digest({"runtime": runtime, "tool": tool, "command": command}))[:200],
            "tool": tool,
            "command": command.strip()[:2000],
            "status": "pass",
        }
        if fact not in facts:
            facts.append(fact)

    for event in events:
        for node in _walk(event):
            if not isinstance(node, dict):
                continue
            node_type = node.get("type")
            name = node.get("name") or node.get("tool")
            if node_type in {"tool_use", "toolCall"} and isinstance(name, str):
                tool_input = node.get("input") if isinstance(node.get("input"), dict) else node.get("arguments")
                command = tool_input.get("command") if isinstance(tool_input, dict) else None
                event_ref = node.get("id") or node.get("tool_use_id") or node.get("call_id")
                if event_ref and isinstance(command, str):
                    tool_uses[str(event_ref)] = {"tool": name, "command": command}
            if node_type == "command_execution":
                status = str(node.get("status", "")).lower()
                exit_code = node.get("exit_code", node.get("exitCode"))
                if status in {"completed", "success"} and exit_code in {None, 0}:
                    add_fact(node.get("id") or node.get("call_id"), "command_execution", node.get("command"))
            if node_type == "tool":
                state = node.get("state") if isinstance(node.get("state"), dict) else {}
                status = str(state.get("status", node.get("status", ""))).lower()
                metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
                exit_code = metadata.get("exit", metadata.get("exitCode", state.get("exitCode")))
                tool_input = state.get("input") if isinstance(state.get("input"), dict) else node.get("input")
                command = tool_input.get("command") if isinstance(tool_input, dict) else None
                if status in {"completed", "success"} and exit_code in {None, 0}:
                    add_fact(node.get("id") or node.get("callID"), name, command)

    for event in events:
        for node in _walk(event):
            if not isinstance(node, dict) or node.get("type") != "tool_result" or node.get("is_error") is True:
                continue
            event_ref = node.get("tool_use_id") or node.get("call_id")
            matched = tool_uses.get(str(event_ref))
            if matched:
                add_fact(event_ref, matched["tool"], matched["command"])
    return facts


def parse_native_result(
    runtime: str,
    stdout: str,
    returncode: int,
    *,
    final_output: str | None = None,
) -> dict[str, Any]:
    events, loose_text = _json_lines(stdout)
    actor_id = None
    output_parts: list[str] = list(loose_text)
    codex_messages: list[str] = []
    actual_tools: list[str] = []
    effective = {"status": "unknown", "model": None, "source": "native event not exposed"}
    tool_permissions = {"status": "unknown", "loaded_tools": [], "source": "native event not exposed"}
    completed = False
    failed = returncode != 0
    native_errors: list[str] = []

    for event in events:
        event_type = str(event.get("type", event.get("method", "")))
        if runtime == "claude":
            if event_type == "system" and event.get("subtype") == "init":
                actor_id = event.get("session_id") or actor_id
                if event.get("model"):
                    effective = {"status": "proven", "model": event["model"], "source": "system.init"}
                if isinstance(event.get("tools"), list) and all(isinstance(item, str) for item in event["tools"]):
                    tool_permissions = {
                        "status": "proven", "loaded_tools": event["tools"], "source": "system.init.tools",
                    }
            if event_type == "result":
                actor_id = event.get("session_id") or actor_id
                completed = event.get("subtype") == "success" and not event.get("is_error", False)
                failed = failed or not completed
                if isinstance(event.get("result"), str):
                    output_parts.append(event["result"])
                    if not completed:
                        native_errors.append(event["result"][:4000])
        elif runtime == "codex":
            if event_type == "thread.started":
                actor_id = event.get("thread_id") or event.get("threadId") or actor_id
            if event_type == "turn.completed":
                completed = True
            if event_type in {"turn.failed", "error"}:
                failed = True
            item = event.get("item") if isinstance(event.get("item"), dict) else event
            if item.get("type") in {"agent_message", "agentMessage"} and isinstance(item.get("text"), str):
                codex_messages.append(item["text"])
        else:
            actor_id = event.get("sessionID") or event.get("session_id") or actor_id
            if event_type in {"session.idle", "session.completed"}:
                completed = True
            if event_type in {"session.error", "error"}:
                failed = True
            part = event.get("part") if isinstance(event.get("part"), dict) else event
            if isinstance(part.get("text"), str):
                output_parts.append(part["text"])
            # OpenCode's modelID is configured request metadata; it has not been
            # proven to report the provider's effective execution model.
        for node in _walk(event):
            if not isinstance(node, dict):
                continue
            if event_type in {"turn.failed", "session.error", "error"}:
                for key in ("message", "error"):
                    value = node.get(key)
                    if isinstance(value, str) and value and value[:4000] not in native_errors:
                        native_errors.append(value[:4000])
            if node.get("type") in {"tool_use", "toolCall", "command_execution", "mcp_tool_call"}:
                name = (
                    "command_execution" if node.get("type") == "command_execution"
                    else node.get("name") or node.get("tool") or node.get("type")
                )
                if isinstance(name, str) and name not in actual_tools:
                    actual_tools.append(name)
    if runtime == "codex":
        # `codex exec --json` emits intermediate commentary and the final answer
        # with the same agent_message item type. Prefer its dedicated last-message
        # file; direct parser callers without that channel fall back to the final
        # event instead of concatenating progress into the deliverable.
        output_parts = [final_output] if final_output is not None else codex_messages[-1:]
    output = "\n".join(part.strip() for part in output_parts if isinstance(part, str) and part.strip()).strip()
    if runtime == "codex" and final_output is not None and completed and not output:
        failed = True
        native_errors.append("Codex completed without a final response in its last-message output")
    return {
        "actor_id": actor_id,
        "output": output,
        "events": events,
        "actual_tools": actual_tools,
        "check_events": _native_check_facts(runtime, events),
        "effective_model": effective,
        "tool_permissions": tool_permissions,
        "native_errors": native_errors,
        "native_completed": completed and not failed,
    }


class NativeProcessError(WorkflowError):
    def __init__(self, message: str, *, process_stopped: bool):
        super().__init__(message)
        self.process_stopped = process_stopped


class OwnedProcessTree:
    """Own a native process tree so writer release never relies on parent exit alone."""

    def __init__(self, process: subprocess.Popen[str]):
        self.process = process
        self.job = None
        if os.name == "nt":
            self.job = self._create_windows_job(process)

    @staticmethod
    def creation_kwargs() -> dict[str, Any]:
        if os.name == "nt":
            return {
                "creationflags": (
                    subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000004
                ),
            }
        return {"start_new_session": True}

    @staticmethod
    def _create_windows_job(process: subprocess.Popen[str]):
        import ctypes
        from ctypes import wintypes

        class BASIC_LIMITS(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class EXTENDED_LIMITS(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMITS),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise WorkflowError(f"cannot create Windows process job: {ctypes.get_last_error()}")
        limits = EXTENDED_LIMITS()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise WorkflowError(f"cannot configure Windows process job: {error}")
        if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise WorkflowError(f"cannot establish Windows process-tree ownership: {error}")
        return job

    def resume(self) -> None:
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
        ntdll.NtResumeProcess.restype = wintypes.LONG
        status = ntdll.NtResumeProcess(wintypes.HANDLE(self.process._handle))
        if status != 0:
            raise WorkflowError(f"cannot resume contained Windows process: NTSTATUS {status:#x}")

    def stop(self) -> bool:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel32.TerminateJobObject.restype = wintypes.BOOL
            if not self.job or not kernel32.TerminateJobObject(self.job, 1):
                return False
        else:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                return False
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                return False
        return self.confirm_stopped()

    def confirm_stopped(self, wait_seconds: float = 1.0) -> bool:
        deadline = time.monotonic() + wait_seconds
        while True:
            if self.process.poll() is None:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.02)
                continue
            if self._tree_is_empty():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def _tree_is_empty(self) -> bool:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class ACCOUNTING(ctypes.Structure):
                _fields_ = [
                    ("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                    ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                    ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                    ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD),
                ]

            info = ACCOUNTING()
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.QueryInformationJobObject.argtypes = [
                wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.QueryInformationJobObject.restype = wintypes.BOOL
            if not self.job or not kernel32.QueryInformationJobObject(
                self.job, 1, ctypes.byref(info), ctypes.sizeof(info), None
            ):
                return False
            return info.ActiveProcesses == 0
        try:
            os.killpg(self.process.pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False

    def close(self) -> None:
        if os.name == "nt" and self.job:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.CloseHandle(self.job)
            self.job = None


def _resolved_executable_command(command: list[str]) -> list[str]:
    executable = shutil.which(command[0])
    if not executable:
        raise WorkflowError(f"native runtime executable not found: {command[0]}")
    resolved = [executable, *command[1:]]
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        command_shell = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
        if not command_shell:
            raise WorkflowError("cmd.exe is required to launch the native runtime wrapper")
        return [command_shell, "/d", "/s", "/c", subprocess.list2cmdline(resolved)]
    return resolved


class NativeProcessRunner:
    def run(
        self,
        runtime: str,
        selection: dict[str, Any],
        prompt: str,
        *,
        cwd: Path,
        timeout_seconds: int,
        max_turns: int,
        on_start: Callable[[dict[str, Any]], None],
        cancel_requested: Callable[[], bool],
    ) -> dict[str, Any]:
        final_output_path = None
        if runtime == "codex":
            handle = tempfile.NamedTemporaryFile(prefix="workflow-codex-", suffix=".txt", delete=False)
            final_output_path = Path(handle.name)
            handle.close()
        try:
            command = build_command(
                runtime, selection, max_turns, output_last_message=final_output_path
            )
            command = _resolved_executable_command(command)
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=safe_child_env(),
                **OwnedProcessTree.creation_kwargs(),
            )
        except Exception:
            if final_output_path is not None:
                final_output_path.unlink(missing_ok=True)
            raise
        try:
            tree = OwnedProcessTree(process)
        except Exception:
            if "tree" in locals():
                tree.stop()
                tree.close()
            else:
                process.terminate()
                process.wait(timeout=2)
            if final_output_path is not None:
                final_output_path.unlink(missing_ok=True)
            raise
        try:
            on_start({"pid": process.pid, "command_digest": digest(command), "started_at": time.time()})
            tree.resume()
            assert process.stdin is not None
            process.stdin.write(prompt)
            process.stdin.close()
            process.stdin = None
            deadline = time.monotonic() + timeout_seconds
            timed_out = cancelled = False
            stdout = stderr = ""
            forced_stop = False
            while True:
                if cancel_requested() and process.poll() is None:
                    cancelled = True
                    forced_stop = tree.stop()
                remaining = deadline - time.monotonic()
                if remaining <= 0 and process.poll() is None:
                    timed_out = True
                    forced_stop = tree.stop()
                try:
                    stdout, stderr = process.communicate(timeout=max(0.05, min(0.25, max(remaining, 0.05))))
                    break
                except subprocess.TimeoutExpired:
                    if (cancelled or timed_out) and process.poll() is None:
                        forced_stop = tree.stop()
                    continue
            stopped = tree.confirm_stopped()
            if not stopped and not (cancelled or timed_out):
                stopped = tree.stop()
            final_output = None
            if final_output_path is not None:
                try:
                    final_output = final_output_path.read_text(encoding="utf-8")
                except OSError as exc:
                    final_output = ""
                    stderr = f"{stderr}\nworkflow: could not read Codex final response: {exc}"[-8000:]
            parsed = parse_native_result(
                runtime, stdout, process.returncode or 0, final_output=final_output
            )
            parsed.update(
                {
                    "returncode": process.returncode,
                    "stderr": stderr[-8000:],
                    "timed_out": timed_out,
                    "cancelled": cancelled,
                    "process_stopped": stopped or forced_stop,
                    "command_digest": digest(command),
                }
            )
            if timed_out or cancelled:
                parsed["native_completed"] = False
            return parsed
        except Exception as exc:
            stopped = tree.stop()
            raise NativeProcessError(
                f"native process communication failed: {exc}", process_stopped=stopped
            ) from exc
        finally:
            tree.close()
            if final_output_path is not None:
                final_output_path.unlink(missing_ok=True)


def _extract_verdict(text: str, *, require_checks: bool = False) -> dict[str, Any] | None:
    candidates = [text.strip()]
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        candidates.insert(0, match.group(1))
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        candidates.append(match.group(1))
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("pass"), bool):
            issues = value.get("issues", [])
            if isinstance(issues, list) and all(isinstance(item, str) for item in issues):
                checks = value.get("checks", [])
                if require_checks and (
                    not isinstance(checks, list) or not checks
                    or any(
                        not isinstance(item, dict)
                        or not isinstance(item.get("name"), str) or not item["name"].strip()
                        or item.get("status") != "pass"
                        or not isinstance(item.get("command"), str) or not item["command"].strip()
                        for item in checks
                    )
                ):
                    continue
                return {"pass": value["pass"], "issues": issues, "checks": checks}
    return None


_POWERSHELL_COMMAND_WRAPPER = re.compile(
    r"^\"[A-Za-z]:\\[^\"\r\n]*\\(?:pwsh|powershell)\.exe\"\s+-NoProfile\s+-Command\s+'([^'\r\n]+)'$",
    re.IGNORECASE,
)


def _command_claim_matches_event(claimed: str, event: dict[str, Any]) -> bool:
    tool = event.get("tool")
    if event.get("status") != "pass" or tool not in {"command_execution", "Bash", "bash", "shell"}:
        return False
    observed = event.get("command")
    if not isinstance(observed, str):
        return False
    claimed = claimed.strip()
    observed = observed.strip()
    if claimed == observed:
        return True
    if tool != "command_execution":
        return False
    wrapped = _POWERSHELL_COMMAND_WRAPPER.fullmatch(observed)
    return wrapped is not None and claimed == wrapped.group(1)


def _bounded_failure_verdict(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    bounded = {"pass": value.get("pass") is True}
    bounded["issues"] = [
        issue[:2000] for issue in value.get("issues", [])[:32] if isinstance(issue, str)
    ] if isinstance(value.get("issues"), list) else []
    checks = []
    for check in value.get("checks", [])[:32] if isinstance(value.get("checks"), list) else []:
        if not isinstance(check, dict):
            continue
        checks.append({
            key: str(check[key])[:2000]
            for key in ("name", "status", "command") if key in check
        })
    bounded["checks"] = checks
    return bounded


def _artifact_hash_packet(root: Path, paths: list[str]) -> list[dict[str, Any]]:
    packet = []
    for relative in sorted(paths):
        path = canonical_artifact(root, relative, allow_missing=False)
        hasher = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
                size += len(chunk)
        packet.append({"path": relative, "bytes": size, "sha256": hasher.hexdigest()})
    return packet


def _bounded_verifier_receipt(receipt: Any) -> dict[str, Any] | None:
    if not isinstance(receipt, dict):
        return None
    bounded = {
        key: receipt.get(key)
        for key in (
            "package_id", "task_id", "actor_id", "provenance", "native_completed",
            "process_stopped", "reviewed_revision", "native_event_digest", "command_digest",
        )
    }
    bounded["verdict"] = _bounded_failure_verdict(receipt.get("verdict"))
    bounded["check_events"] = [
        {
            key: str(event[key])[:2000]
            for key in ("event_ref", "tool", "command", "status") if key in event
        }
        for event in receipt.get("check_events", [])[:32] if isinstance(event, dict)
    ] if isinstance(receipt.get("check_events"), list) else []
    return bounded


class WorkflowController:
    def __init__(
        self,
        root: Path = ROOT,
        runs_dir: Path | None = None,
        *,
        runner: Any | None = None,
        resolver: Callable[..., dict[str, Any]] | None = None,
    ):
        self.root = root.resolve()
        self.runs_dir = (runs_dir or self.root / ".tmp" / "workflows").resolve()
        try:
            self.runs_dir.relative_to(self.root)
        except ValueError as exc:
            raise WorkflowError("workflow state directory must stay inside the repository") from exc
        self.runner = runner or NativeProcessRunner()
        self.resolver = resolver

    def _policy(self) -> tuple[dict[str, Any], str]:
        policy = rp.load_policy(self.root)
        source_hash = rp.policy_digest(policy)
        manifest_path = self.root / rp.MANIFEST
        manifest = read_json(manifest_path)
        if manifest.get("source_hash") != source_hash or manifest.get("policy") != policy:
            raise WorkflowError("delegation policy source/hash drift; regenerate before workflow execution")
        return policy, source_hash

    def _state_path(self, run_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{5,80}", run_id):
            raise WorkflowError(f"invalid run id: {run_id!r}")
        path = (self.runs_dir / run_id / "state.json").resolve()
        try:
            path.relative_to(self.runs_dir)
        except ValueError as exc:
            raise WorkflowError("run path escapes workflow directory") from exc
        return path

    def _run_lock_path(self, run_id: str) -> Path:
        return self._state_path(run_id).parent / "controller.lock"

    def _cancel_path(self, run_id: str) -> Path:
        return self._state_path(run_id).parent / "cancel.requested"

    def plan(self, raw: dict[str, Any]) -> dict[str, Any]:
        policy, source_hash = self._policy()
        spec = normalize_spec(raw, self.root, policy)
        required_depths = [spec["planning_depth"]]
        for package in spec["work_packages"]:
            flags = {key: value for key, value in package["floor_flags"].items() if value}
            required_depths.append(
                rp.composite_floor(policy, package["task_id"], **flags)["planning_floor"]
            )
        spec["planning_depth"] = max(required_depths, key=rp.PLANNING_RANK.__getitem__)
        packages = seed_managed_packages(spec)
        selections = {
            package["id"]: resolve_native(self.root, policy, package, spec["runtime"], self.resolver)
            for package in packages
        }
        return {
            "policy_hash": source_hash, "spec": spec, "packages": packages,
            "selections": selections,
        }

    def start(self, raw: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
        planned = self.plan(raw)
        run_id = run_id or f"wf-{uuid.uuid4().hex[:16]}"
        state_path = self._state_path(run_id)
        all_artifacts = sorted({path for package in planned["packages"] for path in package["artifact_paths"]})
        state = {
            "schema_version": 1,
            "run_id": run_id,
            "repository": self.root.as_posix(),
            "runtime": planned["spec"]["runtime"],
            "mode": planned["spec"]["mode"],
            "policy_hash": planned["policy_hash"],
            "state": "planned",
            "spec": planned["spec"],
            "packages": planned["packages"],
            "selections": planned["selections"],
            "package_states": {package["id"]: "pending" for package in planned["packages"]},
            "receipts": {},
            "failures": {},
            "artifact_paths": all_artifacts,
            "artifact_revision": artifact_revision(self.root, all_artifacts),
            "active_process": None,
            "cancel_requested": False,
            "grade": {"contract": "pass", "managed_gate": "pending", "evidence_audit": "pending"},
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        atomic_create_json(state_path, state)
        return state

    def load(self, run_id: str, *, verify_policy: bool = True) -> dict[str, Any]:
        state = read_json(self._state_path(run_id))
        if state.get("run_id") != run_id or state.get("repository") != self.root.as_posix():
            raise WorkflowError("workflow state is bound to a different run or repository")
        if verify_policy:
            _, source_hash = self._policy()
            if state.get("policy_hash") != source_hash:
                raise WorkflowError("workflow policy hash is stale; start a new ratified run")
        for package_id, receipt in state.get("receipts", {}).items():
            if not isinstance(receipt, dict) or receipt.get("run_id") != run_id or receipt.get("package_id") != package_id:
                raise WorkflowError(f"mixed or foreign receipt detected for {package_id}")
            if receipt.get("provenance") != "controller-owned-native-process":
                raise WorkflowError(f"untrusted imported receipt detected for {package_id}")
        return state

    def _save(self, state: dict[str, Any]) -> None:
        if self._cancel_path(state["run_id"]).exists():
            state["cancel_requested"] = True
        state["updated_at"] = time.time()
        atomic_write_json(self._state_path(state["run_id"]), state)

    def _cancel_requested(self, run_id: str) -> bool:
        return self._cancel_path(run_id).exists()

    def _on_process_start(self, state: dict[str, Any], package: dict[str, Any], process: dict[str, Any]) -> None:
        state["active_process"] = {**process, "package_id": package["id"], "owned": True}
        state["package_states"][package["id"]] = "running"
        self._save(state)

    def _record_native_failure(
        self, state: dict[str, Any], package: dict[str, Any], result: dict[str, Any], reason: str,
        *, semantic_verdict: dict[str, Any] | None = None,
    ) -> None:
        events = result.get("events", [])
        check_events = []
        for event in result.get("check_events", [])[:32]:
            if not isinstance(event, dict):
                continue
            check_events.append({
                key: str(event[key])[:2000]
                for key in ("event_ref", "tool", "command", "status") if key in event
            })
        state.setdefault("failures", {})[package["id"]] = {
            "schema_version": 1,
            "run_id": state["run_id"],
            "package_id": package["id"],
            "provenance": "controller-owned-native-process",
            "reason": reason,
            "actor_id": result.get("actor_id"),
            "returncode": result.get("returncode"),
            "stderr": str(result.get("stderr", ""))[-8000:],
            "native_errors": result.get("native_errors", []),
            "timed_out": bool(result.get("timed_out")),
            "cancelled": bool(result.get("cancelled")),
            "process_stopped": result.get("process_stopped") is True,
            "native_completed": result.get("native_completed") is True,
            "effective_model": result.get("effective_model", {"status": "unknown"}),
            "tool_permissions": result.get("tool_permissions", {"status": "unknown"}),
            "actual_tools": result.get("actual_tools", []),
            "check_events": check_events,
            "semantic_verdict": _bounded_failure_verdict(semantic_verdict),
            "native_event_types": [
                str(event.get("type", event.get("method", "")))
                for event in events if isinstance(event, dict)
            ],
            "native_event_digest": digest(events),
            "command_digest": result.get("command_digest"),
            "recorded_at": time.time(),
        }

    @staticmethod
    def _managed_graph(state: dict[str, Any]) -> list[dict[str, Any]]:
        graph = []
        for item in state["packages"]:
            managed_kind = item["managed_kind"]
            selection = state["selections"][item["id"]]
            node = {
                "id": item["id"],
                "origin": (
                    "user-work-package" if managed_kind == "worker"
                    else "controller-inserted-mandatory-stage"
                ),
                "managed_kind": managed_kind,
                "task_id": item["task_id"],
                "artifact_paths": item["artifact_paths"],
                "dependencies": list(item["dependencies"]),
                "selection": {
                    key: selection[key]
                    for key in (
                        "role_id", "profile", "tool_profile", "model_family", "native_model",
                        "native_tools", "native_permissions", "output_check",
                    )
                },
            }
            if managed_kind == "worker":
                node["prompt"] = item["prompt"]
            else:
                node["prompt_source"] = "controller-generated-at-execution"
            if item.get("review_of"):
                node["review_of"] = list(item["review_of"])
            graph.append(node)
        return graph

    def _prompt(
        self, state: dict[str, Any], package: dict[str, Any], selection: dict[str, Any]
    ) -> tuple[str, str | None]:
        spec = state["spec"]
        kind = package["managed_kind"]
        revision = artifact_revision(self.root, package["artifact_paths"])
        preamble = (
            f"DELEGATED ROLE: {selection['role_id']}\nTASK ID: {selection['task_id']}\n"
            f"PROFILE: {selection['profile']}\nTOOL PROFILE: {selection['tool_profile']}\n"
            f"NATIVE TOOLS: {json.dumps(selection['native_tools'])}\n"
            f"NATIVE PERMISSIONS: {json.dumps(selection['native_permissions'], sort_keys=True)}\n"
            f"OUTPUT CHECK: {selection.get('output_check', '')}\n"
            f"ESCALATION: {selection.get('escalation', '')}\n"
            "You are a bounded child executor. Do not spawn, delegate, message, or invoke the Agent or Workflow tools. "
            "Follow the assigned scope and return the required result directly.\n"
        )
        if kind == "planner":
            graph = self._managed_graph(state)
            return (
                preamble + "You are the delegated work-package planner. Review this already bounded graph. "
                "The graph distinguishes user work packages from mandatory stages inserted by the controller; "
                "do not require the user to supply those internal stages. Identify dependency, scope, acceptance, "
                "routing, or writer conflicts. Do not edit artifacts. "
                'Return only JSON {"pass": boolean, "issues": [string]}.\n'
                f"REQUIREMENTS:\n{spec['requirements']}\nACCEPTANCE:\n{json.dumps(spec['acceptance_criteria'])}\n"
                f"SOURCE EVIDENCE:\n{json.dumps(spec['source_evidence'])}\n"
                f"PACKAGES:\n{json.dumps(graph, sort_keys=True)}",
                None,
            )
        if kind == "analyst":
            graph = self._managed_graph(state)
            return (
                preamble
                + "Independently analyze the requirements, source evidence, acceptance criteria, and bounded work "
                "graph. The graph distinguishes user work packages from mandatory stages inserted by the controller; "
                "do not require the user to supply those internal stages. Identify conflicts, assumptions, failure "
                "modes, and constraints before implementation. "
                'Return only JSON {"pass": boolean, "issues": [string]}.\n'
                f"REQUIREMENTS:\n{spec['requirements']}\nACCEPTANCE:\n{json.dumps(spec['acceptance_criteria'])}\n"
                f"SOURCE EVIDENCE:\n{json.dumps(spec['source_evidence'])}\nPACKAGES:\n{json.dumps(graph, sort_keys=True)}",
                None,
            )
        if kind in {"reviewer", "verifier"}:
            artifacts = read_artifacts_for_review(self.root, package["artifact_paths"])
            artifact_hashes = _artifact_hash_packet(self.root, package["artifact_paths"])
            instruction = (
                "Independently review the current artifacts against the original requirements, acceptance criteria, "
                "and source evidence. You have not received builder reasoning or justifications. Return only JSON "
                '{"pass": boolean, "issues": [string]}. Do not edit production artifacts.'
                if kind == "reviewer" else
                "Run deterministic checks appropriate to the current artifacts and criteria using the assigned "
                "native test or shell tool. Return only JSON "
                '{"pass": boolean, "issues": [string], "checks": '
                '[{"name": string, "status": "pass", "command": string}]}. '
                "Each command must exactly match a successful native command you ran. "
                "Do not edit production artifacts."
            )
            verifier_proof = ""
            if kind == "reviewer":
                verifier_receipt = _bounded_verifier_receipt(state["receipts"].get("_managed-verify"))
                verifier_proof = (
                    "CONTROLLER VERIFIER RECEIPT: not required for T2\n"
                    if spec["planning_depth"] != "T3" else
                    f"CONTROLLER VERIFIER RECEIPT:\n{json.dumps(verifier_receipt, sort_keys=True)}\n"
                )
            return (
                f"{preamble}{instruction}\nREQUIREMENTS:\n{spec['requirements']}\n"
                f"ACCEPTANCE:\n{json.dumps(spec['acceptance_criteria'])}\n"
                f"SOURCE EVIDENCE:\n{json.dumps(spec['source_evidence'])}\n"
                "ARTIFACT SET REVISION ALGORITHM: SHA-256 over each sorted UTF-8 relative path, NUL, "
                "then b'file\\0' plus raw file bytes (or b'missing\\0'). This aggregate is not a raw file SHA-256.\n"
                f"ARTIFACT SET REVISION: {revision}\n"
                f"PER-ARTIFACT SHA-256:\n{json.dumps(artifact_hashes, sort_keys=True)}\n"
                f"{verifier_proof}{artifacts}",
                revision,
            )
        return (
            preamble + "Execute only this bounded work package. Use the assigned native role, tools, and exact artifact files. "
            "Do not make product, architecture, authorization, or scope decisions.\n"
            f"REQUIREMENTS:\n{spec['requirements']}\nACCEPTANCE:\n{json.dumps(spec['acceptance_criteria'])}\n"
            f"PACKAGE:\n{package['prompt']}\nARTIFACT FILES:\n{json.dumps(package['artifact_paths'])}\n"
            + (
                f"INDEPENDENT ANALYSIS:\n{state['receipts']['_managed-analysis']['output']}\n"
                if "_managed-analysis" in state["receipts"] else ""
            )
            + (
                "Return the complete final artifact in your response; the controller will write it atomically."
                if package.get("result_artifact") else ""
            ),
            None,
        )

    def _is_writer(self, policy: dict[str, Any], package: dict[str, Any]) -> bool:
        return (
            task_writes_canonical(policy, package["task_id"]) or bool(package.get("result_artifact"))
        ) and package["managed_kind"] == "worker"

    def _run_package(self, state: dict[str, Any], policy: dict[str, Any], package: dict[str, Any]) -> None:
        selection = state["selections"][package["id"]]
        prompt, reviewed_revision = self._prompt(state, package, selection)
        writer = self._is_writer(policy, package)
        lock = ExclusiveLock(
            self.runs_dir / ".canonical-writer.lock",
            {"run_id": state["run_id"], "package_id": package["id"]},
        ) if writer else None
        before = artifact_revision(self.root, package["artifact_paths"])
        if lock:
            lock.acquire()
        result: dict[str, Any] | None = None
        process_started = False

        def mark_started(process: dict[str, Any]) -> None:
            nonlocal process_started
            process_started = True
            self._on_process_start(state, package, process)

        try:
            result = self.runner.run(
                state["runtime"], selection, prompt, cwd=self.root,
                timeout_seconds=package["timeout_seconds"], max_turns=package["max_turns"],
                on_start=mark_started,
                cancel_requested=lambda: self._cancel_requested(state["run_id"]),
            )
        except Exception as exc:
            process_stopped = getattr(exc, "process_stopped", False)
            if lock and (not process_started or process_stopped):
                lock.release(process_stopped=True)
            if process_started and process_stopped:
                state["active_process"] = None
                state["package_states"][package["id"]] = "failed"
            state["state"] = "cancel-pending" if process_started and not process_stopped else "blocked"
            self._save(state)
            raise
        if result is None:
            state["state"] = "cancel-pending"
            self._save(state)
            raise WorkflowError(f"native runner returned no result for {package['id']}")
        if not result.get("process_stopped"):
            state["state"] = "cancel-pending"
            self._save(state)
            raise WorkflowError(f"owned process for {package['id']} is not confirmed stopped; writer lock retained")
        try:
            active_process = dict(state.get("active_process") or {})
            state["active_process"] = None
            self._save(state)
            if result.get("cancelled"):
                self._record_native_failure(state, package, result, "cancelled")
                state["package_states"][package["id"]] = "cancelled"
                state["state"] = "cancelled"
                self._save(state)
                raise WorkflowError(f"package {package['id']} was cancelled")
            if result.get("timed_out"):
                self._record_native_failure(state, package, result, "timed out")
                state["package_states"][package["id"]] = "failed"
                state["state"] = "blocked"
                self._save(state)
                raise WorkflowError(f"package {package['id']} timed out and its process was stopped")
            if not result.get("native_completed") or result.get("returncode") != 0:
                self._record_native_failure(state, package, result, "failed native completion")
                state["package_states"][package["id"]] = "failed"
                state["state"] = "blocked"
                self._save(state)
                raise WorkflowError(f"package {package['id']} failed native completion")
            failure = None
            if not isinstance(result.get("actor_id"), str) or not result["actor_id"]:
                failure = f"package {package['id']} has no native child actor identity"
            elif not isinstance(result.get("output"), str) or not result["output"].strip():
                failure = f"package {package['id']} returned empty output"
            if failure:
                state["package_states"][package["id"]] = "failed"
                state["state"] = "blocked"
                self._save(state)
                raise WorkflowError(failure)
            effective_model = _normalize_model_evidence(selection, result.get("effective_model", {}))
            if effective_model.get("status") == "proven" and not _effective_model_matches(selection, effective_model):
                state["package_states"][package["id"]] = "failed"
                state["state"] = "blocked"
                self._save(state)
                raise WorkflowError(f"package {package['id']} ran with an unexpected effective model")
            tool_permissions = result.get(
                "tool_permissions",
                {"status": "unknown", "loaded_tools": [], "source": "native event not exposed"},
            )
            if tool_permissions.get("status") == "proven":
                loaded = tool_permissions.get("loaded_tools")
                if not isinstance(loaded, list) or set(loaded) != set(selection["native_tools"]):
                    state["package_states"][package["id"]] = "failed"
                    state["state"] = "blocked"
                    self._save(state)
                    raise WorkflowError(f"package {package['id']} loaded unexpected native tools")
            if package.get("result_artifact"):
                result_path = canonical_artifact(self.root, package["result_artifact"])
                validate_text_artifact_content(result_path, result["output"])
                atomic_write_text(
                    result_path,
                    result["output"],
                )
            after = artifact_revision(self.root, package["artifact_paths"])
            if writer:
                for relative in package["artifact_paths"]:
                    canonical_artifact(self.root, relative, allow_missing=False)
            verdict = (
                _extract_verdict(result["output"], require_checks=package["managed_kind"] == "verifier")
                if package["managed_kind"] in {"planner", "analyst", "reviewer", "verifier"}
                else None
            )
            if package["managed_kind"] in {"planner", "analyst", "reviewer", "verifier"} and verdict is None:
                state["package_states"][package["id"]] = "failed"
                state["state"] = "blocked"
                self._save(state)
                raise WorkflowError(f"package {package['id']} did not return the required structured verdict")
            check_events = result.get("check_events", [])
            if package["managed_kind"] == "verifier":
                unmatched = [
                    check for check in verdict["checks"]
                    if not any(
                        isinstance(event, dict)
                        and _command_claim_matches_event(check["command"], event)
                        for event in check_events
                    )
                ]
                if unmatched:
                    self._record_native_failure(
                        state, package, result,
                        "deterministic verifier checks lack matching successful native command evidence",
                        semantic_verdict=verdict,
                    )
                    state["package_states"][package["id"]] = "failed"
                    state["state"] = "blocked"
                    self._save(state)
                    raise WorkflowError("deterministic verifier checks lack matching successful native command evidence")
            receipt = {
                "schema_version": 1,
                "run_id": state["run_id"],
                "package_id": package["id"],
                "task_id": package["task_id"],
                "managed_kind": package["managed_kind"],
                "provenance": "controller-owned-native-process",
                "actor_id": result["actor_id"],
                "requested": {
                    "profile": selection["profile"], "model_family": selection["model_family"],
                    "native_model": selection["native_model"], "native_permissions": selection["native_permissions"],
                    "native_tools": selection["native_tools"],
                },
                "requested_model_evidence": selection["effective_model_evidence"],
                "role_enforcement": (
                    {"status": "unknown", "source": "Codex delegated role is prompt-bound"}
                    if state["runtime"] == "codex" else
                    {"status": "configured", "source": "native role selector"}
                ),
                "effective_model": effective_model,
                "actual_tools": result.get("actual_tools", []),
                "check_events": check_events if package["managed_kind"] == "verifier" else [],
                "native_event_digest": digest(result.get("events", [])),
                "native_event_types": [
                    str(event.get("type", event.get("method", "")))
                    for event in result.get("events", []) if isinstance(event, dict)
                ],
                "tool_permissions": tool_permissions,
                "permission_limitations": selection["permission_limitations"],
                "native_completed": True,
                "process_stopped": True,
                "command_digest": result.get("command_digest"),
                "started_at": active_process.get("started_at"),
                "completed_at": time.time(),
                "output": result["output"],
                "output_digest": digest(result["output"]),
                "artifact_revision_before": before,
                "artifact_revision_after": after,
                "reviewed_revision": reviewed_revision,
                "verdict": verdict,
            }
            state["receipts"][package["id"]] = receipt
            state.get("failures", {}).pop(package["id"], None)
            state["package_states"][package["id"]] = "completed"
            state["artifact_revision"] = artifact_revision(self.root, state["artifact_paths"])
            self._save(state)
            if package["managed_kind"] in {"planner", "analyst"} and not verdict["pass"]:
                state["state"] = "blocked"
                self._save(state)
                raise WorkflowError(f"delegated {package['managed_kind']} found unresolved package defects")
        finally:
            if lock:
                lock.release(process_stopped=True)

    def _finalize(self, state: dict[str, Any]) -> None:
        packages = {package["id"]: package for package in state["packages"]}
        required = {"_managed-plan", "_managed-review"}
        if state["spec"]["planning_depth"] == "T3":
            required.update({"_managed-analysis", "_managed-verify"})
        if not required <= set(state["receipts"]):
            raise WorkflowError("mandatory planner, analyst, verifier, or reviewer receipt is missing")
        if any(value != "completed" for value in state["package_states"].values()):
            raise WorkflowError("workflow contains unfinished or failed packages")
        reviewer = state["receipts"]["_managed-review"]
        worker_actors = {
            receipt["actor_id"] for package_id, receipt in state["receipts"].items()
            if packages[package_id]["managed_kind"] == "worker"
        }
        if reviewer["actor_id"] in worker_actors:
            raise WorkflowError("reviewer actor is not independent from the builder")
        current = artifact_revision(self.root, state["artifact_paths"])
        self._assert_writer_receipts_current(state)
        if reviewer.get("reviewed_revision") != current:
            reviewer["invalidated"] = "artifact changed after review"
            state["state"] = "verifying"
            self._save(state)
            raise WorkflowError("artifact changed after review; verification and review are stale")
        verifier = state["receipts"].get("_managed-verify")
        analyst = state["receipts"].get("_managed-analysis")
        if analyst:
            other_actors = worker_actors | {
                reviewer["actor_id"], state["receipts"]["_managed-plan"]["actor_id"],
            }
            if verifier:
                other_actors.add(verifier["actor_id"])
            if analyst["actor_id"] in other_actors:
                raise WorkflowError("T3 analyst actor is not separate from workers, verifier, and reviewer")
        if verifier:
            if verifier["actor_id"] in worker_actors or verifier["actor_id"] == reviewer["actor_id"]:
                raise WorkflowError("T3 verifier actor is not separate from builders and reviewer")
            if verifier.get("reviewed_revision") != current:
                state["state"] = "verifying"
                self._save(state)
                raise WorkflowError("artifact changed after deterministic verification; verifier receipt is stale")
        for package_id in ("_managed-plan", "_managed-analysis", "_managed-review", "_managed-verify"):
            if package_id in state["receipts"] and not state["receipts"][package_id].get("verdict", {}).get("pass"):
                state["state"] = "blocked"
                self._save(state)
                raise WorkflowError(f"{package_id} reported unresolved issues")
        evidence_unknown = []
        enforcement_limited = []
        for package_id, receipt in state["receipts"].items():
            if receipt.get("effective_model", {}).get("status") != "proven":
                evidence_unknown.append(f"{package_id}:effective-model")
            permission_status = receipt.get("tool_permissions", {}).get("status")
            if permission_status != "proven":
                evidence_unknown.append(f"{package_id}:tool-permissions")
            if state["runtime"] == "codex" and receipt.get("role_enforcement", {}).get("status") != "proven":
                evidence_unknown.append(f"{package_id}:role-enforcement")
            if receipt.get("permission_limitations"):
                enforcement_limited.append(f"{package_id}:tool-permissions")
        if state["mode"] == "strict" and (evidence_unknown or enforcement_limited):
            state["state"] = "blocked"
            state["grade"] = {
                "contract": "pass", "managed_gate": "pass",
                "evidence_audit": "unknown" if evidence_unknown else "pass",
                "enforcement_grade": "reduced" if enforcement_limited else "full",
            }
            self._save(state)
            raise WorkflowError(
                "strict evidence gate failed: " + ", ".join([*evidence_unknown, *enforcement_limited])
            )
        state["artifact_revision"] = current
        state["state"] = "completed"
        state["grade"] = {
            "contract": "pass",
            "managed_gate": "pass",
            "evidence_audit": "pass" if not evidence_unknown else "unknown",
            "enforcement_grade": "full" if not enforcement_limited else "reduced",
            "unknown": evidence_unknown,
            "limitations": enforcement_limited,
        }
        self._save(state)

    def _assert_writer_receipts_current(self, state: dict[str, Any]) -> None:
        for package in state["packages"]:
            if package["managed_kind"] != "worker" or not package["artifact_paths"]:
                continue
            receipt = state["receipts"].get(package["id"])
            if not receipt:
                continue
            current = artifact_revision(self.root, package["artifact_paths"])
            if receipt.get("artifact_revision_after") != current:
                raise WorkflowError(
                    f"worker artifact changed after {package['id']}; its receipt and downstream review are stale"
                )

    def _invalidate_changed_workers(self, state: dict[str, Any]) -> bool:
        changed = False
        for package in state["packages"]:
            if package["managed_kind"] != "worker" or not package["artifact_paths"]:
                continue
            receipt = state["receipts"].get(package["id"])
            if receipt and receipt.get("artifact_revision_after") != artifact_revision(
                self.root, package["artifact_paths"]
            ):
                changed = True
                break
        if not changed:
            return False
        for package in state["packages"]:
            if package["managed_kind"] in {"worker", "verifier", "reviewer"}:
                state["receipts"].pop(package["id"], None)
                state["package_states"][package["id"]] = "pending"
        state["state"] = "executing"
        self._save(state)
        return True

    def _verify_preflight_selections(self, state: dict[str, Any], policy: dict[str, Any]) -> None:
        expected = state.get("selections")
        if not isinstance(expected, dict):
            raise WorkflowError("workflow state has no preflight native selections")
        for package in state["packages"]:
            current = resolve_native(
                self.root, policy, package, state["runtime"], self.resolver
            )
            if digest(current) != digest(expected.get(package["id"])):
                raise WorkflowError(
                    f"native selection changed after plan for {package['id']}; start a new ratified run"
                )

    def run(self, run_id: str) -> dict[str, Any]:
        controller_lock = ExclusiveLock(
            self._run_lock_path(run_id), {"run_id": run_id, "owner": "workflow-controller"}
        )
        controller_lock.acquire()
        retain_lock = False
        try:
            state = self.load(run_id)
            if state["state"] == "cancelled":
                return state
            if state.get("active_process"):
                retain_lock = True
                raise WorkflowError("run has an active or unconfirmed process; use status/cancel and wait for controller ownership")
            if self._cancel_requested(run_id):
                state["state"] = "cancelled"
                self._save(state)
                return state
            policy, _ = self._policy()
            self._verify_preflight_selections(state, policy)
            current = artifact_revision(self.root, state["artifact_paths"])
            review = state["receipts"].get("_managed-review")
            workers_changed = self._invalidate_changed_workers(state)
            if not workers_changed and review and review.get("reviewed_revision") != current:
                for package_id in ("_managed-verify", "_managed-review"):
                    state["receipts"].pop(package_id, None)
                    if package_id in state["package_states"]:
                        state["package_states"][package_id] = "pending"
                state["state"] = "verifying"
                self._save(state)
            elif state["state"] == "completed":
                return state
            state["state"] = "executing"
            self._save(state)
            for package in topological(state["packages"]):
                if state["package_states"][package["id"]] == "completed":
                    continue
                dependencies = package["dependencies"]
                if any(state["package_states"].get(item) != "completed" for item in dependencies):
                    raise WorkflowError(f"dependencies for {package['id']} are incomplete")
                if package["managed_kind"] == "verifier":
                    self._assert_writer_receipts_current(state)
                    state["state"] = "verifying"
                elif package["managed_kind"] == "reviewer":
                    self._assert_writer_receipts_current(state)
                    state["state"] = "reviewing"
                self._save(state)
                self._run_package(state, policy, package)
                if package["managed_kind"] == "reviewer":
                    state["state"] = "reviewed"
                    self._save(state)
                if state.get("state") == "cancel-pending" or state.get("active_process"):
                    retain_lock = True
            if self._cancel_requested(run_id):
                state["state"] = "cancelled"
                self._save(state)
                return state
            state["state"] = "ready"
            self._save(state)
            self._finalize(state)
            return state
        finally:
            try:
                latest = read_json(self._state_path(run_id))
                retain_lock = retain_lock or bool(latest.get("active_process"))
            except WorkflowError:
                retain_lock = True
            if not retain_lock:
                controller_lock.release(process_stopped=True)

    def cancel(self, run_id: str) -> dict[str, Any]:
        state = self.load(run_id)
        if state["state"] in {"completed", "cancelled"}:
            return state
        atomic_write_json(self._cancel_path(run_id), {"run_id": run_id, "requested_at": time.time()})
        cancel_lock = ExclusiveLock(
            self._run_lock_path(run_id), {"run_id": run_id, "owner": "workflow-cancel"}
        )
        try:
            cancel_lock.acquire()
        except WorkflowError:
            state["cancel_requested"] = True
            state["state"] = "cancel-pending"
            return state
        try:
            state = self.load(run_id)
            state["cancel_requested"] = True
            state["state"] = "cancel-pending" if state.get("active_process") else "cancelled"
            self._save(state)
            return state
        finally:
            cancel_lock.release(process_stopped=True)

    def status(self, run_id: str) -> dict[str, Any]:
        state = self.load(run_id, verify_policy=False)
        if self._cancel_requested(run_id) and state["state"] not in {"completed", "cancelled"}:
            state["cancel_requested"] = True
            state["state"] = "cancel-pending"
        return state


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": state["run_id"], "state": state["state"], "runtime": state["runtime"],
        "mode": state["mode"], "grade": state["grade"], "package_states": state["package_states"],
        "active_process": state["active_process"], "artifact_revision": state["artifact_revision"],
    }


def read_spec_file(root: Path, path: Path) -> dict[str, Any]:
    root = root.resolve()
    candidate = path if path.is_absolute() else root / path
    try:
        relative = candidate.resolve().relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise WorkflowError("workflow spec must stay inside the repository") from exc
    protected = canonical_artifact(root, relative, allow_missing=False)
    if protected.suffix.lower() != ".json":
        raise WorkflowError("workflow spec must be a JSON file")
    return read_json(protected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Managed T2/T3 workflow controller.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--runs-dir", type=Path)
    parser.add_argument(
        "--opt-in", action="store_true",
        help="run even though structure.json delegation.mandatory is false",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "start"):
        child = sub.add_parser(name)
        child.add_argument("spec", type=Path)
        if name == "start":
            child.add_argument("--run-id")
    for name in ("run", "resume", "status", "cancel"):
        child = sub.add_parser(name)
        child.add_argument("run_id")
    args = parser.parse_args(argv)
    refusal = delegation_gate(args.root, args.opt_in)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    controller = WorkflowController(args.root, args.runs_dir)
    try:
        if args.command in {"plan", "start"}:
            raw = read_spec_file(args.root, args.spec)
            if args.command == "plan":
                print(json.dumps(controller.plan(raw), indent=2, sort_keys=True))
                return 0
            state = controller.start(raw, args.run_id)
        elif args.command in {"run", "resume"}:
            state = controller.run(args.run_id)
        elif args.command == "cancel":
            state = controller.cancel(args.run_id)
        else:
            state = controller.status(args.run_id)
        print(json.dumps(_summary(state), indent=2, sort_keys=True))
        return 0
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
