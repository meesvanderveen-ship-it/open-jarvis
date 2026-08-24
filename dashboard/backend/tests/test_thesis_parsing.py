import json

from dashboard.backend.services import thesis as thesis_service
from dashboard.backend.services import ticker_universe


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _patch_state_files(monkeypatch, tmp_path, *, positions=None, orders=None):
    positions_path = tmp_path / "positions.json"
    positions_path.write_text(json.dumps(positions or {}))
    orders_path = tmp_path / "open_orders.json"
    orders_path.write_text(json.dumps({"orders": orders or {}}))

    def _resolve(name: str):
        return {"positions.json": positions_path, "open_orders.json": orders_path}[name]

    monkeypatch.setattr(thesis_service, "resolve_state_file", _resolve)
    return positions_path, orders_path


def test_open_position_prefers_live_position_fields_over_stale_trade_plan(monkeypatch, tmp_path):
    _patch_state_files(
        monkeypatch,
        tmp_path,
        positions={
            "SOL-USDC": {
                "status": "open",
                "entry_price": "80.42",
                "entry_time": "2026-07-05T17:00:00+00:00",
                "entry_reason": "phase_c43_live_limit_buy_filled",
                "setup_type": "reclaim_reversal",
                "position_size_base": "0.76349166",
                "position_size_quote": "61.40",
                "stop_price": "80.32289842475191",
                "take_profit_price": "81.300",
                "invalidation_price": "79.98",
                "trailing_active": False,
                "trailing_trigger_pct": "0.02",
                "trailing_distance_pct": "0.03",
                "highest_price_seen": "80.955",
            }
        },
    )
    analysis_path = tmp_path / "analysis.jsonl"
    _write_jsonl(
        analysis_path,
        [
            {
                "ticker": "SOL-USDC",
                "generated_at": "2026-07-06T08:01:24+00:00",
                "feature_pack": {"market": {"mid_price": "80.765"}},
                "judge": {
                    "decision": "wait",
                    "confidence": 68,
                    "reasons": ["thesis still intact above invalidation"],
                    "must_reject_if": ["1h close below 79.98"],
                },
                "trade_plan": {
                    "plan_action": "manage_existing",
                    "valid_trade_plan": False,
                    "trigger": "Hold while above invalidation.",
                    "stop_loss": 79.98,
                    "take_profit_1": 81.3,
                    "take_profit_2": 82.35,
                    "monitoring_rules": ["Keep position while support holds."],
                },
            }
        ],
    )
    monkeypatch.setattr(thesis_service, "resolve_under_logs", lambda name: analysis_path)

    report = thesis_service.get_thesis_report()

    assert report["summary"]["open_count"] == 1
    sol = next(t for t in report["tickers"] if t["ticker"] == "SOL-USDC")
    assert sol["status"] == "open"
    assert sol["current_price"] == 80.765
    # Live position stop/TP must win over the (now stale) trade_plan copy.
    assert sol["stop_loss_price"] == 80.32289842475191
    assert sol["take_profit_price"] == 81.3
    assert sol["trailing_stop"]["trigger_pct"] == 0.02
    assert sol["trailing_stop"]["distance_pct"] == 0.03
    assert sol["position"]["size_quote_usdc"] == 61.40
    assert sol["thesis_reasons"] == ["thesis still intact above invalidation"]
    assert sol["entry_plan"]["condition_text"] == "Hold while above invalidation."


def test_ticker_with_no_position_falls_back_to_trade_plan_entry_conditions(monkeypatch, tmp_path):
    _patch_state_files(monkeypatch, tmp_path, positions={})
    analysis_path = tmp_path / "analysis.jsonl"
    _write_jsonl(
        analysis_path,
        [
            {
                "ticker": "ETH-USDC",
                "generated_at": "2026-07-06T08:00:00+00:00",
                "feature_pack": {"market": {"mid_price": "1800"}},
                "judge": {"decision": "wait", "confidence": 55, "reasons": ["waiting for trigger"]},
                "trade_plan": {
                    "plan_action": "new_entry",
                    "valid_trade_plan": True,
                    "trigger": "Buy on a 1h close above 1820.",
                    "entry_zone_low": 1805,
                    "entry_zone_high": 1815,
                    "trigger_price": 1820,
                    "do_not_chase_above": 1830,
                    "stop_loss": 1780,
                    "take_profit_1": 1860,
                },
            }
        ],
    )
    monkeypatch.setattr(thesis_service, "resolve_under_logs", lambda name: analysis_path)

    report = thesis_service.get_thesis_report()

    eth = next(t for t in report["tickers"] if t["ticker"] == "ETH-USDC")
    assert eth["status"] == "watching"
    assert eth["position"] is None
    assert eth["entry_plan"]["trigger_price"] == 1820
    assert eth["entry_plan"]["entry_zone_low"] == 1805
    assert eth["entry_plan"]["do_not_chase_above"] == 1830
    assert eth["stop_loss_price"] == 1780
    assert eth["take_profit_price"] == 1860


