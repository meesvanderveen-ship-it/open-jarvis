from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.phase_d6_backlearning_parameter_evidence_plan import DEFAULT_EVIDENCE_REPORTS


PHASE_D6_HUMAN_REVIEW_DECISION_PACK = "d6_human_review_decision_pack_v1"
DECISION_STATUSES = {
    "accepted_for_human_review",
    "labels_only",
    "insufficient_evidence",
    "blocked",
    "requires_more_local_evidence",
    "out_of_scope_until_ACK",
}
REVIEW_SEVERITIES = {"info", "watch", "blocked", "stop"}
DEFAULT_DECISION_REPORTS = {
    "d6_backlearning_parameter_evidence_plan": "reports/d6/d6-backlearning-parameter-evidence-plan-20260609.json",
    **DEFAULT_EVIDENCE_REPORTS,
    "follower_receiver_api_audit": "reports/d6/follower-receiver-api-audit-20260609.json",
}


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
    governance = payload.get("governance_flags") if isinstance(payload.get("governance_flags"), dict) else {}
    d5_flags = (
        payload.get("readiness_and_governance_flags")
        if isinstance(payload.get("readiness_and_governance_flags"), dict)
        else {}
    )
    summary = {
        "phase": payload.get("phase"),
        "classification": payload.get("classification", payload.get("status")),
        "status": payload.get("status"),
    }
    if key == "d6_backlearning_parameter_evidence_plan":
        summary.update(
            {
                "plan_ready": governance.get("d6_backlearning_parameter_evidence_plan_ready"),
                "human_review_ready": governance.get("human_review_ready"),
                "parameter_review_candidate": governance.get("parameter_review_candidate"),
                "parameter_change_allowed": governance.get("parameter_change_allowed"),
                "learning_to_execution_ready": governance.get("learning_to_execution_ready"),
            }
        )
    elif key == "d5_d6_evidence_expansion":
        summary.update(
            {
                "human_review_ready": d5_flags.get("human_review_ready"),
                "fee_gap_present": (payload.get("fee_evidence") or {}).get("fee_gap_present")
                if isinstance(payload.get("fee_evidence"), dict)
                else None,
                "parameter_change_allowed": d5_flags.get("parameter_change_allowed"),
            }
        )
    elif key == "per_ticker_product_rule_evidence_cache":
        summary.update(
            {
                "cache_ready": gate.get("per_ticker_product_rule_evidence_cache_ready"),
                "all_ticker_product_rule_evidence_ready": gate.get("all_ticker_product_rule_evidence_ready"),
                "tickers_ready_count": gate.get("tickers_ready_count"),
                "tickers_missing_count": gate.get("tickers_missing_count"),
            }
        )
    elif key == "multi_ticker_paper_lifecycle_replay":
        summary.update(
            {
                "replay_ready": gate.get("multi_ticker_paper_lifecycle_replay_ready"),
                "tickers_replay_partial_count": gate.get("tickers_replay_partial_count"),
                "all_ticker_lifecycle_parity_ready": gate.get("all_ticker_lifecycle_parity_ready"),
            }
        )
    elif key == "all_ticker_readiness_gate":
        summary.update(
            {
                "btc_usdc_tiny_scope_ready_for_operator_preflight": flags.get(
                    "btc_usdc_tiny_scope_ready_for_operator_preflight"
                ),
                "all_ticker_ready": flags.get("all_ticker_ready"),
                "all_ticker_live_allowed_now": flags.get("all_ticker_live_allowed_now"),
            }
        )
    elif key == "exit_workflow_readiness_report":
        summary.update(
            {
                "exit_workflow_readiness_report_ready": payload.get("exit_workflow_readiness_report_ready"),
                "master_live_exit_ready": payload.get("master_live_exit_ready"),
                "follower_sell_ready": payload.get("follower_sell_ready"),
            }
        )
    elif key == "state_hygiene_cleanup_preview":
        summary.update(
            {
                "cleanup_preview_count": payload.get("cleanup_preview_count"),
                "apply_now": payload.get("apply_now"),
                "state_write_performed": payload.get("state_write_performed"),
            }
        )
    elif key == "follower_receiver_api_audit":
        summary.update(
            {
                "follower_receiver_code_accessible": flags.get("follower_receiver_code_accessible"),
                "follower_buy_ready": flags.get("follower_buy_ready"),
                "follower_sell_ready": flags.get("follower_sell_ready"),
                "follower_ready_for_live": flags.get("follower_ready_for_live"),
            }
        )
    return summary


