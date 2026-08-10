# -*- coding: utf-8 -*-
"""CrewAI 多智能体：意图识别官 -> 客服执行员（多工具编排）。
结构：Agent(角色/目标/背景/工具/LLM) + Task + Crew(sequential)，
与面试叙事一致：把 C2C 客服的"意图路由+工具调用"升级为多 Agent 协作。
"""
from app.config import settings


def run_crew(message: str, history_text: str = "") -> str:
    from crewai import Agent, Crew, LLM, Process, Task

    from app.agents.tools import (
        after_sale_rule_tool,
        query_order_tool,
        search_knowledge_tool,
    )

    llm = LLM(
        model=f"openai/{settings.llm_model}",
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=0.3,
    )
    history_desc = f"\n对话历史：\n{history_text}" if history_text else ""

    router = Agent(
        role="意图识别官",
        goal="准确判断用户消息的意图类型",
        backstory=("你是二手交易平台的意图识别专家，"
                   "只输出 JSON：{{'intent': 'knowledge|order|chat', 'reason': '简短理由'}}"),
        llm=llm,
        verbose=False,
    )

    executive = Agent(
        role="客服执行员",
        goal="根据意图调用对应工具，给出真实、友好、简洁的中文答复",
        backstory=("你是二手交易平台客服，擅长用工具查订单、查知识库、讲售后规则。"
                   "必须依据工具返回的真实数据作答，禁止编造。"),
        tools=[search_knowledge_tool, query_order_tool, after_sale_rule_tool],
        llm=llm,
        verbose=False,
    )

    task_router = Task(
        description=f"分析用户消息：{message}（如有对话历史请结合上下文）{history_desc}。只输出意图 JSON。",
        expected_output="JSON：intent / reason",
        agent=router,
    )
    task_exec = Task(
        description=(
            "根据意图识别官的结论处理用户消息。规则："
            "intent=knowledge 时调用 search_knowledge 回答；"
            "intent=order 时调用 query_order 查询订单；"
            "涉及售后/退货时调用 after_sale_rule；"
            "intent=chat 时直接礼貌闲聊；"
            "结合对话历史保持上下文连贯。"
            "最终给出面向用户的完整中文答复。"
            f"{history_desc}"
        ),
        expected_output="给用户的最终中文答复",
        agent=executive,
    )

    crew = Crew(
        agents=[router, executive],
        tasks=[task_router, task_exec],
        process=Process.sequential,
        verbose=False,
    )
    result = crew.kickoff()
    return str(getattr(result, "raw", result))
