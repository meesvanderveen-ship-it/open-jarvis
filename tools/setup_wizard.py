"""Begeleide credential-setup: `python -m tools.setup_wizard`.

Vervangt het handmatig bewerken van .env. De wizard vraagt om de OpenAI- en
Coinbase-credentials, schrijft ze met eigenaar-only rechten weg en valideert
ze daarna read-only.

Waarom een CLI en geen pagina in het dashboard: `dashboard/backend/app.py`
legt als harde invariant vast dat geen enkel endpoint naar .env schrijft of
Coinbase aanroept, en de backend heeft geen authenticatie. Credential-invoer
daar inbouwen zou beide eigenschappen breken. Het dashboard toont de status
wel (read-only), via dezelfde module die deze wizard gebruikt.

Modi:
    python -m tools.setup_wizard              interactief instellen + valideren
    python -m tools.setup_wizard --check      alleen status tonen, niets wijzigen
    python -m tools.setup_wizard --check --online   status inclusief API-verificatie
    python -m tools.setup_wizard --json       machineleesbare status

Er wordt nooit een secret getoond, gelogd of teruggeschreven naar de console.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from getpass import getpass
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import env_file
from bot.credential_status import (
    COINBASE_KEY_ENV,
    COINBASE_SECRET_ENV,
    CONFIGURATION_ERROR,
    OPENAI_KEY_ENV,
    READY,
    SETUP_REQUIRED,
    VERIFICATION_UNAVAILABLE,
    STATUS_MISSING,
    STATUS_INVALID,
    STATUS_OK,
    STATUS_UNKNOWN,
    CredentialCheck,
    collect_checks,
    is_placeholder,
    overall_state,
)

_MARK = {
    STATUS_OK: "✓",
    STATUS_MISSING: "✗",
    STATUS_INVALID: "✗",
    STATUS_UNKNOWN: "!",
}

_STATE_MESSAGE = {
    READY: "JARVIS READY — configuratie compleet, de bot kan starten.",
    SETUP_REQUIRED: "SETUP REQUIRED — er ontbreken credentials.",
    CONFIGURATION_ERROR: "CONFIGURATION ERROR — credentials aanwezig maar niet bruikbaar.",
    VERIFICATION_UNAVAILABLE: (
        "API-VALIDATIE NIET UITGEVOERD — de credentials staan goed opgeslagen, "
        "maar konden niet bij de API gecontroleerd worden."
    ),
}

# Exit-codes, zodat scripts het onderscheid kunnen maken:
#   0 = alles goed en geverifieerd
#   1 = credentials ontbreken of zijn afgewezen
#   2 = credentials ogen goed, maar de API was niet bereikbaar
EXIT_OK = 0
EXIT_INVALID = 1
EXIT_UNVERIFIED = 2


def exit_code_for(state: str) -> int:
    if state == READY:
        return EXIT_OK
    if state == VERIFICATION_UNAVAILABLE:
        return EXIT_UNVERIFIED
    return EXIT_INVALID


def render_checks(checks: list[CredentialCheck], stream=sys.stdout) -> None:
    for check in checks:
        mark = _MARK.get(check.status, "?")
        print(f"\n{check.provider.upper()}", file=stream)
        print(f"  {mark} {check.summary}", file=stream)
        if check.detail:
            print(f"    {check.detail}", file=stream)
        for key, value in sorted(check.facts.items()):
            print(f"    {key}: {value}", file=stream)

    state = overall_state(checks)
    print(f"\nSYSTEM\n  {_STATE_MESSAGE[state]}", file=stream)


# --------------------------------------------------------------------------
# Invoer
# --------------------------------------------------------------------------


def _drain_pending_newlines() -> None:
    """Haal losse regeleindes uit de consolebuffer van Windows.

    Rechtermuisklik-plakken in cmd.exe duwt de klembordinhoud inclusief het
    afsluitende CRLF de invoerbuffer in. `msvcrt.getwch()` stopt op de CR en
    laat de LF staan; die beantwoordt dan de *volgende* vraag onmiddellijk met
    een lege invoer. Zonder deze drain worden de Coinbase-vragen dus
    overgeslagen zodra iemand zijn OpenAI-sleutel plakt -- precies het gedrag
    waarbij de installatie leek te stoppen op het moment van invoeren.

    Alleen regeleindes worden weggegooid. Het eerste teken dat iets anders is
    hoort bij de volgende invoer en gaat terug de buffer in.
    """
    import msvcrt

    while msvcrt.kbhit():
        char = msvcrt.getwch()
        if char in ("\x00", "\xe0"):  # functie-/pijltoets stuurt twee tekens
            msvcrt.getwch()
            continue
        if char not in ("\r", "\n"):
            msvcrt.ungetwch(char)
            return


def _windows_read_secret(prompt: str) -> str:
    """Lees een secret op Windows, bestand tegen geplakte invoer.

    Verschillen met `getpass` uit de standaardbibliotheek:
    - regeleindes die van een plakactie zijn overgebleven worden opgeruimd,
      voor en na het lezen;
    - pijl- en functietoetsen belanden niet als rommel in het secret;
    - er verschijnt een sterretje per teken, zodat zichtbaar is dat de invoer
      aankomt. Het secret zelf blijft onleesbaar.
    """
    import msvcrt

    _drain_pending_newlines()
    for char in prompt:
        msvcrt.putwch(char)

    buffer: list[str] = []
    while True:
        char = msvcrt.getwch()
        if char in ("\x00", "\xe0"):
            msvcrt.getwch()
            continue
        if char in ("\r", "\n"):
            break
        if char == "\x03":
            raise KeyboardInterrupt
        if char in ("\b", "\x7f"):
            if buffer:
                buffer.pop()
                for out in "\b \b":
                    msvcrt.putwch(out)
            continue
        buffer.append(char)
        msvcrt.putwch("*")

    msvcrt.putwch("\r")
    msvcrt.putwch("\n")
    _drain_pending_newlines()
    return "".join(buffer)


def read_secret(prompt: str) -> str:
    """Lees een secret; op Windows via de gehardde lezer hierboven."""
    if os.name == "nt" and sys.stdin is sys.__stdin__:
        try:
            return _windows_read_secret(prompt)
        except ImportError:  # msvcrt ontbreekt: val terug op de standaard
            pass
    return getpass(prompt)


def read_line(prompt: str) -> str:
    """Lees zichtbare invoer (een bestandspad, een keuze) -- geen secret."""
    return input(prompt)


def _clean_path_input(raw: str) -> str:
    """Maak een geplakt of gesleept pad bruikbaar.

    Windows Verkenner ("Kopiëren als pad") en slepen-naar-venster zetten
    aanhalingstekens om het pad heen; die horen niet bij de bestandsnaam.
    """
    return raw.strip().strip('"').strip("'").strip()


def _prompt_secret(
    label: str,
    env_key: str,
    current: str,
    *,
    reader: Callable[[str], str] = read_secret,
) -> Optional[str]:
    """Vraag één secret. Lege invoer laat de bestaande waarde staan."""
    has_usable_current = bool(current) and not is_placeholder(current)
    suffix = " [Enter = huidige waarde behouden]" if has_usable_current else ""

    if has_usable_current:
        print(f"  {env_key} is al ingesteld ({len(current)} tekens).")
    elif current:
        print(f"  {env_key} bevat nog een voorbeeldwaarde en moet vervangen worden.")

    value = reader(f"  {label}{suffix}: ").strip()
    if not value:
        if has_usable_current:
            print("    Huidige waarde blijft staan.")
        else:
            print("    Niets ingevoerd.")
        return None

    # Bevestiging zonder het secret te tonen: zo is meteen zichtbaar dat de
    # invoer is aangekomen, en dat er niet per ongeluk één teken binnenkwam.
    print(f"    Ontvangen: {len(value)} tekens.")
    return value


# --------------------------------------------------------------------------
# Coinbase-sleutelbestand
# --------------------------------------------------------------------------

_JSON_NAME_FIELDS = ("name", "apiKeyName", "key_name", "keyName")
_JSON_SECRET_FIELDS = ("privateKey", "private_key", "apiKeySecret", "secret")


def load_coinbase_key_file(path: Path) -> tuple[str, str]:
    """Lees 'name' en 'privateKey' uit een Coinbase CDP-sleutelbestand.

    Dit is de betrouwbare route. De privateKey is in PEM-vorm meerregelig, en
    meerregelige tekst plakken in een consoleprompt gaat per definitie mis: de
    eerste regelovergang sluit de invoer af en de rest wordt als losse
    toetsaanslagen in de volgende vraag getypt.

    Raises:
        ValueError: met een uitlegbare melding als het bestand onbruikbaar is.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Kan het bestand niet lezen: {exc.strerror or exc}.") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Dit is geen geldig JSON-bestand. Kies het bestand dat Coinbase je "
            f"liet downloaden (regel {exc.lineno}: {exc.msg})."
        ) from exc

    if not isinstance(data, dict):
        raise ValueError("Het JSON-bestand bevat geen object met sleutelvelden.")

    def _first(fields: tuple[str, ...]) -> str:
        for field_name in fields:
            value = data.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    name = _first(_JSON_NAME_FIELDS)
    secret = _first(_JSON_SECRET_FIELDS)

    missing = [
        label
        for label, value in (("name", name), ("privateKey", secret))
        if not value
    ]
    if missing:
        raise ValueError(
            f"Veld(en) {', '.join(missing)} ontbreken in dit bestand. "
            "Een CDP-sleutelbestand bevat beide."
        )

    return name, secret


