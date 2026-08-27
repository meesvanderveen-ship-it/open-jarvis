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
    client = _FakeCoinbaseClient(error=RuntimeError('Coinbase HTTP error 401: {"message":"Unauthorized"}'))
    check = verify_coinbase(valid_env(), client=client)

    assert check.status == STATUS_INVALID
    assert "mislukt" in check.summary


def test_coinbase_network_failure_is_not_blamed_on_credentials():
    client = _FakeCoinbaseClient(error=OSError("connection reset"))
    check = verify_coinbase(valid_env(), client=client)

    assert check.status == STATUS_UNKNOWN
    assert "netwerk" in check.detail.lower()


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


# ------------------------------- niet-uitgevoerde verificatie


def test_unverifiable_check_never_reports_ready():
    """Een netwerkstoring mag geen valse PASS opleveren.

    verify_* geeft STATUS_UNKNOWN als de API onbereikbaar was. Zou dat als
    READY doorgaan, dan zou de installer 'gelukt' melden zonder dat iemand
    weet of de sleutels werken.
    """
    from bot.credential_status import VERIFICATION_UNAVAILABLE

    unreachable = verify_openai(
        {"OPENAI_API_KEY": FAKE_OPENAI_KEY}, session=_Session(raises=OSError("geen netwerk"))
    )
    assert unreachable.status == STATUS_UNKNOWN

    checks = [unreachable, check_coinbase(valid_env())]
    assert overall_state(checks) == VERIFICATION_UNAVAILABLE
    assert overall_state(checks) != READY


def test_rejected_credentials_outrank_an_unreachable_api():
    """Een afgewezen sleutel is ernstiger dan een niet-bereikbare API."""
    rejected = verify_openai({"OPENAI_API_KEY": FAKE_OPENAI_KEY}, session=_Session(status_code=401))
    unreachable = verify_coinbase(valid_env(), client=_FakeCoinbaseClient(error=OSError("down")))

    assert overall_state([rejected, unreachable]) == CONFIGURATION_ERROR


def test_offline_checks_never_produce_the_unverified_state():
    """Offline levert alleen ok/missing/invalid op, dus dit verandert niets."""
    from bot.credential_status import VERIFICATION_UNAVAILABLE

    for env in ({}, valid_env(), {"OPENAI_API_KEY": "your_openai_api_key_here"}):
        state = overall_state([check_openai(env), check_coinbase(env)])
        assert state != VERIFICATION_UNAVAILABLE


def test_wizard_exit_codes_distinguish_rejected_from_unreachable():
    """De installer leunt op deze codes om geen valse 'GELUKT' te tonen."""
    from bot.credential_status import VERIFICATION_UNAVAILABLE
    from tools.setup_wizard import EXIT_INVALID, EXIT_OK, EXIT_UNVERIFIED, exit_code_for

    assert exit_code_for(READY) == EXIT_OK
    assert exit_code_for(VERIFICATION_UNAVAILABLE) == EXIT_UNVERIFIED
    assert exit_code_for(CONFIGURATION_ERROR) == EXIT_INVALID
    assert exit_code_for(SETUP_REQUIRED) == EXIT_INVALID
    assert EXIT_OK != EXIT_UNVERIFIED != EXIT_INVALID


def test_rejected_ed25519_key_suggests_an_ecdsa_key():
    """Coinbase Advanced Trade accepteert mogelijk alleen ECDSA.

    Wordt een Ed25519-sleutel afgewezen, dan moet de melding dat noemen --
    anders zoekt de gebruiker in de verkeerde richting.
    """
    client = _FakeCoinbaseClient(error=RuntimeError("Coinbase HTTP error 401: unauthorized"))
    check = verify_coinbase(valid_env(ed25519_base64()), client=client)

    assert check.status == STATUS_INVALID
    assert "Ed25519" in check.detail
    assert "ECDSA" in check.detail


def test_rejected_ecdsa_key_does_not_mention_the_key_type():
    """Bij een ECDSA-sleutel is het sleuteltype juist niet de verdachte."""
    client = _FakeCoinbaseClient(error=RuntimeError("Coinbase HTTP error 401: unauthorized"))
    check = verify_coinbase(valid_env(ecdsa_pem()), client=client)

    assert check.status == STATUS_INVALID
    assert "Ed25519" not in check.detail


