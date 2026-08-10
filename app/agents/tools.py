# -*- coding: utf-8 -*-
"""Agent 工具集：RAG 检索问答 / 订单查询(Mock) / 售后规则。
真实项目中：order 工具通过 Feign/HTTP 调用 order-server，售后工具对接多模态质检服务。

命名约定：
- search_knowledge / query_order / after_sale_rule：原始函数，内置路由与 SSE 流式直接调用；
- *_tool 变体：CrewAI Tool 包装（仅安装 crewai 后存在），供多 Agent 编排使用。
"""
import re

from app.rag.retriever import answer_with_rag, build_llm


def search_knowledge(query: str) -> str:
    """检索平台知识库并基于资料回答问题（RAG）。"""
    answer, _ = answer_with_rag(query, build_llm())
    return answer


def query_order(message: str) -> str:
    """查询用户订单状态与物流信息（Mock 数据）。"""
    match = re.search(r"\d{6,}", message)
    order_no = match.group(0) if match else "202608090001"
    return (
        f"订单 {order_no}：状态=已发货，物流=顺丰速运 SF1234567890，"
        "预计 8 月 11 日送达。如需退款或售后，请在订单详情页申请。"
    )


def after_sale_rule(_message: str) -> str:
    """查询平台售后与退货规则。"""
    return ("售后规则：签收 7 天内可申请无理由退货（需不影响二次销售）；"
            "商品破损或与描述不符的，运费由卖家承担；请上传凭证由 AI 质检确认。")


# CrewAI 工具版（供 Agent 编排；未安装 crewai 时为 None，系统自动降级）
search_knowledge_tool = None
query_order_tool = None
after_sale_rule_tool = None
CREW_TOOLS_READY = False
try:
    from crewai.tools import tool
    search_knowledge_tool = tool("search_knowledge")(search_knowledge)
    query_order_tool = tool("query_order")(query_order)
    after_sale_rule_tool = tool("after_sale_rule")(after_sale_rule)
    CREW_TOOLS_READY = True
except Exception:  # pragma: no cover - crewai 未安装
    CREW_TOOLS_READY = False
