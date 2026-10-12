"""
backend/ai/providers/base.py
----------------------------
Abstract base class for all AI Providers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class AIProvider(ABC):
    """Abstract interface for LLM / Vision / Audio providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name identifier ('groq' or 'nvidia')."""
        pass

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        response_format: dict | None = None,
    ) -> str:
        """Synchronous non-streaming chat completion."""
        pass

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """Asynchronous streaming chat completion yielding tokens."""
        pass

    @abstractmethod
    async def stream_vision(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[str, None]:
        """Asynchronous streaming vision completion."""
        pass

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        model: str,
        filename: str = "audio.webm",
    ) -> str:
        """Audio speech-to-text transcription."""
        pass

    @abstractmethod
    async def tts(
        self,
        text: str,
        model: str,
    ) -> bytes:
        """Text-to-speech audio synthesis."""
        pass
