from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

D3_PHASE = "D3_controlled_live_reduce_only_exits"
OPEN_STATUSES = {"planned", "pending", "submitted", "open", "partially_filled", "cancel_pending", "replace_pending"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_jsonl(path: Path, *, since: Optional[datetime] = None, limit: int = 5000) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[-max(1, limit):]:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        ts = parse_ts(row.get("generated_at") or row.get("timestamp") or row.get("created_at"))
        if since is not None and ts is not None and ts < since:
            continue
        rows.append(row)
    return rows


def orders_from_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("orders"), dict):
        return [dict(v) for v in payload["orders"].values() if isinstance(v, dict)]
    if isinstance(payload, list):
        return [dict(v) for v in payload if isinstance(v, dict)]
    return []


def open_orders_summary(root: Path) -> Dict[str, Any]:
    orders = orders_from_payload(load_json(root / "state/open_orders.json"))
    open_orders = [o for o in orders if str(o.get("status") or "").lower() in OPEN_STATUSES]
    open_d3 = [
        o for o in open_orders
        if str(o.get("phase") or "") == D3_PHASE and str(o.get("side") or "").upper() == "SELL"
    ]
    linked_counts = Counter(str(o.get("linked_position_id") or "") for o in open_d3)
    return {
        "open_orders": len(open_orders),
        "open_d3_exit": len(open_d3),
        "duplicate_open_d3_exit_positions": sorted(k for k, v in linked_counts.items() if v > 1),
        "missing_exchange_order_id_client_order_ids": [
            str(o.get("client_order_id") or "") for o in open_d3
            if not str(o.get("exchange_order_id") or o.get("order_id") or "").strip()
        ],
        "open_d3_exit_samples": [
            {
                "client_order_id": str(o.get("client_order_id") or ""),
                "exchange_order_id": str(o.get("exchange_order_id") or o.get("order_id") or ""),
                "status": str(o.get("status") or ""),
                "limit_price": str(o.get("limit_price") or ""),
                "remaining_size": str(o.get("remaining_size") or o.get("size_base") or ""),
                "linked_position_id": str(o.get("linked_position_id") or ""),
            }
            for o in open_d3[:10]
        ],
    }


def detect_service_status(service_name: str = "coinbase-bot.service") -> Dict[str, Any]:
    out = {
        "service_name": service_name,
        "status": "unknown",
        "active_pid": "",
        "detectable": False,
        "active_state": "unknown",
        "sub_state": "unknown",
        "active_enter_timestamp": "",
        "uptime_seconds": None,
    }
    try:
        res = subprocess.run(
            [
                "systemctl",
                "show",
                service_name,
                "--property=ActiveState,SubState,MainPID,ActiveEnterTimestamp",
                "--no-page",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3,
        )
    except Exception as exc:
        out["error"] = str(exc)
        return out
    if res.returncode != 0:
        out["error"] = res.stderr.strip()
        return out
    props = {}
    for line in res.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k] = v
    uptime_seconds = None
    active_enter = props.get("ActiveEnterTimestamp", "")
    try:
        if active_enter:
            dt = datetime.strptime(active_enter, "%a %Y-%m-%d %H:%M:%S %Z").replace(tzinfo=timezone.utc)
            uptime_seconds = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    except Exception:
        uptime_seconds = None
    out.update({
        "detectable": True,
        "active_state": props.get("ActiveState", "unknown"),
        "sub_state": props.get("SubState", "unknown"),
        "status": f"{props.get('ActiveState', 'unknown')}/{props.get('SubState', 'unknown')}",
        "active_pid": props.get("MainPID", ""),
        "active_enter_timestamp": active_enter,
        "uptime_seconds": uptime_seconds,
    })
    return out


