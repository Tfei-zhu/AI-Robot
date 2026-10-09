# Go 代码验证与修复逐项验收

对应用户确认的 25 项清单。每部分先记录开始前验证，完成后测试通过才进入下一部分。
状态中的“完成”必须有实际文件或测试依据；替身模型与真实模型结果分别记录。

## A 支持范围

开始前验证：工作区干净，已有统一 LangGraph 运行时；本地 Go 1.26.2，Python 3.13；Docker 客户端已安装但引擎未启动。项目依赖正在安装。

- [x] A1 标准库单包示例
- [x] A2 固定 Go 版本
- [x] A3 context 取消、并发任务池、channel 三个场景
- [x] A4 需求输入与代码、测试、执行结果、修复记录、参考来源输出
- [x] A5 首次生成后最多修复两轮

实现：`app/go_validation/contracts.py`。
测试：`python -m pytest tests/test_go_contracts.py -q`，10 项通过；覆盖三个场景、修复预算、实现/测试完整性、重复文件、路径穿越和 UTF-8 总量限制。

## B 隔离执行与验证

开始前验证：A 部分 10 项测试通过；Go 1.26.2 可用，Docker 29.4.3 客户端可用，引擎需要启动。采用独立 Docker 验证镜像，禁止将生成代码直接在宿主运行。

- [x] B1 检查 Docker 与 Go，确定沙箱方案
- [x] B2 网络、文件、密钥、CPU、内存、进程和时间限制
- [x] B3 服务端标准库校验与固定命令参数
- [x] B4 编译、go vet、go test
- [x] B5 结构化阶段、退出码、错误、耗时与超时报告
- [x] B6 日志上限与完成、失败、超时、取消清理

实现：`sandbox/go/` 固定摘要镜像与可信 AST 检查程序；`app/go_validation/runner.py`、`scripts/validate_go.py`。
测试：显式启用 `AIROBOT_TEST_DOCKER=1` 后 A+B 合计 24 项全部通过，无跳过。覆盖真实编译、vet、测试失败、外部依赖/unsafe/编译指令拒绝、跳过测试拒绝、日志超限、超时/取消、非特权用户、只读根目录、密钥隔离以及 Docker inspect 的网络与资源配置；检查无残留验证容器。
环境修复：Docker Desktop 因 AF_UNIX socket 故障无法启动。保留 run 与 docker-secrets-engine 目录及 settings-store.json 的 before-go-validation-20261008 备份，临时关闭 EnableDockerAI 后恢复 Linux 引擎；未重置 Docker 数据。
基础回归：开始接入前原有 52 项测试通过。

## C 接入 Agent

开始前验证：A+B 的 24 项真实测试通过；原有 52 项通过；确认现有网关接口仅允许 chat，需要为新功能增加明确路由白名单与按账户读取规则。新节点将接入原 get_agent_graph，保持现有聊天路径与新验证路径共用 LangGraph 运行时。

- [x] C1 代码与测试结构化输出及非法内容拒绝
- [x] C2 新增验证工具并接入 LangGraph
- [x] C3 检索、生成、验证、报错修复与再次验证闭环
- [x] C4 代码版本、报错、修改记录与 run_id 关联
- [x] C5 模型、工具次数与总耗时预算
- [x] C6 JSON 与 SSE 共用流程并展示阶段进度
- [x] C7 成功检查与失败代码、错误的真实展示

实现：新工具 `validate_go_code` 和原 LangGraph 的 go_retrieve/go_generate/go_validate/go_finish 节点；GoTaskService 统一流执行；SQLite 完整记录；新增按认证账户隔离的 POST /api/v1/go/tasks、POST /api/v1/go/tasks/stream、GET /api/v1/go/tasks/{run_id}。
测试：Go 工作流 + 原 Agent/加固测试 42 项通过。验证最多两次修复、原测试冻结、失败代码保留、非法模型输出拒绝、总超时、关闭流后的取消记录、来源/调用数、账户读取隔离、JSON/SSE 一致性；固定模型输出配合真实 Docker 完成失败到修复通过的闭环。真实模型调用尚缺本地密钥，未伪称已验证。

