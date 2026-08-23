"""Coinbase CDP geeft private keys uit als ECDSA-PEM of als Ed25519-base64.

Deze tests gebruiken uitsluitend ter plekke gegenereerde sleutels; er komt
nooit een echte credential in de repository of in testoutput.
"""

import base64

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

import coinbase_auth

FAKE_API_KEY = (
    "organizations/00000000-0000-0000-0000-000000000000"
    "/apiKeys/11111111-1111-1111-1111-111111111111"
)


@pytest.fixture(autouse=True)
def _clear_key_cache():
    coinbase_auth._CACHED_PRIVATE_KEY = None
    yield
    coinbase_auth._CACHED_PRIVATE_KEY = None


def _ecdsa_pem() -> tuple[str, object]:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


def _ed25519_cdp_base64() -> tuple[str, object]:
    """Formaat zoals Coinbase het levert: base64(32-byte seed + 32-byte public)."""
    key = ed25519.Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(seed + public).decode(), key.public_key()


def _set_credentials(monkeypatch, secret: str) -> None:
    monkeypatch.setenv("COINBASE_API_KEY", FAKE_API_KEY)
    monkeypatch.setenv("COINBASE_API_SECRET", secret)


@pytest.mark.parametrize(
    "make_key, expected_algorithm",
    [
        (_ecdsa_pem, "ES256"),
        (_ed25519_cdp_base64, "EdDSA"),
    ],
    ids=["ecdsa_pem", "ed25519_cdp_base64"],
)
def test_jwt_is_signed_and_verifiable_for_both_key_types(
    monkeypatch, make_key, expected_algorithm
):
    secret, public_key = make_key()
    _set_credentials(monkeypatch, secret)

    token = coinbase_auth.generate_coinbase_rest_jwt(
        "GET", "api.coinbase.com", "/api/v3/brokerage/accounts"
    )

    header = jwt.get_unverified_header(token)
    assert header["alg"] == expected_algorithm
    assert header["kid"] == FAKE_API_KEY
    assert header["nonce"]

    claims = jwt.decode(
        token,
        public_key,
        algorithms=[expected_algorithm],
        options={"verify_aud": False},
    )
    assert claims["sub"] == FAKE_API_KEY
    assert claims["iss"] == "cdp"
    assert claims["uri"] == "GET api.coinbase.com/api/v3/brokerage/accounts"


def test_pem_with_escaped_newlines_is_accepted(monkeypatch):
    """.env kan het PEM-blok op één regel met literal \\n bevatten."""
    pem, public_key = _ecdsa_pem()
    _set_credentials(monkeypatch, pem.replace("\n", "\\n"))

    token = coinbase_auth.generate_coinbase_rest_jwt(
        "GET", "api.coinbase.com", "/api/v3/brokerage/accounts"
    )

    jwt.decode(token, public_key, algorithms=["ES256"], options={"verify_aud": False})


def test_missing_secret_reports_clearly(monkeypatch):
    monkeypatch.setenv("COINBASE_API_KEY", FAKE_API_KEY)
    monkeypatch.delenv("COINBASE_API_SECRET", raising=False)

    with pytest.raises(ValueError, match="COINBASE_API_SECRET ontbreekt"):
        coinbase_auth.generate_coinbase_rest_jwt("GET", "api.coinbase.com", "/x")


def test_unrecognised_secret_names_both_supported_formats(monkeypatch):
    _set_credentials(monkeypatch, "dit-is-geen-sleutel")

    with pytest.raises(ValueError, match="onbekend formaat") as excinfo:
        coinbase_auth.generate_coinbase_rest_jwt("GET", "api.coinbase.com", "/x")

    message = str(excinfo.value)
    assert "PEM" in message
    assert "Ed25519" in message


def test_truncated_pem_reports_pem_specific_hint(monkeypatch):
    _set_credentials(monkeypatch, "-----BEGIN EC PRIVATE KEY-----\nnonsense\n")

    with pytest.raises(ValueError, match="PEM-sleutel maar kon niet worden gelezen"):
        coinbase_auth.generate_coinbase_rest_jwt("GET", "api.coinbase.com", "/x")


def test_error_message_never_contains_the_secret(monkeypatch):
    marker = "SECRET-MARKER-SHOULD-NOT-LEAK"
    _set_credentials(monkeypatch, marker)

    with pytest.raises(ValueError) as excinfo:
        coinbase_auth.generate_coinbase_rest_jwt("GET", "api.coinbase.com", "/x")

    assert marker not in str(excinfo.value)
