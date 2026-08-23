from __future__ import annotations

import json

from tools.summarize_backtest_parameter_candidates import build_backtest_parameter_candidate, main as summarize_main


def test_backtest_candidate_requires_operator_review_and_hash_ack():
    payload = build_backtest_parameter_candidate({
        "candidate": {
            "sample_size": 120,
            "confidence": "low",
            "overfit_risk": "high",
            "recommended_parameter_band": {"MAX_LIVE_ORDER_QUOTE_USDC": [50, 100]},
        }
    })
    assert payload["safe_to_live_activate_now"] is False
    assert payload["requires_operator_review"] is True
    assert payload["requires_exact_hash_ack"] is True
    assert payload["approved_parameter_profile_written"] is False
    assert payload["hash_to_approve"]
    assert payload["candidate_is_static_research_prior"] is True
    assert payload["candidate_not_metric_optimized"] is True
    assert payload["candidate_classification"] == "research_prior_backtest_available_candidate"
    assert payload["metric_dependency"]["label_counts_used_for_parameters"] is False


def test_backtest_candidate_tool_writes_report_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "reports/backtests/btc-eth-parameter-backtest-latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"candidate": {"sample_size": 0, "recommended_parameter_band": {}}}), encoding="utf-8")
    rc = summarize_main([])
    assert rc == 0
    payload = json.loads((tmp_path / "reports/backtests/approved-profile-candidate-from-backtest.json").read_text())
    assert payload["safe_to_live_activate_now"] is False
    assert payload["requires_operator_review"] is True
    assert payload["state_write_performed"] is False
