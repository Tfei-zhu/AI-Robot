"""Go 路径保留完整必要源码，只压缩资料及冗余日志。"""
import copy
import json
import re
from langchain_core.messages import SystemMessage,HumanMessage
from app.config import settings
from app.context.budget import check
from app.context.usage import ledger


def messages(state,instructions,data,output_tokens):
    prepared=copy.deepcopy(data)
    if settings.context_mode=="enforce" and "previous_attempt" in prepared:
        for stage in prepared["previous_attempt"]["validation"].get("stages",[]):
            output=stage.get("output","")
            if stage.get("exit_code")==0:
                stage["output"]="检查通过，完整日志已保存"
            elif stage.get("stage")=="test":
                # 提取真实测试输出；完整代码和验收文件不做截断。
                lines=[]
                for line in output.splitlines():
                    try:
                        item=json.loads(line)
                        if item.get("Output"):lines.append(item["Output"])
                    except ValueError:lines.append(line)
                relevant=[line for line in lines if re.search(r"FAIL|panic|timed out|error|\.go:\d|错误|失败|必须",line,re.I)]
                stage["output"]="\n".join(dict.fromkeys(relevant or lines))
    result=[SystemMessage(content=instructions),HumanMessage(content=json.dumps(prepared,ensure_ascii=False))]
    if settings.context_mode!="off":
        metrics=check(result,output_tokens=output_tokens)
        ledger(state["run_id"]).context.update(context_mode=settings.context_mode,go_input_estimate=metrics["input_estimate"],
                                              counter_verified=metrics["counter_verified"])
    return result