def test_proxy_403_is_not_mistaken_for_rejected_credentials():
    """Een blokkerende proxy meldt ook 403; dat is geen sleutelprobleem.

    De oude classificatie zocht "403" in de hele fouttekst en rapporteerde
    dan CONFIGURATION ERROR. De gebruiker zou een prima sleutel vervangen.
    """
    proxy_error = RuntimeError(
        "Coinbase request failed: ProxyError('Cannot connect to proxy.', "
        "OSError('Tunnel connection failed: 403 Forbidden'))"
    )
    check = verify_coinbase(valid_env(), client=_FakeCoinbaseClient(error=proxy_error))

    assert check.status == STATUS_UNKNOWN
    assert "netwerk" in check.detail.lower()


def test_real_http_401_from_coinbase_is_reported_as_invalid():
    error = RuntimeError('Coinbase HTTP error 401: {"message":"Unauthorized"}')
    check = verify_coinbase(valid_env(), client=_FakeCoinbaseClient(error=error))

    assert check.status == STATUS_INVALID
    assert "mislukt" in check.summary


def test_coinbase_server_error_is_not_blamed_on_the_key():
    error = RuntimeError("Coinbase HTTP error 503: service unavailable")
    check = verify_coinbase(valid_env(), client=_FakeCoinbaseClient(error=error))

    assert check.status == STATUS_UNKNOWN
    assert check.facts["http_status"] == 503


# ---------------------------------------------------------------------------
# Windows-invoer: geplakte sleutels
# ---------------------------------------------------------------------------


class _FakeWindowsConsole:
    """De consolebuffer van cmd.exe, genoeg om msvcrt na te bootsen.

    Rechtermuisklik-plakken schuift de klembordinhoud er in één keer in,
    inclusief het CRLF dat aan gekopieerde tekst vastzit.
    """

    def __init__(self, pasted: list[str]) -> None:
        self.pending = list("".join(value + "\r\n" for value in pasted))
        self.echoed: list[str] = []

    def kbhit(self) -> bool:
        return bool(self.pending)

    def getwch(self) -> str:
        return self.pending.pop(0) if self.pending else "\r"

    def ungetwch(self, char: str) -> None:
        self.pending.insert(0, char)

    def putwch(self, char: str) -> None:
        self.echoed.append(char)


def test_pasted_secrets_do_not_skip_the_following_prompts(monkeypatch):
    """Regressie: het CRLF van een plakactie mocht geen vraag overslaan.

    `getpass.win_getpass` stopt op de CR en laat de LF in de buffer staan.
    Die beantwoordde dan de volgende vraag meteen met een lege invoer,
    waardoor de Coinbase-vragen ongemerkt werden overgeslagen en de
    installatie afbrak op het moment dat de gebruiker zijn sleutels invoerde.
    """
    from tools import setup_wizard

    waarden = ["sk-openai-sleutel", "organizations/o/apiKeys/k", "SLEUTELINHOUD"]
    console = _FakeWindowsConsole(waarden)
    monkeypatch.setitem(sys.modules, "msvcrt", console)

    gelezen = [setup_wizard._windows_read_secret("  Sleutel: ") for _ in waarden]

    assert gelezen == waarden


def test_windows_reader_masks_input_without_revealing_it(monkeypatch):
    from tools import setup_wizard

    console = _FakeWindowsConsole(["geheim"])
    monkeypatch.setitem(sys.modules, "msvcrt", console)

    setup_wizard._windows_read_secret("")
    echoed = "".join(console.echoed)

    assert "geheim" not in echoed
    assert echoed.count("*") == len("geheim")


def test_windows_reader_ignores_arrow_and_function_keys(monkeypatch):
    """Pijltoetsen sturen twee tekens; het tweede mag niet in het secret."""
    from tools import setup_wizard

    console = _FakeWindowsConsole([])
    console.pending = list("ab") + ["\xe0", "K"] + list("cd\r")
    monkeypatch.setitem(sys.modules, "msvcrt", console)

    assert setup_wizard._windows_read_secret("") == "abcd"


