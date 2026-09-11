"""Opt-in real Codex + foreign Skill + selected MCP acceptance; synthetic inputs only."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix="kxy-v3-real-"))
os.environ.update(KXY_DATA_ROOT=str(ROOT / "data"), LANGFLOW_CONFIG_DIR=str(ROOT / "lfx"), DO_NOT_TRACK="true")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as core
from backend import agent_config as config
from fastapi.testclient import TestClient

SERVER = '''import json, os, sys
if os.environ.get("KXY_FIXTURE_TOKEN") != "SYNTHETIC_MCP_SECRET_941637":
 sys.exit("Synthetic MCP authentication missing")
for line in sys.stdin:
 try:
  q=json.loads(line); mid=q.get("id"); method=q.get("method")
  if mid is None: continue
  if method=="initialize": r={"protocolVersion":q.get("params",{}).get("protocolVersion","2024-11-05"),"capabilities":{"tools":{}},"serverInfo":{"name":"kxy-fixture","version":"1.0"}}
  elif method=="tools/list": r={"tools":[{"name":"kxy_fixture_marker","description":"Return the synthetic acceptance marker.","annotations":{"readOnlyHint":True,"destructiveHint":False,"idempotentHint":True,"openWorldHint":False},"inputSchema":{"type":"object","properties":{},"additionalProperties":False}}]}
  elif method=="tools/call": r={"content":[{"type":"text","text":"KXY_MCP_TOOL_CONFIRMED_7391"}],"isError":False}
  else: r={}
  print(json.dumps({"jsonrpc":"2.0","id":mid,"result":r}),flush=True)
 except Exception: pass
'''

def checked(response):
    response.raise_for_status()
    return response.json()

original_mcp_paths = config._mcp_native_paths
native_auth_before = {name: hashlib.sha256(p.read_bytes()).hexdigest() for name, p in {"config": Path.home() / ".codex/config.toml", "auth": Path.home() / ".codex/auth.json"}.items() if p.is_file()}
with TestClient(core.app) as client, patch.object(config, "_mcp_native_paths", side_effect=lambda agent: [ROOT / "fake-native-home/.workbuddy/mcp.json"] if agent == "workbuddy" else original_mcp_paths(agent)):
    skill_dir = ROOT / "foreign-skills" / "fixture-method"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: fixture-method\ndescription: Synthetic revenue method.\n---\nRead references/method.md and include its exact marker in the answer.\n")
    (skill_dir / "references/method.md").write_text("Revenue is not profit; margins are unknown. Marker: KXY_FOREIGN_REFERENCE_READ_8462\n")
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in skill_dir.rglob("*") if p.is_file()}
    checked(client.put("/api/agents/claude", json={"skill_roots": [str(skill_dir.parent)]}))
    imported = checked(client.post("/api/agents/claude/skills/import", json={"paths": [str(skill_dir)]}))
    assert not imported["errors"], imported
    skill = imported["imported"][0]
    server = ROOT / "synthetic MCP server.py"
    server.write_text(SERVER)
    native = ROOT / "fake-native-home"
    (native / ".workbuddy").mkdir(parents=True)
    native_config = native / ".workbuddy" / "mcp.json"
    native_config.write_text(json.dumps({"mcpServers": {"kxy_fixture": {"command": sys.executable, "args": [str(server)], "env": {"KXY_FIXTURE_TOKEN": "SYNTHETIC_MCP_SECRET_941637"}}}}))
    native_digest = hashlib.sha256(native_config.read_bytes()).hexdigest()
    with patch.object(config, "_home", return_value=native):
        mcps = checked(client.get("/api/agents/workbuddy/mcps"))
        assert len(mcps) == 1, mcps
        checked(client.post("/api/agents/workbuddy/mcps/import", json={"ids": [mcps[0]["id"]]}))
    asset = checked(client.post("/api/files", files={"file": ("synthetic-revenue.md", b"Company A revenue: 20 million in 2025. Company B: 12 million. Margins unknown.\n")}))
    export = ROOT / "export"
    export.mkdir()
    grant = checked(client.post("/api/grants", json={"path": str(export)}))
    workflow = {"version": "kxy.workflow.v1", "name": "V3 real cross-agent acceptance", "nodes": [
        {"id": "source", "type": "file", "data": {"file_id": asset["id"]}},
        {"id": "analysis", "type": "analyzer", "data": {"cli": "codex", "model": os.environ.get("KXY_SMOKE_MODEL", "gpt-5.4-mini"), "effort": "low", "network": True, "timeout": 180, "skill_ids": [skill["id"]], "mcp_ids": [mcps[0]["id"]], "prompt": "Use the selected Skill, reading its reference. Call the selected MCP tool kxy_fixture_marker. In two sentences summarize ONLY the attached revenue data and include the exact reference marker and exact MCP result. Write the same result into outputs/result.txt. Do not browse or inspect unrelated files."}},
        {"id": "output", "type": "container", "data": {"grant_id": grant["id"]}}
    ], "edges": [{"source": "source", "target": "analysis"}, {"source": "analysis", "target": "output"}]}
    run_id = checked(client.post("/api/runs", json={"workflow": workflow}))["id"]
    deadline = time.monotonic() + 210
    previous = None
    while time.monotonic() < deadline:
        run = checked(client.get("/api/runs/" + run_id))
        if run["status"] != previous:
            print(run_id, run["status"], flush=True)
            previous = run["status"]
        if run["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            break
        time.sleep(1)
    (ROOT / "evidence.json").write_text(json.dumps(run, ensure_ascii=False, indent=2))
    print("Evidence:", ROOT, flush=True)
    native_auth_after = {name: hashlib.sha256(p.read_bytes()).hexdigest() for name, p in {"config": Path.home() / ".codex/config.toml", "auth": Path.home() / ".codex/auth.json"}.items() if p.is_file()}
    (ROOT / "native-auth-integrity.json").write_text(json.dumps({"before": native_auth_before, "after": native_auth_after, "unchanged": native_auth_before == native_auth_after}, indent=2))
    assert native_auth_before == native_auth_after, "Native Codex config/auth changed"
    assert run["status"] == "succeeded", run.get("error")
    output = next(n for n in run["nodes"] if n["node_id"] == "output")["output"]
    artifact_text = "\n".join(p.read_text() for p in (ROOT / "data" / "runs" / run_id / "workspace" / "nodes" / "analysis" / "outputs").glob("*.txt"))
    for marker in ("KXY_MCP_TOOL_CONFIRMED_7391", "KXY_FOREIGN_REFERENCE_READ_8462", "20", "12"):
        assert marker in artifact_text, marker
    with core.connect_db() as db:
        events = [dict(row) for row in db.execute("SELECT * FROM run_events WHERE run_id=?", (run_id,))]
    tool_calls = []
    for event in events:
        payload = json.loads(event["payload"])
        try:
            item = json.loads(payload.get("text", "")).get("item", {})
        except (ValueError, TypeError):
            continue
        if item.get("type") == "mcp_tool_call" and item.get("tool") == "kxy_fixture_marker":
            tool_calls.append(item)
    assert any(c.get("status") == "completed" and "KXY_MCP_TOOL_CONFIRMED_7391" in json.dumps(c.get("result")) for c in tool_calls), "Missing completed MCP call with actual result"
    (ROOT / "events.json").write_text(json.dumps(events, ensure_ascii=False, indent=2))
    for item in run["output_manifest"]["artifacts"]:
        assert client.get(item["url"]).status_code == 200
    assert (export / "kxy" / run_id / "output" / "result.md").is_file()
    assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in skill_dir.rglob("*") if p.is_file()}
    assert native_digest == hashlib.sha256(native_config.read_bytes()).hexdigest()
    assert "skillhub" in json.dumps(run["snapshot"]).lower()
    assert "SYNTHETIC_MCP_SECRET_941637" not in json.dumps(run)
    assert b"SYNTHETIC_MCP_SECRET_941637" not in core.DB_PATH.read_bytes()
    for path in (ROOT / "data" / "runs" / run_id).rglob("*"):
        if path.is_file() and not path.is_symlink():
            assert b"SYNTHETIC_MCP_SECRET_941637" not in path.read_bytes(), str(path)
    print("PASS real Codex + foreign Skill reference + authenticated MCP call + output/download + immutable originals/native auth + no persisted secret", flush=True)
