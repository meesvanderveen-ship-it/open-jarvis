"""HTTP-laag van de control-service.

Alle endpoints staan onder ``/api/control``. Regels die hier per constructie
gelden, niet per afspraak:

* Elk endpoint dat iets *doet* vereist het token uit ``state/control_token.txt``.
  Loopback alleen is geen bescherming: elke webpagina en elk programma op
  dezelfde pc kan 127.0.0.1 benaderen.
* Geen enkele response bevat een secret. Alles gaat door dezelfde
  redactiefunctie als het read-only dashboard.
* Er wordt nooit een order geplaatst. ``/validate-credentials`` doet uitsluitend
  read-only aanroepen; handelen gebeurt alleen door de bot zelf.
* Fouten leveren een leesbare Nederlandse zin op plus een foutcode, nooit een
  kale traceback.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from bot.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    RetryExhausted,
    RetryPolicy,
    describe_failure,
    retry_call,
)
from control_service import auth, config
from control_service.process_manager import ActionResult, ProcessManager
from dashboard.backend.security.redact import redact

LOGGER = logging.getLogger("jarvis.control")

VERSION = "1.0.0"

router = APIRouter(prefix=config.API_PREFIX)

#: Eén manager voor het hele proces: twee tegelijk zouden elkaars pid-bestand
#: kunnen overschrijven.
_MANAGER = ProcessManager()

#: De sleutelcontrole is het enige endpoint dat namens de gebruiker naar buiten
#: belt, en het enige dat hij zelf herhaaldelijk kan aanroepen -- de knop
#: "Controleer mijn API-sleutels" in de popup. Iemand die offline is en drie
#: keer klikt, stuurt anders drie keer een verzoek naar OpenAI en Coinbase.
#: Na drie mislukkingen houdt de breaker dat een minuut tegen en zegt dat ook.
_VALIDATION_BREAKER = CircuitBreaker(
    "de sleutelcontrole", failure_threshold=3, cooldown_seconds=60.0
)

#: Twee pogingen met een korte pauze. Bewust klein: dit endpoint hangt aan een
#: knop in de browser, dus lang wachten is erger dan een eerlijk "onbekend".
_VALIDATION_RETRY = RetryPolicy(max_attempts=2, base_delay=1.0, max_delay=2.0, jitter=0.2)


class _ProviderUnreachable(RuntimeError):
    """De provider antwoordde niet. Bestaat om retry_call te laten herhalen.

    ``status_report`` vangt netwerkfouten zelf af en geeft de toestand
    VERIFICATION_UNAVAILABLE terug in plaats van te falen. Zonder deze
    vertaling naar een exceptie zou de retrylaag nooit iets te herhalen zien.
    """


def get_manager() -> ProcessManager:
    """Overschrijfbaar via ``app.dependency_overrides`` in tests."""
    return _MANAGER


def require_token(
    authorization: Optional[str] = Header(default=None),
    x_jarvis_token: Optional[str] = Header(default=None),
) -> None:
    """Weiger elke aanroep zonder geldig token.

    De foutmelding zegt bewust niet of het token ontbrak of verkeerd was, en
    bevat nooit (een deel van) het verwachte token.
    """
    expected = auth.load_token()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "control_token_missing",
                "message": "De control-service is nog niet ingericht.",
                "advice": "Start JARVIS opnieuw met START-JARVIS.bat; die maakt het token aan.",
            },
        )
    presented = auth.extract_token(authorization, x_jarvis_token)
    if not auth.token_matches(presented, expected):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "unauthorized",
                "message": "Deze aanvraag had geen geldige toegangssleutel.",
                "advice": (
                    "Open de instellingen van de JARVIS-extensie en plak daar de sleutel "
                    "uit het bestand state/control_token.txt."
                ),
            },
        )


def _action_response(result: ActionResult) -> JSONResponse:
    return JSONResponse(status_code=result.http_status, content=redact(result.as_dict()))


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@router.get("/health")
def health() -> dict[str, Any]:
    """Leeft de service? Bewust zonder token, zodat de extension kan zien of
    de backend überhaupt draait voordat hij om een sleutel vraagt."""
    return {
        "ok": True,
        "service": config.SERVICE_NAME,
        "version": VERSION,
        "token_required": True,
        "token_configured": auth.load_token() is not None,
    }


@router.get("/status", dependencies=[Depends(require_token)])
def status(manager: ProcessManager = Depends(get_manager)) -> dict[str, Any]:
    """Draait de bot, en wat is de gezondheid van het geheel?

    De health check draait hier offline: dit endpoint wordt elke paar seconden
    door de extension bevraagd, en een online controle zou dan per keer een
    verzoek naar OpenAI en Coinbase sturen.
    """
    from bot.health_check import run_health_check

    process = manager.status()
    try:
        health_report = run_health_check(online=False)
    except Exception as exc:  # noqa: BLE001 -- de status mag nooit zelf omvallen
        LOGGER.exception("De systeemcontrole is mislukt.")
        health_report = {
            "overall": "ERROR",
            "ready": False,
            "blocking": ["Systeemcontrole"],
            "checks": [
                {
                    "component": "Systeemcontrole",
                    "status": "ERROR",
                    "summary": "De systeemcontrole kon niet uitgevoerd worden.",
                    "detail": type(exc).__name__,
                    "advice": "Draai diagnose.bat voor een volledige controle.",
                    "facts": {},
                }
            ],
        }

    return redact(
        {
            "service": config.SERVICE_NAME,
            "version": VERSION,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "bot": process,
            "health": health_report,
        }
    )


@router.post("/start", dependencies=[Depends(require_token)])
def start(manager: ProcessManager = Depends(get_manager)) -> JSONResponse:
    """Start de bot via de bewaker. Idempotent: al draaien is geen fout."""
    LOGGER.info("Startverzoek ontvangen.")
    return _action_response(manager.start())


@router.post("/stop", dependencies=[Depends(require_token)])
def stop(manager: ProcessManager = Depends(get_manager)) -> JSONResponse:
    """Stop de bot netjes. Al gestopt is geen fout."""
    LOGGER.info("Stopverzoek ontvangen.")
    return _action_response(manager.stop())


@router.post("/restart", dependencies=[Depends(require_token)])
def restart(manager: ProcessManager = Depends(get_manager)) -> JSONResponse:
    LOGGER.info("Herstartverzoek ontvangen.")
    return _action_response(manager.restart())


@router.get("/logs", dependencies=[Depends(require_token)])
def logs(
    name: str = Query(default=config.DEFAULT_LOG),
    lines: int = Query(default=config.DEFAULT_LOG_LINES, ge=1, le=config.MAX_LOG_LINES),
) -> dict[str, Any]:
    """Laatste regels uit een van de bekende logbestanden.

    ``name`` is een sleutel uit een vaste lijst, geen pad. Een vrij pad zou
    met '..' elk bestand op de schijf leesbaar maken.
    """
    path = config.READABLE_LOGS.get(name)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "unknown_log",
                "message": f"Er is geen logbestand met de naam '{name}'.",
                "available": sorted(config.READABLE_LOGS),
            },
        )

    if not path.exists():
        return redact(
            {
                "name": name,
                "exists": False,
                "lines": [],
                "message": "Dit logbestand bestaat nog niet. Dat is normaal als JARVIS nog niet gedraaid heeft.",
            }
        )

    try:
        collected = _tail(path, lines)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "log_unreadable",
                "message": "Het logbestand kon niet gelezen worden.",
                "detail": type(exc).__name__,
            },
        ) from exc

    return redact({"name": name, "exists": True, "lines": collected, "returned": len(collected)})


@router.post("/validate-credentials", dependencies=[Depends(require_token)])
def validate_credentials(online: bool = Query(default=True)) -> dict[str, Any]:
    """Controleer de API-sleutels. Uitsluitend read-only.

    Onderscheidt de drie toestanden die de opdracht vereist: geldig, afgewezen
    en niet-bereikbaar. Er wordt nooit een order geplaatst en het secret zelf
    komt niet in de response.
    """
    from bot import credential_status as cs

    def _verify() -> dict[str, Any]:
        uitkomst = cs.status_report(online=online, timeout=config.VALIDATION_TIMEOUT_SECONDS)
        if online and uitkomst.get("state") == cs.VERIFICATION_UNAVAILABLE:
            # Onbereikbaar is precies het geval dat een tweede poging kan
            # oplossen. Afgewezen sleutels komen hier nooit terecht: die
            # leveren CONFIGURATION_ERROR op en worden meteen teruggegeven.
            raise _ProviderUnreachable("provider niet bereikbaar")
        return uitkomst

    try:
        report = retry_call(
            _verify,
            description="API-sleutels controleren",
            policy=_VALIDATION_RETRY,
            breaker=_VALIDATION_BREAKER,
            retry_on=lambda exc: isinstance(exc, _ProviderUnreachable),
            logger=LOGGER,
        )
    except CircuitBreakerOpen as exc:
        # Herhaald klikken terwijl er geen internet is, moet niet elke keer
        # opnieuw naar OpenAI en Coinbase bellen.
        return redact(
            {
                "state": cs.VERIFICATION_UNAVAILABLE,
                "verified_online": online,
                "providers": {},
                "message": describe_failure(exc),
                "trades_placed": False,
            }
        )
    except RetryExhausted:
        # Alle pogingen op: dit is een netwerkprobleem, geen sleutelprobleem.
        # De offline vormcontrole levert nog wel bruikbare informatie.
        report = cs.status_report(online=False)
        report["verified_online"] = False
        report["state"] = cs.VERIFICATION_UNAVAILABLE
    except Exception as exc:  # noqa: BLE001 -- ook hier nooit een kale traceback
        LOGGER.exception("Credential-validatie is mislukt.")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "validation_failed",
                "message": "De sleutelcontrole kon niet uitgevoerd worden.",
                "detail": type(exc).__name__,
                "advice": "Draai diagnose.bat voor een volledige controle.",
            },
        ) from exc

    human = {
        cs.READY: "Beide sleutels werken.",
        cs.SETUP_REQUIRED: "Er ontbreekt nog een sleutel.",
        cs.CONFIGURATION_ERROR: "Een sleutel werd afgewezen door de provider.",
        cs.VERIFICATION_UNAVAILABLE: (
            "De sleutels konden niet gecontroleerd worden omdat de provider niet bereikbaar was. "
            "Dat wijst op een netwerkprobleem, niet op een verkeerde sleutel."
        ),
    }
    report["message"] = human.get(report.get("state", ""), "Onbekende toestand.")
    report["trades_placed"] = False
    return redact(report)


def _tail(path, max_lines: int) -> list[str]:
    """Laatste ``max_lines`` regels, zonder het hele bestand in te lezen.

    logs/loop.log groeit tot honderden megabytes; een simpele readlines() zou
    het geheugen van een gewone pc opeten.
    """
    chunk_size = 65536
    max_bytes = 4 * 1024 * 1024
    collected = b""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        read = 0
        while position > 0 and collected.count(b"\n") <= max_lines and read < max_bytes:
            step = min(chunk_size, position)
            position -= step
            handle.seek(position)
            collected = handle.read(step) + collected
            read += step
    decoded = collected.decode("utf-8", errors="replace").splitlines()
    return [line for line in decoded if line.strip()][-max_lines:]


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="JARVIS control service",
        version=VERSION,
        docs_url=f"{config.API_PREFIX}/docs",
        openapi_url=f"{config.API_PREFIX}/openapi.json",
    )
    app.include_router(router)

    @app.middleware("http")
    async def _cors_for_extension(request: Request, call_next):
        """Sta alleen de Chrome Extension toe, en alleen de eigen methodes.

        De extension-id staat pas vast nadat de gebruiker de map geladen heeft,
        dus die kan hier niet hard ingevuld worden. Elke ``chrome-extension://``
        oorsprong mag daarom een antwoord ontvangen -- de echte bescherming is
        het token, niet de oorsprong. Gewone webpagina's (``https://...``)
        krijgen geen CORS-header en kunnen het antwoord dus niet uitlezen.
        """
        origin = request.headers.get("origin", "")
        allowed = origin.startswith("chrome-extension://")

        if request.method == "OPTIONS":
            response = JSONResponse(status_code=204, content=None)
        else:
            response = await call_next(request)

        if allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Authorization, X-Jarvis-Token, Content-Type"
            response.headers["Vary"] = "Origin"
        return response

    @app.exception_handler(Exception)
    async def _never_leak_a_traceback(request: Request, exc: Exception) -> JSONResponse:
        """Een onverwachte fout wordt gelogd, maar nooit doorgestuurd.

        Een traceback kan paden en soms stukken configuratie bevatten. De
        gebruiker krijgt een verwijzing naar het logbestand; daar staat alles.
        """
        LOGGER.exception("Onverwachte fout bij %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "Er ging iets mis in de control-service.",
                "advice": f"Kijk in {config.READABLE_LOGS['control']} of draai diagnose.bat.",
            },
        )

    return app


app = create_app()
