from __future__ import annotations

from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_rejected_submit_cleanup import build_phase_d3_rejected_submit_cleanup_report


def _store(tmp_path: Path) -> OrderStore:
    return OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")


def _ghost_order() -> dict:
    return {
        "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-6T0241261580710000",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "exchange_order_id": "",
        "order_id": "",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "limit_price": "81664.97580",
        "coinbase_response": {
            "success": False,
            "error_response": {
                "error": "INVALID_PRICE_PRECISION",
                "message": "Too many decimals in order price",
                "preview_failure_reason": "PREVIEW_INVALID_PRICE_PRECISION",
            },
        },
    }


def test_cleanup_dry_run_mutates_nothing(tmp_path: Path):
    store = _store(tmp_path)
    store.upsert_order(_ghost_order())
    report = build_phase_d3_rejected_submit_cleanup_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0241261580710000",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        reason="coinbase_submit_success_false_invalid_price_precision",
        order_store=store,
        apply=False,
    )
    assert report["dry_run"] is True
    assert report["state_write_performed"] is False
    assert report["blockers"] == []
    assert store.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0241261580710000")["status"] == "submitted"


def test_cleanup_apply_marks_exact_one_record_rejected(tmp_path: Path):
    store = _store(tmp_path)
    store.upsert_order(_ghost_order())
    report = build_phase_d3_rejected_submit_cleanup_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0241261580710000",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        reason="coinbase_submit_success_false_invalid_price_precision",
        order_store=store,
        apply=True,
    )
    assert report["state_write_performed"] is True
    updated = store.get_order("phased3-BTCUSDC-TP1-bc3330fe-6T0241261580710000")
    assert updated["status"] == "rejected"
    assert updated["remaining_size"] == "0"
    assert updated["exchange_order_id"] == ""
    assert store.open_exit_orders("BTC-USDC") == []


def test_cleanup_refuses_when_exchange_order_id_present(tmp_path: Path):
    store = _store(tmp_path)
    order = _ghost_order()
    order["exchange_order_id"] = "cb-1"
    store.upsert_order(order)
    report = build_phase_d3_rejected_submit_cleanup_report(
        ticker="BTC-USDC",
        client_order_id=order["client_order_id"],
        linked_position_id=order["linked_position_id"],
        reason="coinbase_submit_success_false_invalid_price_precision",
        order_store=store,
        apply=True,
    )
    assert "exchange_order_id_present" in report["blockers"]
    assert report["state_write_performed"] is False


def test_cleanup_refuses_when_linked_position_id_mismatch(tmp_path: Path):
    store = _store(tmp_path)
    store.upsert_order(_ghost_order())
    report = build_phase_d3_rejected_submit_cleanup_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-bc3330fe-6T0241261580710000",
        linked_position_id="wrong",
        reason="coinbase_submit_success_false_invalid_price_precision",
        order_store=store,
        apply=True,
    )
    assert "linked_position_id_mismatch" in report["blockers"]
    assert report["state_write_performed"] is False


def test_cleanup_refuses_when_reject_evidence_missing(tmp_path: Path):
    store = _store(tmp_path)
    order = _ghost_order()
    order["coinbase_response"] = {"success": True, "order_id": ""}
    store.upsert_order(order)
    report = build_phase_d3_rejected_submit_cleanup_report(
        ticker="BTC-USDC",
        client_order_id=order["client_order_id"],
        linked_position_id=order["linked_position_id"],
        reason="coinbase_submit_success_false_invalid_price_precision",
        order_store=store,
        apply=True,
    )
    assert "reject_evidence_missing" in report["blockers"]
    assert report["state_write_performed"] is False
