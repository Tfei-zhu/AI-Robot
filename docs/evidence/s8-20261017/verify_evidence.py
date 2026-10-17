"""Final S8 evidence: frozen source, full paired trials, failed labels and old files."""
import hashlib
import json
from pathlib import Path
import runpy
import sys
import tarfile
import xml.etree.ElementTree as ET

OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT))
from eval.multi_agent_protocol import ARMS,digest,load_freeze,aggregate
from eval.run_multi_agent_eval import audit_rows
from app.go_validation.contracts import CodeBundle,artifact_hash,ValidationReport,GoTaskResult
from eval.multi_agent_scoring import label


def need(condition,message):
    if not condition:raise ValueError(message)


def main():
    frozen=load_freeze(OUT/"freeze-v1")
    cases={c["id"]:c for c in frozen["cases"]}
    rows=[]
    for split,n in (("dev",72),("holdout",48)):
        data=json.loads((OUT/split/"report.json").read_text());trials=audit_rows(OUT/split,frozen)
        need(data["complete"] and data["full_split"] and len(trials)==n,"Incomplete main split")
        need(data["freeze_hash"]==frozen["freeze_hash"],"Freeze mismatch")
        need(data["metrics"]==aggregate(trials),"Cannot reproduce metrics")
        for row in trials:
            path=OUT/split/row["trial_id"]
            result=json.loads((path/"result.json").read_text())
            GoTaskResult.model_validate(result)
            need(row["actual_client_calls"]==len(row["calls"])<=ARMS[row["arm"]]["max_calls"],"Actual requests beyond cap")
            need(result["model_calls"]==len(row["calls"]),"Server and captured request counts differ")
            need(row["cost_estimate"]==0 and all(c["usage"] is None for c in row["calls"]),"Fixture usage/cost semantics changed")
            need(all(c["index"]==i for i,c in enumerate(row["calls"],1)),"Call sequence not complete")
            need(not row.get("rerun_of") and not row.get("rerun_reason"),"Main trial rerun must be declared")
            need(row["freeze_hash"]==frozen["freeze_hash"],"Trial freeze mismatch")
            for role in ("initial_independent","independent"):
                score=row[role]
                actual_report=ValidationReport.model_validate(score["report"]) if score.get("report") else None
                recomputed=label(cases[row["case_id"]],actual_report,artifact=score.get("artifact_hash"),
                    scorer_hash=score.get("scorer_input_hash"),refusal=result["status"]=="failed" and result.get("stop_reason")=="clarification_needed")
                need(recomputed["correct"]==score["correct"] and recomputed["checks"]==score["checks"],"Independent labels cannot be reproduced from actual reports")
                if score.get("report"):
                    scorer=CodeBundle(files=score["scorer_files"])
                    need(artifact_hash(scorer.files)==score["scorer_input_hash"]==score["report"]["artifact_hash"],"Independent report not bound")
                    if score["correct"] is True:
                        need(score["report"]["status"]=="passed" and score["report"]["container_removed"] and all(c["status"]=="pass" for c in score["checks"]),"Incomplete success evidence")
                    bundles=[CodeBundle.model_validate(a["bundle"]) for a in result["attempts"]]
                    need(score["artifact_hash"] in {artifact_hash(b.files) for b in bundles},"Score not tied to retained artifact")
            rows.append(row)
    need(len(rows)==120,"Main runs must be 120")
    for stop in ("cancel","timeout"):
        smoke=audit_rows(OUT/("smoke-"+stop),frozen)
        need(len(smoke)==4,"All four smoke arms required")
        need(all(r["business_status"]==("cancelled" if stop=="cancel" else "timeout") for r in smoke),"Interruption failed")
        need(all(r["independent"]["correct"] is None for r in smoke),"Interrupted no-artifact run became success")
    live=json.loads((OUT/"live-preflight.json").read_text())
    need(live["status"]=="blocked" and live["calls_sent"]==0,"Live unexpectedly enabled")
    need(json.loads((OUT/"enablement-gate.json").read_text())["passed"] is False,"Quality gate became green")
    need(json.loads((OUT/"data-audit.json").read_text())["inference_eligible"] is False,"Repeated tasks treated as independent")
    need(json.loads((OUT/"cost-process-proof.json").read_text())["passed"],"Cumulative process guard failed")
    need(json.loads((OUT/"paid-guard-proof.json").read_text())["inner_exit_code"]==2,"Optimized authorization gate failed")
    base=runpy.run_path(str(OUT.parent/"s0-20261017/run_baseline.py"))
    current=base["snapshot"](ROOT);before=json.loads((OUT/"source-before.json").read_text())
    need(current["files_sha256"]==json.loads((OUT/"source-final-validation.json").read_text())["files_sha256"],"Final tested source changed")
    need(all(current["files_sha256"].get(p)==sha for p,sha in before["files_sha256"].items()),"Preexisting source was modified")
    history=json.loads((OUT/"preservation-before.json").read_text())
    log=(ROOT/"docs/multi-agent-execution-log.md").read_bytes()
    need(digest(log[:history["log_bytes"]])==history["log_sha256"],"Old execution log modified")
    need(all(digest((ROOT/p).read_bytes())==sha for p,sha in history["old_evidence"].items()),"Old evidence modified")
    commands=json.loads((OUT/"commands.json").read_text())
    final_test=[c for c in commands if c["label"]=="all-docker"][-1]
    xml=next(a.split("=",1)[1] for a in final_test["argv"] if a.startswith("--junitxml="))
    for suite in ET.parse(xml).iter("testsuite"):
        need(all(suite.get(k)=="0" for k in ("errors","failures","skipped")),"Final suite did not fully pass")
    need(final_test["source_manifest_sha256"]==current["source_manifest_sha256"],"Final regression version differs")
    containers=next(c for c in commands if c["label"]=="containers-after")
    need(not (OUT/containers["output"]).read_text().strip(),"Sandbox containers remain")
    for command in commands:
        need(digest((OUT/command["output"]).read_bytes())==command["output_sha256"],"Output digest mismatch")
        allowed_doc=(command["label"]=="summary" and command.get("added_source_paths")==["docs/multi-agent-evaluation.md"] and not command.get("modified_source_paths"))
        need(command["exit_code"]==0 and (command["source_unchanged"] or allowed_doc),"Unexpected failed or changing check")
    if (OUT/"source-final.tar.gz").exists():
        with tarfile.open(OUT/"source-final.tar.gz","r:gz") as archive:
            archived={m.name:digest(archive.extractfile(m).read()) for m in archive.getmembers()}
        need(archived==current["files_sha256"],"Archive differs from final source")
    final=dict(passed=True,head=current["head"],branch=current["branch"],source_manifest_sha256=current["source_manifest_sha256"],
        tracked_diff_sha256=current["tracked_diff_sha256"],freeze_hash=frozen["freeze_hash"],
        main_trials=120,main_actual_fixture_calls=sum(len(r["calls"]) for r in rows),smoke_interruptions=8,
        paid_model_requests=0,all_preexisting_source_preserved=True,old_log_and_evidence_preserved=True,
        immutable_scoring_and_models=True,live_blocked=True)
    (OUT/"source-after.json").write_text(json.dumps(current,ensure_ascii=False,indent=2)+"\n")
    (OUT/"final-checks.json").write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(final,ensure_ascii=False))


if __name__=="__main__":main()
