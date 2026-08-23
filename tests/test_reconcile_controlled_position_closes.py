from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from bot.controlled_position_close_reconciliation import (
    CONTROLLED_CLOSE_TARGETS,
    REQUIRED_ACK,
    reconcile_controlled_position_closes,
)


class FakeCoinbaseClient:
    def __init__(self, orders: dict[str, dict], fills: dict[str, list[dict]] | None = None, error: Exception | None = None):
        self.orders = orders
        self.fills = fills if fills is not None else {}
        self.error = error
        self.order_calls: list[str] = []
        self.fill_calls: list[str] = []

    def get_order(self, order_id: str):
        self.order_calls.append(order_id)
        if self.error is not None:
            raise self.error
        return {"order": deepcopy(self.orders[order_id])}

    def get_recent_fills_for_order(self, order_id: str, limit: int = 100):
        self.fill_calls.append(order_id)
        if self.error is not None:
            raise self.error
        return deepcopy(self.fills.get(order_id, []))


def _source_report() -> dict:
    orders = []
    for target in CONTROLLED_CLOSE_TARGETS:
        orders.append({
            "ticker": target["ticker"],
            "client_order_id": target["client_order_id"],
            "order_id": target["exchange_order_id"],
            "coinbase_response": {
                "success_response": {
                    "product_id": target["ticker"],
                    "client_order_id": target["client_order_id"],
                    "order_id": target["exchange_order_id"],
                    "side": "SELL",
                }
            },
        })
    return {
        "positions_to_close": [target["ticker"] for target in CONTROLLED_CLOSE_TARGETS],
        "positions_excluded_from_close": ["ADA-USDC"],
        "execution_result": {"coinbase_response": {"orders": orders}},
    }


def _filled_order(target: dict, **overrides) -> dict:
    order = {
        "order_id": target["exchange_order_id"],
        "client_order_id": target["client_order_id"],
        "product_id": target["ticker"],
        "side": "SELL",
        "status": "FILLED",
        "settled": True,
        "remaining_size": "0",
        "filled_size": target["expected_base"],
        "filled_value": str(float(target["expected_base"]) * 100),
        "average_filled_price": "100",
        "total_fees": "0.01",
        "number_of_fills": "1",
    }
    order.update(overrides)
    return order


def _fill(target: dict) -> dict:
    return {
        "order_id": target["exchange_order_id"],
        "product_id": target["ticker"],
        "side": "SELL",
        "price": "100",
        "size": target["expected_base"],
        "quote_size": str(float(target["expected_base"]) * 100),
        "commission": "0.01",
    }


def _client(*, order_overrides: dict[str, dict] | None = None, missing_fills: bool = False, error: Exception | None = None) -> FakeCoinbaseClient:
    overrides = order_overrides or {}
    orders = {
        target["exchange_order_id"]: _filled_order(target, **overrides.get(target["ticker"], {}))
        for target in CONTROLLED_CLOSE_TARGETS
    }
    fills = {} if missing_fills else {
        target["exchange_order_id"]: [_fill(target)] for target in CONTROLLED_CLOSE_TARGETS
    }
    return FakeCoinbaseClient(orders, fills, error=error)


def _state() -> tuple[dict, dict]:
    positions = {
        target["ticker"]: {
            "ticker": target["ticker"],
            "status": "open",
            "position_size_base": target["expected_base"],
            "position_size_quote": "10",
            "bot_managed_base": target["expected_base"],
            "monitoring_enabled": True,
        }
        for target in CONTROLLED_CLOSE_TARGETS
    }
    positions["ADA-USDC"] = {"ticker": "ADA-USDC", "status": "open", "position_size_base": "42"}
    return positions, {"orders": {}}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _setup(tmp_path: Path) -> dict[str, Path]:
    source = tmp_path / "reports/live_runs/risk-incomplete-controlled-close-result.json"
    positions = tmp_path / "state/positions.json"
    orders = tmp_path / "state/open_orders.json"
    _write(source, _source_report())
    position_state, order_state = _state()
    _write(positions, position_state)
    _write(orders, order_state)
    return {
        "source": source,
        "positions": positions,
        "orders": orders,
        "journal": tmp_path / "state/controlled_position_close_reconciliation.journal.json",
    }


