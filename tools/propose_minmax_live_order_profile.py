#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json
from bot.config import BotConfig

DEFAULT_OUTPUT = Path("reports/live_learning/approved-profile-candidate-min20-max100.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hash_payload(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_minmax_live_order_profile_candidate(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    cfg = BotConfig()
    params = {
        "DEFAULT_QUOTE_SIZE_USDC": "20.00",
        "MAX_NOTIONAL_USD": "100.00",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
        "PHASE_C_MAX_ORDER_QUOTE": "100.00",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "100.00",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "MAX_OPEN_POSITIONS": "3",
        "MAX_SPREAD_PCT": str(cfg.max_spread_pct),
    }
    approved_profile_json = {
        "profile_name": "min20_max100_live_order_profile",
        "profile_version": 1,
        "parameters": params,
    }
    hash_to_approve = _hash_payload(approved_profile_json)
    return {
        "phase": "minmax_live_order_profile_candidate_v1",
        "generated_at": generated_at or _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "approved_parameter_profile_written": False,
        "profile_name": approved_profile_json["profile_name"],
        "profile_version": approved_profile_json["profile_version"],
        "candidate_profile": params,
        "approved_profile_json": approved_profile_json,
        "hash_to_approve": hash_to_approve,
        "safe_to_activate_now": False,
        "activation_requirements": [
            "separate explicit operator ACK with exact hash",
            "write state/approved_parameter_profile.json only in that later ACK-gated run",
            "keep market orders disabled",
            "keep learning-to-execution and neural execution disabled",
            "run readiness after activation before service restart",
        ],
        "rationale": {
            "min_live_order_quote_usdc": "20.00",
            "max_live_order_quote_usdc": "100.00",
            "starter_probe_band": "20.00-35.00",
            "normal_entry_band": "35.00-60.00",
            "strong_entry_band": "60.00-100.00",
            "max_new_orders_per_cycle": "1",
            "max_open_orders": "3",
        },
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    target = path.resolve()
    allowed = (Path.cwd() / "reports/live_learning").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/live_learning")
    atomic_write_json(target, payload)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a report-only min20/max100 approved profile candidate.")
    parser.add_argument("--json-out", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    payload = build_minmax_live_order_profile_candidate(root=args.root)
    _write_json(Path(args.json_out), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_minmax_live_order_profile_candidate", "main", "parse_args"]
