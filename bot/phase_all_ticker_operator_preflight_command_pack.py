from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from bot.phase_product_rule_fixture_evidence import DEFAULT_TICKERS


PHASE_ALL_TICKER_OPERATOR_PREFLIGHT_COMMAND_PACK = "all_ticker_operator_preflight_command_pack_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _cmd(purpose: str, command: str) -> Dict[str, Any]:
    return {
        "purpose": f"OPERATOR ONLY — CODEX MUST NOT RUN: {purpose}",
        "command": command,
        "operator_only": True,
        "codex_must_not_run": True,
        "executed_by_codex": False,
    }


def build_all_ticker_operator_preflight_command_pack(
    *, root: str | Path = ".", generated_at: Optional[str] = None
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    tickers = ",".join(DEFAULT_TICKERS)
    tools = {
        "selected_harness": project_root / "tools/run_safe_regression_harness.py",
        "open_orders": project_root / "tools/show_open_orders.py",
        "function_audit": project_root / "tools/show_function_preservation_audit.py",
        "monitor": project_root / "tools/show_all_ticker_24h_live_monitor.py",
        "post_run": project_root / "tools/build_all_ticker_24h_post_run_evidence_pack.py",
        "guard": project_root / "tools/build_all_ticker_live_scope_guard.py",
        "live_readonly_preflight": project_root / "tools/show_all_ticker_live_readonly_preflight.py",
        "shadow_parameter_approximation": project_root / "tools/build_shadow_parameter_approximation_pack.py",
    }
    commands = [
        _cmd("refresh selected-test harness", "python3 tools/run_safe_regression_harness.py --include-selected-tests --json-out reports/d6/safe-regression-harness-$(date -u +%Y%m%d).json --markdown-out reports/d6/safe-regression-harness-$(date -u +%Y%m%d).md"),
        _cmd("check local open orders", "python3 tools/show_open_orders.py --open-only --json --limit 50"),
        _cmd("run function preservation audit", "python3 tools/show_function_preservation_audit.py --fail-on-review"),
        _cmd("build all-ticker live scope guard", "python3 tools/build_all_ticker_live_scope_guard.py --json-out reports/d6/all-ticker-live-scope-guard-$(date -u +%Y%m%d).json --markdown-out reports/d6/all-ticker-live-scope-guard-$(date -u +%Y%m%d).md"),
        _cmd("build local all-ticker live-readonly preflight report without Coinbase by default", "python3 tools/show_all_ticker_live_readonly_preflight.py --json-out reports/d6/all-ticker-live-readonly-preflight-$(date -u +%Y%m%d).json --markdown-out reports/d6/all-ticker-live-readonly-preflight-$(date -u +%Y%m%d).md"),
        _cmd("all-ticker product-rule/balance/min-notional readonly preflight template", f"<FUTURE_ACK_REQUIRED> all-ticker readonly Coinbase preflight for {tickers}"),
        _cmd("build shadow parameter approximation pack", "python3 tools/build_shadow_parameter_approximation_pack.py --preflight-report reports/d6/all-ticker-live-readonly-preflight-$(date -u +%Y%m%d).json --json-out reports/d6/shadow-parameter-approximation-pack-$(date -u +%Y%m%d).json --markdown-out reports/d6/shadow-parameter-approximation-pack-$(date -u +%Y%m%d).md"),
        _cmd("all-ticker config/cap preview", "python3 tools/build_all_ticker_24h_workflow_readiness_pack.py --json-out reports/d6/all-ticker-24h-workflow-readiness-pack-$(date -u +%Y%m%d).json --markdown-out reports/d6/all-ticker-24h-workflow-readiness-pack-$(date -u +%Y%m%d).md"),
        _cmd("all-ticker monitor", "python3 tools/show_all_ticker_24h_live_monitor.py --json --since-utc <OPERATOR_START_UTC>"),
        _cmd("all-ticker post-run evidence pack", "python3 tools/build_all_ticker_24h_post_run_evidence_pack.py --start-utc <OPERATOR_START_UTC> --stop-utc <OPERATOR_STOP_UTC> --json-out reports/live/all-ticker-24h-post-run-evidence-<DATE>.json --markdown-out reports/live/all-ticker-24h-post-run-evidence-<DATE>.md"),
        _cmd("stop/disable review", "pgrep -af 'run_trader_loop.py'  # operator identifies and stops only intended manual process"),
    ]
    missing = [key for key, path in tools.items() if not path.exists()]
    report = {
        "phase": PHASE_ALL_TICKER_OPERATOR_PREFLIGHT_COMMAND_PACK,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "command_templates_only": True,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "order_action_attempted": False,
            "state_write_performed": False,
            "parameter_mutation_performed": False,
        },
        "classification": "OK" if not missing else "WATCH",
        "configured_tickers": list(DEFAULT_TICKERS),
        "commands": commands,
        "missing_command_templates": missing,
        "governance_flags": {
            "all_ticker_operator_preflight_command_pack_ready": not missing,
            "all_commands_operator_only": all(row["operator_only"] and row["codex_must_not_run"] for row in commands),
            "all_ticker_live_authorized": False,
            "live_start_authorized": False,
            "codex_must_not_start_live_test": True,
        },
    }
    return _json_safe(report)


def render_all_ticker_operator_preflight_command_pack_markdown(report: Dict[str, Any]) -> str:
    lines = ["# All-Ticker Operator Preflight Command Pack", ""]
    lines.append(f"- classification: `{report.get('classification')}`")
    lines.append("")
    lines.append("## OPERATOR ONLY - CODEX MUST NOT RUN")
    lines.append("")
    for row in report.get("commands") or []:
        lines.append(f"- {row.get('purpose')}")
        lines.append(f"  - `{row.get('command')}`")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_ALL_TICKER_OPERATOR_PREFLIGHT_COMMAND_PACK",
    "build_all_ticker_operator_preflight_command_pack",
    "render_all_ticker_operator_preflight_command_pack_markdown",
]
