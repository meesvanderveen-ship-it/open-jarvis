"""Canonical local entrypoint: `python -m dashboard.backend.run`.

Refuses to bind off-loopback unless DASHBOARD_ALLOW_NON_LOOPBACK=true is set
explicitly — this dashboard is meant to be reached only via an SSH tunnel.
"""

from __future__ import annotations

import socket
import sys

import uvicorn

from dashboard.backend import config

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _port_in_use(host: str, port: int) -> bool:
    """Luistert er al iets op deze poort?

    Vooraf kijken en niet achteraf opvangen: uvicorn vangt een bindfout zelf af
    en logt hem als 'ERROR: [Errno 98] address already in use'. Voor iemand
    zonder programmeerervaring zegt die regel niets, terwijl een bezette poort
    juist de meest voorkomende startfout is -- meestal doordat JARVIS al draait.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as proef:
        proef.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            proef.bind((host, port))
        except OSError:
            return True
    return False


def main() -> None:
    if config.HOST not in LOOPBACK_HOSTS and not config.ALLOW_NON_LOOPBACK:
        print(
            f"Refusing to bind {config.HOST}: not a loopback address and "
            "DASHBOARD_ALLOW_NON_LOOPBACK is not set. This dashboard is "
            "read-only but still meant to be local-only by default.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if _port_in_use(config.HOST, config.PORT):
        print(
            f"Het dashboard kan poort {config.PORT} niet gebruiken.\n"
            "\n"
            "Er luistert al iets op die poort. Meestal betekent dat:\n"
            "  - JARVIS draait al. Kijk of er nog een zwart venster openstaat,\n"
            "    of stop hem eerst met STOP-JARVIS.bat.\n"
            "  - Of een ander programma gebruikt deze poort.\n"
            "\n"
            f"Wil je een andere poort, zet dan DASHBOARD_PORT in .env op een ander\n"
            f"nummer dan {config.PORT}.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    uvicorn.run("dashboard.backend.app:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