def _load_sources(root: Path, report_paths: Optional[Dict[str, str | Path]]) -> Dict[str, Any]:
    configured = dict(DEFAULT_DECISION_REPORTS)
    if report_paths:
        configured.update({str(k): str(v) for k, v in report_paths.items()})
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
        inspected.append({"key": key, "path": str(path), "summary": _source_summary(key, payload)})
    return {"loaded": loaded, "inspected": inspected, "missing": missing, "malformed": malformed}


def _plan_matrix_by_category(plan: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows = plan.get("parameter_evidence_matrix")
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("category"):
                out[str(row["category"])] = row
    return out


def _decision_row(
    *,
    area: str,
    decision_status: str,
    rationale: str,
    evidence_support: List[str],
    evidence_gaps: List[str],
    blockers: List[str],
    allowed_next_action: str,
    forbidden_actions: List[str],
    review_severity: str,
    blocks_btc_usdc_24h_test: bool,
    blocks_full_workflow: bool,
    blocks_parameter_review: bool,
    blocks_learning_to_execution: bool,
    human_review_notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if decision_status not in DECISION_STATUSES:
        raise ValueError(f"unsupported_decision_status:{decision_status}")
    if review_severity not in REVIEW_SEVERITIES:
        raise ValueError(f"unsupported_review_severity:{review_severity}")
    return {
        "area": area,
        "decision_status": decision_status,
        "rationale": rationale,
        "evidence_present": list(evidence_support),
        "evidence_support": list(evidence_support),
        "evidence_missing": list(evidence_gaps),
        "evidence_gaps": list(evidence_gaps),
        "blockers": list(blockers),
        "human_review_notes": list(human_review_notes or []),
        "allowed_next_action": allowed_next_action,
        "forbidden_actions": list(forbidden_actions),
        "blocks_btc_usdc_24h_test": blocks_btc_usdc_24h_test,
        "blocks_full_workflow": blocks_full_workflow,
        "blocks_parameter_review": blocks_parameter_review,
        "blocks_learning_to_execution": blocks_learning_to_execution,
        "review_severity": review_severity,
        "parameter_values_proposed": False,
        "parameter_review_approved": False,
        "parameter_change_allowed": False,
        "learning_to_execution_ready": False,
    }


def _decision_matrix(loaded: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    plan = loaded.get("d6_backlearning_parameter_evidence_plan") or {}
    plan_rows = _plan_matrix_by_category(plan)
    product_gate = (loaded.get("per_ticker_product_rule_evidence_cache") or {}).get("gate_decision") or {}
    replay_gate = (loaded.get("multi_ticker_paper_lifecycle_replay") or {}).get("gate_decision") or {}
    all_ticker_flags = (loaded.get("all_ticker_readiness_gate") or {}).get("readiness_flags") or {}
    follower_flags = (loaded.get("follower_receiver_api_audit") or {}).get("readiness_flags") or {}
    hygiene = loaded.get("state_hygiene_cleanup_preview") or {}
    fee = (loaded.get("d5_d6_evidence_expansion") or {}).get("fee_evidence") or {}

    def plan_support(category: str) -> List[str]:
        return list((plan_rows.get(category) or {}).get("evidence_present") or [])

    def plan_gaps(category: str) -> List[str]:
        return list((plan_rows.get(category) or {}).get("evidence_missing") or [])

    rows = [
        _decision_row(
            area="entry_gating_evidence",
            decision_status="requires_more_local_evidence",
            rationale="Old multi-ticker decision evidence exists, but lifecycle outcomes and OOS criteria are incomplete.",
            evidence_support=plan_support("entry_gating_parameters"),
            evidence_gaps=plan_gaps("entry_gating_parameters"),
            blockers=["minimum_sample_size_policy_missing", "OOS_walk_forward_acceptance_criteria_missing"],
            allowed_next_action="define human-review acceptance criteria and collect labels",
            forbidden_actions=["change gate thresholds", "change LLM thresholds", "use as live signal"],
            review_severity="watch",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=True,
            blocks_parameter_review=True,
            blocks_learning_to_execution=True,
        ),
        _decision_row(
            area="sizing_evidence",
            decision_status="insufficient_evidence",
            rationale="Tiny BTC scope caps are documented, but all-ticker product-rule and outcome evidence are incomplete.",
            evidence_support=plan_support("sizing_parameters"),
            evidence_gaps=plan_gaps("sizing_parameters"),
            blockers=["non_btc_product_rule_evidence_missing", "drawdown_exposure_evidence_missing"],
            allowed_next_action="collect sizing evidence labels without changing caps",
            forbidden_actions=["change default quote size", "change max notional", "increase order caps"],
            review_severity="watch",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=True,
            blocks_parameter_review=True,
            blocks_learning_to_execution=True,
        ),
        _decision_row(
            area="orderbook_entry_placement_evidence",
            decision_status="requires_more_local_evidence",
            rationale="Paper C4 labels and no-fill evidence are useful, but non-BTC increments and placement samples are missing.",
            evidence_support=plan_support("orderbook_entry_placement_parameters"),
            evidence_gaps=plan_gaps("orderbook_entry_placement_parameters"),
            blockers=["non_btc_increment_evidence_missing", "fresh_orderbook_sample_missing"],
            allowed_next_action="extend paper fixtures with placement evidence labels",
            forbidden_actions=["change maker offsets", "change bid ticks", "relax spread constraints"],
            review_severity="watch",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=True,
            blocks_parameter_review=True,
            blocks_learning_to_execution=True,
        ),
        _decision_row(
            area="fill_no_fill_evidence",
            decision_status="labels_only",
            rationale="No-fill and cancel/replace timing evidence can be reviewed as labels only, not as parameter approval.",
            evidence_support=plan_support("fill_no_fill_parameters"),
            evidence_gaps=plan_gaps("fill_no_fill_parameters"),
            blockers=["larger_sample_size_missing"],
            allowed_next_action="prepare human-review no-fill and cancel/replace labels",
            forbidden_actions=["change timeout windows", "change cancel/replace timing", "enable D4 live automation"],
            review_severity="info",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=False,
            blocks_parameter_review=True,
            blocks_learning_to_execution=True,
            human_review_notes=["safe_for_labels_only_without_parameter_change"],
        ),
        _decision_row(
            area="exit_evidence",
            decision_status="requires_more_local_evidence",
            rationale="Exit readiness is documented, but master live exit and follower SELL remain false.",
            evidence_support=plan_support("exit_parameters"),
            evidence_gaps=plan_gaps("exit_parameters"),
            blockers=["master_live_exit_ready_false", "follower_sell_ready_false"],
            allowed_next_action="keep exit evidence in human-review queue",
            forbidden_actions=["submit live SELL", "apply lifecycle fill", "change reservation rules"],
            review_severity="watch",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=True,
            blocks_parameter_review=True,
            blocks_learning_to_execution=True,
        ),
        _decision_row(
            area="ticker_scope_evidence",
            decision_status="requires_more_local_evidence",
            rationale="The configured universe and old decision flow are known, but non-BTC lifecycle parity is not proven.",
            evidence_support=plan_support("ticker_scope_parameters"),
            evidence_gaps=plan_gaps("ticker_scope_parameters"),
            blockers=["all_ticker_lifecycle_parity_ready_false"],
            allowed_next_action="complete non-BTC product-rule evidence or keep paper-only",
            forbidden_actions=["enable all-ticker live", "promote non-BTC from paper labels to live-ready"],
            review_severity="watch",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=True,
            blocks_parameter_review=True,
            blocks_learning_to_execution=True,
        ),
        _decision_row(
            area="product_rule_evidence",
            decision_status="requires_more_local_evidence"
            if int(product_gate.get("tickers_missing_count") or 0) > 0
            else "accepted_for_human_review",
            rationale="BTC-USDC product-rule evidence is local-ready; 17 non-BTC tickers still lack strong local evidence.",
            evidence_support=[
                f"tickers_ready_count={product_gate.get('tickers_ready_count')}",
                f"tickers_missing_count={product_gate.get('tickers_missing_count')}",
            ],
            evidence_gaps=["local product-rule/min-size/increment evidence for 17 non-BTC tickers"],
            blockers=["non_btc_product_rule_evidence_missing"] if int(product_gate.get("tickers_missing_count") or 0) else [],
            allowed_next_action="targeted local product-rule fixture/evidence completion",
            forbidden_actions=["fetch Coinbase product rules without ACK", "authorize all-ticker live"],
            review_severity="watch",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=True,
            blocks_parameter_review=True,
            blocks_learning_to_execution=True,
        ),
        _decision_row(
            area="all_ticker_lifecycle_parity_evidence",
            decision_status="blocked" if all_ticker_flags.get("all_ticker_ready") is not True else "accepted_for_human_review",
            rationale="All-ticker readiness remains false and every ticker is still not proven through the full lifecycle.",
            evidence_support=[
                f"paper_replay_ready={replay_gate.get('multi_ticker_paper_lifecycle_replay_ready')}",
                f"tickers_replay_partial_count={replay_gate.get('tickers_replay_partial_count')}",
            ],
            evidence_gaps=["per-ticker lifecycle/orderbook parity evidence"],
            blockers=["all_ticker_ready_false", "all_ticker_live_allowed_now_false"],
            allowed_next_action="continue paper/local evidence expansion",
            forbidden_actions=["enable all-ticker live", "treat paper replay as live parity"],
            review_severity="blocked",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=True,
            blocks_parameter_review=True,
            blocks_learning_to_execution=True,
        ),
        _decision_row(
            area="fee_discrepancy_evidence",
            decision_status="accepted_for_human_review" if fee.get("fee_gap_present") is True else "labels_only",
            rationale="TP_CLOSE fee discrepancy is documented and suitable for human review, not repair or parameter action.",
            evidence_support=[f"fee_gap_present={fee.get('fee_gap_present')}"],
            evidence_gaps=["fee discrepancy resolution and reconciliation policy"],
            blockers=["tp_close_fee_gap_requires_human_review"] if fee.get("fee_gap_present") is True else [],
            allowed_next_action="human-review fee discrepancy evidence",
            forbidden_actions=["rewrite historical fees", "mutate state", "change fee model"],
            review_severity="watch" if fee.get("fee_gap_present") is True else "info",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=False,
            blocks_parameter_review=True,
            blocks_learning_to_execution=True,
        ),
        _decision_row(
            area="state_hygiene_evidence",
            decision_status="labels_only" if hygiene.get("status") == "WATCH" else "accepted_for_human_review",
            rationale="Stale reservation cleanup is previewed only; apply remains ACK-gated and not required unless STOP_NOW appears.",
            evidence_support=[
                f"status={hygiene.get('status')}",
                f"cleanup_preview_count={hygiene.get('cleanup_preview_count')}",
                f"apply_now={hygiene.get('apply_now')}",
            ],
            evidence_gaps=["actual cleanup apply requires exact ACK and fresh hashes"],
            blockers=["state_hygiene_apply_ack_missing"],
            allowed_next_action="preserve preview and require ACK for any apply",
            forbidden_actions=["apply cleanup", "edit state manually", "repair historical state"],
            review_severity="watch" if hygiene.get("status") == "WATCH" else "info",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=False,
            blocks_parameter_review=False,
            blocks_learning_to_execution=True,
        ),
        _decision_row(
            area="replication_follower_evidence",
            decision_status="blocked",
            rationale="Follower receiver/API code is not accessible locally and follower BUY/SELL/live remain false.",
            evidence_support=[
                f"follower_receiver_code_accessible={follower_flags.get('follower_receiver_code_accessible')}",
                f"follower_buy_ready={follower_flags.get('follower_buy_ready')}",
                f"follower_sell_ready={follower_flags.get('follower_sell_ready')}",
            ],
            evidence_gaps=["receiver/API endpoint/auth/idempotency/no-oversell audit"],
            blockers=["follower_receiver_code_inaccessible", "follower_ready_for_live_false"],
            allowed_next_action="provide follower repo/path for static audit",
            forbidden_actions=["send HTTP to follower", "enable replication", "enable follower live"],
            review_severity="blocked",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=True,
            blocks_parameter_review=False,
            blocks_learning_to_execution=True,
        ),
        _decision_row(
            area="learning_governance_evidence",
            decision_status="out_of_scope_until_ACK",
            rationale="Learning governance can be reviewed, but live learning and learning-to-execution remain explicitly closed.",
            evidence_support=plan_support("learning_governance_parameters"),
            evidence_gaps=plan_gaps("learning_governance_parameters"),
            blockers=["parameter_review_candidate_false", "learning_to_execution_ready_false", "live_learning_allowed_false"],
            allowed_next_action="define sample-size/OOS/walk-forward acceptance policy",
            forbidden_actions=["run optimization", "rank parameter values", "approve parameter changes", "enable live learning"],
            review_severity="blocked",
            blocks_btc_usdc_24h_test=False,
            blocks_full_workflow=True,
            blocks_parameter_review=True,
            blocks_learning_to_execution=True,
        ),
    ]
    return rows


def _quality_overview(rows: List[Dict[str, Any]]) -> str:
    if any(row["review_severity"] == "stop" for row in rows):
        return "stop_required"
    if any(row["review_severity"] == "blocked" for row in rows):
        return "useful_but_incomplete_with_blocked_areas"
    return "complete_for_human_review_only"


def build_d6_human_review_decision_pack_report(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    report_paths: Optional[Dict[str, str | Path]] = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    sources = _load_sources(project_root, report_paths)
    loaded = sources["loaded"]
    rows = _decision_matrix(loaded)
    stop_items = [
        f"{key}_stop_now"
        for key, payload in loaded.items()
        if payload.get("classification") == "STOP_NOW" or payload.get("status") == "STOP_NOW"
    ]
    known_gaps = sorted(
        set(
            gap
            for row in rows
            for gap in list(row.get("evidence_gaps") or []) + list(row.get("blockers") or [])
        )
    )
    watch_items = sorted(
        set(
            [
                row["area"]
                for row in rows
                if row["review_severity"] in {"watch", "blocked"} or row["decision_status"] != "accepted_for_human_review"
            ]
            + [f"missing_optional_source:{item['key']}" for item in sources["missing"]]
            + [f"malformed_source:{item['key']}" for item in sources["malformed"]]
        )
    )
    if stop_items:
        classification = "STOP_NOW"
    elif watch_items:
        classification = "WATCH"
    else:
        classification = "OK"

    decision_counts: Dict[str, int] = {key: 0 for key in sorted(DECISION_STATUSES)}
    severity_counts: Dict[str, int] = {key: 0 for key in sorted(REVIEW_SEVERITIES)}
    for row in rows:
        decision_counts[row["decision_status"]] += 1
        severity_counts[row["review_severity"]] += 1

    governance_flags = {
        "d6_human_review_decision_pack_ready": bool(rows) and classification != "STOP_NOW",
        "human_review_ready": bool(rows) and classification in {"OK", "WATCH"},
        "parameter_review_candidate": False,
        "parameter_values_proposed": False,
        "parameter_review_approved": False,
        "parameter_change_allowed": False,
        "learning_to_execution_ready": False,
        "live_learning_allowed": False,
    }
    return _json_safe(
        {
            "phase": PHASE_D6_HUMAN_REVIEW_DECISION_PACK,
            "generated_at": generated_at or _now_iso(),
            "metadata": {
                "report_only": True,
                "human_review_only": True,
                "decision_pack_only": True,
                "optimization_performed": False,
                "ranking_performed": False,
                "parameter_values_proposed": False,
                "parameter_mutation_performed": False,
                "parameter_review_approved": False,
                "parameter_change_allowed": False,
                "learning_to_execution_performed": False,
                "learning_to_execution_ready": False,
                "live_learning_allowed": False,
                "coinbase_call_attempted": False,
                "market_data_fetch_attempted": False,
                "http_call_attempted": False,
                "state_write_performed": False,
            },
            "classification": classification,
            "human_review_decision_pack_ready": governance_flags["d6_human_review_decision_pack_ready"],
            "evidence_source_summary": {
                "evidence_sources_inspected": sources["inspected"],
                "evidence_sources_missing": sources["missing"],
                "evidence_sources_malformed": sources["malformed"],
                "evidence_quality_overview": _quality_overview(rows),
                "watch_items": watch_items,
                "stop_items": stop_items,
                "known_gaps": known_gaps,
            },
            "decision_matrix": rows,
            "decision_status_counts": decision_counts,
            "review_severity_counts": severity_counts,
            "parameter_review_readiness": {
                "parameter_review_candidate": False,
                "parameter_review_approved": False,
                "parameter_change_allowed": False,
                "parameter_values_proposed": False,
                "ranking_performed": False,
                "optimization_performed": False,
                "why_not_candidate": [
                    "non-BTC product-rule evidence missing",
                    "all-ticker lifecycle parity false",
                    "sample-size and OOS/walk-forward criteria missing",
                    "learning governance remains ACK-gated",
                ],
            },
            "learning_governance": {
                "learning_to_execution_ready": False,
                "live_learning_allowed": False,
                "live_learning_blockers": [
                    "parameter_review_candidate=false",
                    "parameter_review_approved=false",
                    "parameter_change_allowed=false",
                    "all_ticker_lifecycle_parity_ready=false",
                ],
                "governance_requirements_before_any_future_learning_to_execution": [
                    "human-review acceptance criteria",
                    "sample-size policy",
                    "OOS/walk-forward acceptance policy",
                    "separate parameter proposal task",
                    "separate exact ACK for any bridge to execution",
                ],
            },
            "recommended_next_actions": [
                "targeted local product-rule fixture/evidence completion for 17 non-BTC tickers",
                "sample-size/OOS/walk-forward acceptance policy",
                "D6 human-review acceptance criteria",
                "fresh BTC-USDC live-start decision pack only if operator explicitly asks",
                "controlled learning-governance design with no execution bridge",
            ],
            "governance_flags": governance_flags,
            "safety_boundaries": [
                "human-review decision pack does not authorize live trading",
                "human-review decision pack does not propose parameter values",
                "human-review decision pack does not authorize parameter changes",
                "human-review decision pack does not authorize learning-to-execution",
                "future parameter proposal requires a separate task and exact ACK",
                "future live learning requires separate governance and exact ACK",
            ],
        }
    )


def render_d6_human_review_decision_pack_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    flags = report.get("governance_flags") or {}
    source = report.get("evidence_source_summary") or {}
    lines = [
        "# D6 Human-Review Decision Pack",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- human_review_only: `{meta.get('human_review_only')}`",
        f"- decision_pack_only: `{meta.get('decision_pack_only')}`",
        f"- optimization_performed: `{meta.get('optimization_performed')}`",
        f"- ranking_performed: `{meta.get('ranking_performed')}`",
        f"- parameter_values_proposed: `{meta.get('parameter_values_proposed')}`",
        f"- parameter_mutation_performed: `{meta.get('parameter_mutation_performed')}`",
        f"- learning_to_execution_ready: `{meta.get('learning_to_execution_ready')}`",
        f"- live_learning_allowed: `{meta.get('live_learning_allowed')}`",
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
            "## Evidence Source Summary",
            "",
            f"- evidence_quality_overview: `{source.get('evidence_quality_overview')}`",
            f"- sources_inspected_count: `{len(source.get('evidence_sources_inspected') or [])}`",
            f"- sources_missing_count: `{len(source.get('evidence_sources_missing') or [])}`",
            f"- sources_malformed_count: `{len(source.get('evidence_sources_malformed') or [])}`",
            f"- watch_items: `{'; '.join(source.get('watch_items') or [])}`",
            f"- stop_items: `{'; '.join(source.get('stop_items') or [])}`",
            "",
            "## Decision Matrix",
            "",
        ]
    )
    for row in report.get("decision_matrix") or []:
        lines.append(
            f"- {row.get('area')}: status=`{row.get('decision_status')}`, "
            f"severity=`{row.get('review_severity')}`, "
            f"blocks_full_workflow=`{row.get('blocks_full_workflow')}`, "
            f"allowed_next_action=`{row.get('allowed_next_action')}`"
        )
    readiness = report.get("parameter_review_readiness") or {}
    lines.extend(
        [
            "",
            "## Parameter Review Readiness",
            "",
            f"- parameter_review_candidate: `{readiness.get('parameter_review_candidate')}`",
            f"- parameter_review_approved: `{readiness.get('parameter_review_approved')}`",
            f"- parameter_change_allowed: `{readiness.get('parameter_change_allowed')}`",
            f"- parameter_values_proposed: `{readiness.get('parameter_values_proposed')}`",
            f"- ranking_performed: `{readiness.get('ranking_performed')}`",
            f"- optimization_performed: `{readiness.get('optimization_performed')}`",
            "",
            "## Recommended Next Actions",
            "",
        ]
    )
    for item in report.get("recommended_next_actions") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Safety Boundaries", ""])
    for item in report.get("safety_boundaries") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "DECISION_STATUSES",
    "PHASE_D6_HUMAN_REVIEW_DECISION_PACK",
    "build_d6_human_review_decision_pack_report",
    "render_d6_human_review_decision_pack_markdown",
]
