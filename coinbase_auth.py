import base64
import binascii
import os
import time
import secrets

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519


_CACHED_PRIVATE_KEY = None

# Coinbase CDP geeft de private key in twee vormen uit:
# - ECDSA (P-256): PEM-blok, ondertekend met ES256
# - Ed25519: base64 van 64 bytes (32 seed + 32 public), ondertekend met EdDSA
_ED25519_RAW_LEN = 32
_ED25519_SEED_PLUS_PUBLIC_LEN = 64


def _load_ed25519_from_base64(clean_secret: str):
    """
    Laad een Ed25519-sleutel uit het base64-formaat dat Coinbase CDP uitgeeft.

    Retourneert None als de tekst geen bruikbare base64-sleutel is, zodat de
    aanroeper een foutmelding kan geven die beide sleuteltypes noemt.
    """
    try:
        raw = base64.b64decode(clean_secret, validate=True)
    except (binascii.Error, ValueError):
        return None

    if len(raw) == _ED25519_SEED_PLUS_PUBLIC_LEN:
        raw = raw[:_ED25519_RAW_LEN]
    elif len(raw) != _ED25519_RAW_LEN:
        return None

    return ed25519.Ed25519PrivateKey.from_private_bytes(raw)


def _load_private_key_from_env():
    api_secret = os.getenv("COINBASE_API_SECRET")
    if not api_secret:
        raise ValueError("COINBASE_API_SECRET ontbreekt")

    clean_secret = api_secret.replace("\\n", "\n").strip()

    if "-----BEGIN" in clean_secret:
        try:
            return serialization.load_pem_private_key(
                clean_secret.encode("utf-8"),
                password=None,
            )
        except ValueError as exc:
            raise ValueError(
                "COINBASE_API_SECRET lijkt een PEM-sleutel maar kon niet worden "
                "gelezen. Controleer of het volledige BEGIN/END-blok in .env staat "
                "en of de regeleindes als \\n zijn geschreven."
            ) from exc

    key = _load_ed25519_from_base64(clean_secret)
    if key is not None:
        return key

    raise ValueError(
        "COINBASE_API_SECRET heeft een onbekend formaat. Verwacht ofwel een "
        "ECDSA-sleutel als PEM-blok (-----BEGIN EC PRIVATE KEY-----...), ofwel "
        "een Ed25519-sleutel als base64-tekst, precies zoals Coinbase die in het "
        "gedownloade JSON-bestand onder 'privateKey' zet."
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


def _jwt_algorithm_for(private_key) -> str:
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        return "EdDSA"
    if isinstance(private_key, ec.EllipticCurvePrivateKey):
        return "ES256"
    raise ValueError(
        f"Niet-ondersteund sleuteltype voor Coinbase JWT: {type(private_key).__name__}. "
        "Coinbase CDP ondersteunt ECDSA (P-256) en Ed25519."
    )


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
    algorithm = _jwt_algorithm_for(private_key)
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

    return jwt.encode(payload, private_key, algorithm=algorithm, headers=headers)
