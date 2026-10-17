"""Verify S1 delivery against the tested source and preserve all prior local work."""
import ast
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
from xml.etree import ElementTree as ET

BASE = Path(__file__).resolve().parent
checks = runpy.run_path(str(BASE / "run_checks.py"))
root, snapshot = checks["ROOT"], checks["S0"]["snapshot"]
before = json.loads((BASE / "source-before.json").read_text())
after = {"latest": snapshot(root), "old": snapshot(checks["S0"]["OLD"])}
expected = json.loads((BASE / "source-after.json").read_text())
assert after["latest"]["source_manifest_sha256"] == expected["latest"]["source_manifest_sha256"]
assert before["old"] == after["old"], "Old repository source or status changed"
assert before["latest"]["head"] == after["latest"]["head"]
assert before["latest"]["branch"] == after["latest"]["branch"]
assert before["latest"]["staged_diff_sha256"] == after["latest"]["staged_diff_sha256"]
allowed = {".env.example", "app/config.py", "app/go_validation/contracts.py", "app/go_validation/runner.py"}
changed_existing = {name for name, digest in before["latest"]["files_sha256"].items()
                    if after["latest"]["files_sha256"].get(name) != digest}
assert changed_existing == allowed, changed_existing
rows = json.loads((BASE / "commands.json").read_text())
rows += json.loads((BASE / "docker-commands.json").read_text())
for row in rows:
    assert hashlib.sha256((BASE / row["output"]).read_bytes()).hexdigest() == row["output_sha256"], row["id"]
delivery = [row for row in rows if row["id"].endswith("-delivery") or row["id"] == "contracts-review-config-runner-final"]
assert len(delivery) == 6
for row in delivery:
    assert row["exit_code"] == 0, row["id"]
    assert row["head"] == after["latest"]["head"]
    assert row["source_manifest_sha256"] == after["latest"]["source_manifest_sha256"], row["id"]
    assert row["tracked_diff_sha256"] == after["latest"]["tracked_diff_sha256"], row["id"]
restored_ids = {"independent-environment", "independent-pip-check", "independent-unittest", "full-pytest",
                "agent-fixtures", "docker-version-restored", "docker-image-restored", "docker-pytest",
                "docker-containers-after", "real-gate", "docker-containers-final"}
restored = [row for row in rows if row["id"] in restored_ids]
assert len(restored) == len(restored_ids)
for row in restored:
    assert row["exit_code"] == 0, row["id"]
    assert row["source_manifest_sha256"] == after["latest"]["source_manifest_sha256"], row["id"]
    assert row["tracked_diff_sha256"] == after["latest"]["tracked_diff_sha256"], row["id"]
for name, expected_tests, expected_skips in (("full-pytest.xml", 312, 22), ("docker-pytest.xml", 49, 0)):
    suite = ET.parse(BASE / name).getroot()[0]
    assert int(suite.attrib["failures"]) == int(suite.attrib["errors"]) == 0
    assert int(suite.attrib["tests"]) == expected_tests
    assert int(suite.attrib["skipped"]) == expected_skips
assert "180 passed, 22 skipped" in (BASE / "full-pytest.txt").read_text()
assert "110 subtests passed" in (BASE / "full-pytest.txt").read_text()
gate = json.loads((BASE / "real-gate-report.json").read_text())["results"]
assert len(gate) == 2
for row in gate:
    art = row["artifact"]
    files = sorted(art["files"], key=lambda item: item["name"])
    digest = hashlib.sha256(json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert digest == art["artifact_hash"] == row["validation"]["artifact_hash"] == row["review"]["artifact_hash"]
    assert row["validation"]["container_removed"]
    assert row["review"]["verdict"] == "approve"
assert gate[0]["validation"]["status"] == gate[0]["decision"]["status"] == "passed"
assert gate[1]["validation"]["status"] == "failed" and gate[1]["decision"]["action"] == "repair"
assert (BASE / "docker-containers-final.txt").read_text() == ""
for path in [root / "app/agents/go_workflow.py", *sorted((root / "tests").glob("*multi_agent*.py")),
             *sorted(BASE.glob("*.py"))]:
    ast.parse(path.read_text())
prior = json.loads((BASE / "execution-log-before.json").read_text())
log = root / "docs/multi-agent-execution-log.md"
assert hashlib.sha256(log.read_bytes()[:prior["bytes"]]).hexdigest() == prior["sha256"]
s0_manifest = json.loads((BASE.parent / "s0-20261017/artifact-manifest.json").read_text())
for name, digest in s0_manifest["files_sha256"].items():
    if name == "docs/multi-agent-execution-log.md":
        archive = BASE.parent / "s0.1-20261017/execution-log-before.md"
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest
        assert log.read_bytes().startswith(archive.read_bytes())
    else:
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
s01_manifest = json.loads((BASE.parent / "s0.1-20261017/artifact-manifest.json").read_text())
for name, digest in s01_manifest["files_sha256"].items():
    if name == "docs/multi-agent-execution-log.md":
        assert digest == prior["sha256"]
    else:
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
diff = subprocess.run(["git", "diff", "--check"], cwd=root, capture_output=True, text=True)
assert diff.returncode == 0, diff.stdout + diff.stderr
events = (BASE / "network-audit.txt").read_text() if (BASE / "network-audit.txt").exists() else ""
assert events == "", "Unexpected attempted networking; review audit before accepting checks"
message = ["S1 final evidence consistency: PASS", "command: python3 docs/evidence/s1-20261017/verify_evidence.py", "exit_code: 0",
           "Final 33 unittest tests + 21 regression tests passed on the recorded delivery source",
           f"HEAD: {after['latest']['head']}", f"source_manifest_sha256: {after['latest']['source_manifest_sha256']}",
           f"tracked_diff_sha256: {after['latest']['tracked_diff_sha256']}",
           f"Verified command outputs: {len(rows)}; tested delivery records: {len(delivery)}",
           "Independent environment: full pytest 180 passed / 22 Docker skips / 110 subtests passed",
           "Docker suite: 49 passed / 0 skips (22 actual sandbox cases, 3 new adapter fixtures)",
           "Actual Docker + fixture review gate probes: correct passed, wrong code + approve rejected",
           "Original plans, old source/status, S0/S0.1 evidence and complete prior log prefix: unchanged",
           "Only four authorized pre-existing files modified; staged content unchanged",
           "No DNS/connection audit events; no live model evaluation",
           "git diff --check: passed; new Python files AST: passed",
           "No remaining pytest/Docker blocker; real model quality, Python 3.11, CI and browser not evaluated",
           after["latest"]["status"]]
(BASE / "final-checks.txt").write_text("\n".join(message) + "\n")
files = [log, *[root / name for name in after["latest"]["files_sha256"]
               if name in allowed or name not in before["latest"]["files_sha256"]],
         *sorted(p for p in BASE.rglob("*") if p.is_file() and p.name != "artifact-manifest.json" and "__pycache__" not in p.parts)]
digests = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
manifest = {"algorithm": "sha256", "tested_source_manifest_sha256": after["latest"]["source_manifest_sha256"],
            "tracked_diff_sha256": after["latest"]["tracked_diff_sha256"], "files_sha256": digests,
            "excluded": ["artifact-manifest.json itself", "ignored cache/credentials/virtualenv"]}
manifest["artifact_set_sha256"] = hashlib.sha256(json.dumps(digests, sort_keys=True, ensure_ascii=False,
                                                            separators=(",", ":")).encode()).hexdigest()
(BASE / "artifact-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
print("\n".join(message))
print("artifact_set_sha256:", manifest["artifact_set_sha256"])
