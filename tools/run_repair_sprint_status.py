#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE = "repair_sprint_status_v1"
RISK_REPORT = Path("reports/audits/position-risk-reconstruction-preview-latest.json")
D2D3_REPORT = Path("reports/audits/reconstructed-d2-d3-exit-preview-latest.json")
DECISION_REPORT = Path("reports/audits/position-risk-operator-decision-latest.json")
ENTRY_REPORT = Path("reports/audits/entry-order-type-and-orderbook-usage-audit-latest.json")
P0_GUARD_REPORT = Path("reports/audits/p0-live-entry-guard-patch-latest.json")
MARKET_GUARD_REPORT = Path("reports/audits/market-order-entry-guard-patch-latest.json")
RECONCILIATION_REPORT = Path("reports/audits/open-orders-and-positions-reconciliation-preview-latest.json")
BACKLOG_JSON = Path("reports/audits/repair-sprint-backlog-latest.json")
BACKLOG_MD = Path("reports/audits/repair-sprint-backlog-latest.md")
STALE_LOCK_JSON = Path("reports/audits/stale-lock-operator-plan-latest.json")
STALE_LOCK_MD = Path("reports/audits/stale-lock-operator-plan-latest.md")
STATUS_JSON = Path("reports/audits/repair-sprint-status-latest.json")
STATUS_MD = Path("reports/audits/repair-sprint-status-latest.md")
OPERATOR_CHECKLIST = [
    "[ ] controlled close ETH/AVAX/SOL uitgevoerd of bewust afgewezen",
    "[ ] ADA route gekozen",
    "[ ] stale lock handmatig geverifieerd en verwijderd",
    "[ ] pre-live restart readiness groen",
    "[ ] runtime guard version opnieuw geladen na restart",
    "[ ] eerste full cycle post-restart gecontroleerd",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(root: Path, relative: Path) -> Dict[str, Any]:
    try:
        data = json.loads((root / relative).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _open_order_count(reconciliation: Dict[str, Any]) -> int:
    source = reconciliation.get("reconciliation_preview_source")
    if isinstance(source, dict) and isinstance(source.get("open_orders_current"), int):
        return int(source["open_orders_current"])
    if isinstance(reconciliation.get("open_orders_current"), int):
        return int(reconciliation["open_orders_current"])
    return 0


def _open_position_count(risk_report: Dict[str, Any], reconciliation: Dict[str, Any]) -> int:
    summary = risk_report.get("summary") if isinstance(risk_report.get("summary"), dict) else {}
    positions = summary.get("open_positions") if isinstance(summary.get("open_positions"), list) else []
    if positions:
        return len(positions)
    source = reconciliation.get("reconciliation_preview_source")
    if isinstance(source, dict) and isinstance(source.get("open_positions_current"), int):
        return int(source["open_positions_current"])
    return 0


def _entry_guard_fixed_on_disk(p0_guard: Dict[str, Any], market_guard: Dict[str, Any], entry_report: Dict[str, Any]) -> bool:
    p0_text = json.dumps(p0_guard, sort_keys=True)
    market_text = json.dumps(market_guard, sort_keys=True)
    entry_summary = entry_report.get("summary") if isinstance(entry_report.get("summary"), dict) else {}
    return bool(
        "wait" in p0_text
        or "market_order_entry" in market_text
        or entry_summary.get("current_guard_blocks_replay") is True
    )


def build_stale_lock_plan(root: Path = PROJECT_ROOT) -> Dict[str, Any]:
    risk = _load_json(root, RISK_REPORT)
    runtime = risk.get("runtime") if isinstance(risk.get("runtime"), dict) else {}
    lock_pid = str(runtime.get("lock_pid") or "")
    return {
        "phase": "stale_lock_operator_plan_v1",
        "generated_at": _now_iso(),
        "lock_path": "state/run_trader_loop.lock",
        "lock_pid": lock_pid,
        "service_active": bool(runtime.get("service_active")),
        "process_exists": bool(runtime.get("run_trader_loop_process_found")),
        "safe_to_remove_after_operator_ack": bool(
            runtime.get("service_active") is False
            and runtime.get("run_trader_loop_process_found") is False
            and bool(lock_pid)
        ),
        # Het commando noemde hier een vast serverpad. Op elke andere machine
        # -- en dus op elke Windows-pc -- verwees dat naar een lockbestand dat
        # niet bestaat, waardoor het "voorbeeldcommando" niets zou opruimen.
        # De map waar de status voor opgebouwd wordt is de juiste.
        "command_preview": f"rm -f {Path(root) / 'state' / 'run_trader_loop.lock'}",
        "do_not_execute_now": True,
        "read_only": True,
        "state_write_performed": False,
        "lock_removed": False,
    }


def build_repair_backlog(root: Path = PROJECT_ROOT) -> Dict[str, Any]:
    risk = _load_json(root, RISK_REPORT)
    d2d3 = _load_json(root, D2D3_REPORT)
    decision = _load_json(root, DECISION_REPORT)
    positions_with_stop_breach = (
        (d2d3.get("summary") or {}).get("positions_with_current_stop_breach")
        if isinstance(d2d3.get("summary"), dict)
        else []
    )
    answers = decision.get("answers") if isinstance(decision.get("answers"), dict) else {}
    runtime = risk.get("runtime") if isinstance(risk.get("runtime"), dict) else {}
    return {
        "repair_sprint_status": "in_progress",
        "generated_at": _now_iso(),
        "do_not_run_bot_yet": True,
        "p0_items": [
            {
                "id": "P0-001",
                "problem": "Four open positions remain position_risk_incomplete and cannot enter live D2/D3.",
                "evidence": str((risk.get("summary") or {}).get("reason_live_d2_d3_blocked") or answers.get("order_fill_evidence") or ""),
                "fix_now": True,
                "files_to_change": [
                    "tools/prepare_risk_incomplete_position_action.py",
                    "tests/test_prepare_risk_incomplete_position_action.py",
                    "reports/audits/risk-incomplete-controlled-close-prep-latest.json",
                    "reports/audits/risk-incomplete-controlled-close-prep-latest.md",
                ],
                "tests_to_add": [
                    "preview mode submits never",
                    "missing ACK submits never",
                    "ETH/AVAX/SOL close-candidates when below reconstructed stop",
                    "ADA separate review-route",
                    "command preview contains ACK but executes nothing",
                ],
                "success_criteria": [
                    "controlled-close prep report exists",
                    "ETH-USDC, AVAX-USDC, SOL-USDC are close candidates",
                    "ADA-USDC remains manual review/risk-completion candidate",
                    "live_action_allowed_now=false for all positions",
                ],
            },
            {
                "id": "P0-002",
                "problem": "Bot must not be restarted while stale lock and risk-incomplete positions remain.",
                "evidence": f"service_active={runtime.get('service_active')}, lock_pid={runtime.get('lock_pid')}, stale_lock_likely={runtime.get('stale_lock_likely')}",
                "fix_now": True,
                "files_to_change": [
                    "tools/run_repair_sprint_status.py",
                    "tests/test_repair_sprint_status.py",
                    "reports/audits/stale-lock-operator-plan-latest.json",
                    "reports/audits/stale-lock-operator-plan-latest.md",
                    "reports/audits/repair-sprint-status-latest.json",
                    "reports/audits/repair-sprint-status-latest.md",
                ],
                "tests_to_add": [
                    "stale lock plan removes nothing",
                    "safe_to_restart=false while positions risk-incomplete",
                ],
                "success_criteria": [
                    "status tool reports safe_to_restart=false",
                    "stale-lock plan gives rm command preview only",
                    "no lock removal is performed",
                ],
            },
        ],
        "p1_items": [
            {
                "id": "P1-001",
                "problem": "Risk-completion apply tooling for ADA and any hold exception remains ACK-gated and not implemented in this sprint.",
                "evidence": f"positions_with_current_stop_breach={positions_with_stop_breach}; ADA-USDC remains above reconstructed stop but state-incomplete.",
                "fix_now": False,
                "files_to_change": [],
                "tests_to_add": [],
                "success_criteria": ["Requires separate operator ACK and exact reconstructed values before any state apply."],
            }
        ],
        "p2_items": [],
        "p3_items": [],
    }


def build_status(root: Path = PROJECT_ROOT) -> Dict[str, Any]:
    risk = _load_json(root, RISK_REPORT)
    d2d3 = _load_json(root, D2D3_REPORT)
    entry = _load_json(root, ENTRY_REPORT)
    p0_guard = _load_json(root, P0_GUARD_REPORT)
    market_guard = _load_json(root, MARKET_GUARD_REPORT)
    reconciliation = _load_json(root, RECONCILIATION_REPORT)
    runtime = risk.get("runtime") if isinstance(risk.get("runtime"), dict) else {}
    summary = risk.get("summary") if isinstance(risk.get("summary"), dict) else {}
    d2d3_summary = d2d3.get("summary") if isinstance(d2d3.get("summary"), dict) else {}
    position_risk_completion_done = bool(summary.get("live_d2_d3_allowed_now"))
    controlled_close_preview_ready = bool(d2d3_summary.get("positions_with_current_stop_breach"))
    safe_to_restart = bool(
        runtime.get("service_active") is False
        and runtime.get("stale_lock_likely") is False
        and position_risk_completion_done
    )
    return {
        "phase": PHASE,
        "generated_at": _now_iso(),
        "service_active": bool(runtime.get("service_active")),
        "stale_lock_likely": bool(runtime.get("stale_lock_likely")),
        "open_orders": _open_order_count(reconciliation),
        "open_positions": _open_position_count(risk, reconciliation),
        "p0_entry_guard_fixed_on_disk": _entry_guard_fixed_on_disk(p0_guard, market_guard, entry),
        "p0_entry_guard_runtime_loaded": False,
        "position_risk_completion_done": position_risk_completion_done,
        "controlled_close_preview_ready": controlled_close_preview_ready,
        "safe_to_restart": safe_to_restart,
        "next_operator_action": "review controlled-close ACK plan",
        "operator_checklist": list(OPERATOR_CHECKLIST),
        "do_not_run_bot_yet": True,
        "terminal_operator_status": "do_not_run_bot_yet",
        "read_only": True,
        "state_write_performed": False,
        "lock_removed": False,
        "service_restart_attempted": False,
    }


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def _write_md(path: Path, title: str, data: Dict[str, Any]) -> None:
    lines = [f"# {title}", "", f"Generated: `{data.get('generated_at')}`", ""]
    for key, value in data.items():
        if key in {"phase", "generated_at"}:
            continue
        if isinstance(value, (dict, list)):
            lines.append(f"- `{key}`: `{json.dumps(value, sort_keys=True)}`")
        else:
            lines.append(f"- `{key}`: `{value}`")
    if data.get("operator_checklist"):
        lines.extend(["", "## Operator Checklist", ""])
        lines.extend(str(item) for item in data.get("operator_checklist") or [])
    lines.append("")
    lines.append("No live action was taken.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_reports(root: Path = PROJECT_ROOT) -> Dict[str, Any]:
    backlog = build_repair_backlog(root)
    stale_lock = build_stale_lock_plan(root)
    status = build_status(root)
    _write_json(root / BACKLOG_JSON, backlog)
    _write_md(root / BACKLOG_MD, "Repair Sprint Backlog", backlog)
    _write_json(root / STALE_LOCK_JSON, stale_lock)
    _write_md(root / STALE_LOCK_MD, "Stale Lock Operator Plan", stale_lock)
    _write_json(root / STATUS_JSON, status)
    _write_md(root / STATUS_MD, "Repair Sprint Status", status)
    return {
        "backlog": str(BACKLOG_JSON),
        "stale_lock_plan": str(STALE_LOCK_JSON),
        "status": str(STATUS_JSON),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only repair sprint status from existing audit reports.")
    parser.add_argument("--write-reports", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    status = build_status()
    if args.write_reports:
        status["reports_written"] = write_reports()
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in status.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
