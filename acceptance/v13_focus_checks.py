"""Focused V13 checks: unified inputs, fail-closed filtering, revision transport, and loop gates."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(tempfile.mkdtemp(prefix="kxy-v13-focus-"))
os.environ.update(
    KXY_DATA_ROOT=str(ROOT / "data"),
    LANGFLOW_CONFIG_DIR=str(ROOT / "lfx"),
    DO_NOT_TRACK="true",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend import app as core


def node(identifier: str, kind: str, **data: object) -> dict[str, object]:
    return {
        "id": identifier,
        "type": kind,
        "position": {"x": 0, "y": 0},
        "data": {"label": identifier, **data},
    }


def edge(source: str, target: str) -> dict[str, str]:
    return {
        "id": f"{source}-{target}",
        "source": source,
        "target": target,
        "sourceHandle": "result",
        "targetHandle": "items",
    }


class V13FocusChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = TestClient(core.app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.context.__exit__(None, None, None)

    def test_01_unified_input_and_filter_are_non_destructive(self) -> None:
        workspace = ROOT / "input-fixture"
        workspace.mkdir()
        first = workspace / "sources" / "a.pdf"
        second = workspace / "sources" / "b.pdf"
        first.parent.mkdir()
        first.write_bytes(b"A")
        second.write_bytes(b"B")
        (workspace / "manifest.json").write_text(
            json.dumps(
                {
                    "sources": {
                        "f-a": {"file_path": "sources/a.pdf", "sha256": hashlib.sha256(b"A").hexdigest()},
                        "f-b": {"file_path": "sources/b.pdf", "sha256": hashlib.sha256(b"B").hexdigest()},
                    }
                }
            ),
            encoding="utf-8",
        )
        payload = core.input_source_payload(
            {
                "text": "V13 question",
                "attachments": [
                    {"file_id": "f-a", "relative_path": "reports/a.pdf", "display_name": "first.pdf"},
                    {"file_id": "f-b", "relative_path": "reports/b.pdf", "display_name": "second.pdf"},
                ],
            },
            workspace,
        )
        original = copy.deepcopy(payload)
        filtered = core.filter_payload_items(
            [payload],
            core.normalize_filter_config({"pattern": "first.pdf", "extensions": [".pdf"]}),
        )
        self.assertEqual(filtered["matched_count"], 1)
        self.assertEqual(filtered["excluded_count"], 1)
        self.assertEqual(payload, original)
        self.assertEqual(first.read_bytes(), b"A")
        self.assertEqual(second.read_bytes(), b"B")
        self.assertNotIn("second.pdf", json.dumps(filtered["text"], ensure_ascii=False))
        self.assertEqual([item["relative_path"] for item in payload["items"]], ["reports/a.pdf", "reports/b.pdf"])
        print("PASS unified input names plus non-destructive filter")

    def test_02_regex_batch_timeout_and_no_leak(self) -> None:
        payload = [
            {"status": "source", "file_id": "keep", "name": "keep.pdf", "file_path": "sources/keep.pdf", "text": "keep"},
            {"status": "source", "file_id": "drop", "name": "drop.pdf", "file_path": "sources/drop.pdf", "text": "SECRET_DROP"},
        ]
        calls: list[int] = []
        real_batch = core._safe_regex_search_batch

        def counted(pattern: str, candidates: list[str], timeout_ms: int) -> list[bool]:
            calls.append(len(candidates))
            return real_batch(pattern, candidates, timeout_ms)

        with patch.object(core, "_safe_regex_search_batch", side_effect=counted):
            result = core.filter_payload_items(
                payload,
                core.normalize_filter_config({"pattern": r"keep\.pdf$", "pattern_mode": "regex", "extensions": [".pdf"]}),
            )
        self.assertEqual(calls, [2])
        self.assertNotIn("SECRET_DROP", json.dumps(result, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, "timed out"):
            core.filter_payload_items(
                [{"status": "source", "file_id": "slow", "name": "a" * 1800 + "!", "file_path": "sources/slow"}],
                core.normalize_filter_config({"pattern": r"^(a+)+$", "pattern_mode": "regex", "extensions": ["*"], "timeout_ms": 100}),
            )
        print("PASS regex batch timeout and fail-closed redaction")

    def test_03_missing_condition_and_revision_keep_transport(self) -> None:
        self.assertFalse(core.evaluate_condition({}, "missing", "equals", "x", "false"))
        self.assertTrue(core.evaluate_condition({}, "missing", "equals", "x", "true"))
        with self.assertRaises(ValueError):
            core.evaluate_condition({}, "missing", "equals", "x", "error")
        revised = core.human_revision_payload(
            [{
                "status": "agent",
                "text": "OLD_BODY",
                "items": [{"file_id": "f1", "file_path": "sources/a.pdf", "text": "OLD_SOURCE"}],
                "artifacts": [{"path": "nodes/a.json", "name": "a.json", "content": "OLD_ARTIFACT"}],
            }],
            "",
        )
        self.assertEqual(revised["text"], "")
        self.assertNotIn("OLD_BODY", repr(revised))
        self.assertNotIn("OLD_SOURCE", repr(revised))
        self.assertNotIn("OLD_ARTIFACT", repr(revised))
        self.assertEqual(revised["attachments"][0]["file_path"], "sources/a.pdf")
        self.assertEqual(revised["artifacts"][0]["path"], "nodes/a.json")
        print("PASS condition missing strategies and revision transport")

    def test_04_loop_gate_current_round_return_then_reject(self) -> None:
        script = ROOT / "synthetic-v13-codex"
        script.write_text(
            """#!/usr/bin/env python3
