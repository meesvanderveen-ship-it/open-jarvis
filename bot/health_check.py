"""Startup health check: één plek die zegt of JARVIS echt kan draaien.

Wordt gebruikt door vier plekken, zodat ze onmogelijk een verschillend
oordeel kunnen vellen:

* ``run_trader_loop.py`` bij het opstarten;
* ``diagnose.bat`` / ``python -m bot.health_check``;
* het ``/api/control/status``-endpoint van de control-service;
* de Chrome Extension, die datzelfde endpoint uitleest.

Elke controle levert één van vier toestanden op:

``READY``    onderdeel is in orde;
``WARNING``  bruikbaar, maar er is iets om naar te kijken;
``ERROR``    kapot of ontbrekend -- de bot mag hier niet omheen doen;
``OFFLINE``  niet te controleren omdat er geen verbinding was. Dit is
             nadrukkelijk *geen* ERROR: een internetstoring is iets anders
             dan een verkeerde sleutel.

Geen enkele controle plaatst een order, schrijft een bestand of drukt een
secret af. De online-controles zijn read-only en zitten achter een expliciete
``online=True``.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

LOGGER = logging.getLogger("jarvis.health")
# Zonder handler valt Python terug op logging.lastResort, en die drukt alles
# vanaf WARNING mét traceback naar stderr. Dan zou een afgevangen fout alsnog
# als traceback op het scherm van de gebruiker belanden -- precies wat deze
# module wil voorkomen. Een NullHandler zet die noodroute uit; een programma
# dat zelf logging inricht (de control-service doet dat) vangt de melding
# gewoon op via de root logger.
LOGGER.addHandler(logging.NullHandler())

PROJECT_ROOT = Path(__file__).resolve().parents[1]

READY = "READY"
WARNING = "WARNING"
ERROR = "ERROR"
OFFLINE = "OFFLINE"

#: Van slechtst naar best. Bepaalt de samengevatte eindtoestand.
_SEVERITY = {ERROR: 0, OFFLINE: 1, WARNING: 2, READY: 3}

#: Importnaam -> pakketnaam zoals in requirements.txt. Alleen de pakketten
#: waarzonder de bot echt niet draait; optionele extra's staan hier niet in.
REQUIRED_IMPORTS = {
    "anthropic": "anthropic",
    "cryptography": "cryptography",
    "dotenv": "python-dotenv",
    "jwt": "PyJWT",
    "numpy": "numpy",
    "openai": "openai",
    "pandas": "pandas",
    "pydantic": "pydantic",
    "requests": "requests",
}

#: Alleen nodig voor het dashboard en de control-service, niet voor de bot zelf.
BACKEND_IMPORTS = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
}


@dataclass(frozen=True)
class HealthResult:
    """Uitkomst van één controle. Bevat nooit een secret."""

    component: str
    status: str
    summary: str
    detail: str = ""
    advice: str = ""
    facts: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status,
            "summary": self.summary,
            "detail": self.detail,
            "advice": self.advice,
            "facts": dict(self.facts),
        }


def worst_status(results: list[HealthResult]) -> str:
    """De slechtste toestand uit een lijst; READY als de lijst leeg is."""
    if not results:
        return READY
    return min((result.status for result in results), key=lambda status: _SEVERITY.get(status, 0))


# --------------------------------------------------------------------------
# De losse controles
# --------------------------------------------------------------------------


def check_python() -> HealthResult:
    from tools.check_python import evaluate

    verdict = evaluate()
    if verdict["status"] == "OK":
        return HealthResult(
            "Python",
            READY,
            f"Python {verdict['version']}",
            facts={"version": verdict["version"], "minimum": verdict["minimum"]},
        )
    # Te nieuw is een waarschuwing (het kan werken), te oud is fataal.
    status = WARNING if verdict["status"] == "TE_NIEUW" else ERROR
    return HealthResult(
        "Python",
        status,
        verdict["summary"],
        advice=verdict["advice"],
        facts={"version": verdict["version"], "minimum": verdict["minimum"]},
    )


def _missing_imports(mapping: dict[str, str]) -> list[str]:
    """Welke pakketten uit ``mapping`` zijn niet te importeren?

    Eerst ``sys.modules``, dan pas ``find_spec``. Die volgorde is nodig, niet
    cosmetisch: ``find_spec`` kijkt zelf ook in ``sys.modules`` en geeft dan het
    ``__spec__`` van de gevonden module terug -- maar een module die door iets
    anders in ``sys.modules`` gezet is heeft geen ``__spec__``, en dan gooit
    ``find_spec`` een ValueError. Die zou hier als "pakket ontbreekt" gelezen
    worden terwijl het pakket gewoon geinstalleerd en zelfs al geladen is.
    Staat de naam in ``sys.modules``, dan is hij per definitie beschikbaar.
    """
    missing = []
    for module_name, package_name in sorted(mapping.items()):
        if module_name in sys.modules:
            continue
        try:
            found = importlib.util.find_spec(module_name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(package_name)
    return missing


def check_dependencies() -> HealthResult:
    missing = _missing_imports(REQUIRED_IMPORTS)
    if not missing:
        return HealthResult(
            "Dependencies",
            READY,
            f"Alle {len(REQUIRED_IMPORTS)} vereiste pakketten zijn aanwezig.",
            facts={"required": len(REQUIRED_IMPORTS)},
        )
    return HealthResult(
        "Dependencies",
        ERROR,
        f"{len(missing)} pakket(ten) ontbreken: {', '.join(missing)}.",
        advice="Dubbelklik op INSTALLEREN-WINDOWS.bat om de pakketten (opnieuw) te installeren.",
        facts={"missing": missing},
    )


def check_backend_dependencies() -> HealthResult:
    missing = _missing_imports(BACKEND_IMPORTS)
    if not missing:
        return HealthResult("Dashboard-pakketten", READY, "fastapi en uvicorn zijn aanwezig.")
    return HealthResult(
        "Dashboard-pakketten",
        WARNING,
        f"Ontbreekt: {', '.join(missing)}. De bot draait wel, het dashboard niet.",
        advice="Dubbelklik op INSTALLEREN-WINDOWS.bat om dit te herstellen.",
        facts={"missing": missing},
    )


def check_configuration(root: Optional[Path] = None) -> HealthResult:
    """Bestaat .env, en accepteert BotConfig hem?

    De validatie draait in een try: een configuratiefout moet een leesbare
    zin opleveren, geen traceback midden in een opstartscherm.
    """
    base = root or PROJECT_ROOT
    env_path = base / ".env"
    if not env_path.exists():
        return HealthResult(
            "Configuratie",
            ERROR,
            "Het bestand .env bestaat nog niet.",
            detail="Daarin staan je API-sleutels en instellingen.",
            advice="Dubbelklik op INSTALLEREN-WINDOWS.bat; die maakt het bestand aan en vult het in.",
            facts={"env_path": str(env_path)},
        )

    try:
        from bot.config import BotConfig
    except Exception as exc:  # noqa: BLE001 -- de reden moet leesbaar blijven
        return HealthResult(
            "Configuratie",
            ERROR,
            "De configuratiemodule kon niet geladen worden.",
            detail=f"{type(exc).__name__}: {exc}",
            advice="Draai diagnose.bat; meestal ontbreekt er een pakket.",
        )

    try:
        cfg = BotConfig()
        cfg.validate()
    except Exception as exc:  # noqa: BLE001 -- ValueError van validate() hoort hier
        return HealthResult(
            "Configuratie",
            ERROR,
            "De instellingen in .env zijn niet geldig.",
            detail=f"{type(exc).__name__}: {exc}",
            advice="Corrigeer de genoemde instelling in .env, of herstel .env vanaf .env.example.",
        )

    return HealthResult(
        "Configuratie",
        READY,
        "De instellingen in .env zijn geldig.",
        facts={
            "execution_mode": getattr(cfg, "execution_mode", "onbekend"),
            "tickers": len(getattr(cfg, "allowed_tickers", []) or []),
        },
    )


def check_credentials(*, online: bool = False, timeout: float = 15.0) -> list[HealthResult]:
    """Eén resultaat per provider.

    Vertaalt de drie uitkomsten van ``bot.credential_status`` naar de vier
    health-toestanden. ``unknown`` (niet te verifieren) wordt OFFLINE en
    nadrukkelijk niet ERROR.
    """
    from bot import credential_status as cs

    try:
        checks = cs.collect_checks(online=online, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 -- nooit de health check zelf laten crashen
        return [
            HealthResult(
                "API-sleutels",
                ERROR,
                "De sleutelcontrole kon niet uitgevoerd worden.",
                detail=f"{type(exc).__name__}: {exc}",
                advice="Draai diagnose.bat voor meer details.",
            )
        ]

    mapping = {
        cs.STATUS_OK: READY,
        cs.STATUS_MISSING: ERROR,
        cs.STATUS_INVALID: ERROR,
        cs.STATUS_UNKNOWN: OFFLINE,
    }
    results = []
    for check in checks:
        status = mapping.get(check.status, ERROR)
        advice = ""
        if status == ERROR:
            advice = "Draai INSTALLEREN-WINDOWS.bat of: .venv\\Scripts\\python -m tools.connect_services"
        elif status == OFFLINE:
            advice = "Controleer je internetverbinding. Er is niets mis met de sleutel zelf."
        results.append(
            HealthResult(
                f"Sleutel {check.provider}",
                status,
                check.summary,
                detail=check.detail,
                advice=advice,
                facts=dict(check.facts),
            )
        )
    return results


def check_trading_engine() -> HealthResult:
    """Kan de handelsmotor geladen worden? Start hem niet en handelt niet."""
    try:
        importlib.util.find_spec("bot.strategy_engine")
    except (ImportError, ValueError) as exc:
        return HealthResult(
            "Trading engine",
            ERROR,
            "De handelsmotor kon niet gevonden worden.",
            detail=f"{type(exc).__name__}: {exc}",
            advice="De installatie is onvolledig. Draai INSTALLEREN-WINDOWS.bat opnieuw.",
        )

    try:
        import bot.strategy_engine  # noqa: F401
    except Exception as exc:  # noqa: BLE001 -- importfouten moeten leesbaar zijn
        return HealthResult(
            "Trading engine",
            ERROR,
            "De handelsmotor kon niet geladen worden.",
            detail=f"{type(exc).__name__}: {exc}",
            advice="Draai diagnose.bat; meestal ontbreekt er een pakket of klopt een instelling niet.",
        )

    return HealthResult("Trading engine", READY, "De handelsmotor is laadbaar.")


def _port_is_open(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_local_backend(
    *,
    host: str = "127.0.0.1",
    port: Optional[int] = None,
    probe: Optional[Callable[[str, int], bool]] = None,
) -> HealthResult:
    """Draait het read-only dashboard? Niet draaien is geen fout."""
    resolved_port = port if port is not None else int(os.environ.get("DASHBOARD_PORT", "8000"))
    reachable = (probe or _port_is_open)(host, resolved_port)
    if reachable:
        return HealthResult(
            "Dashboard",
            READY,
            f"Het dashboard antwoordt op http://{host}:{resolved_port}",
            facts={"host": host, "port": resolved_port},
        )
    return HealthResult(
        "Dashboard",
        WARNING,
        "Het dashboard draait nu niet.",
        detail=f"Er luistert niets op poort {resolved_port}.",
        advice="Dat is normaal als JARVIS uit staat. Start met START-JARVIS.bat.",
        facts={"host": host, "port": resolved_port},
    )


def check_control_service(
    *,
    host: str = "127.0.0.1",
    port: Optional[int] = None,
    probe: Optional[Callable[[str, int], bool]] = None,
) -> HealthResult:
    """Draait de control-service waar de Chrome Extension mee praat?"""
    from control_service import config as control_config

    resolved_port = port if port is not None else control_config.PORT
    reachable = (probe or _port_is_open)(host, resolved_port)
    if reachable:
        return HealthResult(
            "Control-service",
            READY,
            f"De control-service antwoordt op http://{host}:{resolved_port}",
            facts={"host": host, "port": resolved_port},
        )
    return HealthResult(
        "Control-service",
        WARNING,
        "De control-service draait nu niet.",
        detail=f"Er luistert niets op poort {resolved_port}.",
        advice="De Chrome Extension heeft deze service nodig. Start met START-JARVIS.bat.",
        facts={"host": host, "port": resolved_port},
    )


def check_chrome_extension(root: Optional[Path] = None) -> HealthResult:
    """Staan de bestanden klaar die Chrome via 'Load unpacked' inleest?"""
    base = (root or PROJECT_ROOT) / "extension"
    manifest = base / "manifest.json"
    if not manifest.exists():
        return HealthResult(
            "Chrome Extension",
            ERROR,
            "De map extension/ met manifest.json ontbreekt.",
            advice="Pak de ZIP opnieuw uit; de map extension hoort erbij te zitten.",
            facts={"path": str(base)},
        )

    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return HealthResult(
            "Chrome Extension",
            ERROR,
            "manifest.json is onleesbaar.",
            detail=f"{type(exc).__name__}: {exc}",
            facts={"path": str(manifest)},
        )

    required_files = [data.get("action", {}).get("default_popup"), data.get("options_page")]
    background = data.get("background", {}).get("service_worker")
    if background:
        required_files.append(background)
    missing = [name for name in required_files if name and not (base / name).exists()]
    if missing:
        return HealthResult(
            "Chrome Extension",
            ERROR,
            f"manifest.json verwijst naar {len(missing)} bestand(en) die ontbreken.",
            detail=", ".join(missing),
            facts={"missing": missing},
        )

    return HealthResult(
        "Chrome Extension",
        READY,
        f"Klaar om te laden ({data.get('name', 'extension')} v{data.get('version', '?')}).",
        detail=f"Laad in Chrome via 'Load unpacked' de map: {base}",
        facts={"path": str(base), "manifest_version": data.get("manifest_version")},
    )


def check_dashboard_build(root: Optional[Path] = None) -> HealthResult:
    index = (root or PROJECT_ROOT) / "dashboard" / "frontend" / "dist" / "index.html"
    if index.exists():
        return HealthResult("Dashboard-build", READY, "Het dashboard is gebouwd.")
    return HealthResult(
        "Dashboard-build",
        WARNING,
        "Het dashboard is nog niet gebouwd.",
        detail="De bot draait wel, maar de webpagina is er nog niet.",
        advice="Dubbelklik op INSTALLEREN-WINDOWS.bat.",
        facts={"expected": str(index)},
    )


# --------------------------------------------------------------------------
# Alles samen
# --------------------------------------------------------------------------


def _isolated(component: str, check: Callable[[], Any]) -> list[HealthResult]:
    """Voer één controle uit en laat hem nooit de hele systeemcontrole meeslepen.

    Dit is geen brede except die fouten wegmoffelt: een onverwachte fout wordt
    juist als ERROR-regel getoond, met het type erbij, en telt gewoon mee voor
    de eindtoestand en de afsluitcode. Wat hij voorkomt is dat de gebruiker een
    kale Python-traceback op zijn scherm krijgt in plaats van een overzicht --
    precies waar deze systeemcontrole voor bestaat. Een ontbrekende submodule
    liet anders `python -m bot.health_check` met een ImportError afbreken,
    zonder één regel over wat er wél goed staat.
    """
    try:
        uitkomst = check()
    except Exception as exc:  # noqa: BLE001 -- zie de uitleg hierboven
        LOGGER.exception("Controle %s is zelf omgevallen.", component)
        return [
            HealthResult(
                component,
                ERROR,
                "Deze controle kon niet uitgevoerd worden.",
                detail=f"{type(exc).__name__}: {exc}",
                advice="Draai DIAGNOSE-JARVIS.bat; als dit blijft terugkomen is de installatie onvolledig.",
            )
        ]
    if isinstance(uitkomst, HealthResult):
        return [uitkomst]
    return list(uitkomst)


def run_health_check(*, online: bool = False, root: Optional[Path] = None) -> dict[str, Any]:
    """Voer alle controles uit en vat ze samen.

    ``online=False`` (standaard) doet geen enkel netwerkverzoek naar een
    provider en is dus altijd veilig en snel.
    """
    results: list[HealthResult] = []
    for component, check in (
        ("Python", check_python),
        ("Dependencies", check_dependencies),
        ("Dashboard-pakketten", check_backend_dependencies),
        ("Configuratie", lambda: check_configuration(root)),
        ("API-sleutels", lambda: check_credentials(online=online)),
        ("Trading engine", check_trading_engine),
        ("Dashboard-build", lambda: check_dashboard_build(root)),
        ("Dashboard", check_local_backend),
        ("Control-service", check_control_service),
        ("Chrome Extension", lambda: check_chrome_extension(root)),
    ):
        results.extend(_isolated(component, check))

    overall = worst_status(results)
    return {
        "overall": overall,
        "ready": overall == READY,
        "verified_online": online,
        "blocking": [result.component for result in results if result.status == ERROR],
        "checks": [result.as_dict() for result in results],
    }


_SYMBOOL = {READY: "[OK]     ", WARNING: "[LET OP] ", ERROR: "[FOUT]   ", OFFLINE: "[OFFLINE]"}


def format_report(report: dict[str, Any]) -> str:
    """Zet het rapport om in tekst die een niet-programmeur kan lezen."""
    lines = [
        "============================================================",
        "  JARVIS - systeemcontrole",
        "============================================================",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"{_SYMBOOL.get(check['status'], '[?]      ')} {check['component']}: {check['summary']}")
        if check["detail"] and check["status"] != READY:
            lines.append(f"          {check['detail']}")
        if check["advice"]:
            lines.append(f"          -> {check['advice']}")
    lines.extend(["", "------------------------------------------------------------"])

    if report["overall"] == READY:
        lines.append("  RESULTAAT: READY - alles staat goed.")
    elif report["overall"] == WARNING:
        lines.append("  RESULTAAT: WARNING - JARVIS kan draaien, kijk naar de punten hierboven.")
    elif report["overall"] == OFFLINE:
        lines.append("  RESULTAAT: OFFLINE - iets was niet te controleren. Meestal een netwerkprobleem.")
    else:
        lines.append("  RESULTAAT: ERROR - JARVIS kan zo niet draaien.")
        lines.append(f"  Blokkerend: {', '.join(report['blocking'])}")
    lines.append("------------------------------------------------------------")
    return "\n".join(lines)


#: Afsluitcodes, zodat een .bat-bestand hierop kan reageren.
EXIT_CODES = {READY: 0, WARNING: 0, OFFLINE: 2, ERROR: 1}


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        report = run_health_check(online="--online" in args)
    except Exception as exc:  # noqa: BLE001 -- laatste vangnet, zie hieronder
        # De losse controles zijn al afzonderlijk afgeschermd; komt er hier tóch
        # iets doorheen, dan is een leesbare regel nog altijd beter dan een
        # traceback in het opstartvenster van iemand zonder programmeerkennis.
        # De afsluitcode blijft 1, dus START-JARVIS.bat stopt gewoon.
        print("De systeemcontrole kon niet worden uitgevoerd.", file=sys.stderr)
        print(f"Technische melding: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Draai DIAGNOSE-JARVIS.bat voor een volledige controle.", file=sys.stderr)
        return EXIT_CODES[ERROR]
    if "--json" in args:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    else:
        print(format_report(report))
    return EXIT_CODES.get(report["overall"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
