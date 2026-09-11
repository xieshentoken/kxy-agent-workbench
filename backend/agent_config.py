"""Global agent/model configuration and bounded native CLI discovery.

The module deliberately keeps the integration surface small.  It owns the
agent profile/model tables and an ``APIRouter``; the runtime still owns LFX
scheduling, process supervision, artifact handling and run snapshots.

Nothing in this module calls a model.  Native discovery is limited to version,
help and (where the CLI documents it) model-catalog commands executed with a
temporary home/config directory.  Existing kxy helpers are imported lazily so
that this module can be included by ``backend.app`` without a circular import.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from fastapi import APIRouter, HTTPException


AGENT_IDS = (
    "codex",
    "claude",
    "opencode",
    "pi",
    "hermes",
    "workbuddy",
    "deepseek",
)
MODEL_SOURCES = {"native", "api", "manual"}
EFFORT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
EXECUTABLE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+@-]{0,127}$")
MAX_PROFILE_ROOTS = 16
MAX_SKILL_CANDIDATES = 200
MAX_SKILL_DEPTH = 8
MAX_SKILL_FILES = 400
MAX_SKILL_BYTES = 20 * 1024 * 1024
MAX_SKILL_TEXT_FILES = 160
MAX_SKILL_TEXT_BYTES = 2 * 1024 * 1024
MAX_SKILL_TEXT_FILE_BYTES = 512 * 1024
MAX_DISCOVERY_DIRS = 5_000
MAX_DISCOVERY_BYTES = 50 * 1024 * 1024
MAX_PROBE_OUTPUT = 200_000
MAX_FINAL_OUTPUT = 250_000
PROBE_TIMEOUT = 8.0
PICKER_TIMEOUT = 60.0
DEPENDENCY_CHECKER_VERSION = "kxy-v15-skillhub-diagnostics-1"
DEPENDENCY_CHECK_SUCCESS_TTL = 24 * 60 * 60
DEPENDENCY_CHECK_PENDING_TTL = 60
DEPENDENCY_CHECK_MAX_ROWS = 1000
LOGIN_STATUS_COMMANDS: dict[str, tuple[str, ...]] = {
    # These two read-only subcommands were confirmed from the installed CLI
    # help on the target host.  Other CLIs stay explicitly unknown/unsupported
    # instead of guessing an auth command.
    "codex": ("login", "status"),
    "claude": ("auth", "status"),
}

# V3 SkillHub integration is deliberately pinned and isolated.  The vendored
# package is the unmodified upstream implementation; KXY-specific checks and
# compatibility normalization live below this module instead of in the vendor
# tree.
SKILLHUB_UPSTREAM_COMMIT = "8ae72075fdafb1d9dda5f3a232fd9fd438d6e485"
SKILLHUB_SUPPORTED_AGENTS = frozenset(
    {"pi", "codex", "opencode", "workbuddy", "claude", "hermes", "grok"}
)
SKILLHUB_MCP_GENERATORS = frozenset({"codex", "claude", "opencode", "workbuddy"})
SKILLHUB_TIMEOUT = 12.0
SKILLHUB_MAX_OUTPUT = 120_000
SKILLHUB_VENDOR_ROOT = Path(__file__).resolve().parents[1] / "vendor" / "skillhub"
_SKILLHUB_PROJECTION_MARKER = ".skillhub-projection.json"
_SKILLHUB_UPSTREAM_BLOBS = {
    "LICENSE": "c0e20fa1079d17da42dea3216665c5668e59c9a9",
    "skillhub/__init__.py": "858dba36a7836b420d264595863872bce28b4a23",
    "skillhub/__main__.py": "f37a3535a28e9893a89fc06d2a7e3b240bc66f27",
    "skillhub/adapters.py": "e495104ff45e1e5eba6d44ea492501c4dfee1cb7",
    "skillhub/cli.py": "0446effd7fe7d99fb56b494dc2159eba2b95efd1",
    "skillhub/config.py": "8af9fedb8f5bd4a2547ae0d29b3be1b0ead03bed",
    "skillhub/mcp.py": "2907e6128e0515c16a529a14c674925068ac2fe8",
    "skillhub/scan.py": "dad1e4ec4866ef9b3d52bc6d07c2a390b2004570",
    "skillhub/store.py": "6ce585f3db69a01757738ac0739f3537b31f9dfc",
    "skillhub/gui.html": "540750904befe982f00c1508286650e7c215d9e8",
    "skillhub/webgui.py": "0da72319f29d5dbd22117347652432e2a9a96518",
}
_SKILLHUB_AGENT_ENV_IDS = tuple(sorted(set(SKILLHUB_SUPPORTED_AGENTS) | {"deepseek"}))
_DEPENDENCY_CHECK_LOCK = threading.RLock()
_RUNTIME_NODE_SHEBANG_RE = re.compile(r"(?:^|/)(?:env\s+)?node(?:\s|$)", re.IGNORECASE)
_MCP_ENV_REF_RE = re.compile(r"^(?:\{\{env:|\{env:|\$\{)([A-Za-z_][A-Za-z0-9_]*)(?:\}\}|\})$")
_MCP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MCP_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MCP_SECRET_KEY_RE = re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key|private[_-]?key)")
_MCP_ENV_ANY_RE = re.compile(
    r"\{\{env:([A-Za-z_][A-Za-z0-9_]*)\}\}|\{env:([A-Za-z_][A-Za-z0-9_]*)\}|\$\{([A-Za-z_][A-Za-z0-9_]*)\}"
)
_MCP_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MCP_SENSITIVE_ARG_RE = re.compile(r"^--?(?:api[_-]?key|token|secret|password|authorization)$", re.IGNORECASE)
_MCP_SENSITIVE_ARG_VALUE_RE = re.compile(r"^--?(?:api[_-]?key|token|secret|password|authorization)=", re.IGNORECASE)
MCP_MAX_CONFIG_BYTES = 8 * 1024 * 1024
MCP_MAX_SERVERS = 100


def _home() -> Path:
    return Path.home()


def _dsh_home() -> Path:
    configured = os.environ.get("DSH_HOME", "").strip()
    return Path(configured).expanduser().resolve() if configured else (_home() / "Documents" / "DSH").resolve()


def _workbuddy_binary() -> Path:
    return Path(
        "/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/bin/codebuddy"
    )


AGENT_PRESETS: dict[str, dict[str, Any]] = {
    "codex": {
        "label": "Codex",
        "executable": "codex",
        "executable_candidates": ("codex",),
        "skill_roots": (str(_home() / ".codex" / "skills"),),
        "headless_command": "codex exec --json",
    },
    "claude": {
        "label": "Claude Code",
        "executable": "claude",
        "executable_candidates": ("claude",),
        "skill_roots": (str(_home() / ".claude" / "skills"),),
        "headless_command": "claude -p --output-format stream-json --verbose",
    },
    "opencode": {
        "label": "OpenCode",
        "executable": "opencode",
        "executable_candidates": ("opencode",),
        "skill_roots": (str(_home() / ".config" / "opencode" / "skills"),),
        "headless_command": "opencode run --format json",
    },
    "pi": {
        "label": "pi",
        "executable": "pi",
        "executable_candidates": ("pi",),
        "skill_roots": (str(_home() / ".agents" / "skills"),),
        "headless_command": "pi --print --mode json",
    },
    "grok": {
        "label": "Grok Build",
        "executable": "grok",
        "executable_candidates": ("grok",),
        # Matches the upstream SkillHub grok adapter: ~/.grok/skills, symlink
        # projection.  Grok also reads ~/.claude/skills and ~/..cursor/skills by
        # default, but only its own native directory is projected here so that
        # SkillHub's ledger accounts for every link it creates.
        "skill_roots": (str(_home() / ".grok" / "skills"),),
        "headless_command": "grok --cwd <workspace> --output-format streaming-json -p <prompt>",
    },
    "hermes": {
        "label": "Hermes",
        "executable": "hermes",
        "executable_candidates": ("hermes", str(_home() / ".local" / "bin" / "hermes")),
        "skill_roots": (
            str(_home() / ".hermes" / "skills"),
            str(_home() / ".hermes" / "hermes-agent" / "skills"),
            str(
                _home()
                / "Library"
                / "Application Support"
                / "cn.org.hermesagent.desktop"
                / "runtime"
                / "hermes-home"
                / "skills"
            ),
        ),
        "headless_command": "hermes -z",
    },
    "workbuddy": {
        "label": "WorkBuddy",
        "executable": "workbuddy",
        "executable_candidates": (
            "workbuddy",
            "workbuddy-cli",
            "cwb",
            "codebuddy",
            "cbc",
            str(_workbuddy_binary()),
        ),
        "skill_roots": (str(_home() / ".workbuddy" / "skills"),),
        "headless_command": "codebuddy -p --output-format stream-json --verbose",
    },
    "deepseek": {
        "label": "DeepSeek Harness",
        "executable": "dsh",
        "executable_candidates": (
            "dsh",
            str(_dsh_home() / "profiles" / "web" / "node_modules" / ".bin" / "dsh"),
        ),
        "skill_roots": (str(_dsh_home() / "profiles" / "headless" / "skills"),),
        "headless_command": "dsh --profile headless",
    },
}


SAFE_ENV_KEYS = {
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "TERM",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_PATH",
    "BUN_INSTALL",
    "NPM_CONFIG_USERCONFIG",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
}
ALLOWED_CREDENTIAL_ENVS = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"}
PI_API_FORMATS = {
    "openai-chat-completions": "openai-completions",
    "openai-responses": "openai-responses",
    "anthropic-messages": "anthropic-messages",
    "google-generative-ai": "google-generative-ai",
}
# These are the only native Claude settings that may cross the isolated
# workspace boundary.  In particular, do not pass the whole settings object:
# it can contain hooks, permissions, paths, and other user-level behavior.
CLAUDE_NATIVE_ENV_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME",
    }
)
CLAUDE_NATIVE_MODEL_KEYS = (
    ("ANTHROPIC_MODEL", None),
    ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME"),
    ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME"),
    ("ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME"),
)
WORKBUDDY_NATIVE_ENV_KEYS = frozenset(
    {"CODEBUDDY_API_KEY", "CODEBUDDY_AUTH_TOKEN", "CODEBUDDY_BASE_URL"}
)


class AgentConfigError(ValueError):
    """An actionable configuration or capability error."""


class HeadlessUnavailable(AgentConfigError):
    """The selected executable/protocol cannot be safely used headlessly."""


router = APIRouter(prefix="/api")
_PICKER_LOCK = threading.Lock()
_AGENT_REFRESH_LOCK = threading.Lock()
_AGENT_REFRESH_IN_FLIGHT: set[str] = set()
_PICKER_CANCELLED = "__KXY_PICKER_CANCELLED__"
_PICKER_SCRIPT = r'''
on run argv
    set pickKind to item 1 of argv
    try
        if pickKind is "folder" then
            set chosen to choose folder with prompt "选择文件夹"
        else if pickKind is "file" then
            set chosen to choose file with prompt "选择文件"
        else
            error number -50
        end if
        return POSIX path of chosen
    on error number -128
        return "__KXY_PICKER_CANCELLED__"
    end try
end run
'''


def _core():
    """Import the existing app module only when a helper is actually called."""

    from . import app

    return app


def _now() -> str:
    return _core().utc_now()


def _json(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _redact(value: str, limit: int = MAX_PROBE_OUTPUT) -> str:
    try:
        return _core().redact(value, max_length=limit)
    except Exception:
        return value[:limit]


def _absolute_lexical(value: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise AgentConfigError("路径不能为空")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise AgentConfigError("路径包含非法控制字符")
    return Path(os.path.abspath(os.path.expanduser(value.strip())))


def _valid_agent_id(agent_id: str) -> str:
    value = str(agent_id or "").strip().lower()
    if value not in AGENT_PRESETS:
        raise AgentConfigError(f"未知 Agent：{agent_id}")
    return value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _lexically_inside(path: Path, root: Path) -> bool:
    """Check containment without resolving a user-selected symlink."""

    try:
        path.absolute().relative_to(root.absolute())
    except ValueError:
        return False
    return True


def _credential_row(credential_id: str | None):
    if not credential_id:
        return None
    with _core().connect_db() as db:
        return db.execute("SELECT * FROM credentials WHERE id=?", (str(credential_id),)).fetchone()


def _validate_credential_id(credential_id: Any) -> str | None:
    if credential_id in (None, ""):
        return None
    value = str(credential_id).strip()
    if not value or len(value) > 160 or "\x00" in value:
        raise AgentConfigError("credential_id 无效")
    if _credential_row(value) is None:
        raise AgentConfigError("所选凭据不存在，请从全局凭据设置中重新绑定")
    return value


def _credential_service_info(credential_id: str, row: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Read only the public service metadata needed for API model binding."""

    credential = row or _credential_row(credential_id)
    if credential is None:
        raise AgentConfigError("所选凭据已删除，请重新配置")
    core = _core()
    metadata = core.credential_metadata_row(str(credential["id"])) or {}
    provider = str(credential["provider"] or "custom").strip().lower()
    env_name = str(credential["env_name"] or "").strip().upper()
    try:
        api_format = core.normalize_api_format(metadata.get("api_format"), provider, env_name)
    except ValueError as exc:
        raise AgentConfigError(str(exc)) from exc
    try:
        models = core.normalize_service_models(_json(metadata.get("models"), []))
    except ValueError as exc:
        raise AgentConfigError("全局服务的模型目录无效，请重新保存该服务") from exc
    return {
        "credential_id": str(credential["id"]),
        "name": str(metadata.get("name") or provider)[:160],
        "provider": provider,
        "api_format": api_format,
        "models": models,
        "endpoint": str(credential["endpoint"] or ""),
        "env_name": env_name,
    }


def _validate_api_model_binding(agent_id: str, credential_id: str, model: str) -> dict[str, Any]:
    """Reject API protocol/Agent pairs that do not have a verified mapping."""

    info = _credential_service_info(credential_id)
    allowed_formats = {
        "codex": {"openai-responses"},
        "claude": {"anthropic-messages"},
        "pi": {"openai-chat-completions", "openai-responses", "anthropic-messages", "google-generative-ai"},
        "opencode": {"openai-chat-completions", "openai-responses", "anthropic-messages"},
    }.get(agent_id, set())
    if info["api_format"] not in allowed_formats:
        raise AgentConfigError(
            f"Agent {agent_id} 尚未验证 {info['api_format']} API 服务映射；请选择兼容的已保存服务"
        )
    catalog = {str(item["id"]) for item in info["models"] if isinstance(item, dict) and item.get("id")}
    if catalog and model not in catalog:
        raise AgentConfigError("model 必须从所选全局服务的模型目录中选择")
    return info


def _validate_executable_spec(value: Any) -> str:
    if not isinstance(value, str):
        raise AgentConfigError("executable 必须是单个二进制名称或文件路径")
    result = value.strip()
    if not result or len(result) > 512 or "\x00" in result or "\n" in result or "\r" in result:
        raise AgentConfigError("executable 不能为空且不能包含控制字符")
    if "/" not in result and not EXECUTABLE_NAME_RE.fullmatch(result):
        raise AgentConfigError("executable 必须是单个二进制名称，不接受 shell 命令串")
    return result


def _configured_executable(agent_id: str, configured: str | None = None) -> str | None:
    agent_id = _valid_agent_id(agent_id)
    override = os.environ.get(f"KXY_{agent_id.upper()}_BIN", "").strip()
    if override:
        try:
            return _resolve_executable_spec(override)
        except AgentConfigError:
            return None
    spec = configured or str(AGENT_PRESETS[agent_id]["executable"])
    try:
        resolved = _resolve_executable_spec(spec)
    except AgentConfigError:
        resolved = None
    if resolved:
        return resolved
    # Only the preset's own candidate list is a fallback. A user-selected
    # missing executable is never replaced by an unrelated binary.
    if configured not in (None, "", AGENT_PRESETS[agent_id]["executable"]):
        return None
    for candidate in AGENT_PRESETS[agent_id].get("executable_candidates", ()):
        try:
            resolved = _resolve_executable_spec(str(candidate))
        except AgentConfigError:
            continue
        if resolved:
            return resolved
    return None


def _resolve_executable_spec(spec: str) -> str | None:
    value = _validate_executable_spec(spec)
    if "/" in value:
        candidate = Path(value).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return None
        return str(resolved) if resolved.is_file() and os.access(resolved, os.X_OK) else None
    found = shutil.which(value)
    return str(Path(found).resolve()) if found else None


def _validate_runtime_interpreter(value: Any) -> str | None:
    """Validate one optional absolute interpreter path without executing it."""

    if value in (None, ""):
        return None
    if not isinstance(value, str) or "\x00" in value or "\n" in value or "\r" in value:
        raise AgentConfigError("runtime_interpreter 必须是绝对文件路径")
    candidate = Path(value.strip()).expanduser()
    if not candidate.is_absolute():
        raise AgentConfigError("runtime_interpreter 必须是绝对文件路径")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise AgentConfigError("runtime_interpreter 文件不存在") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise AgentConfigError("runtime_interpreter 不是可执行文件")
    return str(resolved)


def _runtime_script_uses_node(binary: str) -> bool:
    """Recognise a Node shebang without trusting arbitrary script contents."""

    try:
        with Path(binary).open("rb") as handle:
            first_line = handle.read(512).splitlines()[0].decode("utf-8", "replace")
    except (OSError, IndexError):
        return False
    return first_line.startswith("#!") and bool(_RUNTIME_NODE_SHEBANG_RE.search(first_line[2:].strip()))


def _runtime_interpreter_candidates(agent_id: str, binary: str, configured: Any = None) -> list[str]:
    """Return deterministic, local candidates for a Node-based Agent entry."""

    if configured not in (None, ""):
        value = _validate_runtime_interpreter(configured)
        return [value] if value else []
    if not _runtime_script_uses_node(binary):
        return []
    raw_candidates: list[str] = [
        str(_home() / ".local" / "bin" / "node"),
        str(_home() / ".hermes" / "node" / "bin" / "node"),
        "/opt/homebrew/bin/node",
        "/usr/local/bin/node",
        "/usr/bin/node",
    ]
    found = shutil.which("node")
    if found:
        raw_candidates.append(found)
    result: list[str] = []
    for raw in raw_candidates:
        try:
            path = _validate_runtime_interpreter(raw)
        except AgentConfigError:
            continue
        if path and path not in result:
            result.append(path)
    return result


def _runtime_failure_status(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("dyld", "library not loaded", "image not found", "dylib")):
        return "RUNTIME_DEPENDENCY_FAILURE"
    return "UNHEALTHY"


def _runtime_probe(binary: str, agent_id: str, configured: Any = None, root: Path | None = None) -> dict[str, Any]:
    """Probe the selected interpreter only; never starts the Agent script."""

    candidates = _runtime_interpreter_candidates(agent_id, binary, configured)
    if not candidates:
        if _runtime_script_uses_node(binary):
            return {
                "required": True,
                "status": "NOT_CONFIGURED",
                "interpreter": None,
                "version": None,
                "interpreter_version": None,
                "message": "未找到可用 Node 解释器",
            }
        probe_root = Path(root) if root is not None else None

        def run_agent_probe(probe_dir: Path) -> dict[str, Any]:
            try:
                process = subprocess.run(
                    [binary, "--version"],
                    cwd=str(probe_dir),
                    env=_probe_env(probe_dir),
                    capture_output=True,
                    text=True,
                    timeout=PROBE_TIMEOUT,
                    check=False,
                )
                output = _first_line((process.stdout or "").strip()) or _first_line((process.stderr or "").strip()) or ""
                if process.returncode == 0:
                    return {
                        "required": True,
                        "status": "READY",
                        "interpreter": None,
                        "version": output or "unknown",
                        "interpreter_version": None,
                        "message": None,
                    }
                failure = _redact(output or f"Agent --version 退出码 {process.returncode}", 512)
            except subprocess.TimeoutExpired:
                failure = f"Agent --version timeout after {PROBE_TIMEOUT:g}s"
            except OSError as exc:
                failure = f"{type(exc).__name__}: {_redact(str(exc), 400)}"
            return {
                "required": True,
                "status": _runtime_failure_status(failure),
                "interpreter": None,
                "version": None,
                "interpreter_version": None,
                "message": failure,
            }

        if probe_root is not None:
            return run_agent_probe(probe_root)
        with tempfile.TemporaryDirectory(prefix="kxy-runtime-probe-") as probe_dir:
            return run_agent_probe(Path(probe_dir))

    def run_probe(probe_root: Path) -> dict[str, Any] | None:
        for interpreter in candidates:
            try:
                process = subprocess.run(
                    [interpreter, "--version"],
                    cwd=str(probe_root),
                    env=_probe_env(probe_root),
                    capture_output=True,
                    text=True,
                    timeout=PROBE_TIMEOUT,
                    check=False,
                )
                output = _first_line((process.stdout or "").strip()) or _first_line((process.stderr or "").strip()) or ""
                if process.returncode == 0:
                    # Probe the exact interpreter + Agent script pair too. A
                    # healthy Node binary alone is not enough to authorize a
                    # later run of the selected CLI.
                    agent_process = subprocess.run(
                        [interpreter, binary, "--version"],
                        cwd=str(probe_root),
                        env=_probe_env(probe_root),
                        capture_output=True,
                        text=True,
                        timeout=PROBE_TIMEOUT,
                        check=False,
                    )
                    agent_output = _first_line((agent_process.stdout or "").strip()) or _first_line((agent_process.stderr or "").strip()) or ""
                    if agent_process.returncode != 0:
                        failure = _redact(agent_output or f"Agent --version 退出码 {agent_process.returncode}", 512)
                        return {
                            "required": True,
                            "status": _runtime_failure_status(failure),
                            "interpreter": interpreter,
                            "version": None,
                            "interpreter_version": output or None,
                            "message": failure,
                        }
                    return {
                        "required": True,
                        "status": "READY",
                        "interpreter": interpreter,
                        "version": agent_output or output or "unknown",
                        "interpreter_version": output or None,
                        "message": None,
                    }
                failure = _redact(output or f"解释器退出码 {process.returncode}", 512)
            except subprocess.TimeoutExpired:
                failure = f"runtime interpreter probe timeout after {PROBE_TIMEOUT:g}s"
            except OSError as exc:
                failure = f"{type(exc).__name__}: {_redact(str(exc), 400)}"
            if configured not in (None, ""):
                return {
                    "required": True,
                    "status": _runtime_failure_status(failure),
                    "interpreter": interpreter,
                    "version": None,
                    "interpreter_version": None,
                    "message": failure,
                }
        return {
            "required": True,
            "status": _runtime_failure_status(failure),
            "interpreter": candidates[0],
            "version": None,
            "interpreter_version": None,
            "message": failure,
        }

    if root is not None:
        return run_probe(Path(root))
    with tempfile.TemporaryDirectory(prefix="kxy-runtime-probe-") as probe_dir:
        return run_probe(Path(probe_dir))


def _runtime_argv(binary: str, args: Sequence[str], runtime: Mapping[str, Any] | None = None) -> list[str]:
    command = [str(binary), *[str(item) for item in args]]
    interpreter = str((runtime or {}).get("interpreter") or "").strip()
    if interpreter:
        return [interpreter, *command]
    return command


def probe_agent_runtime(agent_id: str, interpreter: Any = None, *, persist: bool = True) -> dict[str, Any]:
    """Probe and optionally save the selected Agent runtime binding."""

    ensure_agent_config_schema()
    agent_id = _valid_agent_id(agent_id)
    profile = _profile_row(agent_id)
    binary = _configured_executable(agent_id, str(profile["executable"]))
    if not binary:
        result = {
            "required": False,
            "status": "AGENT_UNAVAILABLE",
            "interpreter": None,
            "version": None,
            "message": "Agent 可执行文件不可用",
        }
    else:
        selected = interpreter if interpreter not in (None, "") else profile.get("runtime_interpreter")
        result = _runtime_probe(binary, agent_id, selected)
    if persist:
        with _core().connect_db() as db:
            db.execute(
                "UPDATE agent_profiles SET runtime_interpreter=?, runtime_interpreter_version=?, runtime_status=?, runtime_version=?, "
                "runtime_checked_at=?, runtime_message=?, updated_at=? WHERE id=?",
                (
                    result.get("interpreter"),
                    result.get("interpreter_version"),
                    str(result.get("status") or "unknown"),
                    result.get("version"),
                    _now(),
                    result.get("message"),
                    _now(),
                    agent_id,
                ),
            )
    return {"agent_id": agent_id, **result}


def _dsh_headless_dir() -> Path:
    return _dsh_home() / "profiles" / "headless"


def _dsh_headless_present() -> bool:
    return _dsh_headless_dir().is_dir()


def _presence(agent_id: str, executable: str | None) -> tuple[bool, str, str | None]:
    if agent_id == "deepseek" and not _dsh_headless_present():
        return (
            False,
            "UNAVAILABLE",
            f"DSH headless profile 不存在：{_dsh_headless_dir()}；web profile 不能替代 headless",
        )
    if not executable:
        return False, "NOT_INSTALLED", "未找到可执行文件；请选择本机 Agent 可执行文件"
    return True, "READY", None


def _decode_profile_roots(row: Mapping[str, Any]) -> list[str]:
    roots = _json(row.get("skill_roots"), [])
    return [str(item) for item in roots if isinstance(item, str)][:MAX_PROFILE_ROOTS]


