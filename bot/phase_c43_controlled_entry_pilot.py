from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional

from bot.order_store import OrderStore
from bot.phase_c43_autonomous_entry_live import (
    build_phase_c43_status_report,
    count_local_phase_c_live_entry_orders,
)
from bot.phase_c43_lifecycle_governance import build_phase_c43_lifecycle_governance_report
from bot.phase_c43_lifecycle_orchestrator import build_phase_c43_lifecycle_orchestrator_report
from bot.phase_c43_one_entry_smoke_test import (
    C43_ONE_ENTRY_SMOKE_ACK,
    C43_ONE_ENTRY_SMOKE_PHASE,
    run_c43_one_live_entry_smoke_test,
)
from bot.phase_d31_lifecycle_readiness import D31_ENTRY_ARM_ACK, build_phase_d31_lifecycle_readiness_report
from bot.state_store import StateStore

CONTROLLED_ENTRY_PILOT_PHASE = "C4.4.3_controlled_entry_only_pilot_runner"
ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK = "I_UNDERSTAND_THIS_ARMS_ONE_C43_LIVE_BUY_ONLY"
ONE_SHOT_ACTUAL_ENTRY_SUBMIT_TICKER = "BTC-USDC"
ONE_SHOT_ACTUAL_ENTRY_SUBMIT_MAX_QUOTE = Decimal("10.00")
ONE_SHOT_ACTUAL_ENTRY_SUBMIT_SCOPE = "single_runner_process_only"
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
        if isinstance(value, Decimal):
            return value
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


def _clone_cfg_with(cfg: Any, **overrides: Any) -> Any:
    cloned = copy.copy(cfg)
    for key, value in overrides.items():
        try:
            setattr(cloned, key, value)
        except Exception:
            pass
    return cloned


def _safe_counts(counts: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "total_open_live_entry_orders": int(counts.get("total_open_live_entry_orders") or 0),
        "tickers": counts.get("tickers") or [],
        "orders": counts.get("orders") or [],
    }


def _pilot_next_steps(*, submit_live: bool, live_order_submitted: bool) -> list[str]:
    if live_order_submitted:
        return [
            "Zet ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT direct terug naar false voordat de service opnieuw autonoom mag draaien.",
            "Controleer state/open_orders.json met show_phase_c43_autonomous_entry_live.py.",
            "Laat lifecycle governance eerst previewen; zet Coinbase poll/apply-local pas apart en bewust aan.",
            "Live SELL/exits blijven uit tot D.3/D.4 aparte arming.",
        ]
    if submit_live:
        return [
            "Geen live order geplaatst; inspecteer blockers/warnings voordat je opnieuw probeert.",
            "Laat ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false tenzij je direct opnieuw exact één entry-only smoke-test uitvoert.",
        ]
    return [
        "Preview eerst controleren.",
        "Voor live: zet ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT tijdelijk true, gebruik --submit-live en beide exacte ACKs.",
        "Na live submit: actual submit weer false en lifecycle/status controleren.",
    ]


