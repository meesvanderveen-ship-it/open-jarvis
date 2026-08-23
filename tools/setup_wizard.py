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
}


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


def _prompt_secret(
    label: str,
    env_key: str,
    current: str,
    *,
    reader: Callable[[str], str] = getpass,
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
        return None
    return value


def run_interactive(*, reader: Callable[[str], str] = getpass) -> int:
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

    return 0 if overall_state(checks) == READY else 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.setup_wizard",
        description="Stel de OpenAI- en Coinbase-credentials in en valideer ze.",
    )
    parser.add_argument("--check", action="store_true", help="alleen status tonen, niets wijzigen")
    parser.add_argument("--online", action="store_true", help="verifieer read-only tegen de echte API's")
    parser.add_argument("--json", action="store_true", help="machineleesbare uitvoer (impliceert --check)")
    args = parser.parse_args(argv)

    if args.check or args.json or args.online:
        return run_check(online=args.online, as_json=args.json)

    try:
        return run_interactive()
    except (KeyboardInterrupt, EOFError):
        print("\nAfgebroken; er is niets gewijzigd.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
