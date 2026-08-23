"""Tiny in-memory TTL cache.

Keeps the dashboard from re-shelling out to tools/show_*.py or re-reading
multi-MB state files on every UI poll. Not shared across processes — fine
for a single local uvicorn worker.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

from dashboard.backend import config

T = TypeVar("T")

_store: dict[str, tuple[float, object]] = {}


def get_or_compute(key: str, compute: Callable[[], T], ttl_seconds: float | None = None) -> T:
    ttl = config.CACHE_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    now = time.monotonic()
    cached = _store.get(key)
    if cached is not None:
        expires_at, value = cached
        if now < expires_at:
            return value  # type: ignore[return-value]

    value = compute()
    _store[key] = (now + ttl, value)
    return value


def clear() -> None:
    _store.clear()
