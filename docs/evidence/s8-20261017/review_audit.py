"""Supplementary review diagnostic only; does not change frozen primary scoring."""
import json
from pathlib import Path
import sys

OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT))
from eval.multi_agent_protocol import load_freeze,write_json
from eval.run_multi_agent_eval import audit_rows


def main():
    frozen=load_freeze(OUT/"freeze-v1");rows=[]
    for split in ("dev","holdout"):
        for trial in audit_rows(OUT/split,frozen):
            report=json.loads((OUT/split/trial["trial_id"]/"result.json").read_text())
            labels={s.get("artifact_hash"):s["correct"] for s in (trial["initial_independent"],trial["independent"]) if s.get("artifact_hash")}
            for review in report["reviews"]:
                # A review is an observation under test, NEVER the quality label.
                rows.append(dict(split=split,arm=trial["arm"],trial_id=trial["trial_id"],round=review["round"],
                    artifact_hash=review["artifact_hash"],verdict=review["verdict"],
                    independently_correct=labels.get(review["artifact_hash"])))
    metrics={}
    for split in ("dev","holdout"):
        for arm in ("multi_native","multi_equal3"):
            chosen=[r for r in rows if r["split"]==split and r["arm"]==arm]
            approved=[r for r in chosen if r["verdict"]=="approve"]
            known=[r for r in approved if r["independently_correct"] is not None]
            good=[r for r in chosen if r["independently_correct"] is True]
            metrics[split+"/"+arm]=dict(reviews=len(chosen),approve_known_wrong=sum(r["independently_correct"] is False for r in known),
                approve_known_denominator=len(known),approve_unknown=sum(r["independently_correct"] is None for r in approved),
                false_reject_known=sum(r["verdict"]!="approve" for r in good),false_reject_denominator=len(good))
    result=dict(freeze_hash=frozen["freeze_hash"],scope="supplementary diagnostic on independently scored initial/final versions; intermediate unscored versions stay unknown; not a replacement for frozen primary metrics",metrics=metrics,rows=rows)
    write_json(OUT/"review-audit.json",result)
    print(json.dumps(metrics,ensure_ascii=False))


if __name__=="__main__":main()
