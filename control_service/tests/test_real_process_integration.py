"""Integratietest met échte processen: starten, stoppen, opruimen.

Alle andere tests vervangen het aanmaken van processen door een nepklasse. Dat
is bewust -- het houdt ze snel en voorspelbaar -- maar het bewijst niet dat de
twee processen elkaar in werkelijkheid ook vinden. Precies daar zat een bug die
geen enkele unittest zag: een afgesloten bewaker werd als draaiend gelezen,
waardoor de Start-knop in de extensie geblokkeerd bleef voor een bot die
allang gestopt was.

Deze tests starten daarom een echte bewaker met een echt kindproces. Er wordt
nooit een handelsmotor geladen en er gaat geen enkele aanroep naar een beurs:
het "botproces" is een Python dat slaapt of meteen afsluit.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from bot.supervisor import read_status
from control_service.process_manager import ProcessManager

#: Ruim genoeg voor een trage machine, kort genoeg om de suite niet op te houden.
TIMEOUT_SECONDS = 30.0

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Deze test stuurt processen aan op POSIX-manier; op Windows draait hij handmatig.",
)


def _supervisor_script(workdir: Path, bot_command: str) -> Path:
    """Een echte bewaker die een echt kindproces bewaakt.

    De statusbestanden wijzen naar de tijdelijke map, zodat deze test nooit de
    echte state/ van het project aanraakt.
    """
    script = workdir / "bewaker.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})\n"
        "from pathlib import Path\n"
        "from bot.supervisor import Supervisor, SupervisorPolicy\n"
        f"W = Path({str(workdir)!r})\n"
        "Supervisor(\n"
        f"    [sys.executable, '-c', {bot_command!r}],\n"
        "    policy=SupervisorPolicy(graceful_stop_seconds=10, max_restarts=1),\n"
        "    cwd=W,\n"
        "    status_path=W / 'state' / 'supervisor_status.json',\n"
        "    stop_flag_path=W / 'state' / 'supervisor_stop_requested',\n"
        ").run()\n",
        encoding="utf-8",
    )
    return script


def _manager(workdir: Path) -> ProcessManager:
    return ProcessManager(
        project_root=workdir,
        pid_path=workdir / "state" / "control_supervisor.pid",
        status_path=workdir / "state" / "supervisor_status.json",
        stop_flag_path=workdir / "state" / "supervisor_stop_requested",
    )


def _wait_for_state(manager: ProcessManager, state: str, timeout: float = TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if read_status(manager.status_path).get("state") == state:
            return True
        time.sleep(0.05)
    return False


def _wait_until_gone(manager: ProcessManager, timeout: float = TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not manager.is_running():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture()
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "state").mkdir()
    return tmp_path


def test_a_running_bot_is_stopped_cleanly_and_leaves_nothing_behind(workdir: Path) -> None:
    """Het pad waar een bug betekent: je kunt je handelsbot niet stoppen."""
    manager = _manager(workdir)
    script = _supervisor_script(workdir, "import time; time.sleep(600)")
    supervisor = subprocess.Popen([sys.executable, str(script)])
    manager._write_pid(supervisor.pid)

    try:
        assert _wait_for_state(manager, "running"), "de bewaker meldde zich niet als draaiend"
        bot_pid = read_status(manager.status_path).get("pid")
        assert bot_pid, "de bewaker noemt het pid van het botproces niet"
        assert manager.status()["running"] is True

        result = manager.stop(timeout=TIMEOUT_SECONDS)

        assert result.ok is True, result.message
        assert manager.status()["running"] is False
        assert manager.status()["state"] == "stopped"
        assert not manager.pid_path.exists(), "het pid-bestand blijft achter"
        assert not manager.stop_flag_path.exists(), "de stopvlag blijft achter en houdt de bot uit"

        supervisor.wait(timeout=TIMEOUT_SECONDS)
        assert supervisor.returncode == 0
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=10)


def test_stopping_also_ends_the_bot_process_not_just_the_supervisor(workdir: Path) -> None:
    """Een achtergebleven botproces zou blijven handelen zonder dat iemand het ziet."""
    manager = _manager(workdir)
    script = _supervisor_script(workdir, "import time; time.sleep(600)")
    supervisor = subprocess.Popen([sys.executable, str(script)])
    manager._write_pid(supervisor.pid)

    try:
        assert _wait_for_state(manager, "running")
        bot_pid = int(read_status(manager.status_path)["pid"])

        manager.stop(timeout=TIMEOUT_SECONDS)
        supervisor.wait(timeout=TIMEOUT_SECONDS)

        # Het botproces was een kind van de bewaker; met de bewaker weg mag het
        # niet meer bestaan. Een verweesd proces zou blijven draaien.
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline and Path(f"/proc/{bot_pid}").exists():
            time.sleep(0.05)

        assert not Path(f"/proc/{bot_pid}").exists(), "het botproces draait nog"
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=10)


def _wait_until_zombie(pid: int, timeout: float = TIMEOUT_SECONDS) -> bool:
    """Wacht tot het proces afgesloten is maar nog niet opgeruimd.

    Dit is de toestand die de bug veroorzaakte, dus de test moet hem echt
    bereiken. Zou de test het proces zelf met ``wait()`` opruimen, dan bestaat
    de zombie nooit en bewijst de test niets.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
                if handle.read().split(") ", 1)[1].split()[0] == "Z":
                    return True
        except (OSError, IndexError):
            return False
        time.sleep(0.02)
    return False


def test_a_supervisor_that_exits_is_never_reported_as_running(workdir: Path) -> None:
    """De regressie waarvoor deze module bestaat.

    Een afgesloten kindproces blijft op POSIX als zombie in de proceslijst
    staan en beantwoordt signaal 0 nog gewoon. De statusvraag las dat als
    "draait", terwijl de bot met een foutcode gestopt was -- en de Start-knop
    in de extensie bleef daardoor uitgeschakeld.
    """
    manager = _manager(workdir)
    script = _supervisor_script(workdir, "raise SystemExit(0)")
    supervisor = subprocess.Popen([sys.executable, str(script)])
    manager._write_pid(supervisor.pid)

    try:
        # Bewust géén supervisor.wait() hier: dat zou de zombie opruimen en de
        # test langs de bug heen laten lopen.
        assert _wait_until_zombie(supervisor.pid), "de zombietoestand werd niet bereikt"

        assert manager.status()["running"] is False, "een afgesloten bewaker geldt nog als draaiend"
        assert not manager.pid_path.exists(), "het pid-bestand wordt opgeruimd"
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
        try:
            supervisor.wait(timeout=10)
        except (subprocess.TimeoutExpired, ChildProcessError):
            pass


def test_starting_after_a_stopped_bot_is_allowed_again(workdir: Path) -> None:
    """Anders blijft de Start-knop uitgeschakeld voor een bot die niet draait."""
    manager = _manager(workdir)
    script = _supervisor_script(workdir, "raise SystemExit(0)")
    supervisor = subprocess.Popen([sys.executable, str(script)])
    manager._write_pid(supervisor.pid)

    try:
        assert _wait_until_zombie(supervisor.pid)

        assert manager.running_pid() is None, "een nieuwe start zou geweigerd worden"
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
        try:
            supervisor.wait(timeout=10)
        except (subprocess.TimeoutExpired, ChildProcessError):
            pass
