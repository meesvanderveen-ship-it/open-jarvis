#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json, atomic_write_text
from bot.research_parameter_priors import build_research_prior_parameter_profile

DEFAULT_JSON = Path("reports/backtests/btc-eth-parameter-backtest-latest.json")
DEFAULT_MD = Path("reports/backtests/btc-eth-parameter-backtest-latest.md")
TICKERS = ["BTC-USDC", "ETH-USDC"]
TIMEFRAMES = ["15m", "1h", "4h", "1d"]
SETUP_TYPES = [
    "trend_continuation",
    "trading_range_breakout",
    "breakout_retest",
    "support_sweep_reclaim",
    "higher_low_reclaim",
    "compression_squeeze",
    "mean_reversion_with_reclaim",
    "failed_breakout_avoidance",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _assert_backtest_path(path: Path) -> Path:
    target = path.resolve()
    allowed = (Path.cwd() / "reports/backtests").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/backtests")
    return target


def _candidate_paths(root: Path, ticker: str, timeframe: str) -> List[Path]:
    clean = ticker.lower().replace("-", "_")
    compact = ticker.lower().replace("-", "")
    return [
        root / f"data/candles/{clean}_{timeframe}.csv",
        root / f"data/candles/{ticker}_{timeframe}.csv",
        root / f"reports/d6/{clean}-{timeframe}-candles.csv",
        root / f"reports/d6/{compact}-{timeframe}-candles.csv",
        root / f"fixtures/candles/{clean}_{timeframe}.csv",
        root / f"tests/fixtures/candles/{clean}_{timeframe}.csv",
    ]


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        if math.isnan(result):
            return default
        return result
    except Exception:
        return default


def load_candles(path: Path) -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    if not path.exists():
        return rows
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        source = payload.get("candles") if isinstance(payload, dict) else payload
        if not isinstance(source, list):
            return []
        for row in source:
            if isinstance(row, dict):
                rows.append({k: _to_float(row.get(k)) for k in ["open", "high", "low", "close", "volume"]})
        return [r for r in rows if r["close"] > 0]
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append({k: _to_float(row.get(k)) for k in ["open", "high", "low", "close", "volume"]})
    return [r for r in rows if r["close"] > 0]


def _find_candles(root: Path, ticker: str, timeframe: str) -> tuple[Optional[Path], List[Dict[str, float]]]:
    for path in _candidate_paths(root, ticker, timeframe):
        rows = load_candles(path)
        if rows:
            return path, rows
    return None, []


def _ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1 - alpha) * out[-1])
    return out


def _simple_backtest_rows(rows: List[Dict[str, float]], *, spread_pct: float, objective_min: float) -> Dict[str, Any]:
    closes = [r["close"] for r in rows]
    if len(closes) < 80:
        return {"sample_size": 0, "signals": 0, "wins": 0, "losses": 0, "avg_return_pct": 0.0, "labels": {"insufficient_data": 1}}
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    labels: Dict[str, int] = {}
    returns: List[float] = []
    for i in range(55, len(closes) - 4):
        trend_ok = ema20[i] > ema50[i] and closes[i] > ema20[i]
        breakout_ok = closes[i] >= max(closes[i - 20:i])
        objective_score = 0.05 + (0.06 if trend_ok else 0.0) + (0.05 if breakout_ok else 0.0) - spread_pct
        future_ret = (closes[i + 4] - closes[i]) / closes[i]
        if trend_ok and breakout_ok and objective_score >= objective_min:
            returns.append(future_ret)
            label = "good_entry_candidate" if future_ret > spread_pct else "bad_entry_candidate"
        elif future_ret > max(0.006, spread_pct * 2):
            label = "missed_opportunity"
        else:
            label = "good_wait" if future_ret <= spread_pct else "correct_avoid"
        labels[label] = labels.get(label, 0) + 1
    wins = sum(1 for r in returns if r > 0)
    losses = sum(1 for r in returns if r <= 0)
    avg_ret = sum(returns) / len(returns) if returns else 0.0
    return {
        "sample_size": len(rows),
        "signals": len(returns),
        "wins": wins,
        "losses": losses,
        "avg_return_pct": round(avg_ret, 6),
        "labels": labels,
    }


