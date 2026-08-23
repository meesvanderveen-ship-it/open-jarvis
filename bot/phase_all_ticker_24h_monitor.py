from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.phase_product_rule_fixture_evidence import DEFAULT_TICKERS


PHASE_ALL_TICKER_24H_MONITOR = "all_ticker_24h_monitor_v1"
OPEN_STATUSES = {"planned", "pending", "submitted", "open", "partially_filled", "cancel_pending", "replace_pending"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _orders(path: Path) -> List[Dict[str, Any]]:
    payload = _load_json(path)
    raw = payload.get("orders")
    if isinstance(raw, dict):
        return [dict(v) for v in raw.values() if isinstance(v, dict)]
    if isinstance(raw, list):
        return [dict(v) for v in raw if isinstance(v, dict)]
    return []


def _is_open(order: Dict[str, Any]) -> bool:
    return str(order.get("status") or "").lower() in OPEN_STATUSES


def build_all_ticker_24h_monitor_report(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    orders = _orders(project_root / "state/open_orders.json")
    by_ticker: Dict[str, Dict[str, Any]] = {}
    total_open = 0
    for ticker in DEFAULT_TICKERS:
        rows = [row for row in orders if str(row.get("ticker") or "").upper() == ticker]
        statuses = Counter(str(row.get("status") or "unknown").lower() for row in rows)
        open_count = sum(1 for row in rows if _is_open(row))
        total_open += open_count
        by_ticker[ticker] = {
            "ticker": ticker,
            "order_count": len(rows),
            "open_order_count": open_count,
            "status_counts": dict(statuses),
            "fill_no_fill_cancel_reject_labels": {
                "fill": statuses.get("filled", 0),
                "no_fill": statuses.get("submitted", 0) + statuses.get("open", 0),
                "cancel": statuses.get("cancelled", 0),
                "reject": statuses.get("rejected", 0) + statuses.get("submit_rejected", 0),
            },
            "lifecycle_evidence_status": "local_order_state_only",
            "warnings": [] if rows else ["no local order rows for ticker"],
            "blockers": ["open_orders_present"] if open_count else [],
        }
    classification = "STOP_NOW" if total_open else "OK"
    return {
        "phase": PHASE_ALL_TICKER_24H_MONITOR,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "monitor_scaffold_only": True,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "service_start_attempted": False,
            "state_write_performed": False,
        },
        "classification": classification,
        "configured_tickers": list(DEFAULT_TICKERS),
        "per_ticker_monitor": list(by_ticker.values()),
        "open_orders": total_open,
        "governance_flags": {
            "all_ticker_monitor_scaffold_ready": True,
            "all_ticker_live_authorized": False,
            "live_start_authorized": False,
            "codex_must_not_start_live_test": True,
        },
    }


def render_all_ticker_24h_monitor_markdown(report: Dict[str, Any]) -> str:
    lines = ["# All-Ticker 24h Monitor Scaffold", "", f"- classification: `{report.get('classification')}`", ""]
    for row in report.get("per_ticker_monitor") or []:
        lines.append(f"- {row.get('ticker')}: open_orders=`{row.get('open_order_count')}`")
    return "\n".join(lines).rstrip() + "\n"


__all__ = ["PHASE_ALL_TICKER_24H_MONITOR", "build_all_ticker_24h_monitor_report", "render_all_ticker_24h_monitor_markdown"]
