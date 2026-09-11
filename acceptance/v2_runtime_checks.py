"""V2 runtime acceptance using isolated data and synthetic CLI fixtures only.

This suite exercises the LFX runtime boundary: recursive compilation, durable
human pauses, transport preservation, snapshots, grants, and restart safety.
It never invokes a real model provider or touches the default kxy data root.
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_ROOT = Path(tempfile.mkdtemp(prefix="kxy-v2-runtime-"))
os.environ["KXY_DATA_ROOT"] = str(TEST_ROOT / "data")
os.environ["LANGFLOW_CONFIG_DIR"] = str(TEST_ROOT / "lfx")
os.environ["DO_NOT_TRACK"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import app as core  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def node(identifier: str, kind: str, **data):
    return {
        "id": identifier,
        "type": kind,
        "position": {"x": 0, "y": 0},
        "data": data,
    }


def edge(source: str, target: str, handle: str = "result"):
    return {
        "id": f"{source}-{handle}-{target}",
        "source": source,
        "target": target,
        "sourceHandle": handle,
        "targetHandle": "items",
    }


def workflow(nodes, edges, name="V2 runtime fixture"):
    return {
        "version": "kxy.workflow.v1",
        "name": name,
        "nodes": nodes,
        "edges": edges,
        "settings": {},
    }


def passthrough_child(with_human: bool = False):
    nodes = [node("entry", "subflow_input"), node("exit", "subflow_output")]
    edges = [edge("entry", "exit")]
    if with_human:
        nodes.insert(1, node("review", "human", content="请核对 SYNTHETIC_REVIEW"))
        edges = [edge("entry", "review"), edge("review", "exit")]
    return workflow(nodes, edges, "synthetic child")


class RuntimeV2Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(core.app)
        cls.client = cls.context.__enter__()
        cls.fixture = TEST_ROOT / "fixture-cli"
        cls.fixture.write_text(
            "#!/usr/bin/env python3\n"
            """import json
import os
import pathlib
import sys

args = sys.argv
if '--version' in args:
    print('synthetic-kxy-fixture 2')
    raise SystemExit(0)
prompt = args[-1]
if 'STRUCTURED_FIXTURE' in prompt:
    text = json.dumps({'route': 'close', 'evidence': [{'source': 'synthetic-fixture', 'locator': 'fixture:1'}], 'marker': 'STRUCTURED_MARKER'}, ensure_ascii=False)
else:
    text = 'SYNTHETIC_OUTPUT ' + pathlib.Path('input-context.json').read_text(encoding='utf-8')
pathlib.Path('outputs/report.txt').write_text(text, encoding='utf-8')
if '--output-last-message' in args:
    pathlib.Path(args[args.index('--output-last-message') + 1]).write_text(text, encoding='utf-8')
