from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.strategy_engine import StrategyEngine


class FakeCoinbaseClient:
    def __init__(self, balances: dict[str, str]):
        self._balances = balances

    def get_all_balances(self) -> dict[str, Decimal]:
        return {k: Decimal(v) for k, v in self._balances.items()}


class FailingCoinbaseClient:
    def get_all_balances(self):
        raise RuntimeError("coinbase unreachable")


def _engine(client, *, min_pct="0.10", max_pct="0.20") -> StrategyEngine:
    engine = StrategyEngine.__new__(StrategyEngine)
    engine.client = client
    engine.cfg = SimpleNamespace(
        min_position_pct_of_portfolio=Decimal(min_pct),
        max_position_pct_of_portfolio=Decimal(max_pct),
        min_dynamic_entry_quote_usdc=Decimal("50.00"),
        max_dynamic_entry_quote_usdc=Decimal("100.00"),
        min_live_order_quote_usdc=Decimal("50.00"),
        max_live_order_quote_usdc=Decimal("100.00"),
        phase_c_max_order_quote=Decimal("100.00"),
        autonomous_max_order_quote=Decimal("100.00"),
    )
    engine._to_decimal = StrategyEngine._to_decimal
    engine._json_safe = StrategyEngine._json_safe
    engine._now_iso = lambda: "2026-07-06T00:00:00+00:00"
    written = []
    engine._write_jsonl = lambda filename, payload: written.append((filename, payload))
    engine._written = written
    return engine


def _feature_packs(prices: dict[str, str]) -> dict[str, dict]:
    return {ticker: {"market": {"mid_price": price}} for ticker, price in prices.items()}


def test_portfolio_value_sums_cash_and_priced_holdings():
    client = FakeCoinbaseClient({"USDC": "500.00", "SOL": "10", "BTC": "0.01"})
    engine = _engine(client)
    feature_packs = _feature_packs({"SOL-USDC": "80.00", "BTC-USDC": "60000.00"})

    portfolio = engine._compute_portfolio_value_usdc(feature_packs)

    assert portfolio["priced"] is True
    # 500 (USDC) + 10*80 (SOL) + 0.01*60000 (BTC) = 500 + 800 + 600 = 1900
    assert Decimal(str(portfolio["total_usdc"])) == Decimal("1900.00")


def test_untracked_currency_contributes_zero_not_a_guess():
    client = FakeCoinbaseClient({"USDC": "500.00", "DOGE": "1000"})
    engine = _engine(client)
    feature_packs = _feature_packs({})  # no DOGE-USDC feature pack this cycle

    portfolio = engine._compute_portfolio_value_usdc(feature_packs)

    assert Decimal(str(portfolio["total_usdc"])) == Decimal("500.00")
    assert portfolio["holdings"]["DOGE"]["priced"] is False


def test_apply_portfolio_based_entry_sizing_refreshes_all_entry_caps():
    client = FakeCoinbaseClient({"USDC": "2000.00"})
    engine = _engine(client)
    feature_packs = _feature_packs({"BTC-USDC": "60000.00"})
    feature_packs["ETH-USDC"] = {"market": {"mid_price": "3000.00"}}

    engine._apply_portfolio_based_entry_sizing(feature_packs)

    assert Decimal(str(engine.cfg.min_dynamic_entry_quote_usdc)) == Decimal("200.00")
    assert Decimal(str(engine.cfg.max_dynamic_entry_quote_usdc)) == Decimal("400.00")
    assert Decimal(str(engine.cfg.min_live_order_quote_usdc)) == Decimal("200.00")
    assert Decimal(str(engine.cfg.max_live_order_quote_usdc)) == Decimal("400.00")
    assert Decimal(str(engine.cfg.phase_c_max_order_quote)) == Decimal("400.00")
    assert Decimal(str(engine.cfg.autonomous_max_order_quote)) == Decimal("400.00")
    # every ticker's feature pack gets the same priced portfolio context
    for fp in feature_packs.values():
        assert Decimal(fp["risk_context"]["portfolio_value_usdc"]) == Decimal("2000.00")
        assert fp["risk_context"]["portfolio_priced"] is True


def test_pricing_failure_leaves_previous_entry_caps_untouched():
    engine = _engine(FailingCoinbaseClient())
    engine.cfg.min_dynamic_entry_quote_usdc = Decimal("123.45")
    engine.cfg.max_dynamic_entry_quote_usdc = Decimal("246.90")
    feature_packs = _feature_packs({"BTC-USDC": "60000.00"})

    engine._apply_portfolio_based_entry_sizing(feature_packs)

    # A Coinbase API failure must never zero out or otherwise clobber the
    # last known-good entry caps -- that would either block every entry or
    # (worse) silently fall through to some unintended default.
    assert engine.cfg.min_dynamic_entry_quote_usdc == Decimal("123.45")
    assert engine.cfg.max_dynamic_entry_quote_usdc == Decimal("246.90")
    for fp in feature_packs.values():
        assert fp["risk_context"]["portfolio_priced"] is False
