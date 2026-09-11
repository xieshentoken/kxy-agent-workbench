"""Independent V4 public contracts. Synthetic CLI and local HTTP; no real keys."""
import json, os, sys, tempfile, time, threading, unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(tempfile.mkdtemp(prefix='kxy-v4-independent-'))
os.environ['KXY_DATA_ROOT']=str(ROOT/'data')
os.environ['LANGFLOW_CONFIG_DIR']=str(ROOT/'lfx')
os.environ['DO_NOT_TRACK']='true'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import app as core
from fastapi.testclient import TestClient
KEY='kxy-synthetic-secret-ONLY-acceptance'
REQUESTS=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        REQUESTS.append((self.path,dict(self.headers)))
        if '/slow/' in self.path:time.sleep(2)
        if '/redirect/' in self.path:
            self.send_response(302);self.send_header('Location',f'http://127.0.0.1:{self.server.server_port}/leak');self.end_headers();return
        status=401 if '/unauthorized/' in self.path else 429 if '/limited/' in self.path else 200
        body=(b'plain '+KEY.encode()) if '/invalid/' in self.path else json.dumps({'data':[{'id':'synthetic-model','object':'model'}]}).encode()
        if status!=200:body=json.dumps({'error':{'message':KEY}}).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
def node(identifier,kind,**data):return {'id':identifier,'type':kind,'position':{'x':0,'y':0},'data':data}
def edge(source,target):return {'source':source,'target':target,'sourceHandle':'result','targetHandle':'items'}
def flow(analyzer=None,container=None):
    n=[node('source','text',text='ONLY_SYNTHETIC_MATERIAL')];e=[]
    if analyzer is not None:n.append(node('analysis','analyzer',cli='codex',model='fixture',network=True,timeout=8,**analyzer));e.append(edge('source','analysis'))
    n.append(node('output','container',**(container or {})));e.append(edge('analysis' if analyzer is not None else 'source','output'))
    return {'version':'kxy.workflow.v1','name':'Independent V4','nodes':n,'edges':e}
