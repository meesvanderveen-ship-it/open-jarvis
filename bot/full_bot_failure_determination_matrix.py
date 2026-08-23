from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.full_bot_orchestrator import normalize_ticker, sha256_file


FULL_BOT_FAILURE_DETERMINATION_PHASE = "full_bot_failure_determination_matrix_v1"

CONFIGURED_USDC_TICKERS: List[str] = [
    "BTC-USDC",
    "ETH-USDC",
    "SOL-USDC",
    "XRP-USDC",
    "ADA-USDC",
    "LINK-USDC",
    "AVAX-USDC",
    "DOGE-USDC",
    "SUI-USDC",
    "LTC-USDC",
    "HBAR-USDC",
    "ATOM-USDC",
    "NEAR-USDC",
    "APT-USDC",
    "INJ-USDC",
    "ARB-USDC",
    "OP-USDC",
    "UNI-USDC",
]

ROOT_CAUSE_CATEGORIES = {
    "phase_c_ready",
    "needs_fresh_judge_review",
    "needs_deterministic_live_risk",
    "stale_candidate_needs_refresh",
    "adapter_selection_cap",
    "soft_near_miss_threshold",
    "missing_market_or_orderbook_data",
    "missing_target_or_invalidation",
    "product_or_min_notional_blocker",
    "reservation_or_open_order_cap",
    "hard_strategy_reject",
    "true_safety_blocker",
    "not_selected_low_priority",
    "no_candidate_seen",
    "code_mapping_or_contract_gap",
    "insufficient_context_unknown",
}

