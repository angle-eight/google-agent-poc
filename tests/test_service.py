from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from google.adk.sessions import Session

from helpdesk.service import ChatService, SessionNotFound
from helpdesk.tools import KNOWLEDGE_SEARCH_TOOLS


@pytest.mark.parametrize("representation", ["object", "snake_case", "camel_case"])
async def test_session_continues_and_deletes_across_service_instances(representation):
    session = Session(id="s1", app_name="helpdesk_agent", user_id="alice")
    if representation != "object":
        session = session.model_dump(mode="json", by_alias=representation == "camel_case")

    queries = []

    async def stream(**kwargs):
        queries.append(kwargs)
        yield {"content": {"role": "model", "parts": [{"text": "回答"}]}}

    backend = SimpleNamespace(
        async_create_session=AsyncMock(return_value={"id": "s1", "user_id": "alice"}),
        async_get_session=AsyncMock(return_value=session),
        async_delete_session=AsyncMock(),
        async_stream_query=stream,
    )
    first = await ChatService(backend).chat("alice", "PCを2台購入")
    second = await ChatService(backend).chat("alice", "1台なら？", first["session_id"])
    assert second["session_id"] == first["session_id"] == "s1"
    assert queries == [
        {"user_id": "alice", "session_id": "s1", "message": "PCを2台購入"},
        {"user_id": "alice", "session_id": "s1", "message": "1台なら？"},
    ]
    await ChatService(backend).delete_session("alice", first["session_id"])
    backend.async_create_session.assert_awaited_once_with(user_id="alice")
    backend.async_delete_session.assert_awaited_once_with(user_id="alice", session_id="s1")


@pytest.mark.parametrize(
    "owner_fields",
    [
        {"user_id": "bob"},
        {"userId": "bob"},
        {},
        {"user_id": "bob", "userId": "alice"},
    ],
)
async def test_session_with_wrong_or_missing_owner_is_rejected(owner_fields):
    backend = SimpleNamespace(
        async_get_session=AsyncMock(return_value={"id": "s1", **owner_fields}),
        async_delete_session=AsyncMock(),
        async_stream_query=AsyncMock(),
    )
    service = ChatService(backend)
    with pytest.raises(SessionNotFound):
        await service.chat("alice", "1台なら？", "s1")
    with pytest.raises(SessionNotFound):
        await service.delete_session("alice", "s1")
    backend.async_delete_session.assert_not_awaited()
    backend.async_stream_query.assert_not_called()


@pytest.mark.parametrize("search_tool", sorted(KNOWLEDGE_SEARCH_TOOLS))
async def test_collects_tool_sources_and_discards_thoughts_and_partial_text(search_tool):
    async def stream(**kwargs):
        yield {"content": {"role": "model", "parts": [{"text": "調べます"}]}}
        yield {
            "content": {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": search_tool,
                            "args": {"query": "VPN"},
                        }
                    }
                ],
            }
        }
        yield {
            "content": {
                "parts": [
                    {
                        "functionResponse": {
                            "name": search_tool,
                            "response": {"results": [{"id": "IT-001"}]},
                        }
                    }
                ]
            }
        }
        yield {"partial": True, "content": {"role": "model", "parts": [{"text": "途中"}]}}
        yield {
            "content": {
                "role": "model",
                "parts": [
                    {"text": "internal reasoning", "thought": True},
                    {"text": "最終回答 [IT-001]"},
                ],
            }
        }

    backend = SimpleNamespace(
        async_create_session=AsyncMock(return_value={"id": "s1"}), async_stream_query=stream
    )
    result = await ChatService(backend).chat("alice", "VPN")
    assert result["answer"] == "最終回答 [IT-001]"
    assert result["sources"] == [
        {"id": "IT-001", "title": "VPNに接続できないとき", "category": "IT"}
    ]


async def test_empty_final_answer_and_error_events_fail():
    async def empty_stream(**kwargs):
        yield {"content": {"parts": []}}

    backend = SimpleNamespace(
        async_create_session=AsyncMock(return_value={"id": "s1"}), async_stream_query=empty_stream
    )
    with pytest.raises(RuntimeError, match="no final text"):
        await ChatService(backend).chat("alice", "VPN")

    async def error_stream(**kwargs):
        yield {"error_code": "MODEL_ERROR"}

    backend.async_stream_query = error_stream
    with pytest.raises(RuntimeError, match="error event"):
        await ChatService(backend).chat("alice", "VPN")
