"""Reproduce review fixes with live model/network access blocked; retain old evidence."""
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
env.update(PYTHONPATH=os.pathsep.join([str(OUT.parent / "s0.1-20261017/offline_guard"),
                                     str(ROOT), str(ROOT / "tests")]),
           TIKTOKEN_CACHE_DIR=str(ROOT / ".venv/tiktoken-cache"),
           S01_NETWORK_AUDIT=str(OUT / "network-audit.txt"))
PYTHON = str(ROOT / ".venv/bin/python")


def run(label, argv, timeout=180):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clock = time.monotonic()
    proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    output = proc.stdout + proc.stderr
    path = OUT / "commands.json"
    rows = json.loads(path.read_text()) if path.exists() else []
    sequence = 1 + sum(row["label"] == label for row in rows)
    output_name = label + (f"-{sequence}" if sequence > 1 else "") + ".txt"
    (OUT / output_name).write_text(output)
    row = dict(label=label, argv=argv, started_utc=started, exit_code=proc.returncode,
               elapsed_seconds=round(time.monotonic()-clock, 3),
               output=output_name, output_retained=True,
               output_sha256=hashlib.sha256(output.encode()).hexdigest())
    path.write_text(json.dumps([*rows, row], ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(row), flush=True)
    print(output[-5000:], flush=True)
    return proc.returncode


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode in {"before", "after"}:
        (OUT / ("source-"+mode+".json")).write_text(
            json.dumps(baseline["snapshot"](ROOT), ensure_ascii=False, indent=2)+"\n")
    elif mode in {"probes-before", "probes-after"}:
        sys.exit(run(mode, [PYTHON, str(OUT.parent / "review-s2s4-20261017/probes.py")]))
    elif mode == "targeted":
        sys.exit(run(mode, [PYTHON, "-m", "pytest", "tests/test_multi_agent_regressions.py",
                           "tests/test_multi_agent_agents.py", "tests/test_multi_agent_workflow.py",
                           "tests/test_multi_agent_budget.py", "tests/test_multi_agent_runner_binding.py",
                           "tests/test_go_workflow.py", "-q", "-ra"]))
    elif mode == "all":
        sys.exit(run("pytest-final", [PYTHON, "-m", "pytest", "tests", "-q", "-ra",
                                     "--junitxml="+str(OUT / "pytest.xml")]))
    elif mode == "docker":
        env["AIROBOT_TEST_DOCKER"] = "1"
        code = run("docker-tests", [PYTHON, "-m", "pytest", "tests/test_go_runner.py",
                     "tests/test_go_acceptance.py", "tests/test_go_workflow.py",
                     "tests/test_multi_agent_workflow.py", "tests/test_multi_agent_regressions.py",
                     "-q", "-ra", "--junitxml="+str(OUT / "docker.xml")], timeout=240)
        run("docker-containers", ["docker", "ps", "-a", "--filter", "name=airobot-go-",
                                  "--format", "{{.Names}} {{.Status}}"])
        sys.exit(code)
    elif mode == "fixtures":
        sys.exit(run("go-fixtures", [PYTHON, "eval/run_go_eval.py", "--fixtures",
                     "--output", str(OUT / "go-fixtures.json")], timeout=240))
