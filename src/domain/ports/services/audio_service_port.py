from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, BinaryIO


class ASRServicePort(ABC):
    """Port for Automatic Speech Recognition (Audio to Text) service."""
    
    @abstractmethod
    async def transcribe(
        self, 
        audio_file: BinaryIO, 
        language: str = "zh-CN",
        options: dict[str, Any] | None = None
    ) -> str:
        """Transcribe audio file to text."""

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        language: str = "zh-CN",
        options: dict[str, Any] | None = None
    ) -> AsyncGenerator[str, None]:
        """Transcribe audio stream to text."""

class TTSServicePort(ABC):
    """Port for Text-to-Speech (Text to Audio) service."""
    
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice_type: str | None = None,
        options: dict[str, Any] | None = None
    ) -> bytes:
        """Synthesize text to audio bytes."""

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        voice_type: str | None = None,
        options: dict[str, Any] | None = None
    ) -> AsyncGenerator[bytes, None]:
        """Synthesize text to audio stream."""
