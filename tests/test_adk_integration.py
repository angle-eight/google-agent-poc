"""Exercise real ADK transfers, tools, sessions and serialization without Google calls."""

import cloudpickle
import pytest
import vertexai
from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.genai import types
from vertexai.agent_engines import AdkApp

from helpdesk.agent import create_agent
from helpdesk.service import ChatService


def call(name: str, **args) -> types.Part:
    return types.Part.from_function_call(name=name, args=args)


@pytest.mark.parametrize(
    "specialist,tool,query,document_id",
    [
        ("it_agent", "search_it_knowledge", "VPN", "IT-001"),
        ("hr_agent", "search_hr_knowledge", "有給", "HR-002"),
        ("accounting_agent", "search_accounting_knowledge", "出張", "FIN-002"),
    ],
)
async def test_adk_delegates_and_executes_scoped_search(
    scripted_team, specialist, tool, query, document_id
):
    agent, model = scripted_team(
        [
            call("transfer_to_agent", agent_name=specialist),
            call(tool, query=query),
            types.Part(text=f"規程を参照 [{document_id}]"),
        ]
    )
    service = ChatService(AdkApp(agent=agent))
    result = await service.chat("alice", query)
    assert result["agents_used"] == ["helpdesk_agent", specialist]
    assert result["sources"][0]["id"] == document_id
    assert set(result["tools_used"]) == {"transfer_to_agent", tool}
    assert not model.responses
    await service.delete_session("alice", result["session_id"])


async def test_adk_purchase_followup_preserves_context(scripted_team):
    agent, model = scripted_team(
        [
            call("transfer_to_agent", agent_name="it_agent"),
            call("search_it_knowledge", query="PC購入"),
            call("estimate_purchase", unit_price_yen=180_000, quantity=2),
            types.Part(text="税込360,000円、上長と部門責任者 [IT-002]"),
            call("estimate_purchase", unit_price_yen=180_000, quantity=1),
            types.Part(text="税込180,000円、上長のみ [IT-002]"),
        ]
    )
    service = ChatService(AdkApp(agent=agent))
    first = await service.chat("alice", "税込18万円のPCを2台購入したい")
    assert "360,000" in first["answer"]
    assert first["agents_used"] == ["helpdesk_agent", "it_agent"]
    second = await service.chat("alice", "1台なら？", first["session_id"])
    assert second["session_id"] == first["session_id"]
    assert "180,000" in second["answer"]
    assert second["agents_used"] == ["it_agent"]
    assert second["sources"][0]["id"] == "IT-002"
    assert model.context_sizes[-1] > model.context_sizes[0]
    assert not model.responses


async def test_adk_returns_to_router_when_topic_changes(scripted_team):
    agent, model = scripted_team(
        [
            call("transfer_to_agent", agent_name="it_agent"),
            call("search_it_knowledge", query="VPN"),
            types.Part(text="VPNの回答 [IT-001]"),
            call("transfer_to_agent", agent_name="helpdesk_agent"),
            call("transfer_to_agent", agent_name="hr_agent"),
            call("search_hr_knowledge", query="有給"),
            types.Part(text="有給休暇の回答 [HR-002]"),
            call("transfer_to_agent", agent_name="helpdesk_agent"),
            call("transfer_to_agent", agent_name="accounting_agent"),
            call("search_accounting_knowledge", query="出張"),
            types.Part(text="出張の回答 [FIN-002]"),
        ]
    )
    service = ChatService(AdkApp(agent=agent))
    first = await service.chat("alice", "VPNに接続できない")
    second = await service.chat("alice", "有給休暇の申請期限は？", first["session_id"])
    third = await service.chat("alice", "出張のホテルの上限は？", first["session_id"])
    assert second["agents_used"] == ["it_agent", "helpdesk_agent", "hr_agent"]
    assert third["agents_used"] == ["hr_agent", "helpdesk_agent", "accounting_agent"]
    assert first["sources"][0]["id"] == "IT-001"
    assert second["sources"][0]["id"] == "HR-002"
    assert third["sources"][0]["id"] == "FIN-002"
    assert third["session_id"] == second["session_id"] == first["session_id"]
    assert model.context_sizes[-1] > model.context_sizes[0]
    assert not model.responses


async def test_missing_policy_returns_no_sources(scripted_team):
    agent, _ = scripted_team(
        [
            call("transfer_to_agent", agent_name="hr_agent"),
            call("search_hr_knowledge", query="退職金"),
            types.Part(text="デモ規程には情報がありません。人事窓口に確認してください。"),
        ]
    )
    result = await ChatService(AdkApp(agent=agent)).chat("alice", "退職金の規程は？")
    assert result["sources"] == []
    assert result["agents_used"] == ["helpdesk_agent", "hr_agent"]


@pytest.mark.parametrize("specialist", ["it_agent", "hr_agent", "accounting_agent"])
async def test_google_search_runs_in_its_own_agent_without_mixing_builtin_and_function_tools(
    scripted_team, specialist
):
    agent, model = scripted_team(
        [
            call("transfer_to_agent", agent_name=specialist),
            call("google_search_agent", request="担当分野の最新の一般情報を検索してください"),
            types.Part(text="Google検索の結果 https://example.com/search-source"),
            types.Part(text="Webの一般情報です。出典: https://example.com/search-source"),
        ]
    )
    # The real built-in tool validates Gemini model names even with our offline model.
    model.model = "gemini-offline-test"
    result = await ChatService(AdkApp(agent=agent)).chat("alice", "Google検索で調べて")

    assert "https://example.com/search-source" in result["answer"]
    assert result["sources"] == []  # Public information is not a company policy.
    assert "google_search_agent" in result["tools_used"]
    assert result["agents_used"] == ["helpdesk_agent", specialist]
    assert not model.responses

    parent_config, search_config = model.request_configs[1:3]
    assert all(tool.google_search is None for tool in parent_config.tools)
    assert "google_search_agent" in {
        declaration.name
        for tool in parent_config.tools
        for declaration in tool.function_declarations or []
    }
    assert len(search_config.tools) == 1
    assert search_config.tools[0].google_search is not None
    assert not search_config.tools[0].function_declarations


def test_deployable_team_preserves_models_and_scoped_tools_after_pickling():
    vertexai.init(project="offline-test-project", location="us-central1")
    app = AdkApp(agent=create_agent(project="offline-test-project"))
    restored = cloudpickle.loads(cloudpickle.dumps(app))
    root = restored._tmpl_attrs["agent"]
    assert root.name == "helpdesk_agent"
    assert root.tools == []
    expected_tools = {
        "it_agent": {"search_it_knowledge", "estimate_purchase", "google_search"},
        "hr_agent": {"search_hr_knowledge", "google_search"},
        "accounting_agent": {"search_accounting_knowledge", "google_search"},
    }
    assert {child.name for child in root.sub_agents} == set(expected_tools)
    for member in [root, *root.sub_agents]:
        assert isinstance(member, Agent)
        assert isinstance(member.model, Gemini)
        assert member.model.client_kwargs is not None
        assert member.model.client_kwargs["location"] == "global"
        assert member.model.client_kwargs["project"] == "offline-test-project"
        if member is not root:
            assert member.parent_agent is root
            assert member.disallow_transfer_to_peers
            assert not member.disallow_transfer_to_parent
            assert {
                tool.name if isinstance(tool, GoogleSearchTool) else tool.__name__
                for tool in member.tools
            } == expected_tools[member.name]
            for tool in member.tools:
                if isinstance(tool, GoogleSearchTool):
                    assert tool.bypass_multi_tools_limit
