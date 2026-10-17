"""Capture independent review evidence without changing production or existing tests."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
baseline = runpy.run_path(str(BASE.parent / "s0-20261017/run_baseline.py"))
snapshot = baseline["snapshot"]
env = dict(baseline["env"])
env.update(PYTHONPATH=os.pathsep.join([str(BASE.parent / "s0.1-20261017/offline_guard"),
                                     str(ROOT), str(ROOT / "tests")]),
           TIKTOKEN_CACHE_DIR=str(ROOT / ".venv/tiktoken-cache"),
           S01_NETWORK_AUDIT=str(BASE / "network-audit.txt"))
python = str(ROOT / ".venv/bin/python")


def run(label, argv, timeout=120):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clock = time.monotonic()
    proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    output = proc.stdout + proc.stderr
    (BASE / (label + ".txt")).write_text(output)
    row = dict(label=label, argv=argv, started_utc=started, exit_code=proc.returncode,
               elapsed_seconds=round(time.monotonic() - clock, 3),
               output_sha256=hashlib.sha256(output.encode()).hexdigest())
    path = BASE / "commands.json"
    rows = json.loads(path.read_text()) if path.exists() else []
    path.write_text(json.dumps([*rows, row], ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(row), flush=True)


if __name__ == "__main__":
    if "--docker" in sys.argv:
        env["AIROBOT_TEST_DOCKER"] = "1"
        run("docker-version", ["docker", "version"])
        run("docker-image", ["docker", "image", "inspect", "airobot-go-validator:1.26.2",
                             "--format", "{{.Id}}"])
        run("docker-closed-loops", [python, "-m", "pytest", "tests/test_multi_agent_workflow.py",
                                   "-q", "-ra", "--junitxml=" + str(BASE / "docker.xml")])
        run("docker-containers", ["docker", "ps", "-a", "--filter", "name=airobot-go-",
                                  "--format", "{{.Names}} {{.Status}}"])
    else:
        (BASE / "source-before.json").write_text(json.dumps(snapshot(ROOT), ensure_ascii=False, indent=2) + "\n")
        log = (ROOT / "docs/multi-agent-execution-log.md").read_bytes()
        (BASE / "log-before.json").write_text(json.dumps(dict(bytes=len(log), sha256=hashlib.sha256(log).hexdigest())))
        run("probes", [python, str(BASE / "probes.py")])
        run("pytest", [python, "-m", "pytest", "tests", "-q", "-ra",
                       "--junitxml=" + str(BASE / "pytest.xml")])
        run("diff-check", ["git", "diff", "--check"])
        (BASE / "source-after.json").write_text(json.dumps(snapshot(ROOT), ensure_ascii=False, indent=2) + "\n")
