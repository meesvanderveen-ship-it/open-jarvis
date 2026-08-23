from __future__ import annotations

import pytest

from bot.llm_clients import (
    FINAL_JUDGE_OPTIONAL_ORDERBOOK_ENTRY_KEYS,
    FINAL_JUDGE_REQUIRED_KEYS,
    LLMOutputCorruptError,
    _ensure_only_allowed_keys,
    normalize_final_judge_schema_aliases,
)


def _valid_payload() -> dict:
    return {
        "decision": "wait",
        "side": "NONE",
        "confidence": 52,
        "strategy": "final_judge",
        "setup_type": "trend_continuation",
        "objective_score": 0.11,
        "expected_edge_score": 0.42,
        "risk_penalty": 0.18,
        "cost_penalty": 0.03,
        "drawdown_risk": 0.08,
        "execution_friction_penalty": 0.02,
        "valid_trade_plan": True,
        "plan_type": "starter_probe",
        "judge_reasons": ["objective_score=0.11"],
        "must_reject_if": ["trigger invalidated"],
    }


def test_final_judge_aliases_normalize_to_required_score_keys() -> None:
    payload = _valid_payload()
    for key in (
        "objective_score",
        "expected_edge_score",
        "risk_penalty",
        "cost_penalty",
        "drawdown_risk",
        "execution_friction_penalty",
        "judge_reasons",
    ):
        payload.pop(key)
    payload.update(
        {
            "objective": "0.10",
            "edge": "0.44",
            "risk": "0.20",
            "cost": "0.04",
            "drawdown": "0.07",
            "friction": "0.03",
            "reasons": ["objective_score=0.10"],
        }
    )

    normalized, aliases = normalize_final_judge_schema_aliases(payload)

    assert normalized["objective_score"] == 0.10
    assert normalized["expected_edge_score"] == 0.44
    assert normalized["risk_penalty"] == 0.20
    assert normalized["cost_penalty"] == 0.04
    assert normalized["drawdown_risk"] == 0.07
    assert normalized["execution_friction_penalty"] == 0.03
    assert normalized["judge_reasons"] == ["objective_score=0.10"]
    assert set(aliases) >= {"objective", "edge", "risk", "cost", "drawdown", "friction", "reasons"}
    _ensure_only_allowed_keys(
        normalized,
        allowed_keys=FINAL_JUDGE_REQUIRED_KEYS,
        require_all=True,
        required_keys=FINAL_JUDGE_REQUIRED_KEYS,
    )


def test_incomplete_final_judge_response_stays_invalid_and_cannot_approve() -> None:
    payload = _valid_payload()
    payload.pop("decision")
    payload.pop("valid_trade_plan")
    normalized, _aliases = normalize_final_judge_schema_aliases(payload)

    with pytest.raises(LLMOutputCorruptError) as exc:
        _ensure_only_allowed_keys(
            normalized,
            allowed_keys=FINAL_JUDGE_REQUIRED_KEYS,
            require_all=True,
            required_keys=FINAL_JUDGE_REQUIRED_KEYS,
        )

    assert "decision" in str(exc.value)
    assert "valid_trade_plan" in str(exc.value)
    assert normalized.get("decision") != "approve_trade"


def test_optional_orderbook_entry_fields_are_allowed_but_not_required() -> None:
    payload = _valid_payload()
    payload.update(
        {
            "setup_quality_score": 70,
            "trigger_readiness": "not_ready",
            "orderbook_entry_candidate": True,
            "recommended_entry_type": "reclaim_retest_limit",
            "entry_zone_low": 99.5,
            "entry_zone_high": 100.0,
            "preferred_limit_price": 99.75,
            "invalidation_price": 98.0,
            "target_price_1": 104.0,
            "target_price_2": 106.0,
            "do_not_chase_above": 100.8,
            "cancel_if_price_below": 98.0,
            "cancel_if_price_above": 100.8,
            "setup_expiry_minutes": 60,
            "entry_reason": "retest level",
            "why_not_market_order": "avoid chasing",
            "why_resting_limit_is_or_is_not_valid": "valid only near retest",
        }
    )
    normalized, _aliases = normalize_final_judge_schema_aliases(payload)
    allowed = FINAL_JUDGE_REQUIRED_KEYS + FINAL_JUDGE_OPTIONAL_ORDERBOOK_ENTRY_KEYS
    out = _ensure_only_allowed_keys(normalized, allowed_keys=allowed, require_all=True, required_keys=FINAL_JUDGE_REQUIRED_KEYS)
    assert out["orderbook_entry_candidate"] is True
    assert out["preferred_limit_price"] == 99.75
