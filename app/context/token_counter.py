"""完整请求的本地计量；强制模式仅接受匹配模型和端点的校准记录。"""
import hashlib
import json
from pathlib import Path
import tiktoken
from langchain_core.utils.function_calling import convert_to_openai_tool
from app.config import settings

SERIALIZER_VERSION="json-message-tools-v1"


def payload(messages,tools=()):
    data=[]
    for message in messages:
        item={"role":{"human":"user","ai":"assistant","system":"system","tool":"tool"}.get(message.type,message.type),"content":message.content}
        if getattr(message,"tool_calls",None):item["tool_calls"]=message.tool_calls
        if getattr(message,"tool_call_id",None):item["tool_call_id"]=message.tool_call_id
        data.append(item)
    return {"messages":data,"tools":[convert_to_openai_tool(t) for t in tools]}


class TokenCounter:
    def __init__(self,encoding=None,calibration_path=None):
        self.encoding_name=encoding or settings.context_encoding
        self.encoding=tiktoken.get_encoding(self.encoding_name)
        self.factor=1.0;self.verified=False;self.calibration=None
        path=calibration_path if calibration_path is not None else settings.context_calibration_path
        if path:
            try:data=json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError,ValueError):return
            endpoint=hashlib.sha256(settings.llm_base_url.encode()).hexdigest()
            # 记录包含样本与序列化版本；换模型、端点、编码器后必须重新校准。
            if (data.get("model")==settings.llm_model and data.get("endpoint_sha256")==endpoint
                and data.get("encoding")==self.encoding_name and data.get("serializer")==SERIALIZER_VERSION
                and data.get("samples",0)>=20 and data.get("validated") is True):
                self.factor=float(data["factor"])
                self.verified=1<=self.factor<=4
                if self.verified:self.calibration=data
                else:self.factor=1.0

    def text(self,text):
        import math
        return math.ceil(len(self.encoding.encode(str(text),disallowed_special=()))*self.factor)

    def count(self,messages,tools=()):
        return self.text(json.dumps(payload(messages,tools),ensure_ascii=False,separators=(",",":")))+32


def validate_config():
    if settings.context_mode not in ("off","observe","enforce"):raise ValueError("CONTEXT_MODE 必须是 off/observe/enforce")
    if settings.context_mode=="off":return
    if not 0<=settings.context_summary_target_ratio<settings.context_summary_trigger_ratio<=1:
        raise ValueError("摘要回落阈值必须小于触发阈值，且处于0到1之间")
    for name in ("context_input_limit","context_output_tokens","context_safety_tokens","context_history_tokens",
                 "context_summary_tokens","context_evidence_tokens","context_tool_tokens","context_read_tokens"):
        if getattr(settings,name)<=0:raise ValueError(f"{name} 必须大于零")
    if settings.context_mode=="enforce":
        if settings.context_model_window<=settings.context_output_tokens+settings.context_safety_tokens:
            raise ValueError("强制上下文模式必须配置足够的模型窗口")
        if not TokenCounter().verified:raise ValueError("当前模型计数方式尚未经校准，不允许 enforce")
