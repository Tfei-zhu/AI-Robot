# Go 标准库示例验证第一版

输入指定场景与中文需求，系统检索资料、生成单包代码和测试，在隔离环境验证，最多修复两轮。
工具链固定 Go 1.26.2。所有示例使用 `package example`；只接受当前目录的 `.go` 文件，至少一个实现与一个测试文件，最多 8 个文件、总计 64 KiB。模型不能提交 go.mod、依赖配置、命令或执行参数。

## 三个场景的固定接口

| 场景 | 接口 | 行为 |
| --- | --- | --- |
| context_cancel | WaitForCancel(ctx context.Context) error | 等待取消并返回 ctx.Err() |
| worker_pool | WorkerPool(ctx context.Context, jobs []int, workers int) ([]int, error) | 并发上限为 workers；输入乘二并保持顺序；不修改输入；非法 workers 或取消返回错误 |
| channel | SumChannel(ctx context.Context, input <-chan int) (int, error) | 求和直到关闭；取消返回 ctx.Err()；nil channel 也响应取消 |

输出包含 run_id、场景、最终状态、每轮完整源码与验证报告、修改说明、资料来源、调用次数和耗时。只有全部规定检查通过才标记 passed；该状态只覆盖当前测试和工具链，不代表任意行为均正确。

原单流程历史记录见根目录 GO_VALIDATION_CHECKLIST.md；当前可选多 Agent、配置、回退和限制以 [S9 交付说明](multi-agent.md) 及 [逐项核对](multi-agent-delivery-audit.md) 为准。

---

## 本地启动

前提：Python 3.11+、运行中的 Docker Linux 引擎。宿主无需安装 Go；镜像内版本固定为 1.26.2，基础镜像摘要写在 Dockerfile 中。已有 docker-compose 的应用镜像没有 Docker 客户端和引擎访问权限；本版代码验证按以下方式在宿主启动 Python 服务。

在项目根目录执行 PowerShell：

