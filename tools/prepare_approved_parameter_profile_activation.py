#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.approved_parameter_profile import APPROVED_PARAMETER_PROFILE_WHITELIST
from bot.atomic_io import atomic_write_json
from tools.autonomous_live_run_common import load_json, now_iso


def _hash_payload(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_activation_plan(*, candidate_path: str | Path, profile: str, write: bool = False, ack: str = "", root: str | Path = ".") -> Dict[str, Any]:
    candidate = load_json(Path(candidate_path))
    profiles = candidate.get("profiles") if isinstance(candidate, dict) else {}
    selected = profiles.get(profile) if isinstance(profiles, dict) else None
    params = (selected or {}).get("candidate_params") if isinstance(selected, dict) else None
    blockers = []
    if not isinstance(params, dict):
        blockers.append("profile_not_found")
        params = {}
    unknown = sorted(set(params) - APPROVED_PARAMETER_PROFILE_WHITELIST)
    if unknown:
        blockers.append("candidate_contains_non_whitelisted_keys:" + ",".join(unknown))
    approved_json = {"profile_name": profile, "profile_version": candidate.get("profile_version", 1), "parameters": params}
    h = _hash_payload(approved_json)
    required_ack = f"APPROVE_BALANCED_PROFILE_{h}"
    ack_valid = ack == required_ack
    if write and not ack_valid:
        blockers.append("exact_ack_required")
    state_path = Path(root) / "state/approved_parameter_profile.json"
    wrote = False
    if write and not blockers:
        atomic_write_json(state_path, approved_json)
        wrote = True
    return {
        "phase": "prepare_approved_parameter_profile_activation_v1",
        "generated_at": now_iso(),
        "candidate": str(candidate_path),
        "profile": profile,
        "valid": not blockers,
        "blockers": blockers,
        "allowed_keys_only": not unknown,
        "hash": h,
        "profile_hash": h,
        "required_ack": required_ack,
        "ack_required": required_ack,
        "ack_valid": ack_valid,
        "would_write_path": str(state_path),
        "approved_profile_json": approved_json,
        "profile_json_preview": approved_json,
        "operator_write_command": (
            "python3 tools/prepare_approved_parameter_profile_activation.py "
            f"--candidate {candidate_path} --profile {profile} --write --ack {required_ack} --json"
        ),
        "env_lines_required_later": [
            "ENABLE_APPROVED_PARAMETER_PROFILE=true",
            f"APPROVED_PARAMETER_PROFILE_HASH={h}",
        ],
        "operator_env_lines": [
            "ENABLE_APPROVED_PARAMETER_PROFILE=true",
            f"APPROVED_PARAMETER_PROFILE_HASH={h}",
        ],
        "rollback_steps": [
            "set ENABLE_APPROVED_PARAMETER_PROFILE=false",
            "remove or archive state/approved_parameter_profile.json only with separate state-change ACK",
            "restart coinbase-bot.service only after explicit operator decision",
            "rerun tools/show_full_autonomous_run_readiness.py --json",
        ],
        "write_requested": write,
        "write_performed": wrote,
        "env_write_performed": False,
        "coinbase_call_attempted": False,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dry-run approved parameter profile activation.")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--ack", default="")
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_activation_plan(candidate_path=args.candidate, profile=args.profile, write=args.write, ack=args.ack, root=args.root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"valid={report['valid']} write_performed={report['write_performed']} hash={report['hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_activation_plan", "main", "parse_args"]
