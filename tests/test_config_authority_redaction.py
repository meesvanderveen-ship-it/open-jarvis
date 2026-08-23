from __future__ import annotations

from bot.config import BotConfig
from bot.governance_constants import D3_CONTROLLED_LIVE_EXIT_ACK_VALUE


def test_config_summary_reports_d3_authority_without_exposing_ack(monkeypatch) -> None:
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("PHASE_D3_RUNTIME_SUBMIT_ACK", D3_CONTROLLED_LIVE_EXIT_ACK_VALUE)

    summary = BotConfig().to_dict()

    assert summary["phase_d3_runtime_submit_ack_present"] is True
    assert summary["phase_d3_runtime_submit_ack_valid"] is True
    assert "phase_d3_runtime_submit_ack" not in summary
