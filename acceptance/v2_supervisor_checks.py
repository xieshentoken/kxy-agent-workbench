"""Parent-authored V2 acceptance against real LFX, isolated data, no model calls."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

TEMP = Path(tempfile.mkdtemp(prefix="kxy-v2-supervisor-"))
os.environ["KXY_DATA_ROOT"] = str(TEMP / "data")
os.environ["LANGFLOW_CONFIG_DIR"] = str(TEMP / "lfx")
os.environ["DO_NOT_TRACK"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as core
from fastapi.testclient import TestClient


def node(identifier, kind, **data):
    return {"id": identifier, "type": kind, "position": {"x": 0, "y": 0}, "data": data}


def edge(source, target, handle="result"):
    return {"id": f"{source}-{handle}-{target}", "source": source, "target": target,
            "sourceHandle": handle, "targetHandle": "items"}


def flow(nodes, edges):
    return {"version": "kxy.workflow.v1", "name": "V2 independent synthetic acceptance", "nodes": nodes, "edges": edges, "settings": {}}


def inner(human=False):
    nodes = [node("entry", "subflow_input"), node("exit", "subflow_output")]
    edges = [edge("entry", "exit")]
    if human:
        nodes.insert(1, node("review", "human", content="请核对 SYNTHETIC_REVIEW，不应自动继续。", confirm_label="确认继续"))
        edges = [edge("entry", "review"), edge("review", "exit")]
    return flow(nodes, edges)


class SupervisorV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(core.app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)
        print("Independent evidence data:", TEMP)

    def submit(self, workflow):
        response = self.client.post("/api/runs", json={"workflow": workflow})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def wait(self, identifier, states):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            run = self.client.get(f"/api/runs/{identifier}").json()
            if run["status"] in states:
                return run
            if run["status"] in {"failed", "cancelled", "rejected", "interrupted"}:
                self.fail(f"Unexpected terminal run: {run.get('status')} {run.get('error')}")
            time.sleep(0.08)
        self.fail(f"Timeout waiting for {states}; status={run['status']}")

    def decision(self, identifier, node_id, decision):
        return self.client.post(f"/api/runs/{identifier}/approvals/{node_id}",
                                json={"decision": decision, "note": "Independent acceptance only"})

    def test_human_is_real_breakpoint_and_single_use(self):
        workflow = flow([node("source", "text", text="SYNTHETIC_REVIEW"),
                         node("review", "human", content="Inspect this content"),
                         node("out", "container")], [edge("source", "review"), edge("review", "out")])
        identifier = self.submit(workflow)
        first = self.wait(identifier, {"waiting"})
        time.sleep(0.3)
        refreshed = self.client.get(f"/api/runs/{identifier}").json()
        self.assertEqual(refreshed["status"], "waiting")
        self.assertNotEqual(next(n for n in refreshed["nodes"] if n["node_id"] == "out")["status"], "succeeded")
        approval = refreshed["approvals"][0]
        self.assertIn("Inspect this content", json.dumps(approval, ensure_ascii=False))
        self.assertIn("SYNTHETIC_REVIEW", json.dumps(approval, ensure_ascii=False))
        self.assertEqual(self.decision(identifier, approval["node_id"], "approve").status_code, 200)
        finished = self.wait(identifier, {"succeeded"})
        self.assertIn("SYNTHETIC_REVIEW", json.dumps(finished["output_manifest"]))
        self.assertEqual(self.decision(identifier, approval["node_id"], "approve").status_code, 409)
        self.assertEqual(first["snapshot"]["workflow"]["nodes"][1]["data"]["content"], "Inspect this content")

    def test_reject_and_cancel_do_not_publish_downstream_outputs(self):
        workflow = flow([node("s", "text", text="only synthetic"), node("h", "human", content="stop"), node("o", "container")], [edge("s", "h"), edge("h", "o")])
        for decision, expected in [("reject", "rejected"), ("cancel", "cancelled")]:
            with self.subTest(decision=decision):
                identifier = self.submit(workflow)
                run = self.wait(identifier, {"waiting"})
                if decision == "cancel":
                    response = self.client.post(f"/api/runs/{identifier}/cancel")
                else:
                    response = self.decision(identifier, run["approvals"][0]["node_id"], decision)
                self.assertEqual(response.status_code, 200, response.text)
                stopped = self.wait(identifier, {expected})
                self.assertFalse(stopped.get("output_manifest"))
                self.assertNotEqual(next(n for n in stopped["nodes"] if n["node_id"] == "o")["status"], "succeeded")

    def test_blackbox_runs_and_preserves_nested_definition(self):
        nested = inner()
        nested["nodes"].insert(1, node("innerbox", "blackbox", workflow=inner()))
        nested["edges"] = [edge("entry", "innerbox"), edge("innerbox", "exit")]
        workflow = flow([node("source", "text", text="NESTED_PAYLOAD_837"), node("box", "blackbox", workflow=nested), node("out", "container")], [edge("source", "box"), edge("box", "out")])
        finished = self.wait(self.submit(workflow), {"succeeded"})
        out = next(n for n in finished["nodes"] if n["node_id"] == "out")
        self.assertIn("NESTED_PAYLOAD_837", json.dumps(out["output"]))
        self.assertEqual(finished["snapshot"]["workflow"]["nodes"][1]["type"], "blackbox")
        self.assertEqual(finished["snapshot"]["workflow"]["nodes"][1]["data"]["workflow"], nested)

    def test_inner_human_approval_works_from_top_level(self):
        workflow = flow([node("s", "text", text="BOX_REVIEW_294"), node("box", "blackbox", workflow=inner(True)), node("o", "container")], [edge("s", "box"), edge("box", "o")])
        identifier = self.submit(workflow)
        pending = self.wait(identifier, {"waiting"})
        self.assertEqual(len(pending["approvals"]), 1)
        approval = pending["approvals"][0]
        self.assertIn("BOX_REVIEW_294", json.dumps(approval))
        self.assertEqual(self.decision(identifier, approval["node_id"], "approve").status_code, 200)
        finished = self.wait(identifier, {"succeeded"})
        self.assertIn("BOX_REVIEW_294", json.dumps(next(n for n in finished["nodes"] if n["node_id"] == "o")["output"]))

    def test_blackbox_internal_file_snapshot_and_inactive_source_gate(self):
        asset_response = self.client.post("/api/files", files={"file": ("inside-box.md", b"INNER_FILE_SNAPSHOT_524", "text/markdown")})
        self.assertEqual(asset_response.status_code, 200, asset_response.text)
        child = flow([node("entry", "subflow_input"), node("attachment", "file", file_id=asset_response.json()["id"]), node("merge", "container"), node("review", "human", content="internal file review"), node("exit", "subflow_output")], [edge("entry", "merge"), edge("attachment", "merge"), edge("merge", "review"), edge("review", "exit")])
        workflow = flow([node("box", "blackbox", workflow=child)], [])
        identifier = self.submit(workflow)
        pending = self.wait(identifier, {"waiting"})
        self.assertIn(asset_response.json()["id"], pending["snapshot"]["sources"])
        self.assertIn("INNER_FILE_SNAPSHOT_524", json.dumps(pending["approvals"]))
        response = self.decision(identifier, pending["approvals"][0]["node_id"], "approve")
        self.assertEqual(response.status_code, 200, response.text)
        self.wait(identifier, {"succeeded"})
        inactive = flow([node("s", "text", text="route away"), node("c", "condition", field="status", operator="equals", expected="source"), node("yes", "container"), node("box", "blackbox", workflow=child)], [edge("s", "c"), edge("c", "yes", "true"), edge("c", "box", "false")])
        completed = self.wait(self.submit(inactive), {"succeeded"})
        self.assertFalse(completed.get("approvals"), "Internal file must not activate a human on an excluded outer branch")

    def test_unselected_human_inside_blackbox_does_not_pause(self):
        workflow = flow([node("s", "text", text="FALSE_BRANCH_164"), node("c", "condition", field="status", operator="equals", expected="source"), node("yes", "container"), node("no", "blackbox", workflow=inner(True))], [edge("s", "c"), edge("c", "yes", "true"), edge("c", "no", "false")])
        finished = self.wait(self.submit(workflow), {"succeeded"})
        self.assertFalse(finished.get("approvals"))
        self.assertIn("FALSE_BRANCH_164", json.dumps(finished["output_manifest"]))

    def test_invalid_nested_boundary_cycle_and_embedded_key_rejected(self):
        bad = [flow([node("entry", "subflow_input")], []),
               flow([node("entry", "subflow_input"), node("exit", "subflow_output")], [edge("entry", "exit"), edge("exit", "entry")])]
        credential = inner()
        credential["nodes"][0]["data"]["api_key"] = "SYNTHETIC_NOT_A_REAL_KEY"
        bad.append(credential)
        for child in bad:
            workflow = flow([node("box", "blackbox", workflow=child)], [])
            response = self.client.post("/api/runs", json={"workflow": workflow})
            self.assertEqual(response.status_code, 422, response.text)

    def test_full_chinese_filename_is_retained_without_filesystem_overflow(self):
        name = "长文件名中文资料" * 25 + ".md"
        response = self.client.post("/api/files", files={"file": (name, b"LONG_NAME_SYNTHETIC", "text/markdown")})
        self.assertEqual(response.status_code, 200, response.text)
        asset = response.json()
        self.assertEqual(asset["display_name"], name)
        workflow = flow([node("source", "file", file_id=asset["id"]), node("out", "container")], [edge("source", "out")])
        finished = self.wait(self.submit(workflow), {"succeeded"})
        self.assertIn("LONG_NAME_SYNTHETIC", json.dumps(finished["output_manifest"]))

    def test_seven_global_agents_and_source_bound_model_aliases(self):
        response = self.client.get("/api/agents")
        self.assertEqual(response.status_code, 200, response.text)
        agents = response.json()
        self.assertEqual({item["id"] for item in agents}, {"codex", "claude", "opencode", "pi", "hermes", "workbuddy", "deepseek"})
        model = {"cli_id": "codex", "model": "same-synthetic-model", "alias": "CLI fixture alias", "source": "manual", "efforts": ["low", "high"], "default_effort": "low"}
        native = self.client.post("/api/agent-models", json=model)
        self.assertEqual(native.status_code, 200, native.text)
        secret = "SYNTHETIC_NOT_A_REAL_API_CREDENTIAL_8374"
        with patch.object(core, "store_keychain_secret"):
            stored = self.client.post("/api/credentials/store", json={"provider": "openai", "api_key": secret, "env_name": "OPENAI_API_KEY", "endpoint": "http://127.0.0.1:9823/v1"})
        self.assertEqual(stored.status_code, 200, stored.text)
        api = self.client.post("/api/agent-models", json={**model, "alias": "API fixture alias", "source": "api", "credential_id": stored.json()["id"]})
        self.assertEqual(api.status_code, 200, api.text)
        self.assertNotEqual(native.json()["id"], api.json()["id"])
        catalog = self.client.get("/api/agent-models")
        self.assertEqual(catalog.status_code, 200, catalog.text)
        self.assertNotIn(secret, catalog.text)
        with core.connect_db() as db:
            dump = "\n".join(db.iterdump())
        self.assertNotIn(secret, dump)
        records = [item for item in catalog.json() if item["model"] == model["model"]]
        self.assertEqual({item["alias"] for item in records}, {"CLI fixture alias", "API fixture alias"})
        changed = self.client.put("/api/agent-models/" + native.json()["id"], json={**model, "alias": "Renamed alias"})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["id"], native.json()["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
