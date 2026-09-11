"""Focused Stage 1 checks for the portable workflow package API."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="kxy-portable-stage1-"))
    os.environ["KXY_DATA_ROOT"] = str(root / "data")
    os.environ["LANGFLOW_CONFIG_DIR"] = str(root / "lfx")
    os.environ["DO_NOT_TRACK"] = "true"

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend import agent_config as config
    from backend import app as core
    from backend.portable import PortablePackageError, build_package, commit_package, preview_package

    core.init_db()
    source_file = core.store_file("source.txt", b"portable source")
    skill_source = root / "skill"
    skill_source.mkdir()
    (skill_source / "SKILL.md").write_text(
        "---\nname: smoke-skill\ndescription: smoke\n---\n", encoding="utf-8"
    )
    script = skill_source / "run.sh"
    script.write_text("#!/bin/sh\necho smoke\n", encoding="utf-8")
    script.chmod(0o755)
    source_skill = core.import_skill_root(skill_source)

    config.ensure_agent_config_schema()
    with core.connect_db() as db:
        db.execute(
            "INSERT INTO agent_models(id,agent_id,cli_id,model,alias,source,efforts,default_effort,"
            "discovery_source,credential_id,native_model_ref,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "m1",
                "codex",
                "codex",
                "smoke-model",
                "Smoke",
                "manual",
                '["low"]',
                "low",
                "test",
                None,
                None,
                core.utc_now(),
                core.utc_now(),
            ),
        )

    workflow = {
        "name": "portable smoke",
        "version": "kxy.workflow.v1",
        "nodes": [
            {
                "id": "input",
                "type": "input",
                "data": {
                    "label": "Input",
                    "attachments": [{"file_id": source_file["id"], "display_name": "source.txt"}],
                },
            },
            {
                "id": "analyzer",
                "type": "analyzer",
                "data": {
                    "label": "Analyze",
                    "prompt": "summarize",
                    "model_ref": "m1",
                    "agent_id": "codex",
                    "model": "smoke-model",
                    "skill_ids": [source_skill["id"]],
                    "output_format": "json",
                    "api_key": "must-not-be-exported",
                    "output_schema": {"properties": {"token_count": {"type": "integer"}}},
                },
            },
            {"id": "out", "type": "container", "data": {"label": "Output"}},
        ],
        "edges": [
            {"id": "e1", "source": "input", "target": "analyzer"},
            {"id": "e2", "source": "analyzer", "target": "out"},
        ],
    }

    package = build_package(
        workflow,
        include_file_ids=[source_file["id"]],
        include_skill_ids=[source_skill["id"]],
    )
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        exported_workflow = json.loads(archive.read("workflow.json"))
        assert "api_key" not in json.dumps(exported_workflow)
        assert exported_workflow["nodes"][1]["data"]["output_schema"]["properties"]["token_count"]
        skill_payload = next(
            item["archive_path"]
            for item in manifest["skills"][0]["files"]
            if item["relative_path"] == "run.sh"
        )
        assert archive.getinfo(skill_payload).external_attr >> 16 & 0o111

    preview = preview_package(package)
    assert preview["manifest"]["format"] == "kxy.portable.v1"
    try:
        result = commit_package(
            preview["preview_id"],
            {
                "files": {source_file["id"]: "package"},
                "skills": {source_skill["id"]: "package"},
                "models": {"analyzer": "m1"},
                "mcps": {},
                "outputs": {"out": "default"},
            },
        )
    except Exception as exc:  # pragma: no cover - failure is surfaced below.
        raise AssertionError(f"portable commit failed: {exc}") from exc

    from fastapi.testclient import TestClient

    with TestClient(core.app) as client:
        exported = client.post(
            "/api/workflows/portable/export",
            json={
                "workflow_id": result["workflow"]["id"],
                "include_file_ids": [source_file["id"]],
                "include_skill_ids": [source_skill["id"]],
            },
        )
        assert exported.status_code == 200, exported.text
        preview_response = client.post(
            "/api/workflows/portable/import/preview",
            files={"file": ("portable.zip", exported.content, "application/zip")},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview_id = preview_response.json()["preview_id"]
        committed = client.post(
            "/api/workflows/portable/import/commit",
            json={
                "preview_id": preview_id,
                "bindings": {
                    "files": {source_file["id"]: "package"},
                    "skills": {source_skill["id"]: "package"},
                    "models": {"analyzer": "m1"},
                    "mcps": {},
                    "outputs": {"out": "default"},
                },
            },
        )
        assert committed.status_code == 200, committed.text
    assert len(core.list_workflows()) == 2

    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "format": "kxy.portable.v1",
                    "files": {"../workflow.json": {"sha256": "0" * 64, "size": 0}},
                }
            ),
        )
        archive.writestr("../workflow.json", b"")
    try:
        preview_package(bad.getvalue())
    except PortablePackageError:
        pass
    else:  # pragma: no cover - the safe-unpack gate must reject this archive.
        raise AssertionError("path traversal archive was accepted")
    print("portable_workflow_checks: PASS")


if __name__ == "__main__":
    main()
