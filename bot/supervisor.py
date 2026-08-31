"""Procesbewaking: de bot mag nooit stil verdwijnen.

Zonder deze laag geldt: één onverwachte exceptie buiten de hoofdlus en het
venster van de gebruiker is leeg, zonder uitleg. De supervisor start de bot als
kindproces en handelt elke afloop af volgens één vast patroon:

    crash -> log -> opruimen -> cooldown -> herstart -> bewaken

Met twee remmen die een eindeloze crashlus voorkomen:

1. **Permanente fouten herstarten niet.** ``run_trader_loop.py`` sluit af met
   een eigen code als de configuratie of de sleutels niet kloppen (2, 3, 4).
   Dat verandert niet door het nog eens te proberen, dus de supervisor stopt
   en legt uit wat er moet gebeuren.
2. **Te vaak achter elkaar crashen stopt ook.** Meer dan ``max_restarts``
   herstarts binnen ``restart_window_seconds`` betekent dat er iets structureel
   mis is.

De wachttijd tussen herstarts loopt exponentieel op en wordt teruggezet zodra
een run lang genoeg stabiel draaide. Zo herstelt een korte netwerkstoring
binnen seconden, terwijl een kapotte installatie de machine niet bezet houdt.

Status wordt weggeschreven naar ``state/supervisor_status.json`` zodat de
control-service en de Chrome Extension kunnen tonen wat er aan de hand is.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from bot.resilience import RetryPolicy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "state"
LOGS_DIR = PROJECT_ROOT / "logs"
STATUS_PATH = STATE_DIR / "supervisor_status.json"

#: Vlagbestand waarmee een ander proces (de control-service, STOP-JARVIS.bat)
#: om een nette afsluiting vraagt. Een bestand in plaats van een signaal,
#: omdat Windows geen SIGTERM kent zoals POSIX: `taskkill` zonder /F bereikt
#: een Python-console-app vaak niet, en met /F krijgt de bot geen kans meer om
#: zijn openstaande bestanden en verbindingen netjes af te sluiten.
STOP_FLAG_PATH = STATE_DIR / "supervisor_stop_requested"

LOGGER = logging.getLogger("jarvis.supervisor")

#: Afsluitcodes van run_trader_loop.py die een *configuratie*probleem melden.
#: Herstarten lost die niet op; dan moet de gebruiker iets doen.
PERMANENT_EXIT_CODES: dict[int, str] = {
    2: (
        "De opstartcontrole van de handelsmotor blokkeerde de start. "
        "Er staat een instelling in .env die niet bij de veilige runtime past."
    ),
    3: (
        "Er draait al een JARVIS-bot (procesvergrendeling). "
        "Stop die eerst met STOP-JARVIS.bat."
    ),
    4: (
        "De API-sleutels ontbreken of werden afgewezen. "
        "Draai INSTALLEREN-WINDOWS.bat of: .venv\\Scripts\\python -m tools.connect_services"
    ),
}

STATUS_STARTING = "starting"
STATUS_RUNNING = "running"
STATUS_COOLDOWN = "cooldown"
STATUS_STOPPED = "stopped"
STATUS_FAILED = "failed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _seconds(value: float) -> str:
    """Leesbare seconden: '0 seconden' voor een wachttijd van 0,4 klopt niet."""
    return f"{value:.1f}" if value < 10 else f"{value:.0f}"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Schrijf via een tijdelijk bestand, zodat een lezer nooit half JSON ziet.

    De control-service leest dit bestand terwijl de supervisor het schrijft;
    zonder de rename-truc levert dat op Windows regelmatig een leesfout op.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), prefix=path.name, suffix=".tmp", delete=False
    )
    try:
        with handle:
            json.dump(payload, handle, indent=2, sort_keys=True, ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


@dataclass(frozen=True)
class SupervisorPolicy:
    """Wanneer wel en wanneer niet herstarten."""

    max_restarts: int = 10
    restart_window_seconds: float = 3600.0
    #: Zolang draaien telt als "het werkte" en zet de backoff terug op nul.
    stable_run_seconds: float = 300.0
    #: Hoe lang wachten op een nette afsluiting voordat het proces hard stopt.
    graceful_stop_seconds: float = 30.0
    backoff: RetryPolicy = RetryPolicy(
        max_attempts=10, base_delay=5.0, multiplier=2.0, max_delay=300.0, jitter=0.2
    )

    @classmethod
    def from_env(cls) -> "SupervisorPolicy":
        def _num(name: str, default: float) -> float:
            raw = (os.environ.get(name) or "").strip()
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                LOGGER.warning("%s=%r is geen getal; %s wordt gebruikt.", name, raw, default)
                return default

        return cls(
            max_restarts=int(_num("JARVIS_SUPERVISOR_MAX_RESTARTS", cls.max_restarts)),
            restart_window_seconds=_num("JARVIS_SUPERVISOR_WINDOW", cls.restart_window_seconds),
            stable_run_seconds=_num("JARVIS_SUPERVISOR_STABLE_SECONDS", cls.stable_run_seconds),
            graceful_stop_seconds=_num("JARVIS_SUPERVISOR_STOP_SECONDS", cls.graceful_stop_seconds),
            backoff=RetryPolicy.from_env("JARVIS_SUPERVISOR_BACKOFF", max_attempts=10, base_delay=5.0, max_delay=300.0),
        )


class ProcessHandle:
    """Dun laagje om ``subprocess.Popen`` heen, zodat tests het kunnen vervangen."""

    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process

    @property
    def pid(self) -> int:
        return self._process.pid

    def poll(self) -> Optional[int]:
        return self._process.poll()

    def wait(self, timeout: Optional[float] = None) -> int:
        return self._process.wait(timeout=timeout)

    def request_stop(self) -> None:
        """Vraag netjes stoppen: het kindproces mag zijn eigen opruiming doen.

        Op Windows bestaat SIGTERM niet zoals op POSIX; ``terminate()`` is daar
        de juiste aanroep en levert bij een console-app een afsluiting op die
        de bot via KeyboardInterrupt/atexit nog kan afhandelen.
        """
        try:
            self._process.terminate()
        except (OSError, ProcessLookupError):
            pass

    def kill(self) -> None:
        try:
            self._process.kill()
        except (OSError, ProcessLookupError):
            pass


def _spawn_bot(command: Sequence[str], cwd: Path) -> ProcessHandle:
    """Start het kindproces met een eigen procesgroep waar dat kan.

    Een eigen groep zorgt dat een Ctrl+C in het supervisorvenster niet
    tegelijk het kind hard onderbreekt: de supervisor bepaalt zelf wanneer en
    hoe het kind stopt, zodat de opruiming altijd doorloopt.
    """
    kwargs: dict[str, Any] = {"cwd": str(cwd)}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    return ProcessHandle(subprocess.Popen(list(command), **kwargs))


class Supervisor:
    """Houdt één kindproces in de lucht volgens :class:`SupervisorPolicy`."""

    def __init__(
        self,
        command: Optional[Sequence[str]] = None,
        *,
        policy: Optional[SupervisorPolicy] = None,
        cwd: Optional[Path] = None,
        status_path: Optional[Path] = None,
        stop_flag_path: Optional[Path] = None,
        spawn: Optional[Callable[[Sequence[str], Path], ProcessHandle]] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.cwd = cwd or PROJECT_ROOT
        self.command = list(command or [sys.executable, "run_trader_loop.py"])
        self.policy = policy or SupervisorPolicy.from_env()
        self.status_path = status_path or STATUS_PATH
        self.stop_flag_path = stop_flag_path or STOP_FLAG_PATH
        self._spawn = spawn or _spawn_bot
        self._sleep = sleep
        self._clock = clock
        self._log = logger or LOGGER

        self._stop_requested = threading.Event()
        self._process: Optional[ProcessHandle] = None
        self._restart_times: list[float] = []
        self._consecutive_failures = 0
        self.last_status: dict[str, Any] = {}

    # -- status -----------------------------------------------------------

    def _publish(self, state: str, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state": state,
            "updated_at": _now_iso(),
            "pid": self._process.pid if self._process is not None else None,
            "supervisor_pid": os.getpid(),
            "restarts_in_window": len(self._restart_times),
            "max_restarts": self.policy.max_restarts,
            "command": " ".join(Path(part).name if index == 0 else part for index, part in enumerate(self.command)),
        }
        payload.update(extra)
        self.last_status = payload
        try:
            _atomic_write_json(self.status_path, payload)
        except OSError as exc:
            # Statusbestand kwijt is vervelend maar mag de bot niet stoppen.
            self._log.warning("Statusbestand kon niet geschreven worden: %s", exc)
        return payload

    # -- levenscyclus -----------------------------------------------------

    def request_stop(self) -> None:
        """Vraag de supervisor te stoppen; ook bruikbaar vanuit een signalhandler."""
        self._stop_requested.set()
        process = self._process
        if process is not None:
            process.request_stop()

    def _stop_flag_present(self) -> bool:
        """Heeft een ander proces om een nette afsluiting gevraagd?"""
        try:
            return self.stop_flag_path.exists()
        except OSError:  # pragma: no cover - alleen bij een kapot bestandssysteem
            return False

    def _clear_stop_flag(self) -> None:
        try:
            self.stop_flag_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:  # pragma: no cover
            self._log.warning("De stopvlag kon niet verwijderd worden: %s", exc)

    def _stop_child(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        self._log.info("Bot netjes afsluiten (pid %s)...", process.pid)
        process.request_stop()
        try:
            process.wait(timeout=self.policy.graceful_stop_seconds)
            self._log.info("Bot is netjes afgesloten.")
        except subprocess.TimeoutExpired:
            self._log.warning(
                "De bot reageerde niet binnen %.0f seconden; het proces wordt nu geforceerd gestopt.",
                self.policy.graceful_stop_seconds,
            )
            process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._log.error("Het botproces kon niet gestopt worden (pid %s).", process.pid)

    def _window_is_exhausted(self, now: float) -> bool:
        cutoff = now - self.policy.restart_window_seconds
        self._restart_times = [moment for moment in self._restart_times if moment >= cutoff]
        return len(self._restart_times) >= self.policy.max_restarts

    def run(self) -> int:
        """Draai tot de bot netjes stopt of tot herstarten geen zin meer heeft.

        Retourneert 0 bij een nette afsluiting, 1 als de supervisor het opgeeft.
        """
        if self._stop_flag_present():
            # Een achtergebleven vlag van de vorige keer zou de bot meteen weer
            # stoppen. Bij het starten is de vlag per definitie verouderd.
            self._log.info("Oude stopvlag opgeruimd voordat de bot start.")
            self._clear_stop_flag()

        self._log.info("Supervisor gestart. Commando: %s", " ".join(self.command))
        self._log.info(
            "Herstartbeleid: maximaal %s keer per %.0f minuten, wachttijd loopt op tot %.0f seconden.",
            self.policy.max_restarts,
            self.policy.restart_window_seconds / 60,
            self.policy.backoff.max_delay,
        )

        while not self._stop_requested.is_set():
            started_at = self._clock()
            self._publish(STATUS_STARTING)
            try:
                self._process = self._spawn(self.command, self.cwd)
            except OSError as exc:
                self._log.error("De bot kon niet gestart worden: %s", exc)
                self._publish(
                    STATUS_FAILED,
                    reason="spawn_failed",
                    message=f"Het botproces kon niet gestart worden: {exc}",
                    advice="Draai diagnose.bat. Meestal is de installatie onvolledig.",
                )
                return 1

            self._publish(STATUS_RUNNING, started_at=_now_iso())
            self._log.info("Bot draait (pid %s).", self._process.pid)

            exit_code = self._wait_for_child()
            ran_for = self._clock() - started_at

            if self._stop_requested.is_set():
                self._stop_child()
                self._clear_stop_flag()
                self._log.info("Supervisor stopt op verzoek.")
                self._publish(STATUS_STOPPED, reason="stop_requested", exit_code=exit_code)
                return 0

            if exit_code == 0:
                self._log.info("De bot is uit zichzelf netjes gestopt. De supervisor stopt mee.")
                self._publish(STATUS_STOPPED, reason="clean_exit", exit_code=0)
                return 0

            reason = PERMANENT_EXIT_CODES.get(exit_code)
            if reason is not None:
                self._log.error("De bot stopte met code %s. %s", exit_code, reason)
                self._log.error("Herstarten heeft geen zin; dit moet eerst opgelost worden.")
                self._publish(
                    STATUS_FAILED,
                    reason="permanent_error",
                    exit_code=exit_code,
                    message=reason,
                    advice="Los het punt hierboven op en start JARVIS daarna opnieuw.",
                    log_file=str(LOGS_DIR / "supervisor.log"),
                )
                return 1

            if ran_for >= self.policy.stable_run_seconds:
                # Hij heeft lang genoeg gedraaid: dit is een nieuwe storing,
                # geen doorlopende crashlus. Wachttijd terug naar het begin.
                self._consecutive_failures = 0

            self._consecutive_failures += 1
            now = self._clock()
            self._restart_times.append(now)

            if self._window_is_exhausted(now):
                self._log.error(
                    "De bot is %s keer gecrasht binnen %.0f minuten. De supervisor geeft het op.",
                    len(self._restart_times),
                    self.policy.restart_window_seconds / 60,
                )
                self._publish(
                    STATUS_FAILED,
                    reason="restart_limit_reached",
                    exit_code=exit_code,
                    message=(
                        f"De bot crashte {len(self._restart_times)} keer binnen "
                        f"{self.policy.restart_window_seconds / 60:.0f} minuten en is gestopt."
                    ),
                    advice=f"Kijk in {LOGS_DIR / 'loop.log'} wat er misgaat, of draai diagnose.bat.",
                    log_file=str(LOGS_DIR / "supervisor.log"),
                )
                return 1

            wait = self.policy.backoff.delay_for(min(self._consecutive_failures + 1, self.policy.backoff.max_attempts))
            self._log.warning(
                "De bot stopte onverwacht met code %s na %s seconden. "
                "Herstart %s van %s volgt over %s seconden.",
                exit_code,
                _seconds(ran_for),
                len(self._restart_times),
                self.policy.max_restarts,
                _seconds(wait),
            )
            self._publish(
                STATUS_COOLDOWN,
                exit_code=exit_code,
                cooldown_seconds=round(wait, 1),
                message=(
                    f"De bot stopte onverwacht (code {exit_code}). "
                    f"JARVIS wacht {_seconds(wait)} seconden en probeert het dan opnieuw."
                ),
                log_file=str(LOGS_DIR / "loop.log"),
            )
            self._cooldown_sleep(wait)

        self._stop_child()
        self._clear_stop_flag()
        self._publish(STATUS_STOPPED, reason="stop_requested")
        return 0

    def _cooldown_sleep(self, seconds: float) -> None:
        """Wacht, maar reageer ondertussen op een stopverzoek.

        Eén lange slaap zou betekenen dat 'stoppen' tot vijf minuten kan duren
        terwijl de bot niet eens draait.
        """
        remaining = seconds
        while remaining > 0 and not self._stop_requested.is_set():
            if self._stop_flag_present():
                self._stop_requested.set()
                break
            step = min(1.0, remaining)
            self._sleep(step)
            remaining -= step

    def _wait_for_child(self) -> int:
        """Wacht op het kind, maar blijf reageren op een stopverzoek.

        Wachten in stukjes in plaats van één blokkerende ``wait()``: anders
        blijft een stopverzoek liggen tot het kind uit zichzelf stopt.
        """
        process = self._process
        assert process is not None
        while True:
            if self._stop_flag_present():
                self._log.info("Stopverzoek ontvangen via %s.", self.stop_flag_path.name)
                self._stop_requested.set()
            if self._stop_requested.is_set():
                return process.poll() if process.poll() is not None else -1
            try:
                return process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                continue


def read_status(status_path: Optional[Path] = None) -> dict[str, Any]:
    """Lees het statusbestand. Geeft altijd een bruikbaar antwoord terug."""
    path = status_path or STATUS_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"state": STATUS_STOPPED, "reason": "never_started", "message": "JARVIS is nog niet gestart."}
    except (OSError, ValueError) as exc:
        return {
            "state": "unknown",
            "reason": "status_unreadable",
            "message": f"Het statusbestand kon niet gelezen worden: {type(exc).__name__}.",
        }
    return payload if isinstance(payload, dict) else {"state": "unknown", "reason": "status_malformed"}


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - [supervisor] %(message)s",
        handlers=[
            logging.FileHandler(LOGS_DIR / "supervisor.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main(argv: Optional[list[str]] = None) -> int:
    """Entrypoint: ``python -m bot.supervisor [-- extra argumenten voor de bot]``."""
    args = list(sys.argv[1:] if argv is None else argv)
    _configure_logging()

    command = [sys.executable, str(PROJECT_ROOT / "run_trader_loop.py"), *args]
    supervisor = Supervisor(command)

    def _handle_signal(signum, _frame):  # pragma: no cover - vereist een echt signaal
        LOGGER.info("Stopsignaal %s ontvangen; JARVIS wordt netjes afgesloten.", signum)
        supervisor.request_stop()

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _handle_signal)
            except (ValueError, OSError):  # pragma: no cover - niet elke omgeving staat dit toe
                pass

    try:
        return supervisor.run()
    except KeyboardInterrupt:  # pragma: no cover - handmatige Ctrl+C
        supervisor.request_stop()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
