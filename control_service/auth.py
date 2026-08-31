"""Token-authenticatie voor de control-service.

Deze service kan de bot starten en stoppen. Loopback-only is daarvoor niet
genoeg: elke webpagina in de browser kan requests naar 127.0.0.1 sturen, en
elk programma op dezelfde pc ook. Daarom moet elke aanroep die iets doet een
token meesturen dat alleen in een bestand op de eigen schijf staat.

Het token wordt bij de eerste start aangemaakt met ``secrets.token_urlsafe``
en op POSIX met rechten 0600 weggeschreven. Het komt nooit in een response,
nooit in een log en nooit in een foutmelding terecht.
"""

from __future__ import annotations

import logging
import os
import secrets
import stat
from pathlib import Path
from typing import Optional

from control_service import config

LOGGER = logging.getLogger("jarvis.control.auth")

#: Ruim genoeg om raden uit te sluiten, kort genoeg om te kunnen plakken.
TOKEN_BYTES = 32
MIN_TOKEN_LENGTH = 20


def _restrict_permissions(path: Path) -> None:
    """Alleen de eigenaar mag het tokenbestand lezen.

    Op Windows doet chmod vrijwel niets; daar leunt de bescherming op de
    NTFS-rechten van de gebruikersmap. Op POSIX is dit wel effectief, en het
    faalt nergens hard -- een niet-instelbaar recht mag de start niet blokkeren.
    """
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:  # pragma: no cover - hangt van het bestandssysteem af
        LOGGER.debug("Bestandsrechten van het tokenbestand konden niet gezet worden: %s", exc)


def load_token(path: Optional[Path] = None) -> Optional[str]:
    """Lees het token, of geef None als het er nog niet is."""
    target = path or config.TOKEN_PATH
    try:
        token = target.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    return token or None


def ensure_token(path: Optional[Path] = None) -> str:
    """Geef het bestaande token, of maak er een aan.

    Een bestaand maar te kort token wordt vervangen: dat is nooit door deze
    functie geschreven en biedt geen bescherming.
    """
    target = path or config.TOKEN_PATH
    existing = load_token(target)
    if existing and len(existing) >= MIN_TOKEN_LENGTH:
        return existing

    if existing:
        LOGGER.warning("Het bestaande control-token was te kort en is vervangen door een nieuw token.")

    token = secrets.token_urlsafe(TOKEN_BYTES)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(token + "\n", encoding="utf-8")
    _restrict_permissions(target)
    LOGGER.info("Nieuw control-token aangemaakt in %s", target)
    return token


def rotate_token(path: Optional[Path] = None) -> str:
    """Maak een nieuw token aan en overschrijf het oude."""
    target = path or config.TOKEN_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    target.write_text(token + "\n", encoding="utf-8")
    _restrict_permissions(target)
    return token


def extract_token(authorization: Optional[str], header_token: Optional[str]) -> Optional[str]:
    """Haal het token uit ``Authorization: Bearer ...`` of ``X-Jarvis-Token``."""
    if header_token and header_token.strip():
        return header_token.strip()
    if authorization:
        value = authorization.strip()
        if value.lower().startswith("bearer "):
            candidate = value[7:].strip()
            return candidate or None
        return value or None
    return None


def token_matches(presented: Optional[str], expected: Optional[str]) -> bool:
    """Vergelijk in constante tijd, zodat de lengte niets verraadt."""
    if not presented or not expected:
        return False
    return secrets.compare_digest(presented, expected)


def masked(token: Optional[str]) -> str:
    """Toon alleen de laatste vier tekens -- genoeg om te herkennen, te weinig om te gebruiken."""
    if not token:
        return "(geen token)"
    if len(token) <= 4:
        return "*" * len(token)
    return "*" * 12 + token[-4:]
