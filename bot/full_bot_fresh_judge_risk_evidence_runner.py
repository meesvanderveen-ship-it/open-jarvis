from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.full_bot_failure_determination_matrix import (
    CONFIGURED_USDC_TICKERS,
    build_full_bot_failure_determination_matrix,
    load_json_file,
    load_latest_report,
)
from bot.full_bot_maker_buy_live_adapter import (
    EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK,
    build_full_bot_maker_buy_live_adapter_report,
)
from bot.full_bot_near_miss_phase_c_review import build_full_bot_near_miss_phase_c_review_report
from bot.full_live_parameter_readiness_gate import build_full_live_parameter_readiness_gate
from bot.full_bot_orchestrator import normalize_ticker, sha256_file


FULL_BOT_FRESH_JUDGE_RISK_EVIDENCE_PHASE = "full_bot_fresh_judge_risk_evidence_runner_v1"
MAX_QUOTE = 20.0


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


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _as_float(value: Any) -> float:
    try:
        return float(str(value or "0").strip())
    except (TypeError, ValueError):
        return 0.0


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


def _intent(row: Dict[str, Any]) -> Dict[str, Any]:
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    source = row.get("source_action") if isinstance(row.get("source_action"), dict) else {}
    source_details = source.get("details") if isinstance(source.get("details"), dict) else {}
    for raw in (row.get("intent"), details.get("intent"), source_details.get("intent")):
        if isinstance(raw, dict):
            return raw
    return {}


