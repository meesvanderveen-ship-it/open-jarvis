"""Tests voor de HTTP-laag van de control-service.

Nadruk ligt op de eisen die niet zichtbaar zijn in een happy-path-scherm:
geen enkele route zonder token, nooit een secret in een response, nooit een
traceback naar buiten, en een logbestand dat niet als vrij pad te misbruiken is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bot import supervisor as supervisor_module
from control_service import auth, config
from control_service.app import create_app, get_manager
from control_service.process_manager import ActionResult

TOKEN = "test-token-met-voldoende-lengte-1234567890"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class _FakeManager:
    """Legt vast welke acties gevraagd zijn, zonder ooit een proces te starten."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.next_result = ActionResult(
            ok=True, action="start", state=supervisor_module.STATUS_RUNNING, message="JARVIS is gestart."
        )
        self.next_status = {
            "state": supervisor_module.STATUS_RUNNING,
            "running": True,
            "supervisor_pid": 4242,
            "stop_requested": False,
            "supervisor": {"state": supervisor_module.STATUS_RUNNING},
        }

    def start(self):
        self.calls.append("start")
        return self.next_result

    def stop(self):
        self.calls.append("stop")
        return self.next_result

    def restart(self):
        self.calls.append("restart")
        return self.next_result

    def status(self):
        self.calls.append("status")
        return self.next_status


@pytest.fixture()
def manager() -> _FakeManager:
    return _FakeManager()


@pytest.fixture()
def client(tmp_path: Path, manager: _FakeManager, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    token_path = tmp_path / "control_token.txt"
    token_path.write_text(TOKEN, encoding="utf-8")
    monkeypatch.setattr(config, "TOKEN_PATH", token_path)
    monkeypatch.setattr(
        config,
        "READABLE_LOGS",
        {"bot": tmp_path / "loop.log", "supervisor": tmp_path / "supervisor.log", "control": tmp_path / "control.log"},
    )

    app = create_app()
    app.dependency_overrides[get_manager] = lambda: manager
    return TestClient(app, raise_server_exceptions=False)


P = config.API_PREFIX


# --------------------------------------------------------------------------
# Authenticatie
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", f"{P}/status"),
        ("post", f"{P}/start"),
        ("post", f"{P}/stop"),
        ("post", f"{P}/restart"),
        ("get", f"{P}/logs"),
        ("post", f"{P}/validate-credentials"),
    ],
)
def test_every_endpoint_except_health_requires_a_token(client: TestClient, method: str, path: str) -> None:
    """Loopback is geen bescherming: elke webpagina kan 127.0.0.1 benaderen."""
    response = getattr(client, method)(path)

    assert response.status_code == 401