## D 评测与交付

开始前验证：C 的 42 项测试通过，B 真实容器验收通过；确认 LLM/Embedding 密钥均未配置，已向用户请求本地配置或明确离线验收偏好。固定模型样例的真实编译对比与配置模型的真实生成评测将分别标记。现有 Dashboard 可展示阶段事件，但需要新增代码与验证报告面板。

- [x] D1 三个场景的正常、边界与错误固定评测集
- [x] D2 人工确认的独立行为验收测试
- [x] D3 无限循环、异常、超时、依赖与取消验证
- [x] D4 直接生成与修复后的真实指标对比（固定模型输出 + 实际 Docker；真实模型质量评测待密钥）
- [x] D5 原有问答、文章查询与流式回归测试
- [x] D6 Dashboard 代码、验证与修复展示
- [x] D7 启动、范围、接口与可复现演示文档

| 项目 | 开始前验证 | 实现与完成后测试 |
| --- | --- | --- |
| D1 | C 工作流和真实 Docker 检查已通过，明确三场景接口 | `eval/go_cases.json` 共 9 项；正常、行为错误、编译错误各 3 项，真实运行均得到预期结果 |
| D2 | 确认模型自写测试不足以独立验收 | `app/go_validation/fixtures.py` 追加人工行为测试；弱断言不能掩盖三个场景的错误，修复不能删改服务端测试 |
| D3 | 确认外层超时和清理已有真实验收 | 真实 panic、os.Exit、无限循环、依赖拒绝、取消和重复取消全部通过；清理后没有残留验证容器 |
| D4 | 固定输出来源必须明确，真实模型密钥缺失 | `eval/run_go_eval.py --fixtures` 实际运行 9 项，报告 `docs/go-validation-fixture-report.json` 保存代码与日志；首次编译 6/9、测试 3/9，修复后均 9/9；6 个既定缺陷全部修复通过。`--live` 已实现并验证缺少密钥时明确拒绝，未调用真实模型 |
| D5 | 检查原聊天分支仍使用原工具路径 | `AIROBOT_TEST_DOCKER=1` 全量 pytest 95 项通过、无跳过；原 Agent 离线评测 6 场景全部通过。后续新增真实 HTTP/账户隔离和重复取消专项 2 项通过，合计 97 项 |
| D6 | Dashboard 可复用认证和 SSE 解析，生成内容必须按文本显示 | 新增场景输入、进度、完整代码、阶段日志、修复轮次、run_id 查询与取消；Playwright 浏览器验收通过：真实报告展示、错误到通过、脚本注入拒绝、提前断流处理；截图 `eval/reports/go/dashboard.png` |
| D7 | 确认现有 compose 应用没有 Docker 客户端和引擎访问权限 | `docs/go-validation.md` 给出宿主本地启动、隔离策略、API、预算、评测与部署边界；README/CI 已更新；语法检查和差异空白检查通过。CI 配置已写入，远程 Actions 尚未运行 |

---

## 交付状态与待完成的真实模型验收

25 项的实现和离线验收已完成，按 A → B → C → D 的顺序验证；上述真实指标均来自固定模型输出的真实 Docker 运行，不能说明真实模型有相同生成或修复能力。

- [ ] 配置本地 `AIROBOT_LLM_API_KEY`、模型地址/模型名，然后执行 `python eval/run_go_eval.py --live` 并审核结果。社区来源检索另需 Embedding 配置。当前密钥均为空，真实模型质量、模型调用耗时与 token 消耗尚未测得。

环境变化：为恢复 Docker 引擎，临时关闭 Docker Desktop 的 Docker AI；原设置和两处运行目录已保留备份。没有清空或重置 Docker 数据。项目代码尚未提交或推送。
