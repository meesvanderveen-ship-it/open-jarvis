#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

OPEN_ORDER_STATUSES = {"planned", "pending", "submitted", "partially_filled", "cancel_pending", "replace_pending"}
BTC_TICKER = "BTC-USDC"
STOP_NOW = "STOP_NOW"
WATCH = "WATCH"
OK = "OK"
DEFAULT_BASELINE_OPEN_HASH = "919115b9fbcc20e137a1cfb18e87a4858482ab5c06c3fdb3e5c0e61079066b60"
DEFAULT_BASELINE_POSITIONS_HASH = "d288bc7ca3a9b11fc78e29aa4407036c1e9f66b6b4597b4e0293d4bf615965c2"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _read_text(path: Path, max_chars: int = 2_000_000) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
    except OSError:
        return ""


def _load_json(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        return json.loads(text) if text else None
    except Exception as exc:
        return {"_error": f"json_load_failed:{type(exc).__name__}:{exc}"}


def _iter_jsonl(path: Path, limit_tail: int = 2000, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    text = _read_text(path, max_chars=5_000_000)
    if not text:
        return []
    rows: List[Dict[str, Any]] = []
    for line in text.splitlines()[-limit_tail:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            obj = {"_parse_error": True, "raw_prefix": line[:240]}
        if not isinstance(obj, dict):
            continue
        ts = _parse_ts(obj.get("generated_at") or obj.get("timestamp") or obj.get("created_at") or obj.get("updated_at"))
        if since and ts and ts < since:
            continue
        rows.append(obj)
    return rows


def _sha256(path: Path) -> Optional[str]:
    try:
        if not path.exists() or not path.is_file():
            return None
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _load_orders(path: Path) -> List[Dict[str, Any]]:
    data = _load_json(path)
    if not isinstance(data, dict):
        return []
    orders = data.get("orders", {})
    if isinstance(orders, list):
        out = [dict(v) for v in orders if isinstance(v, dict)]
    elif isinstance(orders, dict):
        out = [dict(v) for v in orders.values() if isinstance(v, dict)]
    else:
        out = []
    out.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    return out


def _order_notional(order: Dict[str, Any]) -> Decimal:
    candidates = [
        order.get("size_quote"),
        order.get("remaining_quote"),
        order.get("filled_quote"),
        order.get("quote_size"),
        order.get("notional_usd"),
        order.get("notional"),
    ]
    for value in candidates:
        dec = _to_decimal(value)
        if dec > 0:
            return dec
    base = _to_decimal(order.get("size_base") or order.get("filled_size") or order.get("remaining_size"))
    price = _to_decimal(order.get("limit_price") or order.get("avg_fill_price") or order.get("price"))
    return base * price if base > 0 and price > 0 else Decimal("0")


def summarize_orders(orders: Sequence[Dict[str, Any]], since: Optional[datetime] = None) -> Dict[str, Any]:
    by_status: Counter[str] = Counter()
    open_orders: List[Dict[str, Any]] = []
    d3_open: List[Dict[str, Any]] = []
    executed_non_btc: List[Dict[str, Any]] = []
    oversized: List[Dict[str, Any]] = []
    unexpected_sells: List[Dict[str, Any]] = []

    for order in orders:
        status = str(order.get("status") or "unknown").lower()
        side = str(order.get("side") or "").upper()
        ticker = str(order.get("ticker") or "").upper()
        cid = str(order.get("client_order_id") or "")
        ts = _parse_ts(order.get("updated_at") or order.get("created_at"))
        is_recent = not since or not ts or ts >= since
        by_status[status] += 1
        notional = _order_notional(order)
        if status in OPEN_ORDER_STATUSES:
            open_orders.append(order)
            if cid.startswith("d3exit-") or cid.startswith("phased3-") or "D3" in str(order.get("phase") or "").upper():
                d3_open.append(order)
        if is_recent and status in {"submitted", "partially_filled", "filled"} and ticker and ticker != BTC_TICKER:
            executed_non_btc.append(order)
        if is_recent and notional > Decimal("10"):
            oversized.append(order)
        if side == "SELL" and status in OPEN_ORDER_STATUSES:
            unexpected_sells.append(order)

    return {
        "total_orders": len(orders),
        "by_status": dict(by_status),
        "open_orders": len(open_orders),
        "open_d3_exits": len(d3_open),
        "open_order_samples": [_order_sample(o) for o in open_orders[:10]],
        "open_d3_exit_samples": [_order_sample(o) for o in d3_open[:10]],
        "executed_non_btc_samples": [_order_sample(o) for o in executed_non_btc[:10]],
        "oversized_notional_samples": [_order_sample(o) for o in oversized[:10]],
        "unexpected_sell_samples": [_order_sample(o) for o in unexpected_sells[:10]],
    }


def _order_sample(order: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "client_order_id": order.get("client_order_id"),
        "ticker": order.get("ticker"),
        "side": order.get("side"),
        "status": order.get("status"),
        "notional": str(_order_notional(order)),
        "updated_at": order.get("updated_at") or order.get("created_at"),
    }


def _detect_active_processes() -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    proc = Path("/proc")
    if not proc.exists():
        return matches
    current_pid = os.getpid()
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == current_pid:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue
        parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\0") if p]
        cmdline = " ".join(parts)
        if "run_trader_loop.py" in cmdline and "--startup-diagnostic" not in cmdline:
            matches.append({"pid": pid, "cmdline": cmdline[:500]})
    return sorted(matches, key=lambda x: x["pid"])


def _extract_tickers_from_loop_log(text: str, since: Optional[datetime]) -> Dict[str, Any]:
    evidence: List[Dict[str, Any]] = []
    startup_rx = re.compile(r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*Execution mode=(?P<mode>\w+)\s+\|\s+tickers=(?P<tickers>[A-Z0-9\-,]+)")
    for line in text.splitlines():
        m = startup_rx.search(line)
        if not m:
            continue
        ts = _parse_ts(m.group("ts").replace(" ", "T") + "+00:00")
        if since and ts and ts < since:
            continue
        tickers = [t.strip() for t in m.group("tickers").split(",") if t.strip()]
        evidence.append({"timestamp": _iso(ts) if ts else None, "mode": m.group("mode"), "tickers": tickers, "raw": line[-300:]})
    last = evidence[-1] if evidence else None
    suspicious = [row for row in evidence if row.get("tickers") != [BTC_TICKER]]
    return {"last_startup": last, "recent_startups": evidence[-5:], "suspicious_startups": suspicious[-5:]}


def _scan_loop_text(text: str, since: Optional[datetime]) -> Dict[str, Any]:
    lines = text.splitlines()
    relevant: List[str] = []
    if since:
        for line in lines:
            m = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
            if m:
                ts = _parse_ts(m.group(1).replace(" ", "T") + "+00:00")
                if ts and ts < since:
                    continue
            relevant.append(line)
    else:
        relevant = lines
    tail = relevant[-800:]
    tracebacks = [line[-300:] for line in tail if "Traceback" in line or "Traceback (most recent call last)" in line]
    errors = [line[-300:] for line in tail if re.search(r"\b(ERROR|CRITICAL)\b", line)]
    lifecycle_apply = [line[-300:] for line in tail if re.search(r"apply_local|applied_actions|lifecycle apply", line, re.IGNORECASE)]
    mutation_signals = [
        line[-300:]
        for line in tail
        if re.search(r"learning[_ -]?to[_ -]?execution|parameter mutation|parameter_change|ranking approval", line, re.IGNORECASE)
    ]
    return {
        "traceback_count": len(tracebacks),
        "error_count": len(errors),
        "traceback_samples": tracebacks[-5:],
        "error_samples": errors[-5:],
        "lifecycle_apply_signal_count": len(lifecycle_apply),
        "lifecycle_apply_signal_samples": lifecycle_apply[-5:],
        "learning_or_parameter_signal_count": len(mutation_signals),
        "learning_or_parameter_signal_samples": mutation_signals[-5:],
    }


def _recent_file_count(root: Path, names: Sequence[str], since: Optional[datetime]) -> Dict[str, Any]:
    details: Dict[str, Any] = {}
    total = 0
    for name in names:
        path = root / "logs" / name
        rows = _iter_jsonl(path, since=since)
        details[name] = {"exists": path.exists(), "recent_count": len(rows), "last": rows[-1] if rows else None}
        total += len(rows)
    return {"total": total, "details": details}


def _replication_status(root: Path, since: Optional[datetime]) -> Dict[str, Any]:
    publish_rows = _iter_jsonl(root / "logs/replication_publish.jsonl", since=since)
    outbox_rows = _iter_jsonl(root / "logs/replication_outbox.jsonl", since=since)
    all_rows = [*publish_rows, *outbox_rows]
    enabled = []
    disabled = []
    for row in all_rows[-100:]:
        text = json.dumps(row, sort_keys=True).lower()
        if "replication_disabled" in text or "skipped" in text:
            disabled.append(row)
        elif "enabled" in text or "posted" in text or "published" in text:
            enabled.append(row)
    return {
        "recent_rows": len(all_rows),
        "recent_disabled_evidence": len(disabled),
        "recent_enabled_or_publish_evidence": len(enabled),
        "last": all_rows[-1] if all_rows else None,
    }


def _env_flag_snapshot(root: Path) -> Dict[str, Any]:
    text = _read_text(root / ".env", max_chars=1_000_000)
    flags: Dict[str, Optional[str]] = {}
    for key in (
        "REPLICATION_ENABLED",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT",
        "ENABLE_LIVE_EXIT_ORDERS",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT",
        "AUTONOMOUS_ALLOW_EXITS",
        "LEARNING_TO_EXECUTION_ALLOWED",
        "PARAMETER_CHANGE_ALLOWED",
    ):
        match = re.findall(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$", text, flags=re.MULTILINE)
        flags[key] = match[-1].strip().strip("\"'") if match else None
    return flags


def _last(rows: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return rows[-1] if rows else None


def _classify(report: Dict[str, Any], baseline_open: Optional[str], baseline_positions: Optional[str]) -> Tuple[str, List[str]]:
    stop: List[str] = []
    watch: List[str] = []
    orders = report["orders"]
    logs = report["logs"]
    cycle = report["cycle_summary"].get("last") or {}
    heartbeat = report["heartbeat_summary"].get("last") or {}
    hashes = report["state_hashes"]
    env = report["env_flags"]
    replication = report["replication"]

    if report["process"]["active_process_count"] == 0:
        watch.append("run_process_not_active")
    if logs["ticker_scope"].get("suspicious_startups"):
        stop.append("non_btc_runtime_scope_seen")
    if int(cycle.get("total") or 0) > 1:
        stop.append("cycle_total_not_btc_only")
    if int(cycle.get("executed") or 0) > 0 and int(cycle.get("total") or 0) > 1:
        stop.append("executed_cycle_in_multi_ticker_scope")
    if orders["open_orders"] > 1:
        stop.append("more_than_one_open_order")
    if orders["open_d3_exits"] > 0:
        stop.append("unexpected_open_d3_exit")
    if orders["executed_non_btc_samples"]:
        stop.append("executed_or_submitted_non_btc_order")
    if orders["oversized_notional_samples"]:
        stop.append("order_notional_above_10_usdc")
    if orders["unexpected_sell_samples"]:
        stop.append("unexpected_sell_or_exit_order")
    if logs["loop_health"]["traceback_count"] > 0:
        stop.append("traceback_seen")
    if logs["loop_health"]["error_count"] >= 3:
        stop.append("runtime_error_burst")
    elif logs["loop_health"]["error_count"] > 0:
        watch.append("runtime_error_seen")
    if logs["loop_health"]["lifecycle_apply_signal_count"] > 0:
        stop.append("lifecycle_apply_signal_seen")
    if logs["loop_health"]["learning_or_parameter_signal_count"] > 0:
        stop.append("learning_or_parameter_mutation_signal_seen")
    if report["llm_corrupt"]["total"] >= 3:
        stop.append("llm_corrupt_burst")
    elif report["llm_corrupt"]["total"] > 0:
        watch.append("llm_corrupt_seen")
    if report["provider_errors"]["total"] >= 3:
        stop.append("provider_error_burst")
    elif report["provider_errors"]["total"] > 0:
        watch.append("provider_error_seen")
    if int(cycle.get("errors") or 0) > 0 or int(heartbeat.get("errors") or 0) > 0:
        watch.append("cycle_or_heartbeat_errors_seen")
    if str(env.get("REPLICATION_ENABLED") or "").lower() == "true" or replication["recent_enabled_or_publish_evidence"] > 0:
        stop.append("replication_unexpectedly_enabled")
    if str(env.get("ENABLE_LIVE_EXIT_ORDERS") or "").lower() == "true" or str(env.get("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT") or "").lower() == "true":
        stop.append("live_exit_flag_enabled")
    if str(env.get("LEARNING_TO_EXECUTION_ALLOWED") or "").lower() == "true" or str(env.get("PARAMETER_CHANGE_ALLOWED") or "").lower() == "true":
        stop.append("learning_or_parameter_flag_enabled")
    if baseline_open and hashes.get("state/open_orders.json") != baseline_open:
        stop.append("state_hash_drift_open_orders")
    if baseline_positions and hashes.get("state/positions.json") != baseline_positions:
        stop.append("state_hash_drift_positions")

    reasons = sorted(set(stop if stop else watch))
    return (STOP_NOW if stop else WATCH if watch else OK), reasons


def build_monitor_report(
    *,
    root: Path,
    since: Optional[datetime] = None,
    baseline_open_orders_hash: Optional[str] = None,
    baseline_positions_hash: Optional[str] = None,
    detect_processes: bool = True,
) -> Dict[str, Any]:
    root = root.resolve()
    orders = _load_orders(root / "state/open_orders.json")
    order_summary = summarize_orders(orders, since=since)
    cycle_rows = _iter_jsonl(root / "logs/cycle_summary.jsonl", since=since)
    heartbeat_rows = _iter_jsonl(root / "logs/heartbeat_summary.jsonl", since=since)
    lifecycle_rows = _iter_jsonl(root / "logs/phase_c43_lifecycle_service.jsonl", since=since)
    loop_text = _read_text(root / "logs/loop.log", max_chars=4_000_000)
    active = _detect_active_processes() if detect_processes else []
    hashes = {
        "state/open_orders.json": _sha256(root / "state/open_orders.json"),
        "state/positions.json": _sha256(root / "state/positions.json"),
    }
    report: Dict[str, Any] = {
        "tool": "show_btc_usdc_24h_live_monitor",
        "phase": "btc_usdc_24h_live_monitor_v1",
        "generated_at": _iso(_now()),
        "read_only": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "target_scope": {"ticker": BTC_TICKER, "max_notional_usdc": "10", "max_open_orders": 1, "live_exits_expected": False},
        "window": {"since": _iso(since) if since else None},
        "process": {"active_process_count": len(active), "active_processes": active[:5]},
        "cycle_summary": {"recent_rows": len(cycle_rows), "last": _last(cycle_rows)},
        "heartbeat_summary": {"recent_rows": len(heartbeat_rows), "last": _last(heartbeat_rows)},
        "orders": order_summary,
        "lifecycle_hook": {"recent_rows": len(lifecycle_rows), "last": _last(lifecycle_rows)},
        "logs": {
            "ticker_scope": _extract_tickers_from_loop_log(loop_text, since),
            "loop_health": _scan_loop_text(loop_text, since),
        },
        "llm_corrupt": _recent_file_count(root, ("llm_corrupt.jsonl", "llm_corrupt_outputs.jsonl"), since),
        "provider_errors": _recent_file_count(root, ("provider_errors.jsonl", "llm_provider_errors.jsonl"), since),
        "replication": _replication_status(root, since),
        "env_flags": _env_flag_snapshot(root),
        "state_hashes": hashes,
        "baseline_hashes": {
            "state/open_orders.json": baseline_open_orders_hash,
            "state/positions.json": baseline_positions_hash,
        },
    }
    classification, reasons = _classify(report, baseline_open_orders_hash, baseline_positions_hash)
    report["classification"] = classification
    report["stop_rule_reasons"] = reasons
    report["operator_action"] = {
        OK: "continue_monitoring",
        WATCH: "review_reasons_before_continuing",
        STOP_NOW: "stop_operator_run_now_and_do_not_apply_repair_without_separate_ack",
    }[classification]
    return report


def _parse_since(value: str, since_hours: float) -> datetime:
    if value:
        parsed = _parse_ts(value)
        if not parsed:
            raise SystemExit(f"Invalid --since-utc value: {value}")
        return parsed
    return _now() - timedelta(hours=since_hours)


def _markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# BTC-USDC 24h Live Monitor",
        "",
        f"- classification: `{report['classification']}`",
        f"- reasons: `{', '.join(report['stop_rule_reasons']) or 'none'}`",
        f"- active_process_count: `{report['process']['active_process_count']}`",
        f"- last_cycle: `{json.dumps(report['cycle_summary'].get('last'), sort_keys=True)}`",
        f"- last_heartbeat: `{json.dumps(report['heartbeat_summary'].get('last'), sort_keys=True)}`",
        f"- open_orders: `{report['orders']['open_orders']}`",
        f"- open_d3_exits: `{report['orders']['open_d3_exits']}`",
        f"- recent_loop_errors: `{report['logs']['loop_health']['error_count']}`",
        f"- recent_tracebacks: `{report['logs']['loop_health']['traceback_count']}`",
        f"- recent_llm_corrupt: `{report['llm_corrupt']['total']}`",
        f"- recent_provider_errors: `{report['provider_errors']['total']}`",
        f"- lifecycle_hook_status: `{(report['lifecycle_hook'].get('last') or {}).get('status')}`",
        f"- replication_enabled_evidence: `{report['replication']['recent_enabled_or_publish_evidence']}`",
        f"- current_open_orders_hash: `{report['state_hashes'].get('state/open_orders.json')}`",
        f"- current_positions_hash: `{report['state_hashes'].get('state/positions.json')}`",
        f"- operator_action: `{report['operator_action']}`",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only local BTC-USDC tiny 24h monitor. No Coinbase calls and no state writes.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--markdown", action="store_true", help="Print compact Markdown output.")
    parser.add_argument("--root", default=".", help="Project root; defaults to current directory.")
    parser.add_argument("--since-hours", type=float, default=26.0, help="Recent log window when --since-utc is omitted.")
    parser.add_argument("--since-utc", default="", help="Only consider log entries at/after this UTC timestamp.")
    parser.add_argument("--baseline-open-orders-hash", default="", help="Expected sha256 for state/open_orders.json.")
    parser.add_argument("--baseline-positions-hash", default="", help="Expected sha256 for state/positions.json.")
    parser.add_argument("--use-default-baseline-hashes", action="store_true", help="Use the last known BTC tiny pre-run hashes from project context.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    baseline_open = args.baseline_open_orders_hash or None
    baseline_positions = args.baseline_positions_hash or None
    if args.use_default_baseline_hashes:
        baseline_open = baseline_open or DEFAULT_BASELINE_OPEN_HASH
        baseline_positions = baseline_positions or DEFAULT_BASELINE_POSITIONS_HASH
    report = build_monitor_report(
        root=Path(args.root),
        since=_parse_since(args.since_utc, args.since_hours),
        baseline_open_orders_hash=baseline_open,
        baseline_positions_hash=baseline_positions,
    )
    if args.markdown and not args.json:
        print(_markdown(report), end="")
    else:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
