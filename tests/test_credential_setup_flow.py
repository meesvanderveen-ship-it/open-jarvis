"""Setup-, validatie- en startup-flow voor OpenAI- en Coinbase-credentials.

Alle sleutels in dit bestand worden ter plekke gegenereerd of zijn duidelijk
nepwaarden. Er komt geen echte credential in de repository, en geen enkele
test doet een echte API-aanroep: het netwerk wordt overal vervangen door een
stub.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

import coinbase_auth
from bot import env_file
from bot.credential_status import (
    CONFIGURATION_ERROR,
    READY,
    SETUP_REQUIRED,
    STATUS_INVALID,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_UNKNOWN,
    check_coinbase,
    check_openai,
    overall_state,
    status_report,
    verify_coinbase,
    verify_openai,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FAKE_COINBASE_KEY = (
    "organizations/00000000-0000-0000-0000-000000000000"
    "/apiKeys/11111111-1111-1111-1111-111111111111"
)
FAKE_OPENAI_KEY = "sk-test-not-a-real-key-000000000000000000"


@pytest.fixture(autouse=True)
def _clear_auth_cache():
    coinbase_auth._CACHED_PRIVATE_KEY = None
    yield
    coinbase_auth._CACHED_PRIVATE_KEY = None


def ecdsa_pem() -> str:
    return (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )


def ed25519_base64() -> str:
    key = ed25519.Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return base64.b64encode(seed + public).decode()


def valid_env(secret: str | None = None) -> dict[str, str]:
    return {
        "OPENAI_API_KEY": FAKE_OPENAI_KEY,
        "COINBASE_API_KEY": FAKE_COINBASE_KEY,
        "COINBASE_API_SECRET": secret or ecdsa_pem(),
    }


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _Session:
    """Minimale requests-vervanger; bewijst tevens dat er geen echt verkeer is."""

    def __init__(self, status_code: int = 200, raises: Exception | None = None):
        self.status_code = status_code
        self.raises = raises
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers or {}))
        if self.raises:
            raise self.raises
        return _Response(self.status_code)


# ---------------------------------------------------------------- OpenAI


def test_openai_key_missing_is_reported_clearly():
    check = check_openai({})
    assert check.status == STATUS_MISSING
    assert "ontbreekt" in check.summary
    assert "setup_wizard" in check.detail


def test_openai_key_present_is_accepted():
    check = check_openai({"OPENAI_API_KEY": FAKE_OPENAI_KEY})
    assert check.status == STATUS_OK
    assert check.ok


def test_openai_placeholder_from_env_example_is_rejected():
    """cp .env.example .env zonder bewerken mag niet als geconfigureerd tellen."""
    check = check_openai({"OPENAI_API_KEY": "your_openai_api_key_here"})
    assert check.status == STATUS_INVALID
    assert "voorbeeldwaarde" in check.summary


def test_openai_authentication_success(monkeypatch):
    session = _Session(status_code=200)
    check = verify_openai({"OPENAI_API_KEY": FAKE_OPENAI_KEY}, session=session)

    assert check.status == STATUS_OK
    assert "geslaagd" in check.summary
    url, headers = session.calls[0]
    assert url == "https://api.openai.com/v1/models"
    assert headers["Authorization"] == f"Bearer {FAKE_OPENAI_KEY}"


def test_openai_invalid_credentials_are_reported_as_invalid():
    check = verify_openai({"OPENAI_API_KEY": FAKE_OPENAI_KEY}, session=_Session(status_code=401))
    assert check.status == STATUS_INVALID
    assert "mislukt" in check.summary


def test_openai_network_failure_is_not_blamed_on_the_key():
    session = _Session(raises=OSError("dns failure"))
    check = verify_openai({"OPENAI_API_KEY": FAKE_OPENAI_KEY}, session=session)

    assert check.status == STATUS_UNKNOWN
    assert "netwerkprobleem" in check.detail


def test_openai_verification_is_skipped_when_key_absent():
    session = _Session()
    check = verify_openai({}, session=session)

    assert check.status == STATUS_MISSING
    assert session.calls == [], "geen request zonder sleutel"


# -------------------------------------------------------------- Coinbase


@pytest.mark.parametrize(
    "make_secret, expected_type, expected_alg",
    [
        (ecdsa_pem, "ECDSA (P-256)", "ES256"),
        (ed25519_base64, "Ed25519", "EdDSA"),
    ],
    ids=["ecdsa", "ed25519"],
)
def test_coinbase_accepts_both_key_types(make_secret, expected_type, expected_alg):
    check = check_coinbase(valid_env(make_secret()))

    assert check.status == STATUS_OK
    assert check.facts["key_type"] == expected_type
    assert check.facts["jwt_algorithm"] == expected_alg


def test_coinbase_missing_credentials_names_what_is_missing():
    check = check_coinbase({"COINBASE_API_KEY": FAKE_COINBASE_KEY})

    assert check.status == STATUS_MISSING
    assert check.facts["missing"] == ["COINBASE_API_SECRET"]


def test_coinbase_invalid_secret_is_rejected_before_startup():
    env = valid_env()
    env["COINBASE_API_SECRET"] = "not-a-key-at-all!!"

    check = check_coinbase(env)
    assert check.status == STATUS_INVALID
    assert "private key" in check.summary.lower()


def test_coinbase_malformed_api_key_is_rejected():
    env = valid_env()
    env["COINBASE_API_KEY"] = "just-some-string"

    check = check_coinbase(env)
    assert check.status == STATUS_INVALID
    assert "formaat" in check.summary


def test_coinbase_check_does_not_leak_the_secret():
    env = valid_env()
    env["COINBASE_API_SECRET"] = "MARKER-SECRET-MUST-NOT-APPEAR"

    check = check_coinbase(env)
    assert "MARKER-SECRET-MUST-NOT-APPEAR" not in json.dumps(check.as_dict())


def test_coinbase_check_restores_the_process_environment():
    """De controle mag os.environ niet blijvend wijzigen."""
    os.environ["COINBASE_API_KEY"] = "sentinel-key"
    os.environ.pop("COINBASE_API_SECRET", None)
    try:
        check_coinbase(valid_env())
        assert os.environ["COINBASE_API_KEY"] == "sentinel-key"
        assert "COINBASE_API_SECRET" not in os.environ
    finally:
        os.environ.pop("COINBASE_API_KEY", None)


class _FakeCoinbaseClient:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload if payload is not None else {"accounts": [{"uuid": "a"}]}
        self.error = error
        self.calls = 0

    def get_accounts(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


def test_coinbase_authentication_success_uses_read_only_call():
    client = _FakeCoinbaseClient()
    check = verify_coinbase(valid_env(), client=client)

    assert check.status == STATUS_OK
    assert check.facts["accounts_visible"] == 1
    assert client.calls == 1


def test_coinbase_rejected_credentials_are_reported_as_invalid():
    client = _FakeCoinbaseClient(error=RuntimeError("Coinbase request failed: 401 Unauthorized"))
    check = verify_coinbase(valid_env(), client=client)

    assert check.status == STATUS_INVALID
    assert "mislukt" in check.summary


def test_coinbase_network_failure_is_not_blamed_on_credentials():
    client = _FakeCoinbaseClient(error=OSError("connection reset"))
    check = verify_coinbase(valid_env(), client=client)

    assert check.status == STATUS_UNKNOWN
    assert "netwerkprobleem" in check.detail


# ------------------------------------------------------- overall state


def test_overall_state_ready_when_both_configured():
    assert overall_state([check_openai(valid_env()), check_coinbase(valid_env())]) == READY


def test_overall_state_setup_required_when_nothing_configured():
    assert overall_state([check_openai({}), check_coinbase({})]) == SETUP_REQUIRED


def test_overall_state_configuration_error_beats_setup_required():
    env = {"OPENAI_API_KEY": "your_openai_api_key_here"}
    checks = [check_openai(env), check_coinbase(env)]
    assert overall_state(checks) == CONFIGURATION_ERROR


def test_status_report_is_json_serialisable_and_secret_free():
    env = valid_env()
    report = status_report(env, online=False)

    encoded = json.dumps(report)
    assert report["state"] == READY
    assert env["COINBASE_API_SECRET"] not in encoded
    assert FAKE_OPENAI_KEY not in encoded


# --------------------------------------------------- credential storage


def test_env_file_roundtrip_persists_values(tmp_path):
    target = tmp_path / ".env"
    secret = ecdsa_pem()

    env_file.write_env_values(
        {"OPENAI_API_KEY": FAKE_OPENAI_KEY, "COINBASE_API_SECRET": secret}, target
    )

    loaded = env_file.read_env(target)
    assert loaded["OPENAI_API_KEY"] == FAKE_OPENAI_KEY
    assert loaded["COINBASE_API_SECRET"].replace("\\n", "\n") == secret


def test_env_file_is_written_owner_only(tmp_path):
    target = tmp_path / ".env"
    env_file.write_env_values({"OPENAI_API_KEY": FAKE_OPENAI_KEY}, target)

    assert env_file.permissions_are_owner_only(target)
    assert target.stat().st_mode & 0o077 == 0


def test_env_file_preserves_comments_and_other_keys(tmp_path):
    target = tmp_path / ".env"
    target.write_text(
        "# leading comment\nEXECUTION_MODE=paper\nOPENAI_API_KEY=old\n\n# trailing\n",
        encoding="utf-8",
    )

    env_file.write_env_values({"OPENAI_API_KEY": "new"}, target)
    content = target.read_text(encoding="utf-8")

    assert "# leading comment" in content
    assert "EXECUTION_MODE=paper" in content
    assert "# trailing" in content
    assert "OPENAI_API_KEY=new" in content
    assert "OPENAI_API_KEY=old" not in content


def test_env_file_appends_keys_that_do_not_exist_yet(tmp_path):
    target = tmp_path / ".env"
    target.write_text("EXECUTION_MODE=paper\n", encoding="utf-8")

    env_file.write_env_values({"COINBASE_API_KEY": FAKE_COINBASE_KEY}, target)

    assert env_file.read_env(target)["COINBASE_API_KEY"] == FAKE_COINBASE_KEY


def test_env_file_quotes_values_containing_hash(tmp_path):
    target = tmp_path / ".env"
    env_file.write_env_values({"SOME_KEY": "value #with hash"}, target)

    assert env_file.read_env(target)["SOME_KEY"] == "value #with hash"


def test_ensure_env_from_example_never_overwrites(tmp_path):
    target = tmp_path / ".env"
    target.write_text("OPENAI_API_KEY=keep-me\n", encoding="utf-8")

    _, created = env_file.ensure_env_from_example(target)

    assert created is False
    assert env_file.read_env(target)["OPENAI_API_KEY"] == "keep-me"


# ------------------------------------------------------------- git hygiene


def test_env_is_ignored_by_git():
    result = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, ".env moet door .gitignore worden genegeerd"


def test_env_example_contains_only_placeholders():
    content = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "BEGIN EC PRIVATE KEY-----\\n<your" in content
    assert "your_openai_api_key_here" in content
    # Een echte OpenAI-sleutel is sk- gevolgd door een lange body.
    assert not re.search(r"sk-[A-Za-z0-9]{20,}", content)
    # En een echte CDP-key-naam draagt een echte UUID, geen <placeholder>.
    assert not re.search(r"organizations/[0-9a-f]{8}-[0-9a-f]{4}", content)


# ------------------------------------------------------- startup preflight


def _run_bot(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    child_env = {
        **os.environ,
        "BOT_CONFIG_SKIP_DOTENV": "true",
        "PYTHONPATH": str(PROJECT_ROOT),
        **env,
    }
    for key in ("OPENAI_API_KEY", "COINBASE_API_KEY", "COINBASE_API_SECRET"):
        if key not in env:
            child_env.pop(key, None)

    return subprocess.run(
        [sys.executable, "run_trader_loop.py", *args],
        cwd=PROJECT_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_startup_without_credentials_fails_with_a_readable_message():
    """Echte start (geen diagnostic): de preflight stopt vóór de engineloop."""
    result = _run_bot({})
    output = result.stdout + result.stderr

    assert result.returncode == 4, "preflight moet blokkeren, niet doorstarten"
    assert "SETUP REQUIRED" in output
    assert "setup_wizard" in output
    assert "Traceback" not in output


def test_startup_with_invalid_coinbase_secret_is_blocked():
    """Vóór de preflight startte de bot hier gewoon op en faalde pas veel later."""
    result = _run_bot(
        {
            "OPENAI_API_KEY": FAKE_OPENAI_KEY,
            "COINBASE_API_KEY": FAKE_COINBASE_KEY,
            "COINBASE_API_SECRET": "invalid-secret-value",
        },
    )
    output = result.stdout + result.stderr

    assert result.returncode == 4
    assert "CONFIGURATION ERROR" in output
    assert "invalid-secret-value" not in output, "secret mag niet in de uitvoer staan"


def test_startup_diagnostic_reports_problems_without_blocking():
    """De diagnose moet juist draaien wanneer de configuratie stuk is."""
    result = _run_bot({}, "--startup-diagnostic")
    output = result.stdout + result.stderr

    assert result.returncode != 4, "diagnostic-modus mag niet op de preflight stuklopen"
    assert "SETUP REQUIRED" in output


def test_startup_with_valid_credentials_reaches_the_diagnostic_stage():
    result = _run_bot(valid_env(), "--startup-diagnostic")
    output = result.stdout + result.stderr

    assert result.returncode == 0, output[-3000:]
    assert "Credentials | openai" in output
    assert "Credentials | coinbase" in output


def test_startup_logging_never_contains_the_secret():
    env = valid_env(ed25519_base64())
    result = _run_bot(env, "--startup-diagnostic")
    output = result.stdout + result.stderr

    assert env["COINBASE_API_SECRET"] not in output
    assert env["OPENAI_API_KEY"] not in output


# ------------------------------------------------------ full setup flow


def test_full_flow_setup_then_restart_then_ready(tmp_path, monkeypatch):
    """Verse installatie -> setup -> herstart -> configuratie is er nog."""
    target = tmp_path / ".env"

    # 1. Verse installatie: nog geen configuratie.
    assert overall_state([check_openai({}), check_coinbase({})]) == SETUP_REQUIRED

    # 2. Setup: credentials opslaan zoals de wizard dat doet.
    secret = ed25519_base64()
    env_file.write_env_values(
        {
            "OPENAI_API_KEY": FAKE_OPENAI_KEY,
            "COINBASE_API_KEY": FAKE_COINBASE_KEY,
            "COINBASE_API_SECRET": secret,
        },
        target,
    )

    # 3. Herstart: alleen vanaf schijf herlezen, niets uit het geheugen.
    reloaded = env_file.read_env(target)

    # 4. Configuratie is compleet en bruikbaar.
    checks = [check_openai(reloaded), check_coinbase(reloaded)]
    assert overall_state(checks) == READY
    assert checks[1].facts["jwt_algorithm"] == "EdDSA"

    # 5. En de sleutel kan daadwerkelijk een JWT ondertekenen.
    monkeypatch.setenv("COINBASE_API_KEY", reloaded["COINBASE_API_KEY"])
    monkeypatch.setenv("COINBASE_API_SECRET", reloaded["COINBASE_API_SECRET"])
    coinbase_auth._CACHED_PRIVATE_KEY = None
    token = coinbase_auth.generate_coinbase_rest_jwt("GET", "api.coinbase.com", "/api/v3/brokerage/accounts")
    assert token.count(".") == 2


def test_setup_wizard_check_reports_json_without_secrets(tmp_path):
    target = tmp_path / ".env"
    secret = ecdsa_pem()
    env_file.write_env_values(
        {
            "OPENAI_API_KEY": FAKE_OPENAI_KEY,
            "COINBASE_API_KEY": FAKE_COINBASE_KEY,
            "COINBASE_API_SECRET": secret,
        },
        target,
    )

    loaded = env_file.read_env(target)
    report = status_report(loaded, online=False)
    encoded = json.dumps(report)

    assert report["state"] == READY
    assert FAKE_OPENAI_KEY not in encoded
    assert secret.splitlines()[1] not in encoded


def test_setup_wizard_cli_runs_and_emits_a_known_state(tmp_path):
    """De CLI moet ook echt uitvoerbaar zijn, niet alleen importeerbaar.

    Het oordeel hangt af van of er lokaal een .env staat, dus dat wordt hier
    niet vastgelegd -- wel dat de CLI draait, geldige JSON produceert en een
    van de bekende toestanden teruggeeft met de bijbehorende exit-code.
    """
    result = subprocess.run(
        [sys.executable, "-m", "tools.setup_wizard", "--check", "--json"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode in (0, 1), result.stderr[-2000:]
    payload = json.loads(result.stdout)
    assert payload["state"] in {READY, SETUP_REQUIRED, CONFIGURATION_ERROR}
    assert (result.returncode == 0) == (payload["state"] == READY)
