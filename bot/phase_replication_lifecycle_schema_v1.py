from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "replication_lifecycle_schema_v1"
SCHEMA_VERSION = "replication.lifecycle.v1"


EVENT_TYPES = {
    "decision": {
        "required": ["event_id", "event_type", "schema_version", "source_bot", "ticker", "decision", "side"],
        "default_follower_effect": "paper_observe_decision",
        "live_order_action": False,
        "state_mutation": False,
    },
    "c4_entry_order": {
        "required": ["event_id", "event_type", "schema_version", "source_bot", "ticker", "order"],
        "default_follower_effect": "observe_order_lifecycle",
        "live_order_action": False,
        "state_mutation": False,
    },
    "c4_terminal_order": {
        "required": ["event_id", "event_type", "schema_version", "source_bot", "ticker", "order", "fill"],
        "default_follower_effect": "observe_terminal_order",
        "live_order_action": False,
        "state_mutation": False,
    },
    "d1_fill_to_position": {
        "required": ["event_id", "event_type", "schema_version", "source_bot", "ticker", "fill", "position"],
        "default_follower_effect": "observe_fill_to_position",
        "live_order_action": False,
        "state_mutation": False,
    },
    "d2_position_plan": {
        "required": ["event_id", "event_type", "schema_version", "source_bot", "ticker", "position", "plan"],
        "default_follower_effect": "paper_store_plan",
        "live_order_action": False,
        "state_mutation": False,
    },
    "d3_exit_preview": {
        "required": ["event_id", "event_type", "schema_version", "source_bot", "ticker", "position", "exit_preview", "governance"],
        "default_follower_effect": "observe_exit_preview",
        "live_order_action": False,
        "state_mutation": False,
    },
    "d3_live_exit_intent": {
        "required": ["event_id", "event_type", "schema_version", "source_bot", "ticker"],
        "default_follower_effect": "observe_live_exit_intent_only",
        "live_order_action": False,
        "state_mutation": False,
    },
    "d4_cancel_replace_trailing": {
        "required": ["event_id", "event_type", "schema_version", "source_bot", "ticker", "replace_intent", "governance"],
        "default_follower_effect": "observe_cancel_replace_only",
        "live_order_action": False,
        "state_mutation": False,
    },
    "d5_execution_metric": {
        "required": ["event_id", "event_type", "schema_version", "source_bot", "ticker", "metric", "governance"],
        "default_follower_effect": "human_review_metric_only",
        "live_order_action": False,
        "state_mutation": False,
    },
    "governance_status": {
        "required": ["event_id", "event_type", "schema_version", "source_bot", "ticker", "status", "governance"],
        "default_follower_effect": "halt_or_watch_signal_only",
        "live_order_action": False,
        "state_mutation": False,
    },
}


LIVE_READINESS_REQUIREMENTS = [
    "follower_receiver_api_present",
    "paper_live_mode_separation",
    "follower_live_ack_gate",
    "allowed_tickers",
    "max_notional_cap",
    "max_open_orders_cap",
    "product_rule_normalization",
    "balance_checks",
    "min_size_increment_checks",
    "idempotency_store",
    "drift_reconcile",
]

SELL_READINESS_EXTRA_REQUIREMENTS = [
    "no_oversell_checks",
    "reduce_only_semantics",
    "open_exit_reservation_governance",
    "cancel_replace_idempotency",
    "separate_live_exit_ack",
]


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


def _read_text(root: Path, rel: str, max_chars: int = 500_000) -> str:
    path = root / rel
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
    except OSError:
        return ""


def _path_exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _has_follower_receiver(root: Path) -> bool:
    searchable = []
    for base in ("replication", "follower", "replica", "server", "api"):
        path = root / base
        if path.exists():
            searchable.extend(path.rglob("*.py"))
    for path in searchable:
        rel = str(path.relative_to(root))
        if rel == "replication/publisher.py":
            continue
        text = _read_text(root, rel)
        if "/api/replica/decision" in text or "x-replica-signature" in text or "verify_signature" in text:
            return True
    return False


def _current_architecture(root: Path) -> Dict[str, Any]:
    publisher = _read_text(root, "replication/publisher.py")
    models = _read_text(root, "replication/models.py")
    runner = _read_text(root, "run_trader_loop.py")
    return {
        "current_replication_shape": "decision_only"
        if "ReplicationEnvelope" in models and "/api/replica/decision" in publisher
        else "unknown",
        "master_publisher_present": "publish_decision_best_effort" in publisher,
        "master_endpoint": "/api/replica/decision" if "/api/replica/decision" in publisher else "",
        "hmac_header_present": "x-replica-signature" in publisher,
        "full_cycle_publish_callsite_present": "_replicate_full_cycle_results" in runner,
        "heartbeat_publish_callsite_present": "_replicate_heartbeat_results" in runner,
        "follower_receiver_present_in_repo": _has_follower_receiver(root),
        "lifecycle_event_publish_callsite_present": "publish_lifecycle" in runner or "lifecycle_event_type" in publisher,
    }