echoed = text
env_token = os.environ.get('SYNTHETIC_AUTH_TOKEN')
if 'ECHO_ENV_TOKEN' in prompt and env_token:
    echoed += ' SYNTHETIC_AUTH_TOKEN=' + env_token
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': echoed}}, ensure_ascii=False))
""",
            encoding="utf-8",
        )
        cls.fixture.chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)
        print("Isolated V2 runtime evidence:", TEST_ROOT)

    def submit(self, document):
        response = self.client.post("/api/runs", json={"workflow": document})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def read_run(self, identifier):
        response = self.client.get(f"/api/runs/{identifier}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def wait_for(self, identifier, states, timeout=25):
        deadline = time.monotonic() + timeout
        latest = None
        while time.monotonic() < deadline:
            latest = self.read_run(identifier)
            if latest["status"] in states:
                return latest
            time.sleep(0.05)
        self.fail(f"run {identifier} did not reach {states}: {latest}")

    def wait_terminal(self, identifier, timeout=25):
        return self.wait_for(identifier, {"succeeded", "failed", "rejected", "cancelled", "interrupted"}, timeout)

    def fixture_env(self):
        return patch.dict(os.environ, {"KXY_CODEX_BIN": str(self.fixture)}, clear=False)

    def test_env_secret_is_redacted_from_logs_and_output(self):
        token = "SYNTHETIC-ENV-TOKEN-NOT-FOR-OUTPUT"
        original_prepare = core.prepare_headless_environment

        def prepare_with_fixture_token(*args, **kwargs):
            env = original_prepare(*args, **kwargs)
            env["SYNTHETIC_AUTH_TOKEN"] = token
            return env

        document = workflow(
            [
                node("source", "text", text="SYNTHETIC_ENV_TOKEN"),
                node("analysis", "analyzer", cli="codex", model="fixture", prompt="ECHO_ENV_TOKEN", timeout=5),
                node("out", "container"),
            ],
            [edge("source", "analysis"), edge("analysis", "out")],
        )
        with self.fixture_env(), patch.object(core, "prepare_headless_environment", side_effect=prepare_with_fixture_token):
            finished = self.wait_for(self.submit(document), {"succeeded"})

        serialized = json.dumps(finished, ensure_ascii=False)
        self.assertNotIn(token, serialized)
        self.assertIn("SYNTHETIC_AUTH_TOKEN=[REDACTED]", serialized)
        workspace = Path(finished["run_dir"]) / "workspace"
        for path in workspace.rglob("*"):
            if path.is_file():
                self.assertNotIn(token, path.read_text(encoding="utf-8", errors="replace"))

    def test_validation_rejects_bad_boundary_depth_and_expansion(self):
        invalid_boundary = workflow(
            [node("entry", "subflow_input"), node("entry2", "subflow_input"), node("exit", "subflow_output")],
            [edge("entry", "exit")],
        )
        response = self.client.post(
            "/api/workflows/validate",
            json=workflow([node("box", "blackbox", workflow=invalid_boundary)], []),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["ok"])
        self.assertTrue(any("exactly one" in item for item in response.json()["errors"]))

        def deep_child(level):
            if level == 0:
                return passthrough_child()
            child = deep_child(level - 1)
            return workflow(
                [node("entry", "subflow_input"), node("inner", "blackbox", workflow=child), node("exit", "subflow_output")],
                [edge("entry", "inner"), edge("inner", "exit")],
            )

        too_deep = workflow([node("box", "blackbox", workflow=deep_child(core.MAX_WORKFLOW_DEPTH + 1))], [])
        self.assertFalse(core.validate_workflow(too_deep)["ok"])
        oversized = workflow(
            [node(f"n{index}", "text", text="synthetic") for index in range(core.MAX_EXPANDED_NODES + 1)],
            [],
        )
        result = core.validate_workflow(oversized)
        self.assertFalse(result["ok"])
        self.assertGreater(result["expanded_nodes"], core.MAX_EXPANDED_NODES)

    def test_structured_payload_survives_analyzer_human_and_container(self):
        document = workflow(
            [
                node("source", "text", text="SYNTHETIC_INPUT"),
                node("analysis", "analyzer", cli="codex", model="fixture", prompt="STRUCTURED_FIXTURE", expect_json=True, timeout=5),
                node("review", "human", content="Inspect STRUCTURED_MARKER", confirm_label="确认这条证据"),
                node("out", "container"),
            ],
            [edge("source", "analysis"), edge("analysis", "review"), edge("review", "out")],
        )
        with self.fixture_env():
            identifier = self.submit(document)
            pending = self.wait_for(identifier, {"waiting"})
        self.assertEqual(len(pending["approvals"]), 1)
        approval = pending["approvals"][0]
        self.assertIn("STRUCTURED_MARKER", json.dumps(approval, ensure_ascii=False))
        self.assertEqual(approval["confirm_label"], "确认这条证据")
        self.assertEqual(
            self.client.post(
                f"/api/runs/{identifier}/approvals/{approval['node_id']}",
                json={"decision": "approve", "note": "synthetic approval"},
            ).status_code,
            200,
        )
        finished = self.wait_for(identifier, {"succeeded"})
        output = next(item for item in finished["nodes"] if item["node_id"] == "out")["output"]
        self.assertEqual(output["items"][0]["structured"]["route"], "close")
        self.assertEqual(output["items"][0]["structured"]["marker"], "STRUCTURED_MARKER")
        self.assertEqual(output["items"][0]["approval"]["decision"], "approve")
        self.assertEqual(
            self.client.post(
                f"/api/runs/{identifier}/approvals/{approval['node_id']}",
                json={"decision": "approve"},
            ).status_code,
            409,
        )

    def test_reject_and_cancel_close_the_breakpoint_without_output_manifest(self):
        document = workflow(
            [node("source", "text", text="SYNTHETIC_REVIEW"), node("review", "human", content="stop"), node("out", "container")],
            [edge("source", "review"), edge("review", "out")],
        )
        with self.subTest(decision="reject"):
            identifier = self.submit(document)
            pending = self.wait_for(identifier, {"waiting"})
            approval = pending["approvals"][0]
            response = self.client.post(
                f"/api/runs/{identifier}/approvals/{approval['node_id']}",
                json={"decision": "reject", "note": "SYNTHETIC_REJECT"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            stopped = self.wait_for(identifier, {"rejected"})
            self.assertIsNone(stopped["output_manifest"])
            self.assertEqual(stopped["approvals"][0]["status"], "rejected")
            self.assertNotEqual(next(item for item in stopped["nodes"] if item["node_id"] == "out")["status"], "succeeded")

        with self.subTest(decision="cancel"):
            identifier = self.submit(document)
            pending = self.wait_for(identifier, {"waiting"})
            response = self.client.post(f"/api/runs/{identifier}/cancel")
            self.assertEqual(response.status_code, 200, response.text)
            stopped = self.wait_for(identifier, {"cancelled"})
            self.assertIsNone(stopped["output_manifest"])
            self.assertEqual(stopped["approvals"][0]["status"], "cancelled")
            self.assertNotEqual(next(item for item in stopped["nodes"] if item["node_id"] == "out")["status"], "succeeded")

    def test_restart_marks_waiting_human_and_approval_interrupted(self):
        document = workflow(
            [node("source", "text", text="SYNTHETIC_RESTART"), node("review", "human", content="wait"), node("out", "container")],
            [edge("source", "review"), edge("review", "out")],
        )
        identifier = self.submit(document)
        self.wait_for(identifier, {"waiting"})
        core.init_db()
        interrupted = self.read_run(identifier)
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertEqual(interrupted["approvals"][0]["status"], "interrupted")
        statuses = {item["node_id"]: item["status"] for item in interrupted["nodes"]}
        self.assertEqual(statuses["source"], "succeeded")
        self.assertEqual(statuses["review"], "interrupted")
        self.assertEqual(statuses["out"], "interrupted")

    def test_condition_excludes_human_without_creating_approval(self):
        document = workflow(
            [
                node("source", "text", text="ACTIVE_SOURCE"),
                node("route", "condition", field="status", operator="equals", expected="source"),
                node("yes", "container"),
                node("no-review", "human", content="must not pause"),
                node("no-out", "container"),
            ],
            [edge("source", "route"), edge("route", "yes", "true"), edge("route", "no-review", "false"), edge("no-review", "no-out")],
        )
        finished = self.wait_terminal(self.submit(document))
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual(finished["approvals"], [])
        review = next(item for item in finished["nodes"] if item["node_id"] == "no-review")
        self.assertEqual(review["status"], "skipped")

    def test_recursive_blackbox_compilation_and_nested_output(self):
        deepest = workflow(
            [node("entry", "subflow_input"), node("analysis", "analyzer", cli="codex", model="fixture", prompt="DEEP_BOX", timeout=5), node("exit", "subflow_output")],
            [edge("entry", "analysis"), edge("analysis", "exit")],
            "deepest",
        )
        middle = workflow(
            [node("entry", "subflow_input"), node("innerbox", "blackbox", workflow=deepest), node("exit", "subflow_output")],
            [edge("entry", "innerbox"), edge("innerbox", "exit")],
            "middle",
        )
        document = workflow(
            [node("source", "text", text="NESTED_PAYLOAD_837"), node("box", "blackbox", workflow=middle), node("out", "container")],
            [edge("source", "box"), edge("box", "out")],
        )
        with self.fixture_env():
            finished = self.wait_for(self.submit(document), {"succeeded"})
        self.assertIn("NESTED_PAYLOAD_837", json.dumps(finished["nodes"], ensure_ascii=False))
        paths = {item["node_path"]: item["status"] for item in finished["nodes"]}
        self.assertEqual(paths["box"], "succeeded")
        self.assertEqual(paths["box/innerbox/analysis"], "succeeded")
        self.assertEqual(finished["snapshot"]["compiled"]["blackboxes"]["box/innerbox"]["depth"], 1)

    def test_internal_file_gate_runs_only_for_active_blackbox(self):
        uploaded = self.client.post(
            "/api/files",
            files={"file": ("内部资料-仅fixture.md", b"INNER_FILE_SNAPSHOT_524", "text/markdown")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        file_id = uploaded.json()["id"]
        child = workflow(
            [
                node("entry", "subflow_input"),
                node("attachment", "file", file_id=file_id),
                node("merge", "container"),
                node("review", "human", content="internal review"),
                node("exit", "subflow_output"),
            ],
            [edge("entry", "merge"), edge("attachment", "merge"), edge("merge", "review"), edge("review", "exit")],
            "internal file child",
        )
        active = workflow([node("box", "blackbox", workflow=child)], [], "active internal source")
        identifier = self.submit(active)
        pending = self.wait_for(identifier, {"waiting"})
        self.assertIn(file_id, pending["snapshot"]["sources"])
        self.assertIn("INNER_FILE_SNAPSHOT_524", json.dumps(pending["approvals"], ensure_ascii=False))
        approval = pending["approvals"][0]
        self.assertEqual(self.client.post(f"/api/runs/{identifier}/approvals/{approval['node_id']}", json={"decision": "approve"}).status_code, 200)
        self.assertEqual(self.wait_for(identifier, {"succeeded"})["status"], "succeeded")

        inactive = workflow(
            [
                node("source", "text", text="route away"),
                node("route", "condition", field="status", operator="equals", expected="source"),
                node("yes", "container"),
                node("box", "blackbox", workflow=child),
            ],
            [edge("source", "route"), edge("route", "yes", "true"), edge("route", "box", "false")],
            "inactive internal source",
        )
        with self.fixture_env():
            finished = self.wait_for(self.submit(inactive), {"succeeded"})
        self.assertEqual(finished["approvals"], [])
        inner_review = next(item for item in finished["nodes"] if item["node_path"] == "box/review")
        self.assertEqual(inner_review["status"], "skipped")

    def test_nested_human_approval_is_operable_by_original_path(self):
        document = workflow(
            [node("source", "text", text="BOX_REVIEW_294"), node("box", "blackbox", workflow=passthrough_child(True)), node("out", "container")],
            [edge("source", "box"), edge("box", "out")],
        )
        identifier = self.submit(document)
        pending = self.wait_for(identifier, {"waiting"})
        self.assertEqual(len(pending["approvals"]), 1)
        approval = pending["approvals"][0]
        self.assertEqual(approval["node_id"], "box/review")
        self.assertIn("BOX_REVIEW_294", json.dumps(approval, ensure_ascii=False))
        self.assertEqual(self.client.post(f"/api/runs/{identifier}/approvals/{approval['node_id']}", json={"decision": "approve"}).status_code, 200)
        finished = self.wait_for(identifier, {"succeeded"})
        self.assertIn("BOX_REVIEW_294", json.dumps(finished["nodes"], ensure_ascii=False))
        self.assertEqual(next(item for item in finished["nodes"] if item["node_path"] == "box")["status"], "succeeded")

    def test_nested_grant_snapshot_and_export(self):
        grant_root = TEST_ROOT / "nested-grant"
        grant_root.mkdir(exist_ok=True)
        grant_response = self.client.post("/api/grants", json={"path": str(grant_root)})
        self.assertEqual(grant_response.status_code, 200, grant_response.text)
        grant_id = grant_response.json()["id"]
        child = workflow(
            [node("entry", "subflow_input"), node("save", "container", grant_id=grant_id), node("exit", "subflow_output")],
            [edge("entry", "save"), edge("save", "exit")],
            "grant child",
        )
        finished = self.wait_for(self.submit(workflow([node("box", "blackbox", workflow=child)], [], "nested grant")), {"succeeded"})
        grant_snapshot = [item for item in finished["snapshot"]["grants"] if item["node_path"] == "box/save"]
        self.assertEqual(len(grant_snapshot), 1)
        self.assertEqual(grant_snapshot[0]["id"], grant_id)
        saved = [item for item in finished["output_manifest"]["granted_outputs"] if item["node_id"] == "box/save"]
        self.assertEqual(len(saved), 1)
        self.assertTrue((Path(saved[0]["path"]) / "result.json").is_file())
        self.assertTrue(Path(saved[0]["path"]).is_relative_to(grant_root.resolve()))

    def test_nested_skill_snapshot_survives_library_deletion(self):
        source = TEST_ROOT / "nested-skill"
        source.mkdir(exist_ok=True)
        (source / "SKILL.md").write_text(
            "---\nname: nested-fixture\ndescription: synthetic nested skill\n---\n\nUse only fixture evidence.\n",
            encoding="utf-8",
        )
        imported = self.client.post("/api/skills/import-path", json={"path": str(source)})
        self.assertEqual(imported.status_code, 200, imported.text)
        skill_id = imported.json()["id"]
        child = workflow(
            [
                node("entry", "subflow_input"),
                node("analysis", "analyzer", cli="codex", model="fixture", prompt="NESTED_SKILL", skill_ids=[skill_id], timeout=5),
                node("exit", "subflow_output"),
            ],
            [edge("entry", "analysis"), edge("analysis", "exit")],
            "skill child",
        )
        document = workflow(
            [node("source", "text", text="SKILL_INPUT"), node("box", "blackbox", workflow=child), node("out", "container")],
            [edge("source", "box"), edge("box", "out")],
            "nested skill snapshot",
        )
        with patch.object(core, "start_background_run"):
            identifier = self.submit(document)
        self.assertEqual(self.client.delete(f"/api/skills/{skill_id}").status_code, 200)
        core.RUN_CANCEL_EVENTS[identifier] = threading.Event()
        with self.fixture_env():
            core.run_workflow(identifier)
        finished = self.wait_terminal(identifier)
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertEqual(len(finished["snapshot"]["skills"]), 1)
        self.assertEqual(finished["snapshot"]["skills"][0]["id"], skill_id)

    def test_nested_model_binding_is_frozen_before_human_pause(self):
        model_response = self.client.post(
            "/api/agent-models",
            json={"cli_id": "codex", "model": "synthetic-bound-model", "alias": "Synthetic bound", "source": "manual", "efforts": ["low"], "default_effort": "low"},
        )
        self.assertEqual(model_response.status_code, 200, model_response.text)
        model_id = model_response.json()["id"]
        child = workflow(
            [
                node("entry", "subflow_input"),
                node("review", "human", content="freeze model"),
                node("analysis", "analyzer", cli="codex", model_ref=model_id, effort="low", prompt="FROZEN_MODEL", timeout=5),
                node("exit", "subflow_output"),
            ],
            [edge("entry", "review"), edge("review", "analysis"), edge("analysis", "exit")],
            "model child",
        )
        document = workflow(
            [node("source", "text", text="MODEL_INPUT"), node("box", "blackbox", workflow=child), node("out", "container")],
            [edge("source", "box"), edge("box", "out")],
            "frozen model",
        )
        with self.fixture_env():
            identifier = self.submit(document)
            pending = self.wait_for(identifier, {"waiting"})
        self.assertEqual(self.client.delete(f"/api/agent-models/{model_id}").status_code, 200)
        analyzer = next(item for item in pending["snapshot"]["workflow"]["nodes"][1]["data"]["workflow"]["nodes"] if item["id"] == "analysis")
        self.assertEqual(analyzer["data"]["resolved_model"]["model"], "synthetic-bound-model")
        approval = pending["approvals"][0]
        self.assertEqual(self.client.post(f"/api/runs/{identifier}/approvals/{approval['node_id']}", json={"decision": "approve"}).status_code, 200)
        with self.fixture_env():
            finished = self.wait_for(identifier, {"succeeded"})
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertIn("synthetic-bound-model", json.dumps(finished["nodes"], ensure_ascii=False))

    def test_long_chinese_display_name_uses_short_run_storage_path(self):
        name = ("长文件名中文资料-" * 35) + ".md"
        response = self.client.post("/api/files", files={"file": (name, b"LONG_NAME_SYNTHETIC", "text/markdown")})
        self.assertEqual(response.status_code, 200, response.text)
        asset = response.json()
        self.assertEqual(asset["display_name"], name)
        with core.connect_db() as db:
            row = db.execute("SELECT stored_path FROM files WHERE id=?", (asset["id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertLess(len(Path(row["stored_path"]).name), 100)
        self.assertNotEqual(Path(row["stored_path"]).name, name)
        document = workflow([node("source", "file", file_id=asset["id"]), node("out", "container")], [edge("source", "out")])
        finished = self.wait_for(self.submit(document), {"succeeded"})
        self.assertIn("LONG_NAME_SYNTHETIC", json.dumps(finished["output_manifest"], ensure_ascii=False))
        self.assertLess(len(Path(finished["snapshot"]["sources"][asset["id"]]["file_path"]).name), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
