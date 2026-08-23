"""Credential-status ophalen zonder secrets in dit proces te halen.

`dashboard/backend/config.py` legt vast dat de dashboardbackend nooit de
bot-config importeert en nooit `.env` leest. Die eigenschap blijft hier
overeind: de status wordt opgehaald door `tools/setup_wizard.py --json` in
een apart proces te draaien, precies zoals de andere services de read-only
`tools/show_*.py`-scripts aanroepen. Alleen het (secret-vrije) JSON-oordeel
komt terug; het secret zelf raakt dit proces nooit.

De wizard geeft bewust exit-code 1 als de configuratie incompleet is. Dat is
een geldige toestand om te tonen, geen uitvoeringsfout, dus die code wordt
hier geaccepteerd.
"""

from __future__ import annotations

import json
import subprocess

from dashboard.backend import cache, config

_ARGV = ["-m", "tools.setup_wizard", "--check", "--json"]

# Exit 0 = READY, exit 1 = SETUP_REQUIRED/CONFIGURATION_ERROR. Beide leveren
# bruikbare JSON op; alles daarbuiten is een echte fout.
_EXPECTED_RETURN_CODES = {0, 1}

# Bovengrens op de foutregels die we doorgeven aan de UI.
_MAX_STDERR_CHARS = 500


def _run() -> dict:
    try:
        result = subprocess.run(
            [config.BOT_PYTHON_EXECUTABLE, *_ARGV],
            cwd=config.PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=config.SUBPROCESS_TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _unavailable("credential-statuscontrole duurde te lang")

    if result.returncode not in _EXPECTED_RETURN_CODES:
        return _unavailable(
            f"statuscontrole eindigde met code {result.returncode}", result.stderr
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        # Meestal een kapotte of ontbrekende Python-omgeving: de wizard kwam
        # niet eens tot uitvoeren. Zonder de foutregel is dat niet te herleiden.
        return _unavailable("statuscontrole gaf geen geldige JSON terug", result.stderr)

    payload["read_only"] = True
    payload["coinbase_calls_enabled"] = False
    return payload


def _unavailable(reason: str, stderr: str = "") -> dict:
    payload = {
        "state": "UNKNOWN",
        "detail": reason,
        "providers": {},
        "read_only": True,
        "coinbase_calls_enabled": False,
    }
    # Laatste regels van stderr helpen de operator de oorzaak te vinden
    # (ontbrekende venv, kapotte dependency). De redactie-middleware scrubt
    # deze tekst nog voordat hij het proces verlaat.
    tail = (stderr or "").strip().splitlines()[-3:]
    if tail:
        payload["error_output"] = "\n".join(tail)[:_MAX_STDERR_CHARS]
    return payload


def read_status() -> dict:
    return cache.get_or_compute("setup_status", _run)
