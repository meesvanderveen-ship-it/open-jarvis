"""Recursive secret redaction, applied to every API response.

This is defense-in-depth: the readers in services/ are not expected to ever
surface real credentials (the bot keeps those in `.env`, which this backend
never opens), but report/log/state JSON is free-form and operator-written,
so we scrub it unconditionally rather than trust each source.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# Keys that should always have their value replaced, regardless of shape.
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|passwd|private[_-]?key|credential|"
    r"authorization|bearer)"
)

# Value-shaped secrets that can show up embedded in free-form strings
# (report markdown, env-diff snippets, raw log lines) even under an
# innocuous-looking key.
_VALUE_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"),  # Anthropic
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # OpenAI-style
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.=]{10,}"),
    re.compile(r"[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}"),  # JWT-shaped
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),  # long hex tokens
]


def _scrub_string(value: str) -> str:
    scrubbed = value
    for pattern in _VALUE_PATTERNS:
        scrubbed = pattern.sub(REDACTED, scrubbed)
    return scrubbed


def redact(value: Any, *, _key: str | None = None) -> Any:
    """Recursively redact secrets from dict/list/str structures.

    Any dict key matching a secret-shaped name has its value replaced
    outright. Every remaining string is also value-scanned for
    secret-shaped substrings (key prefixes, JWTs, long hex tokens).
    """
    if _key is not None and _SECRET_KEY_PATTERN.search(_key):
        return REDACTED

    if isinstance(value, dict):
        return {k: redact(v, _key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _scrub_string(value)
    return value
