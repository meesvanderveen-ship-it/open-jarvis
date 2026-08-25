"""Begeleide credential-koppeling voor OpenAI en Coinbase.

Dit is een *toevoeging* naast `tools/setup_wizard.py`. De wizard blijft de
handmatige route; deze module maakt er een zo automatisch mogelijke variant
naast, waarin JARVIS de officiële providerpagina opent en de credential daarna
zelf oppikt in plaats van hem te laten intypen.

Waarom geen volledig automatische key-creatie
---------------------------------------------
Onderzocht voor beide providers; geen van beide biedt er een officiële route
voor:

- OpenAI kan via de Admin API wel *admin*-keys aanmaken
  (POST /v1/organization/admin_api_keys), maar geen project-API-keys -- juist
  het `sk-...`-type dat deze bot gebruikt. En een admin-key aanmaken vereist
  al een admin-key, dus er is geen beginpunt. Project-keys komen uitsluitend
  van de projectpagina in het dashboard.
- Coinbase maakt CDP-API-keys uitsluitend aan in de CDP Portal. Er is geen
  REST-endpoint dat namens een gebruiker een nieuwe sleutel mint.

Dat omzeilen zou neerkomen op het nabootsen van een ingelogde browsersessie:
cookies uitlezen, een privépagina scrapen of MFA passeren. Dat gebeurt hier
niet. In plaats daarvan wordt de officiële pagina geopend en neemt JARVIS de
credential over zodra de gebruiker hem heeft aangemaakt.

Wat er daardoor wél automatisch gaat
------------------------------------
- de juiste officiële pagina openen;
- het gedownloade Coinbase-sleutelbestand vanzelf opmerken en inlezen;
- een OpenAI-sleutel van het klembord oppikken (die moet je bij OpenAI toch
  kopiëren, want hij is daarna niet meer op te vragen);
- opslaan via de bestaande `bot/env_file.py` (atomisch, 0600);
- direct daarna read-only valideren via `bot/credential_status.py`.

Geen enkele functie hier zet een secret in een returnwaarde, foutmelding of
log; alleen de vorm ervan, net als in `credential_status`.
"""

from __future__ import annotations

import os
import subprocess
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

from bot import env_file
from bot.credential_status import (
    COINBASE_KEY_ENV,
    COINBASE_SECRET_ENV,
    OPENAI_KEY_ENV,
    CredentialCheck,
    describe_secret_shape,
    is_placeholder,
)

# Officiële pagina's waar de gebruiker de credential zelf aanmaakt.
OPENAI_API_KEYS_URL = "https://platform.openai.com/api-keys"
COINBASE_CDP_KEYS_URL = "https://portal.cdp.coinbase.com/access/api"

PROVIDER_URLS = {
    "openai": OPENAI_API_KEYS_URL,
    "coinbase": COINBASE_CDP_KEYS_URL,
}

# Reden per provider waarom automatische creatie niet beschikbaar is. Staat
# in code en niet alleen in een docstring, zodat de UI het kan tonen en een
# test erop kan vastleggen.
NO_AUTOMATIC_CREATION_REASON = {
    "openai": (
        "OpenAI biedt geen officieel endpoint om een project-API-key aan te "
        "maken; dat kan alleen op de projectpagina in het dashboard."
    ),
    "coinbase": (
        "Coinbase maakt CDP-API-keys uitsluitend aan in de CDP Portal; er is "
        "geen officieel endpoint dat namens een gebruiker een sleutel aanmaakt."
    ),
}


def automatic_creation_available(provider: str) -> bool:
    """Of de provider officieel programmatische key-creatie ondersteunt.

    Op dit moment voor geen van beide. Deze functie bestaat zodat de rest van
    de code de vraag stelt in plaats van het antwoord aan te nemen: biedt een
    provider het later wél, dan hoeft alleen dit punt te veranderen.
    """
    return False


# --------------------------------------------------------------------------
# Officiële pagina openen
# --------------------------------------------------------------------------


def open_official_page(
    provider: str, *, opener: Callable[[str], bool] = webbrowser.open
) -> bool:
    """Open de officiële credentialpagina van `provider`.

    Retourneert False als er geen browser geopend kon worden; de aanroeper
    toont dan de URL zodat de gebruiker hem zelf kan openen.
    """
    url = PROVIDER_URLS.get(provider)
    if url is None:
        raise ValueError(f"Onbekende provider: {provider}")
    try:
        return bool(opener(url))
    except Exception:
        # Een ontbrekende of stukke browser mag de setup niet laten crashen.
        return False


# --------------------------------------------------------------------------
# Klembord
# --------------------------------------------------------------------------


def _clipboard_command() -> Optional[Sequence[str]]:
    """Het platformcommando dat het klembord naar stdout schrijft."""
    if os.name == "nt":
        # Get-Clipboard is onderdeel van Windows PowerShell; -Raw houdt
        # meerregelige inhoud intact in plaats van er een array van te maken.
        return (
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-Clipboard -Raw",
        )
    if os.uname().sysname == "Darwin":  # type: ignore[attr-defined]
        return ("pbpaste",)
    if os.environ.get("WAYLAND_DISPLAY"):
        return ("wl-paste", "--no-newline")
    if os.environ.get("DISPLAY"):
        return ("xclip", "-selection", "clipboard", "-o")
    return None


