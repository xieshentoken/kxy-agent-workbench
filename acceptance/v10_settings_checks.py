"""Focused V10 settings checks using isolated data and synthetic CLI responses.

These checks cover the stateful contracts behind the settings UI.  They never
read the host login files, call a model, or store a credential payload.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


TEMP = Path(tempfile.mkdtemp(prefix="kxy-v10-settings-checks-"))
os.environ.update(
    KXY_DATA_ROOT=str(TEMP / "data"),
    LANGFLOW_CONFIG_DIR=str(TEMP / "lfx"),
    DO_NOT_TRACK="true",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend import agent_config as cfg
from backend import app as core


class V10SettingsChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.context = TestClient(core.app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.context.__exit__(None, None, None)

    def setUp(self) -> None:
        with core.connect_db() as db:
            db.execute("DELETE FROM agent_models")
            db.execute(
                "UPDATE settings SET value=? WHERE key=?",
                (json.dumps({"mode": "cli", "agent_id": "codex"}), "default_analyzer"),
            )
            db.execute(
                "UPDATE settings SET value=? WHERE key=?",
                (
                    json.dumps(
                        {
                            "export_formats": [],
                            "allowed_file_extensions": [],
                            "json_mode": "full",
                        }
                    ),
                    "output_defaults",
                ),
            )

    def test_01_failed_native_catalog_keeps_last_valid_models(self) -> None:
        old = cfg._native_model_record(
            "opencode",
            "v10-old-model",
            alias="V10 old",
            efforts=["low"],
            default_effort="low",
            discovery_source="V10 synthetic catalog",
        )
        assert old is not None
        cfg._store_native_records("opencode", [old])
        discovered_at = "2026-09-09T01:02:03+00:00"
        with core.connect_db() as db:
            db.execute(
                "UPDATE agent_profiles SET discovered_at=? WHERE id=?",
                (discovered_at, "opencode"),
            )

        def probe(argv: list[str], _root: Path) -> tuple[int, str, str]:
            if argv[-1] == "--version":
                return 0, "opencode 10.0 synthetic\n", ""
            if argv[-1] == "--help":
                return 0, "run --format json\n", ""
            return 1, "", "catalog token=V10_SECRET\n"

        with (
            patch.object(cfg, "_presence", return_value=(True, "READY", None)),
            patch.object(cfg, "_configured_executable", return_value="/synthetic/opencode"),
            patch.object(cfg, "_probe", side_effect=probe),
        ):
            profile = cfg.discover_agent("opencode")

        models = [item for item in profile["models"] if item["id"] == old["id"]]
        self.assertEqual(len(models), 1)
        self.assertEqual(profile["discovered_at"], discovered_at)
        self.assertIn("保留上次有效目录", profile["message"] or "")
        self.assertNotIn("V10_SECRET", json.dumps(profile, ensure_ascii=False))

    def test_02_login_status_is_boolean_and_secret_free(self) -> None:
        logged_in = CompletedProcess(
            ["codex", "login", "status"],
            0,
            stdout="Logged in using account@example.invalid token=V10_SECRET\n",
            stderr="",
        )
        not_logged_in = CompletedProcess(
            ["codex", "login", "status"],
            1,
            stdout="Not logged in\nLogged in using stale text token=V10_SECRET\n",
            stderr="",
        )
        with (
            patch.object(cfg, "_configured_executable", return_value="/synthetic/codex"),
            patch.object(cfg.subprocess, "run", side_effect=[logged_in, not_logged_in]),
        ):
            first = cfg.check_agent_login_status("codex")
            second = cfg.check_agent_login_status("codex")

        self.assertEqual(first["status"], "verified")
        self.assertTrue(first["verified"])
        self.assertEqual(second["status"], "not_logged_in")
        self.assertFalse(second["verified"])
        self.assertEqual(first["credential_state"], "not_inspected")
        public = cfg.get_agent_profile("codex")
        self.assertEqual(public["login"]["status"], "not_logged_in")
        self.assertNotIn("V10_SECRET", json.dumps({"first": first, "second": second, "profile": public}))

    def test_03_refresh_runs_login_after_discovery_error_and_isolates_bulk_failures(self) -> None:
        login_calls: list[str] = []

        def failed_discovery(_agent_id: str) -> dict[str, object]:
            raise RuntimeError("credential token=V10_SECRET")

        def independent_login(agent_id: str) -> dict[str, object]:
            login_calls.append(agent_id)
            return {"status": "unsupported", "verified": None}

        with (
            patch.object(cfg, "discover_agent", side_effect=failed_discovery),
            patch.object(cfg, "check_agent_login_status", side_effect=independent_login),
        ):
            partial = cfg.refresh_agent("hermes")

        self.assertEqual(login_calls, ["hermes"])
        self.assertIn("发现阶段", partial["refresh_error"])
        self.assertNotIn("V10_SECRET", json.dumps(partial, ensure_ascii=False))

        def bulk_refresh(agent_id: str) -> dict[str, object]:
            if agent_id == "claude":
                raise cfg.AgentConfigError("status token=V10_SECRET")
            return {"id": agent_id, "refresh_error": None}

        with patch.object(cfg, "refresh_agent", side_effect=bulk_refresh):
            result = cfg.refresh_agents(["codex", "claude"])

        self.assertEqual([item["id"] for item in result["results"]], ["codex", "claude"])
        self.assertTrue(result["results"][0]["ok"])
        self.assertFalse(result["results"][1]["ok"])
        self.assertNotIn("V10_SECRET", json.dumps(result, ensure_ascii=False))

    def test_04_default_refs_and_output_defaults_survive_unrelated_updates(self) -> None:
        model = cfg.create_agent_model(
            {
                "agent_id": "codex",
                "cli_id": "codex",
                "model": "v10-default-model",
                "alias": "V10 default alias",
                "source": "manual",
                "efforts": ["low", "high"],
                "default_effort": "low",
            }
        )
        payload = {
            "default_analyzer": {
                "mode": "model",
                "agent_id": "codex",
                "model_ref": model["id"],
                "effort": "high",
            },
            "output_defaults": {
                "export_formats": ["text", "json"],
                "allowed_file_extensions": [".txt"],
                "json_mode": "content",
            },
        }
        saved = self.client.put("/api/settings", json=payload)
        self.assertEqual(saved.status_code, 200, saved.text)
        settings = saved.json()
        self.assertEqual(settings["default_analyzer"]["model_ref"], model["id"])
        self.assertEqual(settings["default_analyzer"]["effort"], "high")
        self.assertEqual(settings["default_analyzer"]["status"], "available")
        self.assertEqual(settings["output_defaults"]["json_mode"], "content")

        unrelated = self.client.put("/api/settings", json={"palette": "mist"})
        self.assertEqual(unrelated.status_code, 200, unrelated.text)
        self.assertEqual(unrelated.json()["default_analyzer"]["model_ref"], model["id"])
        self.assertEqual(unrelated.json()["output_defaults"]["allowed_file_extensions"], [".txt"])

        cfg.delete_agent_model(model["id"])
        missing = self.client.get("/api/settings")
        self.assertEqual(missing.status_code, 200)
        self.assertEqual(missing.json()["default_analyzer"]["status"], "missing")
        self.assertEqual(missing.json()["default_analyzer"]["model_ref"], model["id"])
        preserved = self.client.put("/api/settings", json={"palette": "paper"})
        self.assertEqual(preserved.status_code, 200, preserved.text)
        self.assertEqual(preserved.json()["default_analyzer"]["status"], "missing")

        explicit_missing = self.client.put("/api/settings", json=payload)
        self.assertIn(explicit_missing.status_code, (400, 422))
        invalid_extension = self.client.put(
            "/api/settings",
            json={"output_defaults": {"allowed_file_extensions": [".exe"]}},
        )
        self.assertIn(invalid_extension.status_code, (400, 422))

    def test_05_default_prompt_round_trips_empty_and_legacy_fallback(self) -> None:
        initial = self.client.get("/api/settings")
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["default_analyzer"]["prompt"], core.DEFAULT_ANALYZER_PROMPT)

        custom = "只输出可核查事实；不要补写未提供的结论。"
        saved = self.client.put(
            "/api/settings",
            json={"default_analyzer": {"mode": "cli", "agent_id": "claude", "prompt": custom}},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["default_analyzer"]["prompt"], custom)

        changed_agent = self.client.put(
            "/api/settings",
            json={"default_analyzer": {"mode": "cli", "agent_id": "codex"}},
        )
        self.assertEqual(changed_agent.status_code, 200, changed_agent.text)
        self.assertEqual(changed_agent.json()["default_analyzer"]["prompt"], custom)

        empty = self.client.put(
            "/api/settings",
            json={"default_analyzer": {"mode": "cli", "agent_id": "codex", "prompt": ""}},
        )
        self.assertEqual(empty.status_code, 200, empty.text)
        self.assertEqual(empty.json()["default_analyzer"]["prompt"], "")
        appearance = self.client.put("/api/settings", json={"palette": "mist"})
        self.assertEqual(appearance.status_code, 200, appearance.text)
        self.assertEqual(appearance.json()["default_analyzer"]["prompt"], "")

        with core.connect_db() as db:
            db.execute(
                "UPDATE settings SET value=? WHERE key=?",
                (json.dumps({"mode": "cli", "agent_id": "codex"}), "default_analyzer"),
            )
        legacy = self.client.get("/api/settings")
        self.assertEqual(legacy.status_code, 200)
        self.assertEqual(legacy.json()["default_analyzer"]["prompt"], core.DEFAULT_ANALYZER_PROMPT)


if __name__ == "__main__":
    unittest.main()
