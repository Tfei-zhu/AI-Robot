"""Human code review dispositions + machine resolution of actual test selectors."""
import collections,json,re,runpy,sys,xml.etree.ElementTree as ET
from pathlib import Path
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
# Status is scoped to each original task, not inferred from HTTP success or approve.
def task(number,status,code,checks,note,evidence=None):
    return dict(id=f'T{number:02}',status=status,code=code,tests=checks,note=note,evidence=evidence or [])
tasks=[
 task(1,'完成',[],[],'基线/依赖/提交/未提交差异、Python 和 Docker 均有实际快照；本轮环境另存。',['docs/evidence/s0.1-20261017/summary.json','docs/evidence/s9-20261017/source-before.json']),
 task(2,'完成',[],[],'旧目录只读复用分析已记录，未整文件覆盖或修改旧目录。',['docs/multi-agent-execution-log.md']),
 task(3,'完成',['app/go_validation/fixtures.py','app/go_validation/contracts.py'],['tests/test_go_contracts.py'],'固定三场景、标准库/单包、Go 专用入口。'),
 task(4,'完成',['app/go_validation/contracts.py'],['tests/test_multi_agent_contracts.py'],'任务/产物/审查/修复类型、长度、关联 ID 校验。'),
 task(5,'待验证',['app/agents/go_workflow.py'],['tests/test_multi_agent_review.py','tests/test_multi_agent_workflow.py'],'成功/修复/预算/异常路由已有防线；clarification_needed 仅枚举，标准闭环缺可达路径，完整状态设计未完成。'),
 task(6,'完成',['app/config.py','.env.example','app/agents/go_workflow.py'],['tests/test_multi_agent_config.py','tests/test_multi_agent_budget.py'],'非法配置启动拒绝；发送前共享调用额度和截止时间。'),
 task(7,'完成',['app/agents/supervisor.py'],['tests/test_multi_agent_agents.py::SupervisorPlanTests'],'原需求服务端锚定、固定接口；固定模型证明结构与交接，不能证明任意语义识别。'),
 task(8,'完成',['app/agents/code_agent.py'],['tests/test_multi_agent_agents.py::CodeGenerateTests','tests/test_multi_agent_agents.py::RepairTests'],'独立上下文/完整源码生成修复；不是普通聊天自动派工。'),
 task(9,'完成',['app/go_validation/nodes.py','app/go_validation/fixtures.py','app/agents/code_agent.py'],['tests/test_go_contracts.py','tests/test_go_acceptance.py'],'复用解析和产物边界；服务器测试不可改，模型测试可修复。'),
 task(10,'完成',['app/agents/supervisor.py','app/go_validation/contracts.py'],['tests/test_multi_agent_agents.py::SupervisorReviewTests','tests/test_multi_agent_review.py'],'结构化需求检查与定位、阻断/建议、实际源码和机器报告。'),
 task(11,'完成',['app/agents/role_runtime.py','app/go_validation/contracts.py'],['tests/test_multi_agent_agents.py','tests/test_multi_agent_runner_binding.py'],'完整必要源码/服务端 hash；不能重标历史验证。输入计数是估计，非精确供应商 token 硬上限。'),
 task(12,'完成',['app/agents/graph.py','app/agents/go_workflow.py'],['tests/test_multi_agent_regressions.py::MultiAgentRegressionTests::test_switch_off_uses_original_path_even_when_graph_was_cached','tests/test_agent.py'],'图运行时选择 Go 新/旧路径，普通聊天原路由不变。'),
 task(13,'完成',['app/go_validation/runner.py','app/agents/go_workflow.py'],['tests/test_go_runner.py','tests/test_multi_agent_runner_binding.py'],'真实 Docker；代码失败可审查修复，环境不可用终止。'),
 task(14,'完成',['app/agents/code_agent.py','app/agents/go_workflow.py','app/go_validation/contracts.py'],['tests/test_multi_agent_agents.py::RepairTests','tests/test_multi_agent_acceptance.py::AcceptanceCounterexamples::test_missing_requirement_after_machine_pass_is_repaired_and_rechecked'],'保留问题 ID、修复请求和各轮审查；addressed_issue_ids 表示交给修复的阻断项，不是自动证明已解决。'),
 task(15,'完成',['app/agents/go_workflow.py','app/go_validation/service.py','app/context/usage.py'],['tests/test_multi_agent_budget.py','tests/test_multi_agent_acceptance.py','tests/test_multi_agent_early_interruptions.py'],'失败/解析重试也扣额度；取消和同失败 hash 无进展停止。'),
 task(16,'完成',['app/go_validation/service.py'],['tests/test_multi_agent_regressions.py'],'角色模型/检索/runner 独立注入及结果组装。'),
 task(17,'完成',['app/main.py','app/go_validation/service.py','app/go_validation/contracts.py'],['tests/test_multi_agent_http.py::test_actual_json_sse_equal_and_persist_every_round'],'JSON 消费同一 stream；六种业务终态一致，HTTP 200 不作标签。'),
 task(18,'完成',['app/go_validation/store.py','app/go_validation/contracts.py'],['tests/test_multi_agent_http.py::test_historical_report_rows_read_through_http_after_store_reopen','tests/test_multi_agent_http.py::test_store_rejects_false_success_and_owner_overwrite'],'报告保存、旧字段默认及账户隔离；没有执行断点恢复。'),
 task(19,'完成',['app/go_validation/service.py','app/go_validation/runner.py'],['tests/test_multi_agent_http.py','tests/test_multi_agent_early_interruptions.py'],'各阶段取消/超时保留产物与调用，清理/落库后释放占用；强杀进程不承诺最终保存。'),
 task(20,'完成',['app/static/dashboard.html','scripts/test_multi_agent_dashboard.cjs'],[],'实际阶段、角色、轮次和 run_id；S6 真实浏览器历史证据，S9 未重新运行浏览器。',['docs/evidence/s6-20261017/browser-results.json']),
 task(21,'完成',['app/static/dashboard.html','scripts/test_multi_agent_dashboard.cjs'],[],'审查/预算/文件文本差异/终态与旧报告展示；S6 将响应替换与真实后端固定模型+Docker 分开记录。',['docs/evidence/s6-20261017/browser-results.json','docs/evidence/s6-20261017/backend-results.json']),
 task(22,'完成',['tests/test_multi_agent_workflow.py'],['tests/test_multi_agent_workflow.py'],'首次通过、修复通过、耗尽、无进展和环境终止。'),
 task(23,'完成',['tests/test_multi_agent_review.py','tests/test_multi_agent_contracts.py'],['tests/test_multi_agent_review.py','tests/test_multi_agent_contracts.py','tests/test_multi_agent_acceptance.py'],'错误 approve/旧 hash/可信测试/必要条目反例，S7 五处定向失效已检出并恢复。',['docs/evidence/s7-20261017/mutations.json']),
 task(24,'完成',['tests/test_multi_agent_http.py','tests/test_multi_agent_budget.py'],['tests/test_multi_agent_http.py','tests/test_multi_agent_budget.py'],'真实 ASGI/SQLite 账户/会话/取消/限额；模型与部分 runner 是替身，真实 Docker 节点另列。'),
 task(25,'完成',['tests/test_go_acceptance.py','tests/test_multi_agent_regressions.py'],['tests/test_go_acceptance.py','tests/test_multi_agent_regressions.py','tests/test_agent.py','tests/test_integration.py','tests/test_hardening.py'],'本地真实 Docker 和原业务代码回归；外部 Go API/AMQP/Milvus 联机与远程 CI 未验证。'),
 task(26,'阻塞',['eval/multi_agent_protocol.py','eval/multi_agent_live_cases.jsonl','eval/multi_agent_live_protocol.json'],['tests/test_multi_agent_eval.py','tests/test_multi_agent_eval_candidates.py'],'v1 机制协议和 v2 分组候选/独立评分已固定；真实模型配置、金额、币种/价格未冻结，缺用户累计费用上限。',['docs/evidence/s8.1-20261017/live-preflight.json']),
 task(27,'阻塞',['eval/run_multi_agent_eval.py'],['tests/test_multi_agent_eval.py'],'固定模型 120 次/312 调用的旧机制对照已保存；真实模型未运行，v2 没有质量成绩，不能宣称改善。',['docs/evidence/s8-20261017/summary.json','docs/evidence/s8.1-20261017/archive-proof.json']),
 task(28,'待验证',['docs/multi-agent.md','README.md','.github/workflows/ci.yml','scripts/check_multi_agent_rollback.py'],[],'本地文档、真实开关关闭和旧报告/聊天演练完成；远程 CI 未运行，T26/T27 未完成，整体推广门槛不通过。',['docs/evidence/s9-20261017/rollback/summary.json']),
]
# Validate that review mappings refer to real source symbols, never invented tests.
import ast
for row in tasks:
    for name in row['code']+row['evidence']:assert (ROOT/name).is_file(),name
    for selector in row['tests']:
        bits=selector.split('::');tree=ast.parse((ROOT/bits[0]).read_text())
        for symbol in bits[1:]:
            tree=next((node for node in tree.body if isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and node.name==symbol),None)
            assert tree is not None,selector
