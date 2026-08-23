#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.show_btc_usdc_24h_live_monitor import (  # noqa: E402
    BTC_TICKER,
    OK,
    OPEN_ORDER_STATUSES,
    STOP_NOW,
    WATCH,
    _env_flag_snapshot,
    _iter_jsonl,
    _load_orders,
    _order_sample,
    _parse_ts,
    _read_text,
    _replication_status,
    _scan_loop_text,
    _sha256,
    summarize_orders,
)

PHASE = "btc_usdc_24h_post_run_evidence_pack_v1"
MAX_RECENT_ROWS = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_required_ts(value: str, name: str) -> datetime:
    parsed = _parse_ts(value)
    if not parsed:
        raise SystemExit(f"Invalid {name}: {value!r}")
    return parsed


def _window_rows(rows: Iterable[Dict[str, Any]], start: datetime, stop: datetime) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    for row in rows:
        ts = _row_ts(row)
        if ts and start <= ts <= stop:
            selected.append(row)
    return selected


def _row_ts(row: Dict[str, Any]) -> Optional[datetime]:
    return _parse_ts(row.get("generated_at") or row.get("timestamp") or row.get("created_at") or row.get("updated_at"))


def _window_text_lines(text: str, start: datetime, stop: datetime) -> List[str]:
    selected: List[str] = []
    carry = False
    for line in text.splitlines():
        ts = _line_ts(line)
        if ts:
            carry = start <= ts <= stop
        if carry:
            selected.append(line)
    return selected


def _line_ts(line: str) -> Optional[datetime]:
    match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
    if not match:
        return None
    return _parse_ts(match.group(1).replace(" ", "T") + "+00:00")


def _load_jsonl_window(path: Path, start: datetime, stop: datetime, *, limit_tail: int = 10000) -> List[Dict[str, Any]]:
    return _window_rows(_iter_jsonl(path, limit_tail=limit_tail, since=start), start, stop)


def _counter_sum(rows: Sequence[Dict[str, Any]], keys: Sequence[str]) -> Dict[str, int]:
    totals = {key: 0 for key in keys}
    for row in rows:
        for key in keys:
            try:
                totals[key] += int(row.get(key) or 0)
            except (TypeError, ValueError):
                pass
    return totals


def _extract_scope_and_decisions(loop_lines: Sequence[str]) -> Dict[str, Any]:
    startup_rx = re.compile(
        r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Execution mode=(?P<mode>\w+)\s+\|\s+tickers=(?P<tickers>[A-Z0-9\-,]+)"
    )
    decision_rx = re.compile(
        r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Ticker (?P<ticker>[A-Z0-9]+-USDC) \| gate=(?P<gate>[^|]+) \| decision=(?P<decision>[^|]+) \| side=(?P<side>[^|]+) \| size_quote=(?P<size_quote>[^|]+).*execution_status=(?P<execution_status>[^|]+) \| executed=(?P<executed>True|False)"
    )
    startup_evidence: List[Dict[str, Any]] = []
    decision_rows: List[Dict[str, Any]] = []
    for line in loop_lines:
        startup = startup_rx.search(line)
        if startup:
            ts = _line_ts(line)
            tickers = [ticker.strip() for ticker in startup.group("tickers").split(",") if ticker.strip()]
            startup_evidence.append(
                {
                    "timestamp": _iso(ts) if ts else None,
                    "mode": startup.group("mode"),
                    "tickers": tickers,
                    "raw": line[-300:],
                }
            )
        decision = decision_rx.search(line)
        if decision:
            ts = _line_ts(line)
            decision_rows.append(
                {
                    "timestamp": _iso(ts) if ts else None,
                    "ticker": decision.group("ticker"),
                    "gate": decision.group("gate").strip(),
                    "decision": decision.group("decision").strip(),
                    "side": decision.group("side").strip(),
                    "size_quote": decision.group("size_quote").strip(),
                    "execution_status": decision.group("execution_status").strip(),
                    "executed": decision.group("executed") == "True",
                }
            )
    non_btc_decisions = [row for row in decision_rows if row.get("ticker") != BTC_TICKER]
    multi_ticker_startups = [row for row in startup_evidence if row.get("tickers") != [BTC_TICKER]]
    return {
        "btc_usdc_only_startups": [row for row in startup_evidence if row.get("tickers") == [BTC_TICKER]][-10:],
        "startup_evidence": startup_evidence[-20:],
        "multi_ticker_startups": multi_ticker_startups[-20:],
        "decision_count": len(decision_rows),
        "per_ticker_decision_counts": dict(Counter(str(row.get("ticker")) for row in decision_rows)),
        "per_ticker_executed_counts": dict(Counter(str(row.get("ticker")) for row in decision_rows if row.get("executed"))),
        "non_btc_ticker_decisions": non_btc_decisions[-MAX_RECENT_ROWS:],
        "decision_samples": decision_rows[-MAX_RECENT_ROWS:],
    }


