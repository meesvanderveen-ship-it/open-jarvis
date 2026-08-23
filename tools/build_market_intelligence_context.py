#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.atomic_io import atomic_write_json
from bot.market_intelligence_context import build_market_intelligence_context


def parse_sources(value: str) -> List[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only market intelligence context.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-out", default="")
    parser.add_argument("--ttl-minutes", type=int, default=60)
    parser.add_argument("--sources", default="defillama,coinmetrics,santiment")
    parser.add_argument("--no-network", action="store_true", help="Use built-in fixtures; no external API calls.")
    parser.add_argument("--no-cache", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context = build_market_intelligence_context(
        root=Path(args.root),
        ttl_minutes=args.ttl_minutes,
        sources=parse_sources(args.sources),
        no_network=args.no_network,
        use_cache=not args.no_cache,
    )
    if args.json_out:
        atomic_write_json(Path(args.json_out), context)
    if args.json:
        print(json.dumps(context, indent=2, sort_keys=True))
    else:
        print(f"market_intelligence_context available={context.get('available')} stale={context.get('stale')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
