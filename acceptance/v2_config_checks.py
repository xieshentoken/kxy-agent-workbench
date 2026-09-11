"""Isolated V2 configuration acceptance; no real model calls or global writes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


TEMP = Path(tempfile.mkdtemp(prefix="kxy-v2-config-"))
os.environ["KXY_DATA_ROOT"] = str(TEMP / "data")
os.environ["LANGFLOW_CONFIG_DIR"] = str(TEMP / "lfx")
os.environ["DO_NOT_TRACK"] = "true"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import agent_config as config  # noqa: E402
from backend import app as core  # noqa: E402


AGENTS = {"codex", "claude", "opencode", "pi", "hermes", "workbuddy", "deepseek", "grok"}


class ConfigV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core.init_db()
        config.ensure_agent_config_schema()
        cls.workspace = TEMP / "workspace"
        cls.workspace.mkdir(parents=True)
        cls.binary = cls.workspace / "fake-agent"
        cls.binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        cls.binary.chmod(cls.binary.stat().st_mode | stat.S_IXUSR)

    def test_all_profiles_are_seeded_without_synchronous_probe(self):
        profiles = config.list_agent_profiles()
        self.assertEqual({item["id"] for item in profiles}, AGENTS)
        self.assertTrue(all("models" in item for item in profiles))

    def test_model_identity_and_cli_id_payload_contract(self):
        manual = config.create_agent_model(
            {
                "cli_id": "codex",
                "model": "same-synthetic-model",
                "alias": "Manual fixture",
                "source": "manual",
                "efforts": ["low", "high"],
                "default_effort": "low",
            }
        )
        self.assertEqual(manual["agent_id"], "codex")
        self.assertEqual(manual["cli_id"], "codex")

        credential_id = "credential-synthetic-v2"
        with core.connect_db() as db:
            db.execute(
                "INSERT INTO credentials(id, provider, credential_ref, endpoint, env_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    credential_id,
                    "openai",
                    "opaque-keychain-ref",
                    "https://example.invalid/v1",
                    "OPENAI_API_KEY",
                    core.utc_now(),
                ),
            )
        api = config.create_agent_model(
            {
                "cli_id": "codex",
                "model": "same-synthetic-model",
                "alias": "API fixture",
                "source": "api",
                "credential_id": credential_id,
            }
        )
        self.assertNotEqual(manual["id"], api["id"])
        catalog = json.dumps(config.list_agent_models(), ensure_ascii=False)
        self.assertNotIn("opaque-keychain-ref", catalog)
        self.assertNotIn("SYNTHETIC_NOT_A_REAL_API_CREDENTIAL", catalog)

        native_record = config._native_model_record(
            "codex",
            "refreshable-synthetic-model",
            alias="Native display name",
            efforts=["low", "medium"],
            default_effort="low",
            discovery_source="synthetic discovery",
        )
        self.assertIsNotNone(native_record)
        config._store_native_records("codex", [native_record])
        changed = config.update_agent_model(
            native_record["id"],
            {"alias": "Pinned native alias", "default_effort": "low"},
        )
        self.assertEqual(changed["alias"], "Pinned native alias")
        with self.assertRaisesRegex(config.AgentConfigError, "能力由 discovery 管理"):
            config.update_agent_model(native_record["id"], {"efforts": ["low", "medium", "high"]})
        refreshed = config._native_model_record(
            "codex",
            "refreshable-synthetic-model",
            alias="New CLI display name",
            efforts=["low", "medium", "high"],
            default_effort="low",
            discovery_source="synthetic discovery v2",
        )
        config._store_native_records("codex", [refreshed])
        saved = next(item for item in config.list_agent_models() if item["id"] == native_record["id"])
        self.assertEqual(saved["alias"], "Pinned native alias")
        self.assertEqual(saved["default_effort"], "low")
        selected = config.update_agent_model(native_record["id"], {"default_effort": "high"})
        self.assertEqual(selected["default_effort"], "high")
        with self.assertRaisesRegex(config.AgentConfigError, "native 模型不能绑定凭据"):
            config.update_agent_model(native_record["id"], {"credential_id": credential_id})

        binding = config.resolve_model_binding({"cli": "codex", "model_ref": api["id"]})
        self.assertEqual(binding["model_ref"], api["id"])
        self.assertEqual(binding["credential_id"], credential_id)
        self.assertEqual(binding["credential_env_name"], "OPENAI_API_KEY")
        with self.assertRaisesRegex(config.AgentConfigError, "清除旧 credential_id"):
            config.resolve_model_binding(
                {"cli": "codex", "model_ref": manual["id"], "credential_id": credential_id}
            )

    def test_documented_native_model_and_effort_parsers(self):
        claude_help = """--model <model> Model alias (e.g. 'fable', 'opus', or 'sonnet') or full 'claude-fable-5'.