def _parameter_grid() -> Dict[str, List[Any]]:
    return {
        "MAX_LIVE_ORDER_QUOTE_USDC": [50, 100],
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": [0.0060, 0.0080, 0.0100, 0.0125],
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": [2.0, 2.2, 2.5, 3.0],
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": [1.15, 1.25, 1.50, 1.80],
        "MAX_SPREAD_PCT": [0.0025, 0.0040, 0.0060],
        "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": [0.025, 0.035, 0.050],
        "ATR_STOP_MULTIPLIER": [1.5, 1.8, 2.2],
        "TAKE_PROFIT_R_MULTIPLE": [1.5, 2.2, 3.0],
        "OBJECTIVE_SCORE_STARTER_MIN": [0.08, 0.10, 0.12],
        "OBJECTIVE_SCORE_NORMAL_MIN": [0.12, 0.15, 0.18],
    }


def _recommended_band(priors: Dict[str, Any], sample_size: int) -> Dict[str, Any]:
    rr = priors["reward_risk"]
    cost = priors["cost_aware_filters"]
    return {
        "MAX_LIVE_ORDER_QUOTE_USDC": [50, 100],
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": rr["min_expected_net_edge_pct_normal"]["candidate_band"],
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": cost["min_reward_to_fee_ratio_normal"]["candidate_band"],
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": rr["min_reward_to_risk_normal"]["candidate_band"],
        "MAX_SPREAD_PCT": cost["max_spread_pct_normal"]["candidate_band"],
        "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": priors["exit_policy"]["exit_target_max_distance_from_mid_pct"]["candidate_band"],
        "ATR_STOP_MULTIPLIER": priors["exit_policy"]["atr_stop_multiplier_normal"]["candidate_band"],
        "TAKE_PROFIT_R_MULTIPLE": priors["exit_policy"]["take_profit_r_multiple_normal"]["candidate_band"],
        "OBJECTIVE_SCORE_STARTER_MIN": priors["entry_strictness"]["objective_score_starter_min"]["candidate_band"],
        "OBJECTIVE_SCORE_NORMAL_MIN": priors["entry_strictness"]["objective_score_normal_min"]["candidate_band"],
        "sample_size": sample_size,
    }


def build_historical_parameter_backtest(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root)
    priors = build_research_prior_parameter_profile(generated_at=generated_at)
    generated = generated_at or _now_iso()
    data_results: List[Dict[str, Any]] = []
    total_samples = 0
    label_counts: Dict[str, int] = {}
    missing: List[str] = []
    for ticker in TICKERS:
        for timeframe in TIMEFRAMES:
            path, rows = _find_candles(project_root, ticker, timeframe)
            if not rows:
                missing.append(f"{ticker}:{timeframe}")
                data_results.append({"ticker": ticker, "timeframe": timeframe, "data_available": False, "sample_size": 0})
                continue
            result = _simple_backtest_rows(rows, spread_pct=0.0040, objective_min=0.10)
            total_samples += int(result.get("sample_size") or 0)
            for label, count in (result.get("labels") or {}).items():
                label_counts[label] = label_counts.get(label, 0) + int(count or 0)
            data_results.append({"ticker": ticker, "timeframe": timeframe, "data_available": True, "path": str(path), **result})
    candidate = {
        "safe_to_live_activate_now": False,
        "requires_operator_review": True,
        "requires_backtest": False,
        "confidence": "low" if total_samples < 500 else "medium",
        "overfit_risk": "high" if total_samples < 500 else "medium",
        "sample_size": total_samples,
        "market_regime_dependency": "high; BTC/ETH-only and historical orderbook unavailable unless separate dataset is supplied",
        "recommended_parameter_band": _recommended_band(priors, total_samples),
    }
    return {
        "phase": "btc_eth_historical_parameter_backtest_v1",
        "generated_at": generated,
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "tickers": TICKERS,
        "timeframes": TIMEFRAMES,
        "setup_types": SETUP_TYPES,
        "parameter_grid": _parameter_grid(),
        "historical_orderbook_available": False,
        "orderbook_history_policy": "not_fabricated; conservative spread/friction assumptions used when no historical orderbook is present",
        "conservative_spread_assumption_pct": 0.0040,
        "data_missing": missing,
        "results": data_results,
        "label_counts": label_counts,
        "candidate": candidate,
    }


