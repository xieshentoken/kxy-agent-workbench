"""V7 browser fixture with real Keychain and synthetic CLI/catalog only.

Launch from a normal host process. Records only created refs for exact cleanup.
Never queries unrelated existing Keychain items.
"""
import json, os, sys, threading, subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
DATA=Path('/private/tmp/kxy-v7-browser-data');DATA.mkdir(parents=True,exist_ok=True)
os.environ.update(KXY_DATA_ROOT=str(DATA),LANGFLOW_CONFIG_DIR=str(DATA/'lfx'),DO_NOT_TRACK='true')
sys.path.insert(0,str(ROOT))
from backend import app as core
from backend import agent_config as cfg
from fastapi.staticfiles import StaticFiles
import uvicorn

created_refs=[]
native_store=core.store_keychain_secret
def audited_store(ref,key):
    native_store(ref,key)
    created_refs.append(ref)
    (DATA/'created-keychain-refs.json').write_text(json.dumps(created_refs))
core.store_keychain_secret=audited_store
core.prepare_headless_environment=lambda agent,workspace,**kwargs:{'PATH':os.environ['PATH'],'HOME':str(workspace)}
core.probe_cli=lambda name:{'name':name,'available':True,'status':'READY','version':'V7 synthetic CLI inventory'}

class Catalog(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        body=json.dumps({'data':[{'id':f'fixture-{c}','name':f'Fixture {c}'} for c in 'abc']}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),Catalog)
threading.Thread(target=server.serve_forever,daemon=True).start()
(DATA/'fixture-info.json').write_text(json.dumps({'catalog_endpoint':f'http://127.0.0.1:{server.server_port}/v1','keychain':'real native, synthetic values only'}))
def discover(agent):
    cfg.ensure_agent_config_schema()
    records=[cfg._native_model_record(agent,'fixture-a',efforts=['low','high'],default_effort='high',discovery_source='V7 SYNTHETIC')] if agent=='codex' else []
    cfg._store_native_records(agent,records)
    return cfg.get_agent_profile(agent)
cfg.discover_agent=discover
assert core.app.routes[-1].name=='frontend'
core.app.routes[-1].app=StaticFiles(directory=ROOT/'frontend'/os.environ.get('KXY_V7_DIST','dist-v7'),html=True)
original_lifespan=core.app.router.lifespan_context
@asynccontextmanager
async def fixture_lifespan(app):
    async with original_lifespan(app):
      try:yield
      finally:
        server.shutdown();server.server_close()
        results=[]
        for ref in created_refs:
            result=subprocess.run(['/usr/bin/security','delete-generic-password','-a','kxy','-s','kxy/'+ref],capture_output=True)
            results.append({'ref':ref,'deleted':result.returncode==0})
        (DATA/'keychain-cleanup.json').write_text(json.dumps(results,indent=2))
core.app.router.lifespan_context=fixture_lifespan
if __name__=='__main__':
    uvicorn.run(core.app,host='127.0.0.1',port=8723)
