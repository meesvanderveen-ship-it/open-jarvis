from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_replication_lifecycle_schema_v1 import SCHEMA_VERSION, validate_lifecycle_event_v1


PHASE = "replication_paper_lifecycle_simulator_v1"


@dataclass
class PaperLifecycleConfig:
    allowed_tickers: List[str] = field(default_factory=lambda: ["BTC-USDC"])
    max_notional_quote: Decimal = Decimal("10")
    max_open_orders: int = 1
    quote_balance: Decimal = Decimal("100")
    base_balances: Dict[str, Decimal] = field(default_factory=lambda: {"BTC-USDC": Decimal("0")})
    min_notional_quote: Decimal = Decimal("1")
    stop_now_blocks_transitions: bool = True


def _dec(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _event_key(event: Dict[str, Any]) -> str:
    return "|".join(
        [
            str(event.get("source_bot") or ""),
            str(event.get("schema_version") or ""),
            str(event.get("event_id") or ""),
        ]
    )


def _order_id(event: Dict[str, Any]) -> str:
    order = event.get("order") if isinstance(event.get("order"), dict) else {}
    return str(order.get("order_id") or order.get("client_order_id") or event.get("event_id") or "")


def _position_id(event: Dict[str, Any], ticker: str) -> str:
    position = event.get("position") if isinstance(event.get("position"), dict) else {}
    return str(position.get("position_id") or position.get("id") or f"paper-{ticker}")


def _notional_from_order(order: Dict[str, Any]) -> Decimal:
    for key in ("notional_quote", "requested_size_quote", "quote_size", "size_quote"):
        value = _dec(order.get(key))
        if value > 0:
            return value
    price = _dec(order.get("limit_price") or order.get("price"))
    base = _dec(order.get("base_size") or order.get("size_base"))
    return price * base


def _base_from_fill(fill: Dict[str, Any]) -> Decimal:
    for key in ("base_size", "filled_base", "filled_size_base", "cumulative_filled_base"):
        value = _dec(fill.get(key))
        if value > 0:
            return value
    return Decimal("0")


def _quote_from_fill(fill: Dict[str, Any]) -> Decimal:
    for key in ("quote_size", "filled_quote", "filled_size_quote", "notional_quote"):
        value = _dec(fill.get(key))
        if value > 0:
            return value
    price = _dec(fill.get("avg_price") or fill.get("price"))
    return price * _base_from_fill(fill)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


class PaperLifecycleSimulator:
    def __init__(self, config: Optional[PaperLifecycleConfig] = None) -> None:
        self.config = config or PaperLifecycleConfig()
        self.seen_event_ids: set[str] = set()
        self.paper_decisions: List[Dict[str, Any]] = []
        self.paper_orders: Dict[str, Dict[str, Any]] = {}
        self.paper_positions: Dict[str, Dict[str, Any]] = {}
        self.paper_d2_plans: Dict[str, Dict[str, Any]] = {}
        self.paper_d3_previews: Dict[str, Dict[str, Any]] = {}
        self.paper_governance_status: List[Dict[str, Any]] = []
        self.paper_metrics: List[Dict[str, Any]] = []
        self.fill_evidence: Dict[str, Dict[str, Any]] = {}
        self.rejected_events: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        self.blockers: List[str] = []
        self.processed_events: List[Dict[str, Any]] = []
        self.live_order_attempted = False
        self.coinbase_call_attempted = False
        self.state_write_performed = False
        self.stop_now_active = False

    def _reject(self, event: Dict[str, Any], reason: str, *, errors: Optional[List[str]] = None) -> Dict[str, Any]:
        row = {
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "ticker": event.get("ticker"),
            "status": "rejected",
            "reason": reason,
            "errors": errors or [],
        }
        self.rejected_events.append(row)
        self.blockers.append(reason)
        return row

    def _warn(self, reason: str) -> None:
        if reason not in self.warnings:
            self.warnings.append(reason)

    def _open_order_count(self, ticker: str) -> int:
        return sum(
            1
            for order in self.paper_orders.values()
            if order.get("ticker") == ticker and str(order.get("status") or "").lower() in {"open", "submitted", "partial"}
        )

    def _paper_position_base(self, ticker: str) -> Decimal:
        total = Decimal("0")
        for position in self.paper_positions.values():
            if position.get("ticker") == ticker:
                total += _dec(position.get("base_size"))
        return total

    def _precheck(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        valid, errors, effect = validate_lifecycle_event_v1(event)
        if effect.get("live_order_action") is True:
            self.live_order_attempted = True
        if not valid:
            return self._reject(event, "schema_validation_failed", errors=errors)

        key = _event_key(event)
        if key in self.seen_event_ids:
            return {
                "event_id": event.get("event_id"),
                "event_type": event.get("event_type"),
                "ticker": event.get("ticker"),
                "status": "duplicate_ignored",
            }

        ticker = str(event.get("ticker") or "")
        if ticker not in self.config.allowed_tickers:
            self.seen_event_ids.add(key)
            return self._reject(event, "unsupported_ticker")

        event_type = str(event.get("event_type") or "")
        if self.stop_now_active and self.config.stop_now_blocks_transitions and event_type not in {"governance_status", "d5_execution_metric"}:
            self.seen_event_ids.add(key)
            return self._reject(event, "stop_now_active_blocks_transition")

        self.seen_event_ids.add(key)
        return None

    def apply_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        event = deepcopy(event)
        precheck = self._precheck(event)
        if precheck is not None:
            self.processed_events.append(precheck)
            return precheck

        event_type = str(event.get("event_type") or "")
        handler = getattr(self, f"_apply_{event_type}", None)
        if handler is None:
            result = self._reject(event, "unsupported_event_handler")
        else:
            result = handler(event)
        self.processed_events.append(result)
        return result

    def apply_events(self, events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        for event in events:
            self.apply_event(event)
        return self.report()

    def _apply_decision(self, event: Dict[str, Any]) -> Dict[str, Any]:
        self.paper_decisions.append(event)
        return {"event_id": event.get("event_id"), "event_type": "decision", "status": "stored_paper_decision"}

    def _apply_c4_entry_order(self, event: Dict[str, Any]) -> Dict[str, Any]:
        ticker = str(event.get("ticker") or "")
        order = dict(event.get("order") or {})
        order_id = _order_id(event)
        notional = _notional_from_order(order)
        if notional <= 0:
            return self._reject(event, "entry_order_notional_missing_or_zero")
        if notional < self.config.min_notional_quote:
            return self._reject(event, "entry_order_below_min_notional")
        if notional > self.config.max_notional_quote:
            return self._reject(event, "entry_order_above_max_notional")
        if self._open_order_count(ticker) >= self.config.max_open_orders and order_id not in self.paper_orders:
            return self._reject(event, "max_open_paper_orders_exceeded")
        if notional > self.config.quote_balance:
            return self._reject(event, "paper_quote_balance_insufficient")

        self.paper_orders[order_id] = {
            **order,
            "order_id": order_id,
            "ticker": ticker,
            "status": str(order.get("status") or "open").lower(),
            "notional_quote": str(notional),
            "paper_only": True,
        }
        return {"event_id": event.get("event_id"), "event_type": "c4_entry_order", "status": "paper_order_upserted", "order_id": order_id}

    def _apply_c4_terminal_order(self, event: Dict[str, Any]) -> Dict[str, Any]:
        ticker = str(event.get("ticker") or "")
        order = dict(event.get("order") or {})
        fill = dict(event.get("fill") or {})
        order_id = _order_id(event)
        terminal_status = str(order.get("status") or fill.get("status") or "").lower()
        existing = self.paper_orders.get(order_id, {"order_id": order_id, "ticker": ticker, "paper_only": True})
        existing.update(order)
        existing["status"] = terminal_status or existing.get("status", "terminal")
        self.paper_orders[order_id] = existing

        if terminal_status in {"rejected", "submit_rejected", "cancelled", "canceled", "expired"}:
            return {"event_id": event.get("event_id"), "event_type": "c4_terminal_order", "status": "terminal_no_position", "order_id": order_id}

        if terminal_status not in {"filled", "partial", "partially_filled"}:
            self._warn(f"unknown_terminal_status:{terminal_status or 'missing'}")
            return {"event_id": event.get("event_id"), "event_type": "c4_terminal_order", "status": "terminal_observed", "order_id": order_id}

        base = _base_from_fill(fill)
        quote = _quote_from_fill(fill)
        if base <= 0:
            return self._reject(event, "terminal_fill_base_missing_or_zero")

        self.fill_evidence[order_id] = {
            **fill,
            "order_id": order_id,
            "ticker": ticker,
            "base_size": str(base),
            "quote_size": str(quote),
            "terminal_status": terminal_status,
            "paper_only": True,
        }
        position_id = f"paper-{ticker}"
        current = self.paper_positions.get(position_id, {"position_id": position_id, "ticker": ticker, "base_size": "0", "paper_only": True})
        current["base_size"] = str(_dec(current.get("base_size")) + base)
        current["quote_size"] = str(_dec(current.get("quote_size")) + quote)
        current["source_order_id"] = order_id
        current["status"] = "paper_open"
        self.paper_positions[position_id] = current
        self.config.base_balances[ticker] = self.config.base_balances.get(ticker, Decimal("0")) + base
        return {"event_id": event.get("event_id"), "event_type": "c4_terminal_order", "status": "paper_fill_position_updated", "order_id": order_id}

    def _apply_d1_fill_to_position(self, event: Dict[str, Any]) -> Dict[str, Any]:
        ticker = str(event.get("ticker") or "")
        fill = dict(event.get("fill") or {})
        order_id = str(fill.get("order_id") or fill.get("client_order_id") or "")
        if order_id and order_id not in self.fill_evidence:
            self._warn("d1_missing_prior_fill_evidence")
            return self._reject(event, "d1_missing_prior_fill_evidence")
        if not order_id and not self.fill_evidence:
            self._warn("d1_missing_prior_fill_evidence")
            return self._reject(event, "d1_missing_prior_fill_evidence")

        position = dict(event.get("position") or {})
        position_id = _position_id(event, ticker)
        base = _dec(position.get("base_size") or fill.get("base_size"))
        if base <= 0:
            base = self._paper_position_base(ticker)
        self.paper_positions[position_id] = {
            **position,
            "position_id": position_id,
            "ticker": ticker,
            "base_size": str(base),
            "paper_only": True,
            "status": str(position.get("status") or "paper_open"),
        }
        return {"event_id": event.get("event_id"), "event_type": "d1_fill_to_position", "status": "paper_position_upserted", "position_id": position_id}

    def _apply_d2_position_plan(self, event: Dict[str, Any]) -> Dict[str, Any]:
        ticker = str(event.get("ticker") or "")
        plan = dict(event.get("plan") or {})
        plan_id = str(plan.get("plan_fingerprint") or plan.get("plan_id") or event.get("event_id"))
        self.paper_d2_plans[plan_id] = {**plan, "ticker": ticker, "paper_only": True, "exit_authorized": False}
        return {"event_id": event.get("event_id"), "event_type": "d2_position_plan", "status": "paper_plan_stored", "plan_id": plan_id}

    def _apply_d3_exit_preview(self, event: Dict[str, Any]) -> Dict[str, Any]:
        preview = dict(event.get("exit_preview") or {})
        preview_id = str(preview.get("preview_id") or event.get("event_id"))
        self.paper_d3_previews[preview_id] = {**preview, "ticker": event.get("ticker"), "paper_only": True, "live_exit_authorized": False}
        return {"event_id": event.get("event_id"), "event_type": "d3_exit_preview", "status": "paper_preview_stored", "preview_id": preview_id}

    def _apply_d3_live_exit_intent(self, event: Dict[str, Any]) -> Dict[str, Any]:
        intent = dict(event.get("exit_intent") or {})
        ticker = str(event.get("ticker") or "")
        requested_base = _dec(intent.get("base_size") or intent.get("requested_base_size"))
        available_base = self._paper_position_base(ticker)
        if requested_base > available_base:
            self.blockers.append("no_oversell_check_failed")
        self.blockers.append("d3_live_exit_intent_requires_separate_follower_ack")
        self._warn("d3_live_exit_intent_observe_only")
        return {"event_id": event.get("event_id"), "event_type": "d3_live_exit_intent", "status": "blocked_observe_only"}

    def _apply_d4_cancel_replace_trailing(self, event: Dict[str, Any]) -> Dict[str, Any]:
        self.blockers.append("d4_cancel_replace_requires_separate_follower_ack")
        self._warn("d4_cancel_replace_observe_only")
        return {"event_id": event.get("event_id"), "event_type": "d4_cancel_replace_trailing", "status": "blocked_observe_only"}

    def _apply_d5_execution_metric(self, event: Dict[str, Any]) -> Dict[str, Any]:
        self.paper_metrics.append(event)
        return {"event_id": event.get("event_id"), "event_type": "d5_execution_metric", "status": "metric_stored"}

    def _apply_governance_status(self, event: Dict[str, Any]) -> Dict[str, Any]:
        status = dict(event.get("status") or {})
        classification = str(status.get("classification") or (event.get("governance") or {}).get("classification") or "").upper()
        self.paper_governance_status.append(event)
        if classification == "STOP_NOW":
            self.stop_now_active = True
            self.blockers.append("governance_stop_now_active")
        elif classification == "WATCH":
            self._warn("governance_watch_active")
        return {"event_id": event.get("event_id"), "event_type": "governance_status", "status": "governance_stored", "classification": classification}

    def report(self) -> Dict[str, Any]:
        return _json_safe({
            "generated_at": now_iso(),
            "phase": PHASE,
            "report_mode": "read_only_follower_paper_lifecycle_simulator",
            "schema_version": SCHEMA_VERSION,
            "paper_lifecycle_simulator_ready": True,
            "follower_ready_for_paper_lifecycle_test": True,
            "follower_buy_ready": False,
            "follower_sell_ready": False,
            "lifecycle_parity_ready": False,
            "follower_ready_for_live": False,
            "live_order_attempted": self.live_order_attempted,
            "coinbase_call_attempted": self.coinbase_call_attempted,
            "state_write_performed": self.state_write_performed,
            "summary": {
                "processed_event_count": len(self.processed_events),
                "unique_event_count": len(self.seen_event_ids),
                "duplicate_ignored_count": sum(1 for row in self.processed_events if row.get("status") == "duplicate_ignored"),
                "rejected_event_count": len(self.rejected_events),
                "paper_order_count": len(self.paper_orders),
                "paper_position_count": len(self.paper_positions),
                "paper_d2_plan_count": len(self.paper_d2_plans),
                "paper_d3_preview_count": len(self.paper_d3_previews),
                "paper_metric_count": len(self.paper_metrics),
                "blocker_count": len(self.blockers),
                "warning_count": len(self.warnings),
            },
            "paper_state": {
                "seen_event_ids": sorted(self.seen_event_ids),
                "paper_decisions": self.paper_decisions,
                "paper_orders": self.paper_orders,
                "paper_positions": self.paper_positions,
                "paper_d2_plans": self.paper_d2_plans,
                "paper_d3_previews": self.paper_d3_previews,
                "paper_governance_status": self.paper_governance_status,
                "paper_metrics": self.paper_metrics,
                "fill_evidence": self.fill_evidence,
                "quote_balance": str(self.config.quote_balance),
                "base_balances": self.config.base_balances,
            },
            "processed_events": self.processed_events,
            "rejected_events": self.rejected_events,
            "warnings": self.warnings,
            "blockers": self.blockers,
            "safety_policy": {
                "paper_only": True,
                "d3_live_exit_intent_executes_by_default": False,
                "d4_cancel_replace_executes_by_default": False,
                "unknown_events_fail_closed": True,
                "unsupported_tickers_fail_closed": True,
                "max_notional_enforced": True,
                "max_open_orders_enforced": True,
                "no_oversell_policy_represented": True,
                "learning_to_execution_enabled": False,
                "parameter_mutation_allowed": False,
            },
            **d6_metric_safety_flags(),
        })


def _gov(classification: str = "OK") -> Dict[str, Any]:
    return {
        "classification": classification,
        "follower_default_mode": "paper_only",
        "live_action_authorized": False,
    }


def demo_fixture_events() -> List[Dict[str, Any]]:
    return [
        {
            "event_id": "demo-001-decision",
            "event_type": "decision",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "decision": "approve_trade",
            "side": "BUY",
            "governance": _gov(),
        },
        {
            "event_id": "demo-002-entry",
            "event_type": "c4_entry_order",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "order": {"order_id": "paper-entry-1", "side": "BUY", "status": "open", "notional_quote": "9.50"},
            "governance": _gov(),
        },
        {
            "event_id": "demo-003-terminal-fill",
            "event_type": "c4_terminal_order",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "order": {"order_id": "paper-entry-1", "side": "BUY", "status": "filled"},
            "fill": {"order_id": "paper-entry-1", "base_size": "0.000095", "quote_size": "9.50", "avg_price": "100000"},
            "governance": _gov(),
        },
        {
            "event_id": "demo-004-d1",
            "event_type": "d1_fill_to_position",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "fill": {"order_id": "paper-entry-1", "base_size": "0.000095", "quote_size": "9.50"},
            "position": {"position_id": "paper-BTC-USDC", "base_size": "0.000095", "status": "paper_open"},
            "governance": _gov(),
        },
        {
            "event_id": "demo-005-d2",
            "event_type": "d2_position_plan",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "position": {"position_id": "paper-BTC-USDC"},
            "plan": {"plan_fingerprint": "demo-plan-1", "take_profit_count": 1},
            "governance": _gov(),
        },
        {
            "event_id": "demo-006-d3-preview",
            "event_type": "d3_exit_preview",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "position": {"position_id": "paper-BTC-USDC"},
            "exit_preview": {"preview_id": "demo-preview-1", "side": "SELL", "base_size": "0.00005", "submit_live": False},
            "governance": _gov(),
        },
        {
            "event_id": "demo-007-d3-live-intent",
            "event_type": "d3_live_exit_intent",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "position": {"position_id": "paper-BTC-USDC"},
            "exit_intent": {"side": "SELL", "base_size": "0.00005", "submit_live": False},
            "governance": _gov("WATCH"),
        },
        {
            "event_id": "demo-008-d4",
            "event_type": "d4_cancel_replace_trailing",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "replace_intent": {"cancel_live": False, "submit_live": False, "reason": "paper_trailing_preview"},
            "governance": _gov("WATCH"),
        },
        {
            "event_id": "demo-009-d5",
            "event_type": "d5_execution_metric",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "metric": {"name": "paper_fill_latency_ms", "value": 0},
            "governance": _gov(),
        },
        {
            "event_id": "demo-010-governance",
            "event_type": "governance_status",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "status": {"classification": "OK", "reason": "demo_sequence_complete"},
            "governance": _gov(),
        },
        {
            "event_id": "demo-002-entry",
            "event_type": "c4_entry_order",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "order": {"order_id": "paper-entry-1", "side": "BUY", "status": "open", "notional_quote": "9.50"},
            "governance": _gov(),
        },
        {
            "event_id": "demo-011-over-cap",
            "event_type": "c4_entry_order",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "BTC-USDC",
            "order": {"order_id": "paper-entry-2", "side": "BUY", "status": "open", "notional_quote": "25.00"},
            "governance": _gov(),
        },
        {
            "event_id": "demo-012-unsupported",
            "event_type": "c4_entry_order",
            "schema_version": SCHEMA_VERSION,
            "source_bot": "server1-master",
            "ticker": "ETH-USDC",
            "order": {"order_id": "paper-entry-3", "side": "BUY", "status": "open", "notional_quote": "5.00"},
            "governance": _gov(),
        },
    ]


def run_paper_lifecycle_simulation(
    events: Iterable[Dict[str, Any]],
    *,
    config: Optional[PaperLifecycleConfig] = None,
) -> Dict[str, Any]:
    simulator = PaperLifecycleSimulator(config=config)
    return simulator.apply_events(events)


def render_paper_lifecycle_markdown(report: Dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Replication Paper Lifecycle Simulator",
        "",
        "Local paper-only simulator. It does not enable replication, call Coinbase, place orders, mutate trading state or authorize follower live mode.",
        "",
        "## Readiness",
        f"- follower_ready_for_paper_lifecycle_test: `{report.get('follower_ready_for_paper_lifecycle_test')}`",
        f"- follower_paper_lifecycle_simulator_ready: `{report.get('paper_lifecycle_simulator_ready')}`",
        f"- follower_ready_for_live: `{report.get('follower_ready_for_live')}`",
        f"- follower_buy_ready: `{report.get('follower_buy_ready')}`",
        f"- follower_sell_ready: `{report.get('follower_sell_ready')}`",
        f"- lifecycle_parity_ready: `{report.get('lifecycle_parity_ready')}`",
        "",
        "## Safety",
        f"- live_order_attempted: `{report.get('live_order_attempted')}`",
        f"- coinbase_call_attempted: `{report.get('coinbase_call_attempted')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        "",
        "## Summary",
    ]
    for key in (
        "processed_event_count",
        "unique_event_count",
        "duplicate_ignored_count",
        "rejected_event_count",
        "paper_order_count",
        "paper_position_count",
        "paper_d2_plan_count",
        "paper_d3_preview_count",
        "blocker_count",
        "warning_count",
    ):
        lines.append(f"- {key}: `{summary.get(key)}`")
    lines.extend(["", "## Blockers"])
    for blocker in report.get("blockers") or ["none"]:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Warnings"])
    for warning in report.get("warnings") or ["none"]:
        lines.append(f"- {warning}")
    lines.extend(["", "## Rejected Events"])
    for row in report.get("rejected_events") or []:
        lines.append(f"- `{row.get('event_id')}` `{row.get('event_type')}`: {row.get('reason')}")
    return "\n".join(lines)


__all__ = [
    "PHASE",
    "PaperLifecycleConfig",
    "PaperLifecycleSimulator",
    "demo_fixture_events",
    "render_paper_lifecycle_markdown",
    "run_paper_lifecycle_simulation",
]
