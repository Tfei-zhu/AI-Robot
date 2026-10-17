"""S1 offline checks. Run from repository root; never calls live evaluation entrypoints."""
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
S0 = runpy.run_path(str(BASE.parent / "s0-20261017/run_baseline.py"))
PYTHON = str(ROOT / ".venv/bin/python")
ENV = dict(S0["env"])
ENV.update(S0_NETWORK_AUDIT=str(BASE / "network-audit.txt"), PYTHONPYCACHEPREFIX="/private/tmp/airobot-s1-pycache")
ENV.update(TIKTOKEN_CACHE_DIR=str(ROOT / ".venv/tiktoken-cache"),
           S01_NETWORK_AUDIT=str(BASE / "network-audit.txt"),
           PYTHONPATH=os.pathsep.join([str(BASE.parent / "s0.1-20261017/offline_guard"), str(ROOT)]))


def run(label, argv, *, guarded=True, timeout=55):
    started, clock = datetime.datetime.now(datetime.timezone.utc).isoformat(), time.monotonic()
    result = subprocess.run(argv, cwd=ROOT, env=ENV if guarded else None,
                            capture_output=True, text=True, timeout=timeout)
    output = result.stdout + result.stderr
    (BASE / (label + ".txt")).write_text(output)
    row = {"id": label, "argv": argv, "cwd": str(ROOT), "started_utc": started,
           "elapsed_seconds": round(time.monotonic() - clock, 3), "exit_code": result.returncode,
           "guarded": guarded, "output": label + ".txt",
           "output_sha256": hashlib.sha256(output.encode()).hexdigest()}
    snapshot = S0["snapshot"](ROOT)
    row.update(head=snapshot["head"], source_manifest_sha256=snapshot["source_manifest_sha256"],
               tracked_diff_sha256=snapshot["tracked_diff_sha256"])
    path = BASE / ("docker-commands.json" if {"--docker", "--real-gate"} & set(sys.argv) else "commands.json")
    rows = json.loads(path.read_text()) if path.exists() else []
    rows.append(row)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


if __name__ == "__main__":
    if "--real-gate" in sys.argv:
        run("real-gate", [PYTHON, str(BASE / "real_gate_probe.py")], timeout=120)
        run("docker-containers-final", ["docker", "ps", "-a", "--filter", "name=airobot-go-", "--format", "{{.Names}} {{.Status}}"], guarded=False)
        sys.exit(0)
    if "--docker" in sys.argv:
        run("docker-version-restored", ["docker", "version"], guarded=False)
        run("docker-image-restored", ["docker", "image", "inspect", "airobot-go-validator:1.26.2"], guarded=False)
        ENV["AIROBOT_TEST_DOCKER"] = "1"
        run("docker-pytest", [PYTHON, "-m", "pytest", "tests/test_go_contracts.py", "tests/test_go_workflow.py",
                             "tests/test_go_runner.py", "tests/test_go_acceptance.py",
                             "tests/test_multi_agent_runner_binding.py", "-q", "-ra",
                             "--junitxml=" + str(BASE / "docker-pytest.xml")], timeout=600)
        run("docker-containers-after", ["docker", "ps", "-a", "--filter", "name=airobot-go-", "--format", "{{.Names}} {{.Status}}"], guarded=False)
        sys.exit(0)
    run("independent-environment", [PYTHON, "-c", "import sys,pytest,pydantic; print(sys.executable); print(sys.version); print('pytest',pytest.__version__,'pydantic',pydantic.__version__)"])
    run("independent-pip-check", [PYTHON, "-m", "pip", "check"])
    run("independent-unittest", [PYTHON, "-m", "unittest", "discover", "-s", "tests", "-p", "test_multi_agent_*.py", "-v"])
    run("full-pytest", [PYTHON, "-m", "pytest", "tests", "-q", "-ra",
                        "--junitxml=" + str(BASE / "full-pytest.xml")], timeout=120)
    run("agent-fixtures", [PYTHON, "eval/run_agent_eval.py"])
