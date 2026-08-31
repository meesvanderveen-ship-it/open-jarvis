"""Instellingen van de control-service. Bewust klein en met veilige defaults."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "state"
LOGS_DIR = PROJECT_ROOT / "logs"

SERVICE_NAME = "jarvis-control-service"
API_PREFIX = "/api/control"

#: Loopback-only. Deze service kan de bot starten en stoppen, dus hij hoort
#: nooit vanaf een ander apparaat bereikbaar te zijn. Afwijken kan alleen
#: bewust, met de variabele hieronder, en wordt dan luid gelogd.
HOST = os.environ.get("JARVIS_CONTROL_HOST", "127.0.0.1")
PORT = int(os.environ.get("JARVIS_CONTROL_PORT", "8770"))
ALLOW_NON_LOOPBACK = (os.environ.get("JARVIS_CONTROL_ALLOW_NON_LOOPBACK", "false").lower()) in {
    "1",
    "true",
    "yes",
}
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

#: Het gedeelde geheim tussen extension en service. Wordt bij de eerste start
#: aangemaakt; staat in .gitignore en wordt nooit in een response getoond.
TOKEN_PATH = Path(os.environ.get("JARVIS_CONTROL_TOKEN_PATH", str(STATE_DIR / "control_token.txt")))

#: PID van de supervisor die deze service gestart heeft.
SUPERVISOR_PID_PATH = STATE_DIR / "control_supervisor.pid"
SUPERVISOR_STATUS_PATH = STATE_DIR / "supervisor_status.json"

#: Logbestanden die via /logs opgevraagd mogen worden. Een vaste lijst in
#: plaats van een vrij pad: anders is elk bestand op de schijf te lezen via
#: een pad met '..' erin.
READABLE_LOGS: dict[str, Path] = {
    "bot": LOGS_DIR / "loop.log",
    "supervisor": LOGS_DIR / "supervisor.log",
    "control": LOGS_DIR / "control_service.log",
}
DEFAULT_LOG = "bot"
MAX_LOG_LINES = 500
DEFAULT_LOG_LINES = 100

#: Hoe lang een read-only credential-verificatie mag duren.
VALIDATION_TIMEOUT_SECONDS = float(os.environ.get("JARVIS_CONTROL_VALIDATION_TIMEOUT", "20"))
