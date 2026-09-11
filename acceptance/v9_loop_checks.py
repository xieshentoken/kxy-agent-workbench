"""Focused V9 loop acceptance: isolated API/LFX and synthetic execution only.

The first case exercises the real subprocess path with a local synthetic CLI.
The remaining cases keep the execution deterministic so that loop persistence,
pause/continue, retry isolation, fail-closed review parsing, grant boundaries,
and ordinary V8 resume behavior stay easy to diagnose.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(tempfile.mkdtemp(prefix="kxy-v9-loop-checks-"))
os.environ.update(
    KXY_DATA_ROOT=str(ROOT / "data"),
    LANGFLOW_CONFIG_DIR=str(ROOT / "lfx"),
    DO_NOT_TRACK="true",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend import app as core


def node(identifier: str, kind: str, **data: object) -> dict[str, object]:
    values = {"label": identifier, **data}
    return {
        "id": identifier,
        "type": kind,
        "position": {"x": 0, "y": 0},
        "data": values,
    }


def edge(source: str, target: str, handle: str = "result") -> dict[str, str]:
    return {
        "id": f"{source}-{handle}-{target}",
        "source": source,
        "target": target,
        "sourceHandle": handle,
        "targetHandle": "items",
    }


def flow(nodes: list[dict[str, object]], edges: list[dict[str, str]], name: str = "V9 synthetic") -> dict[str, object]:
    return {"version": "kxy.workflow.v1", "name": name, "nodes": nodes, "edges": edges}


def loop_document(
    executor_prompt: str,
    reviewer_prompt: str,
    *,
    max_rounds: int = 3,
    budget_seconds: int = 120,
    grant_id: str = "",
) -> dict[str, object]:
    nested = flow(
        [
            node("entry", "subflow_input"),
            node("executor", "analyzer", cli="codex", prompt=executor_prompt, output_format="auto"),
            node(
                "reviewer",
                "analyzer",
                cli="codex",
                prompt=reviewer_prompt,
                output_format="json",
                expect_json=True,
            ),
            node("exit", "subflow_output"),
        ],
        [edge("entry", "executor"), edge("executor", "reviewer"), edge("reviewer", "exit")],
        name="V9 bounded inner workflow",
    )
    config = {
        "enabled": True,
        "executor_id": "executor",
        "reviewer_id": "reviewer",
        "goal": "V9 synthetic goal: preserve a traceable result",
        "input_field": "text",
        "review_fields": {"passed": "passed", "issues": "issues", "next_action": "next_action"},
        "feedback": {
            "latest_result": True,
            "issues": True,
            "next_action": True,
            "history_summary": True,
        },
        "max_rounds": max_rounds,
        "active_budget_seconds": budget_seconds,
        "previous_summary_chars": 1200,
    }
    return flow(
        [
            node("source", "text", text="synthetic research input"),
            node("box", "blackbox", workflow=nested, loop=config),
            node(
                "out",
                "container",
                grant_id=grant_id,
                export_formats=["text"] if grant_id else [],
                allowed_file_extensions=[".txt"] if grant_id else [],
                json_mode="full",
            ),
        ],
        [edge("source", "box"), edge("box", "out")],
        name="V9 bounded loop workflow",
    )


def ordinary_document() -> dict[str, object]:
    return flow(
        [
            node("source", "text", text="ordinary V8 input"),
            node("a", "analyzer", cli="codex", prompt="V9 ordinary success"),
            node("b", "analyzer", cli="codex", prompt="V9 ordinary fail once"),
            node("out", "container", export_formats=[], allowed_file_extensions=[]),
        ],
        [edge("source", "a"), edge("a", "b"), edge("b", "out")],
        name="V8 compatibility workflow",
    )


class V9LoopChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = TestClient(core.app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.context.__exit__(None, None, None)

    def setUp(self) -> None:
        self.calls: dict[tuple[str, int, str], int] = {}
        self.execute_patch = patch.object(core, "execute_cli", side_effect=self.execute)
        self.execute_patch.start()
        self.addCleanup(self.execute_patch.stop)
        self.probe_patch = patch.object(
            core,
            "probe_cli",
            side_effect=lambda name: {
                "name": name,
                "available": True,
                "status": "READY",
                "version": "V9 synthetic",
            },
        )
        self.probe_patch.start()
        self.addCleanup(self.probe_patch.stop)

    def total_calls(self, run_id: str, component_id: str) -> int:
        return sum(count for (current_run, _attempt, current_component), count in self.calls.items() if current_run == run_id and current_component == component_id)

    def execute(self, state: object, prompt: str, payloads: list[dict[str, object]], component: object) -> dict[str, object]:
        run_id = str(getattr(state, "run_id"))
        attempt_no = int(getattr(state, "attempt_no"))
        component_id = str(component.get_id())
        key = (run_id, attempt_no, component_id)
        self.calls[key] = self.calls.get(key, 0) + 1
        round_no = int(getattr(state, "loop_round_no") or 0)

        if round_no and prompt.startswith("V9_REVIEW"):
            context_items = [item for item in payloads if item.get("status") == "loop_round_context"]
            if not context_items:
                raise RuntimeError("synthetic reviewer did not receive loop context")
            context = context_items[0].get("round_context")
            if not isinstance(context, dict) or context.get("original_goal") != "V9 synthetic goal: preserve a traceable result":
                raise RuntimeError("synthetic reviewer received incomplete loop context")
            if prompt == "V9_REVIEW_FALSE_UNTIL_2":
                passed = round_no >= 2
            elif prompt == "V9_REVIEW_FALSE_THEN_FAIL_ROUND2":
                if round_no == 1:
                    passed = False
                elif self.total_calls(run_id, component_id) == 1:
                    raise RuntimeError("synthetic reviewer interruption")
                else:
                    passed = True
            elif prompt == "V9_REVIEW_ALWAYS_FALSE":
                passed = False
            elif prompt == "V9_REVIEW_MALFORMED":
                return {"text": "not valid reviewer JSON", "content": "not valid reviewer JSON", "artifacts": []}
            else:
                passed = True
            review = {
                "passed": passed,
                "issues": [] if passed else ["synthetic issue"],
                "next_action": "finish" if passed else "run another bounded round",
            }
            return {"text": json.dumps(review), "content": review, "structured": review, "artifacts": []}

        if round_no and prompt == "V9_EXECUTOR_INTERRUPT" and self.total_calls(run_id, component_id) == 1:
            target = state.active_node_workspace_root / component_id / "outputs" / "partial.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("partial round must not be reused", encoding="utf-8")
            raise RuntimeError("synthetic executor interruption")

        if round_no and prompt == "V9_EXECUTOR_BUDGET":
            time.sleep(1.2)
            return {"text": f"synthetic slow executor result round {round_no}", "artifacts": []}

        if round_no and prompt in {"V9_EXECUTOR_ARTIFACT", "V9_EXECUTOR_INTERRUPT"}:
            target = (
                state.active_node_workspace_root
                / component_id
                / "outputs"
                / f"synthetic-round-{round_no}.txt"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"synthetic executor artifact round {round_no}", encoding="utf-8")
            content = target.read_bytes()
            return {
                "text": f"synthetic executor result round {round_no}",
                "artifacts": [
                    {
                        "name": target.name,
                        "path": str(target.relative_to(state.workspace)),
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }

        if not round_no and prompt == "V9 ordinary fail once" and self.total_calls(run_id, component_id) == 1:
            raise RuntimeError("synthetic ordinary failure")
        return {"text": prompt, "content": {"route": "synthetic"}, "artifacts": []}

    def wait(self, run_id: str, states: tuple[str, ...] = ("succeeded", "failed", "interrupted", "rejected", "cancelled")) -> dict[str, object]:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = self.client.get(f"/api/runs/{run_id}")
            self.assertEqual(response.status_code, 200, response.text)
            payload = response.json()
            status = payload["status"]
            if status in states and (status == "waiting" or run_id not in core.RUN_CANCEL_EVENTS):
                return payload
            if status == "waiting" and "waiting" in states:
                return payload
            time.sleep(0.03)
        self.fail(f"run did not settle: {run_id}")

    def start(self, document: dict[str, object]) -> str:
        response = self.client.post("/api/runs", json={"workflow": document})
        self.assertEqual(response.status_code, 200, response.text)
        return str(response.json()["id"])

    def resume(self, run_id: str) -> dict[str, object]:
        response = self.client.post(f"/api/runs/{run_id}/resume", json={})
        self.assertEqual(response.status_code, 200, response.text)
        return self.wait(run_id)

    def test_01_real_subprocess_two_rounds_and_artifact_handoff(self) -> None:
        self.execute_patch.stop()
        script = ROOT / "synthetic-v9-codex"
        script.write_text(
            """#!/usr/bin/env python3
