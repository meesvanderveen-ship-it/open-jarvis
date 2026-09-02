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


# --------------------------------------------------------------------------
# De uitgebreide handleiding
# --------------------------------------------------------------------------

MANUAL = PROJECT_ROOT / "HANDLEIDING-WINDOWS.md"
TROUBLESHOOTING = PROJECT_ROOT / "PROBLEMEN-OPLOSSEN.md"
CHECKLIST = PROJECT_ROOT / "RELEASE-CHECKLIST.md"
RELEASE = PROJECT_ROOT / "RELEASE-CANDIDATE.md"


@pytest.fixture(scope="module")
def manual() -> str:
    return MANUAL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def troubleshooting() -> str:
    return TROUBLESHOOTING.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "document",
    [MANUAL, TROUBLESHOOTING, CHECKLIST, RELEASE],
    ids=lambda path: path.name,
)
def test_every_local_link_in_the_new_documents_resolves(document: Path) -> None:
    """Dezelfde eis als voor de README: geen doodlopende verwijzingen."""
    text = document.read_text(encoding="utf-8")
    links = re.findall(r"\]\((?!https?://|#)([^)]+)\)", text)

    missing = [target for target in links if not (PROJECT_ROOT / target.split("#")[0]).exists()]

    assert missing == [], f"{document.name} verwijst naar ontbrekende bestanden: {missing}"


@pytest.mark.parametrize(
    "document",
    [MANUAL, TROUBLESHOOTING, CHECKLIST, RELEASE],
    ids=lambda path: path.name,
)
def test_the_new_documents_name_no_bat_file_that_is_missing(document: Path) -> None:
    text = document.read_text(encoding="utf-8")

    for name in sorted(set(re.findall(r"`([A-Za-z0-9._-]+\.bat)`", text))):
        assert (PROJECT_ROOT / name).exists(), f"{document.name} noemt {name}, dat niet bestaat"


@pytest.mark.parametrize(
    "document",
    [MANUAL, TROUBLESHOOTING, CHECKLIST, RELEASE],
    ids=lambda path: path.name,
)
def test_no_document_contains_something_that_looks_like_a_real_key(document: Path) -> None:
    """De opdracht is expliciet: nooit echte sleutels in documentatie.

    ``sk-`` is het voorvoegsel van een OpenAI-sleutel en
    ``organizations/`` dat van een Coinbase CDP-sleutelnaam. Beide horen
    alleen als plaatshouder voor te komen, niet als iets dat op een echte
    waarde lijkt.
    """
    text = document.read_text(encoding="utf-8")

    assert "sk-" not in text
    assert "-----BEGIN" not in text, "dat lijkt op een echte private sleutel"


def test_the_manual_is_a_real_manual_not_a_stub(manual: str) -> None:
    assert len(manual) > 15000, "de uitgebreide handleiding moet echt uitgebreid zijn"


def test_the_manual_uses_placeholders_for_keys(manual: str) -> None:
    assert "JOUW_OPENAI_KEY" in manual
    assert "JOUW_COINBASE_KEY" in manual


def test_the_manual_explains_all_four_validation_outcomes(manual: str) -> None:
    """De lezer moet 'afgewezen' van 'niet bereikbaar' kunnen onderscheiden."""
    for state in ("READY", "SETUP_REQUIRED", "CONFIGURATION_ERROR", "VERIFICATION_UNAVAILABLE"):
        assert state in manual, f"de handleiding legt {state} niet uit"


def test_the_manual_promises_that_data_is_kept(manual: str) -> None:
    lowered = manual.lower()

    assert "blijft staan" in lowered or "blijven staan" in lowered
    assert "state" in lowered and "logs" in lowered


def test_the_readme_points_at_the_manual_and_the_troubleshooting_guide(readme: str) -> None:
    assert "HANDLEIDING-WINDOWS.md" in readme
    assert "PROBLEMEN-OPLOSSEN.md" in readme


#: De opdracht noemt deze situaties met zoveel woorden; ze moeten erin staan.
REQUIRED_TROUBLESHOOTING_TOPICS = [
    "Python is niet gevonden",
    "te oud",
    "Node.js is niet gevonden",
    "installeren van de Python-pakketten is mislukt",
    "poort 8000",
    "poort 8770",
    "afgewezen",
    "niet bereikbaar",
    "crasht",
    "draait nu niet op deze pc",
    "browser opent niet",
    ".env",
    "stopt direct",
    "halverwege gestopt",
    "herstart",
]