def _lifecycle_summary(rows: Sequence[Dict[str, Any]], loop_lines: Sequence[str]) -> Dict[str, Any]:
    proposed = 0
    applied = 0
    d2 = 0
    d3 = 0
    coinbase_attempted = 0
    statuses: Counter[str] = Counter()
    for row in rows:
        statuses[str(row.get("status") or "unknown")] += 1
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        proposed += _int(summary.get("proposed_actions") or row.get("proposed"))
        applied += _int(summary.get("applied_actions") or row.get("applied"))
        d2 += _int(summary.get("d2_reports") or row.get("d2"))
        d3 += _int(summary.get("d3_previews") or row.get("d3"))
        if summary.get("coinbase_call_attempted") is True or row.get("coinbase_call_attempted") is True:
            coinbase_attempted += 1
    action_rx = re.compile(r"submit|cancel|replace|reprice|apply_local|lifecycle apply", re.IGNORECASE)
    action_lines = [line[-300:] for line in loop_lines if action_rx.search(line)]
    return {
        "event_count": len(rows),
        "statuses": dict(statuses),
        "proposed_count": proposed,
        "applied_count": applied,
        "d2_count": d2,
        "d3_count": d3,
        "coinbase_call_attempted_count": coinbase_attempted,
        "action_signal_count": len(action_lines),
        "action_signal_samples": action_lines[-MAX_RECENT_ROWS:],
        "last_events": list(rows[-MAX_RECENT_ROWS:]),
    }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _recent_file_summary(root: Path, names: Sequence[str], start: datetime, stop: datetime) -> Dict[str, Any]:
    details: Dict[str, Any] = {}
    total = 0
    samples: List[Dict[str, Any]] = []
    for name in names:
        path = root / "logs" / name
        rows = _load_jsonl_window(path, start, stop)
        details[name] = {"exists": path.exists(), "count": len(rows), "last": rows[-1] if rows else None}
        total += len(rows)
        samples.extend(rows[-5:])
    return {"total": total, "details": details, "samples": samples[-MAX_RECENT_ROWS:]}


def _retry_storm(loop_lines: Sequence[str]) -> Dict[str, Any]:
    retry_lines = [line[-300:] for line in loop_lines if re.search(r"retry|rate.?limit|timeout|temporar", line, re.IGNORECASE)]
    return {"retry_signal_count": len(retry_lines), "retry_signal_samples": retry_lines[-MAX_RECENT_ROWS:]}


def _replication_window(root: Path, start: datetime, stop: datetime) -> Dict[str, Any]:
    publish_rows = _load_jsonl_window(root / "logs/replication_publish.jsonl", start, stop)
    outbox_rows = _load_jsonl_window(root / "logs/replication_outbox.jsonl", start, stop)
    all_rows = [*publish_rows, *outbox_rows]
    disabled = []
    disabled_reason = []
    enabled = []
    for row in all_rows:
        text = json.dumps(row, sort_keys=True).lower()
        if "replication_disabled" in text or "skipped" in text:
            disabled.append(row)
            if "replication_disabled" in text:
                disabled_reason.append(row)
        elif "enabled" in text or "posted" in text or "published" in text:
            enabled.append(row)
    return {
        "replication_enabled": False,
        "replication_publish_allowed": False,
        "follower_lifecycle_enabled": False,
        "row_count": len(all_rows),
        "publish_attempt_count": len(publish_rows),
        "outbox_count": len(outbox_rows),
        "disabled_or_skipped_count": len(disabled),
        "replication_disabled_reason_count": len(disabled_reason),
        "replication_disabled_reason_seen": bool(disabled_reason),
        "enabled_or_published_count": len(enabled),
        "last_rows": all_rows[-MAX_RECENT_ROWS:],
    }


