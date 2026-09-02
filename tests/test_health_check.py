"""Tests voor bot/health_check.py.

De health check is de enige plek waar de bot, de installer, de diagnose en de
Chrome Extension hun oordeel vandaan halen. De belangrijkste eis is niet dat
hij groen kan zijn, maar dat hij *nooit groen is terwijl er iets ontbreekt*, en
dat hij een netwerkstoring nooit als configuratiefout presenteert.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot import health_check as hc


# --------------------------------------------------------------------------
# Samenvatten
# --------------------------------------------------------------------------


def _result(status: str, component: str = "Test") -> hc.HealthResult:
    return hc.HealthResult(component, status, "samenvatting")


def test_worst_status_picks_the_most_severe() -> None:
    assert hc.worst_status([_result(hc.READY), _result(hc.WARNING)]) == hc.WARNING
    assert hc.worst_status([_result(hc.WARNING), _result(hc.OFFLINE)]) == hc.OFFLINE
    assert hc.worst_status([_result(hc.OFFLINE), _result(hc.ERROR)]) == hc.ERROR
    assert hc.worst_status([_result(hc.READY), _result(hc.READY)]) == hc.READY


def test_an_error_always_beats_an_offline_check() -> None:
    """Een ontbrekend pakket is erger dan een niet-uitgevoerde controle."""
    assert hc.worst_status([_result(hc.OFFLINE), _result(hc.ERROR), _result(hc.READY)]) == hc.ERROR


def test_empty_list_is_ready() -> None:
    assert hc.worst_status([]) == hc.READY


# --------------------------------------------------------------------------
# Losse controles
# --------------------------------------------------------------------------


def test_python_check_passes_on_the_interpreter_running_these_tests() -> None:
    result = hc.check_python()

    assert result.status == hc.READY
    assert result.facts["version"].startswith("3.")


def test_dependency_check_reports_missing_packages_by_their_install_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hc, "REQUIRED_IMPORTS", {"dit_pakket_bestaat_niet": "niet-bestaand-pakket"})

    result = hc.check_dependencies()

    assert result.status == hc.ERROR
    assert result.facts["missing"] == ["niet-bestaand-pakket"]
    assert "INSTALLEREN-WINDOWS.bat" in result.advice


def test_dependency_check_is_ready_when_everything_is_installed() -> None:
    result = hc.check_dependencies()

    assert result.status == hc.READY, f"ontbreekt: {result.facts.get('missing')}"


def test_an_already_loaded_module_counts_as_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """find_spec gooit een ValueError voor een module zonder __spec__.

    Dat overkomt elke module die door iets anders in sys.modules gezet is. Die
    ValueError mag nooit gelezen worden als 'pakket ontbreekt', want dan meldt
    de systeemcontrole een ontbrekend numpy terwijl numpy geladen is.
    """
    import sys
    import types

    monkeypatch.setitem(sys.modules, "nepmodule_zonder_spec", types.ModuleType("nepmodule_zonder_spec"))
    monkeypatch.setattr(hc, "REQUIRED_IMPORTS", {"nepmodule_zonder_spec": "nepmodule"})

    assert hc.check_dependencies().status == hc.READY


def test_missing_backend_packages_are_a_warning_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zonder dashboard kan de bot nog gewoon handelen."""
    monkeypatch.setattr(hc, "BACKEND_IMPORTS", {"bestaat_niet_xyz": "bestaat-niet-xyz"})

    result = hc.check_backend_dependencies()

    assert result.status == hc.WARNING


def test_missing_env_file_gives_an_instruction_not_a_traceback(tmp_path: Path) -> None:
    result = hc.check_configuration(tmp_path)

    assert result.status == hc.ERROR
    assert ".env" in result.summary
    assert "INSTALLEREN-WINDOWS.bat" in result.advice


def test_invalid_configuration_is_reported_readably(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".env").write_text("BOT_CONFIG_SKIP_DOTENV=true\n", encoding="utf-8")

    import bot.config as bot_config

    class _Broken:
        def validate(self):
            raise ValueError("DEFAULT_QUOTE_SIZE_USDC moet groter zijn dan 0")

    monkeypatch.setattr(bot_config, "BotConfig", _Broken)

    result = hc.check_configuration(tmp_path)

    assert result.status == hc.ERROR
    assert "DEFAULT_QUOTE_SIZE_USDC" in result.detail
    assert "Traceback" not in result.detail


