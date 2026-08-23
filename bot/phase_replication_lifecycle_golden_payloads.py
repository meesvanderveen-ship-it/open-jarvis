from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_replication_lifecycle_schema_v1 import SCHEMA_VERSION, validate_lifecycle_event_v1
from bot.phase_replication_paper_lifecycle_simulator import run_paper_lifecycle_simulation


PHASE = "replication_lifecycle_golden_payloads_v1"
TICKER = "BTC-USDC"
SOURCE_BOT = "server1-master"


def _sha256(root: Path, rel: str) -> str:
    path = root / rel
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _gov(classification: str = "OK", *, reason: str = "") -> Dict[str, Any]:
    return {
        "classification": classification,
        "reason": reason,
        "follower_default_mode": "paper_only",
        "live_action_authorized": False,
        "replication_enabled_required": False,
    }


def _event(event_id: str, event_type: str, *, ticker: str = TICKER, governance: Dict[str, Any] | None = None, **fields: Any) -> Dict[str, Any]:
    generated_at = "2026-06-09T00:00:00Z"
    event = {
        "event_id": event_id,
        "event_type": event_type,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "timestamp": generated_at,
        "source": "master",
        "source_bot": SOURCE_BOT,
        "ticker": ticker,
        "mode": "paper_observe",
        "live_order_action": False,
        "state_mutation": False,
        "idempotency_key": f"{SOURCE_BOT}|{SCHEMA_VERSION}|{event_id}",
        "governance": governance or _gov(),
        "safety_flags": {
            "paper_only": True,
            "follower_live_enabled": False,
            "coinbase_call_allowed": False,
            "state_write_allowed": False,
            "learning_to_execution_enabled": False,
            "parameter_mutation_allowed": False,
        },
        "ack_requirements": {
            "follower_live_buy": "separate future follower BUY ACK required",
            "follower_live_sell": "separate future follower SELL/reduce ACK required",
            "fill_to_position_apply": "master/local apply ACK does not transfer to follower",
            "cancel_replace": "separate future follower cancel/replace ACK required",
        },
    }
    event.update(fields)
    return event


def build_positive_golden_sequence() -> List[Dict[str, Any]]:
    return [
        _event(
            "golden-001-governance-ok",
            "governance_status",
            status={"classification": "OK", "scope": "BTC-USDC-only", "follower_mode": "paper_only"},
        ),
        _event(
            "golden-002-decision",
            "decision",
            decision="approve_trade",
            side="BUY",
            confidence=78,
            reason_summary=["btc_tiny_paper_lifecycle_fixture"],
        ),
        _event(
            "golden-003-c4-entry",
            "c4_entry_order",
            order={
                "order_id": "golden-paper-entry-1",
                "client_order_id": "golden-paper-entry-1",
                "side": "BUY",
                "status": "open",
                "notional_quote": "9.50",
                "limit_price": "100000.00",
                "base_size": "0.00009500",
                "product_id": TICKER,
            },
        ),
        _event(
            "golden-004-c4-terminal-fill",
            "c4_terminal_order",
            order={
                "order_id": "golden-paper-entry-1",
                "client_order_id": "golden-paper-entry-1",
                "side": "BUY",
                "status": "filled",
                "product_id": TICKER,
            },
            fill={
                "order_id": "golden-paper-entry-1",
                "base_size": "0.00009500",
                "quote_size": "9.50",
                "avg_price": "100000.00",
                "fee_quote": "0.00",
                "fill_status": "filled",
            },
        ),
        _event(
            "golden-005-d1-fill-position",
            "d1_fill_to_position",
            governance=_gov("WATCH", reason="fill_to_position_is_paper_only_until_ack"),
            fill={"order_id": "golden-paper-entry-1", "base_size": "0.00009500", "quote_size": "9.50"},
            position={
                "position_id": "golden-paper-BTC-USDC",
                "base_size": "0.00009500",
                "quote_size": "9.50",
                "status": "paper_open",
            },
        ),
        _event(
            "golden-006-d2-plan",
            "d2_position_plan",
            position={"position_id": "golden-paper-BTC-USDC", "base_size": "0.00009500"},
            plan={
                "plan_fingerprint": "golden-d2-plan-1",
                "take_profit_count": 1,
                "stop_loss_present": True,
                "exit_authorized": False,
            },
        ),
        _event(
            "golden-007-d3-preview",
            "d3_exit_preview",
            position={"position_id": "golden-paper-BTC-USDC", "base_size": "0.00009500"},
            exit_preview={
                "preview_id": "golden-d3-preview-1",
                "side": "SELL",
                "base_size": "0.00005000",
                "submit_live": False,
                "live_exit_authorized": False,
            },
        ),
        _event(
            "golden-008-d3-live-intent-observe",
            "d3_live_exit_intent",
            governance=_gov("WATCH", reason="live_exit_intent_observe_only"),
            position={"position_id": "golden-paper-BTC-USDC", "base_size": "0.00009500"},
            exit_intent={
                "intent_id": "golden-d3-intent-1",
                "side": "SELL",
                "base_size": "0.00005000",
                "submit_live": False,
                "requires_follower_ack": True,
            },
        ),
        _event(
            "golden-009-d4-replace-observe",
            "d4_cancel_replace_trailing",
            governance=_gov("WATCH", reason="cancel_replace_observe_only"),
            replace_intent={
                "intent_id": "golden-d4-replace-1",
                "cancel_live": False,
                "submit_live": False,
                "requires_follower_ack": True,
            },
        ),
        _event(
            "golden-010-d5-metric",
            "d5_execution_metric",
            metric={
                "name": "golden_lifecycle_payload_validation",
                "value": 1,
                "unit": "count",
                "human_review_only": True,
            },
        ),
        _event(
            "golden-011-governance-conclusion",
            "governance_status",
            governance=_gov("OK", reason="golden_sequence_consumed_paper_only"),
            status={"classification": "OK", "reason": "golden_sequence_consumed_paper_only"},
        ),
    ]


