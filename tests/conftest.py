"""Use the real ADK with scripted model responses instead of Google requests."""

import pytest
import vertexai
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from helpdesk.agent import create_agent


class ScriptedModel(BaseLlm):
    responses: list[LlmResponse]
    context_sizes: list[int] = []
    request_configs: list[types.GenerateContentConfig] = []

    async def generate_content_async(self, llm_request, stream=False):
        self.context_sizes.append(len(llm_request.contents))
        self.request_configs.append(llm_request.config.model_copy(deep=True))
        yield self.responses.pop(0)


@pytest.fixture
def scripted_model():
    return ScriptedModel


@pytest.fixture
def scripted_team(scripted_model):
    def build(parts: list[types.Part]):
        vertexai.init(project="offline-test-project", location="us-central1")
        agent = create_agent(project="offline-test-project")
        model = scripted_model(
            model="offline-test",
            responses=[
                LlmResponse(content=types.Content(role="model", parts=[part])) for part in parts
            ],
        )
        for member in [agent, *agent.sub_agents]:
            member.model = model
        return agent, model

    return build
