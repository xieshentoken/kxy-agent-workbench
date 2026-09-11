"""Parent-owned V5 public contracts; isolated data, no real model or key."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TEMP = Path(tempfile.mkdtemp(prefix='kxy-v5-supervisor-'))
os.environ['KXY_DATA_ROOT'] = str(TEMP/'data')
os.environ['LANGFLOW_CONFIG_DIR'] = str(TEMP/'lfx')
os.environ['DO_NOT_TRACK'] = 'true'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as core
from backend import agent_config as cfg
from fastapi.testclient import TestClient

class V5Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = TestClient(core.app)
        cls.client = cls.context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.context.__exit__(None, None, None)

    def setUp(self):
        with core.connect_db() as db:
            db.execute('DELETE FROM agent_models')
            db.execute('DELETE FROM credentials')
            db.execute("INSERT INTO credentials VALUES (?,?,?,?,?,?)", ('fixture-credential','openai','synthetic-ref','https://example.invalid/v1','OPENAI_API_KEY',core.utc_now()))
        self.a = cfg._native_model_record('codex','fixture-a',efforts=['low','high','max'],default_effort='high',discovery_source='SYNTHETIC V5')
        self.b = cfg._native_model_record('codex','fixture-b',efforts=['minimal'],default_effort='minimal',discovery_source='SYNTHETIC V5')
        self.unknown = cfg._native_model_record('codex','fixture-unknown',efforts=[],discovery_source='SYNTHETIC V5')
        self.foreign = cfg._native_model_record('claude','fixture-c',efforts=['medium'],default_effort='medium',discovery_source='SYNTHETIC V5')
        cfg._store_native_records('codex',[self.a,self.b,self.unknown])
        cfg._store_native_records('claude',[self.foreign])

    def payload(self,record=None,**changes):
        record = record or self.a
        return dict(cli_id=record['cli_id'],model=record['model'],source='manual',alias='V5 selected max',native_model_ref=record['id'],default_effort=record.get('default_effort'),**changes)

    def create(self,payload):
        r = self.client.post('/api/agent-models',json=payload)
        self.assertEqual(r.status_code,200,r.text)
        return r.json()

    def reject(self,payload):
        r = self.client.post('/api/agent-models',json=payload)
        self.assertIn(r.status_code,(400,422),r.text)

    def test_01_selected_model_effort_persists_and_resolves(self):
        p=self.payload();p['default_effort']='max'
        saved=self.create(p)
        self.assertEqual(saved['efforts'],['low','high','max'])
        self.assertEqual(saved['default_effort'],'max')
        binding=cfg.snapshot_model_binding({'cli':'codex','model_ref':saved['id']})
        self.assertEqual((binding['cli'],binding['alias'],binding['model'],binding['selected_effort']),('codex','V5 selected max','fixture-a','max'))
        self.assertIsNone(binding['credential_id'])
        argv=cfg.build_headless_command('codex','SYNTHETIC',TEMP,executable='/bin/echo',model=binding['model'],effort=binding['selected_effort'])
        self.assertEqual(argv[argv.index('--model')+1],'fixture-a')
        self.assertIn('model_reasoning_effort="max"',argv)

    def test_02_two_configs_for_same_model_keep_distinct_identity(self):
        p=self.payload();p['default_effort']='low';p['alias']='V5 low'
        low=self.create(p)
        p['default_effort']='max';p['alias']='V5 max'
        high=self.create(p)
        self.assertNotEqual(low['id'],high['id'])
        self.assertEqual(cfg.resolve_model_binding({'cli':'codex','model_ref':low['id']})['selected_effort'],'low')
        self.assertEqual(cfg.resolve_model_binding({'cli':'codex','model_ref':high['id']})['selected_effort'],'max')

    def test_03_invalid_effort_cannot_be_added_by_client(self):
        p=self.payload();p.update(efforts=['ultra'],default_effort='ultra')
        self.reject(p)

    def test_04_cross_agent_catalog_ref_rejected(self):
        p=self.payload();p['native_model_ref']=self.foreign['id']
        self.reject(p)

    def test_05_mismatched_or_missing_model_ref_rejected(self):
        p=self.payload();p['model']='fixture-b';self.reject(p)
        p=self.payload();p['native_model_ref']='native-codex-missing';self.reject(p)

    def test_06_login_record_cannot_bind_api_credential(self):
        p=self.payload();p['credential_id']='fixture-credential';self.reject(p)

    def test_07_unknown_effort_stays_unknown(self):
        saved=self.create(self.payload(self.unknown))
        self.assertEqual(saved['efforts'],[])
        self.assertFalse(saved['default_effort'])
        self.assertFalse(cfg.resolve_model_binding({'cli':'codex','model_ref':saved['id']})['selected_effort'])

    def test_08_discovery_refresh_preserves_created_config(self):
        p=self.payload();p['default_effort']='max';saved=self.create(p)
        fresh=dict(self.a);fresh['alias']='changed native label';fresh['default_effort']='low'
        cfg._store_native_records('codex',[fresh,self.b,self.unknown])
        actual=next(m for m in self.client.get('/api/agent-models').json() if m['id']==saved['id'])
        self.assertEqual((actual['alias'],actual['default_effort']),('V5 selected max','max'))

    def test_09_node_effort_override_is_local_and_validated(self):
        saved=self.create(self.payload())
        self.assertEqual(cfg.resolve_model_binding({'cli':'codex','model_ref':saved['id'],'effort':'max'})['selected_effort'],'max')
        with self.assertRaises(cfg.AgentConfigError): cfg.resolve_model_binding({'cli':'codex','model_ref':saved['id'],'effort':'ultra'})
        actual=next(m for m in cfg.list_agent_models() if m['id']==saved['id'])
        self.assertEqual(actual['default_effort'],'high')

    def test_10_deleted_or_foreign_binding_never_falls_back(self):
        saved=self.create(self.payload())
        with self.assertRaises(cfg.AgentConfigError): cfg.resolve_model_binding({'cli':'claude','model_ref':saved['id']})
        self.client.delete('/api/agent-models/'+saved['id'])
        with self.assertRaises(cfg.AgentConfigError): cfg.resolve_model_binding({'cli':'codex','model_ref':saved['id']})

    def test_11_api_and_legacy_credentials_remain_compatible(self):
        for source in ('api','manual'):
            saved=self.create({'cli_id':'codex','model':'fixture-a','alias':source,'source':source,'credential_id':'fixture-credential','efforts':['high'],'default_effort':'high'})
            binding=cfg.resolve_model_binding({'cli':'codex','model_ref':saved['id']})
            self.assertEqual(binding['credential_id'],'fixture-credential')
            self.assertEqual(binding['selected_effort'],'high')

    def test_12_workflow_save_reload_keeps_exact_binding(self):
        saved=self.create(self.payload())
        data={'cli':'codex','model_ref':saved['id'],'effort':'max','network':True,'prompt':'SYNTHETIC'}
        flow={'version':'kxy.workflow.v1','name':'V5 persistence fixture','nodes':[{'id':'analysis','type':'analyzer','position':{'x':0,'y':0},'data':data}],'edges':[]}
        r=self.client.post('/api/workflows',json={'workflow':flow});self.assertEqual(r.status_code,200,r.text)
        actual=self.client.get('/api/workflows/'+r.json()['id']).json()['workflow']['nodes'][0]['data']
        self.assertEqual(actual['model_ref'],saved['id']);self.assertEqual(actual['effort'],'max')
        self.assertEqual(cfg.resolve_model_binding(actual)['model'],'fixture-a')

    def test_13_edit_config_preserves_binding_and_validates_effort(self):
        saved=self.create(self.payload())
        r=self.client.put('/api/agent-models/'+saved['id'],json={'alias':'Edited deep','default_effort':'max'})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['model'],'fixture-a')
        self.assertEqual(cfg.resolve_model_binding({'cli':'codex','model_ref':saved['id']})['selected_effort'],'max')
        bad=self.client.put('/api/agent-models/'+saved['id'],json={'efforts':['ultra'],'default_effort':'ultra'})
        self.assertEqual(bad.status_code,422,bad.text)

    def test_14_update_cannot_attach_credentials_to_login_entry(self):
        saved=self.create(self.payload())
        r=self.client.put('/api/agent-models/'+saved['id'],json={'credential_id':'fixture-credential'})
        self.assertEqual(r.status_code,422,r.text)

if __name__=='__main__':
    unittest.main(verbosity=2)
