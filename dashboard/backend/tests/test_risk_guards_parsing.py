from dashboard.backend.services import risk_guards


def _live(**overrides):
    base = {
        "stale_lock_detected": False,
        "pid_consistent": True,
        "service_restart_attempted": False,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "read_only": True,
        "run_health": "ok",
        "systemd_service_status": "active/running",
        "errors_by_type": {},
        "approved_profile_status": {"hash_valid": True, "loaded": True},
    }
    base.update(overrides)
    return base


def _pipeline(**overrides):
    base = {
        "read_only": True,
        "market_order_flags_enabled": [],
        "do_not_run_bot_yet": False,
        "safe_to_restart": True,
        "ack_required": "",
        "positions_risk_incomplete": [],
        "blockers": [],
        "operator_checklist": [],
        "pipeline_health": "green",
        "current_state": {"risk_incomplete_positions": [], "unrecognised_position_tickers": []},
    }
    base.update(overrides)
    return base


def test_risk_guards_flags_danger_when_market_orders_enabled(monkeypatch):
    monkeypatch.setattr(risk_guards, "get_live_status", lambda: _live())
    monkeypatch.setattr(
        risk_guards,
        "get_pipeline_health",
        lambda: _pipeline(
            market_order_flags_enabled=["MODE_C_MARKET_ORDER_ACK"],
            ack_required="request explicit service-start ACK",
            positions_risk_incomplete=["BTC-USDC"],
            blockers=["some_blocker"],
            operator_checklist=["check_x"],
            operator_action="review",
            pipeline_health="red",
        ),
    )

    result = risk_guards.get_risk_guards()

    by_label = {g["guard"]: g for g in result["guards"]}
    assert by_label["Market order flags enabled"]["status"] == "danger"
    assert by_label["PID consistent (systemd vs lock)"]["status"] == "safe"
    assert result["danger_count"] == 3
    assert result["blockers"] == ["some_blocker"]


def test_risk_guards_all_safe_when_clean(monkeypatch):
    monkeypatch.setattr(risk_guards, "get_live_status", lambda: _live())
    monkeypatch.setattr(risk_guards, "get_pipeline_health", lambda: _pipeline())

    result = risk_guards.get_risk_guards()

    assert result["danger_count"] == 0


# --- Regression coverage for the "Critical / runtime_mutation_lock_held"
# false-positive: a healthy, actively running bot legitimately holds its own
# runtime mutation lock and legitimately reports "not safe to restart" —
# neither should ever drive the dashboard's general health/danger signal. ---


def test_runtime_lock_held_by_running_service_is_informational_not_danger(monkeypatch):
    live = _live(systemd_service_status="active/running", pid_consistent=True)
    pipeline = _pipeline(
        pipeline_health="red",
        do_not_run_bot_yet=True,
        safe_to_restart=False,
        blockers=["runtime_mutation_lock_held"],
        current_state={
            "runtime_lock": {"held": True, "path": "state/runtime_mutation.lock", "verifiable": True},
            "risk_incomplete_positions": [],
            "unrecognised_position_tickers": [],
        },
    )
    monkeypatch.setattr(risk_guards, "get_live_status", lambda: live)
    monkeypatch.setattr(risk_guards, "get_pipeline_health", lambda: pipeline)

    result = risk_guards.get_risk_guards()

    assert result["runtime_lock_assessment"]["status"] == "held_by_running_service"
    assert result["runtime_lock_assessment"]["tone"] == "info"
    assert result["annotated_blockers"] == [
        {
            "blocker": "runtime_mutation_lock_held",
            "tone": "info",
            "detail": result["runtime_lock_assessment"]["detail"],
        }
    ]
    # The raw blocker must still be visible, not hidden.
    assert result["blockers"] == ["runtime_mutation_lock_held"]
    # This is the actual bug fix: operational health must stay safe even
    # though show_full_pipeline_health.py says "do not run bot yet" / red.
    assert result["operational_health"]["tone"] == "safe"
    by_label = {g["guard"]: g for g in result["guards"]}
    assert by_label["Runtime mutation lock (state/runtime_mutation.lock)"]["status"] == "info"