# ---------------------------------------------------------------------------
# Coinbase-sleutelbestand
# ---------------------------------------------------------------------------


def test_key_file_preserves_a_multiline_pem(tmp_path):
    """De PEM-route bestaat juist omdat plakken meerregelige tekst afkapt."""
    from tools.setup_wizard import load_coinbase_key_file

    pem = ecdsa_pem()
    assert pem.strip().count("\n") >= 2, "deze test heeft een meerregelige PEM nodig"

    path = tmp_path / "cdp_api_key.json"
    path.write_text(json.dumps({"name": "organizations/o/apiKeys/k", "privateKey": pem}))

    name, secret = load_coinbase_key_file(path)

    assert name == "organizations/o/apiKeys/k"
    assert secret == pem.strip()


def test_key_file_round_trips_through_env_unchanged(tmp_path):
    from tools.setup_wizard import load_coinbase_key_file

    pem = ecdsa_pem()
    path = tmp_path / "cdp_api_key.json"
    path.write_text(json.dumps({"name": "organizations/o/apiKeys/k", "privateKey": pem}))
    name, secret = load_coinbase_key_file(path)

    target = tmp_path / ".env"
    target.write_text("OPENAI_API_KEY=sk-bestaand\n")
    env_file.write_env_values(
        {"COINBASE_API_KEY": name, "COINBASE_API_SECRET": secret}, target
    )

    values = env_file.read_env(target)
    assert values["COINBASE_API_SECRET"].replace("\\n", "\n") == pem.strip()
    assert values["OPENAI_API_KEY"] == "sk-bestaand"


@pytest.mark.parametrize(
    "content, expected",
    [
        ("dit is geen json", "geldig JSON"),
        (json.dumps({"name": "x"}), "privateKey"),
        (json.dumps({"privateKey": "x"}), "name"),
        (json.dumps(["lijst"]), "sleutelvelden"),
    ],
)
def test_unusable_key_file_explains_what_is_wrong(tmp_path, content, expected):
    from tools.setup_wizard import load_coinbase_key_file

    path = tmp_path / "cdp_api_key.json"
    path.write_text(content)

    with pytest.raises(ValueError) as exc:
        load_coinbase_key_file(path)

    assert expected in str(exc.value)


def test_key_file_error_never_contains_the_secret(tmp_path):
    from tools.setup_wizard import load_coinbase_key_file

    path = tmp_path / "cdp_api_key.json"
    path.write_text(json.dumps({"privateKey": "SUPERGEHEIM"}))

    with pytest.raises(ValueError) as exc:
        load_coinbase_key_file(path)

    assert "SUPERGEHEIM" not in str(exc.value)


def test_windows_copy_as_path_quotes_are_stripped():
    """Verkenner en slepen-naar-venster zetten quotes om het pad heen."""
    from tools.setup_wizard import _clean_path_input

    assert _clean_path_input('  "C:\\Users\\Mees\\cdp_api_key.json" ') == (
        "C:\\Users\\Mees\\cdp_api_key.json"
    )


def test_truncated_pem_paste_is_recognised():
    from tools.setup_wizard import _looks_like_truncated_pem

    assert _looks_like_truncated_pem("-----BEGIN EC PRIVATE KEY-----")
    assert not _looks_like_truncated_pem(ecdsa_pem())
    assert not _looks_like_truncated_pem("base64-ed25519-sleutel-zonder-pem")


# ---------------------------------------------------------------------------
# Sleutelbestand vinden zonder een pad te hoeven typen
# ---------------------------------------------------------------------------


def _write_key_file(path: Path) -> str:
    pem = ecdsa_pem()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": "organizations/o/apiKeys/k", "privateKey": pem}))
    return pem


def test_key_files_are_found_in_the_usual_download_locations(tmp_path, monkeypatch):
    """Een pad intypen was het grootste struikelblok van de setup."""
    from tools import setup_wizard

    home = tmp_path / "home"
    _write_key_file(home / "Downloads" / "cdp_api_key.json")
    _write_key_file(home / "Desktop" / "andere_sleutel.json")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    namen = {path.name for path in setup_wizard.find_coinbase_key_files()}

    assert {"cdp_api_key.json", "andere_sleutel.json"} <= namen