def build_negative_fixtures() -> Dict[str, List[Dict[str, Any]]]:
    prior_fill = build_positive_golden_sequence()[:5]
    return {
        "unsupported_ticker": [
            _event(
                "negative-unsupported-ticker",
                "c4_entry_order",
                ticker="ETH-USDC",
                order={"order_id": "negative-eth-entry", "side": "BUY", "status": "open", "notional_quote": "5.00"},
            )
        ],
        "over_cap_notional": [
            _event(
                "negative-over-cap",
                "c4_entry_order",
                order={"order_id": "negative-over-cap-entry", "side": "BUY", "status": "open", "notional_quote": "25.00"},
            )
        ],
        "duplicate_event_id": [
            _event(
                "negative-duplicate-entry",
                "c4_entry_order",
                order={"order_id": "negative-dup-entry", "side": "BUY", "status": "open", "notional_quote": "5.00"},
            ),
            _event(
                "negative-duplicate-entry",
                "c4_entry_order",
                order={"order_id": "negative-dup-entry", "side": "BUY", "status": "open", "notional_quote": "5.00"},
            ),
        ],
        "d1_without_prior_fill": [
            _event(
                "negative-d1-missing-fill",
                "d1_fill_to_position",
                governance=_gov("WATCH", reason="missing_fill_evidence"),
                fill={"order_id": "missing-order", "base_size": "0.00010000", "quote_size": "10.00"},
                position={"position_id": "negative-missing-fill-position", "base_size": "0.00010000"},
            )
        ],
        "d3_live_exit_without_ack": prior_fill
        + [
            _event(
                "negative-d3-live-exit-no-ack",
                "d3_live_exit_intent",
                governance=_gov("WATCH", reason="follower_exit_ack_missing"),
                position={"position_id": "golden-paper-BTC-USDC", "base_size": "0.00009500"},
                exit_intent={"side": "SELL", "base_size": "0.00005000", "submit_live": False, "requires_follower_ack": True},
            )
        ],
        "d4_cancel_replace_without_ack": [
            _event(
                "negative-d4-no-ack",
                "d4_cancel_replace_trailing",
                governance=_gov("WATCH", reason="follower_cancel_replace_ack_missing"),
                replace_intent={"cancel_live": False, "submit_live": False, "requires_follower_ack": True},
            )
        ],
        "no_oversell_violation": prior_fill
        + [
            _event(
                "negative-oversell",
                "d3_live_exit_intent",
                governance=_gov("WATCH", reason="oversell_attempt"),
                position={"position_id": "golden-paper-BTC-USDC", "base_size": "0.00009500"},
                exit_intent={"side": "SELL", "base_size": "0.99900000", "submit_live": False, "requires_follower_ack": True},
            )
        ],
    }


