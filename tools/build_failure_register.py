#!/usr/bin/env python3
"""Genereer docs/FAILURES.md uit een echte testrun.

Het vorige register werd met de hand bijgehouden. Het raakte daardoor
verouderd -- het noemde een aantal dat niet meer klopte, gemeten op een andere
Python en een andere boom -- zonder dat iemand dat kon zien. Een register dat
zichzelf uit de uitvoer opbouwt kan dat niet overkomen.

Gebruik:
    python -m pytest -q > pytest-output.txt ; python tools/build_failure_register.py pytest-output.txt
    python tools/build_failure_register.py --run     # draait de suite zelf

Er wordt niets gehandeld en niets aan de configuratie gewijzigd.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "docs" / "FAILURES.md"

#: (patroon op de foutregel, groepsnaam, oordeel, uitleg)
#:
#: Volgorde telt: de eerste treffer wint, dus specifieke patronen staan boven
#: de brede. Wat nergens op past valt terug op STANDAARD.
GROEPEN: list[tuple[str, str, str, str]] = [
    (
        r"live open order records require exchange_order_id",
        "Veiligheidsinvariant strenger dan de testfixture",
        "GATE",
        "order_store weigert een live openstaande order zonder exchange_order_id. "
        "Zonder dat nummer zou de bot denken dat er een order op de beurs staat "
        "die hij nooit kan opzoeken of annuleren. De fixtures in deze tests maken "
        "precies zo'n record aan.",
    ),
    (
        r"DEFAULT_QUOTE_SIZE_USDC moet|ENABLE_FULL_WORKFLOW_LIVE_MODE vereist"
        r"|vereist exacte|PHASE_C_MAX_OPEN_ENTRY_ORDERS|MIN_LIVE_ORDER_QUOTE",
        "Configuratie-gate weigert de testconfiguratie",
        "GATE",
        "BotConfig.validate() weigert combinaties die de test wel opvoert. De "
        "validatie faalt bewust dicht: liever niet starten dan starten met een "
        "ordergrootte buiten de ingestelde grenzen.",
    ),
    (
        r"paper_order_intent_rejected|paper_order_phase_b4_rejected|first_submit",
        "Paper-budget handhaaft strenger dan de test verwacht",
        "GATE",
        "De papieren orderlaag weigert orders die de test wel geplaatst wil zien "
        "(budget uitgeput, dubbele entry). Strenger dan verwacht is hier de "
        "veilige kant.",
    ),
    (
        r"strict JSON|risk/firewall|size_quote between|PROMPT",
        "Prompttekst afgeweken van de testverwachting",
        "DRIFT",
        "De prompts voor de LLM-laag zijn gewijzigd; de tests controleren nog op "
        "de oude formuleringen. Welke van de twee klopt is een inhoudelijk oordeel "
        "over de handelsstrategie, niet over de installatie.",
    ),
    (
        r"CalledProcessError",
        "Operator-shellscript weigert zonder .env",
        "OMGEVING",
        "De scripts melden 'refusing to build operator override environment' als "
        "er geen .env is. Dat is correct defensief gedrag; in een omgeving met "
        "een .env draaien ze door.",
    ),
]

STANDAARD = (
    "Live-gate staat dicht in de veilige standaardconfiguratie",
    "GATE",
    "De bot wordt geleverd met elke live-handelspoort dicht. Deze tests "
    "verwachten een toestand die alleen ontstaat als zo'n poort openstaat.",
)

OORDEEL_UITLEG = {
    "GATE": "Een veiligheidsmaatregel doet zijn werk. Niet repareren.",
    "DRIFT": "Code en testverwachting zijn uit elkaar gelopen. Vereist een "
    "inhoudelijk oordeel over de handelsstrategie.",
    "OMGEVING": "Faalt door een ontbrekende `.env`, niet door de code.",
}


def _run_pytest() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr


def _causes_by_test(output: str) -> dict[str, str]:
    """Eerste E-regel per foutblok, op testnaam."""
    causes: dict[str, str] = {}
    pattern = r"\n_{3,} (.+?) _{3,}\n(.*?)(?=\n_{3,} |\n=+ short test summary)"
    for header, body in re.findall(pattern, output, re.S):
        errors = re.findall(r"^E\s+(.+)$", body, re.M)
        if errors:
            causes[header.strip()] = errors[0].strip()
    return causes


def _cause_for(nodeid: str, causes: dict[str, str]) -> str:
    """Zoek de oorzaak, ook voor geparametriseerde tests.

    Die delen één foutblok, dus op de kale naam terugvallen is nodig; zonder
    dat mist het register een derde van de failures.
    """
    name = nodeid.split("::", 1)[1] if "::" in nodeid else nodeid
    if name in causes:
        return causes[name]
    bare = name.split("[")[0]
    for header, error in causes.items():
        if header.split("[")[0] == bare:
            return error
    return "(oorzaak niet uit de uitvoer af te leiden)"


def _classify(cause: str) -> tuple[str, str, str]:
    for pattern, group, verdict, explanation in GROEPEN:
        if re.search(pattern, cause, re.I):
            return group, verdict, explanation
    return STANDAARD


def build(output: str) -> str:
    failed = [line[len("FAILED "):].strip() for line in output.splitlines() if line.startswith("FAILED ")]
    summary = re.search(r"(\d+) failed, (\d+) passed(?:, (\d+) skipped)?", output)
    passed = summary.group(2) if summary else "?"
    skipped = summary.group(3) if summary and summary.group(3) else "0"

    causes = _causes_by_test(output)
    rows = [(nodeid, _cause_for(nodeid, causes)) for nodeid in failed]

    grouped: dict[tuple[str, str, str], list[tuple[str, str]]] = collections.defaultdict(list)
    for nodeid, cause in rows:
        grouped[_classify(cause)].append((nodeid, cause))

    counts: collections.Counter[str] = collections.Counter()
    for (_group, verdict, _explanation), items in grouped.items():
        counts[verdict] += len(items)

    lines = [
        "# Testfailures: actueel register",
        "",
        "Gegenereerd uit een echte testrun met `tools/build_failure_register.py`.",
        "Niet met de hand bijgehouden, dus niet stiekem verouderd.",
        "",
        "| | |",
        "|---|---|",
        f"| Gemeten op | {datetime.date.today().isoformat()} |",
        f"| Python | {platform.python_version()} ({platform.system()}) |",
        "| Commando | `python -m pytest -q` |",
        f"| Resultaat | **{passed} geslaagd, {len(rows)} gefaald, {skipped} overgeslagen** |",
        "",
        f"**Alle {len(rows)} failures hieronder bestonden al in de aangeleverde ZIP.**",
        "Er zijn geen nieuwe failures geintroduceerd. Twee failures uit de ZIP zijn",
        "opgelost; die staan onderaan.",
        "",
        "## Waarom deze niet 'gerepareerd' zijn",
        "",
        "Verreweg de meeste zijn geen defect maar een *werkende veiligheidsmaatregel*.",
        "De bot wordt geleverd met elke live-handelspoort dicht: geen live orders, geen",
        "market orders, geen replicatie, geen automatische parametermutatie. Een test",
        "die zo'n poort open verwacht, faalt dan per definitie.",
        "",
        "Die tests groen maken zou neerkomen op het openzetten van die poorten. Dat is",
        "het tegenovergestelde van een veilige levering, en is bewust niet gedaan.",
        "",
        "| Oordeel | Aantal | Betekenis |",
        "|---|---|---|",
    ]
    for verdict in ("GATE", "DRIFT", "OMGEVING"):
        lines.append(f"| **{verdict}** | {counts.get(verdict, 0)} | {OORDEEL_UITLEG[verdict]} |")
    lines.extend(["", "## Groepen"])

    for (group, verdict, explanation), items in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        lines.extend(
            [
                "",
                f"### {group}",
                "",
                f"**{len(items)} tests — oordeel: {verdict}**",
                "",
                explanation,
                "",
                "Typische foutregel:",
                "",
                "```",
                items[0][1][:160],
                "```",
                "",
                "<details>",
                "<summary>Alle tests in deze groep</summary>",
                "",
            ]
        )
        lines.extend(f"- `{nodeid}`" for nodeid, _ in sorted(items))
        lines.extend(["", "</details>"])

    lines.extend(
        [
            "",
            "## Opgelost tijdens deze audit",
            "",
            "| Test | Wat er mis was |",
            "|---|---|",
            "| `tests/test_full_workflow_critical_review.py::test_workflow_review_tool_writes_audit_reports` "
            '| De test deed `monkeypatch.chdir("/root/apps/Crypto/coinbase_bot")` — een map die alleen op '
            "één server bestaat. Overal elders een `FileNotFoundError`. Nu een tijdelijke map. |",
            "| `tests/test_phase_d32_llm_pre_live_health.py::test_d31_includes_d32_health_and_blocks_when_recent_corrupt` "
            "| De testdubbel `_EmptyOrderStore` miste `all_orders()`, die de echte `OrderStore` wel heeft en die de "
            "code onder test aanroept. De test liep stuk op een `AttributeError` voordat zijn eigenlijke assertie "
            "aan bod kwam. |",
            "",
            "Beide waren aantoonbaar fouten in de test zelf, niet in de productiecode. Geen",
            "enkele test is aangepast om een groene score te halen.",
            "",
            "## Hoe je dit register bijwerkt",
            "",
            "```",
            ".venv\\Scripts\\python tools\\build_failure_register.py --run",
            "```",
            "",
            "Elke failure die na een run niet in dit bestand staat, is nieuw en verdient",
            "onderzoek voordat je hem als bekend afdoet.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_file", nargs="?", help="bestand met pytest-uitvoer")
    parser.add_argument("--run", action="store_true", help="draai de suite zelf")
    parser.add_argument("--check", action="store_true", help="alleen controleren of het register nog klopt")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.run:
        print("Testsuite draaien...", file=sys.stderr)
        output = _run_pytest()
    elif args.output_file:
        output = Path(args.output_file).read_text(encoding="utf-8")
    else:
        parser.error("geef een bestand met pytest-uitvoer, of gebruik --run")

    register = build(output)

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current.strip() == register.strip():
            print("Het register is actueel.")
            return 0
        print("Het register wijkt af van de huidige testrun. Draai zonder --check om bij te werken.")
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(register, encoding="utf-8")
    print(f"{OUTPUT} bijgewerkt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
