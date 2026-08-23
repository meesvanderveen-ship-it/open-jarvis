#!/usr/bin/env python3
"""Build read-only forensic reports for the Coinbase bot runtime.

The tool intentionally performs no Coinbase calls and never mutates runtime
state. It reads logs/state/config evidence and writes audit reports only.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


ENV_KEYS = (
    "DEFAULT_QUOTE_SIZE_USDC",
    "MAX_NOTIONAL_USD",
    "AUTONOMOUS_MAX_ORDER_QUOTE",
    "PHASE_C_MAX_ORDER_QUOTE",
    "PHASE_D3_MAX_EXIT_ORDER_QUOTE",
    "AUTONOMOUS_MAX_OPEN_ORDERS",
    "MAX_OPEN_POSITIONS",
    "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE",
)

CODEPATCH_FILES = (
    "run_trader_loop.py",
    "bot/config.py",
    "bot/order_plan.py",
    "bot/execution_planner.py",
    "bot/orderbook_entry_planner.py",
    "bot/phase_c_live_guard.py",
    "bot/phase_c_live_submitter.py",
    "bot/phase_c43_autonomous_entry_live.py",
    "bot/phase_c43_lifecycle_service.py",
    "bot/product_rules.py",
    "bot/exchange_rejection_memory.py",
)

FINAL_ORDER_STATUSES = {
    "filled",
    "cancelled",
    "canceled",
    "rejected",
    "submit_rejected",
    "expired",
    "failed",
}

OPEN_ORDER_STATUSES = {
    "submitted",
    "open",
    "accepted",
    "pending",
    "pending_new",
    "working",
}

SELECTED_LOGS_FOR_TIMELINE = {
    "analysis.jsonl",
    "cycle_summary.jsonl",
    "decision_outcomes.jsonl",
    "errors.jsonl",
    "execution.jsonl",
    "execution_outcomes.jsonl",
    "execution_plans.jsonl",
    "heartbeat.jsonl",
    "heartbeat_summary.jsonl",
    "inventory_sync.jsonl",
    "judge_conflicts.jsonl",
    "live_exit_orders.jsonl",
    "market_intelligence_fetches.jsonl",
    "order_events.jsonl",
    "paper_order_manager.jsonl",
    "pending_order_intents.jsonl",
    "pending_trade_plans.jsonl",
    "phase_c43_fill_reconciliation.jsonl",
    "phase_c43_lifecycle_service.jsonl",
    "phase_c43_lifecycle_service_errors.jsonl",
    "phase_c_live_submit.jsonl",
    "phase_d3_controlled_live_exits.jsonl",
    "reflection_adaptive_sidecar.jsonl",
    "replication_outbox.jsonl",
    "replication_publish.jsonl",
    "trade_reflections.jsonl",
}


@dataclass(frozen=True)
class SourceRecord:
    path: str
    rows: int
    first_timestamp: str | None
    last_timestamp: str | None
    note: str = ""


def parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.isdigit() and len(raw) >= 10:
        try:
            return datetime.fromtimestamp(int(raw[:10]), tz=timezone.utc)
        except (OSError, ValueError):
            return None
    candidates = [raw, raw.replace("Z", "+00:00")]
    if " " in raw and "T" not in raw:
        candidates.append(raw.replace(" ", "T"))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def dt_s(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def dec_s(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def get_path(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def first_value(obj: dict[str, Any], paths: Iterable[str]) -> Any:
    for path in paths:
        value = get_path(obj, path)
        if value is not None and value != "":
            return value
    return None


def first_timestamp(obj: dict[str, Any]) -> datetime | None:
    for path in (
        "generated_at",
        "timestamp",
        "created_at",
        "updated_at",
        "submitted_at",
        "filled_at",
        "cancelled_at",
        "canceled_at",
        "close_time",
        "entry_time",
        "time",
        "event_time",
        "last_heartbeat_at",
    ):
        parsed = parse_dt(get_path(obj, path))
        if parsed is not None:
            return parsed
    return None


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError:
                    yield line_no, {
                        "timestamp": None,
                        "status": "json_decode_error",
                        "raw_prefix": stripped[:200],
                    }
                    continue
                if isinstance(obj, dict):
                    yield line_no, obj
    except FileNotFoundError:
        return


def read_env_selected(path: Path) -> tuple[dict[str, str], dict[str, int]]:
    values: dict[str, str] = {}
    lines: dict[str, int] = {}
    try:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key not in ENV_KEYS:
                continue
            values[key] = value.strip().strip("\"'")
            lines[key] = line_no
    except FileNotFoundError:
        pass
    return values, lines


def load_approved_profile(path: Path) -> dict[str, Any]:
    raw = read_json(path, {})
    if not isinstance(raw, dict):
        return {}
    params = raw.get("parameters")
    if isinstance(params, dict):
        return {
            "profile_name": raw.get("profile_name") or raw.get("name"),
            "profile_hash": raw.get("profile_hash") or raw.get("hash"),
            "parameters": params,
            "raw": raw,
        }
    profile = raw.get("profile")
    if isinstance(profile, dict) and isinstance(profile.get("parameters"), dict):
        return {
            "profile_name": profile.get("profile_name") or profile.get("name") or raw.get("profile_name"),
            "profile_hash": raw.get("profile_hash") or profile.get("hash") or raw.get("hash"),
            "parameters": profile["parameters"],
            "raw": raw,
        }
    return {"raw": raw, "parameters": {}}


def configured_values(root: Path) -> dict[str, Any]:
    env_values, env_lines = read_env_selected(root / ".env")
    approved = load_approved_profile(root / "state" / "approved_parameter_profile.json")
    params = approved.get("parameters") if isinstance(approved.get("parameters"), dict) else {}

    def selected(key: str) -> str | None:
        value = params.get(key)
        if value is not None:
            return str(value)
        return env_values.get(key)

    return {
        "env": env_values,
        "env_lines": env_lines,
        "approved_profile": {
            "profile_name": approved.get("profile_name"),
            "profile_hash": approved.get("profile_hash"),
            "parameters": {key: str(params[key]) for key in ENV_KEYS if key in params},
        },
        "effective": {key: selected(key) for key in ENV_KEYS},
    }


def amount_shell(config: dict[str, Any]) -> dict[str, str | None]:
    effective = config["effective"]
    return {
        "configured_default_quote": effective.get("DEFAULT_QUOTE_SIZE_USDC"),
        "configured_max_quote": effective.get("AUTONOMOUS_MAX_ORDER_QUOTE")
        or effective.get("PHASE_C_MAX_ORDER_QUOTE")
        or effective.get("MAX_NOTIONAL_USD"),
        "requested_quote": None,
        "base_size": None,
        "price": None,
        "filled_value": None,
    }


def make_event(
    *,
    timestamp: datetime | None,
    source: str,
    event_type: str,
    summary: str,
    config: dict[str, Any],
    ticker: str | None = None,
    client_order_id: str | None = None,
    exchange_order_id: str | None = None,
    live_side_effect: bool = False,
    state_side_effect: bool = False,
    amounts: dict[str, Any] | None = None,
    risk_notes: list[str] | None = None,
    evidence: str | None = None,
) -> dict[str, Any]:
    merged_amounts = amount_shell(config)
    if amounts:
        for key in ("requested_quote", "base_size", "price", "filled_value"):
            value = amounts.get(key)
            if value is not None and value != "":
                merged_amounts[key] = str(value)
    notes = [str(note) for note in (risk_notes or []) if note]
    return {
        "timestamp": dt_s(timestamp),
        "source": source,
        "event_type": event_type,
        "ticker": ticker,
        "client_order_id": client_order_id,
        "exchange_order_id": exchange_order_id,
        "summary": summary[:700],
        "live_side_effect": live_side_effect,
        "state_side_effect": state_side_effect,
        "amounts": merged_amounts,
        "risk_notes": notes[:12],
        "evidence": evidence,
    }


def extract_amounts(obj: dict[str, Any]) -> dict[str, str | None]:
    requested = first_value(
        obj,
        (
            "requested_quote",
            "quote_size",
            "size_quote",
            "max_quote_size",
            "max_size_quote",
            "notional",
            "order_quote",
            "filled_value",
            "filled_quote",
            "judge.size_quote",
            "trade_plan.max_quote_size",
            "trade_plan.max_size_quote",
            "order.quote_size",
            "order.notional",
        ),
    )
    base = first_value(
        obj,
        (
            "base_size",
            "size",
            "base_amount",
            "filled_size",
            "order.base_size",
            "order.size",
            "order.filled_size",
            "order_configuration.limit_limit_gtc.base_size",
        ),
    )
    price = first_value(
        obj,
        (
            "price",
            "limit_price",
            "preferred_limit_price",
            "entry_price",
            "fill_price",
            "average_filled_price",
            "order.price",
            "order.limit_price",
            "order_configuration.limit_limit_gtc.limit_price",
        ),
    )
    filled = first_value(
        obj,
        (
            "filled_value",
            "filled_quote",
            "executed_value",
            "total_value_after_fees",
            "order.filled_value",
            "order.executed_value",
        ),
    )
    if filled is None:
        base_dec = dec(base)
        price_dec = dec(price)
        if base_dec is not None and price_dec is not None:
            filled = dec_s(base_dec * price_dec)
    return {
        "requested_quote": None if requested is None else str(requested),
        "base_size": None if base is None else str(base),
        "price": None if price is None else str(price),
        "filled_value": None if filled is None else str(filled),
    }


def extract_ticker(obj: dict[str, Any]) -> str | None:
    value = first_value(
        obj,
        (
            "ticker",
            "product_id",
            "symbol",
            "judge.ticker",
            "trade_plan.ticker",
            "order.ticker",
            "order.product_id",
        ),
    )
    return None if value is None else str(value)


def extract_client_order_id(obj: dict[str, Any]) -> str | None:
    value = first_value(
        obj,
        (
            "client_order_id",
            "clientOrderId",
            "client_id",
            "local_order_id",
            "order.client_order_id",
            "order.client_id",
        ),
    )
    return None if value is None else str(value)


def extract_exchange_order_id(obj: dict[str, Any]) -> str | None:
    value = first_value(
        obj,
        (
            "exchange_order_id",
            "coinbase_order_id",
            "order_id",
            "exchange_id",
            "order.exchange_order_id",
            "order.coinbase_order_id",
            "order.order_id",
        ),
    )
    return None if value is None else str(value)


def status_text(obj: dict[str, Any]) -> str:
    status = first_value(obj, ("status", "event", "action", "result", "reason", "execution_status"))
    return "" if status is None else str(status)


def log_event_type(source_name: str, obj: dict[str, Any]) -> str:
    attempted = first_value(obj, ("live_submission_attempted", "live_submit_attempted", "submit_attempted"))
    submitted = first_value(obj, ("live_order_submitted", "live_submitted", "submitted"))
    attempted_bool = attempted is True or str(attempted).lower() == "true"
    submitted_bool = submitted is True or str(submitted).lower() == "true"
    status_lower = status_text(obj).lower()
    if source_name == "phase_c_live_submit.jsonl":
        if submitted_bool or "live_entry_submitted" in status_lower or status_lower.endswith("_submitted"):
            return "exchange_accept"
        if attempted_bool:
            if "reject" in status_lower or "invalid_" in status_lower:
                return "exchange_reject"
            return "submit_attempt"
        if "rejected" in status_lower:
            return "preview"
        if "blocked" in status_lower or "not_armed" in status_lower or "preview" in status_lower:
            return "preview"
    lowered = json.dumps(
        {
            "status": status_text(obj),
            "error": obj.get("error") or obj.get("error_reason") or obj.get("reject_reason"),
            "decision": first_value(obj, ("decision", "judge.decision", "judge_decision")),
        },
        default=str,
    ).lower()
    if source_name == "cycle_summary.jsonl":
        return "full_cycle"
    if source_name in {"heartbeat.jsonl", "heartbeat_summary.jsonl"}:
        return "heartbeat"
    if "lifecycle" in source_name or "reconciliation" in source_name:
        return "lifecycle"
    if source_name == "analysis.jsonl":
        return "judge_decision"
    if "cancel" in lowered or "cancelled" in lowered or "canceled" in lowered:
        return "cancel"
    if "fill" in lowered or "filled" in lowered:
        return "fill"
    if "invalid_" in lowered or "reject" in lowered or "rejected" in lowered:
        return "exchange_reject"
    if "submitted" in lowered or "accepted" in lowered:
        return "exchange_accept"
    if "attempt" in lowered:
        return "submit_attempt"
    if "preview" in lowered or "dry" in lowered or "wait" in lowered:
        return "preview"
    if "error" in lowered or source_name.startswith("errors"):
        return "error"
    if "replication" in source_name:
        return "preview"
    return "state_write" if source_name in {"inventory_sync.jsonl", "paper_order_manager.jsonl"} else "preview"


def summarize_log_row(source_name: str, obj: dict[str, Any]) -> tuple[str, list[str]]:
    notes: list[str] = []
    status = status_text(obj)
    ticker = extract_ticker(obj)
    decision = first_value(obj, ("decision", "judge.decision", "judge_decision"))
    valid_plan = first_value(obj, ("valid_trade_plan", "judge.valid_trade_plan", "trade_plan.valid_trade_plan"))
    submitted = first_value(obj, ("live_order_submitted", "live_submitted", "submitted"))
    attempted = first_value(obj, ("live_submission_attempted", "live_submit_attempted", "submit_attempted"))
    error = first_value(obj, ("error", "error_reason", "reject_reason", "reason", "message"))
    if error:
        notes.append(str(error)[:300])
    if valid_plan is False or str(valid_plan).lower() == "false":
        notes.append("valid_trade_plan=false")
    if attempted is True or str(attempted).lower() == "true":
        notes.append("live_submit_attempted=true")
    if submitted is True or str(submitted).lower() == "true":
        notes.append("live_order_submitted=true")
    if source_name == "cycle_summary.jsonl":
        if obj.get("live_submit_attempted") and not obj.get("valid_trade_plans"):
            notes.append("cycle reported live_submit_attempted while valid_trade_plans=0")
        summary = (
            f"cycle total={obj.get('total')} wait={obj.get('wait')} "
            f"valid_trade_plans={obj.get('valid_trade_plans')} "
            f"live_submit_attempted={obj.get('live_submit_attempted')}"
        )
        return summary, notes
    if source_name in {"heartbeat.jsonl", "heartbeat_summary.jsonl"}:
        summary = (
            f"heartbeat total={obj.get('total')} full_reviews={obj.get('full_reviews')} "
            f"executed={obj.get('executed')} status={status}"
        )
        return summary, notes
    parts = [source_name]
    if ticker:
        parts.append(f"ticker={ticker}")
    if status:
        parts.append(f"status={status}")
    if decision:
        parts.append(f"decision={decision}")
    if attempted is not None:
        parts.append(f"attempted={attempted}")
    if submitted is not None:
        parts.append(f"submitted={submitted}")
    if error:
        parts.append(f"error={str(error)[:160]}")
    return " | ".join(parts), notes


def inventory_jsonl_sources(root: Path) -> list[SourceRecord]:
    records: list[SourceRecord] = []
    for path_s in sorted(glob.glob(str(root / "logs" / "*.jsonl"))):
        path = Path(path_s)
        rows = 0
        first_ts: datetime | None = None
        last_ts: datetime | None = None
        for _, obj in iter_jsonl(path):
            rows += 1
            ts = first_timestamp(obj)
            if ts is not None:
                first_ts = ts if first_ts is None or ts < first_ts else first_ts
                last_ts = ts if last_ts is None or ts > last_ts else last_ts
        note = ""
        if path.name not in SELECTED_LOGS_FOR_TIMELINE:
            note = "inventoried; raw/debug source not expanded into the timeline"
        records.append(SourceRecord(str(path.relative_to(root)), rows, dt_s(first_ts), dt_s(last_ts), note))
    return records


def collect_log_events(root: Path, config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    order_like: list[dict[str, Any]] = []
    for path_s in sorted(glob.glob(str(root / "logs" / "*.jsonl"))):
        path = Path(path_s)
        if path.name not in SELECTED_LOGS_FOR_TIMELINE:
            continue
        source_name = path.name
        source = path.stem
        for line_no, obj in iter_jsonl(path):
            ts = first_timestamp(obj)
            event_type = log_event_type(source_name, obj)
            summary, notes = summarize_log_row(source_name, obj)
            amounts = extract_amounts(obj)
            ticker = extract_ticker(obj)
            attempted = first_value(obj, ("live_submission_attempted", "live_submit_attempted", "submit_attempted"))
            submitted = first_value(obj, ("live_order_submitted", "live_submitted", "submitted"))
            live_side_effect = event_type in {"submit_attempt", "exchange_accept", "exchange_reject", "fill", "cancel"}
            if attempted is True or str(attempted).lower() == "true":
                live_side_effect = True
            if event_type == "preview" and not (submitted is True or str(submitted).lower() == "true"):
                live_side_effect = False
            state_side_effect = source_name in {
                "order_events.jsonl",
                "inventory_sync.jsonl",
                "paper_order_manager.jsonl",
                "phase_c43_fill_reconciliation.jsonl",
            }
            event = make_event(
                timestamp=ts,
                source=source,
                event_type=event_type,
                ticker=ticker,
                client_order_id=extract_client_order_id(obj),
                exchange_order_id=extract_exchange_order_id(obj),
                summary=summary,
                live_side_effect=live_side_effect,
                state_side_effect=state_side_effect,
                amounts=amounts,
                risk_notes=notes,
                evidence=f"{path.relative_to(root)}:{line_no}",
                config=config,
            )
            events.append(event)
            if any(amounts.values()) or event_type in {"submit_attempt", "exchange_accept", "exchange_reject", "fill", "cancel"}:
                order_like.append({"event": event, "raw": obj, "source": str(path.relative_to(root)), "line": line_no})
    return events, order_like


def normalize_orders(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("orders", "open_orders", "items", "records"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [item for item in value.values() if isinstance(item, dict)]
        if all(isinstance(value, dict) for value in raw.values()):
            return [value for value in raw.values() if isinstance(value, dict)]
    return []


def normalize_positions(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("positions", "items", "records"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                return [item for item in value.values() if isinstance(item, dict)]
        if all(isinstance(value, dict) for value in raw.values()):
            return [value for value in raw.values() if isinstance(value, dict)]
    return []


def collect_state_events(root: Path, config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    order_like: list[dict[str, Any]] = []
    orders = normalize_orders(read_json(root / "state" / "open_orders.json", []))
    for idx, order in enumerate(orders, start=1):
        status = str(first_value(order, ("status", "state")) or "").lower()
        if status in {"filled"}:
            event_type = "fill"
        elif status in {"cancelled", "canceled"}:
            event_type = "cancel"
        elif status in {"rejected", "submit_rejected"}:
            event_type = "exchange_reject"
        elif status in OPEN_ORDER_STATUSES:
            event_type = "exchange_accept"
        else:
            event_type = "state_write"
        ts = first_timestamp(order)
        amounts = extract_amounts(order)
        summary = f"state order status={status or 'unknown'} side={order.get('side')} type={order.get('order_type') or order.get('type')}"
        event = make_event(
            timestamp=ts,
            source="open_orders",
            event_type=event_type,
            ticker=extract_ticker(order),
            client_order_id=extract_client_order_id(order),
            exchange_order_id=extract_exchange_order_id(order),
            summary=summary,
            live_side_effect=False,
            state_side_effect=True,
            amounts=amounts,
            risk_notes=[],
            evidence=f"state/open_orders.json:record[{idx}]",
            config=config,
        )
        events.append(event)
        order_like.append({"event": event, "raw": order, "source": "state/open_orders.json", "line": idx})

    positions = normalize_positions(read_json(root / "state" / "positions.json", []))
    for idx, pos in enumerate(positions, start=1):
        status = str(pos.get("status") or "")
        notes: list[str] = []
        if pos.get("position_risk_incomplete") or pos.get("protective_stop_status") == "position_risk_incomplete":
            notes.append("position_risk_incomplete")
        if pos.get("last_stop_breach_at") or "stop" in str(pos.get("last_heartbeat_reason") or "").lower():
            notes.append("stop/invalidation review signal")
        events.append(
            make_event(
                timestamp=first_timestamp(pos),
                source="positions",
                event_type="state_write",
                ticker=extract_ticker(pos),
                client_order_id=str(pos.get("order_id") or "") or None,
                exchange_order_id=str(pos.get("source_entry_order_id") or "") or None,
                summary=f"position status={status or 'unknown'} entry={pos.get('entry_price')} quote={pos.get('position_size_quote')}",
                live_side_effect=False,
                state_side_effect=True,
                amounts={
                    "requested_quote": pos.get("position_size_quote"),
                    "base_size": pos.get("position_size_base"),
                    "price": pos.get("entry_price"),
                    "filled_value": pos.get("position_size_quote"),
                },
                risk_notes=notes,
                evidence=f"state/positions.json:record[{idx}]",
                config=config,
            )
        )
        if status.lower() == "closed" and pos.get("close_time"):
            events.append(
                make_event(
                    timestamp=parse_dt(pos.get("close_time")),
                    source="positions",
                    event_type="local_apply",
                    ticker=extract_ticker(pos),
                    client_order_id=str(pos.get("order_id") or "") or None,
                    exchange_order_id=str(pos.get("source_entry_order_id") or "") or None,
                    summary=f"position close applied reason={pos.get('close_reason')} close_price={pos.get('close_price')}",
                    live_side_effect=False,
                    state_side_effect=True,
                    amounts={
                        "requested_quote": pos.get("position_size_quote"),
                        "base_size": pos.get("position_size_base"),
                        "price": pos.get("close_price"),
                        "filled_value": pos.get("position_size_quote"),
                    },
                    risk_notes=[],
                    evidence=f"state/positions.json:record[{idx}]",
                    config=config,
                )
            )
    return events, order_like, positions


def collect_config_events(root: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    env_values = config["env"]
    if env_values:
        env_mtime = datetime.fromtimestamp((root / ".env").stat().st_mtime, tz=timezone.utc)
        events.append(
            make_event(
                timestamp=env_mtime,
                source="env",
                event_type="config_change",
                summary="selected non-secret .env trading limits read for audit",
                config=config,
                amounts={
                    "requested_quote": env_values.get("DEFAULT_QUOTE_SIZE_USDC"),
                    "price": None,
                    "base_size": None,
                    "filled_value": None,
                },
                risk_notes=[f"{key}={value}" for key, value in env_values.items()],
                evidence=".env:selected_non_secret_keys",
            )
        )
    profile_path = root / "state" / "approved_parameter_profile.json"
    if profile_path.exists():
        events.append(
            make_event(
                timestamp=datetime.fromtimestamp(profile_path.stat().st_mtime, tz=timezone.utc),
                source="approved_parameter_profile",
                event_type="config_change",
                summary=f"approved profile={config['approved_profile'].get('profile_name')} loaded from state",
                config=config,
                amounts={
                    "requested_quote": config["approved_profile"].get("parameters", {}).get("DEFAULT_QUOTE_SIZE_USDC"),
                },
                risk_notes=[f"{key}={value}" for key, value in config["approved_profile"].get("parameters", {}).items()],
                evidence="state/approved_parameter_profile.json",
            )
        )
    return events


def collect_report_events(root: Path, config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    for base in (root / "reports" / "audits", root / "reports" / "research"):
        for path_s in sorted(glob.glob(str(base / "*"))):
            path = Path(path_s)
            if path.suffix not in {".json", ".md"}:
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            rel = str(path.relative_to(root))
            title = path.name
            if path.suffix == ".md":
                try:
                    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                        stripped = line.strip("# ").strip()
                        if stripped:
                            title = stripped[:160]
                            break
                except OSError:
                    pass
            inventory.append({"path": rel, "modified_at": dt_s(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)), "size": stat.st_size})
            events.append(
                make_event(
                    timestamp=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    source="report",
                    event_type="state_write",
                    summary=f"report inventory: {title}",
                    config=config,
                    evidence=rel,
                    risk_notes=[],
                    live_side_effect=False,
                    state_side_effect=False,
                )
            )
    return events, inventory


def collect_journal_events(root: Path, config: dict[str, Any], since: str | None, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cmd = ["journalctl", "-u", "coinbase-bot.service", "--no-pager", "--output=short-iso"]
    if since:
        cmd.extend(["--since", since])
    if limit:
        cmd.extend(["-n", str(limit)])
    try:
        proc = subprocess.run(cmd, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], {"available": False, "error": str(exc), "command": " ".join(cmd)}
    metadata = {
        "available": proc.returncode == 0,
        "returncode": proc.returncode,
        "stderr": proc.stderr.strip()[:1000],
        "command": " ".join(cmd),
    }
    if proc.returncode != 0:
        return [], metadata
    events: list[dict[str, Any]] = []
    pattern = re.compile(r"^(?P<ts>\S+)\s+\S+\s+python\[(?P<pid>\d+)\]:\s+(?P<msg>.*)$")
    for line_no, line in enumerate(proc.stdout.splitlines(), start=1):
        match = pattern.match(line)
        if not match:
            continue
        msg = match.group("msg")
        ts = parse_dt(match.group("ts"))
        msg_lower = msg.lower()
        if "starting new full trading cycle" in msg_lower:
            event_type = "cycle_start"
        elif "heartbeat" in msg_lower:
            event_type = "heartbeat"
        elif "approved_parameter_profile loaded" in msg_lower:
            event_type = "config_change"
        elif "live_order" in msg_lower or "submit" in msg_lower:
            event_type = "submit_attempt"
        elif "lifecycle" in msg_lower:
            event_type = "lifecycle"
        elif "error" in msg_lower or "warning" in msg_lower:
            event_type = "error"
        else:
            event_type = "preview"
        live_side_effect = event_type == "submit_attempt"
        ticker_match = re.search(r"ticker=([A-Z0-9-]+)", msg)
        events.append(
            make_event(
                timestamp=ts,
                source="journal",
                event_type=event_type,
                ticker=ticker_match.group(1) if ticker_match else None,
                summary=f"pid={match.group('pid')} {msg}",
                live_side_effect=live_side_effect,
                state_side_effect=False,
                risk_notes=[],
                evidence=f"journal:{line_no}",
                config=config,
            )
        )
    return events, metadata


def sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=lambda event: (event["timestamp"] or "0000", event["source"], event["event_type"]))


def latest_timestamp(events: list[dict[str, Any]]) -> datetime | None:
    latest: datetime | None = None
    for event in events:
        ts = parse_dt(event.get("timestamp"))
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    return latest


def latest_codepatch_at(root: Path) -> tuple[datetime | None, list[dict[str, str]]]:
    latest: datetime | None = None
    files: list[dict[str, str]] = []
    for rel in CODEPATCH_FILES:
        path = root / rel
        if not path.exists():
            files.append({"path": rel, "modified_at": "missing"})
            continue
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        latest = ts if latest is None or ts > latest else latest
        files.append({"path": rel, "modified_at": dt_s(ts) or ""})
    return latest, files


def latest_journal_restart(events: list[dict[str, Any]]) -> str | None:
    full_starts = [event["timestamp"] for event in events if event.get("source") == "journal" and event.get("event_type") == "cycle_start"]
    return max([value for value in full_starts if value] or [None])


def split_timeline(events: list[dict[str, Any]], latest: datetime | None, last_restart: str | None, last_patch: datetime | None) -> dict[str, list[dict[str, Any]]]:
    if latest is None:
        latest = datetime.now(tz=timezone.utc)
    cutoff_24h = latest - timedelta(hours=24)
    restart_dt = parse_dt(last_restart)
    splits = {
        "last_24h": [],
        "since_last_restart": [],
        "since_last_codepatch": [],
        "full_available_log_history": events,
    }
    for event in events:
        ts = parse_dt(event.get("timestamp"))
        if ts is None:
            continue
        if ts >= cutoff_24h:
            splits["last_24h"].append(event)
        if restart_dt is not None and ts >= restart_dt:
            splits["since_last_restart"].append(event)
        if last_patch is not None and ts >= last_patch:
            splits["since_last_codepatch"].append(event)
    return splits


def mk_incident(
    *,
    incident_id: str,
    incident_type: str,
    timestamp: str | None,
    ticker: str | None,
    severity: str,
    evidence_file: str,
    evidence_line_or_record: str,
    root_cause_hypothesis: str,
    root_cause: str,
    affected_files: list[str],
    affected_functions: list[str],
    affected_runtime_period: str,
    live_money_risk: str,
    state_integrity_risk: str,
    was_live_order_possible: bool,
    did_live_order_happen: bool,
    needs_patch: bool,
    needs_operator_action: bool,
    configured_limit: str | None = None,
    observed_value: str | None = None,
    fix_required: bool = True,
    confirmed: bool = True,
) -> dict[str, Any]:
    return {
        "incident_id": incident_id,
        "incident_type": incident_type,
        "timestamp": timestamp,
        "ticker": ticker,
        "configured_limit": configured_limit,
        "observed_value": observed_value,
        "severity": severity,
        "evidence_file": evidence_file,
        "evidence_line_or_record": evidence_line_or_record,
        "root_cause_hypothesis": root_cause_hypothesis,
        "fix_required": fix_required,
        "confirmed": confirmed,
        "root_cause": root_cause,
        "affected_files": affected_files,
        "affected_functions": affected_functions,
        "affected_runtime_period": affected_runtime_period,
        "live_money_risk": live_money_risk,
        "state_integrity_risk": state_integrity_risk,
        "was_live_order_possible": was_live_order_possible,
        "did_live_order_happen": did_live_order_happen,
        "needs_patch": needs_patch,
        "needs_operator_action": needs_operator_action,
    }


def event_dec(event: dict[str, Any], key: str) -> Decimal | None:
    return dec(event.get("amounts", {}).get(key))


def analyze_amounts(config: dict[str, Any], order_like: list[dict[str, Any]]) -> dict[str, Any]:
    effective = config["effective"]
    default_quote = effective.get("DEFAULT_QUOTE_SIZE_USDC")
    max_notional = dec(effective.get("MAX_NOTIONAL_USD"))
    max_entry_candidates = [
        dec(effective.get("AUTONOMOUS_MAX_ORDER_QUOTE")),
        dec(effective.get("PHASE_C_MAX_ORDER_QUOTE")),
        max_notional,
    ]
    max_entry = min([value for value in max_entry_candidates if value is not None], default=None)
    max_exit = dec(effective.get("PHASE_D3_MAX_EXIT_ORDER_QUOTE"))
    observed_max_requested: Decimal | None = None
    observed_max_base: Decimal | None = None
    observed_max_filled: Decimal | None = None
    violations: list[dict[str, Any]] = []
    suspicious: list[dict[str, Any]] = []

    env_default = config["env"].get("DEFAULT_QUOTE_SIZE_USDC")
    approved_default = config["approved_profile"].get("parameters", {}).get("DEFAULT_QUOTE_SIZE_USDC")
    if env_default and approved_default and str(env_default) != str(approved_default):
        suspicious.append(
            {
                "incident_type": "stale_config",
                "timestamp": None,
                "ticker": None,
                "configured_limit": str(approved_default),
                "observed_value": str(env_default),
                "severity": "P2",
                "evidence_file": ".env + state/approved_parameter_profile.json",
                "evidence_line_or_record": "DEFAULT_QUOTE_SIZE_USDC",
                "root_cause_hypothesis": ".env default is overlaid by approved profile at runtime; env-only audits can misreport default quote.",
                "fix_required": True,
            }
        )

    for item in order_like:
        event = item["event"]
        source = item["source"]
        line = item["line"]
        quote = event_dec(event, "requested_quote")
        base = event_dec(event, "base_size")
        price = event_dec(event, "price")
        filled = event_dec(event, "filled_value")
        if quote is not None:
            observed_max_requested = quote if observed_max_requested is None or quote > observed_max_requested else observed_max_requested
        if base is not None:
            observed_max_base = base if observed_max_base is None or base > observed_max_base else observed_max_base
        if filled is not None:
            observed_max_filled = filled if observed_max_filled is None or filled > observed_max_filled else observed_max_filled
        if quote is not None and max_entry is not None and quote > max_entry:
            violations.append(
                {
                    "incident_type": "max_quote_violation",
                    "timestamp": event["timestamp"],
                    "ticker": event["ticker"],
                    "configured_limit": dec_s(max_entry),
                    "observed_value": dec_s(quote),
                    "severity": "P0",
                    "evidence_file": source,
                    "evidence_line_or_record": str(line),
                    "root_cause_hypothesis": "Observed quote exceeded the minimum configured entry cap.",
                    "fix_required": True,
                }
            )
        if (
            quote is not None
            and max_exit is not None
            and quote > max_exit
            and ("sell" in event.get("summary", "").lower() or "exit" in source.lower() or "d3" in source.lower())
        ):
            violations.append(
                {
                    "incident_type": "max_quote_violation",
                    "timestamp": event["timestamp"],
                    "ticker": event["ticker"],
                    "configured_limit": dec_s(max_exit),
                    "observed_value": dec_s(quote),
                    "severity": "P0",
                    "evidence_file": source,
                    "evidence_line_or_record": str(line),
                    "root_cause_hypothesis": "Observed exit quote exceeded PHASE_D3_MAX_EXIT_ORDER_QUOTE.",
                    "fix_required": True,
                }
            )
        if quote is not None and base is not None and quote > Decimal("1") and base == quote:
            suspicious.append(
                {
                    "incident_type": "quote_base_confusion",
                    "timestamp": event["timestamp"],
                    "ticker": event["ticker"],
                    "configured_limit": dec_s(max_entry),
                    "observed_value": f"quote={dec_s(quote)} base={dec_s(base)}",
                    "severity": "P0",
                    "evidence_file": source,
                    "evidence_line_or_record": str(line),
                    "root_cause_hypothesis": "base_size equals quote_size for a quote-sized spot order.",
                    "fix_required": True,
                }
            )
        if quote is not None and base is not None and price is not None and quote > 0 and price > 0:
            expected = quote / price
            if expected > 0:
                rel = abs(base - expected) / expected
                if rel > Decimal("0.05") and event.get("event_type") in {"exchange_accept", "fill", "submit_attempt"}:
                    suspicious.append(
                        {
                            "incident_type": "quote_base_confusion",
                            "timestamp": event["timestamp"],
                            "ticker": event["ticker"],
                            "configured_limit": f"expected_base~{dec_s(expected)}",
                            "observed_value": f"base={dec_s(base)} quote={dec_s(quote)} price={dec_s(price)}",
                            "severity": "P1",
                            "evidence_file": source,
                            "evidence_line_or_record": str(line),
                            "root_cause_hypothesis": "Observed base deviates materially from quote/price conversion.",
                            "fix_required": True,
                        }
                    )
        if "smoke" in event.get("summary", "").lower() or (quote is not None and Decimal("0") < quote <= Decimal("10")):
            suspicious.append(
                {
                    "incident_type": "historical_smoke_or_legacy_size",
                    "timestamp": event["timestamp"],
                    "ticker": event["ticker"],
                    "configured_limit": default_quote,
                    "observed_value": dec_s(quote) if quote is not None else None,
                    "severity": "P3",
                    "evidence_file": source,
                    "evidence_line_or_record": str(line),
                    "root_cause_hypothesis": "Legacy smoke/pilot logs use old small sizing and must not be counted as current runtime sizing.",
                    "fix_required": False,
                }
            )

    conclusion = "compliant"
    if violations:
        conclusion = "violation_found"
    elif suspicious:
        conclusion = "suspicious"
    if observed_max_requested is None and observed_max_filled is None:
        conclusion = "insufficient_data"
    return {
        "configured": {
            "default_quote": default_quote,
            "env_default_quote": config["env"].get("DEFAULT_QUOTE_SIZE_USDC"),
            "approved_profile_default_quote": config["approved_profile"].get("parameters", {}).get("DEFAULT_QUOTE_SIZE_USDC"),
            "max_notional": effective.get("MAX_NOTIONAL_USD"),
            "max_entry_quote": dec_s(max_entry),
            "max_exit_quote": effective.get("PHASE_D3_MAX_EXIT_ORDER_QUOTE"),
            "max_open_orders": int(effective.get("AUTONOMOUS_MAX_OPEN_ORDERS") or 0),
            "max_positions": int(effective.get("MAX_OPEN_POSITIONS") or 0),
            "max_new_orders_per_cycle": int(effective.get("AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE") or 0),
        },
        "observed_max_requested_quote": dec_s(observed_max_requested),
        "observed_max_base_size": dec_s(observed_max_base),
        "observed_max_filled_quote": dec_s(observed_max_filled),
        "violations": violations,
        "suspicious_records": suspicious,
        "conclusion": conclusion,
    }


def analyze_incidents(
    root: Path,
    events: list[dict[str, Any]],
    order_like: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    amount_audit: dict[str, Any],
    journal_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    seen_types: set[str] = set()

    for event in events:
        if event.get("source") == "cycle_summary" and "cycle reported live_submit_attempted while valid_trade_plans=0" in event.get("risk_notes", []):
            incidents.append(
                mk_incident(
                    incident_id=f"INC-WAIT-LIVE-{len(incidents)+1:03d}",
                    incident_type="preview_wait_live_submit_attempt",
                    timestamp=event.get("timestamp"),
                    ticker=event.get("ticker"),
                    severity="P0",
                    evidence_file=event.get("evidence", "logs/cycle_summary.jsonl").split(":")[0],
                    evidence_line_or_record=event.get("evidence", "").split(":")[-1],
                    root_cause_hypothesis="Old C4.3 live guard allowed resting/orderbook candidate path even when judge decisions were wait and valid_trade_plans=0.",
                    root_cause="Resting-entry eligibility was treated as live-submit sufficient without requiring fresh approve_trade + BUY + valid_trade_plan evidence.",
                    affected_files=["bot/phase_c43_autonomous_entry_live.py", "bot/phase_c_live_guard.py"],
                    affected_functions=["_fresh_judge_live_buy_approval", "build_phase_c_live_guard_snapshot", "run_autonomous_entry_live_once"],
                    affected_runtime_period="2026-06-17 through 2026-06-18 04:08 UTC evidence",
                    live_money_risk="high",
                    state_integrity_risk="medium",
                    was_live_order_possible=True,
                    did_live_order_happen=False,
                    needs_patch=True,
                    needs_operator_action=False,
                )
            )
    for item in order_like:
        event = item["event"]
        raw = item["raw"]
        raw_dump = json.dumps(raw, default=str).lower()
        attempted = first_value(raw, ("live_submission_attempted", "live_submit_attempted", "submit_attempted"))
        submitted = first_value(raw, ("live_order_submitted", "live_submitted", "submitted"))
        attempted_bool = attempted is True or str(attempted).lower() == "true"
        submitted_bool = submitted is True or str(submitted).lower() == "true"
        if attempted_bool and "judge_decision" in raw_dump and '"wait"' in raw_dump and "resting_entry" in raw_dump:
            incidents.append(
                mk_incident(
                    incident_id=f"INC-WAIT-ATTEMPT-{len(incidents)+1:03d}",
                    incident_type="preview_wait_live_submit_attempt",
                    timestamp=event.get("timestamp"),
                    ticker=event.get("ticker"),
                    severity="P0",
                    evidence_file=item["source"],
                    evidence_line_or_record=str(item["line"]),
                    root_cause_hypothesis="Live submit path retained guard evidence that the candidate judge decision was wait/resting-entry.",
                    root_cause="The deployed runtime treated orderbook/resting entry as enough to arm a BUY attempt even though the judge did not produce a fresh valid BUY approval.",
                    affected_files=["bot/phase_c43_autonomous_entry_live.py", "bot/phase_c_live_guard.py"],
                    affected_functions=["run_autonomous_entry_live_once", "build_phase_c_live_guard_snapshot"],
                    affected_runtime_period="2026-06-16 to 2026-06-18 live attempts",
                    live_money_risk="high",
                    state_integrity_risk="medium",
                    was_live_order_possible=True,
                    did_live_order_happen=submitted_bool,
                    needs_patch=True,
                    needs_operator_action=False,
                )
            )

    precision_events = [
        item
        for item in order_like
        if "INVALID_PRICE_PRECISION" in json.dumps(item["raw"], default=str)
        or "INVALID_SIZE_PRECISION" in json.dumps(item["raw"], default=str)
        or "post only" in json.dumps(item["raw"], default=str).lower()
    ]
    if precision_events:
        first = precision_events[0]["event"]
        incidents.append(
            mk_incident(
                incident_id="INC-PRECISION-REJECTS-001",
                incident_type="product_precision_reject",
                timestamp=first.get("timestamp"),
                ticker=first.get("ticker"),
                severity="P1",
                evidence_file=precision_events[0]["source"],
                evidence_line_or_record=str(precision_events[0]["line"]),
                root_cause_hypothesis="Runtime submitted or attempted payloads before product-rule price/base normalization was consistently enforced.",
                root_cause="Product rules/normalized payload context was missing or not applied on all C4.3 submit paths; Coinbase rejected invalid increments or post-only crossing.",
                affected_files=["bot/product_rules.py", "bot/phase_c_live_submitter.py", "bot/orderbook_entry_planner.py"],
                affected_functions=["canonical_product_rules", "validate_limit_buy_payload", "submit_phase_c_limit_buy"],
                affected_runtime_period="2026-06-17 precision reject window",
                live_money_risk="low",
                state_integrity_risk="low",
                was_live_order_possible=True,
                did_live_order_happen=False,
                needs_patch=True,
                needs_operator_action=False,
            )
        )

    for item in order_like:
        event = item["event"]
        status = str(first_value(item["raw"], ("status", "state")) or "").lower()
        exchange_id = event.get("exchange_order_id")
        if status in {"submitted", "open", "accepted", "filled", "cancelled", "canceled"} and not exchange_id:
            incidents.append(
                mk_incident(
                    incident_id=f"INC-STATE-ID-{len(incidents)+1:03d}",
                    incident_type="local_state_exchange_id_missing",
                    timestamp=event.get("timestamp"),
                    ticker=event.get("ticker"),
                    severity="P1",
                    evidence_file=item["source"],
                    evidence_line_or_record=str(item["line"]),
                    root_cause_hypothesis="Historical local order state was written or carried without durable exchange_order_id evidence.",
                    root_cause="Legacy smoke/order-store paths did not uniformly require exchange_order_id before non-terminal local lifecycle state.",
                    affected_files=["bot/order_store.py", "bot/phase_c43_autonomous_entry_live.py", "tools/*audit*"],
                    affected_functions=["OrderStore.upsert_order", "run_autonomous_entry_live_once"],
                    affected_runtime_period="historical smoke/pilot records; no current open order found",
                    live_money_risk="low",
                    state_integrity_risk="medium",
                    was_live_order_possible=True,
                    did_live_order_happen=True,
                    needs_patch=True,
                    needs_operator_action=False,
                )
            )
            break

    open_risk_positions = []
    for pos in positions:
        if str(pos.get("status") or "").lower() != "open":
            continue
        if pos.get("position_risk_incomplete") or pos.get("protective_stop_status") == "position_risk_incomplete":
            open_risk_positions.append(pos)
    if open_risk_positions:
        tickers = ",".join(str(pos.get("ticker")) for pos in open_risk_positions)
        incidents.append(
            mk_incident(
                incident_id="INC-OPEN-POS-RISK-001",
                incident_type="position_risk_incomplete_active",
                timestamp=max([dt_s(first_timestamp(pos)) for pos in open_risk_positions if first_timestamp(pos)] or [None]),
                ticker=tickers,
                severity="P1",
                evidence_file="state/positions.json",
                evidence_line_or_record="open positions with protective_stop_status=position_risk_incomplete",
                root_cause_hypothesis="Open positions exist before complete deterministic D2/D3 risk state was finalized or reconciled.",
                root_cause="Position management lifecycle records show protective stop/risk state incomplete while heartbeat escalates stop or review conditions; Mode B remains policy-blocked for autonomous market stop exits.",
                affected_files=["bot/phase_c43_lifecycle_orchestrator.py", "bot/phase_d3_controlled_live_exits.py", "run_trader_loop.py"],
                affected_functions=["apply fill lifecycle", "heartbeat position review", "controlled stop-exit policy route"],
                affected_runtime_period="active as of latest state snapshot",
                live_money_risk="medium",
                state_integrity_risk="medium",
                was_live_order_possible=False,
                did_live_order_happen=False,
                needs_patch=True,
                needs_operator_action=True,
            )
        )

    lock_path = root / "state" / "run_trader_loop.lock"
    if lock_path.exists():
        lock_pid = lock_path.read_text(encoding="utf-8", errors="replace").strip()
        note = "host systemctl/ps validation unavailable from sandbox"
        if journal_meta.get("available"):
            note = "journal read succeeded; systemctl/host PID validation unavailable from sandbox"
        incidents.append(
            mk_incident(
                incident_id="INC-RUNTIME-LOCK-001",
                incident_type="stale_or_unverified_runtime_lock",
                timestamp=dt_s(datetime.fromtimestamp(lock_path.stat().st_mtime, tz=timezone.utc)),
                ticker=None,
                severity="P1",
                evidence_file="state/run_trader_loop.lock",
                evidence_line_or_record=f"pid={lock_pid}",
                root_cause_hypothesis=f"Runtime lock exists but host service/PID liveness could not be confirmed read-only here; {note}.",
                root_cause="The pre-restart gate cannot prove single-process integrity from the available sandbox evidence.",
                affected_files=["run_trader_loop.py", "tools/show_autonomous_live_run_status.py"],
                affected_functions=["single process lock handling", "pre-restart status gate"],
                affected_runtime_period="active at audit time",
                live_money_risk="low",
                state_integrity_risk="medium",
                was_live_order_possible=False,
                did_live_order_happen=False,
                needs_patch=True,
                needs_operator_action=True,
            )
        )

    for violation in amount_audit.get("violations", []):
        incidents.append(
            mk_incident(
                incident_id=f"INC-AMOUNT-{len(incidents)+1:03d}",
                incident_type=violation["incident_type"],
                timestamp=violation.get("timestamp"),
                ticker=violation.get("ticker"),
                configured_limit=violation.get("configured_limit"),
                observed_value=violation.get("observed_value"),
                severity=violation.get("severity", "P0"),
                evidence_file=violation.get("evidence_file", ""),
                evidence_line_or_record=violation.get("evidence_line_or_record", ""),
                root_cause_hypothesis=violation.get("root_cause_hypothesis", ""),
                root_cause=violation.get("root_cause_hypothesis", ""),
                affected_files=["bot/phase_c_live_guard.py", "bot/phase_c_live_submitter.py"],
                affected_functions=["amount cap guard", "submit payload builder"],
                affected_runtime_period="observed order-like record",
                live_money_risk="high",
                state_integrity_risk="medium",
                was_live_order_possible=True,
                did_live_order_happen=True,
                needs_patch=True,
                needs_operator_action=True,
            )
        )

    if amount_audit.get("suspicious_records"):
        stale_config = next((item for item in amount_audit["suspicious_records"] if item["incident_type"] == "stale_config"), None)
        if stale_config:
            incidents.append(
                mk_incident(
                    incident_id="INC-CONFIG-DEFAULT-001",
                    incident_type="stale_config",
                    timestamp=None,
                    ticker=None,
                    configured_limit=stale_config.get("configured_limit"),
                    observed_value=stale_config.get("observed_value"),
                    severity="P2",
                    evidence_file=stale_config["evidence_file"],
                    evidence_line_or_record=stale_config["evidence_line_or_record"],
                    root_cause_hypothesis=stale_config["root_cause_hypothesis"],
                    root_cause="Approved profile overrides .env at runtime, but audits/readiness that inspect .env alone can report stale default quote behavior.",
                    affected_files=["bot/config.py", "tools/*readiness*", "tools/*audit*"],
                    affected_functions=["BotConfig.__post_init__", "readiness profile checks"],
                    affected_runtime_period="current config overlay",
                    live_money_risk="none",
                    state_integrity_risk="none",
                    was_live_order_possible=False,
                    did_live_order_happen=False,
                    needs_patch=True,
                    needs_operator_action=False,
                )
            )

    report_paths = [
        root / "reports" / "audits" / "objective-trade-score-audit-latest.md",
        root / "reports" / "audits" / "orderbook-entry-opportunity-audit-latest.md",
        root / "reports" / "audits" / "setup-pattern-and-parameter-gap-analysis-latest.md",
        root / "reports" / "audits" / "reflection-learning-context-latest.md",
    ]
    existing_reports = [str(path.relative_to(root)) for path in report_paths if path.exists()]
    if existing_reports:
        incidents.append(
            mk_incident(
                incident_id="INC-AGENT-CONTEXT-001",
                incident_type="agent_context_report_only_gap",
                timestamp=None,
                ticker=None,
                severity="P2",
                evidence_file=", ".join(existing_reports),
                evidence_line_or_record="latest reports",
                root_cause_hypothesis="Objective score, opportunity memory, setup-pattern and reflection artifacts exist, but parts are report-only or diagnostic unless explicitly wired into runtime prompts/guards.",
                root_cause="Learning/audit artifacts are not uniformly part of deterministic execution authority; some context improves reports without changing live safety gates.",
                affected_files=["run_trader_loop.py", "bot/execution_planner.py", "bot/orderbook_entry_planner.py", "tools/*audit*"],
                affected_functions=["prompt assembly", "judge/planner context assembly", "audit status wording"],
                affected_runtime_period="current reporting/runtime context",
                live_money_risk="low",
                state_integrity_risk="none",
                was_live_order_possible=False,
                did_live_order_happen=False,
                needs_patch=True,
                needs_operator_action=False,
            )
        )

    unique: list[dict[str, Any]] = []
    for incident in incidents:
        key = (incident["incident_type"], incident["evidence_file"], incident["evidence_line_or_record"])
        if key in seen_types:
            continue
        seen_types.add(key)
        unique.append(incident)
    return unique


def build_fix_plan(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "fix_id": "FIX-P0-001",
            "priority": "P0",
            "problem": "Resting/orderbook preview path historically armed live BUY while judge decisions were wait/no valid_trade_plan.",
            "root_cause": "Fresh approve_trade + BUY + valid_trade_plan was not a hard prerequisite for every live-entry path.",
            "proposed_change": "Keep/enforce fail-closed guard requiring fresh judge live BUY approval before any C4.3 live submit; add audit assertion that wait/preview cannot set live_submit_attempted.",
            "files_to_change": ["bot/phase_c43_autonomous_entry_live.py", "bot/phase_c_live_guard.py", "tests/test_phase_c43_autonomous_entry_live.py", "tests/test_phase_c_live_guard.py"],
            "tests_to_add": ["wait + resting_entry_eligible cannot submit live", "valid_trade_plan=false cannot submit live", "prepare_resting_limit_entry=false cannot arm submit"],
            "live_side_effects": False,
            "operator_action_required": "do not restart until tests pass and next-cycle evidence confirms guard_allows_live_submit=false for wait/preview paths",
            "rollback_plan": "Revert guard/test patch only; no state/env changes.",
            "success_criteria": ["No live_submit_attempted when valid_trade_plans=0", "Phase C guard has hard_block fresh_judge_buy_approval_valid_plan_required_for_live_entry"],
            "stop_conditions": ["Any live submit with judge_decision=wait", "Any accepted order without fresh approve_trade BUY evidence"],
        },
        {
            "fix_id": "FIX-P1-002",
            "priority": "P1",
            "problem": "Coinbase INVALID_PRICE_PRECISION/INVALID_SIZE_PRECISION rejects and post-only crossing attempts occurred.",
            "root_cause": "Product rules and normalized payload were not guaranteed on every live submit attempt.",
            "proposed_change": "Make canonical product_rules/base_increment/price_increment mandatory for live submit and keep quote->base conversion centralized in validate_limit_buy_payload.",
            "files_to_change": ["bot/product_rules.py", "bot/phase_c_live_submitter.py", "bot/orderbook_entry_planner.py", "tests/test_product_rules.py", "tests/test_phase_c_live_submitter.py"],
            "tests_to_add": ["missing product rules fail closed", "quote size never equals base size", "price/base quantization matches Coinbase increments"],
            "live_side_effects": False,
            "operator_action_required": "none beyond observing next full cycle after restart gate is clear",
            "rollback_plan": "Revert validator hardening only if it blocks all valid normalized submits; keep fail-closed behavior.",
            "success_criteria": ["No INVALID_PRICE_PRECISION rejects after patch", "No INVALID_SIZE_PRECISION rejects after patch"],
            "stop_conditions": ["Any submit attempt with missing base_increment or price_increment", "Any base_size equals quote_size for quote-sized order"],
        },
        {
            "fix_id": "FIX-P1-003",
            "priority": "P1",
            "problem": "Historical local order records include live/final states without durable exchange_order_id evidence.",
            "root_cause": "Legacy smoke/order-store paths allowed state writes before exchange id was mandatory.",
            "proposed_change": "Add audit/readiness blocker for non-terminal live orders without exchange_order_id; keep lifecycle managers fail-closed when id is missing.",
            "files_to_change": ["bot/order_store.py", "bot/phase_c43_lifecycle_service.py", "tools/build_bot_runtime_forensics.py", "tests/test_phase_c43_lifecycle_service.py"],
            "tests_to_add": ["local open order write requires exchange_order_id", "D3 lifecycle blocks open exit without exchange_order_id"],
            "live_side_effects": False,
            "operator_action_required": "manual review only if a current open order lacks exchange_order_id",
            "rollback_plan": "Remove readiness blocker; do not mutate order state.",
            "success_criteria": ["Current open orders count either zero or every open order has exchange_order_id"],
            "stop_conditions": ["Open order without exchange_order_id", "Fill/cancel apply without terminal exchange evidence"],
        },
        {
            "fix_id": "FIX-P1-004",
            "priority": "P1",
            "problem": "Active positions show protective_stop_status=position_risk_incomplete and heartbeat stop/review escalations while Mode B is disabled.",
            "root_cause": "Open position risk state is not fully reconciled into D2/D3 lifecycle before/after fills.",
            "proposed_change": "Patch D2/D3 readiness so filled entries must produce complete protective stop/invalidation state or remain explicitly blocked from new entries; make heartbeat report exact blocker.",
            "files_to_change": ["bot/phase_c43_lifecycle_orchestrator.py", "bot/phase_d3_controlled_live_exits.py", "run_trader_loop.py", "tests/test_phase_c43_lifecycle_service.py"],
            "tests_to_add": ["filled position without protective stop blocks new entries", "Mode A stop breach remains preview-only"],
            "live_side_effects": False,
            "operator_action_required": "operator must decide how to handle current open risk-incomplete positions before restart/observation",
            "rollback_plan": "Revert readiness wording/guards; no state mutation.",
            "success_criteria": ["Open positions have protective_stop_state_complete or explicit no-live-action blocker", "Heartbeat and reports agree on Mode A preview-only stop behavior"],
            "stop_conditions": ["New entry while any active position has incomplete risk state", "Autonomous market exit route opens without Mode B ACK"],
        },
        {
            "fix_id": "FIX-P1-005",
            "priority": "P1",
            "problem": "Runtime lock/PID state cannot be verified from read-only sandbox evidence.",
            "root_cause": "Pre-restart tooling does not provide a complete read-only single-process proof independent of systemctl/host ps.",
            "proposed_change": "Add read-only status output that combines lock pid, lock mtime, latest journal pid, latest heartbeat/cycle timestamps and explicit liveness confidence.",
            "files_to_change": ["tools/show_autonomous_live_run_status.py", "tools/prepare_autonomous_endurance_run.py", "tests/test_scheduler_cycle_status.py"],
            "tests_to_add": ["stale/unverified lock fails restart gate", "heartbeat fresh but cycle stale is reported separately"],
            "live_side_effects": False,
            "operator_action_required": "operator must clear/verify runtime lock outside this read-only audit before restart",
            "rollback_plan": "Revert status wording only.",
            "success_criteria": ["Restart gate can prove no duplicate process or fails closed"],
            "stop_conditions": ["Lock pid mismatch", "Systemctl/host ps unavailable and lock exists"],
        },
        {
            "fix_id": "FIX-P2-006",
            "priority": "P2",
            "problem": "Audit/status tools can mix old smoke logs, pre-patch rejects and current runtime evidence.",
            "root_cause": "Reports did not consistently split full history, last 24h, since restart and since codepatch.",
            "proposed_change": "Use this forensics report split as a common audit primitive and label smoke/legacy rows explicitly.",
            "files_to_change": ["tools/build_bot_runtime_forensics.py", "tools/*audit*.py"],
            "tests_to_add": ["old smoke logs are labelled legacy", "pre/post restart and pre/post patch splits are deterministic"],
            "live_side_effects": False,
            "operator_action_required": "none",
            "rollback_plan": "Delete generated reports/tooling only.",
            "success_criteria": ["Latest reports do not count old smoke records as current violations"],
            "stop_conditions": ["Any report states current violation using only legacy smoke evidence"],
        },
        {
            "fix_id": "FIX-P2-007",
            "priority": "P2",
            "problem": ".env default quote is 20 while approved profile default quote is 50; env-only readiness can mislead.",
            "root_cause": "Runtime config overlays approved profile after reading .env, but some audits historically reason about .env alone.",
            "proposed_change": "Make readiness/profile checks approved-profile-aware and replace old default_quote_not_20 wording with effective-default checks.",
            "files_to_change": ["bot/config.py", "tools/*readiness*.py", "tests/test_full_poc_workflow_readiness.py"],
            "tests_to_add": ["default quote 50 approved profile is intended", ".env 20 does not become blocker when approved profile hash is loaded"],
            "live_side_effects": False,
            "operator_action_required": "none",
            "rollback_plan": "Revert readiness wording/tests.",
            "success_criteria": ["Reports show env_default_quote and effective_default_quote separately"],
            "stop_conditions": ["Readiness blocks solely on .env DEFAULT_QUOTE_SIZE_USDC=20 while approved profile is valid"],
        },
        {
            "fix_id": "FIX-P2-008",
            "priority": "P2",
            "problem": "Objective score, opportunity memory, setup-pattern library and reflection context are partly report-only or diagnostic.",
            "root_cause": "Learning artifacts are intentionally not a direct learning-to-execution bridge, but reports can imply runtime integration.",
            "proposed_change": "Mark each artifact as report-only, prompt-context, or deterministic-guard input; do not connect learning directly to execution.",
            "files_to_change": ["reports/audits/*.md", "tools/*audit*.py", "run_trader_loop.py"],
            "tests_to_add": ["audit labels objective/opportunity/reflection integration state correctly"],
            "live_side_effects": False,
            "operator_action_required": "none",
            "rollback_plan": "Revert report wording only.",
            "success_criteria": ["No report claims deterministic runtime authority for report-only artifacts"],
            "stop_conditions": ["Learning/reflection directly changes execution thresholds without approval"],
        },
    ]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def severity_counts(incidents: list[dict[str, Any]]) -> dict[str, int]:
    return {sev: sum(1 for item in incidents if item.get("severity") == sev) for sev in ("P0", "P1", "P2", "P3")}


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(cell).replace("\n", " ") for cell in row) + " |")
    return "\n".join(out)


def render_timeline_md(timeline: dict[str, Any]) -> str:
    lines = ["# Bot Runtime Timeline", ""]
    meta = timeline["metadata"]
    lines.append(f"Generated at: `{meta['generated_at']}`")
    lines.append(f"Latest event: `{meta.get('latest_event_at')}`")
    lines.append(f"Last restart evidence: `{meta.get('last_restart_at')}`")
    lines.append(f"Last codepatch mtime: `{meta.get('last_codepatch_at')}`")
    lines.append("")
    for split_name, events in timeline["splits"].items():
        lines.append(f"## {split_name}")
        lines.append(f"Events: `{len(events)}`")
        selected = events[-80:] if split_name != "full_available_log_history" else events[-120:]
        rows = [
            [
                event.get("timestamp"),
                event.get("source"),
                event.get("event_type"),
                event.get("ticker") or "",
                "yes" if event.get("live_side_effect") else "no",
                "yes" if event.get("state_side_effect") else "no",
                event.get("summary", "")[:180],
                event.get("evidence") or "",
            ]
            for event in selected
        ]
        lines.append(md_table(["timestamp", "source", "type", "ticker", "live", "state", "summary", "evidence"], rows))
        lines.append("")
    lines.append("## Source Inventory")
    rows = [
        [src["path"], src["rows"], src.get("first_timestamp"), src.get("last_timestamp"), src.get("note", "")]
        for src in meta.get("sources", [])
    ]
    lines.append(md_table(["source", "rows", "first", "last", "note"], rows))
    return "\n".join(lines)


def render_incidents_md(report: dict[str, Any]) -> str:
    lines = ["# Bot Incident And Suspicious Actions", ""]
    lines.append(f"Generated at: `{report['generated_at']}`")
    lines.append(f"Severity counts: `{report['severity_counts']}`")
    lines.append("")
    rows = [
        [
            item["severity"],
            item["incident_id"],
            item["incident_type"],
            item.get("timestamp") or "",
            item.get("ticker") or "",
            item["live_money_risk"],
            item["state_integrity_risk"],
            item["evidence_file"],
            item["evidence_line_or_record"],
        ]
        for item in report["incidents"]
    ]
    lines.append(md_table(["sev", "id", "type", "timestamp", "ticker", "money", "state", "file", "record"], rows))
    lines.append("")
    for item in report["incidents"]:
        lines.append(f"## {item['incident_id']} {item['severity']}")
        lines.append(f"- type: `{item['incident_type']}`")
        lines.append(f"- confirmed: `{item['confirmed']}`")
        lines.append(f"- root cause: {item['root_cause']}")
        lines.append(f"- affected runtime: {item['affected_runtime_period']}")
        lines.append(f"- live possible/happened: `{item['was_live_order_possible']}` / `{item['did_live_order_happen']}`")
        lines.append(f"- needs patch/operator: `{item['needs_patch']}` / `{item['needs_operator_action']}`")
        lines.append("")
    return "\n".join(lines)


def render_amount_md(report: dict[str, Any]) -> str:
    lines = ["# Amount Cap Compliance Audit", ""]
    lines.append(f"Generated at: `{report['generated_at']}`")
    lines.append(f"Conclusion: `{report['conclusion']}`")
    lines.append("")
    lines.append("## Configured")
    lines.append("```json")
    lines.append(json.dumps(report["configured"], indent=2, sort_keys=True))
    lines.append("```")
    lines.append("")
    lines.append("## Observed")
    lines.append(f"- observed_max_requested_quote: `{report['observed_max_requested_quote']}`")
    lines.append(f"- observed_max_base_size: `{report['observed_max_base_size']}`")
    lines.append(f"- observed_max_filled_quote: `{report['observed_max_filled_quote']}`")
    lines.append("")
    lines.append("## Violations")
    if report["violations"]:
        lines.append(md_table(["type", "timestamp", "ticker", "limit", "observed", "evidence"], [[v["incident_type"], v.get("timestamp") or "", v.get("ticker") or "", v.get("configured_limit") or "", v.get("observed_value") or "", f"{v.get('evidence_file')}:{v.get('evidence_line_or_record')}"] for v in report["violations"]]))
    else:
        lines.append("No confirmed amount/cap violations found.")
    lines.append("")
    lines.append("## Suspicious / Legacy Records")
    rows = [
        [item["severity"], item["incident_type"], item.get("timestamp") or "", item.get("ticker") or "", item.get("observed_value") or "", f"{item.get('evidence_file')}:{item.get('evidence_line_or_record')}"]
        for item in report["suspicious_records"][:120]
    ]
    lines.append(md_table(["sev", "type", "timestamp", "ticker", "observed", "evidence"], rows) if rows else "None.")
    return "\n".join(lines)


def render_fix_plan_md(report: dict[str, Any]) -> str:
    lines = ["# Bot Incident Fix Plan", ""]
    lines.append(f"Generated at: `{report['generated_at']}`")
    lines.append("")
    rows = [
        [fix["priority"], fix["fix_id"], fix["problem"], ", ".join(fix["files_to_change"])]
        for fix in report["fixes"]
    ]
    lines.append(md_table(["priority", "id", "problem", "files"], rows))
    lines.append("")
    for fix in report["fixes"]:
        lines.append(f"## {fix['fix_id']} {fix['priority']}")
        lines.append(f"- problem: {fix['problem']}")
        lines.append(f"- root_cause: {fix['root_cause']}")
        lines.append(f"- proposed_change: {fix['proposed_change']}")
        lines.append(f"- live_side_effects: `{fix['live_side_effects']}`")
        lines.append(f"- operator_action_required: {fix['operator_action_required']}")
        lines.append(f"- success_criteria: {', '.join(fix['success_criteria'])}")
        lines.append(f"- stop_conditions: {', '.join(fix['stop_conditions'])}")
        lines.append("")
    return "\n".join(lines)


def build_reports(root: Path, include_journal: bool, journal_since: str | None, journal_limit: int) -> dict[str, Any]:
    generated_at = dt_s(datetime.now(tz=timezone.utc))
    config = configured_values(root)
    sources = inventory_jsonl_sources(root)
    log_events, log_order_like = collect_log_events(root, config)
    state_events, state_order_like, positions = collect_state_events(root, config)
    config_events = collect_config_events(root, config)
    report_events, report_inventory = collect_report_events(root, config)
    journal_events: list[dict[str, Any]] = []
    journal_meta: dict[str, Any] = {"available": False, "skipped": True}
    if include_journal:
        journal_events, journal_meta = collect_journal_events(root, config, journal_since, journal_limit)
    events = sort_events(log_events + state_events + config_events + report_events + journal_events)
    order_like = log_order_like + state_order_like
    latest = latest_timestamp(events)
    last_patch, patch_files = latest_codepatch_at(root)
    last_restart = latest_journal_restart(events)
    splits = split_timeline(events, latest, last_restart, last_patch)
    timeline = {
        "metadata": {
            "generated_at": generated_at,
            "latest_event_at": dt_s(latest),
            "last_restart_at": last_restart,
            "last_codepatch_at": dt_s(last_patch),
            "codepatch_files": patch_files,
            "sources": [record.__dict__ for record in sources],
            "reports_inventory": report_inventory,
            "journal": journal_meta,
            "config": config,
        },
        "splits": splits,
    }
    amount_audit = analyze_amounts(config, order_like)
    amount_audit["generated_at"] = generated_at
    incidents = analyze_incidents(root, events, order_like, positions, amount_audit, journal_meta)
    incident_report = {
        "generated_at": generated_at,
        "severity_counts": severity_counts(incidents),
        "incidents": incidents,
    }
    fix_plan = {
        "generated_at": generated_at,
        "fixes": build_fix_plan(incidents),
    }
    return {
        "timeline": timeline,
        "amount": amount_audit,
        "incidents": incident_report,
        "fix_plan": fix_plan,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root, default cwd")
    parser.add_argument("--no-journal", action="store_true", help="Skip journalctl read")
    parser.add_argument("--journal-since", default="2026-06-16 00:00:00", help="journalctl --since value")
    parser.add_argument("--journal-limit", type=int, default=2500, help="Maximum latest journal rows to read")
    parser.add_argument("--json", action="store_true", help="Print compact JSON summary")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    reports = build_reports(
        root=root,
        include_journal=not args.no_journal,
        journal_since=args.journal_since,
        journal_limit=args.journal_limit,
    )
    out_dir = root / "reports" / "audits"
    write_json(out_dir / "bot-runtime-timeline-latest.json", reports["timeline"])
    write_md(out_dir / "bot-runtime-timeline-latest.md", render_timeline_md(reports["timeline"]))
    write_json(out_dir / "bot-incident-and-suspicious-actions-latest.json", reports["incidents"])
    write_md(out_dir / "bot-incident-and-suspicious-actions-latest.md", render_incidents_md(reports["incidents"]))
    write_json(out_dir / "amount-cap-compliance-audit-latest.json", reports["amount"])
    write_md(out_dir / "amount-cap-compliance-audit-latest.md", render_amount_md(reports["amount"]))
    write_json(out_dir / "bot-incident-fix-plan-latest.json", reports["fix_plan"])
    write_md(out_dir / "bot-incident-fix-plan-latest.md", render_fix_plan_md(reports["fix_plan"]))
    if args.json:
        print(
            json.dumps(
                {
                    "generated": [
                        "reports/audits/bot-runtime-timeline-latest.json",
                        "reports/audits/bot-runtime-timeline-latest.md",
                        "reports/audits/bot-incident-and-suspicious-actions-latest.json",
                        "reports/audits/bot-incident-and-suspicious-actions-latest.md",
                        "reports/audits/amount-cap-compliance-audit-latest.json",
                        "reports/audits/amount-cap-compliance-audit-latest.md",
                        "reports/audits/bot-incident-fix-plan-latest.json",
                        "reports/audits/bot-incident-fix-plan-latest.md",
                    ],
                    "amount_conclusion": reports["amount"]["conclusion"],
                    "severity_counts": reports["incidents"]["severity_counts"],
                    "event_counts": {key: len(value) for key, value in reports["timeline"]["splits"].items()},
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