class V4Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=TestClient(core.app);cls.client=cls.context.__enter__()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.fixture=ROOT/'fixture-cli'
        cls.fixture.write_text('#!/usr/bin/env python3\n'+'''import json,sys,pathlib
if '--version' in sys.argv:print('synthetic-cli-only');sys.exit()
prompt=sys.argv[-1]
pathlib.Path('prompt-observed.txt').write_text(prompt)
text='{"count":7,"summary":"SYNTHETIC_OK"}'
if 'BAD_TYPE_FIXTURE' in prompt:text='{"count":"seven"}'
if 'PLAIN_FIXTURE' in prompt:text='SYNTHETIC_PLAIN'
pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(text)
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}}))
''');cls.fixture.chmod(0o755)
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.context.__exit__(None,None,None)
    def runflow(self,document):
        with patch.dict(os.environ,{'KXY_CODEX_BIN':str(self.fixture)}):
            r=self.client.post('/api/runs',json={'workflow':document});self.assertEqual(r.status_code,200,r.text)
            rid=r.json()['id'];deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                run=self.client.get('/api/runs/'+rid).json()
                if run['status'] in ['succeeded','failed','cancelled','interrupted']:return run
                time.sleep(.05)
            self.fail('run did not finish')
    def paths(self,run):return core.RUNS_ROOT/run['id']/'workspace'
    def test_01_old_container_keeps_existing_files(self):
        r=self.runflow(flow());self.assertEqual(r['status'],'succeeded',r.get('error'))
        p=self.paths(r);self.assertTrue(list(p.glob('exports/*/result.json')));self.assertTrue(list(p.glob('exports/*/result.md')));self.assertTrue(list(p.glob('exports/*/provenance.json')))
    def test_02_container_text_only_changes_real_files(self):
        r=self.runflow(flow(container={'export_formats':['text']}));self.assertEqual(r['status'],'succeeded',r.get('error'))
        p=self.paths(r);files=list(p.glob('exports/*/result.txt'));self.assertEqual(len(files),1);self.assertIn('ONLY_SYNTHETIC',files[0].read_text());self.assertFalse(list(p.glob('exports/*/result.md')));self.assertFalse(list(p.glob('exports/*/result.json')));self.assertTrue(list(p.glob('exports/*/provenance.json')))
    def test_03_json_schema_and_content_export(self):
        schema={'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}
        r=self.runflow(flow({'output_format':'json','output_schema':schema}, {'export_formats':['json'],'json_mode':'content'}));self.assertEqual(r['status'],'succeeded',r.get('error'))
        p=self.paths(r);answer=list(p.glob('nodes/*/outputs/answer.json'));self.assertEqual(len(answer),1);self.assertEqual(json.loads(answer[0].read_text())['count'],7)
        content=json.loads(next(p.glob('exports/*/result.json')).read_text());self.assertIn(content,[{'count':7,'summary':'SYNTHETIC_OK'},[{'count':7,'summary':'SYNTHETIC_OK'}]])
        self.assertTrue(any('count' in f.read_text() for f in p.glob('nodes/*/prompt-observed.txt')))
    def test_04_schema_mismatch_fails_run(self):
        r=self.runflow(flow({'prompt':'BAD_TYPE_FIXTURE','output_format':'json','output_schema':{'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}}));self.assertEqual(r['status'],'failed');self.assertIn('schema',r.get('error','').lower())
    def test_05_plain_text_and_legacy_json(self):
        r=self.runflow(flow({'prompt':'PLAIN_FIXTURE','output_format':'text'}));self.assertEqual(r['status'],'succeeded',r.get('error'));self.assertTrue(list(self.paths(r).glob('nodes/*/outputs/answer.txt')))
        r=self.runflow(flow({'expect_json':True}));self.assertEqual(r['status'],'succeeded',r.get('error'))
    def test_06_invalid_formats_and_remote_schema_rejected(self):
        for options in [{'output_format':'pdf'},{'output_format':'json','output_schema':{'$ref':'https://example.org/schema.json'}},{'output_format':'json','output_schema':{'type':'nonsense'}},{'output_format':'json','output_schema':{'$dynamicRef':'https://example.org/schema.json'}}]:
            r=self.client.post('/api/workflows/validate',json=flow(options));self.assertEqual(r.status_code,200,r.text);self.assertFalse(r.json()['ok'],r.text)
    def probe(self,provider='openai',suffix='/v1'):
        r=self.client.post('/api/credentials/test',json={'api_key':KEY,'provider':provider,'endpoint':self.base+suffix})
        self.assertEqual(r.status_code,200,r.text);self.assertNotIn(KEY,r.text);return r.json()
    def test_07_api_test_headers_and_version_path(self):
        REQUESTS.clear();r=self.probe();self.assertTrue(r['ok'],r);p,h=REQUESTS[-1];self.assertEqual(p,'/v1/models');self.assertEqual(h.get('Authorization'),f'Bearer {KEY}')
        r=self.probe('anthropic');self.assertTrue(r['ok'],r);_,h=REQUESTS[-1];h={k.lower():v for k,v in h.items()};self.assertEqual(h.get('x-api-key'),KEY);self.assertIn('anthropic-version',h)
    def test_08_api_errors_do_not_leak_key_or_follow_redirect(self):
        for suffix in ['/unauthorized/v1','/limited/v1','/invalid/v1','/redirect/v1']:
            REQUESTS.clear();r=self.probe(suffix=suffix);self.assertFalse(r['ok'],r);self.assertFalse(any(p=='/leak' for p,_ in REQUESTS))
    def test_09_api_cross_origin_blocked(self):
        r=self.client.post('/api/credentials/test',headers={'Origin':'https://evil.example'},json={'api_key':KEY,'provider':'openai','endpoint':self.base});self.assertEqual(r.status_code,403)
    def test_10_custom_base_path_is_preserved(self):
        REQUESTS.clear();r=self.probe(suffix='/compatible/v3');self.assertTrue(r['ok'],r);self.assertEqual(REQUESTS[-1][0],'/compatible/v3/models')
    def test_11_saved_reference_and_invalid_body_do_not_echo_key(self):
        with core.connect_db() as db:
            db.execute('INSERT INTO credentials(id,provider,credential_ref,endpoint,env_name,created_at) VALUES (?,?,?,?,?,?)',('v4-synthetic-reference','openai','v4-only',self.base+'/v1','OPENAI_API_KEY',core.utc_now()))
        with patch.object(core,'keychain_secret',return_value=KEY):
            r=self.client.post('/api/credentials/test',json={'provider':'openai','credential_id':'v4-synthetic-reference'})
        self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['ok']);self.assertNotIn(KEY,r.text)
        for body in [{'provider':'openai','api_key':{'untrusted':KEY}},{'provider':{'untrusted':KEY},'api_key':KEY}]:
            r=self.client.post('/api/credentials/test',json=body);self.assertEqual(r.status_code,422);self.assertNotIn(KEY,r.text)
    def test_12_slow_probe_keeps_health_responsive(self):
        REQUESTS.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(self.probe,'openai','/slow/v1')
            deadline=time.monotonic()+4
            while not REQUESTS and time.monotonic()<deadline:time.sleep(.01)
            self.assertTrue(REQUESTS)
            started=time.monotonic();r=self.client.get('/api/health');elapsed=time.monotonic()-started
            self.assertEqual(r.status_code,200);self.assertLess(elapsed,1.0,'slow API probe blocked health')
            self.assertTrue(future.result(timeout=8)['ok'])
    def test_13_condition_preserves_json_content_type(self):
        document=flow({'output_format':'json'},{'export_formats':['json'],'json_mode':'content'})
        document['nodes'].insert(2,node('route','condition',field='structured.count',operator='equals',expected='7'))
        document['edges']=[edge('source','analysis'),edge('analysis','route'),{**edge('route','output'),'sourceHandle':'true'}]
        r=self.runflow(document);self.assertEqual(r['status'],'succeeded',r.get('error'))
        content=json.loads(next(self.paths(r).glob('exports/*/result.json')).read_text());self.assertEqual(content,{'count':7,'summary':'SYNTHETIC_OK'})
    def test_14_secrets_not_in_database(self):
        for p in (ROOT/'data'/'db').glob('*'):
            if p.is_file():self.assertNotIn(KEY.encode(),p.read_bytes())
if __name__=='__main__':unittest.main(verbosity=2)
