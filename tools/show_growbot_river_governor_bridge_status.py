#!/usr/bin/env python3
"""Show the read-only GrowBot/River -> autonomous-governor bridge status.

Aggregates already-computed reports (growbot-river-learning,
adaptive-policy candidate, growbot-river readiness, live-cycle readiness)
with the existing governor's own `validate_governor` output. Writes no
state and defines no new activation route.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.growbot_river_governor_bridge import (
    build_growbot_river_governor_bridge_status,
    write_growbot_river_governor_bridge_status,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show the report-only GrowBot/River -> governor bridge status.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    status = build_growbot_river_governor_bridge_status(root=root)
    status["outputs"] = write_growbot_river_governor_bridge_status(status, root=root)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        top = status.get("top_parameter_candidate") or {}
        fast_start = status.get("fast_start_candidate_eligibility") or {}
        print(
            "growbot_river_governor_bridge "
            f"bridge_ready={status['bridge_ready']} candidate_ready={status['candidate_ready']} "
            f"strict_stabilization_ready={status.get('strict_stabilization_ready')} "
            f"fast_start_autotune_ready={status.get('fast_start_autotune_ready')} "
            f"auto_apply_eligible={status['auto_apply_eligible']} "
            f"top_parameter={top.get('parameter') or 'none'} "
            f"fast_start_eligible={fast_start.get('eligible')} "
            f"fast_start_blocking_reasons={','.join(fast_start.get('blocking_reasons') or []) or 'none'} "
            f"next_required_condition={status['next_required_condition']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
