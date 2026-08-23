from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional

from bot.order_store import OrderStore
from bot.phase_c43_autonomous_entry_live import build_phase_c43_guard_and_submit_preparation
from bot.phase_c_live_submitter import append_phase_c_live_order_audit

C43_ONE_ENTRY_SMOKE_PHASE = "C43_one_live_entry_smoke_test"
C43_ONE_ENTRY_SMOKE_ACK = "I_UNDERSTAND_AND_APPROVE_C43_ONE_LIVE_ENTRY_SMOKE_TEST"
ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _cfg_dec(cfg: Any, name: str, default: str) -> Decimal:
    return _to_decimal(getattr(cfg, name, default), default)


def _allowed_tickers(cfg: Any) -> set[str]:
    values = getattr(cfg, "phase_c_allowed_tickers", []) or []
    return {_normalize_ticker(x) for x in values if _normalize_ticker(x)}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def extract_product_rules(product: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Normalize Coinbase product metadata to the submitter's product_rules shape."""
    product = product if isinstance(product, dict) else {}
    return {
        "base_increment": str(product.get("base_increment") or product.get("base_increment_size") or "0"),
        "quote_increment": str(product.get("quote_increment") or product.get("quote_increment_size") or "0"),
        "base_min_size": str(product.get("base_min_size") or product.get("base_min_order_size") or "0"),
        "quote_min_size": str(product.get("quote_min_size") or product.get("quote_min_order_size") or "0"),
    }


def build_manual_c43_smoke_candidate(*, ticker: str, quote_size: Decimal, limit_price: Decimal) -> Dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    intent_id = f"manual-c43-smoke-{ticker.replace('-', '')}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    order_intent = {
        "intent_id": intent_id,
        "client_order_id": f"phasec-{ticker.replace('-', '')}-smoke-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "ticker": ticker,
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "size_quote": str(quote_size),
        "limit_price": str(limit_price),
        "manual_smoke_test": True,
        "requires_fresh_judge_and_risk": True,
    }
    analysis = {
        "ticker": ticker,
        "judge": {
            "decision": "approve_trade",
            "side": "BUY",
            "size_quote": str(quote_size),
            "strategy": "manual_c43_one_entry_smoke_test",
            "manual_smoke_test": True,
            "reasons": [
                "Manual C43 one-entry smoke test with explicit human acknowledgement.",
                "This is only for validating the Phase-C post-only live entry path.",
            ],
        },
        "feature_pack": {
            "decision_context": {
                "pending_order_intent": {
                    "intent_id": intent_id,
                    "ticker": ticker,
                    "status": "needs_fresh_analysis",
                    "trigger_ready": True,
                    "requires_fresh_judge_and_risk": True,
                    "manual_smoke_test": True,
                }
            }
        },
    }
    execution_plan = {
        "execution_action": "place_limit_buy",
        "read_only": True,
        "manual_smoke_test": True,
        "orderbook_summary": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "source": "manual_c43_smoke_test_explicit_limit_price",
        },
    }
    return {"analysis": analysis, "execution_plan": execution_plan, "order_intent": order_intent}


