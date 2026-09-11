"""Two-phase actual server restart acceptance against isolated port 8724."""
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

BASE='http://127.0.0.1:8724'
DATA=Path('/private/tmp/kxy-v8-browser-data')
STATE=DATA/'restart-check.json'
def api(path, value=None):
    req=Request(BASE+path, data=json.dumps(value).encode() if value is not None else None,
                headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=10) as response:return json.load(response)
def wait(rid, state):
    for _ in range(150):
        r=api('/api/runs/'+rid)
        if r['status']==state:return r
        if r['status'] in {'failed','rejected','cancelled'}:raise AssertionError(r.get('error'))
        time.sleep(.1)
    raise AssertionError('Timed out waiting for '+state)
def node(i,kind,**data):return dict(id=i,type=kind,position=dict(x=0,y=0),data=data)
def edge(a,b):return dict(id=a+'-'+b,source=a,target=b,sourceHandle='result',targetHandle='items')

if sys.argv[1]=='seed':
    workflow=dict(version='kxy.workflow.v1',name='V8 real server restart synthetic',
      nodes=[node('s','text',text='synthetic'),node('a','analyzer',cli='codex',prompt='RESTART_UPSTREAM'),
             node('h','human',content='Approve this same synthetic result after restart'),
             node('b','analyzer',cli='codex',prompt='RESTART_DOWNSTREAM'),node('o','container',export_formats=[])],
      edges=[edge('s','a'),edge('a','h'),edge('h','b'),edge('b','o')])
    rid=api('/api/runs',{'workflow':workflow})['id'];run=wait(rid,'waiting')
    STATE.write_text(json.dumps({'run_id':rid,'snapshot':run['snapshot']['workflow']}))
    print(json.dumps({'run_id':rid,'status':run['status'],'ready_for_process_restart':True}))
elif sys.argv[1]=='verify':
    state=json.loads(STATE.read_text());rid=state['run_id']
    before=api('/api/runs/'+rid);assert before['status']=='interrupted',before['status']
    api('/api/runs/'+rid+'/resume',{})
    paused=wait(rid,'waiting');assert paused['snapshot']['workflow']==state['snapshot']
    counts=json.loads((DATA/'synthetic-counts.json').read_text())
    assert counts[rid+':a']==1 and rid+':b' not in counts
    api('/api/runs/'+rid+'/approvals/h',{'decision':'approve','note':'V8 synthetic acceptance'})
    final=wait(rid,'succeeded')
    counts=json.loads((DATA/'synthetic-counts.json').read_text())
    assert counts[rid+':a']==1 and counts[rid+':b']==1
    assert len(final['attempts'])==2
    report={'run_id':rid,'real_process_restart':True,'original_snapshot_preserved':True,
            'human_approval_required_after_restart':True,'upstream_calls':1,'downstream_calls':1,'attempts':2,'status':'PASS','real_inference':False}
    out=Path(__file__).resolve().parent/'v8-evidence'/'real-restart.json';out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(report,indent=2));print(json.dumps(report))
else:raise SystemExit('Use seed or verify')
