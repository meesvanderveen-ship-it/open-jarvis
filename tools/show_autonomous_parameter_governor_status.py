#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.atomic_io import atomic_write_json
from bot.autonomous_parameter_governor import STATUS_PATH, validate_governor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show read-only autonomous parameter governor status.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    status = validate_governor(root=root)
    atomic_write_json(root / STATUS_PATH, status)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        layers = status.get("readiness_layers") if isinstance(status.get("readiness_layers"), dict) else {}
        print(
            "governor "
            f"enabled={status['enabled']} mode={status['mode']} allowed={status['governor_activation_allowed']} "
            f"candidate_available={status.get('candidate_available')} reason={status['reason']} "
            f"blocking_gate={status.get('candidate_generation_blocker')} "
            f"raw_regime_count={layers.get('raw_regime_count')} "
            f"distinct_regime_count={layers.get('distinct_regime_count')} "
            f"qualifying_regime_count={layers.get('qualifying_regime_count')} "
            f"regime_key_design={layers.get('regime_key_design')} "
            f"candidate_hash={status.get('candidate_hash') or 'none'} "
            f"blocked_candidate_report_hash={status.get('blocked_candidate_report_hash') or 'none'} "
            f"report_hash={status.get('report_hash') or 'none'} "
            f"candidate_generation_ready={status.get('candidate_generation_ready')} "
            f"candidate_proposal_present={status.get('candidate_proposal_present')} "
            f"proposed_parameter={status.get('proposed_parameter') or 'none'} "
            f"proposed_old_value={status.get('proposed_old_value') or 'none'} "
            f"proposed_new_value={status.get('proposed_new_value') or 'none'} "
            f"step_pct={status.get('proposed_step_pct')} "
            f"operator_ack_missing={status.get('operator_ack_missing')} "
            f"next_operator_action={status.get('next_operator_action')} "
            f"internal_inconsistency_detected={status.get('internal_inconsistency_detected')} "
            f"analysis_blockers={','.join(layers.get('analysis_blockers') or []) or 'none'} "
            f"prepare_blockers={','.join(layers.get('prepare_blockers') or []) or 'none'} "
            f"apply_blockers={','.join(layers.get('apply_blockers') or []) or 'none'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
