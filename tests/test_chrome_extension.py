"""Bouw-/structuurcontrole van de Chrome Extension.

Chrome weigert een extensie zonder uitleg als het manifest naar een bestand
wijst dat er niet is. Dat merkt een gebruiker pas bij 'Load unpacked', en dan
staat er alleen een rode balk. Deze tests vangen dat hier af.

Ze bewaken bovendien twee veiligheidseisen die anders alleen in documentatie
zouden staan: minimale permissies, en geen enkel secret in de extensiecode.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

EXTENSION_DIR = Path(__file__).resolve().parents[1] / "extension"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))


def test_extension_directory_exists() -> None:
    assert EXTENSION_DIR.is_dir(), "de map die de gebruiker in Chrome laadt moet bestaan"


def test_manifest_is_version_3() -> None:
    """Chrome accepteert sinds 2024 geen Manifest V2-extensies meer."""
    data = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert data["manifest_version"] == 3


def test_manifest_has_the_fields_chrome_requires(manifest: dict) -> None:
    for field in ("name", "version", "description"):
        assert manifest.get(field), f"manifest.json mist het veld {field}"
    assert re.fullmatch(r"\d+(\.\d+){0,3}", manifest["version"]), "Chrome eist een numerieke versie"


def test_every_file_the_manifest_points_to_actually_exists(manifest: dict) -> None:
    referenced = [
        manifest["action"]["default_popup"],
        manifest["options_page"],
        manifest["background"]["service_worker"],
        *manifest["icons"].values(),
        *manifest["action"]["default_icon"].values(),
    ]

    missing = [name for name in referenced if not (EXTENSION_DIR / name).exists()]

    assert missing == [], f"manifest.json verwijst naar ontbrekende bestanden: {missing}"


def test_html_pages_only_reference_files_that_exist() -> None:
    """Een ontbrekend script of stylesheet levert een leeg popupscherm op."""
    pattern = re.compile(r'(?:src|href)="([^"#:]+)"')
    problems = []
    for page in EXTENSION_DIR.glob("*.html"):
        for reference in pattern.findall(page.read_text(encoding="utf-8")):
            if not (EXTENSION_DIR / reference).exists():
                problems.append(f"{page.name} -> {reference}")

    assert problems == [], f"ontbrekende bestanden: {problems}"


def test_icons_are_real_png_files(manifest: dict) -> None:
    for name in manifest["icons"].values():
        header = (EXTENSION_DIR / name).read_bytes()[:8]
        assert header == b"\x89PNG\r\n\x1a\n", f"{name} is geen geldig PNG-bestand"


# --------------------------------------------------------------------------
# Veiligheid
# --------------------------------------------------------------------------


def test_only_the_minimum_permissions_are_requested(manifest: dict) -> None:
    """Elke extra permissie vergroot wat een gekaapte extensie kan doen."""
    assert set(manifest["permissions"]) <= {"storage", "alarms"}
    assert "tabs" not in manifest["permissions"]
    assert "content_scripts" not in manifest, "content scripts zijn hier niet nodig"


def test_host_permissions_stay_on_the_local_machine(manifest: dict) -> None:
    """De extensie mag nooit met een server op internet kunnen praten."""
    for host in manifest["host_permissions"] + manifest.get("optional_host_permissions", []):
        assert re.match(r"^https?://(127\.0\.0\.1|localhost)(:\d+)?/", host), host


def test_no_wildcard_host_permission(manifest: dict) -> None:
    for host in manifest["host_permissions"] + manifest.get("optional_host_permissions", []):
        assert "<all_urls>" not in host
        assert not host.startswith("*://")


def test_extension_source_contains_no_credentials() -> None:
    """De API-sleutels van Coinbase en OpenAI horen alleen in het Python-proces."""
    forbidden = re.compile(
        r"(sk-[A-Za-z0-9]{20,}|BEGIN [A-Z ]*PRIVATE KEY|COINBASE_API_SECRET\s*=\s*['\"][^'\"]+)"
    )
    for path in [*EXTENSION_DIR.rglob("*.js"), *EXTENSION_DIR.rglob("*.html"), *EXTENSION_DIR.rglob("*.json")]:
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), f"{path.name} bevat iets dat op een secret lijkt"


def test_extension_never_calls_coinbase_or_openai_directly() -> None:
    """De handelslogica hoort in de backend, niet in browsercode."""
    for path in EXTENSION_DIR.rglob("*.js"):
        text = path.read_text(encoding="utf-8").lower()
        assert "api.coinbase.com" not in text
        assert "api.openai.com" not in text


def test_api_module_talks_only_to_the_control_service() -> None:
    text = (EXTENSION_DIR / "api.js").read_text(encoding="utf-8")

    urls = re.findall(r"https?://[^\s'\"`)]+", text)
    for url in urls:
        assert re.match(r"^https?://(127\.0\.0\.1|localhost)", url), url


def test_api_module_distinguishes_offline_from_unauthorized() -> None:
    """Een niet-draaiende backend mag nooit als 'verkeerde sleutel' verschijnen."""
    text = (EXTENSION_DIR / "api.js").read_text(encoding="utf-8")

    assert "OFFLINE" in text
    assert "UNAUTHORIZED" in text
    assert "START-JARVIS.bat" in text, "de gebruiker moet lezen wat hij moet doen"


def test_every_fetch_has_a_timeout() -> None:
    """Zonder timeout blijft de popup eindeloos op 'Verbinden...' staan."""
    text = (EXTENSION_DIR / "api.js").read_text(encoding="utf-8")

    assert text.count("fetch(") == text.count("signal: controller.signal")


def test_options_page_refuses_a_remote_backend_address() -> None:
    text = (EXTENSION_DIR / "options.js").read_text(encoding="utf-8")

    # De guard is een reguliere expressie, dus de punten staan er escaped in.
    assert r"127\.0\.0\.1" in text and "localhost" in text, "het adresveld moet op de eigen pc begrensd zijn"


def test_popup_explains_that_validation_places_no_trades() -> None:
    text = (EXTENSION_DIR / "popup.html").read_text(encoding="utf-8")

    assert "niets gekocht of verkocht" in text


# --------------------------------------------------------------------------
# Gecontroleerd herstel in de extensie
# --------------------------------------------------------------------------


def test_get_requests_are_retried_before_declaring_the_service_dead() -> None:
    """Eén hapering mag niet als "JARVIS draait niet" gepresenteerd worden.

    De service kan net opstarten, of de eerste aanroep kan traag zijn doordat
    de handelsmotor nog geladen moet worden. Zonder herhaling krijgt de
    gebruiker dan de verkeerde conclusie te zien -- dezelfde fout die de
    Python-kant met retries en backoff juist vermijdt.
    """
    text = (EXTENSION_DIR / "api.js").read_text(encoding="utf-8")

    assert "GET_RETRIES" in text
    assert "RETRY_DELAYS_MS" in text
    assert "attempt <= GET_RETRIES" in text or "attempt < attempts" in text


def test_state_changing_requests_are_never_retried() -> None:
    """Een herhaald startverzoek zou een tweede bot kunnen starten."""
    text = (EXTENSION_DIR / "api.js").read_text(encoding="utf-8")

    assert "method === 'GET' ? GET_RETRIES + 1 : 1" in text, (
        "alleen opvragingen mogen herhaald worden"
    )


def test_retry_delays_increase() -> None:
    text = (EXTENSION_DIR / "api.js").read_text(encoding="utf-8")

    delays = re.search(r"RETRY_DELAYS_MS = \[([^\]]+)\]", text)
    assert delays, "geen wachttijden gevonden"
    values = [int(part.strip()) for part in delays.group(1).split(",")]
    assert values == sorted(values) and len(set(values)) > 1, "de wachttijd loopt niet op"


def test_the_health_probe_is_actually_used() -> None:
    """Zonder gebruiker was getHealth dode code met een misleidend doel."""
    options = (EXTENSION_DIR / "options.js").read_text(encoding="utf-8")

    assert "getHealth" in options


def test_options_page_separates_a_dead_service_from_a_bad_key() -> None:
    """Wie JARVIS niet gestart heeft, mag niet horen dat zijn sleutel fout is."""
    text = (EXTENSION_DIR / "options.js").read_text(encoding="utf-8")

    assert "const health = await getHealth();" in text
    assert "draait, maar accepteert deze sleutel niet" in text
