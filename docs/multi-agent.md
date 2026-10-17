# Go 多 Agent 本地交付说明

交付位置：`/Users/xumanchun/Documents/agent项目/AI-Robot-latest`。基线 HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，分支 `main`；实现仍在未提交工作区，不能只检出该 HEAD 复现。逐文件版本、未提交 patch、可还原源码归档和执行命令见 [S9 证据](evidence/s9-20261017/)。默认关闭多 Agent，当前没有扩大启用的效果证据。

## 已实现的范围

Go 专用 `POST /api/v1/go/tasks` 与 `/api/v1/go/tasks/stream` 支持 `context_cancel`、`worker_pool`、`channel`，固定标准库、单包 `example` 和已有接口。打开开关后，主角色组织需求、委派代码角色、读取完整代码和真实验证报告审查，服务端决定结束或最多两轮修复。两个角色是工作流中的独立组件，可同模型或分别配置模型；不是开放式任意工具团队。

成功必须同时具有完整机器验证、当前产物版本的 approve、必要需求检查均 pass、无 blocking。服务端 hash 包含注入后的可信验收测试，验证和审查必须绑定同一版本。完整条目检查不保证任意自然语言需求的语义正确；固定测试也不能证明所有并发行为。

普通 `/api/v1/chat` 和 `/api/v1/chat/stream` 保持既有知识/文章/规范工具路径；**没有普通聊天自动识别并委派 Go 任务**。用户必须使用 Go 专用入口或 Dashboard 的 Go 区域。

JSON/SSE 消费同一个执行流，报告保存计划、逐轮源码/hash、验证日志、审查、调用、已知用量及停止原因。只用服务器最终 `status=passed` 表示成功，HTTP 200、流结束或模型文字都不是业务通过。Dashboard 按 run_id 展示阶段、问题和文件差异，分开处理断流、取消、超时、未知状态，并以文本渲染源码和日志。

## 配置与运行

当前本机已具备 `.venv`（Python 3.13.13）、Docker Linux Engine 和 `airobot-go-validator:1.26.2` 镜像。本次实际使用镜像 ID 见 S9 环境证据；其他机器按依赖文件安装并构建镜像，本地成功不等于这些机器已验证。支持目标 Python 3.11 的远程 CI 本轮未运行。

```sh
cd /Users/xumanchun/Documents/agent项目/AI-Robot-latest
# 首次安装时才执行；已有虚拟环境、.env 和数据应保留。
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
docker build -t airobot-go-validator:1.26.2 sandbox/go
# .env 不存在时复制：cp .env.example .env；不要覆盖现有文件。
```

实际模型业务运行需在本地 `.env` 配置 `AIROBOT_ADMIN_TOKEN`、`AIROBOT_LLM_API_KEY`、`AIROBOT_LLM_BASE_URL` 和 `AIROBOT_LLM_MODEL`。Embedding 用于检索；不可用时 Go 任务可以空参考资料继续，并记录检索警告。详细认证、网关账户隔离和 Docker 权限见 [Go 验证指南](go-validation.md)。不要把密钥写入命令证据或源码。

默认/回退配置：

```sh
export AIROBOT_GO_MULTI_AGENT_ENABLED=false
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开多 Agent 前，在 `.env` 设置 `AIROBOT_GO_MULTI_AGENT_ENABLED=true`，并填写 `AIROBOT_GO_MULTI_AGENT_SUPERVISOR_WINDOW`、`AIROBOT_GO_MULTI_AGENT_CODE_WINDOW` 为各角色**已核实的上下文窗口整数**，不能保留默认 0。默认输入/输出/安全预留要求窗口至少分别为 22144/26240；这只是配置下限，不是对某个供应商模型窗口的核实。可选 `AIROBOT_GO_MULTI_AGENT_SUPERVISOR_MODEL`、`…CODE_MODEL`；留空继承全局模型。全部字段、默认值及上限见 [配置模板](../.env.example) 和 [实际校验器](../app/config.py)。非法值启动拒绝。`AIROBOT_CONTEXT_MODE` 不必开启。

配置在进程导入时读取；修改开关后重启 Python 服务，不提供在线热切换 API。回退使用 `false` 重启，已有 SQLite 报告应保留。多 Agent 默认最多正常调用 7 次、共享异常重试 1 次、总计 8 次，验证最多 3 次、修复最多 2 次、检索最多 1 次；原流程最多 3 次模型调用。产品有发送前调用及截止时间约束，货币累计费用预占属于下面的评测工具，不能当成线上账户货币配额。

## 报告保存和恢复的边界

`GET /api/v1/go/tasks/{run_id}` 读取当前账户的 `data/go_tasks.sqlite3` 报告。旧 JSON 新字段补默认值，旧 single-v1 不重新认证成 multi-v1。回退后仍可读旧 single-v1 及此前 multi-v1 的保存内容。关闭和重开数据库只会恢复报告读取，**不会恢复 Agent、重新调用模型或继续运行代码**。

取消/断流/超时会保存已产生的进度，等待有界清理和写入后释放会话。进程崩溃、重启或强制杀进程可能遗留 running 报告；没有后台恢复、断点续跑或自动调度。重新提交会创建新 run_id。本地单进程并发槽位与会话隔离不等于跨进程队列；没有跨进程并发协调或报告保存期限管理。

## 不调用付费模型的验证

```sh
# 固定模型 + 真实 ASGI/SQLite/Docker；输出目录必须尚不存在。
PYTHON_DOTENV_DISABLED=1 AIROBOT_GO_MULTI_AGENT_ENABLED=false \
  .venv/bin/python scripts/check_multi_agent_rollback.py --output /private/tmp/airobot-rollback-new