def _source_by_ticker(rows: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        intent = _intent(raw)
        ticker = normalize_ticker(raw.get("ticker") or intent.get("ticker"))
        if ticker and ticker not in out:
            out[ticker] = raw
    return out


def _evidence_for_ticker(evidence: Optional[Dict[str, Any]], ticker: str) -> Dict[str, Any]:
    if not isinstance(evidence, dict):
        return {}
    by_ticker = evidence.get("by_ticker") if isinstance(evidence.get("by_ticker"), dict) else evidence
    raw = by_ticker.get(ticker) if isinstance(by_ticker, dict) else None
    return raw if isinstance(raw, dict) else {}


def _judge_approves_buy(evidence: Dict[str, Any]) -> bool:
    judge = evidence.get("judge") if isinstance(evidence.get("judge"), dict) else evidence.get("fresh_judge")
    judge = judge if isinstance(judge, dict) else {}
    decision = str(judge.get("decision") or judge.get("verdict") or "").strip().lower()
    side = str(judge.get("side") or "").strip().upper()
    approved = bool(judge.get("approved") or judge.get("buy_approved") or decision == "approve_trade")
    return approved and decision in {"approve_trade", "approve_buy", "buy"} and side in {"BUY", ""}


def _risk_approves_live(evidence: Dict[str, Any]) -> bool:
    risk = evidence.get("risk") if isinstance(evidence.get("risk"), dict) else evidence.get("deterministic_risk")
    risk = risk if isinstance(risk, dict) else {}
    mode = str(risk.get("mode") or "").strip().lower()
    approved = bool(risk.get("accepted") or risk.get("approved") or risk.get("risk_approved"))
    return approved and "paper" not in mode and "live" in (mode or "deterministic_live_risk")


def _stale_status(intent: Dict[str, Any], generated_at: datetime) -> Tuple[str, str, Optional[int]]:
    expires = _parse_time(intent.get("expires_at"))
    if not expires:
        return "stale_or_unknown", "missing_expires_at", None
    age = int((generated_at - expires).total_seconds())
    if expires <= generated_at:
        return "stale", "expires_at_in_past", age
    return "fresh", "expires_at_in_future", -age


def determine_candidate_tickers(
    *,
    failure_matrix_report: Dict[str, Any],
    adapter_report: Dict[str, Any],
    near_miss_review_report: Dict[str, Any],
    d6_report: Dict[str, Any],
) -> List[str]:
    tickers: set[str] = set()
    summary = failure_matrix_report.get("summary") if isinstance(failure_matrix_report.get("summary"), dict) else {}
    matrix = failure_matrix_report.get("matrix") if isinstance(failure_matrix_report.get("matrix"), list) else []
    for row in matrix:
        if isinstance(row, dict) and row.get("priority") == "P1":
            tickers.add(normalize_ticker(row.get("ticker")))
    for key in (
        "all_p1_items",
        "top_all_ticker_fresh_judge_candidates",
        "top_all_ticker_deterministic_risk_candidates",
        "top_all_ticker_refresh_candidates",
        "max_new_orders_per_cycle_hidden_tickers",
        "tickers_blocked_only_by_selection_cap",
        "phase_c_ready_tickers",
    ):
        tickers.update(normalize_ticker(x) for x in _as_list(summary.get(key)))
    for row in adapter_report.get("selected_entry_candidates") or []:
        if isinstance(row, dict):
            tickers.add(normalize_ticker(row.get("ticker") or _intent(row).get("ticker")))
    for row in adapter_report.get("rejected_entry_candidates") or []:
        if isinstance(row, dict) and any("max_2_new_orders_per_cycle" in str(x) or "max_new_orders_per_cycle" in str(x) for x in _as_list(row.get("reasons"))):
            tickers.add(normalize_ticker(row.get("ticker") or _intent(row).get("ticker")))
    for row in near_miss_review_report.get("fresh_review_results") or []:
        if isinstance(row, dict):
            tickers.add(normalize_ticker(row.get("ticker")))
    d6_rows = (
        _as_list(d6_report.get("preview_ready_intents"))
        + _as_list(d6_report.get("near_miss_intents"))
        + _as_list(d6_report.get("rejected_candidates"))
        + _as_list(d6_report.get("hard_rejected_candidates"))
    )
    seen = _source_by_ticker(d6_rows)
    return [ticker for ticker in CONFIGURED_USDC_TICKERS if ticker in tickers and ticker in CONFIGURED_USDC_TICKERS and (ticker in seen or tickers)]


def _packet_for_ticker(
    ticker: str,
    *,
    generated_at: datetime,
    d6_by_ticker: Dict[str, Dict[str, Any]],
    orchestrator_by_ticker: Dict[str, Dict[str, Any]],
    selected_by_ticker: Dict[str, Dict[str, Any]],
    rejected_by_ticker: Dict[str, Dict[str, Any]],
    matrix_by_ticker: Dict[str, Dict[str, Any]],
    fresh_review_evidence: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    source = selected_by_ticker.get(ticker) or rejected_by_ticker.get(ticker) or orchestrator_by_ticker.get(ticker) or d6_by_ticker.get(ticker) or {}
    intent = _intent(source) or source
    matrix = matrix_by_ticker.get(ticker, {})
    evidence = _evidence_for_ticker(fresh_review_evidence, ticker)
    judge_ok = _judge_approves_buy(evidence)
    risk_ok = _risk_approves_live(evidence)
    stale_status, stale_reason, ttl_or_age = _stale_status(intent, generated_at)
    blockers: List[str] = []
    side = str(source.get("side") or intent.get("side") or "").strip().upper()
    order_type = str(intent.get("preferred_order_type") or intent.get("order_type") or "").strip().lower()
    quote = str(source.get("quote_size") or intent.get("proposed_size_quote") or intent.get("quote_size") or matrix.get("d6_quote") or "")
    price = str(source.get("limit_price") or intent.get("proposed_price") or intent.get("suggested_watch_level") or matrix.get("d6_price") or "")
    target = str(intent.get("target_reference") or matrix.get("d6_target") or "")
    invalidation = str(intent.get("invalidation_reference") or matrix.get("d6_invalidation") or "")
    if side != "BUY":
        blockers.append("sell_rejected" if side == "SELL" else f"side_not_buy:{side or 'missing'}")
    if "market" in order_type or bool(intent.get("market_order_preview")):
        blockers.append("market_rejected")
    if _as_float(quote) > MAX_QUOTE:
        blockers.append("quote_gt_20_rejected")
    if stale_status != "fresh":
        blockers.append("stale_candidate_rejected" if stale_status == "stale" else "stale_or_missing_expiry")
    if not evidence:
        blockers.append("fresh_review_required")
    if not judge_ok:
        blockers.append("fresh_judge_buy_approval_missing")
    if not risk_ok:
        blockers.append("deterministic_live_risk_approval_missing")
    blockers.extend(str(x) for x in matrix.get("phase_c_guard_blockers") or [])
    return json_safe(
        {
            "ticker": ticker,
            "setup": str(intent.get("setup_family") or matrix.get("d6_setup_family") or ""),
            "proposed_price": price,
            "quote": quote,
            "target": target,
            "invalidation": invalidation,
            "candidate_age": {
                "status": stale_status,
                "reason": stale_reason,
                "seconds_to_expiry_or_age_after_expiry": ttl_or_age,
                "expires_at": intent.get("expires_at"),
            },
            "orderbook_freshness": {
                "locally_available": bool(intent.get("orderbook_score") or intent.get("liquidity_score")),
                "orderbook_score": intent.get("orderbook_score"),
                "liquidity_score": intent.get("liquidity_score"),
            },
            "required_judge_input": {
                "decision": "approve_trade",
                "side": "BUY",
                "ticker": ticker,
                "setup": str(intent.get("setup_family") or ""),
                "price": price,
                "quote": quote,
                "target": target,
                "invalidation": invalidation,
            },
            "required_deterministic_risk_input": {
                "mode": "deterministic_live_risk",
                "ticker": ticker,
                "side": "BUY",
                "order_type": "limit_maker",
                "quote": quote,
                "limit_price": price,
                "max_quote": "20",
            },
            "fresh_judge_status": "approved_buy" if judge_ok else "fresh_judge_review_required",
            "deterministic_live_risk_status": "approved_live" if risk_ok else "deterministic_live_risk_review_required",
            "fresh_judge_evidence": evidence.get("judge") or evidence.get("fresh_judge") or {},
            "deterministic_live_risk_evidence": evidence.get("risk") or evidence.get("deterministic_risk") or {},
            "current_blockers": sorted(set(blockers)),
            "source_priority": matrix.get("priority", ""),
            "source_root_cause_category": matrix.get("root_cause_category", ""),
            "selected_by_adapter": ticker in selected_by_ticker,
            "cap_hidden_by_adapter": ticker in rejected_by_ticker and any("max_2_new_orders_per_cycle" in str(x) or "max_new_orders_per_cycle" in str(x) for x in _as_list(rejected_by_ticker[ticker].get("reasons"))),
        }
    )


def _state_hashes(root: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for rel in ("state/open_orders.json", "state/positions.json"):
        path = root / rel
        out[rel] = sha256_file(path) if path.exists() else ""
    return out


def build_full_bot_fresh_judge_risk_evidence_report(
    *,
    root: str | Path = ".",
    d6_report: Optional[Dict[str, Any]] = None,
    workflow_audit_report: Optional[Dict[str, Any]] = None,
    failure_matrix_report: Optional[Dict[str, Any]] = None,
    adapter_report: Optional[Dict[str, Any]] = None,
    near_miss_review_report: Optional[Dict[str, Any]] = None,
    orchestrator_report: Optional[Dict[str, Any]] = None,
    fresh_review_evidence: Optional[Dict[str, Any]] = None,
    source_paths: Optional[Iterable[str | Path]] = None,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    root_path = Path(root)
    generated_dt = generated_at or datetime.now(timezone.utc)
    before_hashes = _state_hashes(root_path)
    d6 = d6_report or {}
    workflow = workflow_audit_report or {}
    failure = failure_matrix_report or {}
    adapter = adapter_report or {}
    review = near_miss_review_report or {}
    orchestrator = orchestrator_report or {}

    candidate_tickers = determine_candidate_tickers(
        failure_matrix_report=failure,
        adapter_report=adapter,
        near_miss_review_report=review,
        d6_report=d6,
    )
    d6_by_ticker = _source_by_ticker(
        _as_list(d6.get("preview_ready_intents"))
        + _as_list(d6.get("near_miss_intents"))
        + _as_list(d6.get("rejected_candidates"))
        + _as_list(d6.get("hard_rejected_candidates"))
    )
    orchestrator_by_ticker = _source_by_ticker(orchestrator.get("entry_action_candidates") or [])
    selected_by_ticker = _source_by_ticker(adapter.get("selected_entry_candidates") or [])
    rejected_by_ticker = _source_by_ticker(adapter.get("rejected_entry_candidates") or [])
    matrix_by_ticker = {
        normalize_ticker(row.get("ticker")): row
        for row in failure.get("matrix") or []
        if isinstance(row, dict) and normalize_ticker(row.get("ticker"))
    }
    packets = [
        _packet_for_ticker(
            ticker,
            generated_at=generated_dt,
            d6_by_ticker=d6_by_ticker,
            orchestrator_by_ticker=orchestrator_by_ticker,
            selected_by_ticker=selected_by_ticker,
            rejected_by_ticker=rejected_by_ticker,
            matrix_by_ticker=matrix_by_ticker,
            fresh_review_evidence=fresh_review_evidence,
        )
        for ticker in candidate_tickers
    ]

    near_miss_after = build_full_bot_near_miss_phase_c_review_report(
        adapter_report=adapter,
        fresh_review_evidence=fresh_review_evidence,
        now=generated_dt,
    )
    promoted = near_miss_after.get("promoted_phase_c_ready_candidates") or []
    adapter_after = build_full_bot_maker_buy_live_adapter_report(
        orchestrator_report=orchestrator,
        phase_c_ready_candidates=promoted,
    )
    failure_after = build_full_bot_failure_determination_matrix(
        d6_report=d6,
        orchestrator_report=orchestrator,
        adapter_report=adapter,
        post_review_adapter_report=adapter_after,
        review_report=near_miss_after,
        fresh_evidence_report={"by_ticker": {p["ticker"]: p for p in packets}},
        open_orders_state=load_json_file(root_path / "state/open_orders.json"),
        positions_state=load_json_file(root_path / "state/positions.json"),
        configured_tickers=CONFIGURED_USDC_TICKERS,
    )
    readiness_after = build_full_live_parameter_readiness_gate(
        root=root_path,
        report_payloads={
            "workflow_completeness_audit": workflow,
            "failure_determination_matrix": failure_after,
            "maker_buy_adapter": adapter_after,
            "near_miss_review": near_miss_after,
        },
    )

    judge_approvals = [p["ticker"] for p in packets if p["fresh_judge_status"] == "approved_buy"]
    risk_approvals = [p["ticker"] for p in packets if p["deterministic_live_risk_status"] == "approved_live"]
    phase_c_ready = [x.get("ticker") for x in promoted if isinstance(x, dict) and normalize_ticker(x.get("ticker"))]
    blockers = sorted(set(str(x) for p in packets for x in p.get("current_blockers", [])))
    if not judge_approvals:
        blockers.append("fresh_judge_review_required")
    if not risk_approvals:
        blockers.append("deterministic_live_risk_review_required")
    status = "phase_c_ready_preview_ack_required" if phase_c_ready else "fresh_review_required"
    classification = "PHASE_C_READY_PREVIEW" if phase_c_ready else "blocked_by_missing_fresh_judge_and_risk"
    after_hashes = _state_hashes(root_path)
    report = {
        "generated_at": generated_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "phase": FULL_BOT_FRESH_JUDGE_RISK_EVIDENCE_PHASE,
        "status": status,
        "classification": classification,
        "evidence_only": True,
        "live_order_submit_attempted": False,
        "coinbase_write_attempted": False,
        "state_write_performed": False,
        "candidate_count": len(candidate_tickers),
        "candidates_reviewed": candidate_tickers,
        "evidence_packets": packets,
        "fresh_judge_approvals": sorted(set(judge_approvals)),
        "deterministic_live_risk_approvals": sorted(set(risk_approvals)),
        "phase_c_ready_candidates_after_evidence": phase_c_ready,
        "non_promoted_candidates": near_miss_after.get("non_promoted_candidates") or [],
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(str(x) for x in near_miss_after.get("warnings") or [])),
        "exact_next_codex_task": (
            "Provide real fresh judge approve_trade BUY evidence and deterministic live-risk approval for one selected maker BUY candidate, "
            "then rerun this evidence runner and the readiness gate."
            if not phase_c_ready
            else "Rerun the readiness gate with the post-evidence reports; actual submit still requires exact operator ACK."
        ),
        "exact_next_operator_command_preview": (
            "python3 tools/build_full_bot_fresh_judge_risk_evidence_runner.py "
            "--json-out reports/d6/full-bot-fresh-judge-risk-evidence-$(date -u +%Y%m%d).json "
            "--markdown-out reports/d6/full-bot-fresh-judge-risk-evidence-$(date -u +%Y%m%d).md"
        ),
        "exact_actual_submit_command_if_ready": (
            "DO NOT RUN NOW. Requires Phase-C-ready evidence, clean readiness gate, Coinbase client context, and exact ACK: "
            f"python3 tools/build_full_bot_maker_buy_live_adapter_report.py --actual-submit --ack {EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK} "
            "--orchestrator-report reports/d6/full-bot-orchestrator-$(date -u +%Y%m%d).json "
            "--json-out reports/d6/full-bot-maker-buy-live-adapter-actual-$(date -u +%Y%m%d).json "
            "--markdown-out reports/d6/full-bot-maker-buy-live-adapter-actual-$(date -u +%Y%m%d).md"
        ),
        "downstream_report_summaries": {
            "near_miss_after_evidence": {
                "status": near_miss_after.get("status"),
                "classification": near_miss_after.get("classification"),
                "promoted_count": len(promoted),
            },
            "maker_buy_adapter_after_evidence": {
                "status": adapter_after.get("status"),
                "classification": adapter_after.get("classification"),
                "actual_submit_attempted": adapter_after.get("actual_submit_attempted"),
                "coinbase_write_attempted": adapter_after.get("coinbase_write_attempted"),
            },
            "failure_matrix_after_evidence": {
                "any_ticker_phase_c_ready_now": (failure_after.get("summary") or {}).get("any_ticker_phase_c_ready_now"),
                "phase_c_ready_tickers": (failure_after.get("summary") or {}).get("phase_c_ready_tickers"),
            },
            "readiness_gate_after_evidence": {
                "classification": readiness_after.get("classification"),
                "any_ticker_phase_c_ready_now": readiness_after.get("any_ticker_phase_c_ready_now"),
                "first_real_maker_buy_live_submit_allowed_now": readiness_after.get("first_real_maker_buy_live_submit_allowed_now"),
            },
        },
        "state_hashes": {"before": before_hashes, "after": after_hashes, "unchanged": before_hashes == after_hashes},
        "source_input_hashes": {},
    }
    for raw in source_paths or []:
        path = Path(raw)
        if path.exists() and path.is_file():
            report["source_input_hashes"][str(path)] = sha256_file(path)
    return json_safe(report)


def load_latest_inputs(root: str | Path = ".") -> Tuple[Dict[str, Dict[str, Any]], List[Path]]:
    root_path = Path(root)
    patterns = {
        "d6_report": "d6-multi-order-intent-preview-calibrated-*.json",
        "workflow_audit_report": "full-bot-workflow-completeness-audit-*.json",
        "failure_matrix_report": "full-bot-failure-determination-matrix-*.json",
        "adapter_report": "full-bot-maker-buy-live-adapter-post-review-*.json",
        "near_miss_review_report": "full-bot-near-miss-phase-c-review-*.json",
        "orchestrator_report": "full-bot-orchestrator-*.json",
    }
    payloads: Dict[str, Dict[str, Any]] = {}
    paths: List[Path] = []
    for key, pattern in patterns.items():
        payload, path = load_latest_report(root_path, pattern)
        payloads[key] = payload
        if path:
            paths.append(path)
    return payloads, paths


def render_full_bot_fresh_judge_risk_evidence_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Full Bot Fresh Judge/Risk Evidence Runner v1",
        "",
        "Report-only evidence runner. It does not submit orders, call Coinbase write endpoints, write trading state, mutate env, or start the bot.",
        "",
        f"- status: `{report.get('status')}`",
        f"- classification: `{report.get('classification')}`",
        f"- evidence_only: `{report.get('evidence_only')}`",
        f"- live_order_submit_attempted: `{report.get('live_order_submit_attempted')}`",
        f"- coinbase_write_attempted: `{report.get('coinbase_write_attempted')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        f"- candidate_count: `{report.get('candidate_count')}`",
        f"- fresh_judge_approvals: `{report.get('fresh_judge_approvals')}`",
        f"- deterministic_live_risk_approvals: `{report.get('deterministic_live_risk_approvals')}`",
        f"- phase_c_ready_candidates_after_evidence: `{report.get('phase_c_ready_candidates_after_evidence')}`",
        "",
        "## Candidates Reviewed",
        "",
        "```json",
        json.dumps(report.get("candidates_reviewed") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Evidence Packets",
        "",
        "```json",
        json.dumps(report.get("evidence_packets") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Downstream Summary",
        "",
        "```json",
        json.dumps(report.get("downstream_report_summaries") or {}, indent=2, sort_keys=True),
        "```",
        "",
        "## Blockers",
        "",
        "```json",
        json.dumps(report.get("blockers") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Commands",
        "",
        f"- preview: `{report.get('exact_next_operator_command_preview')}`",
        f"- actual submit: `{report.get('exact_actual_submit_command_if_ready')}`",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "FULL_BOT_FRESH_JUDGE_RISK_EVIDENCE_PHASE",
    "build_full_bot_fresh_judge_risk_evidence_report",
    "determine_candidate_tickers",
    "load_latest_inputs",
    "render_full_bot_fresh_judge_risk_evidence_markdown",
]