```powershell
# 使用 UTF-8 读取依赖文件，避免中文 Windows 默认编码导致安装失败。
$env:PYTHONUTF8 = '1'
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# 引擎和固定镜像必须可用；验证任务不会自动下载镜像。
docker info
docker build -t airobot-go-validator:1.26.2 sandbox/go

# 首次配置复制示例；已有 .env 时保留原配置并直接编辑。
if (-not (Test-Path .env)) { Copy-Item .env.example .env }

# 在 .env 本地配置凭据后启动，浏览器打开 /dashboard。
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

必须配置 `AIROBOT_ADMIN_TOKEN`、`AIROBOT_LLM_API_KEY` 及模型地址/模型名。社区资料检索还需要 `AIROBOT_EMBEDDING_API_KEY` 及对应地址/模型名；没有 Embedding 时生成仍可进行，来源为空且进度明确提示。令牌和密钥填写到本地 `.env`，不要写进源码或评测报告。

Dashboard 上方填写管理员令牌；在“Go 示例生成与验证”选择场景、输入需求并执行。该入口独立于普通对话入口，但使用同一个 LangGraph（状态图编排运行时）；普通聊天不会自动执行其中的代码。

真实 Docker 构建会预热 Go 标准库缓存。引擎或镜像缺失时返回 `unavailable`，不在宿主执行用户代码。

---

## 接口与状态

| 接口 | 用途 |
| --- | --- |
| POST /api/v1/go/tasks | 等待最终 JSON 报告 |
| POST /api/v1/go/tasks/stream | SSE（服务端持续推送事件）进度与最终报告 |
| GET /api/v1/go/tasks/{run_id} | 读取当前账户的已有报告 |

请求体：

```jsonc
{
  // 固定三个场景之一，决定接口和服务端行为测试。
  "scenario": "context_cancel",
  "requirement": "等待 context 取消，返回取消或超时错误，取消前不能提前返回。",
  // 可选：同一账户和会话的并行请求返回 409。
  "session_id": "go-example"
}
```

独立管理调用携带 `Authorization: Bearer <AIROBOT_ADMIN_TOKEN>`。经过已有 Go 网关时携带受信任的 `X-Internal-Token` 与 `X-Account-Id`，网关必须自己验证登录态；网页不得持有共享网关令牌。报告按认证主体隔离，其他账户读取返回 404。当前仓库只增加 Python 接口，外部 Go 网关还需配置对应转发路径。

HTTP 200 表示请求有报告；业务成功由报告的 `status` 判断。可能的终态为 `passed`、`failed`、`timeout`、`unavailable`、`cancelled`、`generation_error`、`budget_exceeded`；运行中的报告为 `running`。环境不可用与沙箱级超时直接停止；模型代码挂起（go test 内部超时）按检查失败处理，可触发修复，检查失败最多两轮。

SSE 事件：`go_start` 携带 run_id；`go_stage` 展示检索、生成、验证和修复；`go_call` 记录预算；`go_usage` 记录服务商返回的 token 用量；`go_attempt` 携带每轮完整报告；`go_done` 携带最终结果。断开流会取消任务并清理容器；界面取消后可用 run_id 查询保存的最终状态。

### 可选多 Agent 流程的报告与事件

`AIROBOT_GO_MULTI_AGENT_ENABLED=true` 选择 `multi-v1`；默认关闭，继续使用 `single-v1`。启用前须按 `.env.example` 配置两个角色实际模型窗口；角色模型未分别指定时继承全局模型。两个接口共同消费 `GoTaskService.stream()` 和同一 LangGraph 路径，JSON 不另建修复循环。

多 Agent 报告增加 `task_spec`（原需求、需求 ID 与验收条件）、`artifacts`（每轮完整文件、轮次及服务端 hash）、`reviews`、`agent_calls`、`stop_reason`、`final_summary`。`attempts` 保留每轮机器验证与完整日志。hash 覆盖服务端注入后的可信测试，验证和审查必须绑定同一版本；服务器同时检查机器通过、当前版本审查通过、必要需求覆盖完整和无阻断问题，才返回 `passed`。

多 Agent 保留 `go_start/go_stage/go_call/go_usage/go_attempt/go_done`，并增加 `go_progress` 携带已持久化的完整阶段快照；阶段附加角色与轮次，客户端可忽略新增字段。`go_usage` 只发送完整的已知服务商用量，未知用量在报告 `context_stats.unknown_usage_calls` 中体现：`usage_complete=false`、总 `token_usage=null`，已知部分保留在 `known_token_usage`，不能按零费用解释。

所有 Go SSE 事件携带服务端任务 `run_id`；报告新增兼容默认 `budget`，包含服务器账本 `limits/used`、总时间与快照剩余秒数。界面展示请求预占与实际角色调用，既不自行增加额度，也不以定时器猜测剩余时间；历史报告缺少额度时显示“报告未提供上限”。

控制台根据实际阶段事件显示分解需求、委派、生成、验证、审查及修复，展示必要需求检查、阻断问题与非阻断建议、各轮 hash 和文件差异。中间 passed 快照不能变成绿色成功，只有匹配当前 run_id 的 `go_done.result.status=passed` 或服务器 GET 报告 passed 可显示成功。断流、取消请求、服务器确认 cancelled、timeout 和未知事件/终态分别展示；新请求开始后，旧请求的流事件、查询响应及 finally 都不能改写新任务。

代码、日志、需求、模型说明与审查文本均使用文本节点渲染，不执行其中 HTML。查询历史报告仅展示已保存结果，不虚构一次新执行或实时阶段；旧 single-v1 报告仍可读取源码与实际日志。

接收 `go_start` 后即可查询当前账户的报告。取消、断连或超时会保存已产生的计划、源码、验证、审查及已发生调用，等待活动调用与容器有界清理、最终报告写入后释放会话；是否确认删除容器以 `container_removed` 为准。流正常结束也必须检查 `go_done.result.status`，缺少 `go_done` 时通过 run_id 查询，不能把 HTTP 200、连接关闭或 `go_stage` 当成业务成功。

旧数据库 JSON 无需迁移，新字段及旧验证报告的版本字段读取时提供默认值；旧报告保留 `single-v1`，不会因缺少多 Agent 字段被重新解释为新流程通过。保存新报告时再次执行服务端成功契约，禁止无证据的 `multi-v1/passed` 入库，报告键和账户归属均校验。

报告保存在 `data/go_tasks.sqlite3`，包含代码、日志、来源和错误，不包含模型密钥。首次输出后冻结服务端行为测试（模型不能提交同名文件），模型自身测试可随修复更新，行为判定以服务端测试为准。服务进程崩溃前保存的任务可能停留为 `running`，本版不支持断点恢复或后台重启续跑。

---

## 验证范围与预算

服务端追加 `server_acceptance_test.go`，覆盖已取消、deadline、等待期间不能提前返回、空任务、非法 workers、输出顺序、输入不变、channel 关闭与 nil channel。模型生成最多 7 个文件，建议不超过 56KiB，为验收文件预留空间；最终总量限制为 8 个文件、64KiB。

可信检查程序使用 AST（源码语法树）核验标准库导入、固定包名和测试入口，拒绝 unsafe、syscall、os/exec、plugin、编译指令、TestMain。固定命令依次执行策略检查、`go build .`、`go vet .`、`go test -json -count=1 -timeout=8s .`；零测试、跳过测试及无法完整确认的截断输出均不予通过。

| 限制 | 当前值 |
| --- | --- |
| 原单流程首次生成 + 修复 | 最多 3 次模型调用、3 次验证、1 次检索 |
| 可选多 Agent 流程 | 正常模型调用最多 7 次 + 全任务共享重试 1 次，总计最多 8 次；修复最多 2 轮、验证 3 次、检索 1 次 |
| 整个任务 | 360 秒，包含等待并发槽位；单次模型生成调用上限 120 秒 |
| 同时执行 | 每个 Python 进程最多 2 个任务 |
| 单次验证 | 90 秒，结束后等待容器清理 |
| Docker 权限 | UID 65532、只读根目录、无网络、删除全部 capabilities、禁止新增权限 |
| 资源 | 1 CPU、512MiB 内存且无额外 swap、128 进程、256 文件描述符 |
| 临时目录 | /tmp 384MiB，/work 16MiB；无宿主挂载、无宿主环境密钥、无容器内 Docker socket |
| 日志 | 每阶段 16KiB；外层总报告 80KB，超限停止 |

行为测试不能证明全部并发正确性、无竞争或任意输入下的协程数量。本版不进行 Go race 检查，也不接受第三方依赖、多包项目、真实仓库执行或自改源码的进化过程。

面向公网部署时，将执行器放到独立受控的 Docker 主机/worker，并增加全局队列和账户配额。当前 API 进程有调用宿主 Docker 的权限，适用于本地或可信部署；不要为现有公开 API 容器直接挂载宿主 Docker socket。本版没有跨进程并发协调、任务恢复、保存期限或历史清理功能。

---

## 测试与可复现演示

```powershell
# 真实 Docker 验收：设为 1 后不能跳过容器用例。
$env:AIROBOT_TEST_DOCKER = '1'
.venv\Scripts\python.exe -m pytest tests -q

