from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_baseline_backtest import (
    D6_BASELINES,
    build_phase_d6_baseline_backtest_report,
    write_report as write_baseline_report,
)
from bot.phase_d6_coinbase_candle_ingest import assert_research_path


D6_BASELINE_REPORT_BUNDLE_PHASE = "D6_baseline_report_bundle_v1"
DEFAULT_BUNDLE_BASELINES = ["buy_hold", "simple_ma"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or str(value).strip() == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _decimal_str(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def normalize_candle_paths(paths: Iterable[str | Path]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in paths:
        path = assert_research_path(raw)
        text = str(path)
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    if not out:
        raise ValueError("d6_baseline_bundle_requires_at_least_one_candle_file")
    return out


def normalize_baselines(values: Optional[Iterable[Any]] = None) -> List[str]:
    raw_values = list(values or DEFAULT_BUNDLE_BASELINES)
    out: List[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        baseline = str(raw or "").strip().lower()
        if baseline not in D6_BASELINES:
            raise ValueError(f"unsupported_d6_baseline:{raw}")
        if baseline in seen:
            continue
        seen.add(baseline)
        out.append(baseline)
    if not out:
        raise ValueError("d6_baseline_bundle_requires_at_least_one_baseline")
    return out


def _compact_report(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ticker": report["ticker"],
        "timeframe": report["timeframe"],
        "candles_path": report["candles_path"],
        "candle_count": report["candle_count"],
        "first_candle_start": report["first_candle_start"],
        "last_candle_start": report["last_candle_start"],
        "gap_count": report["gap_count"],
        "baseline_type": report["baseline_type"],
        "initial_quote": report["initial_quote"],
        "final_quote": report["final_quote"],
        "net_return": report["net_return"],
        "net_return_pct": report["net_return_pct"],
        "max_drawdown": report["max_drawdown"],
        "max_drawdown_pct": report["max_drawdown_pct"],
        "trades_count": report["trades_count"],
        "round_trips": report["round_trips"],
        "exposure_pct": report["exposure_pct"],
        "fees_assumption_pct": report["fees_assumption_pct"],
        "warnings": list(report.get("warnings") or []),
    }


def _bundle_summary(reports: List[Dict[str, Any]], candle_paths: List[str], baselines: List[str]) -> Dict[str, Any]:
    net_returns = [_to_decimal(r.get("net_return")) for r in reports]
    drawdowns = [_to_decimal(r.get("max_drawdown")) for r in reports]
    best = max(reports, key=lambda r: _to_decimal(r.get("net_return"))) if reports else {}
    worst = min(reports, key=lambda r: _to_decimal(r.get("net_return"))) if reports else {}
    return {
        "candle_file_count": len(candle_paths),
        "baseline_count": len(baselines),
        "report_count": len(reports),
        "tickers": sorted({str(r.get("ticker")) for r in reports}),
        "timeframes": sorted({str(r.get("timeframe")) for r in reports}),
        "baseline_types": list(baselines),
        "min_net_return": _decimal_str(min(net_returns)) if net_returns else "0",
        "max_net_return": _decimal_str(max(net_returns)) if net_returns else "0",
        "avg_net_return": _decimal_str(sum(net_returns, Decimal("0")) / Decimal(len(net_returns))) if net_returns else "0",
        "max_drawdown_worst": _decimal_str(max(drawdowns)) if drawdowns else "0",
        "best_result": {
            "ticker": best.get("ticker", ""),
            "timeframe": best.get("timeframe", ""),
            "baseline_type": best.get("baseline_type", ""),
            "net_return_pct": best.get("net_return_pct", ""),
        },
        "worst_result": {
            "ticker": worst.get("ticker", ""),
            "timeframe": worst.get("timeframe", ""),
            "baseline_type": worst.get("baseline_type", ""),
            "net_return_pct": worst.get("net_return_pct", ""),
        },
    }


def build_phase_d6_baseline_report_bundle(
    *,
    candle_paths: Iterable[str | Path],
    baselines: Optional[Iterable[Any]] = None,
    initial_quote: Any = "1000",
    fee_pct: Any = "0.0040",
) -> Dict[str, Any]:
    paths = normalize_candle_paths(candle_paths)
    baseline_list = normalize_baselines(baselines)
    reports: List[Dict[str, Any]] = []
    compact_reports: List[Dict[str, Any]] = []
    warnings = [
        "research_report_bundle_only",
        "not_parameter_search",
        "not_optimization",
        "uses_baseline_scaffold_outputs",
    ]

    for path in paths:
        for baseline in baseline_list:
            report = build_phase_d6_baseline_backtest_report(
                candles_path=path,
                baseline=baseline,
                initial_quote=initial_quote,
                fee_pct=fee_pct,
            )
            reports.append(report)
            compact_reports.append(_compact_report(report))

    return {
        "generated_at": _now_iso(),
        "phase": D6_BASELINE_REPORT_BUNDLE_PHASE,
        "status": "d6_baseline_report_bundle_ready",
        "initial_quote": str(initial_quote),
        "fee_pct": str(fee_pct),
        "candle_paths": paths,
        "summary": _bundle_summary(reports, paths, baseline_list),
        "reports": compact_reports,
        "warnings": warnings,
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "parameter_search_performed": False,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
    }


def bundle_to_markdown(bundle: Dict[str, Any]) -> str:
    summary = dict(bundle.get("summary") or {})
    lines = [
        "# D.6 Baseline Report Bundle",
        "",
        f"- generated_at: `{bundle.get('generated_at', '')}`",
        f"- report_count: `{summary.get('report_count', 0)}`",
        f"- candle_file_count: `{summary.get('candle_file_count', 0)}`",
        f"- baselines: `{', '.join(summary.get('baseline_types') or [])}`",
        f"- max_net_return: `{summary.get('max_net_return', '0')}`",
        f"- min_net_return: `{summary.get('min_net_return', '0')}`",
        f"- worst_drawdown: `{summary.get('max_drawdown_worst', '0')}`",
        "",
        "| ticker | timeframe | baseline | candles | net_return_pct | max_drawdown_pct | trades |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in bundle.get("reports") or []:
        lines.append(
            "| {ticker} | {timeframe} | {baseline_type} | {candle_count} | {net_return_pct} | {max_drawdown_pct} | {trades_count} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "Safety:",
            "",
            f"- research_only: `{bundle.get('research_only')}`",
            f"- no_coinbase_call: `{bundle.get('no_coinbase_call')}`",
            f"- no_live_action: `{bundle.get('no_live_action')}`",
            f"- state_write_performed: `{bundle.get('state_write_performed')}`",
            f"- no_optimization: `{bundle.get('no_optimization')}`",
            f"- parameter_change_allowed: `{bundle.get('parameter_change_allowed')}`",
        ]
    )
    return "\n".join(lines) + "\n"


def write_json_bundle(bundle: Dict[str, Any], output_path: str | Path) -> Path:
    return write_baseline_report(bundle, output_path)


def write_markdown_bundle(bundle: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bundle_to_markdown(bundle), encoding="utf-8")
    return path


__all__ = [
    "D6_BASELINE_REPORT_BUNDLE_PHASE",
    "DEFAULT_BUNDLE_BASELINES",
    "build_phase_d6_baseline_report_bundle",
    "bundle_to_markdown",
    "write_json_bundle",
    "write_markdown_bundle",
    "normalize_baselines",
    "normalize_candle_paths",
]
