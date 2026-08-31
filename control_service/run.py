"""Start de control-service: ``python -m control_service.run``.

Weigert te starten op een adres dat niet loopback is, tenzij dat expliciet
aangezet wordt. Deze service kan de bot starten en stoppen; bereikbaar maken
vanaf het netwerk is bijna nooit wat iemand bedoelt.
"""

from __future__ import annotations

import logging
import sys

from control_service import auth, config


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
        # Bijna altijd: poort bezet. Dat is de meest voorkomende startfout en
        # verdient een echte uitleg in plaats van een OSError-traceback.
        print(
            f"\nDe control-service kon poort {config.PORT} niet gebruiken.\n"
            "\n"
            "Meestal betekent dit dat JARVIS al draait, of dat een ander programma\n"
            f"deze poort gebruikt. Kies een andere poort met JARVIS_CONTROL_PORT,\n"
            f"of stop het andere programma.\n"
            f"\nTechnische melding: {exc}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
