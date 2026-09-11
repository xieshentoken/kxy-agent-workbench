"""Independent V7 API contracts. Isolated DB; no real user credential."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(tempfile.mkdtemp(prefix='kxy-v7-supervisor-'))
os.environ.update(KXY_DATA_ROOT=str(ROOT/'data'),LANGFLOW_CONFIG_DIR=str(ROOT/'lfx'),DO_NOT_TRACK='true')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import app as core
from fastapi.testclient import TestClient

class V7Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context=TestClient(core.app);cls.client=cls.context.__enter__()
    @classmethod
    def tearDownClass(cls):cls.context.__exit__(None,None,None)
    def setUp(self):
        with core.connect_db() as db:
            db.execute("DELETE FROM settings WHERE key='motion_intensity'")
            db.execute('DELETE FROM analyzers')
    def test_01_default_and_zero_are_distinct(self):
        self.assertEqual(self.client.get('/api/settings').json().get('motion_intensity'),100)
        response=self.client.put('/api/settings',json={'motion_intensity':0})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['motion_intensity'],0)
        self.assertEqual(self.client.get('/api/settings').json()['motion_intensity'],0)
    def test_02_range_and_null_rejected(self):
        for value in [-1,101,None,'not-a-number',[],{}]:
            with self.subTest(value=value):
                response=self.client.put('/api/settings',json={'motion_intensity':value})
                self.assertEqual(response.status_code,422,response.text)
    def test_03_partial_legacy_update_preserves_strength(self):
        self.assertEqual(self.client.put('/api/settings',json={'motion_intensity':27}).status_code,200)
        response=self.client.put('/api/settings',json={'accent':'#997766'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['motion_intensity'],27)
    def test_04_legacy_string_zero_and_bad_value(self):
        with core.connect_db() as db:
            db.execute('INSERT INTO settings(key,value) VALUES (?,?)',('motion_intensity','0'))
        self.assertEqual(self.client.get('/api/settings').json()['motion_intensity'],0)
        with core.connect_db() as db:db.execute("UPDATE settings SET value='broken' WHERE key='motion_intensity'")
        self.assertEqual(self.client.get('/api/settings').json()['motion_intensity'],100)
    def test_05_new_presets_never_overwrite_by_embedded_config_id(self):
        ids=[]
        for i in range(4):
            r=self.client.post('/api/analyzers',json={'name':f'V7 preset {i}','config':{'id':'same-old-node-id','cli':'codex','prompt':f'Prompt {i}'}})
            self.assertEqual(r.status_code,200,r.text);ids.append(r.json()['id'])
        self.assertEqual(len(set(ids)),4)
        rows=self.client.get('/api/analyzers').json()
        self.assertEqual(len(rows),4)
        self.assertEqual({p['config']['prompt'] for p in rows},{f'Prompt {i}' for i in range(4)})
    def test_06_delete_one_preserves_other_preset(self):
        a=self.client.post('/api/analyzers',json={'name':'A','config':{'prompt':'A'}}).json()
        b=self.client.post('/api/analyzers',json={'name':'B','config':{'prompt':'B'}}).json()
        self.assertEqual(self.client.delete('/api/analyzers/'+a['id']).status_code,200)
        rows=self.client.get('/api/analyzers').json()
        self.assertEqual([r['id'] for r in rows],[b['id']])
    def test_07_keychain_failure_cannot_create_service_record(self):
        with core.connect_db() as db:before=db.execute('SELECT count(*) FROM credentials').fetchone()[0]
        with patch.object(core,'store_keychain_secret',side_effect=RuntimeError('Keychain 100001 test denial')):
            r=self.client.post('/api/credentials/store',json={'name':'V7 failure fixture','provider':'openai','api_format':'openai-responses','api_key':'v7-not-a-real-key','models':[]})
        self.assertEqual(r.status_code,422,r.text)
        self.assertNotIn('v7-not-a-real-key',r.text)
        with core.connect_db() as db:self.assertEqual(db.execute('SELECT count(*) FROM credentials').fetchone()[0],before)
    def test_08_preset_secrets_still_rejected(self):
        r=self.client.post('/api/analyzers',json={'name':'bad','config':{'api_key':'v7-fake-secret'}})
        self.assertEqual(r.status_code,422,r.text)
        self.assertNotIn('v7-fake-secret',r.text)
        self.assertEqual(self.client.get('/api/analyzers').json(),[])
    def test_09_successful_keychain_metadata_is_not_a_permission_error(self):
        with patch.object(core.shutil,'which',return_value='/usr/bin/security'),patch.object(core.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='"svce"="kxy/ref-100001"',stderr='')):
            self.assertTrue(core.keychain_has('ref-100001'))

if __name__=='__main__':unittest.main(verbosity=2)
