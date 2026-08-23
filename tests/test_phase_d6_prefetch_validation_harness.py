from bot.phase_d6_non_live_readiness_continuation import DATA_FETCH_ACK, validate_prefetch_plan


def test_prefetch_validation_requires_ack_and_never_fetches() -> None:
    fetch_plan = {
        "content": {
            "dry_run_command": ".venv/bin/python tools/fetch.py --max-chunks 2 --dry-run --json",
            "fetch_command_after_ack": ".venv/bin/python tools/fetch.py --max-chunks 2 --fetch --json",
            "required_ack": DATA_FETCH_ACK,
            "required_timeframes": ["1H", "4H", "1D"],
            "constraints": {"max_chunks_per_run": 2},
        }
    }
    dataset_plan = {
        "content": {
            "rows": [
                {"ticker": "BTC-USDC", "timeframe": "1H", "cached_data_present": False, "missing_data_blocker": True}
            ]
        }
    }

    report = validate_prefetch_plan(fetch_plan=fetch_plan, dataset_plan=dataset_plan)

    assert report["status"] == "prefetch_validation_pass"
    assert report["required_ack"] == DATA_FETCH_ACK
    assert report["fetch_executed"] is False
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert report["blockers"] == []
