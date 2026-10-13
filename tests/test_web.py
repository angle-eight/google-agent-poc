from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from google.genai import types
from vertexai.agent_engines import AdkApp

from helpdesk.config import Settings
from helpdesk.service import ChatService
from helpdesk.web import create_app


@pytest.fixture
def local_service(scripted_team):
    agent, _ = scripted_team(
        [
            types.Part.from_function_call(
                name="transfer_to_agent", args={"agent_name": "it_agent"}
            ),
            types.Part.from_function_call(name="search_it_knowledge", args={"query": "VPN"}),
            types.Part(text="VPNを再起動 [IT-001]"),
            types.Part.from_function_call(
                name="transfer_to_agent", args={"agent_name": "helpdesk_agent"}
            ),
            types.Part.from_function_call(
                name="transfer_to_agent", args={"agent_name": "hr_agent"}
            ),
            types.Part.from_function_call(name="search_hr_knowledge", args={"query": "在宅勤務"}),
            types.Part(text="在宅勤務は原則週3日 [HR-001]"),
        ]
    )
    return ChatService(AdkApp(agent=agent), serialize=True)


def test_web_local_chat_sources_and_session_isolation(local_service):
    app = create_app(Settings(session_secret="test-secret"), service=local_service)
    with TestClient(app) as alice, TestClient(app) as bob:
        assert alice.get("/").status_code == 200
        assert alice.get("/healthz").json()["backend"] == "local"
        assert alice.get("/api/config").json()["backend"] == "local"
        assert alice.get("/api/config").json()["demo_data"] is True
        assert len(alice.get("/api/knowledge").json()["documents"]) == 16
        result = alice.post("/api/chat", json={"message": "VPNにつながらない"}).json()
        assert result["sources"][0]["id"] == "IT-001"
        assert result["agents_used"] == ["helpdesk_agent", "it_agent"]
        followup = alice.post(
            "/api/chat", json={"message": "在宅勤務", "session_id": result["session_id"]}
        )
        assert followup.status_code == 200
        assert followup.json()["agents_used"] == ["it_agent", "helpdesk_agent", "hr_agent"]
        assert followup.json()["sources"][0]["id"] == "HR-001"
        assert (
            bob.post(
                "/api/chat", json={"message": "VPN", "session_id": result["session_id"]}
            ).status_code
            == 404
        )
        assert bob.delete(f"/api/sessions/{result['session_id']}").status_code == 404
        assert alice.delete(f"/api/sessions/{result['session_id']}").status_code == 204
        assert (
            alice.post(
                "/api/chat", json={"message": "VPN", "session_id": result["session_id"]}
            ).status_code
            == 404
        )


@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": "  "},
        {"message": "x" * 4001},
        {"message": "VPN", "session_id": "../secret"},
    ],
)
def test_invalid_chat_input(body, local_service):
    with TestClient(create_app(Settings(), service=local_service)) as client:
        assert client.post("/api/chat", json=body).status_code == 422


@pytest.mark.parametrize(
    "error,status", [(RuntimeError("private-token"), 502), (TimeoutError(), 504)]
)
def test_backend_failures_are_sanitized(error, status):
    service = ChatService(SimpleNamespace(async_create_session=AsyncMock(side_effect=error)))
    with TestClient(create_app(Settings(), service=service)) as client:
        response = client.post("/api/chat", json={"message": "VPN"})
        assert response.status_code == status
        assert "private-token" not in response.text


def test_remote_requires_resource_and_stable_cookie_secret():
    with pytest.raises(ValueError, match="AGENT_ENGINE_RESOURCE_NAME"):
        create_app(Settings(backend="remote", project="test-project"))
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        create_app(
            Settings(
                backend="remote",
                project="test-project",
                resource_name="projects/test/locations/us-central1/reasoningEngines/123",
            )
        )