# 完整行为检查。显式 Docker=1 后不能拿跳过冒充真实验证。
PYTHON_DOTENV_DISABLED=1 AIROBOT_GO_MULTI_AGENT_ENABLED=false AIROBOT_TEST_DOCKER=1 \
  .venv/bin/python -m pytest tests -q -ra
```

S9 回退演练以新进程的实际环境变量 false 启动，不修改生产 `.env` 或数据库：三场景 JSON/SSE 均走 single-v1；真实编译失败修复通过，持续错误最终 failed；8 次任务共 11 次固定模型请求和 11 次真实 Docker 验证，多 Agent 角色调用 0。重开独立 SQLite 后读取 9 个旧原始 JSON 和 1 个既有 multi-v1 报告，源码/日志和审查保持一致，跨账户均 404；普通聊天六个固定模型案例通过。详见 [本次回退结果](evidence/s9-20261017/rollback/summary.json)。这不是对生产服务执行在线切换，也不证明远程部署已成功。

逐项 T01～T28 和 A01～A18 状态及测试映射见 [S9 交付核对](multi-agent-delivery-audit.md)；最终全套本地结果在 [机器核对结果](evidence/s9-20261017/delivery-status.json)，历史 S6 浏览器结果单列，不伪装为本次浏览器执行。

## CI 与真实评测

[GitHub Actions 配置](../.github/workflows/ci.yml) 保留 Python 3.11 离线检查，并将真实 Docker 任务扩展为完整 pytest、显式关闭开关演练和固定输出对照，上传 JUnit/报告。本轮仅修改并本地校验配置，**没有推送、没有触发或取得匹配当前未提交版本的远程 CI 结果**。本地模拟命令不是远程 CI 通过。

CI 不再因 Secrets 存在就自动执行未限定累计费用的 RAGAS。真实收费评测要先取得明确累计费用上限，核实模型固定版本/窗口、端点、含额外 Token 计费的价格上界及币种，冻结新的数据/代码/模型/金额，再通过 `eval/run_multi_agent_eval.py prepare-live` 和持久账本检查。参考 [评测报告](multi-agent-evaluation.md)；旧 `eval/run_go_eval.py --live` 和 RAGAS 脚本未具备该累计费用账本，不作为本交付的授权评测入口。

本轮真实模型请求为 0，真实模型成功率、推理延迟、Token 和费用未验证，未知不能写为零。旧 v1 固定模型机制对照的留出四组均 25%，没有改善；原样组上限 3 次与 8 次不同，额外资源收益不能归因于多 Agent。v2 新候选数据只通过评分工具检查，尚无模型对照成绩。

## 明确剩余问题

- `clarification_needed` 只有契约枚举，标准闭环没有可达返回路径；不能声称已实现固定接口冲突时的正式澄清/拒绝流程。T05 保留待验证和实现缺口。
- 真实模型及推广条件缺费用授权等条件，T26/T27 阻塞。固定模型不能证明自然语言需求完整识别、审查准确性或抗提示注入能力。
- 远程 Python 3.11 CI、真实外部 Go API/AMQP/Milvus 联机、本次重新进行浏览器验收未运行。既有本地回归的模型及外部业务服务为替身；Docker 项真实。
- 没有任务执行恢复、普通聊天自动代码委派、第三方 Go 依赖、多包/任意仓库执行、Go race 检查或跨进程协调。报告保存可以使用，但不宣称这些能力已完成。

本地可运行交付与效果推广是两个判断。当前保留默认关闭，不提交、推送或发布。
