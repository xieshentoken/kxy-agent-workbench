"""KXY V3 backend checks; isolated data and synthetic processes only."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

TEMP = Path(tempfile.mkdtemp(prefix="kxy-v3-backend-"))
os.environ["KXY_DATA_ROOT"] = str(TEMP / "data")
os.environ["LANGFLOW_CONFIG_DIR"] = str(TEMP / "lfx")
os.environ["DO_NOT_TRACK"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import agent_config as config  # noqa: E402
from backend import app as core  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402


def node(identifier: str, kind: str, **data):
    return {"id": identifier, "type": kind, "position": {"x": 0, "y": 0}, "data": data}


def edge(source: str, target: str):
    return {"id": f"{source}-{target}", "source": source, "target": target, "sourceHandle": "result", "targetHandle": "items"}


def workflow(nodes, edges):
    return {"version": "kxy.workflow.v1", "name": "V3 backend fixture", "nodes": nodes, "edges": edges, "settings": {}}


class V3BackendChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(core.app)
        cls.client = cls.context.__enter__()
        cls.fixture = TEMP / "fixture-cli"
        cls.fixture.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os\n"
            "from pathlib import Path\n"
            "cfg = Path(os.environ['KXY_MCP_CONFIG'])\n"
            "skills = Path('skill-manifest.json')\n"
            "marker = 'MCP_CONFIG=' + cfg.read_text(encoding='utf-8') + ' SKILLS=' + skills.read_text(encoding='utf-8')\n"
            "Path('outputs/fixture.txt').write_text(marker, encoding='utf-8')\n"
            "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'SYNTHETIC_V3_RUNTIME_OK ' + marker}}, ensure_ascii=False))\n",
            encoding="utf-8",
        )
        cls.fixture.chmod(cls.fixture.stat().st_mode | stat.S_IXUSR)

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)
        print("Isolated V3 backend data:", TEMP)

    def native_home(self) -> Path:
        home = TEMP / "native"
        home.mkdir(exist_ok=True)
        return home

    def test_01_image_validation_catches_decompression_bomb(self):
        tiny = io.BytesIO()
        Image.new("RGB", (1, 1)).save(tiny, format="PNG")
        original = tiny.getvalue()
        header = struct.pack(">II", 25000, 25000) + original[24:29]
        dimensions = original[:16] + header + struct.pack(">I", zlib.crc32(b"IHDR" + header) & 0xFFFFFFFF) + original[33:]
        response = self.client.post("/api/appearance/background", files={"file": ("bomb.png", dimensions, "image/png")})
        self.assertIn(response.status_code, (413, 422), response.text)

    def test_02_skillhub_full_hash_and_workbuddy_copy_are_immutable(self):
        root = TEMP / "skills"
        root.mkdir(exist_ok=True)
        folders = []
        original_hashes = {}
        for suffix, reference in (("a", "V3_REF_A"), ("b", "V3_REF_B")):
            folder = root / suffix
            folder.mkdir(exist_ok=True)
            (folder / "SKILL.md").write_text("---\nname: v3-collision\ndescription: synthetic\n---\nRead reference.txt.\n", encoding="utf-8")
            (folder / "reference.txt").write_text(reference, encoding="utf-8")
            folders.append(folder)
            original_hashes.update({path: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir()})
        response = self.client.put("/api/agents/claude", json={"skill_roots": [str(root)]})
        self.assertEqual(response.status_code, 200, response.text)
        imported = []
        for folder in folders:
            response = self.client.post("/api/agents/claude/skills/import", json={"paths": [str(folder)]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(response.json()["errors"], response.text)
            imported.append(response.json()["imported"][0])
        self.assertNotEqual(imported[0]["snapshot_hash"], imported[1]["snapshot_hash"])
        response = self.client.post("/api/skillhub/mount", json={"agent_id": "workbuddy", "skill_ids": [item["id"] for item in imported]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "ready")
        response = self.client.post("/api/skillhub/mount", json={"agent_id": "workbuddy", "skill_ids": [item["id"] for item in imported]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(all(item["status"] == "ready" for item in response.json()["skills"]))
        stored = {path.read_text(encoding="utf-8") for path in (TEMP / "data" / "skillhub").rglob("reference.txt") if path.is_file()}
        self.assertTrue({"V3_REF_A", "V3_REF_B"}.issubset(stored))
        for path, digest in original_hashes.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_03_corrupt_skillhub_index_fails_closed(self):
        path = TEMP / "data" / "skillhub" / "index.json"
        path.write_text("[]", encoding="utf-8")
        with self.assertRaises(config.AgentConfigError):
            config._skillhub_load_index()
        path.unlink()

    def test_04_mcp_secret_source_isolation_and_supported_formats(self):
        native = self.native_home()
        workbuddy = native / ".workbuddy"
        workbuddy.mkdir(exist_ok=True)
        (workbuddy / "mcp.json").write_text(
            json.dumps({"mcpServers": {
                "v3_api": {"type": "http", "url": "https://mcp.example.invalid/v3", "headers": {"Authorization": "Bearer V3_SYNTHETIC_SECRET_VALUE"}},
                "v3_stdio": {"command": str(TEMP / "bin with spaces" / "mcp-server"), "args": [], "env": {"MCP_TOKEN": "V3_STDIO_SECRET_VALUE"}},
            }}),
            encoding="utf-8",
        )
        with patch.object(config, "_home", return_value=native):
            discovered = config.discover_mcps("workbuddy")
            self.assertEqual({item["id"] for item in discovered}, {"v3_api", "v3_stdio"})
            result = config.import_mcps("workbuddy", ["v3_api", "v3_stdio"])
            self.assertFalse(result["errors"], result)
            index_text = (TEMP / "data" / "skillhub" / "mcp" / "index.json").read_text(encoding="utf-8")
            self.assertNotIn("V3_SYNTHETIC_SECRET_VALUE", index_text)
            self.assertIn("KXY_MCP_WORKBUDDY_V3_API_AUTHORIZATION_SECRET", index_text)
            codex = config.prepare_mcp_configuration("codex", ["v3_api", "v3_stdio"], TEMP / "data" / "format-codex")
            opencode = config.prepare_mcp_configuration("opencode", ["v3_stdio"], TEMP / "data" / "format-opencode")
            self.assertTrue(codex["runnable"] and opencode["runnable"])
            import tomllib
            codex_document = tomllib.loads(Path(codex["path"]).read_text())
            self.assertEqual(set(codex_document["mcp_servers"]), {"v3_api", "v3_stdio"})
            self.assertEqual(codex_document["mcp_servers"]["v3_api"]["env_http_headers"]["Authorization"], "KXY_MCP_WORKBUDDY_V3_API_AUTHORIZATION_SECRET")
            self.assertEqual(codex_document["mcp_servers"]["v3_stdio"]["env_vars"], ["MCP_TOKEN"])
            self.assertEqual(codex_document["mcp_servers"]["v3_api"]["default_tools_approval_mode"], "approve")
            overrides = " ".join(core._codex_mcp_overrides(Path(codex["path"])))
            self.assertIn("env_http_headers", overrides)
            self.assertIn("env_vars", overrides)
            self.assertIn("default_tools_approval_mode=\"approve\"", overrides)
            opencode_document = json.loads(Path(opencode["path"]).read_text())
            self.assertEqual(set(opencode_document["mcp"]), {"v3_stdio"})
            self.assertTrue(opencode_document["mcp"]["v3_stdio"]["environment"]["MCP_TOKEN"].startswith("{env:"))
            env = config.mcp_runtime_environment("codex", ["v3_api", "v3_stdio"])
            self.assertEqual(env["KXY_MCP_WORKBUDDY_V3_API_AUTHORIZATION_SECRET"], "Bearer V3_SYNTHETIC_SECRET_VALUE")
            self.assertEqual(env["KXY_MCP_WORKBUDDY_V3_STDIO_MCP_TOKEN_SECRET"], "V3_STDIO_SECRET_VALUE")
            self.assertEqual(env["MCP_TOKEN"], "V3_STDIO_SECRET_VALUE")
            self.assertEqual(set(env), {"KXY_MCP_WORKBUDDY_V3_API_AUTHORIZATION_SECRET", "KXY_MCP_WORKBUDDY_V3_STDIO_MCP_TOKEN_SECRET", "MCP_TOKEN"})
            fixture = TEMP / "MCP auth server.py"
            fixture.write_text(
                "import os\n"
                "raise SystemExit(0 if os.environ.get('MCP_TOKEN') == 'V3_STDIO_SECRET_VALUE' else 1)\n",
                encoding="utf-8",
            )
            fixture.chmod(fixture.stat().st_mode | stat.S_IXUSR)
            process = subprocess.run([sys.executable, str(fixture)], env={**os.environ, **config.mcp_runtime_environment("codex", ["v3_stdio"])}, check=False)
            self.assertEqual(process.returncode, 0)

            claude = native / ".claude.json"
            claude.write_text(json.dumps({"mcpServers": {"v3_api": {"type": "http", "url": "https://mcp.example.invalid/v3", "headers": {"Authorization": "Bearer OTHER_ACCOUNT_SECRET"}}}}), encoding="utf-8")
            conflict = config.import_mcps("claude", ["v3_api"])
            self.assertTrue(conflict["errors"])
            self.assertEqual(config._mcp_load_index()["v3_api"]["source"], "workbuddy")

    def test_05_frozen_mcp_definition_blocks_native_endpoint_change(self):
        native = self.native_home()
        directory = native / ".workbuddy"
        directory.mkdir(exist_ok=True)
        path = directory / "mcp.json"
        path.write_text(json.dumps({"mcpServers": {"v3_frozen": {"type": "http", "url": "https://a.example.invalid/mcp"}}}), encoding="utf-8")
        with patch.object(config, "_home", return_value=native):
            self.assertFalse(config.import_mcps("workbuddy", ["v3_frozen"])["errors"])
            definition = config._mcp_load_index()["v3_frozen"]
            frozen = {"mcps": [{
                "id": "v3_frozen",
                "source_agent": "workbuddy",
                "source_agents": ["workbuddy"],
                "definition": {key: definition[key] for key in ("id", "label", "transport", "enabled", "url", "headers") if key in definition},
                "definition_sha256": config._mcp_definition_digest(definition),
            }]}
            path.write_text(json.dumps({"mcpServers": {"v3_frozen": {"type": "http", "url": "https://b.example.invalid/mcp"}}}), encoding="utf-8")
            with self.assertRaises(config.AgentConfigError):
                config.mcp_runtime_environment("codex", ["v3_frozen"], snapshot=frozen)

    def test_05_native_codex_fields_and_composite_env_are_normalized(self):
        definition, reason = config._mcp_parse_definition(
            "codex",
            "v3_native_http",
            {
                "url": "https://native.example.invalid/mcp",
                "http_headers": {"X-Region": "us-east-1"},
                "env_http_headers": {"Authorization": "V3_BEARER_TOKEN"},
            },
        )
        self.assertIsNone(reason)
        self.assertEqual(definition["headers"]["X-Region"], "us-east-1")
        self.assertEqual(definition["headers"]["Authorization"], "{{env:V3_BEARER_TOKEN}}")
        definition, reason = config._mcp_parse_definition(
            "codex",
            "v3_native_stdio",
            {"command": "/tmp/mcp server", "env_vars": ["V3_STDIO_TOKEN"]},
        )
        self.assertIsNone(reason)
        self.assertEqual(definition["env"], {"V3_STDIO_TOKEN": "{{env:V3_STDIO_TOKEN}}"})
        definition, reason = config._mcp_parse_definition(
            "workbuddy",
            "v3_composite",
            {"url": "https://composite.example.invalid/mcp", "headers": {"Authorization": "Bearer ${V3_COMPOSITE_TOKEN}"}},
        )
        self.assertIsNone(reason)
        self.assertEqual(list(definition["headers"]), ["Authorization"])
        self.assertTrue(definition["headers"]["Authorization"].startswith("{{env:KXY_MCP_"))
        self.assertEqual(definition["env_templates"]["headers"]["Authorization"], "Bearer {{env:V3_COMPOSITE_TOKEN}}")
        _, reason = config._mcp_parse_definition(
            "codex",
            "v3_oauth",
            {"url": "https://oauth.example.invalid/mcp", "auth": "oauth"},
        )
        self.assertIn("OAuth", reason or "")

    def test_06_runtime_replays_frozen_skill_and_mcp_task_config(self):
        native = self.native_home()
        workbuddy = native / ".workbuddy"
        workbuddy.mkdir(exist_ok=True)
        (workbuddy / "mcp.json").write_text(json.dumps({"mcpServers": {"v3_runtime": {"command": str(TEMP / "runtime mcp"), "args": []}}}), encoding="utf-8")
        skill_dir = TEMP / "runtime-skill"
        skill_dir.mkdir(exist_ok=True)
        (skill_dir / "SKILL.md").write_text("---\nname: runtime-skill\ndescription: synthetic runtime skill\n---\nUse runtime-reference.txt.\n", encoding="utf-8")
        (skill_dir / "runtime-reference.txt").write_text("V3_RUNTIME_REFERENCE", encoding="utf-8")
        self.assertEqual(self.client.put("/api/agents/claude", json={"skill_roots": [str(TEMP)]}).status_code, 200)
        skill_response = self.client.post("/api/agents/claude/skills/import", json={"paths": [str(skill_dir)]})
        self.assertEqual(skill_response.status_code, 200, skill_response.text)
        skill_id = skill_response.json()["imported"][0]["id"]
        with patch.object(config, "_home", return_value=native), patch.dict(os.environ, {"KXY_CODEX_BIN": str(self.fixture)}, clear=False):
            mcp_response = self.client.post("/api/agents/workbuddy/mcps/import", json={"ids": ["v3_runtime"]})
            self.assertEqual(mcp_response.status_code, 200, mcp_response.text)
            self.assertFalse(mcp_response.json()["errors"], mcp_response.text)
            document = workflow([
                node("source", "text", text="V3_RUNTIME_INPUT"),
                node("analysis", "analyzer", cli="codex", model="fixture", prompt="V3_RUNTIME_PROMPT", skill_ids=[skill_id], mcp_ids=["v3_runtime"], timeout=5),
                node("out", "container"),
            ], [edge("source", "analysis"), edge("analysis", "out")])
            response = self.client.post("/api/runs", json={"workflow": document})
            self.assertEqual(response.status_code, 200, response.text)
            run_id = response.json()["id"]
            finished = None
            for _ in range(300):
                finished = self.client.get(f"/api/runs/{run_id}").json()
                if finished["status"] in {"succeeded", "failed", "rejected", "cancelled"}:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(finished)
            self.assertEqual(finished["status"], "succeeded", finished.get("error"))
            self.assertEqual(finished["snapshot"]["mcps"][0]["id"], "v3_runtime")
            self.assertTrue(finished["snapshot"].get("mcp_mappings"))
            self.assertTrue(any(item.get("cross_agent") for item in finished["snapshot"].get("skill_mappings", {}).values()))
            workspace = Path(finished["run_dir"]) / "workspace"
            self.assertTrue(list(workspace.rglob("skill-manifest.json")))
            self.assertTrue(list(workspace.rglob("mcp/codex.toml")))
            self.assertIn("SYNTHETIC_V3_RUNTIME_OK", json.dumps(finished, ensure_ascii=False))

    def test_07_runtime_redacts_structured_output_and_deletes_secret_artifacts(self):
        native = self.native_home()
        workbuddy = native / ".workbuddy"
        workbuddy.mkdir(exist_ok=True)
        secret = "V3_ARTIFACT_SECRET_VALUE"
        (workbuddy / "mcp.json").write_text(
            json.dumps({"mcpServers": {"v3_secret": {"command": "/bin/true", "env": {"MCP_TOKEN": secret}}}}),
            encoding="utf-8",
        )
        with patch.object(config, "_home", return_value=native):
            imported = config.import_mcps("workbuddy", ["v3_secret"])
            self.assertFalse(imported["errors"], imported)

        structured_cli = TEMP / "structured-fixture"
        structured_cli.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os\n"
            "token = os.environ['MCP_TOKEN']\n"
            "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'answer ' + token},'structured_output':{'note':token}}))\n",
            encoding="utf-8",
        )
        structured_cli.chmod(structured_cli.stat().st_mode | stat.S_IXUSR)

        def run_fixture(binary: Path):
            document = workflow([
                node("source", "text", text="V3_SECRET_INPUT"),
                node("analysis", "analyzer", cli="codex", model="fixture", prompt="V3_SECRET_PROMPT", mcp_ids=["v3_secret"], timeout=5),
                node("out", "container"),
            ], [edge("source", "analysis"), edge("analysis", "out")])
            response = self.client.post("/api/runs", json={"workflow": document})
            self.assertEqual(response.status_code, 200, response.text)
            run_id = response.json()["id"]
            finished = None
            for _ in range(300):
                finished = self.client.get(f"/api/runs/{run_id}").json()
                if finished["status"] in {"succeeded", "failed", "rejected", "cancelled"}:
                    break
                time.sleep(0.05)
            self.assertIsNotNone(finished)
            return finished

        with patch.object(config, "_home", return_value=native), patch.dict(os.environ, {"KXY_CODEX_BIN": str(structured_cli)}, clear=False):
            finished = run_fixture(structured_cli)
        serialized = json.dumps(finished, ensure_ascii=False)
        self.assertEqual(finished["status"], "succeeded", finished.get("error"))
        self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)

        leaking_cli = TEMP / "leaking-fixture"
        leaking_cli.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os\n"
            "from pathlib import Path\n"
            "Path('outputs/leak.txt').write_text(os.environ['MCP_TOKEN'])\n"
            "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'answer'}}))\n",
            encoding="utf-8",
        )
        leaking_cli.chmod(leaking_cli.stat().st_mode | stat.S_IXUSR)
        with patch.object(config, "_home", return_value=native), patch.dict(os.environ, {"KXY_CODEX_BIN": str(leaking_cli)}, clear=False):
            failed = run_fixture(leaking_cli)
        self.assertEqual(failed["status"], "failed")
        self.assertNotIn(secret, json.dumps(failed, ensure_ascii=False))
        leaked_files = list(Path(failed["run_dir"]).rglob("leak.txt"))
        self.assertFalse(leaked_files)

    def test_08_prelaunch_failure_cleans_temporary_codex_auth(self):
        native = TEMP / "prelaunch-native"
        (native / ".codex").mkdir(parents=True, exist_ok=True)
        secret = "V3_PRELAUNCH_AUTH_SECRET"
        (native / ".codex" / "auth.json").write_text(json.dumps({"access_token": secret}), encoding="utf-8")
        document = workflow([
            node("source", "text", text="V3_PRELAUNCH_INPUT"),
            node("analysis", "analyzer", cli="codex", model="fixture", prompt="V3_PRELAUNCH_PROMPT", timeout=5),
            node("out", "container"),
        ], [edge("source", "analysis"), edge("analysis", "out")])
        with patch.object(config, "_home", return_value=native), patch.object(core, "build_headless_command", side_effect=RuntimeError("synthetic prelaunch failure")):
            response = self.client.post("/api/runs", json={"workflow": document})
            self.assertEqual(response.status_code, 200, response.text)
            run_id = response.json()["id"]
            finished = None
            for _ in range(300):
                finished = self.client.get(f"/api/runs/{run_id}").json()
                if finished["status"] in {"succeeded", "failed", "rejected", "cancelled"}:
                    break
                time.sleep(0.05)
        self.assertIsNotNone(finished)
        self.assertEqual(finished["status"], "failed")
        run_root = Path(finished["run_dir"])
        self.assertFalse(list(run_root.rglob(".cli-state")))
        self.assertNotIn(secret.encode("utf-8"), b"".join(path.read_bytes() for path in run_root.rglob("*") if path.is_file()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
