from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_multi_order_intent_preview import (
    DEFAULT_POLICY as D6_DEFAULT_POLICY,
    build_multi_order_intent_preview_report,
    build_reservation_preview,
    json_safe,
    load_json_file,
    load_recent_analysis_candidates,
)


FULL_BOT_ORCHESTRATOR_PHASE = "full_bot_orchestrator_v1"
ZERO = Decimal("0")
OPEN_ORDER_STATUSES = {"planned", "pending", "submitted", "partially_filled", "open", "active", "new", "queued", "cancel_pending", "replace_pending"}
FINAL_ORDER_STATUSES = {"filled", "done", "completed", "cancelled", "canceled", "expired", "failed", "rejected", "submit_rejected", "replaced"}

ORCHESTRATOR_POLICY: Dict[str, Any] = {
    **D6_DEFAULT_POLICY,
    "preview_only": True,
    "max_open_orders_total": 5,
    "max_quote_per_order": "20.00",
    "max_total_buy_quote_reserved": "100.00",
    "max_total_reserved_buy_quote": "100.00",
    "max_open_orders_per_ticker": 1,
    "max_new_orders_per_cycle": 2,
    "max_open_positions": 5,
    "market_orders_enabled": False,
    "sell_live_execution_enabled": False,
    "replication_enabled": False,
    "learning_to_execution_allowed": False,
    "parameter_mutation_allowed": False,
}

