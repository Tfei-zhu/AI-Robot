"""Disclose repeated public tasks: fault-condition holdout is not task generalization."""
import json
from pathlib import Path
import sys

OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT))
from eval.multi_agent_protocol import load_freeze,write_json,digest


def main():
    frozen=load_freeze(OUT/"freeze-v1");groups={}
    for case in frozen["cases"]:
        key=digest((case["scenario"]," ".join(case["requirement"].split())))
        groups.setdefault(key,[]).append(dict(id=case["id"],split=case["split"],fixture_profile=case["fixture_profile"]))
    cross=[dict(public_requirement_hash=k,cases=v) for k,v in groups.items() if len({c["split"] for c in v})>1]
    result=dict(freeze_hash=frozen["freeze_hash"],frozen_conditions=30,unique_public_requirements=len(groups),
        cross_split_public_requirement_groups=len(cross),cross_split_groups=cross,
        inference_eligible=False,reason="Fixed-output fault-condition holdout only; repeated public tasks and correlated templates do not provide independent task-generalization evidence.",
        live_quality_prerequisite="Create a new deduplicated/grouped real-task protocol before any generalization or quality-improvement claim; do not silently relabel this run.")
    write_json(OUT/"data-audit.json",result)
    print(json.dumps(dict(conditions=30,unique_requirements=len(groups),cross_split_groups=len(cross),inference_eligible=False)))


if __name__=="__main__":main()
