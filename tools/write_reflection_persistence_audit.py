#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.reflection_persistence import write_reflection_persistence_audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write read-only reflection persistence audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = write_reflection_persistence_audit(root=Path(args.root))
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True))
    else:
        status = audit.get("status") or {}
        print(f"reflection_persistence_audit events={status.get('total_events')} validated={status.get('validated_conclusions')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
