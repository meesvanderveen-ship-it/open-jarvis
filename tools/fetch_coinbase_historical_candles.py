#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

PRODUCTS = ["BTC-USDC", "ETH-USDC"]
TIMEFRAMES = ["15m", "1h", "4h", "1d"]
GRANULARITY_SECONDS = {"15m": 900, "1h": 3600, "1d": 86400}
BROKERAGE_GRANULARITY = {"15m": "FIFTEEN_MINUTE", "1h": "ONE_HOUR", "1d": "ONE_DAY"}
OUTPUT_NAMES = {
    ("BTC-USDC", "15m"): "btc_usdc_15m.csv",
    ("BTC-USDC", "1h"): "btc_usdc_1h.csv",
    ("BTC-USDC", "4h"): "btc_usdc_4h.csv",
    ("BTC-USDC", "1d"): "btc_usdc_1d.csv",
    ("ETH-USDC", "15m"): "eth_usdc_15m.csv",
    ("ETH-USDC", "1h"): "eth_usdc_1h.csv",
    ("ETH-USDC", "4h"): "eth_usdc_4h.csv",
    ("ETH-USDC", "1d"): "eth_usdc_1d.csv",
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_products(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for part in str(raw or "").split(","):
            part = part.strip().upper()
            if part and part not in out:
                out.append(part)
    return out or PRODUCTS


def _parse_timeframes(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for part in str(raw or "").split(","):
            part = part.strip().lower()
            if part and part not in out:
                out.append(part)
    return out or TIMEFRAMES


def _fetch_chunk(product: str, timeframe: str, start: datetime, end: datetime, *, timeout: int = 20) -> List[Dict[str, object]]:
    query = urllib.parse.urlencode({
        "start": str(int(start.timestamp())),
        "end": str(int(end.timestamp())),
        "granularity": BROKERAGE_GRANULARITY[timeframe],
    })
    url = f"https://api.coinbase.com/api/v3/brokerage/market/products/{urllib.parse.quote(product)}/candles?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "coinbase-bot-research-candle-fetch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = []
    for item in payload.get("candles", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        ts = item.get("start")
        rows.append({
            "timestamp": datetime.fromtimestamp(int(ts), tz=timezone.utc),
            "open": float(item.get("open")),
            "high": float(item.get("high")),
            "low": float(item.get("low")),
            "close": float(item.get("close")),
            "volume": float(item.get("volume")),
        })
    return rows


def fetch_product_timeframe(product: str, timeframe: str, *, days: int, delay_seconds: float = 0.12) -> List[Dict[str, object]]:
    if timeframe == "4h":
        return aggregate_4h(fetch_product_timeframe(product, "1h", days=days, delay_seconds=delay_seconds))
    granularity = GRANULARITY_SECONDS[timeframe]
    end = _now_utc()
    start = end - timedelta(days=days)
    max_points = 300
    step = timedelta(seconds=granularity * max_points)
    cursor = start
    rows_by_ts: Dict[datetime, Dict[str, object]] = {}
    while cursor < end:
        chunk_end = min(cursor + step, end)
        for row in _fetch_chunk(product, timeframe, cursor, chunk_end):
            rows_by_ts[row["timestamp"]] = row
        cursor = chunk_end
        if delay_seconds > 0:
            time.sleep(delay_seconds)
    return [rows_by_ts[key] for key in sorted(rows_by_ts)]


def aggregate_4h(hourly: List[Dict[str, object]]) -> List[Dict[str, object]]:
    buckets: Dict[datetime, List[Dict[str, object]]] = {}
    for row in hourly:
        ts = row["timestamp"]
        if not isinstance(ts, datetime):
            continue
        bucket = ts.replace(hour=(ts.hour // 4) * 4, minute=0, second=0, microsecond=0)
        buckets.setdefault(bucket, []).append(row)
    out: List[Dict[str, object]] = []
    for bucket in sorted(buckets):
        rows = sorted(buckets[bucket], key=lambda r: r["timestamp"])
        if len(rows) < 1:
            continue
        out.append({
            "timestamp": bucket,
            "open": float(rows[0]["open"]),
            "high": max(float(r["high"]) for r in rows),
            "low": min(float(r["low"]) for r in rows),
            "close": float(rows[-1]["close"]),
            "volume": sum(float(r["volume"]) for r in rows),
        })
    return out


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for row in rows:
            ts = row["timestamp"]
            writer.writerow({
                "timestamp": _iso(ts if isinstance(ts, datetime) else datetime.fromtimestamp(int(ts), tz=timezone.utc)),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            })
    tmp.replace(path)


def summarize_rows(rows: List[Dict[str, object]]) -> Dict[str, object]:
    if not rows:
        return {"candles": 0, "start": "", "end": ""}
    first = rows[0]["timestamp"]
    last = rows[-1]["timestamp"]
    return {
        "candles": len(rows),
        "start": _iso(first if isinstance(first, datetime) else datetime.fromtimestamp(int(first), tz=timezone.utc)),
        "end": _iso(last if isinstance(last, datetime) else datetime.fromtimestamp(int(last), tz=timezone.utc)),
    }


def fetch_and_write(*, products: List[str], timeframes: List[str], days: int, output_dir: Path, delay_seconds: float = 0.12) -> Dict[str, object]:
    results = []
    for product in products:
        hourly_cache: Optional[List[Dict[str, object]]] = None
        for timeframe in timeframes:
            if timeframe == "4h":
                if hourly_cache is None:
                    hourly_cache = fetch_product_timeframe(product, "1h", days=days, delay_seconds=delay_seconds)
                rows = aggregate_4h(hourly_cache)
            else:
                rows = fetch_product_timeframe(product, timeframe, days=days, delay_seconds=delay_seconds)
                if timeframe == "1h":
                    hourly_cache = rows
            output = output_dir / OUTPUT_NAMES[(product, timeframe)]
            write_csv(output, rows)
            results.append({
                "product": product,
                "timeframe": timeframe,
                "path": str(output),
                **summarize_rows(rows),
                "source": "coinbase_advanced_trade_public_market_candles",
                "read_only_market_data": True,
            })
    return {
        "generated_at": _iso(_now_utc()),
        "read_only": True,
        "coinbase_account_or_order_call_performed": False,
        "coinbase_public_market_data_call_performed": True,
        "live_order_action_performed": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "products": products,
        "timeframes": timeframes,
        "requested_days": days,
        "results": results,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch public Coinbase historical candles for research/backtest CSV input.")
    parser.add_argument("--products", action="append", default=[])
    parser.add_argument("--timeframes", action="append", default=[])
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--output-dir", default="data/candles")
    parser.add_argument("--delay-seconds", type=float, default=0.12)
    parser.add_argument("--json-out", default="reports/backtests/btc-eth-candle-data-load-latest.json")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    products = _parse_products(args.products)
    timeframes = _parse_timeframes(args.timeframes)
    invalid = [tf for tf in timeframes if tf not in TIMEFRAMES]
    if invalid:
        raise SystemExit("unsupported timeframes: " + ",".join(invalid))
    report = fetch_and_write(
        products=products,
        timeframes=timeframes,
        days=int(args.days),
        output_dir=Path(args.output_dir),
        delay_seconds=float(args.delay_seconds),
    )
    json_out = Path(args.json_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["aggregate_4h", "fetch_and_write", "fetch_product_timeframe", "main", "parse_args"]
