#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.adaptive_policy_lab import build_adaptive_policy_candidate, write_adaptive_policy_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only adaptive policy candidate from reflection learning output.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    candidate = build_adaptive_policy_candidate(root=root)
    outputs = write_adaptive_policy_outputs(candidate, root=root)
    candidate["outputs"] = outputs
    if args.json:
        print(json.dumps(candidate, indent=2, sort_keys=True))
    else:
        print(f"adaptive_policy candidate_available={candidate.get('candidate_available')} recommendation={candidate.get('recommendation')} hash={candidate.get('hash')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
