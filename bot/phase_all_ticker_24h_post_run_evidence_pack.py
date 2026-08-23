from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from bot.phase_all_ticker_24h_monitor import build_all_ticker_24h_monitor_report
from bot.phase_product_rule_fixture_evidence import DEFAULT_TICKERS


PHASE_ALL_TICKER_24H_POST_RUN_EVIDENCE_PACK = "all_ticker_24h_post_run_evidence_pack_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_all_ticker_24h_post_run_evidence_pack(
    *, root: str | Path = ".", generated_at: Optional[str] = None, start_utc: str = "", stop_utc: str = ""
) -> Dict[str, Any]:
    monitor = build_all_ticker_24h_monitor_report(root=root, generated_at=generated_at)
    missing_window = not bool(start_utc and stop_utc)
    return {
        "phase": PHASE_ALL_TICKER_24H_POST_RUN_EVIDENCE_PACK,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "post_run_scaffold_only": True,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "service_start_attempted": False,
            "state_write_performed": False,
        },
        "classification": "WATCH",
        "window": {"start_utc": start_utc, "stop_utc": stop_utc, "operator_must_supply_real_window": missing_window},
        "configured_tickers": list(DEFAULT_TICKERS),
        "per_ticker_evidence": monitor.get("per_ticker_monitor", []),
        "per_ticker_evidence_labels": monitor.get("per_ticker_monitor", []),
        "warnings": ["missing_live_window_warning"] if missing_window else [],
        "missing_live_window_warning": missing_window,
        "governance_flags": {
            "all_ticker_post_run_evidence_scaffold_ready": True,
            "live_start_authorized": False,
            "codex_must_not_start_live_test": True,
        },
    }


def render_all_ticker_24h_post_run_evidence_pack_markdown(report: Dict[str, Any]) -> str:
    lines = ["# All-Ticker 24h Post-Run Evidence Pack Scaffold", "", f"- classification: `{report.get('classification')}`"]
    lines.append(f"- missing_live_window_warning: `{report.get('missing_live_window_warning')}`")
    for row in report.get("per_ticker_evidence") or []:
        lines.append(f"- {row.get('ticker')}: open_orders=`{row.get('open_order_count')}`")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_ALL_TICKER_24H_POST_RUN_EVIDENCE_PACK",
    "build_all_ticker_24h_post_run_evidence_pack",
    "render_all_ticker_24h_post_run_evidence_pack_markdown",
]
