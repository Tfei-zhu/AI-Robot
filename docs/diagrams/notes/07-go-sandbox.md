Go 沙箱验证把**已注入验收测试的代码包**送入固定 Docker 容器，依次执行策略检查、编译、静态检查和测试，收集报告后再确认资源清理。

已核对 Python 适配器、验收测试、镜像配置和容器内执行器。未修改代码、未读取 `.env`。

---

**主图：验收测试在编排层注入，临时源码文件只在容器内创建。**

<!-- readme-diagram:07-go-sandbox-01 -->
![Go 代码进入隔离验证](../png/07-go-sandbox-01.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    subgraph orchestration_prepare["编排层准备：发生在 DockerGoRunner 之外"]
        generated_bundle["模型产出的代码与测试"]
        bundle_check["CodeBundle 检查<br/>文件名、重复名称、实现与测试文件<br/>文件数量及源码总大小"]
        acceptance_tests["按 scenario 注入 server_acceptance_test.go<br/>模型提交同名文件则拒绝<br/>旧流程修复保留首轮固定测试<br/>多智能体每轮注入并冻结产物"]
        final_bundle["重新校验合并后的代码包<br/>正常任务包含模型测试与服务端验收测试"]
        prepare_error["向上层抛出契约或生成错误<br/>尚未创建容器"]
    end

    subgraph python_runner["宿主侧：DockerGoRunner.validate"]
        runner_check["清空 last_report<br/>再次校验 CodeBundle<br/>计算完整 submitted_hash"]
        runner_init["生成唯一容器名<br/>初始化 unavailable 报告<br/>进入执行 try / finally"]
        docker_engine["启动固定 docker run 命令<br/>不接受模型提供的命令或容器参数<br/>不挂载宿主源码目录或 Docker socket"]
        stdin_send["通过 stdin 发送 UTF-8 JSON<br/>发送完关闭 stdin"]
        container_execution["容器内执行<br/>详见下一张图"]
        pipe_collect["并发读取 Docker 客户端 stdout / stderr<br/>各自默认最多 80000 字节<br/>读至结束后等待客户端退出"]
        docker_exit{"Docker 客户端退出码为 0？"}
        unavailable_report["unavailable<br/>记录 sandbox 错误<br/>包括 Docker / 镜像 / 入口进程故障"]
        report_check["解析 stdout 中的 ValidationReport<br/>核对 Go 版本与已有 hash<br/>自称 passed 时核对阶段顺序及退出码"]
        checked_report["取得本次验证报告<br/>passed / failed / timeout / unavailable"]
        cleanup_entry["统一进入 finally 清理<br/>详见资源清理图"]
    end

    generated_bundle --> bundle_check
    bundle_check -->|"合法"| acceptance_tests
    bundle_check -->|"不合法"| prepare_error
    acceptance_tests -->|"成功"| final_bundle
    acceptance_tests -->|"异常"| prepare_error
    final_bundle --> runner_check
    runner_check -->|"合法"| runner_init
    runner_check -->|"校验失败：未进入执行 try"| prepare_error
    runner_init --> docker_engine
    docker_engine --> stdin_send

    %% 容器执行与宿主读取管道并行推进，不是执行结束后才开始读日志。
    stdin_send --> container_execution
    stdin_send --> pipe_collect
    container_execution -->|"stdout 报告及 stderr"| pipe_collect
    pipe_collect --> docker_exit
    docker_exit -->|"非 0"| unavailable_report
    docker_exit -->|"为 0"| report_check
    report_check -->|"合法"| checked_report
    report_check -->|"JSON、契约、版本或 hash 校验失败"| unavailable_report
    checked_report --> cleanup_entry
    unavailable_report --> cleanup_entry

    %% 外层超时、取消和管道异常也进入同一个 finally，见资源清理图。
```

</details>

`DockerGoRunner` 和直接调用的 `validate_go_code` **不会自动注入验收测试**；正常 Go 任务在调用它们之前完成注入。宿主侧没有创建临时源码目录，源码通过标准输入传输。

固定验收测试覆盖：

| 场景 | 注入测试的主要行为 |
|---|---|
| `context_cancel` | 已取消、等待后取消、截止时间传播 |
| `worker_pool` | 结果及顺序、输入不变、非法 workers、取消、空任务 |
| `channel` | 求和及关闭、空 channel、nil channel 取消、已取消上下文 |

源码：[fixtures.py:66](../../../app/go_validation/fixtures.py#L66)、[contracts.py:44](../../../app/go_validation/contracts.py#L44)、[contracts.py:261](../../../app/go_validation/contracts.py#L261)、[runner.py:56](../../../app/go_validation/runner.py#L56)。

---

**容器内流程：检查顺序严格为 `policy → compile → vet → test`，失败即停止后续阶段。**

<!-- readme-diagram:07-go-sandbox-02 -->
![容器内的四阶段检查](../png/07-go-sandbox-02.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    subgraph container_prepare["镜像入口与代码包检查"]
        container_start["entrypoint.sh<br/>复制预热缓存到 /tmp/go-cache<br/>exec /opt/validator"]
        version_check{"实际 Go 版本为 1.26.2？"}
        version_failure["status=unavailable<br/>stage=sandbox"]
        json_decode["从 stdin 解码代码包 JSON<br/>限制读取范围为 262145 字节<br/>拒绝未知字段"]
        policy_check{"validate 策略检查通过？<br/>文件名、数量、大小和 Go 语法<br/>package example、受限标准库<br/>禁止指令与 TestMain<br/>存在实现与测试函数"}
        policy_failure["status=failed<br/>stage=policy，exit_code=1"]
        source_files["在容器 /work 写入源码与测试<br/>文件权限 0600"]
        source_write_check{"源码文件写入成功？"}
        source_write_failure["stage=sandbox，exit_code=1<br/>代码当前保留默认 status=failed"]
        module_file["写入固定 /work/go.mod<br/>module airobot.example<br/>go 1.26.2"]
        module_write_check{"go.mod 写入成功？"}
        module_write_failure["status=unavailable"]
        policy_success["追加 policy 成功阶段记录"]
    end

    subgraph command_checks["固定 Go 命令：每个命令由 35 秒上下文包装"]
        compile["compile<br/>go build ."]
        compile_result{"退出码为 0？"}
        vet["vet<br/>go vet ."]
        vet_result{"退出码为 0？"}
        test["test<br/>go test -json -count=1 -timeout=8s ."]
        test_result{"退出码为 0？"}
        test_events{"检查测试 JSON 事件<br/>至少一个 run<br/>pass 数等于 run 数<br/>没有 skip，且包级 pass"}
        stage_failure{"失败阶段退出码为 124？"}
        command_timeout["status=timeout<br/>命令阶段超时"]
        command_failed["status=failed<br/>编译、静态检查或测试失败"]
        event_failed["test 阶段改为 exit_code=1<br/>status=failed"]
        sandbox_passed["全部规定阶段成功<br/>status=passed"]
    end

    stage_logs["每个命令共享收集 stdout 与 stderr<br/>保留前 16384 字节并继续排空输出<br/>超出部分标记 truncated=true"]
    container_report["defer 编码 JSON 报告到 stdout<br/>包含状态、Go 版本、阶段日志与耗时<br/>正常失败报告通常仍以进程退出码 0 返回"]

    container_start --> version_check
    version_check -->|"否"| version_failure
    version_check -->|"是"| json_decode
    json_decode --> policy_check
    json_decode -->|"解码失败"| policy_failure
    policy_check -->|"否"| policy_failure
    policy_check -->|"是"| source_files
    source_files --> source_write_check
    source_write_check -->|"否"| source_write_failure
    source_write_check -->|"是"| module_file
    module_file --> module_write_check
    module_write_check -->|"否"| module_write_failure
    module_write_check -->|"是"| policy_success

    %% 策略校验先执行；policy 成功记录在源码和 go.mod 写入完成后追加。
    policy_success --> compile
    compile --> compile_result
    compile_result -->|"是"| vet
    compile_result -->|"否"| stage_failure
    vet --> vet_result
    vet_result -->|"是"| test
    vet_result -->|"否"| stage_failure
    test --> test_result
    test_result -->|"否"| stage_failure
    test_result -->|"是"| test_events
    test_events -->|"通过"| sandbox_passed
    test_events -->|"不通过"| event_failed
    stage_failure -->|"是"| command_timeout
    stage_failure -->|"否"| command_failed

    compile -.->|"执行期间收集"| stage_logs
    vet -.->|"执行期间收集"| stage_logs
    test -.->|"执行期间收集"| stage_logs
    stage_logs -.->|"写入各阶段报告"| container_report

    version_failure --> container_report
    policy_failure --> container_report
    source_write_failure --> container_report
    module_write_failure --> container_report
    command_timeout --> container_report
    command_failed --> container_report
    event_failed --> container_report
    sandbox_passed --> container_report
```

</details>

策略检查使用 AST（语法树）解析源码，实际包含：

- 2～8 个 Go 文件，名称不区分大小写去重，源码 UTF-8 总字节数最多 64 KiB。
- 所有文件属于 `package example`；至少有实现文件和 `Test` 开头的顶层测试函数。
- 导入路径必须属于镜像生成的标准库清单，并排除 `unsafe`、`syscall`、`os/exec`、`plugin`。
- 拒绝包含 `go:` 或以 `//line ` 开头的相应注释，拒绝 `TestMain`。

代码没有在 AST 阶段证明“每个测试都含有效断言”；固定验收测试和测试运行结果承担后续检查。

源码：[runner.go:68](../../../sandbox/go/runner.go#L68)、[runner.go:92](../../../sandbox/go/runner.go#L92)、[runner.go:162](../../../sandbox/go/runner.go#L162)、[runner.go:188](../../../sandbox/go/runner.go#L188)。

---

**资源清理图：进入执行 `try` 后，各种退出路径都会尝试清理，但清理结果必须单独确认。**

<!-- readme-diagram:07-go-sandbox-03 -->
![验证结束后的资源清理](../png/07-go-sandbox-03.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    execution_end{"执行阶段如何结束？"}
    normal_report["取得容器验证报告<br/>passed / failed / timeout / unavailable"]
    outer_timeout["Python wait_for 超时<br/>报告 timeout<br/>sandbox exit_code=124"]
    host_error["OSError / ValueError<br/>例如 Docker 缺失、日志超限或报告无效<br/>报告 unavailable"]
    cancelled["收到 CancelledError<br/>报告 cancelled<br/>sandbox exit_code=130<br/>保留取消传播"]
    unexpected["其他未捕获异常<br/>保留异常传播"]

    subgraph cleanup["DockerGoRunner finally"]
        remove_container["创建独立清理任务<br/>docker rm -f 唯一容器名<br/>默认等待上限 15 秒"]
        shield_cleanup["asyncio.shield 等待同一个清理任务<br/>再次收到取消仍继续等待"]
        remove_result["取得 removed 布尔结果<br/>命令超时或 OS 错误为 false<br/>清理命令进程未退出时也会被终止并等待"]
        stop_client["原 docker run 客户端仍存活时<br/>kill 并等待退出"]
        update_report["写入 container_removed<br/>绑定 submitted_hash、累计耗时<br/>记录 last_report"]
        pass_cleanup_check{"报告为 passed<br/>但 removed=false？"}
        downgrade["改为 unavailable<br/>追加无法确认容器清理的 sandbox 错误"]
        propagate_check{"存在待传播异常<br/>或清理期间收到取消？"}
    end

    report_return["返回 ValidationReport"]
    propagate_exit["清理后继续抛出异常或取消<br/>取消路径不普通返回报告<br/>上层可读取 last_report"]

    execution_end -->|"正常取得报告"| normal_report
    execution_end -->|"执行超时"| outer_timeout
    execution_end -->|"OS 或数据错误"| host_error
    execution_end -->|"任务被取消"| cancelled
    execution_end -->|"其他异常"| unexpected

    normal_report --> remove_container
    outer_timeout --> remove_container
    host_error --> remove_container
    cancelled --> remove_container
    unexpected --> remove_container
    remove_container --> shield_cleanup
    shield_cleanup --> remove_result
    remove_result --> stop_client
    stop_client --> update_report
    update_report --> pass_cleanup_check
    pass_cleanup_check -->|"是"| downgrade
    pass_cleanup_check -->|"否"| propagate_check
    downgrade --> propagate_check
    propagate_check -->|"否"| report_return
    propagate_check -->|"是"| propagate_exit

    %% 入口契约校验在执行 try 之前失败时，尚未创建容器，不经过此清理流程。
```

</details>

客户端断开需先由接口层转化为任务取消；`DockerGoRunner` 本身不监听 HTTP 连接。取消后它先完成清理、写入 `last_report`，再传播取消；多智能体适配层会据此绑定并保存取消验证记录。

`container_removed=false` 不表示已经安全清理完毕。只有原状态为 `passed` 时，代码会因此降级为 `unavailable`；其他失败状态保留原状态，同时携带清理标记。

源码：[runner.py:36](../../../app/go_validation/runner.py#L36)、[runner.py:101](../../../app/go_validation/runner.py#L101)、[go_workflow.py:414](../../../app/agents/go_workflow.py#L414)。

---

**实际隔离与资源限制：**

| 范围 | 当前配置 |
|---|---|
| 镜像与工具链 | 固定 `airobot-go-validator:1.26.2`；基础镜像固定摘要，`--pull=never`，运行时不自动拉镜像 |
| 网络 | `--network=none`；`GOPROXY=off`、`GOSUMDB=off`、`GOTOOLCHAIN=local` |
| 权限 | UID/GID `65532:65532`，删除全部 capabilities，`no-new-privileges` |
| 根文件系统 | `--read-only`；没有宿主源码目录或 Docker socket 挂载 |
| 临时存储 | `/tmp` 为 384 MiB tmpfs，显式允许执行；`/work` 为 16 MiB tmpfs；均带 `nosuid,nodev` |
| CPU 与内存 | `--cpus=1`；内存 512 MiB，`memory-swap=512m` |
| 进程与文件描述符 | `pids-limit=128`，`nofile=256:256` |
| Go 执行环境 | `CGO_ENABLED=0`、`GOMAXPROCS=2`、`GOFLAGS=-p=1`；工作目录固定 `/work` |
| 命令时间 | 每个 Go 命令使用 35 秒上下文；`go test` 内部另有 8 秒测试超时 |
| 外层时间 | Python 执行默认 90 秒；清理命令另有默认 15 秒，不应把 90 秒理解为含清理的总耗时 |
| 日志 | 每个 Go 阶段合并保留前 16384 字节；宿主分别限制 stdout、stderr 各 80000 字节 |

只读根文件系统不等于禁止所有文件读取：代码仍可读取容器内有权限访问的文件。网络和文件系统边界由容器配置落实，不应画成“禁止导入所有网络或文件操作包”。

镜像依据：[Dockerfile](../../../sandbox/go/Dockerfile)、[entrypoint.sh](../../../sandbox/go/entrypoint.sh)、[runner.py:23](../../../app/go_validation/runner.py#L23)。

---

**不同失败类型及“通过”的边界：**

| 情况 | 验证状态与后续 |
|---|---|
| 策略、编译、`vet` 或测试失败 | `failed`，停止后续阶段，保留已完成阶段的报告，然后清理 |
| `go test` 内部 8 秒超时 | 属于测试失败，状态为 `failed`，编排层仍可能修复代码 |
| 单个 Go 命令 35 秒超时 | 阶段退出码改为 124，验证状态为 `timeout` |
| Python 外层执行超时 | `timeout`，尝试强制删除容器并终止客户端 |
| Docker 不可用、镜像缺失、入口进程非零退出 | `unavailable`；不会退到宿主执行源码 |
| 宿主管道日志超过 80000 字节或报告无效 | `unavailable`，进入同一清理路径 |
| 容器内阶段日志被截断 | 标记 `truncated=true`，并非一律立刻失败；测试事件不完整会失败，多智能体成功门禁还会拒绝任何阶段截断 |
| 客户端取消所引发的任务取消 | 清理后传播取消；任务层保存 `cancelled`，不保证再发送终止事件 |

**沙箱通过只说明当前代码包的规定检查通过且容器清理已确认。** 正常 Go 任务还受编排层约束：

- 旧流程主要依据本轮验证报告决定是否通过。
- 多智能体流程还要求合法 `proceed` 评估、同一版本的验证与审查绑定、主智能体 `approve`、必要需求全部通过、没有 `blocking` 问题，并通过最终报告契约校验。

验证器既不是独立智能体，也不能单独决定整个多智能体任务最终成功。对应门禁见 [go_workflow.py:76](../../../app/agents/go_workflow.py#L76)、[go_workflow.py:89](../../../app/agents/go_workflow.py#L89)、[contracts.py:427](../../../app/go_validation/contracts.py#L427)。
