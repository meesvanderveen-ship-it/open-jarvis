from dashboard.backend.services import proposals as proposals_service


def test_merges_approved_profile_with_learning_diagnostics(monkeypatch):
    monkeypatch.setattr(
        proposals_service,
        "get_live_status",
        lambda: {
            "approved_profile_status": {
                "parameters": {
                    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.01227188",
                    "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
                }
            }
        },
    )
    monkeypatch.setattr(
        proposals_service,
        "get_learning_status",
        lambda: {
            "generated_at": "2026-06-23T00:00:00Z",
            "proposal_count": 1,
            "blocked_proposal_count": 0,
            "product_readiness": {"report_only_ready": True},
            "product_readiness_blockers": [],
            "next_operator_action": "review",
            "per_parameter_diagnostics": [
                {
                    "parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
                    "confidence": 0.9,
                    "evidence_count": 200,
                    "direction": "loosen",
                    "dominant_regime": "high_volatility",
                    "regime_effect_direction": {"high_volatility": "loosen"},
                    "expected_reward": -0.1,
                    "good_trade_probability": 0.2,
                    "bad_trade_probability": 0.8,
                    "missed_opportunity_probability": 0.5,
                    "safe_to_activate_now": False,
                }
            ],
            "top_proposals": [
                {
                    "parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
                    "current_value": 0.01227188,
                    "candidate_value": 0.01204787,
                    "direction": "loosen",
                    "reason": "net_edge_below_current_minimum",
                    "confidence": 0.9002,
                    "evidence_count": 209,
                    "regimes": ["high_volatility", "trend_up", "{'regime_label':_'mixed'}"],
                    "blockers": [],
                    "safe_to_activate_now": False,
                    "requires_operator_review": True,
                    "rollback": ["retain_previous_approved_profile_hash"],
                    "activation_route": "current_governor_and_approved_profile",
                }
            ],
        },
    )

    result = proposals_service.get_parameter_proposals()
    by_name = {p["parameter"]: p for p in result["proposals"]}

    edge = by_name["PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"]
    assert edge["current_value"] == "0.01227188"
    assert edge["proposed_value"] == 0.01204787
    assert edge["direction"] == "loosen"
    assert edge["category"] == "D2 planner / exit economics"
    assert edge["safety_status"] == "needs_more_evidence"
    assert "{'regime_label':_'mixed'}" not in edge["regimes_seen"]

    static_only = by_name["AUTONOMOUS_MAX_OPEN_ORDERS"]
    assert static_only["safety_status"] == "no_active_proposal"
    assert static_only["source"] == "approved_profile"
    assert static_only["operator_ack_needed"] is False


def test_blockers_force_blocked_status(monkeypatch):
    monkeypatch.setattr(proposals_service, "get_live_status", lambda: {"approved_profile_status": {"parameters": {}}})
    monkeypatch.setattr(
        proposals_service,
        "get_learning_status",
        lambda: {
            "per_parameter_diagnostics": [{"parameter": "MAX_SPREAD_PCT", "confidence": 0.5}],
            "top_proposals": [
                {
                    "parameter": "MAX_SPREAD_PCT",
                    "blockers": ["cooldown_active"],
                    "safe_to_activate_now": False,
                }
            ],
        },
    )

    result = proposals_service.get_parameter_proposals()
    row = next(p for p in result["proposals"] if p["parameter"] == "MAX_SPREAD_PCT")
    assert row["safety_status"] == "blocked"
    assert row["apply_status"] == "blocked"