@pytest.mark.parametrize("topic", REQUIRED_TROUBLESHOOTING_TOPICS)
def test_troubleshooting_covers_every_required_situation(troubleshooting: str, topic: str) -> None:
    assert topic.lower() in troubleshooting.lower(), f"'{topic}' ontbreekt in de foutenzoeker"


def test_troubleshooting_is_laid_out_as_tables(troubleshooting: str) -> None:
    """De opdracht vraagt om Probleem | Oorzaak | Oplossing."""
    assert troubleshooting.count("| Probleem | Mogelijke oorzaak | Oplossing |") >= 5

    rows = [line for line in troubleshooting.splitlines() if line.startswith("| **")]
    assert len(rows) >= 25, f"maar {len(rows)} probleemregels gevonden"

    for row in rows:
        assert row.count(" | ") >= 2, f"deze regel heeft geen drie kolommen: {row[:60]}"


def test_troubleshooting_never_treats_a_network_fault_as_a_key_fault(troubleshooting: str) -> None:
    """Precies de fout die de opdracht verbiedt: onbereikbaar != verkeerde sleutel."""
    lowered = troubleshooting.lower()

    assert "géén sleutelprobleem" in lowered or "geen sleutelprobleem" in lowered
    assert "verander je sleutel **niet**" in lowered


def test_troubleshooting_warns_against_sharing_secrets(troubleshooting: str) -> None:
    lowered = troubleshooting.lower()

    assert "deel nooit je `.env`" in lowered
    assert "nooit een api-sleutel" in lowered


def test_troubleshooting_names_the_error_strings_the_software_really_prints() -> None:
    """Een foutenzoeker met verzonnen foutteksten helpt niemand.

    Elke tekst hieronder moet letterlijk in de broncode staan die hem toont;
    anders zoekt de lezer op iets wat hij nooit op zijn scherm ziet.
    """
    text = TROUBLESHOOTING.read_text(encoding="utf-8")

    bronnen = {
        "De control-service kan poort": PROJECT_ROOT / "control_service" / "run.py",
        "Het dashboard kan poort": PROJECT_ROOT / "dashboard" / "backend" / "run.py",
        "De toegangssleutel werd niet geaccepteerd.": PROJECT_ROOT / "extension" / "api.js",
        "draait nu niet op deze pc": PROJECT_ROOT / "extension" / "api.js",
        "De API-sleutels ontbreken of werden afgewezen": PROJECT_ROOT / "bot" / "supervisor.py",
        "Er draait al een JARVIS-bot (procesvergrendeling)": PROJECT_ROOT / "bot" / "supervisor.py",
        "restart_limit_reached": PROJECT_ROOT / "bot" / "supervisor.py",
        "permanent_error": PROJECT_ROOT / "bot" / "supervisor.py",
        "clean_exit": PROJECT_ROOT / "bot" / "supervisor.py",
    }

    for fragment, source in bronnen.items():
        assert fragment in text, f"de foutenzoeker noemt '{fragment}' niet"
        assert fragment in source.read_text(encoding="utf-8"), (
            f"'{fragment}' staat wel in de foutenzoeker maar niet in {source.name}"
        )


# --------------------------------------------------------------------------
# De release-documenten
# --------------------------------------------------------------------------


def test_the_checklist_covers_the_five_required_sections() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")

    for heading in ("Installatie", "Runtime", "Security", "Extension", "Tests"):
        assert re.search(rf"^## \d+\. {heading}$", text, re.M), f"sectie {heading} ontbreekt"


def test_the_checklist_has_real_checkboxes() -> None:
    text = CHECKLIST.read_text(encoding="utf-8")

    assert text.count("- [ ] ") >= 40, "een checklist met minder dan veertig punten dekt dit niet"
    assert "- [x] " not in text, "een checklist wordt leeg opgeleverd, niet vooraf afgevinkt"


def test_the_checklist_does_not_demand_a_green_suite() -> None:
    """Alles groen eisen zou betekenen dat de safety-gates opengezet worden."""
    text = CHECKLIST.read_text(encoding="utf-8")

    assert "geen volledig groene testsuite" in text
    assert "docs/FAILURES.md" in text


