from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


PHASE_ALL_TICKER_LIVE_SCOPE_GUARD = "all_ticker_live_scope_guard_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _env_value(text: str, key: str) -> Optional[str]:
    m = re.findall(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$", text, flags=re.MULTILINE)
    return m[-1].strip().strip("\"'") if m else None


def build_all_ticker_live_scope_guard(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    harness = _load_json(project_root / "reports/d6/safe-regression-harness-20260609.json")
    preflight = _load_json(project_root / "reports/d6/all-ticker-live-readonly-preflight-20260609.json")
    shadow = _load_json(project_root / "reports/d6/shadow-parameter-approximation-pack-20260609.json")
    flags = harness.get("readiness_flags") if isinstance(harness.get("readiness_flags"), dict) else {}
    selected = harness.get("selected_tests") if isinstance(harness.get("selected_tests"), dict) else {}
    open_summary = harness.get("open_order_summary") if isinstance(harness.get("open_order_summary"), dict) else {}
    env_text = ""
    try:
        env_text = (project_root / ".env").read_text(encoding="utf-8", errors="replace")
    except Exception:
        env_text = ""
    stop = []
    if selected.get("selected_tests_classification") != "OK":
        stop.append("selected_harness_not_ok")
    if int(open_summary.get("open_orders") or 0) != 0:
        stop.append("open_orders_nonzero")
    if str(_env_value(env_text, "REPLICATION_ENABLED") or "").lower() == "true":
        stop.append("replication_enabled")
    if str(_env_value(env_text, "PARAMETER_CHANGE_ALLOWED") or "").lower() == "true":
        stop.append("parameter_mutation_enabled")
    if str(_env_value(env_text, "LEARNING_TO_EXECUTION_ALLOWED") or "").lower() == "true":
        stop.append("learning_to_execution_enabled")
    if flags.get("all_ticker_live_allowed_now") is True:
        stop.append("all_ticker_live_flag_open")
    shadow_flags = shadow.get("governance_flags") if isinstance(shadow.get("governance_flags"), dict) else {}
    if shadow_flags.get("parameter_change_allowed") is True or shadow_flags.get("safe_to_mutate_parameters_now") is True:
        stop.append("shadow_parameter_pack_allows_mutation")
    preflight_gate = preflight.get("gate_decision") if isinstance(preflight.get("gate_decision"), dict) else {}
    classification = "STOP_NOW" if stop else "OK"
    return {
        "phase": PHASE_ALL_TICKER_LIVE_SCOPE_GUARD,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "guard_only": True,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "service_restart_attempted": False,
            "env_mutation_performed": False,
            "state_write_performed": False,
            "parameter_mutation_performed": False,
        },
        "classification": classification,
        "stop_reasons": stop,
        "guard": {
            "all_ticker_live_readonly_preflight_attempted": bool(
                preflight_gate.get("all_ticker_live_readonly_preflight_attempted", False)
            ),
            "all_ticker_live_readonly_preflight_passed": bool(
                preflight_gate.get("all_ticker_live_readonly_preflight_passed", False)
            ),
            "all_ticker_live_allowed_now": False,
            "live_start_authorized": False,
            "follower_ready_for_live": False,
            "replication_enabled": False,
            "parameter_change_allowed": False,
            "learning_to_execution_ready": False,
            "live_learning_allowed": False,
            "only_allowed_manual_route": "operator_fresh_preflight_then_operator_start",
            "codex_must_not_start_live_test": True,
        },
        "governance_flags": {
            "all_ticker_live_scope_guard_ready": classification == "OK",
            "all_ticker_live_readonly_preflight_passed": bool(
                preflight_gate.get("all_ticker_live_readonly_preflight_passed", False)
            ),
            "all_ticker_live_authorized": False,
            "live_start_authorized": False,
            "codex_must_not_start_live_test": True,
        },
    }


def render_all_ticker_live_scope_guard_markdown(report: Dict[str, Any]) -> str:
    return (
        "# All-Ticker Live Scope Guard\n\n"
        f"- classification: `{report.get('classification')}`\n"
        f"- stop_reasons: `{'; '.join(report.get('stop_reasons') or [])}`\n"
        "- all_ticker_live_allowed_now: `False`\n"
        "- live_start_authorized: `False`\n"
    )


__all__ = ["PHASE_ALL_TICKER_LIVE_SCOPE_GUARD", "build_all_ticker_live_scope_guard", "render_all_ticker_live_scope_guard_markdown"]