def _validate_events(events: Iterable[Dict[str, Any]]) -> Tuple[bool, List[Dict[str, Any]]]:
    rows: List[Dict[str, Any]] = []
    ok = True
    for event in events:
        valid, errors, effect = validate_lifecycle_event_v1(event)
        if not valid:
            ok = False
        rows.append(
            {
                "event_id": event.get("event_id"),
                "event_type": event.get("event_type"),
                "valid": valid,
                "errors": errors,
                "effect": effect,
                "idempotency_key": event.get("idempotency_key"),
                "live_order_action": event.get("live_order_action"),
                "state_mutation": event.get("state_mutation"),
            }
        )
    return ok, rows


def _negative_expectation_passed(name: str, report: Dict[str, Any]) -> bool:
    reasons = {row.get("reason") for row in report.get("rejected_events") or []}
    blockers = set(report.get("blockers") or [])
    statuses = [row.get("status") for row in report.get("processed_events") or []]
    if name == "unsupported_ticker":
        return "unsupported_ticker" in reasons
    if name == "over_cap_notional":
        return "entry_order_above_max_notional" in reasons
    if name == "duplicate_event_id":
        return "duplicate_ignored" in statuses
    if name == "d1_without_prior_fill":
        return "d1_missing_prior_fill_evidence" in reasons
    if name == "d3_live_exit_without_ack":
        return "d3_live_exit_intent_requires_separate_follower_ack" in blockers
    if name == "d4_cancel_replace_without_ack":
        return "d4_cancel_replace_requires_separate_follower_ack" in blockers
    if name == "no_oversell_violation":
        return "no_oversell_check_failed" in blockers
    return False


def build_replication_lifecycle_golden_payload_report(*, root: Path | str = ".") -> Dict[str, Any]:
    repo = Path(root)
    positive = build_positive_golden_sequence()
    negatives = build_negative_fixtures()
    all_events = positive + [event for rows in negatives.values() for event in rows]
    all_valid, validation_rows = _validate_events(all_events)
    positive_report = run_paper_lifecycle_simulation(positive)
    negative_reports = {name: run_paper_lifecycle_simulation(rows) for name, rows in negatives.items()}
    negative_results = {
        name: {
            "expectation_passed": _negative_expectation_passed(name, report),
            "rejected_events": report.get("rejected_events") or [],
            "warnings": report.get("warnings") or [],
            "blockers": report.get("blockers") or [],
            "processed_events": report.get("processed_events") or [],
            "live_order_attempted": report.get("live_order_attempted"),
            "coinbase_call_attempted": report.get("coinbase_call_attempted"),
            "state_write_performed": report.get("state_write_performed"),
        }
        for name, report in negative_reports.items()
    }
    negative_passed = all(row["expectation_passed"] for row in negative_results.values())
    positive_passed = (
        positive_report.get("live_order_attempted") is False
        and positive_report.get("coinbase_call_attempted") is False
        and positive_report.get("state_write_performed") is False
        and "d3_live_exit_intent_requires_separate_follower_ack" in (positive_report.get("blockers") or [])
        and "d4_cancel_replace_requires_separate_follower_ack" in (positive_report.get("blockers") or [])
        and positive_report.get("summary", {}).get("paper_position_count", 0) >= 1
    )
    simulator_validation_passed = bool(all_valid and positive_passed and negative_passed)
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_mode": "read_only_replication_lifecycle_golden_payloads",
        "schema_version": SCHEMA_VERSION,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "replication_enabled_by_report": False,
        "follower_live_enabled": False,
        "follower_ready_for_paper_lifecycle_test": True,
        "follower_paper_lifecycle_simulator_ready": True,
        "follower_buy_ready": False,
        "follower_sell_ready": False,
        "lifecycle_parity_ready": False,
        "follower_ready_for_live": False,
        "lifecycle_payloads_valid": all_valid,
        "positive_sequence_passed": positive_passed,
        "negative_fixtures_passed": negative_passed,
        "simulator_validation_passed": simulator_validation_passed,
        "golden_payload_sequence": positive,
        "negative_fixtures": negatives,
        "schema_validation": validation_rows,
        "positive_simulator_report": positive_report,
        "negative_simulator_results": negative_results,
        "required_before_master_lifecycle_publish": [
            "disabled-by-default lifecycle publisher interface",
            "golden payload serialization tests",
            "HMAC/transport contract for /api/replica/lifecycle or explicit endpoint decision",
            "replication disabled/no-http tests for lifecycle events",
            "operator ACK boundary preserving follower paper-only defaults",
        ],
        "required_before_follower_buy": [
            "follower receiver/API present and audited",
            "paper/live mode separation",
            "follower live BUY ACK gate",
            "follower allowed tickers, caps, balances and product rules",
            "follower idempotency and drift/reconcile",
        ],
        "required_before_follower_sell": [
            "all BUY requirements",
            "no-oversell checks",
            "reduce-only semantics",
            "open-exit reservation governance",
            "separate follower live SELL/reduce ACK",
        ],
        "recommended_next_sprint": {
            "route": "replication_lifecycle_publisher_scaffold_disabled_by_default",
            "why": "Golden payloads now validate through the paper simulator; next add a disabled-by-default master lifecycle publisher scaffold and no-HTTP tests without enabling replication.",
        },
        "state_hashes": {
            "state/open_orders.json": _sha256(repo, "state/open_orders.json"),
            "state/positions.json": _sha256(repo, "state/positions.json"),
        },
        **d6_metric_safety_flags(),
    }