def lifecycle_schema_v1_spec() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_types": EVENT_TYPES,
        "global_required_fields": ["event_id", "event_type", "schema_version", "source_bot", "ticker", "governance"],
        "idempotency": {
            "required_event_id": True,
            "recommended_key": ["source_bot", "event_id", "schema_version"],
            "duplicate_policy": "ignore_duplicate_after_first_valid_event",
        },
        "auth_transport": {
            "hmac_sha256_header": "x-replica-signature",
            "transport_endpoint_recommendation": "/api/replica/lifecycle",
            "decision_endpoint_current": "/api/replica/decision",
        },
        "default_follower_policy": {
            "mode": "paper_only",
            "live_buy_ready": False,
            "live_sell_ready": False,
            "lifecycle_parity_ready": False,
            "d3_exit_events_execute_by_default": False,
            "d4_cancel_replace_execute_by_default": False,
            "learning_to_execution_allowed": False,
            "parameter_mutation_allowed": False,
        },
        "live_readiness_requirements": LIVE_READINESS_REQUIREMENTS,
        "sell_readiness_extra_requirements": SELL_READINESS_EXTRA_REQUIREMENTS,
    }


def follower_default_effect(event: Dict[str, Any]) -> Dict[str, Any]:
    event_type = str(event.get("event_type") or "")
    spec = EVENT_TYPES.get(event_type)
    if spec is None:
        return {
            "accepted_for_transport": False,
            "effect": "reject_unknown_event_type",
            "live_order_action": False,
            "state_mutation": False,
            "requires_human_review": True,
        }
    governance = event.get("governance") if isinstance(event.get("governance"), dict) else {}
    return {
        "accepted_for_transport": True,
        "effect": spec["default_follower_effect"],
        "live_order_action": False,
        "state_mutation": False,
        "requires_human_review": bool(
            event_type in {"d1_fill_to_position", "d3_live_exit_intent", "d4_cancel_replace_trailing"}
            or str(governance.get("classification") or "").upper() in {"WATCH", "STOP_NOW"}
        ),
    }


def validate_lifecycle_event_v1(event: Dict[str, Any]) -> Tuple[bool, List[str], Dict[str, Any]]:
    errors: List[str] = []
    if not isinstance(event, dict):
        return False, ["event_not_object"], {
            "live_order_action": False,
            "state_mutation": False,
            "accepted_for_transport": False,
        }

    event_type = str(event.get("event_type") or "")
    spec = EVENT_TYPES.get(event_type)
    if spec is None:
        errors.append("unknown_event_type")
        return False, errors, follower_default_effect(event)

    if event.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version_mismatch")

    for field in spec["required"]:
        value = event.get(field)
        if value is None or value == "":
            errors.append(f"missing_required_field:{field}")

    ticker = str(event.get("ticker") or "")
    if "-" not in ticker:
        errors.append("ticker_must_be_product_id")

    governance = event.get("governance")
    if isinstance(governance, dict):
        mode = str(governance.get("follower_default_mode") or "paper_only")
        if mode != "paper_only":
            errors.append("follower_default_mode_must_be_paper_only")
        if governance.get("live_action_authorized") is True:
            errors.append("live_action_authorized_forbidden_in_schema_v1_default")

    if event_type == "d3_live_exit_intent":
        exit_intent = event.get("exit_intent") if isinstance(event.get("exit_intent"), dict) else {}
        order = event.get("order") if isinstance(event.get("order"), dict) else {}
        side = str(exit_intent.get("side") or order.get("side") or "").upper()
        if side != "SELL":
            errors.append("d3_live_exit_intent_requires_sell_side")
        if exit_intent.get("submit_live") is True:
            errors.append("d3_live_exit_intent_submit_live_forbidden_by_default")

    if event_type == "d4_cancel_replace_trailing":
        replace_intent = event.get("replace_intent") if isinstance(event.get("replace_intent"), dict) else {}
        if replace_intent.get("submit_live") is True or replace_intent.get("cancel_live") is True:
            errors.append("d4_cancel_replace_live_action_forbidden_by_default")

    return not errors, errors, follower_default_effect(event)


