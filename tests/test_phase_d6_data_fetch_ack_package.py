from __future__ import annotations

from bot.phase_d6_remaining_work_planner import DATA_FETCH_ACK, build_data_fetch_ack_package


def test_data_fetch_ack_package_is_ack_gated_and_does_not_fetch():
    report = build_data_fetch_ack_package(
        dataset_plan={
            "content": {
                "rows": [
                    {
                        "ticker": "ETH-USDC",
                        "timeframe": "1H",
                        "missing_data_blocker": True,
                        "future_fetch_command": {"dry_run": "dry", "fetch_after_ack": "fetch"},
                    }
                ]
            }
        }
    )
    assert report["required_ack"] == DATA_FETCH_ACK
    assert report["rows"][0]["dry_run_command"] == "dry"
    assert report["rows"][0]["fetch_command_after_ack"] == "fetch"
    assert report["rows"][0]["state_write_performed"] is False
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
