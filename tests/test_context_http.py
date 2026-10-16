"""预算失败在 JSON 与流式接口可识别，失败不会提交会话轮次。"""
import asyncio
import json
from unittest.mock import patch
from httpx import ASGITransport,AsyncClient
from app.config import settings
from app.context.store import get_store,close_stores
from app.context.contracts import scope
from app.services.security import session_identity
from test_context_foundation import calibration


def test_budget_error_json_sse_no_partial_turn(monkeypatch,tmp_path):
    import app.main as main
    monkeypatch.setattr(settings,"context_mode","enforce")
    monkeypatch.setattr(settings,"context_model_window",32768)
    monkeypatch.setattr(settings,"context_input_limit",100)
    monkeypatch.setattr(settings,"context_calibration_path",calibration(tmp_path))
    monkeypatch.setattr(settings,"context_store_path",str(tmp_path/"http.sqlite3"))
    monkeypatch.setattr(settings,"admin_token","context-http-token")
    monkeypatch.setattr(settings,"ratelimit_enabled",False)
    monkeypatch.setattr(settings,"cache_enabled",False)
    monkeypatch.setattr(settings,"llm_api_key","fixture")
    async def run():
        async with AsyncClient(transport=ASGITransport(app=main.app),base_url="http://test") as client:
            args={"headers":{"Authorization":"Bearer context-http-token"},"json":{"message":"任务约束"*100,"session_id":"budget"}}
            response=await client.post("/api/v1/chat",**args)
            assert response.status_code==422
            assert response.json()["detail"]["code"]=="context_budget_exceeded"
            response=await client.post("/api/v1/chat/stream",**args)
            events=[json.loads(s[6:]) for s in response.text.splitlines() if s.startswith("data: ")]
            assert any(e.get("code")=="context_budget_exceeded" for e in events)
            _,key=session_identity("admin","budget")
            assert get_store().turns(*scope(key))==[]
    try:asyncio.run(run())
    finally:close_stores()
