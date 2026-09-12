"""默认拒绝匿名 API；区分管理员与可信网关账户，并隔离会话。"""
import hashlib
import re
import secrets
import uuid

from fastapi import HTTPException
from starlette.responses import JSONResponse, StreamingResponse
from app.config import settings


def _matches(value, expected):
    return bool(expected) and secrets.compare_digest(value.encode(), expected.encode())


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}
        admin = _matches(headers.get("authorization", ""), "Bearer " + settings.admin_token) if settings.admin_token else False
        account = headers.get("x-account-id", "")
        gateway = (_matches(headers.get("x-internal-token", ""), settings.ai_internal_token)
                   and bool(re.fullmatch(r"[1-9][0-9]{0,19}", account)))
        if not admin and not gateway:
            status = 401 if (settings.admin_token or settings.ai_internal_token) else 503
            return await JSONResponse({"detail": "需要有效身份凭据" if status == 401 else "服务尚未配置访问凭据"},
                                      status_code=status)(scope, receive, send)
        if not admin and path not in {"/api/v1/chat", "/api/v1/chat/stream"}:
            return await JSONResponse({"detail": "需要管理员权限"}, status_code=403)(scope, receive, send)
        # 内部令牌不等同于管理员；客户端自填账户只有网关令牌匹配后才可信。
        principal = "admin" if admin else "account/" + account
        scope.setdefault("state", {})["principal"] = principal
        if path == "/api/v1/ingest":
            # 在 FastAPI multipart 解析前限制请求体；允许少量 multipart 元数据开销。
            limit = settings.max_upload_bytes + 64 * 1024
            try:
                length = int(headers.get("content-length", "0"))
                if length < 0:
                    raise ValueError
            except ValueError:
                return await JSONResponse({"detail": "Content-Length 无效"}, status_code=400)(scope, receive, send)
            body, size = [], 0
            if length > limit:
                return await JSONResponse({"detail": "上传请求过大"}, status_code=413)(scope, receive, send)
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                size += len(event.get("body", b""))
                if size > limit:
                    return await JSONResponse({"detail": "上传请求过大"}, status_code=413)(scope, receive, send)
                body.append(event)
                if not event.get("more_body", False):
                    break
            iterator = iter(body)

            async def replay():
                event = next(iterator, None)
                return event if event is not None else await receive()

            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


def session_identity(principal, requested):
    public = requested or uuid.uuid4().hex
    owner = hashlib.sha256(principal.encode()).hexdigest()
    # 哈希元组防止账户/会话分隔符碰撞，缓存只取第一个冒号前的账户命名空间。
    key = owner + ":" + hashlib.sha256(public.encode()).hexdigest()
    return public, key


_busy = set()


def claim_session(key):
    if key in _busy:
        raise HTTPException(status_code=409, detail="该会话正在处理上一条消息，请等待完成")
    _busy.add(key)


def release_session(key):
    _busy.discard(key)


class SessionStreamResponse(StreamingResponse):
    def __init__(self, *args, session_key, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_key = session_key

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            release_session(self.session_key)
