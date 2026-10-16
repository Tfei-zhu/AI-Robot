"""预算覆盖实际消息和工具定义；必须内容超限时明确失败。"""
from app.config import settings
from app.context.contracts import ContextBudgetExceeded
from app.context.token_counter import TokenCounter


def input_limit(output_tokens=None):
    output=output_tokens or settings.context_output_tokens
    available=settings.context_model_window-output-settings.context_safety_tokens
    if available<=0:raise ContextBudgetExceeded("context_budget_exceeded: 模型窗口未配置或输出预留过大")
    return min(settings.context_input_limit,available)


def check(messages,tools=(),output_tokens=None):
    counter=TokenCounter();n=counter.count(messages,tools)
    if settings.context_mode=="enforce":
        if not counter.verified:raise ContextBudgetExceeded("context_budget_exceeded: 计数器未经校准")
        if n>input_limit(output_tokens):raise ContextBudgetExceeded("context_budget_exceeded: 必须内容超过输入额度")
    return {"input_estimate":n,"counter_verified":counter.verified,"counter_mode":"calibrated-conservative" if counter.verified else "estimate",
            "input_limit":input_limit(output_tokens) if settings.context_model_window else None}
