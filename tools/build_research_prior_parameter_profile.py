#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.research_parameter_priors import build_research_prior_parameter_profile

DEFAULT_JSON = Path("reports/research/research-prior-parameter-profile-latest.json")
DEFAULT_MD = Path("reports/research/research-prior-parameter-profile-latest.md")


def _assert_research_path(path: Path) -> Path:
    target = path.resolve()
    allowed = (Path.cwd() / "reports/research").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/research")
    return target


def _markdown(profile: dict) -> str:
    sizing = profile["order_sizing"]
    exploration = profile["bounded_exploration"]
    return "\n".join([
        "# Research-Prior Parameter Profile",
        "",
        f"- Generated at: `{profile['generated_at']}`",
        "- Status: research prior only, not a live approved profile.",
        f"- Safe to live activate now: `{profile['safe_to_live_activate_now']}`",
        f"- Requires backtest: `{profile['requires_backtest']}`",
        f"- Requires operator review: `{profile['requires_operator_review']}`",
        "",
        "## Core Priors",
        "",
        f"- EMA trend filter: `{profile['trend_filter']['ema_fast']}/{profile['trend_filter']['ema_mid']}/{profile['trend_filter']['ema_slow']}`",
        f"- Donchian breakout: `{profile['breakout_filter']['donchian_fast']}/{profile['breakout_filter']['donchian_slow']}`",
        f"- ADX thresholds: candidate `{profile['adx_thresholds']['trend_candidate']}`, strong `{profile['adx_thresholds']['strong_trend']}`",
        f"- ATR/RSI/Bollinger: `{profile['volatility_context']['atr_period']}`, `{profile['volatility_context']['rsi_period']}`, `{profile['volatility_context']['bollinger_period']}/2`",
        "",
        "## Order Sizing",
        "",
        f"- Live quote range: `{sizing['min_live_order_quote_usdc']}` to `{sizing['max_live_order_quote_usdc']}` USDC",
        f"- Starter/probe band: `{sizing['starter_probe_band_usdc']}`",
        f"- Normal band: `{sizing['normal_entry_band_usdc']}`",
        f"- Strong band: `{sizing['strong_entry_band_usdc']}`",
        "",
        "## Bounded Exploration",
        "",
        f"- Enabled by default: `{exploration['enabled_by_default']}`",
        f"- Quote range: `{exploration['min_quote_usdc']}` to `{exploration['max_quote_usdc']}` USDC",
        f"- Market orders allowed: `{exploration['allow_market_orders']}`",
        "",
    ])


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write the research-prior parameter profile. Report-only; no activation.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    profile = build_research_prior_parameter_profile()
    atomic_write_json(_assert_research_path(Path(args.json_out)), profile)
    atomic_write_text(_assert_research_path(Path(args.md_out)), _markdown(profile))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "safe_to_live_activate_now": False}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "parse_args"]
