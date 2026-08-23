#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shlex
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.controlled_stop_market_exit_executor import prepare_controlled_close_execution
from bot.order_lifecycle import is_open_order_status

PHASE = "final_controlled_close_preexecution_validation_v1"
CONTROLLED_CLOSE_PREP = Path("reports/audits/risk-incomplete-controlled-close-prep-latest.json")
RISK_REPORT = Path("reports/audits/position-risk-reconstruction-preview-latest.json")
STATE_OPEN_ORDERS = Path("state/open_orders.json")
VALIDATION_JSON = Path("reports/audits/final-controlled-close-preexecution-validation-latest.json")
VALIDATION_MD = Path("reports/audits/final-controlled-close-preexecution-validation-latest.md")

EXPECTED_CLOSE = ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
EXPECTED_REVIEW = ["ADA-USDC"]
EXPECTED_EXCLUDED = ["ADA-USDC"]
EXPECTED_ACK = "CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_20260619"
EXPECTED_EXECUTE_TOOL = "tools/execute_controlled_position_closes.py"
EXPECTED_JSON_OUT_PREFIX = Path("reports/live_runs")
REQUIRED_COMMAND_FLAGS = [
    "--mode",
    "--require-verified-base",
    "--block-oversell",
    "--block-duplicate-exit",
    "--require-terminal-fill-before-state-write",
    "--i-understand-this-submits-live-sells",
]
ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(root: Path, relative: Path) -> Dict[str, Any]:
    try:
        payload = json.loads((root / relative).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value).strip() or default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _as_ticker_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip().upper() for item in value if str(item).strip()]


def _csv_tickers(value: Any) -> List[str]:
    return [item.strip().upper() for item in str(value or "").split(",") if item.strip()]


def _arg_after(tokens: List[str], flag: str) -> str:
    try:
        index = tokens.index(flag)
    except ValueError:
        return ""
    next_index = index + 1
    if next_index >= len(tokens):
        return ""
    return str(tokens[next_index] or "").strip()


