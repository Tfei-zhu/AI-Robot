"""S7 repeatable offline checks. No .env loading, no paid model requests."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
baseline = runpy.run_path(str(OUT.parent / "s0-20261017/run_baseline.py"))
env = dict(baseline["env"])
env.update(PYTHONPATH=os.pathsep.join([str(OUT.parent / "s0.1-20261017/offline_guard"), str(ROOT), str(ROOT / "tests")]),
           TIKTOKEN_CACHE_DIR=str(ROOT / ".venv/tiktoken-cache"), S01_NETWORK_AUDIT=str(OUT / "network-audit.txt"))
PYTHON = str(ROOT / ".venv/bin/python")


def run(label, argv, *, timeout=240, extra=None, cwd=ROOT):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    before = baseline["snapshot"](ROOT)
    clock = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=cwd, env={**env, **(extra or {})}, capture_output=True, text=True, timeout=timeout)
        output, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or b"") + (exc.stderr or b"")).decode(errors="replace") + "\nCHECK_TIMEOUT\n"
        code = 124
    except FileNotFoundError as exc:
        output, code = str(exc), 127
    after = baseline["snapshot"](ROOT)
    path = OUT / "commands.json"
    rows = json.loads(path.read_text()) if path.exists() else []
    name = f"{len(rows)+1:02d}-{label}.txt"
    with (OUT / name).open("x") as handle:
        handle.write(output)
    row = dict(label=label, argv=[str(a) for a in argv], cwd=str(cwd), started_utc=started, exit_code=code,
               elapsed_seconds=round(time.monotonic()-clock,3), output=name,
               output_sha256=hashlib.sha256(output.encode()).hexdigest(), head=after["head"],
               source_manifest_sha256=after["source_manifest_sha256"], tracked_diff_sha256=after["tracked_diff_sha256"],
               source_unchanged=before["files_sha256"]==after["files_sha256"], environment_overrides=extra or {})
    path.write_text(json.dumps([*rows,row],ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(row,ensure_ascii=False),flush=True)
    print(output[-7000:],flush=True)
    return code


if __name__ == "__main__":
    mode=sys.argv[1]
    if mode == "counterexamples":
        sys.exit(run(mode,[PYTHON,"-m","pytest","tests/test_multi_agent_acceptance.py","-q","-ra",
                           "--junitxml="+str(OUT/"counterexamples.xml")]))
    if mode in {"all-docker", "all-docker-final"}:
        sys.exit(run(mode,[PYTHON,"-m","pytest","tests","-q","-ra","--junitxml="+str(OUT/(mode+".xml"))],
                     timeout=600,extra={"AIROBOT_TEST_DOCKER":"1","S7_REAL_EVIDENCE":str(OUT/(mode+"-compile-result.json"))}))
    if mode == "early-interruptions":
        sys.exit(run(mode,[PYTHON,"-m","pytest","tests/test_multi_agent_early_interruptions.py","-q","-ra",
                           "--junitxml="+str(OUT/"early-interruptions.xml")]))
    if mode == "business":
        sys.exit(run(mode,[PYTHON,"-m","pytest",*["tests/test_"+n+".py" for n in
            ("agent","integration","stability","tracing","hardening")],"-q","-ra","--junitxml="+str(OUT/"business.xml")]))
    if mode == "agent-fixtures":
        sys.exit(run(mode,[PYTHON,"eval/run_agent_eval.py"]))
    if mode == "go-fixtures":
        sys.exit(run(mode,[PYTHON,"eval/run_go_eval.py","--fixtures","--output",str(OUT/"go-fixtures.json")],timeout=360))
    if mode == "environment":
        checks=[("python",[PYTHON,"--version"]),("dependencies",[PYTHON,"-m","pip","check"]),
                ("docker-version",["docker","version"]),
                ("docker-image",["docker","image","inspect","airobot-go-validator:1.26.2","--format","{{json .}}"]),
                ("containers-before",["docker","ps","-a","--filter","name=airobot-go-","--format","{{.Names}} {{.Status}}"])]
        sys.exit(max(run(label,argv) for label,argv in checks))
    if mode == "containers-after":
        sys.exit(run(mode,["docker","ps","-a","--filter","name=airobot-go-","--format","{{.Names}} {{.Status}} "]))
    raise SystemExit("unknown mode")
