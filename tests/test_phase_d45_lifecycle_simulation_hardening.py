from __future__ import annotations

from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_cancel_closeout_local_reconcile import (
    D3_CANCEL_CLOSEOUT_LOCAL_RECONCILE_ACK,
    build_phase_d3_cancel_closeout_local_reconcile_report,
)
from bot.phase_d3_open_exit_lifecycle_manager import (
    D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    build_phase_d3_open_exit_lifecycle_report,
)
from bot.phase_d45_exit_operations_report import (
    FILL_APPLY_ROUTE,
    TERMINAL_CLOSEOUT_ROUTE,
    build_phase_d45_exit_operations_report,
)
from bot.phase_d5_execution_metrics import build_phase_d5_execution_metrics_report
from bot.state_store import StateStore


CLIENT_ORDER_ID = "phased4-BTCUSDC-TP1-repl-bc3330fe-20260529064443"
EXCHANGE_ORDER_ID = "6f6fa436-f5b9-4df5-bb23-ddf35a27a56a"
LINKED_POSITION_ID = "76310097-849e-481c-b587-ba44bc3330fe"


def _state(tmp_path: Path, monkeypatch) -> StateStore:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    return StateStore()


def _orders(tmp_path: Path) -> OrderStore:
    return OrderStore(
        path=tmp_path / "state" / "open_orders.json",
        log_path=tmp_path / "logs" / "order_events.jsonl",
    )


def _seed_open_position(state: StateStore, **overrides) -> None:
    payload = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "entry_price": "80000",
        "phase_c43_exchange_order_id": LINKED_POSITION_ID,
        "recovery_linked_position_id": LINKED_POSITION_ID,
        "position_size_base": "0.0000649067431275",
        "bot_managed_base": "0.0001297967431275",
        "reserved_base_open_exit_orders": "0.00006489",
    }
    payload.update(overrides)
    state.upsert_position("BTC-USDC", payload)


def _seed_open_exit(orders: OrderStore, **overrides) -> None:
    payload = {
        "client_order_id": CLIENT_ORDER_ID,
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": LINKED_POSITION_ID,
        "exchange_order_id": EXCHANGE_ORDER_ID,
        "order_id": EXCHANGE_ORDER_ID,
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "filled_base": "0",
        "filled_quote": "0",
        "fill_count": 0,
        "limit_price": "76000.00",
        "post_only": True,
        "reduce_only_local": True,
    }
    payload.update(overrides)
    orders.upsert_order(payload)


def _local_d45(**overrides):
    payload = {
        "lifecycle_branch": "open_keep_open",
        "recommended_operator_action": "wait_for_trigger",
        "active_order_summary": {
            "ticker": "BTC-USDC",
            "client_order_id": CLIENT_ORDER_ID,
            "exchange_order_id": EXCHANGE_ORDER_ID,
            "limit_price": "76000.00",
            "size_base": "0.00006489",
            "remaining_size": "0.00006489",
            "filled_base": "0",
            "fill_count": 0,
        },
        "open_d3_exit_count_for_position": 1,
        "reserved_base_open_exit_orders": "0.00006489",
        "remaining_size": "0.00006489",
        "blockers": [],
    }
    payload.update(overrides)
    return payload


def _poll(status: str, **overrides):
    payload = {
        "coinbase_call_succeeded": True,
        "coinbase_raw_status": status.upper(),
        "normalized_status": status,
        "filled_base": "0",
        "filled_quote": "0",
        "avg_fill_price": "0",
        "fill_count": 0,
        "remaining_size": "0.00006489",
        "proposed_action": "keep_open",
        "blockers": [],
    }
    payload.update(overrides)
    return payload


def _snapshot(status: str, **overrides):
    normalized = "partially_filled" if status == "partial" else status
    payload = {
        "coinbase_call_attempted": False,
        "coinbase_call_succeeded": True,
        "raw_status": normalized.upper(),
        "normalized_status": normalized,
        "filled_base": "0",
        "filled_quote": "0",
        "avg_fill_price": "0",
        "fill_count": 0,
        "remaining_size": "0.00006489",
        "fees": "0",
        "evidence_source": "fixture_only_lifecycle_simulation",
    }
    payload.update(overrides)
    return payload


