"""Two OS processes + restart compete for one synthetic fee reservation; no API calls."""
import json
from pathlib import Path
import subprocess
import sys

from run_checks import ROOT,OUT,PYTHON,env
sys.path.insert(0,str(ROOT))
from eval.multi_agent_protocol import CostLedger,write_json

CHILD='''import json,sys
from eval.multi_agent_protocol import CostLedger
ledger=CostLedger(sys.argv[1],"1","TEST",dict(input_ceiling_per_million="1",output_ceiling_per_million="1"),"synthetic-model")
try:
 ticket=ledger.reserve(1000000,0,"process-proof")
 print(json.dumps(dict(status="reserved",ticket=ticket)))
except RuntimeError as exc:
 print(json.dumps(dict(status="blocked",error=str(exc))))
'''


def main():
    path=OUT/"synthetic-cost-ledger.json"
    if path.exists():raise ValueError("Never overwrite earlier cost proof")
    argv=[PYTHON,"-c",CHILD,str(path)]
    processes=[subprocess.Popen(argv,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    results=[]
    for process in processes:
        stdout,stderr=process.communicate(timeout=15)
        if process.returncode!=0:raise ValueError(stderr)
        results.append(json.loads(stdout))
    if sorted(r["status"] for r in results)!=["blocked","reserved"]:raise ValueError("Two processes overspent one-slot budget")
    restarted=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=15)
    if restarted.returncode!=0 or json.loads(restarted.stdout)["status"]!="blocked":raise ValueError("Restart refunded a pending reservation")
    ledger=CostLedger(path,"1","TEST",dict(input_ceiling_per_million="1",output_ceiling_per_million="1"),"synthetic-model")
    state=json.loads(path.read_text());ticket=state["requests"][0]["ticket"]
    ledger.finish(ticket,None)
    state=json.loads(path.read_text())
    if state["requests"][0]["charged_reserve"]!="1" or state["requests"][0]["actual_estimate"] is not None:
        raise ValueError("Unknown cost was converted to zero")
    result=dict(passed=True,argv=argv,competing_processes=results,restart=json.loads(restarted.stdout),
        provider_requests_sent=0,scope="synthetic TEST budget units only, not real fees",unknown_reserve_retained=True)
    write_json(OUT/"cost-process-proof.json",result)
    print(json.dumps(dict(passed=True,provider_requests_sent=0,process_outcomes=[r["status"] for r in results],restart="blocked")))


if __name__=="__main__":main()
