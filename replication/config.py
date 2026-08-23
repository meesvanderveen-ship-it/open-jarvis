from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _load_env() -> None:
    if os.getenv("BOT_CONFIG_SKIP_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}:
        return

    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        load_dotenv(override=True)


_load_env()


def _get_required(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} ontbreekt")
    return value.strip()


def _get_optional(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return int(raw.strip())


def get_bool_env(name: str, default: bool = False) -> bool:
    return _get_bool(name, default)


def get_optional_env(name: str, default: str = "") -> str:
    return _get_optional(name, default)


@dataclass
class ReplicationConfig:
    enabled: bool
    replica_url: str
    shared_hmac_secret: str
    source_bot_name: str
    timeout_seconds: int
    verify_tls: bool

    @classmethod
    def from_env(cls) -> "ReplicationConfig":
        enabled = _get_bool("REPLICATION_ENABLED", False)

        replica_url = _get_optional("REPLICA_URL", "")
        shared_hmac_secret = _get_optional("REPLICA_SHARED_HMAC_SECRET", "")
        source_bot_name = _get_optional("REPLICATION_SOURCE_BOT", "SERVER1-MASTER")
        timeout_seconds = _get_int("REPLICATION_TIMEOUT_SECONDS", 5)
        verify_tls = _get_bool("REPLICATION_VERIFY_TLS", True)

        if enabled:
            if not replica_url:
                raise ValueError("REPLICA_URL ontbreekt terwijl REPLICATION_ENABLED=true")
            if not shared_hmac_secret:
                raise ValueError("REPLICA_SHARED_HMAC_SECRET ontbreekt terwijl REPLICATION_ENABLED=true")

        return cls(
            enabled=enabled,
            replica_url=replica_url.rstrip("/"),
            shared_hmac_secret=shared_hmac_secret,
            source_bot_name=source_bot_name,
            timeout_seconds=timeout_seconds,
            verify_tls=verify_tls,
        )