plan=(ROOT/'docs/multi-agent-implementation-plan.md').read_text()
for row in tasks:
    match=re.search(r'^\| '+row['id']+r' \| ([^|]+)\|',plan,re.M);assert match,row['id'];row['task']=match[1].strip()
acceptance=json.loads((OUT.parent/'s7-20261017/acceptance-map.json').read_text())
(OUT/'task-map.json').write_text(json.dumps(tasks,ensure_ascii=False,indent=2)+'\n')
if len(sys.argv)>1:
    xml=Path(sys.argv[1]);nodes=list(ET.parse(xml).iter('testcase'))
    matches=runpy.run_path(str(OUT.parent/'s7-20261017/map_results.py'))['matches']
    def resolve(selectors):
        result=[]
        for selector in selectors:
            found=[n for n in nodes if matches(n,selector) or (len(selector.split('::'))==2 and n.get('classname')==selector.split('::')[0].removesuffix('.py').replace('/','.')+'.'+selector.split('::')[1])]
            states=['failed' if n.find('failure') is not None else 'error' if n.find('error') is not None else 'skipped' if n.find('skipped') is not None else 'passed' for n in found]
            result.append(dict(selector=selector,records=len(found),status='not_run' if not found else 'passed' if set(states)=={'passed'} else ','.join(sorted(set(states))),nodes=[n.get('classname')+'::'+n.get('name') for n in found]))
        return result
    for row in tasks:
        row['resolved']=resolve(row['tests']);assert all(r['status']=='passed' for r in row['resolved']),row
    for row in acceptance:
        row['resolved']=resolve(row['tests']);row['status']='完成' if row['resolved'] and all(r['status']=='passed' for r in row['resolved']) else '待验证'
    assert len(acceptance)==18 and all(r['status']=='完成' for r in acceptance)
    result=dict(tasks=tasks,acceptance=acceptance,task_counts=dict(collections.Counter(r['status'] for r in tasks)),
        acceptance_counts=dict(collections.Counter(r['status'] for r in acceptance)),junit_input=str(xml.relative_to(ROOT)),
        local_tests=dict(passed=sum(not any(n.find(k) is not None for k in ('failure','error','skipped')) for n in nodes),failed=len(list(ET.parse(xml).iter('failure'))),errors=len(list(ET.parse(xml).iter('error'))),skipped=len(list(ET.parse(xml).iter('skipped')))),
        remote_ci=dict(status='not_run',reason='当前实现含未提交文件，未推送或触发匹配版本的远程 CI'),
        real_model=dict(status='blocked',requests=0,reason='无明确累计费用上限；固定版本/窗口/价格/账本未准备'),
        enablement=dict(passed=False,reason='真实质量/预算条件不足，clarification_needed 尚缺，保持默认关闭'))
    (OUT/'delivery-status.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'tasks','acceptance'}},ensure_ascii=False))
else:
    doc='''# S9 逐项交付核对

状态范围：**完成**指对应代码和本地机制证据具备，**待验证**包含明确实现缺口或未执行的交付门槛，**阻塞**指缺外部授权/配置。完成不等于真实模型效果已证实，也不把报告保存解释为恢复执行。代码/依赖清单见 [S9 证据](evidence/s9-20261017/)，本轮机器解析的最终节点与结果见 [delivery-status.json](evidence/s9-20261017/delivery-status.json)。原计划定义不改变，以下状态取代“初始待执行”。

## T01～T28

| 编号 | 原任务 | 当前状态 | 实际代码/证据与边界 |
| --- | --- | --- | --- |
'''
    for r in tasks:
        refs='、'.join('`'+p+'`' for p in r['code'])
        doc+=f"| {r['id']} | {r['task']} | **{r['status']}** | {refs}。{r['note']} |\n"
    doc+='''
28 项中 24 项完成、2 项待验证（T05/T28）、2 项阻塞（T26/T27）。T14 的 addressed_issue_ids 是交给修复的任务记录，是否解决仍看当前源码/机器验证/新审查，不能以该字段自证。每项精确测试选择器、既有证据路径和本轮匹配节点保存于机器结果；缺失/跳过/失败不能记作通过。

## A01～A18

以下“完成”限于验收矩阵定义的本地机制。S7/S8.1 已有实际通过证据，本轮按相同选择器重新解析完整 JUnit；若复验不通过，机器结果不会将该行标为完成。A03 的补充需求案例和 A10 的权限边界都不证明真实模型具有通用识别或抗注入能力。

| 编号 | 验收场景 | 状态 | 证据类型/限制 |
| --- | --- | --- | --- |
'''
    for r in acceptance:
        note=r['scope'].replace('本次','S7 当时')
        if r['id']=='A18':note+='；S9 另以环境变量 false 新进程，11 次真实 Docker 验证、9 份旧报告+1 份既有 multi-v1 重开读取，六个聊天案例'
        doc+=f"| {r['id']} | {r['criterion']} | 完成（本地机制） | {note} |\n"
    doc+='''
选择器原文见 [A 矩阵](multi-agent-acceptance-matrix.md)；本轮完整匹配节点以 [delivery-status.json](evidence/s9-20261017/delivery-status.json) 为准。S7 定向失效结果保留为历史证据，不宣称 S9 再做失效。没有把隔离副本中的预期失败混入正常版本通过数。

## 各类证据分开报告

| 类别 | 已知事实 | 仍未验证 |
| --- | --- | --- |
| 本地测试 | S9 显式关闭开关演练已实际通过；完整 pytest 复验、JUnit 统计及版本绑定见机器结果 | 本地不是 Python 3.11/远程 runner 结果 |
| 固定模型 | S9 回退 8 个任务、11 次 Go 模型调用和 11 次真实 Docker 验证；聊天六案例调用17次，均为非计费替身；S8 v1 完整对照 120 次/312 调用保留 | 不代表真实生成/审查能力；v2 无模型成绩 |
| 真实 Docker | S9 回退真实四阶段执行，源码/日志与清理确认已保存；完整 suite 中 Docker 项也实际启用 | Go race/全部并发输入无证明；第三方依赖/任意仓库不支持 |
| 浏览器 | S6 保存 Chromium、截图、响应替换和真实 ASGI 后端+固定模型/Docker 分列结果，当前 UI 源码没有变化 | S9 未重新运行浏览器；没有真实模型浏览器成绩 |
| 远程 CI | 已配置完整 Docker、离线回归和回退检查；移除存在 Secrets 就自动收费评测的路径，本地校验配置 | **未运行**；没有当前未提交版本的远程成功结论 |
| 真实模型 | **0 请求，阻塞**：未获得累计费用上限，缺固定版本/窗口/价格和持久账本配置 | 成功率、真实 Token/费用/推理延迟全部未知；未知不作零 |
| 外部业务联机 | 原问答/文章/检索/消费者代码的替身回归可运行 | 实际 Go API/AMQP/Milvus 本轮未连接 |

旧条件留出四组都为25%，不支持改善或推广；开发多 Agent 原样组同时使用更多调用，不能归因于多 Agent。v1 条件数据有重复/跨集基础需求，v2 按15族分集但仍为三个API上的人工相关任务，不宣称泛化代表性。整体 enablement.passed=false，保持默认关闭。

[可运行位置、配置与回退方法](multi-agent.md)列出当前实现能力。主要剩余项：正式澄清/拒绝路径未实现；真实模型和费用授权不足；远程 CI/外部服务联机未验证；没有执行恢复、普通聊天自动委派、跨进程协调。归档清单覆盖当前未提交源码，HEAD 单独不足以复现。
'''
    (ROOT/'docs/multi-agent-delivery-audit.md').write_text(doc)
