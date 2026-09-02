"""Gecontroleerd herstel bij tijdelijke storingen.

Een tijdelijke netwerkstoring, een timeout of een rate limit mag de bot nooit
laten crashen, en mag hem ook nooit in een agressieve herhaallus duwen die de
provider plat blijft bevragen. Deze module levert de drie bouwstenen die daar
voor nodig zijn:

* :class:`RetryPolicy` -- hoeveel pogingen, hoe lang wachten, met jitter.
* :func:`retry_call`  -- voert een aanroep uit volgens zo'n policy.
* :class:`CircuitBreaker` -- stopt na herhaald falen tijdelijk *alle* pogingen,
  zodat een provider die plat ligt niet elke minuut opnieuw bestookt wordt.

Kernonderscheid, en de reden dat dit een eigen module is: een **tijdelijke**
fout (netwerk, DNS, timeout, 429, 5xx) wordt opnieuw geprobeerd; een
**permanente** fout (401/403 -- verkeerde of ingetrokken sleutel, 400 --
verkeerd verzoek) wordt direct doorgegeven. Een ingetrokken API-sleutel 24 uur
lang opnieuw proberen helpt niemand, en een internetstoring als "verkeerde
sleutel" rapporteren stuurt de gebruiker het verkeerde bos in.

Alles is configureerbaar via omgevingsvariabelen; de standaardwaarden zijn
bewust rustig gekozen.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Optional, TypeVar

LOGGER = logging.getLogger(__name__)

T = TypeVar("T")

# --------------------------------------------------------------------------
# Classificatie: tijdelijk of permanent?
# --------------------------------------------------------------------------

#: HTTP-codes die een herhaling verdienen. 408 = request timeout,
#: 425 = too early, 429 = rate limit, 5xx = storing aan de serverkant.
TRANSIENT_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504, 507, 509, 522, 524})

#: Namen van exceptieklassen die op transport- of netwerkniveau falen. Op naam
#: vergelijken in plaats van importeren houdt deze module vrij van een harde
#: afhankelijkheid op requests of httpx: beide zijn optioneel voor de
#: onderdelen die deze module gebruiken, en een import hier zou de installer
#: laten stuklopen op een pakket dat nog niet geinstalleerd is.
_TRANSIENT_EXCEPTION_NAMES = frozenset(
    {
        "ConnectError",
        "ConnectionError",
        "ConnectionAbortedError",
        "ConnectionResetError",
        "ConnectTimeout",
        "ChunkedEncodingError",
        "IncompleteRead",
        "InternalServerError",
        "NetworkError",
        "PoolTimeout",
        "ProtocolError",
        "ProxyError",
        "ReadError",
        "ReadTimeout",
        "RemoteDisconnected",
        "RemoteProtocolError",
        "SSLError",
        "ServiceUnavailableError",
        "TimeoutException",
        "TimeoutError",
        "TooManyRedirects",
        "WriteError",
        "WriteTimeout",
        "socket.timeout",
        "gaierror",
        "herror",
    }
)

#: Namen die juist *nooit* opnieuw geprobeerd moeten worden, ook niet als een
#: bibliotheek ze van een netwerk-basisklasse laat erven.
_PERMANENT_EXCEPTION_NAMES = frozenset(
    {
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "BadRequestError",
        "UnprocessableEntityError",
    }
)


def _status_code_of(exc: BaseException) -> Optional[int]:
    """Haal een HTTP-status uit een exceptie, ongeacht de bibliotheek."""
    for attribute in ("status_code", "status", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int):
            return value
    return None


def is_transient(exc: BaseException) -> bool:
    """True als het zinvol is deze fout opnieuw te proberen.

    Wordt bewust conservatief gehouden: bij twijfel *niet* opnieuw proberen.
    Een onbekende fout blind herhalen kan een order dubbel insturen, en dat
    is in een tradingbot erger dan een nette foutmelding.
    """
    for klass in type(exc).__mro__:
        if klass.__name__ in _PERMANENT_EXCEPTION_NAMES:
            return False

    status = _status_code_of(exc)
    if status is not None:
        return status in TRANSIENT_STATUS_CODES

    for klass in type(exc).__mro__:
        if klass.__name__ in _TRANSIENT_EXCEPTION_NAMES:
            return True

    # OSError dekt op zowel Windows als Linux de socket- en DNS-fouten die
    # geen eigen klasse hebben (WinError 10054/10060, ECONNRESET, ...).
    return isinstance(exc, OSError)


# --------------------------------------------------------------------------
# Retry-policy
# --------------------------------------------------------------------------


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        LOGGER.warning("%s=%r is geen getal; standaardwaarde %s wordt gebruikt.", name, raw, default)
        return default
    if value < minimum:
        LOGGER.warning("%s=%s is te laag; %s wordt gebruikt.", name, value, minimum)
        return minimum
    return value


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    return int(_env_float(name, float(default), minimum=float(minimum)))


@dataclass(frozen=True)
class RetryPolicy:
    """Hoeveel pogingen en hoe lang ertussen gewacht wordt.

    ``max_attempts`` telt de eerste poging mee: 3 betekent één poging plus
    twee herhalingen. ``cooldown_seconds`` is de extra rustpauze *nadat* alle
    pogingen op zijn -- daar wacht :func:`retry_call` zelf niet op, maar de
    aanroeper (of de circuit breaker) kan hem uitlezen.
    """

    max_attempts: int = 3
    base_delay: float = 2.0
    max_delay: float = 60.0
    multiplier: float = 2.0
    jitter: float = 0.25
    cooldown_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts moet minstens 1 zijn")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("wachttijden mogen niet negatief zijn")
        if self.multiplier < 1:
            raise ValueError("multiplier moet minstens 1 zijn")
        if not 0.0 <= self.jitter <= 1.0:
            raise ValueError("jitter moet tussen 0 en 1 liggen")

    @classmethod
    def from_env(cls, prefix: str = "JARVIS_RETRY", **overrides: Any) -> "RetryPolicy":
        """Bouw een policy uit omgevingsvariabelen.

        Met prefix ``JARVIS_RETRY`` leest dit ``JARVIS_RETRY_MAX_ATTEMPTS``,
        ``JARVIS_RETRY_BASE_DELAY``, enzovoort. Ontbrekende of onleesbare
        waarden vallen terug op de standaard, met een waarschuwing in het log.

        ``overrides`` levert de *standaardwaarden* voor deze aanroepsite; een
        waarde uit de omgeving gaat daar altijd overheen. Andersom zou het
        instellen van bijvoorbeeld JARVIS_RECOVERY_BASE_DELAY in .env geen
        enkel effect hebben zodra de aanroeper een eigen standaard meegeeft --
        de instelling zou er wel zijn maar niets doen.
        """
        defaults = replace(cls(), **overrides) if overrides else cls()
        return cls(
            max_attempts=_env_int(f"{prefix}_MAX_ATTEMPTS", defaults.max_attempts, minimum=1),
            base_delay=_env_float(f"{prefix}_BASE_DELAY", defaults.base_delay),
            max_delay=_env_float(f"{prefix}_MAX_DELAY", defaults.max_delay),
            multiplier=_env_float(f"{prefix}_MULTIPLIER", defaults.multiplier, minimum=1.0),
            jitter=min(1.0, _env_float(f"{prefix}_JITTER", defaults.jitter)),
            cooldown_seconds=_env_float(f"{prefix}_COOLDOWN", defaults.cooldown_seconds),
        )

    def delay_for(self, attempt: int, *, rng: Optional[random.Random] = None) -> float:
        """Wachttijd vóór poging ``attempt`` (1-gebaseerd; poging 1 wacht niet).

        Exponentieel oplopend en afgetopt op ``max_delay``. De jitter voorkomt
        dat meerdere onderdelen die tegelijk faalden ook weer exact tegelijk
        opnieuw beginnen -- anders komt de storing als één golf terug.
        """
        if attempt <= 1:
            return 0.0
        raw = self.base_delay * (self.multiplier ** (attempt - 2))
        capped = min(raw, self.max_delay)
        if self.jitter <= 0:
            return capped
        spread = capped * self.jitter
        source = rng or random
        return max(0.0, capped + source.uniform(-spread, spread))


#: Rustige standaard voor alles wat met een externe API praat.
DEFAULT_POLICY = RetryPolicy()


class RetryExhausted(RuntimeError):
    """Alle pogingen zijn op. De laatste oorzaak zit in ``__cause__``.

    Bevat bewust alleen een omschrijving van de *actie*, nooit argumenten van
    de aanroep: die kunnen een API-sleutel bevatten en foutmeldingen belanden
    in logbestanden.
    """

    def __init__(self, description: str, attempts: int, last_error: BaseException) -> None:
        super().__init__(
            f"{description}: {attempts} poging(en) mislukt. "
            f"Laatste fout: {type(last_error).__name__}: {last_error}"
        )
        self.description = description
        self.attempts = attempts
        self.last_error = last_error


# --------------------------------------------------------------------------
# Circuit breaker
# --------------------------------------------------------------------------


class CircuitBreakerOpen(RuntimeError):
    """De breaker staat open; er wordt nu bewust niets geprobeerd."""

    def __init__(self, name: str, retry_after: float) -> None:
        super().__init__(
            f"{name} is tijdelijk uitgeschakeld na herhaalde storingen. "
            f"Nieuwe poging over {retry_after:.0f} seconden."
        )
        self.name = name
        self.retry_after = retry_after


class CircuitBreaker:
    """Blokkeert aanroepen zolang een provider aantoonbaar plat ligt.

    Drie toestanden:

    ``closed``     alles gaat door (normale werking).
    ``open``       elke aanroep wordt direct geweigerd; pas na ``cooldown``
                   seconden mag er weer iets geprobeerd worden.
    ``half_open``  precies één proefaanroep is toegestaan. Slaagt die, dan
                   gaat de breaker weer dicht; faalt hij, dan opent hij opnieuw.

    Draadveilig, omdat de bot meerdere onderdelen tegelijk kan laten praten
    met dezelfde provider.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold moet minstens 1 zijn")
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._half_open_in_flight = False

    # -- toestand ---------------------------------------------------------

    @property
    def state(self) -> str:
        with self._lock:
            return self._state_locked()

    def _state_locked(self) -> str:
        if self._opened_at is None:
            return self.CLOSED
        if self._clock() - self._opened_at >= self.cooldown_seconds:
            return self.HALF_OPEN
        return self.OPEN

    def retry_after(self) -> float:
        """Seconden tot de breaker weer een poging toestaat (0 als dat nu mag)."""
        with self._lock:
            if self._opened_at is None:
                return 0.0
            remaining = self.cooldown_seconds - (self._clock() - self._opened_at)
            return max(0.0, remaining)

    def snapshot(self) -> dict:
        """Statusbeeld dat veilig gelogd of via HTTP getoond kan worden."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state_locked(),
                "failures": self._failures,
                "failure_threshold": self.failure_threshold,
                "cooldown_seconds": self.cooldown_seconds,
                "retry_after_seconds": round(
                    0.0
                    if self._opened_at is None
                    else max(0.0, self.cooldown_seconds - (self._clock() - self._opened_at)),
                    3,
                ),
            }

    # -- gebruik ----------------------------------------------------------

    def before_call(self) -> None:
        """Sta de aanroep toe, of gooi :class:`CircuitBreakerOpen`."""
        with self._lock:
            state = self._state_locked()
            if state == self.OPEN:
                remaining = self.cooldown_seconds - (self._clock() - (self._opened_at or 0.0))
                raise CircuitBreakerOpen(self.name, max(0.0, remaining))
            if state == self.HALF_OPEN:
                if self._half_open_in_flight:
                    raise CircuitBreakerOpen(self.name, 0.0)
                self._half_open_in_flight = True

    def record_success(self) -> None:
        with self._lock:
            was_open = self._opened_at is not None
            self._failures = 0
            self._opened_at = None
            self._half_open_in_flight = False
        if was_open:
            LOGGER.info("Circuit breaker %s is weer gesloten: de provider antwoordt weer.", self.name)

    def record_failure(self) -> None:
        with self._lock:
            self._half_open_in_flight = False
            if self._opened_at is not None:
                # Een mislukte proefaanroep opent de breaker opnieuw.
                self._opened_at = self._clock()
                opened_now = False
            else:
                self._failures += 1
                opened_now = self._failures >= self.failure_threshold
                if opened_now:
                    self._opened_at = self._clock()
            failures = self._failures
        if opened_now:
            LOGGER.error(
                "Circuit breaker %s geopend na %s opeenvolgende storingen; "
                "%.0f seconden rust voordat er opnieuw geprobeerd wordt.",
                self.name,
                failures,
                self.cooldown_seconds,
            )

    def reset(self) -> None:
        """Zet de breaker terug op 'closed'. Bedoeld voor tests en herstart."""
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open_in_flight = False


# --------------------------------------------------------------------------
# De uitvoerder
# --------------------------------------------------------------------------


def retry_call(
    func: Callable[[], T],
    *,
    description: str,
    policy: Optional[RetryPolicy] = None,
    breaker: Optional[CircuitBreaker] = None,
    retry_on: Optional[Callable[[BaseException], bool]] = None,
    sleep: Callable[[float], None] = time.sleep,
    logger: Optional[logging.Logger] = None,
    rng: Optional[random.Random] = None,
) -> T:
    """Voer ``func`` uit en herhaal bij tijdelijke fouten.

    ``description`` beschrijft de actie in gewone taal ("Coinbase-saldo
    opvragen") en komt in het log en in foutmeldingen terecht. Geef hier nooit
    argumenten of sleutels in mee.

    Gooit de oorspronkelijke exceptie door bij een permanente fout, en
    :class:`RetryExhausted` als alle pogingen op zijn. Zo blijft voor de
    aanroeper zichtbaar of iets *afgewezen* is of *onbereikbaar* was.
    """
    active_policy = policy or DEFAULT_POLICY
    log = logger or LOGGER
    should_retry = retry_on or is_transient
    last_error: Optional[BaseException] = None

    for attempt in range(1, active_policy.max_attempts + 1):
        wait = active_policy.delay_for(attempt, rng=rng)
        if wait > 0:
            log.info(
                "%s: poging %s van %s volgt over %.1f seconden.",
                description,
                attempt,
                active_policy.max_attempts,
                wait,
            )
            sleep(wait)

        if breaker is not None:
            breaker.before_call()

        try:
            result = func()
        except BaseException as exc:  # noqa: BLE001 -- doorgeven of herhalen, nooit inslikken
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            last_error = exc
            transient = should_retry(exc)
            if breaker is not None and transient:
                breaker.record_failure()
            if not transient:
                if breaker is not None:
                    # Een afgewezen sleutel zegt niets over de bereikbaarheid
                    # van de provider; die telt dus niet mee voor de breaker.
                    breaker.record_success()
                log.error(
                    "%s: definitief mislukt (%s). Dit is geen tijdelijke storing, "
                    "dus er wordt niet opnieuw geprobeerd.",
                    description,
                    type(exc).__name__,
                )
                raise
            log.warning(
                "%s: poging %s van %s mislukt door een tijdelijke storing (%s: %s).",
                description,
                attempt,
                active_policy.max_attempts,
                type(exc).__name__,
                exc,
            )
        else:
            if breaker is not None:
                breaker.record_success()
            if attempt > 1:
                log.info("%s: gelukt bij poging %s.", description, attempt)
            return result

    assert last_error is not None  # onbereikbaar: de lus draait minstens één keer
    log.error(
        "%s: alle %s pogingen mislukt. Rustpauze van %.0f seconden aanbevolen.",
        description,
        active_policy.max_attempts,
        active_policy.cooldown_seconds,
    )
    raise RetryExhausted(description, active_policy.max_attempts, last_error) from last_error


def describe_failure(exc: BaseException) -> str:
    """Zet een exceptie om in een zin die een niet-programmeur begrijpt.

    Bevat nooit de exceptie-argumenten zelf: die kunnen een URL met token of
    een stuk van een sleutel bevatten.
    """
    if isinstance(exc, CircuitBreakerOpen):
        return (
            f"{exc.name} wordt op dit moment overgeslagen omdat er kort achter elkaar "
            f"storingen waren. Over ongeveer {exc.retry_after:.0f} seconden wordt het opnieuw geprobeerd."
        )
    if isinstance(exc, RetryExhausted):
        return (
            f"{exc.description} lukte niet na {exc.attempts} pogingen. "
            "Dat wijst op een netwerk- of internetprobleem, of op een storing bij de provider."
        )
    status = _status_code_of(exc)
    if status == 401 or status == 403:
        return "De API-sleutel is afgewezen. Hij is verlopen, ingetrokken of heeft te weinig rechten."
    if status == 429:
        return "De provider ontvangt te veel verzoeken (rate limit). De bot wacht en probeert het later opnieuw."
    if status is not None and 500 <= status < 600:
        return f"De provider meldt een storing aan hun kant (foutcode {status})."
    if is_transient(exc):
        return "De provider was niet bereikbaar. Controleer de internetverbinding."
    return f"Onverwachte fout van het type {type(exc).__name__}."


def policies_snapshot(policy: Optional[RetryPolicy] = None) -> dict:
    """Leesbaar overzicht van de actieve instellingen, voor logs en diagnose."""
    active = policy or RetryPolicy.from_env()
    return {
        "max_attempts": active.max_attempts,
        "base_delay_seconds": active.base_delay,
        "max_delay_seconds": active.max_delay,
        "multiplier": active.multiplier,
        "jitter": active.jitter,
        "cooldown_seconds": active.cooldown_seconds,
        "example_waits_seconds": [round(active.delay_for(n, rng=random.Random(0)), 1) for n in range(1, active.max_attempts + 1)],
    }


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpen",
    "DEFAULT_POLICY",
    "RetryExhausted",
    "RetryPolicy",
    "TRANSIENT_STATUS_CODES",
    "describe_failure",
    "is_transient",
    "policies_snapshot",
    "retry_call",
]