def _window_orders(orders: Sequence[Dict[str, Any]], start: datetime, stop: datetime) -> List[Dict[str, Any]]:
    selected = []
    for order in orders:
        ts = _parse_ts(order.get("updated_at") or order.get("created_at"))
        if ts and start <= ts <= stop:
            selected.append(order)
    return selected


def _state_hash_evidence(root: Path, baseline_open: Optional[str], baseline_positions: Optional[str]) -> Dict[str, Any]:
    current = {
        "state/open_orders.json": _sha256(root / "state/open_orders.json"),
        "state/positions.json": _sha256(root / "state/positions.json"),
    }
    baseline = {
        "state/open_orders.json": baseline_open,
        "state/positions.json": baseline_positions,
    }
    drift = {
        key: bool(baseline.get(key) and current.get(key) != baseline.get(key))
        for key in current
    }
    return {"baseline": baseline, "current": current, "drift": drift, "drift_any": any(drift.values())}


def _classify_pack(report: Dict[str, Any]) -> Tuple[str, List[str]]:
    stop: List[str] = []
    watch: List[str] = []
    scope = report["scope_evidence"]
    cycles = report["cycle_evidence"]
    heartbeat = report["heartbeat_evidence"]
    orders = report["order_lifecycle_evidence"]
    llm = report["llm_provider_evidence"]
    replication = report["replication_evidence"]
    hashes = report["state_hash_evidence"]

    if not scope["btc_usdc_only_evidence_present"]:
        watch.append("btc_usdc_only_startup_evidence_missing")
    if scope["non_btc_ticker_evidence"]:
        stop.append("non_btc_ticker_activity_inside_window")
    if scope["multi_ticker_evidence"]:
        stop.append("multi_ticker_runtime_scope_inside_window")
    if cycles["cycle_count"] == 0 and heartbeat["heartbeat_count"] == 0:
        watch.append("no_cycle_or_heartbeat_rows_inside_window")
    if cycles["totals"].get("executed", 0) > 0 and scope["non_btc_ticker_evidence"]:
        stop.append("execution_seen_with_non_btc_scope")
    if orders["window_order_summary"]["executed_non_btc_samples"]:
        stop.append("executed_or_submitted_non_btc_order_inside_window")
    if orders["window_order_summary"]["oversized_notional_samples"]:
        stop.append("order_notional_above_10_usdc_inside_window")
    if orders["current_open_orders"]["open_orders"] > 1:
        stop.append("more_than_one_current_open_order")
    if orders["current_open_orders"]["open_d3_exits"] > 0:
        stop.append("unexpected_current_open_d3_exit")
    if orders["lifecycle"]["coinbase_call_attempted_count"] > 0:
        stop.append("coinbase_call_attempted_signal_inside_window")
    if orders["lifecycle"]["applied_count"] > 0 or orders["lifecycle"]["action_signal_count"] > 0:
        stop.append("submit_cancel_replace_reprice_or_lifecycle_apply_signal_inside_window")
    if llm["corrupt_llm_count"] >= 3:
        stop.append("llm_corrupt_burst_inside_window")
    elif llm["corrupt_llm_count"] > 0:
        watch.append("llm_corrupt_seen_inside_window")
    if llm["provider_error_count"] >= 3:
        stop.append("provider_error_burst_inside_window")
    elif llm["provider_error_count"] > 0:
        watch.append("provider_error_seen_inside_window")
    if llm["retry_storm"]["retry_signal_count"] >= 5:
        stop.append("retry_storm_signal_inside_window")
    if cycles["totals"].get("errors", 0) > 0 or heartbeat["totals"].get("errors", 0) > 0:
        watch.append("cycle_or_heartbeat_errors_inside_window")
    if replication["enabled_or_published_count"] > 0:
        stop.append("replication_unexpectedly_enabled_inside_window")
    if hashes["drift"].get("state/open_orders.json"):
        stop.append("state_hash_drift_open_orders")
    if hashes["drift"].get("state/positions.json"):
        stop.append("state_hash_drift_positions")

    reasons = sorted(set(stop if stop else watch))
    return (STOP_NOW if stop else WATCH if watch else OK), reasons


