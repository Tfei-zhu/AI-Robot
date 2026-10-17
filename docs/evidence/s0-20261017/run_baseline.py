"""Reproduce the S0 read-only probes and offline baseline; never starts live evals.

Run from AI-Robot-latest: python3 docs/evidence/s0-20261017/run_baseline.py
The sibling venv supplies installed libraries only, not application source.
No dependencies are installed and no old-repository code is executed.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
OLD = ROOT.parent / "AI-Robot-FastAPI-LangChain-RAG-CrewAI-Agent-"
BORROWED = OLD / ".venv/bin/python"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root)


def snapshot(root):
    tracked = git(root, "ls-files", "-z").decode().split("\0")
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z").decode().split("\0")
    # Include tracked content and relevant untracked implementation/documents.
    # Exclude this evidence directory and its log to avoid recursive hashes.
    paths = sorted(set(p for p in tracked + untracked if p and
                       not p.startswith(("docs/evidence/", "output/", "tmp/")) and
                       p not in {"docs/multi-agent-execution-log.md", ".env", ":memory:.ses"}))
    files = {p: sha((root / p).read_bytes()) for p in paths if (root / p).is_file()}
    canonical = json.dumps(files, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return {"root": str(root.resolve()), "head": git(root, "rev-parse", "HEAD").decode().strip(),
            "branch": git(root, "branch", "--show-current").decode().strip(),
            "status": git(root, "status", "--porcelain=v2", "--branch").decode(),
            "tracked_diff_sha256": sha(git(root, "diff", "--binary", "HEAD")),
            "staged_diff_sha256": sha(git(root, "diff", "--cached", "--binary")),
            "source_manifest_sha256": sha(canonical), "files_sha256": files,
            "exclusions": ["ignored files (including .venv/cache/credentials)", "docs/evidence/",
                           "docs/multi-agent-execution-log.md", "output/", "tmp/", ":memory:.ses"]}


env = {k: v for k, v in os.environ.items()
       if not k.startswith(("AIROBOT_", "OPENAI_", "LANGCHAIN_", "LANGSMITH_", "PYTEST_"))}
env.update(PYTHONDONTWRITEBYTECODE="1", PYTHON_DOTENV_DISABLED="1",
           PYTHONPYCACHEPREFIX="/private/tmp/airobot-s0-pycache",
           PYTHONPATH=os.pathsep.join([str(OUT / "offline_guard"), str(ROOT)]),
           AIROBOT_LLM_API_KEY="", AIROBOT_EMBEDDING_API_KEY="", AIROBOT_AMQP_URL="",
           AIROBOT_GO_API_BASE_URL="", AIROBOT_RERANK_ENABLED="false", AIROBOT_CONTEXT_MODE="off",
           LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false",
           S0_NETWORK_AUDIT=str(OUT / "network-audit.txt"))


def run(label, argv, *, guarded=False):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clock = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=ROOT, env=env if guarded else None,
                              capture_output=True, text=True, timeout=55)
        output, code = proc.stdout + proc.stderr, proc.returncode
    except FileNotFoundError:
        output, code = "Executable not available\n", 127
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or b"") + (exc.stderr or b"")).decode(errors="replace")
        output += "\nS0 command timeout (55 seconds)\n"
        code = 124
    (OUT / (label + ".txt")).write_text(output, encoding="utf-8")
    row = {"id": label, "argv": [str(a) for a in argv], "cwd": str(ROOT), "started_utc": started,
           "exit_code": code, "elapsed_seconds": round(time.monotonic() - clock, 3),
           "network_guard": guarded, "output": label + ".txt", "output_sha256": sha(output.encode())}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    before = {"latest": snapshot(ROOT), "old": snapshot(OLD)}
    (OUT / "source-before.json").write_text(json.dumps(before, ensure_ascii=False, indent=2) + "\n")
    (OUT / "network-audit.txt").write_text("")
    checks = []
    commands = [
        ("system-python", [sys.executable, "--version"], False),
        ("system-packages", [sys.executable, "-m", "pip", "list", "--format=json"], False),
        ("system-pytest", [sys.executable, "-m", "pytest", "tests", "-q"], True),
        ("syntax", [sys.executable, "-m", "compileall", "-q", "app", "eval", "scripts", "tests"], True),
        ("docker-version", ["docker", "version"], False),
        ("docker-compose", ["docker", "compose", "version"], False),
        ("docker-image", ["docker", "image", "inspect", "airobot-go-validator:1.26.2"], False),
        ("node-version", ["node", "--version"], False),
        ("host-go-version", ["go", "version"], False),
        ("playwright-availability", ["node", "-e", "console.log(require.resolve('playwright'))"], False),
        ("borrowed-python", [str(BORROWED), "--version"], False),
        ("borrowed-packages", [str(BORROWED), "-m", "pip", "list", "--format=json"], False),
        ("borrowed-pip-check", [str(BORROWED), "-m", "pip", "check"], False),
        ("borrowed-go-pytest", [str(BORROWED), "-m", "pytest", "tests/test_go_contracts.py",
                                "tests/test_go_workflow.py", "tests/test_go_runner.py", "tests/test_go_acceptance.py", "-q"], True),
        ("borrowed-pytest", [str(BORROWED), "-m", "pytest", "tests", "-q"], True),
        ("import-smoke", [str(BORROWED), "-c", "import app.main, app.agents.graph; print(app.main.__file__); print(app.agents.graph.__file__); print('routes:', len(app.main.app.routes))"], True),
        *[("script-" + name, [str(BORROWED), "tests/test_" + name + ".py"], True)
          for name in ("stability", "integration", "agent", "tracing")],
        ("hardening", [str(BORROWED), "-m", "unittest", "discover", "-s", "tests", "-p", "test_hardening.py", "-v"], True),
        ("agent-fixtures", [str(BORROWED), "eval/run_agent_eval.py"], True),
    ]
    for label, argv, guarded in commands:
        checks.append(run(label, argv, guarded=guarded))
        (OUT / "commands.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2) + "\n")
    after = {"latest": snapshot(ROOT), "old": snapshot(OLD)}
    (OUT / "source-after.json").write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n")
    assert before["latest"]["source_manifest_sha256"] == after["latest"]["source_manifest_sha256"]
    assert before["old"] == after["old"], "Old repository changed during baseline"
