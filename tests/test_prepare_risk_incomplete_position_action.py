from __future__ import annotations

import json
import shlex
from datetime import datetime, timezone
from pathlib import Path

from tools.prepare_risk_incomplete_position_action import (
    build_report,
    write_controlled_close_report,
)


FIXED_NOW = datetime(2026, 6, 19, tzinfo=timezone.utc)
ACK = "CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_20260619"
LEGACY_ACK = "CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_ADA_20260619"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _seed_reports(root: Path) -> None:
    positions = [
        ("ETH-USDC", "eth-pos", "0.05000000", "2800", "2900", "breached"),
        ("AVAX-USDC", "avax-pos", "1.20000000", "16.80", "17.25", "breached"),
        ("SOL-USDC", "sol-pos", "0.35000000", "126", "129", "breached"),
        ("ADA-USDC", "ada-pos", "42.00000000", "0.62", "0.55", "above_stop"),
    ]
    _write_json(root / "state/positions.json", {ticker: {"status": "open"} for ticker, *_ in positions})
    _write_json(root / "state/open_orders.json", {"orders": {}})
    _write_json(
        root / "reports/audits/position-risk-reconstruction-preview-latest.json",
        {
            "runtime": {"service_active": False, "run_trader_loop_process_found": False, "lock_pid": "1627274", "stale_lock_likely": True},
            "summary": {"open_positions": [ticker for ticker, *_ in positions], "live_d2_d3_allowed_now": False},
            "positions": [
                {
                    "ticker": ticker,
                    "position_id": position_id,
                    "current_base_balance_verified": True,
                    "exposure": {"base_size_local": base, "avg_entry_price": "1", "current_price": current},
                    "balance_evidence": {"base_balance_available": base},
                    "risk_reconstruction_preview": {"proposed_stop_price": stop, "current_price_vs_stop": relation},
                }
                for ticker, position_id, base, current, stop, relation in positions
            ],
        },
    )
    _write_json(
        root / "reports/audits/reconstructed-d2-d3-exit-preview-latest.json",
        {"positions": [
            {"ticker": "ETH-USDC", "controlled_close_preview": {"recommended": True}},
            {"ticker": "AVAX-USDC", "controlled_close_preview": {"recommended": True}},
            {"ticker": "SOL-USDC", "controlled_close_preview": {"recommended": True}},
            {"ticker": "ADA-USDC", "controlled_close_preview": {"recommended": False}},
        ]},
    )
    _write_json(root / "reports/audits/position-risk-operator-decision-latest.json", {"answers": {"order_fill_evidence": "post-only maker fill evidence"}})


