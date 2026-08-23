"""De installeerbare bot moet ook op Windows kunnen draaien.

Deze tests draaien op elk platform. Ze kunnen Windows-gedrag hier niet echt
uitvoeren, maar ze leggen wel vast dat er geen POSIX-only aanroep op het pad
staat die op Windows meteen een ImportError of AttributeError geeft -- precies
het soort fout dat een gebruiker zonder programmeerervaring niet kan duiden.
"""

from __future__ import annotations

import ast
import os
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
