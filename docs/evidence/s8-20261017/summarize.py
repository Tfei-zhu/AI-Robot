"""Report actual frozen S8 evidence without selecting successful reruns."""
import json
from pathlib import Path
import sys

OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT))
from eval.multi_agent_protocol import ARMS,aggregate,load_freeze,write_json
from eval.run_multi_agent_eval import audit_rows


def pct(value):return "未知" if value is None else f"{100*value:.1f}%"
def ms(value):return "未知" if value is None else f"{value/1000:.2f}"


def main():
    frozen=load_freeze(OUT/"freeze-v1")
    reports={split:json.loads((OUT/split/"report.json").read_text()) for split in ("dev","holdout")}
    rows={split:audit_rows(OUT/split,frozen) for split in reports}
    for split,data in reports.items():
        if not data["complete"] or not data["full_split"] or data["freeze_hash"]!=frozen["freeze_hash"]:
            raise ValueError("Incomplete/fingerprint-mismatched split must not be treated as final")
        if data["metrics"]!=aggregate(rows[split]):raise ValueError("Report aggregation differs from raw trials")
        expected_cases={c["id"] for c in frozen["cases"] if c["split"]==split}
        for arm in ARMS:
            selected=[r for r in rows[split] if r["arm"]==arm]
            if {r["case_id"] for r in selected}!=expected_cases or len(selected)!=len(expected_cases):
                raise ValueError("Missing/duplicated paired cases")
    paired={}
    for split in reports:
        paired[split]={}
        for name,a,b in [("native","single_native","multi_native"),("equal3","single_equal3","multi_equal3")]:
            left={r["case_id"]:r for r in rows[split] if r["arm"]==a}
            right={r["case_id"]:r for r in rows[split] if r["arm"]==b}
            pairs=[(left[k],right[k]) for k in sorted(left)]
            paired[split][name]=dict(cases=len(pairs),
                both_correct=sum(x["independent"]["correct"] is True and y["independent"]["correct"] is True for x,y in pairs),
                only_single_correct=sum(x["independent"]["correct"] is True and y["independent"]["correct"] is not True for x,y in pairs),
                only_multi_correct=sum(y["independent"]["correct"] is True and x["independent"]["correct"] is not True for x,y in pairs),
                neither_verified_correct=sum(x["independent"]["correct"] is not True and y["independent"]["correct"] is not True for x,y in pairs))
    all_rows=rows["dev"]+rows["holdout"]
    audit=json.loads((OUT/"data-audit.json").read_text())
    summary=dict(freeze_hash=frozen["freeze_hash"],model_source="fixed_response_scripts",docker="real Go 1.26.2",
        development=reports["dev"]["metrics"],holdout=reports["holdout"]["metrics"],
        exploratory_combined=aggregate(all_rows),paired=paired,
        total_trials=len(all_rows),total_actual_fixture_invocations=sum(len(r["calls"]) for r in all_rows),
        billable_model_requests=0,paid_cost=0,provider_usage="unknown, never substituted with zero tokens",
        inference="No evidence of real model improvement; holdout false accepts block wider enablement.",
        source_hashes=frozen["source_hashes"],image_id=frozen["docker_image_id"],data_audit=audit)
    write_json(OUT/"summary.json",summary)
    doc=f"""# S8 离线对照与真实评测准备（T26–T27）

本步已完成离线采集和真实评测准备，**没有证明真实模型改善，也不满足扩大启用条件**。所有模型/检索响应为固定替身，业务验证与独立评分均使用真实 Docker。收费模型请求为 0；没有用户给出的累计费用上限，没有运行真实模型评测。

协议指纹 `{frozen['freeze_hash']}`。样本为三个固定接口场景各 10 条，每场景 6 条开发、4 条留出，合计 18/12；本轮各组每条运行一次，共 120 次。先完成开发集 72 次，再锁定并执行留出集 48 次；期间未修改 app/eval 源码、样本、评分、配置或镜像。数据是预先构造且作者可见的机制样本，模板相关，不是第三方盲测或随机总体样本。没有用留出结果调参。

冻结原文、划分与源码清单见 [freeze.json](evidence/s8-20261017/freeze-v1/freeze.json)，原始样本见 [multi_agent_cases.jsonl](../eval/multi_agent_cases.jsonl)。所有 trial、调用输入/输出、角色、用量、事件、每轮报告、产物及 hash、独立评分文件均在 [本次证据](evidence/s8-20261017/) 中；[summary.json](evidence/s8-20261017/summary.json) 可从原始记录重算。原业务文件与原评测脚本未覆盖。

**数据限制：30 条是固定输出故障条件，只有 {audit['unique_public_requirements']} 条不同公开需求，{audit['cross_split_public_requirement_groups']} 组基础需求同时出现于开发/留出条件。** 因而“留出”只表示未用于调试的故障条件，不能声称是独立任务泛化留出；未来真实质量评测必须另建去重/按任务族分组的数据并重新冻结。数据审计见 [data-audit.json](evidence/s8-20261017/data-audit.json)。没有在看过本轮留出后换样本、调评分或重标成功来补救这个证据限制。

| 组 | 流程与调用上限 | 其他预算及差异 |
| --- | --- | --- |
| single_native | 原单生成流程，最多 3 次请求，解析失败/调用失败重试也占这 3 次 | 保留原两轮修复和 120 秒生成上限，输出 8192；没有为对照偷偷提高到 8 次 |
| multi_native | 主 Agent 计划/审查 + 子 Agent 生成，正常 7 次 + 共享重试 1 次，共最多 8 次 | 主角色 60 秒/4096 输出，代码角色 120 秒/8192 输出；更多调用和角色分配都是资源混杂因素 |
| single_equal3 | 原流程加评测侧共同限制：总额 3 次 | 每次 60 秒、8192 输出、16000 输入估计上限，与 multi_equal3 相同；估计未校准，不能称精确 Token 硬上限 |
| multi_equal3 | 同一多 Agent 实现减到总额 3 次，正常 3 次、异常重试 0 次 | 一次计划/生成/审查即用尽，通常没有修复余量；生产配置约束决定此分配，不能把预算不足隐去 |

各组使用相同任务、同一模型身份（固定脚本；未来 live 必须同一已核实模型版本）、同一固定空检索、360 秒任务截止、3 次验证、最多两次修复、1 次检索和相同 Docker。equal3 只统一上限，不保证相同实际调用、Token、修复机会或延迟；单流程的解析重试在其 3 次总额内，新流程保持自己的角色/重试规则。这是同预算产品策略对照，不能独立识别“多 Agent 架构”的因果效应。轮换组执行顺序以减轻固定先后顺序影响。

独立评分不读取 approve：完成业务流程后重新注入不可修改的独立测试，移除模型自己的测试，另算 scorer_input_hash 并绑定真实报告；保留原产物 hash。检查错误身份、取消前等待、输入/顺序、运行期协程上限观测、取消部分和、函数 Go AST 文档注释等需求清单。协程观测是代表性用例，不能证明所有输入下的并发语义。不可完成的第三方依赖要求只接受服务端 failed/clarification_needed 的明确拒绝；没有改规则给固定输出通过。缺测试事件、无产物、环境不可用记未知，未知不算成功。

以下“成功率”是独立评分成功数/全部运行数（包含失败/中断/未知），不是业务 passed 比例。误批准为业务 passed 但独立失败，分母为业务 passed；误拒绝分母为独立正确的产物。修复率分母为首个产物独立失败的任务，包括未实际进入修复的任务，未知首产物不混算。时间为实测墙钟秒：流程延迟包含生成/验证/清理；端到端另加离线评分。固定模型几乎无推理延迟，不能外推真实模型速度。费用 0 仅因为本轮无计费模型请求；所有缺失 Token 都保持 null。

"""
    for split,title in [("dev","开发集（18 条/组）"),("holdout","留出集（12 条/组，主要结果）")]:
        doc+=f"**{title}**\n\n| 组 | 独立成功 | 未验证 | 实际固定客户端调用 | 误批准 | 误拒绝 | 修复成功率 | 流程 P50/P95 秒 | 含评分 P50/P95 秒 | 费用 |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        for arm,m in reports[split]["metrics"].items():
            doc+=f"| {arm} | {m['independent_successes']}/{m['runs']}（{pct(m['independent_success_rate'])}） | {m['unverified_runs']} | {m['model_calls']} | {m['false_accepts']}/{m['false_accept_denominator']}，未知 {m['false_accept_unknown']} | {m['false_rejects']}/{m['false_reject_denominator']} | {pct(m['repair_success_rate'])}（分母 {m['repair_eligible']}） | {ms(m['generation_p50_ms'])}/{ms(m['generation_p95_ms'])} | {ms(m['end_to_end_p50_ms'])}/{ms(m['end_to_end_p95_ms'])} | 0（非计费替身） |\n"
        doc+="\n"
    doc+="""逐角色请求数、已知 Token 小计、未知用量请求数、需求检查通过率、停止原因及 Wilson 95% 区间见原始 summary；区间仅描述本批二项计数，模板相关且样本小，不能作真实模型效果推断。开发与留出分别报告，合并统计明确标为探索性，不代替留出结果。

另有 [主 Agent 审查诊断](evidence/s8-20261017/review-audit.json)：只将已独立评分的首/末版本作为标签，对 approve 本身统计错误；未独立评分的中间轮保持未知。这个补充诊断不改变冻结的主指标或通过门槛，不能拿业务误放行数冒充全部审查的误批准率。

留出集的错误批准包含遗漏补充注释和未明确拒绝不可完成需求。所有组均有已知误放行，不满足冻结的“留出误批准为零、质量不下降”门槛。开发集 native 多 Agent 若有较高成功率，也来自预设固定响应脚本及更多调用，不能归因于真实多 Agent 能力。equal3 的开销/修复不足是实测结果，未提高其预算来制造改善。没有扩大生产开关。

代码核对另发现：`clarification_needed` 当前仅在 stop_reason 枚举出现，标准闭环尚无返回该终态的可达路径。因而不可完成要求的正式拒绝能力仍有缺口；不能把这项固定样本的失败全部归结为模型判断。应在后续产品版本解决并用新冻结实验复验，不能回改本轮规则或结果。

**失败、中断和重跑**

每次 trial 在首次请求前创建独立目录和 started 记录；各次调用失败、解析重试、取消、超时和实际输出都保存。恢复检查读取 pending 记录作为未知中断，不能把未知调用或费用补零；同名目录拒绝覆盖。正式留出再次启动必须附 prior run 和 reason，不自动筛除失败重跑。开发期另有 cancel/timeout 人工中断冒烟记录，明确排除主要质量统计。主对照中的预算耗尽、持续错误、误批准均保留在分母；本轮没有因质量差重跑留出。

**真实模型待运行条件**

真实预检结果见 [live-preflight.json](evidence/s8-20261017/live-preflight.json)。目前缺明确累计费用上限、已核实的固定模型 ID/上下文窗口、单价上界及核实日期/币种、持久化费用账本。qwen-plus 只是配置中的候选别名，没有将其冒充固定快照。模板 [模型配置](../eval/multi_agent_live_model.example.json) 与 [价格上界](../eval/multi_agent_pricebook.example.json) 不含凭据、不假造价格。

之后获明确费用授权时，须先新建冻结版本并固定金额目标，再执行 live 开发集和留出集。`freeze --model-config … --rates … --cost-cap 金额`，随后 `prepare-live --cost-cap 同额 --cost-ledger 持久路径`。运行前再次要求同一上限及账本；SDK 重试关闭，请求模型 ID 必须为已核实版本，返回版本缺失/不符即停止后续请求。请求前以整个已核实窗口及最大输出按保守费率持久化预占，未知/失败用量保留预占；重启和新输出目录不返还额度，不允许改价或增大既有账本上限。费用是单价上界估算而非账单；若服务商返回超出预占的异常用量，保留超额并封锁账本后续调用。

本协议未来 live 每任务每组 3 次，四组完整共 360 次任务运行，最坏 1530 次模型请求；金额预算可以更早停止，未运行项必须显示。默认不读 .env，凭据只能由明确的运行环境提供且不落盘。live 不允许使用离线中断注入标志。模型/价格/费用条件未满足时服务端阻止客户端构建和请求。没有凭此准备工作宣称真实质量、成本或延迟改善。
"""
    (ROOT/"docs/multi-agent-evaluation.md").write_text(doc)
    print(json.dumps(dict(trials=summary["total_trials"],calls=summary["total_actual_fixture_invocations"],paired=paired),ensure_ascii=False))


if __name__=="__main__":main()
