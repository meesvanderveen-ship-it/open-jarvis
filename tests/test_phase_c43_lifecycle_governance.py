from types import SimpleNamespace

from bot.phase_c43_lifecycle_governance import build_phase_c43_lifecycle_governance_report


def _cfg(**overrides):
    base = dict(
        enable_phase_c43_lifecycle_orchestrator=True,
        phase_c43_lifecycle_allow_coinbase_poll=False,
        phase_c43_lifecycle_apply_local=False,
        phase_c43_lifecycle_build_d2_plan=False,
        phase_c43_lifecycle_persist_d2_plan=False,
        phase_c43_lifecycle_build_d3_preview=False,
        phase_c43_lifecycle_max_poll_orders_per_cycle=4,
        phase_c43_lifecycle_max_apply_actions_per_cycle=4,
        phase_c43_lifecycle_apply_requires_coinbase_poll=True,
        phase_c43_lifecycle_block_apply_when_live_exits_enabled=True,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        enable_phase_d3_actual_exit_submit=False,
        phase_c_max_order_quote="25.00",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _order(idx=1, ticker="BTC-USDC", quote="25.00"):
    return {
        "client_order_id": f"phasec-{ticker.replace('-', '')}-{idx}",
        "exchange_order_id": f"cb-{idx}",
        "ticker": ticker,
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "execution_action": "place_limit_buy",
        "opened_via_phase_c43": True,
        "remaining_quote": quote,
    }


def test_default_no_open_orders_is_noop_preview():
    report = build_phase_c43_lifecycle_governance_report(cfg=_cfg(), local_open_c43_orders=[])
    assert report["status"] == "no_open_orders_noop"
    assert report["effective_flags"]["allow_coinbase_poll"] is False
    assert report["effective_flags"]["apply_local"] is False
    assert report["blockers"] == []
    assert "no_open_c43_orders_preview_noop" in report["decisions"]


def test_poll_allowed_only_when_flag_and_open_order():
    report = build_phase_c43_lifecycle_governance_report(
        cfg=_cfg(phase_c43_lifecycle_allow_coinbase_poll=True),
        local_open_c43_orders=[_order()],
    )
    assert report["status"] == "poll_only_governed"
    assert report["effective_flags"]["allow_coinbase_poll"] is True
    assert report["effective_flags"]["apply_local"] is False


def test_apply_requires_poll_flag_by_default():
    report = build_phase_c43_lifecycle_governance_report(
        cfg=_cfg(phase_c43_lifecycle_apply_local=True),
        local_open_c43_orders=[_order()],
    )
    assert report["status"] == "blocked_review_required"
    assert "apply_local_requires_coinbase_poll_flag" in report["blockers"]
    assert report["effective_flags"]["apply_local"] is False


def test_apply_local_d2_d3_effective_when_governed():
    report = build_phase_c43_lifecycle_governance_report(
        cfg=_cfg(
            phase_c43_lifecycle_allow_coinbase_poll=True,
            phase_c43_lifecycle_apply_local=True,
            phase_c43_lifecycle_build_d2_plan=True,
            phase_c43_lifecycle_persist_d2_plan=True,
            phase_c43_lifecycle_build_d3_preview=True,
        ),
        local_open_c43_orders=[_order()],
    )
    assert report["status"] == "apply_local_governed"
    assert report["effective_flags"] == {
        "allow_coinbase_poll": True,
        "apply_local": True,
        "build_d2_plan": True,
        "persist_d2_plan": True,
        "build_d3_preview": True,
    }


def test_apply_blocked_when_live_exit_flags_enabled():
    report = build_phase_c43_lifecycle_governance_report(
        cfg=_cfg(
            phase_c43_lifecycle_allow_coinbase_poll=True,
            phase_c43_lifecycle_apply_local=True,
            enable_live_exit_orders=True,
        ),
        local_open_c43_orders=[_order()],
    )
    assert report["status"] == "blocked_review_required"
    assert "apply_local_blocked_live_exit_flags_enabled" in report["blockers"]
    assert report["effective_flags"]["apply_local"] is False


def test_poll_and_apply_limits_block_large_batches():
    orders = [_order(i) for i in range(1, 4)]
    report = build_phase_c43_lifecycle_governance_report(
        cfg=_cfg(
            phase_c43_lifecycle_allow_coinbase_poll=True,
            phase_c43_lifecycle_apply_local=True,
            phase_c43_lifecycle_max_poll_orders_per_cycle=2,
            phase_c43_lifecycle_max_apply_actions_per_cycle=2,
        ),
        local_open_c43_orders=orders,
    )
    assert report["status"] == "blocked_review_required"
    assert "open_c43_orders_exceed_poll_limit" in report["blockers"]
    assert "open_c43_orders_exceed_apply_limit" in report["blockers"]
    assert report["effective_flags"]["allow_coinbase_poll"] is False
    assert report["effective_flags"]["apply_local"] is False


def test_quote_cap_blocks_oversized_local_order():
    report = build_phase_c43_lifecycle_governance_report(
        cfg=_cfg(phase_c43_lifecycle_allow_coinbase_poll=True, phase_c43_lifecycle_apply_local=True),
        local_open_c43_orders=[_order(quote="50.00")],
    )
    assert report["status"] == "blocked_review_required"
    assert "open_c43_order_quote_exceeds_governance_cap" in report["blockers"]
    assert report["effective_flags"]["allow_coinbase_poll"] is False
    assert report["effective_flags"]["apply_local"] is False