def test_unrelated_json_is_not_offered_as_a_key_file(tmp_path, monkeypatch):
    """Een projectmap staat vol JSON; alleen echte sleutelbestanden tellen."""
    from tools import setup_wizard

    home = tmp_path / "home"
    downloads = home / "Downloads"
    downloads.mkdir(parents=True)
    (downloads / "package-lock.json").write_text(
        json.dumps({"name": "app", "lockfileVersion": 3})
    )
    (downloads / "willekeurig.json").write_text(json.dumps({"foo": "bar"}))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    assert setup_wizard.find_coinbase_key_files() == []


def test_a_found_key_file_can_be_chosen_by_number(tmp_path, monkeypatch):
    from tools import setup_wizard

    home = tmp_path / "home"
    pem = _write_key_file(home / "Downloads" / "cdp_api_key.json")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    name, secret = setup_wizard._prompt_coinbase_from_file(reader=lambda _: "1")

    assert name == "organizations/o/apiKeys/k"
    assert secret == pem.strip()


def test_out_of_range_number_reprompts_instead_of_crashing(tmp_path, monkeypatch):
    from tools import setup_wizard

    home = tmp_path / "home"
    _write_key_file(home / "Downloads" / "cdp_api_key.json")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    antwoorden = iter(["9", "1"])
    name, _ = setup_wizard._prompt_coinbase_from_file(reader=lambda _: next(antwoorden))

    assert name == "organizations/o/apiKeys/k"


def test_enter_falls_back_to_pasting_the_values(tmp_path, monkeypatch):
    from tools import setup_wizard

    home = tmp_path / "home"
    _write_key_file(home / "Downloads" / "cdp_api_key.json")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    assert setup_wizard._prompt_coinbase_from_file(reader=lambda _: "") is None


def test_swapped_key_and_secret_from_the_old_paste_bug_is_flagged(capsys):
    """De oude bug kon de API Key in het Secret-veld laten belanden."""
    from tools import setup_wizard

    setup_wizard._describe_stored_coinbase(
        {
            "COINBASE_API_KEY": "organizations/o/apiKeys/k",
            "COINBASE_API_SECRET": "organizations/o/apiKeys/k",
        }
    )
    uitvoer = capsys.readouterr().out

    assert "verwisseling" in uitvoer


def test_stored_openai_key_without_sk_prefix_is_flagged(capsys):
    """"is al ingesteld (104 tekens)" leest als goedkeuring, maar telt alleen."""
    from tools import setup_wizard

    setup_wizard._warn_if_openai_key_shape_is_odd("a" * 104)
    assert "begint niet met 'sk-'" in capsys.readouterr().out

    setup_wizard._warn_if_openai_key_shape_is_odd("sk-proj-" + "a" * 96)
    assert capsys.readouterr().out == ""


def test_full_wizard_needs_only_enter_and_a_number(tmp_path, monkeypatch):
    """De hele setup in twee toetsaanslagen, met een intacte PEM als resultaat."""
    from tools import setup_wizard

    home = tmp_path / "home"
    pem = _write_key_file(home / "Downloads" / "cdp_api_key.json")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    target = tmp_path / ".env"
    target.write_text("OPENAI_API_KEY=sk-proj-" + "a" * 90 + "\n")
    monkeypatch.setattr(setup_wizard.env_file, "env_path", lambda: target)

    code = setup_wizard.run_interactive(
        reader=lambda _: "",       # Enter: OpenAI-sleutel behouden
        line_reader=lambda _: "1",  # het gevonden sleutelbestand
    )

    assert code == 0
    values = env_file.read_env(target)
    assert values["COINBASE_API_SECRET"].replace("\\n", "\n") == pem.strip()
    assert values["OPENAI_API_KEY"].startswith("sk-proj-")


