from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


PHASE_OPERATOR_24H_PRERUN_BUILD_CHECKLIST = "operator_24h_prerun_build_checklist_v1"


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


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _check(name: str, passed: bool, evidence: Any, blocker: str = "") -> Dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence, "blocker": "" if passed else blocker}


def build_operator_24h_prerun_build_checklist(
    *, root: str | Path = ".", generated_at: Optional[str] = None
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    harness = _load_json(project_root / "reports/d6/safe-regression-harness-20260609.json")
    flags = harness.get("readiness_flags") if isinstance(harness.get("readiness_flags"), dict) else {}
    selected = harness.get("selected_tests") if isinstance(harness.get("selected_tests"), dict) else {}
    open_summary = harness.get("open_order_summary") if isinstance(harness.get("open_order_summary"), dict) else {}
    refs = harness.get("report_references") if isinstance(harness.get("report_references"), dict) else {}
    files = {
        "monitor_test": project_root / "tests/test_btc_usdc_24h_monitor.py",
        "monitor_tool": project_root / "tools/show_btc_usdc_24h_live_monitor.py",
        "post_run_pack_tool": project_root / "tools/build_btc_usdc_24h_post_run_evidence_pack.py",
        "decision_map": project_root / "reports/d6/roadmap-readiness-decision-map-20260609.json",
        "controlled_governance": project_root / "reports/d6/controlled-learning-governance-20260609.json",
        "shadow_learning": project_root / "reports/d6/d6-shadow-learning-report-20260609.json",
    }
    checks = [
        _check("selected-test harness OK", selected.get("selected_tests_classification") == "OK", selected.get("selected_tests_classification"), "selected tests not OK"),
        _check("open_orders=0 expected", int(open_summary.get("open_orders") or 0) == 0, open_summary.get("open_orders"), "open orders present"),
        _check("open_d3_exit=0 expected", int(open_summary.get("open_d3_exit") or 0) == 0, open_summary.get("open_d3_exit"), "open D3 exit present"),
        _check("BTC-USDC tiny scope exists", bool(flags.get("btc_usdc_tiny_scope_ready_for_operator_preflight", flags.get("master_ready_for_operator_preflight"))), flags.get("master_ready_for_operator_preflight"), "BTC tiny scope not ready for operator preflight"),
        _check("monitor test exists", files["monitor_test"].exists(), str(files["monitor_test"]), "BTC monitor test missing"),
        _check("monitor tool exists", files["monitor_tool"].exists(), str(files["monitor_tool"]), "BTC monitor tool missing"),
        _check("post-run evidence pack exists", files["post_run_pack_tool"].exists(), str(files["post_run_pack_tool"]), "post-run evidence pack tool missing"),
        _check("decision map exists", files["decision_map"].exists(), str(files["decision_map"]), "decision map missing"),
        _check("D6 governance exists", files["controlled_governance"].exists(), str(files["controlled_governance"]), "controlled governance missing"),
        _check("shadow learning report exists", files["shadow_learning"].exists(), str(files["shadow_learning"]), "shadow learning report missing"),
        _check("learning-to-execution disabled", flags.get("learning_to_execution_ready") is False, flags.get("learning_to_execution_ready"), "learning-to-execution enabled unexpectedly"),
        _check("parameter mutation disabled", flags.get("parameter_change_allowed") is False, flags.get("parameter_change_allowed"), "parameter mutation allowed unexpectedly"),
        _check("all-ticker live disabled", flags.get("all_ticker_live_allowed_now", False) is False, flags.get("all_ticker_live_allowed_now", False), "all-ticker live allowed unexpectedly"),
        _check("follower live disabled", flags.get("follower_ready_for_live") is False, flags.get("follower_ready_for_live"), "follower live ready unexpectedly"),
    ]
    failed = [row for row in checks if not row["passed"]]
    status = "build_complete_for_operator_live_start_review" if not failed else "build_incomplete"
    report = {
        "phase": PHASE_OPERATOR_24H_PRERUN_BUILD_CHECKLIST,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "local_files_only": True,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "state_write_performed": False,
            "parameter_mutation_performed": False,
            "live_run_started": False,
        },
        "classification": "OK" if not failed else "WATCH",
        "status": status,
        "checks": checks,
        "failed_checks": failed,
        "report_references": {key: value.get("available") for key, value in refs.items() if isinstance(value, dict)},
        "governance_flags": {
            "operator_24h_prerun_build_checklist_ready": True,
            "build_complete_for_operator_live_start_review": not failed,
            "live_start_authorized": False,
            "operator_manual_start_required": True,
            "codex_must_not_start_24h_test": True,
            "master_ready_for_operator_live_start": False,
            "learning_to_execution_ready": False,
            "parameter_change_allowed": False,
            "all_ticker_live_allowed_now": False,
            "follower_ready_for_live": False,
        },
        "still_requires": [
            "fresh read-only preflight if explicitly ACKed",
            "exact operator live-start ACK",
            "operator manual start outside Codex",
            "operator-defined live window, max notional, telemetry cadence and stop thresholds",
        ],
    }
    return _json_safe(report)


def render_operator_24h_prerun_build_checklist_markdown(report: Dict[str, Any]) -> str:
    flags = report.get("governance_flags") or {}
    lines = [
        "# Operator 24h Pre-Run Build Checklist",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- status: `{report.get('status')}`",
        "",
        "## Governance Flags",
        "",
    ]
    for key, value in flags.items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Checks", ""])
    for row in report.get("checks") or []:
        lines.append(f"- {row.get('name')}: passed=`{row.get('passed')}`, blocker=`{row.get('blocker')}`")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_OPERATOR_24H_PRERUN_BUILD_CHECKLIST",
    "build_operator_24h_prerun_build_checklist",
    "render_operator_24h_prerun_build_checklist_markdown",
]
