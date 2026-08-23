from __future__ import annotations

import fcntl
import json
from pathlib import Path

from bot.pre_live_current_state import build_pre_live_current_state


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_state(root: Path, *, positions: object, orders: object) -> None:
    _write_json(root / "state/positions.json", positions)
    _write_json(root / "state/open_orders.json", {"orders": orders})


def test_final_orders_with_remaining_size_are_not_current_reservations(tmp_path: Path) -> None:
    _seed_state(
        tmp_path,
        positions={},
        orders={
            "btc-cancelled": {"status": "cancelled", "remaining_size": "9"},
            "btc-canceled": {"status": "canceled", "remaining_size": "9"},
            "btc-filled": {"status": "filled", "remaining_size": "9"},
            "btc-rejected": {"status": "rejected", "remaining_size": "9"},
            "btc-unknown": {"status": "unknown", "remaining_size": "9"},
        },
    )

    report = build_pre_live_current_state(tmp_path)

    assert report["open_order_ids"] == ["btc-unknown"]
    assert report["open_orders"] == 1


def test_stale_lock_contents_without_held_flock_are_diagnostic_only(tmp_path: Path) -> None:
    _seed_state(tmp_path, positions={}, orders={})
    lock_path = tmp_path / "state/runtime_mutation.lock"
    lock_path.write_text("12345", encoding="utf-8")

    report = build_pre_live_current_state(tmp_path)

    assert report["runtime_lock"]["status"] == "not_held"
    assert report["runtime_lock"]["stale_contents_ignored"] is True
    assert "runtime_mutation_lock_held" not in report["blockers"]


def test_held_runtime_lock_blocks_without_mutating_lock_contents(tmp_path: Path) -> None:
    _seed_state(tmp_path, positions={}, orders={})
    lock_path = tmp_path / "state/runtime_mutation.lock"
    lock_path.write_text("owner", encoding="utf-8")

    with lock_path.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            report = build_pre_live_current_state(tmp_path)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    assert report["runtime_lock"]["held"] is True
    assert "runtime_mutation_lock_held" in report["blockers"]
    assert lock_path.read_text(encoding="utf-8") == "owner"


def test_missing_current_state_fails_closed(tmp_path: Path) -> None:
    report = build_pre_live_current_state(tmp_path)

    assert report["state_evidence_available"] is False
    assert set(report["blockers"]) == {
        "current_open_orders_state_unavailable",
        "current_positions_state_unavailable",
    }
