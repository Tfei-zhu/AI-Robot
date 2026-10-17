"""Verify/recalculate sealed v1 from its own source, never today's scorer."""
import hashlib,json,os,subprocess,sys,tarfile,tempfile
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2];OLD=OUT.parent/'s8-20261017'
sha=lambda b:hashlib.sha256(b).hexdigest()
snapshot=json.loads((OLD/'source-after.json').read_text())
with tempfile.TemporaryDirectory(prefix='s81-v1-',dir='/private/tmp') as folder:
    dest=Path(folder)
    with tarfile.open(OLD/'source-final.tar.gz') as tar:
        members=tar.getmembers()
        assert all(m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts for m in members)
        actual={m.name:sha(tar.extractfile(m).read()) for m in members}
        assert actual==snapshot['files_sha256']
        tar.extractall(dest,filter='data')
    code='''import json,sys
from pathlib import Path
from eval.multi_agent_protocol import load_freeze,aggregate
from eval.run_multi_agent_eval import audit_rows
old=Path(sys.argv[1]);frozen=load_freeze(old/'freeze-v1');results={}
for split in ('dev','holdout'):
    rows=audit_rows(old/split,frozen);saved=json.loads((old/split/'report.json').read_text())
    assert aggregate(rows)==saved['metrics']
    results[split]=dict(runs=len(rows),actual_calls=sum(len(r['calls']) for r in rows),successes={a:m['independent_successes'] for a,m in saved['metrics'].items()})
print(json.dumps(dict(freeze_hash=frozen['freeze_hash'],results=results)))
'''
    env=dict(os.environ);env['PYTHONPATH']=str(OUT.parent/'s0.1-20261017/offline_guard')+os.pathsep+str(dest)
    proc=subprocess.run([sys.executable,'-c',code,str(OLD)],cwd=dest,env=env,text=True,capture_output=True)
    if proc.returncode:raise RuntimeError(proc.stdout+proc.stderr)
    result=dict(status='passed',archived_source_hash=snapshot['source_manifest_sha256'],archived_files=len(actual),
                recalculation=json.loads(proc.stdout),provider_requests=0)
    (OUT/'archive-proof.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
