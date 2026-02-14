"""LLM module for memstack-agent.

Provides unified LLM client abstraction with:
- Protocol-based client interface
- Immutable types (Message, ChatResponse, StreamChunk, etc.)
- Configuration with preset factories
- LiteLLM adapter for 100+ provider support

Example:
    from memstack_agent.llm import (
        LLMConfig,
        LiteLLMAdapter,
        Message,
        create_llm_client,
    )

    # Using factory function
    client = create_llm_client("openai/gpt-4", api_key="sk-...")

    # Or with preset config
    config = openai_config(model="gpt-4-turbo", api_key="sk-...")
    client = LiteLLMAdapter(config)

    # Generate response
    response = await client.generate([
        Message.system("You are a helpful assistant."),
        Message.user("Hello!"),
    ])
    print(response.content)

    # Stream response
    async for chunk in client.stream([Message.user("Tell me a story.")]):
        print(chunk.delta, end="")
"""

from memstack_agent.llm.config import (
    LLMConfig,
    anthropic_config,
    deepseek_config,
    gemini_config,
    openai_config,
)
from memstack_agent.llm.litellm_adapter import LiteLLMAdapter, create_llm_client
from memstack_agent.llm.protocol import LLMClient, LLMClientSync
from memstack_agent.llm.types import (
    ChatResponse,
    Message,
    MessageRole,
    StreamChunk,
    ToolCall,
    Usage,
)

__all__ = [
    # Types
    "Message",
    "MessageRole",
    "ToolCall",
    "Usage",
    "ChatResponse",
    "StreamChunk",
    # Config
    "LLMConfig",
    "anthropic_config",
    "openai_config",
    "gemini_config",
    "deepseek_config",
    # Protocol
    "LLMClient",
    "LLMClientSync",
    # Adapter
    "LiteLLMAdapter",
    "create_llm_client",
]
