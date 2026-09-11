"""Parent-owned V6 acceptance. Synthetic CLI, catalog and in-memory Keychain only."""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from contextlib import nullcontext

ROOT = Path(tempfile.mkdtemp(prefix='kxy-v6-independent-'))
os.environ.update(KXY_DATA_ROOT=str(ROOT/'data'), LANGFLOW_CONFIG_DIR=str(ROOT/'lfx'), DO_NOT_TRACK='true')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as core
from backend import agent_config as cfg
from fastapi.testclient import TestClient

KEY = 'v6-synthetic-key-never-real'
CALLS = []
def node(identifier, kind, **data):
    return dict(id=identifier, type=kind, position=dict(x=0,y=0), data=data)
def edge(source,target):
    return dict(source=source,target=target,sourceHandle='result',targetHandle='items')
def flow(prompt='EXACT_PROMPT', **container):
    return dict(version='kxy.workflow.v1',name='V6 synthetic',
        nodes=[node('source','text',text='SYNTHETIC_INPUT'),
               node('analysis','analyzer',cli='codex',model='fixture',network=True,timeout=8,prompt=prompt,output_format='auto'),
               node('output','container',export_formats=[],allowed_file_extensions=[],**container)],
        edges=[edge('source','analysis'),edge('analysis','output')])