def process_lock_status(root: Path) -> Dict[str, Any]:
    path = root / "state/run_trader_loop.lock"
    pid = ""
    try:
        pid = path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    proc_root = Path("/proc")
    proc_available = proc_root.exists() and proc_root.is_dir()
    alive = bool(pid.isdigit() and proc_available and Path(f"/proc/{pid}").exists())
    proc_status = "available" if proc_available else "proc_unavailable"
    return {
        "path": str(path),
        "exists": path.exists(),
        "pid": pid,
        "pid_alive": alive,
        "pid_liveness_source": proc_status,
        "stale": bool(pid and proc_available and not alive),
        "stale_evidence": "unknown" if pid and not proc_available else ("stale" if pid and not alive else "not_stale"),
        "conflict": bool(pid and alive),
    }


def latest_cycle_times(root: Path) -> Dict[str, Any]:
    cycles = load_jsonl(root / "logs/cycle_summary.jsonl", limit=200)
    heartbeats = load_jsonl(root / "logs/heartbeat_summary.jsonl", limit=200)
    return {
        "last_full_cycle_time": str((cycles[-1] if cycles else {}).get("generated_at") or ""),
        "last_heartbeat_time": str((heartbeats[-1] if heartbeats else {}).get("generated_at") or ""),
        "duplicate_cycle_detection": _duplicate_boundary_count(cycles, "full") + _duplicate_boundary_count(heartbeats, "heartbeat"),
    }


def latest_lifecycle_status(root: Path, *, since_hours: int = 24) -> Dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    lifecycle = load_jsonl(root / "logs/phase_c43_lifecycle_service.jsonl", since=since)
    errors = load_jsonl(root / "logs/phase_c43_lifecycle_service_errors.jsonl", since=since)
    latest = lifecycle[-1] if lifecycle else {}
    summary = latest.get("summary") if isinstance(latest.get("summary"), dict) else {}
    d3_reports = latest.get("d3_open_exit_lifecycle_reports")
    d3_reports = d3_reports if isinstance(d3_reports, list) else []
    d3_actions = summary.get("d3_proposed_actions")
    d3_actions = d3_actions if isinstance(d3_actions, list) else []
    last_d3 = d3_reports[-1] if d3_reports and isinstance(d3_reports[-1], dict) else {}
    last_action = d3_actions[-1] if d3_actions and isinstance(d3_actions[-1], dict) else {}
    return {
        "last_lifecycle_hook_time": str(latest.get("generated_at") or latest.get("timestamp") or ""),
        "last_d3_lifecycle_status": str(last_d3.get("status") or latest.get("status") or ""),
        "last_d3_coinbase_call_attempted": bool(
            last_d3.get("coinbase_call_attempted")
            or summary.get("d3_coinbase_call_attempted")
            or latest.get("coinbase_call_attempted")
        ),
        "last_d3_proposed_action": str(
            last_action.get("proposed_action")
            or last_d3.get("proposed_action")
            or summary.get("proposed_action")
            or ""
        ),
        "lifecycle_error_count": len(errors),
        "latest_lifecycle_error": errors[-1] if errors else {},
    }


def _duplicate_boundary_count(rows: Iterable[Dict[str, Any]], label: str) -> int:
    counts: Counter[str] = Counter()
    for row in rows:
        ts = parse_ts(row.get("generated_at"))
        if ts:
            counts[f"{label}:{ts.replace(minute=0, second=0, microsecond=0).isoformat()}"] += 1
    return sum(v - 1 for v in counts.values() if v > 1)


