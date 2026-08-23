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

DEFAULT_BACKTEST = Path("reports/backtests/btc-eth-parameter-backtest-latest.json")
DEFAULT_OUT = Path("reports/backtests/approved-profile-candidate-from-backtest.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _assert_backtest_path(path: Path) -> Path:
    target = path.resolve()
    allowed = (Path.cwd() / "reports/backtests").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/backtests")
    return target


def build_backtest_parameter_candidate(backtest: Dict[str, Any], *, generated_at: Optional[str] = None) -> Dict[str, Any]:
    candidate = backtest.get("candidate") if isinstance(backtest.get("candidate"), dict) else {}
    band = candidate.get("recommended_parameter_band") if isinstance(candidate.get("recommended_parameter_band"), dict) else {}
    sample_size = int(candidate.get("sample_size") or 0)
    label_counts = backtest.get("label_counts") if isinstance(backtest.get("label_counts"), dict) else {}
    results = backtest.get("results") if isinstance(backtest.get("results"), list) else []
    candidate_is_static = True
    params = {
        "DEFAULT_QUOTE_SIZE_USDC": "20.00",
        "MAX_NOTIONAL_USD": "100.00",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
        "PHASE_C_MAX_ORDER_QUOTE": "100.00",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "100.00",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "MAX_OPEN_POSITIONS": "3",
        "MAX_SPREAD_PCT": "0.0060",
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0100",
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "2.5",
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.50",
        "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
    }
    approved_profile_json = {
        "profile_name": "research_prior_backtest_available_candidate",
        "profile_version": 1,
        "parameters": params,
    }
    return {
        "phase": "approved_profile_candidate_from_backtest_v1",
        "generated_at": generated_at or _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "approved_parameter_profile_written": False,
        "safe_to_live_activate_now": False,
        "requires_operator_review": True,
        "requires_exact_hash_ack": True,
        "candidate_is_static_research_prior": candidate_is_static,
        "candidate_not_metric_optimized": True,
        "candidate_classification": "research_prior_backtest_available_candidate",
        "metric_dependency": {
            "sample_size_used_for_confidence": True,
            "recommended_parameter_band_from_backtest_report": bool(band),
            "label_counts_used_for_parameters": False,
            "per_timeframe_results_used_for_parameters": False,
            "candidate_profile_values_change_with_label_counts": False,
        },
        "label_counts_seen": label_counts,
        "per_timeframe_result_count": len(results),
        "warnings": [
            "candidate_not_metric_optimized",
            "candidate_profile_values_are_static_research_prior_defaults",
            "do_not_activate_full_profile_until_adaptive_candidate_logic_or_operator_accepts_sizing_only",
        ],
        "confidence": candidate.get("confidence") or ("low" if sample_size < 500 else "medium"),
        "overfit_risk": candidate.get("overfit_risk") or ("high" if sample_size < 500 else "medium"),
        "sample_size": sample_size,
        "market_regime_dependency": candidate.get("market_regime_dependency") or "unknown",
        "recommended_parameter_band": band,
        "supports_20_100_sizing": True,
        "research_prior_parameters": [
            "EMA_20_50_200",
            "Donchian_20_55",
            "ADX_20_25",
            "Bollinger_20_2",
            "RSI_14",
            "ATR_14",
            "initial_objective_score_bands",
        ],
        "backtest_supported_parameters": [
            "MAX_LIVE_ORDER_QUOTE_USDC",
            "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
            "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
            "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
            "MAX_SPREAD_PCT",
            "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
            "ATR_STOP_MULTIPLIER",
            "TAKE_PROFIT_R_MULTIPLE",
            "OBJECTIVE_SCORE_STARTER_MIN",
            "OBJECTIVE_SCORE_NORMAL_MIN",
        ],
        "live_learning_only_parameters": [
            "limit_order_fill_probability",
            "orderbook_timing",
            "no_fill_timeout_minutes",
            "cancel_replace_min_age_minutes",
            "bounded_exploration_label_balance",
        ],
        "candidate_profile": params,
        "approved_profile_json": approved_profile_json,
        "hash_to_approve": _hash(approved_profile_json),
        "activation_requirements": [
            "human review of backtest sample size and missing data",
            "separate exact-hash ACK",
            "write state/approved_parameter_profile.json only in later ACK-gated run",
            "run readiness after activation before any service lifecycle action",
        ],
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize report-only backtest parameter candidate.")
    parser.add_argument("--backtest", default=str(DEFAULT_BACKTEST))
    parser.add_argument("--json-out", default=str(DEFAULT_OUT))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    backtest = _load_json(Path(args.backtest))
    payload = build_backtest_parameter_candidate(backtest)
    atomic_write_json(_assert_backtest_path(Path(args.json_out)), payload)
    print(json.dumps({"json_out": args.json_out, "safe_to_live_activate_now": False, "hash_to_approve": payload["hash_to_approve"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_backtest_parameter_candidate", "main", "parse_args"]