def _looks_like_truncated_pem(value: str) -> bool:
    """True als een PEM-sleutel maar één regel lang lijkt.

    Symptoom van een afgekapte plakactie: het BEGIN-blok is er wel, maar de
    sleutelinhoud en het END-blok niet.
    """
    if "-----BEGIN" not in value:
        return False
    return "\n" not in value and "\\n" not in value


def _prompt_coinbase_from_file(
    *, reader: Callable[[str], str] = read_line
) -> Optional[tuple[str, str]]:
    """Vraag om het pad naar het CDP-sleutelbestand. None = handmatig plakken."""
    print("\n  Aanbevolen: wijs het JSON-bestand aan dat Coinbase je liet")
    print("  downloaden. Sleep het bestand in dit venster of plak het pad.")
    print("  Enter = de twee waarden liever zelf plakken.")

    while True:
        raw = _clean_path_input(reader("  Pad naar het JSON-bestand: "))
        if not raw:
            return None

        path = Path(raw).expanduser()
        if not path.is_file():
            print(f"    Niet gevonden: {path}")
            print("    Probeer opnieuw, of druk op Enter om zelf te plakken.")
            continue

        try:
            name, secret = load_coinbase_key_file(path)
        except ValueError as exc:
            print(f"    {exc}")
            print("    Probeer opnieuw, of druk op Enter om zelf te plakken.")
            continue

        print(f"    Gelezen uit {path.name}: name ({len(name)} tekens) en "
              f"privateKey ({len(secret)} tekens).")
        return name, secret


