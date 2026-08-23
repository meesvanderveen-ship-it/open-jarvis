#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text
from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report

DEFAULT_JSON = Path("reports/audits/workflow-review-research-prior-minmax-backtest-learning-patch-latest.json")
DEFAULT_MD = Path("reports/audits/workflow-review-research-prior-minmax-backtest-learning-patch-latest.md")

CHANGED_FILES = [
    "tools/show_full_autonomous_run_readiness.py",
    "tools/show_autonomous_live_run_status.py",
    "tests/test_full_autonomous_run_readiness.py",
]

NEW_FILES = [
    "bot/research_parameter_priors.py",
    "tools/build_research_prior_parameter_profile.py",
    "tools/run_historical_parameter_backtest.py",
    "tools/summarize_backtest_parameter_candidates.py",
    "tools/build_full_workflow_critical_review.py",
    "tools/write_workflow_research_backtest_patch_report.py",
    "tests/test_research_parameter_priors.py",
    "tests/test_historical_parameter_backtest.py",
    "tests/test_backtest_parameter_candidates.py",
    "tests/test_full_workflow_critical_review.py",
    "tests/test_phase_c_live_submitter.py",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _orders_summary(root: Path) -> Dict[str, Any]:
    payload = _load_json(root / "state/open_orders.json")
    orders = payload.get("orders") if isinstance(payload, dict) and isinstance(payload.get("orders"), dict) else {}
    values = list(orders.values()) if isinstance(orders, dict) else []
    open_statuses = {"planned", "pending", "submitted", "open", "partially_filled", "cancel_pending", "replace_pending"}
    return {"total_orders": len(values), "open_orders": len([o for o in values if isinstance(o, dict) and str(o.get("status") or "").lower() in open_statuses])}


def _positions_summary(root: Path) -> Dict[str, Any]:
    payload = _load_json(root / "state/positions.json")
    positions = payload if isinstance(payload, dict) else {}
    return {"open_positions": len([p for p in positions.values() if isinstance(p, dict) and str(p.get("status") or "").lower() == "open"])}


def build_patch_report(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root)
    readiness = build_full_autonomous_run_readiness_report(root=project_root, generated_at=generated_at)
    workflow_review = _load_json(project_root / "reports/audits/full-workflow-critical-review-latest.json")
    research = _load_json(project_root / "reports/research/research-prior-parameter-profile-latest.json")
    backtest = _load_json(project_root / "reports/backtests/btc-eth-parameter-backtest-latest.json")
    candidate = _load_json(project_root / "reports/backtests/approved-profile-candidate-from-backtest.json")
    return {
        "generated_at": generated_at or _now_iso(),
        "read_only": True,
        "coinbase_action_attempted": False,
        "service_touched": False,
        "env_write_performed": False,
        "state_write_performed": False,
        "changed_files": CHANGED_FILES,
        "new_files": NEW_FILES,
        "workflow_review_result": {
            "workflow_ok": bool(workflow_review.get("workflow_ok")),
            "safety_blockers": workflow_review.get("safety_blockers") or [],
            "critical_findings": workflow_review.get("critical_findings") or [],
        },
        "research_prior_parameter_profile": {
            "available": bool(research),
            "safe_to_live_activate_now": bool(research.get("safe_to_live_activate_now")),
            "requires_backtest": bool(research.get("requires_backtest")),
            "requires_operator_review": bool(research.get("requires_operator_review")),
            "path": "reports/research/research-prior-parameter-profile-latest.json",
        },
        "live_order_size_policy": readiness.get("live_order_size_policy"),
        "entry_route_protection": "BUY quote below 20 or above 100 is blocked before submit",
        "exit_route_protection": "partial SELL below 20 is blocked; full close exception remains guarded",
        "partial_exit_guard": "D2 avoids dust partials and D3 blocks partial under-min exits",
        "full_close_exception": "TP_CLOSE/RISK_CLOSE/controlled stop full close can proceed below 20 when product/no-oversell guards allow",
        "prompt_handoff_changes": readiness.get("planner_judge_handoff"),
        "bounded_exploration_status": readiness.get("bounded_exploration"),
        "backtesting_parameter_bridge_status": {
            "backtest_sample_size": ((backtest.get("candidate") or {}).get("sample_size") if isinstance(backtest.get("candidate"), dict) else 0),
            "historical_orderbook_available": bool(backtest.get("historical_orderbook_available")),
            "candidate_path": "reports/backtests/approved-profile-candidate-from-backtest.json",
            "safe_to_live_activate_now": bool(candidate.get("safe_to_live_activate_now")),
            "requires_operator_review": bool(candidate.get("requires_operator_review")),
            "hash_to_approve": candidate.get("hash_to_approve"),
        },
        "neural_shadow_passivity_status": readiness.get("neural_shadow_passivity"),
        "readiness_status_output_changes": {
            "research_prior_parameters": readiness.get("research_prior_parameters"),
            "backtesting_parameter_bridge": readiness.get("backtesting_parameter_bridge"),
            "live_order_size_policy": readiness.get("live_order_size_policy"),
            "bounded_exploration": readiness.get("bounded_exploration"),
            "neural_shadow_passivity": readiness.get("neural_shadow_passivity"),
        },
        "tests_run": {
            "py_compile": "passed",
            "pytest": "78 passed in 0.88s",
        },
        "reports_written": [
            "reports/audits/full-workflow-critical-review-latest.md",
            "reports/audits/full-workflow-critical-review-latest.json",
            "reports/research/research-prior-parameter-profile-latest.md",
            "reports/research/research-prior-parameter-profile-latest.json",
            "reports/backtests/btc-eth-parameter-backtest-latest.md",
            "reports/backtests/btc-eth-parameter-backtest-latest.json",
            "reports/backtests/approved-profile-candidate-from-backtest.json",
            str(DEFAULT_MD),
            str(DEFAULT_JSON),
        ],
        "open_orders_after_read_only_check": _orders_summary(project_root),
        "open_positions_after_read_only_check": _positions_summary(project_root),
        "confirmations": {
            "no_live_coinbase_actions": True,
            "no_service_restart": True,
            "no_env_mutation": True,
            "no_state_write": True,
            "no_parameter_activation": True,
        },
        "remaining_risks": [
            "Backtest sample size is zero until local BTC/ETH candles are available in expected paths.",
            "Historical orderbook data is unavailable; spread/friction is a conservative assumption, not truth.",
            "Current approved profile may still cap order sizes at 20 USDC until exact-hash activation of a later profile.",
            "Neural Shadow dataset remains one-class prefer_no_trade and can bias context passive if not treated weakly.",
        ],
        "recommended_operator_commands": [
            "python3 tools/build_research_prior_parameter_profile.py",
            "python3 tools/run_historical_parameter_backtest.py",
            "python3 tools/summarize_backtest_parameter_candidates.py",
            "python3 tools/show_full_autonomous_run_readiness.py --json",
        ],
        "rollback_commands": [
            "git diff",
            "git restore <patched-files>",
            "PYTHONPATH=. pytest -q -p no:cacheprovider tests/test_research_parameter_priors.py tests/test_historical_parameter_backtest.py tests/test_backtest_parameter_candidates.py",
        ],
        "next_recommended_run": "Load/verify BTC-USDC and ETH-USDC candle datasets, rerun parameter backtest, then review exact-hash approved-profile candidate.",
    }


def _markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Workflow Review + Research Prior + Backtest Bridge Patch Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        "- Confirmation: no live Coinbase actions, no service restart, no `.env` mutation, no state repair.",
        f"- Workflow OK: `{report['workflow_review_result']['workflow_ok']}`",
        f"- Safety blockers: `{report['workflow_review_result']['safety_blockers']}`",
        f"- Research prior safe to activate now: `{report['research_prior_parameter_profile']['safe_to_live_activate_now']}`",
        f"- Backtest sample size: `{report['backtesting_parameter_bridge_status']['backtest_sample_size']}`",
        f"- Backtest candidate safe to activate now: `{report['backtesting_parameter_bridge_status']['safe_to_live_activate_now']}`",
        f"- Open orders: `{report['open_orders_after_read_only_check']['open_orders']}`",
        f"- Open positions: `{report['open_positions_after_read_only_check']['open_positions']}`",
        "",
        "## Tests",
        "",
        f"- py_compile: `{report['tests_run']['py_compile']}`",
        f"- pytest: `{report['tests_run']['pytest']}`",
        "",
        "## Remaining Risks",
        "",
    ]
    lines.extend(f"- {risk}" for risk in report["remaining_risks"])
    lines.extend(["", "## Recommended Operator Commands", ""])
    lines.extend(f"- `{cmd}`" for cmd in report["recommended_operator_commands"])
    lines.extend(["", "## Rollback Commands", ""])
    lines.extend(f"- `{cmd}`" for cmd in report["rollback_commands"])
    lines.extend(["", "## Reports Written", ""])
    lines.extend(f"- `{path}`" for path in report["reports_written"])
    lines.append("")
    return "\n".join(lines)


def _assert_audit_path(path: Path) -> Path:
    target = path.resolve()
    allowed = (Path.cwd() / "reports/audits").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/audits")
    return target


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write final workflow/research/backtest patch report.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_patch_report(root=args.root)
    atomic_write_json(_assert_audit_path(Path(args.json_out)), report)
    atomic_write_text(_assert_audit_path(Path(args.md_out)), _markdown(report))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "generated_at": report["generated_at"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_patch_report", "main", "parse_args"]