import json
import pathlib
import sys

if "--version" in sys.argv:
    print("V9 synthetic subprocess")
    raise SystemExit(0)

prompt = sys.argv[-1]
context = json.loads(pathlib.Path("input-context.json").read_text())

def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

all_values = list(walk(context))
round_no = next((item["round"] for item in all_values if isinstance(item.get("round"), int)), 1)
if "V9_REVIEW_SUBPROCESS" in prompt:
    contexts = [item for item in all_values if item.get("status") == "loop_round_context"]
    assert contexts and contexts[0]["round_context"]["original_goal"]
    artifacts = [artifact for item in all_values for artifact in (item.get("artifacts") or []) if isinstance(artifact, dict)]
    assert artifacts, "reviewer did not receive executor artifact metadata"
    assert pathlib.Path(artifacts[0]["path"]).read_text() == f"synthetic executor artifact round {round_no}"
    output = json.dumps({"passed": round_no >= 2, "issues": [] if round_no >= 2 else ["continue"], "next_action": "finish" if round_no >= 2 else "retry"})
else:
    pathlib.Path("outputs", "nested").mkdir(parents=True, exist_ok=True)
    pathlib.Path("outputs", "nested", f"proof-round-{round_no}.txt").write_text(f"synthetic executor artifact round {round_no}")
    output = f"synthetic executor result round {round_no}"

