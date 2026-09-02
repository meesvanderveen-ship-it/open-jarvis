"""De installeerbare bot moet ook op Windows kunnen draaien.

Deze tests draaien op elk platform. Ze kunnen Windows-gedrag hier niet echt
uitvoeren, maar ze leggen wel vast dat er geen POSIX-only aanroep op het pad
staat die op Windows meteen een ImportError of AttributeError geeft -- precies
het soort fout dat een gebruiker zonder programmeerervaring niet kan duiden.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Modules die op Windows niet bestaan. Ze mogen alleen binnen een functie
# worden geimporteerd, achter een os.name-controle.
POSIX_ONLY_MODULES = {"fcntl", "pwd", "grp", "termios"}


def _module_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:  # alleen top-level, niet binnen functies
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _startup_modules() -> list[Path]:
    """De modules die de bot en de setup-flow bij het opstarten aanraken."""
    return [
        PROJECT_ROOT / "run_trader_loop.py",
        PROJECT_ROOT / "coinbase_auth.py",
        PROJECT_ROOT / "bot" / "atomic_io.py",
        PROJECT_ROOT / "bot" / "config.py",
        PROJECT_ROOT / "bot" / "credential_status.py",
        PROJECT_ROOT / "bot" / "env_file.py",
        PROJECT_ROOT / "bot" / "health_check.py",
        PROJECT_ROOT / "bot" / "resilience.py",
        PROJECT_ROOT / "bot" / "supervisor.py",
        PROJECT_ROOT / "control_service" / "app.py",
        PROJECT_ROOT / "control_service" / "auth.py",
        PROJECT_ROOT / "control_service" / "process_manager.py",
        PROJECT_ROOT / "control_service" / "run.py",
        PROJECT_ROOT / "tools" / "check_python.py",
        PROJECT_ROOT / "tools" / "jarvis_control.py",
        PROJECT_ROOT / "tools" / "setup_wizard.py",
    ]


@pytest.mark.parametrize("path", _startup_modules(), ids=lambda p: p.name)
def test_startup_modules_have_no_posix_only_toplevel_imports(path: Path):
    offending = _module_level_imports(path) & POSIX_ONLY_MODULES
    assert not offending, (
        f"{path.name} importeert {sorted(offending)} op moduleniveau; "
        "dat breekt de import op Windows"
    )


def test_process_lock_helpers_handle_both_platforms():
    """De lockhelpers moeten beide platformtakken bevatten."""
    source = (PROJECT_ROOT / "bot" / "atomic_io.py").read_text(encoding="utf-8")

    assert "msvcrt" in source, "geen Windows-tak in de bestandsvergrendeling"
    assert "fcntl" in source, "POSIX-tak mag niet verdwenen zijn"
    assert 'os.name == "nt"' in source


def test_process_lock_still_works_on_this_platform(tmp_path):
    """Regressiecheck: de herschreven lock doet nog steeds wat hij moet."""
    from bot.atomic_io import process_lock

    lock_file = tmp_path / "runtime.lock"

    with process_lock(lock_file) as info:
        assert info["acquired"] is True
        assert info["pid"] == os.getpid()

        with pytest.raises(RuntimeError, match="process_lock_already_active"):
            with process_lock(lock_file):
                pass

    # Na afloop is de lock weer vrij.
    with process_lock(lock_file) as info:
        assert info["acquired"] is True


def test_env_file_write_does_not_require_fchmod(tmp_path, monkeypatch):
    """Op Windows bestaat os.fchmod niet; het schrijven moet dan blijven werken."""
    from bot import env_file

    monkeypatch.delattr(os, "fchmod", raising=False)

    target = tmp_path / ".env"
    env_file.write_env_values({"OPENAI_API_KEY": "sk-test-placeholder-value"}, target)

    assert env_file.read_env(target)["OPENAI_API_KEY"] == "sk-test-placeholder-value"


def test_dashboard_resolves_a_windows_venv_interpreter(tmp_path, monkeypatch):
    """De dashboardbackend moet .venv\\Scripts\\python.exe ook vinden."""
    from dashboard.backend import config

    scripts = tmp_path / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("", encoding="utf-8")

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    resolved = config._resolve_bot_python()

    assert resolved.endswith("python.exe")


def test_dashboard_falls_back_to_a_plain_interpreter_name(tmp_path, monkeypatch):
    from dashboard.backend import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    resolved = config._resolve_bot_python()

    assert resolved in {"python", "python3"}


# --------------------------------------------------------------------------
# Batchbestanden
# --------------------------------------------------------------------------

#: Wat de gebruiker dubbelklikt. De Engelse namen bestaan omdat ze de
#: gangbare namen zijn; ze sturen door naar de Nederlandse implementatie.
BAT_FORWARDERS = {
    "install.bat": "INSTALLEREN-WINDOWS.bat",
    "start.bat": "START-JARVIS.bat",
    "stop.bat": "STOP-JARVIS.bat",
    "restart.bat": "HERSTART-JARVIS.bat",
    "diagnose.bat": "DIAGNOSE-JARVIS.bat",
}


def _bat_files() -> list[Path]:
    return sorted(PROJECT_ROOT.glob("*.bat"))


@pytest.mark.parametrize("path", _bat_files(), ids=lambda p: p.name)
def test_every_batch_file_keeps_crlf_line_endings(path: Path):
    """Met kale LF vindt cmd.exe zijn eigen labels niet meer terug.

    cmd leest een label inclusief de achterblijvende \\r en zoekt dan naar
    een label dat niet bestaat; goto en call springen dan het niets in. Dit
    is precies waarvoor `*.bat -text` in .gitattributes staat.
    """
    raw = path.read_bytes()
    lone_lf = raw.replace(b"\r\n", b"").count(b"\n")

    assert lone_lf == 0, f"{path.name} bevat {lone_lf} regel(s) zonder CR"


@pytest.mark.parametrize("name", sorted(BAT_FORWARDERS), ids=lambda n: n)
def test_expected_control_scripts_exist(name: str):
    assert (PROJECT_ROOT / name).exists(), f"{name} ontbreekt"
    assert (PROJECT_ROOT / BAT_FORWARDERS[name]).exists(), f"{BAT_FORWARDERS[name]} ontbreekt"


@pytest.mark.parametrize("name", sorted(BAT_FORWARDERS), ids=lambda n: n)
def test_forwarders_point_at_a_file_that_exists(name: str):
    """Een `call` naar een niet-bestaand bestand sluit het venster zonder uitleg."""
    text = (PROJECT_ROOT / name).read_text(encoding="utf-8")
    target = BAT_FORWARDERS[name]

    assert target in text, f"{name} verwijst niet naar {target}"


def test_no_two_batch_files_differ_only_in_capitalisation():
    """Windows kent geen hoofdletterverschil in bestandsnamen.

    Twee bestanden die alleen in casing verschillen zijn daar hetzelfde
    bestand: een forwarder zou zichzelf aanroepen en oneindig doorlussen.
    """
    lowered = [path.name.lower() for path in _bat_files()]

    duplicates = {name for name in lowered if lowered.count(name) > 1}
    assert duplicates == set(), f"botsende namen op Windows: {sorted(duplicates)}"


def test_a_forwarder_never_calls_itself():
    for name, target in BAT_FORWARDERS.items():
        assert name.lower() != target.lower(), f"{name} zou zichzelf aanroepen"


@pytest.mark.parametrize("path", _bat_files(), ids=lambda p: p.name)
def test_batch_files_keep_the_window_open_on_failure(path: Path):
    """Een venster dat bij een fout dichtklapt laat de gebruiker met niets achter."""
    text = (PROJECT_ROOT / path.name).read_text(encoding="utf-8")
    if path.name in BAT_FORWARDERS:
        # Een forwarder toont zelf niets; het doelbestand doet de pauze.
        return

    assert "pause" in text, f"{path.name} pauzeert nergens"


@pytest.mark.parametrize("path", _bat_files(), ids=lambda p: p.name)
def test_batch_files_contain_no_hardcoded_user_paths(path: Path):
    """Geen C:\\Users\\<iemand> of /root/... : dat werkt alleen op één pc."""
    text = path.read_text(encoding="utf-8")

    assert "C:\\Users\\" not in text
    assert "/root/" not in text


@pytest.mark.parametrize("path", _bat_files(), ids=lambda p: p.name)
def test_batch_files_work_from_any_directory(path: Path):
    """Dubbelklikken zet de werkmap niet altijd op de projectmap."""
    text = path.read_text(encoding="utf-8")

    assert 'cd /d "%~dp0"' in text, f"{path.name} zet de werkmap niet op de eigen map"


def test_batch_files_contain_no_secrets():
    for path in _bat_files():
        text = path.read_text(encoding="utf-8")
        assert "sk-" not in text
        assert "BEGIN EC PRIVATE KEY" not in text


# --------------------------------------------------------------------------
# Nieuwe modules: paden en processen
# --------------------------------------------------------------------------


def test_supervisor_uses_terminate_instead_of_a_posix_signal():
    """SIGTERM bestaat niet op Windows; terminate() wel, op beide platformen."""
    source = (PROJECT_ROOT / "bot" / "supervisor.py").read_text(encoding="utf-8")

    assert "self._process.terminate()" in source
    assert "os.kill(" not in source


def test_supervisor_stops_through_a_flag_file_not_a_signal():
    """Op Windows bereikt taskkill zonder /F een Python-console-app niet."""
    source = (PROJECT_ROOT / "bot" / "supervisor.py").read_text(encoding="utf-8")

    assert "STOP_FLAG_PATH" in source


def test_process_manager_has_a_windows_branch_for_liveness():
    source = (PROJECT_ROOT / "control_service" / "process_manager.py").read_text(encoding="utf-8")

    assert 'os.name == "nt"' in source
    assert "OpenProcess" in source


def test_new_modules_derive_paths_from_the_file_location():
    """Geen aannames over de werkmap: dubbelklikken start elders."""
    for relative in (
        "bot/health_check.py",
        "bot/supervisor.py",
        "control_service/config.py",
        "tools/check_python.py",
    ):
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "Path(__file__).resolve().parents[" in source, relative


def test_status_and_token_files_live_under_state():
    """Zo vallen ze onder /state/ in .gitignore en komen ze nooit in git."""
    from bot import supervisor
    from control_service import config as control_config

    assert supervisor.STATUS_PATH.parent.name == "state"
    assert supervisor.STOP_FLAG_PATH.parent.name == "state"
    assert control_config.TOKEN_PATH.parent.name == "state"


def test_gitignore_covers_the_control_token():
    """Het token mag onder geen beding in een repository terechtkomen."""
    patterns = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "/state/" in patterns
    assert "*token*" in patterns


def test_gitattributes_pins_batch_files_to_crlf():
    attributes = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "*.bat -text" in attributes


def test_utf8_output_is_declared_in_every_batch_file():
    """Zonder chcp 65001 worden accenten in cmd.exe onleesbare tekens."""
    for path in _bat_files():
        if path.name in BAT_FORWARDERS:
            continue
        assert "chcp 65001" in path.read_text(encoding="utf-8"), path.name


# --------------------------------------------------------------------------
# Geen Unix-only commandoregelprogramma's in Python-tools
# --------------------------------------------------------------------------

def test_state_hashing_no_longer_shells_out_to_sha256sum():
    """sha256sum bestaat niet op Windows; hashlib doet hetzelfde overal.

    Bovendien gaf sha256sum een foutcode zodra een statusbestand nog niet
    bestond -- normaal op een verse installatie, voordat er ooit een order
    geweest is. Dat leverde een kale traceback op in plaats van een rapport.
    """
    for name in (
        "build_phase_d6_governance_evidence_bundle.py",
        "build_phase_d6_live_test_readiness_report.py",
    ):
        source = (PROJECT_ROOT / "tools" / name).read_text(encoding="utf-8")
        assert '"sha256sum"' not in source, f"{name} roept sha256sum nog aan"
        assert "hashlib.sha256" in source, f"{name} hasht niet met hashlib"


def test_state_hashing_reports_a_missing_file_instead_of_crashing(tmp_path, monkeypatch):
    """Op een verse installatie bestaat state/positions.json nog niet."""
    import importlib

    module = importlib.import_module("tools.build_phase_d6_live_test_readiness_report")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)

    hashes = module._state_hashes()

    assert set(hashes) == set(module._HASHED_STATE_FILES)
    assert all(value == "file_absent" for value in hashes.values())


def test_state_hashing_matches_hashlib_for_a_real_file(tmp_path, monkeypatch):
    import hashlib
    import importlib

    module = importlib.import_module("tools.build_phase_d6_live_test_readiness_report")
    (tmp_path / "state").mkdir()
    payload = b'{"orders": []}'
    (tmp_path / "state" / "open_orders.json").write_bytes(payload)
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)

    hashes = module._state_hashes()

    assert hashes["state/open_orders.json"] == hashlib.sha256(payload).hexdigest()


# --------------------------------------------------------------------------
# Verwijzingen vanuit de batchbestanden naar Python
# --------------------------------------------------------------------------


def _modules_referenced_by_batch_files() -> set[str]:
    """Alle `python -m <module>` aanroepen uit de .bat-bestanden."""
    pattern = re.compile(r"-m\s+([a-z_]+(?:\.[a-z_]+)+)")
    found: set[str] = set()
    for path in _bat_files():
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return found


def test_batch_files_reference_at_least_the_known_modules():
    """Vangt een lege of stukgelopen zoekactie af, zodat de test hieronder telt."""
    modules = _modules_referenced_by_batch_files()

    assert {"bot.health_check", "control_service.run", "tools.jarvis_control"} <= modules


@pytest.mark.parametrize("module", sorted(_modules_referenced_by_batch_files()), ids=lambda m: m)
def test_every_module_a_batch_file_calls_can_be_imported(module: str):
    """Een typefout in een .bat zou pas op de pc van de gebruiker opvallen.

    Daar levert het een ModuleNotFoundError op in een zwart venster -- precies
    de foutmelding die een niet-programmeur niets zegt.
    """
    import importlib

    importlib.import_module(module)


@pytest.mark.parametrize("module", sorted(_modules_referenced_by_batch_files()), ids=lambda m: m)
def test_every_module_a_batch_file_calls_is_runnable_as_a_script(module: str):
    """`python -m x` werkt alleen als de module een __main__-ingang heeft."""
    import importlib

    imported = importlib.import_module(module)
    source = Path(imported.__file__).read_text(encoding="utf-8")

    assert '__name__ == "__main__"' in source, f"{module} is niet met -m te starten"


def _scripts_referenced_by_batch_files() -> set[str]:
    """Losse scriptaanroepen zoals `python tools\\check_python.py`."""
    pattern = re.compile(r'"%VENV_PY%"\s+([a-zA-Z0-9_\\/.-]+\.py)')
    found: set[str] = set()
    for path in _bat_files():
        found.update(pattern.findall(path.read_text(encoding="utf-8")))
    return found


@pytest.mark.parametrize("script", sorted(_scripts_referenced_by_batch_files()), ids=lambda s: s)
def test_every_script_a_batch_file_calls_exists(script: str):
    target = PROJECT_ROOT / script.replace("\\", "/")

    assert target.exists(), f"een .bat roept {script} aan, dat niet bestaat"


def test_batch_files_only_call_test_files_that_exist():
    """DIAGNOSE en de installer draaien een vaste lijst tests als zelftest."""
    pattern = re.compile(r"(tests\\[a-z0-9_]+\.py|control_service\\tests)")
    for path in _bat_files():
        for reference in pattern.findall(path.read_text(encoding="utf-8")):
            target = PROJECT_ROOT / reference.replace("\\", "/")
            assert target.exists(), f"{path.name} verwijst naar {reference}, dat niet bestaat"


# --------------------------------------------------------------------------
# Overschrijfbare zoekpaden voor de optionele replica-installatie
# --------------------------------------------------------------------------


def test_follower_paths_default_to_the_known_server_locations():
    """De twee Linux-serverpaden blijven de standaard.

    Ze stonden eerst hard in de code. Nu zijn het defaults van een
    overschrijfbare zoeklijst: bestaande deployments merken niets, en op een
    Windows-pc kan iemand aanwijzen waar de replica wél staat.
    """
    from bot import phase_follower_receiver_api_audit as module

    assert module._default_follower_paths() == (
        "/opt/coinbase-replica",
        "/root/apps/Crypto/coinbase-replica",
    )


def test_follower_paths_can_be_overridden(monkeypatch):
    """Gescheiden met os.pathsep: ';' op Windows, ':' op POSIX."""
    from bot import phase_follower_receiver_api_audit as module

    first, second = ("C:\\JARVIS\\replica", "D:\\reserve") if os.name == "nt" else ("/srv/replica", "/mnt/reserve")
    monkeypatch.setenv("FOLLOWER_RECEIVER_PATHS", f"{first}{os.pathsep}{second}")

    assert module._default_follower_paths() == (first, second)


def test_the_override_actually_reaches_the_code_that_searches(tmp_path, monkeypatch):
    """De instelling moet doorwerken in de functie die de paden echt gebruikt.

    Eerder las die functie de constante DEFAULT_FOLLOWER_PATHS, die op het
    importmoment wordt vastgezet. Een FOLLOWER_RECEIVER_PATHS uit .env werkte
    daardoor alleen als hij toevallig al in de omgeving stond voordat de module
    geimporteerd werd -- de instelling stond wel gedocumenteerd maar deed niets.
    Deze test gaat bewust langs de productiefunctie en niet langs de helper.
    """
    from bot import phase_follower_receiver_api_audit as module

    doel = tmp_path / "elders" / "replica"
    doel.mkdir(parents=True)
    monkeypatch.setenv("FOLLOWER_RECEIVER_PATHS", str(doel))

    gevonden = module._candidate_paths(tmp_path / "project", None)

    assert doel in gevonden, "de ingestelde map wordt niet doorzocht"
    assert Path("/opt/coinbase-replica") not in gevonden, "de standaard wordt niet vervangen"


def test_without_an_override_the_known_server_paths_are_searched(tmp_path, monkeypatch):
    """Bestaande Linux-deployments mogen niets merken van de instelbaarheid."""
    from bot import phase_follower_receiver_api_audit as module

    monkeypatch.delenv("FOLLOWER_RECEIVER_PATHS", raising=False)

    gevonden = module._candidate_paths(tmp_path / "project", None)

    for standaard in module.FALLBACK_FOLLOWER_PATHS:
        assert Path(standaard) in gevonden


def test_follower_paths_survive_an_empty_or_padded_value(monkeypatch):
    from bot import phase_follower_receiver_api_audit as module

    monkeypatch.setenv("FOLLOWER_RECEIVER_PATHS", "   ")
    assert module._default_follower_paths()[0] == "/opt/coinbase-replica"

    monkeypatch.setenv("FOLLOWER_RECEIVER_PATHS", f"/een{os.pathsep}{os.pathsep}/twee")
    assert module._default_follower_paths() == ("/een", "/twee"), "lege stukken worden overgeslagen"


def test_missing_replica_directories_are_not_an_error():
    """Op een Windows-pc bestaat geen van beide paden; dat mag niets breken."""
    from bot import phase_follower_receiver_api_audit as module

    for path in module._default_follower_paths():
        assert isinstance(path, str) and path


# --------------------------------------------------------------------------
# cmd.exe-valkuilen in de batchbestanden
# --------------------------------------------------------------------------


def _blocks_and_lines(path: Path):
    """Loop de regels langs met de haakjesdiepte erbij.

    Commentaarregels tellen niet mee voor de inhoud, maar hun haakjes wel
    niet: `REM ... ^(EN^)` zou de diepte anders scheeftrekken.
    """
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    depth = 0
    for number, raw in enumerate(text.split("\n"), 1):
        stripped = raw.strip()
        is_comment = stripped.upper().startswith("REM") or stripped.startswith("::")
        yield number, stripped, depth, is_comment
        if not is_comment:
            depth = max(0, depth + stripped.count("(") - stripped.count(")"))


@pytest.mark.parametrize("path", _bat_files(), ids=lambda p: p.name)
def test_no_percent_errorlevel_inside_a_parenthesised_block(path: Path):
    """`set "VAR=%errorlevel%"` binnen een blok leest de verkeerde waarde.

    cmd.exe parseert een heel haakjesblok in een keer en vult daarbij alle
    %VAR% in. `%errorlevel%` wordt dus vervangen door de waarde van *voordat*
    het blok begon, niet door die van het commando ervoor.

    Dit was een echte bug in START-JARVIS.bat: na een geslaagde
    sleutelkoppeling kreeg de gebruiker alsnog "Nog steeds niet startklaar"
    en stopte het script. Binnen een blok hoort `!errorlevel!` te staan.
    """
    fouten = [
        (number, line)
        for number, line, depth, is_comment in _blocks_and_lines(path)
        if depth > 0 and not is_comment and re.search(r'set "?\w+=%errorlevel%', line, re.I)
    ]

    assert fouten == [], f"{path.name}: gebruik !errorlevel! binnen een blok, niet %errorlevel% -> {fouten}"


@pytest.mark.parametrize("path", _bat_files(), ids=lambda p: p.name)
def test_every_goto_and_call_target_exists(path: Path):
    """Een sprong naar een onbekend label laat cmd.exe stilletjes afbreken."""
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    labels = {match.lower() for match in re.findall(r"^:(\w[\w-]*)", text, re.M)}

    onbekend = {
        target
        for target in re.findall(r"\b(?:goto|call)\s+:(\w[\w-]*)", text, re.I)
        if target.lower() not in labels and target.lower() != "eof"
    }

    assert onbekend == set(), f"{path.name} springt naar niet-bestaande labels: {sorted(onbekend)}"


@pytest.mark.parametrize("path", _bat_files(), ids=lambda p: p.name)
def test_no_bare_exit_that_closes_the_users_window(path: Path):
    """Een kale `exit` sluit het hele venster, ook als het script gecalld is.

    Dan is de foutmelding die er net in stond weg voordat iemand hem kon lezen.
    """
    kaal = [
        number
        for number, line, _depth, is_comment in _blocks_and_lines(path)
        if not is_comment and re.fullmatch(r"exit", line, re.I)
    ]

    assert kaal == [], f"{path.name}: gebruik 'exit /b' op regel(s) {kaal}"


def test_delayed_expansion_is_enabled_where_it_is_used():
    """`!VAR!` werkt alleen na `setlocal enabledelayedexpansion`."""
    for path in _bat_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"![A-Za-z_]\w*!", text):
            assert "enabledelayedexpansion" in text.lower(), (
                f"{path.name} gebruikt !VAR! zonder delayed expansion aan te zetten"
            )


# --------------------------------------------------------------------------
# Foutafhandeling in de nieuw toegevoegde modules
# --------------------------------------------------------------------------

NIEUWE_MODULES = [
    "bot/health_check.py",
    "bot/resilience.py",
    "bot/supervisor.py",
    "control_service/app.py",
    "control_service/auth.py",
    "control_service/process_manager.py",
    "control_service/run.py",
    "tools/build_failure_register.py",
    "tools/check_python.py",
    "tools/jarvis_control.py",
]


@pytest.mark.parametrize("relative", NIEUWE_MODULES, ids=lambda r: Path(r).name)
def test_no_broad_exception_is_silently_swallowed(relative: str):
    """`except Exception: pass` verbergt fouten in plaats van ze af te handelen.

    Een smalle except die precies één fouttype opvangt is iets anders: daar
    betekent de fout meestal dat het doel al bereikt is -- een proces dat al
    gestopt is, een bestand dat al weg is. Die mogen wel stil zijn.
    """
    tree = ast.parse((PROJECT_ROOT / relative).read_text(encoding="utf-8"))

    fout = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        alleen_pass = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
        if not alleen_pass:
            continue
        breed = node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
        )
        if breed:
            fout.append(node.lineno)

    assert fout == [], f"{relative}: brede except met alleen 'pass' op regel(s) {fout}"


@pytest.mark.parametrize("relative", NIEUWE_MODULES, ids=lambda r: Path(r).name)
def test_a_broad_except_always_reports_something(relative: str):
    """Een brede except mag, maar dan moet de fout wel ergens terechtkomen.

    Ofwel doorgegooid, ofwel gelogd, ofwel omgezet in een leesbare melding.
    Stilzwijgend doorgaan met een onbekende fout is wat deze regel verbiedt.
    """
    bron = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(bron)

    stil = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        breed = node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"}
        )
        if not breed:
            continue
        lichaam = "\n".join(ast.unparse(stmt) for stmt in node.body)
        meldt = any(
            teken in lichaam
            for teken in ("raise", "LOGGER", "logging", "log.", "print", "return", "HealthResult", "ActionResult")
        )
        if not meldt:
            stil.append(node.lineno)

    assert stil == [], f"{relative}: brede except zonder melding op regel(s) {stil}"
