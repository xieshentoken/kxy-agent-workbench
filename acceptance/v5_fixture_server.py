"""Isolated UI server; opt-in native catalog reads, never model inference."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = os.environ.get('KXY_V5_NATIVE_DISCOVERY') == '1'
DATA = '/private/tmp/kxy-v5-native-browser-data' if NATIVE else '/private/tmp/kxy-v5-browser-data'
os.environ['KXY_DATA_ROOT'] = DATA
os.environ['LANGFLOW_CONFIG_DIR'] = DATA+'/lfx'
os.environ['DO_NOT_TRACK'] = 'true'
sys.path.insert(0, str(ROOT))

from backend import app as core
from backend import agent_config as cfg
from fastapi.staticfiles import StaticFiles
import uvicorn

CATALOGS = {
    'codex': [('fixture-reasoning', ['low', 'high', 'max'], 'high'),
              ('fixture-quick', ['minimal'], 'minimal'),
              ('fixture-unknown', [], None)],
    'claude': [('fixture-claude', ['medium'], 'medium')],
}

def synthetic_discovery(agent_id):
    cfg.ensure_agent_config_schema()
    records = [cfg._native_model_record(agent_id, model, alias=model,
                efforts=efforts, default_effort=default,
                discovery_source='SYNTHETIC V5 TEST CATALOG')
               for model, efforts, default in CATALOGS.get(agent_id, [])]
    cfg._store_native_records(agent_id, records)
    with core.connect_db() as db:
        db.execute("UPDATE agent_profiles SET available=1, status='READY', version='synthetic-v5', "
                   "supported_efforts='[\"low\",\"medium\",\"high\",\"max\"]', "
                   "message=?, discovered_at=? WHERE id=?",
                   (None if records else 'SYNTHETIC: no available model catalog', core.utc_now(), agent_id))
    return cfg.get_agent_profile(agent_id)

if not NATIVE:
    cfg.discover_agent = synthetic_discovery
assert core.app.routes[-1].name == 'frontend'
core.app.routes[-1].app = StaticFiles(directory=ROOT/'frontend/dist-v5', html=True)

if __name__ == '__main__':
    uvicorn.run(core.app, host='127.0.0.1', port=8721 if NATIVE else 8720)
