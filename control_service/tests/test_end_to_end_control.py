"""Integratietest van de keten extensie -> control-service -> bewaker -> bot.

Hier wordt de echte control-service met de echte ProcessManager en de echte
Supervisor-logica gebruikt; alleen het aanmaken van een besturingssysteemproces
is vervangen. Zo wordt getest wat er tussen de lagen misgaat -- precies wat
losse unittests per laag niet zien.

Er wordt nooit een order geplaatst en er draait nooit een echte handelsmotor.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bot import supervisor as supervisor_module
from control_service import config
from control_service.app import create_app, get_manager
from control_service.process_manager import ProcessManager

TOKEN = "integratie-token-lang-genoeg-abcdefghij"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
P = config.API_PREFIX


class _World:
    """Een nagebootste proceswereld met een supervisor die status schrijft."""

    def __init__(self, status_path: Path) -> None:
        self.status_path = status_path
        self.alive: set[int] = set()
        self.next_pid = 7000
        self.starts = 0

    def spawn(self, command, cwd) -> int:
        self.starts += 1
        self.next_pid += 1
        self.alive.add(self.next_pid)
        self._publish(supervisor_module.STATUS_RUNNING)
        return self.next_pid

    def is_alive(self, pid: int) -> bool:
        return pid in self.alive

    def crash_and_cooldown(self, pid: int) -> None:
        """De bot valt om; de bewaker blijft leven en gaat in cooldown."""
        self._publish(
            supervisor_module.STATUS_COOLDOWN,
            message="De bot stopte onverwacht (code 1). JARVIS wacht 5 seconden en probeert het dan opnieuw.",
            cooldown_seconds=5,
        )

    def die(self, pid: int) -> None:
        """Ook de bewaker verdwijnt, zonder zich af te melden."""
        self.alive.discard(pid)

    def _publish(self, state: str, **extra) -> None:
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(json.dumps({"state": state, **extra}), encoding="utf-8")


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        value = self.now
        self.now += 1.0
        return value


@pytest.fixture()
def wiring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    token_path = tmp_path / "control_token.txt"
    token_path.write_text(TOKEN, encoding="utf-8")
    monkeypatch.setattr(config, "TOKEN_PATH", token_path)
    monkeypatch.setattr(
        config,
        "READABLE_LOGS",
        {"bot": tmp_path / "loop.log", "supervisor": tmp_path / "supervisor.log", "control": tmp_path / "control.log"},
    )

    status_path = tmp_path / "state" / "supervisor_status.json"
    world = _World(status_path)
    manager = ProcessManager(
        project_root=tmp_path,
        pid_path=tmp_path / "state" / "control_supervisor.pid",
        status_path=status_path,
        stop_flag_path=tmp_path / "state" / "supervisor_stop_requested",
        spawn=world.spawn,
        pid_alive=world.is_alive,
        sleep=lambda _s: None,
        clock=_Clock(),
    )

    app = create_app()
    app.dependency_overrides[get_manager] = lambda: manager
    return TestClient(app, raise_server_exceptions=False), world, manager


def test_full_start_status_stop_cycle(wiring) -> None:
    client, world, manager = wiring

    assert client.get(f"{P}/status", headers=AUTH).json()["bot"]["running"] is False

    started = client.post(f"{P}/start", headers=AUTH)
    assert started.status_code == 200
    assert started.json()["ok"] is True

    running = client.get(f"{P}/status", headers=AUTH).json()
    assert running["bot"]["running"] is True
    assert running["bot"]["state"] == supervisor_module.STATUS_RUNNING

    # Het stopverzoek wordt door de nagebootste bewaker opgepikt.
    pid = manager.running_pid()
    manager._sleep = lambda _s: world.die(pid)

    stopped = client.post(f"{P}/stop", headers=AUTH)
    assert stopped.status_code == 200
    assert client.get(f"{P}/status", headers=AUTH).json()["bot"]["running"] is False


def test_a_crash_shows_up_as_cooldown_not_as_a_failure(wiring) -> None:
    """De extensie moet 'herstelt van een storing' kunnen tonen, niet 'kapot'."""
    client, world, manager = wiring
    client.post(f"{P}/start", headers=AUTH)

    world.crash_and_cooldown(manager.running_pid())
    status = client.get(f"{P}/status", headers=AUTH).json()

    assert status["bot"]["state"] == supervisor_module.STATUS_COOLDOWN
    assert status["bot"]["running"] is True, "de bewaker leeft nog en gaat herstarten"
    assert "opnieuw" in status["bot"]["supervisor"]["message"]


def test_a_vanished_supervisor_is_never_reported_as_running(wiring) -> None:
    """Het gevaarlijkste antwoord is 'hij draait' terwijl er niets draait."""
    client, world, manager = wiring
    client.post(f"{P}/start", headers=AUTH)
    pid = manager.running_pid()

    world.die(pid)  # taakbeheer, afsluiten van Windows, stroomstoring
    status = client.get(f"{P}/status", headers=AUTH).json()

    assert status["bot"]["running"] is False
    assert status["bot"]["state"] == supervisor_module.STATUS_STOPPED
    assert status["bot"]["supervisor"]["reason"] == "process_gone"


def test_starting_twice_does_not_create_a_second_bot(wiring) -> None:
    """Twee bots die dezelfde posities beheren is het ergste wat kan gebeuren."""
    client, world, _manager = wiring

    client.post(f"{P}/start", headers=AUTH)
    second = client.post(f"{P}/start", headers=AUTH)

    assert second.status_code == 200
    assert world.starts == 1
    assert "draait al" in second.json()["message"]


def test_restart_results_in_exactly_one_running_bot(wiring) -> None:
    client, world, manager = wiring
    client.post(f"{P}/start", headers=AUTH)
    pid = manager.running_pid()
    manager._sleep = lambda _s: world.die(pid)

    client.post(f"{P}/restart", headers=AUTH)

    assert world.starts == 2, "gestopt en opnieuw gestart"
    assert len(world.alive) == 1, "er draait er precies een"


def test_status_stays_answerable_when_the_status_file_is_corrupt(wiring) -> None:
    """Een half geschreven bestand mag de extensie niet blind maken."""
    client, _world, manager = wiring
    client.post(f"{P}/start", headers=AUTH)
    manager.status_path.write_text("{dit is geen json", encoding="utf-8")

    response = client.get(f"{P}/status", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["bot"]["supervisor"]["reason"] == "status_unreadable"


def test_no_response_in_the_whole_cycle_contains_a_secret(wiring, tmp_path: Path) -> None:
    """Eindcontrole: geen enkel endpoint lekt iets dat op een sleutel lijkt."""
    client, world, manager = wiring
    secret = "sk-" + "C" * 40
    (tmp_path / "loop.log").write_text(f"INFO key={secret}\n", encoding="utf-8")

    bodies = [
        client.get(f"{P}/health").text,
        client.post(f"{P}/start", headers=AUTH).text,
        client.get(f"{P}/status", headers=AUTH).text,
        client.get(f"{P}/logs", params={"name": "bot"}, headers=AUTH).text,
    ]
    pid = manager.running_pid()
    manager._sleep = lambda _s: world.die(pid)
    bodies.append(client.post(f"{P}/stop", headers=AUTH).text)

    for body in bodies:
        assert secret not in body
        assert TOKEN not in body
