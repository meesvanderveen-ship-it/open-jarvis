#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.reflection_learning_context import MISSED_JSON_PATH, build_reflection_learning_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize read-only missed opportunity reflection labels.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fixture-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = Path(args.root) / MISSED_JSON_PATH
    if path.exists() and not args.fixture_only:
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        report = build_reflection_learning_report(root=Path(args.root), fixture_only=args.fixture_only, no_network=True)
        items = [ev for ev in report.get("evaluations", []) if ev.get("label") in {"missed_opportunity", "too_strict_wait"}]
        payload = {"generated_at": report.get("generated_at"), "count": len(items), "items": items}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"missed_opportunities count={payload.get('count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
