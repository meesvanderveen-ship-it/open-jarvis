#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.market_intelligence_context import STATE_PATH, context_with_status, load_market_intelligence_context, render_context_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show read-only market intelligence context status.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context = load_market_intelligence_context(Path(args.root) / STATE_PATH)
    if args.json:
        print(json.dumps(context_with_status(context), indent=2, sort_keys=True))
    else:
        print(render_context_status(context))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
