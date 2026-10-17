"""S6 reproducible checks; no credentials or live model calls; unique outputs."""
import datetime
import fcntl
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
           TIKTOKEN_CACHE_DIR=str(ROOT / ".venv/tiktoken-cache"), S01_NETWORK_AUDIT=str(OUT / "network-audit.txt"),
           NODE_PATH="/Users/xumanchun/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules",
           PLAYWRIGHT_CHANNEL="chrome", S6_EVIDENCE_DIR=str(OUT))
PYTHON = str(ROOT / ".venv/bin/python")


def run(label, argv, timeout=180):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clock = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
        output, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or b"") + (exc.stderr or b"")).decode(errors="replace") + "\nCHECK_TIMEOUT\n"
        code = 124
    version = baseline["snapshot"](ROOT)
    with (OUT / "commands.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = OUT / "commands.json"
        rows = json.loads(path.read_text()) if path.exists() else []
        name = f"{len(rows)+1:02d}-{label}.txt"
        assert not (OUT / name).exists()
        (OUT / name).write_text(output)
        row = dict(label=label, argv=argv, started_utc=started, exit_code=code,
            elapsed_seconds=round(time.monotonic()-clock,3), output=name,
            output_sha256=hashlib.sha256(output.encode()).hexdigest(), head=version["head"],
            source_manifest_sha256=version["source_manifest_sha256"], tracked_diff_sha256=version["tracked_diff_sha256"])
        row["browser_environment"]={k:env[k] for k in ("NODE_PATH","PLAYWRIGHT_CHANNEL","S6_EVIDENCE_DIR","S6_RUN_DIR","S6_BACKEND_URL","S6_REAL_DOCKER","S6_FIXTURES","GO_DASHBOARD_SCREENSHOT") if k in env}
        path.write_text(json.dumps([*rows,row],ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(row),flush=True);print(output[-9000:],flush=True)
    return code


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "fixtures":
        target=OUT/f"ui-fixtures-{1+len(list(OUT.glob('ui-fixtures*.json')))}.json"
        sys.exit(run(mode,[PYTHON,"scripts/multi_agent_dashboard_fixtures.py","--output",str(target)]))
    if mode == "all":
        sys.exit(run(mode,[PYTHON,"-m","pytest","tests","-q","-ra","--junitxml="+str(OUT/f"all-{len(list(OUT.glob('all-*.xml')))+1}.xml")]))
    if mode == "browser":
        env["S6_FIXTURES"]=str(max(OUT.glob('ui-fixtures*.json'),key=lambda p:p.stat().st_mtime))
        env["S6_RUN_DIR"]=f"browser-run-{1+len(list(OUT.glob('browser-run-*'))):02d}"
        if len(sys.argv)>2:
            env.update(S6_BACKEND_URL=sys.argv[2],S6_REAL_DOCKER="1")
        sys.exit(run(mode,["node","scripts/test_multi_agent_dashboard.cjs"],timeout=240))
    if mode == "legacy-browser":
        env["GO_DASHBOARD_SCREENSHOT"]=str(OUT/f"legacy-{time.time_ns()}.png")
        sys.exit(run(mode,["node","scripts/test_go_dashboard.cjs"]))
    if mode == "integration-browser":
        env["S6_FIXTURES"]=str(max(OUT.glob('ui-fixtures*.json'),key=lambda p:p.stat().st_mtime))
        env["S6_RUN_DIR"]=f"browser-run-{1+len(list(OUT.glob('browser-run-*'))):02d}"
        argv=[PYTHON,"scripts/multi_agent_dashboard_server.py","--db",str(OUT/"browser.sqlite3"),"--port","8766","--docker"]
        started=datetime.datetime.now(datetime.timezone.utc).isoformat()
        log_path=OUT/f"server-{time.time_ns()}.txt"
        with log_path.open("w") as log:
            server=subprocess.Popen(argv,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                env.update(S6_BACKEND_URL="http://127.0.0.1:8766",S6_REAL_DOCKER="1")
                code=run("integration-browser",["node","scripts/test_multi_agent_dashboard.cjs"],timeout=240)
            finally:
                server.terminate()
                try: server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill();server.wait()
        (OUT/f"{log_path.stem}.json").write_text(json.dumps(dict(argv=argv,started_utc=started,
            exit_code=server.returncode,termination="test harness stopped after browser checks",log=log_path.name,
            log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest()),ensure_ascii=False,indent=2)+"\n")
        run("containers",["docker","ps","-a","--filter","name=airobot-go-","--format","{{.Names}} {{.Status}}"])
        sys.exit(code)
