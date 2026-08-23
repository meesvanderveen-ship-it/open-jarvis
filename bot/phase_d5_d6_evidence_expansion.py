from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


PHASE_D5_D6_EVIDENCE_EXPANSION = "d5_d6_evidence_expansion_v1"
ZERO = Decimal("0")
D3_EXIT_PHASE = "D3_controlled_live_reduce_only_exits"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        return Decimal(text if text else default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _decimal_text(value: Decimal) -> str:
    if value == ZERO:
        return "0"
    return format(value.normalize(), "f")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _seconds_between(start: Any, end: Any) -> Optional[Decimal]:
    start_dt = _parse_time(start)
    end_dt = _parse_time(end)
    if not start_dt or not end_dt:
        return None
    return max(ZERO, Decimal(str((end_dt - start_dt).total_seconds())))


def _first_present(row: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def orders_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = payload.get("orders", payload)
    if isinstance(raw, dict):
        return [dict(order) for order in raw.values() if isinstance(order, dict)]
    if isinstance(raw, list):
        return [dict(order) for order in raw if isinstance(order, dict)]
    return []


def positions_from_payload(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = payload.get("positions", payload)
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            ticker = _normalize_ticker(value.get("ticker") or key)
            if ticker:
                out[ticker] = dict(value)
    elif isinstance(raw, list):
        for value in raw:
            if not isinstance(value, dict):
                continue
            ticker = _normalize_ticker(value.get("ticker"))
            if ticker:
                out[ticker] = dict(value)
    return out


def _is_d3_exit_order(order: Dict[str, Any]) -> bool:
    if str(order.get("side") or "").strip().upper() != "SELL":
        return False
    phase = str(order.get("phase") or "").strip()
    cid = str(order.get("client_order_id") or "").strip().lower()
    mode = str(order.get("mode") or order.get("source_mode") or "").strip().lower()
    return phase == D3_EXIT_PHASE or cid.startswith("phased3-") or cid.startswith("phased4-") or "d3" in mode


def _d3_orders(orders: Iterable[Dict[str, Any]], ticker: str = "BTC-USDC") -> List[Dict[str, Any]]:
    selected = _normalize_ticker(ticker)
    return [
        dict(order)
        for order in orders
        if _is_d3_exit_order(order)
        and _normalize_ticker(order.get("ticker") or order.get("product_id")) == selected
    ]


def _client_order_id(order: Dict[str, Any]) -> str:
    return str(order.get("client_order_id") or order.get("id") or "").strip()


def _order_label(order: Dict[str, Any]) -> str:
    label = str(order.get("d3_exit_label") or order.get("exit_label") or order.get("label") or "").strip()
    if label:
        return label
    cid = _client_order_id(order).upper()
    if "TPCLOSE" in cid or "TP_CLOSE" in cid:
        return "TP_CLOSE"
    if "TP1" in cid:
        return "TP1"
    if "TP2" in cid:
        return "TP2"
    return ""


def _terminal_time(order: Dict[str, Any]) -> Any:
    return _first_present(
        order,
        (
            "terminal_at",
            "closed_at",
            "filled_at",
            "cancelled_at",
            "canceled_at",
            "expired_at",
            "rejected_at",
            "updated_at",
        ),
    )


def _submitted_time(order: Dict[str, Any]) -> Any:
    return _first_present(order, ("submitted_at", "created_at", "order_created_at", "planned_at"))


def _filled_base(order: Dict[str, Any]) -> Decimal:
    return _to_decimal(_first_present(order, ("filled_base", "filled_size", "filled_size_base")), "0")


def _status(order: Dict[str, Any]) -> str:
    status = str(order.get("status") or "").strip().lower()
    return {"canceled": "cancelled"}.get(status, status or "unknown")


def _duration_bucket(seconds: Optional[Decimal]) -> str:
    if seconds is None:
        return "unknown"
    if seconds < Decimal("900"):
        return "<15m"
    if seconds < Decimal("3600"):
        return "15m-1h"
    if seconds < Decimal("21600"):
        return "1h-6h"
    if seconds < Decimal("86400"):
        return "6h-24h"
    return ">=24h"


def _evidence_sources(root: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    candidates = [
        "state/open_orders.json",
        "state/positions.json",
        "docs/CODEX_PROJECT_CONTEXT.md",
        "reports/d6/safe-regression-harness-20260609.json",
        "reports/d6/exit-workflow-readiness-report-20260609.json",
        "reports/d6/state-hygiene-cleanup-preview-20260609.json",
        "logs/phase_d3_controlled_live_exits.jsonl",
        "logs/order_events.jsonl",
        "logs/execution_outcomes.jsonl",
        "logs/phase_c43_fill_reconciliation.jsonl",
        "logs/phase_c43_lifecycle_service.jsonl",
    ]
    sources: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for rel in candidates:
        path = root / rel
        exists = path.exists()
        sources.append({"path": rel, "available": exists, "bytes": path.stat().st_size if exists else 0})
        if not exists and rel.startswith("logs/"):
            warnings.append(f"optional_evidence_source_missing:{rel}")
    return sources, warnings


def _direct_fee_from_context(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {
            "available": False,
            "source": str(path),
            "fee_quote": None,
            "reason": "context_file_missing",
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    candidates: List[Decimal] = []
    for match in re.finditer(r"total_fees[=`:\s]+([0-9]+(?:\.[0-9]+)?)", text):
        window = text[max(0, match.start() - 500) : match.end() + 500].lower()
        if "tp_close" in window or "tpclose" in window:
            candidates.append(_to_decimal(match.group(1), "0"))
    if not candidates:
        for match in re.finditer(r"0\.0288156", text):
            window = text[max(0, match.start() - 500) : match.end() + 500].lower()
            if "tp_close" in window or "tpclose" in window:
                candidates.append(Decimal("0.0288156"))
    if not candidates:
        return {
            "available": False,
            "source": str(path),
            "fee_quote": None,
            "reason": "no_local_direct_tp_close_fee_evidence_found",
        }
    fee = max(candidates)
    return {
        "available": True,
        "source": str(path),
        "fee_quote": _decimal_text(fee),
        "reason": "local_context_direct_tp_close_total_fees",
    }


def _fee_evidence(
    *,
    root: Path,
    d3_orders: Sequence[Dict[str, Any]],
    positions: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    tp_close_orders = [order for order in d3_orders if _order_label(order).upper() == "TP_CLOSE"]
    filled_tp_close = [order for order in tp_close_orders if _status(order) == "filled"]
    selected = filled_tp_close[-1] if filled_tp_close else (tp_close_orders[-1] if tp_close_orders else {})
    position = positions.get("BTC-USDC", {})
    lifecycle_values = {
        "order_fees_paid": _decimal_text(_to_decimal(selected.get("fees_paid"), "0")),
        "order_last_fill_delta_fees": _decimal_text(_to_decimal(selected.get("last_fill_delta_fees"), "0")),
        "position_last_d3_reconcile_fees_delta": _decimal_text(
            _to_decimal(position.get("last_d3_reconcile_fees_delta"), "0")
        ),
    }
    lifecycle_max = max((_to_decimal(value, "0") for value in lifecycle_values.values()), default=ZERO)
    direct = _direct_fee_from_context(root / "docs" / "CODEX_PROJECT_CONTEXT.md")
    direct_fee = _to_decimal(direct.get("fee_quote"), "0")
    fee_gap_present: Any
    if direct.get("available"):
        fee_gap_present = direct_fee != lifecycle_max
    elif selected:
        fee_gap_present = "unknown"
    else:
        fee_gap_present = "unknown"
    return {
        "tp_close_fee_discrepancy_status": "gap_present"
        if fee_gap_present is True
        else ("unknown" if fee_gap_present == "unknown" else "no_gap_detected"),
        "tp_close_order_client_order_id": _client_order_id(selected),
        "tp_close_exchange_order_id": str(selected.get("exchange_order_id") or selected.get("order_id") or ""),
        "lifecycle_fee_evidence": lifecycle_values,
        "direct_exchange_fee_evidence": direct,
        "fee_gap_present": fee_gap_present,
        "human_review_required": bool(fee_gap_present is True or fee_gap_present == "unknown"),
        "no_mutation_performed": True,
    }


def _no_fill_duration(d3_orders: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    warnings: List[str] = []
    buckets = {"<15m": 0, "15m-1h": 0, "1h-6h": 0, "6h-24h": 0, ">=24h": 0, "unknown": 0}
    for order in d3_orders:
        status = _status(order)
        filled = _filled_base(order)
        if filled > ZERO or status == "filled":
            continue
        start = _submitted_time(order)
        end = _terminal_time(order)
        seconds = _seconds_between(start, end)
        bucket = _duration_bucket(seconds)
        buckets[bucket] += 1
        if seconds is None:
            warnings.append(f"missing_no_fill_timestamp:{_client_order_id(order)}")
        rows.append(
            {
                "client_order_id": _client_order_id(order),
                "label": _order_label(order),
                "status": status,
                "submitted_at": start or "",
                "terminal_at": end or "",
                "duration_seconds": _decimal_text(seconds) if seconds is not None else None,
                "duration_bucket": bucket,
            }
        )
    durations = [_to_decimal(row["duration_seconds"], "0") for row in rows if row.get("duration_seconds") is not None]
    return {
        "open_no_fill_event_count": len(rows),
        "duration_buckets": buckets,
        "duration_seconds_min": _decimal_text(min(durations)) if durations else None,
        "duration_seconds_max": _decimal_text(max(durations)) if durations else None,
        "duration_seconds_avg": _decimal_text(sum(durations, ZERO) / Decimal(len(durations))) if durations else None,
        "events": rows,
        "warnings": warnings,
    }


def _cancel_replace_timing(d3_orders: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_client_id = {_client_order_id(order): order for order in d3_orders if _client_order_id(order)}
    chains: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for replacement in d3_orders:
        original_id = str(replacement.get("replacement_of_client_order_id") or "").strip()
        if not original_id:
            continue
        original = by_client_id.get(original_id, {})
        cancel_time = _terminal_time(original)
        replacement_time = _submitted_time(replacement)
        delta = _seconds_between(cancel_time, replacement_time)
        if not original:
            warnings.append(f"replacement_original_missing:{_client_order_id(replacement)}")
        if delta is None:
            warnings.append(f"cancel_replace_timestamp_missing:{_client_order_id(replacement)}")
        terminal_status = _status(replacement)
        terminal_present = terminal_status in {"filled", "cancelled", "expired", "rejected"}
        chains.append(
            {
                "original_client_order_id": original_id,
                "original_status": _status(original) if original else "missing",
                "cancel_event_at": cancel_time or "",
                "replacement_client_order_id": _client_order_id(replacement),
                "replacement_status": terminal_status,
                "replacement_submitted_at": replacement_time or "",
                "cancel_to_replacement_seconds": _decimal_text(delta) if delta is not None else None,
                "terminal_evidence_present": terminal_present,
                "replacement_terminal_at": _terminal_time(replacement) or "",
            }
        )
    return {
        "cancel_replace_chain_count": len(chains),
        "chains": chains,
        "warnings": warnings,
    }


def _partial_fill_evidence(d3_orders: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for order in d3_orders:
        status = _status(order)
        filled = _filled_base(order)
        size = _to_decimal(_first_present(order, ("size_base", "base_size", "remaining_size")), "0")
        if status in {"partial", "partially_filled"} or (filled > ZERO and size > ZERO and filled < size):
            rows.append(
                {
                    "client_order_id": _client_order_id(order),
                    "label": _order_label(order),
                    "status": status,
                    "filled_base": _decimal_text(filled),
                    "size_base": _decimal_text(size),
                    "terminal_at": _terminal_time(order) or "",
                }
            )
    if rows:
        status = "present"
        present = True
    else:
        status = "absent"
        present = False
    return {
        "partial_fills_present": present,
        "status": status,
        "events": rows,
        "blockers": [],
        "missing_fields": [],
    }


def build_d5_d6_evidence_expansion_report(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    source_summary, source_warnings = _evidence_sources(project_root)
    orders = orders_from_payload(_load_json(project_root / "state" / "open_orders.json"))
    positions = positions_from_payload(_load_json(project_root / "state" / "positions.json"))
    d3_orders = _d3_orders(orders)

    fee = _fee_evidence(root=project_root, d3_orders=d3_orders, positions=positions)
    no_fill = _no_fill_duration(d3_orders)
    cancel_replace = _cancel_replace_timing(d3_orders)
    partial = _partial_fill_evidence(d3_orders)

    warnings: List[str] = list(source_warnings)
    warnings.extend(no_fill.get("warnings") or [])
    warnings.extend(cancel_replace.get("warnings") or [])
    if fee.get("fee_gap_present") is True:
        warnings.append("tp_close_fee_gap_requires_human_review")
    if fee.get("fee_gap_present") == "unknown":
        warnings.append("tp_close_fee_gap_unknown_missing_local_direct_evidence")

    stop_reasons: List[str] = []
    if partial.get("partial_fills_present") and any(not row.get("terminal_at") for row in partial.get("events") or []):
        stop_reasons.append("partial_fill_without_terminal_timestamp")

    if stop_reasons:
        classification = "STOP_NOW"
    elif warnings:
        classification = "WATCH"
    else:
        classification = "OK"

    flags = {
        "d5_d6_evidence_expansion_ready": classification != "STOP_NOW",
        "human_review_ready": classification != "STOP_NOW",
        "learning_to_execution_ready": False,
        "parameter_change_allowed": False,
        "parameter_review_approved": False,
        "master_live_exit_ready": False,
        "follower_ready_for_live": False,
    }

    return _json_safe(
        {
            "phase": PHASE_D5_D6_EVIDENCE_EXPANSION,
            "generated_at": generated_at or _now_iso(),
            "report_only": True,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "state_write_performed": False,
            "parameter_mutation_performed": False,
            "learning_to_execution_attempted": False,
            "classification": classification,
            "stop_reasons": sorted(set(stop_reasons)),
            "watch_reasons": sorted(set(warnings)),
            "evidence_sources_inspected": source_summary,
            "fee_evidence": fee,
            "no_fill_duration": no_fill,
            "cancel_replace_timing": cancel_replace,
            "partial_fill_evidence": partial,
            "readiness_and_governance_flags": flags,
            "recommended_next_sprint": {
                "route": "all-ticker readiness gate",
                "reason": (
                    "D5/D6 human-review evidence is now reportable; the next large safe step is a local "
                    "all-ticker readiness gate that keeps BTC tiny-run authorization separate."
                ),
            },
        }
    )


def render_d5_d6_evidence_expansion_markdown(report: Dict[str, Any]) -> str:
    flags = report.get("readiness_and_governance_flags") or {}
    fee = report.get("fee_evidence") or {}
    no_fill = report.get("no_fill_duration") or {}
    cancel_replace = report.get("cancel_replace_timing") or {}
    partial = report.get("partial_fill_evidence") or {}
    lines = [
        "# D5/D6 Evidence Expansion",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{report.get('report_only')}`",
        f"- coinbase_call_attempted: `{report.get('coinbase_call_attempted')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        f"- learning_to_execution_attempted: `{report.get('learning_to_execution_attempted')}`",
        "",
        "## Fee Evidence",
        "",
        f"- TP_CLOSE fee discrepancy status: `{fee.get('tp_close_fee_discrepancy_status')}`",
        f"- lifecycle fee evidence: `{json.dumps(fee.get('lifecycle_fee_evidence') or {}, sort_keys=True)}`",
        f"- direct exchange fee evidence: `{json.dumps(fee.get('direct_exchange_fee_evidence') or {}, sort_keys=True)}`",
        f"- fee_gap_present: `{fee.get('fee_gap_present')}`",
        f"- human_review_required: `{fee.get('human_review_required')}`",
        "",
        "## No-Fill Duration",
        "",
        f"- open_no_fill_event_count: `{no_fill.get('open_no_fill_event_count')}`",
        f"- duration_buckets: `{json.dumps(no_fill.get('duration_buckets') or {}, sort_keys=True)}`",
        f"- duration_seconds_min: `{no_fill.get('duration_seconds_min')}`",
        f"- duration_seconds_max: `{no_fill.get('duration_seconds_max')}`",
        "",
        "## Cancel/Replace Timing",
        "",
        f"- cancel_replace_chain_count: `{cancel_replace.get('cancel_replace_chain_count')}`",
        f"- warnings: `{'; '.join(cancel_replace.get('warnings') or [])}`",
        "",
        "## Partial-Fill Evidence",
        "",
        f"- partial_fills_present: `{partial.get('partial_fills_present')}`",
        f"- status: `{partial.get('status')}`",
        "",
        "## Readiness And Governance",
        "",
    ]
    for key in (
        "d5_d6_evidence_expansion_ready",
        "human_review_ready",
        "learning_to_execution_ready",
        "parameter_change_allowed",
        "parameter_review_approved",
        "master_live_exit_ready",
        "follower_ready_for_live",
    ):
        lines.append(f"- {key}: `{flags.get(key)}`")
    lines.extend(
        [
            "",
            "## Classification Reasons",
            "",
            f"- stop_reasons: `{'; '.join(report.get('stop_reasons') or [])}`",
            f"- watch_reasons: `{'; '.join(report.get('watch_reasons') or [])}`",
            "",
            "## Recommended Next Sprint",
            "",
            f"- route: `{(report.get('recommended_next_sprint') or {}).get('route')}`",
            f"- reason: `{(report.get('recommended_next_sprint') or {}).get('reason')}`",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_D5_D6_EVIDENCE_EXPANSION",
    "build_d5_d6_evidence_expansion_report",
    "render_d5_d6_evidence_expansion_markdown",
]
