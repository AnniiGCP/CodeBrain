"""
backend/docgen/secret_redactor.py
---------------------------------
Automated scanning and redaction of credentials, API keys, tokens, and sensitive secrets
from repository content before sending to AI models, generating documentation, or producing exports.
"""
from __future__ import annotations

import re
from typing import Pattern, List, Tuple

# Compiled regex patterns for detecting secrets
_SECRET_PATTERNS: List[Tuple[Pattern[str], str]] = [
    # Private keys
    (re.compile(r'-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----'), '<REDACTED_PRIVATE_KEY>'),
    # Database connection strings with credentials: postgres://user:password@host:port/db
    (re.compile(r'(?:postgres|postgresql|mysql|mongodb|redis|amqp|mssql)://(?P<user>[^:\s/@]+):(?P<pass>[^@\s/]+)@', re.IGNORECASE), r'\g<1>://\g<user>:<REDACTED_SECRET>@'),
    # Generic API Keys / Tokens in assignment: api_key = "...", token = "..."
    (re.compile(r'(?i)\b(?:api[_-]?key|secret[_-]?key|auth[_-]?token|access[_-]?token|bearer[_-]?token|session[_-]?secret|jwt[_-]?secret|password|passwd|client[_-]?secret)\s*[:=]\s*["\']([^"\'\s]{8,})["\']'), r' = "<REDACTED_SECRET>"'),
    # AWS Access Keys
    (re.compile(r'\b(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b'), '<REDACTED_AWS_KEY>'),
    # GitHub Tokens
    (re.compile(r'\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b'), '<REDACTED_GITHUB_TOKEN>'),
    # OpenAI / Anthropic / HuggingFace style keys
    (re.compile(r'\bsk-(?:proj-|live-)?[a-zA-Z0-9_\-]{20,}\b'), '<REDACTED_API_KEY>'),
    (re.compile(r'\bhf_[a-zA-Z0-9]{34,}\b'), '<REDACTED_API_KEY>'),
    # NVIDIA API Keys
    (re.compile(r'\bnvapi-[A-Za-z0-9_\-]{30,}\b'), '<REDACTED_NVIDIA_KEY>'),
    # Google API Keys
    (re.compile(r'\bAIza[0-9A-Za-z-_]{35}\b'), '<REDACTED_GOOGLE_KEY>'),
    # Generic high entropy hex/base64 JWTs
    (re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'), '<REDACTED_JWT_TOKEN>'),
]

# Patterns for internal AI model, provider, and fallback runtime diagnostics
_AI_PROVIDER_PATTERNS: List[Pattern[str]] = [
    re.compile(r'\*?\(?Using\s+(?:Groq|NVIDIA|OpenAI|Anthropic|Qwen|Ollama|DeepSeek)\s+fallback(?:\s+on\s+`?[^`\n\)]+`?)?\)?\*?\n*', re.IGNORECASE),
    re.compile(r'(?i)^\s*\*?(?:Generated\s+by\s+(?:NVIDIA|Groq|OpenAI|Anthropic|Qwen|Ollama|DeepSeek)[\w\s/.-]*|AI\s+Provider\s*:\s*.*)\*?\s*$\n?', re.MULTILINE),
    re.compile(r'(?i)\bUsing\s+Groq\s+fallback\s+on\s+`?[A-Za-z0-9_\-\.\/]+`?', re.IGNORECASE),
]


def redact_secrets(text: str) -> str:
    """
    Scans input text for sensitive credentials and replaces them with redacted placeholders.
    Also strips all internal AI model, provider, or fallback diagnostic messages
    so that user-facing documentation is professionally authored.
    """
    if not text:
        return ""
    redacted = text
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    for pattern in _AI_PROVIDER_PATTERNS:
        redacted = pattern.sub('', redacted)
    return redacted


def sanitize_host_paths(text: str) -> str:
    r"""
    Sanitize developer host user profiles and personal paths
    (e.g. C:\Users\Name or /home/username) from diagnostic output.
    """
    if not text:
        return ""
    sanitized = re.sub(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s\r\n\"'\)]+", "<HOST_USER_DIR>", text)
    sanitized = re.sub(r"/(?:home|Users)/[^/\s\r\n\"'\)]+", "<HOST_USER_DIR>", sanitized)
    return sanitized


# Alias for backward-compatibility with other modules
sanitize_sensitive_text = redact_secrets

