from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.show_pending_entry_lifecycle_status import build_pending_entry_lifecycle_status, main


def _write_state(root: Path) -> None:
    (root / "state").mkdir(parents=True, exist_ok=True)
    created = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    orders = {
        "orders": {
            "phasec-ETHUSDC-test": {
                "client_order_id": "phasec-ETHUSDC-test",
                "exchange_order_id": "cb-1",
                "ticker": "ETH-USDC",
                "side": "BUY",
                "status": "submitted",
                "execution_action": "place_limit_buy",
                "created_at": created,
                "limit_price": "100",
                "invalidation_level": "98",
                "do_not_chase_above": "101",
                "size_quote": "20",
                "trade_plan_snapshot": {
                    "plan_action": "prepare_buy",
                    "side": "BUY",
                    "setup_type": "reclaim_retest",
                    "entry_zone_low": "99.5",
                    "entry_zone_high": "100.2",
                    "invalidation_price": "98",
                    "take_profit_1": "104",
                    "do_not_chase_above": "101",
                },
                "orderbook_entry_preview": {
                    "current_mid": "100",
                    "best_bid": "99.99",
                    "best_ask": "100.01",
                    "spread_pct": "0.0002",
                },
            },
            "phased3-BTCUSDC-test": {
                "client_order_id": "phased3-BTCUSDC-test",
                "exchange_order_id": "cb-sell",
                "ticker": "BTC-USDC",
                "side": "SELL",
                "status": "submitted",
                "phase": "D3_controlled_live_reduce_only_exits",
                "execution_action": "place_limit_sell",
            },
        }
    }
    (root / "state/open_orders.json").write_text(json.dumps(orders), encoding="utf-8")
    (root / "state/positions.json").write_text("{}", encoding="utf-8")


def test_pending_entry_lifecycle_status_reports_open_buy_and_ignores_d3(tmp_path: Path) -> None:
    _write_state(tmp_path)
    status = build_pending_entry_lifecycle_status(root=tmp_path, env={})
    assert status["read_only"] is True
    assert status["coinbase_call_attempted"] is False
    assert status["state_write_attempted"] is False
    assert status["open_pending_entry_orders"] == 1
    assert status["d3_exit_orders_ignored_by_pending_entry_lifecycle"] == 1
    row = status["pending_entry_orders"][0]
    assert row["lifecycle_action"] == "keep_open"
    assert row["cancel_required"] is False
    assert row["requires_verify_cancel"] is False


def test_pending_entry_lifecycle_status_tool_writes_reports(tmp_path: Path) -> None:
    _write_state(tmp_path)
    assert main(["--root", str(tmp_path), "--json"]) == 0
    assert (tmp_path / "reports/audits/pending-entry-lifecycle-status-latest.json").exists()
    assert (tmp_path / "reports/audits/pending-entry-lifecycle-status-latest.md").exists()
    assert (tmp_path / "reports/audits/pending-entry-cancel-lifecycle-audit-latest.json").exists()
    audit = json.loads((tmp_path / "reports/audits/pending-entry-cancel-lifecycle-audit-latest.json").read_text(encoding="utf-8"))
    assert audit["cancel_preview_first_live_behind_ack_env"] is True
    assert audit["local_state_updated_only_after_verified_cancel"] is True
    assert audit["d3_exit_lifecycle_separate"] is True


def test_pending_entry_lifecycle_status_reads_project_env_for_direct_tool_use(tmp_path: Path) -> None:
    _write_state(tmp_path)
    (tmp_path / ".env").write_text(
        "ENABLE_PENDING_ENTRY_LIVE_CANCEL=true\n"
        "PENDING_ENTRY_LIVE_CANCEL_ACK=I_APPROVE_PENDING_ENTRY_LIVE_CANCEL\n",
        encoding="utf-8",
    )
    status = build_pending_entry_lifecycle_status(root=tmp_path)
    assert status["live_cancel_enabled"] is True
    assert status["cancel_route_design"]["live_cancel_enabled"] is True