def render_replication_lifecycle_golden_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Replication Lifecycle Golden Payloads",
        "",
        "Read-only golden payload and simulator-validation artifact. It does not enable replication, call Coinbase, place follower orders or mutate trading state.",
        "",
        "## Validation",
        f"- lifecycle_payloads_valid: `{report.get('lifecycle_payloads_valid')}`",
        f"- positive_sequence_passed: `{report.get('positive_sequence_passed')}`",
        f"- negative_fixtures_passed: `{report.get('negative_fixtures_passed')}`",
        f"- simulator_validation_passed: `{report.get('simulator_validation_passed')}`",
        f"- follower_ready_for_live: `{report.get('follower_ready_for_live')}`",
        "",
        "## Positive Sequence",
    ]
    for event in report.get("golden_payload_sequence") or []:
        lines.append(f"- `{event.get('event_id')}` `{event.get('event_type')}` ticker=`{event.get('ticker')}` mode=`{event.get('mode')}`")
    lines.extend(["", "## Negative Fixtures"])
    for name, result in (report.get("negative_simulator_results") or {}).items():
        reasons = [row.get("reason") for row in result.get("rejected_events") or []]
        blockers = result.get("blockers") or []
        lines.append(
            f"- `{name}` passed=`{result.get('expectation_passed')}` rejected=`{', '.join(str(x) for x in reasons)}` blockers=`{', '.join(str(x) for x in blockers)}`"
        )
    positive = report.get("positive_simulator_report") or {}
    lines.extend([
        "",
        "## Positive Simulator Summary",
        f"- live_order_attempted: `{positive.get('live_order_attempted')}`",
        f"- coinbase_call_attempted: `{positive.get('coinbase_call_attempted')}`",
        f"- state_write_performed: `{positive.get('state_write_performed')}`",
        f"- blockers: `{', '.join(positive.get('blockers') or [])}`",
        "",
        "## Remaining Work",
    ])
    for item in report.get("required_before_master_lifecycle_publish") or []:
        lines.append(f"- master_publish: {item}")
    for item in report.get("required_before_follower_buy") or []:
        lines.append(f"- follower_buy: {item}")
    for item in report.get("required_before_follower_sell") or []:
        lines.append(f"- follower_sell: {item}")
    next_sprint = report.get("recommended_next_sprint") or {}
    lines.extend([
        "",
        "## Recommended Next Sprint",
        f"- route: `{next_sprint.get('route')}`",
        f"- why: {next_sprint.get('why')}",
        "",
        "## State Hashes",
    ])
    for key, value in (report.get("state_hashes") or {}).items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines)


__all__ = [
    "PHASE",
    "build_negative_fixtures",
    "build_positive_golden_sequence",
    "build_replication_lifecycle_golden_payload_report",
    "render_replication_lifecycle_golden_markdown",
]
