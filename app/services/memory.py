# -*- coding: utf-8 -*-
"""会话记忆：session_id -> InMemoryChatMessageHistory（进程内，演示用）。
生产替换点：Redis / SQLite 持久化，接口保持一致（get_messages / add / clear）。
"""
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.config import settings


class MemoryStore:
    """按 session 保存对话轮次，超出上限时裁剪最旧消息。"""

    def __init__(self, max_turns: int | None = None, retrieve_turns: int | None = None) -> None:
        self.max_turns = max_turns or settings.memory_max_turns
        self.retrieve_turns = retrieve_turns or settings.memory_retrieve_turns
        self._histories: dict[str, InMemoryChatMessageHistory] = {}

    def get_messages(self, session_id: str, limit: int | None = None) -> list[BaseMessage]:
        """返回最近 N 轮消息（含角色），无历史时返回空列表。"""
        history = self._histories.get(session_id)
        if history is None:
            return []
        messages = history.messages
        keep = (limit or self.retrieve_turns) * 2
        return messages[-keep:] if len(messages) > keep else messages

    def add(self, session_id: str, user_message: str, ai_message: str) -> None:
        history = self._histories.setdefault(session_id, InMemoryChatMessageHistory())
        history.add_user_message(user_message)
        history.add_ai_message(ai_message)
        cap = self.max_turns * 2
        if len(history.messages) > cap:
            keep = history.messages[-cap:]
            history.clear()
            history.add_messages(keep)

    def clear(self, session_id: str) -> None:
        history = self._histories.pop(session_id, None)
        if history is not None:
            history.clear()


memory = MemoryStore()


def format_history(messages: list[BaseMessage], max_len: int = 600) -> str:
    """把消息列表格式化为给 Agent 的上下文文本（如 CrewAI Task 描述）。"""
    parts = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            role = "用户"
        elif isinstance(msg, AIMessage):
            role = "助手"
        else:
            role = "系统"
        parts.append(f"{role}: {str(msg.content)[:max_len]}")
    return "\n".join(parts)
