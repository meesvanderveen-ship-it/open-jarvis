from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.phase_d6_parameter_inventory import CATEGORY_LABELS, build_parameter_candidates


PHASE_D6_BACKLEARNING_PARAMETER_EVIDENCE_PLAN = "d6_backlearning_parameter_evidence_plan_v1"

DEFAULT_EVIDENCE_REPORTS = {
    "d5_d6_evidence_expansion": "reports/d6/d5-d6-evidence-expansion-20260609.json",
    "multi_ticker_paper_lifecycle_replay": "reports/d6/multi-ticker-paper-lifecycle-replay-20260609.json",
    "per_ticker_product_rule_evidence_cache": "reports/d6/per-ticker-product-rule-evidence-cache-20260609.json",
    "all_ticker_readiness_gate": "reports/d6/all-ticker-readiness-gate-20260609.json",
    "main_workflow_parity_report": "reports/d6/main-workflow-parity-report-20260609.json",
    "exit_workflow_readiness_report": "reports/d6/exit-workflow-readiness-report-20260609.json",
    "safe_regression_harness": "reports/d6/safe-regression-harness-20260609.json",
    "state_hygiene_cleanup_preview": "reports/d6/state-hygiene-cleanup-preview-20260609.json",
    "coverage_backtest_decision": "reports/d6/coverage-backtest-decision-v1-20260601.json",
}

