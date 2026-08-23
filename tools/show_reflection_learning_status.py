#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.reflection_learning_context import STATE_PATH, load_reflection_learning_context


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show read-only reflection learning context status.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ctx = load_reflection_learning_context(Path(args.root) / STATE_PATH)
    if args.json:
        print(json.dumps(ctx, indent=2, sort_keys=True))
    else:
        summary = ctx.get("summary") if isinstance(ctx.get("summary"), dict) else {}
        print(f"reflection_learning available={ctx.get('available')} stale={ctx.get('stale')} bias={summary.get('overall_bias')} evidence={summary.get('evidence_strength')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
