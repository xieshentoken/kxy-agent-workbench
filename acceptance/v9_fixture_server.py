"""Isolated V9 browser acceptance: real API/LFX, synthetic analyzer only."""
import json, os, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("KXY_V9_FIXTURE_DATA") or tempfile.mkdtemp(prefix="kxy-v9-browser-"))
os.environ.update(KXY_DATA_ROOT=str(DATA), LANGFLOW_CONFIG_DIR=str(DATA/"lfx"), DO_NOT_TRACK="true")
sys.path.insert(0, str(ROOT))
from backend import app as core
from fastapi.staticfiles import StaticFiles
import uvicorn

def synthetic_execute(state, prompt, payloads, component):
    number = state.loop_round_no or 1
    if "V9_REVIEW" in prompt:
        review = {"passed": number >= 2, "issues": [] if number >= 2 else ["补充证据来源"], "next_action": "完成" if number >= 2 else "加入来源后再次提交"}
        return {"text": json.dumps(review, ensure_ascii=False), "content": review, "artifacts": []}
    return {"text": f"合成研究结果，第 {number} 轮。" + ("已补充来源。" if number >= 2 else "等待补充来源。"), "artifacts": []}

core.execute_cli = synthetic_execute
core.probe_cli = lambda name: {"name": name, "available": True, "status": "READY", "version": "V9 synthetic browser inventory"}
assert core.app.routes[-1].name == "frontend"
core.app.routes[-1].app = StaticFiles(directory=ROOT/"frontend"/"dist-v9", html=True)
if __name__ == "__main__":
    print("Isolated fixture data:", DATA, flush=True)
    uvicorn.run(core.app, host="127.0.0.1", port=8724)