def build_controlled_entry_pilot_report(
    *,
    cfg: Any,
    ticker: str,
    quote_size: Decimal,
    limit_price: Decimal,
    submit_live: bool = False,
    one_shot_actual_entry_submit: bool = False,
    one_shot_arm_ack: str = "",
    c43_human_ack: str = "",
    d31_human_ack: str = "",
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    product_rules: Optional[Dict[str, Any]] = None,
    audit_path: str | Path = "logs/phase_c_live_submit.jsonl",
    simulate_actual_submit_for_preview: bool = False,
) -> Dict[str, Any]:
    """Run the controlled entry-only pilot sequence around the existing C.4.3 smoke submitter.

    This function is intentionally an operator/orchestration layer rather than a new
    trading route. It never submits directly; if submit_live=True it delegates exactly
    one BUY post-only limit order attempt to the already tested C.4.3 one-entry smoke
    submitter after readiness, governance and one-open-order guards are checked.
    """
    ticker = _normalize_ticker(ticker)
    quote_size = _to_decimal(quote_size, "0")
    limit_price = _to_decimal(limit_price, "0")
    orders = order_store or OrderStore()
    state = state_store or StateStore()

    counts_before = _safe_counts(count_local_phase_c_live_entry_orders(orders))
    local_orders_before = list(counts_before.get("orders") or [])
    one_shot_requested = bool(one_shot_actual_entry_submit)
    one_shot_blockers: list[str] = []
    one_shot_warnings: list[str] = []
    one_shot_armed_process_local = False
    cfg_for_run = cfg

    if submit_live and one_shot_requested:
        if _cfg_bool(cfg, "enable_phase_c_actual_coinbase_submit", False):
            one_shot_warnings.append("original_cfg_actual_submit_already_true_one_shot_not_needed")
        if str(one_shot_arm_ack or "").strip() != ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK:
            one_shot_blockers.append("one_shot_arm_ack_missing_or_wrong")
        if ticker != ONE_SHOT_ACTUAL_ENTRY_SUBMIT_TICKER:
            one_shot_blockers.append("one_shot_actual_entry_submit_ticker_not_btc_usdc")
        if quote_size <= ZERO or quote_size > ONE_SHOT_ACTUAL_ENTRY_SUBMIT_MAX_QUOTE:
            one_shot_blockers.append("one_shot_actual_entry_submit_quote_above_10_or_missing")
        if counts_before["total_open_live_entry_orders"] != 0:
            one_shot_blockers.append("one_shot_actual_entry_submit_requires_zero_open_c43_orders")
        if _cfg_bool(cfg, "enable_live_exit_orders", False):
            one_shot_blockers.append("one_shot_actual_entry_submit_requires_live_exit_orders_false")
        if _cfg_bool(cfg, "autonomous_allow_exits", False):
            one_shot_blockers.append("one_shot_actual_entry_submit_requires_autonomous_allow_exits_false")
        if _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False):
            one_shot_blockers.append("one_shot_actual_entry_submit_requires_d3_actual_exit_submit_false")
        if _cfg_bool(cfg, "replication_enabled", False):
            one_shot_blockers.append("one_shot_actual_entry_submit_requires_replication_disabled")
        if not one_shot_blockers:
            cfg_for_run = _clone_cfg_with(cfg, enable_phase_c_actual_coinbase_submit=True)
            one_shot_armed_process_local = True

    governance_before = build_phase_c43_lifecycle_governance_report(
        cfg=cfg_for_run,
        ticker=ticker,
        cycle_type="controlled_entry_pilot_preflight",
        source="controlled_entry_pilot",
        local_open_c43_orders=local_orders_before,
    )
    readiness = build_phase_d31_lifecycle_readiness_report(
        cfg=cfg_for_run,
        ticker=ticker,
        order_store=orders,
        state_store=state,
        require_actual_entry_submit=bool(submit_live),
        human_ack=d31_human_ack,
    )

    blockers: list[str] = []
    warnings: list[str] = []
    passed: list[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(quote_size > ZERO, "quote_size_present", "quote_size_missing_or_zero")
    require(limit_price > ZERO, "limit_price_present", "limit_price_missing_or_zero")
    require(counts_before["total_open_live_entry_orders"] == 0, "no_open_c43_orders_before_one_entry_pilot", "existing_open_c43_orders_block_one_entry_pilot")
    require(not _cfg_bool(cfg, "enable_live_exit_orders", False), "live_exit_orders_disabled", "live_exit_orders_enabled_forbidden")
    require(not _cfg_bool(cfg, "autonomous_allow_exits", False), "autonomous_exits_disabled", "autonomous_allow_exits_enabled_forbidden")
    require(not _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False), "d3_actual_exit_submit_disabled", "d3_actual_exit_submit_enabled_forbidden")
    require(not _cfg_bool(cfg, "replication_enabled", False), "config_replication_flag_not_enabled", "config_replication_enabled_review_env")
    require(bool(readiness.get("ready_for_controlled_entry_only_arming")), "d31_ready_for_controlled_entry_only_arming", "d31_not_ready_for_controlled_entry_only_arming")

    if governance_before.get("blockers"):
        blockers.append("lifecycle_governance_has_blockers")
    else:
        passed.append("lifecycle_governance_no_blockers")
    blockers.extend(one_shot_blockers)
    warnings.extend(one_shot_warnings)

    if submit_live:
        require(_cfg_bool(cfg_for_run, "enable_phase_c_actual_coinbase_submit", False), "actual_entry_submit_flag_enabled_for_this_pilot", "actual_entry_submit_flag_false_for_live_pilot")
        require(c43_human_ack == C43_ONE_ENTRY_SMOKE_ACK, "c43_human_ack_ok", "c43_human_ack_missing_or_wrong")
        require(d31_human_ack == D31_ENTRY_ARM_ACK, "d31_human_ack_ok", "d31_human_ack_missing_or_wrong")
        require(coinbase_client is not None, "coinbase_client_present_for_live_submit", "coinbase_client_missing_for_live_submit")
    else:
        warnings.append("preview_only_submit_live_false")

    cfg_for_smoke = cfg_for_run
    preview_actual_submit_simulated = False
    if not submit_live and simulate_actual_submit_for_preview and not _cfg_bool(cfg_for_run, "enable_phase_c_actual_coinbase_submit", False):
        cfg_for_smoke = _clone_cfg_with(cfg_for_run, enable_phase_c_actual_coinbase_submit=True)
        preview_actual_submit_simulated = True
        warnings.append("preview_uses_simulated_enable_phase_c_actual_coinbase_submit_true_no_env_mutation")

    should_call_smoke = not blockers or not submit_live
    smoke_report: Dict[str, Any] | None = None
    if should_call_smoke:
        smoke_report = run_c43_one_live_entry_smoke_test(
            cfg=cfg_for_smoke,
            ticker=ticker,
            quote_size=quote_size,
            limit_price=limit_price,
            submit_live=bool(submit_live and not blockers),
            human_ack=c43_human_ack,
            coinbase_client=coinbase_client if submit_live and not blockers else None,
            order_store=orders,
            product_rules=product_rules,
            audit_path=audit_path,
        )
        if smoke_report.get("status") == "smoke_blocked" and submit_live:
            blockers.append("c43_smoke_submitter_blocked")

    live_submission_attempted = bool((smoke_report or {}).get("live_submission_attempted"))
    live_order_submitted = bool((smoke_report or {}).get("live_order_submitted"))
    counts_after = _safe_counts(count_local_phase_c_live_entry_orders(orders))
    c43_status_after = build_phase_c43_status_report(cfg=cfg_for_run, ticker=ticker, order_store=orders, state_store=state)
    governance_after = build_phase_c43_lifecycle_governance_report(
        cfg=cfg_for_run,
        ticker=ticker,
        cycle_type="controlled_entry_pilot_post_submit",
        source="controlled_entry_pilot",
        local_open_c43_orders=list(counts_after.get("orders") or []),
    )
    orchestrator_preview = build_phase_c43_lifecycle_orchestrator_report(
        cfg=cfg_for_run,
        ticker=ticker,
        order_store=orders,
        state_store=state,
        coinbase_client=None,
        allow_coinbase_poll=False,
        apply_local=False,
        build_d2_plan=False,
        build_d3_preview=False,
    )

    if live_order_submitted:
        status = "controlled_entry_live_order_submitted"
    elif submit_live and blockers:
        status = "controlled_entry_blocked"
    elif submit_live:
        status = "controlled_entry_submit_requested_no_order_submitted"
    elif smoke_report and smoke_report.get("status") == "smoke_ready_preview":
        status = "controlled_entry_preview_ready"
    else:
        status = "controlled_entry_preview_review"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": CONTROLLED_ENTRY_PILOT_PHASE,
        "status": status,
        "ticker": ticker,
        "quote_size": quote_size,
        "limit_price": limit_price,
        "submit_live": bool(submit_live),
        "one_shot_actual_entry_submit_requested": one_shot_requested,
        "one_shot_actual_entry_submit_armed_process_local": one_shot_armed_process_local,
        "one_shot_actual_entry_submit_env_mutation": False,
        "one_shot_actual_entry_submit_scope": ONE_SHOT_ACTUAL_ENTRY_SUBMIT_SCOPE,
        "one_shot_actual_entry_submit_blockers": sorted(set(one_shot_blockers)),
        "preview_actual_submit_simulated": preview_actual_submit_simulated,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "passed_checks": passed,
        "ack_tokens": {
            "one_shot_arm_ack_required": ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK,
            "c43_human_ack_required": C43_ONE_ENTRY_SMOKE_ACK,
            "d31_human_ack_required": D31_ENTRY_ARM_ACK,
        },
        "counts_before": counts_before,
        "governance_before": governance_before,
        "d31_readiness": readiness,
        "smoke_report": smoke_report,
        "live_submission_attempted": live_submission_attempted,
        "live_order_submitted": live_order_submitted,
        "counts_after": counts_after,
        "c43_status_after": c43_status_after,
        "governance_after": governance_after,
        "orchestrator_preview_after": orchestrator_preview,
        "next_steps": _pilot_next_steps(submit_live=bool(submit_live), live_order_submitted=live_order_submitted),
        "safety_policy": {
            "uses_existing_c43_smoke_submitter_only": True,
            "one_entry_order_only_requires_zero_open_before_submit": True,
            "post_only_limit_buy_only": True,
            "does_not_submit_sell_orders": True,
            "does_not_cancel_on_coinbase": True,
            "does_not_enable_replication": True,
            "orchestrator_after_submit_is_preview_only": True,
            "d2_d3_not_built_by_pilot_runner": True,
        },
    })


__all__ = [
    "CONTROLLED_ENTRY_PILOT_PHASE",
    "ONE_SHOT_ACTUAL_ENTRY_SUBMIT_ACK",
    "build_controlled_entry_pilot_report",
]