def test_openai_paste_does_not_corrupt_the_following_coinbase_prompt(monkeypatch):
    """Regressie: de Coinbase-vraag gedroeg zich raar na het plakken van OpenAI.

    De OpenAI-sleutel wordt via msvcrt gelezen, de Coinbase-vraag ging via
    `input()`. Dat zijn twee verschillende invoerlagen: msvcrt leest de
    console-buffer rechtstreeks, `input()` gaat door de gebufferde stdin van
    de C-runtime. Een teken dat `_drain_pending_newlines` met `ungetwch`
    terugduwt komt in de pushback van msvcrt terecht, waar `input()` nooit
    naar kijkt -- dat teken verdween dus, en de vraag erna liep vast of sloeg
    over. Beide vragen horen daarom dezelfde laag te gebruiken.
    """
    from tools import setup_wizard

    console = _FakeWindowsConsole(["sk-geplakte-sleutel", "2"])
    monkeypatch.setitem(sys.modules, "msvcrt", console)

    secret = setup_wizard._windows_read_secret("  OpenAI: ")
    keuze = setup_wizard._windows_read_line("  Nummer: ")

    assert secret == "sk-geplakte-sleutel"
    assert keuze == "2"


def test_windows_line_reader_shows_what_is_typed(monkeypatch):
    """Een pad of nummer is geen secret en moet leesbaar zijn."""
    from tools import setup_wizard

    console = _FakeWindowsConsole(["C:\\keys\\cdp.json"])
    monkeypatch.setitem(sys.modules, "msvcrt", console)

    gelezen = setup_wizard._windows_read_line("  Pad: ")

    assert gelezen == "C:\\keys\\cdp.json"
    assert "C:\\keys\\cdp.json" in "".join(console.echoed)
    # Een secret wordt gemaskeerd, dit juist niet.
    assert "*" not in "".join(console.echoed)


def test_windows_line_reader_ignores_arrow_keys(monkeypatch):
    """Pijltoetsen sturen twee tekens en mogen niet in het pad belanden."""
    from tools import setup_wizard

    console = _FakeWindowsConsole([])
    console.pending = list("cdp") + ["\xe0", "H"] + list(".json\r\n")
    monkeypatch.setitem(sys.modules, "msvcrt", console)

    assert setup_wizard._windows_read_line("  Pad: ") == "cdp.json"


def test_windows_line_reader_supports_backspace(monkeypatch):
    from tools import setup_wizard

    console = _FakeWindowsConsole([])
    console.pending = list("12") + ["\b"] + list("3\r\n")
    monkeypatch.setitem(sys.modules, "msvcrt", console)

    assert setup_wizard._windows_read_line("  Nummer: ") == "13"


def test_read_line_uses_the_windows_reader_on_windows(monkeypatch):
    """De routering zelf vastleggen, niet alleen de lezer.

    Zonder deze test kan read_line ongemerkt terugvallen op input() en is de
    bug hierboven terug zonder dat er iets faalt.
    """
    from tools import setup_wizard

    monkeypatch.setattr(setup_wizard.os, "name", "nt")
    monkeypatch.setattr(setup_wizard.sys, "stdin", setup_wizard.sys.__stdin__)

    gebruikt: list[str] = []
    monkeypatch.setattr(
        setup_wizard,
        "_windows_read_line",
        lambda prompt: gebruikt.append(prompt) or "gelezen",
    )

    assert setup_wizard.read_line("  Nummer: ") == "gelezen"
    assert gebruikt == ["  Nummer: "]


def test_read_line_falls_back_to_input_without_msvcrt(monkeypatch):
    """Op een systeem zonder msvcrt moet de gewone route blijven werken."""
    from tools import setup_wizard

    monkeypatch.setattr(setup_wizard.os, "name", "nt")
    monkeypatch.setattr(setup_wizard.sys, "stdin", setup_wizard.sys.__stdin__)

    def geen_msvcrt(prompt):
        raise ImportError("msvcrt bestaat hier niet")

    monkeypatch.setattr(setup_wizard, "_windows_read_line", geen_msvcrt)
    monkeypatch.setattr("builtins.input", lambda prompt: "via-input")

    assert setup_wizard.read_line("  Pad: ") == "via-input"
