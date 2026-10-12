"""
backend/ai/exceptions.py
------------------------
Standard exception hierarchy for AI providers and centralized routing engine.
"""
from __future__ import annotations


class AIProviderError(Exception):
    """Base exception for all AI provider errors."""
    def __init__(self, message: str, provider: str = "unknown", status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code


class ProviderRateLimited(AIProviderError):
    """Raised on 429 Too Many Requests."""
    pass


class ProviderTimeout(AIProviderError):
    """Raised when provider request times out."""
    pass


class ProviderUnavailable(AIProviderError):
    """Raised on 5xx, network errors, or model unavailable/not found."""
    pass


class ProviderInvalidResponse(AIProviderError):
    """Raised when provider returns unparseable or empty/malformed response."""
    pass


class AIAuthenticationError(AIProviderError):
    """Raised on 401/403 or invalid API credentials."""
    pass


class AIModelNotFoundError(AIProviderError):
    """Raised when the requested model is not found or unsupported."""
    pass


AIRateLimitError = ProviderRateLimited


class AllProvidersFailedError(AIProviderError):
    """Raised when both primary and fallback providers have failed."""
    def __init__(
        self,
        message: str = "AI generation failed across configured providers.",
        errors: list[Exception] | None = None,
        diagnostics: list[str] | None = None,
    ):
        super().__init__(message)
        self.errors = errors or []
        self.diagnostics = diagnostics or []