def build_replication_lifecycle_schema_report(*, root: Path | str = ".") -> Dict[str, Any]:
    repo = Path(root)
    architecture = _current_architecture(repo)
    readiness = {
        "follower_buy_ready": False,
        "follower_sell_ready": False,
        "lifecycle_parity_ready": False,
        "follower_ready_for_paper_lifecycle_test": True,
        "follower_ready_for_live": False,
        "reasons": [
            "master_currently_publishes_decision_envelopes_only",
            "follower_receiver_api_not_present_in_repo" if not architecture["follower_receiver_present_in_repo"] else "follower_receiver_requires_audit",
            "lifecycle_event_transport_not_implemented",
            "follower_product_rules_balances_caps_drift_checks_not_proven",
            "d3_and_d4_events_observe_only_by_default",
        ],
    }
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_mode": "read_only_replication_lifecycle_schema_v1",
        "route": "R1_replication_lifecycle_schema_v1",
        "no_coinbase_call": True,
        "state_write_performed": False,
        "replication_enabled_by_report": False,
        "follower_live_enabled": False,
        "current_architecture": architecture,
        "schema_spec": lifecycle_schema_v1_spec(),
        "readiness": readiness,
        "required_before_follower_buy": LIVE_READINESS_REQUIREMENTS,
        "required_before_follower_sell": LIVE_READINESS_REQUIREMENTS + SELL_READINESS_EXTRA_REQUIREMENTS,
        "events_observe_only_by_default": [
            "c4_entry_order",
            "c4_terminal_order",
            "d1_fill_to_position",
            "d2_position_plan",
            "d3_exit_preview",
            "d3_live_exit_intent",
            "d4_cancel_replace_trailing",
            "d5_execution_metric",
            "governance_status",
        ],
        "recommended_next_sprint": {
            "route": "R2_follower_paper_lifecycle_simulator",
            "why": "Schema v1 now defines lifecycle event shape and safe default effects; next prove fixture consumption, idempotency and paper-only position handling.",
        },
        "state_hashes": {
            "state/open_orders.json": _sha256(repo, "state/open_orders.json"),
            "state/positions.json": _sha256(repo, "state/positions.json"),
        },
        **d6_metric_safety_flags(),
    }


def render_replication_lifecycle_schema_markdown(report: Dict[str, Any]) -> str:
    readiness = report.get("readiness") or {}
    arch = report.get("current_architecture") or {}
    lines = [
        "# Replication Lifecycle Schema V1",
        "",
        "Read-only schema artifact. It does not enable replication, follower live mode, Coinbase calls or trading-state writes.",
        "",
        "## Readiness",
        f"- follower_buy_ready: `{readiness.get('follower_buy_ready')}`",
        f"- follower_sell_ready: `{readiness.get('follower_sell_ready')}`",
        f"- lifecycle_parity_ready: `{readiness.get('lifecycle_parity_ready')}`",
        f"- follower_ready_for_paper_lifecycle_test: `{readiness.get('follower_ready_for_paper_lifecycle_test')}`",
        f"- follower_ready_for_live: `{readiness.get('follower_ready_for_live')}`",
        f"- reasons: `{', '.join(readiness.get('reasons') or [])}`",
        "",
        "## Current Architecture",
        f"- current_replication_shape: `{arch.get('current_replication_shape')}`",
        f"- master_publisher_present: `{arch.get('master_publisher_present')}`",
        f"- master_endpoint: `{arch.get('master_endpoint')}`",
        f"- hmac_header_present: `{arch.get('hmac_header_present')}`",
        f"- follower_receiver_present_in_repo: `{arch.get('follower_receiver_present_in_repo')}`",
        f"- lifecycle_event_publish_callsite_present: `{arch.get('lifecycle_event_publish_callsite_present')}`",
        "",
        "## Event Types",
    ]
    for event_type, spec in (report.get("schema_spec") or {}).get("event_types", {}).items():
        lines.extend([
            "",
            f"### {event_type}",
            f"- required: `{', '.join(spec.get('required') or [])}`",
            f"- default_follower_effect: `{spec.get('default_follower_effect')}`",
            f"- live_order_action: `{spec.get('live_order_action')}`",
            f"- state_mutation: `{spec.get('state_mutation')}`",
        ])
    lines.extend([
        "",
        "## Required Before Follower BUY",
        *[f"- {item}" for item in report.get("required_before_follower_buy") or []],
        "",
        "## Required Before Follower SELL",
        *[f"- {item}" for item in report.get("required_before_follower_sell") or []],
        "",
        "## Recommended Next Sprint",
        f"- route: `{(report.get('recommended_next_sprint') or {}).get('route')}`",
        f"- why: {(report.get('recommended_next_sprint') or {}).get('why')}",
        "",
        "## State Hashes",
    ])
    for key, value in (report.get("state_hashes") or {}).items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines)


__all__ = [
    "PHASE",
    "SCHEMA_VERSION",
    "EVENT_TYPES",
    "build_replication_lifecycle_schema_report",
    "follower_default_effect",
    "lifecycle_schema_v1_spec",
    "render_replication_lifecycle_schema_markdown",
    "validate_lifecycle_event_v1",
]