--effort <level> (low, medium, high, xhigh, max)
"""
        with patch.object(config, "_read_claude_native_env", return_value={}):
            claude = config._native_records("claude", help_text=claude_help)
        self.assertEqual({item["model"] for item in claude}, {"fable", "opus", "sonnet", "claude-fable-5"})
        self.assertTrue(all(item["cli_id"] == "claude" for item in claude))
        self.assertEqual({"low", "medium", "high", "xhigh", "max"}, set(claude[0]["efforts"]))
        self.assertTrue(all(item["default_effort"] is None for item in claude))

        workbuddy_help = """--model <model>
Currently supported: (auto, glm-5v-turbo, glm-5.1, kimi-k2.5, deepseek-v3-2-volc)
--effort <level> (minimal, low, medium, high, xhigh, max)
"""
        workbuddy = config._native_records("workbuddy", help_text=workbuddy_help)
        self.assertEqual(
            {item["model"] for item in workbuddy},
            {"auto", "glm-5v-turbo", "glm-5.1", "kimi-k2.5", "deepseek-v3-2-volc"},
        )
        self.assertEqual({"minimal", "low", "medium", "high", "xhigh", "max"}, set(workbuddy[0]["efforts"]))

        pi = config._native_records(
            "pi",
            '{"models":[{"id":"openai/gpt-4o","thinking":["low","high"]},'
            '{"id":"anthropic/claude-sonnet-4","thinking":["medium"]}]}',
            "--thinking <level> Set thinking level: off, minimal, low, medium, high, xhigh, max",
        )
        self.assertEqual({item["model"] for item in pi}, {"openai/gpt-4o", "anthropic/claude-sonnet-4"})
        self.assertTrue(all(item["cli_id"] == "pi" for item in pi))
        self.assertEqual(config._parse_pi_models("/opt/homebrew/lib/node_modules/pi/docs/models.md\n"), [])

        pi_home = TEMP / "pi-native-home"
        pi_agent_root = pi_home / ".pi" / "agent"
        pi_agent_root.mkdir(parents=True)
        (pi_agent_root / "models.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "openai": {
                            "models": [
                                {
                                    "id": "configured/model",
                                    "name": "Configured model",
                                    "thinkingLevelMap": {"low": "low", "high": "high", "max": None},
                                    "apiKey": "DO_NOT_COPY",
                                }
                            ]
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        (pi_agent_root / "auth.json").write_text(
            json.dumps({"openai": {"type": "api_key", "key": "DO_NOT_COPY"}}),
            encoding="utf-8",
        )
        with patch.object(config, "_home", return_value=pi_home):
            configured_pi = config._read_pi_models(["low", "high"])
            self.assertEqual(config._read_pi_auth_provider_ids(), ["openai"])
            probe_env = config._probe_env(TEMP / "pi-probe")
        self.assertEqual({item["model"] for item in configured_pi}, {"openai/configured/model"})
        self.assertEqual(configured_pi[0]["efforts"], ["low", "high"])
        self.assertNotIn("DO_NOT_COPY", json.dumps(configured_pi, ensure_ascii=False))
        probe_auth = json.loads((TEMP / "pi-probe" / "pi" / "auth.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(probe_auth), ["openai"])
        self.assertEqual(probe_env["PI_CODING_AGENT_DIR"], str(TEMP / "pi-probe" / "pi"))

        opencode = config._native_records("opencode", "openai/gpt-4o\nanthropic/claude-sonnet-4\n")
        self.assertEqual({item["model"] for item in opencode}, {"openai/gpt-4o", "anthropic/claude-sonnet-4"})

    def test_hermes_reader_whitelists_model_fields_only(self):
        native_home = TEMP / "hermes-home"
        catalog_dir = native_home / ".hermes" / "cache"
        catalog_dir.mkdir(parents=True)
        (catalog_dir / "model_catalog.json").write_text(
            json.dumps(
                {
                    "providers": {
                        "openrouter": {"models": [{"id": "anthropic/claude-sonnet-4", "apiKey": "DO_NOT_COPY"}]},
                        "nous": {"models": [{"id": "deepseek/deepseek-v4-flash"}]},
                    }
                }
            ),
            encoding="utf-8",
        )
        (native_home / ".hermes").joinpath("config.yaml").write_text(
            "model:\n  default: configured-model\n  provider: deepseek\n  base_url: https://secret.invalid\n",
            encoding="utf-8",
        )
        with patch.object(config, "_home", return_value=native_home):
            records = config._read_hermes_models()
        models = {item["model"] for item in records}
        self.assertEqual(models, {"anthropic/claude-sonnet-4", "deepseek/deepseek-v4-flash", "configured-model"})
        serialized = json.dumps(records, ensure_ascii=False)
        self.assertNotIn("DO_NOT_COPY", serialized)
        self.assertNotIn("secret.invalid", serialized)
        self.assertTrue(any("config.yaml" in item["discovery_source"] for item in records))

    def test_discovery_uses_only_version_help_and_catalog_commands(self):
        help_text = "--thinking <level> (off, low, high)"
        calls: list[list[str]] = []

        def fake_probe(argv, root, **kwargs):
            calls.append(list(argv))
            if "--version" in argv:
                return 0, "pi fixture 1.0\n", ""
            if "--help" in argv:
                return 0, help_text, ""
            if "--list-models" in argv:
                return 0, "openai/gpt-4o\n", ""
            self.fail(f"unexpected probe: {argv}")

        with patch.object(config, "_configured_executable", return_value=str(self.binary)):
            with patch.object(config, "_probe", side_effect=fake_probe):
                profile = config.discover_agent("pi")
        self.assertEqual(profile["status"], "READY")
        self.assertTrue(profile["capabilities"]["model_discovery"])
        self.assertEqual({item["model"] for item in profile["models"]}, {"openai/gpt-4o"})
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("--help" in call or "--version" in call or "--list-models" in call for call in calls))

    def test_skill_scan_import_and_safe_symlink_boundary(self):
        skill_root = TEMP / "native-skills"
        skill = skill_root / "research" / "fixture-skill"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: fixture-skill\ndescription: A bounded fixture skill\n---\n\nUse only fixture input.\n",
            encoding="utf-8",
        )
        external = TEMP / "outside-skill"
        external.mkdir()
        (external / "SKILL.md").write_text(
            "---\nname: outside-skill\ndescription: Should not be scanned\n---\n",
            encoding="utf-8",
        )
        try:
            (skill_root / "external-link").symlink_to(external, target_is_directory=True)
            (skill_root / "loop").symlink_to(skill_root, target_is_directory=True)
        except OSError:
            self.skipTest("filesystem does not support symlink fixtures")
        config.update_agent_profile("pi", {"skill_roots": [str(skill_root)]})
        scanned = config.scan_agent_skills("pi")
        self.assertEqual([item["name"] for item in scanned], ["fixture-skill"])
        self.assertEqual(scanned[0]["category"], "research")
        result = config.import_agent_skills("pi", [str(skill)])
        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["imported"][0]["name"], "fixture-skill")
        with core.connect_db() as db:
            row = db.execute("SELECT metadata FROM skills WHERE name=?", ("fixture-skill",)).fetchone()
        self.assertIsNotNone(row)
        self.assertIn("native_agent", row["metadata"])

    def test_picker_cancel_and_argv_are_bounded(self):
        fake = SimpleNamespace(returncode=0, stdout=config._PICKER_CANCELLED + "\n", stderr="")
        with patch.object(config.os.sys, "platform", "darwin"):
            with patch.object(config.subprocess, "run", return_value=fake) as run:
                result = config.run_native_picker("folder")
        self.assertEqual(result, {"cancelled": True})
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], "/usr/bin/osascript")
        self.assertEqual(argv[1], "-e")
        self.assertEqual(argv[3:], ["--", "folder"])
        with self.assertRaises(config.AgentConfigError):
            config.run_native_picker("folder; touch /tmp/not-allowed")

    def test_headless_argv_env_and_parser_have_no_bypass_or_secret(self):
        attachment = self.workspace / "fixture.md"
        attachment.write_text("fixture", encoding="utf-8")
        skill = self.workspace / "skill"
        skill.mkdir()
        banned = {"--dangerously-skip-permissions", "--yolo", "--api-key", "--skip-permissions", "bypassPermissions"}
        for agent_id in ("codex", "claude", "opencode", "pi", "hermes", "workbuddy"):
            effort = None if agent_id == "hermes" else "high"
            argv = config.build_headless_command(
                agent_id,
                "fixture prompt --literal",
                self.workspace,
                executable=str(self.binary),
                model="fixture/model",
                effort=effort,
                attachments=[attachment],
                skills=[skill],
                network=False,
            )
            self.assertTrue(set(argv).isdisjoint(banned), (agent_id, argv))
            self.assertTrue(all(isinstance(item, str) for item in argv))
            if agent_id == "opencode":
                self.assertEqual(argv[-2:], ["--", "fixture prompt --literal"])
                file_index = argv.index("--file")
                self.assertEqual(argv[file_index + 1], str(attachment.resolve()))
                self.assertLess(file_index, argv.index("--"))
            if agent_id in {"claude", "workbuddy"}:
                self.assertIn("--verbose", argv)
        env = config.prepare_headless_environment(
            "pi",
            self.workspace,
            base_env={"PATH": "/usr/bin", "HTTPS_PROXY": "http://proxy.invalid", "SYNTHETIC_SECRET": "never"},
            network=False,
        )
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertNotIn("SYNTHETIC_SECRET", env)
        self.assertEqual(env["PI_OFFLINE"], "1")
        claude_env = config.prepare_headless_environment("claude", self.workspace, network=False)
        self.assertTrue(claude_env["CLAUDE_CONFIG_DIR"].endswith("/.cli-state/claude"))
        self.assertEqual(claude_env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"], "1")
        self.assertTrue(claude_env["CLAUDE_CODE_DEBUG_LOGS_DIR"].endswith("/.cli-state/claude/debug"))
        hermes_env = config.prepare_headless_environment("hermes", self.workspace, network=False)
        self.assertTrue(hermes_env["HERMES_HOME"].endswith("/.cli-state/hermes"))
        self.assertTrue(hermes_env["TMPDIR"].endswith("/.cli-state/hermes/tmp"))
        workbuddy_env = config.prepare_headless_environment("workbuddy", self.workspace, network=False)
        self.assertTrue(workbuddy_env["CODEBUDDY_CONFIG_DIR"].endswith("/.cli-state/workbuddy"))
        self.assertEqual(workbuddy_env["CODEBUDDY_DISABLE_COMPILE_CACHE"], "1")
        self.assertTrue(workbuddy_env["WORKBUDDY_DATA_DIR"].endswith("/.cli-state/workbuddy"))
        parsed = config.parse_final_output(
            "codex",
            [
                json.dumps({"type": "item.completed", "item": {"type": "reasoning", "text": "ignore"}}),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "final fixture"}}),
            ],
        )
        self.assertEqual(parsed["text"], "final fixture")
        self.assertEqual(config.parse_final_output("hermes", ["line 1", "line 2"])["text"], "line 1\nline 2")

    def test_native_auth_references_are_local_and_explicit_binding_wins(self):
        native_home = TEMP / "native-auth-home"
        (native_home / ".claude").mkdir(parents=True)
        (native_home / ".local" / "share" / "opencode").mkdir(parents=True)
        (native_home / ".hermes").mkdir(parents=True)
        (native_home / ".codebuddy").mkdir(parents=True)
        (native_home / ".claude" / "settings.json").write_text(
            json.dumps(
                {
                    "env": {
                        "ANTHROPIC_AUTH_TOKEN": "NATIVE_TOKEN_FIXTURE",
                        "ANTHROPIC_BASE_URL": "https://native.example.invalid",
                        "ANTHROPIC_MODEL": "claude-native-direct",
                        "ANTHROPIC_DEFAULT_SONNET_MODEL": "claude-native-sonnet",
                        "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME": "Native Sonnet",
                        "IGNORED_NATIVE_SETTING": "DO_NOT_COPY",
                    },
                    "hooks": {"ignored": "DO_NOT_COPY"},
                }
            ),
            encoding="utf-8",
        )
        (native_home / ".local" / "share" / "opencode" / "auth.json").write_text(
            "NATIVE_OPENCODE_AUTH_FIXTURE", encoding="utf-8"
        )
        (native_home / ".hermes" / ".env").write_text("NATIVE_HERMES_SECRET_FIXTURE\n", encoding="utf-8")
        (native_home / ".hermes" / "config.yaml").write_text("model:\n  default: native/model\n", encoding="utf-8")
        (native_home / ".codebuddy" / "settings.json").write_text(
            json.dumps(
                {
                    "env": {
                        "CODEBUDDY_AUTH_TOKEN": "NATIVE_WORKBUDDY_TOKEN_FIXTURE",
                        "CODEBUDDY_BASE_URL": "https://workbuddy.example.invalid",
                        "IGNORED_NATIVE_SETTING": "DO_NOT_COPY",
                    }
                }
            ),
            encoding="utf-8",
        )
        isolated = TEMP / "native-auth-workspace"
        isolated.mkdir()
        with patch.object(config, "_home", return_value=native_home):
            claude_env = config.prepare_headless_environment("claude", isolated, base_env={"PATH": "/usr/bin"})
            self.assertEqual(claude_env["ANTHROPIC_AUTH_TOKEN"], "NATIVE_TOKEN_FIXTURE")
            self.assertEqual(claude_env["ANTHROPIC_MODEL"], "claude-native-direct")
            self.assertNotIn("IGNORED_NATIVE_SETTING", claude_env)
            opencode_env = config.prepare_headless_environment("opencode", isolated, base_env={"PATH": "/usr/bin"})
            auth_link = isolated / ".cli-state" / "opencode" / "data" / "opencode" / "auth.json"
            self.assertTrue(auth_link.is_symlink())
            self.assertEqual(auth_link.resolve(), (native_home / ".local" / "share" / "opencode" / "auth.json").resolve())
            self.assertTrue(opencode_env["XDG_DATA_HOME"].endswith("/.cli-state/opencode/data"))
            hermes_env = config.prepare_headless_environment("hermes", isolated, base_env={"PATH": "/usr/bin"})
            self.assertTrue((Path(hermes_env["HERMES_HOME"]) / ".env").is_symlink())
            self.assertTrue((Path(hermes_env["HERMES_HOME"]) / "config.yaml").is_symlink())
            workbuddy_env = config.prepare_headless_environment("workbuddy", isolated, base_env={"PATH": "/usr/bin"})
            self.assertEqual(workbuddy_env["CODEBUDDY_AUTH_TOKEN"], "NATIVE_WORKBUDDY_TOKEN_FIXTURE")
            self.assertNotIn("IGNORED_NATIVE_SETTING", workbuddy_env)

            explicit_workspace = TEMP / "explicit-auth-workspace"
            explicit_workspace.mkdir()
            with patch.object(
                config,
                "_credential_env",
                return_value=("ANTHROPIC_API_KEY", "https://explicit.example.invalid", "EXPLICIT_FIXTURE"),
            ):
                explicit_claude = config.prepare_headless_environment(
                    "claude", explicit_workspace, credential_id="explicit-credential", base_env={"PATH": "/usr/bin"}
                )
                self.assertNotIn("ANTHROPIC_AUTH_TOKEN", explicit_claude)
                self.assertNotIn("ANTHROPIC_MODEL", explicit_claude)
                self.assertEqual(explicit_claude["ANTHROPIC_BASE_URL"], "https://explicit.example.invalid")
                explicit_opencode = config.prepare_headless_environment(
                    "opencode", explicit_workspace, credential_id="explicit-credential", base_env={"PATH": "/usr/bin"}
                )
                self.assertFalse(
                    (explicit_workspace / ".cli-state" / "opencode" / "data" / "opencode" / "auth.json").exists()
                )
                explicit_hermes = config.prepare_headless_environment(
                    "hermes", explicit_workspace, credential_id="explicit-credential", base_env={"PATH": "/usr/bin"}
                )
                self.assertFalse((Path(explicit_hermes["HERMES_HOME"]) / ".env").exists())
                explicit_workbuddy = config.prepare_headless_environment(
                    "workbuddy", explicit_workspace, credential_id="explicit-credential", base_env={"PATH": "/usr/bin"}
                )
                self.assertNotIn("CODEBUDDY_AUTH_TOKEN", explicit_workbuddy)

    def test_deepseek_without_headless_profile_is_explicitly_unavailable(self):
        with patch.object(config, "_dsh_headless_present", return_value=False):
            with patch.object(config, "_configured_executable", return_value=str(self.binary)):
                profile = config.discover_agent("deepseek")
        self.assertFalse(profile["available"])
        self.assertEqual(profile["status"], "UNAVAILABLE")
        self.assertIn("headless", profile["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