def _run(paths: dict[str, Path], client: FakeCoinbaseClient, *, mode: str = "check", ack: str = "", confirmation: bool = False, targets=None) -> dict:
    return reconcile_controlled_position_closes(
        mode=mode,
        ack=ack,
        confirmation=confirmation,
        coinbase_client=client,
        source_report_path=paths["source"],
        positions_path=paths["positions"],
        open_orders_path=paths["orders"],
        journal_path=paths["journal"],
        targets=CONTROLLED_CLOSE_TARGETS if targets is None else targets,
    )


def _apply(paths: dict[str, Path], client: FakeCoinbaseClient) -> dict:
    return _run(paths, client, mode="apply", ack=REQUIRED_ACK, confirmation=True)


def test_check_mode_writes_no_state(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    before_positions = paths["positions"].read_bytes()
    before_orders = paths["orders"].read_bytes()

    report = _run(paths, _client())

    assert report["status"] == "controlled_close_reconciliation_check_ready"
    assert report["no_state_write"] is True
    assert paths["positions"].read_bytes() == before_positions
    assert paths["orders"].read_bytes() == before_orders
    assert not paths["journal"].exists()


def test_apply_without_ack_writes_no_state(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    before = paths["positions"].read_bytes(), paths["orders"].read_bytes()

    report = _run(paths, _client(), mode="apply", confirmation=True)

    assert report["status"] == "controlled_close_reconciliation_apply_blocked"
    assert "exact_ack_required" in report["blockers"]
    assert (paths["positions"].read_bytes(), paths["orders"].read_bytes()) == before


def test_apply_without_confirmation_writes_no_state(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    before = paths["positions"].read_bytes(), paths["orders"].read_bytes()

    report = _run(paths, _client(), mode="apply", ack=REQUIRED_ACK)

    assert "extra_confirmation_required" in report["blockers"]
    assert (paths["positions"].read_bytes(), paths["orders"].read_bytes()) == before


def test_filled_evidence_closes_eth_avax_sol_and_records_final_sells(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    report = _apply(paths, _client())
    positions = json.loads(paths["positions"].read_text(encoding="utf-8"))
    orders = json.loads(paths["orders"].read_text(encoding="utf-8"))["orders"]

    assert report["status"] == "controlled_close_reconciliation_apply_performed"
    assert report["state_write_performed"] is True
    assert report["positions_mutated"] is True
    assert report["open_orders_mutated"] is True
    assert positions["ADA-USDC"]["status"] == "open"
    for target in CONTROLLED_CLOSE_TARGETS:
        position = positions[target["ticker"]]
        order = orders[target["client_order_id"]]
        assert position["status"] == "closed"
        assert position["close_source"] == "controlled_position_close_reconciliation"
        assert position["exchange_order_id"] == target["exchange_order_id"]
        assert order["status"] == "filled"
        assert order["side"] == "SELL"
        assert order["remaining_size"] == "0"


def test_pending_order_writes_no_state(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    report = _apply(paths, _client(order_overrides={"ETH-USDC": {"status": "OPEN", "settled": False}}))

    assert "ETH-USDC:terminal_status_not_filled" in report["blockers"]
    assert report["state_write_performed"] is False
    assert json.loads(paths["positions"].read_text())["ETH-USDC"]["status"] == "open"


def test_cancelled_order_writes_no_state(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    report = _apply(paths, _client(order_overrides={"AVAX-USDC": {"status": "CANCELLED", "settled": False}}))

    assert "AVAX-USDC:terminal_status_not_filled" in report["blockers"]
    assert report["state_write_performed"] is False


def test_partial_fill_never_writes_full_close(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    report = _apply(paths, _client(order_overrides={"SOL-USDC": {"filled_size": "0.1", "remaining_size": "0.2485292"}}))

    assert "SOL-USDC:remaining_size_nonzero" in report["blockers"]
    assert "SOL-USDC:filled_base_mismatch" in report["blockers"]
    assert json.loads(paths["positions"].read_text())["SOL-USDC"]["status"] == "open"


def test_missing_fills_writes_no_state(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    report = _apply(paths, _client(missing_fills=True))

    assert "ETH-USDC:fill_evidence_missing" in report["blockers"]
    assert report["state_write_performed"] is False


def test_wrong_order_id_fails_closed(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    report = _apply(paths, _client(order_overrides={"ETH-USDC": {"order_id": "wrong-order"}}))

    assert "ETH-USDC:exchange_order_id_mismatch" in report["blockers"]
    assert report["state_write_performed"] is False


def test_wrong_product_id_fails_closed(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    report = _apply(paths, _client(order_overrides={"AVAX-USDC": {"product_id": "BTC-USDC"}}))

    assert "AVAX-USDC:product_id_mismatch" in report["blockers"]
    assert report["state_write_performed"] is False


def test_buy_side_fails_closed(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    report = _apply(paths, _client(order_overrides={"SOL-USDC": {"side": "BUY"}}))

    assert "SOL-USDC:side_not_sell" in report["blockers"]
    assert report["state_write_performed"] is False


def test_ada_in_scope_fails_closed(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    targets = [*CONTROLLED_CLOSE_TARGETS, {
        "ticker": "ADA-USDC",
        "client_order_id": "controlled-close-ADAUSDC-20260619143856",
        "exchange_order_id": "ada-order",
        "expected_base": "1",
    }]
    report = _run(paths, _client(), mode="apply", ack=REQUIRED_ACK, confirmation=True, targets=targets)

    assert "ada_in_apply_scope" in report["blockers"]
    assert "apply_scope_must_be_exactly_eth_avax_sol" in report["blockers"]
    assert report["state_write_performed"] is False


def test_duplicate_rerun_is_idempotent_noop(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    first = _apply(paths, _client())
    state_after_first = paths["positions"].read_bytes(), paths["orders"].read_bytes()
    second = _apply(paths, _client())

    assert first["status"] == "controlled_close_reconciliation_apply_performed"
    assert second["status"] == "already_reconciled_noop"
    assert second["state_write_performed"] is False
    assert (paths["positions"].read_bytes(), paths["orders"].read_bytes()) == state_after_first


def test_duplicate_rerun_with_mismatched_evidence_hash_fails_closed(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    _apply(paths, _client())
    positions = json.loads(paths["positions"].read_text())
    positions["ETH-USDC"]["evidence_hash"] = "wrong-evidence-hash"
    _write(paths["positions"], positions)
    before = paths["positions"].read_bytes(), paths["orders"].read_bytes()

    report = _apply(paths, _client())

    assert report["status"] == "controlled_close_reconciliation_apply_blocked"
    assert "duplicate_reconciliation_evidence_hash_mismatch:ETH-USDC" in report["blockers"]
    assert (paths["positions"].read_bytes(), paths["orders"].read_bytes()) == before


def test_conflicting_open_sell_blocks_apply(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    state = json.loads(paths["orders"].read_text())
    state["orders"]["existing-eth-sell"] = {
        "client_order_id": "existing-eth-sell",
        "ticker": "ETH-USDC",
        "side": "SELL",
        "status": "submitted",
        "remaining_size": "0.01419647",
    }
    _write(paths["orders"], state)

    report = _apply(paths, _client())

    assert "conflicting_open_sell:ETH-USDC" in report["blockers"]
    assert report["state_write_performed"] is False


def test_coinbase_exception_fails_closed(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    report = _apply(paths, _client(error=RuntimeError("coinbase unavailable")))

    assert "ETH-USDC:coinbase_snapshot_unavailable" in report["blockers"]
    assert report["state_write_performed"] is False


def test_evidence_hash_is_stored_per_position_and_order(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    report = _apply(paths, _client())
    positions = json.loads(paths["positions"].read_text())
    orders = json.loads(paths["orders"].read_text())["orders"]

    for validation in report["validations"]:
        ticker = validation["ticker"]
        client_order_id = validation["client_order_id"]
        assert validation["evidence_hash"]
        assert positions[ticker]["evidence_hash"] == validation["evidence_hash"]
        assert orders[client_order_id]["evidence_hash"] == validation["evidence_hash"]


def test_apply_uses_atomic_writes_with_completed_recovery_journal_and_backups(tmp_path: Path) -> None:
    paths = _setup(tmp_path)
    original_positions = json.loads(paths["positions"].read_text())
    original_orders = json.loads(paths["orders"].read_text())

    report = _apply(paths, _client())
    journal = json.loads(paths["journal"].read_text())

    assert report["transaction"]["journal_path"] == str(paths["journal"])
    assert journal["status"] == "completed"
    assert json.loads(Path(journal["positions_backup"]).read_text()) == original_positions
    assert json.loads(Path(journal["open_orders_backup"]).read_text()) == original_orders