# 无密钥演示：9 个固定模型输出，经真实 Go 编译器检查和修复。
.venv\Scripts\python.exe eval/run_go_eval.py --fixtures

# 本交付不执行真实模型评测：必须先明确累计费用上限并通过
# eval/run_multi_agent_eval.py 的新冻结与费用预检，详见 multi-agent.md。
```

固定评测集 `eval/go_cases.json` 的三个场景各包含正常、行为错误和编译错误输入。边界条件通过人工服务端测试验收；独立异常测试覆盖无限循环、panic、进程异常退出、依赖拒绝、总超时和取消。`--fixtures` 的修复实现由人工预设，不会请求模型，也不会据此评估模型智能。

已有实际报告：[`go-validation-fixture-report.json`](go-validation-fixture-report.json)。其中 baseline 是同次运行的首次验证结果，with_repair 是修复后的结果；保存全部实际代码与 build/vet/test 日志。固定输出没有 token 或模型费用；真实模式只记录服务商实际返回的 token，不能推算未报告的费用。首次验证耗时与完整修复耗时范围不同，报告对此明确标记。

可选浏览器验收依赖 Node.js 和 Playwright。安装 Playwright 及浏览器后，在项目根目录执行 `node scripts/test_go_dashboard.cjs`；Windows 可设置 `PLAYWRIGHT_CHANNEL=msedge` 使用已有 Edge。验收使用上述真实 Go 报告替换浏览器 API 响应，检查失败/修复展示、日志文本隔离、报告读取及提前断流处理，不代表调用了真实模型。截图保存在 `eval/reports/go/dashboard.png`。

GitHub Actions 增加独立 Go 验证任务：Linux runner 构建固定镜像、运行实际容器用例、执行固定输出对比并上传报告。本次远程 CI 未运行；配置已包含全套 Docker 与关闭开关演练，真实模型不会因配置密钥自动执行。真实评测另需明确累计费用上限和新冻结，见 [交付说明](multi-agent.md)。