PARAMETER_CATEGORIES = [
    {
        "category": "entry_gating_parameters",
        "inventory_categories": ["gatekeeper_routing", "entry_signal", "ai_prompt_judge"],
        "evidence_present": [
            "old multi-ticker decision workflow evidence",
            "main workflow parity report",
            "all-ticker readiness gate",
        ],
        "evidence_missing": [
            "lifecycle outcome sample size by setup",
            "fresh OOS or walk-forward evidence for thresholds",
            "human-reviewed accept/watch/reject label quality",
        ],
        "minimum_evidence_required": [
            "bounded outcome samples by setup and ticker",
            "human-reviewed false-positive and false-negative labels",
            "OOS or walk-forward validation with explicit guardrails",
        ],
        "allowed_next_action": "build human-review labels and evidence sufficiency criteria",
        "forbidden_actions": [
            "change hard gate thresholds",
            "change LLM confidence thresholds",
            "use report as live signal",
            "enable learning-to-execution",
        ],
    },
    {
        "category": "sizing_parameters",
        "inventory_categories": ["position_sizing_risk"],
        "evidence_present": [
            "BTC-USDC tiny scope caps documented",
            "per-ticker product-rule cache records max-notional and quote-cap fields",
        ],
        "evidence_missing": [
            "drawdown and exposure evidence by ticker",
            "non-BTC product-rule evidence",
            "live lifecycle outcome sample size",
        ],
        "minimum_evidence_required": [
            "per-ticker product-rule constraints",
            "bounded risk review with drawdown/exposure evidence",
            "operator-approved maximum scope before any change",
        ],
        "allowed_next_action": "collect sizing evidence labels without changing caps",
        "forbidden_actions": [
            "change default quote size",
            "change max notional",
            "increase open-order caps",
            "derive live size from paper-only evidence",
        ],
    },
    {
        "category": "orderbook_entry_placement_parameters",
        "inventory_categories": ["market_data_features", "d2_position_executor"],
        "evidence_present": [
            "paper C4 lifecycle replay labels",
            "BTC-USDC product-rule evidence",
            "D5 no-fill and cancel/replace evidence",
        ],
        "evidence_missing": [
            "non-BTC increments and min-size evidence",
            "fresh orderbook fill/no-fill samples",
            "maker queue and spread evidence by ticker",
        ],
        "minimum_evidence_required": [
            "product rules for every lifecycle candidate",
            "no-fill duration evidence by placement type",
            "cancel/replace timing evidence with terminal states",
        ],
        "allowed_next_action": "extend paper lifecycle fixtures with placement evidence labels",
        "forbidden_actions": [
            "change maker price offsets",
            "change bid tick offsets",
            "relax spread constraints",
            "alter post-only behavior",
        ],
    },
    {
        "category": "fill_no_fill_parameters",
        "inventory_categories": ["d5_execution_learning", "d4_dynamic_order_management"],
        "evidence_present": [
            "five terminal no-fill events",
            "three cancel/replace timing chains",
            "partial-fill absence documented",
        ],
        "evidence_missing": [
            "larger sample size",
            "ticker-stratified fill/no-fill outcomes",
            "partial-fill cases with fees and terminal status",
        ],
        "minimum_evidence_required": [
            "reviewed sample-size threshold",
            "terminal-state evidence for each candidate chain",
            "separate review of retry-storm and churn guardrails",
        ],
        "allowed_next_action": "prepare human-review no-fill and cancel/replace labels",
        "forbidden_actions": [
            "change timeout windows",
            "change cancel/replace timing",
            "automate partial-fill handling",
            "enable D4 live automation",
        ],
    },
    {
        "category": "exit_parameters",
        "inventory_categories": ["d2_position_executor", "d3_controlled_exit", "d4_dynamic_order_management"],
        "evidence_present": [
            "exit workflow readiness report",
            "D2/D3/D4/D5 hardening evidence",
            "TP_CLOSE fee discrepancy evidence",
        ],
        "evidence_missing": [
            "fresh open position evidence",
            "master live exit readiness",
            "fee discrepancy resolution",
            "follower SELL readiness",
        ],
        "minimum_evidence_required": [
            "fresh D2 plan and candidate fingerprint",
            "zero open D3 exits before any new SELL",
            "fee and no-oversell evidence reviewed by a human",
        ],
        "allowed_next_action": "keep exit evidence in human-review queue",
        "forbidden_actions": [
            "submit live SELL",
            "apply lifecycle fill or terminal closeout",
            "change no-oversell or reservation rules",
            "approve D3/D4 automation",
        ],
    },
    {
        "category": "ticker_scope_parameters",
        "inventory_categories": ["universe_market_selection"],
        "evidence_present": [
            "configured 18-ticker universe",
            "old multi-ticker decision workflow evidence",
            "paper lifecycle replay for every configured ticker",
            "BTC-USDC product-rule evidence",
        ],
        "evidence_missing": [
            "17 non-BTC product-rule evidence rows",
            "non-BTC lifecycle/orderbook parity",
            "all-ticker live ACK and scope review",
        ],
        "minimum_evidence_required": [
            "local product-rule evidence for every candidate ticker",
            "per-ticker lifecycle evidence beyond paper labels",
            "separate all-ticker governance review and exact ACK",
        ],
        "allowed_next_action": "complete non-BTC product-rule/evidence fixtures or keep paper-only",
        "forbidden_actions": [
            "enable all-ticker live",
            "promote non-BTC tickers to live-ready from paper labels",
            "fetch product rules without explicit ACK",
        ],
    },
    {
        "category": "learning_governance_parameters",
        "inventory_categories": ["d5_execution_learning"],
        "evidence_present": [
            "D6 parameter inventory and review scaffolds",
            "safe regression harness governance flags",
            "report-only evidence expansion",
        ],
        "evidence_missing": [
            "minimum evidence sufficiency policy",
            "human-review decision pack",
            "OOS and walk-forward acceptance criteria",
            "separate governance for any learning-to-execution bridge",
        ],
        "minimum_evidence_required": [
            "human-reviewed evidence sufficiency thresholds",
            "sample-size policy by parameter category",
            "explicit approval boundary for future parameter proposals",
        ],
        "allowed_next_action": "build a D6 human-review decision pack with no parameter changes",
        "forbidden_actions": [
            "run optimization",
            "rank parameter values for live use",
            "approve parameter review",
            "enable live learning",
            "connect learning to execution",
        ],
    },
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


def _source_summary(key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    gate = payload.get("gate_decision") if isinstance(payload.get("gate_decision"), dict) else {}
    flags = payload.get("readiness_flags") if isinstance(payload.get("readiness_flags"), dict) else {}
    governance = (
        payload.get("readiness_and_governance_flags")
        if isinstance(payload.get("readiness_and_governance_flags"), dict)
        else {}
    )
    if key == "per_ticker_product_rule_evidence_cache":
        return {
            "classification": payload.get("classification"),
            "ready": gate.get("per_ticker_product_rule_evidence_cache_ready"),
            "all_ticker_product_rule_evidence_ready": gate.get("all_ticker_product_rule_evidence_ready"),
            "tickers_ready_count": gate.get("tickers_ready_count"),
            "tickers_missing_count": gate.get("tickers_missing_count"),
        }
    if key == "multi_ticker_paper_lifecycle_replay":
        return {
            "classification": payload.get("classification"),
            "ready": gate.get("multi_ticker_paper_lifecycle_replay_ready"),
            "tickers_replay_ready_count": gate.get("tickers_replay_ready_count"),
            "tickers_replay_partial_count": gate.get("tickers_replay_partial_count"),
            "all_ticker_lifecycle_parity_ready": gate.get("all_ticker_lifecycle_parity_ready"),
        }
    if key == "d5_d6_evidence_expansion":
        return {
            "classification": payload.get("classification"),
            "human_review_ready": governance.get("human_review_ready"),
            "fee_gap_present": (payload.get("fee_evidence") or {}).get("fee_gap_present")
            if isinstance(payload.get("fee_evidence"), dict)
            else None,
            "parameter_change_allowed": governance.get("parameter_change_allowed"),
            "learning_to_execution_ready": governance.get("learning_to_execution_ready"),
        }
    if key == "main_workflow_parity_report":
        return {
            "ready": gate.get("main_workflow_parity_report_ready"),
            "old_multi_ticker_decision_workflow_seen": gate.get("old_multi_ticker_decision_workflow_seen"),
            "all_ticker_live_allowed_now": gate.get("all_ticker_live_allowed_now"),
        }
    if key == "all_ticker_readiness_gate":
        return {
            "classification": payload.get("classification"),
            "btc_usdc_tiny_scope_ready_for_operator_preflight": flags.get(
                "btc_usdc_tiny_scope_ready_for_operator_preflight"
            ),
            "all_ticker_ready": flags.get("all_ticker_ready"),
            "all_ticker_live_allowed_now": flags.get("all_ticker_live_allowed_now"),
        }
    if key == "exit_workflow_readiness_report":
        return {
            "exit_workflow_readiness_report_ready": payload.get("exit_workflow_readiness_report_ready"),
            "master_live_exit_ready": payload.get("master_live_exit_ready"),
            "follower_sell_ready": payload.get("follower_sell_ready"),
            "learning_to_execution_ready": payload.get("learning_to_execution_ready"),
        }
    if key == "safe_regression_harness":
        selected = payload.get("selected_tests") if isinstance(payload.get("selected_tests"), dict) else {}
        return {
            "classification": payload.get("classification"),
            "local_safe_regression_passed": payload.get("local_safe_regression_passed"),
            "selected_tests_classification": selected.get("selected_tests_classification"),
            "selected_tests_passed_count": selected.get("selected_tests_passed_count"),
        }
    if key == "state_hygiene_cleanup_preview":
        return {
            "status": payload.get("status"),
            "cleanup_preview_count": payload.get("cleanup_preview_count"),
            "state_write_performed": payload.get("state_write_performed"),
            "apply_now": payload.get("apply_now"),
        }
    if key == "coverage_backtest_decision":
        return {
            "status": payload.get("status"),
            "parameter_evidence_created": payload.get("parameter_evidence_created"),
            "optimization_performed": payload.get("optimization_performed"),
            "ranking_performed": payload.get("ranking_performed"),
            "learning_to_execution_enabled": payload.get("learning_to_execution_enabled"),
        }
    return {"status": payload.get("status"), "classification": payload.get("classification")}


def _evidence_sources(root: Path, report_paths: Optional[Dict[str, str | Path]]) -> Dict[str, Any]:
    configured = dict(DEFAULT_EVIDENCE_REPORTS)
    if report_paths:
        configured.update({str(key): str(value) for key, value in report_paths.items()})
    inspected: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    malformed: List[Dict[str, Any]] = []
    loaded: Dict[str, Dict[str, Any]] = {}
    for key, rel in configured.items():
        path = Path(rel)
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            missing.append({"key": key, "path": str(path), "reason": "missing_optional_evidence_source"})
            continue
        payload = _load_json(path)
        if not payload:
            malformed.append({"key": key, "path": str(path), "reason": "malformed_or_empty_json"})
            continue
        loaded[key] = payload
        inspected.append(
            {
                "key": key,
                "path": str(path),
                "phase": payload.get("phase"),
                "classification": payload.get("classification", payload.get("status")),
                "summary": _source_summary(key, payload),
            }
        )
    return {"inspected": inspected, "missing": missing, "malformed": malformed, "loaded": loaded}


def _inventory_summary() -> Dict[str, Any]:
    candidates = build_parameter_candidates()
    counts = {key: 0 for key in CATEGORY_LABELS}
    for item in candidates:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return {
        "candidate_count": len(candidates),
        "category_counts": counts,
        "category_labels": dict(CATEGORY_LABELS),
        "parameter_change_allowed": False,
        "contains_parameter_defaults": False,
        "contains_parameter_recommendations": False,
    }


def _matrix_status(category: str, loaded: Dict[str, Dict[str, Any]], has_any_evidence: bool) -> str:
    if not has_any_evidence:
        return "blocked"
    product_gate = (loaded.get("per_ticker_product_rule_evidence_cache") or {}).get("gate_decision") or {}
    d5_flags = (loaded.get("d5_d6_evidence_expansion") or {}).get("readiness_and_governance_flags") or {}
    if category == "fill_no_fill_parameters" and d5_flags.get("human_review_ready") is True:
        return "human_review_candidate"
    if category == "ticker_scope_parameters" and int(product_gate.get("tickers_missing_count") or 0) > 0:
        return "review_not_ready"
    if category == "learning_governance_parameters":
        return "review_not_ready"
    return "exploratory_only"


def _parameter_evidence_matrix(loaded: Dict[str, Dict[str, Any]], has_any_evidence: bool) -> List[Dict[str, Any]]:
    inventory = _inventory_summary()
    counts = inventory["category_counts"]
    rows: List[Dict[str, Any]] = []
    for spec in PARAMETER_CATEGORIES:
        inventory_categories = list(spec["inventory_categories"])
        rows.append(
            {
                "category": spec["category"],
                "current_status": _matrix_status(spec["category"], loaded, has_any_evidence),
                "inventory_categories": inventory_categories,
                "inventory_candidate_count": sum(int(counts.get(key, 0)) for key in inventory_categories),
                "evidence_present": list(spec["evidence_present"]) if has_any_evidence else [],
                "evidence_missing": list(spec["evidence_missing"]),
                "minimum_evidence_required": list(spec["minimum_evidence_required"]),
                "blocker_list": list(spec["evidence_missing"]),
                "allowed_next_action": spec["allowed_next_action"],
                "forbidden_actions": list(spec["forbidden_actions"]),
                "parameter_review_approved": False,
                "parameter_change_allowed": False,
                "learning_to_execution_ready": False,
                "contains_live_parameter_values": False,
                "contains_parameter_proposal": False,
            }
        )
    return rows


def _evidence_gaps(loaded: Dict[str, Dict[str, Any]]) -> List[str]:
    gaps = [
        "minimum_sample_size_policy_missing",
        "OOS_walk_forward_acceptance_criteria_missing",
        "human_review_decision_pack_missing",
    ]
    product_gate = (loaded.get("per_ticker_product_rule_evidence_cache") or {}).get("gate_decision") or {}
    if int(product_gate.get("tickers_missing_count") or 0) > 0:
        gaps.append("non_btc_product_rule_evidence_missing")
    replay_gate = (loaded.get("multi_ticker_paper_lifecycle_replay") or {}).get("gate_decision") or {}
    if int(replay_gate.get("tickers_replay_partial_count") or 0) > 0:
        gaps.append("paper_lifecycle_replay_partial_for_configured_tickers")
    all_gate_flags = (loaded.get("all_ticker_readiness_gate") or {}).get("readiness_flags") or {}
    if all_gate_flags.get("all_ticker_ready") is not True:
        gaps.append("all_ticker_readiness_not_proven")
    exit_report = loaded.get("exit_workflow_readiness_report") or {}
    if exit_report.get("master_live_exit_ready") is not True:
        gaps.append("master_live_exit_ready_false")
    d5_fee = (loaded.get("d5_d6_evidence_expansion") or {}).get("fee_evidence") or {}
    if d5_fee.get("fee_gap_present") in {True, "true", "unknown"}:
        gaps.append("tp_close_fee_gap_requires_human_review")
    hygiene = loaded.get("state_hygiene_cleanup_preview") or {}
    if hygiene.get("status") == "WATCH":
        gaps.append("state_hygiene_cleanup_preview_watch")
    return sorted(set(gaps))


def build_d6_backlearning_parameter_evidence_plan_report(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    report_paths: Optional[Dict[str, str | Path]] = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    sources = _evidence_sources(project_root, report_paths)
    loaded = sources["loaded"]
    inspected = sources["inspected"]
    stop_items = [
        f"{key}_stop_now"
        for key, payload in loaded.items()
        if payload.get("classification") == "STOP_NOW" or payload.get("status") == "STOP_NOW"
    ]
    gaps = _evidence_gaps(loaded)
    watch_items = sorted(
        set(
            gaps
            + [f"missing_optional_source:{item['key']}" for item in sources["missing"]]
            + [f"malformed_source:{item['key']}" for item in sources["malformed"]]
        )
    )
    has_any_evidence = bool(inspected)
    matrix = _parameter_evidence_matrix(loaded, has_any_evidence)
    human_review_ready = has_any_evidence and not stop_items
    parameter_review_candidate = False
    plan_ready = has_any_evidence and not stop_items
    if stop_items:
        classification = "STOP_NOW"
        quality = "unsafe_contradiction_requires_stop"
    elif has_any_evidence:
        classification = "WATCH"
        quality = "partial_useful_for_human_review_not_parameter_review_ready"
    else:
        classification = "WATCH"
        quality = "insufficient_or_malformed_local_evidence"

    governance_flags = {
        "d6_backlearning_parameter_evidence_plan_ready": plan_ready,
        "human_review_ready": human_review_ready,
        "parameter_review_candidate": parameter_review_candidate,
        "parameter_review_approved": False,
        "parameter_change_allowed": False,
        "learning_to_execution_ready": False,
        "live_learning_allowed": False,
    }
    return _json_safe(
        {
            "phase": PHASE_D6_BACKLEARNING_PARAMETER_EVIDENCE_PLAN,
            "generated_at": generated_at or _now_iso(),
            "metadata": {
                "report_only": True,
                "human_review_only": True,
                "backlearning_only": True,
                "optimization_performed": False,
                "ranking_performed": False,
                "parameter_mutation_performed": False,
                "learning_to_execution_performed": False,
                "coinbase_call_attempted": False,
                "market_data_fetch_attempted": False,
                "http_call_attempted": False,
                "state_write_performed": False,
            },
            "classification": classification,
            "evidence_summary": {
                "evidence_sources_inspected": inspected,
                "evidence_sources_missing": sources["missing"],
                "evidence_sources_malformed": sources["malformed"],
                "evidence_quality_classification": quality,
                "watch_items": watch_items,
                "stop_items": stop_items,
                "evidence_gaps": gaps,
            },
            "parameter_inventory_summary": _inventory_summary(),
            "parameter_evidence_matrix": matrix,
            "backlearning_plan": {
                "what_backlearning_can_calculate_later": [
                    "evidence coverage and sufficiency labels by parameter category",
                    "human-reviewed outcome buckets for fill/no-fill/cancel-replace behavior",
                    "per-ticker readiness constraints once local product-rule evidence exists",
                    "sample-size and OOS readiness status for future review packs",
                ],
                "what_it_cannot_calculate_yet": [
                    "approved parameter values",
                    "live strategy rankings",
                    "all-ticker lifecycle parity",
                    "learning-to-execution bridge decisions",
                ],
                "required_sample_or_threshold_policy": [
                    "minimum sample size must be defined by category before parameter review",
                    "OOS or walk-forward acceptance criteria must be documented before proposals",
                    "human review must approve evidence sufficiency before any parameter proposal task",
                ],
                "must_remain_human_reviewed": [
                    "entry gates",
                    "position sizing",
                    "D2/D3/D4 exit behavior",
                    "all-ticker scope",
                    "learning governance",
                ],
                "must_remain_frozen": [
                    "runtime configuration",
                    "risk and sizing limits",
                    "LLM/judge thresholds",
                    "exit automation flags",
                    "replication and follower live flags",
                ],
                "future_reports_should_produce": [
                    "D6 human-review decision pack",
                    "targeted product-rule fixture completion report for non-BTC tickers",
                    "sample-size and OOS sufficiency report",
                    "fee discrepancy resolution evidence report",
                ],
            },
            "governance_flags": governance_flags,
            "safety_boundaries": [
                "evidence plan does not authorize live trading",
                "evidence plan does not authorize parameter changes",
                "evidence plan does not authorize all-ticker live",
                "evidence plan does not authorize learning-to-execution",
                "future parameter review requires separate exact ACK",
                "future live learning requires separate governance and ACK",
            ],
            "prohibited_interpretations": [
                "do_not_infer_parameter_change",
                "do_not_rank_parameter_values",
                "do_not_use_as_live_signal",
                "do_not_approve_learning_to_execution",
                "do_not_enable_live_learning",
            ],
            "recommended_next_sprint": {
                "route": "D6 human-review decision pack",
                "why": (
                    "The plan now defines evidence gaps and frozen parameter categories; the next safe step is a "
                    "human-review decision artifact that classifies evidence sufficiency without proposing values."
                ),
            },
        }
    )


def render_d6_backlearning_parameter_evidence_plan_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    summary = report.get("evidence_summary") or {}
    flags = report.get("governance_flags") or {}
    lines = [
        "# D6 Backlearning Parameter Evidence Plan",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- human_review_only: `{meta.get('human_review_only')}`",
        f"- backlearning_only: `{meta.get('backlearning_only')}`",
        f"- optimization_performed: `{meta.get('optimization_performed')}`",
        f"- ranking_performed: `{meta.get('ranking_performed')}`",
        f"- parameter_mutation_performed: `{meta.get('parameter_mutation_performed')}`",
        f"- learning_to_execution_performed: `{meta.get('learning_to_execution_performed')}`",
        f"- coinbase_call_attempted: `{meta.get('coinbase_call_attempted')}`",
        f"- market_data_fetch_attempted: `{meta.get('market_data_fetch_attempted')}`",
        f"- http_call_attempted: `{meta.get('http_call_attempted')}`",
        f"- state_write_performed: `{meta.get('state_write_performed')}`",
        "",
        "## Governance Flags",
        "",
    ]
    for key, value in flags.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Evidence Summary",
            "",
            f"- evidence_quality_classification: `{summary.get('evidence_quality_classification')}`",
            f"- sources_inspected_count: `{len(summary.get('evidence_sources_inspected') or [])}`",
            f"- sources_missing_count: `{len(summary.get('evidence_sources_missing') or [])}`",
            f"- sources_malformed_count: `{len(summary.get('evidence_sources_malformed') or [])}`",
            f"- watch_items: `{'; '.join(summary.get('watch_items') or [])}`",
            f"- stop_items: `{'; '.join(summary.get('stop_items') or [])}`",
            "",
            "## Parameter Evidence Matrix",
            "",
        ]
    )
    for row in report.get("parameter_evidence_matrix") or []:
        lines.append(
            f"- {row.get('category')}: status=`{row.get('current_status')}`, "
            f"inventory_candidates=`{row.get('inventory_candidate_count')}`, "
            f"allowed_next_action=`{row.get('allowed_next_action')}`"
        )
    lines.extend(["", "## Safety Boundaries", ""])
    for item in report.get("safety_boundaries") or []:
        lines.append(f"- {item}")
    next_sprint = report.get("recommended_next_sprint") or {}
    lines.extend(
        [
            "",
            "## Recommended Next Sprint",
            "",
            f"- route: `{next_sprint.get('route')}`",
            f"- why: {next_sprint.get('why')}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_D6_BACKLEARNING_PARAMETER_EVIDENCE_PLAN",
    "build_d6_backlearning_parameter_evidence_plan_report",
    "render_d6_backlearning_parameter_evidence_plan_markdown",
]
