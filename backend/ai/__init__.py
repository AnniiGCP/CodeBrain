"""
backend/ai package
"""
from ai.config import get_model_for_task, getModelForTask
from ai.router import (
    route_chat,
    route_reasoning,
    route_vision,
    route_transcribe,
    route_tts,
    generate_text,
    generate_code,
)

__all__ = [
    "route_chat",
    "route_reasoning",
    "route_vision",
    "route_transcribe",
    "route_tts",
    "generate_text",
    "generate_code",
    "get_model_for_task",
    "getModelForTask",
]