class Catalog(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        CALLS.append((self.path,dict(self.headers)))
        if '/redirect/' in self.path:
            self.send_response(302);self.send_header('Location','/leak');self.end_headers();return
        body = {'data':[{'id':'fixture-a','name':'Readable A'},{'id':'fixture-b'}]}
        if '/google/' in self.path:
            body = {'models':[{'name':'models/fixture-g','displayName':'Gemini fixture','supportedGenerationMethods':['generateContent']}]}
        if '/leak-body/' in self.path:
            body = {'data':[{'id':KEY,'name':KEY}]}
        data=json.dumps(body).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

class V6Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx=TestClient(core.app);cls.client=cls.ctx.__enter__()
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),Catalog)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.keys={}
        cls.patches=[patch.object(core,'store_keychain_secret',side_effect=lambda ref,key:cls.keys.__setitem__(ref,key)),
                     patch.object(core,'keychain_secret',side_effect=lambda ref:cls.keys[ref]),
                     patch.object(core,'keychain_has',side_effect=lambda ref:ref in cls.keys)]
        for p in cls.patches:p.start()
        cls.fixture=ROOT/'fixture-cli'
        cls.fixture.write_text('#!/usr/bin/env python3\n'+'''
import json,sys,pathlib
if '--version' in sys.argv: print('synthetic-v6-only');sys.exit()
prompt=sys.argv[-1]
pathlib.Path('prompt-observed.txt').write_text(prompt)
reply='  RAW_REPLY\\nsecond line  '
if 'JSON_FIXTURE' in prompt:reply='{ "route": "yes", "count": 7 }'
if 'FILE_FIXTURE' in prompt:
    pathlib.Path('outputs/report.PDF').write_bytes(b'%PDF-1.4\\nV6 synthetic bytes')
    pathlib.Path('outputs/data.csv').write_text('item,value\\na,7\\n')
    pathlib.Path('outputs/ignored.exe').write_bytes(b'not executable; excluded fixture')
if 'ONLY_FILES' in prompt or 'EMPTY_NO_FILES' in prompt:reply=''
if 'SYMLINK_FIXTURE' in prompt:pathlib.Path('outputs/unsafe.pdf').symlink_to(pathlib.Path('input-context.json').resolve())
if 'STARTUP_ONLY_WITH_FILES' in prompt:
    print('UNVERIFIED_STARTUP_LOG');sys.exit()
pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(reply)
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':reply}}))
''')
        cls.fixture.chmod(0o755)
    @classmethod
    def tearDownClass(cls):
        for p in reversed(cls.patches):p.stop()
        cls.server.shutdown();cls.server.server_close();cls.ctx.__exit__(None,None,None)
    def runflow(self,document,real_environment=False):
        environment_patch=nullcontext() if real_environment else patch.object(core,'prepare_headless_environment',side_effect=lambda agent,workspace,**kwargs:{'PATH':os.environ['PATH'],'HOME':str(workspace)})
        with patch.dict(os.environ,{'KXY_CODEX_BIN':str(self.fixture)}), environment_patch:
            r=self.client.post('/api/runs',json={'workflow':document})
            self.assertEqual(r.status_code,200,r.text);rid=r.json()['id']
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                run=self.client.get('/api/runs/'+rid).json()
                if run['status'] in ['succeeded','failed','cancelled','interrupted']:return run
                time.sleep(.05)
            self.fail('synthetic run timeout')
    def workspace(self,run):return core.RUNS_ROOT/run['id']/'workspace'
    def service(self,**changes):
        payload=dict(name='V6 reusable service',provider='custom',api_format='openai-responses',
            endpoint=self.base+'/v1',api_key=KEY,env_name='OPENAI_API_KEY',models=[{'id':'fixture-a','alias':'Model A'}])
        payload.update(changes)
        r=self.client.post('/api/credentials/store',json=payload)
        self.assertEqual(r.status_code,200,r.text);self.assertNotIn(KEY,r.text)
        return r.json()
    def test_01_prompt_is_literal_and_no_automatic_answer_file(self):
        prompt='  Ignore templates; answer freely.\n日本語 / 中文 $x --option\n'
        run=self.runflow(flow(prompt));self.assertEqual(run['status'],'succeeded',run.get('error'))
        p=self.workspace(run)
        self.assertEqual(next(p.glob('nodes/*/prompt-observed.txt')).read_text(),prompt)
        self.assertFalse(list(p.glob('nodes/*/outputs/answer.*')))
        self.assertFalse(list(p.glob('exports/*/result.*')))
        text=json.dumps(run,ensure_ascii=False)
        self.assertIn('RAW_REPLY',text)
        self.assertEqual(next(n['output']['text'] for n in run['nodes'] if n['node_id']=='analysis'),'  RAW_REPLY\nsecond line  ')
    def test_02_json_validation_does_not_change_prompt(self):
        document=flow('JSON_FIXTURE')
        document['nodes'][1]['data'].update(output_format='json',output_schema={'type':'object','required':['count']})
        run=self.runflow(document);self.assertEqual(run['status'],'succeeded',run.get('error'))
        self.assertEqual(next(self.workspace(run).glob('nodes/*/prompt-observed.txt')).read_text(),'JSON_FIXTURE')
    def test_03_auto_json_remains_structured_for_condition(self):
        document=flow('JSON_FIXTURE')
        document['nodes'].insert(2,node('route','condition',field='structured.count',operator='equals',expected='7'))
        document['edges']=[edge('source','analysis'),edge('analysis','route'),{**edge('route','output'),'sourceHandle':'true'}]
        run=self.runflow(document);self.assertEqual(run['status'],'succeeded',run.get('error'))
        self.assertIn('count',json.dumps(run))
    def test_04_only_allowed_real_files_reach_grant(self):
        grant_dir=ROOT/'granted';grant_dir.mkdir(exist_ok=True)
        with core.connect_db() as db:
            db.execute('INSERT OR REPLACE INTO grants(id,canonical_path,created_at,revoked_at) VALUES (?,?,?,NULL)',('v6-grant',str(grant_dir.resolve()),core.utc_now()))
        document=flow('FILE_FIXTURE',grant_id='v6-grant');document['nodes'][-1]['data']['allowed_file_extensions']=['.pdf']
        run=self.runflow(document);self.assertEqual(run['status'],'succeeded',run.get('error'))
        files=[p for p in grant_dir.rglob('*') if p.is_file()]
        pdfs=[p for p in files if p.suffix.lower()=='.pdf']
        self.assertEqual(len(pdfs),1)
        self.assertEqual(pdfs[0].read_bytes(),b'%PDF-1.4\nV6 synthetic bytes')
        self.assertFalse(any(p.suffix.lower() in ['.csv','.exe'] for p in files))
        self.assertIn('ignored.exe',json.dumps(run))
    def test_05_files_only_reply_is_valid(self):
        document=flow('FILE_FIXTURE ONLY_FILES');document['nodes'][-1]['data']['allowed_file_extensions']=['.pdf','.csv']
        run=self.runflow(document);self.assertEqual(run['status'],'succeeded',run.get('error'))
        self.assertTrue(list(self.workspace(run).glob('exports/*/files/*.pdf')) or list(self.workspace(run).glob('exports/*/files/*.PDF')))
    def test_06_symlink_file_is_rejected(self):
        run=self.runflow(flow('SYMLINK_FIXTURE'));self.assertEqual(run['status'],'failed')
    def test_07_grok_attachment_argv_does_not_append_prompt(self):
        root=ROOT/'grok';root.mkdir(exist_ok=True);f=root/'input.txt';f.write_text('fixture')
        argv=cfg.build_headless_command('grok','EXACT_GROK',root,executable='/bin/echo',attachments=[f])
        self.assertEqual(argv[argv.index('-p')+1],'EXACT_GROK')
    def test_08_service_is_reusable_metadata_and_blank_key_edit(self):
        saved=self.service();keyref=saved['credential_ref'];count=len(self.keys)
        r=self.client.put('/api/credentials/'+saved['id'],json={'name':'Edited name','api_key':''})
        self.assertEqual(r.status_code,200,r.text)
        updated=r.json();self.assertEqual(updated['credential_ref'],keyref);self.assertEqual(len(self.keys),count)
        rows=self.client.get('/api/credentials').json();row=next(x for x in rows if x['id']==saved['id'])
        self.assertEqual(row['name'],'Edited name');self.assertEqual(row['api_format'],'openai-responses')
        self.assertEqual(row['models'][0]['id'],'fixture-a');self.assertNotIn(KEY,json.dumps(rows))
    def test_09_service_reuse_and_incompatible_agent_gate(self):
        saved=self.service()
        def create(agent,alias):
            return self.client.post('/api/agent-models',json=dict(cli_id=agent,model='fixture-a',alias=alias,source='api',efforts=[],credential_id=saved['id']))
        for agent in ['codex','pi']:
            r=create(agent,'V6 '+agent);self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['credential_id'],saved['id'])
        self.assertIn(create('claude','V6 incompatible').status_code,[400,422])
    def test_10_saved_key_cannot_be_redirected_by_edit(self):
        saved=self.service()
        r=self.client.put('/api/credentials/'+saved['id'],json={'endpoint':self.base+'/different','api_key':''})
        self.assertIn(r.status_code,[400,422],r.text)
        current=next(x for x in self.client.get('/api/credentials').json() if x['id']==saved['id'])
        self.assertEqual(current['endpoint'],saved['endpoint'])
    def test_11_protocol_catalog_models_and_headers(self):
        for fmt,provider,env,part,header in [
            ('openai-responses','openai','OPENAI_API_KEY','/v1','authorization'),
            ('anthropic-messages','anthropic','ANTHROPIC_API_KEY','/v1','x-api-key'),
            ('google-generative-ai','google','GEMINI_API_KEY','/google/v1beta','x-goog-api-key')]:
            CALLS.clear()
            r=self.client.post('/api/credentials/test',json={'provider':provider,'api_format':fmt,'endpoint':self.base+part,'api_key':KEY})
            self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['ok'],r.text)
            self.assertTrue(r.json()['models']);self.assertNotIn(KEY,r.text)
            headers={k.lower():v for k,v in CALLS[-1][1].items()};self.assertIn(header,headers)
    def test_12_catalog_redirect_and_secret_echo_rejected(self):
        for part in ['/redirect/v1','/leak-body/v1']:
            CALLS.clear()
            r=self.client.post('/api/credentials/test',json={'provider':'openai','api_format':'openai-responses','endpoint':self.base+part,'api_key':KEY})
            self.assertNotIn(KEY,r.text);self.assertFalse(any(p=='/leak' for p,_ in CALLS))
            if 'redirect' in part:self.assertFalse(r.json()['ok'])
    def test_13_key_does_not_enter_database(self):
        self.service()
        with core.connect_db() as db: db.execute('PRAGMA wal_checkpoint(FULL)')
        for p in (ROOT/'data').rglob('*.sqlite3*'):
            self.assertNotIn(KEY.encode(),p.read_bytes())
    def test_14_selected_skill_and_input_manifest_do_not_rewrite_prompt(self):
        folder=ROOT/'fixture-skill';folder.mkdir(exist_ok=True)
        (folder/'SKILL.md').write_text('---\nname: v6-fixture-skill\ndescription: Synthetic acceptance only\n---\nA deliberately selected fixture skill.')
        skill=core.import_skill_root(folder)
        document=flow('EXACT_WITH_SELECTED_SKILL')
        document['nodes'][1]['data']['skill_ids']=[skill['id']]
        run=self.runflow(document);self.assertEqual(run['status'],'succeeded',run.get('error'))
        workspace=self.workspace(run)
        self.assertEqual(next(workspace.glob('nodes/*/prompt-observed.txt')).read_text(),'EXACT_WITH_SELECTED_SKILL')
        self.assertTrue(list(workspace.glob('nodes/*/skill-manifest.json')))
        self.assertIn('SYNTHETIC_INPUT',next(workspace.glob('nodes/*/input-context.json')).read_text())
    def test_15_explicit_json_is_validation_not_a_conversion(self):
        document=flow('NON_JSON_PLAIN_REPLY')
        document['nodes'][1]['data']['output_format']='json'
        run=self.runflow(document);self.assertEqual(run['status'],'failed')
        self.assertEqual(next(self.workspace(run).glob('nodes/*/prompt-observed.txt')).read_text(),'NON_JSON_PLAIN_REPLY')
    def test_16_saved_probe_uses_bound_endpoint(self):
        saved=self.service();CALLS.clear()
        r=self.client.post('/api/credentials/test',json={'provider':'openai','api_format':'openai-responses','credential_id':saved['id'],'endpoint':self.base+'/should-not-receive'})
        self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['ok'],r.text)
        self.assertEqual(CALLS[-1][0],'/v1/models')
    def test_17_attachment_is_available_without_prompt_suffix(self):
        response=self.client.post('/api/files',files={'file':('synthetic.txt',b'V6 ATTACHMENT ORIGINAL','text/plain')})
        self.assertEqual(response.status_code,200,response.text)
        identifier=response.json()['id']
        document=flow('ATTACHMENT_PROMPT_UNCHANGED')
        document['nodes'][0]=node('source','file',file_id=identifier,label='synthetic.txt')
        run=self.runflow(document);self.assertEqual(run['status'],'succeeded',run.get('error'))
        workspace=self.workspace(run)
        self.assertEqual(next(workspace.glob('nodes/*/prompt-observed.txt')).read_text(),'ATTACHMENT_PROMPT_UNCHANGED')
        copies=list(workspace.glob('nodes/*/inputs/*'))
        self.assertTrue(any(p.is_file() and p.read_bytes()==b'V6 ATTACHMENT ORIGINAL' for p in copies))
    def test_18_invalid_file_extension_policy_is_rejected(self):
        for extensions in [['../pdf'],['.pdf/../exe'],['*'],['.exe'],42]:
            document=flow();document['nodes'][-1]['data']['allowed_file_extensions']=extensions
            r=self.client.post('/api/workflows/validate',json=document)
            self.assertEqual(r.status_code,200,r.text);self.assertFalse(r.json()['ok'],str(extensions))
    def test_19_empty_file_allowlist_keeps_actual_files_internal(self):
        run=self.runflow(flow('FILE_FIXTURE'));self.assertEqual(run['status'],'succeeded',run.get('error'))
        workspace=self.workspace(run)
        self.assertTrue(list(workspace.glob('nodes/*/outputs/report.PDF')))
        self.assertFalse(list(workspace.glob('exports/*/files/*')))
    def test_20_blank_prompt_does_not_get_fallback_instruction(self):
        run=self.runflow(flow(''));self.assertEqual(run['status'],'succeeded',run.get('error'))
        self.assertEqual(next(self.workspace(run).glob('nodes/*/prompt-observed.txt')).read_text(),'')
    def test_21_empty_reply_and_no_files_is_failure(self):
        run=self.runflow(flow('EMPTY_NO_FILES'));self.assertEqual(run['status'],'failed')
    def test_22_deleted_service_cannot_fall_back_to_native_login(self):
        saved=self.service()
        response=self.client.post('/api/agent-models',json={'cli_id':'codex','model':'fixture-a','alias':'V6 deleted service','source':'api','efforts':[],'credential_id':saved['id']})
        self.assertEqual(response.status_code,200,response.text)
        model=response.json()
        removed=self.client.delete('/api/credentials/'+saved['id']);self.assertEqual(removed.status_code,200,removed.text)
        with self.assertRaises((ValueError,cfg.AgentConfigError)):
            cfg.resolve_model_binding({'cli':'codex','model_ref':model['id']})
    def test_23_rotated_key_cannot_enter_public_metadata(self):
        for field,value in [('endpoint',self.base+'/v6-rotated-synthetic-key'),('models',[{'id':'fixture-a','alias':'v6-rotated-synthetic-key'}]),('name','v6-rotated-synthetic-key')]:
            saved=self.service()
            r=self.client.put('/api/credentials/'+saved['id'],json={field:value,'api_key':'v6-rotated-synthetic-key'})
            self.assertNotIn('v6-rotated-synthetic-key',r.text)
            self.assertNotIn('v6-rotated-synthetic-key',self.client.get('/api/credentials').text)
    def test_24_valid_key_rotation_preserves_service_identity(self):
        saved=self.service()
        r=self.client.put('/api/credentials/'+saved['id'],json={'name':'Rotated V6 service','api_key':'v6-normal-rotated-key'})
        self.assertEqual(r.status_code,200,r.text)
        row=r.json();self.assertEqual(row['id'],saved['id']);self.assertNotEqual(row['credential_ref'],saved['credential_ref'])
        self.assertEqual(self.keys[row['credential_ref']],'v6-normal-rotated-key')
    def test_25_startup_logs_are_not_final_reply_when_files_exist(self):
        run=self.runflow(flow('FILE_FIXTURE STARTUP_ONLY_WITH_FILES'))
        self.assertEqual(run['status'],'succeeded',run.get('error'))
        output=next(n['output'] for n in run['nodes'] if n['node_id']=='analysis')
        self.assertEqual(output['text'],'')
    def test_26_runtime_uses_exact_saved_service_not_same_named_native_model(self):
        for agent in ['codex','pi','opencode']:
            saved=self.service()
            r=self.client.post('/api/agent-models',json={'cli_id':agent,'model':'fixture-a','alias':'V6 runtime '+agent,'source':'api','efforts':[],'credential_id':saved['id']})
            self.assertEqual(r.status_code,200,r.text)
            model=r.json();captured={}
            def prepare(agent_id,workspace,**kwargs):
                env=cfg.prepare_headless_environment(agent_id,workspace,**kwargs)
                captured['env']=env
                configs=list(Path(workspace).glob('.cli-state/pi/models.json'))
                if configs:captured['pi_config']=json.loads(configs[0].read_text())
                return env
            def build(agent_id,prompt,workspace,**kwargs):
                kwargs['executable']='/bin/echo'
                argv=cfg.build_headless_command(agent_id,prompt,workspace,**kwargs)
                captured['argv']=argv
                return [str(self.fixture),'--output-last-message',str(kwargs['last_message']),prompt]
            document=flow('EXACT_API_RUNTIME')
            document['nodes'][1]['data'].update(cli=agent,agent_id=agent,model_ref=model['id'],model='')
            with patch.object(core,'prepare_headless_environment',side_effect=prepare),patch.object(core,'build_headless_command',side_effect=build),patch.object(core,'wrap_headless_command',side_effect=lambda argv,*args,**kwargs:(argv,None)):
                run=self.runflow(document,real_environment=True)
            self.assertEqual(run['status'],'succeeded',run.get('error'))
            argv=captured['argv'];self.assertEqual(argv[-1],'EXACT_API_RUNTIME')
            self.assertEqual(captured['env']['OPENAI_API_KEY'],KEY)
            if agent=='codex':
                self.assertTrue(any('wire_api="responses"' in arg and saved['endpoint'] in arg for arg in argv))
            elif agent=='pi':
                config=captured['pi_config'];self.assertNotIn(KEY,json.dumps(config))
                provider=next(iter(config['providers']));entry=config['providers'][provider]
                self.assertEqual(entry['api'],'openai-responses');self.assertEqual(entry['baseUrl'],saved['endpoint'])
                explicit=('--provider' in argv and argv[argv.index('--provider')+1]==provider) or argv[argv.index('--model')+1]==provider+'/fixture-a'
                self.assertTrue(explicit,'pi must explicitly select saved service provider')
            else:
                config=json.loads(captured['env']['OPENCODE_CONFIG_CONTENT'])
                self.assertNotIn(KEY,json.dumps(config))
                selected=argv[argv.index('--model')+1]
                self.assertIn('/',selected,'OpenCode requires explicit provider/model')
                provider=selected.split('/',1)[0];entry=config['provider'][provider]
                self.assertEqual(entry['npm'],'@ai-sdk/openai')
                self.assertEqual(entry['options']['baseURL'],saved['endpoint'])
                self.assertIn('fixture-a',entry['models'])
    def test_27_anthropic_sdk_base_does_not_duplicate_version_path(self):
        saved=self.service(provider='anthropic',api_format='anthropic-messages',env_name='ANTHROPIC_API_KEY')
        for agent in ['claude','pi']:
            workspace=ROOT/('anthropic-'+agent);workspace.mkdir(exist_ok=True)
            env=cfg.prepare_headless_environment(agent,workspace,credential_id=saved['id'],api_format='anthropic-messages',model='fixture-a',base_env={'PATH':os.environ['PATH']})
            self.assertEqual(env['ANTHROPIC_BASE_URL'],self.base)
            self.assertEqual(env['ANTHROPIC_API_KEY'],KEY)
            if agent=='pi':
                config=json.loads((workspace/'.cli-state/pi/models.json').read_text())
                entry=next(iter(config['providers'].values()))
                self.assertEqual(entry['baseUrl'],self.base)
                self.assertEqual(entry['api'],'anthropic-messages')
                self.assertNotIn(KEY,json.dumps(config))
    def test_28_google_service_creates_real_pi_configuration(self):
        saved=self.service(provider='google',api_format='google-generative-ai',env_name='GEMINI_API_KEY',endpoint=self.base+'/v1beta')
        response=self.client.post('/api/agent-models',json={'cli_id':'pi','model':'fixture-a','alias':'V6 Google','source':'api','efforts':[],'credential_id':saved['id']})
        self.assertEqual(response.status_code,200,response.text)
        workspace=ROOT/'google-pi';workspace.mkdir(exist_ok=True)
        env=cfg.prepare_headless_environment('pi',workspace,credential_id=saved['id'],model='fixture-a',api_format='google-generative-ai',base_env={'PATH':os.environ['PATH']})
        self.assertEqual(env['GEMINI_API_KEY'],KEY)
        config=json.loads((workspace/'.cli-state/pi/models.json').read_text());entry=next(iter(config['providers'].values()))
        self.assertEqual(entry['api'],'google-generative-ai');self.assertEqual(entry['baseUrl'],saved['endpoint'])
        self.assertEqual(entry['apiKey'],'$GEMINI_API_KEY');self.assertNotIn(KEY,json.dumps(config))

if __name__=='__main__':unittest.main(verbosity=2)
