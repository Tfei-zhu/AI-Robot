这组生命周期图按源码区分入口门禁、业务执行和响应发送，并以 **SSE 响应头是否已经产生**划分错误处理边界。

先修正上一张架构图的两处表述：

- 会话占用控制只适用于聊天、Go 任务的四个 POST 接口；Go 的 `Semaphore(2)`（最多同时执行两个任务）属于 `GoTaskService`，其他接口不共享。
- 补图中 `GoTaskService` 的“保存与读取报告”应改为“保存报告”；GET 报告接口直接读取 `GoTaskStore`。

全程只读源码，未读取 `.env`、未修改代码。以下实线表示处理顺序，虚线表示事件或取消信号，粗线表示数据写入。

---

**入口图：先鉴权、读取受限请求体、限流，再开始请求日志计时。**

<!-- readme-diagram:02-request-lifecycle-01 -->
![请求进入服务](../png/02-request-lifecycle-01.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    request["服务收到 HTTP 请求<br/>框架外层保留未捕获异常兜底"]
    api_path{"路径是否以 /api/ 开头？"}
    api_guard{"SecurityMiddleware<br/>身份与权限校验"}
    auth_error["直接返回 JSON<br/>401：凭据无效<br/>503：两个入站令牌均未配置<br/>403：网关身份访问管理接口"]
    principal["设置 principal<br/>admin 或 account/账号"]

    subgraph body_boundary["SecurityMiddleware：仅受保护接口的 POST / PUT / PATCH"]
        body_method{"是否需要读取请求体？"}
        body_read["检查 Content-Length<br/>按上限读取完整请求体，随后回放"]
        body_result{"读取结果"}
        body_error["直接返回 JSON<br/>400：长度头无效<br/>413：请求体超限"]
        body_disconnect["收到 http.disconnect<br/>直接结束，不进入业务"]
    end

    subgraph middleware_boundary["限流与请求日志"]
        rate_scope{"限流开启且路径以 /api/v1 开头<br/>并且不是 stats / traces？"}
        rate_allow{"limiter.allow(principal)<br/>是否放行？"}
        rate_reject["记录限流 warning<br/>写入 traces：status=429<br/>直接返回 HTTP 429"]
        log_begin["log_requests 开始计时<br/>await call_next(request)"]
    end

    subgraph routing_boundary["框架路由、参数校验与业务入口"]
        route_match{"匹配路径与请求方法"}
        request_validate{"解析请求体、查询参数<br/>执行 Pydantic 参数校验"}
        handled_error["框架生成普通错误响应<br/>404 / 405；解析错误 400 / 422<br/>参数校验失败 422"]
        route_scope{"是否为聊天或 Go 任务<br/>四个 POST 接口？"}
        session_key["session_identity<br/>按身份与 session_id 构造内部会话键"]
        session_busy{"claim_session<br/>会话是否已占用？"}
        conflict["HTTPException 409<br/>本次不占用会话"]
        session_claimed["占用会话，进入对应路由"]
        transport{"响应方式"}
        json_entry["进入 JSON 分图"]
        sse_entry["进入 SSE 分图"]
        other_entry["其他接口直接执行<br/>上传、GET 报告、观测、公开接口等<br/>进入 JSON 分图，不占用会话"]
    end

    log_headers["log_requests 取得下游响应头<br/>写入 info 请求日志<br/>添加 X-Process-Time-Ms"]
    send_error["发送普通错误响应"]

    request --> api_path
    api_path -->|"是"| api_guard
    api_path -->|"否：跳过身份校验"| rate_scope
    api_guard -->|"失败"| auth_error
    api_guard -->|"通过"| principal
    principal --> body_method
    body_method -->|"是"| body_read
    body_method -->|"否"| rate_scope
    body_read --> body_result
    body_result -->|"无效或超限"| body_error
    body_result -->|"客户端断开"| body_disconnect
    body_result -->|"完整读取"| rate_scope

    %% 限流在日志中间件外层；提前拒绝不会进入 log_requests。
    rate_scope -->|"适用"| rate_allow
    rate_scope -->|"关闭或豁免"| log_begin
    rate_allow -->|"否"| rate_reject
    rate_allow -->|"是"| log_begin

    log_begin --> route_match
    route_match -->|"无匹配路径或方法"| handled_error
    route_match -->|"匹配成功"| request_validate
    request_validate -->|"失败"| handled_error
    request_validate -->|"通过"| route_scope
    route_scope -->|"否"| other_entry
    other_entry --> json_entry
    route_scope -->|"是"| session_key
    session_key --> session_busy
    session_busy -->|"已占用"| conflict
    session_busy -->|"未占用"| session_claimed
    conflict --> handled_error
    session_claimed --> transport
    transport -->|"普通 JSON"| json_entry
    transport -->|"SSE"| sse_entry

    %% 参数校验发生在 claim_session 之前；409、422 通常没有业务运行记录。
    handled_error --> log_headers
    log_headers --> send_error
```

</details>

这里的限流按 `principal` 执行：管理员共用 `admin` 额度，可信网关按账号区分，**不是按客户端 IP**。身份拒绝、请求体拒绝、限流拒绝均绕过 `log_requests`，因此没有它生成的 info 日志和耗时响应头；限流分支另有 warning 和轨迹记录。

---

**JSON 图：业务完成或抛错后，才构建普通响应。**

<!-- readme-diagram:02-request-lifecycle-02 -->
![普通 JSON 返回](../png/02-request-lifecycle-02.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    json_entry["进入对应 JSON 路由"]
    json_route{"业务接口"}

    subgraph business_execution["接口各自的执行与记录"]
        chat_service["聊天服务 chat<br/>首轮缓存或普通聊天单智能体<br/>成功路径按分支提交记忆、缓存与运行记录"]
        go_service["GoTaskService.run<br/>内部消费同一个任务事件流<br/>报告保存与并发控制见 Go 分图"]
        other_service["其他业务路由<br/>上传直接调用知识库 kb<br/>GET 报告直接读取 GoTaskStore<br/>观测接口读取进程内状态"]
        chat_error_record["聊天内层执行异常<br/>记录 trace status=500<br/>记录 Agent 异常日志，然后继续抛出"]
    end

    json_release["聊天 / Go POST 路由 finally<br/>release_session"]
    json_release_error["聊天 / Go POST 异常退出<br/>finally release_session"]
    json_serialize["构造响应<br/>有 response_model 时校验输出<br/>序列化为 JSON 字节"]
    json_exception{"异常类型"}

    handled_json["HTTPException 或 ContextBudgetExceeded<br/>由对应处理器生成 JSON<br/>上下文预算错误为 HTTP 422"]
    unhandled_json["未捕获 Exception<br/>外层调用 unhandled_exception_handler<br/>记录异常并返回 HTTP 500<br/>绕过正常请求 info 日志和耗时头"]

    log_headers["log_requests 取得响应头<br/>记录状态与耗时，添加响应头"]
    json_send["发送 JSON 响应"]

    json_disconnect["客户端在执行期间断开<br/>JSON 路由没有主动断开监测<br/>不保证自动取消业务任务"]
    json_cancel["任务实际收到取消<br/>聊天：在捕获范围内记录 499<br/>Go：清理并保存 cancelled 报告"]
    json_cancel_release["聊天 / Go POST finally 释放会话<br/>继续传播取消，不保证返回响应"]

    json_entry --> json_route
    json_route -->|"聊天"| chat_service
    json_route -->|"Go 任务"| go_service
    json_route -->|"其他接口"| other_service

    chat_service -->|"正常返回"| json_release
    go_service -->|"正常返回报告，包含业务失败报告"| json_release
    other_service -->|"正常返回"| json_serialize
    json_release --> json_serialize
    json_serialize -->|"成功"| log_headers
    log_headers --> json_send

    %% 聊天的异常记录只覆盖内层 try；缓存分支等异常不能一概保证有 trace。
    chat_service -->|"内层图执行及提交异常"| chat_error_record
    chat_error_record --> json_release_error
    chat_service -->|"其他未捕获异常"| json_release_error
    go_service -->|"仍向外抛出的异常"| json_release_error
    json_release_error --> json_exception
    other_service -->|"抛出异常"| json_exception
    json_exception -->|"已注册的处理类型"| handled_json
    json_exception -->|"其他 Exception"| unhandled_json
    handled_json --> log_headers
    unhandled_json --> json_send
    json_serialize -->|"输出校验或序列化异常"| unhandled_json

    %% 499 是内部轨迹状态，不是这里发送给客户端的 HTTP 响应。
    json_disconnect -.->|"仅在任务实际被取消时"| json_cancel
    chat_service -.->|"收到取消"| json_cancel
    go_service -.->|"收到取消"| json_cancel
    json_cancel --> json_cancel_release
```

</details>

上传接口没有会话占用或统一业务轨迹：文件校验失败返回相应错误；入库异常被转换成 `HTTPException(500)`，临时文件在 `finally` 删除。它属于**已处理的 HTTP 错误**，仍会经过正常请求日志。

---

**SSE 图：响应头先产生，再消费生成器；业务失败通常无法改变 HTTP 200。**

<!-- readme-diagram:02-request-lifecycle-03 -->
![SSE 建立与结束](../png/02-request-lifecycle-03.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    sse_entry["参数校验通过且已占用会话"]
    sse_response["路由返回 SessionStreamResponse<br/>构造响应时尚未消费业务生成器"]
    sse_start["StreamingResponse 先产生响应头<br/>HTTP 200 / text/event-stream"]

    subgraph header_path["响应头返回路径"]
        log_headers["log_requests 取得响应头<br/>记录 HTTP 200 与当前耗时<br/>添加 X-Process-Time-Ms"]
        client_headers["向客户端转发响应头"]
    end

    subgraph event_path["响应体生成路径"]
        sse_route{"消费哪个业务生成器？"}
        chat_service["聊天服务 stream_chat<br/>首个 stage 事件在异常保护 try 之外<br/>之后执行缓存或普通聊天状态图"]
        chat_success["成功路径提交记忆与运行记录<br/>输出后续事件及 done"]
        chat_error["内层图执行 try 捕获 Exception<br/>记录 trace status=500 与异常日志<br/>输出 error，随后输出 done"]
        go_service["GoTaskService.stream<br/>输出任务进度<br/>终态报告保存后输出 go_done"]
        escaped_error["未被业务捕获的异常<br/>例如部分准备、存储或响应发送异常<br/>不能保证存在 error / done 事件"]
    end

    disconnect["客户端断开 / 发送失败 / 上层取消<br/>框架停止流式消费或传播异常"]
    stream_finally["SessionStreamResponse finally<br/>finish_cleanup 保护关闭外层生成器"]

    subgraph close_boundary["按接口区分生成器关闭"]
        close_route{"所属接口"}
        close_go["Go SSE 路由显式使用 aclosing<br/>关闭 GoTaskService.stream<br/>未完成任务进入取消清理与报告保存"]
        close_chat["聊天 SSE 路由没有显式 aclosing 内层流<br/>内层收到取消或关闭时执行自身清理<br/>不能保证与 Go 相同的同步闭合时序"]
    end

    release_session["finally release_session<br/>即使关闭过程抛错，也尝试释放会话"]
    stream_end["流结束或异常继续传播<br/>不能向已断开的客户端补发终止事件<br/>响应已开始后不能再改发 JSON 500"]

    sse_entry --> sse_response
    sse_response --> sse_start

    %% 响应头转发与生成器推进可能交错；日志并不等待整段 SSE 执行完成。
    sse_start --> log_headers
    log_headers --> client_headers
    sse_start --> sse_route
    sse_route -->|"聊天 SSE"| chat_service
    sse_route -->|"Go SSE"| go_service

    chat_service -->|"正常完成"| chat_success
    chat_service -->|"仅内层 try 捕获的执行异常"| chat_error
    chat_service -->|"未捕获异常"| escaped_error
    go_service -->|"正常耗尽事件流，包括失败报告"| stream_finally
    go_service -->|"仍向外抛出的异常"| escaped_error
    chat_success --> stream_finally
    chat_error --> stream_finally
    escaped_error --> stream_finally

    client_headers -.->|"连接持续期间发生断开"| disconnect
    disconnect -.-> stream_finally

    stream_finally --> close_route
    close_route -->|"Go"| close_go
    close_route -->|"聊天"| close_chat
    close_go --> release_session
    close_chat --> release_session
    release_session --> stream_end
```

</details>

在 SSE 响应建立前，鉴权、限流、参数校验和会话冲突仍返回普通 JSON 错误。建立后，聊天内层异常通过事件表达；Go 任务通过报告终态表达。逃逸到框架的异常只能记录、传播并终止流，不能统一转换为第二个 JSON 响应。

聊天 `stream_chat` 在捕获范围内收到 `CancelledError` 或 `GeneratorExit` 时记录内部 `499`，随后重新抛出；**首个 `stage` 事件在该保护范围之外，不能保证所有早期断开都有 499 记录。**

---

**Go 分图：JSON 与 SSE 共用同一个任务执行流，但只有 SSE 向客户端逐条推送事件。**

<!-- readme-diagram:02-request-lifecycle-04 -->
![Go 任务执行与收尾](../png/02-request-lifecycle-04.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    go_service["GoTaskService.stream<br/>JSON 的 run() 也消费此流"]
    go_init["创建 run_id、状态与任务截止时间"]
    go_initial_save["保存初始 running 报告"]
    go_start["产生 go_start<br/>JSON 内部消费；SSE 对外推送"]
    go_wait["进入 asyncio.timeout<br/>等待 Semaphore(2)<br/>排队等待也处于此超时范围"]
    go_execute["取得执行槽后运行 LangGraph<br/>默认单工作流；显式开启才用多智能体"]
    go_updates["按更新保存报告快照<br/>产生进度、调用量等事件"]
    go_exit["离开执行区<br/>如果已取得执行槽：<br/>等待工作流及沙箱清理，再释放执行槽"]
    go_outcome{"退出原因"}

    subgraph normal_terminal["正常完成、超时或捕获到执行异常"]
        go_result["形成最终报告<br/>成功或业务失败状态<br/>TimeoutError 转 timeout<br/>捕获的其他异常转 failed"]
        go_final_save["保存最终报告"]
        go_trace["写入近期 traces<br/>passed 对应内部 status=200<br/>其他终态对应内部 status=422"]
        go_done["产生 go_done<br/>JSON：run() 返回报告<br/>SSE：继续推送事件"]
    end

    subgraph cancelled_terminal["收到 CancelledError / GeneratorExit"]
        go_cancel_cleanup["finish_cleanup 保护<br/>停止并等待工作流"]
        go_cancel_save["保存 cancelled 报告<br/>清除本次用量记录"]
        go_cancel_raise["重新抛出取消 / 关闭信号<br/>不走正常 trace 和 go_done 收尾"]
    end

    go_service --> go_init
    go_init --> go_initial_save
    go_initial_save --> go_start
    go_start --> go_wait
    go_wait --> go_execute
    go_execute --> go_updates
    go_updates -->|"继续执行"| go_execute
    go_updates -->|"执行结束"| go_exit

    %% 初始保存、go_start、排队或执行阶段都可能被取消。
    go_initial_save -.->|"取消或异常"| go_exit
    go_start -.->|"取消或关闭"| go_exit
    go_wait -.->|"取消、超时或异常"| go_exit
    go_execute -.->|"取消、超时或异常"| go_exit

    go_exit --> go_outcome
    go_outcome -->|"完成 / 超时 / 捕获的异常"| go_result
    go_result --> go_final_save
    go_final_save --> go_trace
    go_trace --> go_done

    go_outcome -->|"取消 / 生成器关闭"| go_cancel_cleanup
    go_cancel_cleanup --> go_cancel_save
    go_cancel_save --> go_cancel_raise

    %% 最终报告构造、最终保存等仍可能抛错；不会保证总能产生 go_done。
```

</details>

Go 的执行槽在工作流清理后释放；取消报告保存完成后，路由才继续释放会话占用。两者不是同一把锁。`run_blocking` 用线程执行阻塞操作并处理取消等待，`finish_cleanup` 进一步保护清理过程免受重复取消中断。

---

**HTTP 状态、请求日志和运行记录是三套不同信息，不能互相替代。**

| 情况 | HTTP / 事件表现 | 日志与运行记录 |
|---|---|---|
| 未授权、权限不足、请求体拒绝 | 普通 JSON 错误 | 不进入 `log_requests`；没有统一业务 trace |
| 限流 | HTTP 429 | 单独 warning、trace 429；没有正常请求 info 日志 |
| 参数错误、会话冲突 | HTTP 422 / 409 | 有请求 info 日志；通常没有业务 trace |
| 聊天内层执行异常 | JSON 通常为 500；上下文预算错误为 422 | 内层异常记录 trace 500，可能与 HTTP 状态不同 |
| 聊天 SSE 内层异常 | HTTP 200，`error` 后接 `done` | 请求日志为 200，业务 trace 为 500 |
| Go 任务未通过或超时 | 通常仍为 HTTP 200；报告包含失败终态 | 正常收尾时业务 trace 为 422 |
| Go 任务取消 | 不保证响应或终止事件送达 | 保存 `cancelled` 报告；取消分支不追加正常终态 trace |
| 上传、GET 报告、观测接口 | 各路由自己的响应 | 没有聊天/Go POST 的会话占用与统一执行记录 |

对应源码位置：

| 内容 | 源码 |
|---|---|
| 身份、权限、请求体限制 | [security.py:20](../../../app/services/security.py#L20)、[security.py:48](../../../app/services/security.py#L48) |
| 限流与请求日志 | [main.py:73](../../../app/main.py#L73)、[main.py:84](../../../app/main.py#L84) |
| 异常处理器 | [main.py:99](../../../app/main.py#L99)、[main.py:105](../../../app/main.py#L105) |
| 四个 POST 路由与报告读取 | [main.py:193](../../../app/main.py#L193)、[main.py:208](../../../app/main.py#L208)、[main.py:223](../../../app/main.py#L223)、[main.py:234](../../../app/main.py#L234)、[main.py:247](../../../app/main.py#L247) |
| 会话占用、流结束清理 | [security.py:92](../../../app/services/security.py#L92)、[security.py:107](../../../app/services/security.py#L107) |
| 聊天执行、错误与轨迹 | [chat.py:137](../../../app/services/chat.py#L137)、[chat.py:219](../../../app/services/chat.py#L219) |
| Go 并发、报告、取消处理 | [service.py:43](../../../app/go_validation/service.py#L43)、[service.py:76](../../../app/go_validation/service.py#L76)、[service.py:127](../../../app/go_validation/service.py#L127) |
| 线程等待与取消保护 | [concurrency.py:6](../../../app/services/concurrency.py#L6)、[concurrency.py:29](../../../app/services/concurrency.py#L29) |
| 中间件顺序、响应头和流式机制的本地依赖依据 | applications.py:1054（本地参考：`.venv/Lib/site-packages/fastapi/applications.py:1054`）、applications.py:104（本地参考：`.venv/Lib/site-packages/starlette/applications.py:104`）、base.py:112（本地参考：`.venv/Lib/site-packages/starlette/middleware/base.py:112`）、responses.py:250（本地参考：`.venv/Lib/site-packages/starlette/responses.py:250`） |
