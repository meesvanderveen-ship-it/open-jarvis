"""De README moet kloppen met wat er werkelijk in het project staat.

Documentatie voor een niet-programmeur is alleen bruikbaar als elk genoemd
bestand bestaat en elke genoemde instelling echt gelezen wordt. Een verwijzing
naar een bestand dat er niet is, is voor die lezer een doodlopende weg -- hij
kan niet zien dat de documentatie fout is in plaats van zijn installatie.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


def test_readme_exists_and_is_not_a_stub(readme: str) -> None:
    assert len(readme) > 4000, "de README moet een echte handleiding zijn"


def test_every_local_link_points_at_an_existing_file(readme: str) -> None:
    """Een kapotte link stuurt de lezer naar een bestand dat niet bestaat."""
    links = re.findall(r"\]\((?!https?://|#)([^)]+)\)", readme)

    missing = [target for target in links if not (PROJECT_ROOT / target.split("#")[0]).exists()]

    assert missing == [], f"README verwijst naar ontbrekende bestanden: {missing}"


def test_every_backticked_bat_file_exists(readme: str) -> None:
    for name in sorted(set(re.findall(r"`([A-Za-z0-9._-]+\.bat)`", readme))):
        assert (PROJECT_ROOT / name).exists(), f"README noemt {name}, dat niet bestaat"


def test_the_technical_readme_was_kept_not_deleted() -> None:
    """De oude README bevatte de volledige technische uitleg.

    Die is verplaatst, niet weggegooid: een handleiding voor een
    niet-programmeur mag de documentatie voor een programmeur niet vervangen.
    """
    technical = PROJECT_ROOT / "docs" / "TECHNISCHE-README.md"

    assert technical.exists()
    assert len(technical.read_text(encoding="utf-8")) > 40000
    assert "docs/TECHNISCHE-README.md" in README.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Instellingen die de README noemt
# --------------------------------------------------------------------------

#: Instellingen die de README als "veilig om aan te passen" presenteert.
DOCUMENTED_SETTINGS = [
    "DASHBOARD_PORT",
    "JARVIS_CONTROL_PORT",
    "JARVIS_RECOVERY_BASE_DELAY",
    "JARVIS_RECOVERY_MAX_DELAY",
    "JARVIS_SUPERVISOR_MAX_RESTARTS",
    "LOG_LEVEL",
]


@pytest.mark.parametrize("setting", DOCUMENTED_SETTINGS)
def test_documented_settings_appear_in_env_example(setting: str) -> None:
    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert re.search(rf"^{setting}=", text, re.M), f"{setting} staat niet in .env.example"


def test_documented_recovery_settings_really_change_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    """Een gedocumenteerde instelling moet effect hebben, niet alleen bestaan.

    Zoeken op de naam in de broncode is hier geen bewijs: de resilience-laag
    stelt variabelenamen samen uit een prefix, dus JARVIS_RECOVERY_MAX_DELAY
    komt nergens letterlijk voor terwijl hij wel degelijk gelezen wordt. Alleen
    het gedrag meten toont aan dat de README de waarheid vertelt.
    """
    from bot.resilience import RetryPolicy

    monkeypatch.setenv("JARVIS_RECOVERY_BASE_DELAY", "7")
    monkeypatch.setenv("JARVIS_RECOVERY_MAX_DELAY", "11")
    monkeypatch.setenv("JARVIS_RECOVERY_JITTER", "0")

    policy = RetryPolicy.from_env("JARVIS_RECOVERY", base_delay=30.0, max_delay=300.0)

    assert policy.base_delay == pytest.approx(7.0)
    assert policy.max_delay == pytest.approx(11.0)
    assert policy.delay_for(2) == pytest.approx(7.0)
    assert policy.delay_for(9) == pytest.approx(11.0)


def test_documented_supervisor_setting_really_changes_behaviour(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot.supervisor import SupervisorPolicy

    monkeypatch.setenv("JARVIS_SUPERVISOR_MAX_RESTARTS", "3")

    assert SupervisorPolicy.from_env().max_restarts == 3


@pytest.mark.parametrize("setting", ["DASHBOARD_PORT", "JARVIS_CONTROL_PORT", "LOG_LEVEL"])
def test_documented_settings_are_read_by_name(setting: str) -> None:
    """Deze drie worden wel letterlijk uit de omgeving gelezen."""
    hits = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in {".venv", "__pycache__", "tests", ".git"} for part in path.parts):
            continue
        if setting in path.read_text(encoding="utf-8"):
            hits.append(path.name)

    assert hits, f"{setting} wordt nergens in de code gelezen"


def test_readme_documents_all_five_control_scripts(readme: str) -> None:
    for name in ("install.bat", "start.bat", "stop.bat", "restart.bat", "diagnose.bat"):
        assert name in readme, f"{name} staat niet in de README"


def test_readme_explains_the_three_credential_outcomes(readme: str) -> None:
    """Het verschil tussen 'afgewezen' en 'niet bereikbaar' moet erin staan."""
    lowered = readme.lower()

    assert "afgewezen" in lowered
    assert "niet bereikbaar" in lowered
    assert "er is niets mis met je sleutel" in lowered


def test_readme_warns_about_real_money_before_anything_else(readme: str) -> None:
    warning_position = readme.lower().find("echte orders plaatsen met echt geld")
    install_position = readme.find("## 1. Installeren")

    assert warning_position != -1, "de waarschuwing over echt geld ontbreekt"
    assert warning_position < install_position, "de waarschuwing hoort vóór de installatie"


def test_readme_never_asks_the_user_to_share_a_secret(readme: str) -> None:
    lowered = readme.lower()

    assert "deel hem met niemand" in lowered or "doe dat niet" in lowered
    assert "sk-" not in readme, "er staat iets dat op een echte sleutel lijkt in de README"


def test_readme_documents_where_the_logs_are(readme: str) -> None:
    for name in ("loop.log", "supervisor.log", "control_service.log"):
        assert name in readme, f"{name} wordt niet in de README genoemd"


def test_readme_documents_uninstalling(readme: str) -> None:
    assert "Verwijderen" in readme
    assert "chrome://extensions" in readme


def test_readme_covers_the_required_failure_situations(readme: str) -> None:
    """De opdracht vraagt expliciet om deze gevallen in de documentatie."""
    lowered = readme.lower()

    for topic in (
        "python is niet gevonden",
        "te oud",
        "installeren van de python-pakketten is mislukt",
        "afgewezen",
        "niet bereikbaar",
        "poort",
        "draait nu niet op deze pc",
    ):
        assert topic in lowered, f"de README behandelt '{topic}' niet"


# --------------------------------------------------------------------------
# De twee handleidingen mogen elkaar niet tegenspreken
# --------------------------------------------------------------------------

INSTALL_GUIDE = PROJECT_ROOT / "INSTALLATIE-WINDOWS.md"


@pytest.fixture(scope="module")
def install_guide() -> str:
    return INSTALL_GUIDE.read_text(encoding="utf-8")


def test_both_guides_name_the_same_minimum_python_version(readme: str, install_guide: str) -> None:
    """Twee documenten die een andere versie noemen sturen de lezer het bos in."""
    from tools.check_python import MINIMUM

    minimum = f"{MINIMUM[0]}.{MINIMUM[1]}"

    assert minimum in readme, f"de README noemt {minimum} niet"
    assert minimum in install_guide, f"de installatiehandleiding noemt {minimum} niet"
    assert "3.12 of nieuwer" not in install_guide, "de oude, te strenge eis staat er nog"


def test_both_guides_describe_stopping_the_same_way(install_guide: str) -> None:
    """Vensters wegklikken kan de bot midden in een handeling afbreken."""
    assert "stop.bat" in install_guide
    assert "Sluit de twee zwarte vensters. Of klik erin" not in install_guide


def test_install_guide_mentions_the_supervisor(install_guide: str) -> None:
    assert "bewaker" in install_guide.lower()


def test_install_guide_mentions_the_chrome_extension(install_guide: str) -> None:
    assert "chrome://extensions" in install_guide
    assert "control_token.txt" in install_guide


def test_install_guide_points_at_the_technical_readme_not_the_old_one(install_guide: str) -> None:
    """De technische uitleg is verplaatst; een verwijzing naar README.md klopt niet meer."""
    assert "TECHNISCHE-README.md" in install_guide
    assert "beschreven in\n`README.md`" not in install_guide


def test_install_guide_separates_unreachable_from_a_wrong_key(install_guide: str) -> None:
    lowered = install_guide.lower()

    assert "niet bereikbaar" in lowered
    assert "geen** sleutelprobleem" in lowered or "geen sleutelprobleem" in lowered


@pytest.mark.parametrize("script", ["install.bat", "start.bat", "stop.bat", "diagnose.bat"])
def test_install_guide_only_names_scripts_that_exist(install_guide: str, script: str) -> None:
    if script in install_guide:
        assert (PROJECT_ROOT / script).exists()
