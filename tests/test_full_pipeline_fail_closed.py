from __future__ import annotations

from bot.controlled_stop_market_exit_executor import prepare_controlled_close_execution


ACK = "CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_20260619"
POSITIONS = ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]


def test_controlled_close_missing_ack_never_submits() -> None:
    report = prepare_controlled_close_execution(
        ack="",
        required_ack=ACK,
        positions_to_close=POSITIONS,
        command_tickers=POSITIONS,
        mock_mode=True,
    )

    assert report["ack_matches_required"] is False
    assert report["would_submit_controlled_close"] is False
    assert report["live_order_submitted"] is False
    assert "exact_ack_required" in report["blockers"]


def test_controlled_close_exact_ack_in_mock_mode_would_submit_without_live_side_effect() -> None:
    report = prepare_controlled_close_execution(
        ack=ACK,
        required_ack=ACK,
        positions_to_close=POSITIONS,
        command_tickers=POSITIONS,
        mock_mode=True,
    )

    assert report["ack_matches_required"] is True
    assert report["would_submit_controlled_close"] is True
    assert report["live_submit_attempted"] is False
    assert report["live_order_submitted"] is False
    assert report["coinbase_call_attempted"] is False


def test_controlled_close_terminal_fill_missing_blocks_state_apply() -> None:
    report = prepare_controlled_close_execution(
        ack=ACK,
        required_ack=ACK,
        positions_to_close=POSITIONS,
        command_tickers=POSITIONS,
        mock_mode=True,
        terminal_fill_evidence={"normalized_status": "open", "filled_base": "0"},
    )

    assert report["terminal_fill_evidence_valid"] is False
    assert report["state_apply_allowed"] is False
    assert report["state_write_performed"] is False


def test_controlled_close_terminal_fill_present_allows_state_apply_gate_only() -> None:
    report = prepare_controlled_close_execution(
        ack=ACK,
        required_ack=ACK,
        positions_to_close=POSITIONS,
        command_tickers=POSITIONS,
        mock_mode=True,
        terminal_fill_evidence={"normalized_status": "filled", "filled_base": "1.0", "fill_count": 1},
    )

    assert report["terminal_fill_evidence_valid"] is True
    assert report["state_apply_allowed"] is True
    assert report["state_write_performed"] is False


def test_controlled_close_blocks_unapproved_ticker_in_command() -> None:
    report = prepare_controlled_close_execution(
        ack=ACK,
        required_ack=ACK,
        positions_to_close=POSITIONS,
        command_tickers=[*POSITIONS, "ADA-USDC"],
        mock_mode=True,
    )

    assert report["would_submit_controlled_close"] is False
    assert "command_contains_unapproved_tickers" in report["blockers"]
