"""Parent browser fixture: real local API/LFX, synthetic analyzer, no credentials."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path('/private/tmp/kxy-v8-browser-data')
DATA.mkdir(exist_ok=True)
os.environ.update(KXY_DATA_ROOT=str(DATA), LANGFLOW_CONFIG_DIR=str(DATA/'lfx'), DO_NOT_TRACK='true')
sys.path.insert(0, str(ROOT))
from backend import app as core
from fastapi.staticfiles import StaticFiles
import uvicorn

def synthetic_execute(state, prompt, payloads, component):
    key = state.run_id + ':' + str(component.get_id())
    counts_file = DATA/'synthetic-counts.json'
    counts = json.loads(counts_file.read_text()) if counts_file.exists() else {}
    counts[key] = counts.get(key, 0) + 1
    counts_file.write_text(json.dumps(counts))
    if 'V8_FAIL_ONCE' in prompt and counts[key] == 1:
        raise RuntimeError('V8 synthetic quota interruption; retry is now available')
    return {'text': 'V8 synthetic reply: ' + prompt, 'content': {'route': 'yes'}, 'artifacts': []}

core.execute_cli = synthetic_execute
core.probe_cli = lambda name: {'name': name, 'available': True, 'status': 'READY', 'version': 'V8 synthetic inventory'}
assert core.app.routes[-1].name == 'frontend'
core.app.routes[-1].app = StaticFiles(directory=ROOT/'frontend'/'dist-v8', html=True)

if __name__ == '__main__':
    uvicorn.run(core.app, host='127.0.0.1', port=8724)
