# S6 最终代码与截图复查

版本：HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，完整工作区源码清单 SHA256 `4b1162f00e22d138b525d0abfb546c6f4e639f4ae7e308505cb4fcf39365a429`，tracked diff SHA256 `2be76607869053633d5a7ec7b8383b42d64137bf6724405001ee868836b93f1a`。

本次实现代理静态自查与实际截图复查：S6 范围未发现剩余阻断项；不声称第三方独立审查或真实模型能力评测。最终 pytest、Chrome 新旧浏览器验收均绑定相同源码，详见 commands.json。

- 服务端给每个 Go SSE 事件补当前 run_id；角色预算来自 SharedBudget 的副本，不是模型文本或前端常量，原 gate/额度预占规则未改变。
- 只有当前请求上下文中匹配 run_id 的 go_done.result.status=passed，或匹配查询键的服务器 GET passed，才将任务状态设为 passed。中间快照、stage finish、approve、HTTP 200 与流结束都不能使任务变绿。
- 新多 Agent 事件缺 run_id 时显示未知；旧 single-v1 无 ID 事件只接受在本次已绑定 go_start 的连接内。旧流 consume/catch/finally 与旧 GET 响应都检查当前请求上下文，不能覆盖新任务或释放其按钮状态。
- 断流、未知状态、未知/非法事件、非终态 go_done、取消请求、服务器确认 cancelled、timeout 分开显示。旧单流程只标记单流程生成/修复；多 Agent 委派和审查由实际事件展示。
- 服务端修复事件和修复调用完成事件标记下一轮；源码、验证、审查保持产物自身当前轮次与 hash，不重新标记旧报告。
- Go 代码、日志、计划、摘要、问题与模型名均通过 textContent 创建；固定 severity 决定 CSS 类，未将模型文本传给 innerHTML、事件属性或 URL。浏览器 XSS 检查涵盖上述全部文本路径，恶意标签可读但无可执行 DOM。
- 差异按完整文件公共前后段展示增加/删除的行，未截断源码或日志；pre 采用换行、滚动。浏览器实际展开了差异，检查非阻断建议与阻断问题分区。
- 新 budget 默认空，旧报告不猜预算上限；实际预占、调用次数、未知 Token 与未知费用分别显示。新增 remaining_seconds 属时间快照，JSON/SSE 比较仅排除此时间差，并另断言其边界；其他预算字段逐项比较不放宽。

已查看最终 browser-run-02/backend-repair-live.png（实际后端+Docker：阶段、轮次、diff、失败日志与审查）、mock-drop.png（中间 passed 后仍红色断流）、mock-mobile-viewport.png（390px 宽、恶意文本按字面渲染且任务区无横向溢出）。图片为实际 Chrome 截图，未合成或编辑。

浏览器 23 项：18 项替换响应/ReadableStream 的状态和安全检查；5 项真实后端检查。真实后端的模型均为固定替身，通过/修复/失败使用真实 Docker 共 6 次验证；取消发生在模型生成阶段，旧报告 GET 不产生新验证。真实模型、Embedding、对照评测未运行。
