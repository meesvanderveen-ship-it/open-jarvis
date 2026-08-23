from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from tools.execute_controlled_position_closes import build_execution_preview_report
from tools.validate_controlled_close_preexecution import build_validation_report, write_validation_report


ACK = "CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_20260619"
OLD_ACK = "CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_ADA_20260619"
COMMAND = (
    "PYTHONPATH=. python3 tools/execute_controlled_position_closes.py \\\n"
    "  --mode execute-live \\\n"
    "  --ack CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_20260619 \\\n"
    "  --positions ETH-USDC,AVAX-USDC,SOL-USDC \\\n"
    "  --exclude ADA-USDC \\\n"
    "  --require-verified-base \\\n"
    "  --block-oversell \\\n"
    "  --block-duplicate-exit \\\n"
    "  --require-terminal-fill-before-state-write \\\n"
    "  --i-understand-this-submits-live-sells \\\n"
    "  --json-out reports/live_runs/risk-incomplete-controlled-close-result.json"
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _seed_prep(root: Path, *, command_preview: object = COMMAND, ack_required: str = ACK) -> None:
    _write_json(
        root / "reports/audits/risk-incomplete-controlled-close-prep-latest.json",
        {
            "status": "controlled_close_command_preview_ready",
            "ack_required": ack_required,
            "command_preview": command_preview,
            "will_not_run_now": True,
            "will_write_state_only_after_terminal_fill": True,
            "positions_to_close": ["ETH-USDC", "AVAX-USDC", "SOL-USDC"],
            "positions_to_review": ["ADA-USDC"],
            "positions_excluded_from_close": ["ADA-USDC"],
            "ada_action": "manual_hold_review_or_risk_completion_after_ack",
            "positions": [
                {
                    "ticker": "ETH-USDC",
                    "base_balance_verified": True,
                    "local_base": "0.01419647",
                    "available_base": "0.0141964735707866",
                    "below_reconstructed_stop": True,
                },
                {
                    "ticker": "AVAX-USDC",
                    "base_balance_verified": True,
                    "local_base": "3.67647058",
                    "available_base": "3.67647058",
                    "below_reconstructed_stop": True,
                },
                {
                    "ticker": "SOL-USDC",
                    "base_balance_verified": True,
                    "local_base": "0.3485292",
                    "available_base": "0.3485292",
                    "below_reconstructed_stop": True,
                },
                {
                    "ticker": "ADA-USDC",
                    "base_balance_verified": True,
                    "local_base": "121.58054711",
                    "available_base": "121.58054711",
                    "below_reconstructed_stop": False,
                },
            ],
        },
    )
    _write_json(
        root / "reports/audits/position-risk-reconstruction-preview-latest.json",
        {"runtime": {"service_active": False, "run_trader_loop_process_found": False, "stale_lock_likely": True}},
    )
    _write_json(root / "state/open_orders.json", {"orders": {}})


def test_controlled_close_validator_requires_exact_ack(tmp_path: Path) -> None:
    _seed_prep(tmp_path)

    missing = build_validation_report(root=tmp_path, ack="")
    exact = build_validation_report(root=tmp_path, ack=ACK)

    assert missing["ack_matches_required"] is False
    assert "exact_ack_required" in missing["execution_gate"]["blockers"]
    assert missing["safe_to_execute_now"] is False
    assert exact["ack_matches_required"] is True
    assert exact["safe_to_execute_after_exact_ack"] is True
    assert exact["command_preview_present"] is True
    assert exact["command_preview"] == COMMAND


def test_controlled_close_validator_never_submits_and_confirms_no_oversell(tmp_path: Path) -> None:
    _seed_prep(tmp_path)

    report = build_validation_report(root=tmp_path, ack=ACK)

    assert report["will_not_run_now"] is True
    assert report["coinbase_call_attempted"] is False
    assert report["live_submit_attempted"] is False
    assert report["live_order_submitted"] is False
    assert report["state_write_performed"] is False
    assert report["base_balances_verified"] is True
    assert report["oversell_blocked"] is True
    assert report["service_active"] is False
    assert report["stale_lock_not_removed"] is True
    assert all(row["would_oversell"] is False for row in report["base_checks"])


def test_controlled_close_validator_excludes_ada_and_blocks_duplicates(tmp_path: Path) -> None:
    _seed_prep(tmp_path)
    _write_json(
        tmp_path / "state/open_orders.json",
        {
            "orders": {
                "existing-sell": {
                    "ticker": "ETH-USDC",
                    "side": "SELL",
                    "status": "submitted",
                    "exchange_order_id": "cb-existing-exit",
                    "size_base": "0.01419647",
                }
            }
        },
    )

    report = build_validation_report(root=tmp_path, ack=ACK)

    assert report["positions_to_close"] == ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
    assert report["positions_to_review"] == ["ADA-USDC"]
    assert report["positions_excluded_from_close"] == ["ADA-USDC"]
    assert report["ada_excluded_from_close_batch"] is True
    assert report["duplicate_exit_blocked"] is False
    assert "duplicate_open_exit_detected" in report["blockers"]


def test_state_write_only_after_terminal_fill_remains_required(tmp_path: Path) -> None:
    _seed_prep(tmp_path)

    report = build_validation_report(root=tmp_path, ack=ACK)

    assert report["state_write_only_after_terminal_fill"] is True
    assert report["execution_gate"]["terminal_fill_evidence_valid"] is False
    assert report["execution_gate"]["state_apply_allowed"] is False
    assert report["state_write_performed"] is False


def test_validator_fails_if_command_preview_is_null(tmp_path: Path) -> None:
    _seed_prep(tmp_path, command_preview=None)

    report = build_validation_report(root=tmp_path, ack=ACK)

    assert report["safe_to_execute_after_exact_ack"] is False
    assert report["command_preview_present"] is False
    assert report["command_preview"] is None
    assert report["blocker"] == "missing_command_preview"
    assert "missing_command_preview" in report["blockers"]


def test_validator_passes_only_with_exact_command_preview(tmp_path: Path) -> None:
    _seed_prep(tmp_path)
    exact = build_validation_report(root=tmp_path, ack=ACK)
    _seed_prep(tmp_path, command_preview=COMMAND.replace(ACK, OLD_ACK), ack_required=ACK)
    old_ack_command = build_validation_report(root=tmp_path, ack=ACK)

    assert exact["safe_to_execute_after_exact_ack"] is True
    assert exact["command_validation"]["exact"] is True
    assert old_ack_command["safe_to_execute_after_exact_ack"] is False
    assert "command_preview_ack_mismatch" in old_ack_command["blockers"]


def test_validator_requires_exact_ack_shape(tmp_path: Path) -> None:
    _seed_prep(tmp_path, ack_required=OLD_ACK)

    report = build_validation_report(root=tmp_path, ack=OLD_ACK)

    assert report["safe_to_execute_after_exact_ack"] is False
    assert report["ack_required"] == OLD_ACK
    assert "ack_required_mismatch" in report["blockers"]


def test_validator_command_contains_required_safety_flags_and_output_path(tmp_path: Path) -> None:
    _seed_prep(tmp_path)

    report = build_validation_report(root=tmp_path, ack=ACK)

    assert report["command_validation"]["positions"] == ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
    assert report["command_validation"]["mode"] == "execute-live"
    assert report["command_validation"]["excluded"] == ["ADA-USDC"]
    assert report["command_validation"]["required_flags_present"] is True
    assert report["command_validation"]["json_out"] == "reports/live_runs/risk-incomplete-controlled-close-result.json"
    assert "--require-terminal-fill-before-state-write" in report["command_preview"]
    assert "--mode execute-live" in report["command_preview"]
    assert "--i-understand-this-submits-live-sells" in report["command_preview"]
    assert "--block-oversell" in report["command_preview"]
    assert "--block-duplicate-exit" in report["command_preview"]


def test_ack_gated_execute_target_dry_run_has_no_live_or_state_side_effects() -> None:
    report = build_execution_preview_report(
        ack=ACK,
        positions=["ETH-USDC", "AVAX-USDC", "SOL-USDC"],
        exclude=["ADA-USDC"],
        require_verified_base=True,
        block_oversell=True,
        block_duplicate_exit=True,
        require_terminal_fill_before_state_write=True,
        json_out="reports/live_runs/risk-incomplete-controlled-close-result.json",
        now=datetime(2026, 6, 19, tzinfo=timezone.utc),
    )

    assert report["status"] == "ack_gated_preview_ready"
    assert report["ack_matches_required"] is True
    assert report["positions_to_close"] == ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
    assert report["positions_excluded_from_close"] == ["ADA-USDC"]
    assert report["live_submit_attempted"] is False
    assert report["live_order_submitted"] is False
    assert report["state_write_performed"] is False


def test_write_validation_report_writes_only_report_files(tmp_path: Path) -> None:
    _seed_prep(tmp_path)
    state_path = tmp_path / "state/open_orders.json"
    before = state_path.read_text(encoding="utf-8")

    report = build_validation_report(root=tmp_path, ack=ACK)
    write_validation_report(report, root=tmp_path)

    assert state_path.read_text(encoding="utf-8") == before
    assert (tmp_path / "reports/audits/final-controlled-close-preexecution-validation-latest.json").exists()
    assert (tmp_path / "reports/audits/final-controlled-close-preexecution-validation-latest.md").exists()
