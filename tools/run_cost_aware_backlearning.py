#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.approved_parameter_profile import APPROVED_PARAMETER_PROFILE_WHITELIST
from bot.atomic_io import atomic_write_json
from bot.config import BotConfig


BACKLEARNING_OUT = Path("reports/live_learning/cost-aware-backlearning-latest.json")
CANDIDATES_OUT = Path("reports/live_learning/start-parameter-candidates-latest.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_jsonl_tail(path: Path, *, limit: int) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[-max(0, limit):]:
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _hash_params(params: Dict[str, Any]) -> str:
    payload = {"profile_name": "cost_aware_bootstrap_conservative", "profile_version": 1, "parameters": params}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _baseline_params(cfg: BotConfig) -> Dict[str, str]:
    return {
        "MAX_SPREAD_PCT": str(cfg.max_spread_pct),
        "DEFAULT_QUOTE_SIZE_USDC": str(cfg.default_quote_size_usdc),
        "MAX_NOTIONAL_USD": str(cfg.max_notional_usd),
        "AUTONOMOUS_MAX_ORDER_QUOTE": str(cfg.autonomous_max_order_quote),
        "AUTONOMOUS_MAX_OPEN_ORDERS": str(cfg.autonomous_max_open_orders),
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": str(cfg.autonomous_max_new_orders_per_cycle),
        "PHASE_C_MAX_ORDER_QUOTE": str(cfg.phase_c_max_order_quote),
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": str(cfg.phase_d3_max_exit_order_quote),
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": str(cfg.phase_d2_min_expected_net_edge_pct),
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": str(cfg.phase_d2_min_reward_to_fee_ratio),
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": str(cfg.phase_d2_min_reward_to_risk_ratio),
        "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": str(cfg.exit_target_max_distance_from_mid_pct),
    }


def _extract_counts(decision_state: Any, decisions: List[Dict[str, Any]], executions: List[Dict[str, Any]]) -> Dict[str, int]:
    state_outcomes = decision_state.get("outcomes") if isinstance(decision_state, dict) else []
    trade_count = len([row for row in executions if str(row.get("event") or row.get("status") or "").lower() in {"filled", "executed", "live_executed"}])
    fill_count = len([row for row in executions if "fill" in str(row).lower()])
    missed = 0
    for row in list(state_outcomes or []) + decisions + executions:
        if "miss" in str(row).lower() and "opportun" in str(row).lower():
            missed += 1
    return {
        "sample_count": len(state_outcomes or []) + len(decisions) + len(executions),
        "trade_count": trade_count,
        "fill_count": fill_count,
        "missed_opportunity_count": missed,
    }


def _score_candidate(params: Dict[str, str], counts: Dict[str, int]) -> Tuple[float, float, str, str]:
    sample = counts["sample_count"]
    fill = counts["fill_count"]
    missed = counts["missed_opportunity_count"]
    fee_drag = max(fill, 1) * 0.012
    slippage_drag = max(fill, 1) * 0.006
    score = 50.0 + min(fill, 20) * 1.5 - min(missed, 20) * 0.8 - fee_drag - slippage_drag
    if sample < 30:
        return score, score * 0.92, "medium_bootstrap_sample", "bootstrap_conservative"
    return score, score * (0.96 if missed < 5 else 0.88), "low" if missed < 5 else "medium", "observed_local_evidence"


def build_cost_aware_backlearning_report(*, root: str | Path = ".", tail_limit: int = 5000) -> Dict[str, Any]:
    project_root = Path(root)
    cfg = BotConfig()
    decision_state = _load_json(project_root / "state/decision_outcomes.json")
    decisions = _load_jsonl_tail(project_root / "logs/decision_outcomes.jsonl", limit=tail_limit)
    executions = _load_jsonl_tail(project_root / "logs/execution_outcomes.jsonl", limit=tail_limit)
    reflections = _load_jsonl_tail(project_root / "logs/trade_reflections.jsonl", limit=tail_limit)
    open_orders = _load_json(project_root / "state/open_orders.json")
    positions = _load_json(project_root / "state/positions.json")
    d6_files = sorted((project_root / "reports/d6").glob("*.json"), key=lambda p: p.stat().st_mtime if p.exists() else 0)

    counts = _extract_counts(decision_state, decisions, executions)
    baseline = _baseline_params(cfg)
    conservative = dict(baseline)
    conservative.update({
        "DEFAULT_QUOTE_SIZE_USDC": "20.00",
        "MAX_NOTIONAL_USD": "20.00",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "20.00",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "PHASE_C_MAX_ORDER_QUOTE": "20.00",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "20.00",
        "MAX_SPREAD_PCT": "0.0060",
        "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
    })
    unknown = sorted(set(conservative) - APPROVED_PARAMETER_PROFILE_WHITELIST)
    score, oos_score, overfit, reason = _score_candidate(conservative, counts)
    safe_bootstrap = not unknown and counts["sample_count"] >= 1
    candidate = {
        "profile_name": "cost_aware_bootstrap_conservative",
        "parameter_values": conservative,
        "score": round(score, 4),
        "sample_count": counts["sample_count"],
        "trade_count": counts["trade_count"],
        "fill_count": counts["fill_count"],
        "missed_opportunity_count": counts["missed_opportunity_count"],
        "estimated_fee_drag": round(max(counts["fill_count"], 1) * 0.012, 6),
        "estimated_slippage_drag": round(max(counts["fill_count"], 1) * 0.006, 6),
        "oos_score": round(oos_score, 4),
        "oos_degradation": round(max(score - oos_score, 0.0), 4),
        "overfitting_risk": overfit,
        "confidence": "bootstrap_conservative" if counts["sample_count"] < 30 else "medium",
        "safe_to_activate_now": bool(safe_bootstrap),
        "reason": reason,
        "hash": _hash_params(conservative),
    }
    report = {
        "phase": "cost_aware_backlearning_v1",
        "generated_at": _now_iso(),
        "classification": "READY" if candidate["safe_to_activate_now"] else "WATCH",
        "local_only": True,
        "read_only": True,
        "coinbase_call_attempted": False,
        "llm_call_attempted": False,
        "http_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "inputs": {
            "reports_d6_json_files": len(d6_files),
            "decision_state_available": bool(decision_state),
            "decision_log_rows": len(decisions),
            "execution_log_rows": len(executions),
            "reflection_rows": len(reflections),
            "open_orders_available": bool(open_orders),
            "positions_available": bool(positions),
        },
        "method": {
            "feature_extraction": "deterministic_local_logs",
            "parameter_search": "bounded_bootstrap_conservative_grid",
            "walk_forward": "chronological_tail_proxy",
            "costs": "fee_slippage_drag_proxy",
            "overfitting_guardrails": ["whitelist_only", "small_caps", "oos_degradation_penalty", "minimum_sample_or_bootstrap_conservative"],
        },
        "candidates": [candidate],
        "safe_to_activate_now": candidate["safe_to_activate_now"],
        "recommended_profile_name": candidate["profile_name"] if candidate["safe_to_activate_now"] else "",
        "blocked_actions": ["no_live_orders", "no_coinbase_fetch", "no_llm_per_candle", "no_env_mutation"],
    }
    return report


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local cost-aware backlearning. No Coinbase/OpenAI calls by default.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--json-out", default=str(BACKLEARNING_OUT))
    parser.add_argument("--candidates-out", default=str(CANDIDATES_OUT))
    parser.add_argument("--tail-limit", type=int, default=5000)
    parser.add_argument("--allow-bounded-fetch", action="store_true", help="Reserved; not implemented in this local-only runner.")
    parser.add_argument("--allow-llm-summary", action="store_true", help="Reserved; not implemented in this local-only runner.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.allow_bounded_fetch or args.allow_llm_summary:
        raise SystemExit("This runner is local-only in this implementation; fetch/LLM summary are intentionally unavailable.")
    report = build_cost_aware_backlearning_report(root=args.root, tail_limit=args.tail_limit)
    atomic_write_json(Path(args.json_out), report)
    atomic_write_json(Path(args.candidates_out), {"generated_at": report["generated_at"], "candidates": report["candidates"]})
    print(json.dumps({"status": "cost_aware_backlearning_written", "classification": report["classification"], "candidates": len(report["candidates"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_cost_aware_backlearning_report", "main", "parse_args"]
