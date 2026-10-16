"""使用合成请求与服务商实际输入用量校准保守计数；不声称模型原生精确分词。"""
import asyncio
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.config import settings
from app.agents.graph import get_llm
from app.agents.tools import AGENT_TOOLS
from app.context.token_counter import TokenCounter,SERIALIZER_VERSION
from langchain_core.messages import HumanMessage,SystemMessage,AIMessage,ToolMessage


async def main():
    if not settings.llm_api_key:raise RuntimeError("缺少模型密钥")
    counter=TokenCounter(calibration_path="");rows=[]
    texts=["你好，请回复确认。","Explain Go cancellation briefly.","func main(){ ch:=make(chan int); _=ch }",
           "中文、emoji 🧪、数字 250ms、否定词不要取消。","العربية اختبار context","上下文预算与引用来源。"*50]
    for i in range(20):
        messages=[SystemMessage(content="测试计量，只回复确认。"),HumanMessage(content=texts[i%len(texts)])]
        tools=AGENT_TOOLS if i%2 else []
        if i%4==3:
            messages += [AIMessage(content="",tool_calls=[{"name":"search_knowledge","args":{"query":"context"},"id":"cal-call"}]),
                         ToolMessage(content=json.dumps({"chunks":[{"text":texts[i%6],"source":"fixture#0"}]},ensure_ascii=False),tool_call_id="cal-call"),HumanMessage(content="请确认")]
        model=get_llm(max_retries=0)
        if tools:model=model.bind_tools(tools)
        response=await model.bind(max_tokens=16).ainvoke(messages)
        observed=(response.usage_metadata or {}).get("input_tokens")
        if observed is None:raise RuntimeError("服务商未返回实际输入 Token，无法校准")
        raw=counter.count(messages,tools)
        rows.append({"sample":i,"raw_estimate":raw,"actual_input_tokens":observed,"has_tools":bool(tools)})
        print(f"计数校准 {i+1}/20",flush=True)
    factor=max(1.0,max(r["actual_input_tokens"]/r["raw_estimate"] for r in rows)*1.15)
    data={"model":settings.llm_model,"endpoint_sha256":hashlib.sha256(settings.llm_base_url.encode()).hexdigest(),
          "encoding":settings.context_encoding,"serializer":SERIALIZER_VERSION,"samples":len(rows),"factor":factor,
          "validated":all(math.ceil(r["raw_estimate"]*factor)>=r["actual_input_tokens"] for r in rows),
          "confidence":"empirically-calibrated-conservative; not native exact tokenization","rows":rows}
    target=ROOT/"eval/reports/context/counter-calibration.json";target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("校准完成：",target,"factor=",round(factor,4))


if __name__=="__main__":asyncio.run(main())
