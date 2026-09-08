"""workflow and workflow_state: controller behavior with fake native runners.

Every test builds its own repository under a scratch directory from the live
routing inputs and never touches the checkout. Model families are the generic
tier labels; the fake resolver maps them to fixture ids.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from ._repo import ROOT, ROUTING_INPUTS, TOOLS, copy_files  # noqa: F401

import routing_policy as rp
import workflow
import workflow_state as ws

OVERRIDE_FAMILY = "strong-main"
MAIN_NEEDLE = '"codex": {"main_profile":"S-MAIN","main_family":"strong-main","child_families":["fast","balanced","strong"],"explicit_child_overrides":[]}'


class ScratchDirectory:
    """A scratch tree under the system temp directory with a guarded cleanup."""

    def __init__(self):
        self.parent = Path(tempfile.gettempdir()).resolve()
        self.path = self.parent / f"workflow-test-{uuid.uuid4().hex}"
        self.path.mkdir()
        self.name = str(self.path)

    def cleanup(self):
        if self.path.resolve().parent != self.parent or self.path.is_symlink():
            raise RuntimeError("test scratch escaped its parent")
        shutil.rmtree(self.path)

    def __enter__(self):
        return self.name

    def __exit__(self, *args):
        self.cleanup()


class FakeResolver:
    def __init__(self, *, permission_evidence="proven", force_family=None):
        self.permission_evidence = permission_evidence
        self.force_family = force_family

    def __call__(self, root, task_id, runtime, profile=None, explicit_model_override=None, phase="execute"):
        policy = rp.load_policy(root)
        selected = rp.resolve_task(
            policy, task_id, runtime, profile=profile,
            explicit_model_override=explicit_model_override,
        )
        task = policy["tasks"][task_id]
        scope = policy["tool_profiles"][task["tool_profile"]]["write_scope"].lower()
        permission = "workspace-write" if scope != "none" else "read-only"
        family = self.force_family or selected["model_family"]
        return {
            **selected,
            "model_family": family,
            "native_model": f"native/{family}",
            "native_effort": selected["effort"],
            "native_permissions": {"sandbox_mode": permission},
            "native_tools": [selected["tool_profile"]],
            "role_id": task_id.replace(".", "-"),
            "missing_capabilities": [],
            "permission_limitations": [] if self.permission_evidence == "proven" else ["path scope is instruction-only"],
            "support": {"status": "supported"},
            "effective_model_evidence": {"status": "configured"},
            "observed_effective_model": f"native/{family}",
            "tool_permission_evidence": {"status": self.permission_evidence},
            "source_hash": rp.policy_digest(policy),
            "output_check": task["output_check"],
            "escalation": task["escalation"],
        }


class FakeRunner:
    def __init__(self, *, evidence="proven", tool_evidence="proven", behavior=None, same_actor=False):
        self.evidence = evidence
        self.tool_evidence = tool_evidence
        self.behavior = behavior or {}
        self.same_actor = same_actor
        self.calls = []
        self.worker_actor = None

    @staticmethod
    def _artifact_paths(prompt):
        marker = "ARTIFACT FILES:\n"
        if marker not in prompt:
            return []
        value = prompt.split(marker, 1)[1].splitlines()[0]
        return json.loads(value)

    def run(self, runtime, selection, prompt, *, cwd, timeout_seconds, max_turns, on_start, cancel_requested):
        task_id = selection["task_id"]
        mode = self.behavior.get(task_id)
        call = len(self.calls) + 1
        on_start({"pid": 1000 + call, "command_digest": f"command-{call}", "started_at": call})
        self.calls.append((task_id, prompt))
        if mode == "null":
            return None
        if task_id not in {"plan.work-packages", "resolve.conflict", "review.adversarial", "verify.deterministic"}:
            actor = self.worker_actor = self.worker_actor or "worker-actor"
            if selection["native_permissions"].get("sandbox_mode") == "workspace-write":
                for relative in self._artifact_paths(prompt):
                    path = cwd / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("built artifact\n", encoding="utf-8")
            output = "worker completed bounded artifact"
        elif task_id == "review.adversarial":
            actor = self.worker_actor if self.same_actor else "reviewer-actor"
            output = json.dumps({"pass": True, "issues": []})
            if mode == "mutate-after-review":
                match = next((line[6:] for line in prompt.splitlines() if line.startswith("FILE: ")), None)
                if match:
                    (cwd / match).write_text("changed after review\n", encoding="utf-8")
        elif task_id == "verify.deterministic":
            actor = self.worker_actor if mode == "same-as-worker" else "verifier-actor"
            output = json.dumps({
                "pass": True, "issues": [],
                "checks": [{"name": "fixture", "status": "pass", "command": "python check.py"}],
            })
            if mode == "mutate-after-verify":
                match = next((line[6:] for line in prompt.splitlines() if line.startswith("FILE: ")), None)
                if match:
                    (cwd / match).write_text("changed after verification\n", encoding="utf-8")
        else:
            actor = "planner-actor"
            if task_id == "resolve.conflict":
                actor = "analyst-actor"
            output = json.dumps({"pass": mode != "planner-reject", "issues": ["bad graph"] if mode == "planner-reject" else []})
        result = {
            "returncode": 0,
            "stderr": "",
            "timed_out": False,
            "cancelled": False,
            "process_stopped": True,
            "native_completed": True,
            "actor_id": actor,
            "output": output,
            "events": [{"type": "native.complete", "actor": actor}],
            "actual_tools": ["command_execution"] if task_id == "verify.deterministic" else [selection["tool_profile"]],
            "check_events": ([{
                "event_ref": "check-1", "tool": "command_execution",
                "command": "python check.py", "status": "pass",
            }] if task_id == "verify.deterministic" else []),
            "effective_model": {"status": self.evidence, "model": selection["native_model"] if self.evidence == "proven" else None},
            "tool_permissions": {
                "status": self.tool_evidence,
                "loaded_tools": selection["native_tools"] if self.tool_evidence == "proven" else [],
                "source": "fake native init",
            },
            "command_digest": f"command-{call}",
        }
        if mode == "failed":
            result.update(
                returncode=1, native_completed=False, stderr="fixture native failure",
                events=[{"type": "turn.failed", "error": "invalid fixture config"}],
                native_errors=["invalid fixture config"],
            )
        elif mode == "timeout":
            result.update(timed_out=True, native_completed=False)
        elif mode == "empty":
            result["output"] = ""
        elif mode == "no-actor":
            result["actor_id"] = None
        elif mode == "unconfirmed-stop":
            result.update(cancelled=True, process_stopped=False, native_completed=False)
        elif mode == "review-fail":
            result["output"] = json.dumps({"pass": False, "issues": ["defect"]})
        elif mode == "wrong-model":
            result["effective_model"] = {"status": "proven", "model": "unexpected-model"}
        elif mode == "secret-output":
            result["output"] = "---\naccess: secret\n---\nprivate\n"
        return result


def seed_repo(root: Path, *, codex_override: bool = False, resolve_all: bool = False) -> None:
    """Copy the live routing inputs into root and compile the manifest there."""
    copy_files(root, ROUTING_INPUTS)
    if codex_override:
        source = root / rp.SOURCE
        text = source.read_text(encoding="utf-8")
        assert MAIN_NEEDLE in text
        source.write_text(
            text.replace(MAIN_NEEDLE, MAIN_NEEDLE.replace('"explicit_child_overrides":[]', f'"explicit_child_overrides":["{OVERRIDE_FAMILY}"]')),
            encoding="utf-8",
        )
    if resolve_all:
        for runtime in ("claude", "codex", "opencode"):
            path = root / "harness/adapters" / runtime / "model-map.json"
            native = json.loads(path.read_text(encoding="utf-8"))
            for family in native["families"]:
                native["families"][family] = f"fixture/{runtime}-{family}"
            path.write_text(json.dumps(native, indent=2) + "\n", encoding="utf-8")
    rp.write_manifest(root, rp.load_policy(root))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = ScratchDirectory()
        self.root = Path(self.temp.name)
        seed_repo(self.root)
        self.runs = self.root / ".tmp" / "workflows"

    def tearDown(self):
        self.temp.cleanup()

    def spec(self, **updates):
        value = {
            "schema_version": 1,
            "runtime": "codex",
            "planning_depth": "T2",
            "mode": "managed",
            "requirements": "Create the bounded output file.",
            "acceptance_criteria": ["out.txt exists", "content is non-empty"],
            "source_evidence": ["local requirement"],
            "ratification": {"actor": "main", "authorized": True},
            "work_packages": [{
                "id": "build", "task_id": "code.feature", "prompt": "Write out.txt.",
                "artifact_paths": ["out.txt"], "dependencies": [],
            }],
        }
        value.update(updates)
        return value

    def controller(self, runner=None, resolver=None):
        return workflow.WorkflowController(
            self.root, self.runs, runner=runner or FakeRunner(), resolver=resolver or FakeResolver()
        )

    def test_plan_seeds_mandatory_t2_and_t3_roles(self):
        t2 = self.controller().plan(self.spec())
        self.assertEqual([p["id"] for p in t2["packages"]], ["_managed-plan", "build", "_managed-review"])
        self.assertEqual(set(t2["selections"]), {"_managed-plan", "build", "_managed-review"})
        t3 = self.controller().plan(self.spec(planning_depth="T3"))
        self.assertEqual(
            [p["id"] for p in t3["packages"]],
            ["_managed-plan", "_managed-analysis", "build", "_managed-verify", "_managed-review"],
        )
        architecture = self.spec()
        architecture["work_packages"][0]["task_id"] = "decide.architecture"
        raised = self.controller().plan(architecture)
        self.assertEqual(raised["spec"]["planning_depth"], "T3")
        self.assertIn("_managed-verify", [package["id"] for package in raised["packages"]])
        self.assertIn("_managed-analysis", [package["id"] for package in raised["packages"]])

    def test_t3_planner_and_analyst_see_full_seeded_graph_and_actual_edges(self):
        controller = self.controller()
        state = controller.start(self.spec(planning_depth="T3"), "wf-full-t3-graph")
        packages = {package["id"]: package for package in state["packages"]}
        expected_edges = {
            "_managed-plan": [],
            "_managed-analysis": ["_managed-plan"],
            "build": ["_managed-analysis"],
            "_managed-verify": ["build"],
            "_managed-review": ["build", "_managed-verify"],
        }
        for stage_id in ("_managed-plan", "_managed-analysis"):
            prompt, _ = controller._prompt(state, packages[stage_id], state["selections"][stage_id])
            graph = json.loads(prompt.split("PACKAGES:\n", 1)[1])
            nodes = {node["id"]: node for node in graph}
            self.assertEqual(set(nodes), set(expected_edges))
            self.assertEqual({node_id: node["dependencies"] for node_id, node in nodes.items()}, expected_edges)
            self.assertEqual(nodes["build"]["origin"], "user-work-package")
            self.assertEqual(nodes["build"]["prompt"], "Write out.txt.")
            for internal_id in set(expected_edges) - {"build"}:
                self.assertEqual(nodes[internal_id]["origin"], "controller-inserted-mandatory-stage")
                self.assertEqual(nodes[internal_id]["prompt_source"], "controller-generated-at-execution")
            for node in nodes.values():
                self.assertEqual(node["managed_kind"], packages[node["id"]]["managed_kind"])
                for key in ("role_id", "profile", "tool_profile", "native_tools"):
                    self.assertIn(key, node["selection"])

    def test_input_cannot_supply_receipts_or_managed_tasks(self):
        with self.assertRaisesRegex(ws.WorkflowError, "cannot import"):
            self.controller().plan({**self.spec(), "receipts": {"fake": "pass"}})
        bad = self.spec()
        bad["work_packages"][0]["task_id"] = "review.adversarial"
        with self.assertRaisesRegex(ws.WorkflowError, "controller-managed"):
            self.controller().plan(bad)

    def test_preflight_rejects_unbound_worker_before_start(self):
        base = FakeResolver()

        def unbound(*args, **kwargs):
            selected = base(*args, **kwargs)
            if args[1] == "code.feature":
                selected["missing_capabilities"] = ["workspace-write"]
            return selected

        with self.assertRaisesRegex(ws.WorkflowError, "misses capabilities"):
            self.controller(resolver=unbound).start(self.spec(), "wf-unbound")
        self.assertFalse((self.runs / "wf-unbound" / "state.json").exists())

    def test_requires_one_explicit_writer_and_rejects_collision(self):
        no_writer = self.spec()
        no_writer["work_packages"][0].update(task_id="retrieve.local", artifact_paths=[])
        with self.assertRaisesRegex(ws.WorkflowError, "explicit canonical artifact writer"):
            self.controller().plan(no_writer)
        collision = self.spec()
        collision["work_packages"].append({
            "id": "second", "task_id": "edit.narrative", "prompt": "also write",
            "artifact_paths": ["out.txt"], "dependencies": [],
        })
        with self.assertRaisesRegex(ws.WorkflowError, "two writers"):
            self.controller().plan(collision)

    def test_managed_run_executes_native_contributions_and_marks_unknown_evidence(self):
        runner = FakeRunner(evidence="unknown")
        controller = self.controller(runner, FakeResolver(permission_evidence="unknown"))
        state = controller.start(self.spec(), "wf-managed-ok")
        final = controller.run(state["run_id"])
        self.assertEqual(final["state"], "completed")
        self.assertEqual(final["grade"]["managed_gate"], "pass")
        self.assertEqual(final["grade"]["evidence_audit"], "unknown")
        self.assertEqual(final["grade"]["enforcement_grade"], "reduced")
        self.assertIn("build:role-enforcement", final["grade"]["unknown"])
        self.assertEqual(len(runner.calls), 3)
        planner_prompt = runner.calls[0][1]
        policy = rp.load_policy(self.root)
        family = policy["profiles"]["B-BUILD"]["families"]["codex"]
        self.assertIn('"profile": "B-BUILD"', planner_prompt)
        self.assertIn('"tool_profile": "code-edit"', planner_prompt)
        self.assertIn(f'"native_model": "native/{family}"', planner_prompt)
        self.assertIn('"prompt": "Write out.txt."', planner_prompt)
        self.assertNotIn("worker completed bounded artifact", runner.calls[-1][1])

    def test_strict_mode_rejects_unknown_effective_model_or_permissions(self):
        controller = self.controller(FakeRunner(evidence="unknown"), FakeResolver(permission_evidence="unknown"))
        state = controller.start(self.spec(mode="strict"), "wf-strict-unknown")
        with self.assertRaisesRegex(ws.WorkflowError, "strict evidence gate"):
            controller.run(state["run_id"])
        self.assertEqual(controller.status(state["run_id"])["state"], "blocked")

    def test_main_family_child_without_recorded_override_is_rejected(self):
        controller = self.controller(FakeRunner(), FakeResolver(force_family=OVERRIDE_FAMILY))
        with self.assertRaisesRegex(ws.WorkflowError, "child model ceiling"):
            controller.start(self.spec(), "wf-override-bad")

    def test_explicit_user_override_is_preserved(self):
        seed_repo(self.root, codex_override=True)
        spec = self.spec()
        spec["work_packages"][0]["explicit_model_override"] = {
            "model_family": OVERRIDE_FAMILY, "authorized_by": "user", "instruction": "Use the main family for this child.",
        }
        controller = self.controller()
        state = controller.start(spec, "wf-override-explicit")
        final = controller.run(state["run_id"])
        self.assertEqual(final["receipts"]["build"]["requested"]["model_family"], OVERRIDE_FAMILY)

    def test_failed_null_empty_and_timeout_children_block(self):
        for behavior, pattern in (
            ("failed", "failed native completion"),
            ("null", "no result"),
            ("empty", "empty output"),
            ("timeout", "timed out"),
        ):
            with self.subTest(behavior=behavior):
                controller = workflow.WorkflowController(
                    self.root,
                    self.root / ".tmp" / f"workflows-{behavior}",
                    runner=FakeRunner(behavior={"code.feature": behavior}),
                    resolver=FakeResolver(),
                )
                run_id = f"wf-failure-{behavior}"
                controller.start(self.spec(), run_id)
                with self.assertRaisesRegex(ws.WorkflowError, pattern):
                    controller.run(run_id)
                if behavior == "failed":
                    failure = controller.status(run_id)["failures"]["build"]
                    self.assertEqual(failure["returncode"], 1)
                    self.assertEqual(failure["native_errors"], ["invalid fixture config"])
                    self.assertEqual(failure["native_event_types"], ["turn.failed"])

    def test_proven_effective_model_mismatch_blocks(self):
        controller = self.controller(FakeRunner(behavior={"code.feature": "wrong-model"}))
        controller.start(self.spec(), "wf-wrong-model")
        with self.assertRaisesRegex(ws.WorkflowError, "unexpected effective model"):
            controller.run("wf-wrong-model")

    def test_same_actor_and_stale_review_are_rejected(self):
        controller = self.controller(FakeRunner(same_actor=True))
        controller.start(self.spec(), "wf-same-actor")
        with self.assertRaisesRegex(ws.WorkflowError, "not independent"):
            controller.run("wf-same-actor")
        controller = self.controller(FakeRunner(behavior={"review.adversarial": "mutate-after-review"}))
        controller.start(self.spec(), "wf-stale-review")
        with self.assertRaisesRegex(ws.WorkflowError, "worker artifact changed"):
            controller.run("wf-stale-review")

    def test_completed_run_revalidates_artifact_and_reruns_review(self):
        runner = FakeRunner()
        controller = self.controller(runner)
        controller.start(self.spec(), "wf-revalidate")
        self.assertEqual(controller.run("wf-revalidate")["state"], "completed")
        (self.root / "out.txt").write_text("operator correction\n", encoding="utf-8")
        final = controller.run("wf-revalidate")
        self.assertEqual(final["state"], "completed")
        self.assertEqual([task for task, _ in runner.calls].count("review.adversarial"), 2)
        self.assertEqual([task for task, _ in runner.calls].count("code.feature"), 2)

    def test_t3_verifier_is_separate_and_bound_to_reviewed_revision(self):
        controller = self.controller(FakeRunner(behavior={"verify.deterministic": "same-as-worker"}))
        controller.start(self.spec(planning_depth="T3"), "wf-verifier-actor")
        with self.assertRaisesRegex(ws.WorkflowError, "verifier actor is not separate"):
            controller.run("wf-verifier-actor")
        controller = workflow.WorkflowController(
            self.root, self.root / ".tmp" / "workflows-verifier-stale",
            runner=FakeRunner(behavior={"verify.deterministic": "mutate-after-verify"}),
            resolver=FakeResolver(),
        )
        controller.start(self.spec(planning_depth="T3"), "wf-verifier-stale")
        with self.assertRaisesRegex(ws.WorkflowError, "worker artifact changed"):
            controller.run("wf-verifier-stale")

    def test_t3_verifier_requires_structured_checks_and_native_check_event(self):
        runner = FakeRunner()
        controller = self.controller(runner)
        controller.start(self.spec(planning_depth="T3"), "wf-verifier-evidence")
        original = runner.run

        def missing_check(*args, **kwargs):
            result = original(*args, **kwargs)
            if result and args[1]["task_id"] == "verify.deterministic":
                result["output"] = json.dumps({"pass": True, "issues": []})
                result["actual_tools"] = []
            return result

        runner.run = missing_check
        with self.assertRaisesRegex(ws.WorkflowError, "structured verdict"):
            controller.run("wf-verifier-evidence")

        runner = FakeRunner()
        original = runner.run

        def mismatched_check(*args, **kwargs):
            result = original(*args, **kwargs)
            if result and args[1]["task_id"] == "verify.deterministic":
                result["check_events"][0]["command"] = "python unrelated.py"
            return result

        runner.run = mismatched_check
        controller = workflow.WorkflowController(
            self.root, self.root / ".tmp" / "workflows-verifier-mismatch",
            runner=runner, resolver=FakeResolver(),
        )
        controller.start(self.spec(planning_depth="T3"), "wf-verifier-mismatch")
        with self.assertRaisesRegex(ws.WorkflowError, "matching successful native command evidence"):
            controller.run("wf-verifier-mismatch")
        failure = controller.status("wf-verifier-mismatch")["failures"]["_managed-verify"]
        self.assertEqual(failure["reason"], "deterministic verifier checks lack matching successful native command evidence")
        self.assertEqual(failure["semantic_verdict"]["checks"][0]["command"], "python check.py")
        self.assertEqual(failure["check_events"][0]["command"], "python unrelated.py")
        self.assertNotIn("output", failure)

        observed_wrapper = '"C:\\tools\\pwsh.exe" -NoProfile -Command \'python check.py\''
        self.assertTrue(workflow._command_claim_matches_event(
            "python check.py",
            {"tool": "command_execution", "status": "pass", "command": observed_wrapper},
        ))
        self.assertFalse(workflow._command_claim_matches_event(
            "python check.py; echo unsafe",
            {"tool": "command_execution", "status": "pass", "command": observed_wrapper},
        ))
        self.assertFalse(workflow._command_claim_matches_event(
            "python check.py",
            {"tool": "command_execution", "status": "failed", "command": observed_wrapper},
        ))
        for shell_tool in ("Bash", "bash", "shell"):
            self.assertTrue(workflow._command_claim_matches_event(
                "python check.py",
                {"tool": shell_tool, "status": "pass", "command": "python check.py"},
            ))
            self.assertFalse(workflow._command_claim_matches_event(
                "python check.py",
                {"tool": shell_tool, "status": "pass", "command": observed_wrapper},
            ))

        malformed = FakeRunner()
        original = malformed.run

        def failed_check(*args, **kwargs):
            result = original(*args, **kwargs)
            if result and args[1]["task_id"] == "verify.deterministic":
                result["output"] = json.dumps({
                    "pass": True, "issues": [],
                    "checks": [{"name": "fixture", "status": "failed", "command": "python check.py"}],
                })
            return result

        malformed.run = failed_check
        controller = workflow.WorkflowController(
            self.root, self.root / ".tmp" / "workflows-verifier-malformed",
            runner=malformed, resolver=FakeResolver(),
        )
        controller.start(self.spec(planning_depth="T3"), "wf-verifier-malformed")
        with self.assertRaisesRegex(ws.WorkflowError, "structured verdict"):
            controller.run("wf-verifier-malformed")

        oversized = workflow._bounded_failure_verdict({
            "pass": True,
            "issues": ["x" * 3000] * 40,
            "checks": [{"name": "n" * 3000, "status": "pass", "command": "c" * 3000}] * 40,
            "output": "must not persist",
        })
        self.assertEqual(len(oversized["issues"]), 32)
        self.assertEqual(len(oversized["issues"][0]), 2000)
        self.assertEqual(len(oversized["checks"]), 32)
        self.assertEqual(len(oversized["checks"][0]["command"]), 2000)
        self.assertNotIn("output", oversized)

    def test_t3_verifier_accepts_exact_successful_shell_facts_per_runtime(self):
        for runtime, shell_tool in (("claude", "Bash"), ("opencode", "bash")):
            with self.subTest(runtime=runtime):
                runner = FakeRunner()
                original = runner.run

                def runtime_shell(*args, **kwargs):
                    result = original(*args, **kwargs)
                    if result and args[1]["task_id"] == "verify.deterministic":
                        result["check_events"][0]["tool"] = shell_tool
                    return result

                runner.run = runtime_shell
                spec = self.spec(planning_depth="T3", runtime=runtime)
                controller = workflow.WorkflowController(
                    self.root, self.root / ".tmp" / f"workflows-{runtime}-shell",
                    runner=runner, resolver=FakeResolver(),
                )
                final = controller.start(spec, f"wf-{runtime}-shell")
                final = controller.run(final["run_id"])
                self.assertEqual(final["state"], "completed")

    def test_t3_reviewer_receives_aggregate_and_verifier_proof_packet(self):
        runner = FakeRunner()
        controller = self.controller(runner)
        controller.start(self.spec(planning_depth="T3"), "wf-review-proof")
        final = controller.run("wf-review-proof")
        self.assertEqual(final["state"], "completed")
        reviewer_prompt = next(prompt for task, prompt in runner.calls if task == "review.adversarial")
        raw_hash = hashlib.sha256((self.root / "out.txt").read_bytes()).hexdigest()
        self.assertIn("This aggregate is not a raw file SHA-256", reviewer_prompt)
        self.assertIn(f'"sha256": "{raw_hash}"', reviewer_prompt)
        self.assertIn("CONTROLLER VERIFIER RECEIPT:", reviewer_prompt)
        self.assertIn('"package_id": "_managed-verify"', reviewer_prompt)
        self.assertIn('"actor_id": "verifier-actor"', reviewer_prompt)
        self.assertIn('"command": "python check.py"', reviewer_prompt)
        self.assertIn(f'"reviewed_revision": "{final["receipts"]["_managed-verify"]["reviewed_revision"]}"', reviewer_prompt)

    def test_all_authored_production_write_scopes_require_writer_controls(self):
        policy = rp.load_policy(self.root)
        expected = {
            task_id for task_id, task in policy["tasks"].items()
            if not str(policy["tool_profiles"][task["tool_profile"]]["write_scope"]).lower().startswith(("none", "scratch", ".tmp"))
        }
        actual = {task_id for task_id in policy["tasks"] if ws.task_writes_canonical(policy, task_id)}
        self.assertEqual(actual, expected)
        self.assertIn("ops.deploy", actual)
        self.assertIn("artifact.imagegen", actual)

    def test_start_claim_is_atomic_under_concurrency(self):
        controller = self.controller()
        barrier = threading.Barrier(2)
        results = []

        def start_once():
            barrier.wait()
            try:
                controller.start(self.spec(), "wf-start-race")
                results.append("created")
            except ws.WorkflowError:
                results.append("rejected")

        threads = [threading.Thread(target=start_once) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertCountEqual(results, ["created", "rejected"])
        self.assertEqual(controller.load("wf-start-race")["run_id"], "wf-start-race")

    def test_unconfirmed_interruption_keeps_writer_lock(self):
        controller = self.controller(FakeRunner(behavior={"code.feature": "unconfirmed-stop"}))
        controller.start(self.spec(), "wf-unconfirmed")
        with self.assertRaisesRegex(ws.WorkflowError, "not confirmed stopped"):
            controller.run("wf-unconfirmed")
        self.assertTrue((self.runs / ".canonical-writer.lock").exists())
        self.assertTrue((self.runs / "wf-unconfirmed" / "controller.lock").exists())
        self.assertEqual(controller.status("wf-unconfirmed")["state"], "cancel-pending")

    def test_writer_collision_blocks_second_run(self):
        self.runs.mkdir(parents=True)
        (self.runs / ".canonical-writer.lock").write_text('{"run_id":"other","package_id":"build"}\n', encoding="utf-8")
        controller = self.controller()
        controller.start(self.spec(), "wf-collision")
        with self.assertRaisesRegex(ws.WorkflowError, "already held"):
            controller.run("wf-collision")

    def test_cancel_with_active_process_stays_pending(self):
        controller = self.controller()
        controller.start(self.spec(), "wf-cancel")
        state = controller.load("wf-cancel")
        state["active_process"] = {"pid": 123, "owned": True, "package_id": "build"}
        controller._save(state)
        cancelled = controller.cancel("wf-cancel")
        self.assertEqual(cancelled["state"], "cancel-pending")
        self.assertTrue((self.runs / "wf-cancel" / "cancel.requested").exists())

    def test_cancel_signal_does_not_overwrite_owned_controller_state(self):
        controller = self.controller()
        controller.start(self.spec(), "wf-cancel-race")
        lock = ws.ExclusiveLock(
            self.runs / "wf-cancel-race" / "controller.lock",
            {"run_id": "wf-cancel-race", "owner": "active-controller"},
        )
        lock.acquire()
        before = controller.load("wf-cancel-race")
        pending = controller.cancel("wf-cancel-race")
        after = controller.load("wf-cancel-race")
        self.assertEqual(pending["state"], "cancel-pending")
        self.assertEqual(after, before)
        self.assertTrue(controller._cancel_requested("wf-cancel-race"))
        lock.release(process_stopped=True)

    def test_real_native_resolver_contract_with_fake_process_runner(self):
        seed_repo(self.root, resolve_all=True)
        runner = FakeRunner(evidence="unknown")
        controller = workflow.WorkflowController(self.root, self.root / ".tmp" / "workflows-real", runner=runner)
        controller.start(self.spec(runtime="claude"), "wf-real-resolver")
        final = controller.run("wf-real-resolver")
        self.assertEqual(final["state"], "completed")
        self.assertEqual(final["grade"]["enforcement_grade"], "reduced")
        policy = rp.load_policy(self.root)
        family = policy["profiles"]["B-BUILD"]["families"]["claude"]
        self.assertEqual(final["receipts"]["build"]["requested"]["native_model"], f"fixture/claude-{family}")
        worker_prompt = next(prompt for task, prompt in runner.calls if task == "code.feature")
        self.assertIn("TOOL PROFILE: code-edit", worker_prompt)
        self.assertIn("Do not spawn, delegate, message", worker_prompt)

    def test_real_resolver_refuses_an_unresolved_model_id(self):
        runner = FakeRunner(evidence="unknown")
        controller = workflow.WorkflowController(self.root, self.root / ".tmp" / "workflows-unresolved", runner=runner)
        native = json.loads((self.root / "harness/adapters/codex/model-map.json").read_text(encoding="utf-8"))
        if any(value for value in native["families"].values()):
            self.skipTest("the live codex model map resolves ids; nothing to refuse")
        with self.assertRaisesRegex(ws.WorkflowError, "no exact model"):
            controller.start(self.spec(runtime="codex"), "wf-unresolved")

    def test_read_only_worker_result_is_atomically_captured(self):
        spec = self.spec()
        spec["work_packages"] = [{
            "id": "research", "task_id": "retrieve.local", "prompt": "Produce a summary.",
            "artifact_paths": ["summary.md"], "result_artifact": "summary.md", "dependencies": [],
        }]
        controller = self.controller()
        controller.start(spec, "wf-read-summary")
        final = controller.run("wf-read-summary")
        self.assertEqual(final["state"], "completed")
        self.assertEqual((self.root / "summary.md").read_text(encoding="utf-8"), "worker completed bounded artifact\n")

    def test_secret_marked_capture_is_rejected_before_materialization(self):
        spec = self.spec()
        spec["work_packages"] = [{
            "id": "research", "task_id": "retrieve.local", "prompt": "Produce a summary.",
            "artifact_paths": ["private.md"], "result_artifact": "private.md", "dependencies": [],
        }]
        controller = self.controller(FakeRunner(behavior={"retrieve.local": "secret-output"}))
        controller.start(spec, "wf-secret-capture")
        with self.assertRaisesRegex(ws.WorkflowError, "access is secret"):
            controller.run("wf-secret-capture")
        self.assertFalse((self.root / "private.md").exists())

    def test_composite_floor_cannot_lower_strong_numeric_package(self):
        policy = rp.load_policy(self.root)
        package = {
            "id": "numeric-plan", "task_id": "plan.work-packages", "managed_kind": "worker",
            "floor_flags": {"numeric_deliverable": True}, "explicit_model_override": None,
        }
        selected = workflow.resolve_native(self.root, policy, package, "codex", FakeResolver())
        self.assertEqual(selected["profile"], "S-ANALYZE")

    def test_policy_hash_drift_and_mixed_or_imported_receipts_fail(self):
        controller = self.controller()
        controller.start(self.spec(), "wf-integrity")
        state = controller.load("wf-integrity")
        state["receipts"]["foreign"] = {
            "run_id": "different", "package_id": "foreign", "provenance": "controller-owned-native-process"
        }
        controller._save(state)
        with self.assertRaisesRegex(ws.WorkflowError, "mixed or foreign"):
            controller.load("wf-integrity")

        controller.start(self.spec(), "wf-import")
        state = controller.load("wf-import")
        state["receipts"]["fake"] = {"run_id": "wf-import", "package_id": "fake", "provenance": "imported"}
        controller._save(state)
        with self.assertRaisesRegex(ws.WorkflowError, "untrusted imported"):
            controller.load("wf-import")

        controller.start(self.spec(), "wf-policy-drift")
        manifest = json.loads((self.root / rp.MANIFEST).read_text(encoding="utf-8"))
        manifest["source_hash"] = "0" * 64
        ws.atomic_write_json(self.root / rp.MANIFEST, manifest)
        with self.assertRaisesRegex(ws.WorkflowError, "source/hash drift"):
            controller.run("wf-policy-drift")

    def test_native_parsers_capture_provenance_and_errors(self):
        claude = "\n".join([
            json.dumps({
                "type": "system", "subtype": "init", "session_id": "s1",
                "model": "fixture-main-model", "tools": ["Read"],
            }),
            json.dumps({
                "type": "assistant", "message": {"content": [{
                    "type": "tool_use", "id": "tool-1", "name": "Bash",
                    "input": {"command": "python check.py"},
                }]},
            }),
            json.dumps({
                "type": "user", "message": {"content": [{
                    "type": "tool_result", "tool_use_id": "tool-1", "is_error": False,
                }]},
            }),
            json.dumps({"type": "result", "subtype": "success", "session_id": "s1", "result": "done"}),
        ])
        parsed = workflow.parse_native_result("claude", claude, 0)
        self.assertTrue(parsed["native_completed"])
        self.assertEqual(parsed["effective_model"]["status"], "proven")
        self.assertEqual(parsed["tool_permissions"]["status"], "proven")
        self.assertEqual(parsed["check_events"][0]["tool"], "Bash")
        codex = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "t1"}),
            json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "I will inspect the files first."},
            }),
            json.dumps({
                "type": "item.completed",
                "item": {
                    "id": "check-1", "type": "command_execution", "command": "python check.py",
                    "status": "completed", "exit_code": 0,
                },
            }),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "done"}}),
            json.dumps({"type": "turn.completed"}),
        ])
        parsed = workflow.parse_native_result("codex", codex, 0)
        self.assertEqual(parsed["actor_id"], "t1")
        self.assertEqual(parsed["output"], "done")
        self.assertEqual(parsed["effective_model"]["status"], "unknown")
        self.assertEqual(parsed["check_events"][0]["command"], "python check.py")
        complete_final = "First final section.\n\nSecond final section.\n\n```json\n{\"ok\": true}\n```"
        parsed = workflow.parse_native_result("codex", codex, 0, final_output=complete_final)
        self.assertEqual(parsed["output"], complete_final)
        self.assertNotIn("inspect the files", parsed["output"])
        self.assertEqual(len(parsed["events"]), 5)
        missing_final = workflow.parse_native_result("codex", codex, 0, final_output="")
        self.assertFalse(missing_final["native_completed"])
        self.assertIn("without a final response", missing_final["native_errors"][0])
        failed_final = workflow.parse_native_result(
            "codex",
            "\n".join([
                json.dumps({"type": "thread.started", "thread_id": "t-failed"}),
                json.dumps({"type": "turn.failed", "error": "provider failure"}),
            ]),
            1,
            final_output="partial response",
        )
        self.assertFalse(failed_final["native_completed"])
        self.assertEqual(failed_final["output"], "partial response")
        self.assertIn("provider failure", failed_final["native_errors"])
        incomplete = workflow.parse_native_result(
            "codex", json.dumps({"type": "thread.started", "thread_id": "t2"}), 0
        )
        self.assertFalse(incomplete["native_completed"])
        opencode = json.dumps({"type": "error", "sessionID": "o1", "message": "provider consent required"})
        self.assertFalse(workflow.parse_native_result("opencode", opencode, 0)["native_completed"])
        opencode = "\n".join([
            json.dumps({"type": "text", "sessionID": "o2", "part": {"text": "done", "modelID": "configured"}}),
            json.dumps({
                "type": "tool", "sessionID": "o2", "part": {
                    "type": "tool", "id": "tool-2", "tool": "bash",
                    "state": {
                        "status": "completed", "input": {"command": "python check.py"},
                        "metadata": {"exit": 0},
                    },
                },
            }),
            json.dumps({"type": "step_finish", "sessionID": "o2"}),
        ])
        parsed = workflow.parse_native_result("opencode", opencode, 0)
        self.assertFalse(parsed["native_completed"])
        self.assertEqual(parsed["effective_model"]["status"], "unknown")
        self.assertEqual(parsed["check_events"][0]["tool"], "bash")
        terminal = opencode + "\n" + json.dumps({"type": "session.completed", "sessionID": "o2"})
        self.assertTrue(workflow.parse_native_result("opencode", terminal, 0)["native_completed"])

    def test_child_env_and_commands_preserve_auth_without_model_forcing(self):
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_SUBAGENT_MODEL": "forced-model", "TEST_RUNTIME_AUTH": "kept"}):
            child = workflow.safe_child_env()
        self.assertNotIn("CLAUDE_CODE_SUBAGENT_MODEL", child)
        self.assertEqual(child["TEST_RUNTIME_AUTH"], "kept")
        claude = workflow.build_command(
            "claude",
            {"native_model": "fixture-fast", "role_id": "role", "task_id": "retrieve.local", "native_tools": []},
            2,
        )
        self.assertEqual(claude[-2:], ["--tools", ""])
        self.assertIn("--strict-mcp-config", claude)
        codex = workflow.build_command(
            "codex",
            {
                "native_model": "fixture-strong", "role_id": "role", "task_id": "review.adversarial",
                "native_permissions": {"sandbox_mode": "read-only"}, "native_effort": "high",
            },
            2,
            output_last_message=Path("last-message.txt"),
        )
        self.assertIn("agents.enabled=false", codex)
        self.assertIn("model_reasoning_effort=high", codex)
        self.assertNotIn('model_reasoning_effort="high"', codex)
        self.assertEqual(codex[codex.index("--output-last-message") + 1], "last-message.txt")
        self.assertEqual(codex[-1], "-")

    def test_codex_runner_uses_native_last_message_and_retains_json_events(self):
        progress = "I will inspect the files first."
        final = "First final section.\n\nSecond final section."
        stdout = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "t-final"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": progress}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "event-stream final"}}),
            json.dumps({"type": "turn.completed"}),
        ])
        process = mock.Mock(pid=1234, returncode=0)
        process.stdin = mock.Mock()
        process.poll.return_value = 0
        process.communicate.return_value = (stdout, "")
        tree = mock.Mock()
        tree.confirm_stopped.return_value = True
        output_path = None

        def resolve_command(command):
            nonlocal output_path
            output_path = Path(command[command.index("--output-last-message") + 1])
            output_path.write_text(final, encoding="utf-8")
            return ["codex"]

        runner = workflow.NativeProcessRunner()
        selection = {
            "native_model": "fixture-strong", "role_id": "role", "task_id": "retrieve.local",
            "native_permissions": {"sandbox_mode": "read-only"}, "native_effort": "high",
        }
        with (
            mock.patch.object(workflow, "_resolved_executable_command", side_effect=resolve_command),
            mock.patch.object(workflow.subprocess, "Popen", return_value=process),
            mock.patch.object(workflow, "OwnedProcessTree", return_value=tree),
        ):
            result = runner.run(
                "codex", selection, "prompt", cwd=self.root, timeout_seconds=1, max_turns=1,
                on_start=lambda _: None, cancel_requested=lambda: False,
            )
        self.assertEqual(result["output"], final)
        self.assertNotIn(progress, result["output"])
        self.assertEqual(
            [event["type"] for event in result["events"]],
            ["thread.started", "item.completed", "item.completed", "turn.completed"],
        )
        self.assertTrue(result["native_completed"])
        self.assertIsNotNone(output_path)
        self.assertFalse(output_path.exists())

    @unittest.skipUnless(os.name == "nt", "pathlib.Path is bound to the host OS class at import time; mocking os.name cannot make a WindowsPath instantiate on POSIX")
    def test_windows_cmd_wrapper_preserves_bare_codex_config_value(self):
        command = [
            "codex", "exec", "-c", "agents.enabled=false",
            "-c", "model_reasoning_effort=high", "-",
        ]
        with (
            mock.patch.object(workflow.os, "name", "nt"),
            mock.patch.object(workflow.shutil, "which", side_effect=[r"C:\\tools\\codex.cmd"]),
            mock.patch.dict(os.environ, {"COMSPEC": r"C:\\Windows\\System32\\cmd.exe"}),
        ):
            wrapped = workflow._resolved_executable_command(command)
        self.assertEqual(wrapped[:4], [r"C:\\Windows\\System32\\cmd.exe", "/d", "/s", "/c"])
        self.assertIn("model_reasoning_effort=high", wrapped[4])
        self.assertNotIn(r'\"high\"', wrapped[4])

    def test_process_start_callback_failure_stops_and_closes_owned_tree(self):
        process = mock.Mock(pid=1234)
        tree = mock.Mock()
        tree.stop.return_value = True
        runner = workflow.NativeProcessRunner()
        selection = {
            "native_model": "fixture-strong", "role_id": "role", "task_id": "retrieve.local",
            "native_permissions": {"sandbox_mode": "read-only"}, "native_effort": "high",
        }
        with (
            mock.patch.object(workflow, "_resolved_executable_command", return_value=["codex"]),
            mock.patch.object(workflow.subprocess, "Popen", return_value=process),
            mock.patch.object(workflow, "OwnedProcessTree", return_value=tree),
            self.assertRaisesRegex(workflow.NativeProcessError, "state callback failed"),
        ):
            runner.run(
                "codex", selection, "prompt", cwd=self.root, timeout_seconds=1, max_turns=1,
                on_start=lambda _: (_ for _ in ()).throw(RuntimeError("state callback failed")),
                cancel_requested=lambda: False,
            )
        tree.resume.assert_not_called()
        tree.stop.assert_called_once_with()
        tree.close.assert_called_once_with()


class DelegationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = ScratchDirectory()
        self.root = Path(self.temp.name)
        seed_repo(self.root, resolve_all=True)
        self.spec_path = self.root / "spec.json"
        self.spec_path.write_text(json.dumps({
            "schema_version": 1, "runtime": "claude", "planning_depth": "T2", "mode": "managed",
            "requirements": "Create the bounded output file.",
            "acceptance_criteria": ["out.txt exists"], "source_evidence": ["local requirement"],
            "ratification": {"actor": "main", "authorized": True},
            "work_packages": [{"id": "build", "task_id": "code.feature", "prompt": "Write out.txt.",
                               "artifact_paths": ["out.txt"], "dependencies": []}],
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = workflow.main(argv)
        return code, out.getvalue(), err.getvalue()

    def _set_mandatory(self, value):
        path = self.root / "harness/registry/structure.json"
        structure = json.loads(path.read_text(encoding="utf-8"))
        structure["delegation"] = {"mandatory": value}
        path.write_text(json.dumps(structure, indent=2), encoding="utf-8")

    def test_refuses_without_opt_in_when_delegation_is_not_mandatory(self):
        self._set_mandatory(False)
        code, out, err = self._main(["--root", str(self.root), "plan", str(self.spec_path)])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("delegation.mandatory is false", err)
        self.assertIn("--opt-in", err)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_opt_in_flag_runs_the_plan(self):
        self._set_mandatory(False)
        code, out, err = self._main(["--root", str(self.root), "--opt-in", "plan", str(self.spec_path)])
        self.assertEqual(code, 0, err)
        self.assertEqual([p["id"] for p in json.loads(out)["packages"]], ["_managed-plan", "build", "_managed-review"])

    def test_mandatory_delegation_runs_without_the_flag(self):
        self._set_mandatory(True)
        code, out, err = self._main(["--root", str(self.root), "plan", str(self.spec_path)])
        self.assertEqual(code, 0, err)
        self.assertIn("_managed-plan", out)

    def test_missing_or_malformed_structure_reads_as_not_mandatory(self):
        path = self.root / "harness/registry/structure.json"
        path.write_text("{not json", encoding="utf-8")
        self.assertFalse(workflow.delegation_mandatory(self.root))
        path.unlink()
        self.assertFalse(workflow.delegation_mandatory(self.root))
        self.assertIsNotNone(workflow.delegation_gate(self.root, False))
        self.assertIsNone(workflow.delegation_gate(self.root, True))


class StatePrimitiveTests(unittest.TestCase):
    def test_artifact_boundary_rejects_secret_broad_and_key_paths(self):
        with ScratchDirectory() as folder:
            root = Path(folder)
            for value in (".env", "harness/secret/a.txt", "private.key", "../outside.txt"):
                with self.subTest(value=value), self.assertRaises(ws.WorkflowError):
                    ws.canonical_artifact(root, value)
            root.mkdir(exist_ok=True)
            with self.assertRaises(ws.WorkflowError):
                ws.canonical_artifact(root, ".")

    def test_artifact_boundary_checks_resolved_links_and_secret_metadata(self):
        with ScratchDirectory() as folder:
            root = Path(folder)
            secret = root / ".env"
            secret.write_text("VALUE=hidden\n", encoding="utf-8")
            alias = root / "alias.txt"
            try:
                alias.symlink_to(secret)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            with self.assertRaisesRegex(ws.WorkflowError, "resolves to a protected"):
                ws.artifact_revision(root, ["alias.txt"])
            private = root / "private.md"
            private.write_text("---\naccess: secret\n---\nprivate\n", encoding="utf-8")
            with self.assertRaisesRegex(ws.WorkflowError, "access is secret"):
                ws.artifact_revision(root, ["private.md"])

    def test_lock_never_expires_and_requires_confirmed_stop(self):
        with ScratchDirectory() as folder:
            path = Path(folder) / "writer.lock"
            lock = ws.ExclusiveLock(path, {"run_id": "one"})
            lock.acquire()
            with self.assertRaisesRegex(ws.WorkflowError, "already held"):
                ws.ExclusiveLock(path, {"run_id": "two"}).acquire()
            with self.assertRaisesRegex(ws.WorkflowError, "confirmed stopped"):
                lock.release(process_stopped=False)
            self.assertTrue(path.exists())
            lock.release(process_stopped=True)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