PRIORITY_BY_CATEGORY = {
    "code_mapping_or_contract_gap": "P0",
    "true_safety_blocker": "P0",
    "phase_c_ready": "P1",
    "needs_fresh_judge_review": "P1",
    "needs_deterministic_live_risk": "P1",
    "stale_candidate_needs_refresh": "P1",
    "adapter_selection_cap": "P1",
    "missing_target_or_invalidation": "P1",
    "missing_market_or_orderbook_data": "P1",
    "soft_near_miss_threshold": "P2",
    "product_or_min_notional_blocker": "P2",
    "reservation_or_open_order_cap": "P3",
    "hard_strategy_reject": "P3",
    "not_selected_low_priority": "P3",
    "no_candidate_seen": "P4",
    "insufficient_context_unknown": "P4",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    return value


def load_json_file(path: str | Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_latest_report(root: str | Path, pattern: str) -> Tuple[Dict[str, Any], Optional[Path]]:
    base = Path(root) / "reports" / "d6"
    for path in sorted(base.glob(pattern), reverse=True):
        payload = load_json_file(path)
        if payload:
            return payload, path
    return {}, None


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _ticker_map(rows: Iterable[Any], *, nested_intent: bool = False) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        intent = _intent(raw) if nested_intent else raw
        ticker = normalize_ticker(raw.get("ticker") or intent.get("ticker"))
        if ticker:
            out[ticker] = dict(raw)
    return out


def _intent(row: Dict[str, Any]) -> Dict[str, Any]:
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    source = row.get("source_action") if isinstance(row.get("source_action"), dict) else {}
    source_details = source.get("details") if isinstance(source.get("details"), dict) else {}
    for value in (details.get("intent"), source_details.get("intent"), row.get("intent")):
        if isinstance(value, dict):
            return value
    return {}


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _unique(values: Iterable[Any]) -> List[str]:
    return sorted({str(x) for x in values if str(x or "").strip()})


def _contains_any(values: Iterable[str], needles: Iterable[str]) -> bool:
    haystack = " ".join(str(x).lower() for x in values)
    return any(needle in haystack for needle in needles)


def _phase_c_snapshot_by_ticker(adapter: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for raw in adapter.get("phase_c_candidate_snapshots") or []:
        if not isinstance(raw, dict):
            continue
        candidate = raw.get("candidate") if isinstance(raw.get("candidate"), dict) else {}
        ticker = normalize_ticker(raw.get("ticker") or candidate.get("ticker"))
        if ticker:
            out[ticker] = raw
    return out


def _fresh_evidence_tickers(evidence: Dict[str, Any]) -> set[str]:
    if not isinstance(evidence, dict):
        return set()
    by_ticker = evidence.get("by_ticker") if isinstance(evidence.get("by_ticker"), dict) else evidence
    return {normalize_ticker(k) for k, v in by_ticker.items() if normalize_ticker(k) and isinstance(v, dict)} if isinstance(by_ticker, dict) else set()


def _empty_row(ticker: str) -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "configured_ticker": True,
        "seen_in_d6": False,
        "seen_in_orchestrator": False,
        "seen_in_adapter": False,
        "seen_in_review": False,
        "seen_in_evidence": False,
        "d6_status": "",
        "d6_setup_family": "",
        "d6_confidence": None,
        "d6_hard_blockers": [],
        "d6_soft_blockers": [],
        "d6_missing_data_blockers": [],
        "d6_price": "",
        "d6_quote": "",
        "d6_target": "",
        "d6_invalidation": "",
        "orchestrator_action_class": "",
        "orchestrator_classification": "",
        "orchestrator_blockers": [],
        "adapter_selected": False,
        "adapter_rejected": False,
        "adapter_rejection_reasons": [],
        "adapter_quote": "",
        "adapter_price": "",
        "review_selected": False,
        "review_promoted": False,
        "review_status": "",
        "judge_review_status": "",
        "deterministic_risk_review_status": "",
        "phase_c_guard_passed": False,
        "phase_c_guard_blockers": [],
        "stale_status": "unknown",
        "stale_reason": "",
        "reservation_blockers": [],
        "product_rule_blockers": [],
        "orderbook_blockers": [],
        "confidence_blockers": [],
        "volume_momentum_blockers": [],
        "root_cause_category": "insufficient_context_unknown",
        "secondary_root_causes": [],
        "root_cause_detail": "",
        "next_fix": "",
        "priority": "P4",
        "can_be_considered_for_future_all_ticker_live": False,
        "future_live_requires_ack": True,
    }


def _classify(row: Dict[str, Any]) -> None:
    blockers = _unique(
        row["d6_hard_blockers"]
        + row["d6_soft_blockers"]
        + row["d6_missing_data_blockers"]
        + row["orchestrator_blockers"]
        + row["adapter_rejection_reasons"]
        + row["phase_c_guard_blockers"]
        + row["reservation_blockers"]
        + row["product_rule_blockers"]
        + row["orderbook_blockers"]
    )
    secondary: List[str] = []

    if not row["seen_in_d6"] and not row["seen_in_orchestrator"] and not row["seen_in_adapter"] and not row["seen_in_review"]:
        category = "no_candidate_seen"
        detail = "Ticker is configured but absent from the loaded D.6, orchestrator, adapter and review artifacts."
        next_fix = "Refresh all-ticker D.6 candidate generation and confirm this ticker appears in candidate inputs."
    elif row["phase_c_guard_passed"] and row["review_promoted"]:
        category = "phase_c_ready"
        detail = "Fresh review promoted the candidate and the Phase-C guard passed in preview; actual submit still requires exact ACK."
        next_fix = "Operator may review for future ACK-gated maker BUY readiness; do not submit from this report."
    elif _contains_any(blockers, ["ticker_missing", "unsupported_action_class"]) or (row["seen_in_adapter"] and not row["adapter_selected"] and not row["adapter_rejected"]):
        category = "code_mapping_or_contract_gap"
        detail = f"Report contract did not map this ticker cleanly through the pipeline: {blockers}."
        next_fix = "Fix report schema/mapping before using this ticker for readiness decisions."
    elif _contains_any(blockers, ["sell_rejected", "market_rejected", "market_orders_disabled", "market_candidate_rejected", "duplicate_sell", "oversell"]):
        category = "true_safety_blocker"
        detail = f"Candidate crossed a hard safety boundary or disabled execution surface: {blockers}."
        next_fix = "Keep blocked; requires separate design/governance, not this diagnostic sprint."
    elif _contains_any(blockers, ["missing_target", "missing_invalidation"]):
        category = "missing_target_or_invalidation"
        detail = f"Candidate lacks valid target/invalidation references: {blockers}."
        next_fix = "Refresh candidate/trade-plan extraction so target and invalidation are populated."
    elif _contains_any(blockers, ["orderbook", "proposed_price_missing", "missing_market", "snapshot_available:false"]):
        category = "missing_market_or_orderbook_data"
        detail = f"Candidate lacks usable market/orderbook data: {blockers}."
        next_fix = "Refresh local market/orderbook evidence before review or ranking."
    elif _contains_any(blockers, ["product_min", "min_notional", "below_product_min", "quote_min"]):
        category = "product_or_min_notional_blocker"
        detail = f"Product rule or minimum notional check blocks this candidate: {blockers}."
        next_fix = "Collect fresh product-rule evidence and adjust only after separate parameter approval."
    elif row["adapter_selected"] and row["judge_review_status"] in {"", "missing_or_not_approved"}:
        category = "needs_fresh_judge_review"
        if row["deterministic_risk_review_status"] in {"", "missing_or_not_approved"}:
            secondary.append("needs_deterministic_live_risk")
        detail = "Adapter selected the ticker, but fresh BUY judge approval is missing; deterministic live-risk approval may also be missing."
        next_fix = "Run/provide fresh Phase-C judge review and deterministic live-risk evidence, then rerun review."
    elif row["adapter_selected"] and row["deterministic_risk_review_status"] in {"", "missing_or_not_approved"}:
        category = "needs_deterministic_live_risk"
        detail = "Adapter selected the ticker and judge evidence is not the active blocker, but deterministic live-risk approval is missing."
        next_fix = "Generate deterministic live-risk evidence for this exact maker BUY candidate."
    elif _contains_any(blockers, ["stale_candidate_rejected", "stale_or_missing_expiry"]):
        category = "stale_candidate_needs_refresh"
        detail = f"Candidate freshness failed or expiry is missing: {blockers}."
        next_fix = "Refresh D.6 candidate data; if stale only appears after review, treat it as data TTL expiry, not live readiness."
    elif _contains_any(blockers, ["max_2_new_orders_per_cycle", "max_new_orders_per_cycle"]):
        category = "adapter_selection_cap"
        detail = "Ticker reached candidate/review stages but was hidden behind max_new_orders_per_cycle=2."
        next_fix = "Rerun diagnostic selection analysis without changing live caps, or review ranking order."
    elif _contains_any(blockers, ["max_5_open", "max_open_order", "max_1_open", "reserved_quote", "reservation"]):
        category = "reservation_or_open_order_cap"
        detail = f"Reservation/open-order governance blocks this ticker: {blockers}."
        next_fix = "Wait for open-order capacity or reconcile reservations with explicit approval if evidence requires it."
    elif row["d6_hard_blockers"]:
        category = "hard_strategy_reject"
        detail = f"D.6 hard strategy blockers rejected the candidate: {row['d6_hard_blockers']}."
        next_fix = "Leave blocked unless future strategy work changes the setup logic."
    elif row["d6_soft_blockers"]:
        category = "soft_near_miss_threshold"
        detail = f"Ticker is a near-miss due to soft blockers: {row['d6_soft_blockers']}."
        next_fix = "Improve confidence, volume/momentum, setup clarity or edge before fresh Phase-C review."
    elif row["seen_in_d6"]:
        category = "not_selected_low_priority"
        detail = "Ticker has D.6 context but was not selected by current ranking/caps."
        next_fix = "Review ranking inputs after higher-priority candidates are resolved."
    else:
        category = "insufficient_context_unknown"
        detail = "Loaded artifacts do not contain enough structured evidence to determine a specific blocker."
        next_fix = "Refresh reports and inspect schema contract."

    if _contains_any(blockers, ["stale_candidate_rejected", "stale_or_missing_expiry"]) and category != "stale_candidate_needs_refresh":
        secondary.append("stale_candidate_needs_refresh")
        row["stale_status"] = "stale"
        row["stale_reason"] = "stale_candidate_rejected" if "stale_candidate_rejected" in blockers else "stale_or_missing_expiry"
    elif row["seen_in_d6"] or row["seen_in_review"]:
        row["stale_status"] = "not_flagged_stale"

    if _contains_any(blockers, ["confidence_below", "setup_family_unclear", "reward_risk", "edge_score"]):
        secondary.append("soft_near_miss_threshold")
    if _contains_any(blockers, ["bad_volume_or_momentum"]):
        secondary.append("soft_near_miss_threshold")
    if _contains_any(blockers, ["max_2_new_orders_per_cycle", "max_new_orders_per_cycle"]) and category != "adapter_selection_cap":
        secondary.append("adapter_selection_cap")
    if _contains_any(blockers, ["fresh_judge_buy_approval_missing", "fresh_review_required"]) and category != "needs_fresh_judge_review":
        secondary.append("needs_fresh_judge_review")
    if _contains_any(blockers, ["deterministic_live_risk_approval_missing"]) and category != "needs_deterministic_live_risk":
        secondary.append("needs_deterministic_live_risk")

    row["root_cause_category"] = category
    row["secondary_root_causes"] = [x for x in _unique(secondary) if x in ROOT_CAUSE_CATEGORIES and x != category]
    row["root_cause_detail"] = detail
    row["next_fix"] = next_fix
    row["priority"] = PRIORITY_BY_CATEGORY.get(category, "P4")
    row["can_be_considered_for_future_all_ticker_live"] = category in {
        "phase_c_ready",
        "needs_fresh_judge_review",
        "needs_deterministic_live_risk",
        "stale_candidate_needs_refresh",
        "adapter_selection_cap",
        "soft_near_miss_threshold",
    }


def build_full_bot_failure_determination_matrix(
    *,
    d6_report: Optional[Dict[str, Any]] = None,
    orchestrator_report: Optional[Dict[str, Any]] = None,
    adapter_report: Optional[Dict[str, Any]] = None,
    post_review_adapter_report: Optional[Dict[str, Any]] = None,
    review_report: Optional[Dict[str, Any]] = None,
    fresh_evidence_report: Optional[Dict[str, Any]] = None,
    open_orders_state: Optional[Dict[str, Any]] = None,
    positions_state: Optional[Dict[str, Any]] = None,
    configured_tickers: Optional[Iterable[str]] = None,
    source_paths: Optional[Iterable[str | Path]] = None,
) -> Dict[str, Any]:
    tickers = [normalize_ticker(t) for t in (configured_tickers or CONFIGURED_USDC_TICKERS) if normalize_ticker(t)]
    d6 = d6_report or {}
    orch = orchestrator_report or {}
    adapter = post_review_adapter_report or adapter_report or {}
    review = review_report or {}
    evidence = fresh_evidence_report or {}

    d6_rows = _ticker_map((d6.get("preview_ready_intents") or []) + (d6.get("near_miss_intents") or []) + (d6.get("rejected_candidates") or []) + (d6.get("hard_rejected_candidates") or []))
    orch_rows = _ticker_map(orch.get("entry_action_candidates") or [], nested_intent=True)
    selected_rows = _ticker_map(adapter.get("selected_entry_candidates") or [], nested_intent=True)
    rejected_rows = _ticker_map(adapter.get("rejected_entry_candidates") or [], nested_intent=True)
    review_rows = _ticker_map(review.get("fresh_review_results") or [])
    promoted_rows = _ticker_map(review.get("promoted_phase_c_ready_candidates") or [])
    phase_c_snapshots = _phase_c_snapshot_by_ticker(adapter)
    evidence_tickers = _fresh_evidence_tickers(evidence)

    matrix: List[Dict[str, Any]] = []
    for ticker in tickers:
        row = _empty_row(ticker)
        d6_item = d6_rows.get(ticker, {})
        orch_item = orch_rows.get(ticker, {})
        selected = selected_rows.get(ticker, {})
        rejected = rejected_rows.get(ticker, {})
        review_item = review_rows.get(ticker, {})
        promoted = promoted_rows.get(ticker, {})
        intent = _intent(orch_item) or _intent(selected) or _intent(rejected) or d6_item

        row["seen_in_d6"] = bool(d6_item)
        row["seen_in_orchestrator"] = bool(orch_item)
        row["seen_in_adapter"] = bool(selected or rejected)
        row["seen_in_review"] = bool(review_item or promoted)
        row["seen_in_evidence"] = ticker in evidence_tickers

        row["d6_status"] = str(_first_nonempty(d6_item.get("status"), intent.get("status"), ""))
        row["d6_setup_family"] = str(_first_nonempty(d6_item.get("setup_family"), intent.get("setup_family"), ""))
        row["d6_confidence"] = _first_nonempty(d6_item.get("confidence"), d6_item.get("confidence_score"), intent.get("confidence"))
        row["d6_hard_blockers"] = _unique(_as_list(_first_nonempty(d6_item.get("hard_blockers"), intent.get("hard_blockers"), [])))
        row["d6_soft_blockers"] = _unique(_as_list(_first_nonempty(d6_item.get("soft_blockers"), intent.get("soft_blockers"), [])))
        row["d6_missing_data_blockers"] = _unique(_as_list(_first_nonempty(d6_item.get("missing_data_blockers"), intent.get("missing_data_blockers"), [])))
        row["d6_price"] = str(_first_nonempty(d6_item.get("proposed_price"), intent.get("proposed_price"), selected.get("limit_price"), rejected.get("limit_price"), ""))
        row["d6_quote"] = str(_first_nonempty(d6_item.get("proposed_size_quote"), intent.get("proposed_size_quote"), selected.get("quote_size"), rejected.get("quote_size"), ""))
        row["d6_target"] = str(_first_nonempty(d6_item.get("target_reference"), intent.get("target_reference"), ""))
        row["d6_invalidation"] = str(_first_nonempty(d6_item.get("invalidation_reference"), intent.get("invalidation_reference"), ""))

        row["orchestrator_action_class"] = str(orch_item.get("action_class") or "")
        row["orchestrator_classification"] = str(orch_item.get("classification") or "")
        row["orchestrator_blockers"] = _unique(_as_list(orch_item.get("blockers")))

        row["adapter_selected"] = bool(selected)
        row["adapter_rejected"] = bool(rejected)
        row["adapter_rejection_reasons"] = _unique(_as_list(rejected.get("reasons")))
        row["adapter_quote"] = str(_first_nonempty(selected.get("quote_size"), rejected.get("quote_size"), ""))
        row["adapter_price"] = str(_first_nonempty(selected.get("limit_price"), rejected.get("limit_price"), ""))

        row["review_selected"] = bool(review_item)
        row["review_promoted"] = bool(promoted) or str(review_item.get("status") or "").lower() == "promoted_phase_c_ready"
        row["review_status"] = str(review_item.get("status") or "")
        row["judge_review_status"] = str(review_item.get("judge_review_status") or "")
        row["deterministic_risk_review_status"] = str(review_item.get("deterministic_risk_review_status") or "")

        guard = {}
        if review_item:
            guard = review_item.get("phase_c_guard_after_review") if isinstance(review_item.get("phase_c_guard_after_review"), dict) else {}
        if not guard and ticker in phase_c_snapshots:
            guard = phase_c_snapshots[ticker].get("guard_result") if isinstance(phase_c_snapshots[ticker].get("guard_result"), dict) else {}
        row["phase_c_guard_passed"] = bool(guard.get("guard_allows_live_submit") or (row["review_promoted"] and not guard.get("hard_block_reasons")))
        row["phase_c_guard_blockers"] = _unique(_as_list(guard.get("hard_block_reasons") or guard.get("blockers") or review_item.get("blockers")))

        all_blockers = row["d6_hard_blockers"] + row["d6_soft_blockers"] + row["d6_missing_data_blockers"] + row["orchestrator_blockers"] + row["adapter_rejection_reasons"] + row["phase_c_guard_blockers"]
        row["reservation_blockers"] = [x for x in _unique(all_blockers) if _contains_any([x], ["max_open", "reserved", "max_1_open", "max_5_open", "max_100"])]
        row["product_rule_blockers"] = [x for x in _unique(all_blockers) if _contains_any([x], ["product", "min_notional", "quote_min", "below_product"])]
        row["orderbook_blockers"] = [x for x in _unique(all_blockers) if _contains_any([x], ["orderbook", "spread", "proposed_price_missing"])]
        row["confidence_blockers"] = [x for x in _unique(all_blockers) if _contains_any([x], ["confidence", "setup_family", "edge_score", "reward_risk"])]
        row["volume_momentum_blockers"] = [x for x in _unique(all_blockers) if _contains_any([x], ["volume", "momentum"])]

        _classify(row)
        matrix.append(row)

    summary = _summary(matrix)
    report = {
        "generated_at": now_iso(),
        "phase": FULL_BOT_FAILURE_DETERMINATION_PHASE,
        "status": "diagnostic_matrix_built",
        "classification": "REPORT_ONLY",
        "report_only": True,
        "live_order_submit_attempted": False,
        "coinbase_write_attempted": False,
        "state_write_performed": False,
        "configured_tickers": tickers,
        "matrix": matrix,
        "summary": summary,
        "input_hashes": {},
        "state_files_read_only": {
            "open_orders_loaded": isinstance(open_orders_state, dict),
            "positions_loaded": isinstance(positions_state, dict),
        },
        "next_implementation_step": summary["exact_next_implementation_step"],
    }
    for raw in source_paths or []:
        path = Path(raw)
        if path.exists() and path.is_file():
            report["input_hashes"][str(path)] = sha256_file(path)
    return json_safe(report)


def _summary(matrix: List[Dict[str, Any]]) -> Dict[str, Any]:
    root_counts = Counter(row["root_cause_category"] for row in matrix)
    priority_counts = Counter(row["priority"] for row in matrix)
    phase_ready = [row["ticker"] for row in matrix if row["root_cause_category"] == "phase_c_ready"]
    selected = [row["ticker"] for row in matrix if row["adapter_selected"]]
    cap_blocked = [row["ticker"] for row in matrix if row["root_cause_category"] == "adapter_selection_cap" or "adapter_selection_cap" in row["secondary_root_causes"]]
    p1 = [row for row in matrix if row["priority"] == "P1"]
    summary = {
        "total_configured_tickers": len(matrix),
        "total_seen_candidates": sum(1 for row in matrix if row["seen_in_d6"] or row["seen_in_orchestrator"] or row["seen_in_adapter"] or row["seen_in_review"]),
        "count_by_root_cause_category": dict(sorted(root_counts.items())),
        "count_by_priority": dict(sorted(priority_counts.items())),
        "all_p0_items": [row["ticker"] for row in matrix if row["priority"] == "P0"],
        "all_p1_items": [row["ticker"] for row in p1],
        "top_all_ticker_refresh_candidates": [row["ticker"] for row in p1 if row["root_cause_category"] in {"stale_candidate_needs_refresh", "adapter_selection_cap", "needs_fresh_judge_review"}][:8],
        "top_all_ticker_fresh_judge_candidates": [row["ticker"] for row in matrix if row["root_cause_category"] == "needs_fresh_judge_review" or "needs_fresh_judge_review" in row["secondary_root_causes"]][:8],
        "top_all_ticker_deterministic_risk_candidates": [row["ticker"] for row in matrix if row["root_cause_category"] == "needs_deterministic_live_risk" or "needs_deterministic_live_risk" in row["secondary_root_causes"]][:8],
        "tickers_blocked_only_by_selection_cap": [
            row["ticker"]
            for row in matrix
            if row["root_cause_category"] == "adapter_selection_cap" and not row["confidence_blockers"] and not row["volume_momentum_blockers"]
        ],
        "tickers_missing_target_or_invalidation": [row["ticker"] for row in matrix if row["root_cause_category"] == "missing_target_or_invalidation"],
        "tickers_missing_orderbook_or_market_data": [row["ticker"] for row in matrix if row["root_cause_category"] == "missing_market_or_orderbook_data"],
        "tickers_with_hard_safety_blockers": [row["ticker"] for row in matrix if row["root_cause_category"] == "true_safety_blocker"],
        "tickers_with_no_candidate_seen": [row["ticker"] for row in matrix if row["root_cause_category"] == "no_candidate_seen"],
        "any_ticker_phase_c_ready_now": bool(phase_ready),
        "phase_c_ready_tickers": phase_ready,
        "xrp_usdc_root_cause": _root_for(matrix, "XRP-USDC"),
        "apt_usdc_root_cause": _root_for(matrix, "APT-USDC"),
        "avax_usdc_root_cause": _root_for(matrix, "AVAX-USDC"),
        "btc_usdc_root_cause": _root_for(matrix, "BTC-USDC"),
        "any_ticker_closer_than_xrp_apt": any(row["root_cause_category"] == "phase_c_ready" for row in matrix if row["ticker"] not in {"XRP-USDC", "APT-USDC"}),
        "max_new_orders_per_cycle_hides_viable_candidates": bool(cap_blocked),
        "max_new_orders_per_cycle_hidden_tickers": cap_blocked,
        "stale_candidate_rejected_explanation": "stale_candidate_rejected is treated as data freshness/TTL expiry unless accompanied by code_mapping_or_contract_gap.",
        "exact_next_implementation_step": "Refresh all-ticker D.6 candidates and run fresh Phase-C judge plus deterministic live-risk evidence for the selected or cap-hidden P1 candidates; keep live caps and ACK gates unchanged.",
    }
    return summary


def _root_for(matrix: List[Dict[str, Any]], ticker: str) -> Dict[str, Any]:
    for row in matrix:
        if row["ticker"] == ticker:
            return {
                "root_cause_category": row["root_cause_category"],
                "secondary_root_causes": row["secondary_root_causes"],
                "priority": row["priority"],
                "detail": row["root_cause_detail"],
                "next_fix": row["next_fix"],
            }
    return {}


def render_full_bot_failure_determination_markdown(report: Dict[str, Any]) -> str:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# Full Bot Failure Determination Matrix v1",
        "",
        "Report-only all-ticker diagnostic. It does not submit orders, call Coinbase write endpoints, mutate config or write trading state.",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- total_configured_tickers: `{summary.get('total_configured_tickers')}`",
        f"- total_seen_candidates: `{summary.get('total_seen_candidates')}`",
        f"- live_order_submit_attempted: `{report.get('live_order_submit_attempted')}`",
        f"- coinbase_write_attempted: `{report.get('coinbase_write_attempted')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        f"- any_ticker_phase_c_ready_now: `{summary.get('any_ticker_phase_c_ready_now')}`",
        f"- max_new_orders_per_cycle_hides_viable_candidates: `{summary.get('max_new_orders_per_cycle_hides_viable_candidates')}`",
        "",
        "## Root Cause Counts",
        "",
        "```json",
        json.dumps(summary.get("count_by_root_cause_category") or {}, indent=2, sort_keys=True),
        "```",
        "",
        "## Priority Counts",
        "",
        "```json",
        json.dumps(summary.get("count_by_priority") or {}, indent=2, sort_keys=True),
        "```",
        "",
        "## Special Cases",
        "",
        f"- XRP-USDC: `{summary.get('xrp_usdc_root_cause')}`",
        f"- APT-USDC: `{summary.get('apt_usdc_root_cause')}`",
        f"- AVAX-USDC: `{summary.get('avax_usdc_root_cause')}`",
        f"- BTC-USDC: `{summary.get('btc_usdc_root_cause')}`",
        f"- stale_candidate_rejected: `{summary.get('stale_candidate_rejected_explanation')}`",
        "",
        "## Required Lists",
        "",
        f"- all_p0_items: `{summary.get('all_p0_items')}`",
        f"- all_p1_items: `{summary.get('all_p1_items')}`",
        f"- top_all_ticker_refresh_candidates: `{summary.get('top_all_ticker_refresh_candidates')}`",
        f"- top_all_ticker_fresh_judge_candidates: `{summary.get('top_all_ticker_fresh_judge_candidates')}`",
        f"- top_all_ticker_deterministic_risk_candidates: `{summary.get('top_all_ticker_deterministic_risk_candidates')}`",
        f"- tickers_blocked_only_by_selection_cap: `{summary.get('tickers_blocked_only_by_selection_cap')}`",
        f"- tickers_missing_target_or_invalidation: `{summary.get('tickers_missing_target_or_invalidation')}`",
        f"- tickers_missing_orderbook_or_market_data: `{summary.get('tickers_missing_orderbook_or_market_data')}`",
        f"- tickers_with_hard_safety_blockers: `{summary.get('tickers_with_hard_safety_blockers')}`",
        f"- tickers_with_no_candidate_seen: `{summary.get('tickers_with_no_candidate_seen')}`",
        "",
        "## Matrix",
        "",
        "| ticker | root cause | priority | selected | seen D6 | detail |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in report.get("matrix") or []:
        detail = str(row.get("root_cause_detail") or "").replace("|", "\\|")
        lines.append(
            f"| {row.get('ticker')} | {row.get('root_cause_category')} | {row.get('priority')} | {row.get('adapter_selected')} | {row.get('seen_in_d6')} | {detail} |"
        )
    lines.extend(
        [
            "",
            "## Next Step",
            "",
            str(summary.get("exact_next_implementation_step") or ""),
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "CONFIGURED_USDC_TICKERS",
    "FULL_BOT_FAILURE_DETERMINATION_PHASE",
    "build_full_bot_failure_determination_matrix",
    "load_json_file",
    "load_latest_report",
    "render_full_bot_failure_determination_markdown",
]
