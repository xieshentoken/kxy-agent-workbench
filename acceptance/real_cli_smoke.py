"""Opt-in real CLI acceptance. Only purpose-created synthetic inputs are sent.
KXY_SMOKE_CLI=codex|opencode KXY_SMOKE_MODEL=... python acceptance/real_cli_smoke.py
Uses an isolated data root; writes full evidence locally, prints no credentials.
"""
import json, os, sys, tempfile, time
from pathlib import Path
root=Path(tempfile.mkdtemp(prefix='kxy-real-'))
os.environ['KXY_DATA_ROOT']=str(root/'data')
os.environ['LANGFLOW_CONFIG_DIR']=str(root/'lfx')
os.environ['DO_NOT_TRACK']='true'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import app as m
from fastapi.testclient import TestClient
cli=os.environ.get('KXY_SMOKE_CLI','codex')
model=os.environ.get('KXY_SMOKE_MODEL','gpt-5.4-mini' if cli=='codex' else 'opencode/big-pickle')
with TestClient(m.app) as client:
    asset=client.post('/api/files',files={'file':('synthetic-revenue.md',b'Company A revenue: 20 million in 2025. Company B: 12 million in 2025. Margins unknown.\n')}).json()
    skill_dir=root/'fixture-skill'; skill_dir.mkdir(); (skill_dir/'references').mkdir()
    (skill_dir/'SKILL.md').write_text('---\nname: fixture-skill\ndescription: Preserve missing revenue context and use a marker.\n---\nRead references/method.md, then include KXY_SKILL_LOADED in your final answer.\n')
    (skill_dir/'references/method.md').write_text('Revenue is not profit. Explicitly say margins are unknown.\n')
    skill=client.post('/api/skills/import-path',json={'path':str(skill_dir)}).json()
    export=root/'export'; export.mkdir()
    grant=client.post('/api/grants',json={'path':str(export)}).json()
    workflow={'version':'kxy.workflow.v1','name':f'{cli} synthetic acceptance','nodes':[
        {'id':'source','type':'file','data':{'file_id':asset['id']}},
        {'id':'analysis','type':'analyzer','data':{'cli':cli,'model':model,'effort':'low' if cli=='codex' else '', 'network':True,'timeout':150,'skill_ids':[skill['id']], 'prompt':'Summarize ONLY the supplied revenue data in two sentences. Use the selected skill. Write a small result.txt in outputs/ containing your same summary. Do not browse the web or inspect unrelated files.'}},
        {'id':'output','type':'container','data':{'grant_id':grant['id']}}
    ],'edges':[{'source':'source','target':'analysis'},{'source':'analysis','target':'output'}]}
    response=client.post('/api/runs',json={'workflow':workflow}); response.raise_for_status(); run_id=response.json()['id']
    last=None
    for _ in range(190):
        run=client.get('/api/runs/'+run_id).json()
        if run['status']!=last: print(cli,run_id,run['status'],flush=True); last=run['status']
        if run['status'] in {'succeeded','failed','cancelled','interrupted'}: break
        time.sleep(1)
    (root/'evidence.json').write_text(json.dumps(run,ensure_ascii=False,indent=2))
    print('evidence',root/'evidence.json',flush=True)
    if run['status']!='succeeded':
        print('error',run.get('error')); sys.exit(1)
    output=next(item for item in run['nodes'] if item['node_id']=='output')['output']
    assert 'KXY_SKILL_LOADED' in output['text'], output['text']
    assert '20' in output['text'] and '12' in output['text'], output['text']
    for artifact in run['output_manifest']['artifacts']:
        downloaded=client.get(artifact['url']); assert downloaded.status_code==200
    assert (export/'kxy'/run_id/'output'/'result.md').is_file()
    print('PASS',cli,'skill marker, revenue, exported output, downloads',flush=True)
