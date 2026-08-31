from pathlib import Path

from bot.phase_live_operator_runbook_pack import (
    build_monitoring_commands,
    build_operator_started_24h_live_test_pack,
    build_operator_sequence,
    build_post_run_commands,
    build_preflight_commands,
    build_route_scores,
)


def test_operator_pack_preserves_hard_safety_flags() -> None:
    report = build_operator_started_24h_live_test_pack(
        generated_at="2026-06-08T00:00:00Z",
        initial_safety={"status": "pass"},
        state_hashes={"state/open_orders.json": "abc"},
    )

    assert report["status"] == "operator_started_24h_live_test_pack_ready"
    assert report["chosen_route"] == "Route D - Combined operator-start pack"
    assert report["scope"]["recommended_live_scope"] == ["BTC-USDC"]
    assert report["scope"]["operator_starts_live_run"] is True
    assert report["scope"]["codex_starts_live_run"] is False
    assert report["hard_boundaries"]["no_coinbase_call_in_pack_build"] is True
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["parameter_change_allowed"] is False
    assert report["blockers"] == []
    assert "all_ticker_live_scope_not_proven" in report["live_start_blockers"]


def test_route_d_is_chosen_and_runtime_mutation_route_rejected() -> None:
    routes = {row["name"]: row for row in build_route_scores()}

    assert routes["Route D - Combined operator-start pack"]["verdict"] == "chosen"
    assert routes["Route D - Combined operator-start pack"]["state_impact"] == "docs_and_reports_only"
    assert routes["Route E - Config/start-script mutation alternative"]["verdict"] == "rejected_for_this_task"
    assert routes["Route E - Config/start-script mutation alternative"]["risk"] > routes["Route D - Combined operator-start pack"]["risk"]


def test_command_sets_include_required_local_checks_without_coinbase_submit() -> None:
    preflight = build_preflight_commands()
    monitoring = build_monitoring_commands()
    post_run = build_post_run_commands()
    all_commands = "\n".join(row["command"] for row in [*preflight, *monitoring, *post_run])

    assert "tools/show_open_orders.py --open-only --json" in all_commands
    assert "tools/show_function_preservation_audit.py --fail-on-review" in all_commands
    assert "tools/show_phase_d3_controlled_live_exits.py --ticker BTC-USDC --json" in all_commands
    assert "run_trader_loop.py --startup-diagnostic" in all_commands
    assert "tools/show_btc_usdc_24h_live_monitor.py --json --since-utc <OPERATOR_START_UTC>" in all_commands
    assert "tools/build_btc_usdc_24h_post_run_evidence_pack.py --start-utc <OPERATOR_START_UTC> --stop-utc <OPERATOR_STOP_UTC>" in all_commands
    assert "tools/build_c4_d1_handoff_branch_map.py" in all_commands
    assert "sha256sum state/open_orders.json state/positions.json" in all_commands
    assert "run_trader_loop.py\n" not in all_commands
    assert "tools/operator_btc_usdc_tiny_env.sh python3 run_trader_loop.py" not in all_commands
    assert "--submit-live" not in all_commands
    assert "cancel" not in " ".join(row["purpose"].lower() for row in preflight)


def test_pack_explains_operator_start_without_authorizing_it() -> None:
    report = build_operator_started_24h_live_test_pack(generated_at="2026-06-08T00:00:00Z")
    start = report["start_instructions"]

    # Was: een vast serverpad (/root/apps/Crypto/coinbase_bot). Een operator op
    # Windows kreeg daardoor een werkmap te zien die op zijn pc niet bestaat.
    # De runbook hoort de map te noemen waar dit project echt staat.
    assert start["working_directory"] == str(Path(__file__).resolve().parents[1])
    assert "/root/apps" not in start["working_directory"]
    assert ".venv/bin/python run_trader_loop.py" in start["repo_direct_start_if_no_bash_exists"]
    assert "tools/operator_btc_usdc_tiny_env.sh python3 run_trader_loop.py" not in start["repo_direct_start_if_no_bash_exists"]
    assert "run_trader_loop.py --startup-diagnostic" in start["startup_diagnostic"]
    assert ".venv/bin/python run_trader_loop.py --startup-diagnostic" in start["startup_diagnostic"]
    assert report["contains_live_instructions"] is False
    assert report["live_recommendation"] is False
    assert "submit_live_order" in report["required_future_acks"]
    assert "fill_to_position_apply" in report["required_future_acks"]
    assert report["post_run_evidence_collection"]["c4_d1_branch_map_note"].startswith("D2/D3 preview is not live exit permission")


def test_operator_sequence_matches_runbook_order_and_ack_boundaries() -> None:
    sequence = build_operator_sequence()
    report = build_operator_started_24h_live_test_pack(generated_at="2026-06-08T00:00:00Z")
    titles = [row["title"] for row in sequence]

    assert [row["step"] for row in sequence] == list("ABCDEFGHIJ")
    assert titles == [
        "Confirm service/process scope",
        "Fresh BTC-USDC tiny preflight",
        "Startup diagnostic",
        "Baseline state hashes",
        "Exact operator ACK live-start command",
        "During-run monitor command",
        "Stop rules",
        "Post-run evidence pack",
        "C4/D1 branch map selection",
        "No-apply/no-repair/no-exit boundaries",
    ]
    assert report["operator_sequence"] == sequence
    required_acks = report["required_future_acks"]
    assert required_acks["fill_to_position_apply"] == "I_UNDERSTAND_AND_APPROVE_C45_FILL_TO_POSITION_APPLY"
    assert "live_d3_exit_submit" in required_acks
    assert "local_repair" in required_acks


def test_generated_pack_has_no_stale_tiny_run_instructions() -> None:
    report = build_operator_started_24h_live_test_pack(generated_at="2026-06-08T00:00:00Z")
    text = repr(report)

    assert "tools/operator_btc_usdc_tiny_env.sh python3 run_trader_loop.py" not in text
    assert "D2/D3 preview is not live exit permission" in text
    assert "enable_live_exit_orders=true" not in text.lower()
    assert "enable_phase_d3_actual_exit_submit=true" not in text.lower()