def test_the_checklist_forbids_placing_real_orders() -> None:
    text = CHECKLIST.read_text(encoding="utf-8").lower()

    assert "geen echte orders" in text or "geen enkele controle hieronder mag met" in text


def test_the_release_note_states_version_date_and_limitations() -> None:
    text = RELEASE.read_text(encoding="utf-8")

    for heading in ("Versie", "Wijzigingen", "Testresultaat", "Beperkingen"):
        assert heading in text, f"{heading} ontbreekt in RELEASE-CANDIDATE.md"


def test_the_release_note_is_honest_about_what_could_not_be_tested() -> None:
    """De opdracht verbiedt het presenteren van een statische controle als een echte test."""
    lowered = RELEASE.read_text(encoding="utf-8").lower()

    assert "niet getest" in lowered
    assert "windows" in lowered


def test_the_release_note_does_not_claim_everything_is_green() -> None:
    """Letterlijk verboden formulering zolang de safety-gates rood staan."""
    lowered = RELEASE.read_text(encoding="utf-8").lower()

    assert "alles groen" not in lowered


def test_the_release_note_counts_match_the_failure_register() -> None:
    """Twee documenten die een ander aantal noemen kunnen niet allebei kloppen."""
    register = FAILURES.read_text(encoding="utf-8")
    stated = re.search(r"\*\*(\d[\d.]*) geslaagd, (\d+) gefaald", register)
    release = RELEASE.read_text(encoding="utf-8")

    assert stated.group(1).replace(".", "") in release.replace(".", ""), "het aantal geslaagde tests wijkt af"
    assert stated.group(2) in release, "het aantal gefaalde tests wijkt af"


# --------------------------------------------------------------------------
# Het failure-register moet intern kloppen
# --------------------------------------------------------------------------

FAILURES = PROJECT_ROOT / "docs" / "FAILURES.md"


@pytest.fixture(scope="module")
def failures_register() -> str:
    return FAILURES.read_text(encoding="utf-8")


def _listed_nodeids(text: str) -> list[str]:
    return re.findall(r"^- `([^`]+::[^`]+)`$", text, re.M)


def test_register_exists(failures_register: str) -> None:
    assert len(failures_register) > 2000


def test_register_count_matches_the_number_of_listed_tests(failures_register: str) -> None:
    """Een register dat een ander aantal noemt dan het opsomt, is niet te vertrouwen."""
    stated = int(re.search(r"\*\*\d+ geslaagd, (\d+) gefaald", failures_register).group(1))

    assert len(_listed_nodeids(failures_register)) == stated


def test_register_lists_no_test_twice(failures_register: str) -> None:
    listed = _listed_nodeids(failures_register)

    duplicates = {name for name in listed if listed.count(name) > 1}
    assert duplicates == set(), f"dubbel vermeld: {sorted(duplicates)}"


def test_every_listed_test_file_actually_exists(failures_register: str) -> None:
    """Een register dat naar verdwenen tests verwijst is stille rot."""
    missing = set()
    for nodeid in _listed_nodeids(failures_register):
        path = PROJECT_ROOT / nodeid.split("::")[0]
        if not path.exists():
            missing.add(nodeid.split("::")[0])

    assert missing == set(), f"register noemt verdwenen bestanden: {sorted(missing)}"


def test_group_totals_add_up_to_the_overall_count(failures_register: str) -> None:
    per_group = [int(n) for n in re.findall(r"^\*\*(\d+) tests — oordeel:", failures_register, re.M)]
    stated = int(re.search(r"\*\*\d+ geslaagd, (\d+) gefaald", failures_register).group(1))

    assert sum(per_group) == stated


def test_register_explains_why_the_gates_stay_closed(failures_register: str) -> None:
    lowered = failures_register.lower()

    assert "veiligheidsmaatregel" in lowered
    assert "bewust niet gedaan" in lowered


def test_register_records_what_was_actually_fixed(failures_register: str) -> None:
    assert "Opgelost tijdens deze audit" in failures_register
    assert "/root/apps/Crypto/coinbase_bot" in failures_register
    assert "_EmptyOrderStore" in failures_register
