"""Start, stop en herstart de bot -- via de supervisor, nooit rechtstreeks.

De control-service start nooit ``run_trader_loop.py`` zelf. Hij start
``bot.supervisor``, en die bewaakt de bot. Anders zou een crash van de bot
alleen zichtbaar zijn zolang de browser toevallig openstaat, en zou er niets
herstarten wanneer de extension dicht is.

Stoppen gaat via een vlagbestand in plaats van een signaal. Windows kent geen
SIGTERM zoals POSIX: ``taskkill`` zonder ``/F`` bereikt een Python-console-app
meestal niet, en met ``/F`` krijgt de bot geen kans meer om openstaande
bestanden en verbindingen netjes af te sluiten. Een vlag die de supervisor elke
seconde leest werkt op beide platformen identiek en is altijd netjes.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from bot import supervisor as supervisor_module
from control_service import config

LOGGER = logging.getLogger("jarvis.control.process")

#: Hoe lang er op een nette afsluiting gewacht wordt voordat het hard gaat.
STOP_TIMEOUT_SECONDS = 45.0
#: Hoe lang er gewacht wordt tot de supervisor zichzelf 'running' meldt.
START_TIMEOUT_SECONDS = 20.0
_POLL_INTERVAL = 0.5


@dataclass(frozen=True)
class ActionResult:
    """Uitkomst van start/stop/restart, klaar om als JSON terug te geven."""

    ok: bool
    action: str
    state: str
    message: str
    http_status: int = 200
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "state": self.state,
            "message": self.message,
            "detail": self.detail,
        }


def _pid_alive(pid: int) -> bool:
    """Draait er een proces met dit pid?

    Op POSIX is signaal 0 de standaardmanier om dat te vragen. Op Windows
    bestaat dat niet: daar wordt via de Win32-API een handle geopend en meteen
    weer gesloten. ``tasklist`` aanroepen zou hier ook kunnen, maar dat start
    een proces per statusvraag en de extension vraagt de status elke paar
    seconden op.
    """
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover - alleen op Windows te testen
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Bestaat wel, maar is van een andere gebruiker.
        return True
    except OSError:
        return False
    return True


class ProcessManager:
    """Beheert precies één supervisorproces voor dit project."""

    def __init__(
        self,
        *,
        project_root: Optional[Path] = None,
        pid_path: Optional[Path] = None,
        status_path: Optional[Path] = None,
        stop_flag_path: Optional[Path] = None,
        spawn: Optional[Callable[[list[str], Path], int]] = None,
        pid_alive: Optional[Callable[[int], bool]] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.project_root = project_root or config.PROJECT_ROOT
        self.pid_path = pid_path or config.SUPERVISOR_PID_PATH
        self.status_path = status_path or config.SUPERVISOR_STATUS_PATH
        self.stop_flag_path = stop_flag_path or supervisor_module.STOP_FLAG_PATH
        self._spawn = spawn or _spawn_supervisor
        self._pid_alive = pid_alive or _pid_alive
        self._sleep = sleep
        self._clock = clock

    # -- pid-bestand ------------------------------------------------------

    def _read_pid(self) -> Optional[int]:
        try:
            raw = self.pid_path.read_text(encoding="utf-8").strip()
        except (OSError, ValueError):
            return None
        try:
            pid = int(raw)
        except ValueError:
            LOGGER.warning("Het pid-bestand bevat geen getal; het wordt genegeerd.")
            return None
        return pid if pid > 0 else None

    def _write_pid(self, pid: int) -> None:
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(pid), encoding="utf-8")

    def _clear_pid(self) -> None:
        try:
            self.pid_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:  # pragma: no cover
            LOGGER.warning("Het pid-bestand kon niet verwijderd worden: %s", exc)

    def running_pid(self) -> Optional[int]:
        """Het pid van de draaiende supervisor, of None.

        Ruimt meteen een pid-bestand op dat naar een verdwenen proces wijst;
        anders zou 'start' voor altijd melden dat er al iets draait.
        """
        pid = self._read_pid()
        if pid is None:
            return None
        if self._pid_alive(pid):
            return pid
        LOGGER.info("Het pid-bestand wees naar proces %s, dat niet meer bestaat. Opgeruimd.", pid)
        self._clear_pid()
        return None

    def is_running(self) -> bool:
        return self.running_pid() is not None

    # -- status -----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Samengestelde status: het procesfeit plus wat de supervisor meldt."""
        pid = self.running_pid()
        published = supervisor_module.read_status(self.status_path)
        state = published.get("state", "unknown")

        if pid is None and state in {
            supervisor_module.STATUS_RUNNING,
            supervisor_module.STATUS_STARTING,
            supervisor_module.STATUS_COOLDOWN,
        }:
            # Het statusbestand is achtergebleven doordat het proces hard
            # gestopt is (afsluiten van Windows, taakbeheer). Het procesfeit
            # wint: doen alsof de bot draait is het ergste wat hier kan.
            state = supervisor_module.STATUS_STOPPED
            published = dict(published)
            published["message"] = (
                "JARVIS draait niet meer. Het proces is gestopt zonder zichzelf af te melden."
            )
            published["reason"] = "process_gone"

        return {
            "state": state,
            "running": pid is not None,
            "supervisor_pid": pid,
            "stop_requested": self.stop_flag_path.exists(),
            "supervisor": {
                key: value
                for key, value in published.items()
                # 'command' kan het volledige pad naar de interpreter bevatten;
                # de supervisor kort dat al in, maar hier nog een keer filteren
                # kost niets en houdt de response vrij van mappenstructuur.
                if key not in {"supervisor_pid"}
            },
        }

    # -- acties -----------------------------------------------------------

    def start(self) -> ActionResult:
        pid = self.running_pid()
        if pid is not None:
            return ActionResult(
                ok=True,
                action="start",
                state=supervisor_module.STATUS_RUNNING,
                message="JARVIS draait al.",
                detail=f"De bewaker draait als proces {pid}.",
            )

        # Een achtergebleven stopvlag zou de nieuwe supervisor meteen weer
        # afsluiten. De supervisor ruimt hem zelf ook op; hier alvast, zodat
        # de statusvraag er nooit nog eentje ziet staan.
        self._clear_stop_flag()

        command = [sys.executable, "-m", "bot.supervisor"]
        try:
            pid = self._spawn(command, self.project_root)
        except OSError as exc:
            LOGGER.error("De bewaker kon niet gestart worden: %s", exc)
            return ActionResult(
                ok=False,
                action="start",
                state=supervisor_module.STATUS_FAILED,
                message="JARVIS kon niet gestart worden.",
                detail="Het bewakingsproces startte niet. Draai diagnose.bat voor een volledige controle.",
                http_status=500,
            )

        self._write_pid(pid)
        LOGGER.info("Bewaker gestart als proces %s.", pid)

        deadline = self._clock() + START_TIMEOUT_SECONDS
        while self._clock() < deadline:
            published = supervisor_module.read_status(self.status_path)
            state = published.get("state")
            if state == supervisor_module.STATUS_RUNNING:
                return ActionResult(
                    ok=True, action="start", state=state, message="JARVIS is gestart."
                )
            if state == supervisor_module.STATUS_FAILED:
                return ActionResult(
                    ok=False,
                    action="start",
                    state=state,
                    message=published.get("message") or "JARVIS kon niet starten.",
                    detail=published.get("advice", ""),
                    http_status=409,
                )
            if not self._pid_alive(pid):
                self._clear_pid()
                return ActionResult(
                    ok=False,
                    action="start",
                    state=supervisor_module.STATUS_FAILED,
                    message="JARVIS stopte direct na het starten.",
                    detail="Kijk in logs/supervisor.log wat daar staat, of draai diagnose.bat.",
                    http_status=500,
                )
            self._sleep(_POLL_INTERVAL)

        # Het proces leeft nog maar heeft zich niet gemeld. Dat is geen fout;
        # op een trage pc duurt het laden van de handelsmotor gewoon langer.
        return ActionResult(
            ok=True,
            action="start",
            state=supervisor_module.STATUS_STARTING,
            message="JARVIS is aan het opstarten.",
            detail="Het opstarten duurt langer dan gebruikelijk. Ververs de status over een halve minuut.",
        )

    def _clear_stop_flag(self) -> None:
        try:
            self.stop_flag_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:  # pragma: no cover
            LOGGER.warning("De stopvlag kon niet verwijderd worden: %s", exc)

    def _request_stop_flag(self) -> None:
        self.stop_flag_path.parent.mkdir(parents=True, exist_ok=True)
        self.stop_flag_path.write_text("stop", encoding="utf-8")

    def stop(self, *, timeout: float = STOP_TIMEOUT_SECONDS) -> ActionResult:
        pid = self.running_pid()
        if pid is None:
            self._clear_stop_flag()
            return ActionResult(
                ok=True,
                action="stop",
                state=supervisor_module.STATUS_STOPPED,
                message="JARVIS draaide al niet.",
            )

        LOGGER.info("Stopverzoek voor proces %s.", pid)
        self._request_stop_flag()

        deadline = self._clock() + timeout
        while self._clock() < deadline:
            if not self._pid_alive(pid):
                self._clear_pid()
                self._clear_stop_flag()
                LOGGER.info("JARVIS is netjes gestopt.")
                return ActionResult(
                    ok=True,
                    action="stop",
                    state=supervisor_module.STATUS_STOPPED,
                    message="JARVIS is gestopt.",
                )
            self._sleep(_POLL_INTERVAL)

        LOGGER.warning("Proces %s reageerde niet binnen %.0f seconden op het stopverzoek.", pid, timeout)
        return ActionResult(
            ok=False,
            action="stop",
            state="stopping",
            message="JARVIS reageert niet op het stopverzoek.",
            detail=(
                "Het stoppen duurt langer dan verwacht. De bot maakt waarschijnlijk een lopende "
                "handelscyclus af. Wacht nog even en probeer het opnieuw; het stopverzoek blijft staan."
            ),
            http_status=504,
        )

    def restart(self, *, timeout: float = STOP_TIMEOUT_SECONDS) -> ActionResult:
        stopped = self.stop(timeout=timeout)
        if not stopped.ok:
            return ActionResult(
                ok=False,
                action="restart",
                state=stopped.state,
                message="JARVIS kon niet herstart worden omdat hij niet stopte.",
                detail=stopped.detail,
                http_status=stopped.http_status,
            )
        started = self.start()
        return ActionResult(
            ok=started.ok,
            action="restart",
            state=started.state,
            message="JARVIS is herstart." if started.ok else started.message,
            detail=started.detail,
            http_status=started.http_status,
        )


def _spawn_supervisor(command: list[str], cwd: Path) -> int:
    """Start de supervisor los van dit proces en geef het pid terug.

    Los starten is essentieel: als de control-service later stopt of herstart,
    moet de bot gewoon blijven draaien. Op Windows zorgt DETACHED_PROCESS er
    bovendien voor dat er geen tweede zwart venster verschijnt.
    """
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":  # pragma: no cover - Windows-specifiek
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs).pid
