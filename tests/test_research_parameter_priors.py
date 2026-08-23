from __future__ import annotations

import json

from bot.research_parameter_priors import build_research_prior_parameter_profile
from tools.build_research_prior_parameter_profile import main as build_research_main


def test_research_prior_profile_is_not_live_activatable():
    profile = build_research_prior_parameter_profile(generated_at="2026-06-14T00:00:00Z")
    assert profile["safe_to_live_activate_now"] is False
    assert profile["requires_backtest"] is True
    assert profile["requires_operator_review"] is True
    assert profile["order_sizing"]["min_live_order_quote_usdc"] == 20.00
    assert profile["order_sizing"]["max_live_order_quote_usdc"] == 100.00
    assert profile["bounded_exploration"]["enabled_by_default"] is False


def test_research_prior_tool_writes_reports_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = build_research_main([])
    assert rc == 0
    payload = json.loads((tmp_path / "reports/research/research-prior-parameter-profile-latest.json").read_text())
    assert payload["safe_to_live_activate_now"] is False
    assert payload["coinbase_call_attempted"] is False
    assert payload["state_write_performed"] is False
    assert (tmp_path / "reports/research/research-prior-parameter-profile-latest.md").exists()

