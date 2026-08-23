from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_root_coinbase_client_is_import_alias_only() -> None:
    source = _source("coinbase_client.py")

    assert "from bot.coinbase_client import CoinbaseClient" in source
    assert "class CoinbaseClient" not in source


def test_mode_a_runtime_has_no_direct_coinbase_order_submit_calls() -> None:
    for relative_path in ("run_trader_loop.py", "bot/strategy_engine.py"):
        source = _source(relative_path)
        assert ".place_market_order(" not in source
        assert ".place_limit_order(" not in source
        assert ".submit_limit_buy_order(" not in source

    strategy_source = _source("bot/strategy_engine.py")
    assert "build_phase_c43_guard_and_submit_preparation(" in strategy_source
    assert "submit_phase_d3_controlled_exit(" in strategy_source


def test_only_c43_submitter_and_d3_boundary_call_the_adapter_in_mode_a_path() -> None:
    c43_source = _source("bot/phase_c43_autonomous_entry_live.py")
    c43_submitter_source = _source("bot/phase_c_live_submitter.py")
    d3_source = _source("bot/phase_d3_controlled_live_exits.py")

    assert ".place_limit_order(" not in c43_source
    assert ".place_market_order(" not in c43_source
    assert c43_submitter_source.count(".submit_limit_buy_order(") == 1
    assert ".place_limit_order(" not in c43_submitter_source
    assert ".place_market_order(" not in c43_submitter_source
    assert d3_source.count(".place_limit_order(") == 1
    assert ".place_market_order(" not in d3_source
