#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.opportunity_memory import DEFAULT_PATH, evaluate_opportunities, load_opportunity_memory


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show report-only opportunity memory status.")
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    data = load_opportunity_memory(args.path)
    report = evaluate_opportunities(market_by_ticker={}, path=args.path, persist=False)
    report["opportunities"] = data.get("opportunities", [])
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print(f"path: {args.path}")
    print(f"count: {report['count']}")
    print("preview_only: true")
    for item in report["opportunities"][:25]:
        print(f"- {item.get('ticker')} {item.get('setup_type')} {item.get('status')} trigger={item.get('trigger_level')} invalidation={item.get('invalidation_level')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
