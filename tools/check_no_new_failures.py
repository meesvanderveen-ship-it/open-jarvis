#!/usr/bin/env python3
"""Bewaak de invariant die er echt toe doet: geen nieuwe testfailures.

Deze suite heeft honderd failures die er horen te zijn. Verreweg de meeste zijn
veiligheidsmaatregelen die hun werk doen: de bot wordt geleverd met elke
live-handelspoort dicht, en tests die zo'n poort open verwachten falen dan per
definitie. Ze groen maken zou betekenen dat die poorten opengezet worden.

Een kale `pytest` in CI zou daardoor permanent rood staan, en een rood dat
altijd rood is bewaakt niets. Dit script vergelijkt in plaats daarvan de
*verzameling* falende tests met het vastgelegde register in docs/FAILURES.md:

* een test die faalt en niet in het register staat  -> nieuwe regressie, CI rood
* een test die slaagt en wel in het register staat  -> opgelost, register bijwerken

Gebruik:
    python tools/check_no_new_failures.py            # draait de suite zelf
    python tools/check_no_new_failures.py uitvoer.txt

Er wordt niets gehandeld en geen enkele instelling gewijzigd.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTER = PROJECT_ROOT / "docs" / "FAILURES.md"

EXIT_OK = 0
EXIT_NIEUWE_FAILURES = 1
EXIT_REGISTER_VEROUDERD = 2
EXIT_ONBRUIKBAAR = 3


def _run_pytest() -> str:
    resultaat = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    return resultaat.stdout + resultaat.stderr


def failures_uit_uitvoer(uitvoer: str) -> set[str]:
    return {
        regel[len("FAILED "):].strip().split(" - ")[0]
        for regel in uitvoer.splitlines()
        if regel.startswith("FAILED ")
    }


def failures_uit_register(tekst: str) -> set[str]:
    return set(re.findall(r"^- `([^`]+::[^`]+)`$", tekst, re.M))


def _samenvatting(uitvoer: str) -> str:
    for regel in reversed(uitvoer.splitlines()):
        if re.search(r"\d+ (passed|failed)", regel):
            return regel.strip()
    return "(geen samenvatting gevonden)"


#: De kopregel waarmee pytest elk faalverslag begint: ``___ test_naam ___``.
_KOP = re.compile(r"^_{3,} (.+?) _{3,}$")


def detailsecties(uitvoer: str) -> dict[str, str]:
    """Knip de faalverslagen uit de pytest-uitvoer, op testnaam.

    De sleutel is wat pytest in zijn kopregel zet. Dat is niet het volledige
    node-id maar alleen de testnaam (bij een klasse: ``Klasse.naam``), dus er
    wordt hieronder op het staartstuk van het node-id gezocht.
    """
    secties: dict[str, str] = {}
    naam: Optional[str] = None
    regels: list[str] = []

    for regel in uitvoer.splitlines():
        kop = _KOP.match(regel)
        if kop:
            if naam is not None:
                secties[naam] = "\n".join(regels).rstrip()
            naam, regels = kop.group(1).strip(), []
            continue
        if naam is None:
            continue
        # Een nieuwe blokkop (=== ... ===) sluit het laatste verslag af.
        if regel.startswith("=") and regel.endswith("="):
            secties[naam] = "\n".join(regels).rstrip()
            naam, regels = None, []
            continue
        regels.append(regel)

    if naam is not None:
        secties[naam] = "\n".join(regels).rstrip()
    return secties


def _detail_voor(nodeid: str, secties: dict[str, str], maxregels: int = 40) -> str:
    """Het faalverslag bij een node-id, ingekort tot de laatste regels.

    Ingekort en niet volledig: bij een lange assertie is het slot -- de
    assertie zelf en de waarden -- wat je nodig hebt, en een CI-log dat
    dichtslibt leest niemand meer.
    """
    staart = nodeid.split("::", 1)[1].replace("::", ".")
    tekst = secties.get(staart)
    if tekst is None:
        return "    (geen faalverslag in deze uitvoer gevonden)"

    regels = tekst.splitlines()
    weggelaten = len(regels) - maxregels
    if weggelaten > 0:
        regels = [f"    [{weggelaten} regels hierboven weggelaten]", *regels[-maxregels:]]
    return "\n".join(f"    {regel}" for regel in regels)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("uitvoer_bestand", nargs="?", help="bestand met pytest-uitvoer")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.uitvoer_bestand:
        uitvoer = Path(args.uitvoer_bestand).read_text(encoding="utf-8", errors="replace")
    else:
        print("Testsuite draaien...", file=sys.stderr)
        uitvoer = _run_pytest()

    if not REGISTER.exists():
        print(f"Het register {REGISTER} ontbreekt; er valt niets te vergelijken.", file=sys.stderr)
        return EXIT_ONBRUIKBAAR

    gemeten = failures_uit_uitvoer(uitvoer)
    bekend = failures_uit_register(REGISTER.read_text(encoding="utf-8"))

    if not bekend:
        print("Het register bevat geen enkele test; waarschijnlijk is het stuk.", file=sys.stderr)
        return EXIT_ONBRUIKBAAR

    nieuw = sorted(gemeten - bekend)
    opgelost = sorted(bekend - gemeten)

    print(_samenvatting(uitvoer))
    print(f"  bekende failures in het register : {len(bekend)}")
    print(f"  gemeten failures in deze run     : {len(gemeten)}")

    if nieuw:
        secties = detailsecties(uitvoer)
        print("")
        print(f"NIEUWE FAILURES ({len(nieuw)}) -- deze stonden niet in het register:")
        for naam in nieuw:
            print(f"  {naam}")
        # Ook het faalverslag erbij: een CI-run die alleen de namen noemt
        # dwingt je het artefact te downloaden voordat je iets kunt zoeken, en
        # juist een failure die alleen op de bouwmachine optreedt is lokaal
        # niet na te spelen.
        for naam in nieuw:
            print("")
            print(f"--- {naam}")
            print(_detail_voor(naam, secties))
        print("")
        print("Dit is een regressie. Zoek de oorzaak op; werk niet eerst het register bij.")
        return EXIT_NIEUWE_FAILURES

    if opgelost:
        print("")
        print(f"OPGELOSTE FAILURES ({len(opgelost)}) -- deze staan nog wel in het register:")
        for naam in opgelost:
            print(f"  {naam}")
        print("")
        print("Goed nieuws, maar het register loopt achter. Werk het bij met:")
        print("  python tools/build_failure_register.py --run")
        return EXIT_REGISTER_VEROUDERD

    print("")
    print("Geen nieuwe regressies. De resterende failures zijn de verklaarde")
    print("pre-existente safety-gates, omgevings- en driftgevallen uit docs/FAILURES.md.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
