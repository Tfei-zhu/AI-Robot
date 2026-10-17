"""Read-only source/behavior-evidence audit; writes only this step's audit artifacts."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
baseline = runpy.run_path(str(OUT.parent / "s0-20261017/run_baseline.py"))
before = json.loads((OUT / "source-before.json").read_text())
after = baseline["snapshot"](ROOT)
expected = "d70a1763e1b34e4b0928c7c2365005eaecf1afa9db43989c6377095fa33f45af"
assert after["source_manifest_sha256"] == expected
assert after["head"] == before["head"] and after["branch"] == before["branch"] == "main"
assert after["staged_diff_sha256"] == before["staged_diff_sha256"]
changed = sorted(p for p in set(before["files_sha256"]) | set(after["files_sha256"])
                 if before["files_sha256"].get(p) != after["files_sha256"].get(p))
assert set(changed) == {"app/agents/go_workflow.py", "app/go_validation/service.py",
    "app/go_validation/store.py", "app/services/concurrency.py", "app/services/security.py",
    "docs/go-validation.md", "tests/test_multi_agent_http.py"}
log = (ROOT / "docs/multi-agent-execution-log.md").read_bytes()
prior = json.loads((OUT / "log-before.json").read_text())
assert hashlib.sha256(log[:prior["bytes"]]).hexdigest() == prior["sha256"]
rows = json.loads((OUT / "commands.json").read_text())
assert len({r["output"] for r in rows}) == len(rows)
for row in rows:
    assert hashlib.sha256((OUT / row["output"]).read_bytes()).hexdigest() == row["output_sha256"]
final = {label: [r for r in rows if r["label"] == label][-1]
         for label in ("all", "docker", "containers", "review-regressions", "docker-version", "docker-image")}
for row in final.values():
    assert row["exit_code"] == 0 and row["source_manifest_sha256"] == expected
    assert row["tracked_diff_sha256"] == after["tracked_diff_sha256"]
assert not (OUT / final["containers"]["output"]).read_text().strip()
audit = OUT / "network-audit.txt"
assert not audit.exists() or audit.stat().st_size == 0
assert "381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af" in (OUT / final["docker-image"]["output"]).read_text()


def junit(row):
    path = next(a.split("=", 1)[1] for a in row["argv"] if a.startswith("--junitxml="))
    root = ET.parse(path).getroot()
    assert not list(root.iter("failure")) and not list(root.iter("error"))
    return {(t.attrib["classname"], t.attrib["name"]): t for t in root.iter("testcase")}


offline, docker = junit(final["all"]), junit(final["docker"])
skipped = {key for key, t in offline.items() if t.find("skipped") is not None}
assert len(skipped) == 29
assert skipped <= set(docker) and all(docker[k].find("skipped") is None for k in skipped)
assert len([t for t in docker.values() if t.find("skipped") is not None]) == 0
assert "257 passed" in (OUT / final["all"]["output"]).read_text()
assert "102 passed" in (OUT / final["docker"]["output"]).read_text()
assert "Ran 8 tests" in (OUT / final["review-regressions"]["output"]).read_text()
subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
(OUT / "source-after.json").write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n")
result = dict(head=after["head"], source_manifest_sha256=expected,
    tracked_diff_sha256=after["tracked_diff_sha256"], changed_files=changed,
    old_log_prefix_preserved=True, execution_log_sha256=hashlib.sha256(log).hexdigest(),
    checked_command_outputs=len(rows), offline_passed=257, offline_skipped=29,
    all_skipped_cases_ran_under_docker=True, docker_suite_passed=102,
    docker_skipped=0, review_regressions_passed=8, network_audit_events=0,
    leftover_containers=0, git_diff_check="passed", paid_model_evaluations="not_run")
(OUT / "final-checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
files = {str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(OUT.rglob("*")) if p.is_file() and p.name != "artifact-manifest.json"}
manifest = dict(files=files, manifest_sha256=hashlib.sha256(
    json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
(OUT / "artifact-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(result, ensure_ascii=False, indent=2))
