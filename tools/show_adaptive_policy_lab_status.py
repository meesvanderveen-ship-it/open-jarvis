#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.adaptive_policy_lab import build_policy_lab_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show read-only adaptive policy lab status.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_policy_lab_report(root=Path(args.root))
    status = {
        "available": report.get("available"),
        "candidate_available": report.get("candidate_available"),
        "recommendation": report.get("recommendation"),
        "reason": report.get("reason"),
        "total_validated_conclusions": (report.get("evidence_summary") or {}).get("total_validated_conclusions", 0),
        "market_regime_coverage_pct": report.get("market_regime_coverage_pct", 0),
        "market_regimes": (report.get("evidence_summary") or {}).get("market_regimes", []),
        "effect_size_gate_summary": report.get("effect_size_gate_summary") or {},
        "confidence_gate_summary": report.get("confidence_gate_summary") or {},
        "direction_stability_summary": report.get("direction_stability_summary") or {},
        "shrinkage_enabled": bool(report.get("shrinkage_enabled")),
        "sample_thresholds": report.get("sample_thresholds"),
        "thresholds_met": report.get("thresholds_met"),
        "blockers": report.get("blockers"),
        "evidence_by_setup_type": report.get("evidence_by_setup_type"),
        "evidence_by_blocker": report.get("evidence_by_blocker"),
        "overfit_risk": report.get("overfit_risk"),
        "source_policy": report.get("source_policy"),
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
    }
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(f"adaptive_policy available={status['available']} candidate_available={status['candidate_available']} recommendation={status['recommendation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
