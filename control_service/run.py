"""Start de control-service: ``python -m control_service.run``.

Weigert te starten op een adres dat niet loopback is, tenzij dat expliciet
aangezet wordt. Deze service kan de bot starten en stoppen; bereikbaar maken
vanaf het netwerk is bijna nooit wat iemand bedoelt.
"""

from __future__ import annotations

import logging
import socket
import sys

from control_service import auth, config


def _port_in_use(host: str, port: int) -> bool:
    """Luistert er al iets op deze poort?

    Vooraf kijken en niet achteraf opvangen: uvicorn vangt een bindfout zelf
    af, logt hem als 'ERROR: [Errno 98] address already in use' en sluit netjes
    af. Een except OSError om uvicorn.run() heen wordt dus nooit bereikt, en de
    gebruiker houdt een Engelse regel over waar hij niets mee kan.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as proef:
        proef.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            proef.bind((host, port))
        except OSError:
            return True
    return False


def _configure_logging() -> None:
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - [control] %(message)s",
        handlers=[
            logging.FileHandler(config.READABLE_LOGS["control"], encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> int:
    _configure_logging()
    log = logging.getLogger("jarvis.control")

    if config.HOST not in config.LOOPBACK_HOSTS and not config.ALLOW_NON_LOOPBACK:
        print(
            f"De control-service weigert te starten op {config.HOST}.\n"
            "\n"
            "Dit adres is van buiten je pc bereikbaar, en deze service kan de\n"
            "handelsbot starten en stoppen. Standaard luistert hij daarom alleen\n"
            "op 127.0.0.1 (je eigen pc).\n"
            "\n"
            "Wil je dit bewust anders, zet dan JARVIS_CONTROL_ALLOW_NON_LOOPBACK=true.",
            file=sys.stderr,
        )
        return 2

    try:
        import uvicorn
    except ImportError:
        print(
            "Het pakket 'uvicorn' ontbreekt; de control-service kan niet starten.\n"
            "Dubbelklik op INSTALLEREN-WINDOWS.bat om de installatie te herstellen.",
            file=sys.stderr,
        )
        return 1

    if _port_in_use(config.HOST, config.PORT):
        print(
            f"De control-service kan poort {config.PORT} niet gebruiken.\n"
            "\n"
            "Er luistert al iets op die poort. Meestal betekent dat:\n"
            "  - JARVIS draait al. Kijk of er nog een zwart venster openstaat,\n"
            "    of stop hem eerst met STOP-JARVIS.bat.\n"
            "  - Of een ander programma gebruikt deze poort.\n"
            "\n"
            f"Wil je een andere poort, zet dan JARVIS_CONTROL_PORT in .env op een\n"
            f"ander nummer dan {config.PORT}, en pas het adres in de instellingen\n"
            "van de JARVIS-extensie aan.",
            file=sys.stderr,
        )
        return 1

    token = auth.ensure_token()
    log.info("Control-service start op http://%s:%s", config.HOST, config.PORT)
    log.info("Toegangssleutel: %s (volledig in %s)", auth.masked(token), config.TOKEN_PATH)

    if config.HOST not in config.LOOPBACK_HOSTS:
        log.warning(
            "LET OP: de control-service luistert op %s en is dus niet alleen vanaf deze pc bereikbaar.",
            config.HOST,
        )

    try:
        uvicorn.run("control_service.app:app", host=config.HOST, port=config.PORT, reload=False, log_level="info")
    except OSError as exc:
        # Vangnet voor het kleine gat tussen de controle hierboven en het
        # moment dat uvicorn de poort echt pakt.
        print(
            f"\nDe control-service kon poort {config.PORT} niet gebruiken: {exc}\n"
            "Waarschijnlijk pakte een ander programma de poort er net tussenuit.\n"
            "Probeer het opnieuw, of kies een andere poort met JARVIS_CONTROL_PORT.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