def test_preview_mode_submits_never_and_writes_no_state(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    report = build_report(mode="preview", root=tmp_path, now=FIXED_NOW)
    assert report["status"] == "preview_ready"
    assert report["coinbase_call_attempted"] is False
    assert report["live_submit_attempted"] is False
    assert report["live_order_submitted"] is False
    assert report["state_write_performed"] is False
    assert report["open_orders_mutated"] is False
    assert report["positions_mutated"] is False
    assert {item["ticker"] for item in report["positions"]} == {"ETH-USDC", "AVAX-USDC", "SOL-USDC", "ADA-USDC"}
    assert all(item["live_action_allowed_now"] is False for item in report["positions"])
    assert all(item["state_write_allowed_now"] is False for item in report["positions"])


def test_missing_ack_submits_never_and_close_candidates_are_stop_breaches(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    report = build_report(mode="prepare-close-command", root=tmp_path, now=FIXED_NOW, ack="")
    assert report["ack_required"] == ACK
    assert report["legacy_ack_required"] == LEGACY_ACK
    assert report["ack_provided"] is False
    assert report["ack_matches_required"] is False
    assert report["live_submit_attempted"] is False
    assert report["live_order_submitted"] is False
    assert report["state_write_performed"] is False
    assert report["positions_to_close"] == ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
    assert report["positions_to_review"] == ["ADA-USDC"]
    assert report["positions_excluded_from_close"] == ["ADA-USDC"]


def test_command_preview_contains_ack_but_does_not_execute(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    report = build_report(mode="prepare-close-command", root=tmp_path, now=FIXED_NOW, ack=ACK)
    assert report["ack_matches_required"] is True
    assert "tools/execute_controlled_position_closes.py" in report["command_preview"]
    assert "--mode execute-live" in report["command_preview"]
    assert "--positions ETH-USDC,AVAX-USDC,SOL-USDC" in report["command_preview"]
    assert "--exclude ADA-USDC" in report["command_preview"]
    assert "--require-terminal-fill-before-state-write" in report["command_preview"]
    assert "--require-verified-base" in report["command_preview"]
    assert "--block-oversell" in report["command_preview"]
    assert "--block-duplicate-exit" in report["command_preview"]
    assert "--i-understand-this-submits-live-sells" in report["command_preview"]
    assert "--json-out reports/live_runs/risk-incomplete-controlled-close-result.json" in report["command_preview"]
    assert report["will_submit_if_ack_given"] is True
    assert report["will_write_state_only_after_terminal_fill"] is True
    assert report["live_action_allowed_now"] is False
    assert report["live_order_submitted"] is False
    assert report["will_not_run_now"] is True


def test_command_preview_closes_eth_avax_sol_and_excludes_ada(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    report = build_report(mode="prepare-close-command", root=tmp_path, now=FIXED_NOW, ack=ACK)
    tokens = shlex.split(report["command_preview"])
    assert tokens[tokens.index("--positions") + 1].split(",") == ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
    assert tokens[tokens.index("--exclude") + 1].split(",") == ["ADA-USDC"]


def test_prepare_risk_completion_keeps_ada_on_review_route(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    report = build_report(mode="prepare-risk-completion", root=tmp_path, now=FIXED_NOW)
    assert report["positions_for_risk_completion_review"] == ["ADA-USDC"]
    assert report["positions_blocked_by_stop_breach"] == ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
    assert report["safe_to_write_state_now"] is False
    assert report["state_write_performed"] is False
    assert report["will_not_run_now"] is True
    assert report["risk_completion_preview_commands"] == [
        "PYTHONPATH=. ./.venv/bin/python tools/apply_reconstructed_position_risk_completion.py --ticker ADA-USDC --json"
    ]


def test_closed_historical_tickers_are_excluded_from_risk_completion_preview(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    _write_json(
        tmp_path / "state/positions.json",
        {"ETH-USDC": {"status": "closed"}, "AVAX-USDC": {"status": "closed"}, "SOL-USDC": {"status": "closed"}, "ADA-USDC": {"status": "open"}},
    )
    report = build_report(mode="prepare-risk-completion", root=tmp_path, now=FIXED_NOW)
    assert [row["ticker"] for row in report["positions"]] == ["ADA-USDC"]
    assert report["positions_for_risk_completion_review"] == ["ADA-USDC"]


def test_write_controlled_close_report_writes_only_report_files(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    state_path = tmp_path / "state/positions.json"
    before_state = state_path.read_text(encoding="utf-8")
    report = build_report(mode="prepare-close-command", root=tmp_path, now=FIXED_NOW)
    write_controlled_close_report(report, root=tmp_path)
    assert state_path.read_text(encoding="utf-8") == before_state
    assert (tmp_path / "reports/audits/risk-incomplete-controlled-close-prep-latest.json").exists()
    assert (tmp_path / "reports/audits/risk-incomplete-controlled-close-prep-latest.md").exists()
    written = json.loads((tmp_path / "reports/audits/risk-incomplete-controlled-close-prep-latest.json").read_text(encoding="utf-8"))
    assert written["state_write_performed"] is False
    assert written["live_order_submitted"] is False
