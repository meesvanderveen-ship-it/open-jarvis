from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_tool_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "tools" / "test_paper_order_lifecycle.py"
    spec = importlib.util.spec_from_file_location("test_paper_order_lifecycle_tool", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase_b_diagnostic_tool_runs_all_scenarios_in_temp_state(tmp_path):
    tool = _load_tool_module()
    result = tool.run_scenarios(
        scenarios=["buy_fill", "buy_keep", "buy_expire", "buy_invalidate", "sell_fill"],
        state_path=tmp_path / "open_orders.json",
        log_path=tmp_path / "order_events.jsonl",
    )

    statuses = {order["client_order_id"]: order["status"] for order in result["orders"]}
    assert statuses["paper-diagnostic-buy_fill"] == "filled"
    assert statuses["paper-diagnostic-buy_keep"] == "submitted"
    assert statuses["paper-diagnostic-buy_expire"] == "expired"
    assert statuses["paper-diagnostic-buy_invalidate"] == "invalidated"
    assert statuses["paper-diagnostic-sell_fill"] == "filled"

    assert result["summary"]["total_orders"] == 5
    assert result["summary"]["open_orders"] == 1
    assert (tmp_path / "order_events.jsonl").exists()
