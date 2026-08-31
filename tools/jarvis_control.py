#!/usr/bin/env python3
"""Bedien JARVIS vanaf de opdrachtregel: start, stop, herstart, status.

Dezelfde laag die de Chrome Extension via HTTP gebruikt, maar dan direct. De
.bat-bestanden roepen dit aan, zodat de logica op één plek staat en getest
wordt in plaats van in batchscript verspreid te raken.

    python -m tools.jarvis_control status
    python -m tools.jarvis_control start
    python -m tools.jarvis_control stop
    python -m tools.jarvis_control restart

Afsluitcodes: 0 = gelukt, 1 = mislukt, 2 = onderbroken door de gebruiker.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from control_service.process_manager import ProcessManager

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_INTERRUPTED = 2

_STATE_LABELS = {
    "running": "JARVIS draait.",
    "starting": "JARVIS is aan het opstarten.",
    "cooldown": "JARVIS herstelt van een storing en probeert het zo opnieuw.",
    "stopped": "JARVIS draait niet.",
    "failed": "JARVIS is gestopt door een fout.",
    "unknown": "De toestand van JARVIS is onbekend.",
}


def _print_status(manager: ProcessManager) -> int:
    status = manager.status()
    supervisor = status.get("supervisor", {})

    print("=" * 60)
    print("  JARVIS - status")
    print("=" * 60)
    print("")
    print(f"  Toestand : {_STATE_LABELS.get(status['state'], status['state'])}")
    if status["running"]:
        print(f"  Proces   : bewaker draait (nummer {status['supervisor_pid']})")
    else:
        print("  Proces   : er draait niets")

    message = supervisor.get("message")
    if message:
        print("")
        print(f"  {message}")
    advice = supervisor.get("advice")
    if advice:
        print(f"  -> {advice}")
    log_file = supervisor.get("log_file")
    if log_file:
        print(f"  Logbestand: {log_file}")
    print("")
    return EXIT_OK if status["running"] else EXIT_FAILED


def _report(result) -> int:
    print("")
    print(result.message)
    if result.detail:
        print(f"  {result.detail}")
    print("")
    return EXIT_OK if result.ok else EXIT_FAILED


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bedien de JARVIS trading bot.")
    parser.add_argument("actie", choices=["start", "stop", "restart", "status"])
    parser.add_argument("--json", action="store_true", help="machineleesbare uitvoer")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    manager = ProcessManager()

    try:
        if args.actie == "status":
            if args.json:
                print(json.dumps(manager.status(), indent=2, sort_keys=True, ensure_ascii=True))
                return EXIT_OK
            return _print_status(manager)

        if args.actie == "start":
            print("JARVIS starten...")
            result = manager.start()
        elif args.actie == "stop":
            print("JARVIS stoppen... dit kan even duren als er een handelscyclus loopt.")
            result = manager.stop()
        else:
            print("JARVIS herstarten...")
            result = manager.restart()
    except KeyboardInterrupt:
        print("\nAfgebroken. Er is niets gewijzigd aan een lopend proces.")
        return EXIT_INTERRUPTED

    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True, ensure_ascii=True))
        return EXIT_OK if result.ok else EXIT_FAILED
    return _report(result)


if __name__ == "__main__":
    raise SystemExit(main())
