"""精确证据去重和查询复用；版本变化、进程重启或会话变化后失效。"""
import hashlib
import json
import uuid
from langchain_core.messages import ToolMessage
from app.config import settings
from app.context.contracts import scope
from app.context.store import get_store
from app.context.token_counter import TokenCounter
from app.context.usage import ledger

INSTANCE_ID=uuid.uuid4().hex


def search_key(args,revision,instance_id=None):
    # 保留否定词、大小写、数值及过滤条件，不把相似问题误当同一请求。
    return hashlib.sha256(json.dumps([instance_id or INSTANCE_ID,revision,args],ensure_ascii=False,sort_keys=True).encode()).hexdigest()


async def retrieve(tool,args,*,session,run_id,revision):
    metrics=ledger(run_id).context
    metrics["retrieval_requested"]=metrics.get("retrieval_requested",0)+1
    key=search_key(args,revision);store=get_store()
    cached=store.search_cache(*scope(session),key,ttl=settings.context_evidence_ttl)
    if cached is not None:
        metrics["retrieval_reused"]=metrics.get("retrieval_reused",0)+1
        return cached
    metrics["retrieval_executed"]=metrics.get("retrieval_executed",0)+1
    raw=await tool.ainvoke(args)
    try:data=json.loads(raw) if isinstance(raw,str) else raw
    except (ValueError,TypeError):data={}
    if isinstance(data,dict) and "chunks" in data and not data.get("error") and data.get("status") in (None,"ok"):
        serialized=raw if isinstance(raw,str) else json.dumps(raw,ensure_ascii=False)
        store.search_cache(*scope(session),key,serialized,ttl=settings.context_evidence_ttl)
    return raw


def register(chunk,session,result_id,query=""):
    text=str(chunk.get("text",""));eid="ev_"+hashlib.sha256(text.encode()).hexdigest()[:24]
    store=get_store();old=store.evidence(*scope(session),eid) or {}
    sources=list(dict.fromkeys([*old.get("sources",[]),str(chunk.get("source",""))]))
    item={"evidence_id":eid,"text":text,"sources":sources,"title":chunk.get("title",""),"result_id":result_id,
          "doc_id":chunk.get("doc_id"),"heading_path":chunk.get("heading_path",[]),"knowledge_revision":chunk.get("knowledge_revision"),
          "query":query,"score":chunk.get("score")}
    store.evidence(*scope(session),eid,item)
    return item


def visible(messages):
    seen={};counter=TokenCounter();tokens=0
    for message in messages:
        if not isinstance(message,ToolMessage):continue
        try:data=json.loads(message.content)
        except (ValueError,TypeError):continue
        for item in data.get("chunks",[]):
            eid=item.get("evidence_id")
            if eid and item.get("text") and eid not in seen:
                seen[eid]=item;tokens+=counter.text(item["text"])
        if data.get("content_type")=="text_slice":tokens+=counter.text(data.get("content",""))
    return seen,tokens
