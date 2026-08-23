from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.full_bot_maker_buy_live_adapter import (
    FULL_BOT_MAKER_BUY_LIVE_ADAPTER_PHASE,
    _adapter_cfg,
    decimal_str,
    json_safe,
    load_json_file,
    phase_c_candidate_from_selection,
    to_decimal,
)
from bot.full_bot_orchestrator import normalize_ticker, sha256_file
from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness


FULL_BOT_NEAR_MISS_PHASE_C_REVIEW_PHASE = "full_bot_near_miss_phase_c_review_v1"
ZERO = Decimal("0")
MAX_QUOTE = Decimal("20")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _intent(selection: Dict[str, Any]) -> Dict[str, Any]:
    source = selection.get("source_action") if isinstance(selection.get("source_action"), dict) else {}
    details = source.get("details") if isinstance(source.get("details"), dict) else {}
    intent = details.get("intent") if isinstance(details.get("intent"), dict) else {}
    return intent


def _fresh_evidence_for(selection: Dict[str, Any], fresh_review_evidence: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(fresh_review_evidence, dict):
        return {}
    ticker = normalize_ticker(selection.get("ticker") or _intent(selection).get("ticker"))
    by_ticker = fresh_review_evidence.get("by_ticker") if isinstance(fresh_review_evidence.get("by_ticker"), dict) else fresh_review_evidence
    raw = by_ticker.get(ticker) if isinstance(by_ticker, dict) else None
    return raw if isinstance(raw, dict) else {}


def _judge_approves_buy(evidence: Dict[str, Any]) -> bool:
    judge = evidence.get("judge") if isinstance(evidence.get("judge"), dict) else evidence.get("fresh_judge")
    judge = judge if isinstance(judge, dict) else evidence
    decision = str(judge.get("decision") or judge.get("verdict") or "").strip().lower()
    side = str(judge.get("side") or "").strip().upper()
    approved = bool(judge.get("approved") or judge.get("buy_approved") or decision == "approve_trade")
    return approved and (side in {"", "BUY"}) and decision in {"", "approve_trade", "approve_buy", "buy"}


def _risk_approves_live(evidence: Dict[str, Any]) -> bool:
    risk = evidence.get("risk") if isinstance(evidence.get("risk"), dict) else evidence.get("deterministic_risk")
    risk = risk if isinstance(risk, dict) else evidence
    accepted = bool(risk.get("accepted") or risk.get("approved") or risk.get("risk_approved"))
    mode = str(risk.get("mode") or "deterministic_live_risk").strip().lower()
    return accepted and "paper" not in mode


def _candidate_shape_blockers(
    selection: Dict[str, Any],
    *,
    now: Optional[datetime],
    product_rules: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], List[str]]:
    intent = _intent(selection)
    ticker = normalize_ticker(selection.get("ticker") or intent.get("ticker"))
    side = str(selection.get("side") or intent.get("side") or "").strip().upper()
    preferred = str(intent.get("preferred_order_type") or intent.get("order_type") or "").strip().lower()
    action_class = str(selection.get("action_class") or "")
    price = to_decimal(selection.get("limit_price") or intent.get("proposed_price") or intent.get("suggested_watch_level"))
    quote = to_decimal(selection.get("quote_size") or intent.get("proposed_size_quote"))
    target = to_decimal(intent.get("target_reference"))
    invalidation = to_decimal(intent.get("invalidation_reference"))
    do_not_chase = to_decimal(intent.get("do_not_chase_boundary"))

    blockers: List[str] = []
    warnings: List[str] = []
    if not ticker:
        blockers.append("missing_ticker")
    if side != "BUY":
        blockers.append("sell_rejected" if side == "SELL" else f"side_not_buy:{side or 'missing'}")
    if "market" in preferred or bool(intent.get("market_order_preview")):
        blockers.append("market_rejected")
    if str(selection.get("classification") or "").strip().lower() == "blocked":
        blockers.append("blocked_candidate_rejected")
    if action_class not in {"near_miss_maker_buy", "pattern_intent_maker_buy", "strict_approve_trade_buy"}:
        blockers.append("unsupported_action_class")
    if price <= ZERO:
        blockers.append("missing_price")
    if quote <= ZERO:
        blockers.append("missing_quote")
    if quote > MAX_QUOTE:
        blockers.append("quote_gt_20_rejected")
    if target <= ZERO:
        blockers.append("missing_target")
    if invalidation <= ZERO:
        blockers.append("missing_invalidation")
    if do_not_chase > ZERO and price > do_not_chase:
        blockers.append("do_not_chase_violation")
    expires_at = _parse_time(intent.get("expires_at"))
    if not expires_at:
        blockers.append("stale_or_missing_expiry")
    elif now and expires_at <= now:
        blockers.append("stale_candidate_rejected")

    rules = product_rules if isinstance(product_rules, dict) else {}
    min_quote = max(
        to_decimal(rules.get("min_order_quote")),
        to_decimal(rules.get("min_market_funds")),
        to_decimal(rules.get("quote_min_size")),
    )
    if min_quote > ZERO and quote < min_quote:
        blockers.append("product_min_notional_failure")
    if not rules:
        warnings.append("product_rules_not_supplied_min_notional_not_checked")
    return sorted(set(blockers)), sorted(set(warnings))


