from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from bot.phase_d6_data_coverage import TIMEFRAME_SPECS, normalize_timeframe


@dataclass(frozen=True)
class HistoricalCandle:
    source: str
    venue: str
    endpoint: str
    symbol: str
    mapped_coinbase_product: str
    quote_asset: str
    timeframe: str
    open_time: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    fetched_at: str
    request_id: str
    run_id: str
    transformation_applied: str
    role: str

    def to_dict(self) -> Dict[str, Any]:
        row = asdict(self)
        row["start"] = self.open_time
        row["product_id"] = self.mapped_coinbase_product
        return row


def _fetched_at_iso(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _quote_from_product(product: str) -> str:
    return str(product).split("-")[-1].upper() if "-" in str(product) else str(product)[-4:].upper()


def coinbase_source_contract(*, product: str, timeframe: str, run_id: str = "") -> Dict[str, Any]:
    timeframe_n = normalize_timeframe(timeframe)
    return {
        "source": "coinbase",
        "venue": "coinbase_advanced_trade_public",
        "role": "primary_execution_market",
        "endpoint": "public_candles",
        "product": product.upper(),
        "symbol": product.upper(),
        "mapped_coinbase_product": product.upper(),
        "quote_asset": _quote_from_product(product),
        "timeframe": timeframe_n,
        "coinbase_granularity": TIMEFRAME_SPECS[timeframe_n].coinbase_granularity,
        "requires_api_key": False,
        "account_or_order_endpoint_allowed": False,
        "trading_endpoint_allowed": False,
        "run_id": run_id,
    }


def binance_source_contract(*, symbol: str, mapped_coinbase_product: str, timeframe: str, run_id: str = "") -> Dict[str, Any]:
    timeframe_n = normalize_timeframe(timeframe)
    return {
        "source": "binance",
        "venue": "binance_spot_public",
        "role": "secondary_reference_only",
        "endpoint": "public_klines",
        "symbol": symbol.upper(),
        "mapped_coinbase_product": mapped_coinbase_product.upper(),
        "quote_asset": _quote_from_product(mapped_coinbase_product),
        "timeframe": timeframe_n,
        "requires_api_key": False,
        "account_or_order_endpoint_allowed": False,
        "trading_endpoint_allowed": False,
        "coinbase_cache_mutation_allowed": False,
        "normal_backtest_release_allowed": False,
        "run_id": run_id,
    }


def normalize_coinbase_candles(
    raw_rows: Iterable[Dict[str, Any]],
    *,
    product: str,
    timeframe: str,
    run_id: str,
    request_id: str,
    fetched_at: datetime | None = None,
) -> List[Dict[str, Any]]:
    contract = coinbase_source_contract(product=product, timeframe=timeframe, run_id=run_id)
    rows: List[Dict[str, Any]] = []
    for raw in raw_rows:
        start = int(raw.get("start") or raw.get("open_time"))
        rows.append(
            HistoricalCandle(
                source="coinbase",
                venue=contract["venue"],
                endpoint=contract["endpoint"],
                symbol=contract["symbol"],
                mapped_coinbase_product=contract["mapped_coinbase_product"],
                quote_asset=contract["quote_asset"],
                timeframe=contract["timeframe"],
                open_time=start,
                open=str(raw.get("open")),
                high=str(raw.get("high")),
                low=str(raw.get("low")),
                close=str(raw.get("close")),
                volume=str(raw.get("volume")),
                fetched_at=_fetched_at_iso(fetched_at),
                request_id=request_id,
                run_id=run_id,
                transformation_applied="coinbase_public_candle_normalized",
                role=contract["role"],
            ).to_dict()
        )
    return sorted(rows, key=lambda row: int(row["start"]))


def normalize_binance_klines(
    raw_rows: Iterable[Dict[str, Any]],
    *,
    symbol: str,
    mapped_coinbase_product: str,
    timeframe: str,
    run_id: str,
    request_id: str,
    fetched_at: datetime | None = None,
) -> List[Dict[str, Any]]:
    contract = binance_source_contract(symbol=symbol, mapped_coinbase_product=mapped_coinbase_product, timeframe=timeframe, run_id=run_id)
    rows: List[Dict[str, Any]] = []
    for raw in raw_rows:
        start = int(raw.get("start") or raw.get("open_time"))
        rows.append(
            HistoricalCandle(
                source="binance",
                venue=contract["venue"],
                endpoint=contract["endpoint"],
                symbol=contract["symbol"],
                mapped_coinbase_product=contract["mapped_coinbase_product"],
                quote_asset=contract["quote_asset"],
                timeframe=contract["timeframe"],
                open_time=start,
                open=str(raw.get("open")),
                high=str(raw.get("high")),
                low=str(raw.get("low")),
                close=str(raw.get("close")),
                volume=str(raw.get("volume")),
                fetched_at=_fetched_at_iso(fetched_at),
                request_id=request_id,
                run_id=run_id,
                transformation_applied="binance_public_kline_reference_normalized",
                role=contract["role"],
            ).to_dict()
        )
    return sorted(rows, key=lambda row: int(row["start"]))


__all__ = [
    "HistoricalCandle",
    "binance_source_contract",
    "coinbase_source_contract",
    "normalize_binance_klines",
    "normalize_coinbase_candles",
]
