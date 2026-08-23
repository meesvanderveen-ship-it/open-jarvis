from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple

from bot.full_bot_failure_determination_matrix import CONFIGURED_USDC_TICKERS
from bot.full_bot_fresh_judge_risk_evidence_runner import (
    build_full_bot_fresh_judge_risk_evidence_report,
    json_safe,
)
from bot.full_bot_maker_buy_live_adapter import EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK
from bot.full_bot_orchestrator import normalize_ticker, sha256_file
from bot.llm_clients import _provider_error_type
from bot.phase_c43_autonomous_entry_live import build_phase_c43_deterministic_live_risk_snapshot
from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness


REAL_FRESH_REVIEW_PHASE = "full_bot_real_fresh_review_runner_v1"
JUDGE_ALLOWED_KEYS = [
    "decision",
    "side",
    "approved",
    "confidence",
    "rationale",
    "reasons",
    "blockers",
    "setup",
    "target",
    "invalidation",
]


class JsonJudgeClient(Protocol):
    def json_response(
        self,
        system_prompt: str,
        payload: Dict[str, Any],
        model: Optional[str] = None,
        max_retries: int = 1,
        *,
        ticker: str = "UNKNOWN",
        stage: str = "unknown",
        allowed_keys: Optional[Iterable[str]] = None,
        require_all_keys: bool = False,
        drop_unknown_keys: bool = False,
    ) -> Dict[str, Any]:
        ...


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _dec(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _judge_prompt() -> str:
    return (
        "You are the final no-submit Phase-C maker BUY judge. Return one JSON object only. "
        "You may approve only if the candidate is a fresh BUY limit-maker setup with a clear setup, "
        "reasonable target/invalidation, and no safety concern. If evidence is insufficient, return wait. "
        "Never authorize live submission; this review is evidence only."
    )


def _risk_cfg(allowed_tickers: Iterable[str]) -> SimpleNamespace:
    return SimpleNamespace(
        execution_mode="live",
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c_live_small_limit_orders=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        autonomous_entry_only_first=True,
        autonomous_require_post_only=True,
        phase_c_allowed_tickers=[normalize_ticker(x) for x in allowed_tickers if normalize_ticker(x)],
        phase_c_max_order_quote="20.00",
        autonomous_max_order_quote="20.00",
        phase_c_max_open_entry_orders=5,
        autonomous_max_open_orders=5,
        phase_c_max_new_orders_per_cycle=2,
        autonomous_max_new_orders_per_cycle=2,
        phase_c_require_orderbook_freshness=True,
        phase_c_require_pending_intent=True,
        phase_c_require_promotion_ready=True,
        phase_c_require_fresh_judge=True,
        phase_c_require_risk_approval=True,
        phase_c_disable_exit_limit_orders=True,
        enable_limit_order_manager=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=False,
        phase_c_live_order_post_only=True,
        phase_c_entry_order_default_expiry_minutes=60,
        phase_c_entry_order_min_expiry_minutes=15,
        phase_c_entry_order_max_expiry_hours=6,
        phase_c_max_cancels_per_cycle=0,
        phase_c_max_replaces_per_cycle=0,
        phase_c_paper_shadow_log=True,
    )


def _candidate_from_packet(packet: Dict[str, Any]) -> Dict[str, Any]:
    ticker = normalize_ticker(packet.get("ticker"))
    return {
        "ticker": ticker,
        "side": "BUY",
        "quote": str(packet.get("quote") or "20"),
        "limit_price": str(packet.get("proposed_price") or ""),
        "setup": str(packet.get("setup") or ""),
        "target": str(packet.get("target") or ""),
        "invalidation": str(packet.get("invalidation") or ""),
        "expires_at": ((packet.get("candidate_age") or {}).get("expires_at")),
        "orderbook_score": ((packet.get("orderbook_freshness") or {}).get("orderbook_score")),
        "liquidity_score": ((packet.get("orderbook_freshness") or {}).get("liquidity_score")),
        "source_priority": packet.get("source_priority"),
        "source_root_cause_category": packet.get("source_root_cause_category"),
        "selected_by_adapter": bool(packet.get("selected_by_adapter")),
        "cap_hidden_by_adapter": bool(packet.get("cap_hidden_by_adapter")),
        "current_blockers_before_real_review": _as_list(packet.get("current_blockers")),
        "required_judge_input": packet.get("required_judge_input") or {},
        "required_deterministic_risk_input": packet.get("required_deterministic_risk_input") or {},
    }


def _normalize_judge(raw: Dict[str, Any], *, ticker: str, generated_at: str, source: str) -> Dict[str, Any]:
    decision = str(raw.get("decision") or "wait").strip().lower()
    if decision not in {"approve_trade", "wait", "reject"}:
        decision = "wait"
    side = str(raw.get("side") or ("BUY" if decision == "approve_trade" else "NONE")).strip().upper()
    if side not in {"BUY", "NONE"}:
        side = "NONE"
    approved = bool(raw.get("approved")) and decision == "approve_trade" and side == "BUY"
    if decision == "approve_trade" and side == "BUY" and "approved" not in raw:
        approved = True
    confidence = raw.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    return json_safe(
        {
            "decision": decision,
            "side": side,
            "approved": approved,
            "confidence": confidence,
            "source": source,
            "generated_at": generated_at,
            "rationale": raw.get("rationale") or raw.get("reason") or "",
            "reasons": _as_list(raw.get("reasons")),
            "blockers": _as_list(raw.get("blockers")),
            "ticker": ticker,
        }
    )


def _missing_judge(
    *,
    ticker: str,
    generated_at: str,
    reason: str,
    error: str = "",
    provider_error_type: str = "",
) -> Dict[str, Any]:
    return {
        "decision": "wait",
        "side": "NONE",
        "approved": False,
        "confidence": None,
        "source": "real_fresh_review_unavailable",
        "generated_at": generated_at,
        "rationale": reason,
        "reasons": [reason],
        "blockers": [reason],
        "ticker": ticker,
        "error": error,
        "provider_error_type": provider_error_type,
    }


def _review_one(
    *,
    packet: Dict[str, Any],
    judge_client: Optional[JsonJudgeClient],
    judge_model: Optional[str],
    generated_at: str,
    cfg: SimpleNamespace,
    call_llm_judge: bool,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    candidate = _candidate_from_packet(packet)
    ticker = candidate["ticker"]
    review_request = {
        "ticker": ticker,
        "candidate": candidate,
        "required_output": {
            "decision": "approve_trade|wait|reject",
            "side": "BUY|NONE",
            "approved": "bool",
            "confidence": "number|null",
            "rationale": "string",
            "blockers": "list",
        },
        "safety_boundaries": {
            "no_submit": True,
            "no_coinbase_write": True,
            "no_state_write": True,
            "maker_buy_only": True,
            "max_quote": "20",
        },
    }
    if not call_llm_judge:
        judge = _missing_judge(
            ticker=ticker,
            generated_at=generated_at,
            reason="llm_judge_not_called_structured_request_only",
        )
    elif judge_client is None:
        judge = _missing_judge(
            ticker=ticker,
            generated_at=generated_at,
            reason="llm_judge_client_unavailable",
        )
    else:
        try:
            raw = judge_client.json_response(
                _judge_prompt(),
                review_request,
                model=judge_model,
                max_retries=1,
                ticker=ticker,
                stage="real_fresh_phase_c_judge",
                allowed_keys=JUDGE_ALLOWED_KEYS,
                require_all_keys=False,
                drop_unknown_keys=True,
            )
            judge = _normalize_judge(raw, ticker=ticker, generated_at=generated_at, source="real_fresh_review")
        except Exception as exc:
            provider_error_type = _provider_error_type(exc) or ""
            judge = _missing_judge(
                ticker=ticker,
                generated_at=generated_at,
                reason="llm_judge_call_failed",
                error=str(exc),
                provider_error_type=provider_error_type,
            )

    analysis = {
        "judge": {
            "decision": judge["decision"],
            "side": judge["side"],
            "size_quote": candidate["quote"],
            "quote_size": candidate["quote"],
        },
        "feature_pack": {
            "decision_context": {
                "pending_order_intent": {
                    "status": "trigger_ready",
                    "trigger_ready": True,
                    "requires_fresh_judge_and_risk": True,
                }
            }
        },
    }
    execution_plan = {
        "execution_action": "place_limit_buy",
        "read_only": True,
        "orderbook_summary": {
            "snapshot_available": bool(candidate.get("orderbook_score") or candidate.get("liquidity_score")),
            "freshness_status": "fresh",
        },
    }
    order_intent = {
        "ticker": ticker,
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "size_quote": candidate["quote"],
        "limit_price": candidate["limit_price"],
        "preview_only": True,
        "promotion_ready": True,
        "status": "trigger_ready",
    }
    risk_snapshot = build_phase_c43_deterministic_live_risk_snapshot(
        cfg=cfg,
        ticker=ticker,
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        open_live_entry_orders_count=0,
        new_live_orders_this_cycle=0,
    )
    risk_approved = bool(risk_snapshot.get("accepted"))
    risk = {
        "mode": "deterministic_live_risk",
        "approved": risk_approved,
        "accepted": risk_approved,
        "risk_approved": risk_approved,
        "source": "real_deterministic_risk",
        "generated_at": generated_at,
        "blockers": risk_snapshot.get("blockers") or [],
        "passed_checks": risk_snapshot.get("passed_checks") or [],
        "deterministic_snapshot": risk_snapshot,
    }
    guard = evaluate_phase_c_live_entry_readiness(
        cfg=cfg,
        ticker=ticker,
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        live_risk_result=risk,
        open_live_entry_orders_count=0,
        new_live_orders_this_cycle=0,
    )
    evidence = {
        "judge": judge,
        "risk": risk,
        "candidate": candidate,
        "phase_c_guard": guard,
        "review_request": review_request,
    }
    summary = {
        "ticker": ticker,
        "judge_decision": judge.get("decision"),
        "judge_approved": bool(judge.get("approved")),
        "risk_approved": risk_approved,
        "phase_c_guard_allows_live_submit": bool(guard.get("guard_allows_live_submit")),
        "phase_c_blockers": guard.get("hard_block_reasons") or [],
    }
    return json_safe(evidence), json_safe(summary)


def build_real_fresh_review_report(
    *,
    root: Path,
    d6_report: Dict[str, Any],
    workflow_audit_report: Dict[str, Any],
    failure_matrix_report: Dict[str, Any],
    adapter_report: Dict[str, Any],
    near_miss_review_report: Dict[str, Any],
    orchestrator_report: Dict[str, Any],
    judge_client: Optional[JsonJudgeClient] = None,
    judge_model: Optional[str] = None,
    call_llm_judge: bool = True,
    source_paths: Optional[Iterable[str | Path]] = None,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    root = Path(root)
    generated_dt = generated_at or datetime.now(timezone.utc)
    generated = generated_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    candidate_packet_report = build_full_bot_fresh_judge_risk_evidence_report(
        root=root,
        d6_report=d6_report,
        workflow_audit_report=workflow_audit_report,
        failure_matrix_report=failure_matrix_report,
        adapter_report=adapter_report,
        near_miss_review_report=near_miss_review_report,
        orchestrator_report=orchestrator_report,
        fresh_review_evidence=None,
        source_paths=source_paths,
        generated_at=generated_dt,
    )
    packets = [p for p in candidate_packet_report.get("evidence_packets") or [] if isinstance(p, dict)]
    cfg = _risk_cfg(CONFIGURED_USDC_TICKERS)
    by_ticker: Dict[str, Dict[str, Any]] = {}
    summaries: List[Dict[str, Any]] = []
    for packet in packets:
        ticker = normalize_ticker(packet.get("ticker"))
        if ticker not in CONFIGURED_USDC_TICKERS:
            continue
        evidence, summary = _review_one(
            packet=packet,
            judge_client=judge_client,
            judge_model=judge_model,
            generated_at=generated,
            cfg=cfg,
            call_llm_judge=call_llm_judge,
        )
        by_ticker[ticker] = evidence
        summaries.append(summary)

    judge_approvals = [t for t, e in by_ticker.items() if (e.get("judge") or {}).get("approved")]
    risk_approvals = [t for t, e in by_ticker.items() if (e.get("risk") or {}).get("risk_approved")]
    phase_c_ready = [
        t
        for t, e in by_ticker.items()
        if (e.get("judge") or {}).get("approved")
        and (e.get("risk") or {}).get("risk_approved")
        and bool((e.get("phase_c_guard") or {}).get("guard_allows_live_submit"))
    ]
    blockers: List[str] = []
    provider_error_types = sorted(
        {
            str((e.get("judge") or {}).get("provider_error_type") or "")
            for e in by_ticker.values()
            if str((e.get("judge") or {}).get("provider_error_type") or "")
        }
    )
    if not judge_approvals:
        blockers.append("fresh_judge_buy_approval_missing")
    if not risk_approvals:
        blockers.append("deterministic_live_risk_approval_missing")
    if not phase_c_ready:
        blockers.append("missing_phase_c_ready_candidate")
    if not call_llm_judge:
        blockers.append("real_llm_judge_not_called")
    for error_type in provider_error_types:
        blockers.append(f"fresh_judge_provider_error:{error_type}")

    report = {
        "generated_at": generated,
        "phase": REAL_FRESH_REVIEW_PHASE,
        "status": "phase_c_ready_candidate_available" if phase_c_ready else "blocked",
        "classification": "PHASE_C_READY_PREVIEW" if phase_c_ready else "blocked_by_missing_fresh_judge_and_risk",
        "report_only": True,
        "no_submit_by_design": True,
        "live_order_submit_attempted": False,
        "coinbase_write_attempted": False,
        "state_write_performed": False,
        "env_mutation_performed": False,
        "bot_start_attempted": False,
        "all_tickers_considered": CONFIGURED_USDC_TICKERS,
        "candidate_count": len(by_ticker),
        "candidates_reviewed": list(by_ticker.keys()),
        "judge_call_requested": bool(call_llm_judge),
        "judge_provider_error_types": provider_error_types,
        "judge_approvals": judge_approvals,
        "deterministic_live_risk_approvals": risk_approvals,
        "phase_c_ready_candidates": phase_c_ready,
        "actual_submit_allowed_now": False,
        "exact_ack_gated_submit_command_if_ready": (
            "DO NOT RUN NOW. Future ACK-gated command only after operator approval: "
            f"FULL_BOT_MAKER_BUY_LIVE_ACK='{EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK}' "
            "python3 tools/build_full_bot_maker_buy_live_adapter_report.py --actual-submit "
            "--max-orders 5 --max-quote 20 --maker-only --buy-only"
        ),
        "blockers": sorted(set(blockers)),
        "by_ticker": by_ticker,
        "review_summaries": summaries,
        "source_candidate_packet_summary": {
            "candidate_count": candidate_packet_report.get("candidate_count"),
            "candidates_reviewed": candidate_packet_report.get("candidates_reviewed"),
            "blockers": candidate_packet_report.get("blockers"),
        },
        "safety_confirmation": {
            "no_live_submit": True,
            "no_coinbase_write": True,
            "no_state_write": True,
            "no_env_mutation": True,
            "no_bot_start": True,
            "sell_disabled": True,
            "market_disabled": True,
            "replication_disabled": True,
            "learning_to_execution_disabled": True,
        },
        "input_hashes": {},
    }
    for raw in source_paths or []:
        path = Path(raw)
        if path.exists() and path.is_file():
            report["input_hashes"][str(path)] = sha256_file(path)
    return json_safe(report)


def render_real_fresh_review_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Real Fresh Judge/Risk Evidence",
        "",
        "No-submit evidence runner. It never submits orders, calls Coinbase write endpoints, writes trading state, mutates `.env`, or starts the bot.",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('status')}`",
        f"- classification: `{report.get('classification')}`",
        f"- judge_call_requested: `{report.get('judge_call_requested')}`",
        f"- judge_provider_error_types: `{report.get('judge_provider_error_types')}`",
        f"- candidate_count: `{report.get('candidate_count')}`",
        f"- judge_approvals: `{report.get('judge_approvals')}`",
        f"- deterministic_live_risk_approvals: `{report.get('deterministic_live_risk_approvals')}`",
        f"- phase_c_ready_candidates: `{report.get('phase_c_ready_candidates')}`",
        f"- actual_submit_allowed_now: `{report.get('actual_submit_allowed_now')}`",
        f"- blockers: `{report.get('blockers')}`",
        "",
        "## Candidates Reviewed",
        "",
        "```json",
        json.dumps(report.get("review_summaries") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Submit Command",
        "",
        f"`{report.get('exact_ack_gated_submit_command_if_ready')}`",
        "",
    ]
    return "\n".join(lines) + "\n"
