"""
voice/transcribe.py — Voice transcription helper.
Routes audio speech-to-text through the centralized AI router (backend/ai/router.py).
"""
from __future__ import annotations

from ai.router import route_transcribe


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """
    Send audio bytes to the centralized AI router and return the transcribed text.

    Args:
        audio_bytes: Raw audio file content (webm, mp4, wav, ogg, etc.).
        filename:    Original filename used to infer MIME type for the API.

    Returns:
        Transcribed text string.
    """
    return await route_transcribe(audio_bytes=audio_bytes, filename=filename)
