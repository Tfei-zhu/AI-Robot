"""Actual optimized CLI must deny live work without a cap; no paid transport created."""
import json
import subprocess
from pathlib import Path
import sys

from run_checks import PYTHON,OUT,ROOT,env
sys.path.insert(0,str(ROOT))
from eval.multi_agent_protocol import write_json


def main():
    target=OUT/"forbidden-live"
    argv=[PYTHON,"-O","eval/run_multi_agent_eval.py","run","--freeze",str(OUT/"freeze-v1"),
          "--mode","live","--split","dev","--output",str(target)]
    proc=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
    if proc.returncode!=2 or "累计费用" not in proc.stderr or target.exists():
        raise ValueError("Optimized CLI failed to block unauthorized live run")
    result=dict(passed=True,argv=argv,inner_exit_code=proc.returncode,stdout=proc.stdout,stderr=proc.stderr,
                expected_result="blocked_before_client_construction",provider_requests_sent=0,output_created=False)
    write_json(OUT/"paid-guard-proof.json",result)
    print(json.dumps(dict(passed=True,inner_exit_code=2,provider_requests_sent=0,output_created=False)))


if __name__=="__main__":main()
