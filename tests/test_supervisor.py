"""Tests voor bot/supervisor.py.

Er wordt geen enkel echt proces gestart: ``spawn`` wordt vervangen door een
scriptbare nepklasse en de klok/slaapfunctie door recorders. Zo is het gedrag
bij crash, permanente fout en herstartlimiet exact vast te leggen zonder dat
de suite trager wordt of van het besturingssysteem afhangt.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bot.resilience import RetryPolicy
from bot.supervisor import (
    STATUS_COOLDOWN,
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_STOPPED,
    Supervisor,
    SupervisorPolicy,
    read_status,
)


class _FakeProcess:
    """Een kindproces dat meteen een van tevoren bepaalde exitcode heeft."""

    def __init__(self, exit_code: int, pid: int) -> None:
        self.exit_code = exit_code
        self.pid = pid
        self.stop_requested = False
        self.killed = False

    def poll(self):
        return self.exit_code

    def wait(self, timeout=None):
        return self.exit_code

    def request_stop(self) -> None:
        self.stop_requested = True

    def kill(self) -> None:
        self.killed = True


class _HangingProcess(_FakeProcess):
    """Reageert niet op een stopverzoek tot hij hard gestopt wordt."""

    def __init__(self, pid: int) -> None:
        super().__init__(exit_code=0, pid=pid)
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def wait(self, timeout=None):
        if self._alive:
            raise subprocess.TimeoutExpired(cmd="bot", timeout=timeout or 0)
        return 0

    def kill(self) -> None:
        self.killed = True
        self._alive = False


class _Spawner:
    """Levert bij elke start de volgende exitcode uit een script."""

    def __init__(self, exit_codes: list[int]) -> None:
        self.exit_codes = list(exit_codes)
        self.started: list[list[str]] = []
        self.processes: list[_FakeProcess] = []

    def __call__(self, command, cwd) -> _FakeProcess:
        self.started.append(list(command))
        code = self.exit_codes.pop(0) if self.exit_codes else 0
        process = _FakeProcess(code, pid=1000 + len(self.started))
        self.processes.append(process)
        return process


class _Clock:
    def __init__(self, step: float = 0.0) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        value = self.now
        self.now += self.step
        return value


def _policy(**overrides) -> SupervisorPolicy:
    defaults = dict(
        max_restarts=3,
        restart_window_seconds=3600.0,
        stable_run_seconds=300.0,
        graceful_stop_seconds=1.0,
        backoff=RetryPolicy(max_attempts=5, base_delay=1.0, multiplier=2.0, max_delay=8.0, jitter=0.0),
    )
    defaults.update(overrides)
    return SupervisorPolicy(**defaults)


def _make(tmp_path: Path, spawner: _Spawner, *, policy=None, clock=None, waits=None) -> Supervisor:
    return Supervisor(
        ["python", "run_trader_loop.py"],
        policy=policy or _policy(),
        cwd=tmp_path,
        status_path=tmp_path / "state" / "supervisor_status.json",
        spawn=spawner,
        sleep=(waits.append if waits is not None else (lambda _seconds: None)),
        clock=clock or _Clock(),
    )


# --------------------------------------------------------------------------
# Nette afsluiting
# --------------------------------------------------------------------------


def test_clean_exit_stops_the_supervisor_without_restarting(tmp_path: Path) -> None:
    spawner = _Spawner([0])

    result = _make(tmp_path, spawner).run()

    assert result == 0
    assert len(spawner.started) == 1, "een nette afsluiting wordt niet herstart"


def test_status_file_reports_stopped_after_clean_exit(tmp_path: Path) -> None:
    supervisor = _make(tmp_path, _Spawner([0]))

    supervisor.run()

    status = read_status(supervisor.status_path)
    assert status["state"] == STATUS_STOPPED
    assert status["reason"] == "clean_exit"


# --------------------------------------------------------------------------
# Herstel na crash
# --------------------------------------------------------------------------


def _capture_cooldowns(supervisor: Supervisor) -> list[float]:
    """Verzamel de gepubliceerde cooldown per herstart.

    De supervisor wacht bewust in stappen van een seconde, zodat een
    stopverzoek tijdens een lange cooldown niet minutenlang blijft liggen. De
    losse slaapaanroepen zeggen daardoor niets; de gepubliceerde waarde wel.
    """
    cooldowns: list[float] = []
    original = supervisor._publish

    def capture(state, **extra):
        payload = original(state, **extra)
        if state == STATUS_COOLDOWN:
            cooldowns.append(payload["cooldown_seconds"])
        return payload

    supervisor._publish = capture  # type: ignore[method-assign]
    return cooldowns


def test_crash_is_followed_by_a_restart(tmp_path: Path) -> None:
    spawner = _Spawner([1, 0])
    waits: list[float] = []
    supervisor = _make(tmp_path, spawner, waits=waits)
    cooldowns = _capture_cooldowns(supervisor)

    result = supervisor.run()

    assert result == 0
    assert len(spawner.started) == 2, "na een crash volgt een herstart"
    assert cooldowns == [1.0], "en daar zit een cooldown tussen"
    assert sum(waits) == pytest.approx(1.0)


def test_repeated_crashes_use_exponential_backoff(tmp_path: Path) -> None:
    spawner = _Spawner([1, 1, 1, 0])
    waits: list[float] = []
    supervisor = _make(tmp_path, spawner, policy=_policy(max_restarts=10), waits=waits)
    cooldowns = _capture_cooldowns(supervisor)

    supervisor.run()

    assert cooldowns == [1.0, 2.0, 4.0], "de wachttijd verdubbelt bij elke opeenvolgende crash"
    assert sum(waits) == pytest.approx(7.0)


def test_backoff_resets_after_a_run_that_stayed_up_long_enough(tmp_path: Path) -> None:
    """Een crash na uren draaien is een nieuwe storing, geen doorlopende lus."""
    spawner = _Spawner([1, 1, 1, 0])
    # Elke klokaflezing springt 400 seconden vooruit, dus elke run telt als stabiel.
    clock = _Clock(step=400.0)
    supervisor = _make(tmp_path, spawner, policy=_policy(max_restarts=10, stable_run_seconds=300.0), clock=clock)
    cooldowns = _capture_cooldowns(supervisor)

    supervisor.run()

    assert cooldowns == [1.0, 1.0, 1.0], "de wachttijd loopt niet op na stabiele runs"


def test_cooldown_is_interrupted_by_a_stop_request(tmp_path: Path) -> None:
    """Stoppen tijdens een wachttijd van vijf minuten mag geen vijf minuten duren."""
    spawner = _Spawner([1, 0])
    waits: list[float] = []
    stop_flag = tmp_path / "state" / "supervisor_stop_requested"
    supervisor = Supervisor(
        ["python", "run_trader_loop.py"],
        policy=_policy(backoff=RetryPolicy(max_attempts=5, base_delay=300.0, multiplier=2.0, max_delay=300.0, jitter=0.0)),
        cwd=tmp_path,
        status_path=tmp_path / "state" / "supervisor_status.json",
        stop_flag_path=stop_flag,
        spawn=spawner,
        sleep=lambda seconds: (waits.append(seconds), stop_flag.parent.mkdir(parents=True, exist_ok=True), stop_flag.write_text("stop")),
    )

    result = supervisor.run()

    assert result == 0
    assert len(waits) < 5, "de cooldown wordt afgebroken zodra er om stoppen gevraagd wordt"
    assert len(spawner.started) == 1, "er volgt geen herstart meer na een stopverzoek"


def test_stop_flag_stops_a_running_supervisor(tmp_path: Path) -> None:
    stop_flag = tmp_path / "state" / "supervisor_stop_requested"
    stop_flag.parent.mkdir(parents=True, exist_ok=True)

    class _LiveProcess(_FakeProcess):
        def __init__(self) -> None:
            super().__init__(exit_code=0, pid=99)

        def poll(self):
            return None

        def wait(self, timeout=None):
            # Zodra er gewacht wordt, vraagt een ander proces om stoppen.
            stop_flag.write_text("stop")
            raise subprocess.TimeoutExpired(cmd="bot", timeout=timeout or 0)

    process = _LiveProcess()
    supervisor = Supervisor(
        ["python", "run_trader_loop.py"],
        policy=_policy(graceful_stop_seconds=0.01),
        cwd=tmp_path,
        status_path=tmp_path / "state" / "supervisor_status.json",
        stop_flag_path=stop_flag,
        spawn=lambda command, cwd: process,
        sleep=lambda _s: None,
    )

    assert supervisor.run() == 0
    assert process.stop_requested is True
    assert not stop_flag.exists(), "de vlag wordt opgeruimd, anders blijft de bot uit"


def test_stale_stop_flag_is_cleared_at_startup(tmp_path: Path) -> None:
    """Een vlag van vorige week mag een nieuwe start niet meteen afbreken."""
    stop_flag = tmp_path / "state" / "supervisor_stop_requested"
    stop_flag.parent.mkdir(parents=True, exist_ok=True)
    stop_flag.write_text("oud")
    spawner = _Spawner([0])

    supervisor = Supervisor(
        ["python", "run_trader_loop.py"],
        policy=_policy(),
        cwd=tmp_path,
        status_path=tmp_path / "state" / "supervisor_status.json",
        stop_flag_path=stop_flag,
        spawn=spawner,
        sleep=lambda _s: None,
    )
    supervisor.run()

    assert len(spawner.started) == 1, "de bot start gewoon"
    assert not stop_flag.exists()


def test_cooldown_status_explains_the_wait_in_plain_language(tmp_path: Path) -> None:
    supervisor = _make(tmp_path, _Spawner([1, 0]))
    published: list[dict] = []
    original = supervisor._publish

    def capture(state, **extra):
        payload = original(state, **extra)
        published.append(payload)
        return payload

    supervisor._publish = capture  # type: ignore[method-assign]
    supervisor.run()

    cooldown = [row for row in published if row["state"] == STATUS_COOLDOWN]
    assert len(cooldown) == 1
    assert "opnieuw" in cooldown[0]["message"]
    assert cooldown[0]["cooldown_seconds"] == 1.0
    assert cooldown[0]["log_file"].endswith("loop.log")


# --------------------------------------------------------------------------
# Permanente fouten
# --------------------------------------------------------------------------


@pytest.mark.parametrize("exit_code", [2, 3, 4])
def test_permanent_exit_codes_are_never_restarted(tmp_path: Path, exit_code: int) -> None:
    """Een verkeerde sleutel of foute config lost zichzelf niet op door wachten."""
    spawner = _Spawner([exit_code, 0])

    result = _make(tmp_path, spawner).run()

    assert result == 1
    assert len(spawner.started) == 1


def test_permanent_failure_status_tells_the_user_what_to_do(tmp_path: Path) -> None:
    supervisor = _make(tmp_path, _Spawner([4]))

    supervisor.run()

    status = read_status(supervisor.status_path)
    assert status["state"] == STATUS_FAILED
    assert status["reason"] == "permanent_error"
    assert "sleutel" in status["message"].lower()
    assert status["advice"]


def test_restart_limit_is_enforced_and_explained(tmp_path: Path) -> None:
    spawner = _Spawner([1, 1, 1, 1, 1, 1])
    supervisor = _make(tmp_path, spawner, policy=_policy(max_restarts=3))

    result = supervisor.run()

    assert result == 1
    assert len(spawner.started) == 3, "na drie herstarts binnen het venster stopt het"
    status = read_status(supervisor.status_path)
    assert status["state"] == STATUS_FAILED
    assert status["reason"] == "restart_limit_reached"
    assert "diagnose.bat" in status["advice"]


def test_spawn_failure_is_reported_instead_of_crashing(tmp_path: Path) -> None:
    def failing_spawn(command, cwd):
        raise OSError("kan het programma niet vinden")

    supervisor = Supervisor(
        ["python", "run_trader_loop.py"],
        policy=_policy(),
        cwd=tmp_path,
        status_path=tmp_path / "state" / "supervisor_status.json",
        spawn=failing_spawn,
        sleep=lambda _s: None,
    )

    assert supervisor.run() == 1
    status = read_status(supervisor.status_path)
    assert status["state"] == STATUS_FAILED
    assert status["reason"] == "spawn_failed"


# --------------------------------------------------------------------------
# Stoppen
# --------------------------------------------------------------------------


def test_stop_request_before_start_exits_immediately(tmp_path: Path) -> None:
    spawner = _Spawner([0])
    supervisor = _make(tmp_path, spawner)
    supervisor.request_stop()

    assert supervisor.run() == 0
    assert spawner.started == []


def test_hanging_child_is_force_stopped_after_the_grace_period(tmp_path: Path) -> None:
    hanging = _HangingProcess(pid=4242)
    supervisor = Supervisor(
        ["python", "run_trader_loop.py"],
        policy=_policy(graceful_stop_seconds=0.01),
        cwd=tmp_path,
        status_path=tmp_path / "state" / "supervisor_status.json",
        spawn=lambda command, cwd: hanging,
        sleep=lambda _s: None,
    )
    supervisor._process = hanging

    supervisor._stop_child()

    assert hanging.stop_requested is True
    assert hanging.killed is True, "een proces dat niet reageert wordt alsnog gestopt"


# --------------------------------------------------------------------------
# Statusbestand
# --------------------------------------------------------------------------


def test_status_is_written_atomically_and_stays_valid_json(tmp_path: Path) -> None:
    supervisor = _make(tmp_path, _Spawner([0]))

    supervisor.run()

    raw = supervisor.status_path.read_text(encoding="utf-8")
    assert json.loads(raw)["state"] == STATUS_STOPPED
    leftovers = list(supervisor.status_path.parent.glob("*.tmp"))
    assert leftovers == [], "er blijven geen tijdelijke bestanden achter"


def test_read_status_handles_a_missing_file(tmp_path: Path) -> None:
    status = read_status(tmp_path / "bestaat-niet.json")

    assert status["state"] == STATUS_STOPPED
    assert status["reason"] == "never_started"


def test_read_status_handles_a_corrupt_file(tmp_path: Path) -> None:
    broken = tmp_path / "kapot.json"
    broken.write_text("{dit is geen json", encoding="utf-8")

    status = read_status(broken)

    assert status["state"] == "unknown"
    assert status["reason"] == "status_unreadable"


def test_running_status_contains_no_absolute_interpreter_path(tmp_path: Path) -> None:
    """Het statusbestand gaat naar de browser; daar hoort geen mappenstructuur in."""
    supervisor = Supervisor(
        ["/home/iemand/geheimemap/.venv/bin/python", "run_trader_loop.py"],
        policy=_policy(),
        cwd=tmp_path,
        status_path=tmp_path / "state" / "supervisor_status.json",
        spawn=_Spawner([0]),
        sleep=lambda _s: None,
    )

    supervisor.run()
    payload = supervisor.status_path.read_text(encoding="utf-8")

    assert "geheimemap" not in payload
    assert "python run_trader_loop.py" in json.loads(payload)["command"]


def test_supervisor_policy_from_env_reads_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_SUPERVISOR_MAX_RESTARTS", "42")
    monkeypatch.setenv("JARVIS_SUPERVISOR_WINDOW", "600")

    policy = SupervisorPolicy.from_env()

    assert policy.max_restarts == 42
    assert policy.restart_window_seconds == pytest.approx(600.0)


def test_supervisor_policy_from_env_survives_nonsense(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JARVIS_SUPERVISOR_WINDOW", "een uurtje")

    policy = SupervisorPolicy.from_env()

    assert policy.restart_window_seconds == SupervisorPolicy.restart_window_seconds


def test_running_state_is_published_while_the_bot_is_up(tmp_path: Path) -> None:
    supervisor = _make(tmp_path, _Spawner([0]))
    seen: list[str] = []
    original = supervisor._publish

    def capture(state, **extra):
        seen.append(state)
        return original(state, **extra)

    supervisor._publish = capture  # type: ignore[method-assign]
    supervisor.run()

    assert STATUS_RUNNING in seen