def test_closed_position_backfills_size_and_close_price_from_linked_orders(monkeypatch, tmp_path):
    # Regression test for a real gap found live (2026-07-06): a governed
    # fill-reconciliation apply correctly zeroes a closed position's own
    # size fields (current exposure really is zero), but that also erases
    # the "how big was this trade" record unless we recover it from the
    # linked entry/close orders.
    _patch_state_files(
        monkeypatch,
        tmp_path,
        positions={
            "SOL-USDC": {
                "status": "closed",
                "order_id": "cdcefd68-dc8c-4c54-bb9f-fb50fbb6505f",
                "entry_price": "80.42",
                "position_size_base": "0",
                "position_size_quote": "0",
                "close_time": "2026-07-06T08:11:45+00:00",
                "close_reason": "d3_live_exit_order_filled_position_flattened",
            }
        },
        orders={
            "entry-order": {
                "exchange_order_id": "cdcefd68-dc8c-4c54-bb9f-fb50fbb6505f",
                "side": "BUY",
                "avg_fill_price": "80.42",
                "filled_quote": "61.3999992972",
            },
            "close-order": {
                "exchange_order_id": "d057362b-45a8-4def-829e-f63295b4b9a1",
                "linked_position_id": "cdcefd68-dc8c-4c54-bb9f-fb50fbb6505f",
                "side": "SELL",
                "status": "filled",
                "avg_fill_price": "80.63",
                "filled_quote": "61.5603325458",
                "fees_paid": "0.37",
                "filled_at": "2026-07-06T08:11:45+00:00",
            },
        },
    )
    monkeypatch.setattr(thesis_service, "resolve_under_logs", lambda name: tmp_path / "missing_analysis.jsonl")

    report = thesis_service.get_thesis_report()

    sol = next(t for t in report["tickers"] if t["ticker"] == "SOL-USDC")
    assert sol["status"] == "closed"
    assert sol["position"]["size_quote_usdc"] == 61.3999992972
    assert sol["position"]["close_price"] == 80.63
    assert round(sol["position"]["realized_pnl"], 4) == round(61.5603325458 - 61.3999992972 - 0.37, 4)


def test_hides_closed_ticker_outside_universe_but_keeps_open_position(monkeypatch, tmp_path):
    _patch_state_files(
        monkeypatch,
        tmp_path,
        positions={
            "BTC-USDC": {"status": "open", "entry_price": "100"},
            "XRP-USDC": {"status": "closed", "close_time": "2026-06-01T00:00:00Z", "entry_price": "0.5"},
        },
    )
    monkeypatch.setattr(thesis_service, "resolve_under_logs", lambda name: tmp_path / "missing_analysis.jsonl")
    universe_path = tmp_path / "runtime_ticker_universe.json"
    universe_path.write_text(json.dumps({"configured_ticker_universe": ["BTC-USDC"]}))
    monkeypatch.setattr(ticker_universe, "resolve_state_file", lambda name: universe_path)

    report = thesis_service.get_thesis_report()

    tickers = {t["ticker"] for t in report["tickers"]}
    assert tickers == {"BTC-USDC"}


def test_handles_missing_files(monkeypatch, tmp_path):
    missing_positions = tmp_path / "missing_positions.json"
    missing_orders = tmp_path / "missing_orders.json"
    missing_analysis = tmp_path / "missing_analysis.jsonl"
    monkeypatch.setattr(
        thesis_service,
        "resolve_state_file",
        lambda name: {"positions.json": missing_positions, "open_orders.json": missing_orders}[name],
    )
    monkeypatch.setattr(thesis_service, "resolve_under_logs", lambda name: missing_analysis)

    report = thesis_service.get_thesis_report()

    assert report["tickers"] == []
    assert report["summary"] == {"open_count": 0, "closed_count": 0, "watching_count": 0}
