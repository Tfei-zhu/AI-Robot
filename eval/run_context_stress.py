"""真实模型快照补充验收：摘要后的纠正、知识更新与实时文章数据。

预置历史只用于独立机制压力测试，不计入正式端到端矩阵的完成率。
"""
import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.config import settings
from app.context.store import get_store
from app.context.contracts import scope
from app.context.summary import render
from app.services.chat import chat
from app.agents import graph
from app.rag.retriever import kb
from langchain_core.tools import tool
from eval.run_context_eval import parse_answer,matches


async def run():
    session=hashlib.sha256(b"context-stress").hexdigest()+":"+uuid.uuid4().hex
    store=get_store();records=[];checks={}
    for i in range(12):
        user="原任务必须用 Go 1.26.2，只用标准库，任务编号 LATE-CTX。" if i==0 else "插入讨论命名和日志，不改变原任务约束。"*3
        store.commit(*scope(session),f"seed-{i}",user,"已记录。")
    async def ask(text):
        result=await chat(text,session);records.append(result);return result
    await ask("确认原任务，只回复已记录。")
    old=store.summary(*scope(session));checks["initial_summary_created"]=old is not None
    await ask("纠正原任务版本：改为 Go 1.25.0，其他要求保持不变。请确认。")
    correction_turn=store.turns(*scope(session))[-1]["turn"]
    for i in range(12):
        await ask("插入一条工程建议，不修改原任务。只用一句话。")
        latest=store.summary(*scope(session))
        if latest and latest["covered_until_turn"]>=correction_turn:break
    latest=store.summary(*scope(session))
    checks["correction_summarized"]=bool(latest and latest["covered_until_turn"]>=correction_turn)
    active=[c["text"] for c in (latest or {}).get("constraints",[]) if c.get("active",True)]
    checks["old_version_inactive"]=not any("1.26.2" in s for s in active)
    answer=parse_answer((await ask("只输出 JSON：language、version、dependency、task_id，填写原任务有效要求。"))["reply"])
    checks["late_constraint_retention"]=all(matches(k,answer.get(k,""),v) for k,v in {"language":"Go","version":"1.25.0","dependency":"标准库","task_id":"LATE-CTX"}.items())
    knowledge={"value":250,"calls":0};article={"value":7,"calls":0}
    @tool("search_knowledge")
    async def search(query:str)->str:
        """读取测试知识的最新超时值。"""
        knowledge["calls"]+=1
        return json.dumps({"chunks":[{"text":f"最新超时是 {knowledge['value']}ms。","source":"stress#0","knowledge_revision":kb.revision}],"sources":["stress#0"]},ensure_ascii=False)
    @tool("query_article")
    async def query_article(message:str)->str:
        """查询测试文章的实时点赞数。"""
        article["calls"]+=1
        return json.dumps({"status":"ok","article":{"id":12,"title":"测试","likes_count":article["value"]},"sources":["article:12"],"queried_at":article["calls"]},ensure_ascii=False)
    with patch.dict(graph._tools_by_name,{"search_knowledge":search,"query_article":query_article}):
        with patch.object(kb,"revision",100):
            first=parse_answer((await ask("调用知识检索查询最新超时，只输出 JSON 字段 timeout_ms。"))["reply"])
        knowledge["value"]=500
        with patch.object(kb,"revision",101):
            second=parse_answer((await ask("知识已更新，请重新调用知识检索查询最新超时，只输出 JSON 字段 timeout_ms。"))["reply"])
        checks["knowledge_update_not_stale"]=first.get("timeout_ms")==250 and second.get("timeout_ms")==500 and knowledge["calls"]>=2
        first=parse_answer((await ask("调用文章查询获取文章12当前点赞数，只输出 JSON 字段 likes。"))["reply"])
        article["value"]=9
        second=parse_answer((await ask("文章数据已变化，请重新调用文章查询获取文章12当前点赞数，只输出 JSON 字段 likes。"))["reply"])
        checks["article_data_not_cached"]=first.get("likes")==7 and second.get("likes")==9 and article["calls"]>=2
    report={"scope":"真实模型、预置快照及受控工具数据的独立压力验收，不并入正式长对话完成率",
            "checks":checks,"passed":all(checks.values()),"records":records}
    target=ROOT/"eval/reports/context/stress.json";target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(checks,ensure_ascii=False));return 0 if report["passed"] else 1


if __name__=="__main__":sys.exit(asyncio.run(run()))
