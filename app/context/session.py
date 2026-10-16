"""会话存储接入，旧路径仍由 MemoryStore 提供最近轮次。"""
from app.config import settings
from app.context.contracts import scope
from app.context.store import get_store
from langchain_core.messages import HumanMessage,AIMessage
from pathlib import Path


def available_store():
    if settings.context_mode!="off":return get_store()
    # 回退后继续读取已有原文；默认 off 且无数据库时不创建数据库。
    from app.context.store import ROOT
    path=Path(settings.context_store_path)
    if settings.context_store_path!=":memory:" and (path if path.is_absolute() else ROOT/path).exists():return get_store()
    return None


def prepare(session_id,messages):
    if settings.context_mode=="off":
        store=available_store()
        if store and not messages:
            from app.services.memory import memory
            for row in store.turns(*scope(session_id))[-memory.max_turns:]:memory.add(session_id,row["user"],row["assistant"])
        return
    get_store().import_legacy(*scope(session_id),messages)


def commit(session_id,run_id,user,assistant):
    if available_store() is not None:
        from app.context.summary import draft
        pending=draft(run_id)
        get_store().commit(*scope(session_id),run_id,user,assistant,
                           summary=pending[0] if pending else None,expected_version=pending[1] if pending else None)


def persist_run(session_id,run_id,report):
    if settings.context_mode!="off":get_store().save_run(*scope(session_id),run_id,report)


def history(session_id,fallback):
    if settings.context_mode!="off":
        rows=get_store().turns(*scope(session_id))
        if rows:
            chosen=rows if settings.context_mode=="enforce" and settings.context_history_enabled else rows[-settings.memory_retrieve_turns:]
            if settings.context_mode=="enforce" and settings.context_summary_enabled:
                summary=get_store().summary(*scope(session_id))
                if summary:chosen=[r for r in chosen if r["turn"]>summary["covered_until_turn"]]
            if not chosen:return [],rows[-1]["turn"]+1
            return [m for r in chosen for m in (HumanMessage(content=r["user"]),AIMessage(content=r["assistant"]))],chosen[0]["turn"]
    return fallback,1


def has_history(session_id,fallback):
    store=available_store()
    if store and store.turns(*scope(session_id)):return True
    return bool(fallback)
