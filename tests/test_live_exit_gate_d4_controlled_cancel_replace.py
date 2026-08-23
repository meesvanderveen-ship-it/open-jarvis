from __future__ import annotations

from types import SimpleNamespace

from bot.live_exit_gate import (
    D4_CONTROLLED_CANCEL_REPLACE_ACK,
    D4_CONTROLLED_CANCEL_REPLACE_SOURCE,
    evaluate_d4_controlled_replacement_submit_allowed,
    evaluate_live_exit_allowed,
)


def _cfg(**overrides):
    base = dict(
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        enable_phase_d3_actual_exit_submit=False,
        phase_c_disable_exit_limit_orders=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _happy_kwargs(**overrides):
    base = dict(
        cfg=_cfg(),
        source_tag=D4_CONTROLLED_CANCEL_REPLACE_SOURCE,
        human_ack=D4_CONTROLLED_CANCEL_REPLACE_ACK,
        one_shot_armed_process_local=True,
        side="SELL",
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        old_order_confirmed_cancelled=True,
        cancel_first_required=True,
        replace_only_after_confirmed_cancel=True,
        post_only=True,
        reduce_only_local=True,
        replacement_size_base="0.00006489",
        reserved_base="0.00006489",
        available_base="0.00006489",
        duplicate_open_exit_detected=False,
        oversell_detected=False,
        candidate_count=1,
        target_price="76000.00",
        price_increment="0.01",
        base_increment="0.00000001",
        min_order_quote="1",
        estimated_quote="4.9316400000",
        current_order_id="phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000",
        current_exchange_order_id="daa5ef77-9967-4fb0-b0c7-4f7c0680b512",
        replacement_client_order_id="phase-d4-replacement-test",
    )
    base.update(overrides)
    return base


def test_d4_source_without_ack_is_blocked() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(**_happy_kwargs(human_ack=""))
    assert evaluation["allowed"] is False
    assert "d4_replacement_ack_missing_or_invalid" in evaluation["blockers"]
    assert evaluation["no_coinbase_call"] is True
    assert evaluation["no_live_action"] is True


def test_d4_source_with_wrong_ack_is_blocked() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(**_happy_kwargs(human_ack="WRONG"))
    assert evaluation["allowed"] is False
    assert "d4_replacement_ack_missing_or_invalid" in evaluation["block_reasons"]


def test_correct_ack_with_default_flags_still_blocked_without_one_shot_arming() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(
        **_happy_kwargs(one_shot_armed_process_local=False)
    )
    assert evaluation["allowed"] is False
    assert "d4_replacement_process_local_arming_missing" in evaluation["blockers"]
    assert "enable_live_exit_orders_false" in evaluation["blockers"]
    assert "autonomous_allow_exits_false" in evaluation["blockers"]
    assert "enable_phase_d3_actual_exit_submit_false" in evaluation["blockers"]
    assert "phase_c_disable_exit_limit_orders_true" in evaluation["blockers"]
    assert evaluation["env_mutation"] is False


def test_correct_ack_with_process_local_one_shot_arming_allows_single_d4_candidate() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(**_happy_kwargs())
    assert evaluation["allowed"] is True
    assert evaluation["blockers"] == []
    assert evaluation["source_tag"] == D4_CONTROLLED_CANCEL_REPLACE_SOURCE
    assert evaluation["ack_valid"] is True
    assert evaluation["one_shot_d4_replacement_submit_armed_process_local"] is True
    assert evaluation["scope"] == "single_runner_process_only"
    assert evaluation["general_live_exits_released"] is False
    assert evaluation["autonomous_exits_allowed"] is False


def test_other_source_remains_blocked() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(
        **_happy_kwargs(source_tag="phase_d3_controlled_live_exit")
    )
    assert evaluation["allowed"] is False
    assert "d4_replacement_source_not_allowed" in evaluation["blockers"]


def test_general_autonomous_live_sell_remains_blocked_by_default() -> None:
    evaluation = evaluate_live_exit_allowed(
        cfg=_cfg(),
        side="SELL",
        source_tag="phase_d3_controlled_live_exit",
        human_ack="anything",
    )
    assert evaluation["allowed"] is False
    assert "autonomous_allow_exits_false" in evaluation["block_reasons"]


def test_replacement_before_confirmed_cancel_is_blocked() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(
        **_happy_kwargs(old_order_confirmed_cancelled=False)
    )
    assert evaluation["allowed"] is False
    assert "d4_replacement_confirmed_cancel_required" in evaluation["blockers"]


def test_non_sell_non_post_only_or_non_reduce_only_is_blocked() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(
        **_happy_kwargs(side="BUY", post_only=False, reduce_only_local=False)
    )
    assert evaluation["allowed"] is False
    assert "d4_replacement_side_must_be_sell" in evaluation["blockers"]
    assert "d4_replacement_post_only_required" in evaluation["blockers"]
    assert "d4_replacement_reduce_only_local_required" in evaluation["blockers"]


def test_duplicate_oversell_or_reservation_mismatch_is_blocked() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(
        **_happy_kwargs(
            duplicate_open_exit_detected=True,
            oversell_detected=True,
            reserved_base="0.00001",
            available_base="0.00001",
        )
    )
    assert evaluation["allowed"] is False
    assert "d4_replacement_duplicate_open_exit_detected" in evaluation["blockers"]
    assert "d4_replacement_oversell_detected" in evaluation["blockers"]
    assert "d4_replacement_reserved_base_insufficient" in evaluation["blockers"]
    assert "d4_replacement_available_base_insufficient" in evaluation["blockers"]


def test_min_quote_and_product_rule_failures_are_blocked() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(
        **_happy_kwargs(
            target_price="76000.005",
            replacement_size_base="0.000064895",
            estimated_quote="0.50",
        )
    )
    assert evaluation["allowed"] is False
    assert "d4_replacement_price_increment_violation" in evaluation["blockers"]
    assert "d4_replacement_base_increment_violation" in evaluation["blockers"]
    assert "d4_replacement_below_min_order_quote" in evaluation["blockers"]


def test_candidate_count_must_be_exactly_one() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(**_happy_kwargs(candidate_count=2))
    assert evaluation["allowed"] is False
    assert "d4_replacement_candidate_count_not_one" in evaluation["blockers"]


def test_gate_output_contains_audit_fields() -> None:
    evaluation = evaluate_d4_controlled_replacement_submit_allowed(**_happy_kwargs())
    assert evaluation["gate"] == "d4_controlled_replacement_submit"
    assert evaluation["required_ack"] == D4_CONTROLLED_CANCEL_REPLACE_ACK
    assert evaluation["allowed_sources"] == [D4_CONTROLLED_CANCEL_REPLACE_SOURCE]
    assert evaluation["safety_flags_snapshot"]["ENABLE_LIVE_EXIT_ORDERS"] is False
    assert evaluation["env_mutation"] is False