def build_post_run_evidence_pack(
    *,
    root: Path,
    start_utc: datetime,
    stop_utc: datetime,
    baseline_open_orders_hash: Optional[str] = None,
    baseline_positions_hash: Optional[str] = None,
) -> Dict[str, Any]:
    if stop_utc < start_utc:
        raise ValueError("stop_utc_must_be_after_start_utc")
    root = root.resolve()
    loop_text = _read_text(root / "logs/loop.log", max_chars=8_000_000)
    loop_lines = _window_text_lines(loop_text, start_utc, stop_utc)
    cycle_rows = _load_jsonl_window(root / "logs/cycle_summary.jsonl", start_utc, stop_utc)
    heartbeat_rows = _load_jsonl_window(root / "logs/heartbeat_summary.jsonl", start_utc, stop_utc)
    lifecycle_rows = _load_jsonl_window(root / "logs/phase_c43_lifecycle_service.jsonl", start_utc, stop_utc)
    all_orders = _load_orders(root / "state/open_orders.json")
    window_orders = _window_orders(all_orders, start_utc, stop_utc)
    scope = _extract_scope_and_decisions(loop_lines)
    loop_health = _scan_loop_text("\n".join(loop_lines), since=None)
    corrupt = _recent_file_summary(root, ("llm_corrupt.jsonl", "llm_corrupt_outputs.jsonl"), start_utc, stop_utc)
    provider = _recent_file_summary(root, ("provider_errors.jsonl", "llm_provider_errors.jsonl"), start_utc, stop_utc)

    report: Dict[str, Any] = {
        "phase": PHASE,
        "tool": "build_btc_usdc_24h_post_run_evidence_pack",
        "generated_at": _iso(_now()),
        "run_metadata": {
            "start_utc": _iso(start_utc),
            "stop_utc": _iso(stop_utc),
            "duration_seconds": int((stop_utc - start_utc).total_seconds()),
            "report_mode": "post_run_local_read_only_windowed",
            "replication_enabled": False,
            "replication_publish_allowed": False,
            "follower_lifecycle_enabled": False,
            "no_coinbase_call": True,
            "state_write_performed": False,
            "report_output_write_only": True,
        },
        "scope_evidence": {
            "btc_usdc_only_evidence_present": bool(scope["btc_usdc_only_startups"]),
            "btc_usdc_only_evidence": scope["btc_usdc_only_startups"],
            "non_btc_ticker_evidence": scope["non_btc_ticker_decisions"],
            "multi_ticker_evidence": scope["multi_ticker_startups"],
            "startup_evidence": scope["startup_evidence"],
            "per_ticker_decision_counts": scope["per_ticker_decision_counts"],
            "per_ticker_executed_counts": scope["per_ticker_executed_counts"],
        },
        "cycle_evidence": {
            "cycle_count": len(cycle_rows),
            "totals": _counter_sum(
                cycle_rows,
                ("errors", "approve_trade", "executed", "wait", "reject", "reduce_size", "close_position"),
            ),
            "last_cycle_summaries": cycle_rows[-MAX_RECENT_ROWS:],
            "per_ticker_decisions": scope["decision_samples"],
        },
        "heartbeat_evidence": {
            "heartbeat_count": len(heartbeat_rows),
            "totals": _counter_sum(heartbeat_rows, ("errors", "heartbeat_ok", "deepseek_hold_ok", "full_reviews", "paused", "skipped", "executed")),
            "last_heartbeat_summaries": heartbeat_rows[-MAX_RECENT_ROWS:],
        },
        "order_lifecycle_evidence": {
            "current_open_orders": summarize_orders(all_orders, since=None),
            "window_order_summary": summarize_orders(window_orders, since=start_utc),
            "window_order_samples": [_order_sample(order) for order in window_orders[-MAX_RECENT_ROWS:]],
            "lifecycle": _lifecycle_summary(lifecycle_rows, loop_lines),
            "loop_health": loop_health,
        },
        "llm_provider_evidence": {
            "corrupt_llm_count": corrupt["total"],
            "provider_error_count": provider["total"],
            "corrupt_llm_rows": corrupt["samples"],
            "provider_error_rows": provider["samples"],
            "corrupt_llm_details": corrupt["details"],
            "provider_error_details": provider["details"],
            "retry_storm": _retry_storm(loop_lines),
        },
        "replication_evidence": _replication_window(root, start_utc, stop_utc),
        "env_flags": _env_flag_snapshot(root),
        "state_hash_evidence": _state_hash_evidence(root, baseline_open_orders_hash, baseline_positions_hash),
        "read_only_policy": {
            "no_coinbase_call": True,
            "no_live_action": True,
            "trading_state_write_performed": False,
            "lifecycle_apply_performed": False,
            "local_repair_apply_performed": False,
            "env_mutation_performed": False,
            "parameter_mutation_performed": False,
        },
    }
    status, reasons = _classify_pack(report)
    report["stop_rule_summary"] = {
        "status": status,
        "reasons": reasons,
        "operator_next_step": {
            OK: "archive_evidence_pack_and_wait_for_operator_decision",
            WATCH: "review_watch_reasons_before_any_next_live_step",
            STOP_NOW: "do_not_apply_repair_cancel_fill_reconciliation_or_restart_without_separate_exact_ack",
        }[status],
    }
    report["human_readable_conclusion"] = _conclusion(report)
    return report


