#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.autonomous_parameter_governor import build_activation_plan, write_activation_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare report-only autonomous parameter activation plan.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    plan = build_activation_plan(root=root)
    plan["outputs"] = write_activation_plan(plan, root=root)
    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))
    else:
        print(f"activation_plan_available={plan['activation_plan_available']} reason={plan['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
