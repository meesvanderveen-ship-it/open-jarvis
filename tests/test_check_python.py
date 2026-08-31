"""Tests voor tools/check_python.py.

Dit is de eerste stap van de installatie en draait voordat er ook maar één
pakket geinstalleerd is. Twee eisen staan hier centraal: hij mag alleen de
standaardbibliotheek gebruiken, en hij mag een werkende Python nooit
afwijzen -- iemand wegsturen om iets te installeren dat hij al heeft, is de
onvriendelijkste fout die een installer kan maken.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import check_python

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "tools" / "check_python.py"


# --------------------------------------------------------------------------
# Oordeel per versie
# --------------------------------------------------------------------------


@pytest.mark.parametrize("version", [(3, 11, 0), (3, 12, 3), (3, 13, 1), (3, 14, 0)])
def test_supported_versions_are_accepted(version: tuple[int, int, int]) -> None:
    result = check_python.evaluate(version)

    assert result["status"] == "OK"
    assert result["exit_code"] == check_python.EXIT_OK
    assert result["advice"] == ""


@pytest.mark.parametrize("version", [(3, 8, 10), (3, 9, 7), (3, 10, 12)])
def test_too_old_versions_are_rejected_with_an_instruction(version: tuple[int, int, int]) -> None:
    result = check_python.evaluate(version)

    assert result["status"] == "TE_OUD"
    assert result["exit_code"] == check_python.EXIT_TOO_OLD
    assert "python.org" in result["advice"]
    assert "Add python.exe to PATH" in result["advice"]


def test_python_311_is_not_rejected() -> None:
    """De installer eiste 3.12 op grond van een onjuiste aanname.

    numpy 2.4.3 en pandas 3.0.1 publiceren allebei `Requires-Python >=3.11`
    en leveren cp311-wheels. Een gebruiker met een werkende 3.11 werd dus
    weggestuurd om iets te installeren dat hij al had.
    """
    assert check_python.evaluate((3, 11, 9))["status"] == "OK"


def test_a_much_newer_version_is_a_warning_not_a_hard_stop() -> None:
    """Te nieuw kán werken; dan hoort er geen deur dichtgegooid te worden."""
    result = check_python.evaluate((3, 15, 0))

    assert result["status"] == "TE_NIEUW"
    assert result["exit_code"] == check_python.EXIT_TOO_NEW
    assert result["advice"]


def test_the_minimum_matches_what_the_pins_actually_require() -> None:
    """Borgt dat de ondergrens niet losraakt van requirements.txt."""
    assert check_python.MINIMUM == (3, 11)
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "numpy==2.4.3" in requirements
    assert "pandas==3.0.1" in requirements


def test_recommended_version_comes_from_the_python_version_file() -> None:
    marker = (PROJECT_ROOT / ".python-version").read_text(encoding="utf-8").strip()

    assert check_python.recommended_version() == marker


# --------------------------------------------------------------------------
# Uitvoerbaar zonder dependencies
# --------------------------------------------------------------------------


def test_script_imports_only_the_standard_library() -> None:
    """Draait vóór pip install; een externe import zou hier altijd falen."""
    third_party = {"numpy", "pandas", "pydantic", "requests", "fastapi", "dotenv", "openai", "anthropic"}
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported & third_party == set(), f"externe imports gevonden: {imported & third_party}"


def test_script_does_not_import_from_the_bot_package() -> None:
    """bot/ trekt zware pakketten mee; die zijn hier nog niet geinstalleerd."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert "from bot" not in source
    assert "import bot" not in source


def test_script_runs_as_a_standalone_file() -> None:
    """Zo roept INSTALLEREN-WINDOWS.bat hem aan: `python tools\\check_python.py`."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=str(PROJECT_ROOT)
    )

    assert result.returncode == check_python.EXIT_OK, result.stderr
    assert "Python" in result.stdout


def test_json_output_is_machine_readable() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"], capture_output=True, text=True, cwd=str(PROJECT_ROOT)
    )

    payload = json.loads(result.stdout)
    assert payload["status"] == "OK"
    assert set(payload) >= {"status", "version", "minimum", "recommended", "summary", "advice"}


def test_output_contains_no_traceback_for_any_verdict() -> None:
    for version in [(3, 8, 0), (3, 12, 0), (3, 20, 0)]:
        result = check_python.evaluate(version)
        assert "Traceback" not in result["summary"]
        assert "Traceback" not in result["advice"]