def _json_out_under_reports_live_runs(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    path = Path(text)
    if path.is_absolute() or ".." in path.parts:
        return False
    return path.parts[:2] == EXPECTED_JSON_OUT_PREFIX.parts and path.suffix == ".json"


def _validate_command_preview(command_preview: Any, ack_required: str) -> Dict[str, Any]:
    command = str(command_preview or "").strip()
    parse_command = command.replace("\\\n", " ")
    blockers: List[str] = []
    if not command:
        return {
            "present": False,
            "exact": False,
            "ack": "",
            "positions": [],
            "excluded": [],
            "json_out": "",
            "required_flags_present": False,
            "blockers": ["missing_command_preview"],
        }
    try:
        tokens = shlex.split(parse_command)
    except ValueError:
        return {
            "present": True,
            "exact": False,
            "ack": "",
            "positions": [],
            "excluded": [],
            "json_out": "",
            "required_flags_present": False,
            "blockers": ["command_preview_parse_error"],
        }

    if tokens[:3] != ["PYTHONPATH=.", "python3", EXPECTED_EXECUTE_TOOL]:
        blockers.append("command_preview_tool_mismatch")
    command_ack = _arg_after(tokens, "--ack")
    command_mode = _arg_after(tokens, "--mode")
    command_positions = _csv_tickers(_arg_after(tokens, "--positions"))
    command_excluded = _csv_tickers(_arg_after(tokens, "--exclude"))
    json_out = _arg_after(tokens, "--json-out")
    missing_flags = [flag for flag in REQUIRED_COMMAND_FLAGS if flag not in tokens]

    if command_ack != ack_required or command_ack != EXPECTED_ACK:
        blockers.append("command_preview_ack_mismatch")
    if command_mode != "execute-live":
        blockers.append("command_preview_mode_must_be_execute_live")
    if command_positions != EXPECTED_CLOSE:
        blockers.append("command_preview_positions_mismatch")
    if command_excluded != EXPECTED_EXCLUDED:
        blockers.append("command_preview_excluded_positions_mismatch")
    if "ADA-USDC" in command_positions:
        blockers.append("command_preview_must_not_close_ada")
    if missing_flags:
        blockers.append("command_preview_required_safety_flags_missing")
    if not _json_out_under_reports_live_runs(json_out):
        blockers.append("command_preview_json_out_not_under_reports_live_runs")

    return {
        "present": True,
        "exact": not blockers,
        "ack": command_ack,
        "mode": command_mode,
        "positions": command_positions,
        "excluded": command_excluded,
        "json_out": json_out,
        "required_flags_present": not missing_flags,
        "missing_flags": missing_flags,
        "blockers": blockers,
    }


def _positions_by_ticker(prep: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    positions = prep.get("positions") if isinstance(prep.get("positions"), list) else []
    return {
        str(position.get("ticker") or "").strip().upper(): position
        for position in positions
        if isinstance(position, dict) and str(position.get("ticker") or "").strip()
    }


def _open_sell_orders(root: Path, tickers: Iterable[str]) -> List[Dict[str, Any]]:
    wanted = {str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()}
    state = _load_json(root, STATE_OPEN_ORDERS)
    orders = state.get("orders") if isinstance(state.get("orders"), dict) else {}
    open_sells: List[Dict[str, Any]] = []
    for order_id, order in orders.items():
        if not isinstance(order, dict):
            continue
        side = str(order.get("side") or "").strip().upper()
        ticker = str(order.get("ticker") or order.get("product_id") or "").strip().upper()
        if is_open_order_status(order.get("status")) and side == "SELL" and ticker in wanted:
            record = dict(order)
            record.setdefault("client_order_id", str(order_id))
            open_sells.append(record)
    return open_sells


def _base_checks(positions: Dict[str, Dict[str, Any]], tickers: List[str]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    blockers: List[str] = []
    for ticker in tickers:
        position = positions.get(ticker, {})
        local_base = _to_decimal(position.get("local_base"), "0")
        available_base = _to_decimal(position.get("available_base") or position.get("local_base"), "0")
        verified = bool(position.get("base_balance_verified"))
        oversell = bool(local_base <= ZERO or available_base <= ZERO or local_base > available_base)
        if not verified:
            blockers.append(f"{ticker}:base_balance_not_verified")
        if oversell:
            blockers.append(f"{ticker}:close_size_exceeds_available_base")
        rows.append(
            {
                "ticker": ticker,
                "base_balance_verified": verified,
                "local_base": str(position.get("local_base") or "0"),
                "available_base": str(position.get("available_base") or ""),
                "would_oversell": oversell,
            }
        )
    return {
        "rows": rows,
        "base_balances_verified": bool(tickers and all(row["base_balance_verified"] for row in rows)),
        "oversell_blocked": not any(row["would_oversell"] for row in rows),
        "blockers": blockers,
    }


def build_validation_report(root: Path = PROJECT_ROOT, ack: str = "") -> Dict[str, Any]:
    prep = _load_json(root, CONTROLLED_CLOSE_PREP)
    risk_report = _load_json(root, RISK_REPORT)
    runtime = risk_report.get("runtime") if isinstance(risk_report.get("runtime"), dict) else {}
    positions_to_close = _as_ticker_list(prep.get("positions_to_close"))
    positions_to_review = _as_ticker_list(prep.get("positions_to_review"))
    positions_excluded_from_close = _as_ticker_list(prep.get("positions_excluded_from_close")) or positions_to_review
    ack_required = str(prep.get("ack_required") or "")
    ack_provided = str(ack or "").strip()
    positions = _positions_by_ticker(prep)
    command_preview = prep.get("command_preview")
    command_validation = _validate_command_preview(command_preview, ack_required)
    base = _base_checks(positions, positions_to_close)
    open_sell_orders = _open_sell_orders(root, positions_to_close)
    duplicate_exit_blocked = len(open_sell_orders) == 0
    execution_gate = prepare_controlled_close_execution(
        ack=ack_provided,
        required_ack=ack_required,
        positions_to_close=positions_to_close,
        command_tickers=command_validation.get("positions") or positions_to_close,
        mock_mode=True,
        terminal_fill_evidence={},
    )
    service_active = bool(runtime.get("service_active") or runtime.get("run_trader_loop_process_found"))

    blockers: List[str] = []
    if positions_to_close != EXPECTED_CLOSE:
        blockers.append("positions_to_close_mismatch")
    if positions_to_review != EXPECTED_REVIEW:
        blockers.append("positions_to_review_mismatch")
    if positions_excluded_from_close != EXPECTED_EXCLUDED:
        blockers.append("positions_excluded_from_close_mismatch")
    if "ADA-USDC" in positions_to_close:
        blockers.append("ada_must_not_be_in_controlled_close_batch")
    if ack_required != EXPECTED_ACK:
        blockers.append("ack_required_mismatch")
    if not command_validation.get("present"):
        blockers.append("missing_command_preview")
    elif not command_validation.get("exact"):
        blockers.append("command_preview_invalid")
    if not base["base_balances_verified"]:
        blockers.append("base_balance_verification_missing")
    if not base["oversell_blocked"]:
        blockers.append("oversell_risk_detected")
    if not duplicate_exit_blocked:
        blockers.append("duplicate_open_exit_detected")
    if prep.get("will_write_state_only_after_terminal_fill") is not True:
        blockers.append("state_write_terminal_fill_gate_missing")
    if service_active:
        blockers.append("service_active")
    blockers.extend(command_validation.get("blockers") or [])
    blockers.extend(base["blockers"])
    blockers = list(dict.fromkeys(blockers))

    safe_after_ack = bool(
        not blockers
        and command_validation.get("present") is True
        and command_validation.get("exact") is True
        and ack_required == EXPECTED_ACK
        and execution_gate.get("state_write_only_after_terminal_fill") is True
    )
    return {
        "safe_to_execute_after_exact_ack": safe_after_ack,
        "blocker": blockers[0] if blockers else "",
        "ack_required": ack_required,
        "positions_to_close": positions_to_close,
        "positions_excluded_from_close": positions_excluded_from_close,
        "positions_to_review": positions_to_review,
        "ada_action": str(prep.get("ada_action") or "manual_hold_review_or_risk_completion_after_ack"),
        "command_preview": command_preview if command_validation.get("present") else None,
        "command_preview_present": bool(command_validation.get("present")),
        "base_balances_verified": base["base_balances_verified"],
        "oversell_blocked": base["oversell_blocked"],
        "duplicate_exit_blocked": duplicate_exit_blocked,
        "state_write_only_after_terminal_fill": bool(
            prep.get("will_write_state_only_after_terminal_fill") is True
            and command_validation.get("required_flags_present") is True
            and execution_gate.get("state_write_only_after_terminal_fill") is True
        ),
        "service_active": service_active,
        "stale_lock_not_removed": True,
        "will_not_run_now": True,
        "operator_action": (
            "safe to execute controlled close only after exact ACK"
            if safe_after_ack
            else "do not execute; fix command preview first"
        ),
        "phase": PHASE,
        "generated_at": _now_iso(),
        "ack_provided": bool(ack_provided),
        "ack_matches_required": ack_provided == ack_required,
        "safe_to_execute_now": False,
        "ada_excluded_from_close_batch": "ADA-USDC" not in positions_to_close and "ADA-USDC" in positions_to_review,
        "base_checks": base["rows"],
        "duplicate_open_exit_orders": open_sell_orders,
        "command_validation": command_validation,
        "execution_gate": execution_gate,
        "blockers": blockers,
        "read_only": True,
        "coinbase_call_attempted": False,
        "live_submit_attempted": False,
        "live_order_submitted": False,
        "state_write_performed": False,
        "open_orders_mutated": False,
        "positions_mutated": False,
        "service_restart_attempted": False,
        "lock_removed": False,
    }


def write_validation_report(report: Dict[str, Any], root: Path = PROJECT_ROOT) -> None:
    json_path = root / VALIDATION_JSON
    md_path = root / VALIDATION_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    lines = [
        "# Final Controlled-Close Preexecution Validation",
        "",
        f"Generated: `{report.get('generated_at')}`",
        "",
        f"- `safe_to_execute_after_exact_ack`: `{report.get('safe_to_execute_after_exact_ack')}`",
        f"- `ack_required`: `{report.get('ack_required')}`",
        f"- `ack_matches_required`: `{report.get('ack_matches_required')}`",
        f"- `command_preview_present`: `{report.get('command_preview_present')}`",
        f"- `positions_to_close`: `{json.dumps(report.get('positions_to_close') or [])}`",
        f"- `positions_excluded_from_close`: `{json.dumps(report.get('positions_excluded_from_close') or [])}`",
        f"- `positions_to_review`: `{json.dumps(report.get('positions_to_review') or [])}`",
        f"- `base_balances_verified`: `{report.get('base_balances_verified')}`",
        f"- `oversell_blocked`: `{report.get('oversell_blocked')}`",
        f"- `duplicate_exit_blocked`: `{report.get('duplicate_exit_blocked')}`",
        f"- `state_write_only_after_terminal_fill`: `{report.get('state_write_only_after_terminal_fill')}`",
        f"- `service_active`: `{report.get('service_active')}`",
        f"- `stale_lock_not_removed`: `{report.get('stale_lock_not_removed')}`",
        f"- `will_not_run_now`: `{report.get('will_not_run_now')}`",
        f"- `operator_action`: `{report.get('operator_action')}`",
        f"- `blocker`: `{report.get('blocker')}`",
        "",
        f"Command preview: `{report.get('command_preview') or ''}`",
        "",
        "No live action was taken.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate controlled-close readiness without executing it.")
    parser.add_argument("--ack", default="")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-out", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_validation_report(ack=args.ack)
    if args.write_report or args.json_out:
        write_validation_report(report)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"safe_to_execute_after_exact_ack: {report.get('safe_to_execute_after_exact_ack')}")
        print(f"ack_required: {report.get('ack_required')}")
        print(f"will_not_run_now: {report.get('will_not_run_now')}")
        print(f"operator_action: {report.get('operator_action')}")
    return 0 if report.get("safe_to_execute_after_exact_ack") else 2


if __name__ == "__main__":
    raise SystemExit(main())