FUTURE_ACKS = {
    "buy_maker_entry": "EXACT_PHASE_C_BUY_MAKER_ACK_REQUIRED_IN_FUTURE",
    "pattern_near_miss_buy": "EXACT_FULL_BOT_PATTERN_BUY_ACK_REQUIRED_IN_FUTURE",
    "sell_maker_exit": "EXACT_D3_D4_SELL_EXIT_ACK_REQUIRED_IN_FUTURE",
    "market_buy": "EXACT_MARKET_BUY_EDGE_ACK_REQUIRED_IN_FUTURE",
    "market_sell": "EXACT_EMERGENCY_OR_EDGE_MARKET_SELL_ACK_REQUIRED_IN_FUTURE",
    "cancel_replace_reprice": "EXACT_D4_CANCEL_REPLACE_REPRICE_ACK_REQUIRED_IN_FUTURE",
    "lifecycle_apply": "EXACT_LIFECYCLE_RECONCILE_OR_FILL_APPLY_ACK_REQUIRED_IN_FUTURE",
    "learning_mutation": "EXACT_PARAMETER_REVIEW_AND_MUTATION_ACK_REQUIRED_IN_FUTURE",
    "replication": "EXACT_REPLICATION_ENABLEMENT_ACK_REQUIRED_IN_FUTURE",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_decimal(value: Any, default: str = "0") -> Decimal:
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


def decimal_str(value: Any) -> str:
    text = format(to_decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _orders(raw: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    data = raw if isinstance(raw, dict) else {}
    orders = data.get("orders")
    values = list(orders.values()) if isinstance(orders, dict) else orders if isinstance(orders, list) else []
    return [dict(x) for x in values if isinstance(x, dict)]


def _open_orders(raw: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for order in _orders(raw):
        status = str(order.get("status") or order.get("order_status") or "").strip().lower()
        if status in OPEN_ORDER_STATUSES or (status and status not in FINAL_ORDER_STATUSES and to_decimal(order.get("remaining_size"), "0") > ZERO):
            out.append(order)
    return out


def _order_ticker(order: Dict[str, Any]) -> str:
    return normalize_ticker(order.get("ticker") or order.get("product_id") or order.get("product"))


def _order_side(order: Dict[str, Any]) -> str:
    return str(order.get("side") or "").strip().upper()


def _open_positions(positions_state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ticker, raw in (positions_state or {}).items():
        if not isinstance(raw, dict):
            continue
        base = max(to_decimal(raw.get("bot_managed_base")), to_decimal(raw.get("position_size_base")), to_decimal(raw.get("size_base")))
        status = str(raw.get("status") or "").strip().lower()
        if base > ZERO and status not in {"closed", "closed_tiny_residual"}:
            pos = dict(raw)
            pos["ticker"] = normalize_ticker(raw.get("ticker") or ticker)
            pos["_orchestrator_base"] = decimal_str(base)
            out.append(pos)
    return out


def _action(
    action_class: str,
    *,
    classification: str,
    ticker: str = "",
    side: str = "",
    reason: str = "",
    blockers: Optional[List[str]] = None,
    ack_boundary: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return json_safe(
        {
            "action_class": action_class,
            "classification": classification,
            "ticker": normalize_ticker(ticker),
            "side": side.upper() if side else "",
            "reason": reason,
            "blockers": blockers or [],
            "live_authorized_now": classification == "live_authorized_now",
            "ack_required": classification == "ack_required",
            "preview_only": classification == "preview_only",
            "ack_boundary": ack_boundary,
            "details": details or {},
        }
    )


def _cap_blockers_for_entry(intent: Dict[str, Any], reservation: Dict[str, Any], selected_so_far: int, policy: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    ticker = normalize_ticker(intent.get("ticker"))
    quote = to_decimal(intent.get("proposed_size_quote"))
    open_count = int(reservation.get("open_order_count") or 0)
    per_ticker = int((reservation.get("open_order_count_by_ticker") or {}).get(ticker) or 0)
    reserved_quote = to_decimal(reservation.get("reserved_quote_open_buy_orders"))
    if open_count >= int(policy["max_open_orders_total"]):
        blockers.append("max_open_orders_total_reached")
    if per_ticker >= int(policy["max_open_orders_per_ticker"]):
        blockers.append("max_open_orders_per_ticker_reached")
    if selected_so_far >= int(policy["max_new_orders_per_cycle"]):
        blockers.append("max_new_orders_per_cycle_reached")
    if quote > to_decimal(policy["max_quote_per_order"]):
        blockers.append("max_quote_per_order_exceeded")
    if reserved_quote + quote > to_decimal(policy["max_total_buy_quote_reserved"]):
        blockers.append("max_total_reserved_buy_quote_exceeded")
    return blockers


def build_entry_action_candidates(d6_preview: Dict[str, Any], reservation: Dict[str, Any], policy: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rules = dict(ORCHESTRATOR_POLICY)
    rules.update(policy or {})
    actions: List[Dict[str, Any]] = []
    selected = 0
    for intent in d6_preview.get("preview_ready_intents") or []:
        cap_blockers = _cap_blockers_for_entry(intent, reservation, selected, rules)
        cls = "blocked" if cap_blockers else "preview_only"
        actions.append(
            _action(
                "pattern_intent_maker_buy",
                classification=cls,
                ticker=str(intent.get("ticker") or ""),
                side="BUY",
                reason="D.6 preview-ready maker BUY intent; dry-run only in orchestrator v1.",
                blockers=cap_blockers,
                ack_boundary=FUTURE_ACKS["pattern_near_miss_buy"],
                details={"intent": intent},
            )
        )
        selected += 0 if cap_blockers else 1

    for intent in d6_preview.get("near_miss_intents") or []:
        cap_blockers = _cap_blockers_for_entry(intent, reservation, selected, rules)
        cls = "blocked" if cap_blockers else "preview_only"
        actions.append(
            _action(
                "near_miss_maker_buy",
                classification=cls,
                ticker=str(intent.get("ticker") or ""),
                side="BUY",
                reason="Near-miss maker BUY can be selected for future live review, not live action now.",
                blockers=cap_blockers + [str(x) for x in intent.get("soft_blockers") or []],
                ack_boundary=FUTURE_ACKS["pattern_near_miss_buy"],
                details={"intent": intent},
            )
        )
        selected += 0 if cap_blockers else 1

    if not actions:
        actions.append(_action("strict_approve_trade_buy", classification="not_applicable", reason="No strict approve_trade BUY candidate was supplied to this dry-run."))
    else:
        actions.insert(
            0,
            _action(
                "strict_approve_trade_buy",
                classification="ack_required",
                side="BUY",
                reason="Only the existing Phase-C strict approve_trade route can become live-authorized later.",
                ack_boundary=FUTURE_ACKS["buy_maker_entry"],
                details={"phase_c_route_touched": False},
            ),
        )
    return actions


def build_exit_action_candidates(
    positions_state: Dict[str, Any],
    open_orders_state: Dict[str, Any],
    reservation: Dict[str, Any],
    policy: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    positions = _open_positions(positions_state)
    open_sells = [o for o in _open_orders(open_orders_state) if _order_side(o) == "SELL"]
    actions: List[Dict[str, Any]] = []
    if not positions:
        return [
            _action("take_profit_sell_preview", classification="not_applicable", reason="No open local bot-managed position with base available."),
            _action("stop_loss_sell_preview", classification="not_applicable", reason="No open local bot-managed position with base available."),
            _action("trailing_sell_preview", classification="not_applicable", reason="No open local bot-managed position with base available."),
            _action("emergency_market_sell_preview", classification="not_applicable", reason="No open local bot-managed position with base available."),
            _action("reduce_position_preview", classification="not_applicable", reason="No open local bot-managed position with base available."),
        ]
    for pos in positions:
        ticker = normalize_ticker(pos.get("ticker"))
        base = to_decimal(pos.get("_orchestrator_base"))
        reserved = to_decimal((reservation.get("reserved_base_sell_by_ticker") or {}).get(ticker))
        available = max(ZERO, base - reserved)
        duplicate = any(_order_ticker(o) == ticker for o in open_sells)
        blockers = []
        if base <= ZERO:
            blockers.append("sell_base_missing")
        if available <= ZERO:
            blockers.append("sell_available_base_after_reservations_zero")
        if duplicate:
            blockers.append("duplicate_open_sell_exit_order")
        cls = "blocked" if blockers else "preview_only"
        detail = {"position_base": decimal_str(base), "reserved_sell_base": decimal_str(reserved), "available_base": decimal_str(available), "position_status": pos.get("status")}
        for action_class, reason in [
            ("take_profit_sell_preview", "Preview D.3 take-profit maker SELL for open position."),
            ("stop_loss_sell_preview", "Preview D.3 stop-loss maker SELL for open position."),
            ("trailing_sell_preview", "Preview D.4 trailing SELL management for open position."),
            ("emergency_market_sell_preview", "Preview emergency market SELL; market orders remain disabled."),
            ("reduce_position_preview", "Preview partial reduce-only SELL for exposure management."),
        ]:
            actions.append(_action(action_class, classification=cls, ticker=ticker, side="SELL", reason=reason, blockers=blockers, ack_boundary=FUTURE_ACKS["sell_maker_exit"], details=detail))
    return actions


def build_market_action_candidates(d6_preview: Dict[str, Any], positions_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    top_buy = (d6_preview.get("top_near_miss_intents") or d6_preview.get("near_miss_intents") or [])[:3]
    for intent in top_buy:
        actions.append(
            _action(
                "market_buy_candidate_preview",
                classification="preview_only",
                ticker=str(intent.get("ticker") or ""),
                side="BUY",
                reason="Market BUY would require expected move greater than taker fee, spread, slippage and liquidity cost; preview only.",
                blockers=["market_orders_disabled", "future_market_buy_ack_required"],
                ack_boundary=FUTURE_ACKS["market_buy"],
                details={"maker_reference_intent": intent, "policy": "positive_expected_edge_after_costs_and_urgency_required"},
            )
        )
    for pos in _open_positions(positions_state):
        actions.append(
            _action(
                "emergency_market_sell_preview",
                classification="preview_only",
                ticker=str(pos.get("ticker") or ""),
                side="SELL",
                reason="Market SELL only rational for emergency/risk-stop or positive edge after taker costs; preview only.",
                blockers=["market_orders_disabled", "live_sell_disabled", "future_market_sell_ack_required"],
                ack_boundary=FUTURE_ACKS["market_sell"],
                details={"position_base": pos.get("_orchestrator_base")},
            )
        )
    if not actions:
        actions.append(_action("market_buy_candidate_preview", classification="not_applicable", reason="No market action candidate has enough dry-run context."))
        actions.append(_action("emergency_market_sell_preview", classification="not_applicable", reason="No open position for emergency market SELL preview."))
    return actions


def build_order_management_candidates(open_orders_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    open_orders = _open_orders(open_orders_state)
    if not open_orders:
        return [
            _action("cancel_stale_entry_preview", classification="not_applicable", reason="No open entry orders."),
            _action("cancel_stale_exit_preview", classification="not_applicable", reason="No open exit orders."),
            _action("replace_entry_preview", classification="not_applicable", reason="No open entry orders."),
            _action("replace_exit_preview", classification="not_applicable", reason="No open exit orders."),
            _action("reprice_maker_order_preview", classification="not_applicable", reason="No open maker orders."),
        ]
    actions: List[Dict[str, Any]] = []
    for order in open_orders:
        side = _order_side(order)
        ticker = _order_ticker(order)
        if side == "BUY":
            classes = ["cancel_stale_entry_preview", "replace_entry_preview", "reprice_maker_order_preview"]
            ack = FUTURE_ACKS["buy_maker_entry"]
        elif side == "SELL":
            classes = ["cancel_stale_exit_preview", "replace_exit_preview", "reprice_maker_order_preview"]
            ack = FUTURE_ACKS["cancel_replace_reprice"]
        else:
            classes = ["reprice_maker_order_preview"]
            ack = FUTURE_ACKS["cancel_replace_reprice"]
        for action_class in classes:
            actions.append(_action(action_class, classification="preview_only", ticker=ticker, side=side, reason="Open-order management dry-run only.", blockers=["future_cancel_replace_ack_required"], ack_boundary=ack, details={"order": order}))
    return actions


def build_lifecycle_candidates(open_orders_state: Dict[str, Any]) -> List[Dict[str, Any]]:
    open_orders = _open_orders(open_orders_state)
    if not open_orders:
        return [
            _action("lifecycle_reconcile_preview", classification="not_applicable", reason="No open order lifecycle to reconcile."),
            _action("fill_apply_preview", classification="not_applicable", reason="No fill evidence supplied and no active lifecycle."),
        ]
    return [
        _action("lifecycle_reconcile_preview", classification="preview_only", reason="Readonly lifecycle reconciliation would be considered; no polling in this tool.", blockers=["coinbase_poll_not_attempted"], ack_boundary=FUTURE_ACKS["lifecycle_apply"], details={"open_order_count": len(open_orders)}),
        _action("fill_apply_preview", classification="ack_required", reason="Any fill apply requires valid terminal/fill evidence plus exact ACK.", blockers=["fill_evidence_not_supplied"], ack_boundary=FUTURE_ACKS["lifecycle_apply"], details={"open_order_count": len(open_orders)}),
    ]


def build_learning_observation_candidates() -> List[Dict[str, Any]]:
    return [
        _action("learning_observation_preview", classification="preview_only", reason="Learning may observe/report outcomes only; no execution linkage.", blockers=["learning_to_execution_disabled"], ack_boundary=FUTURE_ACKS["learning_mutation"]),
        _action("performance_evaluation_preview", classification="preview_only", reason="Performance evaluation may rank evidence for review only; no parameter mutation.", blockers=["parameter_mutation_disabled"], ack_boundary=FUTURE_ACKS["learning_mutation"]),
    ]


def build_live_authorization_matrix() -> Dict[str, Dict[str, Any]]:
    return {
        "BUY maker entry": {"classification": "ack_required", "current_status": "Phase-C path remains required; no submit in this sprint.", "future_ack": FUTURE_ACKS["buy_maker_entry"]},
        "Pattern/near-miss BUY": {"classification": "preview_only", "current_status": "Dry-run only.", "future_ack": FUTURE_ACKS["pattern_near_miss_buy"]},
        "SELL maker exit": {"classification": "preview_only", "current_status": "Live exits disabled.", "future_ack": FUTURE_ACKS["sell_maker_exit"]},
        "Market BUY": {"classification": "preview_only", "current_status": "Market orders disabled.", "future_ack": FUTURE_ACKS["market_buy"]},
        "Market SELL": {"classification": "preview_only", "current_status": "Market orders and autonomous SELL disabled.", "future_ack": FUTURE_ACKS["market_sell"]},
        "Cancel/replace/reprice": {"classification": "preview_only", "current_status": "D.4 cancel/replace remains ACK-gated.", "future_ack": FUTURE_ACKS["cancel_replace_reprice"]},
        "Lifecycle apply": {"classification": "ack_required", "current_status": "Requires evidence plus one-shot ACK; not performed here.", "future_ack": FUTURE_ACKS["lifecycle_apply"]},
        "Learning": {"classification": "preview_only", "current_status": "Observe/report only.", "future_ack": FUTURE_ACKS["learning_mutation"]},
        "Replication": {"classification": "blocked", "current_status": "Disabled.", "future_ack": FUTURE_ACKS["replication"]},
        "Parameter mutation": {"classification": "blocked", "current_status": "Disabled.", "future_ack": FUTURE_ACKS["learning_mutation"]},
    }


def build_exposure_summary(positions_state: Dict[str, Any], reservation_summary: Dict[str, Any]) -> Dict[str, Any]:
    positions = _open_positions(positions_state)
    by_ticker = {}
    for pos in positions:
        ticker = normalize_ticker(pos.get("ticker"))
        by_ticker[ticker] = {
            "position_base": pos.get("_orchestrator_base"),
            "position_quote_hint": decimal_str(to_decimal(pos.get("position_size_quote"))),
            "reserved_exit_base": decimal_str(to_decimal((reservation_summary.get("reserved_base_sell_by_ticker") or {}).get(ticker))),
            "status": pos.get("status"),
        }
    blockers = []
    if len(positions) >= int(ORCHESTRATOR_POLICY["max_open_positions"]):
        blockers.append("max_open_positions_reached")
    return {"open_position_count": len(positions), "max_open_positions": ORCHESTRATOR_POLICY["max_open_positions"], "positions_by_ticker": by_ticker, "blockers": blockers}


def build_full_bot_orchestrator_report(
    *,
    d6_preview_report: Optional[Dict[str, Any]] = None,
    candidates: Optional[Iterable[Dict[str, Any]]] = None,
    open_orders_state: Optional[Dict[str, Any]] = None,
    positions_state: Optional[Dict[str, Any]] = None,
    source_paths: Optional[Iterable[str | Path]] = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rules = dict(ORCHESTRATOR_POLICY)
    rules.update(policy or {})
    open_orders_state = open_orders_state if isinstance(open_orders_state, dict) else {"orders": {}}
    positions_state = positions_state if isinstance(positions_state, dict) else {}
    if d6_preview_report is None:
        d6_preview_report = build_multi_order_intent_preview_report(
            candidates=list(candidates or []),
            open_orders_state=open_orders_state,
            positions_state=positions_state,
            policy=rules,
            source_paths=source_paths,
            selected_tests_summary={"selected_tests_classification": "OK"},
        )
    reservation = build_reservation_preview(open_orders_state=open_orders_state, positions_state=positions_state, quote_available="100", policy=rules)
    entry = build_entry_action_candidates(d6_preview_report, reservation, rules)
    exit_actions = build_exit_action_candidates(positions_state, open_orders_state, reservation, rules)
    market = build_market_action_candidates(d6_preview_report, positions_state)
    order_mgmt = build_order_management_candidates(open_orders_state)
    lifecycle = build_lifecycle_candidates(open_orders_state)
    learning = build_learning_observation_candidates()
    exposure = build_exposure_summary(positions_state, reservation)

    selected = [a for a in entry + exit_actions + market + order_mgmt if a["classification"] == "preview_only"][: int(rules["max_new_orders_per_cycle"])]
    blockers: List[str] = []
    warnings: List[str] = ["full_function_dry_run_only", "no_live_actions_authorized_by_orchestrator_v1"]
    blockers.extend(str(x) for x in reservation.get("blockers") or [])
    blockers.extend(str(x) for x in exposure.get("blockers") or [])
    if d6_preview_report.get("classification") == "WATCH":
        warnings.append("upstream_d6_preview_watch")

    report = {
        "generated_at": now_iso(),
        "phase": FULL_BOT_ORCHESTRATOR_PHASE,
        "status": "full_function_dry_run_ready",
        "classification": "WATCH",
        "full_function_dry_run": True,
        "live_order_submit_attempted": False,
        "live_cancel_attempted": False,
        "live_replace_attempted": False,
        "market_order_attempted": False,
        "sell_order_attempted": False,
        "state_write_performed": False,
        "coinbase_write_attempted": False,
        "coinbase_call_attempted": False,
        "strict_approve_trade_route_touched": False,
        "phase_c_strict_approve_route_remains_untouched": True,
        "d3_d4_live_exit_gates_remain_untouched": True,
        "policy": rules,
        "entry_action_candidates": entry,
        "exit_action_candidates": exit_actions,
        "market_action_candidates": market,
        "order_management_candidates": order_mgmt,
        "lifecycle_candidates": lifecycle,
        "learning_observation_candidates": learning,
        "selected_actions_for_future_live_review": selected,
        "live_authorization_matrix": build_live_authorization_matrix(),
        "reservation_summary": reservation,
        "exposure_summary": exposure,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "exact_future_acks_required": FUTURE_ACKS,
        "next_safe_operator_decision": "Review this dry-run report, then choose an ACK-gated tiny live sprint that enables only maker BUY entries through existing Phase-C first.",
        "d6_preview_summary": {
            "status": d6_preview_report.get("status"),
            "classification": d6_preview_report.get("classification"),
            "total_candidates": d6_preview_report.get("total_candidates"),
            "preview_ready_intent_count": d6_preview_report.get("preview_ready_intent_count"),
            "near_miss_intent_count": d6_preview_report.get("near_miss_intent_count"),
            "top_near_miss_intents": d6_preview_report.get("top_near_miss_intents") or [],
        },
        "safety_flags": {
            "preview_only": True,
            "market_orders_enabled": False,
            "sell_live_execution_enabled": False,
            "replication_enabled": False,
            "learning_to_execution_allowed": False,
            "parameter_mutation_allowed": False,
        },
        "input_hashes": {},
    }
    for raw in source_paths or []:
        path = Path(raw)
        if path.exists() and path.is_file():
            report["input_hashes"][str(path)] = sha256_file(path)
    return json_safe(report)


def render_full_bot_orchestrator_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Full Bot Orchestrator v1",
        "",
        "Full-function dry-run/report layer. No Coinbase writes, no submits, no cancels, no replaces, no market orders, no SELL execution and no trading-state writes.",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('status')}`",
        f"- classification: `{report.get('classification')}`",
        f"- full_function_dry_run: `{report.get('full_function_dry_run')}`",
        f"- live_order_submit_attempted: `{report.get('live_order_submit_attempted')}`",
        f"- live_cancel_attempted: `{report.get('live_cancel_attempted')}`",
        f"- live_replace_attempted: `{report.get('live_replace_attempted')}`",
        f"- market_order_attempted: `{report.get('market_order_attempted')}`",
        f"- sell_order_attempted: `{report.get('sell_order_attempted')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        "",
        "## D.6 Summary",
        "",
        "```json",
        json.dumps(report.get("d6_preview_summary"), indent=2, sort_keys=True),
        "```",
        "",
        "## Reservation Summary",
        "",
        "```json",
        json.dumps(report.get("reservation_summary"), indent=2, sort_keys=True),
        "```",
        "",
        "## Exposure Summary",
        "",
        "```json",
        json.dumps(report.get("exposure_summary"), indent=2, sort_keys=True),
        "```",
        "",
        "## Action Counts",
        "",
    ]
    for key in [
        "entry_action_candidates",
        "exit_action_candidates",
        "market_action_candidates",
        "order_management_candidates",
        "lifecycle_candidates",
        "learning_observation_candidates",
        "selected_actions_for_future_live_review",
    ]:
        lines.append(f"- {key}: `{len(report.get(key) or [])}`")
    lines.extend(["", "## Live Authorization Matrix", "", "```json", json.dumps(report.get("live_authorization_matrix"), indent=2, sort_keys=True), "```", ""])
    lines.extend(["## Future ACKs", "", "```json", json.dumps(report.get("exact_future_acks_required"), indent=2, sort_keys=True), "```", ""])
    lines.extend(["## Next Safe Operator Decision", "", str(report.get("next_safe_operator_decision") or ""), ""])
    return "\n".join(lines)


def load_latest_d6_preview(root: Path) -> Optional[Dict[str, Any]]:
    reports = sorted((root / "reports" / "d6").glob("d6-multi-order-intent-preview-calibrated-*.json"), reverse=True)
    reports += sorted((root / "reports" / "d6").glob("d6-multi-order-intent-preview-*.json"), reverse=True)
    for path in reports:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("phase") == "D6_multi_order_intent_preview_v1":
            return payload
    return None


def load_or_build_d6_preview(root: Path, *, analysis_log: str = "logs/analysis.jsonl", max_analysis_lines: int = 80) -> Dict[str, Any]:
    latest = load_latest_d6_preview(root)
    if latest is not None:
        return latest
    open_orders = load_json_file(root / "state/open_orders.json")
    positions = load_json_file(root / "state/positions.json")
    candidates = load_recent_analysis_candidates(root / analysis_log, max_lines=max_analysis_lines)
    return build_multi_order_intent_preview_report(candidates=candidates, open_orders_state=open_orders, positions_state=positions, source_paths=[root / analysis_log])


__all__ = [
    "FULL_BOT_ORCHESTRATOR_PHASE",
    "FUTURE_ACKS",
    "ORCHESTRATOR_POLICY",
    "build_entry_action_candidates",
    "build_exit_action_candidates",
    "build_full_bot_orchestrator_report",
    "build_live_authorization_matrix",
    "build_market_action_candidates",
    "build_order_management_candidates",
    "render_full_bot_orchestrator_markdown",
]