def run_interactive(*, reader: Callable[[str], str] = read_secret) -> int:
    print("=" * 68)
    print("JARVIS — credential setup")
    print("=" * 68)

    target, created = env_file.ensure_env_from_example()
    if created:
        print(f"\n.env aangemaakt vanaf .env.example ({target}).")
    else:
        print(f"\nBestaand .env gevonden ({target}); bestaande waarden blijven staan.")

    existing = env_file.read_env(target)
    updates: dict[str, str] = {}

    print("\n--- OpenAI ---")
    print("  Je API key van https://platform.openai.com/api-keys")
    openai_key = _prompt_secret("OpenAI API Key", OPENAI_KEY_ENV, existing.get(OPENAI_KEY_ENV, ""), reader=reader)
    if openai_key:
        updates[OPENAI_KEY_ENV] = openai_key

    print("\n--- Coinbase ---")
    print("  Uit het JSON-bestand dat Coinbase je laat downloaden bij het")
    print("  aanmaken van een CDP API-key:")
    print("    - veld 'name'       -> Coinbase API Key")
    print("    - veld 'privateKey' -> Coinbase API Secret")
    print("  Beide sleuteltypes werken: ECDSA (PEM) en Ed25519 (base64).")

    from_file = _prompt_coinbase_from_file()
    if from_file is not None:
        updates[COINBASE_KEY_ENV], updates[COINBASE_SECRET_ENV] = from_file
    else:
        coinbase_key = _prompt_secret(
            "Coinbase API Key (organizations/.../apiKeys/...)",
            COINBASE_KEY_ENV,
            existing.get(COINBASE_KEY_ENV, ""),
            reader=reader,
        )
        if coinbase_key:
            updates[COINBASE_KEY_ENV] = coinbase_key

        coinbase_secret = _prompt_secret(
            "Coinbase API Secret (privateKey)",
            COINBASE_SECRET_ENV,
            existing.get(COINBASE_SECRET_ENV, ""),
            reader=reader,
        )
        if coinbase_secret:
            if _looks_like_truncated_pem(coinbase_secret):
                # Doorschrijven zou een onbruikbare sleutel opleveren en de
                # gebruiker laten zoeken bij Coinbase in plaats van hier.
                print(
                    "\n    De geplakte privateKey lijkt afgekapt: alleen de "
                    "BEGIN-regel is aangekomen."
                )
                print(
                    "    Een PEM-sleutel is meerregelig en overleeft plakken in "
                    "een consolevenster niet."
                )
                print(
                    "    Draai de wizard opnieuw en wijs het JSON-bestand aan; "
                    "die route leest de sleutel in zijn geheel."
                )
                return 1
            updates[COINBASE_SECRET_ENV] = coinbase_secret

    if updates:
        env_file.write_env_values(updates, target)
        print(f"\n{len(updates)} waarde(n) opgeslagen in {target} (rechten 0600).")
    else:
        print("\nGeen wijzigingen; bestaande configuratie blijft ongewijzigd.")

    print("\nValideren...")
    merged = env_file.read_env(target)
    checks = collect_checks(merged, online=False)
    render_checks(checks)

    state = overall_state(checks)
    if state != READY:
        print("\nLos bovenstaande punten op en draai de wizard opnieuw.")
        return 1

    print("\nOfflinecontrole geslaagd. Verifieer de credentials tegen de echte")
    print("API's met:  python -m tools.setup_wizard --check --online")
    print("Start daarna de bot met:  python run_trader_loop.py")
    return 0


