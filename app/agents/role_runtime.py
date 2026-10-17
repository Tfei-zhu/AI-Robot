"""角色 Agent 共享运行时：单次模型调用、超时、用量记录与提示词组装片段。

S2 只提供可独立调用的角色组件；发送前预算预占与统一截止时间编排属 S4。
每次调用的消息都由服务端结构化输入重建，角色实例即任务本地上下文，
实例之间不共享任何消息或任务状态。
"""
import asyncio
import json
import re
import uuid

from app.config import settings
from app.context import usage as context_usage
from app.go_validation.contracts import AgentCall

# context_usage 账本使用的阶段名，与现有单流程 go_generate 保持同风格。
_STAGE_NAMES = {"plan": "go_plan", "review": "go_review", "generate": "go_generate", "repair": "go_repair"}
# 检索资料是辅助输入：显式截断并标注；源码任何情况下不走该裁剪。
MAX_REFERENCE_CHARS = 16000
MAX_STAGE_LOG_CHARS = 8000


class AgentError(RuntimeError):
    """角色调用失败。kind: output=解析/契约校验失败, timeout=角色超时, call=模型请求失败。"""

    def __init__(self, message: str, *, kind: str, role: str, stage: str):
        super().__init__(f"[{role}.{stage}/{kind}] {message}")
        self.kind, self.role, self.stage = kind, role, stage


def text_of(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content)


def extract_json(text: str) -> dict:
    """从模型文本提取 JSON 对象；允许围栏包裹或前后夹带说明文字。"""
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
        candidate = m.group(1) if m else text
        start = candidate.find("{")
        if start < 0:
            raise ValueError("输出不是合法 JSON 对象")
        # raw_decode consumes the complete object, including its closing brace,
        # and ignores trailing prose without confusing braces inside strings.
        data, _ = json.JSONDecoder().raw_decode(candidate[start:])
    if not isinstance(data, dict):
        raise ValueError("输出必须是 JSON 对象")
    return data


def usage_of(response) -> dict | None:
    usage = getattr(response, "usage_metadata", None)
    keys = ("input_tokens", "output_tokens", "total_tokens")
    if not isinstance(usage, dict) or any(
            type(usage.get(k)) is not int or usage[k] < 0 for k in keys):
        return None
    return {k: usage[k] for k in keys}


def clip(text: str, limit: int, marker: str) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n" + marker


def render_files(files) -> str:
    # 输入侧统一使用 --- FILE --- 标记，与模型输出要求的 === FILE === 区分，
    # 降低修复时把展示源码（含服务端测试）原样抄回输出格式的概率。
    return "\n\n".join(f"--- FILE: {f.name} ---\n{f.content}" for f in files)


def render_validation(report, *, cap: int = MAX_STAGE_LOG_CHARS) -> str:
    lines = [f"机器验证状态: {report.status}；Go 版本: {report.go_version}；容器已清理: {report.container_removed}"]
    for s in report.stages:
        lines.append(f"--- 阶段 {s.stage}（exit={s.exit_code}，truncated={s.truncated}）---")
        lines.append(clip(s.output, cap, "[阶段日志超长，已截断]"))
    return "\n".join(lines)


def render_task(task) -> str:
    lines = [f"【场景】{task.scenario}",
             "【固定服务端契约（不可改写）】", task.server_contract,
             "【用户原始需求】", task.original_requirement,
             "【任务需求】"]
    lines += [f"- [{r.requirement_id}]（{'必要' if r.required else '可选'}）{r.text}" for r in task.requirements]
    if task.acceptance_criteria:
        lines.append("【验收条件】")
        lines += [f"- [{c.criterion_id}]（对应 {c.requirement_id}）{c.text}" for c in task.acceptance_criteria]
    if task.constraints:
        lines.append("【约束】")
        lines += [f"- {c}" for c in task.constraints]
    return "\n".join(lines)


class RoleRunner:
    """任务本地模型调用执行器：单次调用、角色超时、失败/取消/用量记录。"""

    def __init__(self, role: str, model, *, model_name: str, run_id: str | None, timeout: float):
        self.role, self.model, self.model_name = role, model, model_name
        self.run_id = run_id or uuid.uuid4().hex
        self.timeout = timeout
        self.config = None  # Workflow binds its task-local settings, including injected roles.
        self.calls: list[AgentCall] = []

    def _record(self, stage: str, status: str, response=None):
        self.calls.append(AgentCall(role=self.role, stage=stage, model=self.model_name,
                                    status=status,
                                    token_usage=usage_of(response) if response is not None else None))

    async def call(self, messages, *, stage: str) -> str:
        from app.agents.go_workflow import BudgetExceededError
        from app.context.token_counter import TokenCounter
        cfg = self.config or settings.go_multi_agent
        tools = getattr(self.model, "kwargs", {}).get("tools", ())
        counter = TokenCounter()
        estimate = counter.count(messages, tools)
        limit = getattr(cfg, self.role + "_input_tokens")
        window = getattr(cfg, self.role + "_window")
        if window:
            limit = min(limit, window - getattr(cfg, self.role + "_output_tokens") - cfg.safety_tokens)
        if estimate > limit:
            # This guard is independent of experimental context_mode. No request
            # was sent, so do not fabricate a failed model call or provider usage.
            raise BudgetExceededError(
                f"{self.role} 输入估计 {estimate} 超过额度 {limit}（计数已校准={counter.verified}）",
                kind="context")
        try:
            response = await asyncio.wait_for(
                context_usage.invoke(self.model, messages, run_id=self.run_id,
                                     stage=_STAGE_NAMES[stage], model_name=self.model_name, retry=False),
                self.timeout)
        except asyncio.CancelledError:
            self._record(stage, "cancelled")
            raise  # 取消必须向上传播，由编排层保存进度并清理。
        except TimeoutError as exc:
            self._record(stage, "failed")
            raise AgentError(f"超过 {self.timeout}s 角色超时", kind="timeout",
                             role=self.role, stage=stage) from exc
        except Exception as exc:
            self._record(stage, "failed")
            raise AgentError(str(exc)[:300], kind="call", role=self.role, stage=stage) from exc
        self._record(stage, "passed", response)
        return text_of(response)

    def mark_output_failure(self, stage: str):
        """请求已发出且用量已计入，但输出未通过解析/契约校验：改记该次调用失败。"""
        for index in range(len(self.calls) - 1, -1, -1):
            if self.calls[index].stage == stage:
                self.calls[index] = self.calls[index].model_copy(update={"status": "failed"})
                return


def default_role_model(role: str):
    """按角色配置构建默认模型：关闭 SDK 隐式重试，限制角色输出长度。"""
    from app.agents.graph import get_llm
    cfg = settings.go_multi_agent
    name = cfg.role_model(role, settings.llm_model)
    bound = get_llm(max_retries=0, model=name)
    return name, bound.bind(max_tokens=getattr(cfg, role + "_output_tokens"))


def injected_model_name(model) -> str:
    return getattr(model, "model_name", None) or type(model).__name__
