from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PHASE_SHADOW_PARAMETER_APPROXIMATION_PACK = "shadow_parameter_approximation_pack_v1"


PARAMETER_CATEGORIES = [
    "Universe/ticker scope",
    "Entry gating thresholds",
    "Sizing/caps",
    "Max open orders / new orders per cycle",
    "Spread tolerance",
    "Maker/post-only placement offsets",
    "No-fill timeout",
    "Cancel/replace timing",
    "Partial-fill handling",
    "Exit preview readiness",
    "Live-exit safety",
    "Backlearning governance thresholds",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _category_row(category: str, preflight_attempted: bool, preflight_passed: bool) -> Dict[str, Any]:
    needs_live = not preflight_attempted or not preflight_passed
    if category in {"Universe/ticker scope", "Sizing/caps", "Max open orders / new orders per cycle"}:
        range_text = "review-only approximation: keep current tiny/BTC scope until live-readonly all-ticker preflight is green"
        status = "needs_live_evidence" if needs_live else "keep_current"
        confidence = "low" if needs_live else "medium"
    elif category in {"Entry gating thresholds", "Spread tolerance", "Maker/post-only placement offsets"}:
        range_text = "review-only approximation: observe current behavior; do not relax before 24h evidence"
        status = "insufficient_evidence"
        confidence = "low"
    elif category in {"No-fill timeout", "Cancel/replace timing", "Partial-fill handling"}:
        range_text = "review-only approximation: evidence labels only; tune only after 24h fill/no-fill samples"
        status = "needs_live_evidence"
        confidence = "low"
    elif category in {"Exit preview readiness", "Live-exit safety"}:
        range_text = "review-only approximation: keep live exits disabled until live position/fill evidence and ACK"
        status = "keep_current"
        confidence = "medium"
    else:
        range_text = "review-only approximation: keep governance thresholds closed; no execution bridge"
        status = "keep_current"
        confidence = "medium"
    return {
        "category": category,
        "current_observed_setting": "current repo/report setting observed; no mutation performed",
        "evidence_basis": [
            "D6 label export",
            "paper lifecycle replay",
            "product-rule fixture/cache",
            "all-ticker live-readonly preflight report" if preflight_attempted else "all-ticker live-readonly preflight not run",
        ],
        "live_situation_relevance": "requires live-readonly product/balance/min-notional context before live use",
        "approximation_status": status,
        "review_only_approximate_range": range_text,
        "confidence": confidence,
        "risk_if_changed_now": "unsafe_before_24h_evidence_and_human_ACK",
        "recommendation_for_24h_test": "keep_current" if category in {"Universe/ticker scope", "Exit preview readiness", "Live-exit safety", "Backlearning governance thresholds"} else "observe_only",
        "forbidden_action": "do not change, approve, optimize, rank for live use, or connect to execution",
    }


def build_shadow_parameter_approximation_pack(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    preflight_report_path: str | Path = "reports/d6/all-ticker-live-readonly-preflight-20260609.json",
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    preflight_path = Path(preflight_report_path)
    if not preflight_path.is_absolute():
        preflight_path = project_root / preflight_path
    preflight = _load_json(preflight_path)
    preflight_gate = preflight.get("gate_decision") if isinstance(preflight.get("gate_decision"), dict) else {}
    preflight_attempted = bool(preflight_gate.get("all_ticker_live_readonly_preflight_attempted", False))
    preflight_passed = bool(preflight_gate.get("all_ticker_live_readonly_preflight_passed", False))
    sources = {
        "d6_label_export": (project_root / "reports/d6/d6-backlearning-label-export-pack-20260609.json").exists(),
        "paper_lifecycle_replay": (project_root / "reports/d6/multi-ticker-paper-lifecycle-replay-20260609.json").exists(),
        "product_rule_cache": (project_root / "reports/d6/per-ticker-product-rule-evidence-cache-20260609.json").exists(),
        "live_readonly_preflight_report": bool(preflight),
    }
    missing = [key for key, present in sources.items() if not present]
    matrix = [_category_row(category, preflight_attempted, preflight_passed) for category in PARAMETER_CATEGORIES]
    report = {
        "phase": PHASE_SHADOW_PARAMETER_APPROXIMATION_PACK,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "approximation_only": True,
            "shadow_parameter_approximation_only": True,
            "training_performed": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "parameter_values_proposed": False,
            "parameter_values_approved": False,
            "parameter_mutation_performed": False,
            "config_mutation_performed": False,
            "env_mutation_performed": False,
            "state_write_performed": False,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "learning_to_execution_ready": False,
            "live_learning_allowed": False,
        },
        "classification": "WATCH" if missing or not preflight_attempted else "OK",
        "evidence_sources": sources,
        "missing_evidence_sources": missing,
        "preflight_consumed": bool(preflight),
        "preflight_attempted": preflight_attempted,
        "preflight_passed": preflight_passed,
        "parameter_approximation_matrix": matrix,
        "governance_flags": {
            "shadow_parameter_approximation_pack_ready": True,
            "parameter_values_approved": False,
            "parameter_change_allowed": False,
            "safe_to_mutate_parameters_now": False,
            "ready_to_change_parameters": False,
            "parameter_mutation_performed": False,
            "config_mutation_performed": False,
            "env_mutation_performed": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "learning_to_execution_ready": False,
            "live_learning_allowed": False,
        },
        "operator_decision_outputs": {
            "choice_1_btc_usdc_only_manual_24h_test": {
                "risk": "lower",
                "recommended": True,
                "conditions": [
                    "selected harness OK",
                    "open_orders=0",
                    "function audit OK",
                    "BTC-USDC fresh preflight OK",
                    "live exits disabled",
                    "parameters unchanged",
                    "operator exact ACK",
                ],
            },
            "choice_2_all_ticker_manual_24h_test": {
                "risk": "higher",
                "recommended": bool(preflight_passed),
                "conditions": [
                    "all-ticker live-readonly preflight OK for every included ticker",
                    "per-ticker blockers empty",
                    "exact all-ticker ACK",
                    "caps reviewed",
                    "max new orders per cycle reviewed",
                    "parameters unchanged",
                    "operator manual start only",
                ],
            },
        },
    }
    return _json_safe(report)


def render_shadow_parameter_approximation_pack_markdown(report: Dict[str, Any]) -> str:
    flags = report.get("governance_flags") or {}
    lines = [
        "# Shadow Parameter Approximation Pack",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- shadow_parameter_approximation_pack_ready: `{flags.get('shadow_parameter_approximation_pack_ready')}`",
        f"- parameter_values_approved: `{flags.get('parameter_values_approved')}`",
        f"- parameter_change_allowed: `{flags.get('parameter_change_allowed')}`",
        f"- safe_to_mutate_parameters_now: `{flags.get('safe_to_mutate_parameters_now')}`",
        "",
        "## Parameter Categories",
        "",
    ]
    for row in report.get("parameter_approximation_matrix") or []:
        lines.append(
            f"- {row.get('category')}: status=`{row.get('approximation_status')}`, "
            f"confidence=`{row.get('confidence')}`, recommendation=`{row.get('recommendation_for_24h_test')}`"
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_SHADOW_PARAMETER_APPROXIMATION_PACK",
    "PARAMETER_CATEGORIES",
    "build_shadow_parameter_approximation_pack",
    "render_shadow_parameter_approximation_pack_markdown",
]
