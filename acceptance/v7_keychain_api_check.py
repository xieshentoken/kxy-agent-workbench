"""Real Keychain API acceptance, unique synthetic values; run with normal host permissions."""
import json, os, secrets, subprocess, sys, tempfile, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
ROOT=Path(tempfile.mkdtemp(prefix='kxy-v7-keychain-api-'))
os.environ.update(KXY_DATA_ROOT=str(ROOT/'data'),LANGFLOW_CONFIG_DIR=str(ROOT/'lfx'),DO_NOT_TRACK='true')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import app as core
from fastapi.testclient import TestClient

expected=secrets.token_hex(32); refs=[];checked=[];cleanup=[]
class Catalog(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        checked.append(self.headers.get('Authorization')=='Bearer '+expected)
        body=b'{"data":[{"id":"v7-synthetic-model"}]}'
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),Catalog)
threading.Thread(target=server.serve_forever,daemon=True).start()
result={'real_keychain':True,'real_provider_inference':False}
try:
    with TestClient(core.app) as client:
        r=client.post('/api/credentials/store',json={'name':'V7 unique synthetic Keychain test','provider':'openai','api_format':'openai-responses','endpoint':f'http://127.0.0.1:{server.server_port}/v1','api_key':expected,'models':[]})
        assert r.status_code==200,r.text
        saved=r.json();refs.append(saved['credential_ref']);identifier=saved['id']
        assert saved['configured'];assert expected not in r.text
        assert core.keychain_secret(refs[-1])==expected
        result['store_and_native_read']=True
        listed=client.get('/api/credentials').json()
        assert next(s for s in listed if s['id']==identifier)['configured']
        result['list_configured']=True
        probe=client.post('/api/credentials/test',json={'credential_id':identifier})
        assert probe.status_code==200 and probe.json()['ok'],probe.text
        assert checked[-1];result['saved_reference_catalog_auth']=True
        r=client.put('/api/credentials/'+identifier,json={'name':'V7 synthetic renamed','api_key':''})
        assert r.status_code==200,r.text
        assert r.json()['credential_ref']==refs[-1];result['blank_edit_keeps_key']=True
        old=expected;expected=secrets.token_hex(32)
        r=client.put('/api/credentials/'+identifier,json={'api_key':expected})
        assert r.status_code==200,r.text
        rotated=r.json();refs.append(rotated['credential_ref'])
        assert rotated['id']==identifier and refs[-1]!=refs[0]
        assert core.keychain_secret(refs[-1])==expected
        assert core.keychain_secret(refs[0])==old
        result['rotation_preserves_service_and_old_item']=True
        probe=client.post('/api/credentials/test',json={'credential_id':identifier})
        assert probe.status_code==200 and probe.json()['ok'] and checked[-1],probe.text
        result['rotated_reference_catalog_auth']=True
        assert client.delete('/api/credentials/'+identifier).status_code==200
        assert client.get('/api/credentials').json()==[]
        db=core.DB_PATH.read_bytes();assert old.encode() not in db and expected.encode() not in db
        result['no_secret_in_database']=True
finally:
    server.shutdown();server.server_close()
    for ref in refs:
        p=subprocess.run(['/usr/bin/security','delete-generic-password','-a','kxy','-s','kxy/'+ref],capture_output=True)
        cleanup.append(p.returncode==0)
    result['created_items']=len(refs);result['deleted_created_items']=sum(cleanup)
    print(json.dumps(result,indent=2))
assert len(refs)==2 and all(cleanup)
