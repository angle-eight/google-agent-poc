"""Give the SDK's lazy public exports concrete types for type checkers."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentplatform._genai.client import Client as Client
    from agentplatform._genai.types import AgentEngineConfig as AgentEngineConfig
else:
    from agentplatform import Client as Client
    from agentplatform import types

    AgentEngineConfig = types.AgentEngineConfig
