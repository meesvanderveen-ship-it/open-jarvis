"""Het credential-statusendpoint moet informeren zonder iets te lekken of te wijzigen."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from dashboard.backend import cache
from dashboard.backend.app import app
from dashboard.backend.services import setup_status

SECRET_MARKER = "MARKER-SECRET-MUST-NEVER-APPEAR"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear() if hasattr(cache, "clear") else None
    yield
    cache.clear() if hasattr(cache, "clear") else None


@pytest.fixture
def client():
    return TestClient(app)


class _Completed:
    def __init__(self, returncode: int, stdout: str, stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _patch_subprocess(monkeypatch, completed):
    recorded = {}

    def fake_run(argv, **kwargs):
        recorded["argv"] = argv
        recorded["kwargs"] = kwargs
        return completed

    monkeypatch.setattr(setup_status.subprocess, "run", fake_run)
    return recorded


def test_status_endpoint_reports_ready(monkeypatch, client):
    payload = {
        "state": "READY",
        "verified_online": False,
        "providers": {
            "openai": {"provider": "openai", "status": "ok", "summary": "aanwezig"},
            "coinbase": {"provider": "coinbase", "status": "ok", "summary": "aanwezig"},
        },
    }
    _patch_subprocess(monkeypatch, _Completed(0, json.dumps(payload)))

    response = client.get("/api/setup/status")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "READY"
    assert body["read_only"] is True
    assert body["coinbase_calls_enabled"] is False


def test_exit_code_one_is_a_valid_state_not_an_error(monkeypatch, client):
    """De wizard geeft exit 1 bij onvolledige setup; dat is geen 502 waard."""
    payload = {"state": "SETUP_REQUIRED", "verified_online": False, "providers": {}}
    _patch_subprocess(monkeypatch, _Completed(1, json.dumps(payload)))

    response = client.get("/api/setup/status")

    assert response.status_code == 200
    assert response.json()["state"] == "SETUP_REQUIRED"


def test_unexpected_exit_code_degrades_to_unknown(monkeypatch, client):
    _patch_subprocess(monkeypatch, _Completed(2, ""))

    response = client.get("/api/setup/status")

    assert response.status_code == 200
    assert response.json()["state"] == "UNKNOWN"


def test_invalid_json_degrades_to_unknown(monkeypatch, client):
    _patch_subprocess(monkeypatch, _Completed(0, "not json at all"))

    assert client.get("/api/setup/status").json()["state"] == "UNKNOWN"


def test_endpoint_never_calls_a_shell(monkeypatch, client):
    payload = {"state": "READY", "verified_online": False, "providers": {}}
    recorded = _patch_subprocess(monkeypatch, _Completed(0, json.dumps(payload)))

    client.get("/api/setup/status")

    assert recorded["kwargs"]["shell"] is False
    assert "--check" in recorded["argv"] and "--json" in recorded["argv"]
    # Geen --online: het endpoint mag Coinbase/OpenAI nooit aanroepen.
    assert "--online" not in recorded["argv"]


def test_secrets_in_tool_output_are_redacted_before_leaving_the_api(monkeypatch, client):
    """Defense-in-depth: zelfs als de tool zou lekken, scrubt de middleware."""
    payload = {
        "state": "READY",
        "verified_online": False,
        "providers": {
            "coinbase": {
                "provider": "coinbase",
                "status": "ok",
                "summary": "aanwezig",
                "api_secret": SECRET_MARKER,
            }
        },
    }
    _patch_subprocess(monkeypatch, _Completed(0, json.dumps(payload)))

    response = client.get("/api/setup/status")

    assert SECRET_MARKER not in response.text