def test_trading_engine_check_loads_without_starting_anything() -> None:
    result = hc.check_trading_engine()

    assert result.status in {hc.READY, hc.ERROR}
    if result.status == hc.ERROR:
        assert result.advice, "een fout moet altijd een volgende stap noemen"


# --------------------------------------------------------------------------
# Credentials: drie uitkomsten
# --------------------------------------------------------------------------


def _fake_checks(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    import bot.credential_status as cs

    check = cs.CredentialCheck(provider="coinbase", status=status, summary="testsamenvatting")
    monkeypatch.setattr(cs, "collect_checks", lambda **_kwargs: [check])


def test_valid_credentials_are_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    import bot.credential_status as cs

    _fake_checks(monkeypatch, cs.STATUS_OK)

    assert hc.check_credentials()[0].status == hc.READY


def test_rejected_credentials_are_an_error_with_a_next_step(monkeypatch: pytest.MonkeyPatch) -> None:
    import bot.credential_status as cs

    _fake_checks(monkeypatch, cs.STATUS_INVALID)
    result = hc.check_credentials()[0]

    assert result.status == hc.ERROR
    assert "connect_services" in result.advice


def test_unreachable_provider_is_offline_and_never_blamed_on_the_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """De harde regel uit de opdracht: onbereikbaar is geen verkeerde sleutel."""
    import bot.credential_status as cs

    _fake_checks(monkeypatch, cs.STATUS_UNKNOWN)
    result = hc.check_credentials()[0]

    assert result.status == hc.OFFLINE
    assert "internetverbinding" in result.advice
    assert "verkeerd" not in result.advice.lower()


def test_a_crashing_credential_check_does_not_crash_the_health_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bot.credential_status as cs

    def explode(**_kwargs):
        raise RuntimeError("iets onverwachts")

    monkeypatch.setattr(cs, "collect_checks", explode)
    results = hc.check_credentials()

    assert len(results) == 1
    assert results[0].status == hc.ERROR


# --------------------------------------------------------------------------
# Diensten en extension
# --------------------------------------------------------------------------


def test_a_stopped_dashboard_is_a_warning_not_an_error() -> None:
    """JARVIS uit hebben staan is geen defect."""
    result = hc.check_local_backend(probe=lambda host, port: False)

    assert result.status == hc.WARNING
    assert "START-JARVIS" in result.advice


def test_a_running_dashboard_is_ready() -> None:
    result = hc.check_local_backend(probe=lambda host, port: True)

    assert result.status == hc.READY


def test_control_service_check_uses_its_own_port() -> None:
    seen: list[int] = []

    hc.check_control_service(probe=lambda host, port: seen.append(port) or False)

    from control_service import config as control_config

    assert seen == [control_config.PORT]


def test_chrome_extension_check_passes_on_the_real_extension() -> None:
    result = hc.check_chrome_extension()

    assert result.status == hc.READY, result.summary
    assert "Load unpacked" in result.detail


def test_missing_extension_directory_is_an_error(tmp_path: Path) -> None:
    result = hc.check_chrome_extension(tmp_path)

    assert result.status == hc.ERROR


def test_manifest_pointing_at_missing_files_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "extension").mkdir()
    (tmp_path / "extension" / "manifest.json").write_text(
        json.dumps({"name": "x", "version": "1", "action": {"default_popup": "weg.html"}}),
        encoding="utf-8",
    )

    result = hc.check_chrome_extension(tmp_path)

    assert result.status == hc.ERROR
    assert "weg.html" in result.detail


def test_corrupt_manifest_is_an_error_not_a_crash(tmp_path: Path) -> None:
    (tmp_path / "extension").mkdir()
    (tmp_path / "extension" / "manifest.json").write_text("{kapot", encoding="utf-8")

    result = hc.check_chrome_extension(tmp_path)

    assert result.status == hc.ERROR
    assert "onleesbaar" in result.summary


def test_missing_dashboard_build_is_a_warning(tmp_path: Path) -> None:
    result = hc.check_dashboard_build(tmp_path)

    assert result.status == hc.WARNING


