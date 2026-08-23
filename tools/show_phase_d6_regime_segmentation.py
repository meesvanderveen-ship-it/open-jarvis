#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_regime_segmentation import build_phase_d6_regime_segmentation_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.6 local-candle regime segmentation scaffold. No Coinbase calls and no live signals."
    )
    parser.add_argument("--candles", required=True, help="Explicit local normalized candle JSON path")
    parser.add_argument("--window-size", type=int, default=20)
    parser.add_argument("--step-size", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_regime_segmentation_report(
        candle_path=args.candles,
        window_size=args.window_size,
        step_size=args.step_size,
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
