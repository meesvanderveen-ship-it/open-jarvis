"""Tests voor de begeleide credential-koppeling (bot/connect_services.py).

Dekt de twaalf punten uit de opdracht: detectie van bestaande credentials,
ontbrekende credentials per provider, een geslaagde en een mislukte koppeling,
persistentie over een herstart, automatische reconnect, afwezigheid van
secrets in uitvoer, en het intact blijven van de bestaande ECDSA-, Ed25519-
en OpenAI-flows.

Geen enkele test raakt het netwerk: elke provider-aanroep wordt geïnjecteerd.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from bot import connect_services, env_file
from bot.credential_status import (
    COINBASE_KEY_ENV,
    COINBASE_SECRET_ENV,
    OPENAI_KEY_ENV,
    READY,
    SETUP_REQUIRED,
    STATUS_INVALID,
    STATUS_MISSING,
    STATUS_OK,
    check_coinbase,
    check_openai,
    collect_checks,
    overall_state,
)
from tests.test_credential_setup_flow import (  # hergebruik van bestaande fixtures
    FAKE_COINBASE_KEY as VALID_COINBASE_KEY_NAME,
    ecdsa_pem,
    ed25519_base64,
)

VALID_OPENAI_KEY = "sk-proj-" + "a" * 40

# Echte sleutels, per test opnieuw gegenereerd door de bestaande helpers:
# een hardgecodeerde PEM in de testsuite is precies het soort waarde dat
# later voor een echte sleutel wordt aangezien.
ECDSA_PRIVATE_KEY = ecdsa_pem()
ED25519_PRIVATE_KEY = ed25519_base64()


# --------------------------------------------------------------------------
# Officiële routes: geen verzonnen automatische creatie
# --------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["openai", "coinbase"])
def test_no_provider_claims_automatic_key_creation(provider):
    """Automatische creatie bestaat officieel niet; dat moet code ook zeggen.

    Zou dit ooit op True gezet worden zonder echte officiële route, dan is dat
    per definitie een nep-key of een omzeiling van provider-security.
    """
    assert connect_services.automatic_creation_available(provider) is False
    assert connect_services.NO_AUTOMATIC_CREATION_REASON[provider]


@pytest.mark.parametrize(
    "provider,expected_host",
    [("openai", "platform.openai.com"), ("coinbase", "portal.cdp.coinbase.com")],
)
def test_official_pages_are_the_real_provider_domains(provider, expected_host):
    """De geopende pagina moet van de provider zelf zijn, niet van een proxy."""
    url = connect_services.PROVIDER_URLS[provider]
    assert url.startswith("https://")
    assert expected_host in url


def test_opening_a_page_that_fails_does_not_raise():
    """Een stukke of ontbrekende browser mag de setup niet laten crashen."""

    def broken_opener(url):
        raise RuntimeError("geen browser beschikbaar")

    assert connect_services.open_official_page("openai", opener=broken_opener) is False


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError):
        connect_services.open_official_page("nasdaq")


# --------------------------------------------------------------------------
# 1. Bestaande credentials worden automatisch gevonden
# --------------------------------------------------------------------------


def test_existing_credentials_are_detected_without_asking(tmp_path, monkeypatch):
    env = {
        OPENAI_KEY_ENV: VALID_OPENAI_KEY,
        COINBASE_KEY_ENV: VALID_COINBASE_KEY_NAME,
        COINBASE_SECRET_ENV: ECDSA_PRIVATE_KEY,
    }
    checks = collect_checks(env)
    assert overall_state(checks) == READY
    assert all(check.status == STATUS_OK for check in checks)


# --------------------------------------------------------------------------
# 2 & 3. Ontbrekende credentials per provider
# --------------------------------------------------------------------------


def test_missing_openai_credential_is_reported_as_setup_required():
    env = {
        COINBASE_KEY_ENV: VALID_COINBASE_KEY_NAME,
        COINBASE_SECRET_ENV: ECDSA_PRIVATE_KEY,
    }
    checks = collect_checks(env)
    assert overall_state(checks) == SETUP_REQUIRED
    assert check_openai(env).status == STATUS_MISSING


def test_missing_coinbase_credential_is_reported_as_setup_required():
    env = {OPENAI_KEY_ENV: VALID_OPENAI_KEY}
    checks = collect_checks(env)
    assert overall_state(checks) == SETUP_REQUIRED
    assert check_coinbase(env).status == STATUS_MISSING


# --------------------------------------------------------------------------
# OpenAI: klembord-overname
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "sk-proj-" + "b" * 40,
        "sk-svcacct-" + "c" * 40,
        "sk-" + "d" * 45,
    ],
)
def test_real_openai_key_shapes_are_recognised(text):
    assert connect_services.looks_like_openai_key(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "",
        "sk-short",
        "hallo dit is geen sleutel",
        "your_openai_api_key_here",
        "sk-proj-" + "a" * 40 + " en nog wat tekst",
        "-----BEGIN EC PRIVATE KEY-----",
    ],
)
def test_non_keys_are_not_mistaken_for_an_openai_key(text):
    assert connect_services.looks_like_openai_key(text) is False


def test_clipboard_key_is_picked_up_without_typing():
    """De kopieerknop bij OpenAI indrukken moet genoeg zijn."""
    clipboard_values = iter(["iets anders", "nog steeds niks", VALID_OPENAI_KEY])

    found = connect_services.wait_for_openai_key_on_clipboard(
        clipboard=lambda: next(clipboard_values),
        clock=lambda: 0.0,
        sleep=lambda _: None,
        timeout=10.0,
    )
    assert found == VALID_OPENAI_KEY


def test_a_key_already_on_the_clipboard_is_not_taken_as_the_new_one():
    """Anders zou een oude sleutel meteen als 'gevonden' gelden."""
    old_key = "sk-proj-" + "z" * 40
    ticks = iter([0.0, 0.0, 99.0])

    found = connect_services.wait_for_openai_key_on_clipboard(
        clipboard=lambda: old_key,
        clock=lambda: next(ticks),
        sleep=lambda _: None,
        timeout=1.0,
        ignore=old_key,
    )
    assert found is None


def test_clipboard_wait_times_out_instead_of_hanging():
    ticks = iter([0.0, 0.0, 100.0])
    found = connect_services.wait_for_openai_key_on_clipboard(
        clipboard=lambda: "",
        clock=lambda: next(ticks),
        sleep=lambda _: None,
        timeout=1.0,
    )
    assert found is None


def test_clipboard_reader_returns_empty_when_no_tool_exists():
    """Zonder klembordcommando volgt een lege string, geen exception."""
    assert connect_services.read_clipboard(command=["definitely-not-a-real-binary"]) == ""


# --------------------------------------------------------------------------
# Coinbase: download-overname
# --------------------------------------------------------------------------


def _write_key_file(path: Path, name: str, secret: str) -> Path:
    path.write_text(json.dumps({"name": name, "privateKey": secret}), encoding="utf-8")
    return path


def test_new_download_is_detected_automatically(tmp_path):
    """Het bestand dat ná het openen van de portal verschijnt, wordt gepakt."""
    old = _write_key_file(tmp_path / "old.json", "oud", ECDSA_PRIVATE_KEY)
    new = _write_key_file(tmp_path / "new.json", VALID_COINBASE_KEY_NAME, ECDSA_PRIVATE_KEY)

    known = connect_services.snapshot_key_files(finder=lambda: [old])
    results = iter([[old], [old], [old, new]])
    found = connect_services.wait_for_new_coinbase_key_file(
        known,
        finder=lambda: next(results),
        clock=lambda: 0.0,
        sleep=lambda _: None,
        timeout=10.0,
    )
    assert found == new


def test_a_pre_existing_key_file_is_not_taken_as_the_new_download(tmp_path):
    old = _write_key_file(tmp_path / "old.json", "oud", ECDSA_PRIVATE_KEY)
    known = connect_services.snapshot_key_files(finder=lambda: [old])
    ticks = iter([0.0, 0.0, 99.0])

    found = connect_services.wait_for_new_coinbase_key_file(
        known,
        finder=lambda: [old],
        clock=lambda: next(ticks),
        sleep=lambda _: None,
        timeout=1.0,
    )
    assert found is None


def test_a_download_overwriting_the_same_filename_is_still_detected(tmp_path):
    """Browsers schrijven de nieuwe sleutel vaak over cdp_api_key.json heen.

    Op alleen het pad vergelijken zou die download onzichtbaar maken: het pad
    is ongewijzigd terwijl de sleutel erin een andere is.
    """
    target = _write_key_file(
        tmp_path / "cdp_api_key.json", "organizations/o/apiKeys/OUD", ECDSA_PRIVATE_KEY
    )
    known = connect_services.snapshot_key_files(finder=lambda: [target])

    # Zelfde bestandsnaam, nieuwe inhoud.
    _write_key_file(target, "organizations/o/apiKeys/NIEUW", ed25519_base64())

    found = connect_services.wait_for_new_coinbase_key_file(
        known,
        finder=lambda: [target],
        clock=lambda: 0.0,
        sleep=lambda _: None,
        timeout=10.0,
    )
    assert found == target


def test_download_wait_times_out_instead_of_hanging():
    ticks = iter([0.0, 0.0, 100.0])
    found = connect_services.wait_for_new_coinbase_key_file(
        set(),
        finder=lambda: [],
        clock=lambda: next(ticks),
        sleep=lambda _: None,
        timeout=1.0,
    )
    assert found is None


# --------------------------------------------------------------------------
# 4, 5, 6, 7. Geslaagde en mislukte setup, persistentie, herstart
# --------------------------------------------------------------------------


def test_successful_setup_persists_and_survives_a_restart(tmp_path):
    """Na opslaan moet een vers proces de waarden terugvinden."""
    target = tmp_path / ".env"

    connect_services.store_openai_key(VALID_OPENAI_KEY, path=target)
    connect_services.store_coinbase_credentials(
        VALID_COINBASE_KEY_NAME, ECDSA_PRIVATE_KEY, path=target
    )

    # Herstart nabootsen: opnieuw van schijf lezen, niets uit het geheugen.
    reloaded = env_file.read_env(target)
    assert reloaded[OPENAI_KEY_ENV] == VALID_OPENAI_KEY
    assert reloaded[COINBASE_KEY_ENV] == VALID_COINBASE_KEY_NAME

    # Een PEM staat in .env op één regel met literal \n; dat is de bestaande
    # opslagvorm die coinbase_auth zelf terugvertaalt. Byte-identiteit is dus
    # de verkeerde eis -- dat de sleutel intact terugkomt, is de juiste.
    restored = reloaded[COINBASE_SECRET_ENV].replace("\\n", "\n").strip()
    assert restored == ECDSA_PRIVATE_KEY.strip()

    # 8. Automatische reconnect: die herladen waarden zijn meteen READY.
    assert overall_state(collect_checks(reloaded)) == READY


def test_stored_credentials_are_owner_only_on_disk(tmp_path):
    target = tmp_path / ".env"
    connect_services.store_openai_key(VALID_OPENAI_KEY, path=target)
    assert env_file.permissions_are_owner_only(target)


def _isolate_env(tmp_path, monkeypatch) -> Path:
    """Laat schrijfacties in tmp_path landen in plaats van in de echte .env."""
    target = tmp_path / ".env"
    monkeypatch.setattr(env_file, "env_path", lambda: target)
    monkeypatch.setattr(env_file, "example_path", lambda: tmp_path / ".env.example")
    return target


def test_full_coinbase_connect_picks_up_the_download_and_validates(tmp_path, monkeypatch):
    """4. Geslaagde setup: browser open, download opgemerkt, opgeslagen, gevalideerd."""
    from tools import connect_services as cli
    from bot.credential_status import CredentialCheck

    target = _isolate_env(tmp_path, monkeypatch)
    keyfile = _write_key_file(
        tmp_path / "cdp_api_key.json", VALID_COINBASE_KEY_NAME, ECDSA_PRIVATE_KEY
    )

    opened: list[str] = []
    accepted = CredentialCheck(
        provider="coinbase", status=STATUS_OK, summary="Coinbase authenticatie geslaagd."
    )

    # De download bestaat nog niet op het moment dat de portal opengaat; hij
    # verschijnt pas daarna. Dat is precies wat de detectie moet opmerken.
    downloads: list[Path] = []

    def finder():
        if opened:
            downloads.append(keyfile)
        return list(downloads)

    stream = io.StringIO()
    outcome = cli.connect_coinbase(
        stream=stream,
        opener=lambda url: opened.append(url) or True,
        finder=finder,
        verifier=lambda env: accepted,
        clock=lambda: 0.0,
        sleep=lambda _: None,
        timeout=5.0,
    )

    assert outcome.connected is True
    assert opened == [connect_services.COINBASE_CDP_KEYS_URL]

    stored = env_file.read_env(target)
    assert stored[COINBASE_KEY_ENV] == VALID_COINBASE_KEY_NAME
    assert stored[COINBASE_SECRET_ENV].replace("\\n", "\n").strip() == ECDSA_PRIVATE_KEY.strip()

    # Het secret mag nergens in het scherm zijn beland.
    assert ECDSA_PRIVATE_KEY.split("\n")[1] not in stream.getvalue()


def test_full_openai_connect_takes_the_key_from_the_clipboard(tmp_path, monkeypatch):
    """4. Geslaagde setup zonder één toetsaanslag."""
    from tools import connect_services as cli
    from bot.credential_status import CredentialCheck

    target = _isolate_env(tmp_path, monkeypatch)
    accepted = CredentialCheck(
        provider="openai", status=STATUS_OK, summary="OpenAI authenticatie geslaagd."
    )

    def refuse_to_prompt(_):
        raise AssertionError("er werd getypt terwijl het klembord de sleutel had")

    # Eerst iets anders (de meting van vóór het openen), daarna de sleutel:
    # zo verloopt het ook echt, want de gebruiker kopieert hem pas op de
    # OpenAI-pagina.
    clipboard_values = iter(["een oud stuk tekst", VALID_OPENAI_KEY])

    stream = io.StringIO()
    outcome = cli.connect_openai(
        stream=stream,
        opener=lambda url: True,
        clipboard=lambda: next(clipboard_values),
        prompt=refuse_to_prompt,
        verifier=lambda env: accepted,
        clock=lambda: 0.0,
        sleep=lambda _: None,
        timeout=5.0,
    )

    assert outcome.connected is True
    assert env_file.read_env(target)[OPENAI_KEY_ENV] == VALID_OPENAI_KEY
    assert VALID_OPENAI_KEY not in stream.getvalue()


def test_rejected_credentials_report_failed_not_connected(tmp_path, monkeypatch):
    """5. Mislukte setup: afgewezen sleutel mag nooit als connected gelden."""
    from tools import connect_services as cli
    from bot.credential_status import CredentialCheck

    _isolate_env(tmp_path, monkeypatch)
    rejected = CredentialCheck(
        provider="openai",
        status=STATUS_INVALID,
        summary="OpenAI authenticatie mislukt.",
        detail="OpenAI wees de sleutel af (HTTP 401).",
    )

    clipboard_values = iter(["oude inhoud", VALID_OPENAI_KEY])

    stream = io.StringIO()
    outcome = cli.connect_openai(
        stream=stream,
        opener=lambda url: True,
        clipboard=lambda: next(clipboard_values),
        verifier=lambda env: rejected,
        clock=lambda: 0.0,
        sleep=lambda _: None,
        timeout=5.0,
    )

    assert outcome.connected is False
    assert "401" in outcome.detail
    assert VALID_OPENAI_KEY not in stream.getvalue()


def test_unusable_key_file_is_reported_without_storing_anything(tmp_path, monkeypatch):
    """Een kapot bestand mag .env niet half beschrijven."""
    from tools import connect_services as cli

    target = _isolate_env(tmp_path, monkeypatch)
    broken = tmp_path / "broken.json"
    broken.write_text('{"name": "alleen-een-naam"}', encoding="utf-8")

    # find_coinbase_key_files zou dit bestand in het echt al overslaan; hier
    # wordt het bewust aangeboden om te bewijzen dat de inleesstap zelf ook
    # weigert, en niet alleen de zoekstap.
    seen: list[Path] = []

    def finder():
        result = list(seen)
        seen.append(broken)
        return result

    stream = io.StringIO()
    outcome = cli.connect_coinbase(
        stream=stream,
        opener=lambda url: True,
        finder=finder,
        verifier=lambda env: pytest.fail("validatie had niet bereikt mogen worden"),
        clock=lambda: 0.0,
        sleep=lambda _: None,
        timeout=5.0,
    )

    assert outcome.connected is False
    assert "privateKey" in outcome.detail
    assert not target.exists() or COINBASE_SECRET_ENV not in env_file.read_env(target)


def test_failed_setup_leaves_a_reason_and_does_not_report_connected():
    outcome = connect_services.ConnectOutcome(
        provider="coinbase",
        connected=False,
        summary="Sleutelbestand onbruikbaar.",
        detail="Veld(en) privateKey ontbreken in dit bestand.",
    )
    assert outcome.connected is False
    assert outcome.as_dict()["check"] is None
    assert "privateKey" in outcome.as_dict()["detail"]


def test_a_partial_write_never_leaves_a_half_env_behind(tmp_path):
    """Bestaande sleutels mogen niet sneuvelen als er één bijkomt."""
    target = tmp_path / ".env"
    target.write_text("BESTAANDE=waarde\n# commentaar\n", encoding="utf-8")

    connect_services.store_openai_key(VALID_OPENAI_KEY, path=target)

    content = target.read_text(encoding="utf-8")
    assert "BESTAANDE=waarde" in content
    assert "# commentaar" in content
    assert env_file.read_env(target)[OPENAI_KEY_ENV] == VALID_OPENAI_KEY


# --------------------------------------------------------------------------
# 9. Geen secrets in uitvoer
# --------------------------------------------------------------------------


def test_status_screen_never_prints_a_secret(tmp_path, monkeypatch):
    from tools import connect_services as cli

    monkeypatch.setattr(env_file, "env_path", lambda: tmp_path / ".env")

    env = {
        OPENAI_KEY_ENV: VALID_OPENAI_KEY,
        COINBASE_KEY_ENV: VALID_COINBASE_KEY_NAME,
        COINBASE_SECRET_ENV: ECDSA_PRIVATE_KEY,
    }
    stream = io.StringIO()
    cli.render_status(collect_checks(env), stream)
    output = stream.getvalue()

    assert VALID_OPENAI_KEY not in output
    assert ECDSA_PRIVATE_KEY not in output
    # Ook geen fragment van de PEM-body.
    body = ECDSA_PRIVATE_KEY.split("\n")[1]
    assert body not in output
    assert "● Connected" in output


def test_outcome_dict_of_a_real_check_carries_no_secret():
    env = {
        COINBASE_KEY_ENV: VALID_COINBASE_KEY_NAME,
        COINBASE_SECRET_ENV: ECDSA_PRIVATE_KEY,
    }
    check = check_coinbase(env)
    payload = json.dumps(
        connect_services.ConnectOutcome(
            provider="coinbase", connected=True, summary=check.summary, check=check
        ).as_dict()
    )
    assert ECDSA_PRIVATE_KEY not in payload
    assert ECDSA_PRIVATE_KEY.split("\n")[1] not in payload


def test_shape_description_reports_shape_but_not_content():
    described = connect_services.describe_stored_shape(ECDSA_PRIVATE_KEY)
    assert described["present"] is True
    assert described["looks_like_pem"] is True
    assert ECDSA_PRIVATE_KEY not in json.dumps(described)


# --------------------------------------------------------------------------
# 10, 11, 12. Bestaande flows blijven werken
# --------------------------------------------------------------------------


def test_existing_ecdsa_flow_still_works():
    env = {
        COINBASE_KEY_ENV: VALID_COINBASE_KEY_NAME,
        COINBASE_SECRET_ENV: ECDSA_PRIVATE_KEY,
    }
    check = check_coinbase(env)
    assert check.status == STATUS_OK
    assert check.facts["jwt_algorithm"] == "ES256"


def test_existing_ed25519_flow_still_works():
    env = {
        COINBASE_KEY_ENV: VALID_COINBASE_KEY_NAME,
        COINBASE_SECRET_ENV: ED25519_PRIVATE_KEY,
    }
    check = check_coinbase(env)
    assert check.status == STATUS_OK
    assert check.facts["jwt_algorithm"] == "EdDSA"


def test_existing_openai_flow_still_works():
    check = check_openai({OPENAI_KEY_ENV: VALID_OPENAI_KEY})
    assert check.status == STATUS_OK


def test_connect_module_does_not_shadow_the_existing_wizard():
    """Beide routes moeten dezelfde opslag- en validatielaag gebruiken."""
    import tools.setup_wizard as wizard

    assert wizard.load_coinbase_key_file is not None
    # connect_services hergebruikt de zoekfunctie van de wizard in plaats van
    # een tweede implementatie te onderhouden die kan gaan afwijken.
    assert connect_services._key_file_finder() is wizard.find_coinbase_key_files


# --------------------------------------------------------------------------
# One-click gedrag
# --------------------------------------------------------------------------


def test_ready_credentials_skip_the_setup_entirely(tmp_path, monkeypatch):
    """Staat alles goed, dan hoort er niets gevraagd te worden."""
    from tools import connect_services as cli

    target = tmp_path / ".env"
    monkeypatch.setattr(env_file, "env_path", lambda: target)
    monkeypatch.setattr(env_file, "example_path", lambda: tmp_path / ".env.example")

    for name, value in (
        (OPENAI_KEY_ENV, VALID_OPENAI_KEY),
        (COINBASE_KEY_ENV, VALID_COINBASE_KEY_NAME),
        (COINBASE_SECRET_ENV, ECDSA_PRIVATE_KEY),
    ):
        monkeypatch.setenv(name, value)

    def must_not_be_called(**kwargs):
        raise AssertionError("setup werd getoond terwijl alles al gekoppeld was")

    stream = io.StringIO()
    code = cli.run(
        stream=stream,
        online=False,
        connect_openai_fn=must_not_be_called,
        connect_coinbase_fn=must_not_be_called,
    )

    assert code == 0
    assert "START JARVIS" in stream.getvalue()


def test_missing_credentials_trigger_only_the_missing_provider(tmp_path, monkeypatch):
    from tools import connect_services as cli

    target = tmp_path / ".env"
    monkeypatch.setattr(env_file, "env_path", lambda: target)
    monkeypatch.setattr(env_file, "example_path", lambda: tmp_path / ".env.example")

    monkeypatch.setenv(OPENAI_KEY_ENV, VALID_OPENAI_KEY)
    monkeypatch.delenv(COINBASE_KEY_ENV, raising=False)
    monkeypatch.delenv(COINBASE_SECRET_ENV, raising=False)

    called: list[str] = []

    def openai_connector(**kwargs):
        called.append("openai")
        raise AssertionError("OpenAI stond al goed en had niet gevraagd mogen worden")

    def coinbase_connector(**kwargs):
        called.append("coinbase")
        return connect_services.ConnectOutcome(
            provider="coinbase", connected=False, summary="Overgeslagen."
        )

    stream = io.StringIO()
    cli.run(
        stream=stream,
        online=False,
        connect_openai_fn=openai_connector,
        connect_coinbase_fn=coinbase_connector,
    )

    assert called == ["coinbase"]


def test_reconnect_replaces_a_provider_that_is_already_connected(tmp_path, monkeypatch):
    """Zonder deze route is een geldige sleutel niet te vervangen."""
    from tools import connect_services as cli

    target = tmp_path / ".env"
    monkeypatch.setattr(env_file, "env_path", lambda: target)
    monkeypatch.setattr(env_file, "example_path", lambda: tmp_path / ".env.example")

    for name, value in (
        (OPENAI_KEY_ENV, VALID_OPENAI_KEY),
        (COINBASE_KEY_ENV, VALID_COINBASE_KEY_NAME),
        (COINBASE_SECRET_ENV, ECDSA_PRIVATE_KEY),
    ):
        monkeypatch.setenv(name, value)

    called: list[str] = []

    def coinbase_connector(**kwargs):
        called.append("coinbase")
        return connect_services.ConnectOutcome(
            provider="coinbase", connected=True, summary="Opnieuw gekoppeld."
        )

    def openai_connector(**kwargs):
        raise AssertionError("alleen coinbase stond in reconnect")

    stream = io.StringIO()
    cli.run(
        stream=stream,
        online=False,
        reconnect=("coinbase",),
        connect_openai_fn=openai_connector,
        connect_coinbase_fn=coinbase_connector,
    )

    assert called == ["coinbase"]


def test_ready_screen_explains_how_to_replace_a_key(tmp_path, monkeypatch):
    """Wie een sleutel wil vervangen moet kunnen zien hoe."""
    from tools import connect_services as cli

    monkeypatch.setattr(env_file, "env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(env_file, "example_path", lambda: tmp_path / ".env.example")
    for name, value in (
        (OPENAI_KEY_ENV, VALID_OPENAI_KEY),
        (COINBASE_KEY_ENV, VALID_COINBASE_KEY_NAME),
        (COINBASE_SECRET_ENV, ECDSA_PRIVATE_KEY),
    ):
        monkeypatch.setenv(name, value)

    stream = io.StringIO()
    code = cli.run(
        stream=stream,
        online=False,
        connect_openai_fn=lambda **k: pytest.fail("niets te koppelen"),
        connect_coinbase_fn=lambda **k: pytest.fail("niets te koppelen"),
    )

    assert code == 0
    assert "--reconnect coinbase" in stream.getvalue()


def test_reconnect_flag_is_parsed_for_both_providers():
    from tools import connect_services as cli

    parsed = []
    cli.run = lambda **kwargs: parsed.append(kwargs.get("reconnect")) or 0  # type: ignore[assignment]
    try:
        cli.main(["--reconnect", "coinbase", "--reconnect", "openai", "--offline"])
    finally:
        import importlib

        importlib.reload(cli)

    assert parsed == [("coinbase", "openai")]


def test_status_screen_shows_not_connected_when_nothing_is_configured(monkeypatch):
    from tools import connect_services as cli

    for name in (OPENAI_KEY_ENV, COINBASE_KEY_ENV, COINBASE_SECRET_ENV):
        monkeypatch.delenv(name, raising=False)

    stream = io.StringIO()
    state = cli.render_status(collect_checks({}), stream)
    output = stream.getvalue()

    assert state == SETUP_REQUIRED
    assert "○ Not connected" in output
    assert "○ Setup required" in output


def test_status_screen_shows_authentication_failed_for_rejected_credentials(monkeypatch):
    from tools import connect_services as cli
    from bot.credential_status import CredentialCheck

    rejected = CredentialCheck(
        provider="openai",
        status=STATUS_INVALID,
        summary="OpenAI authenticatie mislukt.",
        detail="OpenAI wees de sleutel af (HTTP 401).",
    )
    stream = io.StringIO()
    cli.render_status([rejected], stream)
    output = stream.getvalue()

    assert "✕ Authentication failed" in output
    assert "HTTP 401" in output
