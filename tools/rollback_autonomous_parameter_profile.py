#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.autonomous_parameter_governor import rollback_governor_profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rollback autonomous parameter profile. Dry-run by default.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = rollback_governor_profile(root=Path(args.root), apply=args.apply)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"rollback_available={result['rollback_available']} applied={result['applied']} reason={result['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