import json
import pathlib
import sys

if '--version' in sys.argv:
    print('V13 synthetic subprocess')
    raise SystemExit(0)

root = pathlib.Path(__file__).parent
context = json.loads(pathlib.Path('input-context.json').read_text(encoding='utf-8'))
rounds = []

def walk(value):
    if isinstance(value, dict):
        if isinstance(value.get('round'), int):
            rounds.append(value['round'])
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

list(walk(context))
round_no = max(rounds or [1])
prompt = sys.argv[-1]
if prompt == 'V13_EXECUTOR':
    with (root / 'executor-calls.log').open('a', encoding='utf-8') as handle:
        handle.write(str(round_no) + '\\n')
    target = pathlib.Path('outputs') / ('round-%d.txt' % round_no)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('V13_ARTIFACT_R%d' % round_no, encoding='utf-8')
    suffix = '_SEES_REVISION' if '"human_revision"' in json.dumps(context, ensure_ascii=False) else ''
    answer = json.dumps({'executor_text': 'V13_EXECUTOR_R%d%s' % (round_no, suffix)}, ensure_ascii=False)
elif prompt == 'V13_REVIEWER':
    answer = json.dumps({'passed': True, 'issues': [], 'next_action': ''}, ensure_ascii=False)
else:
    raise AssertionError(prompt)

message = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
message.write_text(answer, encoding='utf-8')
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': answer}}))
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        nested = {
            "version": "kxy.workflow.v1",
            "name": "V13 gate",
            "nodes": [
                node("subin", "subflow_input"),
                node("executor", "analyzer", cli="codex", prompt="V13_EXECUTOR", network=False, output_format="auto", timeout=30),
                node("reviewer", "analyzer", cli="codex", prompt="V13_REVIEWER", network=False, output_format="auto", timeout=30),
                node("gate", "human", review_gate=True, content="审阅本轮 executor 正文、附件与 reviewer 意见"),
                node("subout", "subflow_output"),
            ],
            "edges": [edge("subin", "executor"), edge("executor", "reviewer"), edge("reviewer", "gate"), edge("gate", "subout")],
        }
        workflow = {
            "version": "kxy.workflow.v1",
            "name": "V13 loop gate",
            "nodes": [
                node("source", "text", text="V13_ORIGINAL_INPUT"),
                node(
                    "loop",
                    "blackbox",
                    workflow=nested,
                    loop={
                        "enabled": True,
                        "executor_id": "executor",
                        "reviewer_id": "reviewer",
                        "goal": "V13 loop goal",
                        "input_field": "text",
                        "max_rounds": 3,
                        "active_budget_seconds": 60,
                        "previous_summary_chars": 1000,
                    },
                ),
            ],
            "edges": [edge("source", "loop")],
        }
        with (
            patch.dict(os.environ, {"KXY_CODEX_BIN": str(script)}),
            patch.object(core, "prepare_headless_environment", side_effect=lambda _agent, workspace, **_kwargs: {"PATH": os.environ.get("PATH", ""), "HOME": str(workspace)}),
            patch.object(core, "probe_cli", return_value={"name": "codex", "available": True, "status": "READY", "version": "V13 synthetic"}),
        ):
            response = self.client.post("/api/runs", json={"workflow": workflow})
            self.assertEqual(response.status_code, 200, response.text)
            run_id = str(response.json()["id"])

            def wait_for_pending() -> dict[str, object]:
                deadline = time.monotonic() + 25
                latest: dict[str, object] = {}
                while time.monotonic() < deadline:
                    latest = self.client.get(f"/api/runs/{run_id}").json()
                    if any(item.get("status") == "pending" for item in latest.get("approvals", [])):
                        return latest
                    if latest.get("status") in {"failed", "rejected", "cancelled", "succeeded"}:
                        break
                    time.sleep(0.04)
                self.fail(f"loop did not reach approval: {latest.get('status')} {latest.get('error')}")

            first_run = wait_for_pending()
            first = next(item for item in first_run["approvals"] if item["status"] == "pending")
            first_inputs = json.dumps(first["inputs"], ensure_ascii=False)
            self.assertTrue(first["allow_return"])
            self.assertIn("V13_EXECUTOR_R1", first_inputs)
            self.assertIn("round-1.txt", first_inputs)
            self.assertIn('"role": "reviewer"', first_inputs)
            decision = self.client.post(
                f"/api/runs/{run_id}/approvals/{first['flat_node_id']}",
                json={"decision": "return", "revision_text": ""},
            )
            self.assertEqual(decision.status_code, 200, decision.text)

            second_run = wait_for_pending()
            second = next(item for item in second_run["approvals"] if item["status"] == "pending")
            second_inputs = json.dumps(second["inputs"], ensure_ascii=False)
            self.assertIn("V13_EXECUTOR_R2", second_inputs)
            self.assertIn("SEES_REVISION", second_inputs)
            self.assertIn("round-2.txt", second_inputs)
            self.assertNotIn("V13_EXECUTOR_R1", second_inputs)
            self.assertIn('"role": "executor"', second_inputs)
            calls = (ROOT / "executor-calls.log").read_text(encoding="utf-8").splitlines()
            self.assertEqual(calls, ["1", "2"])
            rejected = self.client.post(
                f"/api/runs/{run_id}/approvals/{second['flat_node_id']}",
                json={"decision": "reject", "note": "V13_STOP"},
            )
            self.assertEqual(rejected.status_code, 200, rejected.text)

            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                final = self.client.get(f"/api/runs/{run_id}").json()
                if final.get("status") in {"rejected", "failed", "cancelled", "succeeded"}:
                    break
                time.sleep(0.04)
            self.assertEqual(final.get("status"), "rejected", final)
            self.assertEqual((ROOT / "executor-calls.log").read_text(encoding="utf-8").splitlines(), ["1", "2"])
            with core.connect_db() as db:
                row = db.execute("SELECT next_action FROM loop_rounds WHERE run_id=? AND round_no=1", (run_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertIn("人工闸门已提交修订正文", str(row["next_action"]))
        print("PASS bounded loop return/reject, current-round gate inputs, no replay")


if __name__ == "__main__":
    unittest.main(verbosity=1)
