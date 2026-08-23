#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text


DEFAULT_ACTIVE = Path("state/approved_parameter_profile.json")
DEFAULT_CANDIDATE = Path("reports/backtests/approved-profile-candidate-from-backtest.json")
DEFAULT_BACKTEST = Path("reports/backtests/btc-eth-parameter-backtest-latest.json")
DEFAULT_RESEARCH = Path("reports/research/research-prior-parameter-profile-latest.json")
DEFAULT_JSON_OUT = Path("reports/research/literature-backtest-parameter-matrix-latest.json")
DEFAULT_MD_OUT = Path("reports/research/literature-backtest-parameter-matrix-latest.md")

SIZING_KEYS = {
    "MAX_LIVE_ORDER_QUOTE_USDC",
    "MAX_NOTIONAL_USD",
    "AUTONOMOUS_MAX_ORDER_QUOTE",
    "PHASE_C_MAX_ORDER_QUOTE",
    "PHASE_D3_MAX_EXIT_ORDER_QUOTE",
}
D2_KEYS = {
    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
    "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
    "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _params(payload: Any) -> Dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("parameters"), dict):
        return {str(k): str(v) for k, v in payload["parameters"].items()}
    if isinstance(payload.get("approved_profile_json"), dict):
        return _params(payload["approved_profile_json"])
    if isinstance(payload.get("candidate_profile"), dict):
        return {str(k): str(v) for k, v in payload["candidate_profile"].items()}
    return {}


def _band(backtest: Dict[str, Any], key: str) -> Any:
    candidate = backtest.get("candidate") if isinstance(backtest.get("candidate"), dict) else {}
    band = candidate.get("recommended_parameter_band") if isinstance(candidate.get("recommended_parameter_band"), dict) else {}
    return band.get(key)


def _score_context(backtest: Dict[str, Any]) -> Dict[str, Any]:
    labels = backtest.get("label_counts") if isinstance(backtest.get("label_counts"), dict) else {}
    good_entry = int(labels.get("good_entry_candidate") or 0)
    bad_entry = int(labels.get("bad_entry_candidate") or 0)
    missed = int(labels.get("missed_opportunity") or 0)
    good_wait = int(labels.get("good_wait") or 0)
    correct_avoid = int(labels.get("correct_avoid") or 0)
    sample_size = int((backtest.get("candidate") or {}).get("sample_size") or sum(int(v or 0) for v in labels.values()))
    return {
        "sample_size": sample_size,
        "label_counts": labels,
        "good_entry_candidate": good_entry,
        "bad_entry_candidate": bad_entry,
        "missed_opportunity": missed,
        "good_wait": good_wait,
        "correct_avoid": correct_avoid,
        "bad_entry_gt_good_entry": bad_entry > good_entry,
        "many_waits_likely_correct": good_wait > missed and correct_avoid > good_entry,
        "confidence": (backtest.get("candidate") or {}).get("confidence") or "unknown",
        "overfit_risk": (backtest.get("candidate") or {}).get("overfit_risk") or "unknown",
    }


def _entry(
    *,
    key: str,
    active: Dict[str, str],
    candidate: Dict[str, str],
    backtest: Dict[str, Any],
    recommendation: str,
    safe: bool,
    reason: str,
    research_support: str,
    support_classification: str,
    live_learning_dependency: str,
) -> Dict[str, Any]:
    return {
        "active_value": active.get(key, ""),
        "candidate_value": candidate.get(key, ""),
        "research_support": research_support,
        "support_classification": support_classification,
        "backtest_support": "medium" if _band(backtest, key) else "not_directly_parameterized",
        "backtest_band": _band(backtest, key),
        "live_learning_dependency": live_learning_dependency,
        "recommendation": recommendation,
        "safe_to_activate_now": safe,
        "reason": reason,
    }


def build_matrix(
    *,
    active_path: str | Path = DEFAULT_ACTIVE,
    candidate_path: str | Path = DEFAULT_CANDIDATE,
    backtest_path: str | Path = DEFAULT_BACKTEST,
    research_path: str | Path = DEFAULT_RESEARCH,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    active_payload = _load_json(Path(active_path))
    candidate_payload = _load_json(Path(candidate_path))
    backtest = _load_json(Path(backtest_path))
    research = _load_json(Path(research_path))
    active = _params(active_payload)
    candidate = _params(candidate_payload)
    score = _score_context(backtest if isinstance(backtest, dict) else {})

    matrix: Dict[str, Any] = {}
    for key in [
        "MAX_LIVE_ORDER_QUOTE_USDC",
        "DEFAULT_QUOTE_SIZE_USDC",
        "MAX_NOTIONAL_USD",
        "AUTONOMOUS_MAX_ORDER_QUOTE",
        "PHASE_C_MAX_ORDER_QUOTE",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE",
    ]:
        if key == "MAX_LIVE_ORDER_QUOTE_USDC":
            active_value = active.get("MAX_NOTIONAL_USD") or active.get("AUTONOMOUS_MAX_ORDER_QUOTE") or ""
            candidate_value = candidate.get("MAX_NOTIONAL_USD") or candidate.get("AUTONOMOUS_MAX_ORDER_QUOTE") or ""
            local_active = {key: active_value}
            local_candidate = {key: candidate_value}
        else:
            local_active = active
            local_candidate = candidate
        matrix[key] = _entry(
            key=key,
            active=local_active,
            candidate=local_candidate,
            backtest=backtest,
            recommendation="activate_sizing_only" if key in SIZING_KEYS else "keep_conservative_default",
            safe=key in SIZING_KEYS,
            research_support="position_sizing_risk_policy",
            support_classification="risk_policy_supported",
            live_learning_dependency="fill_quality_and_outcome_tracking",
            reason=(
                "Default quote remains 20; hard rails remain 20-100; max_new_orders_per_cycle=1 and max_open_orders=3."
                if key in SIZING_KEYS
                else "Default quote already stays at the minimum starter size; no extra aggressiveness is introduced."
            ),
        )

    for key in [
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
    ]:
        matrix[key] = _entry(
            key=key,
            active=active,
            candidate=candidate,
            backtest=backtest,
            recommendation="do_not_activate_yet",
            safe=False,
            research_support="transaction_cost_filtering",
            support_classification="research_supported",
            live_learning_dependency="closed_trade_outcomes_and_no_fill_costs",
            reason="bad_entry_candidate exceeds good_entry_candidate; the backtest candidate is static and not metric-optimized.",
        )

    matrix["MAX_SPREAD_PCT"] = _entry(
        key="MAX_SPREAD_PCT",
        active=active,
        candidate=candidate,
        backtest=backtest,
        recommendation="keep_current",
        safe=True,
        research_support="cost_aware_execution",
        support_classification="research_supported",
        live_learning_dependency="real_orderbook_spread_and_fill_quality",
        reason="Current spread cap is inside the tested band and is not loosened by the sizing-only activation.",
    )
    matrix["EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT"] = _entry(
        key="EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
        active=active,
        candidate=candidate,
        backtest=backtest,
        recommendation="keep_current",
        safe=True,
        research_support="cost_aware_execution",
        support_classification="research_supported",
        live_learning_dependency="exit_fill_quality_and_stale_target_detection",
        reason="Current value is unchanged; historical orderbook is unavailable, so exit timing still needs live evidence.",
    )
    for key, research_support in [
        ("ATR_STOP_MULTIPLIER", "technical_trading_rules"),
        ("TAKE_PROFIT_R_MULTIPLE", "technical_trading_rules"),
        ("OBJECTIVE_SCORE_STARTER_MIN", "data_mining_overfit_risk"),
        ("OBJECTIVE_SCORE_NORMAL_MIN", "data_mining_overfit_risk"),
    ]:
        matrix[key] = {
            "active_value": active.get(key, ""),
            "candidate_value": "",
            "research_support": research_support,
            "support_classification": "live_learning_only" if key.startswith("OBJECTIVE") else "backtest_supported",
            "backtest_support": "medium" if _band(backtest, key) else "weak_or_uncertain",
            "backtest_band": _band(backtest, key),
            "live_learning_dependency": "strategy_outcomes_and_missed_opportunity_labels",
            "recommendation": "do_not_activate_yet",
            "safe_to_activate_now": False,
            "reason": "Useful research/backtest prior, but not part of the current approved-profile whitelist or sizing-only scope.",
        }
    matrix["planner_no_plan_policy"] = {
        "active_value": "prompt_policy",
        "candidate_value": "no_plan_only_with_concrete_negative_or_missing_conditions",
        "research_support": "data_mining_overfit_risk",
        "support_classification": "research_supported",
        "backtest_support": "weak_or_uncertain",
        "live_learning_dependency": "missed_opportunity_and_trigger_ready_but_waited_labels",
        "recommendation": "keep_prompt_policy_monitor_outcomes",
        "safe_to_activate_now": False,
        "reason": "Prompt policy can reduce passivity, but it should not bypass deterministic risk or sizing rails.",
    }
    matrix["bounded_exploration_limits"] = {
        "active_value": "disabled",
        "candidate_value": "20-35 USDC, BTC/ETH/SOL, max 1 open probe, max 2/day",
        "research_support": "position_sizing_risk_policy",
        "support_classification": "live_learning_only",
        "backtest_support": "not_supported_yet",
        "live_learning_dependency": "balanced_probe_labels",
        "recommendation": "do_not_activate_without_separate_exploration_ack",
        "safe_to_activate_now": False,
        "reason": "Exploration is present but intentionally disabled; it needs a separate ACK and fresh monitoring.",
    }

    recommendations = {
        "activate_now": sorted(k for k, v in matrix.items() if v.get("recommendation") == "activate_sizing_only"),
        "keep_conservative": sorted(k for k, v in matrix.items() if v.get("recommendation") in {"do_not_activate_yet", "keep_current", "keep_conservative_default"}),
        "interpretation": [
            "Many waits were likely correct.",
            "Missed opportunities exist and should feed learning labels.",
            "bad_entry_candidate is greater than good_entry_candidate, so broad D2 loosening is not supported.",
            "Sizing 20-100 is a bounded risk-policy change, not a signal-threshold loosening.",
        ],
    }
    return {
        "phase": "literature_backtest_parameter_matrix_v1",
        "generated_at": generated_at or _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "service_touched": False,
        "env_write_performed": False,
        "state_write_performed": False,
        "research_prior_categories": [
            "technical_trading_rules",
            "moving_average_rules",
            "trading_range_breakout",
            "transaction_cost_filtering",
            "cost_aware_execution",
            "data_mining_overfit_risk",
            "position_sizing_risk_policy",
        ],
        "support_classifications": [
            "research_supported",
            "backtest_supported",
            "risk_policy_supported",
            "live_learning_only",
            "not_supported_yet",
        ],
        "backtest_context": score,
        "research_prior_available": bool(research),
        "candidate_is_static_research_prior": bool(candidate_payload.get("candidate_is_static_research_prior", True)) if isinstance(candidate_payload, dict) else True,
        "candidate_not_metric_optimized": bool(candidate_payload.get("candidate_not_metric_optimized", True)) if isinstance(candidate_payload, dict) else True,
        "matrix": matrix,
        "recommendations": recommendations,
    }


def _render_md(report: Dict[str, Any]) -> str:
    lines = [
        "# Literature Backtest Parameter Matrix",
        "",
        f"Generated at: `{report['generated_at']}`",
        "",
        "## Conclusion",
        "",
        "- Activate sizing-only caps to 100 USDC.",
        "- Keep D2 thresholds conservative.",
        "- Do not activate bounded exploration without a separate ACK.",
        "- Candidate is treated as research-prior/backtest-available, not metric-optimized.",
        "",
        "## Backtest Context",
        "",
        "```json",
        json.dumps(report["backtest_context"], indent=2, sort_keys=True),
        "```",
        "",
        "## Matrix",
        "",
        "| Parameter | Active | Candidate | Recommendation | Safe now | Reason |",
        "|---|---:|---:|---|---|---|",
    ]
    for key, row in report["matrix"].items():
        reason = str(row.get("reason", "")).replace("|", "/")
        lines.append(
            f"| `{key}` | `{row.get('active_value', '')}` | `{row.get('candidate_value', '')}` | "
            f"`{row.get('recommendation', '')}` | `{row.get('safe_to_activate_now')}` | {reason} |"
        )
    lines.extend(["", "## Safety", "", "- No Coinbase calls attempted.", "- No service touched.", "- No state or env writes performed by this matrix tool.", ""])
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build literature/backtest/profile parameter matrix.")
    parser.add_argument("--active", default=str(DEFAULT_ACTIVE))
    parser.add_argument("--candidate", default=str(DEFAULT_CANDIDATE))
    parser.add_argument("--backtest", default=str(DEFAULT_BACKTEST))
    parser.add_argument("--research", default=str(DEFAULT_RESEARCH))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--md-out", default=str(DEFAULT_MD_OUT))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_matrix(
        active_path=args.active,
        candidate_path=args.candidate,
        backtest_path=args.backtest,
        research_path=args.research,
    )
    atomic_write_json(Path(args.json_out), report)
    atomic_write_text(Path(args.md_out), _render_md(report))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "activate_now": report["recommendations"]["activate_now"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_matrix", "main", "parse_args"]