def read_clipboard(*, command: Optional[Sequence[str]] = None) -> str:
    """Lees de klembordtekst, of "" als dat hier niet kan.

    Bewust geen extra dependency: elk ondersteund platform heeft hiervoor een
    eigen meegeleverd commando. Ontbreekt dat (een kale Linux-server, geen
    grafische sessie), dan is het resultaat leeg en valt de aanroeper terug op
    handmatig plakken.
    """
    argv = command if command is not None else _clipboard_command()
    if not argv:
        return ""
    try:
        result = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


# --------------------------------------------------------------------------
# OpenAI
# --------------------------------------------------------------------------

# Elke OpenAI API key begint met sk-. De moderne varianten zijn sk-proj-,
# sk-svcacct- en sk-admin-; de ondergrens op lengte houdt losse woorden en
# half gekopieerde waarden buiten de deur zonder een exact formaat af te
# dwingen dat OpenAI later kan wijzigen.
_OPENAI_KEY_PREFIX = "sk-"
_OPENAI_KEY_MIN_LENGTH = 20


def looks_like_openai_key(text: str) -> bool:
    """Of `text` de vorm van een OpenAI API key heeft.

    Alleen een vormtest. Of de sleutel echt geldig is, bepaalt uitsluitend
    OpenAI zelf tijdens de validatiestap.
    """
    candidate = text.strip()
    if len(candidate) < _OPENAI_KEY_MIN_LENGTH:
        return False
    if not candidate.startswith(_OPENAI_KEY_PREFIX):
        return False
    if is_placeholder(candidate):
        return False
    # Een sleutel is één token: witruimte betekent dat er meer dan de sleutel
    # op het klembord staat.
    return not any(char.isspace() for char in candidate)


def wait_for_openai_key_on_clipboard(
    *,
    timeout: float = 180.0,
    poll_interval: float = 1.0,
    clipboard: Callable[[], str] = read_clipboard,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    ignore: str = "",
) -> Optional[str]:
    """Wacht tot er een OpenAI-sleutel op het klembord staat.

    OpenAI toont een nieuwe sleutel één keer en zet er een kopieerknop bij;
    die knop indrukken is dus toch al de bedoelde handeling. Door daarop te
    wachten hoeft er niets getypt of geplakt te worden.

    `ignore` is de klembordinhoud van vóór het wachten: stond daar al een
    sleutel op, dan telt die niet mee, anders zou een oude sleutel meteen als
    "gevonden" gelden.

    Retourneert de sleutel, of None bij een timeout.
    """
    deadline = clock() + timeout
    ignored = ignore.strip()
    while True:
        current = clipboard().strip()
        if current and current != ignored and looks_like_openai_key(current):
            return current
        if clock() >= deadline:
            return None
        sleep(poll_interval)


def store_openai_key(key: str, *, path: Optional[Path] = None) -> Path:
    """Schrijf de OpenAI-sleutel naar .env via de bestaande opslaglaag."""
    return env_file.write_env_values({OPENAI_KEY_ENV: key}, path)


# --------------------------------------------------------------------------
# Coinbase
# --------------------------------------------------------------------------


def _key_file_finder() -> Callable[[], list[Path]]:
    """De zoekfunctie van de wizard, lui geïmporteerd.

    Lui omdat `tools.setup_wizard` deze module niet mag hoeven importeren om
    te werken, en om een importcyclus uit te sluiten.
    """
    from tools.setup_wizard import find_coinbase_key_files

    return find_coinbase_key_files


def snapshot_key_files(
    *, finder: Optional[Callable[[], list[Path]]] = None
) -> set[Path]:
    """De sleutelbestanden die er nu al staan.

    Vastleggen vóór het openen van de browser, zodat een bestand van een
    eerdere poging niet wordt aangezien voor de sleutel die nu wordt gemaakt.
    """
    find = finder or _key_file_finder()
    return set(find())


def wait_for_new_coinbase_key_file(
    known: Iterable[Path],
    *,
    timeout: float = 300.0,
    poll_interval: float = 1.0,
    finder: Optional[Callable[[], list[Path]]] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[Path]:
    """Wacht tot er een nieuw CDP-sleutelbestand verschijnt.

    De browser zet het bestand in Downloads; dat is het moment waarop JARVIS
    het kan overnemen. `find_coinbase_key_files` accepteert alleen JSON die
    echt een 'name' en een 'privateKey' bevat, dus een half binnengekomen
    download of een willekeurig ander JSON-bestand telt niet mee.

    Retourneert het pad, of None bij een timeout.
    """
    find = finder or _key_file_finder()
    already = set(known)
    deadline = clock() + timeout
    while True:
        for candidate in find():
            if candidate not in already:
                return candidate
        if clock() >= deadline:
            return None
        sleep(poll_interval)


def store_coinbase_credentials(
    name: str, secret: str, *, path: Optional[Path] = None
) -> Path:
    """Schrijf de Coinbase-credentials naar .env via de bestaande opslaglaag."""
    return env_file.write_env_values(
        {COINBASE_KEY_ENV: name, COINBASE_SECRET_ENV: secret}, path
    )


# --------------------------------------------------------------------------
# Resultaat van een koppelpoging
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConnectOutcome:
    """Uitkomst van één koppeling. Bevat nooit een secret."""

    provider: str
    connected: bool
    summary: str
    detail: str = ""
    check: Optional[CredentialCheck] = None

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "connected": self.connected,
            "summary": self.summary,
            "detail": self.detail,
            "check": self.check.as_dict() if self.check is not None else None,
        }


def describe_stored_shape(value: str) -> dict:
    """Vorm van een opgeslagen waarde, zonder de waarde zelf."""
    return describe_secret_shape(value)