def test_runtime_lock_held_without_live_service_is_danger(monkeypatch):
    live = _live(systemd_service_status="inactive", pid_consistent=False)
    pipeline = _pipeline(
        blockers=["runtime_mutation_lock_held"],
        current_state={
            "runtime_lock": {"held": True, "path": "state/runtime_mutation.lock", "verifiable": True},
            "risk_incomplete_positions": [],
            "unrecognised_position_tickers": [],
        },
    )
    monkeypatch.setattr(risk_guards, "get_live_status", lambda: live)
    monkeypatch.setattr(risk_guards, "get_pipeline_health", lambda: pipeline)

    result = risk_guards.get_risk_guards()

    assert result["runtime_lock_assessment"]["status"] == "held_possibly_stale"
    assert result["runtime_lock_assessment"]["tone"] == "danger"
    assert result["annotated_blockers"][0]["tone"] == "danger"
    assert result["operational_health"]["tone"] == "danger"


def test_runtime_lock_not_held_is_safe(monkeypatch):
    live = _live()
    pipeline = _pipeline(
        current_state={
            "runtime_lock": {"held": False, "path": "state/runtime_mutation.lock", "verifiable": True},
            "risk_incomplete_positions": [],
            "unrecognised_position_tickers": [],
        }
    )
    monkeypatch.setattr(risk_guards, "get_live_status", lambda: live)
    monkeypatch.setattr(risk_guards, "get_pipeline_health", lambda: pipeline)

    result = risk_guards.get_risk_guards()

    assert result["runtime_lock_assessment"]["status"] == "not_held"
    assert result["runtime_lock_assessment"]["tone"] == "safe"


def test_unknown_blocker_defaults_to_danger_not_silently_downgraded(monkeypatch):
    live = _live()
    pipeline = _pipeline(blockers=["some_new_unrecognised_blocker"])
    monkeypatch.setattr(risk_guards, "get_live_status", lambda: live)
    monkeypatch.setattr(risk_guards, "get_pipeline_health", lambda: pipeline)

    result = risk_guards.get_risk_guards()

    assert result["annotated_blockers"] == [
        {
            "blocker": "some_new_unrecognised_blocker",
            "tone": "danger",
            "detail": (
                "Reported by show_full_pipeline_health.py as a restart/maintenance "
                "blocker; not yet correlated by the dashboard, treat as real."
            ),
        }
    ]


def test_operational_health_flags_real_problems_independent_of_restart_readiness(monkeypatch):
    # Restart-readiness says everything is fine (no blockers, safe_to_restart),
    # but the bot itself is actually unhealthy — operational_health must catch
    # this even though show_full_pipeline_health.py wouldn't.
    live = _live(run_health="critical", systemd_service_status="failed", pid_consistent=False, stale_lock_detected=True)
    pipeline = _pipeline()
    monkeypatch.setattr(risk_guards, "get_live_status", lambda: live)
    monkeypatch.setattr(risk_guards, "get_pipeline_health", lambda: pipeline)

    result = risk_guards.get_risk_guards()

    assert result["operational_health"]["tone"] == "danger"
    assert any("run_health" in r for r in result["operational_health"]["reasons"])


def test_operational_health_warning_on_errors_without_being_critical(monkeypatch):
    live = _live(errors_by_type={"llm_timeout": 2})
    pipeline = _pipeline()
    monkeypatch.setattr(risk_guards, "get_live_status", lambda: live)
    monkeypatch.setattr(risk_guards, "get_pipeline_health", lambda: pipeline)

    result = risk_guards.get_risk_guards()

    assert result["operational_health"]["tone"] == "warning"
