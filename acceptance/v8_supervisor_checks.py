"""Independent V8 runtime acceptance. Real API/LFX, isolated data, synthetic analyzer."""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(tempfile.mkdtemp(prefix='kxy-v8-supervisor-'))
os.environ.update(KXY_DATA_ROOT=str(ROOT/'data'), LANGFLOW_CONFIG_DIR=str(ROOT/'lfx'), DO_NOT_TRACK='true')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as core
from fastapi.testclient import TestClient

def node(i, kind, **data):
    return {'id': i, 'type': kind, 'position': {'x': 0, 'y': 0}, 'data': data}
def edge(a, b, handle='result'):
    return {'id': a+'-'+handle+'-'+b, 'source': a, 'target': b, 'sourceHandle': handle, 'targetHandle': 'items'}
def flow(nodes, edges):
    return {'version': 'kxy.workflow.v1', 'name': 'V8 independent synthetic', 'nodes': nodes, 'edges': edges}
def chain():
    return flow([node('s','text',text='synthetic'), node('a','analyzer',cli='codex',prompt='success'),
                 node('b','analyzer',cli='codex',prompt='fail-once'), node('o','container',export_formats=[],allowed_file_extensions=[])],
                [edge('s','a'),edge('a','b'),edge('b','o')])

class V8Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(core.app)
        cls.client = cls.context.__enter__()
    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None,None,None)
    def setUp(self):
        self.calls = {}
        self.patch = patch.object(core,'execute_cli',side_effect=self.execute)
        self.patch.start()
        self.addCleanup(self.patch.stop)
    def execute(self, state, prompt, values, comp):
        key = (state.run_id,str(comp.get_id()))
        self.calls[key] = self.calls.get(key,0)+1
        if prompt == 'fail-once' and self.calls[key] == 1:
            raise RuntimeError('Synthetic quota exhausted')
        artifacts = []
        if prompt == 'artifact':
            target = state.workspace/'nodes'/str(comp.get_id())/'outputs'/'proof.txt'
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text('immutable synthetic artifact')
            artifacts = [{'name':target.name,'path':str(target.relative_to(state.workspace)),
                          'size':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}]
        return {'text':prompt,'content':{'route':'yes'},'artifacts':artifacts}
    def wait(self, rid, states=('succeeded','failed','interrupted','rejected','cancelled')):
        deadline = time.monotonic()+15
        while time.monotonic()<deadline:
            r = self.client.get('/api/runs/'+rid)
            self.assertEqual(r.status_code,200,r.text)
            data = r.json()
            if data['status'] in states and rid not in core.RUN_CANCEL_EVENTS:
                return data
            if data['status']=='waiting' and 'waiting' in states:
                return data
            time.sleep(.03)
        self.fail('run did not settle: '+rid)
    def start(self, document):
        r = self.client.post('/api/runs',json={'workflow':document})
        self.assertEqual(r.status_code,200,r.text)
        return r.json()['id']
    def resume(self, rid):
        r = self.client.post('/api/runs/'+rid+'/resume',json={})
        self.assertEqual(r.status_code,200,r.text)
        return self.wait(rid)
    def test_01_resume_reuses_success_and_preserves_snapshot(self):
        rid = self.start(chain()); first = self.wait(rid)
        self.assertEqual(first['status'],'failed')
        before = first['snapshot']['workflow']
        final = self.resume(rid)
        self.assertEqual(final['status'],'succeeded',final.get('error'))
        self.assertEqual(self.calls[(rid,'a')],1)
        self.assertEqual(self.calls[(rid,'b')],2)
        self.assertEqual(final['snapshot']['workflow'],before)
        self.assertGreater(len(final['events']),len(first['events']))
    def test_02_success_cannot_resume(self):
        document = chain(); document['nodes'][2]['data']['prompt']='ok'
        rid = self.start(document); self.assertEqual(self.wait(rid)['status'],'succeeded')
        self.assertEqual(self.client.post('/api/runs/'+rid+'/resume',json={}).status_code,409)
    def test_03_tampered_success_artifact_blocks_reuse(self):
        document = chain(); document['nodes'][1]['data']['prompt']='artifact'
        rid = self.start(document); self.assertEqual(self.wait(rid)['status'],'failed')
        target = core.RUNS_ROOT/rid/'workspace'/'nodes'/'a'/'outputs'/'proof.txt'
        target.write_text('tampered')
        response = self.client.post('/api/runs/'+rid+'/resume',json={})
        self.assertIn(response.status_code,[409,422],response.text)
        self.assertEqual(self.calls[(rid,'a')],1)
        self.assertEqual(self.calls[(rid,'b')],1)
    def test_04_condition_reconstructs_routing_without_wrong_branch(self):
        document = chain()
        document['nodes'].insert(2,node('c','condition',field='content.route',operator='equals',expected='yes'))
        document['nodes'].append(node('wrong','analyzer',cli='codex',prompt='must-not-run'))
        document['edges']=[edge('s','a'),edge('a','c'),edge('c','b','true'),edge('c','wrong','false'),edge('b','o'),edge('wrong','o')]
        rid = self.start(document); self.assertEqual(self.wait(rid)['status'],'failed')
        self.assertEqual(self.resume(rid)['status'],'succeeded')
        self.assertNotIn((rid,'wrong'),self.calls)
        self.assertEqual(self.calls[(rid,'a')],1)
    def test_05_blackbox_resumes_at_internal_node(self):
        child = chain(); child['nodes'][0]=node('s','subflow_input'); child['nodes'][-1]=node('o','subflow_output')
        document=flow([node('source','text',text='x'),node('box','blackbox',workflow=child),node('out','container',export_formats=[])],[edge('source','box'),edge('box','out')])
        rid=self.start(document);self.assertEqual(self.wait(rid)['status'],'failed')
        self.assertEqual(self.resume(rid)['status'],'succeeded')
        self.assertEqual(self.calls[(rid,'box__a')],1)
        self.assertEqual(self.calls[(rid,'box__b')],2)
    def test_06_human_rejection_cannot_be_resumed(self):
        document=chain();document['nodes'].insert(2,node('h','human',content='review me'))
        document['edges']=[edge('s','a'),edge('a','h'),edge('h','b'),edge('b','o')]
        rid=self.start(document);self.wait(rid,('waiting',))
        r=self.client.post('/api/runs/'+rid+'/approvals/h',json={'decision':'reject','note':'stop'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.wait(rid)['status'],'rejected')
        self.assertEqual(self.client.post('/api/runs/'+rid+'/resume',json={}).status_code,409)
        self.assertNotIn((rid,'b'),self.calls)
    def test_07_approved_checkpoint_not_prompted_again(self):
        document=chain();document['nodes'].insert(2,node('h','human',content='review me'))
        document['edges']=[edge('s','a'),edge('a','h'),edge('h','b'),edge('b','o')]
        rid=self.start(document);self.wait(rid,('waiting',))
        r=self.client.post('/api/runs/'+rid+'/approvals/h',json={'decision':'approve','note':'approved synthetic'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.wait(rid)['status'],'failed')
        self.assertEqual(self.resume(rid)['status'],'succeeded')
        self.assertEqual(self.calls[(rid,'a')],1)
    def test_08_restart_pending_human_still_requires_confirmation(self):
        document=chain();document['nodes'][2]['data']['prompt']='ok'
        document['nodes'].insert(2,node('h','human',content='review me'))
        document['edges']=[edge('s','a'),edge('a','h'),edge('h','b'),edge('b','o')]
        rid=self.start(document);self.wait(rid,('waiting',))
        core.init_db()
        self.assertEqual(self.wait(rid)['status'],'interrupted')
        r=self.client.post('/api/runs/'+rid+'/resume',json={})
        self.assertEqual(r.status_code,200,r.text)
        resumed=self.wait(rid,('waiting',))
        self.assertNotIn((rid,'b'),self.calls)
        self.assertEqual(resumed['approvals'][0]['status'],'pending')
        r=self.client.post('/api/runs/'+rid+'/approvals/h',json={'decision':'approve'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.wait(rid)['status'],'succeeded')
        self.assertEqual(self.calls[(rid,'a')],1)
    def test_09_revoked_grant_blocks_resume_before_cli(self):
        folder=ROOT/'grant';folder.mkdir(exist_ok=True)
        r=self.client.post('/api/grants',json={'path':str(folder)})
        self.assertEqual(r.status_code,200,r.text);gid=r.json()['id']
        document=chain();document['nodes'][-1]['data']['grant_id']=gid
        rid=self.start(document);self.assertEqual(self.wait(rid)['status'],'failed')
        self.assertEqual(self.client.delete('/api/grants/'+gid).status_code,200)
        r=self.client.post('/api/runs/'+rid+'/resume',json={})
        self.assertIn(r.status_code,[409,422],r.text)
        self.assertEqual(self.calls[(rid,'b')],1)
    def test_10_partial_export_resume_keeps_published_first_output(self):
        folder=ROOT/'partial-export';folder.mkdir(exist_ok=True)
        r=self.client.post('/api/grants',json={'path':str(folder)})
        self.assertEqual(r.status_code,200,r.text);gid=r.json()['id']
        document=flow([node('s','text',text='x'),node('a','analyzer',cli='codex',prompt='ok'),
                       node('o1','container',grant_id=gid,export_formats=['text']),
                       node('o2','container',grant_id=gid,export_formats=['text'])],
                      [edge('s','a'),edge('a','o1'),edge('a','o2')])
        original=shutil.copytree;failed=[]
        def copytree(src,dst,*args,**kwargs):
            if Path(src).name=='o2' and 'exports' in Path(src).parts and not failed:
                failed.append(True);raise OSError('Synthetic export disk interruption')
            return original(src,dst,*args,**kwargs)
        with patch.object(core.shutil,'copytree',side_effect=copytree):
            rid=self.start(document);self.assertEqual(self.wait(rid)['status'],'failed')
        self.assertTrue(failed)
        first=folder/'kxy'/rid/'o1'/'result.txt'
        self.assertTrue(first.is_file());before=(first.read_bytes(),first.stat().st_mtime_ns)
        final=self.resume(rid);self.assertEqual(final['status'],'succeeded',final.get('error'))
        self.assertEqual(self.calls[(rid,'a')],1)
        self.assertEqual((first.read_bytes(),first.stat().st_mtime_ns),before)
        self.assertEqual((folder/'kxy'/rid/'o2'/'result.txt').read_text(),'ok')
    def test_11_real_subprocess_retry_mounts_skill_and_copies_upstream_file(self):
        self.patch.stop()
        counts_path=ROOT/'subprocess-counts.json'
        script=ROOT/'synthetic-codex'
        script.write_text('#!/usr/bin/env python3\n'+f'''import sys,json,pathlib
if '--version' in sys.argv: print('V8 synthetic CLI');sys.exit()
prompt=sys.argv[-1]
counts_file=pathlib.Path({str(counts_path)!r})
counts=json.loads(counts_file.read_text()) if counts_file.exists() else {{}}
counts[prompt]=counts.get(prompt,0)+1;counts_file.write_text(json.dumps(counts))
context=json.loads(pathlib.Path('input-context.json').read_text())
if prompt=='child-retry':
    assert list(pathlib.Path('skills').rglob('SKILL.md')), 'Skill missing in retry workspace'
    artifact=context['inputs'][0]['artifacts'][0]
    assert pathlib.Path(artifact['path']).read_text()=='synthetic subprocess artifact'
    if counts[prompt]==1: print('Synthetic quota failure');sys.exit(7)
pathlib.Path('outputs/proof.txt').write_text('synthetic subprocess artifact')
pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(prompt)
print(json.dumps({{'type':'item.completed','item':{{'type':'agent_message','text':prompt}}}}))
''')
        script.chmod(0o755)
        skill=ROOT/'retry-skill';skill.mkdir()
        (skill/'SKILL.md').write_text('---\nname: v8-retry-skill\ndescription: Synthetic retry fixture\n---\nRead the attached synthetic file.\n')
        r=self.client.post('/api/skills/import-path',json={'path':str(skill)})
        self.assertEqual(r.status_code,200,r.text);sid=r.json()['id']
        document=chain();document['nodes'][1]['data']['prompt']='parent-file'
        document['nodes'][2]['data'].update(prompt='child-retry',skill_ids=[sid])
        with patch.dict(os.environ,{'KXY_CODEX_BIN':str(script)}),patch.object(core,'prepare_headless_environment',side_effect=lambda agent,workspace,**kwargs:{'PATH':os.environ['PATH'],'HOME':str(workspace)}):
            rid=self.start(document);first=self.wait(rid);self.assertEqual(first['status'],'failed')
            final=self.resume(rid);self.assertEqual(final['status'],'succeeded',final.get('error'))
        self.assertEqual(json.loads(counts_path.read_text()),{'parent-file':1,'child-retry':2})
        self.assertTrue(any(a['name']=='proof.txt' for a in final['output_manifest']['artifacts']))
        for artifact in final['output_manifest']['artifacts']:
            response=self.client.get(artifact['url'])
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(hashlib.sha256(response.content).hexdigest(),artifact['sha256'])
    def test_12_blackbox_preset_keeps_boundary_nodes_and_local_model_reference(self):
        child=flow([node('entry','subflow_input'),node('a','analyzer',cli='codex',prompt='x',credential_id='local-reference-only'),
                    node('exit','subflow_output')],[edge('entry','a'),edge('a','exit')])
        r=self.client.post('/api/presets',json={'kind':'blackbox','name':'V8 box','config':{'label':'V8 box','workflow':child}})
        self.assertEqual(r.status_code,200,r.text)
        saved=r.json()['config']['workflow']
        self.assertEqual(saved['edges'],child['edges'])
        self.assertEqual(saved['nodes'][1]['data']['credential_id'],'local-reference-only')
    def test_13_legacy_analyzers_are_present_once_in_generic_catalog(self):
        r=self.client.post('/api/analyzers',json={'name':'V8 legacy analyzer','config':{'prompt':'x','cli':'codex'}})
        self.assertEqual(r.status_code,200,r.text);identifier=r.json()['id']
        rows=self.client.get('/api/presets').json()
        selected=[item for item in rows if item['id']==identifier]
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]['kind'],'analyzer')
    def test_14_nested_literal_secret_rejected(self):
        child=flow([node('entry','subflow_input'),node('a','analyzer',cli='codex',prompt='x',api_key='v8-fake-literal-secret'),
                    node('exit','subflow_output')],[edge('entry','a'),edge('a','exit')])
        r=self.client.post('/api/presets',json={'kind':'blackbox','name':'bad','config':{'workflow':child}})
        self.assertEqual(r.status_code,422,r.text)
        self.assertNotIn('v8-fake-literal-secret',r.text)
    def test_15_resume_rejected_until_old_worker_finishes_cleanup(self):
        arrived=threading.Event();release=threading.Event();original=core.append_event
        def append(rid,kind,payload):
            result=original(rid,kind,payload)
            if kind=='run_finished' and payload.get('status')=='failed':
                arrived.set();release.wait(10)
            return result
        try:
            with patch.object(core,'append_event',side_effect=append):
                rid=self.start(chain());self.assertTrue(arrived.wait(10))
                r=self.client.post('/api/runs/'+rid+'/resume',json={})
                self.assertEqual(r.status_code,409,r.text)
                release.set();self.wait(rid)
            self.assertEqual(self.resume(rid)['status'],'succeeded')
        finally:release.set()
    def test_16_motion_migration_is_once_only_and_preserves_zero(self):
        for old,new in [('100',30),('50',15),('0',0),('broken',30)]:
            with self.subTest(old=old):
                with core.connect_db() as db:
                    db.execute('DELETE FROM settings WHERE key=?',(core.MOTION_SCALE_V8_MIGRATION_KEY,))
                    db.execute("INSERT INTO settings(key,value) VALUES ('motion_intensity',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(old,))
                core.init_db()
                self.assertEqual(self.client.get('/api/settings').json()['motion_intensity'],new)
                core.init_db()
                self.assertEqual(self.client.get('/api/settings').json()['motion_intensity'],new)
        self.assertEqual(self.client.put('/api/settings',json={'motion_intensity':100}).status_code,200)
        core.init_db();self.assertEqual(self.client.get('/api/settings').json()['motion_intensity'],100)

if __name__=='__main__':unittest.main(verbosity=2)
