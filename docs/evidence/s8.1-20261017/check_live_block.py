"""Actual optimized CLI must reject before constructing clients or output."""
import json,subprocess,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
target=OUT/'forbidden-live-output'
cmd=[sys.executable,'-O','eval/run_multi_agent_eval.py','run','--mode','live','--split','dev','--freeze',str(OUT/'freeze-v2'),'--output',str(target)]
proc=subprocess.run(cmd,cwd=ROOT,text=True,capture_output=True)
assert proc.returncode==2 and '累计费用' in proc.stderr and not target.exists(),(proc.returncode,proc.stdout,proc.stderr)
result=dict(status='blocked_as_required',inner_argv=cmd,inner_exit_code=proc.returncode,error=proc.stderr,
            output_created=target.exists(),provider_requests=0)
(OUT/'paid-guard-proof.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