def _conclusion(report: Dict[str, Any]) -> Dict[str, Any]:
    status = report["stop_rule_summary"]["status"]
    reasons = report["stop_rule_summary"]["reasons"]
    if status == OK:
        clean = True
        text = "Run window appears clean from local evidence."
    elif status == WATCH:
        clean = False
        text = "Run evidence is not clean enough to advance automatically; review WATCH reasons."
    else:
        clean = False
        text = "Run evidence contains STOP_NOW conditions; separate ACK is required before any apply, repair, cancel or fill reconciliation."
    return {
        "appears_clean": clean,
        "evidence_insufficient": status == WATCH,
        "separate_ack_required_for_apply_repair_cancel_or_fill_reconciliation": status != OK,
        "summary": text,
        "reasons": reasons,
    }


def _markdown(report: Dict[str, Any]) -> str:
    meta = report["run_metadata"]
    stop = report["stop_rule_summary"]
    scope = report["scope_evidence"]
    cycles = report["cycle_evidence"]
    heartbeat = report["heartbeat_evidence"]
    orders = report["order_lifecycle_evidence"]
    llm = report["llm_provider_evidence"]
    replication = report["replication_evidence"]
    hashes = report["state_hash_evidence"]
    lines = [
        "# BTC-USDC 24h Post-Run Evidence Pack",
        "",
        "Read-only local evidence report. No Coinbase calls and no trading-state writes.",
        "",
        "## Run Metadata",
        f"- generated_at: `{report['generated_at']}`",
        f"- start_utc: `{meta['start_utc']}`",
        f"- stop_utc: `{meta['stop_utc']}`",
        f"- duration_seconds: `{meta['duration_seconds']}`",
        f"- report_mode: `{meta['report_mode']}`",
        f"- replication_enabled: `{meta['replication_enabled']}`",
        f"- replication_publish_allowed: `{meta['replication_publish_allowed']}`",
        f"- follower_lifecycle_enabled: `{meta['follower_lifecycle_enabled']}`",
        "",
        "## Stop Rule Summary",
        f"- status: `{stop['status']}`",
        f"- reasons: `{', '.join(stop['reasons']) or 'none'}`",
        f"- operator_next_step: `{stop['operator_next_step']}`",
        "",
        "## Scope Evidence",
        f"- btc_usdc_only_evidence_present: `{scope['btc_usdc_only_evidence_present']}`",
        f"- non_btc_ticker_evidence_count: `{len(scope['non_btc_ticker_evidence'])}`",
        f"- multi_ticker_evidence_count: `{len(scope['multi_ticker_evidence'])}`",
        f"- per_ticker_decision_counts: `{json.dumps(scope['per_ticker_decision_counts'], sort_keys=True)}`",
        "",
        "## Cycle Evidence",
        f"- cycle_count: `{cycles['cycle_count']}`",
        f"- totals: `{json.dumps(cycles['totals'], sort_keys=True)}`",
        "",
        "## Heartbeat Evidence",
        f"- heartbeat_count: `{heartbeat['heartbeat_count']}`",
        f"- totals: `{json.dumps(heartbeat['totals'], sort_keys=True)}`",
        "",
        "## Order And Lifecycle Evidence",
        f"- current_open_orders: `{orders['current_open_orders']['open_orders']}`",
        f"- current_open_d3_exits: `{orders['current_open_orders']['open_d3_exits']}`",
        f"- lifecycle_events: `{orders['lifecycle']['event_count']}`",
        f"- lifecycle_proposed: `{orders['lifecycle']['proposed_count']}`",
        f"- lifecycle_applied: `{orders['lifecycle']['applied_count']}`",
        f"- lifecycle_coinbase_call_attempted: `{orders['lifecycle']['coinbase_call_attempted_count']}`",
        "",
        "## LLM And Provider Evidence",
        f"- corrupt_llm_count: `{llm['corrupt_llm_count']}`",
        f"- provider_error_count: `{llm['provider_error_count']}`",
        f"- retry_signal_count: `{llm['retry_storm']['retry_signal_count']}`",
        "",
        "## Replication Evidence",
        f"- replication_enabled: `{replication['replication_enabled']}`",
        f"- replication_publish_allowed: `{replication['replication_publish_allowed']}`",
        f"- follower_lifecycle_enabled: `{replication['follower_lifecycle_enabled']}`",
        f"- row_count: `{replication['row_count']}`",
        f"- publish_attempt_count: `{replication['publish_attempt_count']}`",
        f"- disabled_or_skipped_count: `{replication['disabled_or_skipped_count']}`",
        f"- replication_disabled_reason_seen: `{replication['replication_disabled_reason_seen']}`",
        f"- enabled_or_published_count: `{replication['enabled_or_published_count']}`",
        "",
        "## State Hash Evidence",
        f"- baseline_open_orders_hash: `{hashes['baseline'].get('state/open_orders.json')}`",
        f"- current_open_orders_hash: `{hashes['current'].get('state/open_orders.json')}`",
        f"- open_orders_hash_drift: `{hashes['drift'].get('state/open_orders.json')}`",
        f"- baseline_positions_hash: `{hashes['baseline'].get('state/positions.json')}`",
        f"- current_positions_hash: `{hashes['current'].get('state/positions.json')}`",
        f"- positions_hash_drift: `{hashes['drift'].get('state/positions.json')}`",
        "",
        "## Conclusion",
        report["human_readable_conclusion"]["summary"],
        "",
    ]
    return "\n".join(lines)


