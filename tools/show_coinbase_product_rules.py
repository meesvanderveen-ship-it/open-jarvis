#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.coinbase_client import CoinbaseClient
from bot.config import BotConfig
from bot.phase_c43_one_entry_smoke_test import extract_product_rules


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Coinbase product rules diagnostic")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_report(ticker: str) -> Dict[str, Any]:
    client = CoinbaseClient()
    report: Dict[str, Any] = {
        "ticker": str(ticker or "").strip().upper().replace("/", "-"),
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": False,
        "base_increment": "0",
        "quote_increment": "0",
        "price_increment": "0",
        "min_order_quote": "0",
        "min_order_base": "0",
        "raw_product_keys": [],
        "warnings": [],
    }
    try:
        product = client.get_product(report["ticker"])
        rules = extract_product_rules(product)
        report["coinbase_call_succeeded"] = True
        report["base_increment"] = str(rules.get("base_increment") or "0")
        report["quote_increment"] = str(rules.get("quote_increment") or "0")
        report["price_increment"] = str(
            product.get("price_increment")
            or product.get("price_increment_size")
            or rules.get("quote_increment")
            or "0"
        )
        report["min_order_quote"] = str(
            product.get("quote_min_size")
            or product.get("quote_min_order_size")
            or product.get("min_market_funds")
            or product.get("min_order_quote")
            or "0"
        )
        report["min_order_base"] = str(
            product.get("base_min_size")
            or product.get("base_min_order_size")
            or product.get("min_order_base")
            or "0"
        )
        report["raw_product_keys"] = sorted(str(key) for key in product.keys())
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["warnings"].append("coinbase_product_rules_fetch_failed")
    return _json_safe(report)


def main() -> int:
    args = parse_args()
    cfg = BotConfig()
    cfg.validate()
    report = build_report(args.ticker)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if report.get("coinbase_call_succeeded") else 2


if __name__ == "__main__":
    raise SystemExit(main())
