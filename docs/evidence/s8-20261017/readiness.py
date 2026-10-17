"""Machine-readable release/evaluation gates, separate from collection exit status."""
import json
from pathlib import Path
import sys

OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT))
from eval.multi_agent_protocol import load_freeze,write_json


def main():
    frozen=load_freeze(OUT/"freeze-v1")
    financial=json.loads((OUT/"live-preflight.json").read_text())
    data=json.loads((OUT/"data-audit.json").read_text())
    holdout=json.loads((OUT/"holdout/report.json").read_text())
    checks=dict(live_model_evaluated=False,independent_task_holdout=data["inference_eligible"],
        zero_known_holdout_false_accepts=all(m["false_accepts"]==0 for m in holdout["metrics"].values()),
        live_cost_budget_fixed=financial["status"]!="blocked",live_quality_no_drop=None,live_latency_goal_met=None)
    gate=dict(freeze_hash=frozen["freeze_hash"],passed=all(v is True for v in checks.values()),checks=checks,
        source="actual independent labels, data audit and authorization preflight; approve excluded",
        production_switch_changed=False)
    write_json(OUT/"enablement-gate.json",gate)
    write_json(OUT/"live-readiness.json",dict(status="blocked",financial_and_model=financial,
        data_readiness=data,refusal_path_implemented=False,gate=gate,
        remaining=["用户明确累计费用上限/币种与持久账本","核实固定模型/窗口/单价上界并重新冻结",
                   "新的去重/按任务族分组的真实需求样本及划分","正式拒绝不可完成需求的路径与新版本回归",
                   "新冻结版本完成 live 开发与留出；保留全部失败与费用未知"] ))
    print(json.dumps(dict(passed=gate["passed"],checks=checks),ensure_ascii=False))


if __name__=="__main__":main()
