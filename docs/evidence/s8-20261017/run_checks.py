"""S8 execution recorder: offline guard, clean credentials, append-only primary outputs."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time

OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
base=runpy.run_path(str(OUT.parent/"s0-20261017/run_baseline.py"))
env=dict(base["env"])
env.update(PYTHONPATH=os.pathsep.join([str(OUT.parent/"s0.1-20261017/offline_guard"),str(ROOT),str(ROOT/"tests")]),
           TIKTOKEN_CACHE_DIR=str(ROOT/".venv/tiktoken-cache"),S01_NETWORK_AUDIT=str(OUT/"network-audit.txt"))
PYTHON=str(ROOT/".venv/bin/python")


def run(label,argv,*,timeout=300,extra=None):
    path=OUT/"commands.json";rows=json.loads(path.read_text()) if path.exists() else []
    index=len(rows)+1;output_path=OUT/f"{index:02d}-{label}.txt"
    before=base["snapshot"](ROOT);started=datetime.datetime.now(datetime.timezone.utc).isoformat();clock=time.monotonic()
    with output_path.open("x") as log:
        try:
            proc=subprocess.run(argv,cwd=ROOT,env={**env,**(extra or {})},stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
            code=proc.returncode
        except subprocess.TimeoutExpired:
            log.write("\nHARNESS_TIMEOUT\n");code=124
    after=base["snapshot"](ROOT)
    row=dict(label=label,argv=argv,exit_code=code,started_utc=started,elapsed_seconds=round(time.monotonic()-clock,3),
        output=output_path.name,output_sha256=hashlib.sha256(output_path.read_bytes()).hexdigest(),
        source_manifest_sha256=after["source_manifest_sha256"],tracked_diff_sha256=after["tracked_diff_sha256"],
        head=after["head"],source_unchanged=before["files_sha256"]==after["files_sha256"],environment_overrides=extra or {})
    row["added_source_paths"]=sorted(set(after["files_sha256"])-set(before["files_sha256"]))
    row["modified_source_paths"]=sorted(p for p in before["files_sha256"] if after["files_sha256"].get(p)!=before["files_sha256"][p])
    path.write_text(json.dumps([*rows,row],ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(row,ensure_ascii=False),flush=True);print(output_path.read_text()[-6000:],flush=True)
    return code


if __name__=="__main__":
    mode=sys.argv[1];runner="eval/run_multi_agent_eval.py"
    count=len(json.loads((OUT/"commands.json").read_text()))+1 if (OUT/"commands.json").exists() else 1
    if mode in {"unit","all-docker"}:
        tests=["tests/test_multi_agent_eval.py"] if mode=="unit" else ["tests"]
        sys.exit(run(mode,[PYTHON,"-m","pytest",*tests,"-q","-ra","--junitxml="+str(OUT/f"{count:02d}-{mode}.xml")],
            timeout=600,extra={"AIROBOT_TEST_DOCKER":"1"} if mode=="all-docker" else None))
    if mode=="freeze":sys.exit(run(mode,[PYTHON,runner,"freeze","--output",str(OUT/"freeze-v1")]))
    if mode in {"dev","holdout","smoke-cancel","smoke-timeout"}:
        split="holdout" if mode=="holdout" else "dev"
        argv=[PYTHON,runner,"run","--freeze",str(OUT/"freeze-v1"),"--mode","fixtures","--split",split,"--output",str(OUT/mode)]
        if mode=="holdout":argv += ["--dev-report",str(OUT/"dev/report.json")]
        if mode.startswith("smoke"):
            argv += ["--limit","1","--inject",mode.split("-")[1]]
        sys.exit(run(mode,argv,timeout=1800))
    if mode=="prepare-live":
        sys.exit(run(mode,[PYTHON,runner,"prepare-live","--freeze",str(OUT/"freeze-v1"),"--output",str(OUT/"live-preflight.json")]))
    if mode in {"docker-version","containers-after"}:
        argv=["docker","version"] if mode=="docker-version" else ["docker","ps","-a","--filter","name=airobot-go-","--format","{{.Names}} {{.Status}}"]
        sys.exit(run(mode,argv))
    raise SystemExit("unknown mode")