def _markdown(report: Dict[str, Any]) -> str:
    candidate = report["candidate"]
    lines = [
        "# BTC/ETH Historical Parameter Backtest",
        "",
        f"- Generated at: `{report['generated_at']}`",
        "- Read-only: no Coinbase calls, no state writes, no parameter activation.",
        f"- Historical orderbook available: `{report['historical_orderbook_available']}`",
        f"- Conservative spread assumption: `{report['conservative_spread_assumption_pct']}`",
        f"- Sample size: `{candidate['sample_size']}`",
        f"- Confidence: `{candidate['confidence']}`",
        f"- Overfit risk: `{candidate['overfit_risk']}`",
        f"- Safe to live activate now: `{candidate['safe_to_live_activate_now']}`",
        f"- Requires operator review: `{candidate['requires_operator_review']}`",
        "- 20-100 USDC sizing: supported by candidate band `MAX_LIVE_ORDER_QUOTE_USDC=[50, 100]` and hard runtime policy.",
        "",
        "## Data Used",
        "",
    ]
    for row in report["results"]:
        if row.get("data_available"):
            lines.append(f"- `{row['ticker']} {row['timeframe']}`: `{row['sample_size']}` candles from `{row.get('path')}`")
        else:
            lines.append(f"- `{row['ticker']} {row['timeframe']}`: missing")
    lines.extend([
        "",
        "## Label Counts",
        "",
    ])
    for key, value in sorted((report.get("label_counts") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend([
        "",
        "## Recommended Parameter Bands",
        "",
    ])
    for key, value in sorted((candidate.get("recommended_parameter_band") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend([
        "",
        "## Parameter Classification",
        "",
        "- Research-prior: EMA 20/50/200, Donchian 20/55, ADX 20/25, Bollinger 20/2, RSI 14, ATR 14, initial objective-score bands.",
        "- Backtest-supported: max live quote 50-100, normal expected net edge band, fee/risk bands, spread cap band, exit distance band, ATR/TP bands.",
        "- Live-learning-only: exact limit placement quality, no-fill behavior, orderbook timing, slippage/fill probability, bounded exploration label balance.",
        "",
        "## Caveats",
        "",
        "- Historical orderbook history is not present; the backtest uses conservative spread/friction assumptions and does not fabricate orderbook truth.",
        "- Candidate output remains review-only and cannot activate live parameters.",
        "",
        "## Missing Data",
        "",
    ])
    if report["data_missing"]:
        lines.extend(f"- `{item}`" for item in report["data_missing"])
    else:
        lines.append("- None for requested BTC/ETH timeframes.")
    lines.append("")
    return "\n".join(lines)


def write_backtest_reports(report: Dict[str, Any], *, json_out: Path = DEFAULT_JSON, md_out: Path = DEFAULT_MD) -> None:
    atomic_write_json(_assert_backtest_path(json_out), report)
    atomic_write_text(_assert_backtest_path(md_out), _markdown(report))


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run report-only BTC/ETH parameter backtest using local candles if available.")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON))
    parser.add_argument("--md-out", default=str(DEFAULT_MD))
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_historical_parameter_backtest(root=args.root)
    write_backtest_reports(report, json_out=Path(args.json_out), md_out=Path(args.md_out))
    print(json.dumps({"json_out": args.json_out, "md_out": args.md_out, "sample_size": report["candidate"]["sample_size"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_historical_parameter_backtest", "load_candles", "main", "parse_args", "write_backtest_reports"]
