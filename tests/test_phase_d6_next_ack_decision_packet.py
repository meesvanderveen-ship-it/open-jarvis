from bot.phase_d6_non_live_readiness_continuation import (
    BTC_SUBMIT_ACK,
    DATA_FETCH_ACK,
    build_next_ack_decision_packet,
)


def test_next_ack_decision_packet_is_bounded_and_non_live_by_default() -> None:
    report = build_next_ack_decision_packet()
    decisions = {row["route"]: row for row in report["decisions"]}

    assert decisions["data_fetch_ack_route"]["ack"] == DATA_FETCH_ACK
    assert decisions["btc_usdc_one_order_submit_ack_route"]["ack"] == BTC_SUBMIT_ACK
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["parameter_review_approved"] is False
    assert report["learning_to_execution_enabled"] is False
    assert all("does_not" in row for row in report["decisions"])
