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

from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.approved_parameter_profile import sha256_file

DEFAULT_JSON = Path("reports/backtests/active-vs-candidate-profile-review-latest.json")
DEFAULT_MD = Path("reports/backtests/active-vs-candidate-profile-review-latest.md")
PARAMETERS = [
    "DEFAULT_QUOTE_SIZE_USDC",
    "MAX_NOTIONAL_USD",
    "AUTONOMOUS_MAX_ORDER_QUOTE",
    "PHASE_C_MAX_ORDER_QUOTE",
    "PHASE_D3_MAX_EXIT_ORDER_QUOTE",
    "MAX_SPREAD_PCT",
    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
    "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
    "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
    "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _canonical_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _dec(value: Any) -> Optional[float]:
    try:
        return float(str(value))
    except Exception:
        return None


def _diff(active: Dict[str, str], candidate: Dict[str, str]) -> list[Dict[str, Any]]:
    rows = []
    for key in PARAMETERS:
        active_value = active.get(key)
        candidate_value = candidate.get(key)
        a = _dec(active_value)
        c = _dec(candidate_value)
        direction = "unchanged"
        if a is not None and c is not None:
            if c > a:
                direction = "looser_or_larger"
            elif c < a:
                direction = "stricter_or_smaller"
        elif str(active_value) != str(candidate_value):
            direction = "changed"
        rows.append({
            "parameter": key,
            "active": active_value,
            "candidate": candidate_value,
            "direction": direction,
            "delta_numeric": None if a is None or c is None else c - a,
        })
    return rows


def build_review(
    *,
    active_path: str | Path = "state/approved_parameter_profile.json",
    candidate_path: str | Path = "reports/backtests/approved-profile-candidate-from-backtest.json",
    backtest_path: str | Path = "reports/backtests/btc-eth-parameter-backtest-latest.json",
    research_path: str | Path = "reports/research/research-prior-parameter-profile-latest.json",
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    active_path_p = Path(active_path)
    candidate_path_p = Path(candidate_path)
    active_payload = _load_json(active_path_p)
    candidate_payload = _load_json(candidate_path_p)
    backtest = _load_json(Path(backtest_path))
    research = _load_json(Path(research_path))
    active_params = {str(k): str(v) for k, v in (active_payload.get("parameters") or {}).items()} if isinstance(active_payload, dict) else {}
    candidate_profile = candidate_payload.get("approved_profile_json") if isinstance(candidate_payload.get("approved_profile_json"), dict) else {}
    candidate_params = {str(k): str(v) for k, v in (candidate_profile.get("parameters") or candidate_payload.get("candidate_profile") or {}).items()}
    label_counts = backtest.get("label_counts") if isinstance(backtest.get("label_counts"), dict) else {}
    good = int(label_counts.get("good_entry_candidate") or 0)
    bad = int(label_counts.get("bad_entry_candidate") or 0)
    missed = int(label_counts.get("missed_opportunity") or 0)
    static = bool(candidate_payload.get("candidate_is_static_research_prior"))
    sizing_only = all(
        row["parameter"] in {"MAX_NOTIONAL_USD", "AUTONOMOUS_MAX_ORDER_QUOTE", "PHASE_C_MAX_ORDER_QUOTE", "PHASE_D3_MAX_EXIT_ORDER_QUOTE"}
        or row["direction"] == "unchanged"
        for row in _diff(active_params, candidate_params)
    )
    recommendation = "activate_only_after_adaptive_candidate_fix" if static else "do_not_activate"
    if static and bad > good:
        recommendation = "activate_only_sizing_after_operator_review_or_wait_for_adaptive_candidate_fix"
    if not static and bad > good:
        recommendation = "do_not_activate"
    return {
        "generated_at": generated_at or _now_iso(),
        "read_only": True,
        "coinbase_action_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "service_touched": False,
        "approved_profile_activation_performed": False,
        "active_profile": {
            "path": str(active_path_p),
            "profile_name": active_payload.get("profile_name"),
            "profile_version": active_payload.get("profile_version"),
            "hash_method": "sha256_file",
            "hash": sha256_file(active_path_p) if active_path_p.exists() else "",
        },
        "candidate_profile": {
            "path": str(candidate_path_p),
            "profile_name": candidate_profile.get("profile_name") or candidate_payload.get("profile_name"),
            "profile_version": candidate_profile.get("profile_version") or candidate_payload.get("profile_version"),
            "hash_method": "canonical_approved_profile_json",
            "hash": candidate_payload.get("hash_to_approve") or _canonical_hash(candidate_profile),
            "safe_to_live_activate_now": bool(candidate_payload.get("safe_to_live_activate_now")),
            "requires_operator_review": bool(candidate_payload.get("requires_operator_review")),
            "requires_exact_hash_ack": bool(candidate_payload.get("requires_exact_hash_ack")),
        },
        "candidate_static_or_adaptive": {
            "candidate_is_static_research_prior": static,
            "candidate_not_metric_optimized": bool(candidate_payload.get("candidate_not_metric_optimized")),
            "label_counts_used_for_parameters": bool((candidate_payload.get("metric_dependency") or {}).get("label_counts_used_for_parameters")),
            "per_timeframe_results_used_for_parameters": bool((candidate_payload.get("metric_dependency") or {}).get("per_timeframe_results_used_for_parameters")),
            "sample_size_used_for_confidence": bool((candidate_payload.get("metric_dependency") or {}).get("sample_size_used_for_confidence")),
        },
        "backtest_metrics": {
            "sample_size": int((backtest.get("candidate") or {}).get("sample_size") or candidate_payload.get("sample_size") or 0),
            "label_counts": label_counts,
            "good_entry_candidate": good,
            "bad_entry_candidate": bad,
            "missed_opportunity": missed,
            "bad_entry_gt_good_entry": bad > good,
            "confidence": (backtest.get("candidate") or {}).get("confidence") or candidate_payload.get("confidence"),
            "overfit_risk": (backtest.get("candidate") or {}).get("overfit_risk") or candidate_payload.get("overfit_risk"),
        },
        "parameter_diffs": _diff(active_params, candidate_params),
        "runtime_effect": {
            "sizing": "MAX_NOTIONAL/AUTONOMOUS/PHASE_C/PHASE_D3 caps move from 20 to 100 USDC; default quote stays 20 USDC.",
            "d2_thresholds": "Expected net edge 0.0125 -> 0.0100 and reward-to-fee 3.0 -> 2.5 are looser; reward-to-risk remains effectively 1.5.",
            "spread": "MAX_SPREAD_PCT unchanged at 0.0060.",
            "exit_distance": "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT unchanged at 0.0350.",
        },
        "risk_assessment": [
            "Candidate is not metric-optimized; concrete values are static research-prior defaults.",
            "bad_entry_candidate=2315 is greater than good_entry_candidate=581, so full threshold loosening may be too aggressive.",
            "Sizing 20-100 is supported by runtime rails and backtest candidate bands, but live fill/no-fill quality still needs learning.",
            "Historical orderbook is absent; orderbook timing remains live-learning-only.",
        ],
        "supports_20_100_sizing": bool(candidate_payload.get("supports_20_100_sizing")),
        "d2_thresholds_loosened": True,
        "could_be_too_aggressive": bool(bad > good),
        "sizing_only_activation_possible": sizing_only,
        "recommendation": recommendation,
        "research_prior_available": bool(research),
    }


def _markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Active vs Candidate Profile Review",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Active hash: `{report['active_profile']['hash']}`",
        f"- Candidate hash: `{report['candidate_profile']['hash']}`",
        f"- Candidate static research prior: `{report['candidate_static_or_adaptive']['candidate_is_static_research_prior']}`",
        f"- Candidate not metric optimized: `{report['candidate_static_or_adaptive']['candidate_not_metric_optimized']}`",
        f"- Recommendation: `{report['recommendation']}`",
        f"- Safe to live activate now: `{report['candidate_profile']['safe_to_live_activate_now']}`",
        f"- Requires operator review: `{report['candidate_profile']['requires_operator_review']}`",
        "",
        "## Backtest Metrics",
        "",
        f"- Sample size: `{report['backtest_metrics']['sample_size']}`",
        f"- good_entry_candidate: `{report['backtest_metrics']['good_entry_candidate']}`",
        f"- bad_entry_candidate: `{report['backtest_metrics']['bad_entry_candidate']}`",
        f"- missed_opportunity: `{report['backtest_metrics']['missed_opportunity']}`",
        f"- Confidence: `{report['backtest_metrics']['confidence']}`",
        f"- Overfit risk: `{report['backtest_metrics']['overfit_risk']}`",
        "",
        "## Parameter Diffs",
        "",
    ]
    for row in report["parameter_diffs"]:
        lines.append(f"- `{row['parameter']}`: active `{row['active']}` -> candidate `{row['candidate']}` ({row['direction']})")
    lines.extend([
        "",
        "## Runtime Effect",
        "",
    ])
    for value in report["runtime_effect"].values():
        lines.append(f"- {value}")
    lines.extend(["", "## Risks", ""])
    lines.extend(f"- {risk}" for risk in report["risk_assessment"])
    lines.append("")
    return "\n".join(lines)


def _assert_backtest_path(path: Path) -> Path:
    target = path.resolve()
    allowed = (Path.cwd() / "reports/backtests").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/backtests")
    return target


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only active-vs-backtest-candidate profile review.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_review()
    atomic_write_json(_assert_backtest_path(Path(args.json_out)), report)
    atomic_write_text(_assert_backtest_path(Path(args.md_out)), _markdown(report))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "recommendation": report["recommendation"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_review", "main", "parse_args"]
