"""S9 offline execution recorder. All mutations remain in this evidence directory."""
import datetime,fcntl,hashlib,json,os,runpy,subprocess,time
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
base=runpy.run_path(str(OUT.parent/'s0-20261017/run_baseline.py'))
env=dict(base['env']);env.update(PYTHONPATH=os.pathsep.join([str(OUT.parent/'s0.1-20261017/offline_guard'),str(ROOT),str(ROOT/'tests')]),
 TIKTOKEN_CACHE_DIR=str(ROOT/'.venv/tiktoken-cache'),S01_NETWORK_AUDIT=str(OUT/'network-audit.txt'),AIROBOT_GO_MULTI_AGENT_ENABLED='false')
PYTHON=str(ROOT/'.venv/bin/python')
def run(label,argv,timeout=600,extra=None):
    with (OUT/'recorder.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=OUT/'commands.json';rows=json.loads(path.read_text()) if path.exists() else []
        target=OUT/f'{len(rows)+1:02d}-{label}.txt';before=base['snapshot'](ROOT)
        start=datetime.datetime.now(datetime.timezone.utc).isoformat();clock=time.monotonic()
        with target.open('x') as log:
            try:code=subprocess.run(argv,cwd=ROOT,env={**env,**(extra or {})},stdout=log,stderr=subprocess.STDOUT,timeout=timeout).returncode
            except subprocess.TimeoutExpired:log.write('\nHARNESS_TIMEOUT\n');code=124
        after=base['snapshot'](ROOT)
        row=dict(label=label,argv=argv,started_utc=start,elapsed_seconds=round(time.monotonic()-clock,3),exit_code=code,
          output=target.name,output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),head=after['head'],
          source_manifest_sha256=after['source_manifest_sha256'],tracked_diff_sha256=after['tracked_diff_sha256'],
          source_unchanged=before['files_sha256']==after['files_sha256'],environment_overrides=extra or {},multi_agent_environment='false')
        path.write_text(json.dumps([*rows,row],ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(row,ensure_ascii=False),flush=True);print(target.read_text()[-6000:],flush=True)
        return code