def summarize_logs(root: Path, *, since_hours: int = 24) -> Dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    cycles = load_jsonl(root / "logs/cycle_summary.jsonl", since=since)
    heartbeats = load_jsonl(root / "logs/heartbeat_summary.jsonl", since=since)
    lifecycle = load_jsonl(root / "logs/phase_c43_lifecycle_service.jsonl", since=since)
    events = load_jsonl(root / "logs/order_events.jsonl", since=since)
    errors = load_jsonl(root / "logs/errors.jsonl", since=since)
    provider_errors = load_jsonl(root / "logs/llm_provider_errors.jsonl", since=since)
    corrupt = load_jsonl(root / "logs/llm_corrupt.jsonl", since=since)
    llm_raw = load_jsonl(root / "logs/llm_raw.jsonl", since=since)
    decisions = load_jsonl(root / "logs/decision_outcomes.jsonl", since=since)
    runtime_text = _read_recent_text(root / "logs/loop.log", max_chars=600000)
    last_cycle_summary = _last_pipe_summary(runtime_text, "Cycle summary")
    last_gate_summary = _last_pipe_summary(runtime_text, "Gate summary")
    event_types = Counter(str(e.get("event_type") or "") for e in events)
    lifecycle_latest = lifecycle[-1] if lifecycle else {}
    duplicate_cycles = _duplicate_boundary_count(cycles, "full") + _duplicate_boundary_count(heartbeats, "heartbeat")
    atomic_write_errors = _error_count(errors, runtime_text, ["FileNotFoundError", ".tmp", "os.replace", "atomic"])
    lifecycle_exceptions = _error_count(errors, runtime_text, ["lifecycle service hook failed", "ticker mag niet leeg zijn"])
    state_write_errors = _error_count(errors, runtime_text, ["state write", "write_json", "positions.json", "open_orders.json", ".tmp"])
    per_ticker: Dict[str, Dict[str, int]] = {}
    for row in [*cycles, *decisions]:
        ticker = str(row.get("ticker") or row.get("product_id") or "").strip()
        decision = str(row.get("decision") or row.get("action") or row.get("recommendation") or "").strip() or "observed"
        if ticker:
            bucket = per_ticker.setdefault(ticker, {})
            bucket[decision] = bucket.get(decision, 0) + 1
    d3_keep_open = _text_count(lifecycle, "keep_open")
    d3_terminal = _text_count(lifecycle, "terminal")
    duplicate_oversell = _text_count([*cycles, *heartbeats, *lifecycle, *events], "oversell") + _text_count(
        [*cycles, *heartbeats, *lifecycle, *events], "duplicate sell"
    )
    false_positive_entries = _text_count([*cycles, *heartbeats, *events], "false_positive") + _text_count(
        [*cycles, *heartbeats, *events], "quick_stop"
    )
    missed_fill = _text_count([*cycles, *heartbeats, *events], "missed_fill")
    return {
        "since_hours": since_hours,
        "cycles": len(cycles),
        "heartbeat_cycles": len(heartbeats),
        "expected_full_cycles": max(1, int(since_hours / 4)),
        "expected_heartbeat_cycles": since_hours,
        "cycles_expected_vs_observed": {"expected": max(1, int(since_hours / 4)), "observed": len(cycles)},
        "heartbeat_expected_vs_observed": {"expected": since_hours, "observed": len(heartbeats)},
        "duplicate_cycle_evidence": duplicate_cycles,
        "tickers_reviewed": sum(int(r.get("total") or 0) for r in cycles),
        "per_ticker_decision_counts": per_ticker,
        "waits": sum(int(r.get("wait") or 0) for r in cycles),
        "no_trade_signals": _text_count([*cycles, *heartbeats], "no_trade"),
        "close_position_signals": sum(int(r.get("close_position") or 0) for r in cycles),
        "entry_attempts": event_types.get("phase_c43_live_entry_order_submitted", 0) + event_types.get("phase_c43_live_entry_order_submit_rejected", 0),
        "buy_intents": _text_count([*cycles, *heartbeats, *events], "buy") + event_types.get("phase_c43_live_entry_order_submit_rejected", 0),
        "buy_submits": event_types.get("phase_c43_live_entry_order_submitted", 0),
        "open_orders_created": event_types.get("phase_c43_live_entry_order_submitted", 0) + event_types.get("phase_d3_live_exit_order_submitted", 0),
        "orders_submitted": sum(v for k, v in event_types.items() if k.endswith("_submitted")),
        "fills": sum(v for k, v in event_types.items() if "filled" in k or "reconciled" in k),
        "cancels": sum(v for k, v in event_types.items() if "cancel" in k),
        "replaces": sum(v for k, v in event_types.items() if "replace" in k),
        "applies": sum(v for k, v in event_types.items() if "apply" in k or "applied" in k),
        "blocked_actions": sum(1 for e in events if "blocked" in json.dumps(e).lower() or "rejected" in str(e.get("event_type") or "")),
        "errors": len(errors),
        "errors_by_type": dict(Counter(str(e.get("error_type") or e.get("error") or "unknown")[:120] for e in errors)),
        "runtime_error_lines": _recent_matching_lines(runtime_text, ["ERROR", "Exception", "Traceback"], limit=20),
        "atomic_write_errors": atomic_write_errors,
        "state_write_errors": state_write_errors,
        "lifecycle_exceptions": lifecycle_exceptions,
        "llm_provider_errors": len(provider_errors),
        "llm_corrupt_outputs": len(corrupt),
        "llm_http_200_count": sum(1 for r in llm_raw if str(r.get("status_code") or r.get("http_status") or "") == "200"),
        "d3_lifecycle_last_status": str(lifecycle_latest.get("status") or ""),
        "d3_lifecycle_summary": lifecycle_latest.get("summary") or {},
        "d3_lifecycle_polls": _text_count(lifecycle, "coinbase_call_attempted") + _text_count(lifecycle, "d3_open_exit"),
        "d3_keep_open_counts": d3_keep_open,
        "d3_terminal_proposals": d3_terminal,
        "stop_breach_signals": _text_count([*cycles, *heartbeats, *lifecycle], "stop_breached_or_below_invalidation"),
        "stale_tp_signals": _text_count([*cycles, *heartbeats, *lifecycle], "stale"),
        "controlled_stop_exit_preview_signals": _text_count([*cycles, *heartbeats, *lifecycle], "controlled_stop"),
        "blocked_duplicate_or_oversell_signals": duplicate_oversell,
        "missed_fill_evidence": missed_fill,
        "false_positive_or_quick_stop_signals": false_positive_entries,
        "top_blockers": Counter(
            b for row in lifecycle for b in ((row.get("governance_report") or {}).get("blockers") or [])
        ).most_common(10),
        "event_type_counts": dict(event_types),
        "last_cycle_summary": last_cycle_summary,
        "last_gate_summary": last_gate_summary,
    }


