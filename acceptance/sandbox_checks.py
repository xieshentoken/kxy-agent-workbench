"""macOS seatbelt check; run outside another seatbelt (nested sandbox is denied by macOS)."""
import os,sys,tempfile,subprocess,json
from pathlib import Path
root=Path(tempfile.mkdtemp(prefix='kxy-seatbelt-check-')); work=root/'workspace'; work.mkdir()
os.environ['KXY_DATA_ROOT']=str(root/'data'); os.environ['LANGFLOW_CONFIG_DIR']=str(root/'lfx'); os.environ['DO_NOT_TRACK']='true'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import app as m
probe='''import sys,socket,json,subprocess
from pathlib import Path
Path('inside.txt').write_text('allowed')
try:
    Path(sys.argv[1]).write_text('must be blocked')
    write_blocked=False
except PermissionError: write_blocked=True
try:
    s=socket.socket();s.connect(('1.1.1.1',443));network_blocked=False
except PermissionError: network_blocked=True
except OSError: network_blocked=False
print(json.dumps({'inside_written':True,'outside_write_blocked':write_blocked,'network_blocked':network_blocked}))
'''
argv,profile=m.sandbox_argv([sys.executable,'-c',probe,str(root/'outside.txt')],work,None,False,'opencode')
result=subprocess.run(argv,cwd=work,capture_output=True,text=True,timeout=15)
print(result.stdout.strip());print(result.stderr.strip()) if result.returncode else None
assert result.returncode==0
checks=json.loads(result.stdout);assert all(checks.values()) and not (root/'outside.txt').exists()
print('PASS actual OS sandbox write and network denial')