def _review_request(selection: Dict[str, Any]) -> Dict[str, Any]:
    intent = _intent(selection)
    return {
        "ticker": normalize_ticker(selection.get("ticker") or intent.get("ticker")),
        "required_output": {
            "fresh_judge": {"decision": "approve_trade|wait|reject", "side": "BUY", "rationale": "required"},
            "deterministic_live_risk": {"approved": "bool", "mode": "deterministic_live_risk", "blockers": "list"},
        },
        "questions": [
            "Is the near-miss still valid now?",
            "Is the setup still near the proposed level?",
            "Does it have a recognizable setup?",
            "Is confidence now sufficient?",
            "Does fresh judge output approve BUY?",
            "Does deterministic live risk approve?",
        ],
        "candidate_input": {
            "action_class": selection.get("action_class"),
            "classification": selection.get("classification"),
            "side": selection.get("side"),
            "quote_size": selection.get("quote_size"),
            "limit_price": selection.get("limit_price"),
            "intent": intent,
        },
    }


def _promoted_candidate(selection: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    candidate = phase_c_candidate_from_selection(selection)
    candidate["analysis"]["judge"] = {
        "decision": "approve_trade",
        "side": "BUY",
        "source": "full_bot_near_miss_phase_c_review",
        "fresh_review_evidence": evidence.get("judge") or evidence.get("fresh_judge") or {},
    }
    candidate["risk"] = {
        "generated_at": now_iso(),
        "mode": str((evidence.get("risk") if isinstance(evidence.get("risk"), dict) else {}).get("mode") or "deterministic_live_risk"),
        "accepted": True,
        "approved": True,
        "risk_approved": True,
        "source": "full_bot_near_miss_phase_c_review",
        "fresh_review_evidence": evidence.get("risk") or evidence.get("deterministic_risk") or {},
        "blockers": [],
    }
    candidate["order_intent"]["preview_only"] = True
    candidate["order_intent"]["promotion_source"] = FULL_BOT_NEAR_MISS_PHASE_C_REVIEW_PHASE
    return json_safe(candidate)


def build_full_bot_near_miss_phase_c_review_report(
    *,
    adapter_report: Dict[str, Any],
    fresh_review_evidence: Optional[Dict[str, Any]] = None,
    product_rules_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    source_paths: Optional[Iterable[str | Path]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now_dt = now or datetime.now(timezone.utc)
    product_rules_by_ticker = product_rules_by_ticker if isinstance(product_rules_by_ticker, dict) else {}
    selected = [dict(x) for x in adapter_report.get("selected_entry_candidates") or [] if isinstance(x, dict)]
    results: List[Dict[str, Any]] = []
    promoted: List[Dict[str, Any]] = []
    non_promoted: List[Dict[str, Any]] = []
    blockers: List[str] = []
    warnings: List[str] = []
    phase_c_blockers: List[str] = []

    cfg = _adapter_cfg(None, allowed_tickers=[x.get("ticker") for x in selected], exact_ack_present=False)
    for index, selection in enumerate(selected):
        ticker = normalize_ticker(selection.get("ticker") or _intent(selection).get("ticker"))
        shape_blockers, shape_warnings = _candidate_shape_blockers(
            selection,
            now=now_dt,
            product_rules=product_rules_by_ticker.get(ticker),
        )
        evidence = _fresh_evidence_for(selection, fresh_review_evidence)
        judge_ok = _judge_approves_buy(evidence)
        risk_ok = _risk_approves_live(evidence)
        candidate_blockers = list(shape_blockers)
        if not evidence:
            candidate_blockers.append("fresh_review_required")
        if not judge_ok:
            candidate_blockers.append("fresh_judge_buy_approval_missing")
        if not risk_ok:
            candidate_blockers.append("deterministic_live_risk_approval_missing")

        candidate = _promoted_candidate(selection, evidence) if not candidate_blockers else phase_c_candidate_from_selection(selection)
        guard = evaluate_phase_c_live_entry_readiness(
            cfg=cfg,
            ticker=ticker,
            analysis=candidate.get("analysis") or {},
            execution_plan=candidate.get("execution_plan") or {},
            order_intent=candidate.get("order_intent") or {},
            live_risk_result=candidate.get("risk") or {},
            open_live_entry_orders_count=int((adapter_report.get("reservation_summary") or {}).get("open_order_count") or 0),
            new_live_orders_this_cycle=index,
        )
        guard_blockers = [str(x) for x in guard.get("hard_block_reasons") or []]
        phase_c_blockers.extend(guard_blockers)
        promoted_now = not candidate_blockers and not guard_blockers
        result = {
            "ticker": ticker,
            "status": "promoted_phase_c_ready" if promoted_now else "not_promoted",
            "classification": "PHASE_C_READY" if promoted_now else "REVIEW_REQUIRED",
            "review_only": True,
            "candidate_validity_blockers": sorted(set(shape_blockers)),
            "fresh_review_required": not evidence,
            "judge_review_status": "approved_buy" if judge_ok else "missing_or_not_approved",
            "deterministic_risk_review_status": "approved_live" if risk_ok else "missing_or_not_approved",
            "phase_c_guard_after_review": guard,
            "review_request": _review_request(selection),
            "blockers": sorted(set(candidate_blockers + guard_blockers)),
            "warnings": shape_warnings,
        }
        results.append(json_safe(result))
        if promoted_now:
            promoted.append(candidate)
        else:
            non_promoted.append({"ticker": ticker, "blockers": result["blockers"]})
        blockers.extend(result["blockers"])
        warnings.extend(shape_warnings)

    report = {
        "generated_at": now_iso(),
        "phase": FULL_BOT_NEAR_MISS_PHASE_C_REVIEW_PHASE,
        "status": "phase_c_ready_candidate_available" if promoted else "fresh_review_required",
        "classification": "WATCH" if not promoted else "PHASE_C_READY_PREVIEW",
        "review_only": True,
        "live_order_submit_attempted": False,
        "coinbase_write_attempted": False,
        "state_write_performed": False,
        "adapter_phase": adapter_report.get("phase"),
        "selected_candidates": selected,
        "fresh_review_results": results,
        "judge_review_status": "approved_buy_present" if any(r["judge_review_status"] == "approved_buy" for r in results) else "fresh_judge_review_required",
        "deterministic_risk_review_status": "approved_live_present" if any(r["deterministic_risk_review_status"] == "approved_live" for r in results) else "deterministic_live_risk_review_required",
        "phase_c_guard_after_review": {
            "all_phase_c_guards_passed": bool(promoted) and not phase_c_blockers,
            "blockers": sorted(set(phase_c_blockers)),
            "guarded_candidate_count": len(results),
        },
        "promoted_phase_c_ready_candidates": promoted,
        "non_promoted_candidates": non_promoted,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "next_operator_decision": "Provide fresh judge BUY approval and deterministic live-risk evidence for one selected BUY maker/limit candidate, then rerun this review. Actual submit remains separate ACK-gated.",
        "input_hashes": {},
    }
    for raw in source_paths or []:
        path = Path(raw)
        if path.exists() and path.is_file():
            report["input_hashes"][str(path)] = sha256_file(path)
    return json_safe(report)


def render_full_bot_near_miss_phase_c_review_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Full Bot Near-Miss Phase-C Review v1",
        "",
        "Preview-only fresh review/promotion report. It does not submit orders, call Coinbase write endpoints or write trading state.",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('status')}`",
        f"- classification: `{report.get('classification')}`",
        f"- review_only: `{report.get('review_only')}`",
        f"- live_order_submit_attempted: `{report.get('live_order_submit_attempted')}`",
        f"- coinbase_write_attempted: `{report.get('coinbase_write_attempted')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        f"- promoted_count: `{len(report.get('promoted_phase_c_ready_candidates') or [])}`",
        "",
        "## Selected Candidates",
        "",
        "```json",
        json.dumps(report.get("selected_candidates") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Fresh Review Results",
        "",
        "```json",
        json.dumps(report.get("fresh_review_results") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Phase-C Guard After Review",
        "",
        "```json",
        json.dumps(report.get("phase_c_guard_after_review") or {}, indent=2, sort_keys=True),
        "```",
        "",
        "## Blockers",
        "",
        "```json",
        json.dumps(report.get("blockers") or [], indent=2, sort_keys=True),
        "```",
        "",
        f"next_operator_decision: `{report.get('next_operator_decision')}`",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "FULL_BOT_NEAR_MISS_PHASE_C_REVIEW_PHASE",
    "build_full_bot_near_miss_phase_c_review_report",
    "load_json_file",
    "render_full_bot_near_miss_phase_c_review_markdown",
]
