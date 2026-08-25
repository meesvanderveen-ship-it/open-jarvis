"""JARVIS CONNECTION SETUP — begeleide koppeling van OpenAI en Coinbase.

Naast `tools/setup_wizard.py`, niet in plaats daarvan. De wizard vraagt om
waarden; dit scherm opent de officiële pagina en pikt de credential daarna
zelf op. Alle validatie en opslag loopt via dezelfde modules als de wizard,
zodat beide routes nooit een ander oordeel kunnen vellen.

Draaien:  python -m tools.connect_services
          python -m tools.connect_services --status   (alleen tonen)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Optional

if __package__ in (None, ""):  # direct aangeroepen i.p.v. via -m
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import connect_services, env_file
from bot.credential_status import (
    CONFIGURATION_ERROR,
    COINBASE_KEY_ENV,
    COINBASE_SECRET_ENV,
    OPENAI_KEY_ENV,
    READY,
    SETUP_REQUIRED,
    STATUS_INVALID,
    STATUS_MISSING,
    STATUS_OK,
    STATUS_UNKNOWN,
    VERIFICATION_UNAVAILABLE,
    CredentialCheck,
    collect_checks,
    overall_state,
)

WIDTH = 52

# Statusregels precies zoals in de opdracht beschreven.
_STATUS_LINE = {
    STATUS_OK: "● Connected",
    STATUS_MISSING: "○ Not connected",
    STATUS_INVALID: "✕ Authentication failed",
    STATUS_UNKNOWN: "○ Not verified",
}

_SYSTEM_LINE = {
    READY: "● Ready",
    SETUP_REQUIRED: "○ Setup required",
    CONFIGURATION_ERROR: "✕ Configuration error",
    VERIFICATION_UNAVAILABLE: "○ Not verified",
}


def _rule(char: str = "=") -> str:
    return char * WIDTH


def _print_header(stream=sys.stdout) -> None:
    print(_rule(), file=stream)
    print("       JARVIS CONNECTION SETUP".rstrip(), file=stream)
    print(_rule(), file=stream)


def _credentials_secure() -> bool:
    """Of .env bestaat en alleen voor de eigenaar leesbaar is."""
    return env_file.env_path().exists() and env_file.permissions_are_owner_only()


def render_status(checks: list[CredentialCheck], stream=sys.stdout) -> str:
    """Toon het statusblok. Retourneert de systeemtoestand."""
    state = overall_state(checks)
    by_provider = {check.provider: check for check in checks}

    print("\nSYSTEM STATUS\n", file=stream)
    for provider, label in (("openai", "OpenAI"), ("coinbase", "Coinbase")):
        check = by_provider.get(provider)
        line = _STATUS_LINE.get(check.status, "○ Unknown") if check else "○ Unknown"
        print(f"  {label:<12} {line}", file=stream)

    secure = _credentials_secure()
    print(
        f"  {'Credentials':<12} "
        f"{'● Secure' if secure else '○ Not stored yet'}",
        file=stream,
    )
    print(f"  {'System':<12} {_SYSTEM_LINE.get(state, '○ Unknown')}", file=stream)

    # De reden hoort erbij, anders is een rode regel niet op te lossen. De
    # detailteksten uit credential_status bevatten nooit een secret.
    for check in checks:
        if check.status != STATUS_OK and check.detail:
            print(f"\n  {check.provider}: {check.detail}", file=stream)

    return state


# --------------------------------------------------------------------------
# Koppelen
# --------------------------------------------------------------------------


def connect_openai(
    *,
    stream=sys.stdout,
    opener: Optional[Callable[[str], bool]] = None,
    clipboard: Callable[[], str] = connect_services.read_clipboard,
    prompt: Callable[[str], str] = input,
    timeout: float = 180.0,
    verifier: Optional[Callable[[dict], CredentialCheck]] = None,
    **wait_kwargs,
) -> connect_services.ConnectOutcome:
    """Open de OpenAI-sleutelpagina en neem de nieuwe sleutel over."""
    print("\n[ Connect OpenAI ]\n", file=stream)
    print(
        "  OpenAI biedt geen officiële manier om vanuit een programma een\n"
        "  API-key aan te maken; dat kan alleen op de eigen sleutelpagina.\n"
        "  Die wordt nu geopend.",
        file=stream,
    )

    before = clipboard()
    kwargs = {"opener": opener} if opener is not None else {}
    opened = connect_services.open_official_page("openai", **kwargs)
    print(
        f"\n  {'Pagina geopend.' if opened else 'Kon de browser niet openen.'}\n"
        f"  {connect_services.OPENAI_API_KEYS_URL}",
        file=stream,
    )
    print(
        "\n  Maak daar een key aan en druk op de kopieerknop.\n"
        "  JARVIS pikt hem vanzelf van het klembord; typen hoeft niet.",
        file=stream,
    )

    key = connect_services.wait_for_openai_key_on_clipboard(
        timeout=timeout, clipboard=clipboard, ignore=before, **wait_kwargs
    )

    if key is None:
        print(
            "\n  Geen sleutel op het klembord gezien. Plak hem hieronder,\n"
            "  of laat leeg om over te slaan.",
            file=stream,
        )
        typed = prompt("  OpenAI API Key: ").strip()
        if not typed:
            return connect_services.ConnectOutcome(
                provider="openai",
                connected=False,
                summary="Overgeslagen: geen sleutel ontvangen.",
            )
        key = typed

    connect_services.store_openai_key(key)
    # Vanaf hier telt alleen nog het oordeel van OpenAI zelf.
    print(f"\n  Ontvangen ({len(key)} tekens) en opgeslagen. Valideren...", file=stream)

    if verifier is None:
        from bot.credential_status import verify_openai as verifier  # type: ignore[assignment]

    check = verifier({OPENAI_KEY_ENV: key})
    return connect_services.ConnectOutcome(
        provider="openai",
        connected=check.ok,
        summary=check.summary,
        detail=check.detail,
        check=check,
    )


def connect_coinbase(
    *,
    stream=sys.stdout,
    opener: Optional[Callable[[str], bool]] = None,
    prompt: Callable[[str], str] = input,
    timeout: float = 300.0,
    finder: Optional[Callable[[], list[Path]]] = None,
    verifier: Optional[Callable[[dict], CredentialCheck]] = None,
    **wait_kwargs,
) -> connect_services.ConnectOutcome:
    """Open de Coinbase CDP-portal en neem het gedownloade sleutelbestand over."""
    print("\n[ Connect Coinbase ]\n", file=stream)
    print(
        "  Coinbase maakt CDP-sleutels alleen aan in de eigen portal; die\n"
        "  wordt nu geopend.",
        file=stream,
    )

    known = connect_services.snapshot_key_files(finder=finder)
    kwargs = {"opener": opener} if opener is not None else {}
    opened = connect_services.open_official_page("coinbase", **kwargs)
    print(
        f"\n  {'Pagina geopend.' if opened else 'Kon de browser niet openen.'}\n"
        f"  {connect_services.COINBASE_CDP_KEYS_URL}",
        file=stream,
    )
    print(
        "\n  Maak daar een API-key aan van het type ECDSA en download het\n"
        "  JSON-bestand. JARVIS ziet de download vanzelf verschijnen;\n"
        "  openen of een pad intypen hoeft niet.",
        file=stream,
    )

    path = connect_services.wait_for_new_coinbase_key_file(
        known, timeout=timeout, finder=finder, **wait_kwargs
    )

    if path is None:
        print(
            "\n  Geen nieuw sleutelbestand gezien. Sleep het bestand hierheen\n"
            "  of plak het pad, of laat leeg om over te slaan.",
            file=stream,
        )
        typed = prompt("  Pad naar het JSON-bestand: ").strip().strip('"').strip("'")
        if not typed:
            return connect_services.ConnectOutcome(
                provider="coinbase",
                connected=False,
                summary="Overgeslagen: geen sleutelbestand ontvangen.",
            )
        path = Path(typed)

    from tools.setup_wizard import load_coinbase_key_file

    try:
        name, secret = load_coinbase_key_file(path)
    except ValueError as exc:
        # De melding van load_coinbase_key_file beschrijft het bestand, nooit
        # de inhoud van de sleutel.
        return connect_services.ConnectOutcome(
            provider="coinbase",
            connected=False,
            summary="Sleutelbestand onbruikbaar.",
            detail=str(exc),
        )

    connect_services.store_coinbase_credentials(name, secret)
    print(f"\n  Gevonden: {path.name}", file=stream)
    print("  Opgeslagen. Valideren met een read-only accountopvraging...", file=stream)

    if verifier is None:
        from bot.credential_status import verify_coinbase as verifier  # type: ignore[assignment]

    check = verifier({COINBASE_KEY_ENV: name, COINBASE_SECRET_ENV: secret})
    return connect_services.ConnectOutcome(
        provider="coinbase",
        connected=check.ok,
        summary=check.summary,
        detail=check.detail,
        check=check,
    )


# --------------------------------------------------------------------------
# Hoofdflow
# --------------------------------------------------------------------------


def run(
    *,
    stream=sys.stdout,
    online: bool = True,
    prompt: Callable[[str], str] = input,
    connect_openai_fn: Callable[..., connect_services.ConnectOutcome] = connect_openai,
    connect_coinbase_fn: Callable[..., connect_services.ConnectOutcome] = connect_coinbase,
) -> int:
    """Toon de status en koppel wat er nog niet staat.

    One-click gedrag: staat alles al goed, dan wordt er niets gevraagd.
    """
    _print_header(stream)

    env_file.ensure_env_from_example()
    checks = collect_checks(online=online)
    state = render_status(checks, stream)

    if state == READY:
        print(f"\n{_rule('-')}", file=stream)
        print("\n  Alles staat al gekoppeld. Geen setup nodig.", file=stream)
        print("\n  [ START JARVIS ]", file=stream)
        print(f"\n{_rule()}", file=stream)
        return 0

    print(f"\n{_rule('-')}", file=stream)

    by_provider = {check.provider: check for check in checks}
    for provider, connector in (
        ("openai", connect_openai_fn),
        ("coinbase", connect_coinbase_fn),
    ):
        check = by_provider.get(provider)
        if check is not None and check.status == STATUS_OK:
            continue
        outcome = connector(stream=stream, prompt=prompt)
        mark = "●" if outcome.connected else "✕"
        print(f"\n  {mark} {outcome.summary}", file=stream)
        if outcome.detail and not outcome.connected:
            print(f"    {outcome.detail}", file=stream)

    # Opnieuw meten in plaats van de uitkomsten optellen: alleen een verse
    # controle bewijst dat wat er nu op schijf staat ook echt werkt.
    print(f"\n{_rule('-')}", file=stream)
    final_checks = collect_checks(online=online)
    final_state = render_status(final_checks, stream)

    print(f"\n{_rule('-')}", file=stream)
    if final_state == READY:
        print("\n  [ START JARVIS ]", file=stream)
    else:
        print("\n  Nog niet startklaar. Hierboven staat wat er mist.", file=stream)
    print(f"\n{_rule()}", file=stream)

    from tools.setup_wizard import exit_code_for

    return exit_code_for(final_state)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.connect_services",
        description="Koppel OpenAI en Coinbase aan JARVIS.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Alleen de huidige status tonen, niets koppelen.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Geen API-validatie; alleen controleren wat er opgeslagen staat.",
    )
    args = parser.parse_args(argv)

    if args.status:
        _print_header()
        checks = collect_checks(online=not args.offline)
        state = render_status(checks)
        print(f"\n{_rule()}")
        from tools.setup_wizard import exit_code_for

        return exit_code_for(state)

    return run(online=not args.offline)


if __name__ == "__main__":
    raise SystemExit(main())
