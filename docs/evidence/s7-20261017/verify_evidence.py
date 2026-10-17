"""Verify final source, concrete test results, mutation failures and preserved history."""
import hashlib
import json
from pathlib import Path
import runpy
import tarfile
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
baseline = runpy.run_path(str(OUT.parent/"s0-20261017/run_baseline.py"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    before=json.loads((OUT/"source-before.json").read_text())
    validated=json.loads((OUT/"source-final-validation.json").read_text())
    current=baseline["snapshot"](ROOT)
    assert current["files_sha256"] == validated["files_sha256"], "Final source differs from tested source"
    with tarfile.open(OUT/"source-final.tar.gz","r:gz") as archive:
        archived={member.name:sha(archive.extractfile(member).read()) for member in archive.getmembers()}
    assert archived == current["files_sha256"]
    assert sha((OUT/"tracked-working-tree.patch").read_bytes())==current["tracked_diff_sha256"]
    assert sha((OUT/"staged-working-tree.patch").read_bytes())==current["staged_diff_sha256"]
    assert current["head"] == before["head"] and current["branch"] == before["branch"]
    assert current["staged_diff_sha256"] == before["staged_diff_sha256"]
    added=sorted(set(current["files_sha256"])-set(before["files_sha256"]))
    modified=sorted(p for p in before["files_sha256"] if current["files_sha256"].get(p)!=before["files_sha256"][p])
    assert not modified, "S7 must preserve pre-existing source exactly"
    assert added == ["docs/multi-agent-acceptance-matrix.md", "tests/test_multi_agent_acceptance.py", "tests/test_multi_agent_early_interruptions.py"]
    commands=json.loads((OUT/"commands.json").read_text())
    expected_failures={"mutation-machine-gate","mutation-review-hash","mutation-trusted-test","mutation-total-budget","mutation-cancel-propagation"}
    for row in commands:
        assert sha((OUT/row["output"]).read_bytes()) == row["output_sha256"]
        assert row["source_unchanged"]
        assert row["exit_code"] == (1 if row["label"] in expected_failures else 0), row
    for label in ["all-docker-final","business","agent-fixtures","containers-after"]:
        row=next(r for r in commands if r["label"]==label)
        assert row["source_manifest_sha256"]==current["source_manifest_sha256"] and row["exit_code"]==0
    assert not (OUT/next(r["output"] for r in commands if r["label"]=="containers-after")).read_text().strip()
    matrix=json.loads((OUT/"matrix-results.json").read_text())
    assert matrix["inputs"] == ["all-docker-final.xml"] and matrix["all_18_passed"]
    mutations=json.loads((OUT/"mutations.json").read_text())
    assert len(mutations)==5
    for mutation in mutations:
        assert mutation["killed_by_assertion"] and mutation["exit_code"]==1 and mutation["restored_exit_code"]==0
        assert mutation["restored_sha256"]==mutation["original_sha256"]==current["files_sha256"][mutation["source"]]
    preservation=json.loads((OUT/"preservation-before.json").read_text())
    log=(ROOT/"docs/multi-agent-execution-log.md").read_bytes()
    assert sha(log[:preservation["execution_log_bytes"]])==preservation["execution_log_sha256"]
    assert all(sha((ROOT/p).read_bytes())==digest for p,digest in preservation["prior_evidence"].items())
    final=ET.parse(OUT/"all-docker-final.xml")
    for suite in final.iter("testsuite"):
        assert suite.get("errors")==suite.get("failures")==suite.get("skipped")=="0"
    docker_names={
        "tests.test_go_acceptance": ["test_server_tests_detect_bad_behavior_even_with_weak_model_tests","test_real_panics_exit_and_infinite_loop","test_real_repair_cannot_remove_server_tests","test_http_real_graph_json_stream_and_report_ownership"],
        "tests.test_go_runner": ["test_real_checks","test_timeout_and_cancel_remove_container","test_real_identity_filesystem_and_secret_isolation","test_real_container_resource_and_network_configuration","test_repeated_cancellation_still_waits_for_cleanup"],
        "tests.test_go_workflow": ["test_actual_graph_repairs_using_real_go_error"],
        "tests.test_multi_agent_workflow.RealSandboxClosedLoopTests": ["test_real_first_pass","test_real_repair_after_compile_or_test_failure"],
        "tests.test_multi_agent_regressions.RealServiceRegressionTests": ["test_actual_service_first_pass_and_repair_use_real_docker"],
        "tests.test_multi_agent_http": ["test_real_docker_http_interrupt_preserves_report_and_confirms_cleanup"],
        "tests.test_multi_agent_acceptance.RealCompileAcceptance": ["test_real_compile_error_is_repaired_with_fresh_validation_and_review"],
    }
    docker=[]
    for classname,names in docker_names.items():
        for name in names:
            selected=[t for t in final.iter("testcase") if t.get("classname")==classname and
                      (t.get("name")==name or t.get("name").startswith(name+"["))]
            assert selected, (classname,name)
            assert all(not any(t.find(tag) is not None for tag in ("failure","error","skipped")) for t in selected)
            docker.extend(classname+"::"+t.get("name") for t in selected)
    (OUT/"real-docker-tests.json").write_text(json.dumps(dict(nodes=sorted(set(docker)),unique_nodes=len(set(docker)),records=len(docker)),indent=2)+"\n")
    (OUT/"source-after.json").write_text(json.dumps(current,ensure_ascii=False,indent=2)+"\n")
    report=dict(passed=True,head=current["head"],branch=current["branch"],
        source_manifest_sha256=current["source_manifest_sha256"],tracked_diff_sha256=current["tracked_diff_sha256"],
        preexisting_source_preserved=True,prior_log_and_evidence_preserved=True,added_source=added,
        final_validation_bound=True,expected_mutant_failures=5,restored_passes=5,
        all_18_passed=True,real_docker_unique_nodes=len(set(docker)),real_docker_records=len(docker),
        final_junit_suite=[s.attrib for s in final.iter("testsuite")])
    (OUT/"final-checks.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":
    main()
