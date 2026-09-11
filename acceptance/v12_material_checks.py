"""Focused V12 material checks using an isolated database and synthetic CLI only."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(tempfile.mkdtemp(prefix="kxy-v12-material-checks-"))
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


class V12MaterialChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = TestClient(core.app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.context.__exit__(None, None, None)

    def test_01_html_yaml_text_formats_and_legacy_reparse(self) -> None:
        html = """<!doctype html>
<html><head><style>.hidden { display:none }</style><script>alert('ignore')</script>
<link rel='stylesheet' href='https://external.invalid/style.css'></head>
<body><h1>可读标题</h1><p>正文段落 <strong>保留文本</strong>。</p>
<script>window.SECRET='not-material';</script></body></html>""".encode("utf-8")
        html_response = self.client.post(
            "/api/files",
            files={"file": ("brief.html", html, "text/html")},
        )
        self.assertEqual(html_response.status_code, 200, html_response.text)
        html_asset = html_response.json()
        self.assertEqual(html_asset["status"], "parsed")
        self.assertIn("可读标题", html_asset["preview"])
        self.assertIn("正文段落", html_asset["preview"])
        self.assertIn("保留文本", html_asset["preview"])
        self.assertNotIn("alert", html_asset["preview"])
        self.assertNotIn("external.invalid", html_asset["preview"])

        yaml_text = "title: 保留格式\nitems:\n  - name: first\n    value: 1\n"
        yaml_response = self.client.post(
            "/api/files",
            files={"file": ("brief.yaml", yaml_text.encode("utf-8"), "text/yaml")},
        )
        self.assertEqual(yaml_response.status_code, 200, yaml_response.text)
        yaml_asset = yaml_response.json()
        self.assertEqual(yaml_asset["status"], "parsed")
        self.assertEqual(yaml_asset["preview"], yaml_text)
        self.assertFalse(yaml_asset["metadata"]["structured"])

        for name, content in (("brief.md", "# Markdown\n"), ("brief.txt", "纯文本\n")):
            response = self.client.post(
                "/api/files",
                files={"file": (name, content.encode("utf-8"), "text/plain")},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "parsed")

        legacy = core.store_file("legacy.html", html)
        with core.connect_db() as db:
            stored = db.execute("SELECT stored_path FROM files WHERE id=?", (legacy["id"],)).fetchone()
            self.assertIsNotNone(stored)
            stored_path = str(stored["stored_path"])
            db.execute(
                "UPDATE files SET status='unsupported-retained', preview='', metadata='{}' WHERE id=?",
                (legacy["id"],),
            )
        reparsed = core.store_file("legacy.html", html)
        self.assertEqual(reparsed["status"], "parsed")
        self.assertIn("可读标题", reparsed["preview"])
        with core.connect_db() as db:
            current = db.execute("SELECT stored_path, status FROM files WHERE id=?", (legacy["id"],)).fetchone()
        self.assertEqual(str(current["stored_path"]), stored_path)
        self.assertEqual(current["status"], "parsed")

    def test_02_container_result_reaches_downstream_analyzer_inputs(self) -> None:
        script = ROOT / "synthetic-v12-codex"
        script.write_text(
            """#!/usr/bin/env python3
import json
import pathlib
import sys

if '--version' in sys.argv:
    print('V12 synthetic subprocess')
    raise SystemExit(0)

prompt = sys.argv[-1]
context = json.loads(pathlib.Path('input-context.json').read_text(encoding='utf-8'))

def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)

values = list(walk(context))
if prompt == 'V12_UPSTREAM':
    target = pathlib.Path('outputs', 'upstream-proof.txt')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('V12_UPSTREAM_ARTIFACT', encoding='utf-8')
    output = json.dumps({'route': 'container', 'text': 'V12_UPSTREAM_TEXT'}, ensure_ascii=False)
elif prompt == 'V12_DOWNSTREAM':
    assert any('V12_UPSTREAM_TEXT' in item.get('text', '') for item in values)
    structured = [item for item in values if item.get('structured') == {'route': 'container', 'text': 'V12_UPSTREAM_TEXT'}]
    assert structured, 'container structured content was not passed'
    artifacts = [artifact for item in values for artifact in (item.get('artifacts') or []) if isinstance(artifact, dict)]
    assert artifacts, 'container artifact metadata was not passed'
    artifact_path = pathlib.Path(artifacts[0]['path'])
    assert artifact_path.as_posix().startswith('inputs/')
    assert artifact_path.read_text(encoding='utf-8') == 'V12_UPSTREAM_ARTIFACT'
    output = 'V12_DOWNSTREAM_SAW_CONTAINER'
else:
    raise AssertionError(prompt)

message = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
message.write_text(output, encoding='utf-8')
print(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': output}}))
""",
            encoding="utf-8",
        )
        script.chmod(0o755)
        workflow = {
            "version": "kxy.workflow.v1",
            "name": "V12 material handoff",
            "nodes": [
                node("source", "text", text="V12_SOURCE_TEXT"),
                node("upstream", "analyzer", cli="codex", prompt="V12_UPSTREAM"),
                node("container", "container", export_formats=[], allowed_file_extensions=[".txt"]),
                node("downstream", "analyzer", cli="codex", prompt="V12_DOWNSTREAM"),
            ],
            "edges": [edge("source", "upstream"), edge("upstream", "container"), edge("container", "downstream")],
        }
        with (
            patch.dict(os.environ, {"KXY_CODEX_BIN": str(script)}),
            patch.object(
                core,
                "prepare_headless_environment",
                side_effect=lambda _agent, workspace, **_kwargs: {
                    "PATH": os.environ.get("PATH", ""),
                    "HOME": str(workspace),
                },
            ),
            patch.object(
                core,
                "probe_cli",
                return_value={"name": "codex", "available": True, "status": "READY", "version": "V12 synthetic"},
            ),
        ):
            response = self.client.post("/api/runs", json={"workflow": workflow})
            self.assertEqual(response.status_code, 200, response.text)
            run_id = str(response.json()["id"])
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                result = self.client.get(f"/api/runs/{run_id}").json()
                if result["status"] in {"succeeded", "failed", "interrupted", "cancelled", "rejected"}:
                    break
                time.sleep(0.03)
            else:
                self.fail("synthetic material handoff run did not settle")

        self.assertEqual(result["status"], "succeeded", result.get("error"))
        downstream = next(item for item in result["nodes"] if item["node_id"] == "downstream")
        self.assertIn("V12_DOWNSTREAM_SAW_CONTAINER", (downstream["output"] or {}).get("text", ""))


if __name__ == "__main__":
    unittest.main()
