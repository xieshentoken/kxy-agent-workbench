"""Isolated UI fixture: real API/LFX, synthetic agent checks and analysis."""
import hashlib, json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DATA = Path(tempfile.mkdtemp(prefix='kxy-v10-browser-'))
os.environ.update(KXY_DATA_ROOT=str(DATA), LANGFLOW_CONFIG_DIR=str(DATA/'lfx'), DO_NOT_TRACK='true')
sys.path.insert(0, str(ROOT))
from backend import app as core, agent_config as agents
from fastapi.staticfiles import StaticFiles
import uvicorn

def discover(agent_id):
    with core.connect_db() as db:
        db.execute("UPDATE agent_profiles SET available=1,status='READY',version='V10 synthetic',discovered_at=?,message=NULL WHERE id=?", (core.utc_now(),agent_id))
    return agents.get_agent_profile(agent_id)

def login(agent_id):
    known = agent_id in {'codex','claude'}
    record=agents._login_record(status='verified' if known else 'unsupported', verified=True if known else None, source='V10 synthetic status', evidence='synthetic_only', reason='合成检查，仅用于界面验收')
    with core.connect_db() as db:
        db.execute('UPDATE agent_profiles SET login_status=?,login_checked_at=?,login_source=?,login_evidence=?,login_reason=? WHERE id=?', (record['status'],record['checked_at'],record['source'],record['evidence'],record['reason'],agent_id))
    return record

def execute(state,prompt,payloads,component):
    target=state.active_node_workspace_root/str(component.get_id())/'outputs'/'proof.txt'
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text('V10 synthetic artifact')
    return {'text':'V10 合成正文', 'artifacts':[{'name':target.name,'path':str(target.relative_to(state.workspace)),'size':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}]}

agents.discover_agent=discover
agents.check_agent_login_status=login
core.execute_cli=execute
core.probe_cli=lambda name:{'name':name,'available':True,'status':'READY','version':'V10 synthetic'}
def seed():
    agents.ensure_agent_config_schema()
    record=agents._native_model_record('codex','v10-fixture-model',alias='V10 native',efforts=['low','high'],default_effort='low',discovery_source='synthetic fixture')
    agents._store_native_records('codex',[record])
    agents.create_agent_model({'cli_id':'codex','model':'v10-fixture-model','alias':'V10 保存模型','source':'manual','native_model_ref':record['id'],'default_effort':'high'})
    for agent_id in agents.AGENT_IDS:discover(agent_id)
core.init_db()
seed()
assert core.app.routes[-1].name=='frontend'
core.app.routes[-1].app=StaticFiles(directory=ROOT/'frontend'/'dist-v10',html=True)
if __name__=='__main__':
    print('Isolated fixture data:',DATA,flush=True)
    uvicorn.run(core.app,host='127.0.0.1',port=8724)