def _lifecycle_report(tmp_path: Path, state: StateStore, orders: OrderStore, **kwargs):
    return build_phase_d3_open_exit_lifecycle_report(
        ticker="BTC-USDC",
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id=EXCHANGE_ORDER_ID,
        linked_position_id=LINKED_POSITION_ID,
        order_store=orders,
        state_store=state,
        **kwargs,
    )


def _state_bytes(tmp_path: Path) -> tuple[bytes, bytes]:
    return (
        (tmp_path / "state" / "open_orders.json").read_bytes(),
        (tmp_path / "state" / "positions.json").read_bytes(),
    )


def _assert_d45_no_writes(report) -> None:
    assert report["no_coinbase_submit"] is True
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert report["no_coinbase_write"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["learning_to_execution_allowed"] is False


def test_partial_and_filled_fixture_evidence_route_to_fill_apply_and_ack_gate_d3(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for status, filled_base, remaining_size in (
        ("partial", "0.00001", "0.00005489"),
        ("filled", "0.00006489", "0"),
    ):
        state = _state(tmp_path / status, monkeypatch)
        orders = _orders(tmp_path / status)
        _seed_open_position(state)
        _seed_open_exit(orders)
        before = _state_bytes(tmp_path / status)

        d45_report = build_phase_d45_exit_operations_report(
            local_report=_local_d45(),
            lifecycle_poll_report=_poll(
                status,
                filled_base=filled_base,
                filled_quote="5.00",
                avg_fill_price="77000",
                fill_count=1,
                remaining_size=remaining_size,
            ),
            explicit_operator_request=True,
        )

        assert d45_report["lifecycle_branch"] == "fill_evidence"
        assert d45_report["recommended_operator_action"] == "prepare_fill_lifecycle_apply"
        assert d45_report["next_route"] == FILL_APPLY_ROUTE
        assert d45_report["required_future_ack"] == D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK
        _assert_d45_no_writes(d45_report)

        preview = _lifecycle_report(
            tmp_path / status,
            state,
            orders,
            snapshot=_snapshot(
                status,
                filled_base=filled_base,
                filled_quote="5.00",
                avg_fill_price="77000",
                fill_count=1,
                remaining_size=remaining_size,
            ),
            allow_coinbase_poll=False,
        )
        assert preview["status"] == "d3_open_exit_lifecycle_reconcile_preview_ready"
        assert preview["proposed_action"] in {"mark_partially_filled", "mark_filled"}
        assert preview["state_write_performed"] is False
        assert _state_bytes(tmp_path / status) == before

        blocked_apply = _lifecycle_report(
            tmp_path / status,
            state,
            orders,
            snapshot=_snapshot(
                status,
                filled_base=filled_base,
                filled_quote="5.00",
                avg_fill_price="77000",
                fill_count=1,
                remaining_size=remaining_size,
            ),
            apply_local=True,
            apply_ack="",
            allow_coinbase_poll=False,
        )
        assert blocked_apply["status"] == "blocked_review_required"
        assert "d3_open_exit_lifecycle_apply_ack_required" in blocked_apply["blockers"]
        assert blocked_apply["state_write_performed"] is False
        assert blocked_apply["duplicate_exit_detected"] is False
        assert blocked_apply["oversell_detected"] is False
        assert _state_bytes(tmp_path / status) == before


def test_repeat_fill_preview_is_stable_and_mutation_free(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_open_position(state)
    _seed_open_exit(orders)
    snapshot = _snapshot(
        "filled",
        filled_base="0.00006489",
        filled_quote="4.93164000",
        avg_fill_price="76000",
        fill_count=1,
        remaining_size="0",
    )

    first = _lifecycle_report(
        tmp_path,
        state,
        orders,
        snapshot=snapshot,
        allow_coinbase_poll=False,
    )
    second = _lifecycle_report(
        tmp_path,
        state,
        orders,
        snapshot=snapshot,
        allow_coinbase_poll=False,
    )

    order = orders.get_order(CLIENT_ORDER_ID) or {}
    position = state.get_position("BTC-USDC") or {}
    assert first["status"] == "d3_open_exit_lifecycle_reconcile_preview_ready"
    assert first["proposed_action"] == "mark_filled"
    assert first["state_write_performed"] is False
    assert second["status"] == "d3_open_exit_lifecycle_reconcile_preview_ready"
    assert second["evidence_hash"] == first["evidence_hash"]
    assert second["state_write_performed"] is False
    assert order["status"] == "submitted"
    assert order["remaining_size"] == "0.00006489"
    assert position["reserved_base_open_exit_orders"] == "0.00006489"


def test_terminal_fixture_evidence_routes_to_closeout_and_blocks_without_ack(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for status in ("cancelled", "expired", "rejected"):
        state = _state(tmp_path / status, monkeypatch)
        orders = _orders(tmp_path / status)
        _seed_open_position(state)
        _seed_open_exit(orders)
        before = _state_bytes(tmp_path / status)

        d45_report = build_phase_d45_exit_operations_report(
            local_report=_local_d45(),
            lifecycle_poll_report=_poll(status, proposed_action=f"mark_{status}"),
            explicit_operator_request=True,
        )
        assert d45_report["lifecycle_branch"] == "terminal_evidence"
        assert d45_report["recommended_operator_action"] == "prepare_terminal_closeout"
        assert d45_report["next_route"] == TERMINAL_CLOSEOUT_ROUTE
        assert d45_report["required_future_ack"] == D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK
        _assert_d45_no_writes(d45_report)

        preview = _lifecycle_report(
            tmp_path / status,
            state,
            orders,
            snapshot=_snapshot(status, remaining_size="0"),
            allow_coinbase_poll=False,
        )
        assert preview["status"] == "d3_open_exit_lifecycle_reconcile_preview_ready"
        assert preview["proposed_action"] == f"mark_{status}"
        assert preview["state_write_performed"] is False
        assert _state_bytes(tmp_path / status) == before

        blocked_apply = _lifecycle_report(
            tmp_path / status,
            state,
            orders,
            snapshot=_snapshot(status, remaining_size="0"),
            apply_local=True,
            apply_ack="WRONG",
            allow_coinbase_poll=False,
        )
        assert blocked_apply["status"] == "blocked_review_required"
        assert "d3_open_exit_lifecycle_apply_ack_required" in blocked_apply["blockers"]
        assert blocked_apply["state_write_performed"] is False
        assert _state_bytes(tmp_path / status) == before


def test_cancelled_closeout_helper_ack_and_hash_gates_remain_fixture_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_open_position(state)
    _seed_open_exit(orders)

    preview = build_phase_d3_cancel_closeout_local_reconcile_report(
        ticker="BTC-USDC",
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id=EXCHANGE_ORDER_ID,
        linked_position_id=LINKED_POSITION_ID,
        evidence_hash="",
        order_store=orders,
        state_store=state,
    )
    evidence_hash = preview["evidence_hash"]
    before = _state_bytes(tmp_path)

    missing_ack = build_phase_d3_cancel_closeout_local_reconcile_report(
        ticker="BTC-USDC",
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id=EXCHANGE_ORDER_ID,
        linked_position_id=LINKED_POSITION_ID,
        evidence_hash=evidence_hash,
        order_store=orders,
        state_store=state,
        apply=True,
    )
    wrong_hash = build_phase_d3_cancel_closeout_local_reconcile_report(
        ticker="BTC-USDC",
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id=EXCHANGE_ORDER_ID,
        linked_position_id=LINKED_POSITION_ID,
        evidence_hash="wrong",
        order_store=orders,
        state_store=state,
        apply=True,
        ack=D3_CANCEL_CLOSEOUT_LOCAL_RECONCILE_ACK,
    )

    assert preview["status"] == "d3_cancel_closeout_local_reconcile_preview_ready"
    assert preview["state_write_performed"] is False
    assert missing_ack["status"] == "d3_cancel_closeout_local_reconcile_blocked"
    assert "d3_cancel_closeout_local_reconcile_ack_required" in missing_ack["blockers"]
    assert wrong_hash["status"] == "d3_cancel_closeout_local_reconcile_blocked"
    assert "evidence_hash_mismatch" in wrong_hash["blockers"]
    assert _state_bytes(tmp_path) == before


def test_open_unknown_and_p0_blockers_fail_closed_without_state_writes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_open_position(state)
    _seed_open_exit(orders)
    before = _state_bytes(tmp_path)

    open_report = build_phase_d45_exit_operations_report(
        local_report=_local_d45(),
        lifecycle_poll_report=_poll("open"),
        explicit_operator_request=True,
    )
    unknown_report = build_phase_d45_exit_operations_report(
        local_report=_local_d45(),
        lifecycle_poll_report=_poll("weird"),
        explicit_operator_request=True,
    )
    duplicate_report = build_phase_d45_exit_operations_report(
        local_report=_local_d45(
            open_d3_exit_count_for_position=2,
            blockers=["duplicate_open_d3_exit_orders_for_position"],
        ),
        lifecycle_poll_report=_poll("partial", filled_base="0.00001", fill_count=1),
        explicit_operator_request=True,
    )
    reservation_report = build_phase_d45_exit_operations_report(
        local_report=_local_d45(reserved_base_open_exit_orders="0.00001"),
        lifecycle_poll_report=_poll("filled", filled_base="0.00006489", fill_count=1),
        explicit_operator_request=True,
    )
    terminal_with_fill = _lifecycle_report(
        tmp_path,
        state,
        orders,
        snapshot=_snapshot("cancelled", filled_base="0.00001", fill_count=1),
        allow_coinbase_poll=False,
    )

    assert open_report["lifecycle_branch"] == "open_keep_open"
    assert open_report["next_route"] == "keep_open"
    assert unknown_report["lifecycle_branch"] == "fail_closed"
    assert unknown_report["next_route"] == "unknown_lifecycle_status_review"
    assert duplicate_report["lifecycle_branch"] == "blocked_p0_safety_drift"
    assert reservation_report["lifecycle_branch"] == "blocked_p0_safety_drift"
    assert terminal_with_fill["status"] == "blocked_review_required"
    assert "terminal_non_fill_status_contains_fill_evidence" in terminal_with_fill["blockers"]
    assert _state_bytes(tmp_path) == before


def test_d5_enrichment_stays_report_only_for_open_partial_filled_and_terminal() -> None:
    for status, filled_base, fill_count in (
        ("open", "0", 0),
        ("partial", "0.00001", 1),
        ("filled", "0.00006489", 1),
        ("cancelled", "0", 0),
    ):
        report = build_phase_d5_execution_metrics_report(
            lifecycle_event={
                "lifecycle_status": status,
                "submitted_at": "2026-05-29T06:44:43+00:00",
                "first_seen_open_at": "2026-05-29T06:44:44+00:00",
                "filled_base": filled_base,
                "fill_count": fill_count,
                "planned_exit_price": "76000.00",
                "planned_size_base": "0.00006489",
            },
            plan_fields={"planned_exit_price": "76000.00", "planned_size_base": "0.00006489"},
            market_refs={"decision_mid": "74000", "decision_best_bid": "74000"},
            fills={
                "filled_base": filled_base,
                "filled_quote": "4.93164000" if filled_base != "0" else "0",
                "avg_fill_price": "76000" if filled_base != "0" else "0",
                "fill_count": fill_count,
            },
        )

        assert report["learning_to_execution_allowed"] is False
        assert report["learning_recommendation_mode"] == "report_only"
        assert report["no_coinbase_call"] is True
        assert report["no_live_action"] is True
        assert report["state_write_performed"] is False
