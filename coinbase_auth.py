import os
import time
import secrets

import jwt
from cryptography.hazmat.primitives import serialization


_CACHED_PRIVATE_KEY = None


def _load_private_key_from_env():
    api_secret = os.getenv("COINBASE_API_SECRET")
    if not api_secret:
        raise ValueError("COINBASE_API_SECRET ontbreekt")

    clean_secret = api_secret.replace("\\n", "\n").strip()
    return serialization.load_pem_private_key(
        clean_secret.encode("utf-8"),
        password=None,
    )


def get_private_key():
    global _CACHED_PRIVATE_KEY
    if _CACHED_PRIVATE_KEY is None:
        _CACHED_PRIVATE_KEY = _load_private_key_from_env()
    return _CACHED_PRIVATE_KEY


def get_api_key() -> str:
    api_key = os.getenv("COINBASE_API_KEY", "").strip()
    if not api_key:
        raise ValueError("COINBASE_API_KEY ontbreekt")
    if not api_key.startswith("organizations/") or "/apiKeys/" not in api_key:
        raise ValueError("COINBASE_API_KEY heeft geen geldig CDP-formaat")
    return api_key


def generate_coinbase_rest_jwt(method: str, host: str, path: str) -> str:
    """
    Coinbase Advanced Trade REST JWT.
    uri claim: '{METHOD} {HOST}{PATH}'
    """
    method = method.upper().strip()
    if method not in {"GET", "POST", "PUT", "DELETE"}:
        raise ValueError(f"Ongeldige HTTP-methode: {method}")
    if not host:
        raise ValueError("host mag niet leeg zijn")
    if not path.startswith("/"):
        raise ValueError("path moet beginnen met '/'")

    api_key = get_api_key()
    private_key = get_private_key()
    now = int(time.time())

    payload = {
        "sub": api_key,
        "iss": "cdp",
        "nbf": now,
        "exp": now + 120,
        "uri": f"{method} {host}{path}",
    }
    headers = {
        "kid": api_key,
        "nonce": secrets.token_hex(16),
    }

    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
