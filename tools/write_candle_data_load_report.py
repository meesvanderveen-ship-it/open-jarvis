#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

DEFAULT_JSON = Path("reports/backtests/btc-eth-candle-data-load-latest.json")
DEFAULT_MD = Path("reports/backtests/btc-eth-candle-data-load-latest.md")


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# BTC/ETH Candle Data Load",
        "",
        f"- Generated at: `{report.get('generated_at', '')}`",
        f"- Requested days: `{report.get('requested_days')}`",
        f"- Public market data call performed: `{report.get('coinbase_public_market_data_call_performed')}`",
        f"- Coinbase account/order call performed: `{report.get('coinbase_account_or_order_call_performed')}`",
        f"- Live order action performed: `{report.get('live_order_action_performed')}`",
        f"- State write performed: `{report.get('state_write_performed')}`",
        f"- Env write performed: `{report.get('env_write_performed')}`",
        "",
        "## Candle Files",
        "",
    ]
    for row in report.get("results") or []:
        lines.append(
            f"- `{row.get('product')} {row.get('timeframe')}`: `{row.get('candles')}` candles, "
            f"`{row.get('start')}` to `{row.get('end')}`, path `{row.get('path')}`, source `{row.get('source')}`"
        )
    lines.extend([
        "",
        "## Backtest Assumptions",
        "",
        "- Historical orderbook history: unavailable in this data load.",
        "- Spread/friction assumption: handled by `tools/run_historical_parameter_backtest.py` using conservative `0.0040` spread assumption.",
        "- 4h candles: aggregated from public 1h Coinbase market candles.",
        "- 20-100 USDC sizing: supported by current hard runtime policy and candidate bands; not activated by this report.",
        "- Safe to live activate now: `False`.",
        "- Requires operator review: `True`.",
        "",
    ])
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write Markdown summary for BTC/ETH candle data load report.")
    parser.add_argument("--json-in", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = _load_json(Path(args.json_in))
    out = Path(args.md_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_markdown(report), encoding="utf-8")
    print(json.dumps({"md_out": str(out), "rows": len(report.get("results") or [])}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "parse_args"]