# --------------------------------------------------------------------------
# Het geheel
# --------------------------------------------------------------------------


def test_full_report_runs_offline_and_has_the_expected_shape() -> None:
    report = hc.run_health_check(online=False)

    assert report["overall"] in {hc.READY, hc.WARNING, hc.ERROR, hc.OFFLINE}
    assert report["verified_online"] is False
    assert len(report["checks"]) >= 8
    for check in report["checks"]:
        assert set(check) == {"component", "status", "summary", "detail", "advice", "facts"}


def test_report_is_json_serialisable() -> None:
    """Het gaat via HTTP naar de browser; niet-serialiseerbare objecten breken dat."""
    json.dumps(hc.run_health_check(online=False))


def test_report_never_claims_ready_while_something_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hc, "check_trading_engine", lambda: _result(hc.ERROR, "Trading engine"))

    report = hc.run_health_check(online=False)

    assert report["overall"] == hc.ERROR
    assert report["ready"] is False
    assert "Trading engine" in report["blocking"]


def test_formatted_report_is_readable_for_a_non_programmer() -> None:
    text = hc.format_report(hc.run_health_check(online=False))

    assert "systeemcontrole" in text
    assert "RESULTAAT:" in text
    assert "Traceback" not in text


def test_exit_codes_separate_offline_from_error() -> None:
    """diagnose.bat moet 'geen internet' anders kunnen behandelen dan 'kapot'."""
    assert hc.EXIT_CODES[hc.READY] == 0
    assert hc.EXIT_CODES[hc.WARNING] == 0
    assert hc.EXIT_CODES[hc.OFFLINE] == 2
    assert hc.EXIT_CODES[hc.ERROR] == 1


def test_main_json_output_parses(capsys: pytest.CaptureFixture[str]) -> None:
    hc.main(["--json"])

    payload = json.loads(capsys.readouterr().out)
    assert "checks" in payload


# --------------------------------------------------------------------------
# Een omvallende deelcontrole mag nooit een traceback opleveren
# --------------------------------------------------------------------------


def test_a_crashing_sub_check_becomes_an_error_row_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """De systeemcontrole is het enige venster van een niet-programmeur.

    Viel een deelcontrole om -- bijvoorbeeld door een ontbrekende submodule --
    dan brak `python -m bot.health_check` af met een ImportError, zonder een
    enkele regel over wat er wel goed stond. Dat is precies de obscure
    traceback die deze laag hoort weg te nemen.
    """

    def explodeert():
        raise ImportError("geen module control_service")

    monkeypatch.setattr(hc, "check_control_service", explodeert)

    report = hc.run_health_check(online=False)

    rij = next(c for c in report["checks"] if c["component"] == "Control-service")
    assert rij["status"] == hc.ERROR
    assert "ImportError" in rij["detail"]
    assert rij["advice"], "een fout moet altijd een volgende stap noemen"


def test_the_other_checks_still_run_when_one_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eén kapotte controle mag de negen andere niet onzichtbaar maken."""

    def explodeert():
        raise RuntimeError("iets onverwachts")

    monkeypatch.setattr(hc, "check_trading_engine", explodeert)

    report = hc.run_health_check(online=False)

    assert len(report["checks"]) >= 10
    assert any(c["component"] == "Python" and c["status"] == hc.READY for c in report["checks"])


def test_a_failing_check_still_blocks_the_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Afschermen mag geen wegmoffelen worden: de fout telt gewoon mee."""

    def explodeert():
        raise RuntimeError("stuk")

    monkeypatch.setattr(hc, "check_dependencies", explodeert)

    report = hc.run_health_check(online=False)

    assert report["overall"] == hc.ERROR
    assert report["ready"] is False
    assert "Dependencies" in report["blocking"]


def test_main_prints_a_readable_line_instead_of_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Laatste vangnet, voor het geval er toch iets doorheen komt."""

    def explodeert(**_kwargs):
        raise RuntimeError("onverwacht")

    monkeypatch.setattr(hc, "run_health_check", explodeert)

    code = hc.main([])

    uitvoer = capsys.readouterr()
    assert code == hc.EXIT_CODES[hc.ERROR]
    assert "Traceback" not in uitvoer.err
    assert "DIAGNOSE-JARVIS.bat" in uitvoer.err
