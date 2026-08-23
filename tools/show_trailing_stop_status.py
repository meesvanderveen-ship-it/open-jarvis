#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.trailing_stop_manager import build_trailing_stop_status


def _load_json(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show report-only trailing stop status.")
    parser.add_argument("--position-json", default="")
    parser.add_argument("--market-json", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    position = _load_json(args.position_json) if args.position_json else {}
    market = _load_json(args.market_json) if args.market_json else {}
    report = build_trailing_stop_status(position=position, market=market)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print(f"status: {report['status']}")
    print(f"trailing_stop_price: {report['trailing_stop_price']}")
    print("preview_only: true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
