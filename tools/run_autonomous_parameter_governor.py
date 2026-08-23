#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.autonomous_parameter_governor import run_governor, run_governor_cycle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run autonomous parameter governor. Use --dry-run for diagnostic no-op mode.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-report-refresh", action="store_true")
    parser.add_argument("--cycle", action="store_true", help="Run full reflection/adaptive/governor cycle with lock.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    dry_run = bool(args.dry_run)
    if args.cycle or not args.skip_report_refresh:
        result = run_governor_cycle(root=root, apply=not dry_run, dry_run=dry_run, run_reports=not args.skip_report_refresh)
    else:
        result = run_governor(root=root, apply=not dry_run)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"applied={result['applied']} reason={result['reason']} dry_run={result['dry_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
