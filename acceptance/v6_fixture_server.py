"""Parent-owned isolated browser server. No real keys, provider or inference."""
import json
import os
import sys
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT=Path(__file__).resolve().parents[1]
DATA=Path('/private/tmp/kxy-v6-browser-data')
DATA.mkdir(parents=True,exist_ok=True)
os.environ.update(KXY_DATA_ROOT=str(DATA),LANGFLOW_CONFIG_DIR=str(DATA/'lfx'),DO_NOT_TRACK='true')
sys.path.insert(0,str(ROOT))
from backend import app as core
from backend import agent_config as cfg
from fastapi.staticfiles import StaticFiles
import uvicorn

KEYS={}
core.keychain_secret=lambda ref:KEYS.get(ref,'V6-fake-browser-key')
core.keychain_has=lambda ref:True
core.store_keychain_secret=lambda ref,key:KEYS.__setitem__(ref,key)
core.prepare_headless_environment=lambda agent,workspace,**kwargs:{'PATH':os.environ['PATH'],'HOME':str(workspace)}
core.probe_cli=lambda name:{'name':name,'available':True,'status':'READY','version':'V6 synthetic CLI inventory'}
class Catalog(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        body=json.dumps({'data':[{'id':'fixture-a','name':'Fixture model A'},{'id':'fixture-b','name':'Fixture model B'}]}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),Catalog)
threading.Thread(target=server.serve_forever,daemon=True).start()
(DATA/'fixture-info.json').write_text(json.dumps({'catalog_endpoint':f'http://127.0.0.1:{server.server_port}/v1'}))

cli=DATA/'fixture-cli'
cli.write_text('#!/usr/bin/env python3\n'+'''
import sys,json,pathlib
if '--version' in sys.argv:print('synthetic-v6');sys.exit()
pathlib.Path('prompt-observed.txt').write_text(sys.argv[-1])
pathlib.Path('outputs/report.pdf').write_bytes(b'%PDF-1.4\\nSYNTHETIC V6 UI FILE')
pathlib.Path('outputs/data.csv').write_text('x,y\\n1,2\\n')
reply='V6 实际文本回复：这是独立验收夹具的结果。'
pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(reply)
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':reply}},ensure_ascii=False))
''')
cli.chmod(0o755)
os.environ['KXY_CODEX_BIN']=str(cli)
def discover(agent):
    cfg.ensure_agent_config_schema()
    values=[('fixture-a',['low','high','max'],'high'),('fixture-b',[],None)] if agent=='codex' else []
    records=[cfg._native_model_record(agent,m,alias=m,efforts=e,default_effort=d,discovery_source='V6 SYNTHETIC') for m,e,d in values]
    cfg._store_native_records(agent,records)
    with core.connect_db() as db:
        db.execute("UPDATE agent_profiles SET available=1,status='READY',version='synthetic-v6' WHERE id=?",(agent,))
    return cfg.get_agent_profile(agent)
cfg.discover_agent=discover
assert core.app.routes[-1].name=='frontend'
core.app.routes[-1].app=StaticFiles(directory=ROOT/'frontend'/os.environ.get('KXY_V6_DIST','dist-v6'),html=True)
if __name__=='__main__':
    try:uvicorn.run(core.app,host='127.0.0.1',port=8722)
    finally:server.shutdown();server.server_close()
