"""The same ADK session/query API is used locally and on Agent Runtime."""

import asyncio
from typing import Any

from helpdesk.config import Settings
from helpdesk.tools import KNOWLEDGE_SEARCH_TOOLS, load_knowledge


class SessionNotFound(Exception):
    """The session does not exist or belongs to another anonymous browser."""


def session_field(session: Any, key: str) -> Any:
    """Read local ADK fields and the aliases used in remote JSON responses."""
    if not isinstance(session, dict):
        return getattr(session, key, None)
    if key in session:
        return session[key]
    aliases = {"user_id": "userId"}
    return session.get(aliases.get(key, key))


class ChatService:
    def __init__(self, backend: Any, *, serialize: bool = False):
        self.backend = backend
        self.lock = asyncio.Lock() if serialize else None

    async def _verify_session(self, user_id: str, session_id: str):
        from google.api_core.exceptions import NotFound

        try:
            session = await self.backend.async_get_session(user_id=user_id, session_id=session_id)
        except NotFound as exc:
            raise SessionNotFound from exc
        except RuntimeError as exc:
            if "Session not found" in str(exc):
                raise SessionNotFound from exc
            raise
        if not session or session_field(session, "user_id") != user_id:
            raise SessionNotFound

    async def chat(self, user_id: str, message: str, session_id: str | None = None) -> dict:
        if self.lock:
            async with self.lock:
                return await self._chat(user_id, message, session_id)
        return await self._chat(user_id, message, session_id)

    async def _chat(self, user_id: str, message: str, session_id: str | None) -> dict:
        if session_id:
            await self._verify_session(user_id, session_id)
        else:
            session = await self.backend.async_create_session(user_id=user_id)
            session_id = session_field(session, "id")
            if not session_id:
                raise RuntimeError("Backend returned no session ID")
        answer = ""
        source_ids: set[str] = set()
        tool_names: set[str] = set()
        agents_used: list[str] = []
        async for event in self.backend.async_stream_query(
            user_id=user_id,
            session_id=session_id,
            message=message,
        ):
            if event.get("error_code"):
                raise RuntimeError("Agent returned an error event")
            content = event.get("content") or {}
            author = event.get("author")
            if content.get("role") == "model" and isinstance(author, str):
                if not agents_used or agents_used[-1] != author:
                    agents_used.append(author)
            parts = content.get("parts") or []
            has_call = any(part.get("function_call") or part.get("functionCall") for part in parts)
            if has_call:
                answer = ""
            for part in parts:
                response = part.get("function_response") or part.get("functionResponse")
                if response:
                    tool_names.add(response["name"])
                    payload = response.get("response") or {}
                    if response["name"] in KNOWLEDGE_SEARCH_TOOLS:
                        source_ids.update(doc["id"] for doc in payload.get("results", []))
                    if response["name"] == "estimate_purchase" and payload.get("source_id"):
                        source_ids.add(payload["source_id"])
            # Ignore thought text, tool events, user echoes and partial stream chunks.
            if content.get("role") == "model" and not has_call and not event.get("partial"):
                text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
                if text:
                    answer = text
        if not answer:
            raise RuntimeError("Agent returned no final text")
        sources = [
            {"id": doc["id"], "title": doc["title"], "category": doc["category"]}
            for doc in load_knowledge()
            if doc["id"] in source_ids
        ]
        return {
            "answer": answer,
            "session_id": session_id,
            "sources": sources,
            "tools_used": sorted(tool_names),
            "agents_used": agents_used,
        }

    async def delete_session(self, user_id: str, session_id: str):
        await self._verify_session(user_id, session_id)
        await self.backend.async_delete_session(user_id=user_id, session_id=session_id)


def create_service(settings: Settings) -> ChatService:
    settings.require_cloud()
    if settings.backend == "remote":
        from helpdesk.platform_client import Client

        settings.require_remote()
        client = Client(project=settings.project, location=settings.location)
        remote = client.agent_engines.get(name=settings.resource_name)
        return ChatService(remote)
    import vertexai
    from vertexai.agent_engines import AdkApp

    from helpdesk.agent import create_agent

    vertexai.init(project=settings.project, location=settings.location)
    return ChatService(
        AdkApp(
            agent=create_agent(
                settings.model,
                settings.model_location,
                settings.project,
            )
        ),
        serialize=True,
    )