def test_health_needs_no_token_so_the_extension_can_see_the_service_is_up(client: TestClient) -> None:
    response = client.get(f"{P}/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["token_required"] is True


def test_wrong_token_is_rejected_and_starts_nothing(client: TestClient, manager: _FakeManager) -> None:
    response = client.post(f"{P}/start", headers={"Authorization": "Bearer verkeerd"})

    assert response.status_code == 401
    assert manager.calls == [], "een afgewezen aanvraag raakt de bot niet aan"


def test_rejection_never_reveals_the_expected_token(client: TestClient) -> None:
    response = client.post(f"{P}/start", headers={"Authorization": "Bearer verkeerd"})

    assert TOKEN not in response.text


def test_alternative_header_is_accepted(client: TestClient) -> None:
    response = client.post(f"{P}/start", headers={"X-Jarvis-Token": TOKEN})

    assert response.status_code == 200


def test_missing_token_file_gives_a_clear_setup_message(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "TOKEN_PATH", tmp_path / "bestaat-niet.txt")

    response = client.get(f"{P}/status")

    assert response.status_code == 503
    assert "START-JARVIS" in json.dumps(response.json())


# --------------------------------------------------------------------------
# Acties
# --------------------------------------------------------------------------


def test_start_stop_restart_are_forwarded_to_the_manager(client: TestClient, manager: _FakeManager) -> None:
    assert client.post(f"{P}/start", headers=AUTH).status_code == 200
    assert client.post(f"{P}/stop", headers=AUTH).status_code == 200
    assert client.post(f"{P}/restart", headers=AUTH).status_code == 200

    assert manager.calls == ["start", "stop", "restart"]


def test_a_failed_action_keeps_its_http_status_and_message(client: TestClient, manager: _FakeManager) -> None:
    manager.next_result = ActionResult(
        ok=False,
        action="stop",
        state="stopping",
        message="JARVIS reageert niet op het stopverzoek.",
        detail="De bot maakt een lopende handelscyclus af.",
        http_status=504,
    )

    response = client.post(f"{P}/stop", headers=AUTH)

    assert response.status_code == 504
    assert response.json()["ok"] is False
    assert "handelscyclus" in response.json()["detail"]


def test_status_combines_process_state_and_health(client: TestClient) -> None:
    response = client.get(f"{P}/status", headers=AUTH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["bot"]["state"] == supervisor_module.STATUS_RUNNING
    assert payload["health"]["overall"] in {"READY", "WARNING", "ERROR", "OFFLINE"}
    assert isinstance(payload["health"]["checks"], list)


def test_status_survives_a_broken_health_check(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """De statusvraag is het enige venster van de gebruiker; die mag nooit omvallen."""
    import bot.health_check as health_module

    def explode(**_kwargs):
        raise RuntimeError("iets onverwachts")

    monkeypatch.setattr(health_module, "run_health_check", explode)

    response = client.get(f"{P}/status", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["health"]["overall"] == "ERROR"
    assert "diagnose.bat" in json.dumps(response.json())


# --------------------------------------------------------------------------
# Logs
# --------------------------------------------------------------------------


def test_logs_returns_the_last_lines(client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "loop.log").write_text("\n".join(f"regel {n}" for n in range(1, 51)), encoding="utf-8")

    response = client.get(f"{P}/logs", params={"name": "bot", "lines": 5}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["lines"] == [f"regel {n}" for n in range(46, 51)]


def test_logs_of_a_file_that_does_not_exist_yet_is_not_an_error(client: TestClient) -> None:
    response = client.get(f"{P}/logs", params={"name": "supervisor"}, headers=AUTH)

    assert response.status_code == 200
    assert response.json()["exists"] is False
    assert response.json()["lines"] == []


@pytest.mark.parametrize("name", ["../../.env", "..\\..\\.env", "/etc/passwd", "onbekend"])
def test_logs_only_accepts_names_from_the_fixed_list(client: TestClient, name: str) -> None:
    """Een vrij pad zou met '..' elk bestand op de schijf leesbaar maken."""
    response = client.get(f"{P}/logs", params={"name": name}, headers=AUTH)

    assert response.status_code == 404
    assert "available" in response.json()["detail"]


def test_logs_line_count_is_capped(client: TestClient) -> None:
    response = client.get(f"{P}/logs", params={"lines": 100000}, headers=AUTH)

    assert response.status_code == 422, "een absurd aantal regels wordt geweigerd, niet ingelezen"


def test_secrets_in_a_log_line_are_redacted_before_they_leave_the_service(
    client: TestClient, tmp_path: Path
) -> None:
    """Logbestanden zijn vrije tekst; een per ongeluk gelogd secret mag niet doorlekken."""
    secret = "sk-" + "A" * 40
    (tmp_path / "loop.log").write_text(f"2026-01-01 - INFO - key={secret}\n", encoding="utf-8")

    response = client.get(f"{P}/logs", params={"name": "bot"}, headers=AUTH)

    assert secret not in response.text
    assert "REDACTED" in response.text


# --------------------------------------------------------------------------
# Credential-validatie
# --------------------------------------------------------------------------


def test_validate_credentials_distinguishes_the_three_outcomes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bot.credential_status as cs

    for state, expected_word in [
        (cs.READY, "werken"),
        (cs.CONFIGURATION_ERROR, "afgewezen"),
        (cs.VERIFICATION_UNAVAILABLE, "netwerkprobleem"),
    ]:
        monkeypatch.setattr(
            cs, "status_report", (lambda fixed: lambda **_kw: {"state": fixed, "providers": {}})(state)
        )

        response = client.post(f"{P}/validate-credentials", headers=AUTH)

        assert response.status_code == 200
        assert expected_word in response.json()["message"], state


def test_validate_credentials_never_places_a_trade(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import bot.credential_status as cs

    monkeypatch.setattr(cs, "status_report", lambda **_kw: {"state": cs.READY, "providers": {}})

    response = client.post(f"{P}/validate-credentials", headers=AUTH)

    assert response.json()["trades_placed"] is False


def test_validate_credentials_response_contains_no_secret(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bot.credential_status as cs

    secret = "sk-" + "B" * 40
    monkeypatch.setattr(
        cs,
        "status_report",
        lambda **_kw: {"state": cs.READY, "providers": {"openai": {"api_key": secret, "summary": secret}}},
    )

    response = client.post(f"{P}/validate-credentials", headers=AUTH)

    assert secret not in response.text


def test_validate_credentials_failure_is_readable_and_not_a_traceback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bot.credential_status as cs

    def explode(**_kwargs):
        raise RuntimeError("intern detail dat niemand hoeft te zien")

    monkeypatch.setattr(cs, "status_report", explode)

    response = client.post(f"{P}/validate-credentials", headers=AUTH)

    assert response.status_code == 500
    assert "intern detail" not in response.text
    assert "diagnose.bat" in response.text


# --------------------------------------------------------------------------
# CORS en foutafhandeling
# --------------------------------------------------------------------------


def test_chrome_extension_origin_gets_cors_headers(client: TestClient) -> None:
    origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"

    response = client.get(f"{P}/health", headers={"Origin": origin})

    assert response.headers["Access-Control-Allow-Origin"] == origin


def test_a_normal_website_gets_no_cors_headers(client: TestClient) -> None:
    """Een willekeurige webpagina mag het antwoord niet kunnen uitlezen."""
    response = client.get(f"{P}/health", headers={"Origin": "https://kwaadaardig.example"})

    assert "Access-Control-Allow-Origin" not in response.headers


def test_preflight_is_answered_for_the_extension(client: TestClient) -> None:
    origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"

    response = client.options(f"{P}/start", headers={"Origin": origin})

    assert response.status_code == 204
    assert "Authorization" in response.headers["Access-Control-Allow-Headers"]


def test_an_unexpected_error_never_returns_a_traceback(
    client: TestClient, manager: _FakeManager
) -> None:
    def explode():
        raise RuntimeError("pad/naar/geheime/map en een stack trace")

    manager.start = explode  # type: ignore[method-assign]

    response = client.post(f"{P}/start", headers=AUTH)

    assert response.status_code == 500
    assert "Traceback" not in response.text
    assert "geheime" not in response.text
    assert "diagnose.bat" in response.text


# --------------------------------------------------------------------------
# Token-beheer
# --------------------------------------------------------------------------


def test_ensure_token_creates_a_long_random_token(tmp_path: Path) -> None:
    path = tmp_path / "token.txt"

    token = auth.ensure_token(path)

    assert len(token) >= auth.MIN_TOKEN_LENGTH
    assert path.read_text(encoding="utf-8").strip() == token


def test_ensure_token_is_stable_across_restarts(tmp_path: Path) -> None:
    """Anders zou de gebruiker na elke herstart opnieuw moeten plakken."""
    path = tmp_path / "token.txt"

    first = auth.ensure_token(path)
    second = auth.ensure_token(path)

    assert first == second


def test_a_too_short_token_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "token.txt"
    path.write_text("123", encoding="utf-8")

    token = auth.ensure_token(path)

    assert token != "123"
    assert len(token) >= auth.MIN_TOKEN_LENGTH


def test_rotate_token_produces_a_different_token(tmp_path: Path) -> None:
    path = tmp_path / "token.txt"
    first = auth.ensure_token(path)

    second = auth.rotate_token(path)

    assert first != second


def test_masked_token_shows_at_most_four_characters(tmp_path: Path) -> None:
    token = auth.ensure_token(tmp_path / "token.txt")

    shown = auth.masked(token)

    assert shown.endswith(token[-4:])
    assert token[:-4] not in shown


def test_token_comparison_rejects_a_prefix(tmp_path: Path) -> None:
    token = auth.ensure_token(tmp_path / "token.txt")

    assert auth.token_matches(token[:-1], token) is False
    assert auth.token_matches(token, token) is True
    assert auth.token_matches(None, token) is False


def test_extract_token_handles_both_header_styles() -> None:
    assert auth.extract_token("Bearer abc", None) == "abc"
    assert auth.extract_token(None, "abc") == "abc"
    assert auth.extract_token("abc", None) == "abc"
    assert auth.extract_token(None, None) is None


# --------------------------------------------------------------------------
# Herstel bij een onbereikbare provider
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_breaker():
    """Elke test begint met een gesloten breaker."""
    from control_service.app import _VALIDATION_BREAKER

    _VALIDATION_BREAKER.reset()
    yield
    _VALIDATION_BREAKER.reset()


def test_a_single_hiccup_is_retried_before_reporting_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eén hapering mag niet meteen 'niet bereikbaar' opleveren."""
    import bot.credential_status as cs

    pogingen = {"n": 0}

    def wisselvallig(**kwargs):
        if kwargs.get("online"):
            pogingen["n"] += 1
            if pogingen["n"] == 1:
                return {"state": cs.VERIFICATION_UNAVAILABLE, "providers": {}}
        return {"state": cs.READY, "providers": {}}

    monkeypatch.setattr(cs, "status_report", wisselvallig)

    response = client.post(f"{P}/validate-credentials", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["state"] == cs.READY
    assert pogingen["n"] == 2, "de tweede poging is niet gedaan"


def test_a_rejected_key_is_never_retried(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Een ingetrokken sleutel opnieuw aanbieden helpt niemand."""
    import bot.credential_status as cs

    pogingen = {"n": 0}

    def afgewezen(**_kwargs):
        pogingen["n"] += 1
        return {"state": cs.CONFIGURATION_ERROR, "providers": {}}

    monkeypatch.setattr(cs, "status_report", afgewezen)

    response = client.post(f"{P}/validate-credentials", headers=AUTH)

    assert pogingen["n"] == 1
    assert "afgewezen" in response.json()["message"]


def test_a_persistently_unreachable_provider_reports_unreachable_not_rejected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """De harde regel: onbereikbaar is nooit een verkeerde sleutel."""
    import bot.credential_status as cs

    monkeypatch.setattr(
        cs, "status_report", lambda **_kw: {"state": cs.VERIFICATION_UNAVAILABLE, "providers": {}}
    )

    body = client.post(f"{P}/validate-credentials", headers=AUTH).json()

    assert body["state"] == cs.VERIFICATION_UNAVAILABLE
    assert "netwerkprobleem" in body["message"]
    assert "afgewezen" not in body["message"]
    assert body["trades_placed"] is False


def test_repeated_clicking_while_offline_stops_calling_the_provider(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drie keer klikken zonder internet moet niet zes keer naar buiten bellen."""
    import bot.credential_status as cs

    aanroepen = {"n": 0}

    def onbereikbaar(**kwargs):
        if kwargs.get("online"):
            aanroepen["n"] += 1
        return {"state": cs.VERIFICATION_UNAVAILABLE, "providers": {}}

    monkeypatch.setattr(cs, "status_report", onbereikbaar)

    for _ in range(5):
        response = client.post(f"{P}/validate-credentials", headers=AUTH)
        assert response.status_code == 200

    assert aanroepen["n"] <= 4, f"de breaker greep niet in: {aanroepen['n']} uitgaande pogingen"
    laatste = client.post(f"{P}/validate-credentials", headers=AUTH).json()
    assert "overgeslagen" in laatste["message"] or "niet bereikbaar" in laatste["message"].lower()


def test_the_breaker_never_hides_a_working_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Een geslaagde controle sluit de breaker weer."""
    import bot.credential_status as cs
    from control_service.app import _VALIDATION_BREAKER

    monkeypatch.setattr(cs, "status_report", lambda **_kw: {"state": cs.READY, "providers": {}})

    assert client.post(f"{P}/validate-credentials", headers=AUTH).json()["state"] == cs.READY
    assert _VALIDATION_BREAKER.state == "closed"
