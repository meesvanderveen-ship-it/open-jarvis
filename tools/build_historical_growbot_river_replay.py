#!/usr/bin/env python3
"""Build historical_replay episodes and report combined GrowBot/River coverage.

Reads only the genuinely orphaned, signal-bearing slice of historical logs
(see bot/growbot_historical_replay.py), appends them to a ledger separate
from the forward one, and reports forward/historical/combined coverage plus
sandboxed (non-production) River diagnostics. Never mutates
reports/growbot_river/history/episodes.jsonl, the production River model
state, or any BotConfig/profile.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.growbot_historical_replay import (
    append_historical_episodes,
    build_coverage_report,
    build_historical_episodes,
    write_coverage_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build GrowBot/River historical replay episodes (report-only).")
    parser.add_argument("--root", default=".")
    parser.add_argument("--max-per-source", type=int, default=1500)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    built = build_historical_episodes(root, max_per_source=max(1, args.max_per_source))
    memory = append_historical_episodes(built["episodes"], root=root)
    coverage = build_coverage_report(root)
    outputs = write_coverage_report(coverage, root=root)

    report = {
        "phase": "growbot_historical_replay_v1",
        "by_source": built["by_source"],
        "memory": memory,
        "coverage_report_path": outputs["json"],
    }
    if args.json:
        print(json.dumps({**report, "coverage": coverage}, indent=2, sort_keys=True))
    else:
        print(
            "growbot_historical_replay "
            f"built={len(built['episodes'])} added={memory['added']} "
            f"existing_or_duplicate={memory['existing_or_duplicate']} "
            f"total_after={memory['total_after']} -> {outputs['json']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
