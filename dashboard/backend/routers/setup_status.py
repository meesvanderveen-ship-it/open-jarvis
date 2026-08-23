"""Read-only zicht op de credential-configuratie.

Houdt zich aan dezelfde invariant als de rest van deze backend: leest alleen,
schrijft nooit naar .env en doet geen enkele Coinbase- of OpenAI-aanroep. De
online verificatie zit bewust alleen in de CLI (`tools/setup_wizard.py`), niet
achter een onbeveiligd HTTP-endpoint.

De response bevat nooit een secret — alleen status, uitleg en vormkenmerken
zoals sleuteltype en lengte.
"""

from __future__ import annotations

from fastapi import APIRouter

from dashboard.backend.services import setup_status

router = APIRouter()


@router.get("/api/setup/status")
def read_setup_status() -> dict:
    return setup_status.read_status()