def _text_count(rows: Iterable[Dict[str, Any]], needle: str) -> int:
    n = needle.lower()
    return sum(1 for row in rows if n in json.dumps(row, default=str).lower())


def _read_recent_text(path: Path, *, max_chars: int = 200000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[-max_chars:]


def _recent_matching_lines(text: str, needles: List[str], *, limit: int = 20) -> List[str]:
    lowered_needles = [n.lower() for n in needles]
    matches = []
    for line in text.splitlines():
        lower = line.lower()
        matched = False
        for needle in lowered_needles:
            if needle == "error":
                matched = " - error" in lower or "\terror" in lower or lower.startswith("error")
            else:
                matched = needle in lower
            if matched:
                break
        if matched:
            matches.append(line[-500:])
    return matches[-limit:]


def _last_pipe_summary(text: str, marker: str) -> Optional[Dict[str, int]]:
    found: Optional[Dict[str, int]] = None
    needle = f"{marker} |"
    for line in text.splitlines():
        if needle not in line:
            continue
        tail = line.split(needle, 1)[1]
        parsed: Dict[str, int] = {}
        for part in tail.split("|"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            try:
                parsed[key] = int(value)
            except ValueError:
                continue
        if parsed:
            found = parsed
    return found


def _error_count(errors: List[Dict[str, Any]], text: str, needles: List[str]) -> int:
    haystack = "\n".join([json.dumps(e, default=str) for e in errors] + [text]).lower()
    return sum(len(re.findall(re.escape(n.lower()), haystack)) for n in needles)
