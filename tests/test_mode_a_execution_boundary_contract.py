from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_strategy_engine_has_no_generic_coinbase_execution_boundary() -> None:
    source = _source("bot/strategy_engine.py")

    assert "CoinbaseExecutor" not in source
    assert "self.executor" not in source
    assert ".place_market_order(" not in source
    assert ".place_limit_order(" not in source
    assert "execute_close_spot_position" not in source


def test_c43_buy_boundary_uses_only_the_canonical_buy_adapter_method() -> None:
    source = _source("bot/phase_c_live_submitter.py")

    assert "coinbase_client.submit_limit_buy_order(" in source
    assert "coinbase_client.place_limit_order(" not in source
    assert "coinbase_client.create_order(" not in source


def test_no_mode_a_runtime_module_invokes_a_market_order_method() -> None:
    matches = []
    for path in sorted((ROOT / "bot").glob("*.py")):
        if ".place_market_order(" in path.read_text(encoding="utf-8"):
            matches.append(path.relative_to(ROOT).as_posix())

    assert matches == []
    assert "def place_market_order(" in _source("bot/coinbase_client.py")


def test_manual_c43_smoke_tool_is_preview_only() -> None:
    source = _source("bot/phase_c43_one_entry_smoke_test.py")

    assert "manual_c43_smoke_live_submit_retired_use_canonical_strategy_workflow" in source
    assert "should_submit = False" in source


def test_c44_is_the_only_production_module_with_c43_local_apply_capability() -> None:
    holders = []
    for path in sorted((ROOT / "bot").glob("*.py")):
        if "_C43_LIFECYCLE_APPLY_AUTHORITY" in path.read_text(encoding="utf-8"):
            holders.append(path.relative_to(ROOT).as_posix())

    assert holders == [
        "bot/phase_c43_autonomous_entry_live.py",
        "bot/phase_c43_lifecycle_orchestrator.py",
    ]
    assert "reconcile_phase_c43_fills_to_positions" not in _source("bot/phase_d1_fill_position.py")