def run_from_json(path_text: str) -> int:
    """Zet de Coinbase-credentials uit een sleutelbestand, zonder vragen.

    Bedoeld om een half gelukte setup te repareren zonder de hele wizard,
    en om vanuit een script aan te roepen.
    """
    path = Path(_clean_path_input(path_text)).expanduser()
    if not path.is_file():
        print(f"Bestand niet gevonden: {path}")
        return 1

    try:
        name, secret = load_coinbase_key_file(path)
    except ValueError as exc:
        print(f"Onbruikbaar sleutelbestand: {exc}")
        return 1

    target, _ = env_file.ensure_env_from_example()
    env_file.write_env_values(
        {COINBASE_KEY_ENV: name, COINBASE_SECRET_ENV: secret}, target
    )
    print(f"Coinbase-credentials opgeslagen in {target} (rechten 0600).")

    checks = collect_checks(env_file.read_env(target), online=False)
    render_checks(checks)
    return exit_code_for(overall_state(checks))


def run_check(*, online: bool, as_json: bool) -> int:
    target = env_file.env_path()
    if not target.exists():
        if as_json:
            print(json.dumps({"state": SETUP_REQUIRED, "detail": ".env ontbreekt"}, indent=2))
        else:
            print("SETUP REQUIRED — er is nog geen .env.")
            print("Draai: python -m tools.setup_wizard")
        return 1

    merged = env_file.read_env(target)

    if online and not as_json:
        print("Credentials verifiëren tegen OpenAI en Coinbase (read-only)...")

    checks = collect_checks(merged, online=online)

    if as_json:
        report = {
            "state": overall_state(checks),
            "verified_online": online,
            "providers": {check.provider: check.as_dict() for check in checks},
        }
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        render_checks(checks)
        if not env_file.permissions_are_owner_only(target):
            print(f"\nWaarschuwing: {target} is leesbaar voor andere gebruikers.")
            print(f"Herstel met:  chmod 600 {target}")

    return exit_code_for(overall_state(checks))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.setup_wizard",
        description="Stel de OpenAI- en Coinbase-credentials in en valideer ze.",
    )
    parser.add_argument("--check", action="store_true", help="alleen status tonen, niets wijzigen")
    parser.add_argument("--online", action="store_true", help="verifieer read-only tegen de echte API's")
    parser.add_argument("--json", action="store_true", help="machineleesbare uitvoer (impliceert --check)")
    parser.add_argument(
        "--from-json",
        metavar="PAD",
        help="lees de Coinbase-credentials uit een CDP-sleutelbestand en stop",
    )
    args = parser.parse_args(argv)

    if args.from_json:
        return run_from_json(args.from_json)

    if args.check or args.json or args.online:
        return run_check(online=args.online, as_json=args.json)

    try:
        return run_interactive()
    except (KeyboardInterrupt, EOFError):
        print("\nAfgebroken; er is niets gewijzigd.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
