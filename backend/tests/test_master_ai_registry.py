"""
Tests for Master Model Selector & AI Provider Registry Fix.
Verifies end-to-end model normalization, provider separation, routing, and security.
"""

import os
import sys
from pathlib import Path
import pytest

backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from fastapi.testclient import TestClient
from main import app
from ai.registry import (
    get_master_ai_registry,
    normalize_model,
    NVIDIA_UPSTREAM_MAP,
    DISPLAY_NAME_MAP,
)
from ai.providers.nvidia_provider import NvidiaProvider
from ai.providers.anthropic_compatible_provider import AnthropicCompatibleProvider


def test_master_ai_registry_endpoint():
    client = TestClient(app)
    resp = client.get("/ai/models")
    assert resp.status_code == 200
    data = resp.json()

    assert "providers" in data
    assert "preferredProvider" in data
    assert "preferredModel" in data

    providers_list = data["providers"]
    provider_ids = [p["id"] for p in providers_list]
    assert "nvidia" in provider_ids
    assert "groq" in provider_ids
    assert "openai-compatible" in provider_ids
    assert "anthropic-compatible" in provider_ids

    # Neither Anthropic catalog nor OpenRouter must appear in provider catalog
    assert "anthropic" not in provider_ids
    assert "openrouter" not in provider_ids

    providers = data.get("providers_map") or {p["id"]: p for p in providers_list}

    # Verify NVIDIA models
    nvidia = providers["nvidia"]
    assert nvidia["id"] == "nvidia"
    assert nvidia["displayName"] == "NVIDIA"
    nvidia_models = {m["id"]: m for m in nvidia["models"]}

    # Core 4 models + vision
    assert "glm-5-3" in nvidia_models
    assert nvidia_models["glm-5-3"]["displayName"] == "GLM 5.3"
    assert nvidia_models["glm-5-3"]["providerId"] == "nvidia"
    assert nvidia_models["glm-5-3"]["providerDisplayName"] == "NVIDIA"

    assert "glm-5-3-flash" in nvidia_models
    assert nvidia_models["glm-5-3-flash"]["displayName"] == "GLM 5.3 Flash"

    assert "deepseek-v4.1-flash" in nvidia_models
    assert nvidia_models["deepseek-v4.1-flash"]["displayName"] == "DeepSeek V4.1 Flash"

    assert "nemotron-3-ultra-550b-a55b" in nvidia_models
    assert nvidia_models["nemotron-3-ultra-550b-a55b"]["displayName"] == "Nemotron 3 Ultra"

    # Verify Groq models (dynamically discovered or fallback cache)
    groq = providers["groq"]
    assert groq["id"] == "groq"
    assert groq["displayName"] == "Groq"
    assert len(groq["models"]) > 0
    assert all(m["providerId"] == "groq" for m in groq["models"])
    groq_model_ids = [m["id"] for m in groq["models"]]
    assert any("llama" in m_id or "gpt-oss" in m_id or "qwen" in m_id for m_id in groq_model_ids)

    # Compatible providers must initially have NO default models
    openai_compat = providers["openai-compatible"]
    assert openai_compat["id"] == "openai-compatible"
    assert len(openai_compat["models"]) == 0

    anthropic_compat = providers["anthropic-compatible"]
    assert anthropic_compat["id"] == "anthropic-compatible"
    assert len(anthropic_compat["models"]) == 0


def test_nvidia_upstream_resolution():
    provider = NvidiaProvider()
    assert provider._resolve_model("glm-5-3") == "z-ai/glm-5.3"
    assert provider._resolve_model("glm-5-3-flash") == "z-ai/glm-5.3-flash"
    assert provider._resolve_model("deepseek-v4.1-flash") == "deepseek-ai/deepseek-v4.1-flash"
    assert provider._resolve_model("nemotron-3-ultra-550b-a55b") == "nvidia/nemotron-3-ultra-550b-a55b"
    assert provider._resolve_model("meta/llama-3.2-11b-vision-instruct") == "meta/llama-3.2-11b-vision-instruct"


def test_model_normalization_layer():
    norm = normalize_model(
        raw="deepseek-v4.1-flash",
        provider_id="nvidia",
        provider_display_name="NVIDIA",
        default_badge="CODING / REASONING",
        default_capabilities=["chat", "code", "reasoning"],
        default_context=131072,
    )
    assert norm["id"] == "deepseek-v4.1-flash"
    assert norm["displayName"] == "DeepSeek V4.1 Flash"
    assert norm["providerId"] == "nvidia"
    assert norm["providerDisplayName"] == "NVIDIA"
    assert norm["badge"] == "CODING / REASONING"
    assert norm["status"] == "AVAILABLE"


def test_anthropic_compatible_provider_structure():
    provider = AnthropicCompatibleProvider()
    assert provider.name == "anthropic-compatible"
    assert provider.is_available is False  # without credentials configured
