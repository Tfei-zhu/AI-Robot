"""S5 checks with network/model access disabled; retain every run's output."""
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
env.update(PYTHONPATH=os.pathsep.join([str(OUT.parent / "s0.1-20261017/offline_guard"),
                                     str(ROOT), str(ROOT / "tests")]),
           TIKTOKEN_CACHE_DIR=str(ROOT / ".venv/tiktoken-cache"),
           S01_NETWORK_AUDIT=str(OUT / "network-audit.txt"))
PYTHON = str(ROOT / ".venv/bin/python")


def run(label, argv, timeout=180):
    path = OUT / "commands.json"
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clock = time.monotonic()
    proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    output = proc.stdout + proc.stderr
    version = baseline["snapshot"](ROOT)
    row = dict(label=label, argv=argv, cwd=str(ROOT), started_utc=started,
               exit_code=proc.returncode, elapsed_seconds=round(time.monotonic()-clock, 3),
               output_sha256=hashlib.sha256(output.encode()).hexdigest(),
               head=version["head"], source_manifest_sha256=version["source_manifest_sha256"],
               tracked_diff_sha256=version["tracked_diff_sha256"])
    # Serialize evidence writes even when independent checks finish concurrently.
    with (OUT / "commands.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = json.loads(path.read_text()) if path.exists() else []
        sequence = len(rows) + 1
        output_name = f"{sequence:02d}-{label}.txt"
        while (OUT / output_name).exists():
            sequence += 1
            output_name = f"{sequence:02d}-{label}.txt"
        (OUT / output_name).write_text(output)
        row["output"] = output_name
        path.write_text(json.dumps([*rows, row], ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(row), flush=True)
    print(output[-7000:], flush=True)
    return proc.returncode


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "targeted":
        sys.exit(run(mode, [PYTHON, "-m", "pytest", "tests/test_multi_agent_http.py", "-q", "-ra",
                           "--junitxml="+str(OUT / f"http-{len(list(OUT.glob('*targeted.txt')))+1}.xml")]))
    if mode == "all":
        sys.exit(run(mode, [PYTHON, "-m", "pytest", "tests", "-q", "-ra",
                           "--junitxml="+str(OUT / f"all-{len(list(OUT.glob('*all.txt')))+1}.xml")]))
    if mode == "review-regressions":
        sys.exit(run(mode, [PYTHON, str(OUT.parent / "review-s2s4-20261017/probes.py")]))
    if mode == "docker":
        env["AIROBOT_TEST_DOCKER"] = "1"
        code = run(mode, [PYTHON, "-m", "pytest", "tests/test_go_runner.py", "tests/test_go_acceptance.py",
            "tests/test_go_workflow.py", "tests/test_multi_agent_workflow.py", "tests/test_multi_agent_regressions.py",
            "tests/test_multi_agent_http.py", "-q", "-ra",
            "--junitxml="+str(OUT / f"docker-{1+len(list(OUT.glob('docker*.xml')))}.xml")], timeout=240)
        run("containers", ["docker", "ps", "-a", "--filter", "name=airobot-go-", "--format", "{{.Names}} {{.Status}}"])
        sys.exit(code)
