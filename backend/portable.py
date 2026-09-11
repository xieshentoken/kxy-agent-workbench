"""Portable kxy workflow packages.

The package format is deliberately data-only.  It carries a sanitized
workflow, optional content-addressed attachments, optional complete Skill
snapshots, and dependency descriptions.  Import is a two-step preview/commit
flow: preview never executes package content, while commit requires explicit
target-device bindings for every model, MCP, and output node.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


PORTABLE_FORMAT = "kxy.portable.v1"
PORTABLE_MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
PORTABLE_MAX_FILES = 800
PORTABLE_MAX_MEMBER_BYTES = 50 * 1024 * 1024
PORTABLE_MAX_TOTAL_BYTES = 100 * 1024 * 1024
PORTABLE_MAX_MANIFEST_BYTES = 1 * 1024 * 1024
PORTABLE_MAX_WORKFLOW_BYTES = 5 * 1024 * 1024
PORTABLE_PREVIEW_TTL_SECONDS = 15 * 60
PORTABLE_MAX_SKILL_FILES = 400
PORTABLE_MAX_SKILL_BYTES = 20 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,255}$")


class PortablePackageError(ValueError):
    """A package or binding failed a local, deterministic validation gate."""


class PortablePreviewExpired(PortablePackageError):
    """The temporary preview has expired or no longer exists."""


def _app():
    """Load the existing application owner lazily to avoid the app import cycle."""

    from . import app

    return app


def _agent_config():
    from . import agent_config

    return agent_config


def _preview_root() -> Path:
    return _app().DATA_ROOT / "portable" / "previews"


def _list_file_rows() -> list[dict[str, Any]]:
    app = _app()
    with app.connect_db() as db:
        return [dict(row) for row in db.execute("SELECT * FROM files ORDER BY created_at DESC").fetchall()]


def _read_file(row: Mapping[str, Any], *, max_bytes: int | None = None) -> bytes:
    app = _app()
    raw_path = str(row.get("stored_path") or "")
    if not raw_path:
        raise PortablePackageError("attachment has no local stored path")
    path = Path(raw_path)
    if path.is_symlink():
        raise PortablePackageError("attachment stored path is a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PortablePackageError("attachment stored path is unavailable") from exc
    if not app.resolved_inside(resolved, app.FILES_ROOT) or not resolved.is_file():
        raise PortablePackageError("attachment stored path leaves the KXY files directory")
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise PortablePackageError("attachment content is unavailable") from exc
    if max_bytes is not None and size > max_bytes:
        raise PortablePackageError("attachment exceeds the portable member limit")
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise PortablePackageError("attachment content is unavailable") from exc
    if max_bytes is not None and len(content) > max_bytes:
        raise PortablePackageError("attachment exceeds the portable member limit")
    return content


def _list_skill_rows() -> list[dict[str, Any]]:
    app = _app()
    with app.connect_db() as db:
        return [dict(row) for row in db.execute("SELECT * FROM skills ORDER BY created_at DESC").fetchall()]


def _skill_root(row: Mapping[str, Any]) -> Path:
    app = _app()
    path = Path(str(row.get("root_path") or ""))
    if path.is_symlink():
        raise PortablePackageError("Skill root is a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PortablePackageError("Skill root is unavailable") from exc
    if not app.resolved_inside(resolved, app.SKILLS_ROOT) or not resolved.is_dir():
        raise PortablePackageError("Skill root leaves the KXY skills directory")
    return resolved


def _list_model_rows() -> list[dict[str, Any]]:
    agent = _agent_config()
    agent.ensure_agent_config_schema()
    rows = [dict(item) for item in agent.list_agent_models()]
    app = _app()
    with app.connect_db() as db:
        for row in rows:
            credential_id = str(row.get("credential_id") or "").strip()
            row["credential_exists"] = bool(
                credential_id
                and db.execute("SELECT 1 FROM credentials WHERE id=?", (credential_id,)).fetchone()
            )
    return rows


def _list_mcp_rows() -> list[dict[str, Any]]:
    # This is a read-only local index lookup.  It intentionally does not call
    # any CLI probe, renderer, network, or credential/Keychain path.
    return [dict(item) for item in _agent_config().list_imported_mcps()]


def _list_grant_rows() -> list[dict[str, Any]]:
    app = _app()
    with app.connect_db() as db:
        return [
            dict(row)
            for row in db.execute("SELECT id, canonical_path, revoked_at, created_at FROM grants ORDER BY created_at DESC").fetchall()
        ]


def _save_imported_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    app = _app()
    identifier = uuid.uuid4().hex
    name = str(workflow.get("name") or "未命名研究流程")
    workflow = app.normalize_workflow(workflow)
    workflow["id"] = identifier
    workflow["name"] = name
    validation = app.validate_workflow(workflow)
    if not validation.get("ok"):
        raise PortablePackageError("bound workflow failed kxy validation before save")
    timestamp = app.utc_now()
    with app.connect_db() as db:
        db.execute(
            "INSERT INTO workflows(id, name, version, document, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (identifier, name, workflow.get("version", ""), app.json_text(workflow), timestamp, timestamp),
        )
    return {"id": identifier, "name": name, "workflow": workflow, "validation": validation}


def _cleanup_created_file(file_id: str) -> None:
    app = _app()
    with app.connect_db() as db:
        row = db.execute("SELECT stored_path FROM files WHERE id=?", (file_id,)).fetchone()
        if row is None:
            return
        path = Path(str(row["stored_path"] or ""))
        db.execute("DELETE FROM files WHERE id=?", (file_id,))
    try:
        resolved = path.resolve(strict=False)
        if app.resolved_inside(resolved, app.FILES_ROOT) and resolved.parent.name == file_id:
            shutil.rmtree(resolved.parent, ignore_errors=True)
    except OSError:
        pass


def _cleanup_created_skill(skill_id: str) -> None:
    app = _app()
    with app.connect_db() as db:
        row = db.execute("SELECT root_path FROM skills WHERE id=?", (skill_id,)).fetchone()
        if row is None:
            return
        root = Path(str(row["root_path"] or ""))
        db.execute("DELETE FROM skills WHERE id=?", (skill_id,))
    try:
        resolved = root.resolve(strict=False)
        if app.resolved_inside(resolved, app.SKILLS_ROOT) and resolved.parent == app.SKILLS_ROOT:
            shutil.rmtree(resolved, ignore_errors=True)
    except OSError:
        pass


def _persist_imported_skill_declarations(skill_id: str, declarations: Any) -> None:
    """Persist a package declaration without invoking SkillHub authority paths."""

    safe = _safe_portable_declarations(declarations)
    if not safe:
        return
    app = _app()
    with app.connect_db() as db:
        row = db.execute("SELECT metadata FROM skills WHERE id=?", (skill_id,)).fetchone()
        if row is None:
            raise PortablePackageError(f"imported Skill record is missing: {skill_id}")
        metadata = row["metadata"]
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
        metadata = dict(metadata) if isinstance(metadata, Mapping) else {}
        # A local declaration already attached to this Skill is authoritative;
        # the portable copy must never replace it.
        if isinstance(metadata.get("portable_declarations"), Mapping):
            return
        metadata["portable_declarations"] = safe
        db.execute("UPDATE skills SET metadata=? WHERE id=?", (app.json_text(metadata), skill_id))


_DROP_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
    "authorization",
    "client_secret",
    "credential_id",
    "credential_ref",
    "grant_id",
    "stored_path",
    "root_path",
    "canonical_path",
    "source_path",
    "native_source",
    "workspace",
    "workdir",
    "executable",
    "runtime_interpreter",
    "runtime_status",
    "runtime_message",
    "file_status",
    "filestatus",
    "skill_names",
    "resolved_model",
    "env",
    "environment",
    "headers",
    "command",
    "args",
    "mcp_config",
}
_PATH_KEYS = {
    "path",
    "stored_path",
    "root_path",
    "canonical_path",
    "source_path",
    "native_source",
    "workspace",
    "workdir",
    "executable",
    "runtime_interpreter",
}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_logical_path(value: Any, fallback: str) -> str:
    raw = str(value or fallback).replace("\\", "/").replace("\x00", "").strip()
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts or raw.startswith("/") or ".." in parts:
        raw = str(fallback or "untitled").replace("\\", "/")
        parts = [part for part in raw.split("/") if part not in {"", ".", ".."}]
    return "/".join(parts)[:512] or "untitled"


def _archive_leaf(value: Any, fallback: str) -> str:
    raw = PurePosixPath(_safe_logical_path(value, fallback)).name
    raw = re.sub(r"[^A-Za-z0-9._()\-\u4e00-\u9fff ]+", "_", raw).strip(" .")
    return (raw or "untitled")[:160]


def _validate_archive_path(raw: Any) -> str:
    if not isinstance(raw, str) or not raw or "\x00" in raw or "\\" in raw:
        raise PortablePackageError("package path must be a non-empty POSIX path")
    if raw.startswith("/") or raw.startswith("./"):
        raise PortablePackageError(f"package path is absolute or rooted: {raw!r}")
    parts = raw.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise PortablePackageError(f"package path contains traversal: {raw!r}")
    return raw


def _json_safe(value: Any, *, key: str = "", schema_context: bool = False) -> Any:
    if isinstance(value, list):
        return [_json_safe(item, key=key, schema_context=schema_context) for item in value]
    if not isinstance(value, Mapping):
        return value
    result: dict[str, Any] = {}
    for raw_key, item in value.items():
        child_key = str(raw_key)
        lower = child_key.lower()
        if not schema_context and (lower in _DROP_KEYS or lower.endswith(("_api_key", "_password", "_secret", "_token"))):
            continue
        if not schema_context and lower in _PATH_KEYS:
            continue
        child_schema = schema_context or lower == "output_schema"
        result[child_key] = _json_safe(item, key=child_key, schema_context=child_schema)
    return result


_PORTABLE_DECLARATION_KEYS = ("compatibility", "dependencies", "tools", "env", "services", "network", "requirements")


def _safe_portable_declarations(value: Any) -> dict[str, Any]:
    """Keep only non-authoritative, secret/path-scrubbed Skill declarations."""

    raw = _mapping(value)
    result: dict[str, Any] = {}
    for key in _PORTABLE_DECLARATION_KEYS:
        if key in raw:
            result[key] = _json_safe(raw[key])
    skillhub = _mapping(raw.get("skillhub"))
    if skillhub:
        result["skillhub"] = {
            key: _json_safe(skillhub[key])
            for key in ("dependencies", "tools", "env", "services", "network")
            if key in skillhub
        }
        if not result["skillhub"]:
            result.pop("skillhub", None)
    # Force a JSON round trip so a malformed declaration cannot be persisted
    # into the local metadata database as an executable or opaque object.
    try:
        return json.loads(json.dumps(result, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise PortablePackageError("Skill dependency declaration is not JSON-safe") from exc


def _nested_workflow(node: Mapping[str, Any]) -> Mapping[str, Any] | None:
    data = node.get("data")
    if not isinstance(data, Mapping):
        return None
    nested = data.get("workflow")
    if not isinstance(nested, Mapping):
        nested = data.get("subflow")
    return nested if isinstance(nested, Mapping) else None


def sanitize_workflow(document: Mapping[str, Any], *, root: bool = True) -> dict[str, Any]:
    """Remove local authority, credentials, and runtime paths recursively."""

    result = _json_safe(copy.deepcopy(dict(document)))
    if not isinstance(result, dict):
        raise PortablePackageError("workflow must be an object")
    nodes = result.get("nodes")
    if not isinstance(nodes, list):
        raise PortablePackageError("workflow.nodes must be an array")
    original_nodes = document.get("nodes") if isinstance(document, Mapping) else []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        original = original_nodes[index] if isinstance(original_nodes, list) and index < len(original_nodes) else node
        original_data = original.get("data") if isinstance(original, Mapping) else None
        nested = _nested_workflow(original) if isinstance(original, Mapping) else None
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        data.pop("subflow", None)
        data.pop("grant_id", None)
        if nested is not None:
            data["workflow"] = sanitize_workflow(nested, root=False)
        node["data"] = data
    if root:
        result.pop("id", None)
    return result


def _walk_workflow(document: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    nodes = document.get("nodes") if isinstance(document, Mapping) else []
    if not isinstance(nodes, list):
        return result
    for index, raw_node in enumerate(nodes):
        if not isinstance(raw_node, Mapping):
            continue
        node = dict(raw_node)
        node_id = str(node.get("id") or f"node-{index + 1}")
        path = "/".join((*prefix, node_id))
        result.append((path, node))
        nested = _nested_workflow(node)
        if nested is not None:
            result.extend(_walk_workflow(nested, (*prefix, node_id)))
    return result


def _append_resource(
    resources: dict[str, dict[str, Any]],
    source_id: str,
    reference: dict[str, Any],
) -> None:
    if not source_id:
        return
    item = resources.setdefault(source_id, {"source_id": source_id, "references": []})
    if reference not in item["references"]:
        item["references"].append(reference)


def _input_file_refs(data: Mapping[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    attachments = data.get("attachments")
    if isinstance(attachments, list):
        for item in attachments:
            if not isinstance(item, Mapping):
                continue
            source_id = str(item.get("file_id") or "").strip()
            if not source_id:
                continue
            fallback = str(item.get("display_name") or item.get("name") or source_id)
            refs.append(
                {
                    "file_id": source_id,
                    "name": str(item.get("name") or fallback),
                    "display_name": str(item.get("display_name") or fallback),
                    "relative_path": _safe_logical_path(item.get("relative_path"), fallback),
                }
            )
    for source_id in _as_ids(data.get("file_ids")):
        if not any(item["file_id"] == source_id for item in refs):
            refs.append({"file_id": source_id, "name": source_id, "display_name": source_id, "relative_path": source_id})
    source_id = str(data.get("file_id") or "").strip()
    if source_id and not any(item["file_id"] == source_id for item in refs):
        refs.insert(0, {"file_id": source_id, "name": source_id, "display_name": source_id, "relative_path": source_id})
    return refs


def collect_dependencies(workflow: Mapping[str, Any]) -> dict[str, Any]:
    attachments: dict[str, dict[str, Any]] = {}
    skills: dict[str, dict[str, Any]] = {}
    mcps: dict[str, dict[str, Any]] = {}
    models: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for node_path, node in _walk_workflow(workflow):
        data = _mapping(node.get("data"))
        node_type = str(node.get("type") or data.get("kind") or "")
        if node_type == "input":
            file_refs = _input_file_refs(data)
        else:
            file_refs = []
            for source_id in _as_ids(data.get("file_ids")):
                file_refs.append({"file_id": source_id, "name": source_id, "display_name": source_id, "relative_path": source_id})
            source_id = str(data.get("file_id") or "").strip()
            if source_id:
                file_refs.append({"file_id": source_id, "name": source_id, "display_name": source_id, "relative_path": str(data.get("fileName") or source_id)})
        for item in file_refs:
            _append_resource(
                attachments,
                item["file_id"],
                {
                    "node_path": node_path,
                    "name": item.get("name") or item.get("display_name") or item["file_id"],
                    "display_name": item.get("display_name") or item.get("name") or item["file_id"],
                    "relative_path": _safe_logical_path(item.get("relative_path"), item["file_id"]),
                },
            )
        for source_id in _as_ids(data.get("skill_ids")):
            _append_resource(skills, source_id, {"node_path": node_path})
        for source_id in _as_ids(data.get("mcp_ids")):
            _append_resource(mcps, source_id, {"node_path": node_path})
        if node_type == "analyzer":
            resolved = _mapping(data.get("resolved_model"))
            models.append(
                {
                    "key": node_path,
                    "node_path": node_path,
                    "node_name": str(data.get("label") or node.get("id") or node_path),
                    "agent_id": str(data.get("agent_id") or data.get("cli") or resolved.get("agent_id") or "").strip().lower(),
                    "model_ref": str(data.get("model_ref") or resolved.get("model_ref") or "").strip(),
                    "model": str(data.get("model") or resolved.get("model") or "").strip(),
                    "alias": str(data.get("model_alias") or data.get("alias") or resolved.get("alias") or "").strip(),
                    "effort": str(data.get("effort") or data.get("variant") or resolved.get("selected_effort") or resolved.get("effort") or "").strip(),
                    "default_effort": "",
                    "required": True,
                }
            )
        if node_type == "container":
            outputs.append(
                {
                    "key": node_path,
                    "node_path": node_path,
                    "node_name": str(data.get("label") or node.get("id") or node_path),
                    "source_has_grant": bool(str(data.get("grant_id") or "").strip()),
                    "required": True,
                }
            )
    return {
        "attachments": [attachments[key] for key in sorted(attachments)],
        "skills": [skills[key] for key in sorted(skills)],
        "mcps": [mcps[key] for key in sorted(mcps)],
        "models": models,
        "outputs": outputs,
    }


def _skill_declarations(metadata: Any, *, skill_id: str = "") -> dict[str, Any]:
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    raw = _mapping(metadata)
    result: dict[str, Any] = {}
    for key in _PORTABLE_DECLARATION_KEYS:
        if key in raw:
            result[key] = _json_safe(raw[key])
    stored = _safe_portable_declarations(raw.get("portable_declarations"))
    for key, value in stored.items():
        if key not in result:
            result[key] = value
    skillhub = _mapping(raw.get("skillhub"))
    if skillhub:
        for key in ("dependencies", "tools", "env", "services", "network"):
            if key in skillhub and key not in result:
                result[key] = _json_safe(skillhub[key])
    if skill_id:
        try:
            current = _agent_config()._skillhub_dependency_context(skill_id)
            declared = _mapping(current.get("dependencies"))
            if declared:
                result["skillhub"] = {key: _json_safe(value) for key, value in declared.items()}
        except Exception:
            # A local Skill can predate the SkillHub ledger.  Its stored
            # metadata remains the only available declaration; preview/import
            # must not execute a diagnostic to fill this optional field.
            pass
    return result


def _snapshot_skill(root: Path) -> tuple[str, list[tuple[str, bytes, int]]]:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise PortablePackageError("Skill snapshot root is not a safe directory")
    digest = hashlib.sha256()
    files: list[tuple[str, bytes, int]] = []
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise PortablePackageError("Skill snapshot contains a symlink")
    # Keep the exact Path ordering used by app.snapshot_skill.  Sorting the
    # relative strings changes the order for names such as scripts.py and
    # scripts/run.sh, which would make an unchanged Skill look modified.
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if "\\" in relative or not relative or ".." in PurePosixPath(relative).parts:
            raise PortablePackageError("Skill snapshot contains an unsafe relative path")
        try:
            stat = path.stat()
            if stat.st_size > PORTABLE_MAX_MEMBER_BYTES:
                raise PortablePackageError(f"Skill file exceeds the portable member limit: {relative}")
            if total + stat.st_size > PORTABLE_MAX_SKILL_BYTES:
                raise PortablePackageError("Skill snapshot exceeds the portable Skill limit")
            content = path.read_bytes()
            mode = stat.st_mode & 0o777
        except OSError as exc:
            raise PortablePackageError(f"Skill file is unavailable: {relative}") from exc
        if len(content) > PORTABLE_MAX_MEMBER_BYTES:
            raise PortablePackageError(f"Skill file exceeds the portable member limit: {relative}")
        digest.update(relative.encode("utf-8") + b"\0" + content)
        # Preserve ordinary permission bits for executable Skill scripts while
        # never carrying setuid/setgid/sticky bits across devices.
        files.append((relative, content, mode))
        total += len(content)
        if len(files) > PORTABLE_MAX_SKILL_FILES or total > PORTABLE_MAX_SKILL_BYTES:
            raise PortablePackageError("Skill snapshot exceeds the portable Skill limit")
    return digest.hexdigest(), files


def _row_id(row: Mapping[str, Any]) -> str:
    return str(row.get("id") or row.get("file_id") or "").strip()


def _public_model(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in ("id", "agent_id", "cli_id", "model", "alias", "source", "efforts", "default_effort")
        if row.get(key) is not None
    }


def _public_mcp(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "name": str(row.get("name") or row.get("label") or row.get("id") or ""),
        "transport": str(row.get("transport") or "unknown"),
        "supported": row.get("supported", True) is not False,
    }


def _public_grant(row: Mapping[str, Any]) -> dict[str, Any]:
    canonical = str(row.get("canonical_path") or "")
    return {
        "id": str(row.get("id") or ""),
        "name": Path(canonical).name if canonical else "目标设备默认 output",
        "path": canonical,
        "active": not bool(row.get("revoked_at")),
    }


def build_package(
    workflow: Mapping[str, Any],
    *,
    include_file_ids: list[str] | None = None,
    include_skill_ids: list[str] | None = None,
    created_at: str | None = None,
) -> bytes:
    sanitized = sanitize_workflow(workflow)
    # Build dependency descriptors before sanitization so source-grant
    # presence and source model hints remain visible without exporting their
    # IDs, paths, credentials, or runtime configuration.
    dependencies = collect_dependencies(workflow)
    source_models = {_row_id(row): row for row in _list_model_rows() if _row_id(row)}
    for dependency in dependencies["models"]:
        source_ref = str(dependency.get("model_ref") or "")
        source_row = source_models.get(source_ref)
        if source_row is not None:
            dependency["model"] = str(source_row.get("model") or dependency.get("model") or "")
            dependency["alias"] = str(source_row.get("alias") or dependency.get("alias") or dependency.get("model") or "")
            dependency["default_effort"] = str(source_row.get("default_effort") or "")
            dependency["effort"] = str(dependency.get("effort") or source_row.get("default_effort") or "")
            dependency["source"] = str(source_row.get("source") or "")
        elif not source_ref:
            dependency["agent_default"] = True
    file_selection = {str(item).strip() for item in (include_file_ids or []) if str(item).strip()}
    skill_selection = {str(item).strip() for item in (include_skill_ids or []) if str(item).strip()}
    attachment_ids = {item["source_id"] for item in dependencies["attachments"]}
    skill_ids = {item["source_id"] for item in dependencies["skills"]}
    if not file_selection.issubset(attachment_ids):
        raise PortablePackageError("include_file_ids contains an attachment not used by the workflow")
    if not skill_selection.issubset(skill_ids):
        raise PortablePackageError("include_skill_ids contains a Skill not used by the workflow")

    file_rows = {_row_id(row): row for row in _list_file_rows() if _row_id(row)}
    skill_rows = {_row_id(row): row for row in _list_skill_rows() if _row_id(row)}
    payloads: dict[str, tuple[bytes, str]] = {}
    payload_modes: dict[str, int] = {}
    payload_total = 0

    def add_payload(path: str, content: bytes, kind: str, mode: int = 0o644) -> None:
        nonlocal payload_total
        _validate_archive_path(path)
        if len(content) > PORTABLE_MAX_MEMBER_BYTES:
            raise PortablePackageError(f"portable payload exceeds the member limit: {path}")
        existing = payloads.get(path)
        if existing is not None:
            if existing[0] != content or existing[1] != kind or (kind == "skill" and payload_modes.get(path, 0o644) != (int(mode) & 0o777)):
                raise PortablePackageError(f"portable payload path collision: {path}")
            return
        if len(payloads) >= PORTABLE_MAX_FILES:
            raise PortablePackageError("portable export contains too many payload files")
        next_total = payload_total + len(content)
        # Reserve the maximum manifest size while collecting payloads.  This
        # makes the incremental guard safe before the manifest is assembled.
        if next_total + PORTABLE_MAX_MANIFEST_BYTES > PORTABLE_MAX_TOTAL_BYTES:
            raise PortablePackageError("portable export expands beyond the total size limit")
        payloads[path] = (content, kind)
        payload_modes[path] = int(mode) & 0o777
        payload_total = next_total

    attachments: list[dict[str, Any]] = []
    for reference in dependencies["attachments"]:
        source_id = reference["source_id"]
        row = file_rows.get(source_id)
        if row is None:
            raise PortablePackageError(f"Workflow references missing local attachment: {source_id}")
        # Stat and bound the file before reading it into the export buffer.
        content = _read_file(row, max_bytes=PORTABLE_MAX_MEMBER_BYTES)
        digest = _sha256_bytes(content)
        expected = str(row.get("sha256") or source_id).lower()
        if not _SHA256_RE.fullmatch(expected) or digest != expected:
            raise PortablePackageError(f"Attachment content hash changed: {source_id}")
        descriptor = {
            "source_id": source_id,
            "sha256": digest,
            "size": len(content),
            "display_name": str(row.get("display_name") or source_id)[:512],
            "mime": str(row.get("mime") or "application/octet-stream")[:160],
            "included": source_id in file_selection,
            "archive_path": None,
            "references": reference["references"],
        }
        if source_id in file_selection:
            archive_path = f"attachments/{digest}/{_archive_leaf(row.get('display_name'), source_id)}"
            if archive_path in payloads:
                raise PortablePackageError("Attachment archive path collision")
            descriptor["archive_path"] = archive_path
            add_payload(archive_path, content, "attachment")
        attachments.append(descriptor)

    skills: list[dict[str, Any]] = []
    for reference in dependencies["skills"]:
        source_id = reference["source_id"]
        row = skill_rows.get(source_id)
        if row is None:
            raise PortablePackageError(f"Workflow references missing local Skill: {source_id}")
        root = _skill_root(row)
        digest, files = _snapshot_skill(root)
        expected = str(row.get("snapshot_hash") or "").lower()
        if not _SHA256_RE.fullmatch(expected) or digest != expected:
            raise PortablePackageError(f"Skill snapshot changed: {source_id}")
        descriptor = {
            "source_id": source_id,
            "name": str(row.get("name") or source_id)[:128],
            "description": str(row.get("description") or "")[:2048],
            "snapshot_hash": digest,
            "file_count": len(files),
            "byte_count": sum(len(content) for _, content, _mode in files),
            "declarations": _skill_declarations(row.get("metadata"), skill_id=source_id),
            "included": source_id in skill_selection,
            "files": [],
            "references": reference["references"],
        }
        if source_id in skill_selection:
            for relative, content, mode in files:
                archive_path = f"skills/{digest}/{relative}"
                _validate_archive_path(archive_path)
                descriptor["files"].append(
                    {
                        "relative_path": relative,
                        "sha256": _sha256_bytes(content),
                        "size": len(content),
                        "mode": mode & 0o777,
                        "archive_path": archive_path,
                    }
                )
                add_payload(archive_path, content, "skill", mode)
        skills.append(descriptor)

    mcp_rows = {_row_id(row): row for row in _list_mcp_rows() if _row_id(row)}
    mcps: list[dict[str, Any]] = []
    for reference in dependencies["mcps"]:
        source_id = reference["source_id"]
        row = mcp_rows.get(source_id)
        if row is None:
            raise PortablePackageError(f"Workflow references missing imported MCP: {source_id}")
        mcps.append(
            {
                "source_id": source_id,
                "name": str(row.get("name") or row.get("label") or source_id)[:240],
                "transport": str(row.get("transport") or "unknown"),
                "references": reference["references"],
            }
        )

    manifest: dict[str, Any] = {
        "format": PORTABLE_FORMAT,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "workflow": {"path": "workflow.json"},
        "attachments": attachments,
        "skills": skills,
        "dependencies": {
            "models": dependencies["models"],
            "mcps": mcps,
            "outputs": dependencies["outputs"],
            "skills": [
                {
                    "source_id": item["source_id"],
                    "name": item["name"],
                    "snapshot_hash": item["snapshot_hash"],
                    "declarations": item["declarations"],
                    "references": item["references"],
                }
                for item in skills
            ],
        },
        "selection": {
            "attachments_included": bool(file_selection),
            "skills_included": bool(skill_selection),
        },
    }
    workflow_bytes = json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    if len(workflow_bytes) > PORTABLE_MAX_WORKFLOW_BYTES:
        raise PortablePackageError("workflow.json exceeds the portable workflow limit")
    add_payload("workflow.json", workflow_bytes, "workflow")
    files_manifest: dict[str, Any] = {}
    for path, (content, kind) in sorted(payloads.items()):
        _validate_archive_path(path)
        files_manifest[path] = {
            "sha256": _sha256_bytes(content),
            "size": len(content),
            "kind": kind,
            "mode": int(payload_modes.get(path, 0o644)) & 0o777,
        }
    manifest["files"] = files_manifest
    manifest["workflow"].update(files_manifest["workflow.json"])
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    if len(manifest_bytes) > PORTABLE_MAX_MANIFEST_BYTES:
        raise PortablePackageError("manifest.json exceeds the portable package limit")
    if len(payloads) > PORTABLE_MAX_FILES:
        raise PortablePackageError("portable export contains too many payload files")
    expanded_total = len(manifest_bytes) + sum(len(content) for content, _kind in payloads.values())
    if expanded_total > PORTABLE_MAX_TOTAL_BYTES:
        raise PortablePackageError("portable export expands beyond the total size limit")

    output = io.BytesIO()
    # Store generated members without compression.  The export guard is based
    # on bounded expanded bytes, and highly-compressible text must remain a
    # valid package rather than being rejected by a ratio heuristic on import.
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        for path, (content, _kind) in sorted(payloads.items()):
            info = zipfile.ZipInfo(path)
            info.compress_type = zipfile.ZIP_STORED
            mode = int(files_manifest[path].get("mode") or 0o644) & 0o777
            info.external_attr = ((0o100000 | mode) & 0xFFFF) << 16
            archive.writestr(info, content)
    result = output.getvalue()
    if len(result) > PORTABLE_MAX_ARCHIVE_BYTES:
        raise PortablePackageError("portable ZIP exceeds the archive limit")
    return result


def _check_member(member: zipfile.ZipInfo) -> str:
    name = _validate_archive_path(member.filename)
    if member.is_dir() or member.filename.endswith("/"):
        raise PortablePackageError("directory entries are not allowed in a portable package")
    if member.flag_bits & 0x1:
        raise PortablePackageError("encrypted ZIP entries are not allowed")
    unix_mode = (member.external_attr >> 16) & 0xFFFF
    if unix_mode & 0o170000 == 0o120000:
        raise PortablePackageError("ZIP symlinks are not allowed")
    if member.file_size > PORTABLE_MAX_MEMBER_BYTES:
        raise PortablePackageError("ZIP member exceeds the portable member limit")
    if member.file_size and member.compress_size == 0:
        raise PortablePackageError("ZIP member has an invalid compression size")
    if member.file_size > 1_000_000 and member.file_size / max(member.compress_size, 1) > 1_000:
        raise PortablePackageError("ZIP compression ratio is unsafe")
    return name


def _read_member(archive: zipfile.ZipFile, member: zipfile.ZipInfo, target: Path | None = None) -> bytes:
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    count = 0
    with archive.open(member, "r") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > PORTABLE_MAX_MEMBER_BYTES:
                raise PortablePackageError("ZIP member exceeds the portable member limit")
            digest.update(chunk)
            chunks.append(chunk)
    if count != member.file_size:
        raise PortablePackageError(f"ZIP member size mismatch: {member.filename}")
    content = b"".join(chunks)
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return content


def _validate_manifest_value(value: Any, *, key: str = "") -> None:
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            lower = str(child_key).lower()
            if lower in _PATH_KEYS and isinstance(child_value, str):
                if child_value.startswith("/") or "\\" in child_value or re.match(r"^[A-Za-z]:", child_value):
                    raise PortablePackageError("manifest contains an absolute or Windows path")
            _validate_manifest_value(child_value, key=str(child_key))
    elif isinstance(value, list):
        for item in value:
            _validate_manifest_value(item, key=key)


def _manifest_and_members(archive: zipfile.ZipFile) -> tuple[dict[str, Any], dict[str, zipfile.ZipInfo]]:
    members = archive.infolist()
    if not members or len(members) > PORTABLE_MAX_FILES + 1:
        raise PortablePackageError("portable ZIP contains too many entries")
    seen: set[str] = set()
    seen_casefold: dict[str, str] = {}
    indexed: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for member in members:
        name = _check_member(member)
        if name in seen:
            raise PortablePackageError(f"duplicate ZIP entry: {name}")
        folded = name.casefold()
        if folded in seen_casefold and seen_casefold[folded] != name:
            raise PortablePackageError("ZIP contains paths that collide by case")
        for ancestor in PurePosixPath(name).parents:
            ancestor_name = ancestor.as_posix()
            if ancestor_name != "." and ancestor_name in seen:
                raise PortablePackageError("ZIP contains a file/directory path collision")
        if any(existing.startswith(name + "/") for existing in seen):
            raise PortablePackageError("ZIP contains a file/directory path collision")
        seen.add(name)
        seen_casefold[folded] = name
        indexed[name] = member
        total += member.file_size
        if total > PORTABLE_MAX_TOTAL_BYTES:
            raise PortablePackageError("portable ZIP expands beyond the total size limit")
    manifest_member = indexed.get("manifest.json")
    if manifest_member is None or manifest_member.file_size > PORTABLE_MAX_MANIFEST_BYTES:
        raise PortablePackageError("portable ZIP must contain a small manifest.json")
    try:
        manifest = json.loads(_read_member(archive, manifest_member).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PortablePackageError("manifest.json is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != PORTABLE_FORMAT:
        raise PortablePackageError("unsupported portable package format")
    _validate_manifest_value(manifest)
    files = manifest.get("files")
    if not isinstance(files, dict) or "workflow.json" not in files:
        raise PortablePackageError("manifest.files must list workflow.json")
    expected: set[str] = set()
    for raw_path, entry in files.items():
        path = _validate_archive_path(raw_path)
        if path in {"manifest.json", "preview.json"} or path in expected:
            raise PortablePackageError("manifest contains a duplicate or reserved file")
        if not isinstance(entry, Mapping) or not _SHA256_RE.fullmatch(str(entry.get("sha256") or "")):
            raise PortablePackageError(f"manifest file digest is invalid: {path}")
        try:
            size = int(entry.get("size"))
        except (TypeError, ValueError) as exc:
            raise PortablePackageError(f"manifest file size is invalid: {path}") from exc
        if size < 0 or size > PORTABLE_MAX_MEMBER_BYTES:
            raise PortablePackageError(f"manifest file size is unsafe: {path}")
        expected.add(path)
    if set(indexed) != expected | {"manifest.json"}:
        raise PortablePackageError("ZIP entries do not exactly match manifest.files")
    return manifest, indexed


def _validate_payloads(
    archive: zipfile.ZipFile,
    manifest: Mapping[str, Any],
    indexed: Mapping[str, zipfile.ZipInfo],
    stage: Path,
) -> dict[str, Any]:
    files = manifest["files"]
    for path, raw_entry in files.items():
        entry = _mapping(raw_entry)
        member = indexed[path]
        if int(entry["size"]) != member.file_size:
            raise PortablePackageError(f"manifest size mismatch: {path}")
        content = _read_member(archive, member)
        if _sha256_bytes(content) != str(entry["sha256"]):
            raise PortablePackageError(f"manifest digest mismatch: {path}")
        target = stage / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if any(parent.is_symlink() for parent in [target.parent, *target.parent.parents] if parent != stage and stage in parent.parents):
            raise PortablePackageError("portable preview extraction encountered a symlink")
        target.write_bytes(content)
        mode = _safe_mode(entry.get("mode"), kind=str(entry.get("kind") or ""))
        try:
            os.chmod(target, mode)
        except OSError as exc:
            raise PortablePackageError(f"portable preview could not apply file mode: {path}") from exc
    workflow_path = stage / "workflow.json"
    if workflow_path.stat().st_size > PORTABLE_MAX_WORKFLOW_BYTES:
        raise PortablePackageError("workflow.json exceeds the portable workflow limit")
    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PortablePackageError("workflow.json is not valid UTF-8 JSON") from exc
    if not isinstance(workflow, dict):
        raise PortablePackageError("workflow.json must contain an object")
    return workflow


def _verify_stage(stage: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if stage.is_symlink() or not stage.is_dir():
        raise PortablePackageError("portable preview root is unsafe")
    manifest_path = stage / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise PortablePackageError("portable preview is missing manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PortablePackageError("portable preview manifest is invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != PORTABLE_FORMAT:
        raise PortablePackageError("portable preview format is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise PortablePackageError("portable preview manifest.files is invalid")
    for path in stage.rglob("*"):
        if path.is_symlink():
            raise PortablePackageError("portable preview contains a symlink")
    expected = {"manifest.json", *files.keys()}
    actual = set()
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(stage).as_posix()
        if relative != "preview.json":
            actual.add(relative)
    if actual != expected:
        raise PortablePackageError("portable preview contains unexpected or missing files")
    for path, raw_entry in files.items():
        _validate_archive_path(path)
        entry = _mapping(raw_entry)
        target = stage / path
        if target.is_symlink() or not target.is_file():
            raise PortablePackageError(f"portable preview payload is not a regular file: {path}")
        content = target.read_bytes()
        if len(content) != int(entry.get("size", -1)) or _sha256_bytes(content) != str(entry.get("sha256") or ""):
            raise PortablePackageError(f"portable preview digest mismatch: {path}")
    try:
        workflow = json.loads((stage / "workflow.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PortablePackageError("portable preview workflow is invalid") from exc
    if not isinstance(workflow, dict):
        raise PortablePackageError("portable preview workflow must be an object")
    return manifest, workflow


def _safe_mode(value: Any, *, kind: str) -> int:
    try:
        mode = int(value)
    except (TypeError, ValueError) as exc:
        raise PortablePackageError("portable file mode is invalid") from exc
    if mode < 0 or mode & ~0o777:
        raise PortablePackageError("portable file mode contains special permission bits")
    if kind != "skill" and mode & 0o111:
        raise PortablePackageError("only Skill files may carry executable bits")
    return mode


def _manifest_size(value: Any, label: str) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError) as exc:
        raise PortablePackageError(f"manifest size is invalid: {label}") from exc
    if size < 0 or size > PORTABLE_MAX_MEMBER_BYTES:
        raise PortablePackageError(f"manifest size is unsafe: {label}")
    return size


def _validate_manifest_structure(manifest: Mapping[str, Any], workflow: Mapping[str, Any]) -> None:
    """Require the manifest to describe exactly the recursive workflow refs."""

    actual = collect_dependencies(workflow)
    attachments = manifest.get("attachments")
    skills = manifest.get("skills")
    dependencies = _mapping(manifest.get("dependencies"))
    mcps = dependencies.get("mcps")
    models = dependencies.get("models")
    outputs = dependencies.get("outputs")
    dependency_skills = dependencies.get("skills")
    if not all(isinstance(value, list) for value in (attachments, skills, mcps, models, outputs, dependency_skills)):
        raise PortablePackageError("manifest resource lists are invalid")

    def unique_ids(items: list[Any], field: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for raw in items:
            item = _mapping(raw)
            value = str(item.get(field) or "")
            if not value or value in result:
                raise PortablePackageError(f"manifest contains duplicate or empty {field}")
            result[value] = item
        return result

    manifest_files = _mapping(manifest.get("files"))
    referenced_payloads: set[str] = set()
    workflow_descriptor = _mapping(manifest.get("workflow"))
    workflow_entry = _mapping(manifest_files.get("workflow.json"))
    if workflow_descriptor.get("path") != "workflow.json":
        raise PortablePackageError("manifest.workflow must point to workflow.json")
    if workflow_descriptor.get("sha256") != workflow_entry.get("sha256") or _manifest_size(workflow_descriptor.get("size"), "workflow") != _manifest_size(workflow_entry.get("size"), "workflow.json"):
        raise PortablePackageError("manifest.workflow digest does not match workflow.json")
    attachment_map = unique_ids(attachments, "source_id")
    expected_attachment_ids = {item["source_id"] for item in actual["attachments"]}
    if set(attachment_map) != expected_attachment_ids:
        raise PortablePackageError("manifest attachments do not exactly match workflow references")
    for source_id, descriptor in attachment_map.items():
        actual_item = next(item for item in actual["attachments"] if item["source_id"] == source_id)
        if descriptor.get("references") != actual_item.get("references"):
            raise PortablePackageError(f"attachment references do not match workflow: {source_id}")
        if not _SHA256_RE.fullmatch(str(descriptor.get("sha256") or "")):
            raise PortablePackageError(f"attachment hash is invalid: {source_id}")
        _manifest_size(descriptor.get("size"), source_id)
        included = bool(descriptor.get("included"))
        archive_path = descriptor.get("archive_path")
        if not included:
            if archive_path not in (None, ""):
                raise PortablePackageError(f"non-included attachment has a payload path: {source_id}")
            continue
        path = _validate_archive_path(archive_path)
        referenced_payloads.add(path)
        entry = _mapping(manifest_files.get(path))
        if entry.get("kind") != "attachment" or entry.get("sha256") != descriptor.get("sha256") or _manifest_size(entry.get("size"), path) != _manifest_size(descriptor.get("size"), source_id):
            raise PortablePackageError(f"attachment payload descriptor is inconsistent: {source_id}")

    skill_map = unique_ids(skills, "source_id")
    expected_skill_ids = {item["source_id"] for item in actual["skills"]}
    if set(skill_map) != expected_skill_ids:
        raise PortablePackageError("manifest Skills do not exactly match workflow references")
    seen_skill_payloads: dict[str, tuple[str, int, int]] = {}
    for source_id, descriptor in skill_map.items():
        actual_item = next(item for item in actual["skills"] if item["source_id"] == source_id)
        if descriptor.get("references") != actual_item.get("references"):
            raise PortablePackageError(f"Skill references do not match workflow: {source_id}")
        digest = str(descriptor.get("snapshot_hash") or "")
        if not _SHA256_RE.fullmatch(digest):
            raise PortablePackageError(f"Skill snapshot hash is invalid: {source_id}")
        included = bool(descriptor.get("included"))
        files = descriptor.get("files")
        if not isinstance(files, list):
            raise PortablePackageError(f"Skill file list is invalid: {source_id}")
        if not included and files:
            raise PortablePackageError(f"non-included Skill has payload files: {source_id}")
        descriptor_paths: set[str] = set()
        for raw_file in files:
            item = _mapping(raw_file)
            path = _validate_archive_path(item.get("archive_path"))
            if path in descriptor_paths:
                raise PortablePackageError(f"Skill descriptor repeats a payload: {source_id}")
            descriptor_paths.add(path)
            referenced_payloads.add(path)
            if not path.startswith(f"skills/{digest}/"):
                raise PortablePackageError(f"Skill payload path does not match its snapshot: {source_id}")
            entry = _mapping(manifest_files.get(path))
            if entry.get("kind") != "skill" or entry.get("sha256") != item.get("sha256") or _manifest_size(entry.get("size"), path) != _manifest_size(item.get("size"), source_id):
                raise PortablePackageError(f"Skill payload descriptor is inconsistent: {source_id}")
            mode = _safe_mode(item.get("mode"), kind="skill")
            identity = (str(item.get("sha256")), _manifest_size(item.get("size"), source_id), mode)
            previous = seen_skill_payloads.get(path)
            if previous is not None and previous != identity:
                raise PortablePackageError(f"shared Skill payload differs between descriptors: {path}")
            seen_skill_payloads[path] = identity

    mcp_map = unique_ids(mcps, "source_id")
    expected_mcp_ids = {item["source_id"] for item in actual["mcps"]}
    if set(mcp_map) != expected_mcp_ids:
        raise PortablePackageError("manifest MCPs do not exactly match workflow references")
    for source_id, descriptor in mcp_map.items():
        actual_item = next(item for item in actual["mcps"] if item["source_id"] == source_id)
        if descriptor.get("references") != actual_item.get("references"):
            raise PortablePackageError(f"MCP references do not match workflow: {source_id}")
    dependency_skill_map = unique_ids(dependency_skills, "source_id")
    if set(dependency_skill_map) != expected_skill_ids:
        raise PortablePackageError("manifest Skill dependency declarations are incomplete or stale")
    for source_id, descriptor in skill_map.items():
        dependency = dependency_skill_map[source_id]
        if dependency.get("snapshot_hash") != descriptor.get("snapshot_hash") or dependency.get("declarations") != descriptor.get("declarations"):
            raise PortablePackageError(f"Skill dependency declaration mismatch: {source_id}")

    model_map = unique_ids(models, "key")
    expected_model_keys = {item["key"] for item in actual["models"]}
    if set(model_map) != expected_model_keys:
        raise PortablePackageError("manifest analyzer dependencies do not exactly match workflow analyzers")
    output_map = unique_ids(outputs, "key")
    expected_output_keys = {item["key"] for item in actual["outputs"]}
    if set(output_map) != expected_output_keys:
        raise PortablePackageError("manifest output dependencies do not exactly match workflow outputs")

    for path, raw_entry in manifest_files.items():
        _validate_archive_path(path)
        entry = _mapping(raw_entry)
        kind = str(entry.get("kind") or "")
        if kind not in {"workflow", "attachment", "skill"}:
            raise PortablePackageError(f"manifest file kind is invalid: {path}")
        _safe_mode(entry.get("mode"), kind=kind)
        if kind == "workflow" and path != "workflow.json":
            raise PortablePackageError("only workflow.json may have kind=workflow")
    if set(manifest_files) != {"workflow.json", *referenced_payloads}:
        raise PortablePackageError("manifest contains unreferenced or missing payload files")


def _candidate_files(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = {_row_id(row): row for row in _list_file_rows() if _row_id(row)}
    result: list[dict[str, Any]] = []
    for item in manifest.get("attachments", []):
        descriptor = _mapping(item)
        expected = str(descriptor.get("sha256") or "")
        candidates: list[dict[str, Any]] = []
        for source_id, row in rows.items():
            if str(row.get("sha256") or "").lower() != expected:
                continue
            try:
                content = _read_file(row)
            except Exception:
                continue
            if _sha256_bytes(content) != expected or len(content) != _manifest_size(descriptor.get("size"), str(descriptor.get("source_id") or source_id)):
                continue
            candidates.append(
                {
                    "id": source_id,
                    "display_name": str(row.get("display_name") or source_id),
                    "size": len(content),
                    "sha256": expected,
                }
            )
        result.append(
            {
                **{key: descriptor.get(key) for key in ("source_id", "sha256", "size", "display_name", "mime", "included", "references")},
                "candidates": candidates,
                "status": "matched" if candidates else "carried" if descriptor.get("included") else "missing",
            }
        )
    return result


def _candidate_skills(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = {_row_id(row): row for row in _list_skill_rows() if _row_id(row)}
    result: list[dict[str, Any]] = []
    for item in manifest.get("skills", []):
        descriptor = _mapping(item)
        expected = str(descriptor.get("snapshot_hash") or "")
        candidates: list[dict[str, Any]] = []
        for target_id, row in rows.items():
            if str(row.get("snapshot_hash") or "").lower() != expected:
                continue
            try:
                digest, _files = _snapshot_skill(_skill_root(row))
            except Exception:
                continue
            if digest != expected:
                continue
            candidates.append({"id": target_id, "name": str(row.get("name") or target_id), "snapshot_hash": expected})
        result.append(
            {
                **{key: descriptor.get(key) for key in ("source_id", "name", "description", "snapshot_hash", "file_count", "byte_count", "declarations", "included", "references")},
                "candidates": candidates,
                "status": "matched" if candidates else "carried" if descriptor.get("included") else "missing",
            }
        )
    return result


def _candidate_models(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    models = [_public_model(row) for row in _list_model_rows() if _row_id(row)]
    return [
        {
            **{key: item.get(key) for key in ("key", "node_path", "node_name", "agent_id", "model_ref", "model", "alias", "effort", "default_effort", "agent_default", "required")},
            "candidates": models,
            "status": "requires_explicit_target_model" if not models else "unbound",
        }
        for item in manifest.get("dependencies", {}).get("models", [])
    ]


def _candidate_mcps(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    mcps = [_public_mcp(row) for row in _list_mcp_rows() if _row_id(row)]
    return [
        {
            **{key: item.get(key) for key in ("source_id", "name", "transport", "references")},
            "candidates": mcps,
            "status": "unbound" if mcps else "missing",
        }
        for item in manifest.get("dependencies", {}).get("mcps", [])
    ]


def _candidate_outputs(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    grants = [{"mode": "default", "id": "default", "name": "目标设备默认 output", "active": True}]
    grants.extend({"mode": "grant", **_public_grant(row)} for row in _list_grant_rows())
    return [
        {
            **{key: item.get(key) for key in ("key", "node_path", "node_name", "source_has_grant", "required")},
            "candidates": grants,
            "status": "requires_explicit_output_target",
        }
        for item in manifest.get("dependencies", {}).get("outputs", [])
    ]


def cleanup_expired_previews(preview_root: Path, *, now: float | None = None) -> None:
    current = time.time() if now is None else now
    preview_root = Path(preview_root)
    if preview_root.is_symlink() or not preview_root.is_dir():
        return
    for directory in preview_root.iterdir():
        if directory.is_symlink() or not directory.is_dir() or not re.fullmatch(r"[a-f0-9]{32}", directory.name):
            continue
        metadata_path = directory / "preview.json"
        try:
            expires_at = float(json.loads(metadata_path.read_text(encoding="utf-8")).get("expires_at", 0))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            expires_at = 0
        if expires_at <= current:
            shutil.rmtree(directory, ignore_errors=True)


def preview_package(
    content: bytes,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    if len(content) > PORTABLE_MAX_ARCHIVE_BYTES:
        raise PortablePackageError("portable ZIP exceeds the archive limit")
    current = time.time() if now is None else now
    preview_root = _preview_root()
    if preview_root.is_symlink():
        raise PortablePackageError("portable preview root is a symlink")
    cleanup_expired_previews(preview_root, now=current)
    preview_root = Path(preview_root)
    preview_root.mkdir(parents=True, exist_ok=True)
    preview_id = uuid.uuid4().hex
    stage = preview_root / preview_id
    stage.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            manifest, indexed = _manifest_and_members(archive)
            workflow = _validate_payloads(archive, manifest, indexed, stage)
        _validate_manifest_structure(manifest, workflow)
        validation = dict(_app().validate_workflow(workflow))
        if not validation.get("ok"):
            raise PortablePackageError("workflow.json failed kxy validation: " + "; ".join(str(item) for item in validation.get("errors", []))[:1000])
        expires_at = current + PORTABLE_PREVIEW_TTL_SECONDS
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        (stage / "preview.json").write_text(json.dumps({"preview_id": preview_id, "expires_at": expires_at}, ensure_ascii=False), encoding="utf-8")
        dependencies = _mapping(manifest.get("dependencies"))
        return {
            "preview_id": preview_id,
            "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
            "format": PORTABLE_FORMAT,
            "workflow": {
                "name": str(workflow.get("name") or "未命名研究流程"),
                "version": str(workflow.get("version") or ""),
                "nodes": len(workflow.get("nodes", [])) if isinstance(workflow.get("nodes"), list) else 0,
                "edges": len(workflow.get("edges", [])) if isinstance(workflow.get("edges"), list) else 0,
            },
            "manifest": manifest,
            "validation": validation,
            "resources": {
                "attachments": _candidate_files(manifest),
                "skills": _candidate_skills(manifest),
            },
            "dependencies": {
                "models": _candidate_models(manifest),
                "mcps": _candidate_mcps(manifest),
                "outputs": _candidate_outputs(manifest),
            },
        }
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def _load_preview(preview_root: Path, preview_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if not re.fullmatch(r"[a-f0-9]{32}", str(preview_id or "")):
        raise PortablePackageError("preview_id is invalid")
    stage = Path(preview_root) / str(preview_id)
    metadata_path = stage / "preview.json"
    if stage.is_symlink() or not stage.is_dir() or not metadata_path.is_file():
        raise PortablePreviewExpired("portable preview is missing or expired")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        expires_at = float(metadata["expires_at"])
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise PortablePreviewExpired("portable preview metadata is invalid") from exc
    if expires_at <= time.time():
        shutil.rmtree(stage, ignore_errors=True)
        raise PortablePreviewExpired("portable preview has expired")
    manifest, workflow = _verify_stage(stage)
    return stage, manifest, workflow


def _binding_map(bindings: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    raw = bindings.get(key, {})
    if not isinstance(raw, Mapping):
        raise PortablePackageError(f"bindings.{key} must be an object")
    return raw


def _resource_binding_value(raw: Any, *, field: str) -> str:
    if isinstance(raw, str):
        value = raw.strip()
    elif isinstance(raw, Mapping):
        value = str(raw.get(field) or raw.get("id") or "").strip()
    else:
        value = ""
    return value


def _remap_workflow(
    document: Mapping[str, Any],
    *,
    file_map: Mapping[str, str],
    skill_map: Mapping[str, str],
    mcp_map: Mapping[str, str],
    model_map: Mapping[str, Mapping[str, Any]],
    output_map: Mapping[str, Mapping[str, Any]],
    root: bool = True,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(document))
    nodes = result.get("nodes")
    if not isinstance(nodes, list):
        raise PortablePackageError("workflow.nodes must be an array")
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or f"node-{index + 1}")
        prefix = () if root else ()
        # The caller passes model/output maps keyed by the same recursive path;
        # compute it below through the small recursive helper instead.
        _remap_node(node, node_id, prefix, file_map, skill_map, mcp_map, model_map, output_map)
    if root:
        result["id"] = uuid.uuid4().hex
    return result


def _remap_node(
    node: dict[str, Any],
    node_id: str,
    prefix: tuple[str, ...],
    file_map: Mapping[str, str],
    skill_map: Mapping[str, str],
    mcp_map: Mapping[str, str],
    model_map: Mapping[str, Mapping[str, Any]],
    output_map: Mapping[str, Mapping[str, Any]],
) -> None:
    node_path = "/".join((*prefix, node_id))
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    if isinstance(data.get("file_id"), str) and data["file_id"] in file_map:
        data["file_id"] = file_map[data["file_id"]]
    if isinstance(data.get("file_ids"), list):
        data["file_ids"] = [file_map.get(str(item), str(item)) for item in data["file_ids"]]
    if isinstance(data.get("attachments"), list):
        for item in data["attachments"]:
            if isinstance(item, dict) and isinstance(item.get("file_id"), str):
                item["file_id"] = file_map.get(item["file_id"], item["file_id"])
    if isinstance(data.get("skill_ids"), list):
        data["skill_ids"] = list(dict.fromkeys(skill_map.get(str(item), str(item)) for item in data["skill_ids"]))
    if isinstance(data.get("mcp_ids"), list):
        data["mcp_ids"] = list(dict.fromkeys(mcp_map.get(str(item), str(item)) for item in data["mcp_ids"]))
    if str(node.get("type") or data.get("kind") or "") == "analyzer":
        binding = model_map.get(node_path)
        if binding is None:
            raise PortablePackageError(f"missing target model binding for {node_path}")
        data["agent_id"] = binding["agent_id"]
        data["cli"] = binding["agent_id"]
        data["model_ref"] = binding["model_ref"]
        data["model"] = binding["model"]
        data["effort"] = binding.get("effort") or ""
        data.pop("variant", None)
    if str(node.get("type") or data.get("kind") or "") == "container":
        output = output_map.get(node_path)
        if output is None:
            raise PortablePackageError(f"missing target output binding for {node_path}")
        if output["mode"] == "default":
            data.pop("grant_id", None)
            data["portable_output_target"] = "default"
        else:
            data["grant_id"] = output["grant_id"]
            data.pop("portable_output_target", None)
    nested = data.get("workflow") if isinstance(data.get("workflow"), Mapping) else data.get("subflow")
    data.pop("subflow", None)
    if isinstance(nested, Mapping):
        nested_copy = copy.deepcopy(dict(nested))
        nested_nodes = nested_copy.get("nodes")
        if isinstance(nested_nodes, list):
            for index, child in enumerate(nested_nodes):
                if isinstance(child, dict):
                    child_id = str(child.get("id") or f"node-{index + 1}")
                    _remap_node(child, child_id, (*prefix, node_id), file_map, skill_map, mcp_map, model_map, output_map)
        data["workflow"] = nested_copy
    node["data"] = data


def _stage_payload(stage: Path, manifest: Mapping[str, Any], raw_path: Any, *, kind: str) -> bytes:
    path = _validate_archive_path(raw_path)
    entry = _mapping(_mapping(manifest.get("files")).get(path))
    if entry.get("kind") != kind:
        raise PortablePackageError(f"portable payload kind mismatch: {path}")
    target = stage / path
    try:
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise PortablePackageError(f"portable payload is missing: {path}") from exc
    if resolved.is_symlink() or not resolved.is_file() or not _app().resolved_inside(resolved, stage):
        raise PortablePackageError(f"portable payload leaves its preview root: {path}")
    content = resolved.read_bytes()
    if len(content) != int(entry.get("size", -1)) or _sha256_bytes(content) != str(entry.get("sha256") or ""):
        raise PortablePackageError(f"portable payload digest mismatch: {path}")
    return content


def _stage_skill_root(stage: Path, manifest: Mapping[str, Any], digest: str) -> Path:
    if not _SHA256_RE.fullmatch(digest):
        raise PortablePackageError("Skill snapshot hash is invalid")
    prefix = f"skills/{digest}/"
    paths: list[str] = []
    for raw_skill in manifest.get("skills", []):
        skill = _mapping(raw_skill)
        if str(skill.get("snapshot_hash") or "") != digest:
            continue
        for raw_file in skill.get("files", []):
            paths.append(str(_mapping(raw_file).get("archive_path") or ""))
    if not paths or any(not path.startswith(prefix) for path in paths):
        raise PortablePackageError("Skill package payload is incomplete")
    root = (stage / "skills" / digest).resolve()
    if not _app().resolved_inside(root, stage) or root.is_symlink() or not root.is_dir():
        raise PortablePackageError("Skill package root is unsafe")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise PortablePackageError("Skill package contains a symlink")
    return root


def commit_package(preview_id: str, bindings: Mapping[str, Any]) -> dict[str, Any]:
    stage, manifest, workflow = _load_preview(_preview_root(), preview_id)
    if not isinstance(bindings, Mapping):
        raise PortablePackageError("bindings must be an object")
    _validate_manifest_structure(manifest, workflow)
    dependencies = _mapping(manifest.get("dependencies"))
    file_bindings = _binding_map(bindings, "files")
    skill_bindings = _binding_map(bindings, "skills")
    model_bindings = _binding_map(bindings, "models")
    mcp_bindings = _binding_map(bindings, "mcps")
    output_bindings = _binding_map(bindings, "outputs")

    target_files = {_row_id(row): row for row in _list_file_rows() if _row_id(row)}
    target_skills = {_row_id(row): row for row in _list_skill_rows() if _row_id(row)}
    target_models = {_row_id(row): row for row in _list_model_rows() if _row_id(row)}
    target_mcps = {_row_id(row): row for row in _list_mcp_rows() if _row_id(row)}
    target_grants = {_row_id(row): row for row in _list_grant_rows() if _row_id(row)}

    # Validate every resource and every target binding before importing or
    # writing anything.  Package resources are represented by a plan entry;
    # actual creation happens only after model/MCP/output validation passes.
    file_plan: dict[str, tuple[str, bytes | None, str]] = {}
    for raw_item in manifest.get("attachments", []):
        descriptor = _mapping(raw_item)
        source_id = str(descriptor.get("source_id") or "")
        value = _resource_binding_value(file_bindings.get(source_id), field="file_id")
        expected = str(descriptor.get("sha256") or "")
        if value == "package":
            if not descriptor.get("included"):
                raise PortablePackageError(f"attachment {source_id} is not carried in the package")
            content = _stage_payload(stage, manifest, descriptor.get("archive_path"), kind="attachment")
            if _sha256_bytes(content) != expected:
                raise PortablePackageError(f"carried attachment changed: {source_id}")
            existing = None
            corrupt_existing = False
            for row in target_files.values():
                if str(row.get("sha256") or "") != expected:
                    continue
                try:
                    current = _read_file(row)
                    if _sha256_bytes(current) == expected and len(current) == int(descriptor.get("size", -1)):
                        existing = row
                        break
                    corrupt_existing = True
                except PortablePackageError:
                    corrupt_existing = True
            if existing is None and corrupt_existing:
                raise PortablePackageError(f"target attachment record has a damaged stored copy: {source_id}")
            file_plan[source_id] = ("existing", None, _row_id(existing)) if existing else ("package", content, "")
        elif value:
            row = target_files.get(value)
            if row is None:
                raise PortablePackageError(f"target attachment does not exist: {value}")
            content = _read_file(row)
            if _sha256_bytes(content) != expected:
                raise PortablePackageError(f"target attachment hash does not match: {source_id}")
            file_plan[source_id] = ("existing", None, value)
        else:
            raise PortablePackageError(f"attachment {source_id} requires an explicit target or package binding")

    skill_plan: dict[str, tuple[str, Path | None, str]] = {}
    skill_plan_by_digest: dict[str, str] = {}
    for raw_item in manifest.get("skills", []):
        descriptor = _mapping(raw_item)
        source_id = str(descriptor.get("source_id") or "")
        digest = str(descriptor.get("snapshot_hash") or "")
        value = _resource_binding_value(skill_bindings.get(source_id), field="skill_id")
        if value == "package":
            if not descriptor.get("included"):
                raise PortablePackageError(f"Skill {source_id} is not carried in the package")
            package_root = _stage_skill_root(stage, manifest, digest)
            actual, _files = _snapshot_skill(package_root)
            if actual != digest:
                raise PortablePackageError(f"carried Skill changed: {source_id}")
            existing = None
            corrupt_existing = False
            for row in target_skills.values():
                if str(row.get("snapshot_hash") or "") != digest:
                    continue
                try:
                    actual_target, _target_files = _snapshot_skill(_skill_root(row))
                    if actual_target == digest:
                        existing = row
                        break
                    corrupt_existing = True
                except PortablePackageError:
                    corrupt_existing = True
            if existing is None and corrupt_existing:
                raise PortablePackageError(f"target Skill record has a damaged snapshot: {source_id}")
            if existing:
                skill_plan[source_id] = ("existing", None, _row_id(existing))
            elif digest in skill_plan_by_digest:
                skill_plan[source_id] = ("planned", None, skill_plan_by_digest[digest])
            else:
                skill_plan[source_id] = ("package", package_root, "")
                skill_plan_by_digest[digest] = source_id
        elif value:
            row = target_skills.get(value)
            if row is None:
                raise PortablePackageError(f"target Skill does not exist: {value}")
            actual, _files = _snapshot_skill(_skill_root(row))
            if actual != digest:
                raise PortablePackageError(f"target Skill snapshot does not match: {source_id}")
            skill_plan[source_id] = ("existing", None, value)
        else:
            raise PortablePackageError(f"Skill {source_id} requires an explicit target or package binding")

    model_map: dict[str, Mapping[str, Any]] = {}
    for raw_item in dependencies.get("models", []):
        dependency = _mapping(raw_item)
        key = str(dependency.get("key") or dependency.get("node_path") or "")
        raw = model_bindings.get(key)
        target_ref = _resource_binding_value(raw, field="model_ref")
        if not target_ref or target_ref not in target_models:
            raise PortablePackageError(f"analyzer {key} requires an existing target model record; source Agent defaults are not auto-inherited")
        row = _mapping(target_models[target_ref])
        agent_id = str(row.get("agent_id") or row.get("cli_id") or "").strip().lower()
        model = str(row.get("model") or "").strip()
        if not agent_id or not model:
            raise PortablePackageError(f"target model record is incomplete: {target_ref}")
        if str(row.get("source") or "") == "api" and not bool(row.get("credential_exists")):
            raise PortablePackageError(f"target API model has no local credential binding: {target_ref}")
        efforts = row.get("efforts", [])
        if isinstance(efforts, str):
            try:
                efforts = json.loads(efforts)
            except json.JSONDecodeError:
                efforts = []
        efforts = [str(value) for value in efforts if isinstance(value, str)] if isinstance(efforts, list) else []
        requested_effort = str(raw.get("effort") or "").strip() if isinstance(raw, Mapping) else ""
        effort = requested_effort or str(row.get("default_effort") or "").strip()
        if effort and effort not in efforts:
            raise PortablePackageError(f"effort {effort!r} is not available on target model {target_ref}")
        model_map[key] = {
            "model_ref": target_ref,
            "agent_id": agent_id,
            "model": model,
            "alias": str(row.get("alias") or model),
            "effort": effort,
        }

    mcp_map: dict[str, str] = {}
    for raw_item in dependencies.get("mcps", []):
        descriptor = _mapping(raw_item)
        source_id = str(descriptor.get("source_id") or "")
        target_id = _resource_binding_value(mcp_bindings.get(source_id), field="mcp_id")
        target = target_mcps.get(target_id)
        if not target_id or target is None:
            raise PortablePackageError(f"MCP {source_id} requires an explicit existing target MCP binding")
        if target.get("supported") is False:
            raise PortablePackageError(f"target MCP is not supported: {target_id}")
        mcp_map[source_id] = target_id

    output_map: dict[str, Mapping[str, Any]] = {}
    for raw_item in dependencies.get("outputs", []):
        descriptor = _mapping(raw_item)
        key = str(descriptor.get("key") or descriptor.get("node_path") or "")
        raw = output_bindings.get(key)
        mode = str(raw.get("mode") or "") if isinstance(raw, Mapping) else str(raw or "")
        if mode == "default":
            output_map[key] = {"mode": "default"}
            continue
        grant_id = str(raw.get("grant_id") or raw.get("id") or "").strip() if isinstance(raw, Mapping) else mode.strip()
        grant = target_grants.get(grant_id)
        if grant is None or grant.get("revoked_at"):
            raise PortablePackageError(f"output {key} requires an active target grant or explicit default output")
        canonical = Path(str(grant.get("canonical_path") or ""))
        try:
            resolved = canonical.resolve(strict=True)
        except OSError as exc:
            raise PortablePackageError(f"target output grant is unavailable: {grant_id}") from exc
        if resolved != canonical or not resolved.is_dir():
            raise PortablePackageError(f"target output grant is not a canonical existing directory: {grant_id}")
        output_map[key] = {"mode": "grant", "grant_id": grant_id}

    # Validate final workflow shape with planned IDs before any resource write.
    planned_file_map = {source: value[2] or source for source, value in file_plan.items()}
    planned_skill_map = {source: value[2] or source for source, value in skill_plan.items()}
    planned_workflow = _remap_workflow(
        sanitize_workflow(workflow),
        file_map=planned_file_map,
        skill_map=planned_skill_map,
        mcp_map=mcp_map,
        model_map=model_map,
        output_map=output_map,
    )
    planned_validation = dict(_app().validate_workflow(planned_workflow))
    if not planned_validation.get("ok"):
        raise PortablePackageError("bound workflow failed kxy validation before resource import: " + "; ".join(str(item) for item in planned_validation.get("errors", []))[:1000])

    created_files: list[str] = []
    created_skills: list[str] = []
    try:
        file_map: dict[str, str] = {}
        for source_id, (kind, content, existing_id) in file_plan.items():
            if kind == "existing":
                file_map[source_id] = existing_id
                continue
            if content is None:
                raise PortablePackageError(f"attachment import plan is incomplete: {source_id}")
            imported = _app().store_file(str(next(item for item in manifest.get("attachments", []) if _mapping(item).get("source_id") == source_id).get("display_name") or source_id), content)
            target_id = _row_id(imported)
            if not target_id:
                raise PortablePackageError(f"imported attachment has no id: {source_id}")
            if target_id not in target_files:
                created_files.append(target_id)
            file_map[source_id] = target_id

        skill_map: dict[str, str] = {}
        imported_skill_by_source: dict[str, str] = {}
        for source_id, (kind, package_root, existing_id) in skill_plan.items():
            if kind in {"existing", "planned"}:
                skill_map[source_id] = existing_id or imported_skill_by_source.get(existing_id, existing_id)
                continue
            if package_root is None:
                raise PortablePackageError(f"Skill import plan is incomplete: {source_id}")
            imported = _app().import_skill_root(package_root)
            target_id = _row_id(imported)
            if not target_id:
                raise PortablePackageError(f"imported Skill has no id: {source_id}")
            package_descriptor = next(
                (_mapping(item) for item in manifest.get("skills", []) if _mapping(item).get("source_id") == source_id),
                {},
            )
            _persist_imported_skill_declarations(target_id, package_descriptor.get("declarations"))
            created_skills.append(target_id)
            imported_skill_by_source[source_id] = target_id
            skill_map[source_id] = target_id
        for source_id, (kind, _package_root, existing_id) in skill_plan.items():
            if kind == "planned":
                skill_map[source_id] = imported_skill_by_source.get(existing_id, existing_id)

        final_workflow = _remap_workflow(
            sanitize_workflow(workflow),
            file_map=file_map,
            skill_map=skill_map,
            mcp_map=mcp_map,
            model_map=model_map,
            output_map=output_map,
        )
        validation = dict(_app().validate_workflow(final_workflow))
        if not validation.get("ok"):
            raise PortablePackageError("bound workflow failed kxy validation: " + "; ".join(str(item) for item in validation.get("errors", []))[:1000])
        saved = _save_imported_workflow(final_workflow)
    except Exception:
        for skill_id in reversed(created_skills):
            _cleanup_created_skill(skill_id)
        for file_id in reversed(created_files):
            _cleanup_created_file(file_id)
        raise

    shutil.rmtree(stage, ignore_errors=True)
    return {
        "ok": True,
        "preview_id": preview_id,
        "workflow": saved,
        "bindings": {
            "attachments": file_map,
            "skills": skill_map,
            "models": {key: value["model_ref"] for key, value in model_map.items()},
            "mcps": mcp_map,
            "outputs": {key: value.get("grant_id") or "default" for key, value in output_map.items()},
        },
    }
