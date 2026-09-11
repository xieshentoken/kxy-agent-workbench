"""Opt-in macOS Keychain round trip with a new synthetic item; never prints secret values."""
import os,sys,tempfile,uuid,subprocess
from pathlib import Path
root=Path(tempfile.mkdtemp(prefix='kxy-keychain-check-'));os.environ['KXY_DATA_ROOT']=str(root);os.environ['LANGFLOW_CONFIG_DIR']=str(root/'lfx');os.environ['DO_NOT_TRACK']='true'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import app as m
from fastapi.testclient import TestClient
with TestClient(m.app) as client:
    fake='kxy-synthetic-test-'+uuid.uuid4().hex
    ref=None
    try:
        response=client.post('/api/credentials/store',json={'provider':'acceptance-only','api_key':fake,'env_name':'OPENAI_API_KEY','endpoint':'https://example.invalid/v1'})
        assert response.status_code==200,response.text
        info=response.json();ref=info['credential_ref'];assert fake not in response.text
        assert m.keychain_has(ref)
        assert m.keychain_secret(ref)==fake
        assert fake.encode() not in m.DB_PATH.read_bytes()
        print('PASS native Keychain create, lookup, secret-free API and database',flush=True)
    finally:
        if ref:
            cleanup=subprocess.run(['security','delete-generic-password','-a','kxy','-s','kxy/'+ref],capture_output=True,timeout=10)
            assert cleanup.returncode==0,'Could not delete the synthetic Keychain item'
            print('PASS synthetic Keychain item removed',flush=True)
