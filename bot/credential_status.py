"""Credential-status en -validatie voor OpenAI en Coinbase.

Eén canonieke plek die antwoord geeft op "is dit correct geconfigureerd?",
gebruikt door de setup-wizard, de startup-preflight en het read-only
dashboard. Zo kan geen van die drie een ander oordeel vellen dan de andere.

Twee niveaus:

- *offline* (`check_openai` / `check_coinbase`): leest alleen de omgeving en
  de vorm van de waarde. Geen netwerk, altijd veilig, altijd snel.
- *online* (`verify_openai` / `verify_coinbase`): één read-only request per
  provider om te bewijzen dat de credentials echt geaccepteerd worden.
  Nooit een order, nooit een mutatie.

Geen enkele functie hier zet een secret in een returnwaarde, foutmelding of
log. Alleen de *vorm* (lengte, prefix, sleuteltype) wordt gerapporteerd.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

OPENAI_KEY_ENV = "OPENAI_API_KEY"
COINBASE_KEY_ENV = "COINBASE_API_KEY"
COINBASE_SECRET_ENV = "COINBASE_API_SECRET"

# Waarden uit .env.example. Wie het bestand kopieert en vergeet te bewerken
# heeft een niet-lege maar betekenisloze waarde; die telt niet als geconfigureerd.
_PLACEHOLDER_VALUES = {
    "your_openai_api_key_here",
    "your_deepseek_api_key_here",
    "your_anthropic_api_key_here",
    "<your-org-id>",
    "<your-key-id>",
    "<your_base64_key_body>",
}

_PLACEHOLDER_MARKERS = ("your_", "your-", "<your", "changeme", "xxxxx", "placeholder")

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_INVALID = "invalid"
STATUS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class CredentialCheck:
    """Uitkomst van één provider-controle. Bevat nooit een secret."""

    provider: str
    status: str
    summary: str
    detail: str = ""
    facts: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def configured(self) -> bool:
        return self.status in {STATUS_OK, STATUS_UNKNOWN}

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "ok": self.ok,
            "configured": self.configured,
            "summary": self.summary,
            "detail": self.detail,
            "facts": dict(self.facts),
        }


def _read(env: Optional[Mapping[str, str]], name: str) -> str:
    source = os.environ if env is None else env
    return (source.get(name) or "").strip()


def is_placeholder(value: str) -> bool:
    """True voor onbewerkte voorbeeldwaarden uit .env.example."""
    candidate = value.strip()
    if not candidate:
        return False
    if candidate in _PLACEHOLDER_VALUES:
        return True
    lowered = candidate.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_MARKERS)


def describe_secret_shape(value: str) -> dict[str, Any]:
    """Beschrijf een secret zonder het te onthullen.

    Alleen lengte en grove vorm; genoeg om te debuggen, te weinig om te
    misbruiken.
    """
    stripped = value.strip()
    return {
        "present": bool(stripped),
        "length": len(stripped),
        "looks_like_pem": "-----BEGIN" in stripped,
    }


# --------------------------------------------------------------------------
# OpenAI
# --------------------------------------------------------------------------


def check_openai(env: Optional[Mapping[str, str]] = None) -> CredentialCheck:
    """Offline controle van OPENAI_API_KEY."""
    raw = _read(env, OPENAI_KEY_ENV)

    if not raw:
        return CredentialCheck(
            provider="openai",
            status=STATUS_MISSING,
            summary="OpenAI API key ontbreekt.",
            detail=(
                f"Zet {OPENAI_KEY_ENV} in .env. Draai `python -m tools.setup_wizard` "
                "om dit begeleid te doen."
            ),
        )

    if is_placeholder(raw):
        return CredentialCheck(
            provider="openai",
            status=STATUS_INVALID,
            summary="OpenAI API key is nog de voorbeeldwaarde.",
            detail=(
                f"{OPENAI_KEY_ENV} bevat nog de placeholder uit .env.example. "
                "Vervang die door je echte sleutel."
            ),
        )

    return CredentialCheck(
        provider="openai",
        status=STATUS_OK,
        summary="OpenAI credentials aanwezig.",
        facts={"key_length": len(raw)},
    )


def verify_openai(
    env: Optional[Mapping[str, str]] = None,
    *,
    timeout: float = 15.0,
    session: Any = None,
) -> CredentialCheck:
    """Read-only bewijs dat OpenAI de sleutel accepteert.

    Gebruikt `GET /v1/models`: geen tokens, geen kosten, geen zijeffecten.
    """
    offline = check_openai(env)
    if not offline.ok:
        return offline

    import requests

    api_key = _read(env, OPENAI_KEY_ENV)
    http = session or requests

    try:
        response = http.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except Exception as exc:  # netwerk/DNS/TLS
        return CredentialCheck(
            provider="openai",
            status=STATUS_UNKNOWN,
            summary="OpenAI niet bereikbaar.",
            detail=(
                "De sleutel is aanwezig maar kon niet worden geverifieerd: "
                f"{type(exc).__name__}. Dit is een netwerkprobleem, geen sleutelprobleem."
            ),
        )

    status_code = getattr(response, "status_code", 0)

    if status_code == 200:
        return CredentialCheck(
            provider="openai",
            status=STATUS_OK,
            summary="OpenAI authenticatie geslaagd.",
            facts={"http_status": 200},
        )

    if status_code in (401, 403):
        return CredentialCheck(
            provider="openai",
            status=STATUS_INVALID,
            summary="OpenAI authenticatie mislukt.",
            detail=(
                f"OpenAI wees de sleutel af (HTTP {status_code}). Controleer of de "
                "sleutel geldig en niet ingetrokken is."
            ),
            facts={"http_status": status_code},
        )

    return CredentialCheck(
        provider="openai",
        status=STATUS_UNKNOWN,
        summary="OpenAI gaf een onverwacht antwoord.",
        detail=f"HTTP {status_code}. Sleutel niet bevestigd, maar ook niet afgewezen.",
        facts={"http_status": status_code},
    )


# --------------------------------------------------------------------------
# Coinbase
# --------------------------------------------------------------------------


def check_coinbase(env: Optional[Mapping[str, str]] = None) -> CredentialCheck:
    """Offline controle van COINBASE_API_KEY en COINBASE_API_SECRET.

    Laadt de private key daadwerkelijk, zodat een onbruikbaar sleutelformaat
    hier aan het licht komt en niet pas midden in een handelscyclus.
    """
    key = _read(env, COINBASE_KEY_ENV)
    secret = _read(env, COINBASE_SECRET_ENV)

    missing = [
        name
        for name, value in ((COINBASE_KEY_ENV, key), (COINBASE_SECRET_ENV, secret))
        if not value
    ]
    if missing:
        return CredentialCheck(
            provider="coinbase",
            status=STATUS_MISSING,
            summary="Coinbase credentials ontbreken.",
            detail=(
                f"Niet ingesteld: {', '.join(missing)}. Neem 'name' en 'privateKey' "
                "over uit het JSON-bestand dat Coinbase je laat downloaden."
            ),
            facts={"missing": missing},
        )

    if is_placeholder(key) or is_placeholder(secret):
        return CredentialCheck(
            provider="coinbase",
            status=STATUS_INVALID,
            summary="Coinbase credentials zijn nog voorbeeldwaarden.",
            detail=(
                "De waarden komen nog uit .env.example. Vervang ze door de echte "
                "'name' en 'privateKey' uit je Coinbase CDP-sleutelbestand."
            ),
        )

    # Hergebruikt exact de auth-code die de bot zelf gebruikt, zodat de
    # controle niet kan afwijken van de werkelijke runtime.
    import coinbase_auth

    previous_cache = coinbase_auth._CACHED_PRIVATE_KEY
    previous_env: dict[str, Optional[str]] = {}
    try:
        if env is not None:
            for name in (COINBASE_KEY_ENV, COINBASE_SECRET_ENV):
                previous_env[name] = os.environ.get(name)
                os.environ[name] = env.get(name, "")

        coinbase_auth._CACHED_PRIVATE_KEY = None
        try:
            coinbase_auth.get_api_key()
        except ValueError as exc:
            return CredentialCheck(
                provider="coinbase",
                status=STATUS_INVALID,
                summary="Coinbase API key heeft een ongeldig formaat.",
                detail=str(exc),
            )

        try:
            private_key = coinbase_auth.get_private_key()
            algorithm = coinbase_auth._jwt_algorithm_for(private_key)
        except ValueError as exc:
            return CredentialCheck(
                provider="coinbase",
                status=STATUS_INVALID,
                summary="Coinbase private key kon niet worden gelezen.",
                detail=str(exc),
                facts=describe_secret_shape(secret),
            )
    finally:
        coinbase_auth._CACHED_PRIVATE_KEY = previous_cache
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    key_type = "Ed25519" if algorithm == "EdDSA" else "ECDSA (P-256)"
    return CredentialCheck(
        provider="coinbase",
        status=STATUS_OK,
        summary=f"Coinbase credentials aanwezig ({key_type}).",
        facts={"key_type": key_type, "jwt_algorithm": algorithm},
    )


def verify_coinbase(
    env: Optional[Mapping[str, str]] = None,
    *,
    timeout: float = 15.0,
    client: Any = None,
) -> CredentialCheck:
    """Read-only bewijs dat Coinbase de credentials accepteert.

    Vraagt de accountlijst op. Dat is een GET zonder zijeffecten; er wordt
    geen order geplaatst en niets gewijzigd.
    """
    offline = check_coinbase(env)
    if not offline.ok:
        return offline

    previous_env: dict[str, Optional[str]] = {}
    try:
        if env is not None:
            for name in (COINBASE_KEY_ENV, COINBASE_SECRET_ENV):
                previous_env[name] = os.environ.get(name)
                os.environ[name] = env.get(name, "")

        if client is None:
            from bot.coinbase_client import CoinbaseClient

            client = CoinbaseClient()

        try:
            payload = client.get_accounts()
        except Exception as exc:
            return _coinbase_failure_from_exception(exc, offline)
    finally:
        for name, value in previous_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    from bot.coinbase_client import _extract_accounts_list

    count = len(_extract_accounts_list(payload))
    return CredentialCheck(
        provider="coinbase",
        status=STATUS_OK,
        summary="Coinbase authenticatie geslaagd.",
        detail=f"Read-only accountopvraging gelukt ({count} accounts zichtbaar).",
        facts={**offline.facts, "accounts_visible": count},
    )


_HTTP_ERROR_PREFIX = "Coinbase HTTP error "


def _http_status_from_client_error(text: str) -> Optional[int]:
    """Haal de HTTP-status uit een CoinbaseClient-foutmelding.

    Retourneert None als de fout geen antwoord van Coinbase was (netwerk,
    proxy, timeout) -- dan valt er over de credentials niets te concluderen.
    """
    if _HTTP_ERROR_PREFIX not in text:
        return None
    remainder = text.split(_HTTP_ERROR_PREFIX, 1)[1]
    digits = ""
    for char in remainder:
        if not char.isdigit():
            break
        digits += char
    return int(digits) if digits else None


def _coinbase_failure_from_exception(exc: Exception, offline: CredentialCheck) -> CredentialCheck:
    """Vertaal een clientfout naar een oordeel, zonder secrets door te geven.

    CoinbaseClient._request maakt zelf al het onderscheid dat hier telt:
    een antwoord van Coinbase komt terug als "Coinbase HTTP error <status>",
    en alles wat de server nooit bereikte als "Coinbase request failed".

    Dat onderscheid moet hier gerespecteerd worden. Zoeken naar "403" in de
    hele fouttekst is te grof: een bedrijfsproxy die de verbinding weigert
    meldt ook 403, en dan zou een netwerkstoring als "sleutel afgewezen"
    gerapporteerd worden -- de gebruiker gaat dan een prima sleutel vervangen.
    """
    text = str(exc)
    status = _http_status_from_client_error(text)
    unauthorized = status in {401, 403}

    if unauthorized:
        detail = (
            "Coinbase wees de credentials af. Controleer of de sleutel nog actief "
            "is en of 'View'-rechten aanstaan voor deze API-key."
        )
        # Coinbase documenteert Ed25519 als voorkeur voor CDP in het algemeen,
        # maar noemt bij Advanced Trade dat daar ECDSA gebruikt moet worden.
        # Wordt een Ed25519-sleutel hier afgewezen, dan is dat de eerste
        # verdenking -- en een ECDSA-sleutel werkt in deze bot net zo goed.
        if offline.facts.get("jwt_algorithm") == "EdDSA":
            detail += (
                " Deze sleutel is van het type Ed25519. Coinbase Advanced Trade "
                "accepteert mogelijk alleen ECDSA; maak in dat geval een nieuwe "
                "API-key aan van het type ECDSA en draai de setup opnieuw."
            )
        return CredentialCheck(
            provider="coinbase",
            status=STATUS_INVALID,
            summary="Coinbase authenticatie mislukt.",
            detail=detail,
            facts=offline.facts,
        )

    if status is not None:
        return CredentialCheck(
            provider="coinbase",
            status=STATUS_UNKNOWN,
            summary="Coinbase gaf een onverwacht antwoord.",
            detail=(
                f"HTTP {status}. De credentials zijn niet afgewezen, maar ook niet "
                "bevestigd. Dit wijst op een probleem aan de kant van Coinbase."
            ),
            facts={**offline.facts, "http_status": status},
        )

    return CredentialCheck(
        provider="coinbase",
        status=STATUS_UNKNOWN,
        summary="Coinbase niet bereikbaar.",
        detail=(
            "De credentials zijn geldig van vorm maar konden niet worden geverifieerd; "
            "het verzoek bereikte Coinbase niet. Dat wijst op een netwerk-, proxy- of "
            "internetprobleem, niet op een verkeerde sleutel."
        ),
        facts=offline.facts,
    )


# --------------------------------------------------------------------------
# Samenvatting
# --------------------------------------------------------------------------

READY = "READY"
SETUP_REQUIRED = "SETUP_REQUIRED"
CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
VERIFICATION_UNAVAILABLE = "VERIFICATION_UNAVAILABLE"


def overall_state(checks: list[CredentialCheck]) -> str:
    """Vertaal losse controles naar één systeemtoestand.

    Volgorde van ernst: afgewezen credentials wegen zwaarder dan ontbrekende,
    en die weer zwaarder dan een controle die niet uitgevoerd kon worden.

    Een niet-uitgevoerde controle mag nooit als READY doorgaan. Anders zou een
    netwerkstoring tijdens de online verificatie een succesmelding opleveren
    terwijl niemand weet of de sleutels werken. Offline levert geen enkele
    controle deze toestand op, dus daar verandert niets.
    """
    if any(check.status == STATUS_INVALID for check in checks):
        return CONFIGURATION_ERROR
    if any(check.status == STATUS_MISSING for check in checks):
        return SETUP_REQUIRED
    if any(check.status == STATUS_UNKNOWN for check in checks):
        return VERIFICATION_UNAVAILABLE
    return READY


def collect_checks(
    env: Optional[Mapping[str, str]] = None, *, online: bool = False, timeout: float = 15.0
) -> list[CredentialCheck]:
    if online:
        return [
            verify_openai(env, timeout=timeout),
            verify_coinbase(env, timeout=timeout),
        ]
    return [check_openai(env), check_coinbase(env)]


def status_report(
    env: Optional[Mapping[str, str]] = None, *, online: bool = False, timeout: float = 15.0
) -> dict[str, Any]:
    """Machineleesbare status, veilig om te loggen of via HTTP te serveren."""
    checks = collect_checks(env, online=online, timeout=timeout)
    return {
        "state": overall_state(checks),
        "verified_online": online,
        "providers": {check.provider: check.as_dict() for check in checks},
    }
