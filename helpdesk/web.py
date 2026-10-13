"""FastAPI web app. Cloud Run IAM protects access in the deployment guide."""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.sessions import SessionMiddleware

from helpdesk.config import Settings
from helpdesk.service import ChatService, SessionNotFound, create_service
from helpdesk.tools import load_knowledge

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")

    @field_validator("message")
    @classmethod
    def strip_message(cls, message):
        message = message.strip()
        if not message:
            raise ValueError("メッセージを入力してください。")
        return message


class Source(BaseModel):
    id: str
    title: str
    category: str


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    sources: list[Source]
    tools_used: list[str]
    agents_used: list[str]


def browser_user(request: Request) -> str:
    if "user_id" not in request.session:
        request.session["user_id"] = uuid4().hex
    return request.session["user_id"]


def create_app(settings: Settings | None = None, service: ChatService | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if settings.backend == "remote":
        settings.require_remote()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.chat_service = service or await asyncio.to_thread(create_service, settings)
        yield

    app = FastAPI(title="社内ヘルプデスク / Agent Platform PoC", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret or secrets.token_urlsafe(32),
        session_cookie="helpdesk_browser",
        same_site="strict",
        https_only=settings.cookie_secure,
        max_age=86400,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index(request: Request):
        browser_user(request)
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "backend": settings.backend}

    @app.get("/api/config")
    async def config(request: Request):
        browser_user(request)
        return {"backend": settings.backend, "demo_data": True}

    @app.get("/api/knowledge")
    async def knowledge():
        return {"documents": load_knowledge(), "demo_data": True}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request):
        try:
            async with asyncio.timeout(120):
                return await request.app.state.chat_service.chat(
                    browser_user(request),
                    body.message,
                    body.session_id,
                )
        except SessionNotFound as exc:
            raise HTTPException(
                404,
                "会話が見つかりません。「新しい会話」でやり直してください。",
            ) from exc
        except TimeoutError as exc:
            raise HTTPException(
                504,
                "回答がタイムアウトしました。時間をおいてお試しください。",
            ) from exc
        except Exception as exc:
            logger.exception("Agent query failed")
            raise HTTPException(
                502,
                "接続に失敗しました。認証・設定・サーバーログを確認してください。",
            ) from exc

    @app.delete("/api/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str, request: Request):
        try:
            async with asyncio.timeout(30):
                await request.app.state.chat_service.delete_session(
                    browser_user(request),
                    session_id,
                )
        except SessionNotFound as exc:
            raise HTTPException(404, "会話が見つかりません。") from exc
        except TimeoutError as exc:
            raise HTTPException(504, "会話の削除がタイムアウトしました。") from exc
        except Exception as exc:
            logger.exception("Session deletion failed")
            raise HTTPException(502, "会話を削除できませんでした。") from exc
        return Response(status_code=204)

    return app


app = create_app()
