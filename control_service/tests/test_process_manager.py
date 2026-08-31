"""Tests voor de procesbesturing van de control-service.

Er wordt geen enkel echt proces gestart. ``spawn`` en ``pid_alive`` worden
vervangen, zodat elk scenario -- al draaiend, verdwenen proces, weigerend te
stoppen -- exact reproduceerbaar is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot import supervisor as supervisor_module
from control_service.process_manager import ProcessManager


class _World:
    """Een nagebootste proceswereld: welke pids leven er, en wat is gestart."""

    def __init__(self) -> None:
        self.alive: set[int] = set()
        self.started: list[list[str]] = []
        self.next_pid = 5000

    def spawn(self, command, cwd) -> int:
        self.started.append(list(command))
        self.next_pid += 1
        self.alive.add(self.next_pid)
        return self.next_pid

    def is_alive(self, pid: int) -> bool:
        return pid in self.alive

    def kill(self, pid: int) -> None:
        self.alive.discard(pid)


class _Clock:
    """Een klok die bij elke aflezing vooruit loopt.

    Moet vooruit lopen: de wachtlussen in ProcessManager stoppen op een
    deadline, dus een stilstaande klok zou de test laten hangen in plaats van
    laten falen. De stap is groot genoeg om elke lus binnen enkele
    iteraties te laten aflopen.
    """

    def __init__(self, step: float = 1.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


def _manager(tmp_path: Path, world: _World, *, clock=None, sleep=None) -> ProcessManager:
    return ProcessManager(
        project_root=tmp_path,
        pid_path=tmp_path / "state" / "control_supervisor.pid",
        status_path=tmp_path / "state" / "supervisor_status.json",
        stop_flag_path=tmp_path / "state" / "supervisor_stop_requested",
        spawn=world.spawn,
        pid_alive=world.is_alive,
        sleep=sleep or (lambda _s: None),
        clock=clock or _Clock(),
    )


def _write_status(manager: ProcessManager, state: str, **extra) -> None:
    manager.status_path.parent.mkdir(parents=True, exist_ok=True)
    manager.status_path.write_text(json.dumps({"state": state, **extra}), encoding="utf-8")


# --------------------------------------------------------------------------
# Starten
# --------------------------------------------------------------------------


def test_start_spawns_the_supervisor_not_the_bot_directly(tmp_path: Path) -> None:
    """De bot moet altijd onder bewaking draaien, ook als de browser dicht is."""
    world = _World()
    manager = _manager(tmp_path, world)

    class _Immediate(_Clock):
        def __call__(self) -> float:
            _write_status(manager, supervisor_module.STATUS_RUNNING)
            return self.now

    manager._clock = _Immediate()
    result = manager.start()

    assert result.ok is True
    assert world.started[0][-2:] == ["-m", "bot.supervisor"]


def test_start_is_idempotent_when_already_running(tmp_path: Path) -> None:
    world = _World()
    manager = _manager(tmp_path, world)
    manager._write_pid(4321)
    world.alive.add(4321)

    result = manager.start()

    assert result.ok is True
    assert "draait al" in result.message
    assert world.started == [], "er wordt geen tweede bot gestart"


def test_start_reports_a_failed_supervisor_with_advice(tmp_path: Path) -> None:
    world = _World()
    manager = _manager(tmp_path, world)

    class _FailingClock(_Clock):
        def __call__(self) -> float:
            _write_status(
                manager,
                supervisor_module.STATUS_FAILED,
                message="De API-sleutels werden afgewezen.",
                advice="Draai INSTALLEREN-WINDOWS.bat.",
            )
            return self.now

    manager._clock = _FailingClock()
    result = manager.start()

    assert result.ok is False
    assert result.http_status == 409
    assert "sleutels" in result.message
    assert result.detail == "Draai INSTALLEREN-WINDOWS.bat."


def test_start_detects_a_supervisor_that_dies_immediately(tmp_path: Path) -> None:
    world = _World()
    manager = _manager(tmp_path, world)

    def spawn_and_die(command, cwd) -> int:
        pid = world.spawn(command, cwd)
        world.kill(pid)
        return pid

    manager._spawn = spawn_and_die
    result = manager.start()

    assert result.ok is False
    assert "logs/supervisor.log" in result.detail.replace("\\", "/")
    assert not manager.pid_path.exists(), "het pid-bestand wordt opgeruimd"


def test_start_that_cannot_spawn_returns_a_readable_error(tmp_path: Path) -> None:
    manager = _manager(tmp_path, _World())

    def refuse(command, cwd):
        raise OSError("kan het programma niet vinden")

    manager._spawn = refuse
    result = manager.start()

    assert result.ok is False
    assert result.http_status == 500
    assert "diagnose.bat" in result.detail


def test_start_clears_a_stale_stop_flag(tmp_path: Path) -> None:
    """Anders zou de nieuwe bewaker zichzelf meteen weer afsluiten."""
    world = _World()
    manager = _manager(tmp_path, world)
    manager.stop_flag_path.parent.mkdir(parents=True, exist_ok=True)
    manager.stop_flag_path.write_text("oud")

    manager.start()

    assert not manager.stop_flag_path.exists()


def test_slow_start_is_reported_as_starting_not_as_a_failure(tmp_path: Path) -> None:
    """Op een trage pc duurt het laden van de handelsmotor gewoon langer."""
    world = _World()
    clock = _Clock()
    manager = _manager(tmp_path, world, clock=clock, sleep=lambda seconds: setattr(clock, "now", clock.now + 5))

    result = manager.start()

    assert result.ok is True
    assert result.state == supervisor_module.STATUS_STARTING
    assert "opstarten" in result.message


# --------------------------------------------------------------------------
# Stoppen
# --------------------------------------------------------------------------


def test_stop_asks_politely_via_the_flag_file(tmp_path: Path) -> None:
    """Nooit hard afschieten: de bot moet zijn bestanden netjes kunnen sluiten."""
    world = _World()
    manager = _manager(tmp_path, world)
    manager._write_pid(777)
    world.alive.add(777)

    flags_seen: list[bool] = []

    def sleep(_seconds: float) -> None:
        flags_seen.append(manager.stop_flag_path.exists())
        world.kill(777)

    manager._sleep = sleep
    result = manager.stop()

    assert result.ok is True
    assert flags_seen == [True], "de stopvlag stond er voordat het proces verdween"
    assert not manager.stop_flag_path.exists(), "en wordt daarna opgeruimd"
    assert not manager.pid_path.exists()


def test_stop_when_nothing_runs_is_not_an_error(tmp_path: Path) -> None:
    result = _manager(tmp_path, _World()).stop()

    assert result.ok is True
    assert "draaide al niet" in result.message


def test_stop_that_times_out_explains_itself_without_killing(tmp_path: Path) -> None:
    world = _World()
    clock = _Clock()
    manager = _manager(tmp_path, world, clock=clock, sleep=lambda seconds: setattr(clock, "now", clock.now + 10))
    manager._write_pid(888)
    world.alive.add(888)

    result = manager.stop(timeout=30.0)

    assert result.ok is False
    assert result.http_status == 504
    assert "handelscyclus" in result.detail
    assert 888 in world.alive, "een lopende cyclus wordt niet halverwege afgebroken"


# --------------------------------------------------------------------------
# Herstarten
# --------------------------------------------------------------------------


def test_restart_stops_before_it_starts(tmp_path: Path) -> None:
    world = _World()
    manager = _manager(tmp_path, world)
    manager._write_pid(999)
    world.alive.add(999)
    order: list[str] = []

    def sleep(_seconds: float) -> None:
        if 999 in world.alive:
            order.append("gestopt")
            world.kill(999)

    manager._sleep = sleep
    original_spawn = manager._spawn

    def spawn(command, cwd):
        order.append("gestart")
        return original_spawn(command, cwd)

    manager._spawn = spawn
    manager.restart()

    assert order[:2] == ["gestopt", "gestart"]


def test_restart_refuses_when_the_bot_will_not_stop(tmp_path: Path) -> None:
    world = _World()
    clock = _Clock()
    manager = _manager(tmp_path, world, clock=clock, sleep=lambda seconds: setattr(clock, "now", clock.now + 10))
    manager._write_pid(555)
    world.alive.add(555)

    result = manager.restart(timeout=20.0)

    assert result.ok is False
    assert world.started == [], "er wordt geen tweede bot naast de eerste gezet"


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------


def test_status_of_a_never_started_bot(tmp_path: Path) -> None:
    status = _manager(tmp_path, _World()).status()

    assert status["running"] is False
    assert status["state"] == supervisor_module.STATUS_STOPPED
    assert status["supervisor"]["reason"] == "never_started"


def test_status_prefers_the_process_fact_over_a_stale_status_file(tmp_path: Path) -> None:
    """Doen alsof de bot draait terwijl hij weg is, is het gevaarlijkste antwoord."""
    world = _World()
    manager = _manager(tmp_path, world)
    manager._write_pid(1234)  # proces bestaat niet in deze wereld
    _write_status(manager, supervisor_module.STATUS_RUNNING)

    status = manager.status()

    assert status["running"] is False
    assert status["state"] == supervisor_module.STATUS_STOPPED
    assert status["supervisor"]["reason"] == "process_gone"


def test_stale_pid_file_is_cleaned_up(tmp_path: Path) -> None:
    manager = _manager(tmp_path, _World())
    manager._write_pid(31337)

    assert manager.running_pid() is None
    assert not manager.pid_path.exists()


def test_corrupt_pid_file_is_ignored(tmp_path: Path) -> None:
    manager = _manager(tmp_path, _World())
    manager.pid_path.parent.mkdir(parents=True, exist_ok=True)
    manager.pid_path.write_text("dit is geen pid", encoding="utf-8")

    assert manager.running_pid() is None


def test_status_reports_a_running_bot(tmp_path: Path) -> None:
    world = _World()
    manager = _manager(tmp_path, world)
    manager._write_pid(2222)
    world.alive.add(2222)
    _write_status(manager, supervisor_module.STATUS_RUNNING, pid=2223)

    status = manager.status()

    assert status["running"] is True
    assert status["state"] == supervisor_module.STATUS_RUNNING
    assert status["supervisor_pid"] == 2222


def test_status_reports_cooldown_while_the_supervisor_waits(tmp_path: Path) -> None:
    world = _World()
    manager = _manager(tmp_path, world)
    manager._write_pid(3333)
    world.alive.add(3333)
    _write_status(
        manager,
        supervisor_module.STATUS_COOLDOWN,
        message="De bot stopte onverwacht. JARVIS wacht 30 seconden.",
        cooldown_seconds=30,
    )

    status = manager.status()

    assert status["state"] == supervisor_module.STATUS_COOLDOWN
    assert "wacht" in status["supervisor"]["message"]


# --------------------------------------------------------------------------
# Echte processen: een afgesloten kind mag nooit als "draait" gelezen worden
# --------------------------------------------------------------------------


def test_a_finished_child_is_not_reported_as_alive() -> None:
    """Op POSIX blijft een afgesloten kind als zombie in de proceslijst staan.

    Een zombie beantwoordt signaal 0 nog gewoon, dus de kale kill(pid, 0)-check
    las hem als levend. Gevolg: de statusvraag meldde "JARVIS draait" voor een
    bot die met een foutcode gestopt was, en de Start-knop in de extensie bleef
    uitgeschakeld. Dit is de gevaarlijke kant om je in te vergissen.
    """
    import subprocess
    import sys
    import time

    from control_service import process_manager

    child = subprocess.Popen([sys.executable, "-c", "raise SystemExit(4)"])
    process_manager._SPAWNED[child.pid] = child
    try:
        deadline = time.monotonic() + 10
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)

        assert process_manager._pid_alive(child.pid) is False
    finally:
        process_manager._SPAWNED.pop(child.pid, None)
        child.wait()


def test_a_running_child_is_reported_as_alive() -> None:
    """Tegenhanger: de fix mag een draaiend proces niet dood verklaren."""
    import subprocess
    import sys

    from control_service import process_manager

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    process_manager._SPAWNED[child.pid] = child
    try:
        assert process_manager._pid_alive(child.pid) is True
    finally:
        process_manager._SPAWNED.pop(child.pid, None)
        child.kill()
        child.wait()


def test_a_pid_that_never_existed_is_not_alive() -> None:
    from control_service import process_manager

    assert process_manager._pid_alive(0) is False
    assert process_manager._pid_alive(-1) is False


def test_the_real_spawner_registers_the_child_so_it_can_be_reaped(tmp_path: Path) -> None:
    """Zonder deze administratie kan _pid_alive de zombie niet opruimen."""
    import sys
    import time

    from control_service import process_manager

    pid = process_manager._spawn_supervisor([sys.executable, "-c", "raise SystemExit(0)"], tmp_path)
    try:
        assert pid in process_manager._SPAWNED

        deadline = time.monotonic() + 10
        while process_manager._pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)

        assert process_manager._pid_alive(pid) is False
        assert pid not in process_manager._SPAWNED, "de administratie loopt niet vol"
    finally:
        child = process_manager._SPAWNED.pop(pid, None)
        if child is not None:
            child.kill()
            child.wait()