def _model_public(row: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(row)
    result = {
        "id": str(row["id"]),
        "agent_id": str(row["agent_id"]),
        "cli_id": str(row["cli_id"]),
        "model": str(row["model"]),
        "alias": str(row["alias"]),
        "source": str(row["source"]),
        "efforts": [str(item) for item in _json(row.get("efforts"), []) if isinstance(item, str)],
        "default_effort": row.get("default_effort"),
        "discovery_source": str(row.get("discovery_source") or ""),
        "credential_id": row.get("credential_id"),
        "native_model_ref": row.get("native_model_ref"),
    }
    return result


def _profile_public(row: Mapping[str, Any], db) -> dict[str, Any]:
    agent_id = str(row["id"])
    configured = str(row.get("executable") or AGENT_PRESETS[agent_id]["executable"])
    models = db.execute(
        "SELECT id, agent_id, cli_id, model, alias, source, efforts, default_effort, "
        "discovery_source, credential_id, native_model_ref FROM agent_models WHERE agent_id=? "
        "ORDER BY CASE source WHEN 'native' THEN 0 WHEN 'api' THEN 1 ELSE 2 END, alias COLLATE NOCASE",
        (agent_id,),
    ).fetchall()
    login = {
        "status": str(row.get("login_status") or "unknown"),
        "verified": (
            True
            if str(row.get("login_status") or "").lower() == "verified"
            else False
            if str(row.get("login_status") or "").lower() == "not_logged_in"
            else None
        ),
        "checked_at": row.get("login_checked_at"),
        "source": str(row.get("login_source") or "not_checked"),
        "evidence": str(row.get("login_evidence") or "not_checked"),
        "reason": str(row.get("login_reason") or "尚未进行登录态检查；模型目录不代表已登录。"),
        "credential_state": "not_inspected",
    }
    return {
        "id": agent_id,
        "label": str(row["label"]),
        "executable": configured,
        "resolved_executable": _configured_executable(agent_id, configured),
        "skill_roots": _decode_profile_roots(row),
        "available": bool(row.get("available")),
        "version": row.get("version"),
        "status": str(row.get("status") or "UNCONFIGURED"),
        "message": row.get("message"),
        "supported_efforts": [
            str(item) for item in _json(row.get("supported_efforts"), []) if isinstance(item, str)
        ],
        "capabilities": _json(row.get("capabilities"), {}),
        "models": [_model_public(model) for model in models],
        "discovered_at": row.get("discovered_at"),
        "runtime": {
            "interpreter": row.get("runtime_interpreter"),
            "interpreter_version": row.get("runtime_interpreter_version"),
            "status": str(row.get("runtime_status") or "unknown"),
            "version": row.get("runtime_version"),
            "checked_at": row.get("runtime_checked_at"),
            "message": row.get("runtime_message"),
        },
        "runtime_interpreter": row.get("runtime_interpreter"),
        "login": login,
        # Keep flat aliases for small clients while the nested object carries
        # the complete sanitized evidence record.
        "login_status": login["status"],
        "login_checked_at": login["checked_at"],
    }


def _profile_row(agent_id: str):
    agent_id = _valid_agent_id(agent_id)
    with _core().connect_db() as db:
        row = db.execute("SELECT * FROM agent_profiles WHERE id=?", (agent_id,)).fetchone()
        if row is None:
            raise AgentConfigError(f"Agent 配置不存在：{agent_id}")
        return dict(row)


def ensure_agent_config_schema() -> None:
    """Create only configuration tables and seed all seven profiles.

    This intentionally does not call ``backend.app.init_db()``: that function
    performs startup run recovery, which must not happen when a settings route
    or discovery request is opened while another run is waiting.
    """

    core = _core()
    core.ensure_roots()
    with core.connect_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_profiles (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                executable TEXT NOT NULL,
                skill_roots TEXT NOT NULL DEFAULT '[]',
                available INTEGER NOT NULL DEFAULT 0,
                version TEXT,
                status TEXT NOT NULL DEFAULT 'UNCONFIGURED',
                message TEXT,
                supported_efforts TEXT NOT NULL DEFAULT '[]',
                capabilities TEXT NOT NULL DEFAULT '{}',
                discovered_at TEXT,
                runtime_interpreter TEXT,
                runtime_interpreter_version TEXT,
                runtime_status TEXT NOT NULL DEFAULT 'unknown',
                runtime_version TEXT,
                runtime_checked_at TEXT,
                runtime_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_models (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                cli_id TEXT NOT NULL,
                model TEXT NOT NULL,
                alias TEXT NOT NULL,
                source TEXT NOT NULL,
                efforts TEXT NOT NULL DEFAULT '[]',
                default_effort TEXT,
                discovery_source TEXT NOT NULL,
                credential_id TEXT,
                native_model_ref TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS agent_models_agent_idx ON agent_models(agent_id);
            CREATE INDEX IF NOT EXISTS agent_models_model_idx ON agent_models(agent_id, model);
            CREATE TABLE IF NOT EXISTS skill_dependency_checks (
                cache_key TEXT PRIMARY KEY,
                skill_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                dependency_hash TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                model_binding_hash TEXT NOT NULL,
                runtime_fingerprint TEXT NOT NULL,
                checker_version TEXT NOT NULL,
                result_json TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                cache_hit INTEGER NOT NULL DEFAULT 0,
                invalidation_reason TEXT
            );
            CREATE INDEX IF NOT EXISTS skill_dependency_checks_skill_idx
                ON skill_dependency_checks(skill_id, agent_id, checked_at);
            """
        )
        columns = {str(row[1]) for row in db.execute("PRAGMA table_info(agent_models)").fetchall()}
        if "native_model_ref" not in columns:
            db.execute("ALTER TABLE agent_models ADD COLUMN native_model_ref TEXT")
        profile_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(agent_profiles)").fetchall()}
        for column, definition in {
            "login_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "login_checked_at": "TEXT",
            "login_source": "TEXT",
            "login_evidence": "TEXT",
            "login_reason": "TEXT",
            "runtime_interpreter": "TEXT",
            "runtime_interpreter_version": "TEXT",
            "runtime_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "runtime_version": "TEXT",
            "runtime_checked_at": "TEXT",
            "runtime_message": "TEXT",
        }.items():
            if column not in profile_columns:
                db.execute(f"ALTER TABLE agent_profiles ADD COLUMN {column} {definition}")
        now = _now()
        for agent_id, preset in AGENT_PRESETS.items():
            exists = db.execute("SELECT id FROM agent_profiles WHERE id=?", (agent_id,)).fetchone()
            if exists is not None:
                continue
            resolved = _configured_executable(agent_id, str(preset["executable"]))
            available, status, message = _presence(agent_id, resolved)
            db.execute(
                "INSERT INTO agent_profiles(id, label, executable, skill_roots, available, status, message, "
                "supported_efforts, capabilities, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    agent_id,
                    preset["label"],
                    preset["executable"],
                    _json_text(list(preset["skill_roots"])),
                    int(available),
                    status,
                    message,
                    "[]",
                    _json_text({"headless": False, "verified": False, "model_discovery": False}),
                    now,
                    now,
                ),
            )


def list_agent_profiles() -> list[dict[str, Any]]:
    ensure_agent_config_schema()
    with _core().connect_db() as db:
        rows = db.execute("SELECT * FROM agent_profiles ORDER BY rowid").fetchall()
        return [_profile_public(dict(row), db) for row in rows]


def get_agent_profile(agent_id: str) -> dict[str, Any]:
    ensure_agent_config_schema()
    agent_id = _valid_agent_id(agent_id)
    with _core().connect_db() as db:
        row = db.execute("SELECT * FROM agent_profiles WHERE id=?", (agent_id,)).fetchone()
        if row is None:
            raise AgentConfigError(f"Agent 配置不存在：{agent_id}")
        return _profile_public(dict(row), db)


def _normalise_skill_roots(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise AgentConfigError("skill_roots 必须是路径数组")
    if len(value) > MAX_PROFILE_ROOTS:
        raise AgentConfigError(f"skill_roots 最多 {MAX_PROFILE_ROOTS} 个")
    result: list[str] = []
    for raw in value:
        path = _absolute_lexical(raw)
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise AgentConfigError(f"Skill 根目录不存在：{path}") from exc
        if not resolved.is_dir():
            raise AgentConfigError(f"Skill 根目录不是文件夹：{path}")
        if str(path) not in result:
            result.append(str(path))
    return result


def update_agent_profile(agent_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    ensure_agent_config_schema()
    agent_id = _valid_agent_id(agent_id)
    if not isinstance(payload, Mapping):
        raise AgentConfigError("请求需要 JSON 对象")
    if not any(key in payload for key in ("executable", "skill_roots", "runtime_interpreter")):
        raise AgentConfigError("至少提供 executable、skill_roots 或 runtime_interpreter")
    current = _profile_row(agent_id)
    executable = str(current["executable"])
    roots = _decode_profile_roots(current)
    runtime_interpreter = current.get("runtime_interpreter")
    runtime_changed = False
    if "executable" in payload:
        raw = payload.get("executable")
        executable = str(AGENT_PRESETS[agent_id]["executable"]) if raw in (None, "") else _validate_executable_spec(raw)
        runtime_changed = True
    if "skill_roots" in payload:
        roots = _normalise_skill_roots(payload.get("skill_roots"))
    if "runtime_interpreter" in payload:
        runtime_interpreter = _validate_runtime_interpreter(payload.get("runtime_interpreter"))
        runtime_changed = True
    elif "executable" in payload:
        runtime_interpreter = None
    resolved = _configured_executable(agent_id, executable)
    available, status, message = _presence(agent_id, resolved)
    with _core().connect_db() as db:
        db.execute(
            "UPDATE agent_profiles SET executable=?, skill_roots=?, available=?, status=?, message=?, "
            "runtime_interpreter=?, runtime_interpreter_version=?, runtime_status=?, runtime_version=?, runtime_checked_at=?, runtime_message=?, "
            "login_status='unknown', login_checked_at=NULL, login_source='not_checked', "
            "login_evidence='configuration_changed', login_reason=?, updated_at=? WHERE id=?",
            (
                executable,
                _json_text(roots),
                int(available),
                status,
                message,
                runtime_interpreter,
                None if runtime_changed else current.get("runtime_interpreter_version"),
                "not_checked" if runtime_changed else str(current.get("runtime_status") or "unknown"),
                None if runtime_changed else current.get("runtime_version"),
                None if runtime_changed else current.get("runtime_checked_at"),
                "解释器或 Agent 可执行文件已改变；请重新进行运行时检查。" if runtime_changed else current.get("runtime_message"),
                "可执行文件或 Skill 根目录已改变；请重新进行登录态检查。",
                _now(),
                agent_id,
            ),
        )
    return get_agent_profile(agent_id)


def _probe_env(root: Path) -> dict[str, str]:
    source = os.environ
    env = {key: source[key] for key in SAFE_ENV_KEYS if source.get(key)}
    env["HOME"] = str(root)
    env["CODEX_HOME"] = str(root / "codex")
    env["CODEBUDDY_HOME"] = str(root / "codebuddy")
    env["CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
    env["PI_CODING_AGENT_DIR"] = str(root / "pi")
    env["PI_OFFLINE"] = "1"
    env["NO_COLOR"] = "1"
    # pi's documented --list-models command filters the built-in catalog by
    # configured providers.  Preserve only provider *names* in a temporary
    # probe auth file, with a non-secret placeholder value; never copy auth
    # values or the user's models/config files into the probe environment.
    pi_providers = _read_pi_auth_provider_ids()
    if pi_providers:
        pi_root = root / "pi"
        pi_root.mkdir(parents=True, exist_ok=True)
        auth_path = pi_root / "auth.json"
        auth_path.write_text(
            _json_text(
                {
                    provider: {"type": "api_key", "key": "__kxy_catalog_probe__"}
                    for provider in pi_providers
                }
            ),
            encoding="utf-8",
        )
        try:
            auth_path.chmod(0o600)
        except OSError:
            pass
    return env


def _probe(argv: Sequence[str], root: Path, *, cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        process = subprocess.run(
            [str(item) for item in argv],
            cwd=str(cwd or root),
            env=_probe_env(root),
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            check=False,
        )
        stdout = (process.stdout or "")[:MAX_PROBE_OUTPUT]
        stderr = (process.stderr or "")[:MAX_PROBE_OUTPUT]
        return process.returncode, stdout, stderr
    except subprocess.TimeoutExpired as exc:
        return 124, str(exc.stdout or "")[:MAX_PROBE_OUTPUT], f"probe timeout after {PROBE_TIMEOUT:g}s"
    except OSError as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"


def _native_login_env() -> dict[str, str]:
    """Keep only non-secret native process context for status inspection."""

    env = {key: os.environ[key] for key in SAFE_ENV_KEYS if os.environ.get(key)}
    # These are path/config selectors, not credential payloads.  They are
    # retained so a user's native CLI installation is checked in its real
    # context; unlike _probe_env, HOME is deliberately not redirected.
    for key in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    env["NO_COLOR"] = "1"
    return env


def _login_record(
    *,
    status: str,
    verified: bool | None,
    source: str,
    evidence: str,
    reason: str,
) -> dict[str, Any]:
    """Return the small allowlisted login-state contract exposed to the UI."""

    return {
        "status": status,
        "verified": verified,
        "checked_at": _now(),
        "source": source,
        "evidence": evidence,
        "reason": reason,
        "credential_state": "not_inspected",
    }


def check_agent_login_status(agent_id: str) -> dict[str, Any]:
    """Run only a host-verified, read-only login status command.

    The command executes with native HOME/config selectors because a temporary
    probe HOME would incorrectly report an installed CLI as logged out.  Its
    stdout/stderr are used only for allowlisted boolean classification and are
    never stored, returned, or logged.
    """

    ensure_agent_config_schema()
    agent_id = _valid_agent_id(agent_id)
    profile = _profile_row(agent_id)
    command_args = LOGIN_STATUS_COMMANDS.get(agent_id)
    if command_args is None:
        record = _login_record(
            status="unsupported",
            verified=None,
            source="not_applicable",
            evidence="unsupported_cli",
            reason="当前 CLI 没有已确认的只读登录态命令；模型目录或配置存在不等于已登录。",
        )
    else:
        binary = _configured_executable(agent_id, str(profile["executable"]))
        if not binary:
            record = _login_record(
                status="unknown",
                verified=None,
                source="not_run",
                evidence="cli_unavailable",
                reason="CLI 当前不可用，未执行登录态命令；不能据此推断已登录。",
            )
        else:
            try:
                process = subprocess.run(
                    [binary, *command_args],
                    cwd=str(_home()),
                    env=_native_login_env(),
                    capture_output=True,
                    text=True,
                    timeout=PROBE_TIMEOUT,
                    check=False,
                )
                stdout = (process.stdout or "")[:MAX_PROBE_OUTPUT]
                stderr = (process.stderr or "")[:MAX_PROBE_OUTPUT]
                combined = f"{stdout}\n{stderr}"
                if agent_id == "codex":
                    # Check the negative phrase first: "Not logged in" can
                    # otherwise be misclassified by a broad logged-in match.
                    if re.search(r"\bnot\s+logged\s+in\b", combined, re.IGNORECASE):
                        record = _login_record(
                            status="not_logged_in",
                            verified=False,
                            source="codex login status",
                            evidence="status_command_not_logged_in",
                            reason="Codex 只读状态命令报告当前未登录。",
                        )
                    elif process.returncode == 0 and re.search(
                        r"\blogged\s+in\s+using\b", combined, re.IGNORECASE
                    ):
                        record = _login_record(
                            status="verified",
                            verified=True,
                            source="codex login status",
                            evidence="status_command_logged_in",
                            reason="Codex 只读状态命令确认已登录；账户信息未返回。",
                        )
                    else:
                        record = _login_record(
                            status="unknown",
                            verified=None,
                            source="codex login status",
                            evidence="status_command_unrecognized",
                            reason="Codex 状态命令已执行，但返回内容未达到可验证登录条件。",
                        )
                else:
                    # Claude's documented status output is JSON.  Parse only
                    # the boolean loggedIn field and discard every other key.
                    parsed: Any = None
                    try:
                        parsed = json.loads(stdout)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        parsed = None
                    logged_in = parsed.get("loggedIn") if isinstance(parsed, dict) else None
                    if process.returncode == 0 and logged_in is True:
                        record = _login_record(
                            status="verified",
                            verified=True,
                            source="claude auth status",
                            evidence="status_command_logged_in",
                            reason="Claude 只读状态命令确认已登录；账户信息未返回。",
                        )
                    elif process.returncode == 0 and logged_in is False:
                        record = _login_record(
                            status="not_logged_in",
                            verified=False,
                            source="claude auth status",
                            evidence="status_command_not_logged_in",
                            reason="Claude 只读状态命令报告当前未登录。",
                        )
                    else:
                        record = _login_record(
                            status="unknown",
                            verified=None,
                            source="claude auth status",
                            evidence="status_command_unrecognized",
                            reason="Claude 状态命令已执行，但未返回可验证的 loggedIn 布尔值。",
                        )
            except subprocess.TimeoutExpired:
                record = _login_record(
                    status="unknown",
                    verified=None,
                    source=f"{agent_id} {' '.join(command_args)}",
                    evidence="status_command_timeout",
                    reason=f"{agent_id} 只读状态命令超时；未判断登录状态。",
                )
            except (OSError, UnicodeError):
                record = _login_record(
                    status="unknown",
                    verified=None,
                    source=f"{agent_id} {' '.join(command_args)}",
                    evidence="status_command_failed",
                    reason=f"{agent_id} 只读状态命令无法完成；未判断登录状态。",
                )
    with _core().connect_db() as db:
        db.execute(
            "UPDATE agent_profiles SET login_status=?, login_checked_at=?, login_source=?, "
            "login_evidence=?, login_reason=?, updated_at=? WHERE id=?",
            (
                record["status"],
                record["checked_at"],
                record["source"],
                record["evidence"],
                record["reason"],
                _now(),
                agent_id,
            ),
        )
    return record


def _first_line(value: str) -> str | None:
    for line in value.splitlines():
        clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
        if clean:
            return _redact(clean, 256)
    return None


def _help_command(agent_id: str, binary: str) -> list[str]:
    if agent_id == "codex":
        return [binary, "exec", "--help"]
    if agent_id == "claude":
        return [binary, "--help"]
    if agent_id == "opencode":
        return [binary, "run", "--help"]
    if agent_id == "pi":
        return [binary, "--help"]
    if agent_id == "grok":
        return [binary, "--help"]
    if agent_id == "hermes":
        return [binary, "--help"]
    if agent_id == "workbuddy":
        return [binary, "--help"]
    if agent_id == "deepseek":
        return [binary, "--profile", "headless", "--help"]
    raise AgentConfigError(f"未知 Agent：{agent_id}")


def _extract_efforts(help_text: str) -> list[str]:
    # Parse only values shown near a documented effort/thinking/variant option;
    # words elsewhere in help text are not treated as a model capability.
    values: list[str] = []
    for match in re.finditer(r"--(?:effort|thinking|variant)\b", help_text, re.IGNORECASE):
        section = help_text[match.start() : match.start() + 700]
        for token in re.findall(r"\b(?:minimal|low|medium|high|xhigh|max|ultra|off)\b", section, re.IGNORECASE):
            lowered = token.lower()
            if lowered not in values:
                values.append(lowered)
    return values


def _model_id(
    source: str,
    agent_id: str,
    model: str,
    credential_id: str | None = None,
    *,
    identity: str | None = None,
) -> str:
    basis = "\0".join((source, agent_id, identity if identity is not None else model, credential_id or ""))
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    return f"{source}-{agent_id}-{digest}"


def _effort_list(value: Any, *, field: str = "efforts") -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, list) or len(value) > 32:
        raise AgentConfigError(f"{field} 必须是最多 32 项的数组")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not EFFORT_RE.fullmatch(item.strip()):
            raise AgentConfigError(f"{field} 包含无效 effort：{item}")
        item = item.strip()
        if item not in result:
            result.append(item)
    return result


def _read_codex_models() -> list[dict[str, Any]]:
    path = _home() / ".codex" / "models_cache.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    records: list[dict[str, Any]] = []
    for item in raw.get("models", []) if isinstance(raw, dict) else []:
        if not isinstance(item, dict):
            continue
        visibility = str(item.get("visibility") or "").lower()
        if item.get("internal_only") or item.get("is_internal") or item.get("hidden"):
            continue
        if visibility and visibility not in {"list", "public", "visible"}:
            continue
        cli_id = _safe_model_value(item.get("slug") or item.get("id"))
        if not cli_id:
            continue
        alias = _safe_public_text(item.get("display_name") or item.get("name") or cli_id, cli_id)
        efforts: list[str] = []
        levels = item.get("supported_reasoning_levels", [])
        if isinstance(levels, list):
            for level in levels:
                candidate = level.get("effort") if isinstance(level, dict) else level
                if isinstance(candidate, str) and EFFORT_RE.fullmatch(candidate) and candidate not in efforts:
                    efforts.append(candidate)
        default = item.get("default_reasoning_level")
        if not isinstance(default, str) or default not in efforts:
            # The cache does not make the first listed level a default. Keep
            # unknown defaults explicit rather than guessing one.
            default = None
        records.append(
            {
                "id": _model_id("native", "codex", cli_id),
                "agent_id": "codex",
                "cli_id": "codex",
                "model": cli_id,
                "alias": alias,
                "source": "native",
                "efforts": efforts,
                "default_effort": default,
                "discovery_source": "codex models_cache.json",
                "credential_id": None,
            }
        )
    return records


_SAFE_MODEL_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+\-]{0,255}$")


def _safe_model_value(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value or "\x00" in value or "\r" in value or "\n" in value:
        return ""
    return value if _SAFE_MODEL_VALUE_RE.fullmatch(value) else ""


def _safe_public_text(value: Any, fallback: str = "", limit: int = 256) -> str:
    if value in (None, ""):
        return fallback[:limit]
    text = re.sub(r"[\x00-\x1f\x7f]", " ", str(value)).strip()[:limit]
    return _redact(text, limit) or fallback[:limit]


def _catalog_efforts(item: Mapping[str, Any], fallback: Sequence[str] = ()) -> list[str]:
    values: list[str] = []
    for key in (
        "efforts",
        "thinking",
        "thinking_levels",
        "reasoning_levels",
        "supported_reasoning_levels",
        "variants",
    ):
        raw = item.get(key)
        if isinstance(raw, dict):
            raw = raw.get("levels") or raw.get("values") or raw.get("efforts")
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            continue
        for value in raw:
            value = value.get("effort") if isinstance(value, dict) else value
            if isinstance(value, str):
                value = value.strip().lower()
                if EFFORT_RE.fullmatch(value) and value not in values:
                    values.append(value)
    thinking_map = item.get("thinkingLevelMap")
    if isinstance(thinking_map, dict):
        for level, mapped in thinking_map.items():
            if mapped is None or not isinstance(level, str):
                continue
            level = level.strip().lower()
            if EFFORT_RE.fullmatch(level) and level not in values:
                values.append(level)
    if not values:
        for value in fallback:
            value = str(value).strip().lower()
            if EFFORT_RE.fullmatch(value) and value not in values:
                values.append(value)
    return values


def _catalog_default_effort(item: Mapping[str, Any], efforts: Sequence[str]) -> str | None:
    for key in ("default_effort", "default_thinking", "default_reasoning_level", "default_variant"):
        value = item.get(key)
        if isinstance(value, dict):
            value = value.get("effort") or value.get("level") or value.get("name")
        if isinstance(value, str) and value.strip().lower() in efforts:
            return value.strip().lower()
    return None


def _native_model_record(
    agent_id: str,
    model: Any,
    *,
    alias: Any = None,
    efforts: Sequence[str] = (),
    default_effort: str | None = None,
    discovery_source: str,
    identity: str | None = None,
) -> dict[str, Any] | None:
    model_value = _safe_model_value(model)
    if not model_value:
        return None
    alias_value = _safe_public_text(alias or model_value, model_value)
    effort_values = []
    for effort in efforts:
        effort = str(effort).strip().lower()
        if EFFORT_RE.fullmatch(effort) and effort not in effort_values:
            effort_values.append(effort)
    selected_default = str(default_effort or "").strip().lower() or None
    if selected_default not in effort_values:
        selected_default = None
    return {
        "id": _model_id("native", agent_id, model_value, identity=identity),
        "agent_id": agent_id,
        "cli_id": agent_id,
        "model": model_value,
        "alias": alias_value,
        "source": "native",
        "efforts": effort_values,
        "default_effort": selected_default,
        "discovery_source": _safe_public_text(discovery_source, "native discovery"),
        "credential_id": None,
    }


def _dedupe_native_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicate model IDs while retaining every safe provenance marker."""

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in records:
        record = dict(raw)
        key = (str(record.get("agent_id") or ""), str(record.get("model") or ""))
        if not key[0] or not key[1]:
            continue
        current = merged.get(key)
        if current is None:
            current = record
            current["efforts"] = list(record.get("efforts") or [])
            merged[key] = current
            continue
        for effort in record.get("efforts") or []:
            if effort not in current["efforts"]:
                current["efforts"].append(effort)
        if not current.get("default_effort") and record.get("default_effort"):
            current["default_effort"] = record["default_effort"]
        if current.get("alias") == current.get("model") and record.get("alias"):
            current["alias"] = record["alias"]
        source = str(record.get("discovery_source") or "")
        existing_sources = str(current.get("discovery_source") or "").split(" | ")
        if source and source not in existing_sources:
            current["discovery_source"] = " | ".join([*existing_sources, source])[:256]
    return list(merged.values())


def _catalog_records_from_value(
    agent_id: str,
    value: Any,
    *,
    discovery_source: str,
    fallback_efforts: Sequence[str] = (),
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in _walk_json_values(value):
        if not isinstance(item, dict):
            continue
        model = None
        for key in ("id", "model", "model_id", "modelID", "slug"):
            if isinstance(item.get(key), str):
                model = item[key]
                break
        if model is None and isinstance(item.get("name"), str) and any(
            key in item for key in ("provider", "efforts", "thinking", "variants")
        ):
            model = item["name"]
        if not _safe_model_value(model):
            continue
        efforts = _catalog_efforts(item, fallback_efforts)
        record = _native_model_record(
            agent_id,
            model,
            alias=item.get("display_name") or item.get("name") or item.get("label") or model,
            efforts=efforts,
            default_effort=_catalog_default_effort(item, efforts),
            discovery_source=discovery_source,
            identity=f"{item.get('provider', '')}:{model}" if item.get("provider") else None,
        )
        if record is not None:
            records.append(record)
    return _dedupe_native_records(records)


def _read_json_model_catalog(
    path: Path,
    agent_id: str,
    *,
    discovery_source: str,
    fallback_efforts: Sequence[str] = (),
) -> list[dict[str, Any]]:
    try:
        if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
            return []
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return []
    return _catalog_records_from_value(
        agent_id,
        value,
        discovery_source=discovery_source,
        fallback_efforts=fallback_efforts,
    )


def _catalog_token(value: str) -> str:
    candidate = value.strip().strip("'\"`.,;()[]")
    candidate = _safe_model_value(candidate)
    if not candidate:
        return ""
    lowered = candidate.lower()
    if lowered in {
        "model",
        "models",
        "provider",
        "providers",
        "available",
        "available-models",
        "name",
        "id",
        "modelid",
    }:
        return ""
    if "/" in candidate:
        parts = candidate.split("/")
        if len(parts) > 3 or "://" in candidate:
            return ""
        blocked_parts = {
            "applications",
            "bin",
            "docs",
            "home",
            "homebrew",
            "lib",
            "node_modules",
            "opt",
            "private",
            "tmp",
            "usr",
            "users",
            "var",
        }
        if any(part.casefold() in blocked_parts for part in parts) or any(
            part.casefold().endswith((".md", ".json", ".js", ".ts", ".yaml", ".yml")) for part in parts
        ):
            return ""
        return candidate
    if re.match(
        r"^(?:gpt|o[1-9]|claude|gemini|deepseek|qwen|glm|kimi|minimax|moonshot|mistral|llama|sonnet|opus|haiku|fable|codestral|command|nova|yi|doubao|internlm|ernie)[-_.:]",
        candidate,
        re.IGNORECASE,
    ):
        return candidate
    return ""


def _parse_text_model_catalog(
    agent_id: str,
    text: str,
    *,
    discovery_source: str,
    fallback_efforts: Sequence[str] = (),
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
        if not clean:
            continue
        try:
            value = json.loads(clean)
        except (ValueError, json.JSONDecodeError):
            value = None
        if value is not None:
            records.extend(
                _catalog_records_from_value(
                    agent_id,
                    value,
                    discovery_source=discovery_source,
                    fallback_efforts=fallback_efforts,
                )
            )
        if value is not None and isinstance(value, (dict, list)):
            continue
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.:@/+\-]*", clean):
            model = _catalog_token(token)
            if not model:
                continue
            record = _native_model_record(
                agent_id,
                model,
                alias=model,
                efforts=fallback_efforts,
                discovery_source=discovery_source,
            )
            if record is not None:
                records.append(record)
    return _dedupe_native_records(records)


def _parse_pi_models(text: str, fallback_efforts: Sequence[str] = ()) -> list[dict[str, Any]]:
    return _parse_text_model_catalog(
        "pi",
        text,
        discovery_source="pi --list-models (isolated probe)",
        fallback_efforts=fallback_efforts,
    )


_GROK_MODEL_LINE_RE = re.compile(
    r"^[*\-]\s+([A-Za-z0-9][A-Za-z0-9._:@+/-]*)(?:\s+\((?:default|recommended)\))?\s*$"
)


def _parse_grok_models(text: str, fallback_efforts: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Parse `grok models`, which lists one model per `*`/`-` bullet line.

    The generic text catalog parser is deliberately not used here: the output
    also contains prose lines ("You are logged in with grok.com.") whose word
    tokens would otherwise be offered as model names.
    """

    records: list[dict[str, Any]] = []
    for raw in text.splitlines():
        clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw).strip()
        match = _GROK_MODEL_LINE_RE.match(clean)
        if not match:
            continue
        record = _native_model_record(
            "grok",
            match.group(1),
            alias=match.group(1),
            efforts=fallback_efforts,
            discovery_source="grok models (isolated probe)",
        )
        if record is not None:
            records.append(record)
    return _dedupe_native_records(records)


def _pi_provider_id(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@+\-]{0,127}", value) else ""


def _pi_records_from_provider_map(
    value: Any,
    *,
    provider_root: str | None,
    discovery_source: str,
    fallback_efforts: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Read pi's provider-scoped model definitions without auth/config fields."""

    providers = value.get(provider_root) if provider_root and isinstance(value, dict) else value
    if not isinstance(providers, dict):
        return []
    records: list[dict[str, Any]] = []
    for raw_provider, provider_value in providers.items():
        provider = _pi_provider_id(raw_provider)
        if not provider or not isinstance(provider_value, dict):
            continue
        models = provider_value.get("models")
        if not isinstance(models, list):
            continue
        for item in models[:512]:
            fields: Mapping[str, Any] = item if isinstance(item, dict) else {}
            model_id = item if isinstance(item, str) else fields.get("id")
            model_id = _safe_model_value(model_id)
            if not model_id:
                continue
            model = model_id if model_id.split("/", 1)[0] == provider else f"{provider}/{model_id}"
            efforts = _catalog_efforts(fields, fallback_efforts)
            record = _native_model_record(
                "pi",
                model,
                alias=fields.get("name") or fields.get("display_name") or model,
                efforts=efforts,
                default_effort=_catalog_default_effort(fields, efforts),
                discovery_source=f"{discovery_source} ({provider})",
                identity=f"{provider}:{model_id}",
            )
            if record is not None:
                records.append(record)
    return _dedupe_native_records(records)


def _read_json_value(path: Path, *, max_bytes: int = 5 * 1024 * 1024) -> Any:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None


def _safe_native_env_value(value: Any) -> str:
    """Keep a native env value usable without accepting control characters."""

    if not isinstance(value, str) or not value or len(value) > 8 * 1024:
        return ""
    if "\x00" in value or "\r" in value or "\n" in value:
        return ""
    return value


def _read_native_settings_env(path: Path, allowed_keys: set[str] | frozenset[str]) -> dict[str, str]:
    """Read only an explicit env allowlist from a regular native settings file."""

    value = _read_json_value(path, max_bytes=2 * 1024 * 1024)
    raw_env = value.get("env") if isinstance(value, dict) else None
    if not isinstance(raw_env, dict):
        return {}
    return {
        key: safe_value
        for key in allowed_keys
        if (safe_value := _safe_native_env_value(raw_env.get(key)))
    }


def _read_claude_native_env() -> dict[str, str]:
    return _read_native_settings_env(_home() / ".claude" / "settings.json", CLAUDE_NATIVE_ENV_KEYS)


def _read_workbuddy_native_env() -> dict[str, str]:
    # CodeBuddy's documented user settings path is ~/.codebuddy/settings.json.
    # The desktop login/session store is separate and has not been assumed.
    return _read_native_settings_env(_home() / ".codebuddy" / "settings.json", WORKBUDDY_NATIVE_ENV_KEYS)


def _link_native_readonly(local_path: Path, native_path: Path, label: str) -> bool:
    """Reference one verified native file without copying or mutating it."""

    try:
        if native_path.is_symlink() or not native_path.is_file():
            return False
        native_target = native_path.resolve(strict=True)
        if local_path.is_symlink():
            if local_path.resolve(strict=True) == native_target:
                return True
            raise AgentConfigError(f"{label} workspace reference already points elsewhere")
        if local_path.exists():
            raise AgentConfigError(f"{label} workspace path already exists and is not the native reference")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.symlink_to(native_target)
        return True
    except AgentConfigError:
        raise
    except OSError as exc:
        raise AgentConfigError(f"{label} native reference unavailable") from exc


def _copy_native_private(local_path: Path, native_path: Path, label: str) -> bool:
    """Copy one bounded native auth file to a task-local 0600 file."""

    try:
        if native_path.is_symlink() or not native_path.is_file():
            return False
        if native_path.stat().st_size > 2 * 1024 * 1024:
            raise AgentConfigError(f"{label} native auth file exceeds the safety limit")
        content = native_path.read_bytes()
        if not content:
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)
        try:
            local_path.chmod(0o600)
        except OSError:
            pass
        return True
    except AgentConfigError:
        raise
    except OSError as exc:
        raise AgentConfigError(f"{label} native auth unavailable") from exc


def _read_pi_models(fallback_efforts: Sequence[str] = ()) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    agent_root = _home() / ".pi" / "agent"
    models_path = agent_root / "models.json"
    models_value = _read_json_value(models_path)
    records.extend(
        _pi_records_from_provider_map(
            models_value,
            provider_root="providers",
            discovery_source="pi models.json (read-only native catalog)",
            fallback_efforts=fallback_efforts,
        )
    )
    store_path = agent_root / "models-store.json"
    store_value = _read_json_value(store_path)
    records.extend(
        _pi_records_from_provider_map(
            store_value,
            provider_root=None,
            discovery_source="pi models-store.json (read-only native catalog)",
            fallback_efforts=fallback_efforts,
        )
    )
    return _dedupe_native_records(records)


def _read_pi_auth_provider_ids() -> list[str]:
    """Read only pi auth provider names for an isolated catalog probe."""

    path = _home() / ".pi" / "agent" / "auth.json"
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 512 * 1024:
            return []
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(value, dict):
        return []
    providers: list[str] = []
    for raw_provider in value:
        if not isinstance(raw_provider, str):
            continue
        provider = raw_provider.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@+\-]{0,127}", provider):
            continue
        if provider not in providers:
            providers.append(provider)
    return providers[:128]


def _claude_models(help_text: str, fallback_efforts: Sequence[str]) -> list[dict[str, Any]]:
    match = re.search(r"--model <model>(.*?)(?=\n\s*--[A-Za-z]|\Z)", help_text, re.IGNORECASE | re.DOTALL)
    models: list[str] = []
    records: list[dict[str, Any]] = []
    if match is not None:
        section = match.group(1)[:1600]
        values = re.findall(r"['\"]([A-Za-z][A-Za-z0-9_.:-]{1,80})['\"]", section)
        for value in values:
            lowered = value.lower()
            if lowered in {"fable", "opus", "sonnet"} or lowered.startswith("claude-"):
                if value not in models:
                    models.append(value)
        for model in models:
            record = _native_model_record(
                "claude",
                model,
                alias=model,
                efforts=fallback_efforts,
                discovery_source="claude --help (documented model alias)",
            )
            if record is not None:
                records.append(record)

    # The installed Claude Code setup can pin concrete model IDs and display
    # names in settings.json.  Read only the allowlisted env keys; values are
    # never included in discovery output except as validated model/alias data.
    native_env = _read_claude_native_env()
    for model_key, alias_key in CLAUDE_NATIVE_MODEL_KEYS:
        model = _safe_model_value(native_env.get(model_key))
        if not model:
            continue
        alias = _safe_public_text(native_env.get(alias_key), model) if alias_key else model
        record = _native_model_record(
            "claude",
            model,
            alias=alias,
            efforts=fallback_efforts,
            discovery_source="claude ~/.claude/settings.json (allowlisted model env)",
        )
        if record is not None:
            records.append(record)
    return _dedupe_native_records(records)


def _workbuddy_models(help_text: str, fallback_efforts: Sequence[str]) -> list[dict[str, Any]]:
    match = re.search(r"currently supported:\s*\(([^)]*)\)", help_text, re.IGNORECASE | re.DOTALL)
    if match is None:
        return []
    models: list[str] = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.:+\-]*", match.group(1)):
        model = _safe_model_value(token)
        if model and model not in models:
            models.append(model)
    records = [
        _native_model_record(
            "workbuddy",
            model,
            alias=model,
            efforts=fallback_efforts,
            discovery_source="codebuddy --help (documented supported models)",
        )
        for model in models
    ]
    return [record for record in records if record is not None]


def _read_hermes_models() -> list[dict[str, Any]]:
    """Read Hermes' local catalog/config without opening auth or refreshing it."""

    catalog_path = _home() / ".hermes" / "cache" / "model_catalog.json"
    records_by_model: dict[str, dict[str, Any]] = {}
    try:
        if catalog_path.is_file() and catalog_path.stat().st_size <= 5 * 1024 * 1024:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        else:
            catalog = {}
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        catalog = {}
    providers = catalog.get("providers") if isinstance(catalog, dict) else None
    if isinstance(providers, dict):
        for provider, provider_value in providers.items():
            provider_name = _safe_model_value(str(provider))
            models = provider_value.get("models") if isinstance(provider_value, dict) else None
            if not isinstance(models, list):
                continue
            for item in models:
                if isinstance(item, str):
                    model = item
                    fields: Mapping[str, Any] = {}
                elif isinstance(item, dict):
                    fields = item
                    model = fields.get("id") or fields.get("model") or fields.get("slug") or ""
                else:
                    continue
                model = _safe_model_value(model)
                if not model:
                    continue
                efforts = _catalog_efforts(fields)
                source = "hermes cache/model_catalog.json"
                if provider_name:
                    source += f" ({provider_name})"
                record = _native_model_record(
                    "hermes",
                    model,
                    alias=fields.get("display_name") or fields.get("name") or model,
                    efforts=efforts,
                    default_effort=_catalog_default_effort(fields, efforts),
                    discovery_source=source,
                )
                if record is None:
                    continue
                existing = records_by_model.get(model)
                if existing is None:
                    records_by_model[model] = record
                else:
                    merged = _dedupe_native_records([existing, record])
                    records_by_model[model] = merged[0] if merged else existing

    # The selected model/provider is useful even when it is not in the cached
    # catalog.  Read only these two whitelisted scalar fields; never expose or
    # copy base_url, API keys, tokens, or any other config value.
    config_path = _home() / ".hermes" / "config.yaml"
    selected_model = ""
    selected_provider = ""
    try:
        if config_path.is_file() and config_path.stat().st_size <= 2 * 1024 * 1024:
            import yaml

            config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        else:
            config = {}
    except Exception:
        config = {}
    model_config = config.get("model") if isinstance(config, dict) else None
    if isinstance(model_config, dict):
        selected_model = _safe_model_value(model_config.get("default") or model_config.get("model"))
        selected_provider = _safe_model_value(model_config.get("provider"))
    if selected_model:
        source = "hermes config.yaml (selected model)"
        if selected_provider:
            source += f" provider={selected_provider}"
        selected = _native_model_record(
            "hermes",
            selected_model,
            alias=selected_model,
            discovery_source=source,
        )
        if selected is not None:
            existing = records_by_model.get(selected_model)
            if existing is None:
                records_by_model[selected_model] = selected
            else:
                merged = _dedupe_native_records([existing, selected])
                records_by_model[selected_model] = merged[0] if merged else existing
    return list(records_by_model.values())


def _walk_json_values(value: Any, depth: int = 0):
    if depth > 16:
        return
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk_json_values(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json_values(item, depth + 1)


def _parse_opencode_models(text: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        raw = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            value = None
        candidates: list[Any] = []
        if value is not None:
            candidates.extend(_walk_json_values(value))
        candidates.append(raw)
        for candidate in candidates:
            if isinstance(candidate, dict):
                candidate = candidate.get("id") or candidate.get("model") or candidate.get("modelID")
            if not isinstance(candidate, str):
                continue
            candidate = candidate.strip().strip("'\"")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@/+\-]*", candidate):
                continue
            candidate = _catalog_token(candidate)
            if not candidate:
                continue
            if candidate not in found:
                found.append(candidate)
    return found[:200]


def _native_records(agent_id: str, model_output: str = "", help_text: str = "") -> list[dict[str, Any]]:
    fallback_efforts = _extract_efforts(help_text)
    if agent_id == "codex":
        return _dedupe_native_records(_read_codex_models())
    if agent_id == "opencode":
        records = []
        for model in _parse_opencode_models(model_output):
            record = _native_model_record(
                agent_id,
                model,
                alias=model,
                discovery_source="opencode models",
            )
            if record is not None:
                records.append(record)
        return records
    if agent_id == "claude":
        return _claude_models(help_text, fallback_efforts)
    if agent_id == "pi":
        records = _parse_pi_models(model_output, fallback_efforts) if model_output else []
        records.extend(_read_pi_models(fallback_efforts))
        return _dedupe_native_records(records)
    if agent_id == "grok":
        return _parse_grok_models(model_output, fallback_efforts) if model_output else []
    if agent_id == "hermes":
        return _read_hermes_models()
    if agent_id == "workbuddy":
        return _workbuddy_models(help_text, fallback_efforts)
    return []


def _store_native_records(agent_id: str, records: Sequence[Mapping[str, Any]]) -> None:
    now = _now()
    with _core().connect_db() as db:
        existing_rows = db.execute(
            "SELECT * FROM agent_models WHERE agent_id=? AND source='native'",
            (agent_id,),
        ).fetchall()
        existing_by_id = {str(row["id"]): dict(row) for row in existing_rows}
        incoming_ids: set[str] = set()
        for record in records:
            record_id = str(record["id"])
            incoming_ids.add(record_id)
            previous = existing_by_id.get(record_id)
            efforts = list(record.get("efforts", []))
            default_effort = record.get("default_effort")
            # A native PUT may customize alias/default_effort.  There is no
            # separate override column in the v2 schema, so retain the old
            # alias and any still-valid old default across discovery refresh.
            if previous is not None:
                previous_alias = str(previous.get("alias") or "").strip()
                if previous_alias:
                    alias = previous_alias
                else:
                    alias = str(record["alias"])
                previous_default = str(previous.get("default_effort") or "").strip()
                if previous_default and previous_default in efforts:
                    default_effort = previous_default
            else:
                alias = str(record["alias"])
            values = (
                record["agent_id"],
                record["cli_id"],
                record["model"],
                alias,
                _json_text(efforts),
                default_effort,
                record["discovery_source"],
                now,
                record_id,
            )
            if previous is None:
                db.execute(
                    "INSERT INTO agent_models(id, agent_id, cli_id, model, alias, source, efforts, default_effort, "
                    "discovery_source, credential_id, native_model_ref, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        record_id,
                        values[0],
                        values[1],
                        values[2],
                        values[3],
                        "native",
                        values[4],
                        values[5],
                        values[6],
                        None,
                        None,
                        now,
                        now,
                    ),
                )
            else:
                db.execute(
                    "UPDATE agent_models SET agent_id=?, cli_id=?, model=?, alias=?, efforts=?, default_effort=?, "
                    "discovery_source=?, credential_id=NULL, native_model_ref=NULL, updated_at=? WHERE id=?",
                    values,
                )
        stale_ids = set(existing_by_id) - incoming_ids
        if stale_ids:
            db.executemany("DELETE FROM agent_models WHERE id=?", [(item,) for item in stale_ids])


def discover_agent(agent_id: str) -> dict[str, Any]:
    """Run bounded native probes and refresh only native model records."""

    ensure_agent_config_schema()
    agent_id = _valid_agent_id(agent_id)
    profile = _profile_row(agent_id)
    binary = _configured_executable(agent_id, str(profile["executable"]))
    present, presence_status, presence_message = _presence(agent_id, binary)
    if not present:
        with _core().connect_db() as db:
            db.execute(
                "UPDATE agent_profiles SET available=0, status=?, message=?, capabilities=?, updated_at=? WHERE id=?",
                (
                    presence_status,
                    presence_message,
                    _json_text({"headless": False, "verified": False, "model_discovery": False}),
                    _now(),
                    agent_id,
                ),
            )
        return get_agent_profile(agent_id)

    with tempfile.TemporaryDirectory(prefix="kxy-agent-probe-") as probe_dir:
        root = Path(probe_dir)
        runtime = _runtime_probe(binary, agent_id, profile.get("runtime_interpreter"), root)
        if runtime.get("required") and runtime.get("status") != "READY":
            runtime_message = str(runtime.get("message") or "Agent runtime 解释器不可用")
            with _core().connect_db() as db:
                db.execute(
                    "UPDATE agent_profiles SET available=0, status='UNHEALTHY', message=?, "
                    "runtime_interpreter=?, runtime_interpreter_version=?, runtime_status=?, runtime_version=?, runtime_checked_at=?, runtime_message=?, "
                    "capabilities=?, updated_at=? WHERE id=?",
                    (
                        f"运行时依赖失败：{runtime_message}",
                        runtime.get("interpreter"),
                        runtime.get("interpreter_version"),
                        runtime.get("status"),
                        runtime.get("version"),
                        _now(),
                        runtime_message,
                        _json_text({"headless": False, "verified": False, "model_discovery": False, "runtime_probe": False}),
                        _now(),
                        agent_id,
                    ),
                )
            return get_agent_profile(agent_id)
        runtime_command = lambda args: _runtime_argv(binary, args, runtime)
        version_rc, version_out, version_err = _probe(runtime_command(["--version"]), root)
        help_rc, help_out, help_err = _probe(runtime_command(_help_command(agent_id, binary)[1:]), root)
        combined_help = (help_out + "\n" + help_err)[:MAX_PROBE_OUTPUT]
        # DSH's launcher can create a missing profile while processing --help;
        # it is therefore never probed until the profile directory was found.
        if agent_id == "deepseek" and (
            help_rc != 0
            or "headless" not in combined_help.lower()
            or not any(word in combined_help.lower() for word in ("answer", "print", "prompt"))
        ):
            help_rc = 125
            help_err = "DSH headless interface did not pass the explicit help verification"
        version = _first_line(version_out) or _first_line(version_err) if version_rc == 0 else None
        if version_rc != 0 and help_rc == 0:
            message = f"帮助协议可用，但版本探测失败：{_first_line(version_err) or 'unknown error'}"
        elif help_rc != 0:
            message = _first_line(help_err) or "headless 帮助探测失败；请检查 CLI 权限和安装状态"
        else:
            message = None
        supported_efforts = _extract_efforts(combined_help) if help_rc == 0 else []
        model_output = ""
        model_discovery = False
        model_probe_ok = True
        model_probe_attempted = False
        if agent_id == "opencode" and help_rc == 0:
            model_probe_attempted = True
            model_rc, model_out, model_err = _probe(runtime_command(["models"]), root)
            if model_rc == 0:
                model_output = model_out
            else:
                model_probe_ok = False
                message = message or f"模型目录不可用：{_first_line(model_err) or f'命令退出码 {model_rc}'}；已保留上次有效目录"
        elif agent_id == "pi" and help_rc == 0:
            model_probe_attempted = True
            # --list-models is a documented read-only catalog command.  It is
            # run with PI_CODING_AGENT_DIR redirected to the temporary probe
            # root and PI_OFFLINE=1, so no global auth/config is refreshed.
            model_rc, model_out, model_err = _probe(runtime_command(["--list-models"]), root)
            if model_rc == 0:
                model_output = model_out
            else:
                model_probe_ok = False
                message = message or f"模型目录不可用：{_first_line(model_err) or f'命令退出码 {model_rc}'}；已保留上次有效目录"
        elif agent_id == "grok" and help_rc == 0:
            model_probe_attempted = True
            # `grok models` is a documented read-only catalog command.  _probe
            # already points HOME at the temporary root, so Grok reads
            # <root>/.grok instead of the real ~/.grok: the real auth.json is
            # never read and no credential is refreshed.  Verified: an
            # unauthenticated probe still exits 0 and lists the full catalog.
            model_rc, model_out, model_err = _probe(runtime_command(["models"]), root)
            if model_rc == 0:
                model_output = model_out
            else:
                model_probe_ok = False
                message = message or f"模型目录不可用：{_first_line(model_err) or f'命令退出码 {model_rc}'}；已保留上次有效目录"
        records = _native_records(agent_id, model_output, combined_help) if help_rc == 0 else []
        model_discovery = bool(records)
        if records:
            for record in records:
                for effort in record["efforts"]:
                    if effort not in supported_efforts:
                        supported_efforts.append(effort)
        native_catalog_replaced = help_rc == 0 and model_probe_ok and bool(records)
        if native_catalog_replaced:
            _store_native_records(agent_id, records)
        elif help_rc == 0 and model_probe_attempted and model_probe_ok and not records:
            message = message or "模型目录没有可解析记录；已保留上次有效目录"
        elif help_rc == 0 and not records:
            message = message or "本次没有可解析的原生模型目录；已保留上次有效目录"
        capabilities = {
            "headless": help_rc == 0,
            "verified": help_rc == 0,
            "model_discovery": model_discovery,
            "version_probe": version_rc == 0,
        }
        with _core().connect_db() as db:
            db.execute(
                "UPDATE agent_profiles SET available=?, version=?, status=?, message=?, supported_efforts=?, "
                "capabilities=?, runtime_interpreter=?, runtime_interpreter_version=?, runtime_status=?, runtime_version=?, runtime_checked_at=?, "
                "runtime_message=?, discovered_at=COALESCE(?, discovered_at), updated_at=? WHERE id=?",
                (
                    int(help_rc == 0),
                    version,
                    "READY" if help_rc == 0 else "UNHEALTHY",
                    message,
                    _json_text(supported_efforts),
                    _json_text(capabilities),
                    runtime.get("interpreter"),
                    runtime.get("interpreter_version"),
                    runtime.get("status"),
                    runtime.get("version"),
                    _now(),
                    runtime.get("message"),
                    _now() if native_catalog_replaced or (not model_probe_attempted and bool(records)) else profile.get("discovered_at"),
                    _now(),
                    agent_id,
                ),
            )
    return get_agent_profile(agent_id)


def refresh_agent(agent_id: str) -> dict[str, Any]:
    """Refresh one profile once, then attach its independent login status."""

    ensure_agent_config_schema()
    agent_id = _valid_agent_id(agent_id)
    with _AGENT_REFRESH_LOCK:
        if agent_id in _AGENT_REFRESH_IN_FLIGHT:
            raise AgentConfigError("该 Agent 正在检查，请等待当前检查完成")
        _AGENT_REFRESH_IN_FLIGHT.add(agent_id)
    try:
        # discover_agent owns the existing version/model/effort probes and
        # preserves non-native saved model records.  Login is a separate
        # native-context status read and never part of the temporary probe.
        discovery_error: str | None = None
        try:
            discover_agent(agent_id)
        except Exception as exc:
            discovery_error = _refresh_error(exc)
        login_error: str | None = None
        try:
            check_agent_login_status(agent_id)
        except Exception as exc:
            login_error = _refresh_error(exc)
        if discovery_error or login_error:
            profile = get_agent_profile(agent_id)
            details = []
            if discovery_error:
                details.append(f"发现阶段：{discovery_error}")
            if login_error:
                details.append(f"登录态阶段：{login_error}")
            profile["refresh_error"] = "；".join(details)
            return profile
        return get_agent_profile(agent_id)
    finally:
        with _AGENT_REFRESH_LOCK:
            _AGENT_REFRESH_IN_FLIGHT.discard(agent_id)


def _refresh_error(exc: Exception) -> str:
    if isinstance(exc, AgentConfigError):
        return _redact(str(exc), 512)
    # Do not surface arbitrary subprocess/fixture exception text from a bulk
    # status endpoint.  It could contain an account or credential payload.
    return "检查失败：内部错误；未返回命令输出。"


def refresh_agents(agent_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Refresh a bounded set concurrently while isolating each failure."""

    requested = list(AGENT_IDS if agent_ids is None else agent_ids)
    if len(requested) > len(AGENT_IDS):
        raise AgentConfigError(f"一次最多检查 {len(AGENT_IDS)} 个 Agent")
    normalized: list[str] = []
    for raw in requested:
        agent_id = _valid_agent_id(str(raw))
        if agent_id not in normalized:
            normalized.append(agent_id)
    results: dict[str, dict[str, Any]] = {}
    max_workers = max(1, min(3, len(normalized))) if normalized else 1
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="kxy-agent-refresh") as executor:
        futures = {executor.submit(refresh_agent, agent_id): agent_id for agent_id in normalized}
        for future in as_completed(futures):
            agent_id = futures[future]
            try:
                profile = future.result()
                results[agent_id] = {
                    "id": agent_id,
                    "ok": True,
                    "partial": bool(profile.get("refresh_error")),
                    "profile": profile,
                }
            except Exception as exc:  # each Agent is independent
                results[agent_id] = {"id": agent_id, "ok": False, "error": _refresh_error(exc)}
    ordered = [results[agent_id] for agent_id in normalized]
    return {
        "results": ordered,
        "agents": [item["profile"] for item in ordered if item.get("ok") and item.get("profile")],
        "checked_at": _now(),
    }


def _skill_frontmatter(skill_file: Path) -> tuple[str, str, dict[str, Any]]:
    try:
        content = skill_file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise AgentConfigError(f"无法读取 SKILL.md：{skill_file}") from exc
    if len(content.encode("utf-8")) > 512 * 1024:
        raise AgentConfigError("SKILL.md 超过 512 KB")
    lines = content.splitlines()
    frontmatter: dict[str, Any] = {}
    if lines and lines[0].strip() == "---":
        end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
        if end is None:
            raise AgentConfigError("SKILL.md frontmatter 未闭合")
        try:
            import yaml

            parsed = yaml.safe_load("\n".join(lines[1:end]))
        except Exception as exc:
            raise AgentConfigError("SKILL.md frontmatter 不是有效 YAML") from exc
        if isinstance(parsed, dict):
            frontmatter = parsed
    name = str(frontmatter.get("name") or skill_file.parent.name).strip()[:128]
    description = str(frontmatter.get("description") or "").strip()[:1024]
    compatibility: list[str] = []
    if frontmatter.get("compatibility"):
        compatibility.append(str(frontmatter["compatibility"])[:1024])
    compatibility.extend(
        line.strip()[:1024]
        for line in lines
        if re.search(r"compatib|dependenc|requirement|install", line, re.IGNORECASE)
    )
    return name, description, {"compatibility": compatibility[:20], "skill_file": "SKILL.md"}


def _safe_skill_snapshot(root: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AgentConfigError(f"Skill 含有未允许的符号链接：{path.relative_to(root)}")
        if not path.is_file():
            continue
        count += 1
        if count > MAX_SKILL_FILES:
            raise AgentConfigError("Skill 文件数超过上限")
        content = path.read_bytes()
        total += len(content)
        if total > MAX_SKILL_BYTES:
            raise AgentConfigError("Skill 总大小超过上限")
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + content)
    return digest.hexdigest(), count, total


def _skill_modified_at(root: Path) -> str:
    """Return the latest included file mtime without exposing file paths.

    A source directory can disappear while a scan is being rendered.  In that
    case the explicit value keeps the API honest and lets the caller decide
    whether to retry; normal files always receive an ISO UTC timestamp.
    """

    latest: float | None = None
    try:
        for path in root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            value = path.stat().st_mtime
            latest = value if latest is None else max(latest, value)
    except OSError:
        return "unavailable"
    if latest is None:
        return "unavailable"
    from datetime import datetime, timezone

    return datetime.fromtimestamp(latest, timezone.utc).isoformat()


def _skill_candidate(
    agent_id: str,
    configured_root: Path,
    root_canonical: Path,
    display_dir: Path,
    canonical_dir: Path,
) -> dict[str, Any] | None:
    skill_file = canonical_dir / "SKILL.md"
    if not skill_file.is_file() or not _inside(skill_file, canonical_dir):
        return None
    try:
        snapshot_hash, file_count, byte_count = _safe_skill_snapshot(canonical_dir)
        name, description, metadata = _skill_frontmatter(skill_file)
    except (OSError, AgentConfigError):
        return None
    try:
        category = display_dir.relative_to(configured_root).parent.as_posix()
    except ValueError:
        category = ""
    return {
        "path": str(display_dir),
        "name": name,
        "description": description,
        "source": f"{agent_id}:{configured_root}",
        "source_agent": agent_id,
        "category": "" if category == "." else category,
        "snapshot_hash": snapshot_hash,
        "file_count": file_count,
        "byte_count": byte_count,
        "modified_at": _skill_modified_at(canonical_dir),
        "metadata": metadata,
    }


def _scan_one_skill_root(
    agent_id: str,
    configured_root: Path,
    *,
    max_skills: int,
    max_depth: int,
) -> list[dict[str, Any]]:
    try:
        root_canonical = configured_root.resolve(strict=True)
    except OSError:
        return []
    if not root_canonical.is_dir():
        return []
    queue: list[tuple[Path, Path, int]] = [(configured_root, root_canonical, 0)]
    visited: set[Path] = set()
    results: list[dict[str, Any]] = []
    total_bytes = 0
    while queue and len(results) < max_skills and len(visited) < MAX_DISCOVERY_DIRS:
        display_dir, canonical_dir, depth = queue.pop(0)
        if canonical_dir in visited:
            continue
        if not canonical_dir.is_dir():
            continue
        visited.add(canonical_dir)
        candidate = _skill_candidate(agent_id, configured_root, root_canonical, display_dir, canonical_dir)
        if candidate is not None:
            total_bytes += int(candidate["byte_count"])
            if total_bytes > MAX_DISCOVERY_BYTES:
                break
            results.append(candidate)
        if depth >= max_depth:
            continue
        try:
            entries = sorted(display_dir.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith(".") and entry.name not in {".well-known"}:
                continue
            try:
                target = entry.resolve(strict=True)
            except OSError:
                continue
            # A configured root may itself be a symlink. Descendant links must
            # remain inside its resolved root, otherwise they are not scanned.
            if not _inside(target, root_canonical):
                continue
            if target.is_dir():
                queue.append((entry, target, depth + 1))
    return results


def scan_agent_skills(
    agent_id: str,
    roots: Sequence[str] | None = None,
    *,
    max_skills: int = MAX_SKILL_CANDIDATES,
    max_depth: int = MAX_SKILL_DEPTH,
) -> list[dict[str, Any]]:
    ensure_agent_config_schema()
    agent_id = _valid_agent_id(agent_id)
    max_skills = max(1, min(int(max_skills), MAX_SKILL_CANDIDATES))
    max_depth = max(0, min(int(max_depth), MAX_SKILL_DEPTH))
    if roots is None:
        roots = get_agent_profile(agent_id)["skill_roots"]
    if not isinstance(roots, Sequence) or isinstance(roots, (str, bytes)):
        raise AgentConfigError("roots 必须是路径数组")
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in list(roots)[:MAX_PROFILE_ROOTS]:
        configured_root = _absolute_lexical(str(raw))
        for candidate in _scan_one_skill_root(
            agent_id,
            configured_root,
            max_skills=max_skills - len(candidates),
            max_depth=max_depth,
        ):
            key = (candidate["path"], candidate["snapshot_hash"])
            if key not in seen:
                seen.add(key)
                candidates.append(candidate)
            if len(candidates) >= max_skills:
                return candidates
    return candidates


def _validate_agent_skill_path(agent_id: str, raw_path: str) -> tuple[Path, Path, dict[str, Any]]:
    lexical = _absolute_lexical(raw_path)
    try:
        canonical = lexical.resolve(strict=True)
    except OSError as exc:
        raise AgentConfigError(f"Skill 路径不存在：{lexical}") from exc
    if not canonical.is_dir() or not (canonical / "SKILL.md").is_file():
        raise AgentConfigError("请选择包含根级 SKILL.md 的 Skill 文件夹")
    configured_roots = get_agent_profile(agent_id)["skill_roots"]
    if not any(
        _lexically_inside(lexical, Path(root))
        and _inside(canonical, Path(root).resolve())
        for root in configured_roots
        if Path(root).exists()
    ):
        raise AgentConfigError("所选 Skill 不在该 Agent 的已配置 Skill 根目录内")
    candidate = _skill_candidate(
        agent_id,
        lexical,
        canonical,
        lexical,
        canonical,
    )
    if candidate is None:
        raise AgentConfigError("Skill 含有不安全的符号链接、超限文件或无法读取的 SKILL.md")
    return lexical, canonical, candidate


def import_agent_skills(agent_id: str, paths: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    ensure_agent_config_schema()
    agent_id = _valid_agent_id(agent_id)
    if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
        raise AgentConfigError("paths 必须是路径数组")
    if len(paths) > 50:
        raise AgentConfigError("一次最多导入 50 个 Skill")
    imported: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    core = _core()
    for raw in paths:
        try:
            lexical, canonical, candidate = _validate_agent_skill_path(agent_id, str(raw))
            with core.connect_db() as db:
                existing = db.execute(
                    "SELECT * FROM skills WHERE snapshot_hash=? ORDER BY created_at LIMIT 1",
                    (candidate["snapshot_hash"],),
                ).fetchone()
            if existing is not None:
                item = core.skill_row(existing)
                item = _merge_local_skill_provenance(item, candidate, agent_id, lexical)
                try:
                    mapping = _skillhub_import_snapshot(
                        Path(existing["root_path"]),
                        kxy_skill_id=str(existing["id"]),
                        name=str(existing["name"]),
                        category=candidate.get("category", ""),
                        snapshot_hash=str(existing["snapshot_hash"]),
                        source_agent=agent_id,
                        source_path=str(lexical),
                    )
                    item = _apply_skillhub_metadata(item, mapping[1])
                except (AgentConfigError, OSError, ValueError) as exc:
                    item = _apply_skillhub_error(item, str(exc))
                imported.append(item)
                continue
            item = core.import_skill_root(canonical)
            metadata = dict(item.get("metadata") or {})
            metadata.update(
                {
                    "native_agent": agent_id,
                    "native_source": str(lexical),
                    "native_snapshot_hash": candidate["snapshot_hash"],
                    "native_category": candidate.get("category", ""),
                    "source_agent": agent_id,
                    "modified_at": candidate.get("modified_at", "unavailable"),
                }
            )
            with core.connect_db() as db:
                db.execute(
                    "UPDATE skills SET metadata=? WHERE id=?",
                    (_json_text(metadata), item["id"]),
                )
                row = db.execute("SELECT * FROM skills WHERE id=?", (item["id"],)).fetchone()
            item = core.skill_row(row) if row is not None else item
            try:
                mapping = _skillhub_import_snapshot(
                    canonical,
                    kxy_skill_id=str(item["id"]),
                    name=str(item["name"]),
                    category=candidate.get("category", ""),
                    snapshot_hash=str(item["snapshot_hash"]),
                    source_agent=agent_id,
                    source_path=str(lexical),
                )
                item = _apply_skillhub_metadata(item, mapping[1])
            except (AgentConfigError, OSError, ValueError) as exc:
                item = _apply_skillhub_error(item, str(exc))
            imported.append(item)
        except (OSError, ValueError, AgentConfigError) as exc:
            errors.append({"path": str(raw), "error": str(exc)})
    return {"imported": imported, "errors": errors}


# ---------------------------------------------------------------------------
# KXY-owned SkillHub boundary
# ---------------------------------------------------------------------------

def _skillhub_home() -> Path:
    return _core().DATA_ROOT / "skillhub"


def _skillhub_runtime_root() -> Path:
    root = _skillhub_home() / ".runtime"
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _git_blob_sha(path: Path) -> str:
    content = path.read_bytes()
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


def _skillhub_vendor_check() -> tuple[bool, str | None]:
    for relative, expected in _SKILLHUB_UPSTREAM_BLOBS.items():
        path = SKILLHUB_VENDOR_ROOT / relative
        try:
            actual = _git_blob_sha(path)
        except OSError:
            return False, f"vendor/skillhub 缺少上游文件：{relative}"
        if actual != expected:
            return False, f"vendor/skillhub 上游文件校验失败：{relative}"
    return True, None


def _skillhub_env(
    runtime_root: Path,
    destination_overrides: Mapping[str, Path] | None = None,
    *,
    runtime_env_presence: Sequence[str] = (),
    runtime_path: str | None = None,
) -> dict[str, str]:
    """Return an environment in which every upstream destination is KXY-owned."""

    runtime_root = Path(runtime_root).resolve()
    data_root = _core().DATA_ROOT.resolve()
    if not _inside(runtime_root, data_root):
        raise AgentConfigError("SkillHub runtime 必须位于 KXY_DATA_ROOT 内")
    runtime_root.mkdir(parents=True, exist_ok=True)
    destination_root = runtime_root / "dest"
    home_root = destination_root / "home"
    home_root.mkdir(parents=True, exist_ok=True)
    agent_root = destination_root / "agent-roots"
    mcp_root = destination_root / "mcp"
    agent_root.mkdir(parents=True, exist_ok=True)
    mcp_root.mkdir(parents=True, exist_ok=True)
    central = _skillhub_home()
    central.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": runtime_path or os.environ.get("PATH", os.defpath),
        "HOME": str(home_root),
        "LANG": os.environ.get("LANG", "C"),
        "NO_COLOR": "1",
        "PYTHONPATH": str(SKILLHUB_VENDOR_ROOT),
        "PYTHONNOUSERSITE": "1",
        "SKILLHUB_HOME": str(central),
        "SKILLHUB_MCP_PI_DIR": str(mcp_root / "pi-servers"),
    }
    overrides = dict(destination_overrides or {})
    for agent in overrides:
        if agent not in _SKILLHUB_AGENT_ENV_IDS:
            raise AgentConfigError(f"未知 SkillHub destination Agent：{agent}")
        override = Path(overrides[agent]).resolve()
        if not _inside(override, _core().DATA_ROOT.resolve()):
            raise AgentConfigError("SkillHub destination 必须位于 KXY_DATA_ROOT 内")
    for agent in _SKILLHUB_AGENT_ENV_IDS:
        destination = Path(overrides.get(agent, agent_root / agent))
        destination.mkdir(parents=True, exist_ok=True)
        env[f"SKILLHUB_AGENT_DIR_{agent}"] = str(destination)
        env[f"SKILLHUB_MCP_FILE_{agent}"] = str(mcp_root / f"{agent}.json")
    for name in runtime_env_presence:
        if isinstance(name, str) and _MCP_ENV_NAME_RE.fullmatch(name) and name not in env:
            # Upstream diagnose_skill only needs presence.  Never pass a
            # Keychain value or the real environment mapping into SkillHub.
            env[name] = "__kxy_runtime_present__"
    # The upstream package has no deepseek adapter, but override the variable
    # anyway so a future package update cannot fall back to a native directory.
    return env


def _run_skillhub(
    args: Sequence[str],
    runtime_root: Path,
    *,
    timeout: float = SKILLHUB_TIMEOUT,
    destination_overrides: Mapping[str, Path] | None = None,
    runtime_env_presence: Sequence[str] = (),
    runtime_path: str | None = None,
) -> tuple[int, str, str]:
    ok, message = _skillhub_vendor_check()
    if not ok:
        raise AgentConfigError(message or "SkillHub vendor 校验失败")
    if not isinstance(args, Sequence) or isinstance(args, (str, bytes)):
        raise AgentConfigError("SkillHub 参数必须是数组")
    command = [str(item) for item in args]
    if any(not item or "\x00" in item or "\n" in item or "\r" in item for item in command):
        raise AgentConfigError("SkillHub 参数包含非法控制字符")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "skillhub", *command],
            cwd=str(Path(runtime_root).resolve()),
            env=_skillhub_env(
                Path(runtime_root),
                destination_overrides,
                runtime_env_presence=runtime_env_presence,
                runtime_path=runtime_path,
            ),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (
            int(completed.returncode),
            _redact((completed.stdout or "")[:SKILLHUB_MAX_OUTPUT], SKILLHUB_MAX_OUTPUT),
            _redact((completed.stderr or "")[:SKILLHUB_MAX_OUTPUT], SKILLHUB_MAX_OUTPUT),
        )
    except subprocess.TimeoutExpired as exc:
        return 124, _redact(str(exc.stdout or "")[:SKILLHUB_MAX_OUTPUT]), f"SkillHub timeout after {timeout:g}s"
    except OSError as exc:
        return 127, "", f"SkillHub unavailable: {type(exc).__name__}: {exc}"


def _run_skillhub_python(
    script: str,
    args: Sequence[str],
    runtime_root: Path,
    *,
    timeout: float = SKILLHUB_TIMEOUT,
    destination_overrides: Mapping[str, Path] | None = None,
    runtime_env_presence: Sequence[str] = (),
    runtime_path: str | None = None,
) -> tuple[int, str, str]:
    """Run a tiny KXY-owned bridge against the pinned vendored package.

    The bridge is used only for upstream APIs which have no CLI flag for a
    task-local source (notably MCP import/render).  It still executes in the
    same bounded, destination-overridden environment as the upstream CLI.
    """

    ok, message = _skillhub_vendor_check()
    if not ok:
        raise AgentConfigError(message or "SkillHub vendor 校验失败")
    if not isinstance(script, str) or not script.strip() or "\x00" in script:
        raise AgentConfigError("SkillHub bridge script 无效")
    if not isinstance(args, Sequence) or isinstance(args, (str, bytes)):
        raise AgentConfigError("SkillHub bridge 参数必须是数组")
    command = [str(item) for item in args]
    if any(not item or "\x00" in item or "\n" in item or "\r" in item for item in command):
        raise AgentConfigError("SkillHub bridge 参数包含非法控制字符")
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, *command],
            cwd=str(Path(runtime_root).resolve()),
            env=_skillhub_env(
                Path(runtime_root),
                destination_overrides,
                runtime_env_presence=runtime_env_presence,
                runtime_path=runtime_path,
            ),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (
            int(completed.returncode),
            _redact((completed.stdout or "")[:SKILLHUB_MAX_OUTPUT], SKILLHUB_MAX_OUTPUT),
            _redact((completed.stderr or "")[:SKILLHUB_MAX_OUTPUT], SKILLHUB_MAX_OUTPUT),
        )
    except subprocess.TimeoutExpired as exc:
        return 124, _redact(str(exc.stdout or "")[:SKILLHUB_MAX_OUTPUT]), f"SkillHub bridge timeout after {timeout:g}s"
    except OSError as exc:
        return 127, "", f"SkillHub bridge unavailable: {type(exc).__name__}: {exc}"


_SKILLHUB_DIAGNOSTIC_BRIDGE = r'''
import json, sys
from skillhub import store

operation = sys.argv[1]
sid = sys.argv[2]
index = store.load_index()
if operation == "diagnose":
    result = store.diagnose_skill(sid)
elif operation == "set-dependencies":
    result = store.set_dependencies(sid, json.loads(sys.argv[3]))
elif operation == "confirm":
    result = store.confirm_diagnostics(sid, json.loads(sys.argv[3]), note=sys.argv[4] if len(sys.argv) > 4 else "")
else:
    raise ValueError("unknown diagnostic operation")
index = store.load_index()
manifest = index.get(sid) or {}
print(json.dumps({
    "diagnosis": result,
    "dependencies": manifest.get("dependencies") or {},
    "diagnostics_verified": manifest.get("diagnostics_verified") or [],
}, ensure_ascii=False, sort_keys=True))
'''


_SKILLHUB_SUMMARY_BRIDGE = r'''
import json, sys
from pathlib import Path
from skillhub.store import file_summary

result = file_summary(Path(sys.argv[1]))
print(json.dumps({
    "md5": result.get("md5"),
    "file_count": result.get("file_count"),
    "size": result.get("size"),
}, ensure_ascii=False, sort_keys=True))
'''


def _skillhub_diagnostic_bridge(
    operation: str,
    upstream_id: str,
    *,
    dependencies: Mapping[str, Any] | None = None,
    keys: Sequence[str] = (),
    note: str = "",
    runtime_env_presence: Sequence[str] = (),
    runtime_path: str | None = None,
) -> dict[str, Any]:
    if operation not in {"diagnose", "set-dependencies", "confirm"}:
        raise AgentConfigError("未知 SkillHub diagnostic 操作")
    runtime_root = _skillhub_runtime_root() / f"diagnose-{uuid.uuid4().hex}"
    args: list[str] = [operation, upstream_id]
    if operation == "set-dependencies":
        args.append(_json_text(dict(dependencies or {})))
    elif operation == "confirm":
        args.extend((_json_text([str(key) for key in keys]), str(note)[:300]))
    try:
        return_code, stdout, stderr = _run_skillhub_python(
            _SKILLHUB_DIAGNOSTIC_BRIDGE,
            args,
            runtime_root,
            runtime_env_presence=runtime_env_presence,
            runtime_path=runtime_path,
        )
        if return_code != 0:
            raise AgentConfigError(f"SkillHub diagnostic failed: {stderr or 'unknown error'}")
        try:
            value = json.loads(stdout.strip())
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AgentConfigError("SkillHub diagnostic 返回了无效 JSON，已拒绝猜测") from exc
        if not isinstance(value, dict) or not isinstance(value.get("diagnosis"), dict):
            raise AgentConfigError("SkillHub diagnostic 返回结构无效")
        return value
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def _skillhub_load_index() -> dict[str, dict[str, Any]]:
    path = _skillhub_home() / "index.json"
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > 20 * 1024 * 1024:
            raise AgentConfigError("SkillHub index 超过大小上限")
        value = json.loads(path.read_text(encoding="utf-8"))
    except AgentConfigError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AgentConfigError("SkillHub index 已损坏，拒绝继续导入或投影") from exc
    if not isinstance(value, dict):
        raise AgentConfigError("SkillHub index 必须是对象")
    for skill_id, manifest in value.items():
        if not isinstance(skill_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", skill_id):
            raise AgentConfigError("SkillHub index 含有不安全的 skill id")
        if not isinstance(manifest, dict):
            raise AgentConfigError("SkillHub index 含有无效 manifest")
    return value


def _skillhub_save_index(index: Mapping[str, Any]) -> None:
    path = _skillhub_home() / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(dict(index), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    temp.replace(path)


def _skillhub_ledger_path() -> Path:
    return _skillhub_home() / "kxy-skill-index.json"


def _skillhub_load_ledger() -> dict[str, Any]:
    path = _skillhub_ledger_path()
    if not path.exists():
        return {"version": 1, "skills": {}}
    try:
        if path.stat().st_size > 20 * 1024 * 1024:
            raise AgentConfigError("KXY SkillHub ledger 超过大小上限")
        value = json.loads(path.read_text(encoding="utf-8"))
    except AgentConfigError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise AgentConfigError("KXY SkillHub ledger 已损坏，拒绝继续导入或投影") from exc
    if not isinstance(value, dict) or not isinstance(value.get("skills", {}), dict):
        raise AgentConfigError("KXY SkillHub ledger 格式无效")
    if "deleted" in value and not isinstance(value.get("deleted"), dict):
        raise AgentConfigError("KXY SkillHub ledger deleted 标记格式无效")
    return value


def _skillhub_save_ledger(ledger: Mapping[str, Any]) -> None:
    path = _skillhub_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(json.dumps(dict(ledger), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    temp.replace(path)


def _skillhub_data_relative(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        resolved = Path(path).resolve(strict=False)
        return str(resolved.relative_to(_core().DATA_ROOT.resolve()))
    except (OSError, ValueError):
        return None


def _skillhub_skillhub_entry(kxy_skill_id: str) -> dict[str, Any] | None:
    ledger = _skillhub_load_ledger()
    entry = ledger.get("skills", {}).get(kxy_skill_id)
    return dict(entry) if isinstance(entry, dict) else None


def skillhub_prepare_skill_delete(row: Mapping[str, Any], *, staged_path: Path | None = None) -> dict[str, Any]:
    """Record a reversible KXY-owned delete intent before touching a snapshot."""

    skill_id = str(row.get("id") or "").strip()
    if not skill_id:
        raise AgentConfigError("Skill 删除缺少稳定 ID")
    metadata = _json(row.get("metadata"), {})
    if not isinstance(metadata, dict):
        metadata = {}
    entry = _skillhub_skillhub_entry(skill_id) or metadata.get("skillhub")
    if not isinstance(entry, dict):
        entry = {}
    marker = {
        "skill_id": skill_id,
        "name": str(row.get("name") or "")[:160],
        "snapshot_hash": str(row.get("snapshot_hash") or ""),
        "upstream_skill_id": str(entry.get("upstream_skill_id") or "") or None,
        "upstream_name": str(entry.get("upstream_name") or "") or None,
        "root_relative": _skillhub_data_relative(Path(str(row.get("root_path") or ""))),
        "staged_relative": _skillhub_data_relative(staged_path),
        "state": "pending",
        "updated_at": _now(),
    }
    ledger = _skillhub_load_ledger()
    deleted = ledger.setdefault("deleted", {})
    if not isinstance(deleted, dict):
        raise AgentConfigError("KXY SkillHub ledger deleted 标记格式无效")
    deleted[skill_id] = marker
    _skillhub_save_ledger(ledger)
    return marker


def skillhub_update_skill_delete(skill_id: str, state: str, **fields: Any) -> dict[str, Any]:
    if state not in {"pending", "committing", "deleted", "cancelled"}:
        raise AgentConfigError("Skill 删除状态无效")
    ledger = _skillhub_load_ledger()
    deleted = ledger.setdefault("deleted", {})
    if not isinstance(deleted, dict):
        raise AgentConfigError("KXY SkillHub ledger deleted 标记格式无效")
    marker = deleted.get(str(skill_id))
    if not isinstance(marker, dict):
        raise AgentConfigError("Skill 删除标记不存在")
    marker = dict(marker)
    marker.update({key: value for key, value in fields.items() if value is not None})
    marker["state"] = state
    marker["updated_at"] = _now()
    deleted[str(skill_id)] = marker
    _skillhub_save_ledger(ledger)
    return marker


def skillhub_cancel_skill_delete(skill_id: str) -> None:
    ledger = _skillhub_load_ledger()
    deleted = ledger.setdefault("deleted", {})
    if not isinstance(deleted, dict):
        raise AgentConfigError("KXY SkillHub ledger deleted 标记格式无效")
    marker = deleted.get(str(skill_id))
    if isinstance(marker, dict) and marker.get("state") != "deleted":
        deleted.pop(str(skill_id), None)
        _skillhub_save_ledger(ledger)


def skillhub_clear_skill_delete_marker(skill_id: str) -> None:
    ledger = _skillhub_load_ledger()
    deleted = ledger.setdefault("deleted", {})
    if not isinstance(deleted, dict):
        raise AgentConfigError("KXY SkillHub ledger deleted 标记格式无效")
    deleted.pop(str(skill_id), None)
    _skillhub_save_ledger(ledger)


def _skillhub_component(value: Any, field: str, *, max_length: int = 128) -> str:
    if not isinstance(value, str):
        raise AgentConfigError(f"SkillHub {field} 必须是文本")
    value = value.strip()
    if not value or len(value) > max_length or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise AgentConfigError(f"SkillHub {field} 含有不安全字符")
    if value in {".", ".."}:
        raise AgentConfigError(f"SkillHub {field} 不能是路径片段")
    return value


def _skillhub_category(value: Any) -> tuple[str, ...]:
    if value in (None, "", "."):
        return ()
    if isinstance(value, (tuple, list)):
        if len(value) > 8 or not all(isinstance(part, str) and part for part in value):
            raise AgentConfigError("SkillHub category 层级无效")
        return tuple(_skillhub_component(part, "category") for part in value)
    if not isinstance(value, str) or value.startswith("/") or "\\" in value:
        raise AgentConfigError("SkillHub category 不是安全的相对路径")
    parts = tuple(part for part in value.split("/") if part)
    if len(parts) > 8:
        raise AgentConfigError("SkillHub category 层级超过上限")
    return tuple(_skillhub_component(part, "category") for part in parts)


def _skillhub_agents(source_agent: Any, target_agent: Any) -> tuple[str, str]:
    source = str(source_agent or "").strip().lower()
    target = _valid_agent_id(str(target_agent or "").strip().lower())
    if source not in SKILLHUB_SUPPORTED_AGENTS:
        raise AgentConfigError(f"来源 Agent {source or 'unknown'} 没有可验证的 SkillHub 投影适配器")
    if target not in SKILLHUB_SUPPORTED_AGENTS:
        raise AgentConfigError(f"目标 Agent {target} 没有可验证的 SkillHub 投影适配器")
    return source, target


def _skillhub_store_snapshot(path: Path) -> str:
    path = Path(path).resolve()
    marker = path / _SKILLHUB_PROJECTION_MARKER
    if marker.exists() or marker.is_symlink():
        raise AgentConfigError("SkillHub 中央或来源副本包含保留 projection marker")
    try:
        return _core().snapshot_skill(path)[0]
    except (OSError, ValueError) as exc:
        raise AgentConfigError(f"SkillHub 中央副本无法完整校验：{path.name}") from exc


def _skillhub_copy_snapshot(path: Path, manifest: Mapping[str, Any]) -> str:
    """Validate a vendored WorkBuddy copy and hash its payload without the marker."""

    path = Path(path).resolve()
    marker = path / _SKILLHUB_PROJECTION_MARKER
    if not marker.is_file() or marker.is_symlink():
        raise AgentConfigError("SkillHub copy projection 缺少安全的 projection marker")
    try:
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AgentConfigError("SkillHub copy projection marker 无效") from exc
    if not isinstance(marker_data, dict):
        raise AgentConfigError("SkillHub copy projection marker 格式无效")
    if type(marker_data.get("schema_version")) is not int or marker_data.get("schema_version") != 2:
        raise AgentConfigError("SkillHub copy projection marker schema 不受支持")
    if type(marker_data.get("skillhub")) is not int or marker_data.get("skillhub") != 1:
        raise AgentConfigError("SkillHub copy projection marker 归属标记无效")
    for field in ("sid", "md5"):
        if not isinstance(marker_data.get(field), str) or marker_data.get(field) != manifest.get("id" if field == "sid" else field):
            raise AgentConfigError(f"SkillHub copy projection marker {field} 与中央 manifest 不一致")
    for field in ("file_count", "size"):
        expected = manifest.get(field)
        if type(marker_data.get(field)) is not int or type(expected) is not int or marker_data.get(field) != expected:
            raise AgentConfigError(f"SkillHub copy projection marker {field} 与中央 manifest 不一致")

    core = _core()
    digest = hashlib.sha256()
    count = 0
    total = 0
    try:
        for item in sorted(item for item in path.rglob("*") if item.is_file()):
            if item == marker:
                continue
            if item.is_symlink():
                raise AgentConfigError("SkillHub copy projection 包含软链接")
            relative = item.relative_to(path).as_posix().encode("utf-8")
            content = item.read_bytes()
            digest.update(relative + b"\0" + content)
            count += 1
            total += len(content)
            if count > core.MAX_SKILL_FILES or total > core.MAX_SKILL_BYTES:
                raise AgentConfigError("SkillHub copy projection 超过 Skill 大小上限")
    except (OSError, ValueError) as exc:
        raise AgentConfigError("SkillHub copy projection 无法完整校验") from exc
    if count != manifest["file_count"] or total != manifest["size"]:
        raise AgentConfigError("SkillHub copy projection payload 摘要计数与中央 manifest 不一致")
    return digest.hexdigest()


def _skillhub_write_projection_marker(path: Path, manifest: Mapping[str, Any], sid: str) -> None:
    marker = Path(path) / _SKILLHUB_PROJECTION_MARKER
    temporary = marker.with_name(f".{marker.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps({
        "schema_version": 2,
        "skillhub": 1,
        "sid": sid,
        "md5": manifest.get("md5", ""),
        "file_count": manifest.get("file_count", 0),
        "size": manifest.get("size", 0),
        "created_at": _now(),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(marker)


def _skillhub_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _skillhub_vendor_summary(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    if not _inside(path, _core().DATA_ROOT.resolve()) or not path.is_dir() or path.is_symlink():
        raise AgentConfigError("SkillHub 摘要来源必须是 KXY_DATA_ROOT 内的安全目录")
    runtime_root = _skillhub_runtime_root() / f"summary-{uuid.uuid4().hex}"
    try:
        return_code, stdout, stderr = _run_skillhub_python(
            _SKILLHUB_SUMMARY_BRIDGE,
            [str(path)],
            runtime_root,
        )
        if return_code != 0:
            raise AgentConfigError(f"SkillHub vendor 摘要失败：{_redact(stderr or 'unknown error', 512)}")
        try:
            value = json.loads(stdout.strip())
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AgentConfigError("SkillHub vendor 摘要返回了无效 JSON") from exc
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("md5"), str)
            or type(value.get("file_count")) is not int
            or type(value.get("size")) is not int
        ):
            raise AgentConfigError("SkillHub vendor 摘要结构无效")
        return value
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def _skillhub_projection_target(target_root: Path, target_agent: str, manifest: Mapping[str, Any]) -> Path:
    target_root = Path(target_root).resolve()
    name = _skillhub_component(manifest.get("name"), "name")
    category = _skillhub_category(manifest.get("category", ""))
    if target_agent == "hermes":
        return target_root.joinpath(*category, name) if category else target_root / "uncategorized" / name
    return target_root / name


def _skillhub_stage_snapshot(source_root: Path, stage_root: Path, stage_name: str, category: tuple[str, ...]) -> Path:
    source_root = Path(source_root).resolve()
    if not source_root.is_dir():
        raise AgentConfigError("Skill 快照来源不是文件夹")
    full_hash = _skillhub_store_snapshot(source_root)
    destination = stage_root.joinpath(*category, stage_name)
    if destination.exists() or destination.is_symlink():
        raise AgentConfigError("SkillHub 临时来源路径已存在")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root, destination, symlinks=False)
    if _skillhub_store_snapshot(destination) != full_hash:
        raise AgentConfigError("SkillHub 临时复制改变了 Skill 内容")
    return destination


def _skillhub_manifest_for(index: Mapping[str, Any], skill_id: str) -> dict[str, Any]:
    value = index.get(skill_id)
    if not isinstance(value, dict):
        raise AgentConfigError(f"SkillHub 中央库缺少副本：{skill_id}")
    if value.get("id") not in (None, skill_id):
        raise AgentConfigError("SkillHub manifest id 与 index 不一致")
    return dict(value)


def _iso_after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _iso_expired(value: Any) -> bool:
    try:
        expires = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc)


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_json_text(value).encode("utf-8")).hexdigest()


def _path_identity(path: str | None) -> dict[str, Any]:
    if not path:
        return {"path": None, "exists": False}
    try:
        resolved = Path(path).resolve(strict=True)
        stat = resolved.stat()
        return {
            "path": str(resolved),
            "exists": True,
            "device": int(stat.st_dev),
            "inode": int(stat.st_ino),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }
    except OSError:
        return {"path": str(path), "exists": False}


def _runtime_fingerprint(
    agent_id: str,
    binary: str | None,
    profile: Mapping[str, Any],
    runtime: Mapping[str, Any] | None = None,
    dependency_fingerprint: str | None = None,
) -> str:
    runtime = runtime or {}
    path_values = [str(item) for item in str(os.environ.get("PATH", os.defpath)).split(os.pathsep) if item]
    payload = {
        "agent_id": agent_id,
        "platform": sys.platform,
        "arch": platform.machine(),
        "cli": _path_identity(binary),
        "cli_version": profile.get("version"),
        "interpreter": _path_identity(str(runtime.get("interpreter") or profile.get("runtime_interpreter") or "")),
        "interpreter_version": runtime.get("interpreter_version") or profile.get("runtime_interpreter_version"),
        "runtime_version": runtime.get("version") or profile.get("runtime_version"),
        "runtime_status": runtime.get("status") or profile.get("runtime_status"),
        "path_hash": _stable_hash(path_values),
        "dependency_runtime": dependency_fingerprint or "",
    }
    return _stable_hash(payload)


def _model_binding_fingerprint(agent_id: str, binding: Mapping[str, Any] | None) -> str:
    binding = binding or {}
    credential_id = str(binding.get("credential_id") or "")
    credential_state: dict[str, Any] = {"id": credential_id}
    if credential_id:
        with _core().connect_db() as db:
            row = db.execute(
                "SELECT c.provider, c.endpoint, c.env_name, m.api_format, m.updated_at "
                "FROM credentials c LEFT JOIN credential_metadata m ON m.credential_id=c.id WHERE c.id=?",
                (credential_id,),
            ).fetchone()
        if row is not None:
            credential_state.update(
                {
                    "provider": str(row["provider"] or ""),
                    "endpoint": str(row["endpoint"] or ""),
                    "env_name": str(row["env_name"] or ""),
                    "api_format": str(row["api_format"] or ""),
                    "updated_at": str(row["updated_at"] or ""),
                }
            )
    return _stable_hash(
        {
            "agent_id": agent_id,
            "model_ref": str(binding.get("model_ref") or ""),
            "model_id": str(binding.get("model_id") or ""),
            "model": str(binding.get("model") or ""),
            "source": str(binding.get("source") or ""),
            "credential": credential_state,
        }
    )


def _skillhub_dependency_context(skill_id: str) -> dict[str, Any]:
    core = _core()
    with core.connect_db() as db:
        row = db.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
    if row is None:
        raise AgentConfigError(f"Skill 不存在，请重新导入：{skill_id}")
    row_dict = dict(row)
    ledger = _skillhub_load_ledger()
    ledger_entry = ledger.get("skills", {}).get(skill_id)
    metadata = _skill_row_metadata(row_dict)
    if not isinstance(ledger_entry, dict):
        ledger_entry = metadata.get("skillhub") if isinstance(metadata.get("skillhub"), dict) else {}
    upstream_id = str(ledger_entry.get("upstream_skill_id") or "").strip()
    index = _skillhub_load_index()
    if not upstream_id and skill_id in index:
        upstream_id = skill_id
    manifest = index.get(upstream_id) if upstream_id else None
    if not isinstance(manifest, dict):
        manifest = None
        upstream_id = ""
    def dependency_values(candidate: Any) -> dict[str, Any]:
        if not isinstance(candidate, dict):
            candidate = {"tools": candidate}
        return {
            key: value
            for key, value in candidate.items()
            if key in {"tools", "env", "services", "network"}
        }

    dependencies = dependency_values(manifest.get("dependencies") if manifest else {})
    # Keep existing local SkillHub/index declarations authoritative.  A
    # portable declaration is only a read-only fallback for Skills that have
    # no local central declaration yet.
    if not dependencies:
        for local_declaration in (ledger_entry, metadata.get("skillhub")):
            if not isinstance(local_declaration, dict):
                continue
            candidate = local_declaration.get("dependencies", local_declaration)
            dependencies = dependency_values(candidate)
            if dependencies:
                break
    if not dependencies:
        portable = metadata.get("portable_declarations")
        if isinstance(portable, dict):
            dependencies = dependency_values(portable)
            if not dependencies:
                dependencies = dependency_values(portable.get("skillhub"))
    return {
        "row": row_dict,
        "metadata": metadata,
        "upstream_id": upstream_id,
        "manifest": manifest,
        "dependencies": dependencies,
        "dependency_hash": _stable_hash(dependencies),
        "content_hash": str(row_dict.get("snapshot_hash") or ""),
    }


def _runtime_env_presence(agent_id: str, binding: Mapping[str, Any] | None, mcp_ids: Sequence[str] = ()) -> set[str]:
    # Only report variables that the actual child environment is allowlisted
    # to receive.  Arbitrary host variables and credential names are not
    # inherited merely because they exist in this parent process.
    present = {key for key in SAFE_ENV_KEYS if os.environ.get(key)}
    binding = binding or {}
    credential_id = str(binding.get("credential_id") or "")
    if credential_id:
        row = _credential_row(credential_id)
        if row is not None:
            name = str(row["env_name"] or "").strip().upper()
            if _MCP_ENV_NAME_RE.fullmatch(name):
                # prepare_headless_environment obtains the value from the
                # existing Keychain reference at launch time.
                present.add(name)
    if mcp_ids:
        index = _mcp_load_index()
        for raw_id in mcp_ids:
            definition = index.get(str(raw_id))
            if isinstance(definition, dict):
                present.update(name for name in _mcp_all_env_refs(definition) if os.environ.get(name))
    return present


_TRUSTED_RUNTIME_TOOLS = frozenset({"node", "nodejs", "python", "python3", "git", "npm", "ffmpeg", "curl", "wget", "docker"})


def _skill_diagnostic_text(root: Path) -> str:
    """Read a small, text-only view for local inference on cache misses.

    The cache key uses the immutable Skill snapshot hash, so the pre-cache
    path must not rescan every file just to rediscover inferred names.  A
    bounded text pass is only used when a local Skill actually needs static
    diagnosis; binary assets and user-provided executables are skipped.
    """

    text_suffixes = frozenset(
        {
            ".bash",
            ".cjs",
            ".css",
            ".csv",
            ".go",
            ".html",
            ".ini",
            ".js",
            ".json",
            ".jsx",
            ".md",
            ".mjs",
            ".py",
            ".rb",
            ".rs",
            ".sh",
            ".sql",
            ".toml",
            ".ts",
            ".tsx",
            ".txt",
            ".xml",
            ".yaml",
            ".yml",
            ".zsh",
        }
    )
    parts: list[str] = []
    total = 0
    count = 0
    try:
        candidates = root.rglob("*")
    except OSError:
        return ""
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            continue
        if count >= MAX_SKILL_TEXT_FILES or total >= MAX_SKILL_TEXT_BYTES:
            break
        if path.suffix.lower() not in text_suffixes:
            continue
        try:
            if path.stat().st_size > MAX_SKILL_TEXT_FILE_BYTES:
                continue
            remaining = MAX_SKILL_TEXT_BYTES - total
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                raw = handle.read(remaining)
        except (OSError, UnicodeError):
            continue
        count += 1
        total += len(raw.encode("utf-8", "replace"))
        parts.append(raw)
    return "\n".join(parts)


def _dependency_runtime_context(
    context: Mapping[str, Any],
    env_presence: set[str],
    *,
    runtime_path: str | None = None,
    include_text: bool = False,
) -> dict[str, Any]:
    root = Path(str((context.get("row") or {}).get("root_path") or ""))
    text = _skill_diagnostic_text(root) if include_text and root.is_dir() else ""
    dependencies = context.get("dependencies") if isinstance(context.get("dependencies"), dict) else {}
    declared_tools = dependencies.get("tools") or []
    declared_env = dependencies.get("env") or []
    if isinstance(declared_tools, str):
        declared_tools = [declared_tools]
    if isinstance(declared_env, str):
        declared_env = [declared_env]
    tools: list[str] = [str(item).strip() for item in declared_tools if isinstance(item, str) and str(item).strip()]
    tools.extend(name for name in sorted(_TRUSTED_RUNTIME_TOOLS.intersection(set(re.findall(r"\b[A-Za-z][A-Za-z0-9_.-]*\b", text)))) if name not in tools)
    env_names: list[str] = [str(item).strip() for item in declared_env if isinstance(item, str) and str(item).strip()]
    for match in re.finditer(r"(?:os\.environ(?:\.get)?|getenv)\s*\(?[\"']([A-Z][A-Z0-9_]+)", text):
        if match.group(1) not in env_names:
            env_names.append(match.group(1))
    for match in _MCP_ENV_ANY_RE.finditer(text):
        name = next((group for group in match.groups() if group), "")
        if name and name not in env_names:
            env_names.append(name)
    runtime_path = runtime_path or os.environ.get("PATH", os.defpath)
    # Fingerprint all fixed, trusted command resolutions.  This catches a
    # PATH/tool replacement without reading arbitrary Skill files on every
    # cache lookup; actual probes still run only for names reported by the
    # static diagnosis on a cache miss.
    identity_names = set(tools) | set(_TRUSTED_RUNTIME_TOOLS)
    tool_identities = {
        name: _path_identity(shutil.which(name, path=runtime_path))
        for name in sorted(identity_names)
    }
    env_states = {name: bool(name in env_presence) for name in sorted(set(env_names))}
    return {
        "text": text,
        "tools": sorted(set(tools)),
        "env": sorted(set(env_names)),
        "tool_identities": tool_identities,
        "env_states": env_states,
        "env_presence_hash": _stable_hash(sorted(env_presence)),
        "os_env_names_hash": _stable_hash(
            sorted(name for name in os.environ if _MCP_ENV_NAME_RE.fullmatch(str(name)))
        ),
        "runtime_path": runtime_path,
        "fingerprint": _stable_hash(
            {
                "tools": tool_identities,
                "env": env_states,
                "env_presence": _stable_hash(sorted(env_presence)),
                "os_env_names": _stable_hash(
                    sorted(name for name in os.environ if _MCP_ENV_NAME_RE.fullmatch(str(name)))
                ),
                "path": _stable_hash(runtime_path.split(os.pathsep)),
            }
        ),
    }


def _trusted_tool_probe(name: str, runtime_path: str) -> dict[str, Any]:
    if name not in _TRUSTED_RUNTIME_TOOLS:
        return {"name": name, "status": "unverified", "reason": "未知工具不自动执行"}
    path = shutil.which(name, path=runtime_path)
    if not path:
        return {"name": name, "status": "missing"}
    try:
        with tempfile.TemporaryDirectory(prefix="kxy-tool-probe-") as probe_dir:
            env = {"PATH": runtime_path, "LANG": os.environ.get("LANG", "C"), "NO_COLOR": "1", "HOME": probe_dir}
            version_arg = "-version" if name == "ffmpeg" else "--version"
            process = subprocess.run(
                [path, version_arg],
                cwd=probe_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT,
                check=False,
            )
        output = _first_line((process.stdout or "").strip()) or _first_line((process.stderr or "").strip()) or ""
        return {
            "name": name,
            "status": "verified" if process.returncode == 0 else "unverified",
            "version": output[:160] if process.returncode == 0 else None,
            "reason": None if process.returncode == 0 else "固定版本探针未通过",
        }
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "unverified", "reason": "固定版本探针超时"}
    except OSError as exc:
        return {"name": name, "status": "unverified", "reason": _redact(str(exc), 240)}


def _local_static_diagnosis(
    context: Mapping[str, Any], runtime_path: str, env_presence: set[str]
) -> dict[str, Any]:
    diagnostic = _dependency_runtime_context(
        context, env_presence, runtime_path=runtime_path, include_text=True
    )
    dependencies = context.get("dependencies") if isinstance(context.get("dependencies"), dict) else {}
    declared_tools = dependencies.get("tools") or []
    declared_env = dependencies.get("env") or []
    if isinstance(declared_tools, str):
        declared_tools = [declared_tools]
    if isinstance(declared_env, str):
        declared_env = [declared_env]
    explicit_tools = {str(item).strip() for item in declared_tools if str(item).strip()}
    explicit_env = {str(item).strip() for item in declared_env if str(item).strip()}
    tools = []
    for name in diagnostic["tools"]:
        identity = diagnostic["tool_identities"].get(name, {})
        explicit = name in explicit_tools
        tools.append(
            {
                "name": name,
                "source": "declared" if explicit else "inferred",
                "certainty": "explicit" if explicit else "inferred",
                "kind": "tool",
                "status": "present" if identity.get("exists") else "missing" if explicit else "verify",
            }
        )
    env = []
    for name in diagnostic["env"]:
        present = bool(diagnostic["env_states"].get(name))
        explicit = name in explicit_env
        env.append(
            {
                "name": name,
                "source": "declared" if explicit else "inferred",
                "certainty": "explicit" if explicit else "inferred",
                "kind": "env",
                "status": "present" if present else "missing" if explicit else "verify",
            }
        )
    missing = [item for item in [*tools, *env] if item["status"] == "missing"]
    manual = [item for item in [*tools, *env] if item["status"] == "verify"]
    return {
        "diagnosis": {
            "tools": tools,
            "env": env,
            "inferred": [],
            "missing": missing,
            "needs_manual": manual,
            "blocking": bool(missing),
        },
        "dependencies": dependencies,
        "diagnostics_verified": [],
        "runtime_context": diagnostic,
    }


def _dependency_cache_key(
    *,
    skill_id: str,
    content_hash: str,
    dependency_hash: str,
    agent_id: str,
    model_binding_hash: str,
    runtime_fingerprint: str,
) -> str:
    return _stable_hash(
        {
            "skill_id": skill_id,
            "content_hash": content_hash,
            "dependency_hash": dependency_hash,
            "agent_id": agent_id,
            "model_binding_hash": model_binding_hash,
            "runtime_fingerprint": runtime_fingerprint,
            "checker_version": DEPENDENCY_CHECKER_VERSION,
            "skillhub_upstream_commit": SKILLHUB_UPSTREAM_COMMIT,
        }
    )


def _dependency_cache_public(row: Mapping[str, Any], *, cache_hit: bool | None = None) -> dict[str, Any]:
    result = _json(row.get("result_json"), {})
    if not isinstance(result, dict):
        result = {"status": "unknown", "message": "缓存记录损坏"}
    result = json.loads(_json_text(result))
    result["cache_hit"] = bool(row.get("cache_hit")) if cache_hit is None else cache_hit
    result["checked_at"] = row.get("checked_at")
    result["expires_at"] = row.get("expires_at")
    result["duration_ms"] = int(row.get("duration_ms") or 0)
    result["invalidation_reason"] = row.get("invalidation_reason")
    return result


def _dependency_cache_reason(skill_id: str, agent_id: str, context: Mapping[str, Any], runtime_fingerprint: str) -> str | None:
    with _core().connect_db() as db:
        row = db.execute(
            "SELECT content_hash, dependency_hash, runtime_fingerprint, checker_version, expires_at "
            "FROM skill_dependency_checks WHERE skill_id=? AND agent_id=? ORDER BY checked_at DESC LIMIT 1",
            (skill_id, agent_id),
        ).fetchone()
    if row is None:
        return None
    if str(row["content_hash"]) != str(context.get("content_hash")):
        return "skill_content_changed"
    if str(row["dependency_hash"]) != str(context.get("dependency_hash")):
        return "dependency_declaration_changed"
    if str(row["runtime_fingerprint"]) != runtime_fingerprint:
        return "runtime_changed"
    if str(row["checker_version"]) != DEPENDENCY_CHECKER_VERSION:
        return "checker_changed"
    if _iso_expired(row["expires_at"]):
        return "expired"
    return None


def _save_runtime_probe(agent_id: str, result: Mapping[str, Any]) -> None:
    with _core().connect_db() as db:
        db.execute(
            "UPDATE agent_profiles SET runtime_interpreter=?, runtime_interpreter_version=?, runtime_status=?, runtime_version=?, "
            "runtime_checked_at=?, runtime_message=?, updated_at=? WHERE id=?",
            (
                result.get("interpreter"),
                result.get("interpreter_version"),
                str(result.get("status") or "unknown"),
                result.get("version"),
                _now(),
                result.get("message"),
                _now(),
                agent_id,
            ),
        )


def _normalize_dependency_diagnosis(
    skill_id: str,
    context: Mapping[str, Any],
    payload: Mapping[str, Any],
    runtime: Mapping[str, Any],
    *,
    runtime_path: str,
) -> dict[str, Any]:
    diagnosis = payload.get("diagnosis") if isinstance(payload.get("diagnosis"), dict) else {}
    missing = [item for item in diagnosis.get("missing", []) if isinstance(item, dict)]
    manual = [item for item in diagnosis.get("needs_manual", []) if isinstance(item, dict)]
    tool_items = [item for item in diagnosis.get("tools", []) if isinstance(item, dict)]
    inferred_items = [item for item in diagnosis.get("inferred", []) if isinstance(item, dict)]
    trusted_names = sorted(
        {
            str(item.get("name"))
            for item in [*tool_items, *inferred_items]
            if str(item.get("name") or "") in _TRUSTED_RUNTIME_TOOLS
        }
    )
    trusted_checks = [_trusted_tool_probe(name, runtime_path) for name in trusted_names]
    trusted_by_name = {str(item["name"]): item for item in trusted_checks}
    for item in [*tool_items, *inferred_items]:
        checked = trusted_by_name.get(str(item.get("name") or ""))
        if checked is None:
            item.setdefault("verification", "not_run")
        else:
            item["verification"] = checked.get("status")
            if checked.get("status") == "verified" and item.get("status") in {"present", "verify"}:
                item["status"] = "verified"
    verified_names = {name for name, item in trusted_by_name.items() if item.get("status") == "verified"}
    manual = [item for item in manual if not (str(item.get("kind")) == "tool" and str(item.get("name")) in verified_names)]
    dependencies = context.get("dependencies") if isinstance(context.get("dependencies"), dict) else {}
    declared_services = dependencies.get("services")
    if isinstance(declared_services, str):
        declared_services = [declared_services]
    if isinstance(declared_services, list):
        manual.extend(
            {
                "name": str(item)[:160],
                "kind": "service",
                "source": "declared",
                "certainty": "explicit",
                "status": "verify",
            }
            for item in declared_services
            if isinstance(item, str) and item.strip()
        )
    if "network" in dependencies:
        manual.append(
            {
                "name": "network",
                "kind": "network",
                "source": "declared",
                "certainty": "explicit",
                "status": "verify",
                "value": bool(dependencies.get("network")),
            }
        )
    runtime_status = str(runtime.get("status") or "unknown")
    runtime_pending = runtime_status in {"NOT_CHECKED", "not_checked", "unknown"}
    runtime_failure = not runtime_pending and runtime_status not in {"READY", "NOT_REQUIRED"}
    if runtime_failure:
        status = "runtime_failed"
    elif missing:
        status = "blocked"
    elif manual or runtime_pending:
        status = "manual"
    else:
        status = "ready"
    return {
        "skill_id": skill_id,
        "upstream_skill_id": context.get("upstream_id") or None,
        "status": status,
        "blocking": bool(runtime_failure or missing),
        "runtime": {
            "status": runtime_status,
            "interpreter": runtime.get("interpreter"),
            "version": runtime.get("version"),
            "message": runtime.get("message"),
        },
        "tools": tool_items,
        "env": [item for item in diagnosis.get("env", []) if isinstance(item, dict)],
        "inferred": inferred_items,
        "missing": missing,
        "needs_manual": manual,
        "declared_dependencies": dependencies,
        "trusted_tool_checks": trusted_checks,
        "upstream_blocking": bool(diagnosis.get("blocking")),
        "source": "skillhub_static_plus_kxy_runtime_probe",
        "message": (
            "Agent runtime 未通过短启动检查；未执行 Skill、脚本、服务或模型。"
            if runtime_failure
            else "依赖声明已更新；Agent runtime 尚未执行短启动检查。"
            if runtime_pending
            else "SkillHub 只做静态依赖与存在性检查；服务、网络和 inferred 项仍需人工确认。"
            if manual
            else "静态依赖检查通过；这不代表已执行 Skill 或 MCP handshake。"
        ),
    }


def _check_skill_dependencies(
    skill_id: str,
    agent_id: str,
    binding: Mapping[str, Any] | None,
    *,
    force: bool = False,
    mcp_ids: Sequence[str] = (),
) -> dict[str, Any]:
    ensure_agent_config_schema()
    agent_id = _valid_agent_id(agent_id)
    skill_id = str(skill_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", skill_id):
        raise AgentConfigError("skill_id 无效")
    context = _skillhub_dependency_context(skill_id)
    profile = _profile_row(agent_id)
    binary = _configured_executable(agent_id, str(profile["executable"]))
    if not binary:
        raise AgentConfigError(f"Agent {agent_id} 可执行文件不可用；未执行 SkillHub diagnosis")
    model_hash = _model_binding_fingerprint(agent_id, binding)
    env_presence = _runtime_env_presence(agent_id, binding, mcp_ids)
    dependency_runtime = _dependency_runtime_context(
        context,
        env_presence,
        runtime_path=os.environ.get("PATH", os.defpath),
        include_text=False,
    )
    runtime_path = str(dependency_runtime.get("runtime_path") or os.environ.get("PATH", os.defpath))
    selected_runtime_interpreter = (binding or {}).get("runtime_interpreter") or profile.get("runtime_interpreter")
    pre_runtime = {
        "interpreter": selected_runtime_interpreter,
        "interpreter_version": profile.get("runtime_interpreter_version"),
        "version": profile.get("runtime_version"),
        "status": profile.get("runtime_status"),
    }
    pre_runtime_hash = _runtime_fingerprint(
        agent_id,
        binary,
        profile,
        pre_runtime,
        dependency_fingerprint=str(dependency_runtime["fingerprint"]),
    )
    pre_key = _dependency_cache_key(
        skill_id=skill_id,
        content_hash=context["content_hash"],
        dependency_hash=context["dependency_hash"],
        agent_id=agent_id,
        model_binding_hash=model_hash,
        runtime_fingerprint=pre_runtime_hash,
    )
    if not force:
        with _core().connect_db() as db:
            cached = db.execute("SELECT * FROM skill_dependency_checks WHERE cache_key=?", (pre_key,)).fetchone()
        if cached is not None and not _iso_expired(cached["expires_at"]):
            return _dependency_cache_public(dict(cached), cache_hit=True)

    started = datetime.now(timezone.utc)
    runtime = _runtime_probe(
        binary,
        agent_id,
        (binding or {}).get("runtime_interpreter") or profile.get("runtime_interpreter"),
    )
    _save_runtime_probe(agent_id, runtime)
    profile = _profile_row(agent_id)
    runtime_hash = _runtime_fingerprint(
        agent_id,
        binary,
        profile,
        runtime,
        dependency_fingerprint=str(dependency_runtime["fingerprint"]),
    )
    cache_key = _dependency_cache_key(
        skill_id=skill_id,
        content_hash=context["content_hash"],
        dependency_hash=context["dependency_hash"],
        agent_id=agent_id,
        model_binding_hash=model_hash,
        runtime_fingerprint=runtime_hash,
    )
    if not force:
        with _core().connect_db() as db:
            cached = db.execute("SELECT * FROM skill_dependency_checks WHERE cache_key=?", (cache_key,)).fetchone()
        if cached is not None and not _iso_expired(cached["expires_at"]):
            return _dependency_cache_public(dict(cached), cache_hit=True)

    if context.get("upstream_id"):
        payload = _skillhub_diagnostic_bridge(
            "diagnose",
            str(context["upstream_id"]),
            runtime_env_presence=sorted(env_presence),
            runtime_path=runtime_path,
        )
        result = _normalize_dependency_diagnosis(
            skill_id, context, payload, runtime, runtime_path=runtime_path
        )
    else:
        payload = _local_static_diagnosis(context, runtime_path, env_presence)
        result = _normalize_dependency_diagnosis(
            skill_id, context, payload, runtime, runtime_path=runtime_path
        )
        result["source"] = "kxy_local_static_plus_runtime_probe"
    duration_ms = max(0, int((datetime.now(timezone.utc) - started).total_seconds() * 1000))
    checked_at = _now()
    ttl = DEPENDENCY_CHECK_SUCCESS_TTL if result.get("status") == "ready" else DEPENDENCY_CHECK_PENDING_TTL
    invalidation = _dependency_cache_reason(skill_id, agent_id, context, runtime_hash)
    expires_at = _iso_after(ttl)
    with _core().connect_db() as db:
        db.execute(
            "INSERT INTO skill_dependency_checks(cache_key, skill_id, content_hash, dependency_hash, agent_id, "
            "model_binding_hash, runtime_fingerprint, checker_version, result_json, checked_at, expires_at, duration_ms, cache_hit, invalidation_reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET result_json=excluded.result_json, "
            "checked_at=excluded.checked_at, expires_at=excluded.expires_at, duration_ms=excluded.duration_ms, "
            "cache_hit=0, invalidation_reason=excluded.invalidation_reason",
            (
                cache_key,
                skill_id,
                context["content_hash"],
                context["dependency_hash"],
                agent_id,
                model_hash,
                runtime_hash,
                DEPENDENCY_CHECKER_VERSION,
                _json_text(result),
                checked_at,
                expires_at,
                duration_ms,
                0,
                invalidation,
            ),
        )
        db.execute(
            "DELETE FROM skill_dependency_checks WHERE rowid NOT IN "
            "(SELECT rowid FROM skill_dependency_checks ORDER BY checked_at DESC LIMIT ?)",
            (DEPENDENCY_CHECK_MAX_ROWS,),
        )
        saved = db.execute("SELECT * FROM skill_dependency_checks WHERE cache_key=?", (cache_key,)).fetchone()
    return _dependency_cache_public(dict(saved), cache_hit=False) if saved is not None else {
        **result,
        "cache_hit": False,
        "checked_at": checked_at,
        "expires_at": expires_at,
        "duration_ms": duration_ms,
        "invalidation_reason": invalidation,
    }


def check_skill_dependencies(
    agent_id: str,
    skill_ids: Sequence[str],
    *,
    force: bool = False,
    binding: Mapping[str, Any] | None = None,
    mcp_ids: Sequence[str] = (),
) -> dict[str, Any]:
    if not isinstance(skill_ids, Sequence) or isinstance(skill_ids, (str, bytes)):
        raise AgentConfigError("skill_ids 必须是数组")
    if len(skill_ids) > 50:
        raise AgentConfigError("一次最多检查 50 个 Skill")
    normalized = list(dict.fromkeys(str(item or "").strip() for item in skill_ids if str(item or "").strip()))
    if not normalized:
        return {"agent_id": _valid_agent_id(agent_id), "skills": [], "status": "skipped", "checked_at": _now()}
    with _DEPENDENCY_CHECK_LOCK:
        results = [
            _check_skill_dependencies(item, agent_id, binding, force=force, mcp_ids=mcp_ids)
            for item in normalized
        ]
    return {
        "agent_id": _valid_agent_id(agent_id),
        "skills": results,
        "status": "blocked" if any(item.get("blocking") for item in results) else "ready",
        "checked_at": _now(),
        "force": bool(force),
        "cache": {
            "hits": sum(1 for item in results if item.get("cache_hit")),
            "misses": sum(1 for item in results if not item.get("cache_hit")),
            "ttl_success_seconds": DEPENDENCY_CHECK_SUCCESS_TTL,
            "ttl_pending_seconds": DEPENDENCY_CHECK_PENDING_TTL,
        },
    }


def list_dependency_checks(skill_id: str | None = None) -> list[dict[str, Any]]:
    ensure_agent_config_schema()
    query = "SELECT * FROM skill_dependency_checks"
    args: tuple[Any, ...] = ()
    if skill_id:
        query += " WHERE skill_id=?"
        args = (str(skill_id),)
    query += " ORDER BY checked_at DESC LIMIT ?"
    args = (*args, DEPENDENCY_CHECK_MAX_ROWS)
    with _core().connect_db() as db:
        rows = db.execute(query, args).fetchall()
    result = []
    for row in rows:
        item = _dependency_cache_public(dict(row), cache_hit=False)
        item["cache_key"] = str(row["cache_key"])
        item["skill_id"] = str(row["skill_id"])
        item["agent_id"] = str(row["agent_id"])
        item["checker_version"] = str(row["checker_version"])
        result.append(item)
    return result


def clear_dependency_checks(skill_id: str | None = None) -> int:
    ensure_agent_config_schema()
    with _core().connect_db() as db:
        if skill_id:
            cursor = db.execute("DELETE FROM skill_dependency_checks WHERE skill_id=?", (str(skill_id),))
        else:
            cursor = db.execute("DELETE FROM skill_dependency_checks")
        return int(cursor.rowcount if cursor.rowcount is not None else 0)


def _ensure_skillhub_dependency_mapping(context: Mapping[str, Any]) -> dict[str, Any]:
    """Enroll a local immutable snapshot before a dependency write.

    Some older/local imports predate the SkillHub ledger and therefore have no
    ``upstream_id``.  Dependency declarations still belong to the same
    immutable central snapshot, so the first explicit edit promotes that
    snapshot through the existing import path instead of rejecting the edit.
    """

    upstream_id = str(context.get("upstream_id") or "").strip()
    if upstream_id:
        return dict(context)
    row = context.get("row") if isinstance(context.get("row"), Mapping) else {}
    skill_id = str(row.get("id") or "").strip()
    root_path = Path(str(row.get("root_path") or ""))
    if not skill_id or not root_path.is_dir():
        raise AgentConfigError("该本地 Skill 快照不可用，无法纳入 SkillHub 中央库")
    metadata = context.get("metadata") if isinstance(context.get("metadata"), Mapping) else {}
    source_agent = _skill_source_agent(metadata, "codex")
    if source_agent not in SKILLHUB_SUPPORTED_AGENTS:
        source_agent = "codex"
    _manifest, entry = _skillhub_import_snapshot(
        root_path,
        kxy_skill_id=skill_id,
        name=str(row.get("name") or skill_id),
        category=metadata.get("native_category", ""),
        snapshot_hash=str(row.get("snapshot_hash") or context.get("content_hash") or ""),
        source_agent=source_agent,
        source_path=str(metadata.get("native_source") or "") or None,
    )
    _apply_skillhub_metadata({"id": skill_id, "metadata": dict(metadata)}, entry)
    return _skillhub_dependency_context(skill_id)


def set_skill_dependencies(skill_id: str, dependencies: Mapping[str, Any]) -> dict[str, Any]:
    context = _skillhub_dependency_context(str(skill_id))
    context = _ensure_skillhub_dependency_mapping(context)
    upstream_id = str(context.get("upstream_id") or "")
    if not upstream_id:
        raise AgentConfigError("该 Skill 未能纳入 SkillHub 中央库，不能设置依赖声明")
    result = _skillhub_diagnostic_bridge("set-dependencies", upstream_id, dependencies=dependencies)
    clear_dependency_checks(str(skill_id))
    return _normalize_dependency_diagnosis(
        str(skill_id),
        _skillhub_dependency_context(str(skill_id)),
        result,
        {"status": "not_checked", "interpreter": None, "version": None, "message": "依赖声明已更新；等待运行时检查"},
        runtime_path=os.environ.get("PATH", os.defpath),
    )


def confirm_skill_diagnostics(skill_id: str, keys: Sequence[str], note: str = "") -> dict[str, Any]:
    context = _skillhub_dependency_context(str(skill_id))
    context = _ensure_skillhub_dependency_mapping(context)
    upstream_id = str(context.get("upstream_id") or "")
    if not upstream_id:
        raise AgentConfigError("该 Skill 未能纳入 SkillHub 中央库，不能确认诊断项")
    result = _skillhub_diagnostic_bridge("confirm", upstream_id, keys=keys, note=note)
    clear_dependency_checks(str(skill_id))
    return _normalize_dependency_diagnosis(
        str(skill_id),
        _skillhub_dependency_context(str(skill_id)),
        result,
        {"status": "not_checked", "interpreter": None, "version": None, "message": "人工确认已记录；等待运行时检查"},
        runtime_path=os.environ.get("PATH", os.defpath),
    )


def _save_skill_metadata(skill_id: str, metadata: Mapping[str, Any]) -> dict[str, Any]:
    core = _core()
    with core.connect_db() as db:
        db.execute("UPDATE skills SET metadata=? WHERE id=?", (_json_text(dict(metadata)), skill_id))
        row = db.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
    return core.skill_row(row) if row is not None else {"id": skill_id, "metadata": dict(metadata)}


def _merge_local_skill_provenance(
    item: Mapping[str, Any], candidate: Mapping[str, Any], agent_id: str, lexical: Path
) -> dict[str, Any]:
    result = dict(item)
    metadata = dict(result.get("metadata") or {})
    metadata.setdefault("source_agent", agent_id)
    metadata.setdefault("native_agent", agent_id)
    metadata["modified_at"] = str(candidate.get("modified_at") or metadata.get("modified_at") or "unavailable")
    agents = [str(value) for value in metadata.get("native_agents", []) if isinstance(value, str)]
    for value in (metadata.get("native_agent"), agent_id):
        if value and str(value) not in agents:
            agents.append(str(value))
    metadata["native_agents"] = agents
    sources = [value for value in metadata.get("native_sources", []) if isinstance(value, dict)]
    record = {"agent": agent_id, "path": str(lexical)}
    if record not in sources:
        sources.append(record)
    metadata["native_sources"] = sources
    saved = _save_skill_metadata(str(result["id"]), metadata)
    result.update(saved)
    return result


def _skillhub_metadata_payload(entry: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "status": "ready",
        "upstream_skill_id": entry.get("upstream_skill_id"),
        "upstream_commit": SKILLHUB_UPSTREAM_COMMIT,
        "snapshot_hash": entry.get("snapshot_hash"),
        "source_agents": [value for value in entry.get("source_agents", []) if isinstance(value, str)],
        "projections": entry.get("projections", {}),
    }
    history = [
        value for value in entry.get("legacy_upstream_skill_ids", [])
        if isinstance(value, str) and value and value != payload["upstream_skill_id"]
    ]
    if history:
        payload["legacy_upstream_skill_ids"] = list(dict.fromkeys(history))
    return payload


def _skillhub_sync_metadata_reference(kxy_skill_id: str, entry: Mapping[str, Any]) -> None:
    core = _core()
    with core.connect_db() as db:
        row = db.execute("SELECT metadata FROM skills WHERE id=?", (str(kxy_skill_id),)).fetchone()
        if row is None:
            return
        metadata = _json(row["metadata"], {})
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["skillhub"] = _skillhub_metadata_payload(entry)
        db.execute("UPDATE skills SET metadata=? WHERE id=?", (_json_text(metadata), str(kxy_skill_id)))


def _apply_skillhub_metadata(item: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(item)
    metadata = dict(result.get("metadata") or {})
    metadata["skillhub"] = _skillhub_metadata_payload(entry)
    result = _save_skill_metadata(str(result["id"]), metadata)
    return result


def _apply_skillhub_error(item: Mapping[str, Any], message: str) -> dict[str, Any]:
    result = dict(item)
    metadata = dict(result.get("metadata") or {})
    metadata["skillhub"] = {
        "status": "blocked",
        "upstream_commit": SKILLHUB_UPSTREAM_COMMIT,
        "message": _redact(str(message), 512),
    }
    return _save_skill_metadata(str(result["id"]), metadata)


def _skillhub_existing_snapshot(index: Mapping[str, Any], upstream_id: str) -> str | None:
    manifest = index.get(upstream_id)
    store_path = _skillhub_home() / "store" / upstream_id
    if manifest is None:
        if store_path.exists():
            raise AgentConfigError("SkillHub 中央 store 存在无 index 的副本，拒绝猜测其归属")
        return None
    if not store_path.is_dir() or store_path.is_symlink():
        raise AgentConfigError(f"SkillHub manifest 没有安全的中央副本：{upstream_id}")
    return _skillhub_store_snapshot(store_path)


def _skillhub_manifest_summary_matches(manifest: Mapping[str, Any], store_path: Path) -> bool:
    summary = _skillhub_vendor_summary(store_path)
    return (
        manifest.get("md5") == summary["md5"]
        and type(manifest.get("file_count")) is int
        and manifest.get("file_count") == summary["file_count"]
        and type(manifest.get("size")) is int
        and manifest.get("size") == summary["size"]
    )


def _skillhub_matching_candidates(
    index: Mapping[str, Any],
    *,
    snapshot_hash: str,
    kxy_skill_id: str,
    name: str,
    category: tuple[str, ...],
) -> list[tuple[str, dict[str, Any]]]:
    """Return only complete central copies using the current vendor identity rule."""

    expected_category = "/".join(category)
    candidates: list[tuple[str, dict[str, Any]]] = []
    for raw_id, raw_manifest in index.items():
        if not isinstance(raw_id, str) or not isinstance(raw_manifest, dict):
            continue
        if raw_manifest.get("name") != name:
            continue
        manifest_kxy_id = raw_manifest.get("kxy_skill_id")
        if manifest_kxy_id not in (None, "", kxy_skill_id):
            continue
        try:
            manifest_category = "/".join(_skillhub_category(raw_manifest.get("category", "")))
        except AgentConfigError:
            continue
        if manifest_category != expected_category:
            continue
        store_path = _skillhub_home() / "store" / raw_id
        if not store_path.is_dir() or store_path.is_symlink():
            continue
        try:
            if _skillhub_store_snapshot(store_path) != snapshot_hash:
                continue
            if not _skillhub_manifest_summary_matches(raw_manifest, store_path):
                continue
        except (AgentConfigError, OSError, ValueError):
            continue
        manifest = dict(raw_manifest)
        manifest.setdefault("id", raw_id)
        candidates.append((raw_id, manifest))
    return candidates


def _skillhub_upsert_metadata(
    *,
    kxy_skill_id: str,
    name: str,
    category: Any,
    snapshot_hash: str,
    upstream_id: str,
    upstream_name: str,
    source_agent: str,
    source_path: str | None,
    migration_from: str | None = None,
) -> dict[str, Any]:
    category = _skillhub_category(category)
    ledger = _skillhub_load_ledger()
    entries = ledger.setdefault("skills", {})
    previous = entries.get(kxy_skill_id)
    if previous is not None:
        if not isinstance(previous, dict) or previous.get("snapshot_hash") != snapshot_hash:
            raise AgentConfigError("同一个 KXY Skill id 的完整快照发生变化，拒绝覆盖")
        entry = dict(previous)
    else:
        entry = {
            "skill_id": kxy_skill_id,
            "name": name,
            "category": "/".join(category),
            "snapshot_hash": snapshot_hash,
            "upstream_skill_id": upstream_id,
            "upstream_name": upstream_name,
            "upstream_commit": SKILLHUB_UPSTREAM_COMMIT,
            "source_agents": [],
            "sources": [],
            "projections": {},
        }
    previous_upstream_id = str(entry.get("upstream_skill_id") or "")
    if previous_upstream_id not in ("", upstream_id):
        if not migration_from or previous_upstream_id != migration_from:
            raise AgentConfigError("KXY SkillHub mapping 已指向另一份 upstream 副本")
        history = [
            value for value in entry.get("legacy_upstream_skill_ids", [])
            if isinstance(value, str) and value
        ]
        if previous_upstream_id not in history:
            history.append(previous_upstream_id)
        entry["legacy_upstream_skill_ids"] = list(dict.fromkeys(history))
    entry["upstream_skill_id"] = upstream_id
    entry["upstream_name"] = upstream_name
    entry["upstream_commit"] = SKILLHUB_UPSTREAM_COMMIT
    agents = [str(value) for value in entry.get("source_agents", []) if isinstance(value, str)]
    if source_agent not in agents:
        agents.append(source_agent)
    entry["source_agents"] = agents
    sources = [value for value in entry.get("sources", []) if isinstance(value, dict)]
    source_record = {"agent": source_agent}
    if source_path:
        source_record["path"] = source_path
    if source_record not in sources:
        sources.append(source_record)
    entry["sources"] = sources
    entry["updated_at"] = _now()
    _skillhub_sync_metadata_reference(kxy_skill_id, entry)
    entries[kxy_skill_id] = entry
    _skillhub_save_ledger(ledger)
    return entry


def _skillhub_merge_legacy_manifest_fields(
    old_manifest: Mapping[str, Any] | None,
    new_manifest: dict[str, Any],
) -> None:
    """Carry dependency metadata without overwriting a conflicting value."""

    if not isinstance(old_manifest, Mapping):
        return
    old_dependencies = old_manifest.get("dependencies")
    new_dependencies = new_manifest.get("dependencies")
    if old_dependencies is not None:
        if new_dependencies is None:
            new_manifest["dependencies"] = _json(old_dependencies, old_dependencies)
        elif isinstance(old_dependencies, dict) and isinstance(new_dependencies, dict):
            merged = dict(new_dependencies)
            for key, value in old_dependencies.items():
                if key in merged and merged[key] != value:
                    raise AgentConfigError("SkillHub 新旧中央副本的依赖声明冲突，未覆盖")
                merged[key] = value
            new_manifest["dependencies"] = merged
        elif old_dependencies != new_dependencies:
            raise AgentConfigError("SkillHub 新旧中央副本的依赖声明冲突，未覆盖")
    old_verified = old_manifest.get("diagnostics_verified")
    new_verified = new_manifest.get("diagnostics_verified")
    if old_verified is not None:
        if not isinstance(old_verified, list) or (new_verified is not None and not isinstance(new_verified, list)):
            raise AgentConfigError("旧 SkillHub 诊断声明格式无效，未覆盖")
        new_values = new_verified if isinstance(new_verified, list) else []
        new_manifest["diagnostics_verified"] = sorted(
            set(value for value in new_values if isinstance(value, str))
            | set(value for value in old_verified if isinstance(value, str))
        )


def _skillhub_import_snapshot(
    source_root: Path,
    *,
    kxy_skill_id: str,
    name: str,
    category: Any,
    snapshot_hash: str,
    source_agent: str,
    source_path: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Import or reuse one immutable snapshot through the pinned SkillHub."""

    source_agent = str(source_agent or "").strip().lower()
    if source_agent not in SKILLHUB_SUPPORTED_AGENTS:
        raise AgentConfigError(f"来源 Agent {source_agent or 'unknown'} 没有可验证的 SkillHub 适配器")
    name = _skillhub_component(name, "name")
    category_parts = _skillhub_category(category)
    actual_hash = _skillhub_store_snapshot(Path(source_root).resolve())
    if actual_hash != snapshot_hash:
        raise AgentConfigError("SkillHub 来源快照 hash 与数据库记录不一致")
    source_root = Path(source_root).resolve()
    skill_file = source_root / "SKILL.md"
    if not skill_file.is_file() or skill_file.is_symlink():
        raise AgentConfigError("SkillHub 来源缺少安全的 SKILL.md")
    index = _skillhub_load_index()
    ledger = _skillhub_load_ledger()
    previous = ledger.get("skills", {}).get(kxy_skill_id)
    if previous is not None:
        if not isinstance(previous, dict) or previous.get("snapshot_hash") != snapshot_hash:
            raise AgentConfigError("KXY SkillHub ledger 检测到完整快照冲突")
        stage_name = str(previous.get("upstream_name") or "")
        if stage_name:
            stage_name = _skillhub_component(stage_name, "upstream_name")
        else:
            stage_name = name
    else:
        stage_name = name

    previous_upstream_id = str(previous.get("upstream_skill_id") or "") if isinstance(previous, dict) else ""
    previous_manifest = index.get(previous_upstream_id) if previous_upstream_id else None
    if previous_upstream_id and isinstance(previous_manifest, dict):
        previous_store = _skillhub_home() / "store" / previous_upstream_id
        if previous_store.exists():
            if not previous_store.is_dir() or previous_store.is_symlink():
                raise AgentConfigError("既有 SkillHub 中央副本不是安全目录，未覆盖")
            if _skillhub_store_snapshot(previous_store) != snapshot_hash:
                raise AgentConfigError("SkillHub 既有 upstream 副本与当前完整快照冲突，未覆盖")

    candidates = _skillhub_matching_candidates(
        index,
        snapshot_hash=snapshot_hash,
        kxy_skill_id=kxy_skill_id,
        name=stage_name,
        category=category_parts,
    )
    if len(candidates) > 1:
        raise AgentConfigError("SkillHub 中央库存在多个完整 hash 与新摘要均匹配的副本，拒绝猜测映射")
    upstream_id: str | None = candidates[0][0] if candidates else None
    manifest: dict[str, Any] | None = candidates[0][1] if candidates else None
    migration_from = previous_upstream_id if previous_upstream_id and upstream_id != previous_upstream_id else None

    runtime_root = _skillhub_runtime_root() / f"import-{uuid.uuid4().hex}"
    stage_root = runtime_root / "source"
    try:
        if upstream_id is None:
            _skillhub_stage_snapshot(source_root, stage_root, stage_name, category_parts)
            return_code, stdout, stderr = _run_skillhub(
                ["import", "--agent", source_agent, "--json", "--apply"],
                runtime_root,
                destination_overrides={source_agent: stage_root},
            )
            if return_code != 0:
                raise AgentConfigError(f"SkillHub central import failed: {stderr or stdout or 'unknown error'}")
            index = _skillhub_load_index()
            candidates = _skillhub_matching_candidates(
                index,
                snapshot_hash=snapshot_hash,
                kxy_skill_id=kxy_skill_id,
                name=stage_name,
                category=category_parts,
            )
            if len(candidates) != 1:
                raise AgentConfigError("SkillHub import 后无法唯一解析符合新摘要规则的中央副本，拒绝猜测映射")
            upstream_id, manifest = candidates[0]
            migration_from = previous_upstream_id if previous_upstream_id and upstream_id != previous_upstream_id else None
        assert upstream_id is not None and manifest is not None
        store_path = _skillhub_home() / "store" / upstream_id
        stored_hash = _skillhub_store_snapshot(store_path)
        if stored_hash != snapshot_hash:
            raise AgentConfigError("SkillHub central store full hash mismatch; import blocked")
        if not _skillhub_manifest_summary_matches(manifest, store_path):
            raise AgentConfigError("SkillHub central manifest 未通过当前摘要规则，未覆盖")
        if migration_from:
            _skillhub_merge_legacy_manifest_fields(previous_manifest, manifest)
        manifest["kxy_skill_id"] = kxy_skill_id
        manifest["kxy_snapshot_hash"] = snapshot_hash
        source_agents = [value for value in manifest.get("kxy_source_agents", []) if isinstance(value, str)]
        if source_agent not in source_agents:
            source_agents.append(source_agent)
        manifest["kxy_source_agents"] = source_agents
        manifest["kxy_upstream_commit"] = SKILLHUB_UPSTREAM_COMMIT
        index[upstream_id] = manifest
        _skillhub_save_index(index)
        entry = _skillhub_upsert_metadata(
            kxy_skill_id=kxy_skill_id,
            name=name,
            category=category_parts,
            snapshot_hash=snapshot_hash,
            upstream_id=upstream_id,
            upstream_name=stage_name,
            source_agent=source_agent,
            source_path=source_path,
            migration_from=migration_from,
        )
        return manifest, entry
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


_SKILLHUB_LINK_BLOCKING_TYPES = frozenset(
    {"error", "broken", "store_drift", "blocked", "conflict", "copy_drift"}
)


def _skillhub_link_json(stdout: str, *, mode: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        payload = json.loads(stdout.strip())
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AgentConfigError("SkillHub projection 返回了无效 JSON，拒绝猜测") from exc
    if not isinstance(payload, dict) or payload.get("mode") != mode or not isinstance(payload.get("actions"), dict):
        raise AgentConfigError("SkillHub projection JSON 结构无效，拒绝继续")
    actions: list[dict[str, Any]] = []
    for agent, rows in payload["actions"].items():
        if not isinstance(agent, str) or not isinstance(rows, list):
            raise AgentConfigError("SkillHub projection actions 结构无效")
        for action in rows:
            if not isinstance(action, dict) or not isinstance(action.get("type"), str):
                raise AgentConfigError("SkillHub projection action 缺少安全 type")
            actions.append(dict(action))
    return payload, actions


def _skillhub_link_action_detail(actions: Sequence[Mapping[str, Any]]) -> str:
    details = []
    for action in actions:
        action_type = str(action.get("type") or "error")
        if action_type in _SKILLHUB_LINK_BLOCKING_TYPES:
            detail = _redact(str(action.get("detail") or action_type), 512)
            details.append(f"{action_type}: {detail}")
    return "; ".join(details)[:1200]


def _skillhub_migrate_owned_projection(
    expected: Path,
    *,
    projection_root: Path,
    central_store: Path,
    projection_mode: str,
    manifest: Mapping[str, Any],
    entry: Mapping[str, Any],
    known_projection: Mapping[str, Any] | None,
    snapshot_hash: str,
) -> bool:
    """Migrate only a ledger-owned old projection with two full-hash checks."""

    history = {
        value for value in entry.get("legacy_upstream_skill_ids", [])
        if isinstance(value, str) and value
    }
    if not isinstance(known_projection, Mapping):
        return False
    if (
        known_projection.get("mode") != projection_mode
        or known_projection.get("path") != str(expected.relative_to(_core().DATA_ROOT.resolve()))
        or known_projection.get("snapshot_hash") != snapshot_hash
    ):
        return False
    old_id = str(known_projection.get("upstream_skill_id") or "")
    if old_id not in history:
        return False
    index = _skillhub_load_index()
    old_manifest = index.get(old_id)
    old_store = _skillhub_home() / "store" / old_id
    if not isinstance(old_manifest, dict) or not old_store.is_dir() or old_store.is_symlink():
        return False
    if not _inside(expected.parent.resolve(strict=False), projection_root.resolve(strict=False)):
        return False
    if _skillhub_store_snapshot(old_store) != snapshot_hash:
        return False
    if _skillhub_store_snapshot(central_store) != snapshot_hash:
        return False
    new_id = str(manifest.get("id") or "")
    if not new_id or new_id == old_id:
        return False
    if projection_mode == "symlink":
        if not expected.is_symlink() or expected.resolve(strict=False) != old_store.resolve(strict=False):
            return False
        temporary = expected.with_name(f".{expected.name}.migrate-{uuid.uuid4().hex}")
        temporary.symlink_to(central_store)
        expected.unlink()
        temporary.rename(expected)
        return True
    if projection_mode != "copy" or expected.is_symlink() or not expected.is_dir():
        return False
    if _skillhub_copy_snapshot(expected, old_manifest) != snapshot_hash:
        return False
    temporary = expected.with_name(f".{expected.name}.migrate-{uuid.uuid4().hex}")
    backup = expected.with_name(f".{expected.name}.legacy-{uuid.uuid4().hex}")
    try:
        shutil.copytree(central_store, temporary, symlinks=False)
        _skillhub_write_projection_marker(temporary, manifest, new_id)
        if _skillhub_copy_snapshot(temporary, manifest) != snapshot_hash:
            raise AgentConfigError("新 SkillHub copy projection 完整 hash 校验失败")
        expected.rename(backup)
        temporary.rename(expected)
        shutil.rmtree(backup)
        return True
    except Exception:
        if temporary.exists() and not expected.exists():
            try:
                temporary.rename(expected)
            except OSError:
                pass
        if backup.exists() and not expected.exists():
            try:
                backup.rename(expected)
            except OSError:
                pass
        raise


def _skillhub_project_snapshot(
    source_root: Path,
    *,
    kxy_skill_id: str,
    name: str,
    category: Any,
    snapshot_hash: str,
    source_agent: str,
    target_agent: str,
    source_path: str | None = None,
    projection_root: Path | None = None,
) -> dict[str, Any]:
    """Import and, when needed, project an immutable SkillHub snapshot."""

    source_agent, target_agent = _skillhub_agents(source_agent, target_agent)
    manifest, entry = _skillhub_import_snapshot(
        source_root,
        kxy_skill_id=kxy_skill_id,
        name=name,
        category=category,
        snapshot_hash=snapshot_hash,
        source_agent=source_agent,
        source_path=source_path,
    )
    if source_agent == target_agent:
        entry["status"] = "same-agent"
        return {
            "skill_id": kxy_skill_id,
            "source_agent": source_agent,
            "target_agent": target_agent,
            "cross_agent": False,
            "status": "same-agent",
            "message": "来源与目标 Agent 相同，保留本地 Skill 快照",
            "upstream_skill_id": manifest["id"],
            "snapshot_hash": snapshot_hash,
            "upstream_commit": SKILLHUB_UPSTREAM_COMMIT,
            "projection": None,
        }
    if target_agent not in SKILLHUB_SUPPORTED_AGENTS:
        raise AgentConfigError(f"目标 Agent {target_agent} 没有可验证的 SkillHub 投影适配器")
    if projection_root is None:
        projection_root = _skillhub_home() / "projections" / target_agent
    projection_root = Path(projection_root).resolve()
    if not _inside(projection_root, _core().DATA_ROOT.resolve()):
        raise AgentConfigError("SkillHub projection 必须位于 KXY_DATA_ROOT 内")
    if projection_root.is_symlink() or (projection_root.exists() and not projection_root.is_dir()):
        raise AgentConfigError("SkillHub projection 根目录不是安全的普通目录")
    projection_root.mkdir(parents=True, exist_ok=True)
    expected = _skillhub_projection_target(projection_root, target_agent, manifest)
    projection_mode = "copy" if target_agent == "workbuddy" else "symlink"
    ledger = _skillhub_load_ledger()
    ledger_entry = dict(ledger.get("skills", {}).get(kxy_skill_id) or entry)
    known_projection = (ledger_entry.get("projections") or {}).get(target_agent)
    central_store = (_skillhub_home() / "store" / str(manifest["id"])).resolve()
    projection_migrated = False
    if expected.is_symlink() or expected.exists():
        if projection_mode == "symlink" and expected.is_symlink() and expected.resolve() == central_store:
            projected_hash = _skillhub_store_snapshot(expected.resolve())
            if projected_hash != snapshot_hash:
                raise AgentConfigError("既有 SkillHub projection 内容冲突")
        elif _skillhub_migrate_owned_projection(
            expected,
            projection_root=projection_root,
            central_store=central_store,
            projection_mode=projection_mode,
            manifest=manifest,
            entry=ledger_entry,
            known_projection=known_projection,
            snapshot_hash=snapshot_hash,
        ):
            projection_migrated = True
        elif projection_mode == "copy" and expected.is_dir() and not expected.is_symlink():
            expected_relative = str(expected.relative_to(_core().DATA_ROOT.resolve()))
            if not isinstance(known_projection, dict) or known_projection.get("mode") != "copy" or known_projection.get("path") != expected_relative:
                raise AgentConfigError("目标 Agent 已存在未由 KXY ledger 记录的 copy projection")
            projected_hash = _skillhub_copy_snapshot(expected, manifest)
            if projected_hash != snapshot_hash or known_projection.get("snapshot_hash") != snapshot_hash:
                raise AgentConfigError("既有 SkillHub copy projection 内容冲突")
        else:
            raise AgentConfigError(f"目标 Agent 已存在非 SkillHub projection：{expected.name}")
    elif not projection_migrated:
        runtime_root = _skillhub_runtime_root() / f"project-{uuid.uuid4().hex}"
        try:
            return_code, stdout, stderr = _run_skillhub(
                ["link", str(manifest["id"]), "--agents", target_agent, "--json", "--dry-run"],
                runtime_root,
                destination_overrides={target_agent: projection_root},
            )
            preview_actions: list[dict[str, Any]] = []
            if stdout.strip():
                _preview, preview_actions = _skillhub_link_json(stdout, mode="plan")
            elif return_code == 0:
                raise AgentConfigError("SkillHub projection preview 未返回 JSON")
            if return_code != 0:
                raise AgentConfigError(
                    f"SkillHub projection preview failed for target Agent {target_agent}; "
                    f"expected target: {expected}; {_skillhub_link_action_detail(preview_actions) or _redact(stderr or 'unknown error', 512)}"
                )
            preview_detail = _skillhub_link_action_detail(preview_actions)
            if preview_detail:
                raise AgentConfigError(f"SkillHub projection preview blocked: {preview_detail}")
            return_code, stdout, stderr = _run_skillhub(
                ["link", str(manifest["id"]), "--agents", target_agent, "--json", "--apply"],
                runtime_root,
                destination_overrides={target_agent: projection_root},
            )
            apply_actions: list[dict[str, Any]] = []
            if stdout.strip():
                _apply, apply_actions = _skillhub_link_json(stdout, mode="apply")
            elif return_code == 0:
                raise AgentConfigError("SkillHub projection apply 未返回 JSON")
            if return_code != 0:
                raise AgentConfigError(
                    f"SkillHub projection failed for target Agent {target_agent}; "
                    f"expected target: {expected}; {_skillhub_link_action_detail(apply_actions) or _redact(stderr or 'unknown error', 512)}"
                )
            apply_detail = _skillhub_link_action_detail(apply_actions)
            if apply_detail:
                raise AgentConfigError(f"SkillHub projection apply blocked: {apply_detail}")
        finally:
            shutil.rmtree(runtime_root, ignore_errors=True)
    if not expected.exists() and not expected.is_symlink():
        raise AgentConfigError(
            f"SkillHub projection command completed without creating target for Agent {target_agent}; "
            f"expected target: {expected}"
        )
    actual = expected.resolve()
    if projection_mode == "symlink":
        if not expected.is_symlink() or not _inside(actual, _skillhub_home() / "store"):
            raise AgentConfigError("SkillHub symlink projection 越过中央 store 边界")
    else:
        if expected.is_symlink() or not _inside(actual, projection_root):
            raise AgentConfigError("SkillHub copy projection 越过目标目录边界")
    projected_hash = (
        _skillhub_copy_snapshot(actual, manifest)
        if projection_mode == "copy"
        else _skillhub_store_snapshot(actual)
    )
    if projected_hash != snapshot_hash:
        raise AgentConfigError("SkillHub projection full hash 校验失败")
    entry = dict(ledger.get("skills", {}).get(kxy_skill_id) or entry)
    projections = dict(entry.get("projections") or {})
    projections[target_agent] = {
        "target_agent": target_agent,
        "path": str(expected.relative_to(_core().DATA_ROOT.resolve())),
        "mode": projection_mode,
        "snapshot_hash": snapshot_hash,
        "upstream_skill_id": manifest["id"],
        "created_at": _now(),
    }
    entry["projections"] = projections
    ledger.setdefault("skills", {})[kxy_skill_id] = entry
    _skillhub_save_ledger(ledger)
    return {
        "skill_id": kxy_skill_id,
        "source_agent": source_agent,
        "target_agent": target_agent,
        "cross_agent": True,
        "status": "ready",
        "message": "已通过固定版本 SkillHub 完成中央导入和目标 projection",
        "upstream_skill_id": manifest["id"],
        "snapshot_hash": snapshot_hash,
        "upstream_commit": SKILLHUB_UPSTREAM_COMMIT,
        "projection": str(expected.relative_to(_core().DATA_ROOT.resolve())),
    }


def _skill_row_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("metadata", {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, json.JSONDecodeError):
            value = {}
    return dict(value) if isinstance(value, dict) else {}


def _skill_source_agent(metadata: Mapping[str, Any], target_agent: str) -> str:
    candidates: list[str] = []
    for key in ("source_agents", "native_agents"):
        values = metadata.get(key, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            candidates.extend(str(value).strip().lower() for value in values if str(value).strip())
    for key in ("source_agent", "native_agent"):
        if metadata.get(key):
            candidates.append(str(metadata[key]).strip().lower())
    candidates = list(dict.fromkeys(candidates))
    if target_agent in candidates:
        return target_agent
    for candidate in candidates:
        if candidate in SKILLHUB_SUPPORTED_AGENTS:
            return candidate
    return candidates[0] if candidates else "local"


_SKILLHUB_SYNC_ACTIONS = frozenset({"repair", "add", "restore"})


def _skillhub_manifest_fingerprint(manifest: Mapping[str, Any] | None) -> str | None:
    if not isinstance(manifest, Mapping):
        return None
    return _stable_hash({
        key: manifest.get(key)
        for key in (
            "id", "name", "category", "md5", "file_count", "size",
            "dependencies", "diagnostics_verified", "kxy_skill_id",
            "kxy_snapshot_hash", "kxy_source_agents", "logical_id",
            "formal_sid", "ul_sid", "channel",
        )
    })


def _skillhub_mapping_fingerprint(
    manifest: Mapping[str, Any] | None,
    *,
    old_manifest: Mapping[str, Any] | None = None,
    ledger_entry: Mapping[str, Any] | None = None,
    tombstone: Mapping[str, Any] | None = None,
) -> str:
    """Bind a scan item to both central metadata and its KXY association."""

    ledger_fields = (
        "skill_id", "name", "category", "snapshot_hash", "upstream_skill_id",
        "upstream_name", "upstream_commit", "source_agents", "sources",
        "projections", "legacy_upstream_skill_ids",
    )
    tombstone_fields = (
        "skill_id", "snapshot_hash", "upstream_skill_id", "upstream_name",
        "root_relative", "staged_relative", "state", "updated_at",
    )
    return _stable_hash({
        "manifest": _skillhub_manifest_fingerprint(manifest),
        "old_manifest": _skillhub_manifest_fingerprint(old_manifest),
        "ledger": (
            {field: ledger_entry.get(field) for field in ledger_fields}
            if isinstance(ledger_entry, Mapping) else None
        ),
        "deleted": (
            {field: tombstone.get(field) for field in tombstone_fields}
            if isinstance(tombstone, Mapping) else None
        ),
    })


def _skillhub_mapped_store_matches(upstream_id: str, snapshot_hash: str) -> bool:
    """Require the prior ledger mapping to still contain the same full snapshot."""

    if not upstream_id:
        return True
    store_path = _skillhub_home() / "store" / upstream_id
    if not store_path.is_dir() or store_path.is_symlink():
        return False
    try:
        return _skillhub_store_snapshot(store_path) == snapshot_hash
    except (AgentConfigError, OSError, ValueError):
        return False


def _skillhub_scan_central(index: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    home = _skillhub_home()
    store_root = home / "store"
    if store_root.exists() and (store_root.is_symlink() or not store_root.is_dir()):
        raise AgentConfigError("SkillHub store 根目录不是安全的普通目录")
    store_ids: set[str] = set()
    if store_root.is_dir():
        for child in store_root.iterdir():
            if child.is_dir() and not child.is_symlink():
                store_ids.add(child.name)
    records: dict[str, dict[str, Any]] = {}
    for skill_id in sorted(set(index) | store_ids):
        manifest = index.get(skill_id)
        store_path = store_root / skill_id
        record: dict[str, Any] = {
            "central_id": skill_id,
            "manifest": dict(manifest) if isinstance(manifest, dict) else None,
            "store_path": store_path,
            "valid": False,
            "snapshot_hash": None,
            "summary_valid": False,
            "manifest_fingerprint": _skillhub_manifest_fingerprint(manifest),
        }
        if not isinstance(manifest, dict):
            record.update({"status": "missing", "reason": "central store 存在无 index 的副本"})
        elif not store_path.exists():
            record.update({"status": "missing", "reason": "index manifest 对应的 central store 缺失"})
        elif store_path.is_symlink() or not store_path.is_dir():
            record.update({"status": "conflict", "reason": "central store 副本不是安全目录"})
        else:
            try:
                full_hash = _skillhub_store_snapshot(store_path)
                summary_valid = _skillhub_manifest_summary_matches(manifest, store_path)
                record["snapshot_hash"] = full_hash
                record["summary_valid"] = summary_valid
                record["valid"] = summary_valid
                if not summary_valid:
                    record.update({"status": "stale", "reason": "manifest 未通过当前 vendor 摘要规则"})
                else:
                    record["status"] = "valid"
            except (AgentConfigError, OSError, ValueError) as exc:
                record.update({"status": "conflict", "reason": _redact(str(exc), 512)})
        records[skill_id] = record
    return records


def _skillhub_scan_item(
    *,
    key: str,
    status: str,
    name: str = "",
    skill_id: str | None = None,
    upstream_id: str | None = None,
    snapshot_hash: str | None = None,
    reason: str = "",
    actions: Sequence[str] = (),
    manifest_fingerprint: str | None = None,
) -> dict[str, Any]:
    item = {
        "key": key,
        "status": status,
        "name": name[:160],
        "skill_id": skill_id,
        "upstream_skill_id": upstream_id,
        "snapshot_hash": snapshot_hash,
        "manifest_fingerprint": manifest_fingerprint,
        "reason": _redact(reason, 512) if reason else None,
        "actions": [action for action in actions if action in _SKILLHUB_SYNC_ACTIONS],
    }
    item["fingerprint"] = _stable_hash({
        field: item[field]
        for field in ("key", "status", "name", "skill_id", "upstream_skill_id", "snapshot_hash", "manifest_fingerprint", "reason", "actions")
    })
    return item


def scan_skillhub_index() -> dict[str, Any]:
    """Read only the isolated KXY SkillHub/index state and local snapshots."""

    index = _skillhub_load_index()
    ledger = _skillhub_load_ledger()
    central = _skillhub_scan_central(index)
    core = _core()
    with core.connect_db() as db:
        rows = db.execute(
            "SELECT id, name, root_path, snapshot_hash, metadata FROM skills ORDER BY id"
        ).fetchall()
    live_by_id = {str(row["id"]): dict(row) for row in rows}
    ledger_skills = ledger.get("skills", {}) if isinstance(ledger.get("skills", {}), dict) else {}
    deleted = ledger.get("deleted", {}) if isinstance(ledger.get("deleted", {}), dict) else {}
    items: list[dict[str, Any]] = []
    associated_central: set[str] = set()

    for skill_id in sorted(live_by_id):
        row = live_by_id[skill_id]
        metadata = _skill_row_metadata(row)
        ledger_entry = ledger_skills.get(skill_id)
        if not isinstance(ledger_entry, dict):
            ledger_entry = metadata.get("skillhub") if isinstance(metadata.get("skillhub"), dict) else {}
        upstream_id = str(ledger_entry.get("upstream_skill_id") or "")
        snapshot_hash = str(row.get("snapshot_hash") or "")
        root = Path(str(row.get("root_path") or ""))
        root_status = "ok"
        try:
            resolved = root.resolve(strict=False)
            if not _inside(resolved, core.SKILLS_ROOT) or resolved == core.SKILLS_ROOT.resolve() or root.is_symlink() or not resolved.is_dir():
                root_status = "conflict"
            elif _skillhub_store_snapshot(resolved) != snapshot_hash:
                root_status = "conflict"
        except (OSError, RuntimeError, ValueError, AgentConfigError):
            root_status = "conflict"
        name = str(row.get("name") or skill_id)
        category = _skillhub_category(metadata.get("native_category", ""))
        candidates: list[tuple[str, dict[str, Any]]] = []
        if root_status == "ok":
            for central_id, record in central.items():
                manifest = record.get("manifest")
                if not record.get("valid") or not isinstance(manifest, dict) or record.get("snapshot_hash") != snapshot_hash:
                    continue
                if manifest.get("name") != name:
                    continue
                if manifest.get("kxy_skill_id") not in (None, "", skill_id):
                    continue
                try:
                    if "/".join(_skillhub_category(manifest.get("category", ""))) != "/".join(category):
                        continue
                except AgentConfigError:
                    continue
                candidates.append((central_id, manifest))
        if len(candidates) > 1:
            for candidate_id, _candidate_manifest in candidates:
                associated_central.add(candidate_id)
            items.append(_skillhub_scan_item(
                key=f"kxy:{skill_id}", status="conflict", name=name, skill_id=skill_id,
                upstream_id=upstream_id or None, snapshot_hash=snapshot_hash,
                reason="同一完整 hash 存在多个明确匹配的 central 副本",
                manifest_fingerprint=_stable_hash([
                    central[candidate_id].get("manifest_fingerprint") for candidate_id, _ in candidates
                ]),
            ))
            continue
        candidate_id = candidates[0][0] if candidates else ""
        candidate_manifest = candidates[0][1] if candidates else None
        if root_status != "ok":
            status, reason, actions = "conflict", "KXY 本地 Skill 快照缺失或内容已变化", ()
        elif not candidate_id:
            status, reason, actions = "missing", "本地 Skill 尚未找到通过新摘要规则的 central 副本", ()
        else:
            old_manifest = central.get(upstream_id, {}).get("manifest") if upstream_id else None
            merge_probe = dict(candidate_manifest or {})
            mapping_valid = upstream_id == candidate_id or _skillhub_mapped_store_matches(upstream_id, snapshot_hash)
            try:
                if not mapping_valid:
                    raise AgentConfigError("现有 SkillHub mapping 的旧 central 副本缺失或完整 hash 已变化，拒绝 repair")
                if upstream_id != candidate_id:
                    _skillhub_merge_legacy_manifest_fields(old_manifest, merge_probe)
            except AgentConfigError as exc:
                associated_central.add(candidate_id)
                status, reason, actions = "conflict", str(exc), ()
            else:
                associated_central.add(candidate_id)
                metadata_upstream = str((metadata.get("skillhub") or {}).get("upstream_skill_id") or "") if isinstance(metadata.get("skillhub"), dict) else ""
                if upstream_id == candidate_id and metadata_upstream in {"", candidate_id}:
                    status, reason, actions = "unchanged", "", ()
                else:
                    status, reason, actions = "repairable", "可按完整 hash 修复 central 映射", ("repair",)
        items.append(_skillhub_scan_item(
            key=f"kxy:{skill_id}", status=status, name=name, skill_id=skill_id,
            upstream_id=(candidate_id or upstream_id or None), snapshot_hash=snapshot_hash,
            reason=reason, actions=actions,
            manifest_fingerprint=(
                _skillhub_mapping_fingerprint(
                    candidate_manifest,
                    old_manifest=central.get(upstream_id, {}).get("manifest") if upstream_id else None,
                    ledger_entry=ledger_entry,
                )
                if candidate_id else None
            ),
        ))

    # A valid central row that explicitly names a live KXY record is already
    # associated, even when that record's local root is conflicted.  Do not
    # reclassify the same central row as a selectable new/add item.
    for central_id, record in central.items():
        manifest = record.get("manifest")
        mapped_id = str(manifest.get("kxy_skill_id") or "") if isinstance(manifest, dict) else ""
        if mapped_id and mapped_id in live_by_id:
            associated_central.add(central_id)

    for central_id in sorted(central):
        record = central[central_id]
        if central_id in associated_central:
            continue
        manifest = record.get("manifest") if isinstance(record.get("manifest"), dict) else {}
        manifest_kxy_id = str(manifest.get("kxy_skill_id") or "")
        tombstone = deleted.get(manifest_kxy_id) if manifest_kxy_id else None
        if record.get("status") != "valid":
            status = str(record.get("status") or "conflict")
            reason = str(record.get("reason") or "central index/store 状态异常")
            actions: tuple[str, ...] = ()
        elif manifest_kxy_id and manifest_kxy_id not in live_by_id:
            if isinstance(tombstone, dict) and tombstone.get("snapshot_hash") == record.get("snapshot_hash"):
                status, reason, actions = "deleted", "该 Skill 曾被删除，只能显式恢复", ("restore",)
            else:
                status, reason, actions = "stale", "central manifest 引用了不存在的 KXY Skill 记录", ()
        elif central_id not in associated_central:
            status, reason, actions = "new", "central 副本尚未建立 KXY Skill 记录", ("add",)
        else:
            continue
        ledger_entry = ledger_skills.get(manifest_kxy_id) if manifest_kxy_id else None
        old_upstream = str(ledger_entry.get("upstream_skill_id") or "") if isinstance(ledger_entry, dict) else ""
        mapping_fingerprint = (
            _skillhub_mapping_fingerprint(
                manifest,
                old_manifest=central.get(old_upstream, {}).get("manifest") if old_upstream else None,
                ledger_entry=ledger_entry,
                tombstone=tombstone,
            )
            if manifest_kxy_id else record.get("manifest_fingerprint")
        )
        items.append(_skillhub_scan_item(
            key=f"central:{central_id}", status=status,
            name=str(manifest.get("name") or central_id), skill_id=manifest_kxy_id or None,
            upstream_id=central_id, snapshot_hash=record.get("snapshot_hash"),
            reason=reason, actions=actions,
            manifest_fingerprint=mapping_fingerprint,
        ))

    items.sort(key=lambda item: str(item["key"]))
    counts: dict[str, int] = {}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    fingerprint = _stable_hash([
        {key: item.get(key) for key in ("key", "status", "name", "skill_id", "upstream_skill_id", "snapshot_hash", "manifest_fingerprint", "reason", "actions", "fingerprint")}
        for item in items
    ])
    return {"scan_fingerprint": fingerprint, "counts": counts, "items": items}


def _skillhub_restore_from_central(central_id: str, manifest: Mapping[str, Any], preferred_id: str | None = None) -> dict[str, Any]:
    core = _core()
    index = _skillhub_load_index()
    indexed_manifest = index.get(central_id)
    if not isinstance(indexed_manifest, dict):
        raise AgentConfigError("central manifest 已不存在")
    original_manifest = dict(indexed_manifest)
    store_path = _skillhub_home() / "store" / central_id
    if not store_path.is_dir() or store_path.is_symlink():
        raise AgentConfigError("central store 副本缺失或不是安全目录")
    if not _skillhub_manifest_summary_matches(manifest, store_path):
        raise AgentConfigError("central manifest 未通过当前摘要规则")
    snapshot_hash = _skillhub_store_snapshot(store_path)
    name, description, metadata = core.skill_metadata(store_path)
    if manifest.get("name") != name:
        raise AgentConfigError("central manifest name 与 SKILL.md 不一致")
    if preferred_id and (not re.fullmatch(r"[A-Za-z0-9._-]{1,160}", preferred_id) or preferred_id in {".", ".."}):
        raise AgentConfigError("restore 的 KXY Skill id 无效")
    skill_id = preferred_id or uuid.uuid4().hex
    destination = core.SKILLS_ROOT / skill_id
    with core.connect_db() as db:
        if db.execute("SELECT 1 FROM skills WHERE id=?", (skill_id,)).fetchone() is not None:
            raise AgentConfigError("restore 的 KXY Skill id 已被占用")
    if destination.exists() or destination.is_symlink():
        raise AgentConfigError("restore 目标快照路径已存在")
    stage = core.SKILLS_ROOT / f".restore-{uuid.uuid4().hex}"
    index_written = False
    try:
        shutil.copytree(store_path, stage, symlinks=False)
        if _skillhub_store_snapshot(stage) != snapshot_hash:
            raise AgentConfigError("restore 复制改变了完整快照")
        stage.rename(destination)
        metadata = dict(metadata)
        metadata.update({"source_agent": "local", "native_agent": "local", "native_category": manifest.get("category", ""), "skillhub_restore": central_id})
        restored_manifest = dict(indexed_manifest)
        restored_manifest.update({
            "id": central_id,
            "kxy_skill_id": skill_id,
            "kxy_snapshot_hash": snapshot_hash,
            "kxy_upstream_commit": SKILLHUB_UPSTREAM_COMMIT,
        })
        source_agents = [value for value in restored_manifest.get("kxy_source_agents", []) if isinstance(value, str)]
        if "local" not in source_agents:
            source_agents.append("local")
        restored_manifest["kxy_source_agents"] = source_agents
        index[central_id] = restored_manifest
        _skillhub_save_index(index)
        index_written = True
        with core.connect_db() as db:
            db.execute(
                "INSERT INTO skills(id, name, description, root_path, snapshot_hash, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (skill_id, name, description, str(destination), snapshot_hash, core.json_text(metadata), core.utc_now()),
            )
        entry = _skillhub_upsert_metadata(
            kxy_skill_id=skill_id,
            name=name,
            category=manifest.get("category", ""),
            snapshot_hash=snapshot_hash,
            upstream_id=central_id,
            upstream_name=name,
            source_agent="local",
            source_path=None,
        )
        skillhub_clear_skill_delete_marker(skill_id)
        return {"skill_id": skill_id, "upstream_skill_id": central_id, "entry": entry}
    except Exception:
        if index_written:
            try:
                index[central_id] = original_manifest
                _skillhub_save_index(index)
            except Exception:
                pass
        if destination.exists() and destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination, ignore_errors=True)
        if stage.exists() and stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage, ignore_errors=True)
        with core.connect_db() as db:
            db.execute("DELETE FROM skills WHERE id=?", (skill_id,))
        raise


def _skillhub_apply_scan_item(item: Mapping[str, Any], action: str) -> dict[str, Any]:
    key = str(item.get("key") or "")
    if action not in _SKILLHUB_SYNC_ACTIONS or key != str(item.get("key") or ""):
        raise AgentConfigError("SkillHub sync action 无效")
    index = _skillhub_load_index()
    central_id = str(item.get("upstream_skill_id") or "")
    manifest = index.get(central_id)
    if not central_id or not isinstance(manifest, dict):
        raise AgentConfigError("所选 central manifest 已不存在")
    store_path = _skillhub_home() / "store" / central_id
    if not store_path.is_dir() or store_path.is_symlink():
        raise AgentConfigError("所选 central store 已不存在或不安全")
    current_hash = _skillhub_store_snapshot(store_path)
    if current_hash != str(item.get("snapshot_hash") or "") or not _skillhub_manifest_summary_matches(manifest, store_path):
        raise AgentConfigError("所选 central 副本在扫描后发生变化，请重新扫描")
    if action in {"add", "restore"}:
        ledger = _skillhub_load_ledger()
        skill_id = str(item.get("skill_id") or "")
        ledger_entry = ledger.get("skills", {}).get(skill_id) if skill_id else None
        tombstone = ledger.get("deleted", {}).get(skill_id) if skill_id else None
        old_upstream = str(ledger_entry.get("upstream_skill_id") or "") if isinstance(ledger_entry, Mapping) else ""
        expected_fingerprint = (
            _skillhub_mapping_fingerprint(
                manifest,
                old_manifest=index.get(old_upstream) if old_upstream else None,
                ledger_entry=ledger_entry if isinstance(ledger_entry, Mapping) else None,
                tombstone=tombstone if isinstance(tombstone, Mapping) else None,
            )
            if action == "restore" else _skillhub_manifest_fingerprint(manifest)
        )
        if expected_fingerprint != item.get("manifest_fingerprint"):
            raise AgentConfigError("所选 central 关联信息在扫描后发生变化，请重新扫描")
        preferred_id = str(item.get("skill_id") or "") if action == "restore" else None
        restored = _skillhub_restore_from_central(central_id, manifest, preferred_id=preferred_id)
        return {"key": key, "action": action, "status": "updated", **{key: value for key, value in restored.items() if key != "entry"}}

    skill_id = str(item.get("skill_id") or "")
    if not skill_id:
        raise AgentConfigError("repair 缺少 KXY Skill id")
    core = _core()
    with core.connect_db() as db:
        row = db.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
    if row is None:
        raise AgentConfigError("repair 的 KXY Skill 已不存在")
    row_data = dict(row)
    if str(row_data.get("snapshot_hash") or "") != current_hash:
        raise AgentConfigError("repair 的 KXY Skill 完整 hash 已变化")
    metadata = _skill_row_metadata(row_data)
    old_entry = _skillhub_skillhub_entry(skill_id) or metadata.get("skillhub") or {}
    old_upstream = str(old_entry.get("upstream_skill_id") or "") if isinstance(old_entry, dict) else ""
    old_manifest = index.get(old_upstream) if old_upstream else None
    if old_upstream != central_id and not _skillhub_mapped_store_matches(old_upstream, current_hash):
        raise AgentConfigError("旧 central mapping 缺失或完整 hash 已变化，拒绝 repair")
    expected_fingerprint = _skillhub_mapping_fingerprint(
        manifest,
        old_manifest=old_manifest,
        ledger_entry=old_entry if isinstance(old_entry, Mapping) else None,
    )
    if expected_fingerprint != item.get("manifest_fingerprint"):
        raise AgentConfigError("SkillHub repair 关联信息在扫描后发生变化，请重新扫描")
    merged_manifest = dict(manifest)
    if old_upstream != central_id:
        _skillhub_merge_legacy_manifest_fields(old_manifest, merged_manifest)
    merged_manifest.update({"id": central_id, "kxy_skill_id": skill_id, "kxy_snapshot_hash": current_hash, "kxy_upstream_commit": SKILLHUB_UPSTREAM_COMMIT})
    index[central_id] = merged_manifest
    _skillhub_save_index(index)
    source_agent = _skill_source_agent(metadata, "codex")
    if source_agent not in SKILLHUB_SUPPORTED_AGENTS:
        source_agent = "local"
    entry = _skillhub_upsert_metadata(
        kxy_skill_id=skill_id,
        name=str(row_data.get("name") or manifest.get("name") or skill_id),
        category=manifest.get("category", ""),
        snapshot_hash=current_hash,
        upstream_id=central_id,
        upstream_name=str(manifest.get("name") or row_data.get("name") or skill_id),
        source_agent=source_agent,
        source_path=str(metadata.get("native_source") or "") or None,
        migration_from=old_upstream if old_upstream and old_upstream != central_id else None,
    )
    return {"key": key, "action": action, "status": "updated", "skill_id": skill_id, "upstream_skill_id": central_id, "entry": entry}


def sync_skillhub_index(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
        raise AgentConfigError("sync items 必须是数组")
    requested = payload["items"]
    if len(requested) > 100:
        raise AgentConfigError("一次最多同步 100 个索引项目")
    current = scan_skillhub_index()
    results: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw in requested:
        if not isinstance(raw, dict):
            results.append({"status": "failed", "reason": "同步项目必须是对象"})
            continue
        key = str(raw.get("key") or "")
        action = str(raw.get("action") or "")
        if key in seen_keys:
            results.append({"key": key, "status": "failed", "reason": "同一索引项目不能在一次同步中重复提交"})
            continue
        seen_keys.add(key)
        current = scan_skillhub_index()
        current_items = {str(item.get("key")): item for item in current.get("items", []) if isinstance(item, dict)}
        item = current_items.get(key)
        if item is None:
            results.append({"key": key, "status": "failed", "reason": "扫描项目已不存在，请重新扫描"})
            continue
        if action not in item.get("actions", []) or action not in _SKILLHUB_SYNC_ACTIONS:
            results.append({"key": key, "status": "failed", "reason": "该项目当前状态不允许此同步动作"})
            continue
        if str(raw.get("fingerprint") or "") != str(item.get("fingerprint") or ""):
            results.append({"key": key, "status": "failed", "reason": "扫描后项目已变化，请重新扫描"})
            continue
        try:
            result = _skillhub_apply_scan_item(item, action)
            results.append(result)
        except (AgentConfigError, OSError, ValueError) as exc:
            results.append({"key": key, "action": action, "status": "failed", "reason": _redact(str(exc), 512)})
    ok_count = sum(1 for result in results if result.get("status") == "updated")
    fail_count = len(results) - ok_count
    latest = scan_skillhub_index()
    return {
        "status": "ok" if fail_count == 0 else "partial" if ok_count else "blocked",
        "scan_fingerprint": latest.get("scan_fingerprint"),
        "results": results,
    }


def mount_skillhub(agent_id: str, skill_ids: Sequence[str]) -> dict[str, Any]:
    """Preview/perform selected SkillHub mappings without touching native roots."""

    ensure_agent_config_schema()
    target_agent = _valid_agent_id(agent_id)
    if not isinstance(skill_ids, Sequence) or isinstance(skill_ids, (str, bytes)):
        raise AgentConfigError("skill_ids 必须是数组")
    if len(skill_ids) > 50:
        raise AgentConfigError("一次最多挂载 50 个 Skill")
    results: list[dict[str, Any]] = []
    core = _core()
    for raw_id in skill_ids:
        skill_id = str(raw_id or "").strip()
        if not skill_id or len(skill_id) > 160 or not re.fullmatch(r"[A-Za-z0-9._-]+", skill_id):
            raise AgentConfigError("skill_id 无效")
        with core.connect_db() as db:
            row = db.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        if row is None:
            raise AgentConfigError(f"Skill 不存在，请重新导入：{skill_id}")
        metadata = _skill_row_metadata(dict(row))
        source_agent = _skill_source_agent(metadata, target_agent)
        if source_agent == "local":
            mapping = {
                "skill_id": skill_id,
                "source_agent": "local",
                "target_agent": target_agent,
                "cross_agent": False,
                "status": "same-agent",
                "message": "该快照没有来源 Agent，直接使用 KXY immutable copy",
            }
        else:
            try:
                mapping = _skillhub_project_snapshot(
                    Path(row["root_path"]),
                    kxy_skill_id=skill_id,
                    name=str(row["name"]),
                    category=metadata.get("native_category", ""),
                    snapshot_hash=str(row["snapshot_hash"]),
                    source_agent=source_agent,
                    target_agent=target_agent,
                    source_path=str(metadata.get("native_source") or ""),
                )
            except (AgentConfigError, OSError, ValueError) as exc:
                mapping = {
                    "skill_id": skill_id,
                    "source_agent": source_agent,
                    "target_agent": target_agent,
                    "cross_agent": source_agent != target_agent,
                    "status": "blocked",
                    "message": _redact(str(exc), 512),
                }
        metadata.setdefault("skillhub_mounts", {})[target_agent] = {
            key: mapping.get(key)
            for key in ("source_agent", "target_agent", "cross_agent", "status", "message", "upstream_skill_id", "snapshot_hash", "upstream_commit", "projection")
            if mapping.get(key) is not None
        }
        _save_skill_metadata(skill_id, metadata)
        results.append(
            {
                "skill_id": skill_id,
                "source_agent": mapping.get("source_agent", source_agent),
                "target_agent": target_agent,
                "cross_agent": bool(mapping.get("cross_agent", source_agent != target_agent)),
                "status": mapping.get("status", "blocked"),
                "message": str(mapping.get("message") or "")[:512],
            }
        )
    overall = "ready" if all(item["status"] in {"ready", "same-agent"} for item in results) else "blocked"
    return {"skills": results, "status": overall}


def skillhub_status() -> dict[str, Any]:
    """Report actual vendor/central availability and MCP target support."""

    vendor_ok, vendor_message = _skillhub_vendor_check()
    runtime_root = _skillhub_runtime_root() / f"status-{uuid.uuid4().hex}"
    probe_ok = False
    probe_message = vendor_message
    try:
        if vendor_ok:
            return_code, _stdout, stderr = _run_skillhub(["--help"], runtime_root)
            probe_ok = return_code == 0
            probe_message = None if probe_ok else (stderr or "SkillHub help probe failed")[:512]
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)
    central = _skillhub_home()
    index_valid = False
    skill_count = 0
    try:
        index = _skillhub_load_index()
        index_valid = True
        skill_count = len(index)
    except AgentConfigError as exc:
        probe_message = probe_message or str(exc)
    mcp_support = {agent: _mcp_support(agent) for agent in AGENT_PRESETS}
    support_public = {
        agent: {"supported": supported, "reason": reason}
        for agent, (supported, reason) in mcp_support.items()
    }
    return {
        "upstream": {
            "available": bool(vendor_ok and probe_ok),
            "commit": SKILLHUB_UPSTREAM_COMMIT,
            "version": "0.1.0" if vendor_ok else None,
            "message": probe_message,
        },
        "central_store": {
            "available": bool(vendor_ok and index_valid),
            "path": "skillhub",
            "index_valid": index_valid,
            "skill_count": skill_count,
        },
        "mcp_support": support_public,
        "agents": support_public,
    }


def _mcp_support(agent_id: str) -> tuple[bool, str]:
    agent_id = _valid_agent_id(agent_id)
    if agent_id in SKILLHUB_MCP_GENERATORS:
        return True, ""
    if agent_id == "pi":
        return False, "pi host-core servers format is not verified for this KXY release"
    if agent_id == "grok":
        return False, "Grok MCP target support is not verified"
    if agent_id == "hermes":
        return False, "Hermes MCP target support is not verified"
    return False, "DeepSeek headless MCP target support is not verified"


def _mcp_native_paths(agent_id: str) -> list[Path]:
    """Return only the documented native MCP locations for one agent."""

    home = _home()
    if agent_id == "codex":
        return [home / ".codex" / "config.toml"]
    if agent_id == "claude":
        return [home / ".claude.json"]
    if agent_id == "opencode":
        jsonc = home / ".config" / "opencode" / "opencode.jsonc"
        return [jsonc if jsonc.exists() else home / ".config" / "opencode" / "opencode.json"]
    if agent_id == "workbuddy":
        return [home / ".workbuddy" / "mcp.json"]
    if agent_id == "pi":
        root = home / ".agents" / "servers"
        if not root.is_dir() or root.is_symlink():
            return []
        return sorted(root.glob("*.json"))[:MCP_MAX_SERVERS]
    return []


def _mcp_strip_jsonc(text: str) -> str:
    """Remove JSONC comments and trailing commas without touching strings."""

    output: list[str] = []
    index = 0
    quote = False
    escaped = False
    line_comment = False
    block_comment = False
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
                output.append(char)
            else:
                output.append(" ")
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                output.extend((" ", " "))
                index += 2
            else:
                output.append("\n" if char in "\r\n" else " ")
                index += 1
            continue
        if quote:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == '"':
            quote = True
            output.append(char)
            index += 1
        elif char == "/" and next_char == "/":
            line_comment = True
            output.extend((" ", " "))
            index += 2
        elif char == "/" and next_char == "*":
            block_comment = True
            output.extend((" ", " "))
            index += 2
        else:
            output.append(char)
            index += 1
    if quote or block_comment:
        raise AgentConfigError("MCP JSONC 配置未闭合")

    # Remove commas immediately before a closing token, again only outside
    # strings.  Native JSONC files commonly use this legal extension.
    text = "".join(output)
    output = []
    quote = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
            index += 1
            continue
        if char == '"':
            quote = True
            output.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _mcp_read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        if path.stat().st_size > MCP_MAX_CONFIG_BYTES:
            raise AgentConfigError("MCP native 配置超过大小上限")
        value = json.loads(_mcp_strip_jsonc(path.read_text(encoding="utf-8")))
    except AgentConfigError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise AgentConfigError("MCP native 配置无法安全解析") from exc
    if not isinstance(value, dict):
        raise AgentConfigError("MCP native 配置必须是 JSON 对象")
    return value


def _mcp_read_toml(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        if path.stat().st_size > MCP_MAX_CONFIG_BYTES:
            raise AgentConfigError("MCP Codex 配置超过大小上限")
        import tomllib

        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except AgentConfigError:
        raise
    except (ImportError, OSError, UnicodeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise AgentConfigError("MCP Codex 配置无法安全解析") from exc
    if not isinstance(value, dict):
        raise AgentConfigError("MCP Codex 配置必须是 TOML 对象")
    return value


def _mcp_native_definitions(agent_id: str) -> list[tuple[str, dict[str, Any]]]:
    """Read configured server blocks, never credentials or unrelated settings."""

    agent_id = _valid_agent_id(agent_id)
    paths = _mcp_native_paths(agent_id)
    if agent_id == "codex":
        document = _mcp_read_toml(paths[0]) if paths else {}
        servers = document.get("mcp_servers", {})
        if not isinstance(servers, dict):
            raise AgentConfigError("Codex MCP 配置的 mcp_servers 必须是表")
        result: list[tuple[str, dict[str, Any]]] = []
        for sid, raw in servers.items():
            if isinstance(raw, list):
                for item in raw:
                    if not isinstance(item, dict):
                        raise AgentConfigError("Codex MCP server 条目格式无效")
                    result.append((str(sid), dict(item)))
            elif isinstance(raw, dict):
                result.append((str(sid), dict(raw)))
            else:
                raise AgentConfigError("Codex MCP server 条目格式无效")
        return result[:MCP_MAX_SERVERS]

    result = []
    for path in paths:
        document = _mcp_read_json(path)
        if agent_id == "opencode":
            servers = document.get("mcp", {})
        else:
            servers = document.get("mcpServers", {})
        if agent_id == "pi" and not servers:
            sid = document.get("id") or path.stem
            if isinstance(sid, str):
                result.append((sid, document))
            continue
        if not isinstance(servers, dict):
            raise AgentConfigError("MCP native server 容器必须是对象")
        for sid, raw in servers.items():
            if not isinstance(raw, dict):
                raise AgentConfigError("MCP native server 条目格式无效")
            result.append((str(sid), dict(raw)))
    return result[:MCP_MAX_SERVERS]


def _mcp_env_refs(value: Any) -> list[str]:
    if not isinstance(value, str):
        return []
    result: list[str] = []
    for match in _MCP_ENV_ANY_RE.finditer(value):
        name = next((group for group in match.groups() if group), None)
        if name and name not in result:
            result.append(name)
    return result


def _mcp_all_env_refs(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(_mcp_env_refs(value))
    if isinstance(value, dict):
        result: set[str] = set()
        for item in value.values():
            result.update(_mcp_all_env_refs(item))
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result.update(_mcp_all_env_refs(item))
        return result
    return set()


def _mcp_normalize_refs(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = next((group for group in match.groups() if group), "")
        return "{{env:%s}}" % name

    return _MCP_ENV_ANY_RE.sub(replace, value)


def _mcp_is_secret_literal(key: str, value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if _mcp_env_refs(value):
        return False
    if _MCP_SECRET_KEY_RE.search(key):
        return True
    return bool(
        re.search(r"(?i)^Bearer\s+\S+", value)
        or re.search(r"(?i)^sk-[A-Za-z0-9]{8,}", value)
        or re.search(r"^(?:gh[pousr]_|xox[baprs]-|AKIA[0-9A-Z]{16})", value)
    )


def _mcp_secret_env_name(server_id: str, key: str, source_agent: str = "") -> str:
    identity = f"{source_agent}_{server_id}" if source_agent else server_id
    base = re.sub(r"[^A-Za-z0-9]+", "_", f"{identity}_{key}").strip("_").upper()
    return f"KXY_MCP_{base[:80]}_SECRET"


def _mcp_safe_string(value: Any, field: str, *, limit: int = 4096) -> str:
    if not isinstance(value, str):
        raise AgentConfigError(f"MCP {field} 必须是文本")
    if not value or len(value) > limit or any(char in value for char in "\x00\r\n"):
        raise AgentConfigError(f"MCP {field} 含有非法字符或超过长度上限")
    normalized = _mcp_normalize_refs(value)
    if "${" in normalized or "{env:" in normalized and "{{env:" not in normalized:
        raise AgentConfigError(f"MCP {field} 的环境变量引用格式不受支持")
    return normalized


def _mcp_env_template_map(value: Any, field: str) -> dict[str, str]:
    """Keep only non-secret composite env expressions for replay validation."""

    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or len(value) > 200:
        raise AgentConfigError(f"MCP {field} 必须是有限对象")
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _mcp_safe_string(str(raw_key), f"{field} key", limit=128)
        if not _MCP_KEY_RE.fullmatch(key):
            raise AgentConfigError(f"MCP {field} key 不安全")
        text = _mcp_safe_string(str(raw_value), f"{field}.{key}", limit=8192)
        if _mcp_env_refs(text) and _MCP_ENV_REF_RE.fullmatch(text) is None:
            result[key] = text
    return result


def _mcp_stored_env_templates(value: Any) -> dict[str, dict[str, str]]:
    """Validate the persisted, secret-free composite env metadata."""

    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or set(value) - {"headers", "env"}:
        raise AgentConfigError("MCP env_templates 格式无效")
    result: dict[str, dict[str, str]] = {}
    for container, raw_map in value.items():
        if not isinstance(raw_map, dict):
            raise AgentConfigError("MCP env_templates 条目必须是对象")
        cleaned = _mcp_env_template_map(raw_map, f"env_templates.{container}")
        if cleaned != raw_map:
            raise AgentConfigError("MCP env_templates 必须保留规范化后的 composite 表达式")
        if cleaned:
            result[container] = cleaned
    return result


def _mcp_clean_map(value: Any, server_id: str, field: str, source_agent: str = "") -> dict[str, str]:
    if value in (None, {}):
        return {}
    if not isinstance(value, dict) or len(value) > 200:
        raise AgentConfigError(f"MCP {field} 必须是有限对象")
    result: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _mcp_safe_string(str(raw_key), f"{field} key", limit=128)
        if not _MCP_KEY_RE.fullmatch(key):
            raise AgentConfigError(f"MCP {field} key 不安全")
        string_value = _mcp_safe_string(str(raw_value), f"{field}.{key}", limit=8192)
        # Codex's env_http_headers and env_vars can reference one variable,
        # but cannot expand a composite such as "Bearer ${TOKEN}".  Store a
        # generated reference for both secret literals and composite refs; the
        # complete value is assembled only in the child-process environment.
        if _mcp_is_secret_literal(key, string_value) or (
            _mcp_env_refs(string_value) and _MCP_ENV_REF_RE.fullmatch(string_value) is None
        ):
            string_value = "{{env:%s}}" % _mcp_secret_env_name(server_id, key, source_agent)
        result[key] = string_value
    return result


def _mcp_safe_url(value: Any) -> str:
    from urllib.parse import urlsplit

    url = _mcp_safe_string(value, "url", limit=4096)
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise AgentConfigError("MCP URL 必须不含凭据、查询参数或片段")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise AgentConfigError("MCP 远程 URL 需要 HTTPS，本机服务可用 HTTP")
    return url.rstrip("/")


def _mcp_command(value: Any, args: Any, server_id: str) -> tuple[str, list[str], dict[str, str]]:
    if isinstance(value, list):
        tokens = value
    elif isinstance(value, str):
        # A string command is an executable path, not a shell command.  In
        # particular, retain spaces in paths instead of shlex-splitting them.
        tokens = [value]
    else:
        raise AgentConfigError("MCP stdio server 缺少 command")
    if not tokens or len(tokens) > 64 or any(not isinstance(item, str) for item in tokens):
        raise AgentConfigError("MCP stdio command 参数无效")
    command = _mcp_safe_string(tokens[0], "command", limit=2048)
    command_args = [_mcp_safe_string(item, "args", limit=4096) for item in tokens[1:]]
    if args not in (None, []):
        if not isinstance(args, list) or len(args) > 63:
            raise AgentConfigError("MCP args 必须是有限数组")
        command_args.extend(_mcp_safe_string(item, "args", limit=4096) for item in args)
    sensitive_flag = False
    for item in command_args:
        if sensitive_flag:
            if not _mcp_env_refs(item):
                raise AgentConfigError("MCP command args 含有未受保护的 secret 参数")
            sensitive_flag = False
            continue
        if _MCP_SENSITIVE_ARG_VALUE_RE.match(item) and not _mcp_env_refs(item):
            raise AgentConfigError("MCP command args 含有未受保护的 secret 参数")
        if _MCP_SENSITIVE_ARG_RE.fullmatch(item):
            sensitive_flag = True
    return command, command_args, _mcp_clean_map({}, server_id, "env")


def _mcp_parse_definition(source_agent: str, server_id: str, config: Mapping[str, Any]) -> tuple[dict[str, Any], str | None]:
    source_agent = _valid_agent_id(source_agent)
    sid = _mcp_safe_string(server_id, "server id", limit=128)
    if not _MCP_ID_RE.fullmatch(sid):
        raise AgentConfigError("MCP server id 不安全")
    if not isinstance(config, Mapping):
        raise AgentConfigError("MCP server 配置必须是对象")
    base = dict(config)
    transport_value = base.get("transport")
    if isinstance(transport_value, Mapping):
        merged = dict(transport_value)
        merged.update({key: value for key, value in base.items() if key != "transport"})
        base = merged
    kind = str(base.get("type") or base.get("transport") or "").strip().lower()
    aliases = {"remote": "http", "streamable-http": "http", "local": "stdio"}
    kind = aliases.get(kind, kind)
    if not kind:
        kind = "http" if base.get("url") else "stdio" if base.get("command") else ""
    label = _mcp_safe_string(base.get("name") or base.get("label") or sid, "name", limit=240)
    definition: dict[str, Any] = {
        "id": sid,
        "label": label,
        "transport": kind or "unknown",
        "enabled": bool(base.get("enabled", True)),
        "agents": [source_agent],
        "source": source_agent,
    }
    compatibility_reason: str | None = None
    stored_templates = _mcp_stored_env_templates(base.get("env_templates"))
    computed_templates: dict[str, dict[str, str]] = {}
    if kind not in {"http", "stdio"}:
        return definition, f"transport {kind or 'unknown'} 未被 KXY 目标适配器支持"
    if kind == "http":
        definition["url"] = _mcp_safe_url(base.get("url"))
        raw_headers: dict[str, Any] = {}
        for field in ("headers", "http_headers"):
            value = base.get(field)
            if value is not None:
                if not isinstance(value, dict):
                    raise AgentConfigError(f"MCP {field} 必须是有限对象")
                raw_headers.update(value)
        env_http_headers = base.get("env_http_headers")
        if env_http_headers is not None:
            if not isinstance(env_http_headers, dict):
                raise AgentConfigError("MCP env_http_headers 必须是对象")
            for raw_key, raw_name in env_http_headers.items():
                header = _mcp_safe_string(str(raw_key), "env_http_headers key", limit=128)
                env_name = _mcp_safe_string(raw_name, f"env_http_headers.{header}", limit=256)
                if not _MCP_ENV_NAME_RE.fullmatch(env_name):
                    raise AgentConfigError("MCP env_http_headers 的环境变量名无效")
                if header in raw_headers and raw_headers[header] not in (None, ""):
                    raise AgentConfigError(f"MCP HTTP header {header} 同时存在静态和环境引用")
                raw_headers[header] = "{{env:%s}}" % env_name
        bearer_name = base.get("bearer_token_env_var")
        if bearer_name not in (None, ""):
            bearer_name = _mcp_safe_string(bearer_name, "bearer_token_env_var", limit=256)
            if not _MCP_ENV_NAME_RE.fullmatch(bearer_name):
                raise AgentConfigError("MCP bearer_token_env_var 的环境变量名无效")
            if "Authorization" in raw_headers:
                raise AgentConfigError("MCP Authorization 同时存在 bearer 和 header 定义")
            raw_headers["Authorization"] = "{{env:%s}}" % bearer_name
        if base.get("auth") not in (None, "") or base.get("oauth") not in (None, ""):
            compatibility_reason = "Codex OAuth/auth 状态依赖 native 会话，拒绝迁移"
        if base.get("http_headers_helper") not in (None, ""):
            compatibility_reason = "MCP HTTP header helper 未被 KXY 迁移"
        definition["headers"] = _mcp_clean_map(raw_headers, sid, "headers", source_agent)
        composite = _mcp_env_template_map(raw_headers, "headers")
        if composite:
            computed_templates["headers"] = composite
    else:
        raw_command = base.get("command")
        if isinstance(raw_command, list):
            command_tokens = raw_command
            explicit_args = base.get("args") or []
        else:
            command_tokens = raw_command
            explicit_args = base.get("args") or []
        command, command_args, _ = _mcp_command(command_tokens, explicit_args, sid)
        definition["command"] = command
        definition["args"] = command_args
        raw_env = base.get("env", base.get("environment"))
        if raw_env is None:
            raw_env = {}
        if not isinstance(raw_env, dict):
            raise AgentConfigError("MCP env 必须是对象")
        raw_env = dict(raw_env)
        env_vars = base.get("env_vars")
        if env_vars is not None:
            if not isinstance(env_vars, list) or len(env_vars) > 200:
                raise AgentConfigError("MCP env_vars 必须是有限数组")
            for item in env_vars:
                if isinstance(item, str):
                    env_name = _mcp_safe_string(item, "env_vars", limit=128)
                    source = "local"
                elif isinstance(item, dict):
                    env_name = _mcp_safe_string(item.get("name"), "env_vars.name", limit=128)
                    source = str(item.get("source") or "local").lower()
                else:
                    raise AgentConfigError("MCP env_vars 条目格式无效")
                if not _MCP_ENV_NAME_RE.fullmatch(env_name):
                    raise AgentConfigError("MCP env_vars 的环境变量名无效")
                if source != "local":
                    compatibility_reason = "MCP remote stdio env_vars 未被 KXY 迁移"
                if env_name in raw_env and raw_env[env_name] not in (None, ""):
                    raise AgentConfigError(f"MCP stdio env {env_name} 同时存在 env 和 env_vars 定义")
                raw_env[env_name] = "{{env:%s}}" % env_name
        definition["env"] = _mcp_clean_map(raw_env, sid, "env", source_agent)
        composite = _mcp_env_template_map(raw_env, "env")
        if composite:
            computed_templates["env"] = composite
    if stored_templates and computed_templates and stored_templates != computed_templates:
        raise AgentConfigError("MCP env_templates 与定义不一致")
    if stored_templates or computed_templates:
        definition["env_templates"] = stored_templates or computed_templates
    return definition, compatibility_reason


def _mcp_public(definition: Mapping[str, Any], target_agent: str | None = None) -> dict[str, Any]:
    source = str(definition.get("source") or (definition.get("agents") or [""])[0]).lower()
    target = target_agent or source
    try:
        supported, reason = _mcp_support(target)
    except AgentConfigError:
        supported, reason = False, "目标 Agent 未知"
    transport = str(definition.get("transport") or "unknown")
    if transport not in {"http", "stdio"}:
        supported = False
        reason = definition.get("reason") or f"transport {transport} 未被支持"
    elif definition.get("reason"):
        supported = False
        reason = str(definition["reason"])
    return {
        "id": str(definition.get("id") or ""),
        "name": str(definition.get("label") or definition.get("name") or definition.get("id") or ""),
        "transport": transport,
        "source_agent": source,
        "supported": bool(supported),
        "reason": str(reason) if reason else "",
    }


def discover_mcps(agent_id: str) -> list[dict[str, Any]]:
    agent_id = _valid_agent_id(agent_id)
    target_supported, target_reason = _mcp_support(agent_id)
    seen: dict[str, dict[str, Any]] = {}
    for sid, raw in _mcp_native_definitions(agent_id):
        try:
            definition, reason = _mcp_parse_definition(agent_id, sid, raw)
            definition["reason"] = reason or ""
            record = _mcp_public(definition, agent_id)
            if not target_supported:
                record["supported"] = False
                record["reason"] = target_reason
        except AgentConfigError as exc:
            safe_id = str(sid).strip()
            if not _MCP_ID_RE.fullmatch(safe_id):
                continue
            record = {
                "id": safe_id,
                "name": safe_id,
                "transport": "unknown",
                "source_agent": agent_id,
                "supported": False,
                "reason": _redact(str(exc), 240),
            }
        if record["id"] in seen:
            record["supported"] = False
            record["reason"] = "同一 native 配置中出现重复 server id，拒绝猜测"
        seen[record["id"]] = record
    return [seen[key] for key in sorted(seen)]


def _mcp_index_path() -> Path:
    return _skillhub_home() / "mcp" / "index.json"


def _mcp_contains_secret_literal(value: Any, key: str = "") -> bool:
    if isinstance(value, dict):
        return any(_mcp_contains_secret_literal(item, str(item_key)) for item_key, item in value.items())
    if isinstance(value, list):
        return any(_mcp_contains_secret_literal(item, key) for item in value)
    return _mcp_is_secret_literal(key, value)


def _mcp_definition_digest(definition: Mapping[str, Any]) -> str:
    stable = {
        key: definition.get(key)
        for key in ("id", "label", "transport", "enabled", "url", "headers", "command", "args", "env", "env_templates")
        if key in definition
    }
    return hashlib.sha256(_json_text(stable).encode("utf-8")).hexdigest()


def _mcp_load_index() -> dict[str, dict[str, Any]]:
    path = _mcp_index_path()
    if not path.exists():
        return {}
    try:
        if path.stat().st_size > MCP_MAX_CONFIG_BYTES:
            raise AgentConfigError("KXY MCP index 超过大小上限")
        value = json.loads(path.read_text(encoding="utf-8"))
    except AgentConfigError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise AgentConfigError("KXY MCP index 已损坏，拒绝继续使用") from exc
    if not isinstance(value, dict):
        raise AgentConfigError("KXY MCP index 必须是对象")
    result: dict[str, dict[str, Any]] = {}
    for sid, raw in value.items():
        if not isinstance(sid, str) or not _MCP_ID_RE.fullmatch(sid) or not isinstance(raw, dict):
            raise AgentConfigError("KXY MCP index 含有不安全条目")
        if raw.get("id") not in (None, sid) or _mcp_contains_secret_literal(raw):
            raise AgentConfigError("KXY MCP index 含有冲突或明文 secret")
        source = str(raw.get("source") or ((raw.get("agents") or [""])[0] if isinstance(raw.get("agents"), list) else "")).lower()
        if source not in AGENT_PRESETS:
            raise AgentConfigError("KXY MCP index 缺少可验证来源 Agent")
        definition, reason = _mcp_parse_definition(source, sid, raw)
        definition["reason"] = reason or ""
        definition["source_agents"] = [
            str(item).lower()
            for item in raw.get("source_agents", raw.get("agents", [source]))
            if isinstance(item, str) and item.lower() in AGENT_PRESETS
        ] or [source]
        if isinstance(raw.get("imported_at"), str):
            definition["imported_at"] = raw["imported_at"]
        result[sid] = definition
    return result


def _mcp_save_index(index: Mapping[str, Any]) -> None:
    path = _mcp_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(dict(index), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(path)


def _mcp_import_definition(definition: Mapping[str, Any], source_agent: str) -> dict[str, Any]:
    source_agent = _valid_agent_id(source_agent)
    index = _mcp_load_index()
    sid = str(definition["id"])
    existing = index.get(sid)
    if existing is not None and _mcp_definition_digest(existing) != _mcp_definition_digest(definition):
        raise AgentConfigError("同一 MCP id 已存在不同定义，拒绝覆盖")
    runtime_root = _skillhub_runtime_root() / f"mcp-import-{uuid.uuid4().hex}"
    source_path = runtime_root / "servers.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {sid: dict(definition)}
    source_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    try:
        script = (
            "import json,sys\n"
            "from skillhub.mcp import _import_from_source\n"
            "with open(sys.argv[2], encoding='utf-8') as handle: servers=json.load(handle)\n"
            "n,_,_,_= _import_from_source(sys.argv[1], sys.argv[2], servers, True)\n"
            "print(json.dumps({'imported': n}))\n"
        )
        return_code, _stdout, stderr = _run_skillhub_python(
            script,
            [source_agent, str(source_path)],
            runtime_root,
        )
        if return_code != 0:
            raise AgentConfigError(f"SkillHub MCP central import failed: {stderr or 'unknown error'}")
        refreshed = _mcp_load_index()
        stored = refreshed.get(sid)
        if stored is not None and definition.get("env_templates"):
            # The pinned upstream MCP index has no field for KXY's
            # secret-free composite replay metadata.  Restore that metadata
            # only after the actual upstream import, then verify the complete
            # normalized definition before saving the central projection.
            stored["env_templates"] = definition["env_templates"]
        if stored is None or _mcp_definition_digest(stored) != _mcp_definition_digest(definition):
            raise AgentConfigError("SkillHub MCP central import 后定义校验失败")
        sources = [
            str(item).lower()
            for item in (stored.get("source_agents") or stored.get("agents") or [])
            if isinstance(item, str) and item.lower() in AGENT_PRESETS
        ]
        if source_agent not in sources:
            sources.append(source_agent)
        stored["source_agents"] = list(dict.fromkeys(sources))
        stored["agents"] = list(dict.fromkeys([*sources]))
        stored["source"] = sources[0] if sources else source_agent
        stored["kxy_upstream_commit"] = SKILLHUB_UPSTREAM_COMMIT
        refreshed[sid] = stored
        _mcp_save_index(refreshed)
        return stored
    finally:
        shutil.rmtree(runtime_root, ignore_errors=True)


def import_mcps(agent_id: str, ids: Sequence[str]) -> dict[str, Any]:
    agent_id = _valid_agent_id(agent_id)
    if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)):
        raise AgentConfigError("ids 必须是数组")
    if len(ids) > MCP_MAX_SERVERS:
        raise AgentConfigError("一次最多导入 100 个 MCP server")
    candidates = {item["id"]: item for item in discover_mcps(agent_id)}
    imported: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw_id in ids:
        sid = str(raw_id or "").strip()
        if not _MCP_ID_RE.fullmatch(sid):
            errors.append("MCP id 无效")
            continue
        candidate = candidates.get(sid)
        if candidate is None:
            errors.append(f"MCP server 不存在或未在 native 配置中发现：{sid}")
            continue
        if not candidate.get("supported"):
            errors.append(f"MCP server {sid} 不支持：{candidate.get('reason') or '目标 Agent 不支持'}")
            continue
        try:
            raw = next(raw for raw_sid, raw in _mcp_native_definitions(agent_id) if raw_sid == sid)
            definition, reason = _mcp_parse_definition(agent_id, sid, raw)
            if reason:
                raise AgentConfigError(reason)
            stored = _mcp_import_definition(definition, agent_id)
            imported.append(_mcp_public(stored, agent_id))
        except AgentConfigError as exc:
            errors.append(f"{sid}: {_redact(str(exc), 400)}")
    return {"imported": imported, "errors": errors}


def _mcp_frozen_definitions(
    agent_id: str,
    ids: Sequence[str],
    snapshot: Mapping[str, Any] | None,
) -> list[Mapping[str, Any]]:
    """Resolve selected definitions from a run snapshot, never a live index."""

    if snapshot is not None:
        records = snapshot.get("servers", snapshot.get("mcps", snapshot)) if isinstance(snapshot, Mapping) else snapshot
        if not isinstance(records, list):
            raise AgentConfigError("运行快照中的 MCP 定义格式无效")
        frozen = {str(item.get("id")): item for item in records if isinstance(item, Mapping) and item.get("id")}
        result: list[Mapping[str, Any]] = []
        for sid in ids:
            item = frozen.get(str(sid))
            if item is None or not isinstance(item.get("definition"), Mapping):
                raise AgentConfigError(f"运行快照中缺少 MCP server：{sid}")
            source = str(item.get("source_agent") or agent_id)
            definition, reason = _mcp_parse_definition(source, str(sid), item["definition"])
            if reason:
                definition["reason"] = reason
            if item.get("definition_sha256") and item["definition_sha256"] != _mcp_definition_digest(definition):
                raise AgentConfigError(f"运行快照中的 MCP server 已损坏：{sid}")
            definition["source_agents"] = [
                str(value).lower()
                for value in item.get("source_agents", [source])
                if isinstance(value, str) and value.lower() in AGENT_PRESETS
            ] or [source]
            result.append(definition)
        return result
    index = _mcp_load_index()
    result = []
    for sid in ids:
        definition = index.get(str(sid))
        if definition is None:
            raise AgentConfigError(f"MCP server 尚未导入中央库：{sid}")
        result.append(definition)
    return result


def _mcp_runtime_value(
    server_id: str,
    key: str,
    raw_value: Any,
    source_agent: str,
    required_refs: set[str],
) -> tuple[str, str | None]:
    """Resolve one native value without persisting its literal contents."""

    text = _mcp_safe_string(str(raw_value), f"runtime {key}", limit=8192)
    normalized = _mcp_normalize_refs(text)
    refs = _mcp_env_refs(normalized)
    exact = _MCP_ENV_REF_RE.fullmatch(normalized)
    generated_name = _mcp_secret_env_name(server_id, key, source_agent)
    if exact is not None:
        canonical = "{{env:%s}}" % exact.group(1)
    elif refs or _mcp_is_secret_literal(key, normalized):
        canonical = "{{env:%s}}" % generated_name
    else:
        return normalized, None
    if canonical not in {"{{env:%s}}" % name for name in required_refs}:
        return canonical, None
    if refs:
        resolved: dict[str, str] = {}
        for ref in refs:
            if ref not in required_refs:
                raise AgentConfigError(f"MCP runtime env 引用未被选中：{ref}")
            value = os.environ.get(ref)
            if not value:
                raise AgentConfigError(f"MCP runtime env 引用不可用：{ref}")
            resolved[ref] = value
        if exact is not None:
            return canonical, resolved[exact.group(1)]

        def replace(match: re.Match[str]) -> str:
            name = next((group for group in match.groups() if group), "")
            return resolved[name]

        return canonical, _MCP_ENV_ANY_RE.sub(replace, normalized)
    return canonical, normalized


def _mcp_required_runtime_env(definition: Mapping[str, Any], agent_id: str) -> set[str]:
    required = _mcp_all_env_refs(definition)
    if agent_id == "codex" and definition.get("transport") == "stdio":
        raw_env = definition.get("env")
        if isinstance(raw_env, dict):
            required.update(
                str(key)
                for key, value in raw_env.items()
                if _mcp_env_refs(value)
            )
    return required


def mcp_runtime_environment(
    agent_id: str,
    mcp_ids: Sequence[str],
    *,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Resolve selected native references only in memory for one child process."""

    agent_id = _valid_agent_id(agent_id)
    definitions = _mcp_frozen_definitions(agent_id, mcp_ids, snapshot)
    result: dict[str, str] = {}
    for definition in definitions:
        sid = str(definition.get("id") or "")
        required_refs = _mcp_all_env_refs(definition)
        references = [
            str(value).lower()
            for value in (definition.get("source_agents") or definition.get("agents") or [definition.get("source")])
            if isinstance(value, str) and value.lower() in AGENT_PRESETS
        ]
        references.extend(
            value
            for value in (str(definition.get("source") or "").lower(), agent_id)
            if value in AGENT_PRESETS
        )
        source_records: dict[tuple[str, str], dict[str, Any]] = {}
        for source in dict.fromkeys(references):
            try:
                matches = [(raw_sid, raw) for raw_sid, raw in _mcp_native_definitions(source) if raw_sid == sid]
                if len(matches) > 1:
                    raise AgentConfigError(f"MCP native source {source} 中出现重复 server id：{sid}")
                for raw_sid, raw in matches:
                    cleaned, reason = _mcp_parse_definition(source, raw_sid, raw)
                    if reason or _mcp_definition_digest(cleaned) != _mcp_definition_digest(definition):
                        raise AgentConfigError(f"MCP native source {source} 已改变，拒绝把新凭据用于冻结定义：{sid}")
                    if raw_sid == sid:
                        source_records[(source, sid)] = raw
            except AgentConfigError:
                if source == str(definition.get("source") or "").lower():
                    raise
                continue
        value_maps: list[tuple[str, Any, str]] = []
        for (source, _), raw in source_records.items():
            base = dict(raw)
            transport = base.get("transport")
            if isinstance(transport, Mapping):
                merged = dict(transport)
                merged.update({key: value for key, value in base.items() if key != "transport"})
                base = merged
            normalized, _reason = _mcp_parse_definition(source, sid, raw)
            for container in ("headers", "env"):
                expected = normalized.get(container)
                if not isinstance(expected, dict):
                    continue
                native_values: dict[str, Any] = {}
                if container == "headers":
                    for field in ("headers", "http_headers"):
                        value = base.get(field)
                        if isinstance(value, dict):
                            native_values.update(value)
                    env_headers = base.get("env_http_headers")
                    if isinstance(env_headers, dict):
                        native_values.update(
                            {
                                str(name): "{{env:%s}}" % str(env_name)
                                for name, env_name in env_headers.items()
                            }
                        )
                    bearer_name = base.get("bearer_token_env_var")
                    if bearer_name not in (None, ""):
                        native_values.setdefault("Authorization", "{{env:%s}}" % str(bearer_name))
                else:
                    for field in ("env", "environment"):
                        value = base.get(field)
                        if isinstance(value, dict):
                            native_values.update(value)
                    env_vars = base.get("env_vars")
                    if isinstance(env_vars, list):
                        for item in env_vars:
                            if isinstance(item, str):
                                native_values.setdefault(item, "{{env:%s}}" % item)
                            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                                name = item["name"]
                                native_values.setdefault(name, "{{env:%s}}" % name)
                for name, canonical_value in expected.items():
                    value = native_values.get(name, canonical_value)
                    value_maps.append((str(name), value, source))
        for key, value, source in value_maps:
            canonical, runtime_value = _mcp_runtime_value(sid, key, value, source, required_refs)
            if runtime_value is None:
                continue
            canonical_name = next(iter(_mcp_env_refs(canonical)), None)
            if canonical_name is None or canonical_name not in required_refs:
                continue
            previous = result.get(canonical_name)
            if previous is not None and previous != runtime_value:
                raise AgentConfigError(f"MCP server {sid} 的运行时 env 引用发生冲突")
            result[canonical_name] = runtime_value
            if agent_id == "codex" and definition.get("transport") == "stdio" and source:
                previous = result.get(key)
                if previous is not None and previous != runtime_value:
                    raise AgentConfigError(f"MCP server {sid} 的 stdio env 名称发生冲突：{key}")
                result[key] = runtime_value

        # A direct {{env:VAR}} reference remains usable when its native source
        # file is absent; generated KXY references never do, because they are
        # resolved from the selected native definition above.
        for container in ("headers", "env"):
            raw_map = definition.get(container)
            if not isinstance(raw_map, dict):
                continue
            for key, value in raw_map.items():
                match = _MCP_ENV_REF_RE.fullmatch(str(value))
                if (
                    match is None
                    or match.group(1) not in required_refs
                    or match.group(1).startswith("KXY_MCP_")
                ):
                    continue
                candidate = os.environ.get(match.group(1))
                if candidate:
                    result.setdefault(match.group(1), candidate)
                    if agent_id == "codex" and definition.get("transport") == "stdio" and container == "env":
                        result.setdefault(str(key), candidate)
        generated_required = {
            ref
            for ref in required_refs
            if ref.startswith("KXY_MCP_")
        }
        missing_generated = sorted(generated_required - set(result))
        if missing_generated:
            raise AgentConfigError(
                f"MCP server {sid} 的 native secret/reference 不可用：{', '.join(missing_generated)}"
            )
    return result


def list_imported_mcps() -> list[dict[str, Any]]:
    index = _mcp_load_index()
    return [_mcp_public(index[sid]) for sid in sorted(index)]


def _mcp_render_upstream(definition: Mapping[str, Any], agent_id: str, runtime_root: Path) -> Any:
    source_path = Path(runtime_root) / "definition.json"
    output_path = Path(runtime_root) / "rendered.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(json.dumps(dict(definition), ensure_ascii=False), encoding="utf-8")
    script = (
        "import json,sys\n"
        "from skillhub import mcp\n"
        "with open(sys.argv[1], encoding='utf-8') as handle: d=json.load(handle)\n"
        "agent=sys.argv[2]\n"
        "if agent == 'codex': value=mcp._render_toml(d)\n"
        "elif agent == 'claude': value=mcp._render_json_block(d, '${VAR}', 'http')\n"
        "elif agent == 'opencode': value=mcp._render_json_block(d, '{env:VAR}', 'remote')\n"
        "else: value=mcp._render_json_block(d, '${VAR}', None)\n"
        "with open(sys.argv[3], 'w', encoding='utf-8') as handle: json.dump(value, handle, ensure_ascii=False)\n"
        "print('rendered')\n"
    )
    return_code, stdout, stderr = _run_skillhub_python(
        script,
        [str(source_path), agent_id, str(output_path)],
        runtime_root,
    )
    if return_code != 0:
        raise AgentConfigError(f"SkillHub MCP renderer failed: {stderr or 'unknown error'}")
    try:
        if output_path.stat().st_size > MCP_MAX_CONFIG_BYTES:
            raise AgentConfigError("SkillHub MCP renderer output exceeds the safety limit")
        return json.loads(output_path.read_text(encoding="utf-8"))
    except AgentConfigError:
        raise
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise AgentConfigError("SkillHub MCP renderer returned invalid output") from exc


def _mcp_toml_quote(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _mcp_render_target_value(value: Any, syntax: str) -> str:
    text = str(value)

    def replace(match: re.Match[str]) -> str:
        name = next((group for group in match.groups() if group), "")
        return syntax.replace("VAR", name)

    return _MCP_ENV_ANY_RE.sub(replace, text)


def _mcp_task_toml(definitions: Sequence[Mapping[str, Any]], upstream_values: Sequence[Any]) -> str:
    lines: list[str] = []
    for definition, upstream in zip(definitions, upstream_values, strict=True):
        # The pinned upstream renderer emits [[mcp_servers.id]], while the
        # installed Codex accepts the ordinary [mcp_servers.id] table.  We
        # deliberately retain the upstream invocation and normalize only this
        # documented compatibility difference.
        if not isinstance(upstream, str):
            raise AgentConfigError("SkillHub Codex renderer returned non-TOML output")
        try:
            import tomllib

            parsed = tomllib.loads(upstream)
        except (ImportError, ValueError, tomllib.TOMLDecodeError) as exc:
            raise AgentConfigError("SkillHub Codex renderer returned invalid TOML") from exc
        if not isinstance(parsed.get("mcp_servers"), dict):
            raise AgentConfigError("SkillHub Codex renderer omitted mcp_servers")
        sid = _mcp_safe_string(definition["id"], "server id")
        table = f"[mcp_servers.{_mcp_toml_quote(sid)}]"
        lines.append(table)
        lines.append(f"enabled = {'true' if definition.get('enabled', True) else 'false'}")
        lines.append('default_tools_approval_mode = "approve"')
        if definition["transport"] == "http":
            lines.append(f"url = {_mcp_toml_quote(definition['url'])}")
            headers = definition.get("headers")
            static_headers: dict[str, str] = {}
            env_headers: dict[str, str] = {}
            if isinstance(headers, dict):
                for key, value in headers.items():
                    refs = _mcp_env_refs(value)
                    if refs:
                        if len(refs) != 1 or _MCP_ENV_REF_RE.fullmatch(str(value)) is None:
                            raise AgentConfigError("Codex HTTP header composite 未被规范化为单一 env 引用")
                        env_headers[str(key)] = refs[0]
                    else:
                        static_headers[str(key)] = str(value)
            if static_headers:
                lines.append(f"[mcp_servers.{_mcp_toml_quote(sid)}.http_headers]")
                for key, value in static_headers.items():
                    lines.append(f"{_mcp_toml_quote(key)} = {_mcp_toml_quote(value)}")
            if env_headers:
                lines.append(f"[mcp_servers.{_mcp_toml_quote(sid)}.env_http_headers]")
                for key, value in env_headers.items():
                    lines.append(f"{_mcp_toml_quote(key)} = {_mcp_toml_quote(value)}")
        else:
            lines.append(f"command = {_mcp_toml_quote(definition['command'])}")
            args = ", ".join(_mcp_toml_quote(value) for value in definition.get("args", []))
            lines.append(f"args = [{args}]")
            env = definition.get("env")
            static_env: dict[str, str] = {}
            env_vars: list[str] = []
            if isinstance(env, dict):
                for key, value in env.items():
                    refs = _mcp_env_refs(value)
                    if refs:
                        if len(refs) != 1 or _MCP_ENV_REF_RE.fullmatch(str(value)) is None:
                            raise AgentConfigError("Codex stdio env composite 未被规范化为单一 env 引用")
                        env_vars.append(str(key))
                    else:
                        static_env[str(key)] = str(value)
            if env_vars:
                lines.append("env_vars = [" + ", ".join(_mcp_toml_quote(value) for value in dict.fromkeys(env_vars)) + "]")
            if static_env:
                lines.append(f"[mcp_servers.{_mcp_toml_quote(sid)}.env]")
                for key, value in static_env.items():
                    lines.append(f"{_mcp_toml_quote(key)} = {_mcp_toml_quote(value)}")
        lines.append("")
    return "\n".join(lines)


def _mcp_task_json(definitions: Sequence[Mapping[str, Any]], upstream_values: Sequence[Any], agent_id: str) -> dict[str, Any]:
    root_key = "mcp" if agent_id == "opencode" else "mcpServers"
    servers: dict[str, Any] = {}
    syntax = "{env:VAR}" if agent_id == "opencode" else "${VAR}"
    for definition, upstream in zip(definitions, upstream_values, strict=True):
        if not isinstance(upstream, dict):
            raise AgentConfigError("SkillHub MCP renderer returned invalid JSON block")
        item: dict[str, Any] = {"enabled": bool(definition.get("enabled", True))}
        if definition["transport"] == "http":
            if agent_id == "opencode":
                item["type"] = "remote"
            elif agent_id == "claude":
                item["type"] = "http"
            item["url"] = definition["url"]
            if definition.get("headers"):
                item["headers"] = {
                    str(key): _mcp_render_target_value(value, syntax)
                    for key, value in definition["headers"].items()
                }
        else:
            if agent_id == "opencode":
                item["type"] = "local"
                item["command"] = [definition["command"], *definition.get("args", [])]
                item.pop("enabled", None)
                item["enabled"] = bool(definition.get("enabled", True))
                if definition.get("env"):
                    item["environment"] = {
                        str(key): _mcp_render_target_value(value, syntax)
                        for key, value in definition["env"].items()
                    }
            else:
                if agent_id == "claude":
                    item["type"] = "stdio"
                item["command"] = definition["command"]
                item["args"] = list(definition.get("args", []))
                if definition.get("env"):
                    item["env"] = {
                        str(key): _mcp_render_target_value(value, syntax)
                        for key, value in definition["env"].items()
                    }
        servers[str(definition["id"])] = item
    return {root_key: servers}


def _mcp_validate_task_config(path: Path, agent_id: str, ids: Sequence[str]) -> None:
    expected = set(ids)
    try:
        if agent_id == "codex":
            import tomllib

            document = tomllib.loads(path.read_text(encoding="utf-8"))
            servers = document.get("mcp_servers")
        else:
            document = json.loads(path.read_text(encoding="utf-8"))
            servers = document.get("mcp" if agent_id == "opencode" else "mcpServers")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise AgentConfigError("task-local MCP 配置无法解析") from exc
    if not isinstance(servers, dict) or set(servers) != expected or _mcp_task_contains_secret_literal(document):
        raise AgentConfigError("task-local MCP 配置未通过 selected-only/secret 校验")
    for sid, item in servers.items():
        if not isinstance(item, dict):
            raise AgentConfigError("task-local MCP server 条目无效")
        if agent_id == "codex":
            if item.get("command") and not isinstance(item.get("command"), str):
                raise AgentConfigError("Codex task-local command 格式无效")
        elif item.get("type") == "local" and not isinstance(item.get("command"), list):
            raise AgentConfigError("OpenCode task-local local command 必须是数组")


def _mcp_task_contains_secret_literal(value: Any, key: str = "") -> bool:
    """Reject literals while allowing Codex's variable-name indirections."""

    if key == "env_http_headers":
        return not isinstance(value, dict) or any(
            not _MCP_ENV_NAME_RE.fullmatch(str(item))
            for item in value.values()
        )
    if key == "env_vars":
        return not isinstance(value, list) or any(
            not isinstance(item, str) or not _MCP_ENV_NAME_RE.fullmatch(item)
            for item in value
        )
    if isinstance(value, dict):
        return any(
            _mcp_task_contains_secret_literal(item, str(item_key))
            for item_key, item in value.items()
        )
    if isinstance(value, list):
        return any(_mcp_task_contains_secret_literal(item, key) for item in value)
    return _mcp_is_secret_literal(key, value)


def prepare_mcp_configuration(
    agent_id: str,
    mcp_ids: Sequence[str],
    workspace: Path,
    *,
    snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Generate selected MCP definitions inside one run workspace only."""

    agent_id = _valid_agent_id(agent_id)
    if not isinstance(mcp_ids, Sequence) or isinstance(mcp_ids, (str, bytes)):
        raise AgentConfigError("mcp_ids 必须是数组")
    ids = [str(item or "").strip() for item in mcp_ids]
    if len(ids) > MCP_MAX_SERVERS or any(not _MCP_ID_RE.fullmatch(item) for item in ids):
        raise AgentConfigError("mcp_ids 含有无效或过多的 server id")
    ids = list(dict.fromkeys(ids))
    if not ids:
        return None
    supported, reason = _mcp_support(agent_id)
    if not supported:
        raise AgentConfigError(f"目标 Agent {agent_id} 不支持选定 MCP：{reason}")
    definitions: list[Mapping[str, Any]] = []
    for sid, definition in zip(ids, _mcp_frozen_definitions(agent_id, ids, snapshot), strict=True):
        if definition.get("reason"):
            raise AgentConfigError(f"MCP server {sid} 不可运行：{definition['reason']}")
        if definition.get("transport") not in {"http", "stdio"}:
            raise AgentConfigError(f"MCP server {sid} transport 不受支持")
        definitions.append(definition)

    workspace = Path(workspace).resolve()
    if not _inside(workspace, _core().DATA_ROOT.resolve()):
        raise AgentConfigError("MCP task workspace 必须位于 KXY_DATA_ROOT 内")
    target_dir = workspace / "mcp"
    if target_dir.is_symlink() or (target_dir.exists() and not target_dir.is_dir()):
        raise AgentConfigError("MCP task workspace 目录不安全")
    target_dir.mkdir(parents=True, exist_ok=True)
    render_root = _skillhub_runtime_root() / f"mcp-render-{uuid.uuid4().hex}"
    try:
        upstream_values = [_mcp_render_upstream(definition, agent_id, render_root) for definition in definitions]
        if agent_id == "codex":
            content = _mcp_task_toml(definitions, upstream_values)
            path = target_dir / "codex.toml"
        else:
            content = _mcp_task_json(definitions, upstream_values, agent_id)
            path = target_dir / f"{agent_id}.json"
            content = json.dumps(content, ensure_ascii=False, indent=2) + "\n"
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(content, encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(path)
        _mcp_validate_task_config(path, agent_id, ids)
        relative = str(path.relative_to(workspace))
        refs = sorted(
            {
                ref
                for definition in definitions
                for value in (definition.get("headers", {}), definition.get("env", {}))
                for item in (value.values() if isinstance(value, dict) else [])
                for ref in _mcp_env_refs(item)
            }
        )
        if agent_id == "codex":
            refs.extend(
                sorted(
                    {
                        str(key)
                        for definition in definitions
                        if definition.get("transport") == "stdio"
                        and isinstance(definition.get("env"), dict)
                        for key, value in definition["env"].items()
                        if _mcp_env_refs(value)
                    }
                )
            )
            refs = list(dict.fromkeys(refs))
        return {
            "agent_id": agent_id,
            "server_ids": ids,
            "path": str(path),
            "relative_path": relative,
            "format": "toml" if agent_id == "codex" else "json",
            "required_env": refs,
            "runnable": True,
            "upstream_commit": SKILLHUB_UPSTREAM_COMMIT,
            "compatibility": "KXY normalizes pinned SkillHub MCP output to installed task-local Agent formats",
        }
    finally:
        shutil.rmtree(render_root, ignore_errors=True)


def _model_request_values(payload: Mapping[str, Any], *, existing: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise AgentConfigError("请求需要 JSON 对象")
    current = existing or {}
    # ``cli_id`` is the public agent identity in the shared contract.  Keep
    # ``agent_id`` as a backwards-compatible alias, but allow the minimal
    # frontend payload ({cli_id, model, ...}) to create a record.
    requested_agent = payload.get("agent_id")
    if requested_agent in (None, ""):
        requested_agent = current.get("agent_id")
    if requested_agent in (None, ""):
        requested_agent = payload.get("cli_id", current.get("cli_id", ""))
    agent_id = str(requested_agent).strip().lower()
    _valid_agent_id(agent_id)
    source = str(payload.get("source", current.get("source", "manual"))).strip().lower()
    if source not in MODEL_SOURCES:
        raise AgentConfigError("source 必须是 native、api 或 manual")
    if existing is None and source == "native":
        raise AgentConfigError("native 模型只能由显式 discovery 刷新")
    native_model_ref_value = payload.get("native_model_ref", current.get("native_model_ref"))
    if native_model_ref_value in (None, ""):
        native_model_ref = None
    else:
        native_model_ref = str(native_model_ref_value).strip()
        if not MODEL_ID_RE.fullmatch(native_model_ref):
            raise AgentConfigError("native_model_ref 格式无效")
    if native_model_ref is not None and source != "manual":
        raise AgentConfigError("native_model_ref 只能用于 source=manual 的本机登录态记录")
    cli_id = str(payload.get("cli_id", current.get("cli_id", agent_id))).strip().lower()
    if cli_id != agent_id:
        raise AgentConfigError("cli_id 必须等于所属 Agent ID")
    model = _safe_model_value(payload.get("model", current.get("model", "")))
    if not model:
        raise AgentConfigError("model 不能为空且只能包含安全的模型 ID 字符")
    alias = _safe_public_text(payload.get("alias", current.get("alias", model)), model)
    if not alias:
        alias = model
    efforts = _effort_list(payload.get("efforts", current.get("efforts", [])))
    default_effort = payload.get("default_effort", current.get("default_effort"))
    if default_effort in (None, ""):
        default_effort = efforts[0] if efforts else None
    else:
        default_effort = str(default_effort).strip()
        if default_effort not in efforts:
            raise AgentConfigError("default_effort 必须属于 efforts")
    credential_id = _validate_credential_id(payload.get("credential_id", current.get("credential_id")))
    if source == "native" and credential_id is not None:
        raise AgentConfigError("native 模型不能绑定凭据；请创建 source=api 的模型记录")
    if source == "api" and credential_id is None:
        raise AgentConfigError("API 模型必须绑定全局 Keychain credential_id")
    if source == "api":
        _validate_api_model_binding(agent_id, credential_id, model)
    discovery_source = _safe_public_text(
        payload.get(
            "discovery_source",
            current.get("discovery_source") or ("user API model" if source == "api" else "manual entry"),
        ),
        "manual entry",
    )
    if not discovery_source:
        discovery_source = "manual entry"
    return {
        "agent_id": agent_id,
        "cli_id": cli_id,
        "model": model,
        "alias": alias,
        "source": source,
        "efforts": efforts,
        "default_effort": default_effort,
        "discovery_source": discovery_source,
        "credential_id": credential_id,
        "native_model_ref": native_model_ref,
    }


def _native_login_model_values(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate a login-state selection against the current native catalog."""

    if not isinstance(payload, Mapping):
        raise AgentConfigError("请求需要 JSON 对象")
    raw_ref = payload.get("native_model_ref")
    if raw_ref in (None, ""):
        return None
    source = str(payload.get("source", "manual")).strip().lower()
    if source != "manual":
        raise AgentConfigError("native_model_ref 只能用于 source=manual 的本机登录态记录")
    raw_agent = payload.get("agent_id")
    raw_cli = payload.get("cli_id")
    if raw_agent in (None, "") and raw_cli in (None, ""):
        raise AgentConfigError("登录态模型必须提供 agent_id 或 cli_id")
    agent_id = str(raw_agent if raw_agent not in (None, "") else raw_cli).strip().lower()
    _valid_agent_id(agent_id)
    cli_id = str(raw_cli if raw_cli not in (None, "") else agent_id).strip().lower()
    if cli_id != agent_id:
        raise AgentConfigError("cli_id 必须等于所属 Agent ID")
    native_model_ref = str(raw_ref).strip()
    if not MODEL_ID_RE.fullmatch(native_model_ref):
        raise AgentConfigError("native_model_ref 格式无效")
    model = _safe_model_value(payload.get("model"))
    if not model:
        raise AgentConfigError("model 不能为空且只能包含安全的模型 ID 字符")
    alias = _safe_public_text(payload.get("alias"), "")
    if not alias:
        raise AgentConfigError("alias 不能为空")
    if "efforts" in payload:
        raise AgentConfigError("登录态模型的 efforts 必须由 native_model_ref 派生")
    if payload.get("credential_id") not in (None, ""):
        raise AgentConfigError("登录态模型不能绑定 API credential")
    with _core().connect_db() as db:
        catalog = db.execute(
            "SELECT * FROM agent_models WHERE id=? AND agent_id=? AND source='native'",
            (native_model_ref, agent_id),
        ).fetchone()
    if catalog is None:
        raise AgentConfigError("native_model_ref 不存在或不属于当前 Agent，请先刷新模型目录")
    catalog_model = _safe_model_value(catalog["model"])
    if model != catalog_model:
        raise AgentConfigError("model 必须与 native_model_ref 指向的原生模型一致")
    efforts = _effort_list(_json(catalog["efforts"], []), field="native model efforts")
    requested_default = payload.get("default_effort")
    if requested_default in (None, ""):
        catalog_default = str(catalog["default_effort"] or "").strip().lower()
        default_effort = catalog_default if catalog_default in efforts else None
    else:
        default_effort = str(requested_default).strip().lower()
        if default_effort not in efforts:
            raise AgentConfigError("default_effort 必须属于 native_model_ref 声明的 efforts")
    return {
        "agent_id": agent_id,
        "cli_id": cli_id,
        "model": catalog_model,
        "alias": alias,
        "source": "manual",
        "efforts": efforts,
        "default_effort": default_effort,
        "discovery_source": str(catalog["discovery_source"] or "native discovery"),
        "credential_id": None,
        "native_model_ref": native_model_ref,
    }


def create_agent_model(payload: Mapping[str, Any]) -> dict[str, Any]:
    ensure_agent_config_schema()
    values = _native_login_model_values(payload)
    if values is not None:
        model_id = f"manual-{uuid.uuid4().hex}"
    else:
        values = _model_request_values(payload)
        provided_id = payload.get("id")
        if provided_id not in (None, ""):
            model_id = str(provided_id).strip()
            if not MODEL_ID_RE.fullmatch(model_id):
                raise AgentConfigError("模型 id 格式无效")
        elif values["source"] == "api":
            model_id = _model_id("api", values["agent_id"], values["model"], values["credential_id"])
        else:
            model_id = f"manual-{uuid.uuid4().hex}"
    now = _now()
    try:
        with _core().connect_db() as db:
            db.execute(
                "INSERT INTO agent_models(id, agent_id, cli_id, model, alias, source, efforts, default_effort, "
                "discovery_source, credential_id, native_model_ref, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    model_id,
                    values["agent_id"],
                    values["cli_id"],
                    values["model"],
                    values["alias"],
                    values["source"],
                    _json_text(values["efforts"]),
                    values["default_effort"],
                    values["discovery_source"],
                    values["credential_id"],
                    values["native_model_ref"],
                    now,
                    now,
                ),
            )
            row = db.execute("SELECT * FROM agent_models WHERE id=?", (model_id,)).fetchone()
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise AgentConfigError(f"模型 id 已存在：{model_id}") from exc
        raise
    return _model_public(dict(row)) if row is not None else {"id": model_id, **values}


def list_agent_models() -> list[dict[str, Any]]:
    ensure_agent_config_schema()
    with _core().connect_db() as db:
        rows = db.execute(
            "SELECT id, agent_id, cli_id, model, alias, source, efforts, default_effort, discovery_source, credential_id, native_model_ref "
            "FROM agent_models ORDER BY agent_id, alias COLLATE NOCASE"
        ).fetchall()
        return [_model_public(dict(row)) for row in rows]


def update_agent_model(model_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    ensure_agent_config_schema()
    if not isinstance(payload, Mapping):
        raise AgentConfigError("请求需要 JSON 对象")
    model_id = str(model_id or "").strip()
    if not MODEL_ID_RE.fullmatch(model_id):
        raise AgentConfigError("模型 id 格式无效")
    with _core().connect_db() as db:
        row = db.execute("SELECT * FROM agent_models WHERE id=?", (model_id,)).fetchone()
    if row is None:
        raise AgentConfigError(f"模型不存在，请重新绑定：{model_id}")
    current = dict(row)
    current["efforts"] = _json(current.get("efforts"), [])
    if "source" in payload and str(payload["source"]).lower() != current["source"]:
        raise AgentConfigError("不能修改模型 source；请创建新的手动/API模型")
    if "agent_id" in payload and str(payload["agent_id"]).strip().lower() != str(current["agent_id"]):
        raise AgentConfigError("不能修改模型所属 Agent")
    if "cli_id" in payload and str(payload["cli_id"]).strip().lower() != str(current["cli_id"]):
        raise AgentConfigError("不能修改模型 cli_id；请创建新的模型记录")
    current_native_ref = str(current.get("native_model_ref") or "").strip()
    requested_native_ref = payload.get("native_model_ref")
    has_login_ref = current_native_ref or requested_native_ref not in (None, "")
    if has_login_ref:
        if payload.get("credential_id") not in (None, ""):
            raise AgentConfigError("登录态模型不能绑定凭据；凭据由本机 CLI 登录态管理")
        unsupported = set(payload) - {"alias", "default_effort"}
        if unsupported:
            raise AgentConfigError("登录态模型只允许修改 alias/default_effort；能力由 native_model_ref 管理")
        values = _model_request_values({**current, **dict(payload)}, existing=current)
    elif current["source"] == "native":
        if payload.get("credential_id") not in (None, ""):
            raise AgentConfigError("native 模型不能绑定凭据；请创建 source=api 的模型记录")
        unsupported = set(payload) - {"alias", "default_effort"}
        if unsupported:
            raise AgentConfigError("native 模型只允许修改 alias/default_effort；能力由 discovery 管理")
    if not has_login_ref:
        values = _model_request_values({**current, **dict(payload)}, existing=current)
    now = _now()
    with _core().connect_db() as db:
        db.execute(
            "UPDATE agent_models SET cli_id=?, model=?, alias=?, efforts=?, default_effort=?, discovery_source=?, "
            "credential_id=?, native_model_ref=?, updated_at=? WHERE id=?",
            (
                values["cli_id"],
                values["model"],
                values["alias"],
                _json_text(values["efforts"]),
                values["default_effort"],
                values["discovery_source"],
                values["credential_id"],
                values["native_model_ref"],
                now,
                model_id,
            ),
        )
        saved = db.execute("SELECT * FROM agent_models WHERE id=?", (model_id,)).fetchone()
    return _model_public(dict(saved))


def delete_agent_model(model_id: str) -> None:
    ensure_agent_config_schema()
    with _core().connect_db() as db:
        db.execute("DELETE FROM agent_models WHERE id=?", (str(model_id),))


def _credential_binding_metadata(credential_id: str | None) -> dict[str, Any]:
    row = _credential_row(credential_id)
    if row is None:
        raise AgentConfigError("所选凭据已删除，请重新配置")
    env_name = str(row["env_name"])
    if env_name not in ALLOWED_CREDENTIAL_ENVS:
        raise AgentConfigError("凭据环境变量类型不受支持")
    info = _credential_service_info(str(row["id"]), row)
    return {
        "credential_id": str(row["id"]),
        "credential_env_name": env_name,
        "credential_endpoint": row["endpoint"] or "",
        "credential_name": info["name"],
        "credential_provider": info["provider"],
        "credential_api_format": info["api_format"],
        "credential_models": info["models"],
    }


def resolve_model_binding(config: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve an analyzer's model once without selecting an unrelated fallback.

    New analyzers use ``model_ref``. Legacy analyzers with only ``model`` and
    ``credential_id`` remain readable; their source is reported as ``legacy``
    so a run snapshot makes the compatibility path visible.
    """

    ensure_agent_config_schema()
    if not isinstance(config, Mapping):
        raise AgentConfigError("analyzer config 必须是对象")
    requested_agent = str(config.get("agent_id") or config.get("cli") or "codex").strip().lower()
    _valid_agent_id(requested_agent)
    model_ref = str(config.get("model_ref") or "").strip()
    model_row = None
    if model_ref:
        with _core().connect_db() as db:
            model_row = db.execute("SELECT * FROM agent_models WHERE id=?", (model_ref,)).fetchone()
        if model_row is None:
            raise AgentConfigError(f"模型绑定已不存在，请重新绑定：{model_ref}")
        if str(model_row["agent_id"]) != requested_agent:
            raise AgentConfigError("模型绑定与 analyzer 的 Agent 不一致")
    else:
        requested_model = str(config.get("model") or "").strip()
        if requested_model:
            with _core().connect_db() as db:
                matches = db.execute(
                    "SELECT * FROM agent_models WHERE agent_id=? AND model=? ORDER BY source",
                    (requested_agent, requested_model),
                ).fetchall()
            requested_credential = str(config.get("credential_id") or "")
            if requested_credential:
                matches = [row for row in matches if str(row["credential_id"] or "") == requested_credential]
            if len(matches) == 1:
                model_row = matches[0]
            elif len(matches) > 1:
                raise AgentConfigError("legacy model 同时匹配多个 native/API记录，请选择明确的 model_ref")
    profile = get_agent_profile(requested_agent)
    selected_effort = str(config.get("effort") or config.get("variant") or "").strip()
    legacy_model = str(config.get("model") or "").strip()
    if model_row is not None:
        row = dict(model_row)
        efforts = [str(item) for item in _json(row.get("efforts"), []) if isinstance(item, str)]
        if selected_effort and selected_effort not in efforts:
            raise AgentConfigError(
                f"所选 effort 不在模型记录中：{selected_effort}；可用值：{', '.join(efforts) or '未发现'}"
            )
        credential_id = row.get("credential_id")
        if config.get("credential_id") and credential_id and str(config["credential_id"]) != str(credential_id):
            raise AgentConfigError("模型记录已经绑定另一条凭据，请在全局模型设置中修改")
        if credential_id is None and config.get("credential_id"):
            raise AgentConfigError("明确的 model_ref 没有凭据绑定；请清除旧 credential_id 或在全局模型设置中绑定")
        if str(row.get("source") or "") == "api":
            _validate_api_model_binding(str(row["agent_id"]), str(credential_id), str(row["model"]))
        binding = {
            "model_ref": row["id"],
            "model_id": row["id"],
            "agent_id": row["agent_id"],
            "cli": row["agent_id"],
            "executable": profile.get("resolved_executable") or profile["executable"],
            "runtime_interpreter": profile.get("runtime_interpreter"),
            "runtime_status": profile.get("runtime", {}).get("status") if isinstance(profile.get("runtime"), dict) else None,
            "cli_id": row["cli_id"],
            "model": row["model"],
            "alias": row["alias"],
            "source": row["source"],
            "native_model_ref": row.get("native_model_ref"),
            "efforts": efforts,
            "default_effort": row.get("default_effort"),
            "selected_effort": selected_effort or str(row.get("default_effort") or ""),
            "discovery_source": row["discovery_source"],
            "credential_id": _validate_credential_id(credential_id),
        }
    else:
        # Compatibility path: preserve the old model/credential fields and do
        # not invent a native/API record or silently choose a different model.
        credential_id = _validate_credential_id(config.get("credential_id"))
        binding = {
            "model_ref": None,
            "model_id": None,
            "agent_id": requested_agent,
            "cli": requested_agent,
            "executable": profile.get("resolved_executable") or profile["executable"],
            "runtime_interpreter": profile.get("runtime_interpreter"),
            "runtime_status": profile.get("runtime", {}).get("status") if isinstance(profile.get("runtime"), dict) else None,
            "cli_id": requested_agent,
            "model": legacy_model,
            "alias": legacy_model or "CLI 默认模型",
            "source": "legacy" if legacy_model else "cli-default",
            "efforts": [],
            "default_effort": None,
            "selected_effort": selected_effort,
            "discovery_source": "legacy analyzer config" if legacy_model else "CLI default",
            "credential_id": credential_id,
            "native_model_ref": None,
        }
    if binding.get("credential_id"):
        binding.update(_credential_binding_metadata(str(binding["credential_id"])))
    else:
        binding.update(
            {
                "credential_env_name": None,
                "credential_endpoint": "",
                "credential_name": None,
                "credential_provider": None,
                "credential_api_format": None,
                "credential_models": [],
            }
        )
    return binding


def snapshot_model_binding(config: Mapping[str, Any]) -> dict[str, Any]:
    """Return the immutable, secret-free model/executable binding for a run."""

    return json.loads(_json_text(resolve_model_binding(config)))


def _workspace_path(workspace: Path) -> Path:
    if not isinstance(workspace, Path):
        workspace = Path(workspace)
    try:
        resolved = workspace.resolve(strict=True)
    except OSError as exc:
        raise AgentConfigError(f"运行 workspace 不存在：{workspace}") from exc
    if not resolved.is_dir():
        raise AgentConfigError("运行 workspace 必须是文件夹")
    return resolved


def _workspace_file(path: Path, workspace: Path, *, must_exist: bool = True) -> Path:
    try:
        resolved = path.resolve(strict=must_exist)
    except OSError as exc:
        raise AgentConfigError(f"workspace 内文件不存在：{path}") from exc
    if not _inside(resolved, workspace) or (must_exist and (resolved.is_symlink() or not resolved.is_file())):
        raise AgentConfigError("附件必须是 workspace 内的普通文件")
    return resolved


def _workspace_skill(path: Path, workspace: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise AgentConfigError(f"workspace 内 Skill 不存在：{path}") from exc
    if not _inside(resolved, workspace) or not resolved.is_dir():
        raise AgentConfigError("Skill 必须位于当前 workspace 内")
    return resolved


def _project_grok_skills(skill_paths: Sequence[Path], workspace: Path) -> None:
    """Project workspace skills into grok's CWD-level discovery directory.

    grok has no ``--skill`` flag; skills are discovered from
    ``<cwd>/.grok/skills``.  Links stay inside the workspace so the OS
    confinement boundary is unchanged, and each link target has already been
    validated by ``_workspace_skill`` before this helper runs.
    """

    grok_root = workspace / ".grok"
    if grok_root.is_symlink() or (grok_root.exists() and not grok_root.is_dir()):
        raise AgentConfigError("Grok workspace .grok 路径不是目录")
    skills_root = grok_root / "skills"
    skills_root.mkdir(parents=True, exist_ok=True)
    for skill in skill_paths:
        if not skill.is_dir():
            raise AgentConfigError(f"Grok skill 投影源不是目录：{skill}")
        link = skills_root / skill.name
        try:
            if link.is_symlink() and os.readlink(link) == str(skill):
                continue
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(skill, target_is_directory=True)
        except OSError as exc:
            raise AgentConfigError(f"Grok skill 投影失败：{skill.name}") from exc


def build_headless_command(
    agent_id: str,
    prompt: str,
    workspace: Path,
    *,
    executable: str | None = None,
    runtime_interpreter: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    attachments: Sequence[Path] = (),
    skills: Sequence[Path] = (),
    expect_json: bool = False,
    network: bool = True,
    last_message: Path | None = None,
    endpoint: str | None = None,
    credential_env_name: str | None = None,
    credential_provider: str | None = None,
) -> list[str]:
    """Build a verified CLI argv list; no shell interpolation is used."""

    agent_id = _valid_agent_id(agent_id)
    if not isinstance(prompt, str) or "\x00" in prompt:
        raise AgentConfigError("prompt 必须是无 NUL 字符的文本")
    root = _workspace_path(workspace)
    binary = _resolve_executable_spec(executable) if executable else _configured_executable(agent_id)
    if not binary:
        raise HeadlessUnavailable(f"{agent_id} 可执行文件不可用")
    runtime_binding = _runtime_probe(binary, agent_id, runtime_interpreter)
    # Every actual CLI launch is gated by the same bounded --version probe,
    # including fixed native binaries that do not need a separate interpreter.
    if runtime_binding.get("status") != "READY":
        raise HeadlessUnavailable(
            f"{agent_id} runtime 不可用：{runtime_binding.get('message') or '请在 Agent 设置中选择可用解释器'}"
        )

    def finalize(command: Sequence[str]) -> list[str]:
        return _runtime_argv(binary, [str(item) for item in command][1:], runtime_binding)

    if agent_id == "deepseek" and not _dsh_headless_present():
        raise HeadlessUnavailable(
            f"DSH headless profile 不存在：{_dsh_headless_dir()}；不能把 web profile 当作 headless"
        )
    if endpoint and credential_env_name not in ALLOWED_CREDENTIAL_ENVS:
        raise AgentConfigError("API endpoint 必须和受支持的凭据环境变量绑定")
    model_value = _safe_model_value(model) if model else ""
    if model and not model_value:
        raise AgentConfigError("model 格式无效")
    model = model_value or None
    effort = str(effort or "").strip()
    if model and "\x00" in model:
        raise AgentConfigError("model 包含非法字符")
    if effort and not EFFORT_RE.fullmatch(effort):
        raise AgentConfigError("effort 格式无效")
    attachment_paths = [_workspace_file(Path(item), root) for item in attachments]
    skill_paths = [_workspace_skill(Path(item), root) for item in skills]
    message_file = _workspace_file(Path(last_message), root, must_exist=False) if last_message else root / "last-message.txt"

    if agent_id == "codex":
        argv = [
            binary,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--json",
            "--output-last-message",
            str(message_file),
            "--sandbox",
            "workspace-write",
            "--skip-git-repo-check",
            "-C",
            str(root),
        ]
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--config", f"model_reasoning_effort={json.dumps(effort)}"]
        argv += ["--config", f"sandbox_workspace_write.network_access={'true' if network else 'false'}"]
        if endpoint:
            if credential_env_name != "OPENAI_API_KEY":
                raise AgentConfigError("Codex API 绑定必须使用 OpenAI Responses 兼容凭据")
            argv += [
                "--config",
                'model_provider="kxy"',
                "--config",
                "model_providers.kxy="
                + "{name=\"kxy\",base_url="
                + json.dumps(endpoint.rstrip("/"))
                + ',env_key="OPENAI_API_KEY",wire_api="responses"}',
            ]
        for attachment in attachment_paths:
            if attachment.suffix.lower() in {".png", ".jpg", ".jpeg"}:
                argv += ["--image", str(attachment)]
        return finalize([*argv, prompt])

    if agent_id == "claude":
        argv = [
            binary,
            "-p",
            "--output-format",
            "json" if expect_json else "stream-json",
            "--no-session-persistence",
            "--permission-mode",
            "acceptEdits",
        ]
        if not expect_json:
            # Claude Code requires verbose mode for the useful stream-json
            # event stream; the flag is documented and has no bypass effect.
            argv.append("--verbose")
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        return finalize([*argv, prompt])

    if agent_id == "opencode":
        argv = [binary, "run", "--pure", "--format", "json", "--dir", str(root)]
        if model:
            provider_key = _task_provider_key(credential_provider) if credential_provider else ""
            argv += ["--model", f"{provider_key}/{model}" if provider_key else model]
        if effort:
            argv += ["--variant", effort]
        for attachment in attachment_paths:
            argv += ["--file", str(attachment)]
        # OpenCode's --file is an array option. The CLI handler explicitly
        # merges the yargs `message` and `--` buckets, so the separator keeps
        # the prompt out of the last file value and protects prompts beginning
        # with a dash.
        return finalize([*argv, "--", prompt])

    if agent_id == "pi":
        argv = [
            binary,
            "--print",
            "--mode",
            "json",
            "--no-session",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
        ]
        if credential_provider:
            argv += ["--provider", _task_provider_key(credential_provider)]
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--thinking", effort]
        for skill in skill_paths:
            argv += ["--skill", str(skill)]
        argv.append("--")
        argv.extend(f"@{attachment}" for attachment in attachment_paths)
        argv.append(prompt)
        return finalize(argv)

    if agent_id == "hermes":
        if effort:
            raise HeadlessUnavailable("Hermes oneshot help 未声明 effort 参数")
        argv = [binary]
        if model:
            argv += ["--model", model]
        if skill_paths:
            argv += ["--skills", ",".join(str(path) for path in skill_paths)]
        argv += ["-z", prompt]
        return finalize(argv)

    if agent_id == "workbuddy":
        argv = [
            binary,
            "-p",
            "--output-format",
            "json" if expect_json else "stream-json",
            "--no-session-persistence",
            "--permission-mode",
        ]
        # acceptEdits is a documented permission mode; the OS wrapper below is
        # the actual file boundary. No dangerous bypass flag is ever emitted.
        argv.append("acceptEdits")
        if not expect_json:
            argv.append("--verbose")
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        return finalize([*argv, prompt])

    if agent_id == "grok":
        if skill_paths:
            _project_grok_skills(skill_paths, root)
        # --single/-p is the documented headless one-shot entry; its prompt is
        # an option value, not a positional (a bare positional opens the TUI).
        # streaming-json is line-delimited; --output-format json is pretty
        # printed and cannot be parsed line by line.
        # "auto" is the only verified mode that approves tool execution in
        # single-turn headless runs: acceptEdits and dontAsk both cancel the
        # tool call ("User cancelled the execution"), which silently ends the
        # turn without a final answer. The actual file boundary stays the OS
        # seatbelt profile, which only permits writes inside the workspace.
        argv = [
            binary,
            "--cwd",
            str(root),
            "--output-format",
            "streaming-json",
            "--permission-mode",
            "auto",
        ]
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
        argv += ["-p", prompt]
        return finalize(argv)

    # The DSH profile's own app interface is intentionally not guessed. The
    # explicit launcher help verification only authorizes a prompt positional
    # argument; model/effort/file flags require a future verified probe.
    if model or effort or attachment_paths or skill_paths:
        raise HeadlessUnavailable("DSH headless 当前只验证了 prompt positional interface")
    return finalize([binary, "--profile", "headless", prompt])


def _credential_env(credential_id: str | None) -> tuple[str | None, str | None, str | None]:
    if not credential_id:
        return None, None, None
    row = _credential_row(credential_id)
    if row is None:
        raise AgentConfigError("所选凭据已删除，请重新配置")
    env_name = str(row["env_name"])
    if env_name not in ALLOWED_CREDENTIAL_ENVS:
        raise AgentConfigError("凭据环境变量类型不受支持")
    secret = _core().keychain_secret(str(row["credential_ref"]))
    if not isinstance(secret, str) or not secret:
        raise AgentConfigError("Keychain 凭据为空")
    return env_name, str(row["endpoint"] or ""), secret


def _anthropic_sdk_base(endpoint: str) -> str:
    """Return the base expected by Anthropic SDK clients before /v1/messages."""

    value = str(endpoint or "").rstrip("/")
    return re.sub(r"/v1$", "", value, flags=re.IGNORECASE) or value


def _task_provider_key(provider: str) -> str:
    return {
        "openai": "kxy-openai",
        "anthropic": "kxy-anthropic",
        "google": "kxy-google",
    }.get(str(provider or "custom").strip().lower(), "kxy-custom")


def _write_pi_models_config(state_root: Path, service_info: Mapping[str, Any], selected_model: str | None) -> None:
    """Project one saved service into pi's documented task-local models.json.

    The file contains only public endpoint/protocol/model metadata and an env
    reference.  The Keychain value is injected into the child environment and
    is never written to this file.
    """

    api_format = str(service_info.get("api_format") or "")
    pi_api = PI_API_FORMATS.get(api_format)
    if not pi_api:
        raise AgentConfigError(f"pi 尚未验证 {api_format} API 服务映射")
    env_name = str(service_info.get("env_name") or "").strip().upper()
    if env_name not in ALLOWED_CREDENTIAL_ENVS:
        raise AgentConfigError("pi API 服务的密钥环境变量类型不受支持")
    provider = str(service_info.get("provider") or "custom").strip().lower()
    endpoint = str(service_info.get("endpoint") or "").strip().rstrip("/")
    if api_format == "anthropic-messages":
        endpoint = _anthropic_sdk_base(endpoint)
    if not endpoint:
        endpoint = {
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com",
            "google": "https://generativelanguage.googleapis.com/v1beta",
        }.get(provider, "")
    if not endpoint:
        raise AgentConfigError("pi API 服务必须提供 Endpoint")

    models: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in service_info.get("models") or []:
        if not isinstance(item, Mapping):
            continue
        model_id = str(item.get("id") or "").strip()
        if not model_id or not _SAFE_MODEL_VALUE_RE.fullmatch(model_id) or model_id in seen:
            continue
        alias = str(item.get("alias") or model_id).replace("\x00", "").strip()[:256] or model_id
        models.append({"id": model_id, "name": alias})
        seen.add(model_id)
    selected = str(selected_model or "").strip()
    if selected and _SAFE_MODEL_VALUE_RE.fullmatch(selected) and selected not in seen:
        models.append({"id": selected, "name": selected})
    config_path = state_root / "models.json"
    if not models:
        if config_path.is_symlink() or config_path.is_file():
            config_path.unlink()
        elif config_path.exists():
            raise AgentConfigError("pi task-local models.json 路径不是普通文件")
        return

    provider_key = _task_provider_key(provider)
    document = {
        "providers": {
            provider_key: {
                "baseUrl": endpoint,
                "api": pi_api,
                "apiKey": f"${env_name}",
                "models": models,
            }
        }
    }
    if config_path.is_symlink() or (config_path.exists() and not config_path.is_file()):
        raise AgentConfigError("pi task-local models.json 路径不是普通文件")
    fd, temporary_name = tempfile.mkstemp(prefix=".models-", suffix=".tmp", dir=str(state_root))
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            json.dump(document, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, config_path)
    finally:
        if fd != -1:
            os.close(fd)
        if temporary_path.exists():
            temporary_path.unlink()


def prepare_headless_environment(
    agent_id: str,
    workspace: Path,
    *,
    credential_id: str | None = None,
    network: bool = True,
    base_env: Mapping[str, str] | None = None,
    api_format: str | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """Prepare a minimal child environment and reuse a Keychain credential.

    The returned mapping is an in-memory process environment. Callers must not
    serialize it; in particular, the selected API key is present only when a
    child process is launched and must be redacted from its output.
    """

    agent_id = _valid_agent_id(agent_id)
    root = _workspace_path(workspace)
    source = base_env if base_env is not None else os.environ
    env = {key: str(source[key]) for key in SAFE_ENV_KEYS if source.get(key) is not None}
    env.setdefault("PATH", os.defpath)
    env["KXY_NODE_WORKSPACE"] = str(root)
    if not network:
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
            env.pop(key, None)
    env_name, endpoint, secret = _credential_env(credential_id)
    service_info = _credential_service_info(str(credential_id)) if credential_id else None
    effective_api_format = str(api_format or (service_info or {}).get("api_format") or "")
    effective_model = str(model or "").strip() or None
    if env_name and secret:
        env[env_name] = secret
        endpoint_for_env = endpoint
        if effective_api_format == "anthropic-messages" and agent_id in {"claude", "pi"}:
            endpoint_for_env = _anthropic_sdk_base(endpoint_for_env)
        endpoint_env = {
            "OPENAI_API_KEY": "OPENAI_BASE_URL",
            "ANTHROPIC_API_KEY": "ANTHROPIC_BASE_URL",
            "GEMINI_API_KEY": "GEMINI_BASE_URL",
        }.get(env_name)
        if endpoint and endpoint_env:
            env[endpoint_env] = endpoint_for_env

    if agent_id == "codex":
        state_root = root / ".cli-state" / "codex"
        if state_root.is_symlink() or (state_root.exists() and not state_root.is_dir()):
            raise AgentConfigError("Codex workspace-local state path is not a directory")
        # Each run owns this directory.  Clear a stale task-local auth copy
        # before creating a new one, so an interrupted run cannot be reused.
        if state_root.exists():
            shutil.rmtree(state_root)
        state_root.mkdir(parents=True, exist_ok=True)
        (state_root / "tmp").mkdir(parents=True, exist_ok=True)
        if not credential_id:
            # CODEX_HOME prevents config/model-cache migration into the native
            # home.  Copy only auth.json, if present, as a short-lived 0600
            # task file; do not symlink a writable native credential target.
            _copy_native_private(
                state_root / "auth.json",
                _home() / ".codex" / "auth.json",
                "Codex native auth",
            )
        env.update(
            {
                "CODEX_HOME": str(state_root),
                "TMPDIR": str(state_root / "tmp"),
            }
        )
    elif agent_id == "opencode":
        state_root = root / ".cli-state" / "opencode"
        if state_root.is_symlink() or (state_root.exists() and not state_root.is_dir()):
            raise AgentConfigError("OpenCode workspace-local state path is not a directory")
        for kind in ("data", "state", "cache", "config", "tmp"):
            (state_root / kind).mkdir(parents=True, exist_ok=True)
        for name, kind in (
            ("XDG_DATA_HOME", "data"),
            ("XDG_STATE_HOME", "state"),
            ("XDG_CACHE_HOME", "cache"),
            ("XDG_CONFIG_HOME", "config"),
        ):
            env[name] = str(state_root / kind)
        env["TMPDIR"] = str(state_root / "tmp")
        if not credential_id:
            native_data_value = os.environ.get("XDG_DATA_HOME", "").strip()
            native_data = Path(native_data_value).expanduser() if native_data_value else _home() / ".local" / "share"
            if not native_data.is_absolute():
                native_data = _home() / native_data
            # OpenCode stores its native account in this documented XDG data
            # path.  Keep the account file as a read-only reference while all
            # other OpenCode state remains workspace-local.
            _link_native_readonly(
                state_root / "data" / "opencode" / "auth.json",
                native_data / "opencode" / "auth.json",
                "OpenCode native auth",
            )
        local_config: dict[str, Any] = {
            "autoupdate": False,
            "share": "disabled",
            "snapshot": False,
            "permission": {"*": "allow", "external_directory": "deny"},
            "instructions": [],
        }
        if service_info:
            api_format = str(service_info.get("api_format") or "")
            package = {
                "openai-chat-completions": "@ai-sdk/openai-compatible",
                "openai-responses": "@ai-sdk/openai",
                "anthropic-messages": "@ai-sdk/anthropic",
            }.get(api_format)
            if not package:
                raise AgentConfigError(f"OpenCode 尚未验证 {api_format} API 服务映射")
            provider_key = _task_provider_key(str(service_info.get("provider") or "custom"))
            service_endpoint = str(service_info.get("endpoint") or "").strip().rstrip("/")
            if not service_endpoint:
                service_endpoint = {
                    "openai": "https://api.openai.com/v1",
                    "anthropic": "https://api.anthropic.com/v1",
                }.get(str(service_info.get("provider") or "custom").strip().lower(), "")
            if not service_endpoint:
                raise AgentConfigError("OpenCode API 服务必须提供 Endpoint")
            models: dict[str, dict[str, str]] = {}
            for item in service_info.get("models") or []:
                if not isinstance(item, Mapping):
                    continue
                model_id = str(item.get("id") or "").strip()
                if not model_id or not _SAFE_MODEL_VALUE_RE.fullmatch(model_id):
                    continue
                models[model_id] = {"name": str(item.get("alias") or model_id).replace("\x00", "").strip()[:256] or model_id}
            if effective_model and _SAFE_MODEL_VALUE_RE.fullmatch(effective_model) and effective_model not in models:
                models[effective_model] = {"name": effective_model}
            local_config["provider"] = {
                provider_key: {
                    "npm": package,
                    "name": str(service_info.get("name") or provider_key)[:160],
                    "options": {
                        "baseURL": service_endpoint,
                        "apiKey": "{" + "env:" + str(service_info.get("env_name") or env_name) + "}",
                    },
                    "models": models,
                }
            }
        env["OPENCODE_CONFIG_CONTENT"] = _json_text(local_config)
    elif agent_id == "claude":
        state_root = root / ".cli-state" / "claude"
        if state_root.is_symlink() or (state_root.exists() and not state_root.is_dir()):
            raise AgentConfigError("Claude workspace-local state path is not a directory")
        for kind in ("tmp", "debug"):
            (state_root / kind).mkdir(parents=True, exist_ok=True)
        if not credential_id:
            # Claude Code reads these documented settings.env values even when
            # CLAUDE_CONFIG_DIR points to an isolated workspace directory.
            # Copy only the explicit credential/endpoint/model allowlist; do
            # not import hooks, permissions, paths, or other user settings.
            env.update(_read_claude_native_env())
        env.update(
            {
                "CLAUDE_CONFIG_DIR": str(state_root),
                "CLAUDE_CODE_TMPDIR": str(state_root / "tmp"),
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
                "CLAUDE_CODE_DEBUG_LOGS_DIR": str(state_root / "debug"),
                "TMPDIR": str(state_root / "tmp"),
            }
        )
    elif agent_id == "pi":
        state_root = root / ".cli-state" / "pi"
        if state_root.is_symlink() or (state_root.exists() and not state_root.is_dir()):
            raise AgentConfigError("pi workspace-local state path is not a directory")
        (state_root / "tmp").mkdir(parents=True, exist_ok=True)
        if service_info:
            _write_pi_models_config(state_root, service_info, effective_model)
        else:
            config_path = state_root / "models.json"
            if config_path.is_symlink() or config_path.is_file():
                config_path.unlink()
            elif config_path.exists():
                raise AgentConfigError("pi task-local models.json 路径不是普通文件")
        env["PI_CODING_AGENT_DIR"] = str(state_root)
        env["TMPDIR"] = str(state_root / "tmp")
        env["PI_OFFLINE"] = "0" if network else "1"
    elif agent_id == "hermes":
        state_root = root / ".cli-state" / "hermes"
        if state_root.is_symlink() or (state_root.exists() and not state_root.is_dir()):
            raise AgentConfigError("Hermes workspace-local state path is not a directory")
        (state_root / "tmp").mkdir(parents=True, exist_ok=True)
        if not credential_id:
            native_home = _home() / ".hermes"
            _link_native_readonly(state_root / ".env", native_home / ".env", "Hermes native dotenv")
            _link_native_readonly(
                state_root / "config.yaml",
                native_home / "config.yaml",
                "Hermes native config",
            )
        env["HERMES_HOME"] = str(state_root)
        env["TMPDIR"] = str(state_root / "tmp")
    elif agent_id == "workbuddy":
        state_root = root / ".cli-state" / "workbuddy"
        if state_root.is_symlink() or (state_root.exists() and not state_root.is_dir()):
            raise AgentConfigError("WorkBuddy workspace-local state path is not a directory")
        (state_root / "tmp").mkdir(parents=True, exist_ok=True)
        if not credential_id:
            # The CLI's documented user settings file may contain an explicit
            # API token/base URL under env.  The desktop login/session store is
            # separate and intentionally not guessed or traversed here.
            env.update(_read_workbuddy_native_env())
        env.update(
            {
                "CODEBUDDY_CONFIG_DIR": str(state_root),
                "WORKBUDDY_CONFIG_DIR": str(state_root),
                "WORKBUDDY_DATA_DIR": str(state_root),
                "CODEBUDDY_DISABLE_COMPILE_CACHE": "1",
                "TMPDIR": str(state_root / "tmp"),
            }
        )
        env["CODEBUDDY_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
    elif agent_id == "grok":
        state_root = root / ".cli-state" / "grok"
        if state_root.is_symlink() or (state_root.exists() and not state_root.is_dir()):
            raise AgentConfigError("Grok workspace-local state path is not a directory")
        (state_root / "tmp").mkdir(parents=True, exist_ok=True)
        if not credential_id:
            # grok resolves every state path under $HOME/.grok.  HOME points
            # at the workspace-local state root, so the private auth file is
            # copied one level below it; user config.toml and skills are
            # intentionally not imported.
            _copy_native_private(
                state_root / ".grok" / "auth.json",
                _home() / ".grok" / "auth.json",
                "Grok native auth",
            )
        env["HOME"] = str(state_root)
        env["TMPDIR"] = str(state_root / "tmp")
    elif agent_id == "deepseek":
        env["DSH_HOME"] = str(_dsh_home())
    return env


def _seatbelt_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _seatbelt_profile(workspace: Path, network: bool) -> str:
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny file-write*)",
        '(allow file-write* (literal "/dev/null") (literal "/dev/tty") (literal "/dev/urandom"))',
        f"(allow file-write* (subpath {_seatbelt_quote(str(workspace))}))",
    ]
    if not network:
        lines.append("(deny network*)")
    return "\n".join(lines) + "\n"


def wrap_headless_command(
    argv: Sequence[str],
    agent_id: str,
    workspace: Path,
    *,
    network: bool = True,
) -> tuple[list[str], Path | None]:
    """Apply the actual confinement boundary for CLIs without native sandboxing."""

    agent_id = _valid_agent_id(agent_id)
    root = _workspace_path(workspace)
    if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)) or not argv:
        raise AgentConfigError("argv 必须是非空参数数组")
    command = [str(item) for item in argv]
    if any("\x00" in item for item in command):
        raise AgentConfigError("argv 包含 NUL 字符")
    if agent_id == "codex":
        if not network and not any(
            item == "sandbox_workspace_write.network_access=false" for item in command
        ):
            raise HeadlessUnavailable("Codex network-off 未包含其 workspace sandbox 的网络禁用配置")
        return command, None
    if os.sys.platform != "darwin":
        raise HeadlessUnavailable("当前平台没有可验证的 OS 文件/网络隔离实现")
    sandbox = "/usr/bin/sandbox-exec"
    if not Path(sandbox).is_file() or not os.access(sandbox, os.X_OK):
        raise HeadlessUnavailable("macOS sandbox-exec 不可用，拒绝无隔离运行")
    profile_file = root / ".kxy-seatbelt.sb"
    if profile_file.exists() or profile_file.is_symlink():
        raise AgentConfigError("workspace 中已存在 sandbox profile")
    profile_file.write_text(_seatbelt_profile(root, network), encoding="utf-8")
    return [sandbox, "-f", str(profile_file), "--", *command], profile_file


def _bounded_final(value: str, *, preserve_whitespace: bool = False) -> str:
    if len(value) > MAX_FINAL_OUTPUT:
        raise RuntimeError("最终回答超过 250000 字符，请将长报告写入 outputs/ 并返回摘要")
    return _redact(value if preserve_whitespace else value.strip(), MAX_FINAL_OUTPUT)


def _text_from_content(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = [_text_from_content(item) for item in value]
        joined = "\n".join(item for item in parts if item)
        return joined.strip() or None
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"].strip() or None
        return _text_from_content(value.get("content"))
    return None


def _extract_json_event(value: Any) -> tuple[str | None, Any | None]:
    if not isinstance(value, dict):
        return None, None
    structured = value.get("structured_output")
    if structured is None and isinstance(value.get("structured"), (dict, list)):
        structured = value["structured"]
    if isinstance(value.get("result"), str):
        return value["result"].strip() or None, structured
    if isinstance(value.get("output"), str):
        return value["output"].strip() or None, structured
    if value.get("type") == "text":
        part: Any = value.get("part")
        if part is None and isinstance(value.get("data"), str):
            # grok --output-format streaming-json emits {"type":"text","data":...}
            part = value["data"]
        return _text_from_content(part), structured
    if value.get("type") in {"result", "item.completed", "message.completed", "agent_message"}:
        item = value.get("item", value)
        if isinstance(item, dict):
            return _text_from_content(item.get("text") or item.get("content") or item.get("message")), structured
    if value.get("type") in {"assistant", "message"}:
        message = value.get("message", value)
        if isinstance(message, dict):
            return _text_from_content(message.get("content") or message.get("text")), structured
    if isinstance(value.get("message"), dict):
        return _text_from_content(value["message"].get("content") or value["message"].get("text")), structured
    return None, structured


def parse_final_output(
    agent_id: str,
    lines: Sequence[str],
    *,
    last_message: Path | None = None,
    expect_json: bool = False,
) -> dict[str, Any]:
    """Parse transport output without asserting that model semantics are correct."""

    agent_id = _valid_agent_id(agent_id)
    if last_message is not None:
        message_path = Path(last_message)
        if message_path.is_file():
            final = _bounded_final(
                message_path.read_text(encoding="utf-8", errors="replace"),
                preserve_whitespace=True,
            )
            if final.strip():
                result: dict[str, Any] = {"text": final, "structured": None, "format": "last-message"}
                if expect_json:
                    try:
                        structured = json.loads(final)
                    except (ValueError, json.JSONDecodeError) as exc:
                        raise RuntimeError("分析器要求 JSON，但最终回答不是合法 JSON") from exc
                    if not isinstance(structured, dict):
                        raise RuntimeError("分析器要求单个 JSON 对象")
                    result["structured"] = structured
                return result
    candidates: list[str] = []
    structured_value: Any | None = None
    plain: list[str] = []
    # grok streaming-json splits the final answer into incremental
    # {"type":"text","data":...} deltas; the deltas must be joined in order.
    grok_text_parts: list[str] = []
    for raw in lines:
        line = str(raw).strip()
        if not line:
            continue
        if len(line) > MAX_PROBE_OUTPUT:
            line = line[:MAX_PROBE_OUTPUT]
        try:
            value = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            plain.append(line)
            continue
        text_value, structured = _extract_json_event(value)
        if structured is not None:
            structured_value = structured
        if text_value:
            if agent_id == "grok":
                grok_text_parts.append(text_value)
            else:
                candidates.append(text_value)
    if agent_id == "grok" and grok_text_parts:
        candidates.append("".join(grok_text_parts))
    if candidates:
        final = _bounded_final(candidates[-1])
        format_name = "json-event"
    elif plain:
        # Hermes -z is documented as final text only; for other CLIs this is a
        # bounded fallback for a text-mode fixture or a compatible wrapper.
        final = _bounded_final("\n".join(plain) if agent_id == "hermes" else plain[-1])
        format_name = "plain"
    else:
        raise RuntimeError("CLI 未产生最终回答；运行失败")
    result = {"text": final, "structured": structured_value, "format": format_name}
    if expect_json:
        try:
            structured = json.loads(final)
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("分析器要求 JSON，但最终回答不是合法 JSON") from exc
        if not isinstance(structured, dict):
            raise RuntimeError("分析器要求单个 JSON 对象")
        result["structured"] = structured
    return result


def extract_final_output(
    lines: Sequence[str],
    last_message: Path | None,
    agent_id: str = "codex",
) -> str:
    """Compatibility wrapper matching the old app helper's string result."""

    return str(parse_final_output(agent_id, lines, last_message=last_message)["text"])


def _picker_path(kind: str, output: str) -> str:
    path = Path(output).expanduser().resolve(strict=True)
    if kind == "file" and not path.is_file():
        raise AgentConfigError("原生选择器返回的路径不是文件")
    if kind == "folder" and not path.is_dir():
        raise AgentConfigError("原生选择器返回的路径不是文件夹")
    return str(path)


def run_native_picker(kind: Literal["file", "folder"], *, timeout: float = PICKER_TIMEOUT) -> dict[str, Any]:
    """Open the fixed macOS chooser and return cancellation separately."""

    if kind not in {"file", "folder"}:
        raise AgentConfigError("picker kind 必须是 file 或 folder")
    if os.sys.platform != "darwin":
        raise HeadlessUnavailable("原生文件选择器仅支持 macOS")
    timeout = max(1.0, min(float(timeout), PICKER_TIMEOUT))
    if not _PICKER_LOCK.acquire(timeout=timeout):
        raise AgentConfigError("已有原生选择器正在打开，请稍后重试")
    try:
        try:
            process = subprocess.run(
                ["/usr/bin/osascript", "-e", _PICKER_SCRIPT, "--", kind],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise HeadlessUnavailable("原生选择器超时，已取消本次选择") from exc
        stdout = (process.stdout or "").strip()
        stderr = (process.stderr or "").strip()
        if stdout == _PICKER_CANCELLED or "user canceled" in stderr.lower() or "-128" in stderr:
            return {"cancelled": True}
        if process.returncode != 0:
            raise HeadlessUnavailable(f"原生选择器失败：{_redact(stderr, 1000) or 'unknown error'}")
        if not stdout:
            return {"cancelled": True}
        return {"cancelled": False, "path": _picker_path(kind, stdout)}
    finally:
        _PICKER_LOCK.release()


@router.get("/agents")
def api_list_agents() -> list[dict[str, Any]]:
    try:
        return list_agent_profiles()
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/agents/{agent_id}")
def api_update_agent(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return update_agent_profile(agent_id, payload)
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agents/refresh")
def api_refresh_agents(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        if payload is not None and not isinstance(payload, dict):
            raise AgentConfigError("请求需要 JSON 对象")
        requested = payload.get("agent_ids") if payload else None
        if requested is not None and (
            not isinstance(requested, list) or any(not isinstance(item, str) for item in requested)
        ):
            raise AgentConfigError("agent_ids 必须是 Agent ID 数组")
        return refresh_agents(requested)
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/discover")
def api_discover_agent(agent_id: str) -> dict[str, Any]:
    try:
        return refresh_agent(agent_id)
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/runtime-probe")
def api_probe_agent_runtime(agent_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        payload = payload if isinstance(payload, dict) else {}
        return probe_agent_runtime(
            agent_id,
            payload.get("runtime_interpreter"),
            persist=payload.get("persist", True) is not False,
        )
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/skillhub/check")
def api_skillhub_check(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise AgentConfigError("请求需要 JSON 对象")
        agent_id = str(payload.get("agent_id") or "codex")
        raw_skill_ids = payload.get("skill_ids", [])
        binding: dict[str, Any] = {
            "agent_id": agent_id,
            "model_ref": payload.get("model_ref"),
            "credential_id": payload.get("credential_id"),
            "model": payload.get("model"),
            "source": payload.get("source"),
        }
        if payload.get("model_ref"):
            binding = resolve_model_binding({"agent_id": agent_id, "model_ref": payload.get("model_ref")})
        return check_skill_dependencies(
            agent_id,
            raw_skill_ids,
            force=bool(payload.get("force")),
            binding=binding,
            mcp_ids=payload.get("mcp_ids", []) if isinstance(payload.get("mcp_ids", []), list) else [],
        )
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/skillhub/checks")
def api_skillhub_checks(skill_id: str | None = None) -> list[dict[str, Any]]:
    try:
        return list_dependency_checks(skill_id)
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/skillhub/checks")
def api_clear_skillhub_checks(skill_id: str | None = None) -> dict[str, Any]:
    try:
        return {"ok": True, "cleared": clear_dependency_checks(skill_id)}
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/skillhub/dependencies")
def api_skillhub_dependencies(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise AgentConfigError("请求需要 JSON 对象")
        skill_id = str(payload.get("skill_id") or "").strip()
        dependencies = payload.get("dependencies")
        if not isinstance(dependencies, dict):
            raise AgentConfigError("dependencies 必须是对象")
        return set_skill_dependencies(skill_id, dependencies)
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/skillhub/diagnostics/confirm")
def api_confirm_skillhub_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise AgentConfigError("请求需要 JSON 对象")
        skill_id = str(payload.get("skill_id") or "").strip()
        keys = payload.get("keys", [])
        if not isinstance(keys, list):
            raise AgentConfigError("keys 必须是数组")
        return confirm_skill_diagnostics(skill_id, keys, str(payload.get("note") or ""))
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/agent-models")
def api_list_agent_models() -> list[dict[str, Any]]:
    try:
        return list_agent_models()
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agent-models")
def api_create_agent_model(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return create_agent_model(payload)
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/skillhub/status")
def api_skillhub_status() -> dict[str, Any]:
    try:
        return skillhub_status()
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/skillhub/index/scan")
def api_skillhub_index_scan() -> dict[str, Any]:
    try:
        return scan_skillhub_index()
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/skillhub/index/sync")
def api_skillhub_index_sync(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return sync_skillhub_index(payload)
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/skillhub/mount")
def api_skillhub_mount(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise AgentConfigError("请求需要 JSON 对象")
        return mount_skillhub(payload.get("agent_id", ""), payload.get("skill_ids", []))
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/agents/{agent_id}/mcps")
def api_discover_agent_mcps(agent_id: str) -> list[dict[str, Any]]:
    try:
        return discover_mcps(agent_id)
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/mcps/import")
def api_import_agent_mcps(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        if not isinstance(payload, dict):
            raise AgentConfigError("请求需要 JSON 对象")
        return import_mcps(agent_id, payload.get("ids", []))
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/mcps")
def api_list_imported_mcps() -> list[dict[str, Any]]:
    try:
        return list_imported_mcps()
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/agent-models/{model_id}")
def api_update_agent_model(model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return update_agent_model(model_id, payload)
    except AgentConfigError as exc:
        status = 404 if "不存在" in str(exc) or "重新绑定" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.delete("/agent-models/{model_id}")
def api_delete_agent_model(model_id: str) -> dict[str, bool]:
    try:
        delete_agent_model(model_id)
        return {"ok": True}
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/agents/{agent_id}/skills")
def api_scan_agent_skills(agent_id: str) -> list[dict[str, Any]]:
    try:
        return scan_agent_skills(agent_id)
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agents/{agent_id}/skills/import")
def api_import_agent_skills(agent_id: str, payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    try:
        return import_agent_skills(agent_id, payload.get("paths", []))
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/picker")
def api_native_picker(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        kind = payload.get("kind")
        if kind not in {"file", "folder"}:
            raise AgentConfigError("picker kind 必须是 file 或 folder")
        return run_native_picker(kind)
    except AgentConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
