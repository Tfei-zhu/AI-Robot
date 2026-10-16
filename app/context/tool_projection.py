"""工具原文单独保存；按类型构造有效、可补读的模型结果。"""
import json
import re
from contextvars import ContextVar
from langchain_core.tools import tool
from app.config import settings
from app.context.contracts import scope,ContextBudgetExceeded
from app.context.store import get_store
from app.context.token_counter import TokenCounter

tool_session=ContextVar("context_tool_session",default=None)


def dumps(value):return json.dumps(value,ensure_ascii=False,separators=(",",":"))


def text_slice(text,offset,budget):
    counter=TokenCounter();remaining=text[offset:];lo,hi=0,len(remaining)
    while lo<hi:
        mid=(lo+hi+1)//2
        if counter.text(remaining[:mid])<=budget:lo=mid
        else:hi=mid-1
    return remaining[:lo],offset+lo


def excerpt(text,query,budget):
    counter=TokenCounter()
    if counter.text(text)<=budget:return text,False
    if "```" in text or re.search(r"\bpackage\s+\w+",text):
        # 源码不做静默裁断，调用方通过原文补读获取完整内容。
        return "[完整代码超过片段预算，请补读原文]",True
    sentences=list(dict.fromkeys(s.strip() for s in re.split(r"(?<=[。！？\n])",text) if s.strip()))
    terms=set(re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}",query))
    ranked=sorted(enumerate(sentences),key=lambda pair:(-sum(term.lower() in pair[1].lower() for term in terms),
                                                       -bool(re.search(r"\d|错误|结论|禁止|必须",pair[1])),pair[0]))
    chosen=[]
    for index,line in ranked:
        candidate="\n".join(s for _,s in sorted(chosen+[(index,line)]))
        if counter.text(candidate)<=budget:chosen.append((index,line))
    return "\n".join(s for _,s in sorted(chosen)) or "[片段超过额度，请补读原文]",True


def project(name,raw,*,session,run_id,args,messages=()):
    store=get_store();result_id=store.save_result(*scope(session),run_id,{"tool":name,"data":raw,"args":args})
    sources=[str(s) for s in raw.get("sources",[])][:20]
    out={"status":raw.get("status","error" if raw.get("error") else "ok"),"result_id":result_id,
         "sources":sources,"truncated":False,"readable_fields":list(raw)}
    counter=TokenCounter();limit=settings.context_tool_tokens
    if name=="search_knowledge" and "chunks" in raw:
        from app.context.evidence import register,visible
        from app.context.usage import ledger
        seen,used=visible(messages);remaining=max(0,settings.context_evidence_tokens-used)
        metrics=ledger(run_id).context
        out["chunks"]=[]
        for chunk in raw.get("chunks",[]):
            evidence=register(chunk,session,result_id,str(args.get("query","")));eid=evidence["evidence_id"]
            if eid in seen:
                if any(c.get("evidence_id")==eid for c in out["chunks"]):continue
                item={"evidence_id":eid,"source":chunk.get("source",""),"sources":evidence["sources"],"result_id":result_id,"reused":True}
                metrics["evidence_deduplicated"]=metrics.get("evidence_deduplicated",0)+1
                candidate={**out,"chunks":[*out["chunks"],item]}
                if counter.text(dumps(candidate))<=limit:out["chunks"].append(item)
                else:out["truncated"]=True
                continue
            text,cut=excerpt(str(chunk.get("text","")),str(args.get("query","")),max(0,min(limit//2,remaining)))
            item={"text":text,"evidence_id":eid,"source":chunk.get("source",""),"sources":evidence["sources"],"title":chunk.get("title",""),
                  "knowledge_revision":evidence["knowledge_revision"],"result_id":result_id}
            candidate={**out,"chunks":[*out["chunks"],item]}
            size=counter.text(text)
            if counter.text(dumps(candidate))<=limit and size<=remaining:
                out["chunks"].append(item);remaining-=size;seen[eid]=item
            else:cut=True
            out["truncated"]|=cut
        if len(out["chunks"])<len(raw.get("chunks",[])):out["truncated"]=True
        metrics["evidence_tokens"]=settings.context_evidence_tokens-remaining
    elif name=="query_article" and "article" in raw:
        data=raw.get("article") or {};question=str(args.get("message",""))
        keys={"id","title"}
        for field,words in {"likes_count":("点赞","likes"),"comments_count":("评论","comments"),
                            "username":("作者","author"),"tags":("标签","tags"),"content":("正文","全文")}.items():
            if any(w in question for w in words):keys.add(field)
        if any(w in question for w in ("详情","数据","detail")):keys|={"likes_count","comments_count","username","tags"}
        out["article"]={k:v for k,v in data.items() if k in keys}
        out["queried_at"]=raw.get("queried_at")
        out["truncated"]=set(out["article"])!=set(data)
    else:
        if raw.get("error"):out["error"]=str(raw["error"])
        if raw.get("answer") is not None:
            out["answer"],out["truncated"]=excerpt(str(raw["answer"]),str(args),max(40,limit//2))
        elif "article" not in raw and name!="search_knowledge":out["data"]=raw
    # 大字段逐个省略并提供原文入口；绝不截断整个 JSON 字符串。
    if counter.text(dumps(out))>limit:
        out={k:v for k,v in out.items() if k not in ("data","article","answer","chunks")}
        out["truncated"]=True
    if counter.text(dumps(out))>limit:
        raise ContextBudgetExceeded("context_budget_exceeded: 工具状态和来源超过额度")
    from app.context.usage import ledger
    metrics=ledger(run_id).context
    metrics["tool_raw_tokens"]=metrics.get("tool_raw_tokens",0)+counter.text(dumps(raw))
    metrics["tool_projected_tokens"]=metrics.get("tool_projected_tokens",0)+counter.text(dumps(out))
    return out


@tool("read_tool_result")
async def read_tool_result(result_id:str,field:str="",offset:int=0)->str:
    """补读当前会话工具原文；可选择顶层字段与字符偏移，返回受额度限制的文本片段。"""
    session=tool_session.get()
    if session is None or offset<0:return dumps({"status":"error","error":"补读参数无效"})
    record=get_store().result(*scope(session),result_id)
    if record is None:
        evidence=get_store().evidence(*scope(session),result_id)
        if evidence:record={"data":{"answer":evidence["text"],"sources":evidence["sources"]}}
    if record is None:return dumps({"status":"error","error":"结果不存在或不属于当前会话"})
    raw=record["data"]
    if field and field not in raw:return dumps({"status":"error","error":"字段不存在"})
    value=raw[field] if field else raw
    text=value if isinstance(value,str) else dumps(value)
    out={"status":"ok","result_id":result_id,"field":field,"offset":offset,"sources":raw.get("sources",[])[:20],
         "content_type":"text_slice","content":"","next_offset":None,"truncated":False}
    counter=TokenCounter();allow=settings.context_read_tokens-counter.text(dumps(out))-40
    if allow<=0:raise ContextBudgetExceeded("context_budget_exceeded: 补读元数据超过额度")
    content,end=text_slice(text,offset,allow)
    out.update(content=content,next_offset=end if end<len(text) else None,truncated=end<len(text))
    if counter.text(dumps(out))>settings.context_read_tokens:raise ContextBudgetExceeded("context_budget_exceeded: 补读结果超限")
    return dumps(out)
