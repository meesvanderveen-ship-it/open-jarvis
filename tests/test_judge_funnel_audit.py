from __future__ import annotations

import json
from pathlib import Path

from tools.build_judge_funnel_audit import build_judge_funnel_audit, main


def _append(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def test_judge_funnel_counts_and_recommendation(tmp_path: Path) -> None:
    _append(tmp_path / "logs/analysis.jsonl", {
        "generated_at": "2026-06-15T00:00:00Z",
        "ticker": "BTC-USDC",
        "entry_gate": {"decision": "analyze", "setup_type": "reclaim_reversal"},
        "feature_pack": {
            "market": {"spread_pct": 0.001},
            "decision_context": {
                "product_rules": {"product_id": "BTC-USDC", "price_increment": "0.01", "base_increment": "0.00000001", "quote_increment": "0.01"},
                "recent_exchange_rejections": [{"ticker": "BTC-USDC", "reject_reason": "INVALID_PRICE_PRECISION"}],
                "execution_feasibility": {"can_construct_valid_limit_buy_payload": True},
            },
        },
        "bull": {"bull_case_score": 58},
        "bear": {"bear_case_score": 45},
        "trade_plan": {"plan_action": "prepare_buy", "entry_zone_low": 99, "invalidation": "below 95"},
        "judge": {"expensive_judge_called": True, "decision": "approve_trade", "objective_score": 0.18, "setup_type": "reclaim_reversal"},
    })
    _append(tmp_path / "logs/analysis.jsonl", {
        "generated_at": "2026-06-15T00:01:00Z",
        "ticker": "ETH-USDC",
        "entry_gate": {"decision": "watch", "setup_type": "mean_reversion"},
        "feature_pack": {"market": {"spread_pct": 0.001}},
        "bull": {"bull_case_score": 50},
        "bear": {"bear_case_score": 62},
        "trade_plan": {"plan_action": "no_plan", "reason": "skipped"},
        "judge": {"expensive_judge_called": False, "decision": "wait", "judge_skip_reason": "bull_score_below_threshold"},
    })
    _append(tmp_path / "logs/execution.jsonl", {"ticker": "BTC-USDC", "executed": True})
    _append(tmp_path / "logs/phase_c_live_submit.jsonl", {
        "generated_at": "2026-06-15T00:02:00Z",
        "ticker": "BTC-USDC",
        "live_submission_attempted": True,
        "live_order_submitted": False,
        "submit_result": {
            "reject_reason": "INVALID_PRICE_PRECISION",
            "payload": {
                "precision_normalization": {"valid": True},
                "product_rules": {"precision_context_available": True},
            },
        },
    })
    report = build_judge_funnel_audit(root=tmp_path, since="2026-06-15T00:00:00Z")
    assert report["gate_counts"]["analyze"] == 1
    assert report["expensive_judge_called_count"] == 1
    assert report["expensive_judge_not_called_count"] == 1
    assert report["unique_tickers"] == 2
    assert report["decision_rows_total"] == 2
    assert report["entry_candidate_rows"] == 2
    assert report["planner_rows"] == 2
    assert report["final_judge_event_rows"] == 2
    assert report["final_judge_called"] == 1
    assert report["final_judge_not_called"] == 1
    assert report["judge_skip_reason_counts"]["bull_score_below_threshold"] == 1
    assert report["no_plan_count"] == 1
    assert report["no_plan"] == 1
    assert report["objective_score_extracted_count"] == 1
    assert report["objective_score_extracted"] == 1
    assert report["valid_trade_plan_count"] == 1
    assert report["valid_trade_plans"] == 1
    assert report["ratios"]["final_judge_reach_rate"] == 0.5
    assert report["ratios"]["valid_plan_rate"] == 0.5
    assert report["ratios"]["no_plan_drop_rate"] == 0.5
    assert report["ratio_denominators"]["final_judge_reach_rate"] == "final_judge_event_rows"
    assert report["ratio_denominators"]["valid_plan_rate"] == "planner_rows"
    assert report["ratio_denominators"]["no_plan_drop_rate"] == "planner_rows"
    assert report["precision_context_audit"]["planner_judge_rows_with_product_rules"] == 1
    assert report["precision_context_audit"]["planner_judge_rows_with_recent_exchange_rejections"] == 1
    assert report["precision_context_audit"]["precision_normalized_attempt_count"] == 1
    assert report["precision_context_audit"]["invalid_price_precision_reject_count"] == 1
    assert all(0 <= float(v) <= 1 for v in report["ratios"].values())
    assert report["recommendation"] in {"insufficient_evidence", "judge_too_strict", "planner_handoff_too_strict", "market_weak_correct_wait", "valid_wait_objective_below_threshold"}
    json_out = tmp_path / "reports/audits/judge.json"
    md_out = tmp_path / "reports/audits/judge.md"
    assert main(["--root", str(tmp_path), "--json-out", str(json_out), "--md-out", str(md_out)]) == 0
    assert json_out.exists()
    assert md_out.exists()


def test_judge_funnel_schema_failures_dominate_recommendation(tmp_path: Path) -> None:
    for idx, key in enumerate(("cost_penalty", "drawdown_risk", "execution_friction_penalty")):
        _append(tmp_path / "logs/analysis.jsonl", {
            "generated_at": f"2026-06-15T01:0{idx}:00Z",
            "ticker": f"BAD{idx}-USDC",
            "entry_gate": {"decision": "analyze"},
            "trade_plan": {"plan_action": "prepare_buy", "invalidation": "below support"},
            "judge": {
                "expensive_judge_called": True,
                "decision": "wait",
                "strategy": "judge_fallback_safe_wait",
                "reasons": [f"openai_gpt_5_5_failed: OpenAI json_response mislukt: missing_required_keys: ['{key}']", "anthropic_fallback_disabled"],
            },
        })

    report = build_judge_funnel_audit(root=tmp_path, since="2026-06-15T00:00:00Z")

    assert report["recommendation"] == "judge_schema_contract_failure"
    assert report["schema_failure_count"] == 3
    assert report["provider_fallback_count"] == 3
    assert report["missing_required_keys_count_by_key"]["cost_penalty"] == 1
    assert report["missing_required_keys_count_by_key"]["drawdown_risk"] == 1
    assert report["missing_required_keys_count_by_key"]["execution_friction_penalty"] == 1
    assert report["invalid_judge_response_count"] == 3


def test_valid_low_objective_wait_classification(tmp_path: Path) -> None:
    _append(tmp_path / "logs/analysis.jsonl", {
        "generated_at": "2026-06-15T02:00:00Z",
        "ticker": "LOW-USDC",
        "entry_gate": {"decision": "analyze"},
        "trade_plan": {"plan_action": "prepare_buy", "invalidation": "below support"},
        "judge": {
            "expensive_judge_called": True,
            "decision": "wait",
            "side": "NONE",
            "confidence": 60,
            "strategy": "final_judge",
            "setup_type": "reclaim_reversal",
            "objective_score": 0.05,
            "expected_edge_score": 0.25,
            "risk_penalty": 0.12,
            "cost_penalty": 0.03,
            "drawdown_risk": 0.04,
            "execution_friction_penalty": 0.01,
            "valid_trade_plan": True,
            "plan_type": "starter_probe",
            "judge_reasons": ["objective_score=0.05 below threshold"],
            "must_reject_if": ["below invalidation"],
        },
    })

    report = build_judge_funnel_audit(root=tmp_path, since="2026-06-15T00:00:00Z")

    assert report["recommendation"] == "valid_wait_objective_below_threshold"
    assert report["audit_classification_counts"]["valid_wait_objective_below_threshold"] == 1
    assert report["waits_with_objective_score_below_threshold"] == 1
    assert report["valid_judge_response_count"] == 1


def test_post_trigger_ev_wait_is_trigger_not_ready_not_judge_too_strict(tmp_path: Path) -> None:
    _append(tmp_path / "logs/analysis.jsonl", {
        "generated_at": "2026-06-15T03:00:00Z",
        "ticker": "SUI-USDC",
        "entry_gate": {"decision": "analyze"},
        "trade_plan": {"plan_action": "prepare_buy", "invalidation": "below reclaim"},
        "judge": {
            "expensive_judge_called": True,
            "decision": "wait",
            "side": "NONE",
            "confidence": 64,
            "strategy": "final_judge",
            "setup_type": "breakout",
            "objective_score": 0.05,
            "post_trigger_objective_score": 0.23,
            "expected_edge_score": 0.30,
            "risk_penalty": 0.14,
            "cost_penalty": 0.03,
            "drawdown_risk": 0.06,
            "execution_friction_penalty": 0.02,
            "valid_trade_plan": True,
            "plan_type": "breakout_trigger",
            "judge_reasons": ["trigger_not_ready; wait for 1h close"],
            "trigger_wait_reason": "trigger_not_ready: wait for 1h close above resistance",
            "must_reject_if": [],
        },
    })

    report = build_judge_funnel_audit(root=tmp_path, since="2026-06-15T00:00:00Z")

    assert report["recommendation"] == "market_wait_trigger_not_ready"
    assert report["audit_classification_counts"]["valid_wait_trigger_not_ready"] == 1
    assert report["post_trigger_objective_score_count"] == 1
    assert "judge_too_strict" not in report["audit_classification_counts"]


def test_valid_high_objective_wait_without_hard_reason_is_judge_too_strict(tmp_path: Path) -> None:
    _append(tmp_path / "logs/analysis.jsonl", {
        "generated_at": "2026-06-15T04:00:00Z",
        "ticker": "HIGH-USDC",
        "entry_gate": {"decision": "analyze"},
        "trade_plan": {"plan_action": "prepare_buy", "invalidation": "below support"},
        "judge": {
            "expensive_judge_called": True,
            "decision": "wait",
            "side": "NONE",
            "confidence": 72,
            "strategy": "final_judge",
            "setup_type": "trend_continuation",
            "objective_score": 0.19,
            "expected_edge_score": 0.45,
            "risk_penalty": 0.15,
            "cost_penalty": 0.03,
            "drawdown_risk": 0.06,
            "execution_friction_penalty": 0.02,
            "valid_trade_plan": True,
            "plan_type": "starter_probe",
            "judge_reasons": ["positive objective but wait"],
            "must_reject_if": ["below invalidation"],
        },
    })

    report = build_judge_funnel_audit(root=tmp_path, since="2026-06-15T00:00:00Z")

    assert report["recommendation"] == "judge_too_strict"
    assert report["audit_classification_counts"]["judge_too_strict"] == 1
    assert report["waits_with_objective_score_gte_approval_threshold_no_approve"] == 1


def test_since_accepts_uppercase_lowercase_z_and_utc_string(tmp_path: Path) -> None:
    for since in ("2026-06-15T13:35:00Z", "2026-06-15T13:35:00z", "2026-06-15 13:35:00 UTC"):
        root = tmp_path / since.replace(" ", "_").replace(":", "-")
        _append(root / "logs/analysis.jsonl", {
            "generated_at": "2026-06-15T13:35:01Z",
            "ticker": "BTC-USDC",
            "entry_gate": {"decision": "analyze"},
            "trade_plan": {"plan_action": "no_plan"},
            "judge": {"expensive_judge_called": False, "decision": "wait"},
        })
        report = build_judge_funnel_audit(root=root, since=since)
        assert report["audit_window_valid"] is True
        assert report["since_parsed_utc"] == "2026-06-15T13:35:00Z"
        assert report["decision_rows_total"] == 1


def test_since_excludes_missing_and_old_rows_without_historical_fallback(tmp_path: Path) -> None:
    _append(tmp_path / "logs/analysis.jsonl", {
        "generated_at": "2026-06-15T13:34:59Z",
        "ticker": "OLD-USDC",
        "trade_plan": {"plan_action": "prepare_buy"},
        "judge": {"expensive_judge_called": True, "decision": "approve_trade"},
    })
    _append(tmp_path / "logs/analysis.jsonl", {
        "ticker": "MISSING-USDC",
        "trade_plan": {"plan_action": "prepare_buy"},
        "judge": {"expensive_judge_called": True, "decision": "approve_trade"},
    })
    _append(tmp_path / "logs/analysis.jsonl", {
        "generated_at": "2026-06-15T13:35:01+00:00",
        "ticker": "NEW-USDC",
        "trade_plan": {"plan_action": "no_plan"},
        "judge": {"expensive_judge_called": False, "decision": "wait"},
    })
    report = build_judge_funnel_audit(root=tmp_path, since="2026-06-15T13:35:00Z")
    assert report["decision_rows_total"] == 1
    assert report["unique_tickers"] == 1
    assert report["rows_excluded_before_since"] == 1
    assert report["rows_without_timestamp_excluded"] == 1


def test_no_rows_after_since_returns_insufficient_new_data(tmp_path: Path) -> None:
    _append(tmp_path / "logs/analysis.jsonl", {
        "generated_at": "2026-06-15T13:34:59Z",
        "ticker": "OLD-USDC",
        "trade_plan": {"plan_action": "prepare_buy"},
        "judge": {"expensive_judge_called": True, "decision": "approve_trade"},
    })
    report = build_judge_funnel_audit(root=tmp_path, since="2026-06-15T13:35:00Z")
    assert report["decision_rows_total"] == 0
    assert report["recommendation"] in {"insufficient_new_data", "no_recent_full_cycle"}
    assert report["rows"] == 0
    assert report["stdout_valid"] is True
    assert report["data_sources_checked"]
    assert report["reason"] in {"no_full_cycle_since_since_time", "no_decision_rows_in_checked_sources"}


def test_relative_since_24_hours_ago_is_valid_window(tmp_path: Path) -> None:
    report = build_judge_funnel_audit(root=tmp_path, since="24 hours ago")
    assert report["audit_window_valid"] is True
    assert report["since_parsed_utc"].endswith("Z")
    assert report["stdout_valid"] is True


def test_impossible_execution_ratio_is_clipped_and_warned(tmp_path: Path) -> None:
    _append(tmp_path / "logs/analysis.jsonl", {
        "generated_at": "2026-06-15T13:35:01Z",
        "ticker": "BTC-USDC",
        "trade_plan": {"plan_action": "prepare_buy"},
        "judge": {"expensive_judge_called": True, "decision": "approve_trade"},
    })
    _append(tmp_path / "logs/execution.jsonl", {"generated_at": "2026-06-15T13:35:02Z", "executed": True})
    _append(tmp_path / "logs/execution.jsonl", {"generated_at": "2026-06-15T13:35:03Z", "executed": True})
    report = build_judge_funnel_audit(root=tmp_path, since="2026-06-15T13:35:00Z")
    assert report["ratios"]["execution_rate_after_approve"] == 1.0
    assert any("execution_rate_after_approve_clipped" in warning for warning in report["audit_invariant_warnings"])
