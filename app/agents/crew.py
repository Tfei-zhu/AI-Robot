# -*- coding: utf-8 -*-
"""CrewAI 多智能体：意图识别官 -> 社区助手（多工具编排）。
结构：Agent(角色/目标/背景/工具/LLM) + Task + Crew(sequential)，
把 Go 文章社区的“意图路由 + 工具调用”组织为多 Agent 协作。
"""
from app.config import settings


def run_crew(message: str, history_text: str = "") -> str:
    from crewai import Agent, Crew, LLM, Process, Task

    from app.agents.tools import (
        community_guideline_tool,
        query_article_tool,
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
        backstory=("你是 Go 文章社区的意图识别专家，"
                   "只输出 JSON：{{'intent': 'knowledge|article|chat', 'reason': '简短理由'}}。"
                   "article 用于指定文章查询，knowledge 用于 Go 技术、发文与社区规范。"),
        llm=llm,
        verbose=False,
    )

    executive = Agent(
        role="社区助手",
        goal="根据意图调用对应工具，给出准确、友好、简洁的中文答复",
        backstory=("你是 Go 文章社区助手，擅长查询文章、检索 Go 技术知识库、说明社区规范。"
                   "必须依据工具返回的真实数据作答，禁止编造。"),
        tools=[search_knowledge_tool, query_article_tool, community_guideline_tool],
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
            "intent=article 时调用 query_article 查询文章；"
            "涉及发文、评论或社区规范时调用 community_guideline；"
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