def assess_c43_smoke_preconditions(*, cfg: Any, ticker: str, quote_size: Decimal, limit_price: Decimal, submit_live: bool, human_ack: str) -> Dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    blockers: list[str] = []
    warnings: list[str] = []
    passed: list[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    max_quote = min(_cfg_dec(cfg, "phase_c_max_order_quote", "25.00"), _cfg_dec(cfg, "autonomous_max_order_quote", "25.00"), Decimal("25.00"))
    allowed = _allowed_tickers(cfg)

    require(_cfg_bool(cfg, "enable_phase_c_live_small_limit_orders", False), "phase_c_small_live_limit_orders_enabled", "phase_c_small_live_limit_orders_disabled")
    require(_cfg_bool(cfg, "enable_live_limit_orders", False), "live_limit_orders_enabled", "live_limit_orders_disabled")
    require(_cfg_bool(cfg, "enable_live_entry_orders", False), "live_entry_orders_enabled", "live_entry_orders_disabled")
    require(not _cfg_bool(cfg, "enable_live_exit_orders", False), "live_exit_orders_disabled", "live_exit_orders_enabled_forbidden")
    require(not _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False), "d3_actual_exit_submit_disabled", "d3_actual_exit_submit_enabled_forbidden")
    require(not _cfg_bool(cfg, "autonomous_allow_exits", False), "autonomous_allow_exits_disabled", "autonomous_allow_exits_enabled_forbidden")
    require(_cfg_bool(cfg, "enable_phase_c_actual_coinbase_submit", False), "phase_c_actual_coinbase_submit_enabled", "phase_c_actual_coinbase_submit_disabled")
    require(_cfg_bool(cfg, "phase_c_live_order_post_only", True), "post_only_enabled", "post_only_disabled_forbidden")
    require(bool(allowed) and ticker in allowed, "ticker_in_phase_c_allowlist", "ticker_not_in_phase_c_allowlist")
    require(quote_size > ZERO and quote_size <= max_quote, "quote_within_25_usdc_cap", "quote_missing_or_above_cap")
    require(limit_price > ZERO, "limit_price_present", "limit_price_missing")
    require(not _env_bool("REPLICATION_ENABLED", False), "replication_disabled", "replication_enabled_forbidden_for_master_only_smoke")

    if submit_live:
        require(human_ack == C43_ONE_ENTRY_SMOKE_ACK, "human_ack_ok", "human_ack_missing_or_wrong")
    else:
        warnings.append("preview_only_submit_live_false")

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": C43_ONE_ENTRY_SMOKE_PHASE,
        "ticker": ticker,
        "submit_live": bool(submit_live),
        "accepted": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "max_quote": str(max_quote),
        "safety_policy": {
            "master_only_requires_replication_disabled": True,
            "entry_only_buy_only": True,
            "live_exits_forbidden": True,
            "post_only_limit_order_only": True,
            "requires_explicit_human_ack_for_submit": True,
        },
    })


def run_c43_one_live_entry_smoke_test(
    *,
    cfg: Any,
    ticker: str,
    quote_size: Decimal,
    limit_price: Decimal,
    submit_live: bool = False,
    human_ack: str = "",
    coinbase_client: Any = None,
    order_store: Optional[OrderStore] = None,
    product_rules: Optional[Dict[str, Any]] = None,
    audit_path: str | Path = "logs/phase_c_live_submit.jsonl",
) -> Dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    preflight = assess_c43_smoke_preconditions(
        cfg=cfg,
        ticker=ticker,
        quote_size=quote_size,
        limit_price=limit_price,
        submit_live=submit_live,
        human_ack=human_ack,
    )
    candidate = build_manual_c43_smoke_candidate(ticker=ticker, quote_size=quote_size, limit_price=limit_price)

    # A hand-built smoke candidate is not evidence from the canonical
    # market-data -> LLM -> deterministic-risk chain. Keep this legacy helper
    # diagnostic-only so it cannot become a parallel BUY execution boundary.
    should_submit = False
    if submit_live:
        preflight.setdefault("blockers", []).append(
            "manual_c43_smoke_live_submit_retired_use_canonical_strategy_workflow"
        )
        preflight["accepted"] = False
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg,
        ticker=ticker,
        analysis=candidate["analysis"],
        execution_plan=candidate["execution_plan"],
        order_intent=candidate["order_intent"],
        coinbase_client=coinbase_client,
        order_store=order_store,
        submit_live=should_submit,
        product_rules=product_rules,
    )
    if submit_live and coinbase_client is None:
        preflight.setdefault("blockers", []).append("coinbase_client_not_provided")
        preflight["accepted"] = False

    final = _json_safe({
        "generated_at": _now_iso(),
        "phase": C43_ONE_ENTRY_SMOKE_PHASE,
        "ticker": ticker,
        "submit_requested": bool(submit_live),
        "preflight": preflight,
        "c43_result": result,
        "live_submission_attempted": bool(result.get("live_submission_attempted")),
        "live_order_submitted": bool(result.get("live_order_submitted")),
        "status": "smoke_ready_preview" if preflight.get("accepted") else "smoke_blocked",
        "safety_policy": {
            "does_not_enable_follower": True,
            "does_not_enable_exits": True,
            "one_entry_order_only": True,
            "post_only_limit_buy_only": True,
            "manual_smoke_live_submit_retired": True,
        },
    })
    append_phase_c_live_order_audit(audit_path, final)
    return final


__all__ = [
    "C43_ONE_ENTRY_SMOKE_ACK",
    "C43_ONE_ENTRY_SMOKE_PHASE",
    "assess_c43_smoke_preconditions",
    "build_manual_c43_smoke_candidate",
    "extract_product_rules",
    "run_c43_one_live_entry_smoke_test",
]
