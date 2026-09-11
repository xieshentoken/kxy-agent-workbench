"""Runtime fault-injection integration checks. Fixture CLIs are explicitly synthetic."""
import json, os, sys, tempfile, threading, time, unittest, zipfile, io
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
ROOT=Path(tempfile.mkdtemp(prefix='kxy-runtime-checks-'))
os.environ['KXY_DATA_ROOT']=str(ROOT/'data'); os.environ['LANGFLOW_CONFIG_DIR']=str(ROOT/'lfx'); os.environ['DO_NOT_TRACK']='true'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import app as m
from fastapi.testclient import TestClient

class RuntimeChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=TestClient(m.app); cls.client=cls.context.__enter__()
        cls.fixture=ROOT/'fixture-cli'
        cls.fixture.write_text('#!/usr/bin/env python3\n'+'''import json,sys,time,pathlib,subprocess,os
args=sys.argv
if '--version' in args: print('synthetic-fixture 1'); sys.exit()
prompt=args[-1]
if 'FAIL_FIXTURE' in prompt: print('deliberate fixture failure'); sys.exit(9)
if 'TIMEOUT_FIXTURE' in prompt or 'CANCEL_FIXTURE' in prompt:
    child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
    pathlib.Path('child.pid').write_text(str(child.pid))
    time.sleep(60)
if 'NO_OUTPUT_FIXTURE' in prompt: print('plain startup log'); sys.exit()
text='SYNTHETIC_OUTPUT '+pathlib.Path('input-context.json').read_text()
pathlib.Path('outputs/report.txt').write_text(text)
pathlib.Path(args[args.index('--output-last-message')+1]).write_text(text)
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}}))
''')
        cls.fixture.chmod(0o755)
    @classmethod
    def tearDownClass(cls): cls.context.__exit__(None,None,None)
    def flow(self,prompt='fixture',grant_id=None):
        return {'nodes':[{'id':'source','type':'text','data':{'text':'ONLY_SYNTHETIC_MATERIAL'}},{'id':'a','type':'analyzer','data':{'cli':'codex','model':'fixture','network':True,'timeout':5,'prompt':prompt}},{'id':'output','type':'container','data':{'grant_id':grant_id}}], 'edges':[{'source':'source','target':'a'},{'source':'a','target':'output'}]}
    def submit(self,flow):
        response=self.client.post('/api/runs',json={'workflow':flow}); self.assertEqual(response.status_code,200,response.text); return response.json()['id']
    def wait(self,identifier):
        for _ in range(240):
            run=self.client.get('/api/runs/'+identifier).json()
            if run['status'] in {'succeeded','failed','cancelled'}: return run
            time.sleep(.05)
        self.fail('Run did not terminate')
    def test_argv_maps_effort_model_images_without_shell(self):
        argv=m.build_cli_argv({'cli':'codex','model':'m','effort':'high'},'literal $(do not execute)',ROOT,ROOT/'answer',[ROOT/'a.png'])
        self.assertIn('model_reasoning_effort="high"',argv); self.assertIn('--image',argv); self.assertEqual(argv[-1],'literal $(do not execute)'); self.assertNotIn('--add-dir',argv)
    def test_oversized_final_answer_fails_instead_of_silent_truncation(self):
        answer=ROOT/'long-answer.txt'; answer.write_text('x'*(m.MAX_TEXT_BYTES+1))
        with self.assertRaises(RuntimeError): m.extract_final_output([],answer)

    def test_restart_marks_unfinished_run_and_nodes_interrupted(self):
        with patch.object(m,'start_background_run'):
            identifier=self.submit(self.flow())
        m.init_db()
        run=self.client.get('/api/runs/'+identifier).json()
        self.assertEqual(run['status'],'interrupted')
        self.assertTrue(all(node['status']=='interrupted' for node in run['nodes']))

    def test_secret_filter_keeps_token_budget(self):
        cleaned,removed=m.sanitize_config({'max_tokens':200,'nested':[{'api_key':'secret-value','credential_id':'opaque'}]})
        self.assertEqual(cleaned['max_tokens'],200); self.assertNotIn('api_key',cleaned['nested'][0]); self.assertTrue(removed)
    def test_keychain_store_does_not_persist_secret_in_sqlite(self):
        secret='SYNTHETIC-KEY-NOT-A-REAL-CREDENTIAL'
        with patch.object(m,'store_keychain_secret') as store:
            response=self.client.post('/api/credentials/store',json={'provider':'fixture','api_key':secret,'endpoint':'http://127.0.0.1:1234/v1','env_name':'OPENAI_API_KEY'})
        self.assertEqual(response.status_code,200,response.text); store.assert_called_once()
        self.assertNotIn(secret,response.text)
        self.assertNotIn(secret,m.DB_PATH.read_bytes().decode('utf-8',errors='ignore'))
        self.assertEqual(self.client.post('/api/credentials/store',json={'api_key':secret,'endpoint':'https://user:pass@example.org'}).status_code,422)

    def test_granted_folder_symlink_replacement_is_rejected(self):
        folder=ROOT/'original-grant'; folder.mkdir(); elsewhere=ROOT/'elsewhere'; elsewhere.mkdir()
        grant=self.client.post('/api/grants',json={'path':str(folder)}).json()['id']
        folder.rmdir(); folder.symlink_to(elsewhere,target_is_directory=True)
        flow={'nodes':[{'id':'source','type':'text','data':{'text':'test'}},{'id':'out','type':'container','data':{'grant_id':grant}}],'edges':[{'source':'source','target':'out'}]}
        run=self.wait(self.submit(flow)); self.assertEqual(run['status'],'failed'); self.assertEqual(list(elsewhere.iterdir()),[])

    def test_zip_traversal_and_total_expansion_rejected(self):
        for entries in [[('../escape','x')],[('SKILL.md','x'),('a','a'*m.MAX_SKILL_BYTES),('b','b'*10)]]:
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
                for name,text in entries: z.writestr(name,text)
            response=self.client.post('/api/skills/import-zip',files={'file':('bad.zip',data.getvalue())})
            self.assertEqual(response.status_code,422,response.text)
    def test_real_graph_with_fixture_cli_output_and_grant(self):
        export=ROOT/'grant'; export.mkdir(exist_ok=True)
        grant=self.client.post('/api/grants',json={'path':str(export)}).json()
        with patch.dict(os.environ,{'KXY_CODEX_BIN':str(self.fixture)}): run=self.wait(self.submit(self.flow(grant_id=grant['id'])))
        self.assertEqual(run['status'],'succeeded',run.get('error'))
        artifacts=run['output_manifest']['artifacts']; self.assertTrue(any(a['name']=='report.txt' for a in artifacts))
        for a in artifacts: self.assertEqual(self.client.get(a['url']).status_code,200)
        self.assertEqual(self.client.get(f"/api/runs/{run['id']}/artifact/manifest.json").status_code,404)
        self.assertTrue((export/'kxy'/run['id']/'output'/'result.md').is_file())
        self.client.delete('/api/grants/'+grant['id'])
        with patch.dict(os.environ,{'KXY_CODEX_BIN':str(self.fixture)}): failed=self.wait(self.submit(self.flow(grant_id=grant['id'])))
        self.assertEqual(failed['status'],'failed')
        self.assertFalse((export/'kxy'/failed['id']).exists())
    def test_nonzero_and_log_only_are_failures(self):
        with patch.dict(os.environ,{'KXY_CODEX_BIN':str(self.fixture)}):
            for prompt in ['FAIL_FIXTURE','NO_OUTPUT_FIXTURE']:
                run=self.wait(self.submit(self.flow(prompt))); self.assertEqual(run['status'],'failed')
    def test_timeout_and_cancel_stop_processes(self):
        with patch.dict(os.environ,{'KXY_CODEX_BIN':str(self.fixture)}):
            run=self.wait(self.submit(self.flow('TIMEOUT_FIXTURE'))); self.assertEqual(run['status'],'failed'); self.assertIn('超时',run['error'])
            identifier=self.submit(self.flow('CANCEL_FIXTURE'))
            for _ in range(80):
                if identifier in m.RUN_PROCESSES: break
                time.sleep(.05)
            self.client.post('/api/runs/'+identifier+'/cancel')
            cancelled=self.wait(identifier); self.assertEqual(cancelled['status'],'cancelled')
            self.assertNotIn(identifier,m.RUN_PROCESSES)
    def test_snapshot_survives_skill_removal_before_run(self):
        skill=ROOT/'method'; skill.mkdir(exist_ok=True); (skill/'SKILL.md').write_text('---\nname: method\ndescription: Snapshot fixture.\n---\noriginal method')
        imported=self.client.post('/api/skills/import-path',json={'path':str(skill)}).json()
        flow=self.flow(); flow['nodes'][1]['data']['skill_ids']=[imported['id']]
        with patch.object(m,'start_background_run'):
            identifier=self.submit(flow)
        self.client.delete('/api/skills/'+imported['id'])
        m.RUN_CANCEL_EVENTS[identifier]=threading.Event()
        with patch.dict(os.environ,{'KXY_CODEX_BIN':str(self.fixture)}): m.run_workflow(identifier)
        run=self.wait(identifier); self.assertEqual(run['status'],'succeeded',run.get('error')); self.assertEqual(len(run['snapshot']['skills']),1)
    def test_two_containers_same_grant_and_active_branch_only(self):
        folder=ROOT/'two'; folder.mkdir(exist_ok=True); grant=self.client.post('/api/grants',json={'path':str(folder)}).json()['id']
        flow={'nodes':[{'id':'source','type':'text','data':{'text':'retain'}},{'id':'a','type':'container','data':{'grant_id':grant}},{'id':'b','type':'container','data':{'grant_id':grant}}],'edges':[{'source':'source','target':'a'},{'source':'source','target':'b'}]}
        run=self.wait(self.submit(flow)); self.assertEqual(run['status'],'succeeded',run.get('error')); self.assertEqual(len(run['output_manifest']['granted_outputs']),2)

if __name__=='__main__': unittest.main(verbosity=2)
