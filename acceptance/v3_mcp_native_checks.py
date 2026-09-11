"""Real installed CLI config readers and local synthetic MCP; no model calls."""
import os,sys,json,tempfile,subprocess,shutil
from pathlib import Path
from unittest.mock import patch
root=Path(tempfile.mkdtemp(prefix="kxy-v3-generated-mcp-"))
os.environ["KXY_DATA_ROOT"]=str(root/"data")
os.environ["LANGFLOW_CONFIG_DIR"]=str(root/"lfx")
os.environ["DO_NOT_TRACK"]="true"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import app as core
from backend import agent_config as config
from fastapi.testclient import TestClient
native=root/"native"; (native/".workbuddy").mkdir(parents=True)
server=root/"synthetic MCP server.py"
server.write_text('import json,sys\nfor line in sys.stdin:\n try:\n  req=json.loads(line);method=req.get("method");rid=req.get("id")\n  if rid is None:continue\n  if method=="initialize":result={"protocolVersion":req.get("params",{}).get("protocolVersion","2024-11-05"),"capabilities":{"tools":{}},"serverInfo":{"name":"kxy-independent-fixture","version":"1.0"}}\n  elif method=="tools/list":result={"tools":[{"name":"kxy_fixture_marker","description":"Return the deterministic acceptance marker for this synthetic test.","inputSchema":{"type":"object","properties":{},"additionalProperties":False}}]}\n  elif method=="tools/call":result={"content":[{"type":"text","text":"KXY_MCP_TOOL_CONFIRMED_7391"}],"isError":False}\n  elif method=="ping":result={}\n  else:result={}\n  print(json.dumps({"jsonrpc":"2.0","id":rid,"result":result}),flush=True)\n except Exception:pass\n')
(native/".workbuddy/mcp.json").write_text(json.dumps({"mcpServers":{"kxy_fixture":{"command":sys.executable,"args":[str(server)]}}}))
with TestClient(core.app) as client:
 with patch.object(config,"_home",return_value=native):
  discovery=client.get("/api/agents/workbuddy/mcps");discovery.raise_for_status()
  imported=client.post("/api/agents/workbuddy/mcps/import",json={"ids":["kxy_fixture"]});imported.raise_for_status()
 result={}
 for agent in ["codex","opencode"]:
  workspace=root/"data"/"generated"/agent;workspace.mkdir(parents=True)
  generated=config.prepare_mcp_configuration(agent,["kxy_fixture"],workspace)
  cfg=Path(generated["path"])
  env={k:os.environ[k] for k in ["PATH","HOME","USER","LANG","SHELL"] if k in os.environ}
  if agent=="codex":
   ch=workspace/"codex-home";ch.mkdir();shutil.copy2(cfg,ch/"config.toml");env["CODEX_HOME"]=str(ch)
   argv=[shutil.which("codex"),"mcp","list","--json"]
  else:
   for name,folder in [("XDG_CONFIG_HOME","config"),("XDG_DATA_HOME","data"),("XDG_CACHE_HOME","cache"),("XDG_STATE_HOME","state")]:
    target=workspace/folder;target.mkdir();env[name]=str(target)
   env["OPENCODE_CONFIG"]=str(cfg);env["OPENCODE_CONFIG_CONTENT"]=json.dumps({"autoupdate":False,"share":"disabled"})
   argv=[shutil.which("opencode"),"--pure","mcp","list"]
  proc=subprocess.run(argv,env=env,cwd=workspace,capture_output=True,text=True,timeout=25)
  result[agent]={"exit":proc.returncode,"stdout":proc.stdout,"stderr":proc.stderr,"generated_path":str(cfg)}
  assert proc.returncode==0,result[agent]
  if agent=="codex":assert [x["name"] for x in json.loads(proc.stdout)]==["kxy_fixture"]
  else:assert "connected" in proc.stdout and "1 server(s)" in proc.stdout
 (root/"result.json").write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));print("Evidence",root)
