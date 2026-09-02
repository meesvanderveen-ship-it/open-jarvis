#!/usr/bin/env python3
"""Controleer of deze Python de vastgezette pakketten aankan.

Dit bestand gebruikt bewust *alleen* de standaardbibliotheek en importeert
niets uit `bot/`. Het draait namelijk als allereerste stap van de installatie,
voordat er ook maar één pakket geinstalleerd is; een import van numpy of
pydantic zou hier dus altijd stuklopen.

De ondergrens hieronder is niet gegokt maar afgeleid uit de `Requires-Python`
van de pins in requirements.txt. De strengste zijn numpy 2.4.3 en pandas
3.0.1, en die eisen allebei >=3.11. De aanbevolen versie komt uit
`.python-version`.

Gebruik:
    python tools/check_python.py            # mensvriendelijke uitvoer
    python tools/check_python.py --json     # machineleesbaar
Afsluitcodes: 0 = geschikt, 1 = te oud, 2 = te nieuw om te vertrouwen.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Harde ondergrens: hieronder installeert requirements.txt aantoonbaar niet.
MINIMUM = (3, 11)
# Bovengrens (exclusief): hierboven bestaan er nog geen wheels voor de pins,
# en dan probeert pip vanaf broncode te bouwen -- op Windows vrijwel altijd
# een onbegrijpelijke compilerfout voor een niet-programmeur.
MAXIMUM_EXCLUSIVE = (3, 15)

EXIT_OK = 0
EXIT_TOO_OLD = 1
EXIT_TOO_NEW = 2


def _fmt(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def recommended_version() -> str:
    """De versie uit .python-version, of de ondergrens als dat bestand mist."""
    marker = PROJECT_ROOT / ".python-version"
    try:
        text = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return _fmt(MINIMUM)
    return text or _fmt(MINIMUM)


def evaluate(version_info: tuple[int, ...] | None = None) -> dict:
    """Beoordeel een Python-versie zonder iets te printen of af te sluiten."""
    current = tuple((version_info or sys.version_info)[:3])

    if current[:2] < MINIMUM:
        status, exit_code = "TE_OUD", EXIT_TOO_OLD
        summary = (
            f"Python {_fmt(current)} is te oud. Nodig is {_fmt(MINIMUM)} of nieuwer."
        )
        advice = (
            "Installeer Python van https://www.python.org/downloads/ en zet bij het "
            'installeren een vinkje bij "Add python.exe to PATH".'
        )
    elif current[:2] >= MAXIMUM_EXCLUSIVE:
        status, exit_code = "TE_NIEUW", EXIT_TOO_NEW
        summary = (
            f"Python {_fmt(current)} is nieuwer dan waarop deze bot getest is "
            f"(tot en met {MAXIMUM_EXCLUSIVE[0]}.{MAXIMUM_EXCLUSIVE[1] - 1})."
        )
        advice = (
            "Voor numpy en pandas bestaan voor deze versie mogelijk nog geen kant-en-klare "
            f"pakketten. Installeer Python {recommended_version()} ernaast; de installatie "
            "kiest daarna vanzelf de juiste."
        )
    else:
        status, exit_code = "OK", EXIT_OK
        summary = f"Python {_fmt(current)} is geschikt."
        advice = ""

    return {
        "status": status,
        "exit_code": exit_code,
        "version": _fmt(current),
        "minimum": _fmt(MINIMUM),
        "maximum_exclusive": _fmt(MAXIMUM_EXCLUSIVE),
        "recommended": recommended_version(),
        "executable": sys.executable,
        "implementation": platform.python_implementation(),
        "summary": summary,
        "advice": advice,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    result = evaluate()

    if "--json" in args:
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
        return int(result["exit_code"])

    print(f"Python          : {result['version']}  ({result['implementation']})")
    print(f"Nodig           : {result['minimum']} of nieuwer")
    print(f"Aanbevolen      : {result['recommended']}")
    print(f"Uitvoerbestand  : {result['executable']}")
    print("")
    print(result["summary"])
    if result["advice"]:
        print("")
        print(result["advice"])
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
