from __future__ import annotations

import json
from pathlib import Path

from tools.build_literature_backtest_parameter_matrix import build_matrix, main as matrix_main


def _write_inputs(root: Path) -> None:
    (root / "state").mkdir(parents=True)
    (root / "reports/backtests").mkdir(parents=True)
    (root / "reports/research").mkdir(parents=True)
    (root / "state/approved_parameter_profile.json").write_text(json.dumps({
        "profile_name": "active",
        "profile_version": 1,
        "parameters": {
            "DEFAULT_QUOTE_SIZE_USDC": "20.00",
            "MAX_NOTIONAL_USD": "20.00",
            "AUTONOMOUS_MAX_ORDER_QUOTE": "20.00",
            "PHASE_C_MAX_ORDER_QUOTE": "20.00",
            "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "20.00",
            "MAX_SPREAD_PCT": "0.0060",
            "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125",
            "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "3.0",
            "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.5",
            "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
        },
    }), encoding="utf-8")
    (root / "reports/backtests/approved-profile-candidate-from-backtest.json").write_text(json.dumps({
        "candidate_is_static_research_prior": True,
        "candidate_not_metric_optimized": True,
        "approved_profile_json": {
            "profile_name": "research_prior_backtest_available_candidate",
            "profile_version": 1,
            "parameters": {
                "DEFAULT_QUOTE_SIZE_USDC": "20.00",
                "MAX_NOTIONAL_USD": "100.00",
                "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
                "PHASE_C_MAX_ORDER_QUOTE": "100.00",
                "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "100.00",
                "MAX_SPREAD_PCT": "0.0060",
                "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0100",
                "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "2.5",
                "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.50",
                "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
            },
        },
    }), encoding="utf-8")
    (root / "reports/backtests/btc-eth-parameter-backtest-latest.json").write_text(json.dumps({
        "label_counts": {
            "good_wait": 34661,
            "missed_opportunity": 3471,
            "correct_avoid": 4162,
            "good_entry_candidate": 581,
            "bad_entry_candidate": 2315,
        },
        "candidate": {
            "sample_size": 45662,
            "confidence": "medium",
            "overfit_risk": "medium",
            "recommended_parameter_band": {
                "MAX_LIVE_ORDER_QUOTE_USDC": [50, 100],
                "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": [0.009, 0.0125],
            },
        },
    }), encoding="utf-8")
    (root / "reports/research/research-prior-parameter-profile-latest.json").write_text(json.dumps({
        "order_sizing": {"max_live_order_quote_usdc": 100.0}
    }), encoding="utf-8")


def test_matrix_activates_sizing_only_and_keeps_d2_conservative(tmp_path: Path) -> None:
    _write_inputs(tmp_path)
    report = build_matrix(
        active_path=tmp_path / "state/approved_parameter_profile.json",
        candidate_path=tmp_path / "reports/backtests/approved-profile-candidate-from-backtest.json",
        backtest_path=tmp_path / "reports/backtests/btc-eth-parameter-backtest-latest.json",
        research_path=tmp_path / "reports/research/research-prior-parameter-profile-latest.json",
        generated_at="2026-06-14T00:00:00Z",
    )

    assert report["read_only"] is True
    assert report["backtest_context"]["bad_entry_gt_good_entry"] is True
    assert report["matrix"]["MAX_NOTIONAL_USD"]["recommendation"] == "activate_sizing_only"
    assert report["matrix"]["MAX_NOTIONAL_USD"]["safe_to_activate_now"] is True
    assert report["matrix"]["PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"]["recommendation"] == "do_not_activate_yet"
    assert report["matrix"]["PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"]["safe_to_activate_now"] is False


def test_matrix_tool_writes_reports(tmp_path: Path, monkeypatch) -> None:
    _write_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert matrix_main([]) == 0

    payload = json.loads((tmp_path / "reports/research/literature-backtest-parameter-matrix-latest.json").read_text())
    assert payload["coinbase_call_attempted"] is False
    assert (tmp_path / "reports/research/literature-backtest-parameter-matrix-latest.md").exists()
