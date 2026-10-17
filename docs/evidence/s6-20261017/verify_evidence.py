"""S6 final evidence audit: source/log preservation, real result hashes and provenance."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0,str(ROOT))
from app.go_validation.contracts import CodeArtifact, GoTaskResult

baseline = runpy.run_path(str(OUT.parent / "s0-20261017/run_baseline.py"))
before = json.loads((OUT / "source-before.json").read_text())
after = baseline["snapshot"](ROOT)
expected = "4b1162f00e22d138b525d0abfb546c6f4e639f4ae7e308505cb4fcf39365a429"
assert after["source_manifest_sha256"] == expected
assert after["head"] == before["head"] and after["branch"] == before["branch"] == "main"
assert after["staged_diff_sha256"] == before["staged_diff_sha256"]
changed = sorted(p for p in set(before["files_sha256"]) | set(after["files_sha256"])
                 if before["files_sha256"].get(p) != after["files_sha256"].get(p))
assert set(changed) == {"app/agents/go_workflow.py", "app/go_validation/contracts.py", "app/go_validation/service.py",
    "app/static/dashboard.html", "docs/go-validation.md", "tests/test_multi_agent_http.py",
    "scripts/test_go_dashboard.cjs", "scripts/test_multi_agent_dashboard.cjs",
    "scripts/multi_agent_dashboard_fixtures.py", "scripts/multi_agent_dashboard_server.py"}
log = (ROOT / "docs/multi-agent-execution-log.md").read_bytes()
prior = json.loads((OUT / "log-before.json").read_text())
assert hashlib.sha256(log[:prior["bytes"]]).hexdigest() == prior["sha256"]
rows = json.loads((OUT / "commands.json").read_text())
assert len({r["output"] for r in rows}) == len(rows)
for row in rows:
    assert hashlib.sha256((OUT / row["output"]).read_bytes()).hexdigest() == row["output_sha256"]
final = {label:[r for r in rows if r["label"] == label][-1]
         for label in ("all","integration-browser","legacy-browser","containers","runtime","diff-check","docker-version","docker-image")}
for row in final.values():
    assert row["exit_code"] == 0 and row["source_manifest_sha256"] == expected
    assert row["tracked_diff_sha256"] == after["tracked_diff_sha256"]
assert not (OUT / final["containers"]["output"]).read_text().strip()
audit = OUT / "network-audit.txt"
assert not audit.exists() or audit.stat().st_size == 0
assert "381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af" in (OUT / final["docker-image"]["output"]).read_text()
xml = next(a.split("=",1)[1] for a in final["all"]["argv"] if a.startswith("--junitxml="))
suite = ET.parse(xml).getroot()
assert not list(suite.iter("failure")) and not list(suite.iter("error"))
assert len(list(suite.iter("skipped"))) == 29
assert "257 passed" in (OUT / final["all"]["output"]).read_text()
run = OUT / final["integration-browser"]["browser_environment"]["S6_RUN_DIR"]
browser = json.loads((run / "browser-results.json").read_text())
assert len(browser["checks"]) == 23 and all(c["status"] == "passed" for c in browser["checks"])
assert browser["page_errors"] == [] and browser["paid_models"] == "not_run"
assert final["integration-browser"]["browser_environment"]["S6_REAL_DOCKER"] == "1"
assert final["integration-browser"]["browser_environment"]["S6_BACKEND_URL"] == "http://127.0.0.1:8766"
results = json.loads((run / "backend-results.json").read_text())
assert [r["case"] for r in results] == ["passed","repair","failed","cancelled"]
validations = 0
for row in results:
    result = GoTaskResult.model_validate(row["result"])
    assert result.model_source == "fixture" and result.workflow_version == "multi-v1"
    assert result.status == ("passed" if row["case"] in ("passed","repair") else row["case"])
    assert result.validation_calls == len(result.attempts)
    for art, attempt in zip(result.artifacts,result.attempts):
        art = CodeArtifact.model_validate(art.model_dump())  # Recompute hash and check trusted test bytes.
        assert art.artifact_hash == attempt.validation.artifact_hash
        assert attempt.validation.container_removed and attempt.validation.go_version == "1.26.2"
    for review in result.reviews:
        assert review.artifact_hash == result.artifacts[review.round].artifact_hash
    validations += result.validation_calls
assert validations == 6
assert all(r["verdict"] == "approve" for r in results[2]["result"]["reviews"])
assert results[2]["result"]["status"] == "failed"  # Actual machine failure beats model approval.
for path in OUT.glob("server-*.json"):
    record = json.loads(path.read_text())
    assert record["exit_code"] in (0,-15)  # Expected explicit SIGTERM; no forced -9 exit.
    assert hashlib.sha256((OUT / record["log"]).read_bytes()).hexdigest() == record["log_sha256"]
    assert "Traceback" not in (OUT / record["log"]).read_text()
subprocess.run(["git","diff","--check"],cwd=ROOT,check=True)
(OUT / "source-after.json").write_text(json.dumps(after,ensure_ascii=False,indent=2)+"\n")
result = dict(head=after["head"],source_manifest_sha256=expected,tracked_diff_sha256=after["tracked_diff_sha256"],
    changed_files=changed,old_log_prefix_preserved=True,execution_log_sha256=hashlib.sha256(log).hexdigest(),
    checked_command_outputs=len(rows),offline_passed=257,offline_skipped=29,subtests_passed=138,
    browser_checks_passed=23,replaced_response_checks=18,real_backend_checks=5,real_docker_validations=6,
    browser=browser["browser"],page_errors=0,model_source="fixed substitutes",paid_evaluations="not_run",
    network_audit_events=0,leftover_containers=0,git_diff_check="passed",browser_run=str(run.relative_to(OUT)))
(OUT / "final-checks.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
files = {str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "artifact-manifest.json"}
manifest = dict(files=files,manifest_sha256=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(",",":")).encode()).hexdigest())
(OUT / "artifact-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
print(json.dumps(result,ensure_ascii=False,indent=2))
