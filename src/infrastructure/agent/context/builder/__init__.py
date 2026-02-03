"""
Builder module for context management.

Provides components for building LLM-ready messages:
- MessageBuilder: Convert domain messages to OpenAI format
- AttachmentInjector: Add attachment context to messages
"""

from src.infrastructure.agent.context.builder.attachment_injector import AttachmentInjector
from src.infrastructure.agent.context.builder.message_builder import MessageBuilder

__all__ = [
    "MessageBuilder",
    "AttachmentInjector",
]