def _assert_reports_live_path(path: Path) -> Path:
    resolved = path
    parts = [part.lower() for part in resolved.parts]
    for index, part in enumerate(parts[:-1]):
        if part == "reports" and parts[index + 1] == "live":
            if ".env" in resolved.name:
                raise ValueError("post_run_evidence_pack_refuses_env_output")
            return resolved
    raise ValueError("post_run_evidence_pack_output_must_be_under_reports_live")


def _atomic_write(path: Path, data: bytes) -> None:
    safe = _assert_reports_live_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    tmp = safe.with_name(f".{safe.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, safe)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build local read-only BTC-USDC 24h post-run evidence pack. No Coinbase calls.")
    parser.add_argument("--root", default=".", help="Project root; defaults to current directory.")
    parser.add_argument("--start-utc", default="", help="Operator run start UTC timestamp.")
    parser.add_argument("--since-utc", default="", help="Alias for --start-utc.")
    parser.add_argument("--stop-utc", default="", help="Operator run stop UTC timestamp; defaults to now.")
    parser.add_argument("--baseline-open-orders-hash", default="")
    parser.add_argument("--baseline-positions-hash", default="")
    parser.add_argument("--json-out", default="", help="Output JSON path under reports/live/.")
    parser.add_argument("--markdown-out", default="", help="Output Markdown path under reports/live/.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown to stdout.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    start_raw = args.start_utc or args.since_utc
    if not start_raw:
        raise SystemExit("--start-utc or --since-utc is required")
    start = _parse_required_ts(start_raw, "--start-utc")
    stop = _parse_required_ts(args.stop_utc, "--stop-utc") if args.stop_utc else _now()
    report = build_post_run_evidence_pack(
        root=Path(args.root),
        start_utc=start,
        stop_utc=stop,
        baseline_open_orders_hash=args.baseline_open_orders_hash or None,
        baseline_positions_hash=args.baseline_positions_hash or None,
    )
    if args.json_out:
        _atomic_write(Path(args.json_out), (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8"))
    if args.markdown_out:
        _atomic_write(Path(args.markdown_out), (_markdown(report) + "\n").encode("utf-8"))
    if args.markdown and not args.json:
        print(_markdown(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
