#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.reflection_persistence import build_reflection_persistence_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show read-only reflection persistence status.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    status = build_reflection_persistence_status(root=Path(args.root))
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(
            "reflection_persistence "
            f"ledger={status['reflection_ledger_available']} "
            f"events={status['total_events']} "
            f"validated={status['validated_conclusions']} "
            f"corrupt={status['corrupt_lines']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