message = pathlib.Path(sys.argv[sys.argv.index("--output-last-message") + 1])
message.write_text(output)
print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": output}}))
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        with patch.dict(os.environ, {"KXY_CODEX_BIN": str(script)}), patch.object(
            core,
            "prepare_headless_environment",
            side_effect=lambda agent, workspace, **kwargs: {"PATH": os.environ["PATH"], "HOME": str(workspace)},
        ):
            run_id = self.start(loop_document("V9_EXECUTOR_SUBPROCESS", "V9_REVIEW_SUBPROCESS", max_rounds=2))
            result = self.wait(run_id)
        self.assertEqual(result["status"], "succeeded", result.get("error"))
        rounds = result["loop_rounds"]
        self.assertEqual([(item["round_no"], item["status"]) for item in rounds], [(1, "reviewed"), (2, "succeeded")])
        reviewer_input = rounds[0]["reviewer_input"]
        self.assertTrue(any(item.get("status") == "loop_round_context" for item in reviewer_input))
        self.assertTrue(any(item.get("artifacts") for item in reviewer_input))
        artifacts = result["output_manifest"]["artifacts"]
        self.assertTrue(any("proof-round-2.txt" in item["path"] for item in artifacts))
        for artifact in artifacts:
            fetched = self.client.get(artifact["url"])
            self.assertEqual(fetched.status_code, 200, fetched.text)
            self.assertEqual(hashlib.sha256(fetched.content).hexdigest(), artifact["sha256"])

    def test_02_round_limit_pauses_until_explicit_continue(self) -> None:
        run_id = self.start(loop_document("V9_EXECUTOR_ARTIFACT", "V9_REVIEW_FALSE_UNTIL_2", max_rounds=1))
        paused = self.wait(run_id, ("waiting",))
        self.assertIsNone(paused["output_manifest"])
        self.assertEqual(
            [(item["round_no"], item["status"]) for item in paused["loop_rounds"]],
            [(1, "reviewed"), (2, "round_limit_waiting")],
        )
        response = self.client.post(
            f"/api/runs/{run_id}/loops/box/continue",
            json={"additional_rounds": 1, "additional_seconds": 30},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = self.wait(run_id)
        self.assertEqual(result["status"], "succeeded", result.get("error"))
        self.assertEqual([(item["round_no"], item["status"]) for item in result["loop_rounds"]], [(1, "reviewed"), (2, "succeeded")])
        self.assertEqual(result["loop_rounds"][-1]["effective_max_rounds"], 2)

    def test_03_failed_reviewer_reuses_prior_round_and_executor_checkpoint(self) -> None:
        run_id = self.start(loop_document("V9_EXECUTOR_ARTIFACT", "V9_REVIEW_FALSE_THEN_FAIL_ROUND2", max_rounds=2))
        first = self.wait(run_id)
        self.assertEqual(first["status"], "failed")
        scope1 = core.loop_scope_id("box", 1)
        scope2 = core.loop_scope_id("box", 2)
        executor1 = core.scoped_component_id(scope1, "executor")
        executor2 = core.scoped_component_id(scope2, "executor")
        reviewer1 = core.scoped_component_id(scope1, "reviewer")
        reviewer2 = core.scoped_component_id(scope2, "reviewer")
        self.assertEqual(self.total_calls(run_id, executor1), 1)
        self.assertEqual(self.total_calls(run_id, reviewer1), 1)
        self.assertEqual(self.total_calls(run_id, executor2), 1)
        self.assertEqual(self.total_calls(run_id, reviewer2), 1)
        first_artifact = core.RUNS_ROOT / run_id / "workspace" / "nodes" / "loops" / scope1 / executor1 / "outputs" / "synthetic-round-1.txt"
        second_artifact = core.RUNS_ROOT / run_id / "workspace" / "nodes" / "loops" / scope2 / executor2 / "outputs" / "synthetic-round-2.txt"
        self.assertTrue(first_artifact.is_file())
        self.assertTrue(second_artifact.is_file())
        self.assertNotEqual(first_artifact.parent, second_artifact.parent)
        result = self.resume(run_id)
        self.assertEqual(result["status"], "succeeded", result.get("error"))
        self.assertEqual(self.total_calls(run_id, executor1), 1)
        self.assertEqual(self.total_calls(run_id, reviewer1), 1)
        self.assertEqual(self.total_calls(run_id, executor2), 1)
        self.assertEqual(self.total_calls(run_id, reviewer2), 2)
        rounds = {(item["attempt_no"], item["round_no"]): item["status"] for item in result["loop_rounds"]}
        self.assertEqual(rounds[(1, 1)], "reviewed")
        self.assertEqual(rounds[(1, 2)], "failed")
        self.assertEqual(rounds[(2, 1)], "reused")
        self.assertEqual(rounds[(2, 2)], "succeeded")

    def test_04_malformed_review_fails_closed_and_grant_is_final_only(self) -> None:
        malformed_id = self.start(loop_document("V9_EXECUTOR_ARTIFACT", "V9_REVIEW_MALFORMED", max_rounds=1))
        malformed = self.wait(malformed_id)
        self.assertEqual(malformed["status"], "failed")
        self.assertEqual(malformed["loop_rounds"][0]["status"], "failed")
        self.assertIsNone(malformed["output_manifest"])

        grant_folder = ROOT / "authorized-output-after-revoke"
        grant_folder.mkdir(exist_ok=True)
        grant_response = self.client.post("/api/grants", json={"path": str(grant_folder)})
        self.assertEqual(grant_response.status_code, 200, grant_response.text)
        grant_id = grant_response.json()["id"]
        run_id = self.start(loop_document("V9_EXECUTOR_ARTIFACT", "V9_REVIEW_FALSE_UNTIL_2", max_rounds=1, grant_id=grant_id))
        paused = self.wait(run_id, ("waiting",))
        self.assertEqual(paused["loop_rounds"][0]["status"], "reviewed")
        snapshot_loop = paused["snapshot"]["workflow"]["nodes"][1]["data"]["loop"]
        self.assertNotIn("reviewer_prompt", snapshot_loop)
        revoke_response = self.client.delete(f"/api/grants/{grant_id}")
        self.assertEqual(revoke_response.status_code, 200, revoke_response.text)
        continue_response = self.client.post(
            f"/api/runs/{run_id}/loops/box/continue",
            json={"additional_rounds": 1, "additional_seconds": 30},
        )
        self.assertEqual(continue_response.status_code, 200, continue_response.text)
        result = self.wait(run_id)
        self.assertEqual(result["status"], "failed")
        self.assertIn("授权", result.get("error") or "")
        self.assertIsNone(result["output_manifest"])
        destination_root = grant_folder / "kxy" / run_id
        self.assertFalse(destination_root.exists() and any(destination_root.rglob("*")))

    def test_05_ordinary_v8_resume_still_reuses_successful_nodes(self) -> None:
        run_id = self.start(ordinary_document())
        first = self.wait(run_id)
        self.assertEqual(first["status"], "failed")
        result = self.resume(run_id)
        self.assertEqual(result["status"], "succeeded", result.get("error"))
        self.assertEqual(sum(count for key, count in self.calls.items() if key[0] == run_id and key[2] == "a"), 1)
        self.assertEqual(sum(count for key, count in self.calls.items() if key[0] == run_id and key[2] == "b"), 2)
        self.assertEqual(len(result["attempts"]), 2)

    def test_06_active_budget_pauses_and_continuation_preserves_elapsed_time(self) -> None:
        run_id = self.start(loop_document("V9_EXECUTOR_BUDGET", "V9_REVIEW_PASS", max_rounds=3, budget_seconds=1))
        paused = self.wait(run_id, ("waiting",))
        self.assertEqual(paused["loop_rounds"][0]["status"], "budget_waiting")
        self.assertGreaterEqual(paused["loop_rounds"][0]["active_seconds"], 1.0)
        response = self.client.post(
            f"/api/runs/{run_id}/loops/box/continue",
            json={"additional_rounds": 0, "additional_seconds": 30},
        )
        self.assertEqual(response.status_code, 200, response.text)
        result = self.wait(run_id)
        self.assertEqual(result["status"], "succeeded", result.get("error"))
        round_row = result["loop_rounds"][0]
        self.assertEqual(round_row["status"], "succeeded")
        self.assertGreaterEqual(round_row["active_seconds"], 1.0)
        self.assertEqual(round_row["effective_max_rounds"], 3)
        self.assertGreaterEqual(round_row["budget_seconds"], 31.0)


if __name__ == "__main__":
    print(f"V9 isolated fixture data: {ROOT}")
    unittest.main(verbosity=2)
