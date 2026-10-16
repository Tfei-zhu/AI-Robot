"""使用显式版本化单价估算金额；缺少用量、模型或端点匹配时返回未知。"""
import json
from decimal import Decimal
from pathlib import Path
from app.config import settings


def estimate(calls):
    if not settings.context_price_book:return None,None,None
    try:book=json.loads(Path(settings.context_price_book).read_text(encoding="utf-8"))
    except (OSError,ValueError):return None,None,None
    total=Decimal(0);uncached=Decimal(0)
    for call in calls:
        usage=call.get("usage");rate=book.get("models",{}).get(call["model"])
        endpoint=settings.embedding_base_url if call["stage"]=="embedding" else settings.llm_base_url
        if not usage or not rate or rate.get("endpoint","").rstrip("/")!=endpoint.rstrip("/"):return None,None,book.get("currency")
        if usage["input_tokens"]>rate.get("max_input_tokens",0):return None,None,book.get("currency")
        input_price=Decimal(str(rate["input"]));output_price=Decimal(str(rate.get("output",0)))
        output_details=usage.get("output_token_details",{})
        if output_details.get("reasoning",0):output_price=Decimal(str(rate.get("thinking_output",rate.get("output",0))))
        cached=usage.get("input_token_details",{}).get("cache_read",0)
        cache_price=Decimal(str(rate.get("cache_read",rate["input"])))
        if cached<0 or cached>usage["input_tokens"]:return None,None,book.get("currency")
        creation=usage.get("input_token_details",{}).get("cache_creation",0)
        if creation:return None,None,book.get("currency")
        total+=(input_price*(usage["input_tokens"]-cached)+cache_price*cached+output_price*usage["output_tokens"])/1000000
        uncached+=(input_price*usage["input_tokens"]+output_price*usage["output_tokens"])/1000000
    return float(total),float(uncached),book.get("currency")
