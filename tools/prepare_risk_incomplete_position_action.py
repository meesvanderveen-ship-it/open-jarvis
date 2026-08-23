#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Sequence

from bot.pre_live_current_state import build_pre_live_current_state


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE = "risk_incomplete_position_action_prep_v1"
TARGET_TICKERS = ("ETH-USDC", "AVAX-USDC", "SOL-USDC", "ADA-USDC")
CONTROLLED_CLOSE_TICKERS = ("ETH-USDC", "AVAX-USDC", "SOL-USDC")
CONTROLLED_CLOSE_EXCLUDED_TICKERS = ("ADA-USDC",)
RISK_REPORT = Path("reports/audits/position-risk-reconstruction-preview-latest.json")
D2D3_REPORT = Path("reports/audits/reconstructed-d2-d3-exit-preview-latest.json")
DECISION_REPORT = Path("reports/audits/position-risk-operator-decision-latest.json")
CONTROLLED_CLOSE_REPORT_JSON = Path("reports/audits/risk-incomplete-controlled-close-prep-latest.json")
CONTROLLED_CLOSE_REPORT_MD = Path("reports/audits/risk-incomplete-controlled-close-prep-latest.md")
CONTROLLED_CLOSE_RESULT_JSON = Path("reports/live_runs/risk-incomplete-controlled-close-result.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _today_token(now: datetime | None = None) -> str:
    selected = now or datetime.now(timezone.utc)
    return selected.strftime("%Y%m%d")


def _load_json(root: Path, relative: Path) -> Dict[str, Any]:
    path = root / relative
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        return Decimal(text or default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _ack_required(date_token: str) -> str:
    return f"CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_{date_token}"


def _legacy_close_ack_required(date_token: str) -> str:
    return f"CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_ADA_{date_token}"


def _ada_review_ack_required(date_token: str) -> str:
    return f"ADA_ROUTE_REVIEW_REQUIRED_{date_token}"


def _risk_completion_ack_required(date_token: str) -> str:
    return f"APPLY_RECONSTRUCTED_RISK_COMPLETION_ETH_AVAX_SOL_ADA_{date_token}"


def _risk_positions(risk_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    positions = risk_report.get("positions") if isinstance(risk_report.get("positions"), list) else []
    by_ticker = {
        _normalize_ticker(position.get("ticker")): position
        for position in positions
        if isinstance(position, dict)
    }
    return [by_ticker[ticker] for ticker in TARGET_TICKERS if ticker in by_ticker]


def _d2d3_positions(d2d3_report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    positions = d2d3_report.get("positions") if isinstance(d2d3_report.get("positions"), list) else []
    return {
        _normalize_ticker(position.get("ticker")): position
        for position in positions
        if isinstance(position, dict)
    }


def _below_reconstructed_stop(position: Dict[str, Any]) -> bool:
    risk = position.get("risk_reconstruction_preview") if isinstance(position.get("risk_reconstruction_preview"), dict) else {}
    if str(risk.get("current_price_vs_stop") or "").strip().lower() == "breached":
        return True
    exposure = position.get("exposure") if isinstance(position.get("exposure"), dict) else {}
    current = _to_decimal(exposure.get("current_price"), "0")
    stop = _to_decimal(risk.get("proposed_stop_price"), "0")
    return bool(current > 0 and stop > 0 and current <= stop)


def build_position_preview(root: Path = PROJECT_ROOT) -> List[Dict[str, Any]]:
    risk_report = _load_json(root, RISK_REPORT)
    d2d3_by_ticker = _d2d3_positions(_load_json(root, D2D3_REPORT))
    current_open = set(build_pre_live_current_state(root).get("open_positions") or [])
    preview: List[Dict[str, Any]] = []
    for position in _risk_positions(risk_report):
        ticker = _normalize_ticker(position.get("ticker"))
        if ticker not in current_open:
            continue
        exposure = position.get("exposure") if isinstance(position.get("exposure"), dict) else {}
        balance = position.get("balance_evidence") if isinstance(position.get("balance_evidence"), dict) else {}
        risk = position.get("risk_reconstruction_preview") if isinstance(position.get("risk_reconstruction_preview"), dict) else {}
        controlled_close = (
            d2d3_by_ticker.get(ticker, {}).get("controlled_close_preview")
            if isinstance(d2d3_by_ticker.get(ticker, {}).get("controlled_close_preview"), dict)
            else {}
        )
        below_stop = _below_reconstructed_stop(position)
        recommended_action = (
            "controlled_close_requires_ack"
            if below_stop or bool(controlled_close.get("recommended"))
            else "risk_completion_review_requires_ack"
        )
        preview.append(
            {
                "ticker": ticker,
                "position_id": str(position.get("position_id") or ""),
                "base_balance_verified": bool(position.get("current_base_balance_verified")),
                "local_base": str(exposure.get("base_size_local") or position.get("base_filled") or "0"),
                "available_base": str(balance.get("base_balance_available") or ""),
                "avg_entry": str(exposure.get("avg_entry_price") or position.get("avg_entry_price") or ""),
                "current_price": str(exposure.get("current_price") or ""),
                "reconstructed_stop": str(risk.get("proposed_stop_price") or ""),
                "below_reconstructed_stop": bool(below_stop),
                "recommended_action": recommended_action,
                "live_action_allowed_now": False,
                "state_write_allowed_now": False,
                "source_report": str(RISK_REPORT),
            }
        )
    return preview


def _command_preview(positions_to_close: Sequence[str], positions_excluded: Sequence[str], ack: str) -> str:
    joined = ",".join(positions_to_close)
    excluded = ",".join(positions_excluded)
    return (
        "PYTHONPATH=. python3 tools/execute_controlled_position_closes.py \\\n"
        "  --mode execute-live \\\n"
        f"  --ack {ack} \\\n"
        f"  --positions {joined} \\\n"
        f"  --exclude {excluded} \\\n"
        "  --require-verified-base \\\n"
        "  --block-oversell \\\n"
        "  --block-duplicate-exit \\\n"
        "  --require-terminal-fill-before-state-write \\\n"
        "  --i-understand-this-submits-live-sells \\\n"
        f"  --json-out {CONTROLLED_CLOSE_RESULT_JSON}"
    )


def build_report(
    *,
    mode: str,
    root: Path = PROJECT_ROOT,
    now: datetime | None = None,
    ack: str = "",
) -> Dict[str, Any]:
    mode = str(mode or "preview").strip()
    date_token = _today_token(now)
    required_close_ack = _ack_required(date_token)
    legacy_close_ack = _legacy_close_ack_required(date_token)
    ada_review_ack = _ada_review_ack_required(date_token)
    required_risk_ack = _risk_completion_ack_required(date_token)
    positions = build_position_preview(root)
    positions_to_close = [
        p["ticker"]
        for p in positions
        if p.get("below_reconstructed_stop") and p.get("ticker") in CONTROLLED_CLOSE_TICKERS
    ]
    positions_to_review = [p["ticker"] for p in positions if not p.get("below_reconstructed_stop")]
    positions_excluded_from_close = [
        ticker
        for ticker in CONTROLLED_CLOSE_EXCLUDED_TICKERS
        if ticker in {p.get("ticker") for p in positions}
    ]
    common: Dict[str, Any] = {
        "phase": PHASE,
        "generated_at": _now_iso(),
        "mode": mode,
        "read_only": True,
        "coinbase_call_attempted": False,
        "live_submit_attempted": False,
        "live_order_submitted": False,
        "state_write_performed": False,
        "open_orders_mutated": False,
        "positions_mutated": False,
        "service_restart_attempted": False,
        "lock_removed": False,
        "will_not_run_now": True,
        "positions": positions,
        "positions_to_close": positions_to_close,
        "positions_to_review": positions_to_review,
        "positions_excluded_from_close": positions_excluded_from_close,
        "ada_action": "manual_hold_review_or_risk_completion_after_ack",
        "ada_review_ack_required": ada_review_ack,
        "safety_policy": {
            "preview_only_by_default": True,
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_replace": True,
            "does_not_apply_state": True,
            "does_not_remove_lock": True,
            "does_not_restart_service": True,
        },
    }
    if mode == "preview":
        common.update(
            {
                "status": "preview_ready",
                "live_action_allowed_now": False,
                "next_operator_action": "review controlled-close ACK plan",
            }
        )
        return common

    if mode == "prepare-close-command":
        command_ack = required_close_ack
        common.update(
            {
                "status": "controlled_close_command_preview_ready",
                "ack_required": command_ack,
                "legacy_ack_required": legacy_close_ack,
                "ack_provided": bool(str(ack or "").strip()),
                "ack_matches_required": str(ack or "").strip() == command_ack,
                "command_preview": _command_preview(positions_to_close, positions_excluded_from_close, command_ack),
                "will_submit_if_ack_given": True,
                "will_write_state_only_after_terminal_fill": True,
                "will_not_run_now": True,
                "live_action_allowed_now": False,
                "blockers": [
                    "preview_tool_does_not_submit",
                    "operator_ack_required",
                    "dedicated_apply_command_must_be_reviewed_before_use",
                ],
            }
        )
        return common

    if mode == "prepare-risk-completion":
        common.update(
            {
                "status": "risk_completion_command_preview_ready",
                "ack_required": required_risk_ack,
                "ack_provided": bool(str(ack or "").strip()),
                "ack_matches_required": str(ack or "").strip() == required_risk_ack,
                "positions_for_risk_completion_review": positions_to_review,
                "positions_blocked_by_stop_breach": positions_to_close,
                "safe_to_write_state_now": False,
                "will_not_run_now": True,
                "risk_completion_preview_commands": [
                    "PYTHONPATH=. ./.venv/bin/python tools/apply_reconstructed_position_risk_completion.py "
                    f"--ticker {ticker} --json"
                    for ticker in positions_to_review
                ],
                "blockers": [
                    "preview_tool_does_not_apply_state",
                    "operator_ack_required",
                    "risk_completion_apply_requires_runtime_ack_and_evidence_hash",
                ],
            }
        )
        return common

    common.update(
        {
            "status": "invalid_mode",
            "blockers": ["invalid_mode"],
            "valid_modes": ["preview", "prepare-close-command", "prepare-risk-completion"],
        }
    )
    return common


def write_controlled_close_report(report: Dict[str, Any], root: Path = PROJECT_ROOT) -> None:
    json_path = root / CONTROLLED_CLOSE_REPORT_JSON
    md_path = root / CONTROLLED_CLOSE_REPORT_MD
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    rows = []
    for item in report.get("positions") or []:
        rows.append(
            "| {ticker} | {position_id} | {base_balance_verified} | {local_base} | {available_base} | {current_price} | {reconstructed_stop} | {below_reconstructed_stop} | {recommended_action} |".format(
                **item
            )
        )
    table = "\n".join(
        [
            "| ticker | position_id | base_verified | local_base | available_base | current | stop | below_stop | action |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            *rows,
        ]
    )
    md = (
        "# Risk-Incomplete Controlled Close Prep\n\n"
        f"Generated: `{report.get('generated_at')}`\n\n"
        f"Mode: `{report.get('mode')}`\n\n"
        f"{table}\n\n"
        f"ACK required: `{report.get('ack_required', '')}`\n\n"
        f"Legacy ACK retained for compatibility: `{report.get('legacy_ack_required', '')}`\n\n"
        f"Positions excluded from close: `{json.dumps(report.get('positions_excluded_from_close') or [])}`\n\n"
        f"ADA action: `{report.get('ada_action', '')}`\n\n"
        f"Command preview: `{report.get('command_preview', '')}`\n\n"
        "No live action was taken. This tool does not submit, cancel, replace, apply state, restart service, or remove the stale lock.\n"
    )
    md_path.write_text(md, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare preview-only action plans for risk-incomplete open positions.")
    parser.add_argument("--mode", choices=["preview", "prepare-close-command", "prepare-risk-completion"], default="prepare-close-command")
    parser.add_argument("--ack", default="")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-out", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(mode=args.mode, ack=args.ack)
    if args.write_report or args.json_out:
        write_controlled_close_report(report)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"status: {report.get('status')}")
        print(f"positions_to_close: {report.get('positions_to_close')}")
        print(f"positions_to_review: {report.get('positions_to_review')}")
        print(f"ack_required: {report.get('ack_required', '')}")
        print(f"will_not_run_now: {report.get('will_not_run_now')}")
    return 2 if report.get("status") == "invalid_mode" else 0


if __name__ == "__main__":
    raise SystemExit(main())
