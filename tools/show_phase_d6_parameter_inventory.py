#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_parameter_inventory import (  # noqa: E402
    CATEGORY_LABELS,
    build_phase_d6_parameter_inventory_report,
)


def _split_csv(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for item in str(raw or "").split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.6 research-only parameter candidate inventory. Stdout-only; no Coinbase calls, no state writes."
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help=(
            "Optional category filter. May be comma-separated or repeated. "
            f"Allowed: {', '.join(sorted(CATEGORY_LABELS))}"
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON. JSON is the default stdout format.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_parameter_inventory_report(categories=_split_csv(args.category))
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
