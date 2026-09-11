"""Independent V3 public-contract checks. Synthetic data, real upstream mapping."""
from pathlib import Path
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import struct
import zlib
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix="kxy-v3-supervisor-"))
os.environ["KXY_DATA_ROOT"] = str(ROOT / "data")
os.environ["LANGFLOW_CONFIG_DIR"] = str(ROOT / "lfx")
os.environ["DO_NOT_TRACK"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as core
from backend import agent_config as config
from fastapi.testclient import TestClient
from PIL import Image


class V3Supervisor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(core.app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)
        print("Independent V3 data:", ROOT)

    def style(self, **changes):
        payload = self.client.get("/api/settings").json()
        payload.update(changes)
        return self.client.put("/api/settings", json=payload)

    def fixture(self, suffix, reference):
        folder = ROOT / ("fixture-" + suffix)
        folder.mkdir(exist_ok=True)
        (folder / "SKILL.md").write_text("---\nname: same-method\ndescription: Synthetic test only\n---\nRead reference.txt before answering.\n")
        (folder / "reference.txt").write_text(reference)
        response = self.client.put("/api/agents/claude", json={"skill_roots": [str(ROOT)]})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post("/api/agents/claude/skills/import", json={"paths": [str(folder)]})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertFalse(data["errors"], data)
        return folder, data["imported"][0]

    def test_01_default_types_and_legacy_settings(self):
        default = self.client.get("/api/settings").json()
        self.assertEqual(default["undo_limit"], 5)
        self.assertIs(type(default["motion_enabled"]), bool)
        self.assertIs(type(default["font_size"]), int)
        with core.connect_db() as db:
            db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('font','serif')")
        migrated = self.client.get("/api/settings").json()
        self.assertEqual(migrated["font"], "serif")
        self.assertEqual(migrated["undo_limit"], 5)

    def test_02_fonts_are_detected_and_unicode_roundtrips(self):
        response = self.client.get("/api/fonts")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        families = [item["family"] for item in result["fonts"]]
        if sys.platform == "darwin":
            self.assertGreater(len(families), 20, result)
        self.assertEqual(len(families), len(set(families)))
        family = next((f for f in families if any(ord(c) > 127 for c in f)), "PingFang SC")
        response = self.style(text_font=family, code_font="Menlo", font_size=18, code_font_size=16, motion_enabled=False, undo_limit=50)
        self.assertEqual(response.status_code, 200, response.text)
        saved = self.client.get("/api/settings").json()
        for key, value in {"text_font": family, "code_font": "Menlo", "font_size": 18, "code_font_size": 16, "motion_enabled": False, "undo_limit": 50}.items():
            self.assertEqual(saved[key], value)

    def test_03_invalid_style_is_atomic(self):
        before = self.client.get("/api/settings").json()
        for key, value in [("undo_limit", 0), ("undo_limit", 51), ("undo_limit", 2.5), ("font_size", 100), ("code_font_size", 0), ("background_image", "https://example.invalid/tracker.png")]:
            with self.subTest(key=key, value=value):
                response = self.style(**{key: value})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.client.get("/api/settings").json(), before)

    def test_04_raster_background_and_saved_reference(self):
        buffer = io.BytesIO()
        Image.new("RGB", (32, 24), "#b9cbbb").save(buffer, format="PNG")
        response = self.client.post("/api/appearance/background", files={"file": ("背景.png", buffer.getvalue(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        asset = response.json()
        self.assertTrue(asset["id"])
        served = self.client.get(asset["url"])
        self.assertEqual(served.status_code, 200)
        self.assertTrue(served.headers["content-type"].startswith("image/"))
        Image.open(io.BytesIO(served.content)).verify()
        self.assertEqual(self.style(background_image=asset["id"]).status_code, 200)
        self.assertEqual(self.client.get("/api/settings").json()["background_image"], asset["id"])
        self.assertEqual(self.style(background_image="").status_code, 200)

    def test_05_background_rejects_active_or_corrupt_files(self):
        tiny = io.BytesIO()
        Image.new("RGB", (1, 1)).save(tiny, format="PNG")
        original = tiny.getvalue()
        header = struct.pack(">II", 25000, 25000) + original[24:29]
        dimensions = original[:16] + header + struct.pack(">I", zlib.crc32(b"IHDR" + header) & 0xffffffff) + original[33:]
        for name, mime, body in [("fake.png", "image/png", b"not an image"), ("vector.svg", "image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'), ("huge.png", "image/png", b"x" * (10 * 1024 * 1024 + 1)), ("dimensions.png", "image/png", dimensions)]:
            with self.subTest(name=name):
                response = self.client.post("/api/appearance/background", files={"file": (name, body, mime)})
                self.assertIn(response.status_code, (400, 413, 415, 422))

    def test_06_cross_agent_uses_upstream_and_all_reference_content(self):
        first_dir, first = self.fixture("a", "SYNTHETIC_REFERENCE_A")
        second_dir, second = self.fixture("b", "SYNTHETIC_REFERENCE_B")
        self.assertNotEqual(first["snapshot_hash"], second["snapshot_hash"])
        hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for folder in (first_dir, second_dir) for p in folder.iterdir() if p.is_file()}
        response = self.client.post("/api/skillhub/mount", json={"agent_id": "codex", "skill_ids": [first["id"], second["id"]]})
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()["skills"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["cross_agent"] for row in rows))
        stored = {p.read_text() for p in (ROOT / "data" / "skillhub").rglob("reference.txt") if p.is_file()}
        self.assertIn("SYNTHETIC_REFERENCE_A", stored)
        self.assertIn("SYNTHETIC_REFERENCE_B", stored)
        for path, digest in hashes.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        again = self.client.post("/api/skillhub/mount", json={"agent_id": "codex", "skill_ids": [first["id"], second["id"]]})
        self.assertEqual(again.status_code, 200, again.text)

    def test_07_skill_scan_has_real_dates_and_missing_mount_fails(self):
        self.fixture("dated", "SYNTHETIC_DATE")
        candidates = self.client.get("/api/agents/claude/skills").json()
        self.assertTrue(candidates)
        self.assertTrue(all(item.get("modified_at") for item in candidates))
        response = self.client.post("/api/skillhub/mount", json={"agent_id": "codex", "skill_ids": ["not-a-skill"]})
        self.assertIn(response.status_code, (400, 404, 409, 422), response.text)

    def test_08_cross_origin_mutations_stay_blocked(self):
        response = self.client.post("/api/skillhub/mount", json={"agent_id": "codex", "skill_ids": []}, headers={"Origin": "https://example.invalid"})
        self.assertEqual(response.status_code, 403)
        response = self.client.put("/api/settings", json={}, headers={"Origin": "https://example.invalid"})
        self.assertEqual(response.status_code, 403)

    def test_09_mcp_command_path_with_spaces_remains_one_executable(self):
        binary = str(ROOT / "MCP tools" / "server")
        definition, reason = config._mcp_parse_definition("workbuddy", "path-test", {"command": binary, "args": ["--version"]})
        self.assertIsNone(reason)
        self.assertEqual(definition["command"], binary)
        self.assertEqual(definition["args"], ["--version"])

    def test_10_native_mcp_metadata_and_import_do_not_store_secret_literals(self):
        native = ROOT / "native-mcp-home"
        (native / ".workbuddy").mkdir(parents=True, exist_ok=True)
        marker = "SYNTHETIC_MCP_CREDENTIAL_DO_NOT_PERSIST_6328"
        path = native / ".workbuddy" / "mcp.json"
        path.write_text(json.dumps({"mcpServers": {"v3-safe-http": {"url": "https://example.invalid/mcp", "headers": {"Authorization": "Bearer " + marker}}}}))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with patch.object(config, "_home", return_value=native):
            response = self.client.get("/api/agents/workbuddy/mcps")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn(marker, response.text)
            rows = response.json()
            self.assertTrue(rows)
            response = self.client.post("/api/agents/workbuddy/mcps/import", json={"ids": [rows[0]["id"]]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn(marker, response.text)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)
        self.assertNotIn(marker.encode(), core.DB_PATH.read_bytes())
        for item in (ROOT / "data" / "skillhub").rglob("*.json"):
            self.assertNotIn(marker, item.read_text(), str(item))

    def test_11_workbuddy_copy_projection_is_idempotent(self):
        _, item = self.fixture("workbuddy-copy", "SYNTHETIC_WORKBUDDY_COPY")
        for _ in range(2):
            response = self.client.post("/api/skillhub/mount", json={"agent_id": "workbuddy", "skill_ids": [item["id"]]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "ready", response.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
