from __future__ import annotations

from pathlib import Path

from tools.build_multi_agent_prompt_audit import (
    PROJECT_ROOT,
    build_audit,
    render_markdown,
)

EXPECTED_LAYER_NAMES = {
    "cheap_prefilter",
    "hard_risk_gate",
    "deepseek_gate",
    "entry_gate",
    "analyst_modules",
    "trade_planner",
    "final_judge",
    "position_watch",
    "d2_planner",
    "c43_entry",
    "d3_exit",
    "lifecycle_service_hook",
    "reflection_outcome_layer",
    "growbot_river_learning",
}

EXPECTED_PROMPT_NAMES = {
    "GPT_NANO_GATE_PROMPT",
    "GPT_NANO_POSITION_WATCH_PROMPT",
    "DEEPSEEK_PREPROCESS_PROMPT",
    "REGIME_PROMPT",
    "TREND_PROMPT",
    "BREAKOUT_PROMPT",
    "MEANREV_PROMPT",
    "BULL_PROMPT",
    "BEAR_PROMPT",
    "SYNTH_PROMPT",
    "TRADE_PLANNER_PROMPT",
    "CLAUDE_JUDGE_PROMPT",
}


def test_build_audit_covers_every_requested_layer():
    report = build_audit(root=PROJECT_ROOT)
    names = {layer["name"] for layer in report["layers"]}
    assert EXPECTED_LAYER_NAMES.issubset(names)


def test_build_audit_is_read_only_self_reported():
    report = build_audit(root=PROJECT_ROOT)
    assert report["read_only"] is True
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["service_restart_attempted"] is False
    assert report["env_write_performed"] is False


def test_prompt_inventory_finds_all_prompts_py_templates():
    report = build_audit(root=PROJECT_ROOT)
    names = {p["name"] for p in report["prompt_inventory"]["prompts"]}
    assert names == EXPECTED_PROMPT_NAMES
    for p in report["prompt_inventory"]["prompts"]:
        assert p["length_chars"] > 0


def test_no_secrets_found_in_real_prompts_py():
    report = build_audit(root=PROJECT_ROOT)
    inv = report["prompt_inventory"]
    assert inv["secret_like_strings_found_in_prompts_py"] == []
    assert inv["suspicious_api_key_usage_in_payload_modules"] == {}
    assert inv["secrets_in_prompts_conclusion"] == "clean_no_secrets_found"


def test_audit_detects_injected_secret_like_string(tmp_path):
    bot_dir = tmp_path / "bot"
    bot_dir.mkdir()
    (bot_dir / "prompts.py").write_text(
        'LEAKED_PROMPT = "use this key sk-ant-abcdefghijklmnopqrstuvwxyz1234567890"\n',
        encoding="utf-8",
    )
    (bot_dir / "strategy_engine.py").write_text("# no api_key usage here\n", encoding="utf-8")
    (bot_dir / "execution_planner.py").write_text("# none\n", encoding="utf-8")
    (bot_dir / "trade_planner.py").write_text("# none\n", encoding="utf-8")

    report = build_audit(root=tmp_path)
    assert report["prompt_inventory"]["secret_like_strings_found_in_prompts_py"]
    assert report["prompt_inventory"]["secrets_in_prompts_conclusion"] == "REVIEW_NEEDED_see_suspicious_api_key_usage_and_secret_like_strings_fields"


def test_audit_flags_raw_api_key_usage_outside_client_constructor(tmp_path):
    bot_dir = tmp_path / "bot"
    bot_dir.mkdir()
    (bot_dir / "prompts.py").write_text('SAFE_PROMPT = "hello"\n', encoding="utf-8")
    (bot_dir / "strategy_engine.py").write_text(
        'dossier = {"api_key": cfg.openai_api_key}\n', encoding="utf-8"
    )

    report = build_audit(root=tmp_path)
    suspicious = report["prompt_inventory"]["suspicious_api_key_usage_in_payload_modules"]
    assert "bot/strategy_engine.py" in suspicious


def test_workflow_efficiency_section_present():
    report = build_audit(root=PROJECT_ROOT)
    efficiency = report["workflow_efficiency"]
    assert efficiency["final_judge_only_called_for_real_candidate"]["answer"] is True
    assert efficiency["are_prompts_cached"]["answer"] is False
    assert efficiency["dashboard_fully_read_only_no_own_llm_calls"]["answer"] is True


def test_render_markdown_includes_conclusion():
    report = build_audit(root=PROJECT_ROOT)
    md = render_markdown(report)
    assert "# Multi-Agent Pipeline + Prompt Audit" in md
    assert "multi_agent_system_correctness" in md
